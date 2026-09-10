import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pyrogram import filters
from pyrogram.enums import MessageEntityType
from pyrogram.errors import FloodWait, InternalServerError, RPCError, ServiceUnavailable
from pyrogram.raw.types.messages import BotCallbackAnswer
from pyrogram.types import InlineKeyboardMarkup, Message

from embykeeper.runinfo import RunStatus
from embykeeper.utils import to_iterable

from ..link import Link
from . import BotCheckin

__ignore__ = True

VERIFY_PATTERN = r"请\s*(?P<called>.+?)\s*在\s*(?P<seconds>\d+)\s*秒内点击按钮"
VERIFY_BUTTON = "✅ 点击完成人类验证"
VERIFY_SUCCESS = "✅ 验证成功，祝您聊天愉快！"
VERIFY_WATCH = 120
VERIFY_TIMEOUT = 60
VERIFY_CLICK_ATTEMPTS = 3


def normalize_name(name: Optional[str]) -> str:
    """归一化昵称后再比较.

    抽查消息把被点名用户渲染为数学花体等 Unicode 变体 (如 𝓣𝓪𝓭𝓲𝓳𝓪), 直接比较必然失配,
    需先 NFKC 折叠回基础字母, 并忽略空白与大小写差异。
    """
    folded = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"\s+", "", folded).casefold()


@dataclass
class _Verification:
    reply_id: Optional[int]
    deadline: float
    message: Optional[Message] = None
    attempts: int = 0
    attempted: bool = False
    receipt: bool = False
    error: str = "未收到明确成功回执"

    @property
    def verified(self):
        return self.receipt


