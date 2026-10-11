import asyncio
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from embykeeper.runinfo import RunContext, RunStatus
from embykeeper.telegram.checkin_main import CheckinerManager
from embykeeper.telegram.checkiner import plusemby


@pytest.mark.parametrize(
    "status_code,payload,expected",
    [
        pytest.param(200, {"hasCheckedInToday": True}, RunStatus.NONEED, id="already-checked-in"),
        pytest.param(200, {"hasCheckedInToday": False}, RunStatus.RUNNING, id="not-checked-in"),
        pytest.param(
            200, {"success": False, "hasCheckedInToday": True}, RunStatus.FAIL, id="explicit-failure"
        ),
        pytest.param(199, {"hasCheckedInToday": True}, RunStatus.FAIL, id="informational-response"),
        pytest.param(300, {"hasCheckedInToday": False}, RunStatus.FAIL, id="redirect-response"),
        pytest.param(401, {"hasCheckedInToday": True}, RunStatus.FAIL, id="unauthorized"),
        pytest.param(403, {"hasCheckedInToday": True}, RunStatus.FAIL, id="access-blocked"),
        pytest.param(500, {"hasCheckedInToday": True}, RunStatus.FAIL, id="server-error"),
        pytest.param(200, {"hasCheckedInToday": 1}, RunStatus.FAIL, id="integer-is-not-true"),
        pytest.param(200, {"hasCheckedInToday": 0}, RunStatus.FAIL, id="integer-is-not-false"),
        pytest.param(200, {"hasCheckedInToday": "true"}, RunStatus.FAIL, id="string-is-not-boolean"),
        pytest.param(200, {"checkedIn": True}, RunStatus.FAIL, id="unknown-field"),
        pytest.param(200, {}, RunStatus.FAIL, id="empty-object"),
        pytest.param(200, None, RunStatus.FAIL, id="null-response"),
        pytest.param(200, [], RunStatus.FAIL, id="array-response"),
    ],
)
def test_status_response_requires_explicit_boolean_on_successful_http(status_code, payload, expected):
    status, _ = plusemby.classify_status_response(status_code, payload)

    assert status == expected


@pytest.mark.parametrize(
    "status_code,payload,expected",
    [
        pytest.param(200, {"success": True, "hasCheckedIn": True}, RunStatus.SUCCESS, id="newly-completed"),
        pytest.param(299, {"success": True}, RunStatus.SUCCESS, id="successful-http-upper-bound"),
        pytest.param(200, {"success": False, "hasCheckedIn": True}, RunStatus.NONEED, id="already-completed"),
        pytest.param(200, {"hasCheckedIn": True}, RunStatus.NONEED, id="legacy-duplicate"),
        pytest.param(
            400, {"success": False, "hasCheckedIn": True}, RunStatus.NONEED, id="bad-request-duplicate"
        ),
        pytest.param(
            409, {"success": False, "hasCheckedIn": True}, RunStatus.NONEED, id="conflict-duplicate"
        ),
        pytest.param(
            400, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="bad-request-success-conflict"
        ),
        pytest.param(
            409, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="conflict-success-conflict"
        ),
        pytest.param(401, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="unauthorized"),
        pytest.param(403, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="access-blocked"),
        pytest.param(404, {"hasCheckedIn": True}, RunStatus.FAIL, id="missing-endpoint"),
        pytest.param(429, {"hasCheckedIn": True}, RunStatus.FAIL, id="rate-limited"),
        pytest.param(500, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="server-error"),
        pytest.param(
            199, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="informational-response"
        ),
        pytest.param(300, {"success": True, "hasCheckedIn": True}, RunStatus.FAIL, id="redirect-response"),
        pytest.param(409, {"message": "发生冲突"}, RunStatus.FAIL, id="unknown-conflict"),
        pytest.param(409, {"message": "今日已签到"}, RunStatus.FAIL, id="message-without-status-evidence"),
        pytest.param(200, {"success": 1}, RunStatus.FAIL, id="integer-is-not-success"),
        pytest.param(200, {"success": "true"}, RunStatus.FAIL, id="string-is-not-success"),
        pytest.param(200, {"hasCheckedIn": 1}, RunStatus.FAIL, id="integer-is-not-duplicate"),
        pytest.param(200, {"amount": 2, "currencyUnit": "积分"}, RunStatus.FAIL, id="reward-without-success"),
        pytest.param(200, {"checkedIn": True}, RunStatus.FAIL, id="unknown-field"),
        pytest.param(200, {}, RunStatus.FAIL, id="empty-object"),
        pytest.param(200, None, RunStatus.FAIL, id="null-response"),
        pytest.param(200, [], RunStatus.FAIL, id="array-response"),
    ],
)
def test_checkin_response_distinguishes_success_duplicate_and_failure(status_code, payload, expected):
    status, _ = plusemby.classify_checkin_response(status_code, payload)

    assert status == expected


@pytest.mark.parametrize(
    "payload,expected_message",
    [
        ({"success": True, "hasCheckedIn": True, "amount": 0, "currencyUnit": "积分"}, "+0 积分"),
        ({"success": True, "message": "签到完成"}, "签到完成"),
        ({"success": True}, "签到成功"),
    ],
)
def test_success_keeps_reward_and_message_details(payload, expected_message):
    assert plusemby.classify_checkin_response(200, payload) == (RunStatus.SUCCESS, expected_message)


