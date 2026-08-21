# Embykeeper

Embykeeper 是一个基于 Python asyncio 的自动化工具，负责 Telegram 机器人签到、群组监控与发言、账号注册，以及 Emby / Subsonic 定时保活。仓库同时包含命令行程序、内嵌 FastAPI、独立面板 API、旧版 Flask 控制台和 Vue 3 管理面板。

本文件是维护者和编码 Agent 的唯一完整指南。`CLAUDE.md` 只保留 `@AGENTS.md`，让 Claude Code 自动加载本文件；不要在两处复制规则。若子目录以后增加更具体的 `AGENTS.md`，以离改动文件最近的规范为准。

## 工作规程

- 开始和结束时运行 `git status --short --branch`。已有修改和未跟踪文件默认属于用户，不覆盖、不删除、不格式化、不暂存。
- 修改前阅读真实实现、配置、测试和工作流，并用 `rg` 搜索定义、调用方、序列化、文档及前后端消费者。
- 先复现并定位根因，再做最小修改。同一方案连续无效时停止叠加补丁，重新检查假设和证据。
- 只写代码无法直接表达的注释，例如并发时序、生命周期约束、安全边界和兼容原因；不复述下一行代码，不记录版本沿革或外部参考来源。
- 完成后至少执行 `git diff --check` 和与改动匹配的测试或构建。未运行的检查不得写成“已通过”。
- 除非用户在当前请求中明确授权，不执行 `git add`、commit、push、merge、rebase、创建或移动 tag、创建 Release、触发发布工作流。
- 获得提交授权后也只精确暂存目标路径，不使用 `git add .` 或 `git add -A`，并先检查 `git diff --cached`。

## 技术栈与真源

- Python 支持范围以 `pyproject.toml` 为准，当前为 `>=3.12,<3.13`；tox 和 CI 使用 Python 3.12。
- 生产依赖以 `requirements.txt` 为准，开发依赖以 `requirements_dev.txt` 为准，包入口和 Black 配置以 `pyproject.toml` 为准。Black 行宽为 110。
- 配置模型、默认值、旧字段兼容和校验规则的真源是 `embykeeper/schema.py`；加载、热更新和示例配置生成逻辑在 `embykeeper/config.py`。
- 项目版本必须同时核对 `pyproject.toml` 和 `embykeeper/__init__.py`。Docker 精确 Python 版本看 `Dockerfile` / `Dockerfile.dev`，Windows Python 版本看 `installer.cfg` 和 `windows/installer-script/`，不要从文档反推版本。
- 前端栈为 Vue 3 + TypeScript + Vite + Pinia + Tailwind，依赖与命令以 `frontend/package.json` 为准。文档站为 VitePress，命令以根目录 `package.json` 为准。
- 发布行为只以 `.github/workflows/` 当前内容为准。`.bumpversion.cfg`、工作流默认输入、固定镜像 Dockerfile 可能落后于当前版本，使用前必须逐项对齐。
- `Makefile` 包含历史环境逻辑，并且 `make lint` 会先运行 Black 直接改写文件；只检查格式时使用 `python -m black --check .`。不要把 `make develop` 的环境选择逻辑当作当前 Python 支持范围。

## 代码地图

```text
embykeeper/
├── cli.py                 Typer CLI、事件循环、模块启动和退出收口
├── config.py              TOML / EK_CONFIG 加载、热更新和回调
├── schema.py              Pydantic 配置模型与旧字段兼容
├── schedule.py            周期任务调度与 RunContext 状态收口
├── runinfo.py             运行记录和状态
├── telegram/
│   ├── session.py         Telegram 客户端池、登录和引用计数
│   ├── pyrogram.py        Pyrogram 修复、扩展和生命周期
│   ├── dynamic.py         签到器/监控器/水群器/注册器动态发现
│   ├── *_main.py          各 Telegram 模块的任务管理
│   └── {checkiner,monitor,messager,registrar}/
├── emby/                  Emby API、播放模拟和任务管理
├── subsonic/              Subsonic API、播放和任务管理
└── api/                   随核心进程启动的业务 FastAPI
embykeeperapi/             独立面板 API、认证、进程管理、SSE 和反向代理
embykeeperweb/             旧版 Flask 控制台，仍是已发布入口
frontend/                  Vue 3 管理面板
tests/                     pytest 回归测试
docs/                      VitePress 用户文档
.github/workflows/         CI、发布、镜像、Windows 制品和文档部署
```