class EPubGroupChatCheckin(BotCheckin):
    name = "EPub 电子书库群组每日发言"
    chat_name = "libhsulife"
    verification_bot_id = 8161923203
    additional_auth = ["prime"]
    bot_use_captcha = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._verification_active = False
        self._verification_queue = asyncio.Queue()
        self._verification_states = {}
        self._verification_receipts = set()
        self._verification_deferred = []
        self._verification_tasks = []
        self._verification_task = None
        self._sent_ids = set()
        self._send_serial = 0
        self._send_completed = 0
        self._verification_chat_id = None
        self._watch_deadline = None

    def get_filter(self):
        return super().get_filter() & filters.user(self.verification_bot_id)

    def is_self(self, message: Message, called: Optional[str] = None, *, reply_id=None) -> bool:
        text = message.text or message.caption or ""
        match = re.search(VERIFY_PATTERN, text)
        if not match:
            return False
        called = called if called is not None else match.group("called")
        # Telegram 实体偏移使用 UTF-16; 只认被抽查姓名中的实体, 不认消息其他位置的提及.
        start = len(text[: match.start("called")].encode("utf-16-le")) // 2
        end = len(text[: match.end("called")].encode("utf-16-le")) // 2
        entities = message.entities if message.text else message.caption_entities
        targets = {
            getattr(entity.user, "id", None)
            for entity in entities or []
            if entity.type == MessageEntityType.TEXT_MENTION
            and start <= entity.offset < entity.offset + entity.length <= end
        }
        if targets:
            return targets == {self.client.me.id}

        reply_id = reply_id if reply_id is not None else message.reply_to_message_id
        if reply_id not in self._sent_ids:
            return False
        name = normalize_name(self.client.me.full_name)
        called = normalize_name(called)
        return bool(name) and called in (name, ":" + name)

    def _is_verification_source(self, message):
        if getattr(message.from_user, "id", None) != self.verification_bot_id or not message.chat:
            return False
        if self._verification_chat_id is not None:
            return message.chat.id == self._verification_chat_id
        if isinstance(self.chat_name, int):
            return message.chat.id == self.chat_name
        return (message.chat.username or "").casefold() == self.chat_name.lstrip("@").casefold()

    @staticmethod
    def _is_verification_success(text):
        return re.sub(r"\s+", "", text or "") == re.sub(r"\s+", "", VERIFY_SUCCESS)

    def _record_verification_receipt(self, message, received):
        if message.id in self._verification_receipts:
            return
        state = self._verification_states.get(message.id)
        if state is None:
            state = self._verification_states.get(message.reply_to_message_id)
        if state is None and message.reply_to_message_id in self._sent_ids:
            candidates = [
                s for s in self._verification_states.values() if s.reply_id == message.reply_to_message_id
            ]
            if len(candidates) == 1:
                state = candidates[0]
        if state is not None and received <= state.deadline:
            state.receipt = True
            self._verification_receipts.add(message.id)

    async def click_verification(self, state: _Verification) -> None:
        accepted = False
        try:
            while not state.verified and state.attempts < VERIFY_CLICK_ATTEMPTS:
                remaining = state.deadline - time.monotonic()
                if remaining <= 0:
                    state.error = "验证已超时"
                    return
                state.attempts += 1
                delay = state.attempts
                try:
                    async with asyncio.timeout(remaining):
                        response = await state.message.click(VERIFY_BUTTON, timeout=remaining)
                except asyncio.TimeoutError:
                    state.error = "验证点击超时"
                except FloodWait as e:
                    state.error = "验证点击受到 Telegram 频率限制"
                    delay = max(delay, e.value)
                except (OSError, InternalServerError, ServiceUnavailable):
                    state.error = "验证点击暂时无法连接 Telegram"
                except RPCError:
                    state.error = "验证点击发生 Telegram RPC 错误"
                    return
                except Exception as e:
                    state.error = f"验证点击失败 ({type(e).__name__})"
                    return
                else:
                    if not isinstance(response, BotCallbackAnswer):
                        state.error = "验证按钮未返回有效点击响应"
                        return
                    accepted = True
                    if time.monotonic() > state.deadline:
                        state.error = "验证已超时"
                        return
                    if self._is_verification_success(response.message):
                        state.receipt = True
                    else:
                        state.error = "未收到明确成功回执"
                    self.log.info("已发送人类验证点击, 等待确认验证结果.")
                    return
                if state.verified or state.attempts >= VERIFY_CLICK_ATTEMPTS:
                    return
                remaining = state.deadline - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(min(delay, remaining))
        finally:
            state.attempted = accepted
            self._verification_queue.put_nowait(None)

    async def _process_verification(self, message, received, send_serial):
        reply_id = message.reply_to_message_id
        related = (
            message.id in self._verification_states
            or reply_id in self._sent_ids
            or reply_id in self._verification_states
        )
        # 发送 RPC 返回 ID 前先缓冲; 不阻塞其他已关联挑战的点击和回执.
        if send_serial > self._send_completed and not related:
            self._verification_deferred.append((received, message, send_serial))
            return
        text = message.text or message.caption or ""
        if self._is_verification_success(text):
            self._record_verification_receipt(message, received)
            return
        match = re.search(VERIFY_PATTERN, text)
        if not match:
            return

        state = self._verification_states.get(message.id)
        if state is None:
            if self._watch_deadline is not None and received > self._watch_deadline:
                return
            if not self._sent_ids or (reply_id is not None and reply_id not in self._sent_ids):
                return
            if not self.is_self(message, match.group("called")):
                return
            remaining = min(int(match.group("seconds")), VERIFY_TIMEOUT)
            deadline = received + remaining
            if isinstance(message.date, datetime):
                remaining -= max(0, time.time() - message.date.timestamp())
                deadline = min(deadline, time.monotonic() + remaining)
            state = _Verification(reply_id, deadline)
            self._verification_states[message.id] = state
        elif not self.is_self(message, match.group("called"), reply_id=state.reply_id):
            return

        if state.verified:
            return
        if time.monotonic() >= state.deadline:
            state.error = "验证已超时"
            return
        markup = message.reply_markup
        if not isinstance(markup, InlineKeyboardMarkup) or not any(
            button.text == VERIFY_BUTTON and button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ):
            state.error = "未找到可点击的人类验证按钮"
            return
        state.message = message
        if state.attempted or state.attempts >= VERIFY_CLICK_ATTEMPTS:
            return
        state.attempted = True
        state.error = "未收到明确成功回执"
        self._verification_tasks.append(asyncio.create_task(self.click_verification(state)))

    async def watch_verification(self) -> None:
        while not self.finished.is_set():
            remaining = None
            if self._watch_deadline is not None:
                deadline = max(
                    [self._watch_deadline]
                    + [s.deadline for s in self._verification_states.values() if not s.verified]
                )
                remaining = max(0, deadline - time.monotonic())
            try:
                if not self._verification_queue.empty():
                    item = self._verification_queue.get_nowait()
                elif remaining == 0:
                    return
                else:
                    item = await asyncio.wait_for(self._verification_queue.get(), remaining)
            except asyncio.TimeoutError:
                return
            if item is not None:
                received, message, send_serial = item
                await self._process_verification(message, received, send_serial)
            else:
                deferred, self._verification_deferred = self._verification_deferred, []
                for received, message, send_serial in deferred:
                    await self._process_verification(message, received, send_serial)

    async def _send_with_verification(self, lines, retry):
        self._verification_active = True
        self._verification_task = asyncio.create_task(self.watch_verification())
        send_error = None
        try:
            await asyncio.sleep(10)
            for index, cmd in enumerate(to_iterable(lines)):
                if retry and not index:
                    await asyncio.sleep(self.bot_retry_wait)
                await asyncio.sleep(self.bot_send_interval)
                self._send_serial += 1
                try:
                    message = await self.send(cmd)
                    if not message or not message.id:
                        send_error = "发送结果缺少消息 ID, 无法关联验证"
                        break
                    self._sent_ids.add(message.id)
                    self._verification_chat_id = message.chat.id
                except (RPCError, OSError) as e:
                    send_error = f"发送发言失败 ({type(e).__name__})"
                    break
                finally:
                    self._send_completed = self._send_serial
                    self._verification_queue.put_nowait(None)
            watch = VERIFY_WATCH if self._sent_ids else 0
            self._watch_deadline = time.monotonic() + watch
            self._verification_queue.put_nowait(None)
            if send_error:
                self.log.warning(f"{send_error}, 停止后续发言并收口已发送消息的人类验证.")
            else:
                self.log.info(f"发言完毕, 继续守候人类验证抽查 ({watch} 秒).")
            await self._verification_task
            if self.finished.is_set():
                return
            unresolved = [s for s in self._verification_states.values() if not s.verified]
            if unresolved:
                reason = "; ".join(dict.fromkeys(s.error for s in unresolved))
                self.log.warning(f"发言后有 {len(unresolved)} 项人类验证未确认通过: {reason}.")
                reason = f"人类验证未确认通过: {reason}"
                return await self.finish(RunStatus.FAIL, f"{send_error}; {reason}" if send_error else reason)
            if send_error:
                return await self.finish(RunStatus.FAIL, send_error)
            message = "已发送发言, 人类验证已通过" if self._verification_states else "已发送发言, 未收到抽查"
            return await self.finish(message=message)
        finally:
            self._verification_active = False
            tasks = [self._verification_task, *self._verification_tasks]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._verification_task = None
            self._verification_tasks.clear()
            self._verification_states.clear()
            self._verification_receipts.clear()
            self._verification_deferred.clear()
            self._sent_ids.clear()
            self._send_serial = 0
            self._send_completed = 0
            self._verification_queue = asyncio.Queue()
            self._watch_deadline = None
            self._verification_chat_id = None

    async def send_checkin(self, retry=False):
        for _ in range(3):
            times = self.config.get("times", 2)
            min_letters = self.config.get("letters", 7)
            prompt = self.config.get(
                "prompt",
                f"请输出{times}行的诗, 所有行都至少{min_letters}个字, 必须严格遵守每行字数要求！最多{times+2}行, 只输出古诗内容, 禁止输出其他提示语言, 禁止输出逗号句号, 每行开头必须有标号'@@@'",
            )
            answer, by = await Link(self.client).gpt(prompt)
            if not answer:
                continue
            lines = [
                l.lstrip("@@@").strip()
                for l in answer.splitlines()
                if l.startswith("@@@") and len(l.strip()) >= min_letters + 3
            ]
            if len(lines) > times + 2 or len(lines) < times:
                continue
            else:
                for l in lines:
                    self.log.info(f"即将向群组发送水群消息: {l}.")
                return await self._send_with_verification(lines, retry)
        else:
            return await self.fail(message="无法生成发言内容")

    async def message_handler(self, client, message: Message, type=None):
        if not self._verification_active or not self._is_verification_source(message):
            return
        text = message.text or message.caption or ""
        if re.search(VERIFY_PATTERN, text) or self._is_verification_success(text):
            self._verification_queue.put_nowait((time.monotonic(), message, self._send_serial))
