# Changelog

## 2.0.13 - 2026-09-19

- 修复挂载成功后写入 SQLite 状态时的参数绑定错误。
- 修复数据库写入失败后可能残留真实宿主机挂载的问题。
- 多分区 IMG 优先使用 Synology 可见的 `/sys/class/block/loopNpX`。
- 通过 `blkid` 补充 NTFS / FAT32 / exFAT / EXT 等文件系统识别。
- 支持多分区 IMG 手工选择。
- NAS 内部镜像选择与电脑上传并存。
- 挂载成功后显示真实 NAS / DSM File Station 路径。
- 大容量 IMG 检查与挂载采用异步任务和进度展示。
- 前端静态资源增加版本缓存清理。

## Earlier 2.0.x milestones

The 2.0 series progressively added NAS-side image selection, host mount namespace integration, multi-partition IMG handling, checksum jobs, mount history, usage display, and the web file manager.
