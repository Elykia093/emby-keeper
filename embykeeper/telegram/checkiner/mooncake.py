import asyncio
from urllib.parse import parse_qs, urlparse

from curl_cffi.requests import AsyncSession, RequestsError
from pyrogram.types import Message, InlineKeyboardMarkup
from pyrogram.raw.functions.messages import RequestWebView

from embykeeper.config import config
from embykeeper.runinfo import RunStatus
from embykeeper.utils import to_iterable, truncate_str, get_proxy_str, show_exception

from ._templ_a import TemplateACheckin

from embykeeper.turnstile import TurnstileService


class MooncakeCheckin(TemplateACheckin):
    name = "月饼"
    bot_username = "Moonkkbot"
    bot_use_captcha = False
    bot_checkin_cmd = "/start"
    templ_panel_keywords = ["用户面板", "请选择下方功能"]
    bot_text_ignore = ["用户面板", "请选择下方功能", "账号概览", "最近签到"]
    max_retries = 1
    # Turnstile 求解约 2 分钟; 整体时限略长一点
    default_timeout = 150

    # 月饼改版后, 签到由 embyguard 服务端完成, 客户端仅提交 Telegram WebApp 数据.
    # 流程: POST /telegram/checkin (init_data) → 若需 Turnstile 则本地求解 token
    # → POST /telegram/checkin/{challenge} (init_data + turnstile_token)
    api_base = "https://embyguard.com/api/v1"

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if not self._timeout or self._timeout < self.default_timeout:
            self._timeout = self.default_timeout
        self._panel_lock = asyncio.Lock()
        self._checkin_started = False

    def _is_panel(self, text: str) -> bool:
        if not text:
            return False
        return any(keyword in text for keyword in to_iterable(self.templ_panel_keywords))

    def _iter_inline_buttons(self, message: Message):
        rm = message.reply_markup
        if not isinstance(rm, InlineKeyboardMarkup):
            return []
        return [k for r in rm.inline_keyboard for k in r]

    def _find_checkin_webapp_url(self, message: Message):
        for k in self._iter_inline_buttons(message):
            text = k.text or ""
            if "签到" not in text and "簽到" not in text:
                continue
            if k.web_app and k.web_app.url:
                return k.web_app.url
            if k.url:
                return k.url
        return None

    async def _resolve_panel_message(self, message: Message) -> Message:
        if self._find_checkin_webapp_url(message):
            return message
        try:
            async for m in self.client.get_chat_history(self.bot_username, limit=8):
                text = m.caption or m.text or ""
                if self._is_panel(text) and self._find_checkin_webapp_url(m):
                    self.log.debug(f"从历史消息 {m.id} 找回带签到按钮的面板.")
                    return m
        except Exception as e:
            self.log.debug(f"读取历史面板失败: {e}")
            show_exception(e)
        return message

    async def message_handler(self, client, message: Message):
        text = message.caption or message.text or ""
        rm = message.reply_markup

        # ReplyKeyboardRemove 等中间消息: 只在 debug 里记一笔, 默认不刷屏
        if rm and not isinstance(rm, InlineKeyboardMarkup):
            self.log.debug(f"忽略非行内键盘: {type(rm).__name__}")
            return

        if not self._is_panel(text):
            if getattr(message, "is_first_response", False) and isinstance(rm, InlineKeyboardMarkup):
                if self._find_checkin_webapp_url(message):
                    return await self._handle_panel(message)
            await super().message_handler(client, message)
            return

        async with self._panel_lock:
            if self._checkin_started or self.finished.is_set():
                self.log.debug("签到已在进行/已结束, 忽略重复面板.")
                return

            buttons = self._iter_inline_buttons(message)
            self.log.debug(
                f"收到面板: reply_markup={type(rm).__name__ if rm else None}, 按钮数={len(buttons)}"
            )
            for b in buttons:
                self.log.debug(
                    f"  按钮 text={b.text!r} web_app={getattr(b.web_app, 'url', None)!r} url={b.url!r}"
                )

            message = await self._resolve_panel_message(message)
            if not self._find_checkin_webapp_url(message):
                self.log.debug("当前面板无签到按钮, 继续等待.")
                return

            self._checkin_started = True
            self.log.info("开始 WebApp 签到.")
            return await self._handle_panel(message)

    async def _handle_panel(self, message: Message):
        url = self._find_checkin_webapp_url(message)
        if not url:
            self.log.warning("签到失败: 未找到签到 WebApp 按钮.")
            return await self.fail()

        self.log.debug(f"签到 WebApp URL: {url}")
        try:
            bot_peer = await self.client.resolve_peer(self.bot_username)
            url_auth = (
                await self.client.invoke(RequestWebView(peer=bot_peer, bot=bot_peer, platform="ios", url=url))
            ).url
        except Exception as e:
            self.log.warning(f"签到失败: 无法打开 WebApp ({e.__class__.__name__}: {e}).")
            show_exception(e)
            self._checkin_started = False
            return await self.retry()

        init_data = parse_qs(urlparse(url_auth).fragment).get("tgWebAppData", [None])[0]
        server = parse_qs(urlparse(url).query).get("server", [None])[0]
        if not server:
            server = parse_qs(urlparse(url_auth).query).get("server", [None])[0]
        self.log.debug(f"WebApp 凭据: server={server!r}, init_data_len={len(init_data) if init_data else 0}")
        if not init_data or not server:
            self.log.warning("签到失败: 无法获取 WebApp 数据或 server 参数.")
            return await self.fail()

        return await self.do_checkin(server, init_data, url)

    def _unwrap_result(self, result):
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        if isinstance(data, dict) and ("status" in data or "site_key" in data or "challenge" in data):
            return data
        return result

    def _turnstile_service(self) -> TurnstileService:
        """从 config.toml [turnstile] / 环境变量构造求解器.
        solver_url 支持逗号分隔多个地址, 失败自动换下一个.
        """
        t = getattr(config, "turnstile", None)
        return TurnstileService(
            solver_url=(getattr(t, "solver_url", None) or "") if t else "",
            yescaptcha_key=(getattr(t, "yescaptcha_key", None) or "") if t else "",
        )

    async def _solve_turnstile(
        self,
        website_url: str,
        website_key: str,
        action: str = "",
        cdata: str = "",
    ) -> str | None:
        """同步 TurnstileService 放到线程池, 避免阻塞事件循环.

        embyguard 前端用 siteKey + action + cdata 渲染 widget,
        求解时必须带上相同参数, 否则服务端 invalid_turnstile.
        """
        try:
            svc = self._turnstile_service()
            self.log.debug(
                f"Turnstile solvers: {svc.solver_urls}"
                + (f", yescaptcha={'on' if svc.yescaptcha_key else 'off'}")
            )
            return await asyncio.to_thread(
                svc.solve_turnstile,
                website_url,
                website_key,
                action=action or "",
                cdata=cdata or "",
            )
        except Exception as e:
            self.log.warning(f"Turnstile 求解失败: {e.__class__.__name__}: {e}")
            show_exception(e)
            return None

    async def do_checkin(self, server: str, init_data: str, webview_url: str):
        api = f"{self.api_base}/servers/{server}"
        origin = f"{urlparse(webview_url).scheme}://{urlparse(webview_url).netloc}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": webview_url,
            "Origin": origin,
        }
        for i in range(3):
            try:
                async with AsyncSession(
                    proxy=get_proxy_str(config.proxy, curl=True),
                    impersonate="edge",
                    timeout=20.0,
                    allow_redirects=True,
                    headers=headers,
                ) as session:
                    resp = await session.post(f"{api}/telegram/checkin", json={"init_data": init_data})
                    if resp.status_code == 403 and (
                        "Just a moment" in (resp.text or "") or "cf-wrapper" in (resp.text or "")
                    ):
                        self.log.warning(
                            "签到失败: embyguard API 触发了 Cloudflare 页面挑战, "
                            "curl_cffi 指纹未能直接放行. 可尝试更换代理 IP 后重试."
                        )
                        return await self.fail()

                    try:
                        raw = resp.json()
                    except Exception:
                        self.log.warning(
                            f"签到失败: 接口返回非 JSON (HTTP {resp.status_code}): "
                            f"{truncate_str(resp.text or '', 200)}"
                        )
                        return await self.retry()

                    result = self._unwrap_result(raw)
                    error = raw.get("error") if isinstance(raw, dict) else None
                    if error and not result.get("status"):
                        msg = error.get("message", "") if isinstance(error, dict) else str(error)
                        code = error.get("code", "") if isinstance(error, dict) else ""
                        self.log.warning(f"签到失败: 接口返回错误 ({code}): {msg}.")
                        return await self.retry()

                    status = result.get("status")
                    if status in ("checked_in", "already_checked_in", "pending"):
                        return await self._handle_result(status, result)

                    challenge = (result.get("challenge") or "").strip()
                    site_key = (result.get("site_key") or "").strip()
                    action = (result.get("action") or "").strip()
                    cdata = (result.get("cdata") or "").strip()
                    if not challenge or not site_key:
                        self.log.warning(
                            f"签到失败: 未完成且无验证码配置 (HTTP {resp.status_code}): "
                            f"{truncate_str(str(raw), 300)}"
                        )
                        return await self.retry()

                    self.log.info("需要 Turnstile 验证, 正在求解.")
                    self.log.debug(
                        f"Turnstile 参数: site_key={site_key[:16]}..., "
                        f"action={action!r}, cdata_len={len(cdata)}, challenge={challenge[:16]}..."
                    )
                    token = await self._solve_turnstile(webview_url, site_key, action=action, cdata=cdata)
                    if not token:
                        self.log.warning(
                            "签到失败: Turnstile 求解失败. " "请确认 SOLVER_URL / YESCAPTCHA_KEY 可用."
                        )
                        return await self.fail()

                    self.log.info("Turnstile 通过, 正在提交.")
                    self.log.debug(f"Turnstile token_len={len(token)}")
                    # 与前端 completeInlineCheckin 一致: 只提交 init_data + turnstile_token
                    payload = {
                        "init_data": init_data,
                        "turnstile_token": token,
                    }

                    resp = await session.post(
                        f"{api}/telegram/checkin/{challenge}",
                        json=payload,
                    )
                    try:
                        raw = resp.json()
                    except Exception:
                        self.log.warning(
                            f"签到失败: 验证码提交后返回非 JSON (HTTP {resp.status_code}): "
                            f"{truncate_str(resp.text or '', 200)}"
                        )
                        return await self.retry()

                    result = self._unwrap_result(raw)
                    status = result.get("status")
                    if status in ("checked_in", "already_checked_in", "pending"):
                        return await self._handle_result(status, result)
                    self.log.warning(f"签到失败: 验证码提交后返回异常:\n{truncate_str(str(raw), 300)}")
                    return await self.retry()
            except (RequestsError, OSError, ValueError) as e:
                self.log.warning(
                    f"无法连接到签到接口 ({e.__class__.__name__}), "
                    f"可能是网络或代理不稳定, 正在重试 ({i + 1}/3)."
                )
                continue
            except Exception as e:
                self.log.warning(f"签到失败: 接口异常: {e.__class__.__name__}: {e}.")
                show_exception(e)
                return await self.fail()
        self.log.warning("无法连接到签到接口, 重试超限.")
        return await self.retry()

    async def _handle_result(self, status: str, result: dict):
        balance = result.get("wallet_balance", "")
        if status == "checked_in":
            reward = result.get("reward", "")
            self.log.info(f"[yellow]签到成功[/]: 获得奖励 {reward}, 当前余额 {balance}.")
            return await self.finish(RunStatus.SUCCESS, "签到成功")
        elif status == "already_checked_in":
            self.log.info(f"今日已经签到, 当前余额 {balance}.")
            return await self.finish(RunStatus.NONEED, "今日已签到")
        else:
            self.log.info("签到结果待核对, 请勿重复签到.")
            return await self.finish(RunStatus.NONEED, "签到结果待核对")
