import asyncio

from embykeeper.runinfo import RunStatus
from embykeeper.telegram.checkiner.kotomi import (
    KotomiCheckin,
    build_login_payload,
    classify_signin_response,
    classify_signin_status_response,
    has_signed_today,
    is_already_signed,
    normalize_base_url,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.text = str(payload)

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return next(self.responses)

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return next(self.responses)


def make_checkin(config):
    checkin = object.__new__(KotomiCheckin)
    checkin.config = config
    return checkin


def test_build_login_payload_uses_email_when_identity_contains_at():
    assert build_login_payload(" user@example.com ", "secret") == {
        "email": "user@example.com",
        "username": "",
        "password": "secret",
    }


def test_build_login_payload_uses_username_otherwise():
    assert build_login_payload("alice", "secret") == {
        "username": "alice",
        "password": "secret",
    }


def test_normalize_base_url_adds_https_and_strips_slash():
    assert normalize_base_url("embymb.ichinosekotomi.com/") == "https://embymb.ichinosekotomi.com"


def test_has_signed_today_finds_nested_status():
    assert has_signed_today({"success": True, "data": {"today_signed": True}})


def test_classify_signin_response_success():
    assert classify_signin_response(200, {"success": True, "message": "+5"}) == (
        RunStatus.SUCCESS,
        "+5",
    )


def test_classify_signin_response_already_signed_by_status():
    assert classify_signin_response(409, {"success": False, "message": "今日已签到"}) == (
        RunStatus.NONEED,
        "今日已签到",
    )


def test_classify_signin_response_disabled():
    assert classify_signin_response(
        400,
        {"success": False, "error_code": "SIGNIN_DISABLED", "message": "disabled"},
    ) == (RunStatus.FAIL, "签到功能未开启")


def test_classify_signin_response_does_not_treat_unknown_conflict_as_already_signed():
    assert classify_signin_response(
        409,
        {"success": False, "error_code": "ACCOUNT_CONFLICT", "message": "账号冲突"},
    ) == (RunStatus.FAIL, "账号冲突")


def test_already_signed_message_requires_an_exact_authoritative_phrase():
    assert not is_already_signed(409, {"success": False, "message": "未找到已签到记录"})


def test_already_signed_rejects_unauthorized_response_even_with_positive_fields():
    assert not is_already_signed(
        401,
        {"success": False, "data": {"today_signed": True}, "message": "今日已签到"},
    )


def test_classify_signin_response_requires_explicit_success():
    assert classify_signin_response(200, {"message": "unexpected"}) == (
        RunStatus.FAIL,
        "unexpected",
    )


def test_classify_signin_response_reports_security_block():
    assert classify_signin_response(403, "<html>blocked</html>") == (
        RunStatus.FAIL,
        "站点安全验证拦截",
    )


def test_classify_signin_status_response_stops_on_api_failure():
    assert classify_signin_status_response(
        503,
        {"success": False, "message": "service unavailable"},
    ) == (RunStatus.FAIL, "service unavailable")


def test_classify_signin_status_response_requires_explicit_success():
    assert classify_signin_status_response(200, {"message": "unexpected"}) == (
        RunStatus.FAIL,
        "unexpected",
    )


def test_classify_signin_status_response_reports_security_block():
    assert classify_signin_status_response(403, "<html>blocked</html>") == (
        RunStatus.FAIL,
        "站点安全验证拦截",
    )


def test_classify_signin_status_response_allows_unsigned_account_to_continue():
    assert classify_signin_status_response(
        200,
        {"success": True, "data": {"today_signed": False}},
    ) == (RunStatus.RUNNING, "尚未签到")


def test_api_flow_logs_in_checks_status_and_signs_in():
    client = FakeClient(
        [
            FakeResponse(200, "login page"),
            FakeResponse(200, {"success": True}),
            FakeResponse(200, {"success": True, "data": {"today_signed": False}}),
            FakeResponse(200, {"success": True, "message": "+5"}),
        ]
    )
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(client)) == (RunStatus.SUCCESS, "+5")
    assert [request[0] for request in client.requests] == ["GET", "POST", "GET", "POST"]
    assert client.requests[1][2]["json"] == {"username": "alice", "password": "secret"}


def test_api_flow_does_not_submit_credentials_when_login_page_is_blocked():
    client = FakeClient([FakeResponse(403, "blocked")])
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(client)) == (RunStatus.FAIL, "站点安全验证拦截")
    assert [request[0] for request in client.requests] == ["GET"]


def test_api_flow_requires_explicit_login_success():
    client = FakeClient(
        [
            FakeResponse(200, "login page"),
            FakeResponse(200, {"message": "unexpected"}),
        ]
    )
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(client)) == (RunStatus.FAIL, "unexpected")
    assert [request[0] for request in client.requests] == ["GET", "POST"]


def test_api_flow_reports_security_block_from_login_api():
    client = FakeClient(
        [
            FakeResponse(200, "login page"),
            FakeResponse(403, "<html>blocked</html>"),
        ]
    )
    checkin = make_checkin({"username": "alice", "password": "secret"})

    assert asyncio.run(checkin.run_api_flow(client)) == (
        RunStatus.FAIL,
        "站点安全验证拦截",
    )
    assert [request[0] for request in client.requests] == ["GET", "POST"]
