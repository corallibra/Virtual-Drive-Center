import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(os.environ.get("HOST_ROOT", "/volume1/docker/virtual-drive"))
IMAGES = Path(os.environ.get("IMAGES_DIR", ROOT / "images"))
MOUNTS = Path(os.environ.get("MOUNTS_DIR", ROOT / "mounts"))
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
EXPORT = Path(os.environ.get("EXPORT_DIR", ROOT / "export"))
NAS_ROOT = Path(os.environ.get("NAS_ROOT", "/volume1")).resolve()
# 宿主机 PID 1 的根目录：容器使用 pid: host 时，/proc/1/root 指向 DSM 宿主机根文件系统。
HOST_FS_VIEW = Path(os.environ.get("HOST_FS_VIEW", "/proc/1/root")).resolve()
DB = DATA / "virtual-drive.db"
PORT = int(os.environ.get("PORT", "8099"))
AUTO_RESTORE = os.environ.get("AUTO_RESTORE", "true").lower() == "true"
NAS_IMPORT_ROOT = os.environ.get("NAS_IMPORT_ROOT", "/volume1")
VD_USER = os.environ.get("VD_USER", "admin")
VD_PASSWORD = os.environ.get("VD_PASSWORD", "")
AUTH_FILE = DATA / "admin-password.txt"

ALLOWED_EXT = {".iso", ".img", ".ima", ".raw", ".bin"}
SUPPORTED_FS = {"ext2", "ext3", "ext4", "xfs", "ntfs", "ntfs3", "exfat", "vfat", "msdos", "f2fs", "iso9660", "udf"}
READONLY_FS = {"iso9660", "udf"}
FS_LABELS = {
    "ext2": "EXT2", "ext3": "EXT3", "ext4": "EXT4", "xfs": "XFS",
    "ntfs": "NTFS", "ntfs3": "NTFS", "exfat": "exFAT", "vfat": "FAT32",
    "msdos": "FAT", "f2fs": "F2FS", "iso9660": "ISO9660", "udf": "UDF",
}

for p in (ROOT, IMAGES / "iso", IMAGES / "img", MOUNTS, DATA, EXPORT):
    p.mkdir(parents=True, exist_ok=True)

APP_VERSION = os.environ.get("APP_VERSION", "2.0.13")
app = FastAPI(title=f"Synology Virtual Drive {APP_VERSION}")
app.mount("/static", StaticFiles(directory="/opt/virtual-drive/static"), name="static")
templates = Jinja2Templates(directory="/opt/virtual-drive/templates")
lock = threading.RLock()
checksum_jobs = {}
inspect_jobs = {}
mount_jobs = {}
library_scan = {"status":"idle","progress":100,"stage":"ready","detail":"","updated_at":now() if "now" in globals() else ""}
job_lock = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def db_conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def get_password():
    global VD_PASSWORD
    if VD_PASSWORD:
        return VD_PASSWORD
    if AUTH_FILE.exists():
        return AUTH_FILE.read_text().strip()
    pwd = secrets.token_urlsafe(18)
    AUTH_FILE.write_text(pwd)
    os.chmod(AUTH_FILE, 0o600)
    print(f"[VirtualDrive] Generated admin password for '{VD_USER}': {pwd}", flush=True)
    return pwd


def unauthorized():
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Virtual Drive"'})


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path == "/health" or request.url.path.startswith("/static/"):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return unauthorized()
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        user, pwd = raw.split(":", 1)
    except Exception:
        return unauthorized()
    if not (secrets.compare_digest(user, VD_USER) and secrets.compare_digest(pwd, get_password())):
        return unauthorized()
    return await call_next(request)


def init_db():
    with db_conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              path TEXT NOT NULL UNIQUE,
              kind TEXT NOT NULL,
              size INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              mounted INTEGER NOT NULL DEFAULT 0,
              mount_id TEXT,
              fs_type TEXT,
              mount_mode TEXT,
              sha256 TEXT,
              checksum_at TEXT
            );
            CREATE TABLE IF NOT EXISTS mounts (
              id TEXT PRIMARY KEY,
              image_id TEXT NOT NULL,
              mount_path TEXT NOT NULL UNIQUE,
              loop_device TEXT,
              partition TEXT,
              fs_type TEXT,
              mode TEXT NOT NULL,
              mounted_at TEXT NOT NULL,
              unmounted_at TEXT,
              active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event TEXT NOT NULL,
              image_id TEXT,
              image_name TEXT,
              detail TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        # Backfill columns for old 1.x databases.
        for sql in [
            "ALTER TABLE images ADD COLUMN sha256 TEXT",
            "ALTER TABLE images ADD COLUMN checksum_at TEXT",
            "ALTER TABLE mounts ADD COLUMN unmounted_at TEXT",
            "ALTER TABLE images ADD COLUMN availability INTEGER NOT NULL DEFAULT 1",
        ]:
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass


def host_exec(args, check=True, timeout=120, text=True):
    try:
        return subprocess.run(["nsenter", "-t", "1", "-m", "--", *args], capture_output=True, text=text, timeout=timeout, check=check)
    except subprocess.CalledProcessError as e:
        detail=(e.stderr or e.stdout or "").strip()
        cmd=" ".join(str(x) for x in args)
        raise RuntimeError(f"宿主机命令失败: {cmd}; {detail or ('exit status '+str(e.returncode))}") from e


def rowdict(row):
    return dict(row) if row else None


def nas_host_view_path(host_path: Path) -> Path:
    """Map a DSM host path (/volume1/...) to the host root visible via /proc/1/root."""
    host_path = Path(host_path)
    try:
        rel = host_path.resolve().relative_to(NAS_ROOT)
    except ValueError:
        raise HTTPException(400, "路径必须位于 NAS 的 /volume1 内")
    return HOST_FS_VIEW / NAS_ROOT.relative_to(Path("/")) / rel


def validate_nas_path(path: str) -> Path:
    """Validate a NAS host path without relying on a /volume1 bind mount inside the container."""
    raw = Path(path or str(NAS_ROOT))
    if not raw.is_absolute():
        raw = NAS_ROOT / raw
    resolved = raw.resolve()
    try:
        resolved.relative_to(NAS_ROOT)
    except ValueError:
        raise HTTPException(400, "仅允许浏览 /volume1 内的 NAS 路径")
    return resolved


def default_nas_import_root() -> Path:
    try:
        p = validate_nas_path(NAS_IMPORT_ROOT)
        check = host_exec(["test", "-d", str(p)], check=False, timeout=20)
        return p if check.returncode == 0 else NAS_ROOT
    except Exception:
        return NAS_ROOT

def nas_visible_path(path: str) -> tuple[Path, Path]:
    """Return (NAS host path, container-side host-root view path)."""
    host_path = validate_nas_path(path)
    return host_path, nas_host_view_path(host_path)

def host_stat(path: Path):
    r = host_exec(["stat", "-c", "%F\t%s\t%Y", str(path)], check=False, timeout=30)
    if r.returncode != 0:
        return None
    try:
        kind, size, mtime = r.stdout.splitlines()[0].split("\t", 2)
        return {"kind": kind, "size": int(size), "mtime": float(mtime), "is_file": kind.startswith("regular file"), "is_dir": kind.startswith("directory")}
    except Exception:
        return None

def host_exists(path: Path) -> bool:
    return host_exec(["test", "-e", str(path)], check=False, timeout=20).returncode == 0

def image_source_exists(path: Path) -> bool:
    try:
        path.resolve().relative_to(IMAGES.resolve())
        return path.exists()
    except ValueError:
        return host_exists(path)

def host_block_device_exists(path: str) -> bool:
    return host_exec(["test", "-b", str(path)], check=False, timeout=20).returncode == 0

def image_source_stat(path: Path):
    try:
        path.resolve().relative_to(IMAGES.resolve())
        if not path.exists():
            return None
        st = path.stat()
        return {"size": st.st_size, "mtime": st.st_mtime}
    except ValueError:
        st = host_stat(path)
        if not st or not st["is_file"]:
            return None
        return st

def is_managed_image_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(IMAGES.resolve())
        return True
    except ValueError:
        return False


def safe_name(name: str):
    s = Path(name).name.strip().replace(" ", "-")
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:180] or "image"


