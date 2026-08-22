import asyncio
import base64
import mimetypes
import random
import re
from pathlib import Path
from typing import Callable, Coroutine, List, Optional, Tuple, Union
import uuid
from io import BytesIO

import tomli
from loguru import logger
from pyrogram import filters
from pyrogram.handlers import MessageHandler
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from pyrogram.errors.exceptions.bad_request_400 import YouBlockedUser
from pyrogram.errors import FloodWait
from thefuzz import process

from embykeeper.config import config
from embykeeper.utils import async_partial, to_thread_compat, truncate_str

from .lock import super_ad_shown, super_ad_shown_lock, authed_services, authed_services_lock
from .pyrogram import Client


class LinkError(Exception):
    pass


class Link:
    """云服务类, 用于认证和高级权限任务通讯."""

    bot = "embykeeper_auth_bot"
    post_count = 0
    _zhipu_clients = {}

    def __init__(self, client: Client):
        self.client = client
        self.log = logger.bind(scheme="telelink", username=client.me.full_name)

    @property
    def instance(self):
        """当前设备识别码."""
        rd = random.Random()
        rd.seed(uuid.getnode())
        return uuid.UUID(int=rd.getrandbits(128))

    async def delete_messages(self, messages: List[Message]):
        """删除一系列消息."""

        async def delete(m: Message):
            try:
                await asyncio.wait_for(m.delete(revoke=True), 3)
                text = m.text or m.caption or "图片或其他内容"
                text = truncate_str(text.replace("\n", ""), 30)
                self.log.debug(f"[gray50]删除了 API 消息记录: {text}[/]")
            except asyncio.TimeoutError:
                pass

        return await asyncio.gather(*[delete(m) for m in messages])

    async def post(self, *args, stop_grace: float = 0, **kw):
        async def stop(task: asyncio.Task):
            if stop_grace and not task.done():
                await asyncio.sleep(stop_grace)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(self._post(*args, **kw))
        stop_handler = async_partial(stop, task=task)
        self.client.stop_handlers.append(stop_handler)
        try:
            return await task
        finally:
            self.client.stop_handlers.remove(stop_handler)

    async def _post(
        self,
        cmd,
        photo=None,
        file=None,
        condition: Callable = None,
        timeout: int = 60,
        retries=3,
        name: str = None,
        fail: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        向机器人发送请求.
        参数:
            cmd: 命令字符串
            condition: 布尔或函数, 参数为响应 toml 的字典形式, 决定该响应是否为有效响应.
            timeout: 超时 (s)
            retries: 最大重试次数
            name: 请求名称, 用于用户提示
            fail: 当出现错误时抛出错误, 而非发送日志
        """
        Link.post_count += 1
        try:
            self.log.info(f"正在进行服务请求: {name}")

            if photo and file:
                raise ValueError("can not use both photo and file")

            for r in range(retries):
                try:
                    await self.client.mute_chat(self.bot)
                except FloodWait:
                    self.log.debug(f"[gray50]设置禁用提醒因访问超限而失败: {self.bot}[/]")
                future = asyncio.Future()
                handler = MessageHandler(
                    async_partial(self._handler, cmd=cmd, future=future, condition=condition),
                    filters.text & filters.bot & filters.user(self.bot),
                )
                await self.client.add_handler(handler, group=1)
                try:
                    messages = []
                    if photo:
                        messages.append(
                            await self.client.send_photo(
                                self.bot, photo, caption=cmd, parse_mode=ParseMode.DISABLED
                            )
                        )
                    elif file:
                        messages.append(
                            await self.client.send_document(
                                self.bot, file, caption=cmd, parse_mode=ParseMode.DISABLED
                            )
                        )
                    else:
                        messages.append(
                            await self.client.send_message(self.bot, cmd, parse_mode=ParseMode.DISABLED)
                        )
                    self.log.debug(f"[gray50]-> {cmd}[/]")
                    results = await asyncio.wait_for(future, timeout=timeout)
                except asyncio.CancelledError:
                    try:
                        await asyncio.wait_for(self.delete_messages(messages), 3)
                    except asyncio.TimeoutError:
                        pass
                    finally:
                        raise
                except asyncio.TimeoutError:
                    await self.delete_messages(messages)
                    if r + 1 < retries:
                        self.log.info(f"{name}超时 ({r + 1}/{retries}), 将在 3 秒后重试.")
                        await asyncio.sleep(3)
                        continue
                    else:
                        msg = f"{name}超时 ({r + 1}/{retries})."
                        if fail:
                            raise LinkError(msg)
                        else:
                            self.log.warning(msg)
                            return None
                except YouBlockedUser:
                    msg = "您在账户中禁用了用于 API 信息传递的 Bot: @embykeeper_auth_bot, 这将导致 embykeeper 无法运行, 请尝试取消禁用."
                    if fail:
                        raise LinkError(msg)
                    else:
                        self.log.error(msg)
                        return None
                else:
                    await self.delete_messages(messages)
                    status, errmsg = [results.get(p, None) for p in ("status", "errmsg")]
                    if status == "error":
                        if fail:
                            raise LinkError(f"{errmsg}.")
                        else:
                            self.log.warning(f"{name}错误: {errmsg}.")
                            return False
                    elif status == "ok":
                        self.log.info(f"服务请求完成: {name}")
                        return results
                    else:
                        if fail:
                            raise LinkError("出现未知错误.")
                        else:
                            self.log.warning(f"{name}出现未知错误.")
                            return False
                finally:
                    try:
                        await self.client.remove_handler(handler, group=1)
                    except:
                        pass

        finally:
            Link.post_count -= 1

    async def _handler(
        self,
        client: Client,
        message: Message,
        cmd: str,
        future: asyncio.Future,
        condition: Union[bool, Callable[..., Coroutine], Callable] = None,
    ):
        try:
            toml = tomli.loads(message.text)
        except tomli.TOMLDecodeError:
            await self.delete_messages([message])
        else:
            try:
                if toml.get("command", None) == cmd:
                    if condition is None:
                        cond = True
                    elif asyncio.iscoroutinefunction(condition):
                        cond = await condition(toml)
                    elif callable(condition):
                        cond = condition(toml)
                    if cond:
                        if not future.done():
                            future.set_result(toml)
                        await asyncio.sleep(0.5)
                        await self.delete_messages([message])
                        return
            except asyncio.CancelledError as e:
                try:
                    await asyncio.wait_for(self.delete_messages([message]), 3)
                except asyncio.TimeoutError:
                    pass
                finally:
                    if not future.done():
                        future.set_exception(e)
                    raise
            else:
                message.continue_propagation()

    async def auth(self, service: str, log_func=None):
        """向机器人发送授权请求."""
        async with authed_services_lock:
            user_auth_cache = authed_services.get(self.client.me.id, {}).get(service, None)
            if user_auth_cache is not None:
                return user_auth_cache

            # No cache, perform auth
            if not log_func:
                result = await self.post(
                    f"/auth {service} {self.instance}", name=f"服务 {service.upper()} 认证"
                )
                authed_services.setdefault(self.client.me.id, {})[service] = bool(result)
                return bool(result)
            else:
                try:
                    await self.post(
                        f"/auth {service} {self.instance}",
                        name=f"服务 {service.upper()} 认证",
                        fail=True,
                    )
                except LinkError as e:
                    log_func(f"初始化错误: 使用 {service.upper()} 服务, 但{e}")
                    if "权限不足" in str(e):
                        await self._show_super_ad()
                    authed_services.setdefault(self.client.me.id, {})[service] = False
                    return False
                else:
                    authed_services.setdefault(self.client.me.id, {})[service] = True
                    return True

    async def _show_super_ad(self):
        async with super_ad_shown_lock:
            user_super_ad_shown = super_ad_shown.get(self.client.me.id, False)
            if not user_super_ad_shown:
                self.log.info("请访问 https://go.zetx.tech/eksuper 赞助项目以升级为高级用户, 尊享更多功能.")
                super_ad_shown[self.client.me.id] = True
                return True
            else:
                return False

    async def captcha(self, site: str, url: str = None) -> Optional[str]:
        """向机器人发送验证码解析请求."""
        cmd = f"/captcha {self.instance} {site}"
        if url:
            cmd += f" {url}"
        results = await self.post(cmd, timeout=120, name="请求跳过验证码")
        if results:
            return results.get("token", None)
        else:
            return None

    async def captcha_content(self, site: str, url: str = None) -> Optional[str]:
        """向机器人发送带验证码的远程网页解析请求."""
        cmd = f"/captcha {self.instance} {site}"
        if url:
            cmd += f" {url}"
        results = await self.post(cmd, timeout=120, name="请求跳过验证码")
        if results:
            return results.get("content", None)
        else:
            return None

    async def wssocks(self) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送逆向 Socks 代理隧道监听请求."""
        cmd = f"/wssocks {self.instance}"
        results = await self.post(cmd, timeout=20, name="请求新建代理隧道以跳过验证码")
        if results:
            return results.get("url", None), results.get("token", None)
        else:
            return None, None

    async def captcha_wssocks(
        self, token: str, url: str, user_agent: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送通过代理隧道进行验证码解析请求."""
        cmd = f"/captcha_wssocks {self.instance} {token} {url}"
        if user_agent:
            cmd += f" {user_agent}"
        results = await self.post(cmd, timeout=120, name="请求跳过验证码")
        if results:
            return results.get("cf_clearance", None), results.get("useragent", None)
        else:
            return None, None

    async def pornemby_answer(self, question: str) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送问题回答请求."""
        results = await self.post(
            f"/pornemby_answer {self.instance} {question}", timeout=20, name="请求问题回答"
        )
        if results:
            return results.get("answer", None), results.get("by", None)
        else:
            return None, None

    async def terminus_answer(self, question: str) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送问题回答请求."""
        results = await self.post(
            f"/terminus_answer {self.instance} {question}", timeout=20, name="请求问题回答"
        )
        if results:
            return results.get("answer", None), results.get("by", None)
        else:
            return None, None

    async def gpt(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送智能回答请求, 主后端失败时依次回退备用后端."""
        backends = self._build_ai_backends(self._get_local_ai_config())
        if not backends:
            self.log.warning("请求智能回答失败: 未设置本地智谱 AI 配置 `[checkiner.ai].api_key`.")
            return None, None

        for index, backend in enumerate(backends):
            content = await self._request_ai_backend(
                backend,
                [{"role": "user", "content": prompt}],
                name="智能回答",
                attempt=(index + 1, len(backends)),
            )
            if content is None:
                continue

            answer = self._strip_think_content(self._normalize_ai_content(content))
            if not answer:
                self.log.warning(
                    f"请求智能回答失败: 仅返回思维链或空内容, 原始响应预览: {self._preview_ai_content(content)}."
                )
                continue

            self.log.info("服务请求完成: 请求智能回答")
            return answer, f"zhipu:{backend['model_id']}"

        return None, None

    def _get_local_ai_config(self):
        ai_config = getattr(config.checkiner, "ai", None) or {}
        if isinstance(ai_config, dict):
            return ai_config
        return {}

    @classmethod
    def _get_zhipu_client(cls, api_key: str, base_url: str = None):
        cache_key = (api_key, base_url or "")
        if cache_key in cls._zhipu_clients:
            return cls._zhipu_clients[cache_key]

        from zai import ZhipuAiClient

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = ZhipuAiClient(**kwargs)
        cls._zhipu_clients[cache_key] = client
        return client

    @staticmethod
    def _is_content_filter_error(error) -> bool:
        """判断异常是否为服务商内容审核拦截, 这类失败重试同一后端没有意义."""
        text = str(error)
        return "contentFilter" in text or '"1301"' in text or ("敏感" in text and "内容" in text)

    def _build_ai_backends(self, ai_config: dict) -> List[dict]:
        """展开主后端与 fallbacks, 未指定的字段继承主后端."""
        primary = {
            "api_key": ai_config.get("api_key"),
            "base_url": ai_config.get("base_url"),
            "model_id": ai_config.get("model_id") or "glm-4.1v-thinking-flashx",
            "timeout": ai_config.get("llm_timeout", 40),
            "prompt": ai_config.get("llm_prompt"),
        }
        backends = [primary]
        for entry in ai_config.get("fallbacks") or []:
            if not isinstance(entry, dict):
                continue
            backend = dict(primary)
            for key, alias in (
                ("api_key", "api_key"),
                ("base_url", "base_url"),
                ("model_id", "model_id"),
                ("timeout", "llm_timeout"),
                ("prompt", "llm_prompt"),
            ):
                if entry.get(alias) is not None:
                    backend[key] = entry[alias]
            backends.append(backend)
        return [b for b in backends if b["api_key"]]

    @staticmethod
    def _normalize_ai_content(content):
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item) for item in content
            )
        return (content or "").strip()

    @staticmethod
    def _preview_ai_content(content, limit: int = 200) -> str:
        normalized = Link._normalize_ai_content(content).replace("\n", " ")
        return truncate_str(normalized, limit) if normalized else "<empty>"

    @staticmethod
    def _strip_think_content(content: str) -> str:
        return re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()

    @staticmethod
    def _encode_image_data(image) -> str:
        suffix = Path(getattr(image, "name", "")).suffix.lower()
        mime_type = mimetypes.types_map.get(suffix, "image/png")
        data = base64.b64encode(image.getvalue()).decode("utf-8")
        return f"data:{mime_type};base64,{data}"

    @staticmethod
    def _extract_answer_tag(content: str) -> Optional[str]:
        match = re.search(r"\[ANSWER\](.+?)\[/ANSWER\]", content, flags=re.S)
        if match:
            answer = match.group(1)
        else:
            answer = content
        answer = (answer or "").strip().strip("`").strip()
        if not answer or answer.upper() == "[UNKNOWN]":
            return None
        return answer

    async def _request_ai_backend(self, backend: dict, messages: List[dict], name: str, attempt=None):
        """向单个 AI 后端发起请求, 失败返回 None 并记录可区分的原因."""
        suffix = ""
        if attempt and attempt[1] > 1:
            suffix = f" [后端 {attempt[0]}/{attempt[1]}: {backend['model_id']}]"
        self.log.info(f"正在进行服务请求: 请求{name}{suffix}")

        try:
            client = self._get_zhipu_client(backend["api_key"], backend.get("base_url"))
        except ImportError:
            self.log.warning(f"请求{name}失败: 未安装 zai-sdk, 请先安装 `zai-sdk>=0.2.2`.")
            return None
        except Exception as e:
            self.log.warning(f"请求{name}失败: 初始化客户端失败: {e}.")
            return None

        def run_request():
            response = client.chat.completions.create(model=backend["model_id"], messages=messages)
            return response.choices[0].message.content

        try:
            return await asyncio.wait_for(to_thread_compat(run_request), timeout=backend["timeout"])
        except asyncio.TimeoutError:
            self.log.warning(f"请求{name}超时{suffix}.")
        except Exception as e:
            if self._is_content_filter_error(e):
                self.log.warning(
                    f"请求{name}被服务商内容审核拦截{suffix}, "
                    "可通过 `[checkiner.ai].fallbacks` 配置其他模型或服务商回退."
                )
            else:
                self.log.warning(f"请求{name}失败{suffix}: {e}.")
        return None

    async def visual(self, photo, options: List[str], question=None) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送视觉问题解答请求, 主后端失败时依次回退备用后端."""
        backends = self._build_ai_backends(self._get_local_ai_config())
        if not backends:
            self.log.warning("请求视觉问题解答失败: 未设置本地智谱 AI 配置 `[checkiner.ai].api_key`.")
            return None, None

        try:
            image = await self.client.download_media(photo, in_memory=True)
        except Exception as e:
            self.log.warning(f"请求视觉问题解答失败: 下载图片失败: {e}.")
            return None, None

        image_data = self._encode_image_data(image)
        option_lines = "\n".join(f"- {option}" for option in options)

        for index, backend in enumerate(backends):
            model_id = backend["model_id"]
            prompt = backend["prompt"] or "请根据图片内容，只从候选项中选择唯一正确的一项。"
            if question:
                prompt += f"\n题目或提示: {question}"
            prompt += (
                f"\n候选项如下:\n{option_lines}\n\n"
                "只输出一行，格式必须为 [ANSWER]候选项原文[/ANSWER]。\n"
                "如果无法判断，请输出 [ANSWER][UNKNOWN][/ANSWER]。"
            )

            content = await self._request_ai_backend(
                backend,
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data}},
                        ],
                    }
                ],
                name="视觉问题解答",
                attempt=(index + 1, len(backends)),
            )
            if content is None:
                continue

            answer = self._extract_answer_tag(self._strip_think_content(self._normalize_ai_content(content)))
            if not answer:
                self.log.warning(
                    f"请求视觉问题解答失败: 未返回可用答案, 原始响应预览: {self._preview_ai_content(content)}."
                )
                continue

            if answer in options:
                self.log.info("服务请求完成: 请求视觉问题解答")
                return answer, f"zhipu:{model_id}"

            matched = process.extractOne(answer, options)
            if not matched or matched[1] < 70:
                self.log.warning(
                    f'请求视觉问题解答失败: 返回答案 "{answer}" 无法匹配候选项 {options}, '
                    f"最佳匹配结果: {matched}."
                )
                continue

            self.log.info("服务请求完成: 请求视觉问题解答")
            return matched[0], f"zhipu:{model_id}"

        return None, None

    async def ocr(self, photo) -> Optional[str]:
        """向机器人发送 OCR 解答请求."""
        cmd = f"/ocr {self.instance}"
        results = await self.post(cmd, photo=photo, timeout=20, name="请求验证码解答")
        if results:
            return results.get("answer", None)
        else:
            return None

    async def send_log(self, message):
        """向机器人发送日志记录请求."""
        results = await self.post(f"/log {self.instance} {message}", name="发送日志到 Telegram ")
        return bool(results)

    async def send_msg(self, message):
        """向机器人发送即时日志记录请求."""
        results = await self.post(f"/msg {self.instance} {message}", name="发送即时日志到 Telegram ")
        return bool(results)

    async def infer(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """向机器人发送话术推测记录请求."""
        bio = BytesIO()
        bio.write(prompt.encode("utf-8"))
        bio.seek(0)
        bio.name = "data.txt"

        results = await self.post(f"/infer {self.instance}", timeout=120, file=bio, name="发送话术推测请求")
        if results:
            return results.get("answer", None), results.get("by", None)
        else:
            return None, None
