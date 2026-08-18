import asyncio
from types import SimpleNamespace

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from embykeeper.runinfo import RunStatus
from embykeeper.telegram.checkiner import mooncake
from embykeeper.telegram.checkiner.mooncake import MooncakeCheckin
from embykeeper.turnstile import TurnstileService, _split_solver_urls


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.text = str(payload)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return next(self.responses)


def make_checkin(monkeypatch, session):
    checkin = object.__new__(MooncakeCheckin)
    checkin.log = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    checkin._handle_result = _handle_result
    checkin.retry = _retry
    checkin.fail = _fail
    monkeypatch.setattr(mooncake, "AsyncSession", lambda **kwargs: session)
    monkeypatch.setattr(mooncake, "config", SimpleNamespace(proxy=None, turnstile=None))
    return checkin


async def _handle_result(status, result):
    return RunStatus.SUCCESS if status == "checked_in" else RunStatus.NONEED


async def _retry():
    return RunStatus.RESCHEDULE


async def _fail(*args, **kwargs):
    return RunStatus.FAIL


def test_split_solver_urls_normalizes_and_deduplicates():
    assert _split_solver_urls(" http://one:8889/;http://two:8889\nhttp://one:8889 ") == [
        "http://one:8889",
        "http://two:8889",
    ]


def test_turnstile_service_uses_configured_solver_urls():
    service = TurnstileService(solver_url="http://one:8889,http://two:8889")

    assert service.solver_urls == ["http://one:8889", "http://two:8889"]
    assert service.solver_url == "http://one:8889"


def test_mooncake_unwraps_nested_api_data():
    checkin = object.__new__(MooncakeCheckin)

    assert checkin._unwrap_result({"data": {"status": "checked_in", "reward": 1}}) == {
        "status": "checked_in",
        "reward": 1,
    }
    assert checkin._unwrap_result({"status": "already_checked_in"}) == {"status": "already_checked_in"}


def test_mooncake_finds_checkin_webapp_button():
    checkin = object.__new__(MooncakeCheckin)
    message = SimpleNamespace(
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("签到", web_app=WebAppInfo(url="https://web.example/app?server=one"))]]
        )
    )

    assert checkin._find_checkin_webapp_url(message) == "https://web.example/app?server=one"


def test_do_checkin_submits_webapp_data_for_success(monkeypatch):
    session = FakeSession([FakeResponse(200, {"status": "checked_in", "reward": 2})])
    checkin = make_checkin(monkeypatch, session)

    result = asyncio.run(checkin.do_checkin("server-1", "init-data", "https://web.example/app"))

    assert result == RunStatus.SUCCESS
    assert session.requests == [
        (
            "https://embyguard.com/api/v1/servers/server-1/telegram/checkin",
            {"json": {"init_data": "init-data"}},
        )
    ]


def test_do_checkin_solves_turnstile_and_submits_challenge(monkeypatch):
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "status": "challenge",
                    "challenge": "challenge-1",
                    "site_key": "site-key",
                    "action": "checkin",
                    "cdata": "cdata-value",
                },
            ),
            FakeResponse(200, {"status": "checked_in", "reward": 3}),
        ]
    )
    checkin = make_checkin(monkeypatch, session)
    solved = []

    async def solve(website_url, website_key, action="", cdata=""):
        solved.append((website_url, website_key, action, cdata))
        return "turnstile-token"

    checkin._solve_turnstile = solve

    result = asyncio.run(checkin.do_checkin("server-1", "init-data", "https://web.example/app"))

    assert result == RunStatus.SUCCESS
    assert solved == [("https://web.example/app", "site-key", "checkin", "cdata-value")]
    assert session.requests[1] == (
        "https://embyguard.com/api/v1/servers/server-1/telegram/checkin/challenge-1",
        {"json": {"init_data": "init-data", "turnstile_token": "turnstile-token"}},
    )
