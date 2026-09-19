# Architecture

## Why host mount namespace?

A normal Docker mount is isolated in the container mount namespace. For this project the desired behavior is different: after mounting an IMG/ISO, DSM File Station should see the mount at a real `/volume1/...` path.

The project therefore uses:

```text
privileged: true
pid: host
```

and invokes host commands through:

```text
nsenter -t 1 -m -- <command>
```

This avoids requiring `/volume1` itself to be a shared mount. In particular, the project does **not** require `:rshared` on the main `/volume1` bind mount.

## Data paths

Application data is bind-mounted at `PROJECT_ROOT`.

The NAS image picker accepts host-style paths under `NAS_ROOT`. The backend validates paths and executes NAS filesystem operations through the host mount namespace.

## Image inspection

For IMG files the inspection order is:

1. Probe the whole image for a filesystem signature.
2. If no whole-image filesystem is found, attach a read-only loop device with partition scanning.
3. Prefer `/sys/class/block/loopNpX` on Synology where possible.
4. Fall back to `sfdisk` partition information.
5. Probe partition filesystems using `blkid` or temporary offset loops.

## Mounting

- ISO: read-only loop mount.
- Whole-image IMG: mount the image as a filesystem if a supported filesystem is detected.
- Partitioned IMG: mount the selected partition device or a temporary offset loop when required.
- NTFS RW: try `ntfs3`, then fall back to `ntfs-3g`.

## Important security boundary

Because host namespace and block-device operations are required, the container is intentionally privileged. This is a deliberate trade-off for DSM File Station integration and should be treated as a host-administration service, not as an untrusted multi-tenant web app.