def slug_for(name: str):
    s = Path(name).stem.lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s).strip("-") or "image"
    return s[:48]


def classify(name: str):
    return "iso" if Path(name).suffix.lower() == ".iso" else "img"


def get_image(image_id: str):
    with db_conn() as con:
        row = con.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, "映像不存在")
    return row


def get_mount(mount_id: str):
    with db_conn() as con:
        row = con.execute("SELECT * FROM mounts WHERE id=?", (mount_id,)).fetchone()
    if not row:
        raise HTTPException(404, "挂载不存在")
    return row


def log_history(event: str, image=None, detail=""):
    with db_conn() as con:
        con.execute(
            "INSERT INTO history(event,image_id,image_name,detail,created_at) VALUES(?,?,?,?,?)",
            (event, image["id"] if image else None, image["name"] if image else None, detail, now()),
        )


def blkid(device: str, probe: bool = False):
    try:
        args = ["blkid"]
        if probe:
            args += ["-p"]
        args += ["-o", "export", device]
        r = host_exec(args, check=False)
        out = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k] = v
        return out
    except Exception:
        return {}

def probe_whole_image_filesystem(image_path: Path):
    """Probe an image file itself, without attaching a partitioned loop.

    This catches raw images that contain a filesystem directly (no MBR/GPT),
    which lsblk on a loop device may report without an FSTYPE.
    """
    bi = blkid(str(image_path), probe=True)
    fs = (bi.get("TYPE") or "").lower()
    if not fs:
        return None
    return {
        "fstype": fs,
        "fs_label": FS_LABELS.get(fs, fs.upper()),
        "label": bi.get("LABEL"),
        "uuid": bi.get("UUID"),
    }


def lsblk_json(device: str):
    """Run host lsblk when available. Synology/container combinations may expose blkid
    and partition sysfs but not make lsblk executable after entering the host mount
    namespace, so callers must have a sysfs fallback."""
    r = host_exec(["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,FSTYPE,LABEL,SIZE,RO,PARTTYPE,PARTUUID,MOUNTPOINT,START,SECTORS", device], check=False)
    try:
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except Exception:
        return {}


def sysfs_partitions(loop_device: str):
    """Discover loop partition nodes directly from /sys/class/block.

    This is the most reliable fallback on Synology because `lsblk` may not be
    executable after nsenter, while /sys/class/block and /dev/loopNpX remain
    visible. Filesystem type/label/UUID are then obtained via host blkid."""
    name = Path(loop_device).name
    base = Path('/sys/class/block')
    if not name.startswith('loop'):
        return []
    candidates = []
    for entry in base.glob(f'{name}p*'):
        m = re.fullmatch(re.escape(name) + r'p(\d+)', entry.name)
        if m:
            candidates.append((int(m.group(1)), entry))
    out = []
    for part_no, entry in sorted(candidates):
        try:
            start = int((entry / 'start').read_text().strip())
            sectors = int((entry / 'size').read_text().strip())
        except Exception:
            continue
        dev = f'/dev/{entry.name}'
        bi = blkid(dev, probe=True)
        fs = (bi.get('TYPE') or '').lower()
        size = sectors * 512
        out.append({
            'name': entry.name,
            'path': dev,
            'type': 'part',
            'fstype': fs or None,
            'fs_label': FS_LABELS.get(fs, fs.upper() if fs else 'UNKNOWN'),
            'supported': fs in SUPPORTED_FS,
            'label': bi.get('LABEL'),
            'size': size,
            'start_sectors': start,
            'sectors': sectors,
            'offset_bytes': start * 512,
            'read_only': False,
            'parttype': None,
            'partuuid': bi.get('PARTUUID'),
            'mountpoint': None,
            'partition_number': part_no,
        })
    return out


