# Virtual Drive Center — 架构说明

作者：Michael

## 1. 核心目标

项目需要同时满足两个条件：

1. Web 可以管理 ISO / IMG。
2. 挂载结果必须出现在 Synology NAS 的真实文件系统中，以便 DSM File Station 继续访问。

## 2. 为什么普通 Docker mount 不足够

如果只在容器内部执行：

```text
mount image.img /mnt/image
```

挂载只属于该容器的 mount namespace，DSM 宿主机未必能够看到。

本项目因此采用：

```text
Container
   ↓
pid: host
   ↓
nsenter -t 1 -m
   ↓
Host mount namespace
```

## 3. 核心权限

```yaml
privileged: true
pid: host
```

这是当前实现的必要条件之一。

## 4. 挂载流程

### ISO

```text
ISO
 ↓
宿主机 namespace
 ↓
loop / filesystem
 ↓
RO mount
 ↓
/volume1/docker/virtual-drive/mounts/<id>
```

### IMG 整盘文件系统

```text
IMG
 ↓
识别文件系统
 ↓
loop mount
 ↓
挂载
```

### 分区 IMG

```text
IMG
 ↓
MBR/GPT
 ↓
loop --partscan
 ↓
/dev/loopNp1 / p2 / p3 ...
 ↓
blkid
 ↓
用户选择分区
 ↓
mount
```

## 5. NAS 文件选择器

NAS 文件选择并不依赖浏览器本地文件选择器。

```text
Browser
 ↓
/api/nas/browse
 ↓
宿主机 namespace
 ↓
/volume1
 ↓
返回目录与文件
```

电脑上传则是另一条流程：

```text
Browser local file
 ↓
HTTP upload
 ↓
images/
 ↓
Image Library
```

## 6. 为什么不使用 rshared

Synology 某些安装环境下：

```text
/volume1
```

并不是 Docker 所要求的 shared mount。使用：

```text
:rshared
```

可能导致容器创建失败。

因此项目不把 mount propagation 作为部署前提，而是把真正的 mount 动作放到宿主机 mount namespace。

## 7. File Station

成功挂载后，挂载目录位于真实 NAS 路径：

```text
/volume1/docker/virtual-drive/mounts/<mount-id>
```

于是 DSM File Station 可以直接定位该目录。

## 8. 重要限制

实际文件系统支持取决于：

- Synology DSM 内核
- CPU 架构
- 基础镜像
- `mount` 工具
- 文件系统辅助工具
- IMG 本身是否完整
- 文件系统是否损坏或加密

因此“支持的文件系统”应该理解为“当前 NAS 环境能够实际完成 mount 的文件系统”。
