import asyncio
from types import SimpleNamespace

import pytest

import embykeeper.emby.api as emby_api_module
import embykeeper.emby.main as emby_main_module
from embykeeper.emby.api import Emby, EmbyPlayError, PlaySessionResult
from embykeeper.emby.main import EmbyManager
from embykeeper.runinfo import RunStatus
from embykeeper.schema import EmbyAccount


@pytest.fixture(autouse=True)
def restore_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def make_account(**overrides):
    data = {
        "url": "https://example.com:443",
        "username": "tester",
        "password": "secret",
        "time": 30,
        "allow_multiple": True,
        "allow_stream": False,
    }
    data.update(overrides)
    return EmbyAccount(**data)


async def fast_sleep(*args, **kwargs):
    return None


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json_data

    async def aclose(self):
        return None


class DummyTask:
    def cancel(self):
        return None

    def __await__(self):
        async def _done():
            return None

        return _done().__await__()


def fake_create_task(coro):
    coro.close()
    return DummyTask()


def make_logger():
    return SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        bind=lambda **kwargs: make_logger(),
    )


def test_watch_skips_play_for_login_only(monkeypatch):
    monkeypatch.setattr(emby_api_module.asyncio, "sleep", fast_sleep)
    account = make_account(time=-1)
    emby = Emby(account)

    async def unexpected_play(*args, **kwargs):
        raise AssertionError("play() should not be called when time < 0")

    monkeypatch.setattr(emby, "play", unexpected_play)

    assert asyncio.run(emby.watch()) is True


def test_watch_allows_success_without_playcount_increment(monkeypatch):
    monkeypatch.setattr(emby_api_module.asyncio, "sleep", fast_sleep)
    account = make_account(time=30)
    emby = Emby(account)
    emby.items = {
        "video-1": {
            "Id": "video-1",
            "Name": "Demo",
            "MediaType": "Video",
            "RunTimeTicks": 600000000,
        }
    }

    async def fake_play(*args, **kwargs):
        return PlaySessionResult(
            session_started=True,
            progress_updates=2,
            stop_reported=True,
            last_position_ticks=300000000,
            stop_endpoint="/Sessions/Playing/Stopped",
        )

    async def fake_get_item(*args, **kwargs):
        return {"Id": "video-1", "UserData": {"PlayCount": 0}}

    monkeypatch.setattr(emby, "play", fake_play)
    monkeypatch.setattr(emby, "get_item", fake_get_item)

    assert asyncio.run(emby.watch()) is True


def test_watch_caps_requested_play_time(monkeypatch):
    monkeypatch.setattr(emby_api_module.asyncio, "sleep", fast_sleep)
    account = make_account(time=5)
    emby = Emby(account)
    emby.items = {
        "video-1": {
            "Id": "video-1",
            "Name": "Short clip",
            "MediaType": "Video",
            "RunTimeTicks": 80000000,
        }
    }
    recorded = {}

    async def fake_play(*args, **kwargs):
        recorded["time"] = kwargs["time"]
        recorded["total_ticks"] = kwargs["total_ticks"]
        return PlaySessionResult(
            session_started=True,
            progress_updates=1,
            stop_reported=True,
            last_position_ticks=50000000,
            stop_endpoint="/Sessions/Playing/Stopped",
        )

    async def fake_get_item(*args, **kwargs):
        return {"Id": "video-1", "UserData": {"PlayCount": 0}}

    monkeypatch.setattr(emby, "play", fake_play)
    monkeypatch.setattr(emby, "get_item", fake_get_item)

    assert asyncio.run(emby.watch()) is True
    assert recorded["time"] == pytest.approx(5)
    assert recorded["total_ticks"] == 80000000


def test_play_uses_stable_start_ticks_and_stopped_endpoint(monkeypatch):
    monkeypatch.setattr(emby_api_module.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(emby_api_module.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(emby_api_module.random, "uniform", lambda a, b: a)
    monkeypatch.setattr(emby_api_module.random, "random", lambda: 0.5)

    account = make_account()
    emby = Emby(account)
    emby._user_id = "user-1"
    emby._token = "token-1"
    requests = []

    async def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path.endswith("/AdditionalParts"):
            return FakeResponse({})
        if path.endswith("/PlaybackInfo"):
            return FakeResponse(
                {
                    "PlaySessionId": "play-session-1",
                    "MediaSources": [
                        {"Id": "media-source-1", "DirectStreamUrl": "/Videos/video-1/original.mp4"}
                    ],
                }
            )
        if path == "/Sessions/Playing":
            return FakeResponse({})
        if path == "/Sessions/Playing/Progress":
            return FakeResponse({})
        if path == "/Sessions/Playing/Stopped":
            return FakeResponse({})
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(emby, "_request", fake_request)

    result = asyncio.run(
        emby.play(
            {"Id": "video-1", "Name": "Feature", "RunTimeTicks": 80000000},
            time=5,
            total_ticks=80000000,
        )
    )

    assert result.is_successful
    assert result.stop_endpoint == "/Sessions/Playing/Stopped"

    payloads = [
        kwargs["json"]
        for method, path, kwargs in requests
        if path in {"/Sessions/Playing", "/Sessions/Playing/Progress", "/Sessions/Playing/Stopped"}
    ]
    assert payloads
    assert len({payload["PlaybackStartTimeTicks"] for payload in payloads}) == 1
    assert payloads[-1]["PositionTicks"] > 0
    assert payloads[-1]["PositionTicks"] <= 80000000
    assert requests[-1][1] == "/Sessions/Playing/Stopped"


def test_play_raises_clear_error_without_media_sources(monkeypatch):
    monkeypatch.setattr(emby_api_module.asyncio, "sleep", fast_sleep)

    account = make_account()
    emby = Emby(account)
    emby._user_id = "user-1"
    emby._token = "token-1"

    async def fake_request(method, path, **kwargs):
        if path.endswith("/AdditionalParts"):
            return FakeResponse({})
        if path.endswith("/PlaybackInfo"):
            return FakeResponse({"PlaySessionId": "play-session-1", "MediaSources": []})
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(emby, "_request", fake_request)

    with pytest.raises(EmbyPlayError, match="无可用媒体源"):
        asyncio.run(emby.play({"Id": "video-1", "Name": "Broken"}, time=12))


def test_watch_main_handles_emby_init_exception_without_nameerror(monkeypatch):
    bad = make_account(username="bad")
    good = make_account(username="good")

    class FakeConfig:
        emby = SimpleNamespace(concurrency=1)

        def on_list_change(self, *args, **kwargs):
            return None

    monkeypatch.setattr(emby_main_module, "config", FakeConfig())

    class FakeEmby:
        def __init__(self, account):
            if account.username == "bad":
                raise RuntimeError("boom")
            self.account = account
            self.log = make_logger()
            self._user_id = "user-1"
            self.items = {}

        @property
        def user_id(self):
            return self._user_id

        async def login(self):
            return True

        async def load_main_page(self):
            self.items = {
                "video-1": {
                    "Id": "video-1",
                    "Name": "Demo",
                    "MediaType": "Video",
                    "RunTimeTicks": 600000000,
                }
            }

        async def watch(self):
            return True

    monkeypatch.setattr(emby_main_module, "Emby", FakeEmby)
    monkeypatch.setattr(emby_main_module, "show_exception", lambda *args, **kwargs: None)
    monkeypatch.setattr(emby_main_module.RunContext, "save", lambda self: None)

    manager = EmbyManager()
    result = asyncio.run(manager._watch_main([bad, good], instant=True))

    assert result.status == RunStatus.FAIL