def normalize_partitions(data):
    roots = data.get("blockdevices") or []
    children = roots[0].get("children") if roots else []
    out = []
    for c in children or []:
        fs = (c.get("fstype") or "").lower()
        start = int(c.get("start") or 0)
        sectors = int(c.get("sectors") or 0)
        size = int(c.get("size") or 0)
        out.append({
            "name": c.get("name"),
            "path": c.get("path"),
            "type": c.get("type"),
            "fstype": fs or None,
            "fs_label": FS_LABELS.get(fs, fs.upper() if fs else "UNKNOWN"),
            "supported": fs in SUPPORTED_FS,
            "label": c.get("label"),
            "size": size,
            "start_sectors": start,
            "sectors": sectors,
            "offset_bytes": start * 512 if start else 0,
            "read_only": bool(int(c.get("ro") or 0)),
            "parttype": c.get("parttype"),
            "partuuid": c.get("partuuid"),
            "mountpoint": c.get("mountpoint"),
        })
    return out

def sfdisk_partitions(image_path: Path):
    """Fallback partition detection for DSM kernels where loop partition child nodes are not exposed."""
    r = host_exec(["sfdisk", "-J", str(image_path)], check=False, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        table = json.loads(r.stdout).get("partitiontable") or {}
    except Exception:
        return []
    sector_size = int(table.get("sectorsize") or 512)
    out = []
    for i, part in enumerate(table.get("partitions") or [], 1):
        start = int(part.get("start") or 0)
        sectors = int(part.get("size") or 0)
        size = sectors * sector_size
        typ = str(part.get("type") or "")
        # sfdisk does not identify the filesystem; probe later using an offset loop.
        out.append({
            "name": f"partition-{i}",
            "path": None,
            "type": "part",
            "fstype": None,
            "fs_label": "UNKNOWN",
            "supported": True,
            "label": part.get("name"),
            "size": size,
            "start_sectors": start,
            "sectors": sectors,
            "offset_bytes": start * sector_size,
            "read_only": False,
            "parttype": typ,
            "partuuid": part.get("uuid"),
            "mountpoint": None,
        })
    return out

def enrich_partition_probe(image_path: Path, parts):
    """Probe partitions with temporary offset loops when no kernel partition nodes expose filesystem types."""
    enriched=[]
    for p in parts:
        if p.get("path") and p.get("fstype"):
            enriched.append(p); continue
        offset=int(p.get("offset_bytes") or 0)
        limit=int(p.get("size") or 0)
        if not offset:
            enriched.append(p); continue
        loop=None
        try:
            args=["losetup","--find","--show","--read-only",f"--offset={offset}"]
            if limit:
                args.append(f"--sizelimit={limit}")
            args.append(str(image_path))
            r=host_exec(args, timeout=120)
            loop=r.stdout.strip().splitlines()[-1]
            bi=blkid(loop)
            fs=(bi.get("TYPE") or "").lower()
            p=dict(p)
            p["probe_path"]=loop
            p["fstype"]=fs or None
            p["fs_label"]=FS_LABELS.get(fs, fs.upper() if fs else "UNKNOWN")
            p["supported"]=fs in SUPPORTED_FS
            p["label"]=bi.get("LABEL") or p.get("label")
        except Exception:
            pass
        finally:
            if loop:
                host_exec(["losetup","-d",loop],check=False,timeout=60)
        enriched.append(p)
    return enriched

def partition_records(image_path: Path, loop_device=None):
    parts=[]
    if loop_device:
        # Prefer kernel-exposed partition devices. On Synology, sysfs is often
        # available even when lsblk cannot be executed after nsenter.
        parts = sysfs_partitions(loop_device)
        if not parts:
            parts=normalize_partitions(lsblk_json(loop_device))
    if not parts:
        parts=sfdisk_partitions(image_path)
    if parts:
        parts=enrich_partition_probe(image_path, parts)
    return parts


def inspect_image(row):
    host_p = Path(row["path"])
    st = image_source_stat(host_p)
    result = {
        "id": row["id"], "name": row["name"], "kind": row["kind"],
        "size": int(st["size"] if st else 0),
        "exists": bool(st), "filesystem": None, "filesystem_label": "UNKNOWN",
        "supported": False, "partitions": [], "whole_image": False, "image_read_only": row["kind"] == "iso",
        "partition_table": None,
    }
    if not st:
        result["error"] = "映像文件不存在或 NAS 当前不可访问"
        return result
    if row["kind"] == "iso":
        bi = blkid(str(host_p))
        fs = (bi.get("TYPE") or "").lower()
        result.update({"filesystem": fs or None, "filesystem_label": FS_LABELS.get(fs, fs.upper() if fs else "ISO/UDF"), "supported": (not fs) or fs in SUPPORTED_FS})
        return result
    temp_loop = None
    try:
        # First probe the image file itself. Some raw images are a single filesystem
        # without an MBR/GPT partition table. In that case there is no partition to
        # choose, and the correct target is the whole image.
        whole = probe_whole_image_filesystem(host_p)
        if whole:
            fs = whole["fstype"]
            result.update({
                "filesystem": fs,
                "filesystem_label": whole["fs_label"],
                "supported": fs in SUPPORTED_FS,
                "whole_image": True,
                "partitions": [],
            })
            return result

        r = host_exec(["losetup", "--find", "--show", "--partscan", "--read-only", str(host_p)], timeout=120)
        temp_loop = r.stdout.strip().splitlines()[-1]
        root_bi = blkid(temp_loop, probe=True)
        result["partition_table"] = root_bi.get("PTTYPE") or None
        data = lsblk_json(temp_loop)
        root = (data.get("blockdevices") or [{}])[0]
        rootfs = (root.get("fstype") or "").lower()
        result["filesystem"] = rootfs or None
        result["filesystem_label"] = FS_LABELS.get(rootfs, rootfs.upper() if rootfs else "未知")
        result["supported"] = bool(rootfs and rootfs in SUPPORTED_FS)
        parts = partition_records(host_p, temp_loop)
        result["partitions"] = parts
        result["whole_image"] = bool(rootfs and not parts)
        if not result["partitions"] and rootfs:
            result["whole_image"] = True
            result["partitions"] = []
    except Exception as e:
        result["error"] = str(e)
    finally:
        if temp_loop:
            host_exec(["losetup", "-d", temp_loop], check=False, timeout=60)
    return result


def refresh_images(background=False):
    """Refresh the managed library without probing/mounting large images. External NAS images are validated in the host namespace."""
    global library_scan
    def set_scan(stage, progress, detail=""):
        library_scan.update({"status":"running","stage":stage,"progress":progress,"detail":detail,"updated_at":now()})
    set_scan("scan", 10, "扫描本地映像库")
    inserted = 0
    for sub in (IMAGES / "iso", IMAGES / "img"):
        for p in sorted(sub.iterdir(), key=lambda x: x.name.lower()) if sub.exists() else []:
            if p.is_file() and p.suffix.lower() in ALLOWED_EXT:
                try:
                    with db_conn() as con:
                        exists = con.execute("SELECT id FROM images WHERE path=?", (str(p.resolve()),)).fetchone()
                        if not exists:
                            con.execute("INSERT INTO images(id,name,path,kind,size,created_at) VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, p.name, str(p.resolve()), classify(p.name), p.stat().st_size, now()))
                            inserted += 1
                except Exception:
                    pass
    set_scan("sync", 55, "同步 NAS 映像状态")
    with db_conn() as con:
        rows = con.execute("SELECT id,path,size,mounted FROM images").fetchall()
    total = max(1, len(rows))
    for idx, row in enumerate(rows, 1):
        p = Path(row["path"])
        st = image_source_stat(p)
        if not st:
            # Do not delete external NAS image registrations; mark as missing through availability fields if present.
            try:
                with db_conn() as con:
                    con.execute("UPDATE images SET availability=0 WHERE id=?", (row["id"],))
            except sqlite3.OperationalError:
                pass
        else:
            try:
                with db_conn() as con:
                    con.execute("UPDATE images SET availability=1,size=? WHERE id=?", (int(st["size"]), row["id"]))
            except sqlite3.OperationalError:
                pass
        library_scan["progress"] = 55 + int(idx / total * 40)
    library_scan.update({"status":"done","stage":"ready","progress":100,"detail":f"映像库就绪 · 新增 {inserted} 个","updated_at":now()})
    return inserted


def is_mounted_host(path: Path):
    r = host_exec(["findmnt", "-J", "-T", str(path)], check=False)
    try:
        return bool((json.loads(r.stdout) or {}).get("filesystems"))
    except Exception:
        return False


def unique_mount_id(name: str):
    return f"{slug_for(name)}-{uuid.uuid4().hex[:6]}"


def mount_image(image_id: str, mode: str = "ro", partition: str | None = None, progress=None):
    image = get_image(image_id)
    source = Path(image["path"])
    if progress:
        progress(5, "验证映像路径", "正在确认 NAS 上的映像文件…")
    if not image_source_exists(source):
        raise HTTPException(400, "映像文件不存在或 NAS 当前不可访问")
    if mode not in ("ro", "rw"):
        raise HTTPException(400, "挂载模式无效")
    if image["kind"] == "iso" and mode == "rw":
        raise HTTPException(400, "ISO/UDF 作为光盘介质只读挂载")

    with lock:
        with db_conn() as con:
            active = con.execute("SELECT * FROM mounts WHERE image_id=? AND active=1", (image_id,)).fetchone()
        if active:
            return rowdict(active)

        mount_id = unique_mount_id(image["name"])
        mount_path = MOUNTS / mount_id
        mount_path.mkdir(parents=True, exist_ok=True)
        loop = None
        chosen_partition = partition
        fs = None
        try:
            if image["kind"] == "iso":
                if progress:
                    progress(30, "挂载 ISO", "正在以只读方式挂载光盘映像…")
                host_exec(["mount", "-o", "loop,ro", str(source), str(mount_path)], timeout=120)
                bi = blkid(str(mount_path), probe=True)
                fs = (bi.get("TYPE") or "iso9660").lower()
            else:
                # First try the image as a whole filesystem. This is important for
                # raw filesystem images that contain no MBR/GPT partition table.
                whole = probe_whole_image_filesystem(source)
                if whole and not chosen_partition:
                    fs = whole["fstype"]
                    if fs in READONLY_FS and mode == "rw":
                        raise RuntimeError("该文件系统属于只读介质")
                    if fs not in SUPPORTED_FS:
                        raise RuntimeError(f"暂不支持的文件系统: {fs}")
                    if progress:
                        progress(55, "识别整盘文件系统", f"检测到 {whole['fs_label']}，未发现分区表；正在直接挂载整个 IMG…")
                    try:
                        if fs in {"ntfs", "ntfs3"}:
                            try:
                                host_exec(["mount", "-t", "ntfs3", "-o", f"{mode},loop", str(source), str(mount_path)], timeout=120)
                            except Exception:
                                helper = "rw,loop" if mode == "rw" else "ro,loop"
                                host_exec(["mount", "-t", "ntfs-3g", "-o", helper, str(source), str(mount_path)], timeout=120)
                        else:
                            host_exec(["mount", "-t", fs, "-o", f"{mode},loop", str(source), str(mount_path)], timeout=120)
                    except Exception as e:
                        detail = str(e)
                        raise RuntimeError(f"整盘 IMG 挂载失败（{whole['fs_label']}）：{detail}")
                    chosen_partition = None
                else:
                    if progress:
                        progress(25, "连接 IMG", "正在连接 loop device；大容量镜像可能需要一些时间…")
                    r = host_exec(["losetup", "--find", "--show", "--partscan", str(source)], timeout=120)
                    loop = r.stdout.strip().splitlines()[-1]
                    if progress:
                        progress(55, "扫描分区", "正在读取 IMG 分区表与文件系统信息…")
                    parts = partition_records(source, loop)
                    selected = None
                    if chosen_partition:
                        selected = next((p for p in parts if p.get("path") == chosen_partition or p.get("name") == chosen_partition or p.get("probe_path") == chosen_partition), None)
                        if selected is None:
                            selected = next((p for p in parts if p.get("name") == str(chosen_partition)), None)
                        if selected is None:
                            raise RuntimeError("选择的分区不存在；请重新检查 IMG 分区")
                    elif len(parts) == 1:
                        selected = parts[0]
                        chosen_partition = selected.get("path") or selected.get("name")
                    elif len(parts) > 1:
                        usable = [x for x in parts if x.get("supported")]
                        if len(usable) == 1:
                            selected = usable[0]
                            chosen_partition = selected.get("path") or selected.get("name")
                        else:
                            raise RuntimeError("该 IMG 含多个分区，请在网页中选择具体分区后重新挂载")

                    if selected and selected.get("offset_bytes") and (not selected.get("path") or not host_block_device_exists(str(selected.get("path")))):
                        args = ["losetup", "--find", "--show", f"--offset={int(selected['offset_bytes'])}"]
                        if selected.get("size"):
                            args.append(f"--sizelimit={int(selected['size'])}")
                        if mode == "ro":
                            args.append("--read-only")
                        args.append(str(source))
                        rr = host_exec(args, timeout=120)
                        partition_loop = rr.stdout.strip().splitlines()[-1]
                        host_exec(["losetup", "-d", loop], check=False, timeout=60)
                        loop = partition_loop
                        device = loop
                        chosen_partition = selected.get("name") or device
                    else:
                        device = (selected.get("path") if selected else None) or loop

                    fs_probe = blkid(device, probe=True)
                    fs = (fs_probe.get("TYPE") or (selected or {}).get("fstype") or "").lower()
                    if not fs and selected and selected.get("probe_path"):
                        fs = (blkid(selected["probe_path"], probe=True).get("TYPE") or "").lower()
                    if not fs:
                        raise RuntimeError("无法识别该 IMG 的文件系统；请执行“检查”查看结构信息")
                    if fs in READONLY_FS and mode == "rw":
                        raise RuntimeError("该文件系统属于只读介质")
                    if fs not in SUPPORTED_FS:
                        raise RuntimeError(f"暂不支持的文件系统: {fs}")
                    if progress:
                        progress(78, "挂载文件系统", f"正在以 {mode.upper()} 模式挂载 {device}…")
                    try:
                        host_exec(["mount", "-o", mode, device, str(mount_path)], timeout=120)
                    except Exception as e:
                        detail = str(e)
                        if fs in {"ntfs", "ntfs3"} and mode == "rw":
                            try:
                                host_exec(["mount", "-t", "ntfs-3g", "-o", "rw", device, str(mount_path)], timeout=120)
                            except Exception as e2:
                                raise RuntimeError(f"NTFS 读写挂载失败：{e2}")
                        else:
                            raise RuntimeError(f"mount 失败（设备 {device}）：{detail}")

            with db_conn() as con:
                # 4 placeholders: mount_id, fs_type, mount_mode, image_id.
                # Previous 2.0.12 accidentally supplied mount_id twice (5 bindings).
                con.execute(
                    "UPDATE images SET mounted=1,mount_id=?,fs_type=?,mount_mode=? WHERE id=?",
                    (mount_id, fs, mode, image_id),
                )
                con.execute("INSERT INTO mounts(id,image_id,mount_path,loop_device,partition,fs_type,mode,mounted_at,active) VALUES(?,?,?,?,?,?,?,?,1)", (mount_id, image_id, str(mount_path), loop, chosen_partition, fs, mode, now()))
            log_history("mount", image, f"{mode.upper()} · {fs or 'UNKNOWN'} · {chosen_partition or 'whole-image'}")
            if progress:
                progress(100, "挂载完成", f"{mount_path}")
            return rowdict(get_mount(mount_id))
        except HTTPException:
            raise
        except Exception as e:
            # If the real host mount succeeded but DB bookkeeping failed, clean up
            # the mount first. Otherwise a failed API call could leave a stale mount
            # visible in DSM File Station.
            try:
                if is_mounted_host(mount_path):
                    host_exec(["umount", str(mount_path)], check=False, timeout=60)
            except Exception:
                pass
            if loop:
                host_exec(["losetup", "-d", loop], check=False, timeout=60)
            try:
                mount_path.rmdir()
            except OSError:
                pass
            raise HTTPException(400, f"挂载失败：{e}")


def unmount_image(mount_id: str):
    m = get_mount(mount_id)
    image = get_image(m["image_id"])
    with lock:
        try:
            host_exec(["sync"], check=False, timeout=30)
            r = host_exec(["umount", m["mount_path"]], check=False, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "umount failed；请先关闭占用该目录的 File Station/程序")
            if m["loop_device"]:
                host_exec(["losetup", "-d", m["loop_device"]], check=False, timeout=60)
            with db_conn() as con:
                con.execute("UPDATE mounts SET active=0,unmounted_at=? WHERE id=?", (now(), mount_id))
                con.execute("UPDATE images SET mounted=0,mount_id=NULL,fs_type=NULL,mount_mode=NULL WHERE id=?", (m["image_id"],))
            log_history("unmount", image, f"{m['mode'].upper()} · {m['fs_type'] or 'UNKNOWN'}")
            try: Path(m["mount_path"]).rmdir()
            except OSError: pass
        except Exception as e:
            raise HTTPException(400, f"卸载失败：{e}")


def restore_mounts():
    if not AUTO_RESTORE:
        return
    with db_conn() as con:
        rows = con.execute("SELECT * FROM mounts WHERE active=1").fetchall()
    for m in rows:
        try:
            if is_mounted_host(Path(m["mount_path"])):
                continue
            mount_image(m["image_id"], m["mode"], m["partition"])
        except Exception:
            with db_conn() as con:
                con.execute("UPDATE mounts SET active=0 WHERE id=?", (m["id"],))


def safe_join(base: Path, rel: str):
    target = (base / rel.lstrip("/")).resolve()
    if os.path.commonpath([str(base.resolve()), str(target)]) != str(base.resolve()):
        raise HTTPException(400, "非法路径")
    return target


def list_dir(path: Path):
    if not path.exists() or not path.is_dir():
        raise HTTPException(404, "目录不存在")
    items = []
    for p in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            st = p.stat()
            items.append({"name": p.name, "dir": p.is_dir(), "size": st.st_size if p.is_file() else None, "mtime": st.st_mtime})
        except OSError:
            pass
    return items


def update_checksum_job(job_id, image_id):
    row = get_image(image_id)
    host_path = Path(row["path"])
    checksum_jobs[job_id]["status"] = "running"
    st = image_source_stat(host_path)
    if not st:
        checksum_jobs[job_id].update({"status":"error","error":"映像文件不存在或 NAS 当前不可访问"})
        return
    total = int(st["size"])
    checksum_jobs[job_id]["size"] = total
    try:
        # sha256sum executes in DSM host namespace, so external /volume1 images work too.
        r = host_exec(["sha256sum", str(host_path)], check=True, timeout=max(300, int(total / (25*1024*1024))))
        digest = r.stdout.split()[0].strip()
        with db_conn() as con:
            con.execute("UPDATE images SET sha256=?,checksum_at=?,size=?,availability=1 WHERE id=?", (digest, now(), total, image_id))
        log_history("checksum", row, digest)
        checksum_jobs[job_id].update({"status":"done", "progress":100, "sha256":digest})
    except Exception as e:
        checksum_jobs[job_id].update({"status":"error", "error":str(e)})



@app.on_event("startup")
def startup():
    init_db()
    print(f"[VirtualDrive] Version {APP_VERSION}; mount DB binding fix active", flush=True)
    threading.Thread(target=refresh_images, daemon=True).start()
    threading.Thread(target=restore_mounts, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Never block the first paint on image scanning or 1 TB image probing.
    with db_conn() as con:
        images = con.execute("SELECT * FROM images ORDER BY name COLLATE NOCASE").fetchall()
        mounts = con.execute("SELECT m.*,i.name image_name FROM mounts m JOIN images i ON i.id=m.image_id WHERE m.active=1 ORDER BY m.mounted_at DESC").fetchall()
    disk = shutil.disk_usage(ROOT)
    stats = {"images": len(images), "mounted": len(mounts), "iso": sum(x["kind"] == "iso" for x in images), "img": sum(x["kind"] == "img" for x in images), "used": disk.used, "total": disk.total, "free": disk.free}
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats})


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    name = safe_name(file.filename or "image.img")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的映像类型: {ext}")
    sub = IMAGES / ("iso" if ext == ".iso" else "img")
    dest = sub / name
    if dest.exists(): dest = sub / f"{Path(name).stem}-{uuid.uuid4().hex[:6]}{ext}"
    with dest.open("wb") as f:
        while chunk := await file.read(8 * 1024 * 1024): f.write(chunk)
    refresh_images()
    log_history("upload", next((r for r in db_conn().execute("SELECT * FROM images WHERE path=?", (str(dest.resolve()),)).fetchall()), None), f"{dest.name}")
    return {"ok": True, "name": dest.name}


@app.get("/api/nas/browse")
def api_nas_browse(path: str | None = None):
    if not path:
        path = str(default_nas_import_root())
    """Browse DSM host filesystem through the same mount namespace used by mount operations.

    Do not enumerate /proc/1/root from Python. On Synology, the reliable view is the
    host mount namespace reached with nsenter -t 1 -m.
    """
    host_folder = validate_nas_path(path)
    target = str(host_folder)

    try:
        check = host_exec(["test", "-d", target], check=False)
        if check.returncode != 0:
            raise HTTPException(404, f"NAS 目录不存在：{target}")

        listing = host_exec([
            "find", target, "-mindepth", "1", "-maxdepth", "1", "-print0"
        ], check=True, timeout=60, text=False)
    except FileNotFoundError:
        raise HTTPException(500, "NAS 浏览需要宿主机提供 find/stat；当前 DSM 环境未找到相应命令")
    except subprocess.CalledProcessError as e:
        raise HTTPException(403, f"没有权限读取 NAS 目录：{target}") from e
    except subprocess.TimeoutExpired as e:
        raise HTTPException(504, f"读取 NAS 目录超时：{target}") from e

    raw_items = [x for x in listing.stdout.split(b"\x00") if x]
    entries = []
    for raw in raw_items:
        try:
            item_path = raw.decode("utf-8", "surrogateescape")
        except UnicodeDecodeError:
            item_path = raw.decode("utf-8", "replace")
        try:
            st = host_exec(["stat", "-c", "%F\t%s\t%Y", item_path], check=True, timeout=20)
            kind_text, size_text, mtime_text = st.stdout.splitlines()[0].split("\t", 2)
            is_dir = kind_text.startswith("directory")
            is_file = kind_text.startswith("regular file")
            name = item_path.rsplit("/", 1)[-1]
            is_image = is_file and Path(name).suffix.lower() in ALLOWED_EXT
            entries.append({
                "name": name,
                "dir": is_dir,
                "size": int(size_text) if is_file else None,
                "mtime": float(mtime_text),
                "image": is_image,
                "kind": classify(name) if is_image else None,
                "path": item_path,
            })
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError):
            continue

    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    parent = str(host_folder.parent) if host_folder != NAS_ROOT else None
    return {"path": str(host_folder), "parent": parent, "items": entries, "backend": "nsenter-host-mount", "default_root": str(default_nas_import_root())}


