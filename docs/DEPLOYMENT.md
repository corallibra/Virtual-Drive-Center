# 部署指南

## 1. Synology 目录建议

推荐：

```text
/volume1/docker/virtual-drive-app/      ← GitHub 项目源码
/volume1/docker/virtual-drive/           ← Virtual Drive 运行数据
```

运行目录会包含：

```text
virtual-drive/
├── images/
│   ├── iso/
│   └── img/
├── mounts/
├── data/
└── export/
```

## 2. 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TZ` | `Asia/Tokyo` | 容器时区 |
| `EXTERNAL_PORT` | `9109` | NAS Web 访问端口 |
| `PROJECT_ROOT` | `/volume1/docker/virtual-drive` | 运行数据目录 |
| `NAS_ROOT` | `/volume1` | 宿主机 NAS 根目录 |
| `NAS_IMPORT_ROOT` | `/volume1` | NAS 选择器初始目录 |
| `AUTO_RESTORE` | `true` | 容器重启后尝试恢复活动挂载 |
| `VD_USER` | `admin` | Web 用户名 |
| `VD_PASSWORD` | 空 | Web 密码；留空则首次启动随机生成 |

## 3. 使用 Container Manager

1. 把仓库文件放入 NAS 项目目录。
2. 创建 `.env` 并按 NAS 实际目录修改。
3. Container Manager → 项目 → 创建。
4. 使用 `compose.yml`。
5. 构建项目。
6. 启动容器。
7. 打开 `http://<NAS-IP>:<EXTERNAL_PORT>`。

## 4. NAS 内部选择器

将：

```dotenv
NAS_IMPORT_ROOT=/volume1/your-share/Downloads
```

修改为你自己的共享文件夹路径。例如：

```dotenv
NAS_IMPORT_ROOT=/volume1/media/images
```

应用通过宿主机 mount namespace 浏览该路径，而不是依赖浏览器本地文件选择器。

## 5. 电脑上传

“电脑上传”功能不会被 NAS 选择器替代。浏览器本地文件会上传到：

```text
<PROJECT_ROOT>/images/iso/
<PROJECT_ROOT>/images/img/
```

## 6. 删除与数据保留

从映像库移除一个由 NAS 外部路径引用的 ISO/IMG 时，仅移除索引，不删除原始 NAS 文件。

项目 `images/` 目录内由应用上传/管理的文件可以由应用删除。
