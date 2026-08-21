import asyncio

import pyrogram
import pytest

from embykeeper.telegram.pyrogram import Client


class FakeSession:
    def __init__(self, client):
        self.client = client
        self.stored_msg_ids = [1, 2, 3]
        self.recent_msg_ids = []
        self.stop_calls = 0
        self.start_calls = 0

    async def stop(self):
        self.stop_calls += 1

    async def start(self):
        self.start_calls += 1


def make_client():
    client = object.__new__(Client)
    client._stopping = False
    client._session_lifecycle_lock = asyncio.Lock()
    return client


def test_handle_updates_consumes_connection_timeout(monkeypatch):
    async def raise_timeout(self, updates):
        raise TimeoutError('Failed to invoke "updates.GetChannelDifference" after 10 retries')

    monkeypatch.setattr(pyrogram.Client, "handle_updates", raise_timeout)
    client = make_client()

    assert asyncio.run(client.handle_updates(object())) is None


def test_handle_updates_propagates_unexpected_timeout(monkeypatch):
    async def raise_timeout(self, updates):
        raise TimeoutError("unrelated operation timed out")

    monkeypatch.setattr(pyrogram.Client, "handle_updates", raise_timeout)
    client = make_client()

    with pytest.raises(TimeoutError, match="unrelated operation timed out"):
        asyncio.run(client.handle_updates(object()))


def test_handle_updates_propagates_unexpected_connection_error(monkeypatch):
    async def raise_connection_reset(self, updates):
        raise ConnectionResetError("connection reset")

    monkeypatch.setattr(pyrogram.Client, "handle_updates", raise_connection_reset)
    client = make_client()

    with pytest.raises(ConnectionResetError, match="connection reset"):
        asyncio.run(client.handle_updates(object()))


def test_handle_updates_consumes_connection_error_during_shutdown(monkeypatch):
    async def raise_connection_reset(self, updates):
        raise ConnectionResetError("connection reset")

    monkeypatch.setattr(pyrogram.Client, "handle_updates", raise_connection_reset)
    client = make_client()
    client._stopping = True

    assert asyncio.run(client.handle_updates(object())) is None


def test_session_restart_runs_while_client_is_active():
    async def run():
        client = make_client()
        session = client._guard_session_restart(FakeSession(client))

        await session.restart()

        assert session.stop_calls == 1
        assert session.start_calls == 1
        assert session.recent_msg_ids == [1, 2, 3]

    asyncio.run(run())


def test_session_restart_does_not_start_after_shutdown_begins():
    async def run():
        client = make_client()
        session = FakeSession(client)

        async def stop_during_shutdown():
            session.stop_calls += 1
            client._stopping = True

        session.stop = stop_during_shutdown
        client._guard_session_restart(session)

        await session.restart()

        assert session.stop_calls == 1
        assert session.start_calls == 0

    asyncio.run(run())


def test_get_session_guards_returned_session(monkeypatch):
    async def run():
        client = make_client()
        session = FakeSession(client)

        async def base_get_session(self, *args, **kwargs):
            return session

        monkeypatch.setattr(pyrogram.Client, "get_session", base_get_session)

        assert await client.get_session(is_media=True) is session
        assert session._embykeeper_restart_guarded is True

    asyncio.run(run())


def test_client_stop_prevents_in_flight_restart_from_starting(monkeypatch):
    async def run():
        client = make_client()
        session = FakeSession(client)
        restart_stopping = asyncio.Event()
        allow_restart_stop = asyncio.Event()

        async def session_stop():
            session.stop_calls += 1
            restart_stopping.set()
            await allow_restart_stop.wait()

        async def base_stop(self, *args, **kwargs):
            assert self._stopping is True
            return "stopped"

        session.stop = session_stop
        client._guard_session_restart(session)
        monkeypatch.setattr(pyrogram.Client, "stop", base_stop)

        restart_task = asyncio.create_task(session.restart())
        await restart_stopping.wait()
        stop_task = asyncio.create_task(client.stop())

        async with asyncio.timeout(1):
            while not client._stopping:
                await asyncio.sleep(0)

        allow_restart_stop.set()

        assert await restart_task is None
        assert await stop_task == "stopped"
        assert session.stop_calls == 1
        assert session.start_calls == 0

    asyncio.run(run())


def test_client_stop_marks_shutdown_before_delegating(monkeypatch):
    async def run():
        client = make_client()
        delegated = False

        async def base_stop(self, *args, **kwargs):
            nonlocal delegated
            delegated = True
            assert self._stopping is True
            return "stopped"

        monkeypatch.setattr(pyrogram.Client, "stop", base_stop)

        assert await client.stop() == "stopped"
        assert delegated is True

    asyncio.run(run())


def test_client_start_restores_shutdown_state_when_delegating_fails(monkeypatch):
    async def run():
        client = make_client()

        async def base_start(self):
            assert self._stopping is False
            raise RuntimeError("start failed")

        monkeypatch.setattr(pyrogram.Client, "start", base_start)

        with pytest.raises(RuntimeError, match="start failed"):
            await client.start()

        assert client._stopping is True

    asyncio.run(run())
