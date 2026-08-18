"""
Turnstile验证服务类
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

import requests
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# 仅作最后兜底; 正式环境请在 config.toml [turnstile] solver_url 配置
DEFAULT_SOLVER_URL = "http://127.0.0.1:8889"


def _normalize_solver_base(url: str) -> str:
    """Strip trailing slash; empty → default turnsolve."""
    base = (url or "").strip().rstrip("/")
    return base or DEFAULT_SOLVER_URL


def _split_solver_urls(raw: str) -> List[str]:
    """支持逗号/分号/空白分隔的多个 solver 地址, 去重保序."""
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        u = chunk.strip()
        if not u:
            continue
        parts.append(_normalize_solver_base(u))
    # 去重保序
    seen = set()
    out = []
    for u in parts:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _config_turnstile():
    """从 embykeeper config.toml 的 [turnstile] 读取, 不可用则返回空."""
    try:
        from embykeeper.config import config

        return getattr(config, "turnstile", None)
    except Exception:
        return None


def _is_loopback_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


# Local solver must not go through HTTP(S)_PROXY (Clash/etc often break loopback).
_NO_PROXY = {"http": None, "https": None}


class TurnstileService:
    """Turnstile验证服务类

    支持两种后端（自动判断）：
      - YESCAPTCHA_KEY 环境变量 / config.toml yescaptcha_key 存在 → YesCaptcha API
      - 否则 → turnsolve（config.toml solver_url / 环境变量 / 默认 127.0.0.1:8889）

    solver_url 支持逗号分隔多个地址, 失败自动换下一个:
      solver_url = "http://a:8889,http://b:8889"

    接口兼容 YesCaptchaSolver：
      solve_turnstile(website_url, website_key, premium=False) → token str

    默认对失败整轮重试 3 次（每次新建 task，不重用失败的 task_id）。
    多 solver 时: 每个地址各自 max_attempts, 全挂再换下一个。
    """

    def __init__(self, solver_url="", yescaptcha_key=""):
        # 优先级: 构造参数 > 环境变量 > config.toml [turnstile] > 默认兜底
        cfg = _config_turnstile()
        cfg_key = (getattr(cfg, "yescaptcha_key", None) or "") if cfg else ""
        cfg_url = (getattr(cfg, "solver_url", None) or "") if cfg else ""

        self.yescaptcha_key = (
            yescaptcha_key
            or os.getenv("YESCAPTCHA_KEY", "")
            or os.getenv("YESCAPTCHA_API_KEY", "")
            or cfg_key
        ).strip()
        raw = solver_url or os.getenv("SOLVER_URL", "") or cfg_url or DEFAULT_SOLVER_URL
        self.solver_urls = _split_solver_urls(raw) or [DEFAULT_SOLVER_URL]
        # 兼容旧属性: 当前/首选地址
        self.solver_url = self.solver_urls[0]
        self.yescaptcha_api = "https://api.yescaptcha.com"

    def solve_turnstile(
        self,
        website_url,
        website_key,
        *,
        action: str = "",
        cdata: str = "",
        premium=False,
        max_attempts: int = 3,
        retry_delay: float = 2.0,
    ):
        """兼容 YesCaptchaSolver 接口，返回 token 字符串。

        action / cdata 用于 managed Turnstile（如 embyguard checkin），
        必须与页面渲染 widget 时一致，否则服务端会 invalid_turnstile。

        解码失败 / 创建任务失败时会整轮重试（每次新建 task），最多 max_attempts 次。
        若配置了多个 solver_url, 当前地址耗尽重试后自动换下一个。
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        # YesCaptcha 优先: 不走本地 solver 列表
        if self.yescaptcha_key:
            return self._solve_with_backend(
                website_url,
                website_key,
                action=action,
                cdata=cdata,
                max_attempts=max_attempts,
                retry_delay=retry_delay,
                solver_url=None,
            )

        last_error: Optional[Exception] = None
        for idx, url in enumerate(self.solver_urls):
            self.solver_url = url  # 当前使用的地址 (create_task/get_response 读它)
            try:
                return self._solve_with_backend(
                    website_url,
                    website_key,
                    action=action,
                    cdata=cdata,
                    max_attempts=max_attempts,
                    retry_delay=retry_delay,
                    solver_url=url,
                )
            except Exception as e:
                last_error = e
                if idx + 1 < len(self.solver_urls):
                    print(
                        f"Turnstile solver {url} 失败, 切换下一个 "
                        f"({idx + 1}/{len(self.solver_urls)}): {e}"
                    )
                    time.sleep(retry_delay)
                else:
                    print(
                        f"Turnstile solver {url} 失败, 已无更多备用地址 "
                        f"({idx + 1}/{len(self.solver_urls)}): {e}"
                    )

        assert last_error is not None
        raise RuntimeError(
            f"TurnstileService: 全部 solver 失败 ({len(self.solver_urls)} 个): {last_error}"
        ) from last_error

    def _solve_with_backend(
        self,
        website_url,
        website_key,
        *,
        action: str = "",
        cdata: str = "",
        max_attempts: int = 3,
        retry_delay: float = 2.0,
        solver_url: Optional[str] = None,
    ):
        """在当前后端 (YesCaptcha 或指定 solver_url) 上重试 max_attempts 次."""
        if solver_url:
            self.solver_url = solver_url

        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                task_id = self.create_task(website_url, website_key, action=action, cdata=cdata)
                token = self.get_response(task_id)
                if token:
                    if attempt > 1 or (solver_url and solver_url != self.solver_urls[0]):
                        print(
                            f"Turnstile 求解成功 (attempt {attempt}/{max_attempts}, "
                            f"solver={self.solver_url or 'yescaptcha'}, task_id={task_id})"
                        )
                    return token
                last_error = RuntimeError(f"TurnstileService: 解码失败 (task_id={task_id})")
            except Exception as e:
                last_error = e

            if attempt < max_attempts:
                print(
                    f"Turnstile 求解失败 (attempt {attempt}/{max_attempts}, "
                    f"solver={self.solver_url or 'yescaptcha'}): "
                    f"{last_error}，{retry_delay:.0f}s 后重试..."
                )
                time.sleep(retry_delay)
            else:
                print(
                    f"Turnstile 求解失败 (attempt {attempt}/{max_attempts}, "
                    f"solver={self.solver_url or 'yescaptcha'}): "
                    f"{last_error}，已达最大重试次数"
                )

        assert last_error is not None
        if isinstance(last_error, RuntimeError) and str(last_error).startswith("TurnstileService: 解码失败"):
            raise last_error
        raise RuntimeError(
            f"TurnstileService: 求解失败 (attempts={max_attempts}, "
            f"solver={self.solver_url or 'yescaptcha'}): {last_error}"
        ) from last_error

    def create_task(self, siteurl, sitekey, action: str = "", cdata: str = ""):
        """创建Turnstile验证任务"""
        action = (action or "").strip()
        cdata = (cdata or "").strip()

        if self.yescaptcha_key:
            url = f"{self.yescaptcha_api}/createTask"
            task = {
                "type": "TurnstileTaskProxyless",
                "websiteURL": siteurl,
                "websiteKey": sitekey,
            }
            # managed challenge 需要与前端 widget 一致的 action / cData
            if action:
                task["action"] = action
            if cdata:
                task["data"] = cdata
            payload = {
                "clientKey": self.yescaptcha_key,
                "task": task,
            }
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("errorId") != 0:
                raise Exception(f"YesCaptcha创建任务失败: {data.get('errorDescription')}")
            return data["taskId"]

        # 本地 Turnstile Solver：
        # 1) 用 params 做 URL 编码（sign-up?redirect=... 不能手拼 query）
        # 2) 本机地址禁用代理（否则 HTTP_PROXY 会把请求转丢）
        params = {"url": siteurl, "sitekey": sitekey}
        if action:
            params["action"] = action
        if cdata:
            params["cdata"] = cdata
            params["data"] = cdata
        kwargs = {
            "params": params,
            "timeout": 30,
        }
        if _is_loopback_url(self.solver_url):
            kwargs["proxies"] = _NO_PROXY
        response = requests.get(f"{self.solver_url}/turnstile", **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"本地 solver 创建任务失败 HTTP {response.status_code} "
                f"base={self.solver_url} body={(response.text or '')[:200]}"
            )
        data = response.json()
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"本地 solver 未返回 taskId: {data!r}"[:300])
        return task_id

    def get_response(self, task_id, max_retries=30, initial_delay=5, retry_delay=2):
        """获取Turnstile验证响应"""
        time.sleep(initial_delay)

        for _ in range(max_retries):
            try:
                if self.yescaptcha_key:
                    url = f"{self.yescaptcha_api}/getTaskResult"
                    payload = {
                        "clientKey": self.yescaptcha_key,
                        "taskId": task_id,
                    }
                    response = requests.post(url, json=payload, timeout=30)
                    response.raise_for_status()
                    data = response.json()

                    if data.get("errorId") != 0:
                        print(f"YesCaptcha获取结果失败: {data.get('errorDescription')}，重试中...")
                        time.sleep(retry_delay)
                        continue

                    if data.get("status") == "ready":
                        token = data.get("solution", {}).get("token")
                        if token:
                            return token
                        print("YesCaptcha返回结果中没有token")
                        return None
                    if data.get("status") == "processing":
                        time.sleep(retry_delay)
                    else:
                        print(f"YesCaptcha未知状态: {data.get('status')}")
                        time.sleep(retry_delay)
                else:
                    kwargs = {"params": {"id": task_id}, "timeout": 30}
                    if _is_loopback_url(self.solver_url):
                        kwargs["proxies"] = _NO_PROXY
                    response = requests.get(f"{self.solver_url}/result", **kwargs)
                    response.raise_for_status()
                    data = response.json()
                    captcha = (data.get("solution") or {}).get("token") or data.get("value")

                    if captcha:
                        if captcha != "CAPTCHA_FAIL":
                            return captcha
                        return None
                    time.sleep(retry_delay)
            except Exception as e:
                print(f"获取Turnstile响应异常: {e}")
                time.sleep(retry_delay)

        return None
