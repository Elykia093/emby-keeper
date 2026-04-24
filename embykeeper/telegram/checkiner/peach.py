import asyncio
import random
from pyrogram.types import Message
from pyrogram.errors import Timeout

from . import BotCheckin


class PeachCheckin(BotCheckin):
    name = "Peach"
    bot_username = "peach_emby_bot"
    bot_checkin_cmd = "/start"
    bot_captcha_len = 4
    bot_checkin_caption_pat = "请输入验证码"

    async def message_handler(self, client, message: Message):
        if message.caption and "欢迎使用" in message.caption and message.reply_markup:
            keys = [k.text for r in message.reply_markup.inline_keyboard for k in r]
            for k in keys:
                if "签到" in k:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    try:
                        await message.click(k)
                    except (TimeoutError, Timeout) as e:
                        self.log.debug(f"点击签到按钮超时，继续等待后续消息：{e}")
                    return
            else:
                self.log.warning(f"签到失败: 账户错误.")
                return await self.fail()
        await super().message_handler(client, message)
