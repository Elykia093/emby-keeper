import asyncio

from embykeeper.utils import to_iterable

from ..link import Link
from . import BotCheckin

__ignore__ = True


class EPubGroupChatCheckin(BotCheckin):
    name = "EPub 电子书库群组每日发言"
    chat_name = "libhsulife"
    additional_auth = ["prime"]
    bot_use_captcha = False

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
                await asyncio.sleep(10)
                cmds = to_iterable(lines)
                for i, cmd in enumerate(cmds):
                    if retry and not i:
                        await asyncio.sleep(self.bot_retry_wait)
                    if i < len(cmds):
                        await asyncio.sleep(self.bot_send_interval)
                    await self.send(cmd)
                await self.finish(message="已发送发言")
                return
        else:
            return await self.fail(message="无法生成发言内容")

    async def message_handler(*args, **kw):
        return