@pytest.mark.parametrize("classify", [plusemby.classify_status_response, plusemby.classify_checkin_response])
@pytest.mark.parametrize(
    "status_code,expected_message",
    [(401, "登录已失效"), (403, plusemby.ACCESS_BLOCKED_MESSAGE), (500, "接口暂时不可用")],
)
def test_failures_keep_authentication_and_server_messages(classify, status_code, expected_message):
    assert classify(status_code, {"message": "接口暂时不可用"}) == (RunStatus.FAIL, expected_message)


class FakeResponse:
    def __init__(self, status_code, payload=None, *, text=None):
        self.status_code = status_code
        self.payload = payload
        self.text = text if text is not None else str(payload)
        self.invalid_json = text is not None

    def json(self):
        if self.invalid_json:
            raise ValueError("invalid JSON")
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited = True
        return False

    async def request(self, method, url, **kwargs):
        self.requests.append((method, urlsplit(url).path, kwargs))
        assert self.responses, "签到流程发出了多余请求"
        return self.responses.pop(0)


@pytest.fixture
def run_checkin(monkeypatch):
    contexts = []
    monkeypatch.setattr(RunContext, "save", lambda self: None)

    def run(responses):
        session = FakeSession(responses)
        monkeypatch.setattr(plusemby, "AsyncSession", lambda **kwargs: session)
        ctx = RunContext.prepare(description="Plusemby 测试")
        contexts.append(ctx)
        client = SimpleNamespace(me=SimpleNamespace(full_name="Test User"))
        checkin = plusemby.PlusembyCheckin(
            client,
            context=ctx,
            timeout=5,
            config={"url": "https://checkin.example", "access_token": "test-access-token"},
        )

        result = asyncio.run(checkin.start())

        assert result is ctx
        assert ctx._finished.is_set()
        assert ctx.start_time is not None
        assert ctx.end_time is not None
        assert session.exited
        assert not session.responses
        return checkin, session

    yield run

    for ctx in contexts:
        if not ctx._finished.is_set():
            ctx.finish(RunStatus.CANCELLED)


def test_new_checkin_completes_successfully_and_counts_as_success(run_checkin):
    checkin, session = run_checkin(
        [
            FakeResponse(200, {"hasCheckedInToday": False}),
            FakeResponse(200, {}),
            FakeResponse(200, {"success": True, "hasCheckedIn": True, "amount": 0, "currencyUnit": "积分"}),
        ]
    )

    assert checkin.ctx.status == RunStatus.SUCCESS
    assert checkin.ctx.status_info == "+0 积分"
    assert any("签到成功" in entry.message and "+0 积分" in entry.message for entry in checkin.ctx.log)
    assert [(method, path) for method, path, _ in session.requests] == [
        ("GET", "/api/checkin/status"),
        ("GET", "/api/settings/verification/public"),
        ("POST", "/api/checkin"),
    ]
    assert session.requests[-1][2]["json"] == {}

    summary_messages = []
    log = SimpleNamespace(info=summary_messages.append, error=summary_messages.append)
    log.bind = lambda **kwargs: log
    CheckinerManager._log_batch_summary({"plusemby": (checkin, checkin.ctx)}, log)

    assert summary_messages == ["签到成功 (共1个, 1成功)."]


def test_precheck_already_complete_skips_submission_and_explains_stage(run_checkin):
    checkin, session = run_checkin([FakeResponse(200, {"hasCheckedInToday": True})])

    assert checkin.ctx.status == RunStatus.NONEED
    assert checkin.ctx.status_info == "签到前查询确认今日已签到, 跳过提交"
    assert any(checkin.ctx.status_info in entry.message for entry in checkin.ctx.log)
    assert [(method, path) for method, path, _ in session.requests] == [("GET", "/api/checkin/status")]


def test_duplicate_during_submission_explains_stage_without_retry(run_checkin):
    checkin, session = run_checkin(
        [
            FakeResponse(200, {"hasCheckedInToday": False}),
            FakeResponse(200, {}),
            FakeResponse(409, {"success": False, "hasCheckedIn": True}),
        ]
    )

    assert checkin.ctx.status == RunStatus.NONEED
    assert checkin.ctx.status_info == "提交时站点确认今日已签到"
    assert any(checkin.ctx.status_info in entry.message for entry in checkin.ctx.log)
    assert [(method, path) for method, path, _ in session.requests] == [
        ("GET", "/api/checkin/status"),
        ("GET", "/api/settings/verification/public"),
        ("POST", "/api/checkin"),
    ]


@pytest.mark.parametrize(
    "response,expected_message",
    [
        (FakeResponse(403, {"success": True, "hasCheckedIn": True}), plusemby.ACCESS_BLOCKED_MESSAGE),
        (FakeResponse(500, {"success": True, "hasCheckedIn": True, "message": "服务错误"}), "服务错误"),
        (FakeResponse(200, text="<html>服务不可用</html>"), "服务不可用"),
    ],
    ids=["access-blocked", "server-error", "non-json"],
)
@pytest.mark.parametrize("stage", ["query", "submit"])
def test_request_failure_finishes_without_retry_or_additional_submission(
    run_checkin, response, expected_message, stage
):
    responses = [response]
    expected_requests = [("GET", "/api/checkin/status")]
    if stage == "submit":
        responses = [FakeResponse(200, {"hasCheckedInToday": False}), FakeResponse(200, {}), response]
        expected_requests += [("GET", "/api/settings/verification/public"), ("POST", "/api/checkin")]

    checkin, session = run_checkin(responses)

    assert checkin.ctx.status == RunStatus.FAIL
    assert expected_message in checkin.ctx.status_info
    assert any(entry.level == "WARNING" and expected_message in entry.message for entry in checkin.ctx.log)
    assert [(method, path) for method, path, _ in session.requests] == expected_requests