@app.post("/api/library/add")
def api_library_add(path: str = Form(...)):
    host_path = validate_nas_path(path)
    ext = host_path.suffix.lower()
    host_str = str(host_path)
    try:
        check = host_exec(["test", "-f", host_str], check=False, timeout=20)
        if check.returncode != 0 or ext not in ALLOWED_EXT:
            raise HTTPException(400, "请选择 NAS 内的 ISO/IMG 映像文件")
        st = host_exec(["stat", "-c", "%s", host_str], check=True, timeout=20)
        size = int(st.stdout.strip())
    except subprocess.CalledProcessError as e:
        raise HTTPException(403, f"无法读取 NAS 映像：{host_str}") from e
    except (ValueError, subprocess.TimeoutExpired) as e:
        raise HTTPException(500, f"无法获取 NAS 映像大小：{host_str}") from e
    with db_conn() as con:
        row = con.execute("SELECT * FROM images WHERE path=?", (host_str,)).fetchone()
        if row:
            return {"ok": True, "existing": True, "image": rowdict(row)}
        image_id = uuid.uuid4().hex
        con.execute("INSERT INTO images(id,name,path,kind,size,created_at) VALUES(?,?,?,?,?,?)", (image_id, host_path.name, host_str, classify(host_path.name), size, now()))
        row = con.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    log_history("import", row, f"NAS 现有文件 · {host_str}")
    return {"ok": True, "existing": False, "image": rowdict(row)}


