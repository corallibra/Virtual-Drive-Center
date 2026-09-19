# GitHub 发布指南

## 1. 发布前检查

确保仓库中不存在以下内容：

- `.env` 或其他本地配置
- 管理员密码、API token、SSH 私钥
- SQLite 数据库和运行日志
- 私有 NAS 用户名、私有 IP、个人目录名
- 私有 ISO/IMG 或其他大型测试文件

建议在发布前对整个工作目录做一次人工隐私审查，并确认 `.gitignore` 与 `.dockerignore` 已生效。

仓库中提供了 CI 工作流，用于执行 Python 编译检查和基本的敏感值扫描。

## 2. 建议的首次公开仓库

建议仓库名：

```text
virtual-drive-center
```

建议仓库描述：

```text
Web-based ISO/IMG mounting tool for Synology Container Manager with DSM File Station integration.
```

## 3. Git 初始化

```bash
git init
git add .
git commit -m "Release Virtual Drive Center 2.0.13"
git branch -M main
```

创建 GitHub 空仓库后：

```bash
git remote add origin git@github.com:OWNER/REPOSITORY.git
git push -u origin main
```

或者使用 HTTPS remote。

## 4. 建议 GitHub 仓库设置

公开仓库发布后建议开启 Dependabot alerts、secret scanning / push protection，以及 code scanning；同时保留 `SECURITY.md` 并明确漏洞报告方式。

## 5. 创建 Release

```bash
git tag -a v2.0.13 -m "Virtual Drive Center 2.0.13"
git push origin v2.0.13
```

然后在 GitHub → Releases → New release，选择 `v2.0.13` 标签，并上传发布压缩包。

## 6. 不要把大型 ISO/IMG 放进 Git 仓库

代码仓库只发布软件。测试镜像和大型二进制文件应留在独立存储中；GitHub 对仓库大文件有相应限制。
