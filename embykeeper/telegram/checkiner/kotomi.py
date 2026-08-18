from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx
from faker import Faker

from embykeeper.runinfo import RunStatus
from embykeeper.utils import get_proxy_str, truncate_str

from ._base import BaseBotCheckin

__ignore__ = True

DEFAULT_BASE_URL = "https://embymb.ichinosekotomi.com"
ACCESS_BLOCKED_MESSAGE = "站点安全验证拦截"
ALREADY_SIGNED_CODES = {
    "SIGNIN_ALREADY_DONE",
    "SIGNIN_ALREADY_SIGNED",
    "SIGNIN_ALREADY_CHECKED",
    "ALREADY_SIGNED",
    "ALREADY_CHECKED",
}
ALREADY_SIGNED_MESSAGES = {
    "已签到",
    "今日已签到",
    "今天已签到",
    "今日已经签到",
    "今天已经签到",
    "already signed",
    "already checked in",
}


def build_login_payload(username: str, password: str) -> dict[str, str]:
    identity = username.strip()
    if "@" in identity:
        return {"email": identity, "username": "", "password": password}
    return {"username": identity, "password": password}


def normalize_base_url(url: str | None) -> str:
    base = (url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base


def extract_error_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    code = payload.get("error_code") or payload.get("errorCode") or payload.get("code")
    return str(code).strip().upper() if code is not None else None


def extract_message(payload: Any, fallback: str = "") -> str:
    if not isinstance(payload, dict):
        return fallback
    for key in ("message", "detail", "error", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def has_signed_today(payload: Any) -> bool:
    keys = {
        "today_signed",
        "signed_today",
        "already_signed",
        "has_signed_today",
        "has_checked_in_today",
        "checked_today",
        "is_signed_today",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in keys and value is True:
                return True
            if isinstance(value, (dict, list)) and has_signed_today(value):
                return True
    elif isinstance(payload, list):
        return any(has_signed_today(item) for item in payload)
    return False


def is_already_signed(status_code: int, payload: Any) -> bool:
    if status_code >= 500 or status_code in {401, 403}:
        return False
    message = extract_message(payload).strip().lower().rstrip(".!。！")
    code = extract_error_code(payload)
    return code in ALREADY_SIGNED_CODES or has_signed_today(payload) or message in ALREADY_SIGNED_MESSAGES


def classify_signin_status_response(status_code: int, payload: Any) -> tuple[RunStatus, str]:
    if status_code == 403:
        return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE
    if is_already_signed(status_code, payload):
        return RunStatus.NONEED, "今日已签到"
    if (
        status_code >= 400
        or not isinstance(payload, dict)
        or not (payload.get("success") is True or payload.get("ok") is True)
    ):
        return RunStatus.FAIL, extract_message(payload, "获取签到状态失败")
    return RunStatus.RUNNING, "尚未签到"


def classify_signin_response(status_code: int, payload: Any) -> tuple[RunStatus, str]:
    if status_code == 403:
        return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE
    code = extract_error_code(payload)
    message = extract_message(payload)
    success = payload.get("success") if isinstance(payload, dict) else None
    ok = payload.get("ok") if isinstance(payload, dict) else None

    if is_already_signed(status_code, payload):
        return RunStatus.NONEED, "今日已签到"
    if code == "SIGNIN_DISABLED":
        return RunStatus.FAIL, "签到功能未开启"
    if status_code >= 400 or not isinstance(payload, dict) or not (success is True or ok is True):
        return RunStatus.FAIL, message or "签到失败"
    return RunStatus.SUCCESS, message or "签到成功"


class KotomiCheckin(BaseBotCheckin):
    name = "Kotomi"

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
    def use_proxy(self) -> bool:
        return self.config.get("use_proxy", True) is not False

    def api_url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/api/v1/", path.lstrip("/"))

    def page_url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def client_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base_url,
            "Referer": self.page_url("/login"),
            "User-Agent": self.config.get("useragent") or Faker().safari(),
            "X-Twilight-Client": "webui",
        }

    async def request_json(
        self, client: httpx.AsyncClient, method: str, path: str, **kwargs
    ) -> tuple[int, Any]:
        resp = await client.request(method, self.api_url(path), **kwargs)
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text
        return resp.status_code, payload

    async def run_api_flow(self, client: httpx.AsyncClient) -> tuple[RunStatus, str]:
        response = await client.get(self.page_url("/login"))
        if response.status_code == 403:
            return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE
        if response.status_code >= 400:
            return RunStatus.FAIL, "登录页面不可用"

        status_code, payload = await self.request_json(
            client,
            "POST",
            "/auth/login",
            json=build_login_payload(self.username, self.password),
        )
        if status_code == 403:
            return RunStatus.FAIL, ACCESS_BLOCKED_MESSAGE
        login_succeeded = isinstance(payload, dict) and (
            payload.get("success") is True or payload.get("ok") is True
        )
        if status_code >= 400 or not login_succeeded:
            return RunStatus.FAIL, extract_message(payload, "登录失败")

        status_code, payload = await self.request_json(client, "GET", "/signin/me")
        status, message = classify_signin_status_response(status_code, payload)
        if status != RunStatus.RUNNING:
            return status, message

        status_code, payload = await self.request_json(client, "POST", "/signin")
        return classify_signin_response(status_code, payload)

    async def start(self):
        from embykeeper.config import config as global_config

        self.ctx.start(RunStatus.INITIALIZING)

        if not self.username or not self.password:
            self.log.warning("初始化错误: 请在 [checkiner.kotomi] 中配置 username 和 password.")
            return self.ctx.finish(RunStatus.FAIL, "缺少账号配置")

        proxy = get_proxy_str(global_config.proxy) if self.use_proxy else None
        timeout = httpx.Timeout(self.timeout)
        self.ctx.status = RunStatus.RUNNING

        try:
            async with httpx.AsyncClient(
                http2=True,
                follow_redirects=True,
                timeout=timeout,
                proxy=proxy,
                headers=self.client_headers(),
            ) as client:
                status, message = await self.run_api_flow(client)
        except httpx.HTTPError as e:
            self.log.warning(f'无法连接到 Kotomi 页面或接口: "{e}", 签到器将停止.')
            return self.ctx.finish(RunStatus.FAIL, "网络错误")
        except OSError as e:
            self.log.warning(f'网络错误: "{e}", 签到器将停止.')
            return self.ctx.finish(RunStatus.FAIL, "网络错误")

        if status == RunStatus.SUCCESS:
            self.log.info(f"[yellow]签到成功[/]: {truncate_str(message, 80)}")
        elif status == RunStatus.NONEED:
            self.log.info("今日已经签到过了.")
        else:
            self.log.warning(f"签到失败: {truncate_str(message, 80)}")
        return self.ctx.finish(status, message)