@app.get("/api/nas/status")
def api_nas_status():
    target = str(NAS_ROOT)
    try:
        root_ok = host_exec(["test", "-d", target], check=False, timeout=20).returncode == 0
        volume_ok = root_ok
        mount_info = host_exec(["findmnt", "-T", target, "-n", "-o", "TARGET,FSTYPE,OPTIONS"], check=False, timeout=20)
        mount_text = mount_info.stdout.strip() if mount_info.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        root_ok = False
        volume_ok = False
        mount_text = ""
    return {
        "host_root": target,
        "host_fs_view": str(HOST_FS_VIEW),
        "view_root": target,
        "view_exists": root_ok,
        "volume1_exists": volume_ok,
        "mount": mount_text,
        "mode": "nsenter-host-mount",
        "import_root": str(default_nas_import_root()),
    }


@app.get("/api/library/roots")
def api_library_roots():
    return {"root": str(NAS_ROOT.resolve()), "image_root": str(IMAGES.resolve())}


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION}


@app.get("/api/summary")
def summary():
    with db_conn() as con:
        images = con.execute("SELECT * FROM images").fetchall(); mounts = con.execute("SELECT * FROM mounts WHERE active=1").fetchall()
    disk = shutil.disk_usage(ROOT)
    return {"images":len(images),"mounted":len(mounts),"iso":sum(x["kind"]=="iso" for x in images),"img":sum(x["kind"]=="img" for x in images),"disk":disk._asdict(),"scan":library_scan}


