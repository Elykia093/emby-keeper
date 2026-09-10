"""
Turnstile验证服务类
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _config_turnstile():
    """从 embykeeper config.toml 的 [turnstile] 读取, 不可用则返回空."""
    try:
        from embykeeper.config import config

        return getattr(config, "turnstile", None)
    except Exception:
        return None


class TurnstileService:
    """通过 YesCaptcha 求解 Turnstile 验证.

    接口兼容 YesCaptchaSolver：
      solve_turnstile(website_url, website_key, premium=False) → token str

    默认对失败整轮重试 3 次, 总限时 120 秒。
    """

    def __init__(self, yescaptcha_key=""):
        cfg = _config_turnstile()
        cfg_key = (getattr(cfg, "yescaptcha_key", None) or "") if cfg else ""

        keys = (yescaptcha_key, os.getenv("YESCAPTCHA_KEY", ""), os.getenv("YESCAPTCHA_API_KEY", ""), cfg_key)
        self.yescaptcha_key = next((key.strip() for key in keys if key and key.strip()), "")
        if not self.yescaptcha_key:
            raise RuntimeError(
                "未配置 YesCaptcha API Key, 请设置 [turnstile].yescaptcha_key 或环境变量 YESCAPTCHA_KEY."
            )
        self.yescaptcha_api = "https://api.yescaptcha.com"

    def solve_turnstile(
        self,
        website_url,
        website_key,
        **kwargs,
    ) -> str:
        """保留同步入口; 异步调用方应使用 solve_turnstile_async 以便取消请求."""
        return asyncio.run(self.solve_turnstile_async(website_url, website_key, **kwargs))

    async def solve_turnstile_async(
        self,
        website_url,
        website_key,
        *,
        action: str = "",
        cdata: str = "",
        premium=False,
        max_attempts: int = 3,
        retry_delay: float = 2.0,
        timeout: float = 120.0,
    ) -> str:
        """返回 token 字符串; 超时或取消会停止请求、轮询和后续整轮重试。

        action / cdata 用于 managed Turnstile（如 embyguard checkin），
        必须与页面渲染 widget 时一致，否则服务端会 invalid_turnstile。

        解码失败 / 创建任务失败时会整轮重试（每次新建 task），最多 max_attempts 次。
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        last_error: Optional[Exception] = None
        async with asyncio.timeout(timeout), httpx.AsyncClient(timeout=30) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    task_id = await self._create_task(
                        client, website_url, website_key, action=action, cdata=cdata
                    )
                    token = await self._get_response(client, task_id)
                    if token:
                        if attempt > 1:
                            print(f"YesCaptcha Turnstile 求解成功 (attempt {attempt}/{max_attempts})")
                        return token
                    last_error = RuntimeError("TurnstileService: 解码失败")
                except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as e:
                    last_error = e

                if attempt < max_attempts:
                    print(
                        f"YesCaptcha Turnstile 求解失败 (attempt {attempt}/{max_attempts}): "
                        f"{last_error.__class__.__name__}，{retry_delay:.0f}s 后重试..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    print(f"YesCaptcha Turnstile 求解失败, 已达最大重试次数 ({max_attempts})")

        assert last_error is not None
        if isinstance(last_error, RuntimeError) and str(last_error).startswith("TurnstileService: 解码失败"):
            raise last_error
        raise RuntimeError(
            f"TurnstileService: YesCaptcha 求解失败 (attempts={max_attempts}): {last_error}"
        ) from last_error

    async def _create_task(
        self, client: httpx.AsyncClient, siteurl, sitekey, action: str = "", cdata: str = ""
    ):
        """创建Turnstile验证任务"""
        action = (action or "").strip()
        cdata = (cdata or "").strip()

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
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("YesCaptcha创建任务响应无效")
        if data.get("errorId") != 0:
            message = str(data.get("errorDescription") or "未知错误").replace(
                self.yescaptcha_key, "[REDACTED]"
            )
            raise RuntimeError(f"YesCaptcha创建任务失败: {message}")
        if not data.get("taskId"):
            raise ValueError("YesCaptcha创建任务响应缺少 taskId")
        return data["taskId"]

    async def _get_response(
        self, client: httpx.AsyncClient, task_id, max_retries=30, initial_delay=5, retry_delay=2
    ):
        """获取Turnstile验证响应"""
        await asyncio.sleep(initial_delay)

        for _ in range(max_retries):
            try:
                url = f"{self.yescaptcha_api}/getTaskResult"
                payload = {
                    "clientKey": self.yescaptcha_key,
                    "taskId": task_id,
                }
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("YesCaptcha获取结果响应无效")

                if data.get("errorId") != 0:
                    print("YesCaptcha获取结果失败, 重试中...")
                    await asyncio.sleep(retry_delay)
                    continue

                if data.get("status") == "ready":
                    solution = data.get("solution")
                    token = solution.get("token") if isinstance(solution, dict) else None
                    if isinstance(token, str) and token.strip():
                        return token.strip()
                    print("YesCaptcha返回结果中没有token")
                    return None
                if data.get("status") == "processing":
                    await asyncio.sleep(retry_delay)
                else:
                    print("YesCaptcha未知状态")
                    await asyncio.sleep(retry_delay)
            except (httpx.HTTPError, ValueError) as e:
                print(f"获取Turnstile响应异常: {e.__class__.__name__}")
                await asyncio.sleep(retry_delay)

        return None
