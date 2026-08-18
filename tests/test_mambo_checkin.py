import asyncio

import pytest

from embykeeper.runinfo import RunStatus
from embykeeper.telegram.checkiner.mambo import (
    MamboCheckin,
    build_login_payload,
    classify_checkin_response,
    classify_status_response,
    normalize_base_url,
    verification_required,
)
from embykeeper.telegram.dynamic import get_cls


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

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return next(self.responses)


def make_checkin(config):
    checkin = object.__new__(MamboCheckin)
    checkin.config = config
    checkin._timeout = 60
    return checkin


def test_dynamic_loader_resolves_configured_web_checkiners():
    classes = get_cls("checkiner", ["kotomi", "mambo"])

    assert {cls.__name__ for cls in classes} == {"KotomiCheckin", "MamboCheckin"}


def test_normalize_base_url_adds_https_and_strips_slash():
    assert normalize_base_url("mambo-hachimi.biliblili.uk/") == ("https://mambo-hachimi.biliblili.uk")


def test_build_login_payload_matches_frontend_contract():
    assert build_login_payload(" alice ", "secret", "challenge") == {
        "userName": "alice",
        "password": "secret",
        "recaptchaToken": "",
        "verificationToken": "challenge",
    }


def test_verification_required_for_enabled_turnstile():
    settings = {"login": {"type": "cloudflare_turnstile_v2", "enabled": True}}
    assert verification_required(settings, "login")


def test_verification_not_required_for_disabled_action():
    settings = {"checkin": {"type": "cloudflare_turnstile_v2", "enabled": False}}
    assert not verification_required(settings, "checkin")


def test_enabled_action_without_type_is_treated_as_requiring_verification():
    assert verification_required({"checkin": {"enabled": True}}, "checkin")


def test_status_response_reports_already_checked_in():
    assert classify_status_response(200, {"hasCheckedInToday": True}) == (RunStatus.NONEED, "今日已签到")


def test_status_response_does_not_treat_ambiguous_200_as_success():
    assert classify_status_response(200, {"message": "unexpected"}) == (
        RunStatus.FAIL,
        "unexpected",
    )


def test_status_response_honors_explicit_failure():
    assert classify_status_response(
        200,
        {"success": False, "hasCheckedInToday": False, "message": "status unavailable"},
    ) == (RunStatus.FAIL, "status unavailable")


def test_status_response_reports_security_block():
    assert classify_status_response(403, "<html>blocked</html>") == (
        RunStatus.FAIL,
        "站点安全验证拦截",
    )


def test_checkin_response_formats_reward():
    assert classify_checkin_response(
        200,
        {"success": True, "amount": 1.77, "currencyUnit": "STARRY", "balance": 15.9},
    ) == (RunStatus.SUCCESS, "+1.77 STARRY")


def test_checkin_response_uses_explicit_already_checked_flag():
    assert classify_checkin_response(400, {"success": False, "hasCheckedIn": True, "message": "already"}) == (
        RunStatus.NONEED,
        "今日已签到",
    )


def test_checkin_response_rejects_already_flag_from_server_error():
    assert classify_checkin_response(
        503,
        {"success": False, "hasCheckedIn": True, "message": "service unavailable"},
    ) == (RunStatus.FAIL, "service unavailable")


def test_checkin_response_rejects_html_or_unknown_payload():
    assert classify_checkin_response(200, "<html>challenge</html>") == (
        RunStatus.FAIL,
        "签到失败",
    )


def test_checkin_response_reports_security_block():
    assert classify_checkin_response(403, "<html>blocked</html>") == (
        RunStatus.FAIL,
        "站点安全验证拦截",
    )


def test_verification_settings_report_security_block():
    session = FakeSession([FakeResponse(403, "<html>blocked</html>")])
    checkin = make_checkin({})

    with pytest.raises(RuntimeError, match="站点安全验证拦截"):
        asyncio.run(checkin.get_verification_settings(session))


