# 故障排查

## 1. Web 页面无法访问

检查：

```bash
docker ps --filter name=virtual-drive
```

查看日志：

```bash
docker logs --tail 200 virtual-drive
```

确认浏览器访问：

```text
http://<NAS-IP>:<EXTERNAL_PORT>
```

## 2. NAS 选择器看不到文件

进入容器终端后，先验证宿主机 namespace：

```bash
nsenter -t 1 -m -- ls -la /volume1
nsenter -t 1 -m -- ls -la /volume1/your-share/Downloads
```

如果这里能看到文件，说明 host namespace 路径正常；继续查看 Web API 日志。

确认 `.env`：

```dotenv
NAS_ROOT=/volume1
NAS_IMPORT_ROOT=/volume1/your-share/Downloads
```

## 3. 不要使用 `:rshared`

本项目不要求：

```yaml
- /volume1/...:/volume1/...:rshared
```

在某些 Synology 环境中会导致：

```text
path ... is mounted on /volume1 but it is not a shared mount
```

## 4. IMG 被识别为未知

对目标 IMG 执行：

```bash
nsenter -t 1 -m -- file -sL /path/to/image.img
nsenter -t 1 -m -- blkid -p -o full /path/to/image.img
nsenter -t 1 -m -- sfdisk -J /path/to/image.img
```

然后测试 loop/partition：

```bash
nsenter -t 1 -m -- losetup --find --show --partscan --read-only /path/to/image.img
```

检查：

```bash
ls -la /sys/class/block/loopNp*
```

以及：

```bash
nsenter -t 1 -m -- blkid /dev/loopNp1
```

## 5. `lsblk` 在容器中不可执行

这在部分 Synology + `nsenter` 场景中并不一定意味着 loop 分区不存在。项目优先读取：

```text
/sys/class/block
```

并使用 `blkid` 探测分区。

## 6. mount 返回 exit status 32

不要只看退出码，查看应用返回的完整 `mount` stderr。常见原因包括：

- 把整块分区镜像误当作文件系统挂载
- 文件系统不受支持
- NTFS dirty/incomplete shutdown
- 文件系统损坏
- 缺少相应用户态 helper
- IMG 分区设备选择错误

## 7. Docker/Container Manager 更新后仍是旧版本

确认镜像重新构建，而不是仅重启旧容器。建议：

```bash
docker compose build --no-cache virtual-drive
docker compose up -d --force-recreate
```

然后访问：

```text
/api/version
```

应返回当前 `APP_VERSION`。
