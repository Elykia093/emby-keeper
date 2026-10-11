import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pyrogram.raw.types.messages import BotCallbackAnswer
from pyrogram.types import Message

from embykeeper.runinfo import RunContext, RunStatus
from embykeeper.telegram.checkiner import _templ_ai
from embykeeper.telegram.checkiner._base import BotCheckin
from embykeeper.telegram.checkiner._templ_a import TemplateACheckin
from embykeeper.telegram.checkiner._templ_ai import TemplateAICheckin
from embykeeper.telegram.checkiner._templ_b import TemplateBCheckin
from embykeeper.telegram.link import Link

CHECKIN_CLASSES = [BotCheckin, TemplateACheckin, TemplateBCheckin, TemplateAICheckin]


@pytest.fixture
def gpt(monkeypatch):
    request = AsyncMock(return_value=("[IS_STATUS]", "test-model"))
    monkeypatch.setattr(Link, "gpt", request)
    return request


@pytest.fixture
def make_checkin(monkeypatch):
    monkeypatch.setattr(_templ_ai, "config", SimpleNamespace(checkiner=SimpleNamespace(ai={})))

    async def make(checkin_class=BotCheckin):
        client = SimpleNamespace(me=SimpleNamespace(full_name="Test User"), send_message=AsyncMock())
        context = RunContext(id="progress-test", status=RunStatus.RUNNING)
        checkin = checkin_class(client, context=context, retries=2, timeout=120)
        checkin.bot_username = "test_checkin_bot"
        assert await checkin.init()
        checkin.bot_retry_wait = 0
        checkin.bot_send_interval = 0
        checkin.log = Mock()
        return checkin

    return make


def assert_waiting_without_reply(checkin, gpt):
    gpt.assert_not_awaited()
    assert checkin.log.mock_calls == []
    checkin.client.send_message.assert_not_awaited()
    assert not checkin.finished.is_set()
    assert checkin.ctx.status == RunStatus.RUNNING
    assert checkin.current_retries == 0


@pytest.mark.parametrize("checkin_class", CHECKIN_CLASSES)
def test_progress_message_waits_for_following_success(make_checkin, gpt, checkin_class):
    async def run():
        checkin = await make_checkin(checkin_class)

        await checkin.message_handler(checkin.client, Message(id=1, text="签到中..."))

        assert_waiting_without_reply(checkin, gpt)

        await checkin.message_handler(checkin.client, Message(id=2, text="签到成功，获得 1 分，累计 10 分"))

        assert checkin.finished.is_set()
        assert checkin.ctx.status == RunStatus.SUCCESS
        assert checkin.ctx.status_info == "签到成功"
        assert checkin.current_retries == 0
        gpt.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "签到中",
        "簽到中……",
        "正在签到，请稍候...",
        "簽到中，請稍後。",
        "签到中，请稍等",
        "  签到中...\n",
    ],
)
def test_short_progress_variants_are_silent(make_checkin, gpt, text):
    async def run():
        checkin = await make_checkin()

        await checkin.message_handler(checkin.client, Message(id=1, text=text))

        assert_waiting_without_reply(checkin, gpt)

    asyncio.run(run())


def test_template_a_progress_callback_keeps_waiting(make_checkin, gpt):
    async def run():
        checkin = await make_checkin(TemplateACheckin)

        await checkin.on_button_answer(BotCallbackAnswer(cache_time=0, message="签到中..."))

        assert_waiting_without_reply(checkin, gpt)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("text", "status", "retries", "finished"),
    [
        ("签到中，签到成功", RunStatus.SUCCESS, 0, True),
        ("签到中，今日已签到", RunStatus.NONEED, 0, True),
        ("签到中，账户未注册", RunStatus.FAIL, float("inf"), True),
        ("签到中，尝试次数过多", RunStatus.FAIL, float("inf"), True),
        ("签到中，验证码错误", RunStatus.RUNNING, 1, False),
    ],
)
def test_checkin_results_are_not_hidden_by_progress_prefix(
    make_checkin, gpt, text, status, retries, finished
):
    async def run():
        checkin = await make_checkin()

        await checkin.message_handler(checkin.client, Message(id=1, text=text))

        assert checkin.ctx.status == status
        assert checkin.current_retries == retries
        assert checkin.finished.is_set() == finished
        gpt.assert_not_awaited()
        if finished:
            checkin.client.send_message.assert_not_awaited()
        else:
            checkin.client.send_message.assert_awaited_once_with("test_checkin_bot", "/checkin")

    asyncio.run(run())


@pytest.mark.parametrize("text", ["签到中，请输入验证码", "请选择图中的数字"])
def test_verification_and_unknown_text_still_use_ai(make_checkin, gpt, text):
    async def run():
        checkin = await make_checkin()

        await checkin.message_handler(checkin.client, Message(id=1, text=text))

        gpt.assert_awaited_once()
        assert text in gpt.await_args.args[0]
        assert "接收到异常返回信息" in checkin.log.warning.call_args.args[0]
        assert checkin.finished.is_set()
        assert checkin.ctx.status == RunStatus.FAIL

    asyncio.run(run())


@pytest.mark.parametrize("checkin_class", CHECKIN_CLASSES)
def test_captcha_photo_with_progress_caption_is_still_dispatched(
    monkeypatch, make_checkin, gpt, checkin_class
):
    async def run():
        checkin = await make_checkin(checkin_class)
        on_photo = AsyncMock()
        monkeypatch.setattr(checkin, "on_photo", on_photo)
        message = Message(id=1, caption="签到中...", photo=SimpleNamespace(file_id="test-photo"))

        await checkin.message_handler(checkin.client, message)

        on_photo.assert_awaited_once_with(message)
        assert_waiting_without_reply(checkin, gpt)

    asyncio.run(run())