@app.get("/api/images")
def api_images():
    with db_conn() as con: rows = con.execute("SELECT * FROM images ORDER BY name COLLATE NOCASE").fetchall()
    return [rowdict(r) for r in rows]


@app.get("/api/library/status")
def api_library_status():
    return library_scan


@app.post("/api/library/scan")
def api_library_scan():
    if library_scan.get("status") == "running":
        return {"ok": True, "already_running": True, "scan": library_scan}
    threading.Thread(target=refresh_images, daemon=True).start()
    return {"ok": True, "already_running": False, "scan": library_scan}


@app.get("/api/images/{image_id}/inspect")
def api_inspect(image_id: str):
    return inspect_image(get_image(image_id))

@app.post("/api/images/{image_id}/inspect/start")
def api_inspect_start(image_id: str):
    get_image(image_id)
    job_id = uuid.uuid4().hex
    inspect_jobs[job_id] = {"status":"queued","progress":0,"stage":"排队","detail":"","image_id":image_id}
    def worker():
        inspect_jobs[job_id].update({"status":"running","progress":10,"stage":"验证映像","detail":"确认 NAS 映像可访问…"})
        try:
            inspect_jobs[job_id].update({"progress":30,"stage":"读取分区","detail":"正在读取分区表；大容量 IMG 可能需要一些时间…"})
            result = inspect_image(get_image(image_id))
            inspect_jobs[job_id].update({"status":"done","progress":100,"stage":"完成","detail":"映像分析完成","result":result})
        except Exception as e:
            inspect_jobs[job_id].update({"status":"error","progress":100,"stage":"失败","error":str(e)})
    threading.Thread(target=worker, daemon=True).start()
    return {"job_id":job_id}