主要运行关系：

```text
CLI -> ConfigManager -> Telegram / Emby / Subsonic managers -> Scheduler -> RunContext

Vue frontend -> embykeeperapi (auth/process/proxy/SSE)
             -> managed Embykeeper process -> embykeeper/api
```

`embykeeper/api` 与 `embykeeperapi` 不是同一个服务；`embykeeperweb` 也不是 Vue 面板。修改路由、认证、进程状态或配置接口前，先确认目标入口和消费方，不能只改其中一层。

## 核心约束

### 配置与热更新

- `ConfigModel` 默认拒绝未知字段；签到器、监控器、水群器和注册器配置允许站点自定义键。不要为了兼容一个站点而全局放宽校验。
- 旧配置字段迁移集中在 `Config.handle_aliases`。重命名字段时保留明确的兼容路径，并补充新旧格式测试。
- `ConfigManager` 先替换内存配置，再触发 `on_change` / `on_list_change`。新增可热更新配置必须检查实际消费者是否注册回调、旧任务是否取消、新任务是否只启动一次。
- 代理变化会影响 Telegram、Emby 和 Subsonic；只重启真实受影响的模块，不能因任意配置保存而全量重启。
- 配置变化同步检查 `schema.py`、`config.py`、CLI、业务 API、前端类型与页面、`config.example.toml`、README、docs 和测试。
- `config.example.toml` 由程序生成。注意 `make config/generate` 不只是生成文件，它还会执行 `git add` 和 commit，未经提交授权不得运行。

### asyncio 与任务生命周期

- `embykeeper/cli.py` 拥有主事件循环：先执行 `var.exit_handlers`，再取消剩余任务并关闭异步生成器。长期后台服务必须有明确所有者和退出路径。
- 新建 `asyncio.create_task` 后必须保存引用、注册清理或确保任务短期自收口；不得留下 “Task exception was never retrieved”。
- `asyncio.CancelledError` 必须按取消语义传播，不能被宽泛 `except Exception` 当作普通网络错误吞掉。
- `Scheduler.schedule()` 负责区分任务内部取消与外部取消，并更新 `RunContext`。修改调度时保持状态、缓存的下次运行时间和取消结果一致。
- 停止、重启、热更新可能并发到达。客户端和管理器的 `start` / `stop` / `restart` 应幂等或串行，禁止停止过程中再次启动已关闭的 session。

### Telegram 客户端池

- `ClientsSession.pool`、`lock` 和 `watch` 是类级共享状态。上下文进入增加引用，退出只降低引用；真正清理只能在引用归零、看门狗超时或强制关闭时发生。
- 清理顺序为：从池移除、等待 `stop_handlers`、停止 Client、删除临时 storage。改变顺序可能产生关闭后的数据库访问或残留监听。
- 首次登录由 Telethon 获取 session，再交给 Pyrogram；已有 session 可能来自配置、缓存或旧登录文件迁移。不要在日志、异常或测试快照中输出 session 字符串、API hash、验证码或两步验证密码。
- 修改 `embykeeper/telegram/pyrogram.py` 前先核对当前 Pyrogram 版本的上游签名和 session 生命周期。重连、停止和 update difference 异常必须覆盖并发回归测试。
- 网络超时可以降级为可诊断警告，但鉴权失效、session 注销和数据库生命周期错误不能一律当作普通断网忽略。

### 动态站点模块

