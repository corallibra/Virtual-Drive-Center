# Virtual Drive Center 2.0.13 — 部署指南

作者：Michael  
目标平台：Synology NAS + DSM + Container Manager

## 1. 部署目标

本指南用于将 Virtual Drive Center 部署到 Synology NAS，并实现：

- Web 管理访问
- 从 NAS 内部选择 ISO / IMG
- 从电脑上传 ISO / IMG
- ISO 只读挂载
- IMG 多分区识别与选择
- 挂载后从 DSM File Station 访问

## 2. 推荐目录

项目源码：

```text
/volume1/docker/virtual-drive-app/
```

运行数据：

```text
/volume1/docker/virtual-drive/
```

创建数据目录：

```bash
mkdir -p /volume1/docker/virtual-drive/images/iso
mkdir -p /volume1/docker/virtual-drive/images/img
mkdir -p /volume1/docker/virtual-drive/mounts
mkdir -p /volume1/docker/virtual-drive/data
mkdir -p /volume1/docker/virtual-drive/export
```

## 3. 配置

建议复制：

```bash
cp .env.example .env
```

示例：

```dotenv
PROJECT_ROOT=/volume1/docker/virtual-drive
NAS_ROOT=/volume1
NAS_IMPORT_ROOT=/volume1/homes/<your-user>/Downloads
EXTERNAL_PORT=9109
VD_USER=admin
VD_PASSWORD=CHANGE-ME
```

请将 `<your-user>` 替换为自己的 DSM 用户目录。

## 4. Container Manager

1. 打开 Container Manager。
2. 创建项目。
3. 选择仓库项目目录。
4. 使用 `compose.yml`。
5. 检查端口与环境变量。
6. 构建项目。
7. 启动项目。
8. 查看日志。

## 5. SSH 部署

```bash
cd /volume1/docker/virtual-drive-app
docker compose up -d --build
docker compose ps
docker compose logs -f virtual-drive
```

## 6. 端口

如果 Compose 使用：

```yaml
ports:
  - "9109:8099"
```

浏览器访问：

```text
http://<NAS-IP>:9109
```

## 7. 首次验证

先测试 NAS 浏览：

```text
导入映像 → NAS 内部选择
```

确认能够进入：

```text
/volume1/homes/<your-user>/Downloads
```

再选择一个较小的 ISO 进行第一次挂载测试。

## 8. IMG 测试

确认 ISO 工作正常后，再使用 IMG：

```text
导入 → NAS 内部选择 → IMG → 检查 → 选择分区 → 挂载
```

建议第一次优先测试 RO 模式。

## 9. DSM File Station 验证

挂载成功后，记录页面提供的真实路径，例如：

```text
/volume1/docker/virtual-drive/mounts/example-123456
```

然后使用 DSM File Station 打开：

```text
/docker/virtual-drive/mounts/example-123456
```

## 10. 更新

保留数据目录：

```text
/volume1/docker/virtual-drive/
```

源码更新后重新构建：

```bash
docker compose build --no-cache
docker compose up -d
```

## 11. 升级注意事项

升级前：

1. 卸载所有活动镜像。
2. 确认没有文件写入。
3. 备份 `data/`。
4. 再重新构建。

## 12. 安全

当前方案使用：

```yaml
privileged: true
pid: host
```

请只在可信环境使用，不建议直接暴露公网。
