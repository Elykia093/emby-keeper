## What's Changed

1. 继承上游发布线至 `v7.6.2`，并合入后续发布流程修复。
2. 将运行、测试、Docker 与 Windows 安装基线统一到 Python 3.12。
3. 使用智谱 AI 接管智能问答与图片验证码识别，依赖范围为 `zai-sdk>=0.2.2`。
4. 更新月饼 Turnstile 签到流程，并补充 Kotomi、Mambo 与 Emby 保活回归覆盖。
5. Docker 镜像统一发布到 `elykia093/emby-keeper`，保留 Apprise Telegram Bot API 反代配置。

**Full Changelog**: https://github.com/Elykia093/emby-keeper/compare/v7.6.2...v7.6.3
