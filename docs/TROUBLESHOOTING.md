# Virtual Drive Center — 故障排查

作者：Michael

## 1. 容器无法启动：not a shared mount

错误：

```text
path /volume1/docker/virtual-drive is mounted on /volume1 but it is not a shared mount
```

处理：

- 检查 Compose 是否有 `:rshared`。
- 当前方案不要使用 `rshared`。
- 使用普通 `rw` bind mount，并依靠 host mount namespace 执行挂载。

## 2. NAS 浏览为空

容器内测试：

```bash
nsenter -t 1 -m -- ls -la /volume1
```

然后：

```bash
nsenter -t 1 -m -- ls -la /volume1/homes
```

以及实际默认目录：

```bash
nsenter -t 1 -m -- ls -la /volume1/homes/<user>/Downloads
```

如果这里可以看到文件，而 Web 不能显示，优先检查 NAS 浏览 API 和应用日志。

## 3. `docker` 不存在

如果终端提示：

```text
docker: command not found
```

而提示符类似：

```text
root@container:/opt/virtual-drive#
```

说明你已经在容器中，不需要从容器里运行 `docker exec`。

## 4. `lsblk` 不存在

`nsenter` 只改变 namespace，不会自动让容器获得宿主机命令文件。

检查：

```bash
which lsblk
```

或者：

```bash
ls -la /proc/1/root/usr/bin/lsblk
```

如果不存在，可使用 `/sys/class/block` 和 `blkid` 做分区状态诊断。

## 5. 检查 IMG

```bash
nsenter -t 1 -m -- file -sL /volume1/path/to/test.img
```

```bash
nsenter -t 1 -m -- blkid -p -o full /volume1/path/to/test.img
```

```bash
nsenter -t 1 -m -- sfdisk -J /volume1/path/to/test.img
```

## 6. 建立 loop

```bash
nsenter -t 1 -m -- losetup --find --show --partscan --read-only /volume1/path/to/test.img
```

如果返回：

```text
/dev/loop1
```

检查：

```bash
nsenter -t 1 -m -- sh -c 'ls -la /dev/loop1*'
```

## 7. 查看 filesystem

```bash
nsenter -t 1 -m -- sh -c 'for x in /dev/loop1 /dev/loop1p*; do [ -e "$x" ] || continue; echo "=== $x ==="; blkid "$x" 2>&1 || true; done'
```

## 8. mount exit status 32

不要仅凭 `32` 判断原因。获取实际 stderr。

常见方向：

- 错误的设备节点
- 错误的文件系统类型
- 文件系统损坏
- 缺少 filesystem helper
- 权限问题
- IMG 并不是普通可挂载格式

## 9. SQLite binding error

例如：

```text
Incorrect number of bindings supplied.
The current statement uses 4, and there are 5 supplied.
```

这是 SQL 占位符与参数数量不一致。重点检查挂载状态更新 SQL。

## 10. 页面卡在“正在读取映像库”

检查：

1. 浏览器 Console 是否有 JavaScript 异常。
2. API 是否返回错误。
3. 容器日志是否正常。
4. 页面版本号是否与当前构建一致。
5. 是否是浏览器缓存。

## 11. 版本号未变化

重新 Build：

```bash
docker compose build --no-cache
```

然后：

```bash
docker compose up -d
```

浏览器执行强制刷新，并检查 HTML、JS/CSS 版本参数。
