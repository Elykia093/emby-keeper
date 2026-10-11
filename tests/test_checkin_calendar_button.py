"""测试签到日历按钮场景的识别"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from embykeeper.runinfo import RunContext, RunStatus
from embykeeper.telegram.checkiner._base import BotCheckin


def make_checkin():
    """创建测试用的签到器实例"""
    client = SimpleNamespace(me=SimpleNamespace(full_name="Test User"), send_message=AsyncMock())
    context = RunContext(id="calendar-test", status=RunStatus.RUNNING)
    checkin = BotCheckin(client, context=context, retries=2, timeout=120)
    checkin.bot_username = "test_bot"
    checkin.bot_retry_wait = 0
    checkin.bot_send_interval = 0
    checkin.log = Mock()
    return checkin


def create_message(text: str, has_button: bool = False):
    """创建模拟消息，可选带按钮"""
    msg = Mock(spec=Message)
    msg.text = text
    msg.caption = None
    msg.photo = None
    msg.video = None
    msg.animation = None
    msg.document = None
    msg.sticker = None
    msg.web_page = None
    if has_button:
        button = InlineKeyboardButton(text="签到日历", callback_data="checkin_calendar")
        msg.reply_markup = InlineKeyboardMarkup([[button]])
    else:
        msg.reply_markup = None
    return msg


def test_already_checked_with_calendar_button():
    """测试带签到日历按钮的已签到消息"""
    checkin = make_checkin()

    async def run_test():
        assert await checkin.init()
        msg = create_message("您已经连续签到 12 天了，请继续坚持哦😊", has_button=True)
        await checkin.message_handler(None, msg)
        await asyncio.sleep(0.01)

        # 应该识别为已签到
        assert checkin.finished.is_set()
        assert checkin.ctx.status == RunStatus.NONEED
        checkin.log.info.assert_called_once()
        assert "已经签到" in str(checkin.log.info.call_args)

    asyncio.run(run_test())


def test_checkin_success_with_streak_info():
    """测试带连续签到天数的成功消息"""
    checkin = make_checkin()

    async def run_test():
        assert await checkin.init()
        # 模拟签到成功，显示连续天数
        msg = create_message("签到成功！您已连续签到 7 天")
        await checkin.message_handler(None, msg)
        await asyncio.sleep(0.01)

        # 应该识别为签到成功
        assert checkin.finished.is_set()
        assert checkin.ctx.status == RunStatus.SUCCESS

    asyncio.run(run_test())


def test_points_and_streak_message():
    """测试积分+连续签到的复合消息"""
    checkin = make_checkin()

    async def run_test():
        assert await checkin.init()
        msg = create_message("水群也有积分，还不赶紧试试😘\n您已经连续签到 12 天了，请继续坚持哦😊")
        await checkin.message_handler(None, msg)
        await asyncio.sleep(0.01)

        # 应该识别为已签到（因为包含"已经...签到"）
        assert checkin.finished.is_set()
        assert checkin.ctx.status == RunStatus.NONEED

    asyncio.run(run_test())


def test_calendar_button_not_clicked():
    """测试签到日历按钮不会被自动点击"""
    checkin = make_checkin()

    async def run_test():
        assert await checkin.init()
        msg = create_message("您已经连续签到 12 天了", has_button=True)
        await checkin.message_handler(None, msg)
        await asyncio.sleep(0.01)

        # 确认已完成签到
        assert checkin.finished.is_set()
        # 确认没有发送任何消息（没有点击按钮）
        checkin.client.send_message.assert_not_awaited()

    asyncio.run(run_test())
