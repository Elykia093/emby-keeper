## What's Changed

1. 修复 Telegram 客户端 session 生命周期竞争问题，停止期间不再重启已关闭的 session。
2. 处理 `updates.GetChannelDifference` 超时，避免后台更新任务产生未处理异常。
3. 同步 Docker 部署文档与 `elykia093/emby-keeper` 镜像命名，并补充仓库维护规范文档。

**Full Changelog**: https://github.com/Elykia093/emby-keeper/compare/v7.6.3...v7.6.4
