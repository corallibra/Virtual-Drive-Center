# Virtual Drive Center 2.0.13

**ISO / IMG 磁盘挂载工具 · Synology Container Manager**

作者：**Michael**  
项目类型：Self-hosted / Community Project  
适用平台：Synology NAS + DSM + Container Manager

> Virtual Drive Center 是一个面向 Synology NAS 的 Web 化 ISO / IMG 映像管理与挂载工具。它的目标不是模拟硬件光驱，而是把 NAS 上保存的 ISO / IMG 作为可管理的虚拟磁盘映像，通过网页完成选择、检查、分区识别、挂载、读写和卸载，并让成功挂载的目录出现在 NAS 的真实文件系统中，从而可以继续使用 DSM File Station 访问。
>
> **本项目不是 Synology 官方产品，与 Synology Inc. 没有隶属、授权或商业合作关系。**

---

## 目录

- [一、项目目的](#一项目目的)
- [二、项目说明](#二项目说明)
- [三、核心设计思路](#三核心设计思路)
- [四、主要功能](#四主要功能)
- [五、典型使用场景](#五典型使用场景)
- [六、系统架构](#六系统架构)
- [七、基础要求](#七基础要求)
- [八、部署前准备](#八部署前准备)
- [九、详细部署指南](#九详细部署指南)
- [十、首次启动与登录](#十首次启动与登录)
- [十一、首次使用流程](#十一首次使用流程)
- [十二、ISO 与 IMG 的处理方式](#十二iso-与-img-的处理方式)
- [十三、多分区 IMG](#十三多分区-img)
- [十四、DSM File Station 集成](#十四dsm-file-station-集成)
- [十五、配置说明](#十五配置说明)
- [十六、安全说明](#十六安全说明)
- [十七、故障排查](#十七故障排查)
- [十八、数据与备份](#十八数据与备份)
- [十九、项目规划](#十九项目规划)
- [二十、参与开发](#二十参与开发)
- [二十一、版权与许可证](#二十一版权与许可证)
- [二十二、免责声明](#二十二免责声明)

---

## 一、项目目的

Virtual Drive Center 的核心目的，是解决一个实际的 NAS 使用需求：**大量 ISO / IMG 文件已经存储在 NAS 上，但访问其中内容时，传统方式通常需要 SSH、手工 `losetup`、手工 `mount`，对于多分区 IMG 更加繁琐。**

本项目希望把这一过程统一到一个易用的 Web 控制台中：

```text
NAS 中已有 ISO / IMG
        │
        ▼
   Web 映像管理器
        │
        ├─ NAS 内部选择
        ├─ 电脑上传
        ├─ 映像检查
        ├─ 分区识别
        ├─ 文件系统识别
        └─ 挂载 / 卸载
        │
        ▼
DSM 宿主机真实挂载点
        │
        ▼
    DSM File Station
```

项目的长期方向，是让用户无需频繁进入 SSH，即可管理 NAS 上的虚拟磁盘映像，并在 Web 与 DSM File Station 之间保持清晰、可追踪的工作流。

---

## 二、项目说明

Virtual Drive Center 2.0.13 是一个运行在 Docker / Container Manager 中的 Web 管理应用，主要由以下几个部分组成：

1. **映像库**：记录 ISO / IMG 的来源、类型、容量、状态和挂载关系。
2. **NAS 文件选择器**：从 NAS 指定目录开始浏览实际 NAS 文件系统，并直接选择已有映像，不需要重新上传。
3. **电脑上传入口**：保留浏览器本地文件上传和拖拽上传功能。
4. **Image Inspector**：检查映像类型、容量、分区表、分区、文件系统和可支持状态。
5. **Mount Manager**：负责 loop device、分区设备、mount、umount 和状态恢复。
6. **Web File Manager**：对成功挂载的文件系统提供基础文件操作。
7. **DSM File Station 路径提示**：挂载成功后显示真实 NAS 路径，帮助用户快速定位挂载内容。
8. **历史记录与状态**：保存挂载、卸载、校验等操作历史。

本项目重点面向 **Synology DSM + Container Manager**，但内部使用的 Linux 工具链具有一定通用性。

---

## 三、核心设计思路

### 3.1 不是“容器内部假挂载”

项目最终采用的是宿主机 mount namespace 方案。容器具备 `pid: host` 和高权限，通过 `nsenter -t 1 -m` 在 NAS 宿主机的 mount namespace 中执行必要的挂载操作。

简化理解：

```text
Web UI
  ↓
FastAPI
  ↓
宿主机 namespace bridge
  ↓
nsenter -t 1 -m
  ↓
DSM host mount namespace
  ↓
losetup / blkid / mount / umount
```

这样做的目标是让挂载点真正存在于 NAS 主机路径中，而不仅存在于容器自己的 namespace 中。

### 3.2 为什么不依赖 `rshared`

Synology 的 `/volume1` 在某些环境中并不是 Docker 所要求的 shared mount。直接使用 `:rshared` 可能导致容器创建阶段出现：

```text
path /volume1/docker/virtual-drive is mounted on /volume1 but it is not a shared mount
```

本项目因此不把 `rshared` 作为部署前提，而是直接通过 host mount namespace 执行挂载操作。

### 3.3 NAS 浏览与本地上传是两个独立入口

“NAS 内部选择”不会调用浏览器本地文件选择框，而是由服务端读取 NAS 文件系统并将目录内容返回到 Web 页面。

```text
NAS 内部选择
  → 浏览 NAS
  → 选择已有 ISO / IMG
  → 登记到映像库
  → 不复制原始文件
```

而“电脑上传”仍然使用浏览器上传文件到 NAS 项目的映像目录。

---

## 四、主要功能

| 功能 | 说明 |
|---|---|
| Web 登录 | 自定义账号与密码 |
| NAS 内部选择 | 默认从指定 NAS 目录开始浏览 |
| 电脑上传 | 支持本地文件上传与拖拽 |
| ISO 管理 | ISO 类型识别与只读挂载 |
| IMG 管理 | 原始整盘镜像与分区镜像 |
| MBR/GPT | 自动识别分区表 |
| 多分区 IMG | Web 中手工选择目标分区 |
| 文件系统识别 | NTFS / exFAT / FAT32 / EXT 等，具体能力取决于 DSM 环境 |
| RO / RW | ISO 默认只读；IMG 根据文件系统和挂载方式决定 |
| SHA-256 | 映像完整性校验 |
| 异步任务 | 大容量 IMG 检查与挂载过程提供状态显示 |
| 文件管理 | 浏览、上传、下载、创建目录、删除等基础操作 |
| NAS 路径 | 显示真实 DSM File Station 路径 |
| 挂载历史 | 记录挂载、卸载、检查等事件 |
| 状态恢复 | 支持启动时恢复可恢复的挂载状态 |
| 响应式 UI | 面向桌面端 NAS 管理使用场景设计 |

---

## 五、典型使用场景

### 场景 A：从 NAS 直接打开一个 ISO

```text
/volume1/isos/ubuntu.iso
        ↓
NAS 内部选择
        ↓
挂载
        ↓
只读文件系统
        ↓
DSM File Station
```

### 场景 B：打开多分区 IMG

例如一个 IMG：

```text
Disk Image
├── Partition 1  NTFS   GAMES
├── Partition 2  FAT32  BATOCERA
└── Partition 3  NTFS   SHARE
```

用户可以在 Image Inspector 中查看所有分区，然后选择需要的分区进行挂载，而不是把整个磁盘镜像直接当作单一文件系统挂载。

### 场景 C：从电脑上传一个新镜像

```text
电脑
 ↓ 拖拽
Web UI
 ↓
NAS /volume1/docker/virtual-drive/images/
 ↓
映像库
```

---

## 六、系统架构

```text
┌───────────────────────────────────────────────┐
│                 Browser / Web UI              │
│                                               │
│  Dashboard  Image Inspector  Mount  Files    │
└───────────────────────┬───────────────────────┘
                        │ HTTP
                        ▼
┌───────────────────────────────────────────────┐
│              Virtual Drive Container           │
│                                               │
│ FastAPI / Web App                             │
│ ├─ NAS File Picker                            │
│ ├─ Image Inspector                            │
│ ├─ Mount Manager                              │
│ ├─ File Manager                               │
│ └─ History / SQLite                           │
│                                               │
│ host namespace bridge                         │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
                nsenter -t 1 -m
                        │
                        ▼
┌───────────────────────────────────────────────┐
│             Synology Host Namespace           │
│                                               │
│ /volume1                                      │
│ ├─ homes                                      │
│ ├─ docker                                     │
│ ├─ ...                                        │
│ └─ virtual-drive/mounts                       │
│                                               │
│ loop devices                                  │
│ ├─ /dev/loopN                                 │
│ ├─ /dev/loopNp1                               │
│ ├─ /dev/loopNp2                               │
│ └─ ...                                        │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
              DSM File Station
```

---

## 七、基础要求

### 7.1 NAS 基础要求

建议环境：

- Synology NAS
- DSM 7.x 或兼容的现代 DSM 环境
- Container Manager
- 支持 Docker Compose 项目
- NAS 文件系统可以正常访问 ISO / IMG
- 需要能够在容器内执行宿主机 namespace 操作

### 7.2 容器权限要求

当前版本为了实现真实宿主机挂载，Compose 使用：

```yaml
privileged: true
pid: host
```

这是本项目的关键设计要求，同时也是最大的安全风险来源之一。

### 7.3 NAS 存储要求

至少准备一个项目目录，例如：

```text
/volume1/docker/virtual-drive/
```

建议最终结构：

```text
/volume1/docker/virtual-drive/
├── images/
│   ├── iso/
│   └── img/
├── mounts/
├── data/
└── export/
```

### 7.4 软件工具

实际功能会使用 Linux 环境中的工具，例如：

- `nsenter`
- `losetup`
- `mount`
- `umount`
- `blkid`
- 分区检测相关工具
- 必要的文件系统辅助工具

不同 Synology 型号、DSM 版本和基础镜像可能导致工具可用性不同。

---

## 八、部署前准备

### 8.1 创建项目目录

在 NAS 上创建：

```text
/volume1/docker/virtual-drive-app/
```

其中保存本项目源代码与 Compose 文件。

**注意：**项目源码目录与应用数据目录可以分开。

建议：

```text
源代码：/volume1/docker/virtual-drive-app/
数据：  /volume1/docker/virtual-drive/
```

### 8.2 创建数据目录

```bash
mkdir -p /volume1/docker/virtual-drive/images/iso
mkdir -p /volume1/docker/virtual-drive/images/img
mkdir -p /volume1/docker/virtual-drive/mounts
mkdir -p /volume1/docker/virtual-drive/data
mkdir -p /volume1/docker/virtual-drive/export
```

### 8.3 配置 `.env`

复制：

```bash
cp .env.example .env
```

推荐配置：

```dotenv
PROJECT_ROOT=/volume1/docker/virtual-drive
NAS_ROOT=/volume1
NAS_IMPORT_ROOT=/volume1/your-share/Downloads
EXTERNAL_PORT=9109
VD_USER=admin
VD_PASSWORD=请设置一个强密码
```

---

## 九、详细部署指南

### 方法 A：Synology Container Manager

1. 将项目上传到 NAS。
2. 打开 **Container Manager → 项目**。
3. 创建新项目。
4. 选择项目目录。
5. 使用项目中的 `compose.yml`。
6. 检查 `.env` 或 Compose 中的 NAS 路径、端口和账号密码。
7. 构建项目。
8. 启动容器。
9. 查看容器日志，确认 Web 服务已启动。

### 方法 B：SSH + Docker Compose

进入项目目录：

```bash
cd /volume1/docker/virtual-drive-app
```

构建并启动：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f virtual-drive
```

停止：

```bash
docker compose down
```

重新构建：

```bash
docker compose build --no-cache
```

启动：

```bash
docker compose up -d
```

---

## 十、首次启动与登录

如果设置：

```yaml
ports:
  - "9109:8099"
```

则访问：

```text
http://NAS-IP:9109
```

账号由：

```dotenv
VD_USER=admin
```

决定。

建议使用强密码，例如：

```dotenv
VD_PASSWORD=Vd@2026#StrongPassword
```

不要把实际密码提交到 Git 仓库。

---

## 十一、首次使用流程

### 11.1 从 NAS 选择映像

点击：

```text
导入映像 → NAS 内部选择
```

默认进入：

```text
/volume1/your-share/Downloads
```

例如：

```dotenv
NAS_IMPORT_ROOT=/volume1/homes/<your-user>/Downloads
```

点击 ISO / IMG 后，程序登记该 NAS 文件。

**NAS 原文件不会因为加入映像库而被复制。**

### 11.2 从电脑上传

点击：

```text
导入映像 → 电脑上传
```

或者把映像文件直接拖入上传区域。

### 11.3 检查映像

推荐先执行：

```text
检查
```

再根据检查结果决定挂载方式。

### 11.4 挂载

对于 ISO：

```text
选择 ISO → 只读挂载
```

对于多分区 IMG：

```text
选择 IMG
→ 检查
→ 查看分区
→ 选择目标分区
→ RO / RW
→ 挂载
```

### 11.5 卸载

完成读写后：

```text
卸载
```

建议始终通过程序执行卸载，让程序完成必要的同步和清理工作。

---

## 十二、ISO 与 IMG 的处理方式

### 12.1 ISO

ISO 通常作为光盘映像使用：

```text
ISO
 ↓
loop / filesystem
 ↓
read-only mount
```

本项目默认按照只读介质处理 ISO。

### 12.2 单文件系统 IMG

某些 IMG 是整个文件本身就是一个文件系统：

```text
image.img
└── NTFS / ext4 / FAT32 / ...
```

这种情况下不需要选择分区，可以直接挂载整个映像。

### 12.3 分区 IMG

例如：

```text
image.img
├── MBR/GPT
├── partition 1
├── partition 2
└── partition 3
```

应先识别分区，再选择具体分区挂载。

---

## 十三、多分区 IMG

多分区 IMG 是本项目的重要使用场景。

例如某个磁盘镜像可能显示：

```text
Partition 1
NTFS
LABEL=GAMES

Partition 2
FAT32
LABEL=BATOCERA

Partition 3
NTFS
LABEL=SHARE
```

Web 页面应允许用户选择：

```text
[挂载 Partition 1]
[挂载 Partition 2]
[挂载 Partition 3]
```

程序应优先使用系统生成的：

```text
/dev/loopNp1
/dev/loopNp2
/dev/loopNp3
```

如果目标系统未自动提供分区节点，则可以根据分区起始位置与长度采用 offset/sizelimit 方式建立可挂载设备。

---

## 十四、DSM File Station 集成

本项目最重要的设计目标之一，是让成功挂载的内容出现在 NAS 的真实文件路径中。

例如：

```text
/volume1/docker/virtual-drive/mounts/example-123456/
```

Web 页面应同时显示：

```text
NAS 真实路径
/volume1/docker/virtual-drive/mounts/example-123456
```

以及：

```text
DSM File Station
Docker → virtual-drive → mounts → example-123456
```

这样用户可以：

```text
Web
 ↓
选择并挂载
 ↓
取得真实 NAS 路径
 ↓
DSM File Station
 ↓
读取 / copy / 写入
```

需要注意：是否能从 File Station 读取或写入某个具体挂载文件系统，仍取决于 DSM、文件系统驱动、权限和挂载方式。

---

## 十五、配置说明

主要环境变量：

| 变量 | 示例 | 说明 |
|---|---|---|
| `TZ` | `Asia/Tokyo` | 时区 |
| `PROJECT_ROOT` | `/volume1/docker/virtual-drive` | 应用数据根目录 |
| `HOST_ROOT` | `/volume1/docker/virtual-drive` | 宿主机项目根路径 |
| `IMAGES_DIR` | `/volume1/docker/virtual-drive/images` | 映像目录 |
| `MOUNTS_DIR` | `/volume1/docker/virtual-drive/mounts` | 挂载目录 |
| `DATA_DIR` | `/volume1/docker/virtual-drive/data` | 数据库与状态 |
| `EXPORT_DIR` | `/volume1/docker/virtual-drive/export` | 导出/复制目录 |
| `NAS_ROOT` | `/volume1` | NAS 宿主机根路径 |
| `NAS_IMPORT_ROOT` | `/volume1/homes/<your-user>/Downloads` | NAS 选择器默认目录 |
| `HOST_FS_VIEW` | `/proc/1/root` | 兼容辅助路径 |
| `PORT` | `8099` | 容器内部 Web 端口 |
| `EXTERNAL_PORT` | `9109` | NAS 对外映射端口 |
| `AUTO_RESTORE` | `true` | 启动时尝试恢复状态 |
| `VD_USER` | `admin` | Web 用户名 |
| `VD_PASSWORD` | `...` | Web 密码 |

### 推荐配置模板

```yaml
environment:
  TZ: Asia/Tokyo
  HOST_ROOT: /volume1/docker/virtual-drive
  IMAGES_DIR: /volume1/docker/virtual-drive/images
  MOUNTS_DIR: /volume1/docker/virtual-drive/mounts
  DATA_DIR: /volume1/docker/virtual-drive/data
  EXPORT_DIR: /volume1/docker/virtual-drive/export
  NAS_ROOT: /volume1
  HOST_FS_VIEW: /proc/1/root
  NAS_IMPORT_ROOT: /volume1/your-share/Downloads
  PORT: "8099"
  AUTO_RESTORE: "true"
  VD_USER: admin
  VD_PASSWORD: "CHANGE-ME"
```

---

## 十六、安全说明

### 16.1 高权限容器

当前实现需要：

```yaml
privileged: true
pid: host
```

这意味着容器具备非常高的主机访问能力。

因此：

- 建议只在可信的 LAN 环境部署。
- 不建议将 Web 端口直接暴露到公网。
- 必须设置强密码。
- 应定期更新镜像和依赖。
- 不要在仓库中提交 `.env`、数据库、密码文件或私人日志。

### 16.2 文件系统写入风险

RW 挂载会让 IMG 中的数据真实发生修改。对重要镜像操作前，建议：

1. 保留原始备份。
2. 优先 RO 检查。
3. 确认目标文件系统支持 RW。
4. 再切换到 RW。
5. 卸载之前等待写操作完成。

### 16.3 互联网暴露

如果需要远程访问，推荐通过 VPN、反向代理或其他有身份认证和访问控制的安全通道，而不是直接将 `9109` 映射到公网。

---

## 十七、故障排查

### 17.1 容器启动时报 shared mount

错误：

```text
path /volume1/docker/virtual-drive is mounted on /volume1 but it is not a shared mount
```

检查 Compose 是否还存在：

```yaml
: rshared
```

例如：

```yaml
- /volume1/docker/virtual-drive:/volume1/docker/virtual-drive:rshared
```

当前方案**不要使用 `rshared`**。

### 17.2 Web 无法浏览 NAS

先进入容器终端测试：

```bash
nsenter -t 1 -m -- ls -la /volume1
```

进一步：

```bash
nsenter -t 1 -m -- ls -la /volume1/homes
```

以及：

```bash
nsenter -t 1 -m -- ls -la /volume1/homes/<user>/Downloads
```

如果这些命令可以看到 NAS 文件，而 Web 不能显示，则应检查应用日志和 NAS 浏览 API。

### 17.3 `docker: command not found`

如果你已经进入 `virtual-drive` 容器：

```text
root@container:/opt/virtual-drive#
```

此时容器内不一定安装 Docker CLI，因此：

```bash
docker exec ...
```

不能再次执行。

直接使用已经进入的容器 shell，或者从 NAS 主机执行 Docker 命令。

### 17.4 `lsblk` 找不到

`nsenter -t 1 -m` 只切换 mount namespace，不会把宿主机的可执行文件路径自动变成容器中的命令路径。

可尝试：

```bash
which lsblk
```

或检查：

```bash
ls -la /proc/1/root/usr/bin/lsblk
```

如果不存在，则使用 `/sys/class/block`、`blkid` 等已可用能力进行补充判断。

### 17.5 IMG 显示未知

建议执行：

```bash
nsenter -t 1 -m -- file -sL /volume1/path/to/image.img
```

```bash
nsenter -t 1 -m -- blkid -p -o full /volume1/path/to/image.img
```

```bash
nsenter -t 1 -m -- sfdisk -J /volume1/path/to/image.img
```

然后建立 loop：

```bash
nsenter -t 1 -m -- losetup --find --show --partscan --read-only /volume1/path/to/image.img
```

查看分区节点：

```bash
nsenter -t 1 -m -- sh -c 'ls -la /dev/loopN*'
```

查看 filesystem：

```bash
nsenter -t 1 -m -- sh -c 'for x in /dev/loopN /dev/loopNp*; do [ -e "$x" ] || continue; echo "=== $x ==="; blkid "$x" 2>&1 || true; done'
```

### 17.6 mount 返回 exit status 32

不要只看：

```text
exit status 32
```

应该查看实际 mount stderr，例如：

```text
wrong fs type
bad superblock
unknown filesystem
missing helper
permission denied
```

先确认选择的是正确的：

```text
/dev/loopNp1
```

而不是把整块分区镜像错误地作为单一 filesystem：

```text
/dev/loopN
```

### 17.7 `Incorrect number of bindings supplied`

这是 SQLite SQL 参数数量不一致造成的应用程序错误。如果出现类似：

```text
The current statement uses 4, and there are 5 supplied.
```

应检查挂载成功后数据库状态更新 SQL 的参数数量。

### 17.8 页面显示旧版本

浏览器缓存可能保留旧 CSS / JS。建议：

1. 强制刷新。
2. 确认容器重新 Build。
3. 确认页面版本号已变化。
4. 检查静态资源版本参数。

---

## 十八、数据与备份

建议至少备份：

```text
/volume1/docker/virtual-drive/data/
/volume1/docker/virtual-drive/images/
```

如果项目中保存了重要运行状态，也建议保留：

```text
mounts/
```

但在恢复之前需要确认原来的 loop device 和 mount 状态已经不存在，以避免残留挂载。

建议不要把下面这些文件提交到 Git：

```text
.env
*.db
*.db-wal
*.db-shm
admin-password.txt
logs/
```

---

## 十九、项目规划

### 第一阶段：稳定版（当前 2.0.x）

当前目标是完成以下基础闭环：

```text
NAS / PC 导入
      ↓
映像识别
      ↓
分区识别
      ↓
文件系统识别
      ↓
挂载 / 卸载
      ↓
Web 文件管理
      ↓
DSM File Station
```

### 第二阶段：2.1.x

规划方向：

- 更完善的 NAS 双栏文件浏览器
- 多选和批量导入
- 批量挂载 / 卸载
- 更详细的磁盘占用统计
- 目录树与面包屑导航
- 右键操作菜单
- 更完整的任务中心
- 更好的失败诊断
- 进程与 loop device 状态监控

### 第三阶段：2.2.x

规划方向：

- 更完善的文件系统兼容性检测
- 镜像健康检查
- SMART/底层磁盘状态关联信息（如环境允许）
- 挂载策略模板
- 多用户与更细粒度权限
- Web 操作审计

### 第四阶段：长期方向

可能探索：

- 网络块设备集成
- ISO 内容修改与重新生成
- 自动镜像转换
- API / Webhook
- 多 NAS / 多节点管理

以上为项目规划方向，不代表所有功能均承诺在特定版本实现。

---

## 二十、参与开发

欢迎提交：

- Bug report
- Feature request
- Pull Request
- 文档改进
- Synology / DSM 兼容性报告

提交问题时建议提供：

1. NAS 型号。
2. DSM 版本。
3. Container Manager 版本。
4. CPU 架构。
5. IMG/ISO 类型。
6. 相关 Web 错误。
7. 必要时提供脱敏后的命令输出。

**不要公开上传私人镜像、账号、密码、token 或完整 NAS 日志。**

更多贡献说明见：[CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 二十一、版权与许可证

Copyright (c) 2026 **Michael**

本项目采用 **MIT License**，除非仓库中另有明确说明。

完整许可证文本见：[LICENSE.md](LICENSE.md)。

项目中的第三方依赖、基础镜像、字体、图标或其他资源，其版权与许可证仍归各自权利人所有；使用者需要分别遵守相关许可证。

Synology、DSM、Container Manager、File Station 等名称和商标归其各自权利人所有。本项目仅用于描述兼容的运行环境和功能，不代表官方产品关系。

---

## 二十二、免责声明

本项目属于开源社区软件，按“现状”提供，不对特定 NAS 型号、DSM 版本、文件系统、镜像格式或数据完整性作无条件保证。

特别是 RW 挂载属于高风险操作。使用者应在操作前做好数据备份，并自行确认镜像及目标文件系统适合写入。

作者 Michael 不对因软件使用、错误挂载、文件系统损坏、镜像损坏、权限配置错误、DSM 更新或其他环境变化导致的数据丢失承担责任。

---

## 项目作者

**Michael**

Virtual Drive Center 2.0.13

> ISO / IMG 磁盘挂载工具 for Synology Container Manager
