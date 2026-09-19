# Security Policy

## Supported versions

目前主要支持 `2.0.x` 系列，优先修复当前主线版本的安全问题。

## Reporting a vulnerability

请不要在公开 Issue 中提交可直接利用的安全漏洞、凭据或主机访问细节。

请通过 GitHub Security Advisories（如仓库启用）或维护者提供的私下联系方式报告。

报告中建议包含：

- Virtual Drive 版本
- Synology DSM / Container Manager 环境信息（避免包含个人路径和公网地址）
- 复现步骤
- 影响范围
- 必要的日志片段（请先删除用户名、IP、密码、token 和私有路径）

## Deployment security

该项目使用 `privileged: true` 和 `pid: host`，因此应按主机管理服务的权限等级进行部署。不要把管理端口直接暴露到公网。