@app.get("/api/inspect/{job_id}")
def api_inspect_status(job_id: str):
    if job_id not in inspect_jobs:
        raise HTTPException(404, "任务不存在")
    return inspect_jobs[job_id]


@app.post("/api/images/{image_id}/checksum")
def api_checksum(image_id: str):
    get_image(image_id); job_id = uuid.uuid4().hex
    checksum_jobs[job_id] = {"status":"queued","progress":0,"image_id":image_id}
    threading.Thread(target=update_checksum_job, args=(job_id,image_id), daemon=True).start()
    return {"job_id":job_id}


@app.get("/api/checksum/{job_id}")
def api_checksum_status(job_id: str):
    if job_id not in checksum_jobs: raise HTTPException(404,"任务不存在")
    return checksum_jobs[job_id]


@app.post("/api/images/{image_id}/mount/start")
def api_mount_start(image_id: str, mode: str = Form("ro"), partition: str | None = Form(None)):
    get_image(image_id)
    job_id = uuid.uuid4().hex
    mount_jobs[job_id] = {"status":"queued","progress":0,"stage":"排队","detail":"","image_id":image_id,"mode":mode,"partition":partition}
    def worker():
        try:
            def progress(p, stage, detail=""):
                mount_jobs[job_id].update({"status":"running","progress":p,"stage":stage,"detail":detail})
            progress(2, "开始挂载", "正在准备挂载任务…")
            m = mount_image(image_id, mode, partition, progress=progress)
            mount_jobs[job_id].update({"status":"done","progress":100,"stage":"挂载完成","detail":"挂载成功","mount":m})
        except HTTPException as e:
            mount_jobs[job_id].update({"status":"error","progress":100,"stage":"挂载失败","error":e.detail})
        except Exception as e:
            mount_jobs[job_id].update({"status":"error","progress":100,"stage":"挂载失败","error":str(e)})
    threading.Thread(target=worker, daemon=True).start()
    return {"job_id":job_id}