- `telegram/dynamic.py` 通过模块文件名发现服务，并按 `<name><suffix>` 匹配类：`foo.py` 对应 `FooCheckin`、`FooMonitor`、`FooMessager` 或 `FooRegistrar`。
- 基类和模板文件以下划线开头。`__ignore__ = True` 表示默认列表不启用；`test*` 模块不会被 `all` 自动纳入。不要通过手工维护中心注册表绕过动态发现。
- 简单站点优先复用 `_templ_*` 或对应 `_base.py`；只有协议、验证码、WebApp 或状态判断确实不同才增加定制流程。
- 第三方响应必须要求明确成功证据。任意 2xx、未知 409、包含“签到”字样或存在正向字段都不能自动等同成功或已签到。
- 登录页或 API 被 Cloudflare / 安全验证拦截时，不继续提交用户凭据。Turnstile 求解只使用配置的 solver / YesCaptcha，并为挑战、失败切换和返回结构补测试。
- 新增或调整站点后检查 README 支持列表、示例配置、站点文档和 `tests/`；复杂状态机、认证和外部 HTTP 流程必须使用 fake/mocks，不连接真实账号。

### Emby 与 Subsonic

- Emby 播放流程中的 `PlaybackStartTimeTicks` 在 start、progress、stop 上报间保持稳定，使用真实 `UserId`，结束上报走 `/Sessions/Playing/Stopped`。
- 播放数没有即时递增不能单独判定保活失败；真正成功条件由 session 启动、进度和停止上报共同决定。
- 登录但不播放、播放时长封顶、无媒体源、停止上报和初始化异常已有回归测试，修改播放逻辑时同步扩展 `tests/test_emby_playback.py`。
- HTTP 流和播放器资源必须在取消、异常和正常结束时关闭。不要把整段媒体读入内存，也不要用无上限后台读取掩盖连接问题。
- Emby 与 Subsonic 的账号级 `enabled`、代理、并发、时间范围和间隔可触发运行时任务变化；修改 manager 时检查增删账号、配置热更新和正在运行任务的收口。

### API、认证与前端

- `embykeeper/api` 暴露核心业务状态和操作；`embykeeperapi` 管理后端进程并代理 `/api/*`。新增接口需同步检查两层路由、代理方法、状态码和前端调用。
- 面板同时支持 cookie 与 Bearer token。认证失败必须保持 401 语义，不能为了开发便利绕过 `require_auth` 或让 SSE/代理成为无鉴权旁路。
- 反向代理必须过滤 hop-by-hop、host 和 content-length 头；SSE 断开时必须关闭上游 response 与 httpx client。
- `frontend/src/composables/useSSE.ts` 负责 AbortController、指数退避和单一重连计时器。修改 SSE 时检查卸载、手动退出、401、半包、多事件和重复连接。
- 前端字段变化同步更新 `frontend/src/types/`、store/composable、页面和后端响应。用户可见错误应保留可理解信息，日志不得泄露密码、token、cookie 或配置全文。
- 修改控制台前先确认是否需要兼容 `embykeeperweb` 旧版 Flask 入口；若只支持新 Vue 面板，应在变更说明中明确。

## 本分支更新记录

README 顶部 `## 本分支更新记录` 是面向用户的变更日志，不是 commit 流水账。每项可交付更新完成并经过必要检查后再记录。

- 已有条目视为历史记录，不删除、不改写、不重新排序；新条目只能追加到现有列表末尾。
- 一条只写一个主题，表达为“动作 + 功能或模块 + 具体变化 + 用户影响或兼容说明”。
- 动词优先使用“新增”“修复”“优化”“调整”“升级”“移除”，避免“相关更新”“改了一下”等模糊表述。
- 同一功能涉及代码、配置、文档和回归测试时尽量合并；除非测试设施本身是交付内容，否则不单独记录“增加测试”。
- 重点写最终行为和用户可感知结果，不写函数名、内部重构过程、代码来源、尝试过的方案或提交数量。
- 配置键、站点名、API、镜像名、依赖和 Python 小版本必须与当前仓库证据一致。
- 版本对比写明实际基线，例如“相比 v7.6.3”；不写“相比上个版本”，不把 Python 3.12 写成“Python 12”。
- 发布流程变化说明触发方式、构建产物和发布目标；依赖升级仅在影响功能、安装或兼容性时记录。
- 尚未完成、未经验证、计划中或仅存在于本地工作区的变化不得提前写入。

