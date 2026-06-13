import asyncio
import random
import string
from urllib.parse import parse_qs, urlparse

from faker import Faker
import httpx
from pyrogram.types import Message
from pyrogram import filters
from pyrogram.raw.functions.messages import RequestWebView
from pyrogram.errors import MessageIdInvalid

from embykeeper.config import config
from embykeeper.utils import get_proxy_str

from ..link import Link
from . import Monitor

misty_monitor_pool = {}


class WokeMonitor(Monitor):
    name = "蜗壳"
    chat_name = "Walking_Chat"
    chat_keyword = r"可注册人数: (?!0$)"
    bot_username = "Readsnail_bot"
    notify_create_name = True
    additional_auth = ["prime"]
    allow_edit = False

    async def solve_captcha(self, url: str):
        token = await Link(self.client).captcha("woke")
        if not token:
            return False
        else:
            scheme = urlparse(url)
            params = parse_qs(scheme.query)
            url_submit = scheme._replace(path="/api/verify", query="", fragment="").geturl()
            uuid = params.get("id", [None])[0]
            origin = scheme._replace(path="/", query="", fragment="").geturl()
            useragent = Faker().safari()
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": url,
                "Origin": origin,
                "User-Agent": useragent,
            }
            data = {
                "uuid": uuid,
                "cf-turnstile-response": token,
            }
            try:
                async with httpx.AsyncClient(http2=True, proxy=get_proxy_str(config.proxy)) as client:
                    resp = await client.post(url_submit, headers=headers, data=data)
                    result = resp.text
                    if "完成" in result:
                        return True
            except:
                return False

    async def on_trigger(self, message: Message, key, reply):
        for i in range(3):
            await self.client.send_message(self.bot_username, "/cancel")
            await asyncio.sleep(random.uniform(1, 2))
            if i:
                self.log.info(f"正在重试注册 ({i}/3).")
            try:
                msg_start = await self.client.wait_reply(self.bot_username, f"/start")
            except asyncio.TimeoutError:
                self.log.warning("发送消息无响应, 无法注册.")
                return
            text = msg_start.text or msg_start.caption
            if not "您还未注册" in text:
                self.log.info("账户已注册, 无需抢注.")
                return
            async with self.client.catch_reply(self.bot_username) as f:
                try:
                    msg = await msg_start.click("创建账户", timeout=1)
                except (TimeoutError, MessageIdInvalid):
                    pass
                except ValueError:
                    self.log.warning("未能找到注册按钮, 无法注册.")
                    return
                try:
                    msg: Message = await asyncio.wait_for(f, timeout=10)
                except asyncio.TimeoutError:
                    self.log.warning("点击注册按钮无响应, 无法注册.")
                    return
            text = msg.text or msg.caption
            if msg.text and "先加入" in msg.text:
                self.log.warning("账户错误, 无法注册.")
                continue
            elif "完成验证" in text:
                self.log.info("需要验证, 正在解析.")
                url = None
                if msg.reply_markup:
                    buttons = [button for line in msg.reply_markup.inline_keyboard for button in line]
                    for b in buttons:
                        if "验证" in b.text and b.web_app:
                            url = b.web_app.url
                            break
                if not url:
                    self.log.warning("需要验证身份但没有找到 URL, 无法注册.")
                    return
                bot_peer = await self.client.resolve_peer(self.bot_username)
                url_auth = (
                    await self.client.invoke(
                        RequestWebView(peer=bot_peer, bot=bot_peer, platform="ios", url=url)
                    )
                ).url
                if not await self.solve_captcha(url_auth):
                    self.log.warning("验证码解析失败, 无法注册.")
                    return
                else:
                    await asyncio.sleep(random.uniform(3, 5))
                    self.log.info("已成功验证, 继续进行注册流程.")
                async with self.client.catch_reply(
                    self.bot_username, filter=~filters.regex("请耐心等待")
                ) as f:
                    try:
                        msg = await msg_start.click("创建账户", timeout=1)
                    except (TimeoutError, MessageIdInvalid):
                        pass
                    except ValueError:
                        self.log.warning("未能找到注册按钮, 无法注册.")
                        return
                    try:
                        msg: Message = await asyncio.wait_for(f, timeout=10)
                    except asyncio.TimeoutError:
                        self.log.warning("点击注册按钮无响应, 无法注册.")
                        return
                    if "可注册名额不足" in msg:
                        self.log.warning("名额不足, 无法注册.")
                        return
                    else:
                        self.log.bind(msg=True).info(f"已在 Bot @{self.bot_username} 成功创建用户, 请查看.")
                        return