def test_api_flow_logs_in_checks_status_and_checks_in():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "login": {"enabled": True, "type": "cloudflare_turnstile_v2"},
                    "checkin": {"enabled": True, "type": "cloudflare_turnstile_v2"},
                },
            ),
            FakeResponse(200, {"token": "access-token", "user": {"userName": "alice"}}),
            FakeResponse(200, {"hasCheckedInToday": False}),
            FakeResponse(200, {"success": True, "amount": 2.5, "currencyUnit": "STARRY"}),
        ]
    )
    checkin = make_checkin(
        {
            "username": "alice",
            "password": "secret",
            "login_verification_token": "login-challenge",
            "checkin_verification_token": "checkin-challenge",
        }
    )

    assert asyncio.run(checkin.run_api_flow(session)) == (
        RunStatus.SUCCESS,
        "+2.5 STARRY",
    )
    assert [request[0] for request in session.requests] == ["GET", "POST", "GET", "POST"]
    assert session.requests[1][2]["json"] == {
        "userName": "alice",
        "password": "secret",
        "recaptchaToken": "",
        "verificationToken": "login-challenge",
    }
    assert session.requests[2][2]["headers"] == {"Authorization": "Bearer access-token"}
    assert session.requests[3][2]["json"] == {"verificationToken": "checkin-challenge"}


def test_api_flow_stops_before_login_when_turnstile_token_is_missing():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "login": {"enabled": True, "type": "cloudflare_turnstile_v2"},
                    "checkin": {"enabled": True, "type": "cloudflare_turnstile_v2"},
                },
            )
        ]
    )
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(session)) == (
        RunStatus.FAIL,
        "登录需要 Turnstile 验证",
    )
    assert len(session.requests) == 1


def test_api_flow_stops_before_checkin_when_turnstile_token_is_missing():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "login": {"enabled": False},
                    "checkin": {"enabled": True, "type": "cloudflare_turnstile_v2"},
                },
            ),
            FakeResponse(200, {"token": "access-token"}),
            FakeResponse(200, {"hasCheckedInToday": False}),
        ]
    )
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(session)) == (
        RunStatus.FAIL,
        "签到需要 Turnstile 验证",
    )
    assert [request[0] for request in session.requests] == ["GET", "POST", "GET"]


def test_api_flow_reports_security_block_from_login_api():
    session = FakeSession(
        [
            FakeResponse(200, {"login": {"enabled": False}, "checkin": {"enabled": False}}),
            FakeResponse(403, "<html>blocked</html>"),
        ]
    )
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(session)) == (
        RunStatus.FAIL,
        "站点安全验证拦截",
    )
    assert [request[0] for request in session.requests] == ["GET", "POST"]


def test_api_flow_uses_access_token_and_stops_when_already_checked_in():
    session = FakeSession([FakeResponse(200, {"hasCheckedInToday": True})])
    checkin = make_checkin({"access_token": "existing-token"})

    assert asyncio.run(checkin.run_api_flow(session)) == (
        RunStatus.NONEED,
        "今日已签到",
    )
    assert [request[0] for request in session.requests] == ["GET"]
    assert session.requests[0][2]["headers"] == {"Authorization": "Bearer existing-token"}


def test_api_flow_with_access_token_loads_settings_only_when_checkin_is_needed():
    session = FakeSession(
        [
            FakeResponse(200, {"hasCheckedInToday": False}),
            FakeResponse(200, {"checkin": {"enabled": True, "type": "cloudflare_turnstile_v2"}}),
            FakeResponse(200, {"success": True, "amount": 2.5, "currencyUnit": "STARRY"}),
        ]
    )
    checkin = make_checkin(
        {
            "access_token": "existing-token",
            "checkin_verification_token": "checkin-challenge",
        }
    )

    assert asyncio.run(checkin.run_api_flow(session)) == (RunStatus.SUCCESS, "+2.5 STARRY")
    assert [request[0] for request in session.requests] == ["GET", "GET", "POST"]
    assert session.requests[0][2]["headers"] == {"Authorization": "Bearer existing-token"}
    assert session.requests[2][2]["json"] == {"verificationToken": "checkin-challenge"}


def test_api_flow_without_credentials_stops_before_network_request():
    session = FakeSession([])
    checkin = make_checkin({})

    assert asyncio.run(checkin.run_api_flow(session)) == (
        RunStatus.FAIL,
        "缺少账号配置",
    )
    assert session.requests == []
