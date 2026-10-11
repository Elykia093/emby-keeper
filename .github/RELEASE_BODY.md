## What's Changed

1. 优化签到器进度消息识别：纯“签到中”“正在处理”等进度提示会静默等待后续结果，避免触发不必要的 AI 调用；带结果关键词的复合消息仍按原逻辑处理。
2. 修复結束バンド签到结果归类：提交响应为 HTTP 2xx 且 `success=true` 时计为本次成功；单项日志区分签到前已完成与提交时重复签到。

## 升级说明

- 无需修改现有配置；回退到 `v7.6.6` 无需额外配置迁移。
- 本仓库不向上游 PyPI 项目发布版本，请使用 Docker 镜像或本 Release 的安装包、wheel / 源码包。

**Full Changelog**: https://github.com/Elykia093/emby-keeper/compare/v7.6.6...v7.6.7