@app.get("/api/mount-job/{job_id}")
def api_mount_status(job_id: str):
    if job_id not in mount_jobs:
        raise HTTPException(404, "任务不存在")
    return mount_jobs[job_id]


@app.post("/api/images/{image_id}/mount")
def api_mount(image_id: str, mode: str = Form("ro"), partition: str | None = Form(None)):
    return {"ok":True,"mount":mount_image(image_id,mode,partition)}


@app.delete("/api/images/{image_id}")
def api_delete_image(image_id: str):
    img = get_image(image_id)
    if img["mounted"]: raise HTTPException(409,"请先卸载映像")
    p = Path(img["path"])
    # 外部 NAS 映像只从“映像库索引”移除，不直接删除原文件；项目 images/ 下的导入文件才允许真正删除。
    if p.exists() and is_managed_image_path(p):
        p.unlink()
        detail = "删除映像文件"
    else:
        detail = "仅移除 NAS 映像索引，原文件保留"
    with db_conn() as con: con.execute("DELETE FROM images WHERE id=?", (image_id,))
    log_history("delete", img, detail)
    return {"ok":True}


@app.get("/api/mounts")
def api_mounts():
    with db_conn() as con: rows = con.execute("SELECT m.*,i.name image_name FROM mounts m JOIN images i ON i.id=m.image_id WHERE m.active=1 ORDER BY m.mounted_at DESC").fetchall()
    out=[]
    for r in rows:
        d=rowdict(r)
        try:
            real = is_mounted_host(Path(d["mount_path"]))
        except Exception:
            real = False
        if not real:
            with db_conn() as con:
                con.execute("UPDATE mounts SET active=0,unmounted_at=? WHERE id=?", (now(), d["id"]))
                con.execute("UPDATE images SET mounted=0,mount_id=NULL,fs_type=NULL,mount_mode=NULL WHERE id=?", (d["image_id"],))
            continue
        out.append(d)
    return out


@app.post("/api/mounts/{mount_id}/unmount")
def api_unmount(mount_id: str):
    unmount_image(mount_id); return {"ok":True}


@app.get("/api/mounts/{mount_id}/files")
def api_files(mount_id: str, path: str = "/"):
    m=get_mount(mount_id); base=Path(m["mount_path"]).resolve(); target=safe_join(base,path)
    return {"path":"/" + str(target.relative_to(base)) if target != base else "/","items":list_dir(target)}


@app.get("/api/mounts/{mount_id}/download")
def api_download(mount_id: str, path: str):
    m=get_mount(mount_id); target=safe_join(Path(m["mount_path"]).resolve(),path)
    if not target.exists() or not target.is_file(): raise HTTPException(404,"文件不存在")
    return FileResponse(target,filename=target.name)


@app.post("/api/mounts/{mount_id}/upload")
async def api_mount_upload(mount_id: str, path: str = Form("/"), file: UploadFile = File(...)):
    m=get_mount(mount_id)
    if m["mode"]!="rw": raise HTTPException(400,"当前挂载为只读")
    folder=safe_join(Path(m["mount_path"]).resolve(),path); folder.mkdir(parents=True,exist_ok=True)
    target=safe_join(folder,safe_name(file.filename or "upload.bin"))
    with target.open("wb") as f:
        while chunk := await file.read(8*1024*1024): f.write(chunk)
    return {"ok":True}


@app.post("/api/mounts/{mount_id}/mkdir")
def api_mkdir(mount_id: str, path: str = Form("/"), name: str = Form(...)):
    m=get_mount(mount_id)
    if m["mode"]!="rw": raise HTTPException(400,"当前挂载为只读")
    safe_join(Path(m["mount_path"]).resolve(),path).joinpath(safe_name(name)).mkdir(parents=False,exist_ok=False)
    return {"ok":True}


@app.delete("/api/mounts/{mount_id}/file")
def api_delete_file(mount_id: str, path: str):
    m=get_mount(mount_id)
    if m["mode"]!="rw": raise HTTPException(400,"当前挂载为只读")
    p=safe_join(Path(m["mount_path"]).resolve(),path)
    if p.is_dir(): shutil.rmtree(p)
    elif p.exists(): p.unlink()
    else: raise HTTPException(404,"不存在")
    return {"ok":True}


@app.post("/api/mounts/{mount_id}/copy-to-nas")
def api_copy_to_nas(mount_id: str, path: str, destination: str = Form("/")):
    m=get_mount(mount_id); src=safe_join(Path(m["mount_path"]).resolve(),path)
    if not src.exists(): raise HTTPException(404,"源路径不存在")
    destdir=safe_join(EXPORT.resolve(),destination); destdir.mkdir(parents=True,exist_ok=True); dest=destdir/src.name
    if src.is_dir(): shutil.copytree(src,dest,dirs_exist_ok=True)
    else: shutil.copy2(src,dest)
    return {"ok":True,"destination":str(dest.relative_to(EXPORT))}


@app.get("/api/history")
def api_history(limit: int = 100):
    limit=max(1,min(limit,500))
    with db_conn() as con: rows=con.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [rowdict(r) for r in rows]


@app.get("/api/mounts/{mount_id}/usage")
def api_usage(mount_id: str):
    m=get_mount(mount_id); p=Path(m["mount_path"])
    try:
        st=shutil.disk_usage(p); return {"total":st.total,"used":st.used,"free":st.free,"percent":round(st.used/st.total*100,1) if st.total else 0}
    except Exception as e: raise HTTPException(400,str(e))


@app.get("/health")
def health(): return {"ok":True,"time":now()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