统一模板：

```markdown
- <新增/修复/优化/调整/升级/移除> <功能或模块>：<具体变化>，<用户影响或兼容说明>。
```

## 验证

按风险从最小相关检查开始，再扩大范围：

```bash
python -m pytest tests/<相关测试文件>.py
python -m pytest
tox
python -m black --check .
python -m pre_commit run --all-files
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm run docs:build
```

- 仅修改 Markdown 时检查内容、路径、版本事实、行尾和 pre-commit，不要求运行无关的 Python 全套测试。
- 修改 Python 逻辑时至少运行相关 pytest 和 Black；共享生命周期、调度、配置、认证或 API 变化尽量运行完整 pytest / tox。
- 修改前端时运行 typecheck 和 build；修改文档站时运行 docs build。
- 修改 Docker 或工作流时核对 YAML、触发条件、权限、目标 ref、镜像 tag 和制品来源。能本地构建时再做对应构建。
- 检查失败时报告准确命令和首个有效错误。环境限制导致无法运行时明确写“未验证”及原因。

## 版本与发布

发布是外部可见操作，只有用户明确批准具体版本、目标仓库和动作后才能执行。

发布前至少核对：

1. 目标提交已位于预期分支，工作区和暂存区只包含本次发布内容。
2. `pyproject.toml`、`embykeeper/__init__.py`、`installer.cfg`、Windows requirements、发布说明和工作流默认 tag 一致。
3. `Dockerfile`、`Dockerfile.dev`、`deploy/Dockerfile`、`hf/Dockerfile` 中需要固定的 Python 或镜像版本已逐项确认。
4. `.bumpversion.cfg` 的 `current_version`、搜索文本和文件映射与当前仓库一致。
5. README 新增记录和 `.github/RELEASE_BODY.md` 的 compare 链接使用正确的上一版本和新版本。
6. 测试、Black、构建和 GitHub Actions 结果已检查；新 tag 尚不存在并将指向预期提交。

不要在未审阅和未授权时运行 `make version*`：这些目标会调用 bumpversion、生成配置、commit、打 tag 并 push。`make config/generate` 本身也会 commit。

当前发布链路：

- 推送 `v*` tag 创建或更新草稿 Release。
- Release 进入 `released` 状态后触发正式 Docker、`-dev` Docker、Windows 制品、PyPI 构建和 stable 分支更新。
- 正式与开发镜像发布到 `elykia093/emby-keeper`，开发镜像使用 `-dev` 后缀。
- fork 可以构建并上传 GitHub Release 制品，但实际 PyPI 发布仅允许 `emby-keeper/emby-keeper`。
- `main` 上的 `docs/**`、`README.md` 或文档工作流变化触发 GitHub Pages 部署。
- 手动运行发布工作流时，所选 Git ref、输入 tag 和该 ref 内版本必须一致，避免把错误提交发布到同名标签。

已发布 tag 视为不可变。发布后发现问题应增加修订版本，例如从 `v7.6.3` 发布 `v7.6.4`，不能移动或覆盖旧 tag。

## 完成检查

- [ ] 初始与最终 Git 状态已核对，用户已有改动未被触碰。
- [ ] 相关定义、调用方、配置、接口、文档和测试已搜索。
- [ ] 改动保持最小，没有混入无关格式化、依赖升级或生成物。
- [ ] 已执行与风险匹配的测试、格式和构建检查。
- [ ] 敏感信息未进入代码、测试、日志、diff 或提交历史。
- [ ] 最终报告列出实际改动、实际验证、未执行项和剩余风险。
