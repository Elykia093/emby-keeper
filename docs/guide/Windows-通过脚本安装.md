# Windows 安装脚本安装

::: info 提示
推荐使用该方式安装, 方便后续更新.
:::

## 安装教程

您需要转到 [本仓库的 Release](https://github.com/Elykia093/emby-keeper/releases) 界面, 选择最新版本 (`Latest`), 然后展开 `Assets`, 点击下载 `embykeeper-win-vx.x.x.zip` 文件 (请注意**不是** `exe`!).

解压后运行 `Embykeeper.bat`, Embykeeper 将会自动安装到当前文件夹中.

首次安装使用压缩包对应的版本, 程序包从同一版本的 GitHub Release 下载, PyAES 依赖随压缩包提供, 其余依赖通过 Python 包源安装. 如果提示程序包尚未就绪, 请等待该版本的发布构建完成后重新运行脚本.

:::info 如果运行失败

如果您遇到了 `SSLEOFError` / `ConnectionError` 等问题, 请转用 `Embykeeper-NoMirror.bat`.

如果还是不行, 请检查您的网络环境, 或进行反馈.
:::

:::info 文件说明

`Embykeeper.bat`: 默认的启动文件, 支持命令行参数.
`Embykeeper-NoMirror.bat`: 如果需要下载, 则不使用镜像源.
`Embykeeper-Instant.bat`: 启动时立刻运行一次签到或保活, 相当于命令行参数 `-i`.

:::

安装后 Embykeeper 将首次运行并在当前目录下生成模板 `config.toml` 文件 (您也可以从[这里](https://github.com/Elykia093/emby-keeper/blob/main/config.example.toml)下载).

<!--@include: ./_简要配置.md-->

随后, 重新运行 `Embykeeper.bat`, 即可启动程序.

您将被询问设备验证码以登录, 登录成功后, Embykeeper 将首先执行一次签到和保活, 此后每日进行一次签到和保活.

恭喜您！您已经成功部署了 Embykeeper.

若您后续需要修改 `config.toml` 文件, 您需要结束程序并重新运行.

::: info 支持

<!--@include: ./_支持.md-->

:::

## 后台运行

您可以使用多种工具实现后台运行, 包括 [NSSM](https://nssm.cc/), [AHK](https://superuser.com/a/1106399) 等.

您可以自行探索, 但推荐新手用户前台运行, 以观察输出日志.

## 版本更新

当您需要更新版本时, 您需要关闭 Embykeeper, 然后运行 `Embykeeper.bat` 同一目录下的 `Update.bat`.

脚本会从本仓库最新的正式 Release 获取更新, 并检查版本与程序包完整性. 如果下载或安装失败, 修复网络问题或等待发布构建完成后, 可以重新运行更新脚本.

更新后, 重新运行 `Embykeeper.bat`.
