import asyncio
import random
import emoji
from pyrogram.types import Message
from pyrogram.errors import RPCError

from ...runinfo import RunStatus
from ..link import Link
from . import AnswerBotCheckin


class TerminusCheckin(AnswerBotCheckin):
    name = "终点站"
    bot_username = "EmbyPublicBot"
    bot_checkin_cmd = ["/cancel", "/checkin"]
    bot_text_ignore = ["会话已取消", "没有活跃的会话"]
    bot_checked_keywords = ["今天已签到"]
    additional_auth = ["visual"]
    max_retries = 1
    # 验证码仅在当前会话的 30 秒内有效, 不能重放历史图片.
    bot_use_history = None

    async def on_text(self, message: Message, text: str):
        if text and "签到机会已用完" in text:
            self.log.warning("今日签到机会不可用, 签到状态未确认.")
            return await self.finish(RunStatus.FAIL, "今日签到机会不可用, 签到状态未确认")
        if text and "回答超时" in text and "今日不能再签到" in text:
            self.log.warning("签到失败: 回答超时, 今日不能再签到.")
            return await self.finish(RunStatus.FAIL, "回答超时, 今日不能再签到")
        return await super().on_text(message, text)

    async def on_photo(self, message: Message):
        """分析分析传入的验证码图片并返回验证码."""
        if message.reply_markup:
            clean = lambda o: emoji.replace_emoji(o, "").replace(" ", "")
            keys = [k for r in message.reply_markup.inline_keyboard for k in r]
            options = [k.text for k in keys]
            options_cleaned = [clean(o) for o in options]
            if len(options) < 2:
                return
            for i in range(3):
                result, by = await Link(self.client).visual(message.photo.file_id, options_cleaned)
                if result:
                    self.log.debug(f"已通过远端 ({by}) 解析答案: {result}.")
                    break
                else:
                    self.log.warning(f"远端解析失败, 正在重试解析 ({i + 1}/3).")
            else:
                self.log.warning(f"签到失败: 验证码识别错误.")
                return await self.fail()
            result = options[options_cleaned.index(result)]
            await asyncio.sleep(random.uniform(0.5, 1.5))
            try:
                await message.click(result)
            except RPCError:
                self.log.warning("按钮点击失败.")
