## What's Changed

1. 結束バンド签到支持 Turnstile 自动求解，按站点和账号隔离登录令牌缓存；查询或提交签到时令牌失效，会重新登录、复查状态并获取新的验证码，最多恢复一次。站点标识由 `mambo` 改为 `plusemby`。
2. 规范 AI 打码配置与结果来源：`[checkiner.ai]` 超时与提示词键统一为 `timeout` 与 `prompt`，识别结果与日志改为显示实际服务商，配置 `base_url` 指向第三方端点时不再标记为智谱。
3. 新增电子书库群组每日发言的人类验证处理：发言后守候随机抽查，仅响应本账号，在原验证期限内重试临时点击错误；后续发言失败时先处理已有验证，只有明确成功回执才判定通过。
4. Turnstile 求解仅保留 YesCaptcha，支持整体超时与取消，停止签到后不再继续轮询或创建后续求解任务；月饼同步接入异步求解。
5. Windows 脚本安装与更新改用本仓库 GitHub Release 的程序包，校验来源、版本和完整性，支持失败重试；Windows Python 3.12 使用 `TgCrypto-pyrofork==1.2.8`，并随 ZIP 提供预构建的 PyAES，避免用户机器编译依赖。ZIP 上传前会等待同版 Python 程序包就绪。
6. 终点站不再重放历史验证码，签到机会用尽或回答超时会明确报告失败；通知配置中的空反代地址可正常保存。

## 升级说明

- 将站点列表中的 `mambo`、`[checkiner.mambo]` 以及账号级同名配置改为 `plusemby`；移除已废弃的 `kotomi` 配置。
- 将 `[checkiner.ai]`、每个 `fallbacks` 后端及 AI 签到模板站点配置中的 `llm_timeout` / `llm_prompt` 改为 `timeout` / `prompt`。旧键不再生效，未配置新键时使用默认值。
- 月饼和結束バンド触发 Turnstile 时，需要配置 `[turnstile].yescaptcha_key` 或环境变量 `YESCAPTCHA_KEY`。`solver_url` / `SOLVER_URL` 不再使用，配置文件中的旧 `solver_url` 会被忽略。
- 登录缓存键已更新，旧缓存保留；首次使用新版本可能需要重新登录并建立新缓存。
- 本仓库不向上游 PyPI 项目发布版本，请使用 Docker 镜像或本 Release 的安装包、wheel / 源码包。升级前备份配置；如需退回 `v7.6.5`，同时恢复对应的旧配置键和站点标识。

**Full Changelog**: https://github.com/Elykia093/emby-keeper/compare/v7.6.5...v7.6.6
