from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession, RequestsError

from embykeeper.runinfo import RunStatus
from embykeeper.utils import get_proxy_str, truncate_str

from ._base import BaseBotCheckin

__ignore__ = True

DEFAULT_BASE_URL = "https://mambo-hachimi.biliblili.uk"
ACCESS_BLOCKED_MESSAGE = "站点安全验证拦截"


def normalize_base_url(url: str | None) -> str:
    base = (url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base


def build_login_payload(
    username: str, password: str, verification_token: str | None = None
) -> dict[str, str]:
    payload = {
        "userName": username.strip(),
        "password": password,
        "recaptchaToken": "",
        "verificationToken": verification_token or "",
    }
    return payload


def extract_message(payload: Any, fallback: str = "") -> str:
    if not isinstance(payload, dict):
        return fallback
    for key in ("message", "msg", "detail", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def verification_required(settings: Any, action: str) -> bool:
    if not isinstance(settings, dict):
        return False
    action_settings = settings.get(action)
    if not isinstance(action_settings, dict):
        return False
    verification_type = action_settings.get("type")
    return bool(action_settings.get("enabled") and verification_type != "none")


def classify_status_response(status_code: int, payload: Any) -> tuple[RunStatus, str]:
    if status_code == 401:
        return RunStatus.FAIL, "登录已失效"
    if status_code == 403:
        return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE
    if status_code >= 400 or not isinstance(payload, dict):
        return RunStatus.FAIL, extract_message(payload, "获取签到状态失败")
    if payload.get("success") is False:
        return RunStatus.FAIL, extract_message(payload, "获取签到状态失败")
    checked_in = payload.get("hasCheckedInToday")
    if checked_in is True:
        return RunStatus.NONEED, "今日已签到"
    if checked_in is False:
        return RunStatus.RUNNING, "尚未签到"
    return RunStatus.FAIL, extract_message(payload, "签到状态响应异常")


def classify_checkin_response(status_code: int, payload: Any) -> tuple[RunStatus, str]:
    if status_code == 403:
        return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE
    if (
        status_code < 500
        and status_code not in {401, 403}
        and isinstance(payload, dict)
        and payload.get("hasCheckedIn") is True
    ):
        return RunStatus.NONEED, "今日已签到"
    if status_code >= 400 or not isinstance(payload, dict) or payload.get("success") is not True:
        return RunStatus.FAIL, extract_message(payload, "签到失败")

    amount = payload.get("amount")
    currency = payload.get("currencyUnit")
    if amount is not None and currency:
        return RunStatus.SUCCESS, f"+{amount} {currency}"
    return RunStatus.SUCCESS, extract_message(payload, "签到成功")


class MamboCheckin(BaseBotCheckin):
    name = "Mambo"

    @property
    def base_url(self) -> str:
        return normalize_base_url(self.config.get("url"))

    @property
    def username(self) -> str:
        return str(self.config.get("username") or "").strip()

    @property
    def password(self) -> str:
        return str(self.config.get("password") or "")

    @property
    def access_token(self) -> str:
        return str(self.config.get("access_token") or "").strip()

    @property
    def use_proxy(self) -> bool:
        return self.config.get("use_proxy", False) is True

    def api_url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def client_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base_url,
            "Referer": self.api_url("/login"),
        }
        if self.config.get("useragent"):
            headers["User-Agent"] = str(self.config["useragent"])
        return headers

    async def request_json(self, session: AsyncSession, method: str, path: str, **kwargs) -> tuple[int, Any]:
        response = await session.request(method, self.api_url(path), **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": truncate_str(response.text, 200) or "服务返回非 JSON 响应"}
        return response.status_code, payload

    async def get_verification_settings(self, session: AsyncSession) -> Any:
        status_code, payload = await self.request_json(session, "GET", "/api/settings/verification/public")
        if status_code == 403:
            raise RuntimeError(ACCESS_BLOCKED_MESSAGE)
        if status_code >= 400 or not isinstance(payload, dict):
            raise RuntimeError("无法读取验证配置")
        return payload

    def configured_verification_token(self, action: str) -> str:
        return str(self.config.get(f"{action}_verification_token") or "").strip()

    async def login(self, session: AsyncSession, settings: Any) -> tuple[RunStatus, str, str]:
        if self.access_token:
            return RunStatus.RUNNING, "已使用访问令牌", self.access_token
        if not self.username or not self.password:
            return RunStatus.FAIL, "缺少账号配置", ""

        verification_token = self.configured_verification_token("login")
        if verification_required(settings, "login") and not verification_token:
            return RunStatus.FAIL, "登录需要 Turnstile 验证", ""

        status_code, payload = await self.request_json(
            session,
            "POST",
            "/api/auth/login",
            json=build_login_payload(self.username, self.password, verification_token),
        )
        if status_code == 403:
            return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE, ""
        token = payload.get("token") if isinstance(payload, dict) else None
        if status_code >= 400 or not isinstance(token, str) or not token.strip():
            return RunStatus.FAIL, extract_message(payload, "登录失败"), ""
        return RunStatus.RUNNING, "登录成功", token.strip()

    async def run_api_flow(self, session: AsyncSession) -> tuple[RunStatus, str]:
        if not self.access_token and (not self.username or not self.password):
            return RunStatus.FAIL, "缺少账号配置"

        settings = None
        if self.access_token:
            token = self.access_token
        else:
            settings = await self.get_verification_settings(session)
            status, message, token = await self.login(session, settings)
            if status == RunStatus.FAIL:
                return status, message

        headers = {"Authorization": f"Bearer {token}"}
        status_code, payload = await self.request_json(session, "GET", "/api/checkin/status", headers=headers)
        status, message = classify_status_response(status_code, payload)
        if status != RunStatus.RUNNING:
            return status, message

        if settings is None:
            settings = await self.get_verification_settings(session)

        verification_token = self.configured_verification_token("checkin")
        if verification_required(settings, "checkin") and not verification_token:
            return RunStatus.FAIL, "签到需要 Turnstile 验证"

        body = {"verificationToken": verification_token} if verification_token else {}
        status_code, payload = await self.request_json(
            session, "POST", "/api/checkin", headers=headers, json=body
        )
        return classify_checkin_response(status_code, payload)

    async def start(self):
        from embykeeper.config import config as global_config

        self.ctx.start(RunStatus.INITIALIZING)
        self.ctx.status = RunStatus.RUNNING

        api_proxy = get_proxy_str(global_config.proxy, curl=True) if self.use_proxy else None
        try:
            async with AsyncSession(
                proxy=api_proxy,
                impersonate="edge",
                allow_redirects=True,
                timeout=float(self.timeout),
                headers=self.client_headers(),
            ) as session:
                status, message = await self.run_api_flow(session)
        except (RequestsError, OSError) as error:
            self.log.warning(f"无法连接到 Mambo 页面或接口 ({error.__class__.__name__}).")
            return self.ctx.finish(RunStatus.FAIL, "网络错误")
        if status == RunStatus.SUCCESS:
            self.log.info(f"[yellow]签到成功[/]: {truncate_str(message, 80)}")
        elif status == RunStatus.NONEED:
            self.log.info("今日已经签到过了.")
        else:
            self.log.warning(f"签到失败: {truncate_str(message, 80)}")
        return self.ctx.finish(status, message)
