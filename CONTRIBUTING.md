# Contributing

欢迎提交 Issue 和 Pull Request。

提交代码前请至少执行：

```bash
python3 -m compileall -q app
```

如果修改了前端，请同步更新版本号/缓存参数，并补充变更说明。

涉及挂载、loop device、namespace 或权限的改动，请在 Pull Request 中说明测试环境和失败场景。
