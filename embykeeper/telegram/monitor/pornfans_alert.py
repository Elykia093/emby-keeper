from datetime import datetime, timedelta
import random
import re

import asyncio
from typing import List
from cachetools import TTLCache
from pyrogram.types import Message, User, Chat
from pyrogram.enums import ChatMemberStatus, MessageServiceType, MessageEntityType
from pyrogram.errors import BadRequest

from ..lock import pornfans_alert, pornfans_messager_mids
from . import Monitor

__ignore__ = True


class PornfansAlertMonitor(Monitor):
    name = "PornFans 风险急停监控"
    chat_name = ["embytestflight", "PornFans_Chat"]
    additional_auth = ["pornemby_pack"]
    allow_edit = True
    debug_no_log = True
    trigger_interval = 0
    trigger_sem = None

    user_alert_keywords = ["脚本", "真人", "@admin", "机器人", "/report"]
    admin_alert_keywords = ["封脚本", "抓脚本"]
    alert_reply_keywords = ["真人", "脚本", "每次", "在吗", "机器", "封", "warn", "ban", "回", "说"]
    alert_reply_except_keywords = ["不要回复", "别回复", "勿回复"]
    reply_words = ["?" * (i + 1) for i in range(3)] + ["嗯?", "欸?", "🤔"]
    reply_interval = 7200

    async def init(self):
        self.lock = asyncio.Lock()
        self.last_reply = None
        self.alert_remaining = 0.0
        self.member_status_cache = TTLCache(maxsize=128, ttl=86400)
        self.member_status_cache_lock = asyncio.Lock()
        self.monitor_task = asyncio.create_task(self.monitor())
        self.pin_checked = False
        self.pin_checked_lock = False
        return True

    async def check_admin(self, chat: Chat, user: User):
        if not user:
            return True
        if user.is_bot:
            return False
        async with self.member_status_cache_lock:
            if not user.id in self.member_status_cache:
                try:
                    member = await self.client.get_chat_member(chat.id, user.id)
                    self.member_status_cache[user.id] = member.status
                except BadRequest:
                    return False
        if self.member_status_cache[user.id] in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return True

    def check_keyword(self, message: Message, keywords: List[str]):
        content = message.text or message.caption
        if content:
            for k in keywords:
                match = re.search(k, content)
                if match:
                    return match.group(0)

    async def monitor(self):
        while True:
            await self.lock.acquire()
            while self.alert_remaining > 0:
                pornfans_alert[self.client.me.id] = True
                t = datetime.now()
                self.lock.release()
                await asyncio.sleep(1)
                await self.lock.acquire()
                self.alert_remaining -= (datetime.now() - t).total_seconds()
            else:
                pornfans_alert[self.client.me.id] = False
            self.lock.release()
            await asyncio.sleep(1)

    async def set_alert(self, time: float = None, reason: str = None):
        if time:
            async with self.lock:
                if self.alert_remaining > time:
                    return
                else:
                    msg = f"PornFans 风险急停被触发, 停止操作 {time} 秒"
                    if reason:
                        msg += f" (原因: {reason})"
                    msg += "."
                    self.log.warning(msg)
                    self.alert_remaining = time
        else:
            msg = "PornFans 风险急停被触发, 所有操作永久停止"
            if reason:
                msg += f" (原因: {reason})"
            msg += "."
            self.log.bind(msg=True).error(msg)
            async with self.lock:
                self.alert_remaining = float("inf")

    async def on_trigger(self, message: Message, key, reply):
        # 管理员回复水群消息, 永久停止, 若存在关键词即回复
        # 用户回复水群消息, 停止 3600 秒, 若存在关键词即回复
        if message.reply_to_message_id and message.reply_to_message_id in pornfans_messager_mids.get(
            self.client.me.id, []
        ):
            if await self.check_admin(message.chat, message.from_user):
                await self.set_alert(reason="管理员回复了水群消息")
                self.log.bind(msg=True).warning("PornFans 管理员回复了您的自动水群消息, 已急停, 请查看.")
            else:
                await self.set_alert(3600, reason="非管理员回复了水群消息")
            if self.check_keyword(message, self.alert_reply_keywords):
                if not self.check_keyword(message, self.alert_reply_except_keywords):
                    if (not self.last_reply) or (
                        self.last_reply < datetime.now() - timedelta(seconds=self.reply_interval)
                    ):
                        await asyncio.sleep(random.uniform(5, 15))
                        await message.reply(random.choice(self.reply_words))
                        self.last_reply = datetime.now()
                        self.log.bind(msg=True).warning("PornFans 群中有人回复了您的自动水群消息, 已回复, 请查看.")
            return

        # 管理员 @ 当前用户, 永久停止
        # 非管理员 @ 当前用户, 停止 3600 秒
        if message.entities:
            for entity in message.entities:
                if (
                    entity.type == MessageEntityType.MENTION
                    and entity.user
                    and entity.user.id == self.client.me.id
                ):
                    if await self.check_admin(message.chat, message.from_user):
                        await self.set_alert(reason="管理员 @ 了当前用户")
                        self.log.bind(msg=True).warning("PornFans 管理员回复了您的自动水群消息, 已急停, 请查看.")
                    else:
                        await self.set_alert(3600, reason="非管理员 @ 了当前用户")
                    return

        # 新置顶消息包含关键词, 停止 86400 秒
        if message.service == MessageServiceType.PINNED_MESSAGE:
            keyword = self.check_keyword(
                message.pinned_message, self.user_alert_keywords + self.admin_alert_keywords
            )
            if keyword:
                await self.set_alert(86400, reason=f'有新消息被置顶, 且包含风险关键词: "{keyword}"')
            else:
                await self.set_alert(3600, reason="有新消息被置顶")
            return

        # 管理员发送消息包含关键词, 停止 86400 秒
        # 用户发送消息包含关键词, 停止 1800 秒
        keyword = self.check_keyword(message, self.user_alert_keywords + self.admin_alert_keywords)
        if keyword:
            if await self.check_admin(message.chat, message.from_user):
                await self.set_alert(86400, reason=f'管理员发送了消息, 且包含风险关键词: "{keyword}"')
