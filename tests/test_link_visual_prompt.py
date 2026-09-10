import asyncio
import base64
import io
import json
import sys

import httpx
import pytest

from embykeeper.telegram.link import Link

CONTENT_FILTER_ERROR = Exception(
    'Error code: 400, with error text {"contentFilter":[{"level":2,"role":"user"}],'
    '"error":{"code":"1301","message":"系统检测到输入或生成内容可能包含不安全或敏感内容"}}'
)


class FakeMe:
    full_name = "tester"


class FakeTelegramClient:
    def __init__(self):
        self.me = FakeMe()

    async def download_media(self, photo, in_memory=True):
        return io.BytesIO(b"fake-image-bytes")


class AIRequestLog:
    """记录经过真实 HTTPX 序列化后到达 MockTransport 的请求."""

    def __init__(self):
        self.calls = []
        self.http_requests = []
        self.http_clients = []

    def record_call(self, model, messages):
        content = messages[0]["content"]
        prompt = content[0]["text"] if isinstance(content, list) else content
        self.calls.append((model, prompt))


@pytest.fixture(autouse=True)
def isolate_ai_environment(monkeypatch):
    monkeypatch.delenv("ZAI_BASE_URL", raising=False)
    monkeypatch.setitem(sys.modules, "zai", None)


def install(monkeypatch, ai_config, behaviors):
    client = AIRequestLog()
    requested = []

    async def handle_http(request):
        payload = json.loads(request.content)
        client.http_requests.append(request)
        client.record_call(payload["model"], payload["messages"])
        requested.append(
            (
                request.headers["authorization"].removeprefix("Bearer "),
                str(request.url).removesuffix("/chat/completions"),
            )
        )
        behavior = behaviors.get(payload["model"])
        if isinstance(behavior, BaseException):
            raise behavior
        if callable(behavior):
            return await behavior(request)
        if isinstance(behavior, httpx.Response):
            return behavior
        return httpx.Response(200, json={"choices": [{"message": {"content": behavior}}]})

    real_async_client = httpx.AsyncClient

    def http_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handle_http)
        instance = real_async_client(*args, **kwargs)
        client.http_clients.append(instance)
        return instance

    monkeypatch.setattr(Link, "_get_local_ai_config", lambda self: ai_config)
    monkeypatch.setattr(httpx, "AsyncClient", http_client)
    return client, requested


def run_visual(monkeypatch, ai_config, behaviors, options=("选项A", "选项B"), question=None):
    client, requested = install(monkeypatch, ai_config, behaviors)
    link = Link(FakeTelegramClient())
    result, by = asyncio.run(link.visual("photo-id", list(options), question=question))
    return result, by, client, requested


DEFAULT_MODEL = "glm-4.6v-flash"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
OK = "[ANSWER]选项A[/ANSWER]"


# --- 提示词 ---


def test_visual_prompt_omits_platform_and_captcha_wording(monkeypatch):
    # 智谱内容安全策略会因 "验证码识别" 等意图声明拒绝请求 (contentFilter role=user)
    result, _, client, _ = run_visual(monkeypatch, {"api_key": "k"}, {DEFAULT_MODEL: OK})

    assert result == "选项A"
    _, prompt = client.calls[0]
    assert "Telegram" not in prompt
    assert "验证码识别" not in prompt


def test_visual_prompt_can_be_overridden_by_config(monkeypatch):
    _, _, client, _ = run_visual(
        monkeypatch, {"api_key": "k", "prompt": "自定义开场白。"}, {DEFAULT_MODEL: OK}
    )

    assert client.calls[0][1].startswith("自定义开场白。")


def test_visual_prompt_keeps_options_and_answer_format(monkeypatch):
    _, _, client, _ = run_visual(monkeypatch, {"api_key": "k"}, {DEFAULT_MODEL: OK})

    _, prompt = client.calls[0]
    assert "- 选项A" in prompt
    assert "- 选项B" in prompt
    assert "[ANSWER]" in prompt


def test_visual_prompt_includes_question_when_provided(monkeypatch):
    _, _, client, _ = run_visual(
        monkeypatch, {"api_key": "k"}, {DEFAULT_MODEL: OK}, question="图中是什么动物"
    )

    assert "图中是什么动物" in client.calls[0][1]


# --- 回退链 ---


def test_visual_falls_back_after_content_filter(monkeypatch):
    ai_config = {
        "api_key": "primary",
        "model_id": "blocked-model",
        "fallbacks": [{"model_id": "backup-model"}],
    }
    result, by, client, _ = run_visual(
        monkeypatch, ai_config, {"blocked-model": CONTENT_FILTER_ERROR, "backup-model": OK}
    )

    assert result == "选项A"
    assert by == "zhipu:backup-model"
    assert [model for model, _ in client.calls] == ["blocked-model", "backup-model"]


def test_visual_fallback_inherits_unset_fields_from_primary(monkeypatch):
    ai_config = {
        "api_key": "primary",
        "base_url": "https://primary.example",
        "model_id": "blocked-model",
        "fallbacks": [{"model_id": "backup-model"}],
    }
    _, _, _, requested = run_visual(
        monkeypatch, ai_config, {"blocked-model": CONTENT_FILTER_ERROR, "backup-model": OK}
    )

    assert requested == [("primary", "https://primary.example"), ("primary", "https://primary.example")]


def test_visual_fallback_can_switch_provider(monkeypatch):
    ai_config = {
        "api_key": "primary",
        "model_id": "blocked-model",
        "fallbacks": [
            {"api_key": "other", "base_url": "https://other.example/v1", "model_id": "backup-model"}
        ],
    }
    result, _, _, requested = run_visual(
        monkeypatch, ai_config, {"blocked-model": CONTENT_FILTER_ERROR, "backup-model": OK}
    )

    assert result == "选项A"
    assert requested[1] == ("other", "https://other.example/v1")


def test_visual_returns_none_when_all_backends_fail(monkeypatch):
    ai_config = {"api_key": "k", "model_id": "a", "fallbacks": [{"model_id": "b"}]}
    result, by, client, _ = run_visual(
        monkeypatch, ai_config, {"a": CONTENT_FILTER_ERROR, "b": CONTENT_FILTER_ERROR}
    )

    assert result is None and by is None
    assert [model for model, _ in client.calls] == ["a", "b"]


def test_visual_does_not_call_fallback_when_primary_succeeds(monkeypatch):
    ai_config = {"api_key": "k", "model_id": "a", "fallbacks": [{"model_id": "b"}]}
    result, by, client, _ = run_visual(monkeypatch, ai_config, {"a": OK, "b": OK})

    assert result == "选项A"
    assert by == "zhipu:a"
    assert [model for model, _ in client.calls] == ["a"]


def test_visual_falls_back_on_unusable_answer(monkeypatch):
    ai_config = {"api_key": "k", "model_id": "a", "fallbacks": [{"model_id": "b"}]}
    result, by, _, _ = run_visual(monkeypatch, ai_config, {"a": "无法解析的响应", "b": OK})

    assert result == "选项A"
    assert by == "zhipu:b"


def test_visual_without_api_key_returns_none(monkeypatch):
    monkeypatch.setattr(Link, "_get_local_ai_config", lambda self: {})

    link = Link(FakeTelegramClient())
    result, by = asyncio.run(link.visual("photo-id", ["选项A", "选项B"]))

    assert result is None and by is None


# --- 文本路径也走同一条链 ---


def test_gpt_falls_back_after_content_filter(monkeypatch):
    ai_config = {"api_key": "k", "model_id": "a", "fallbacks": [{"model_id": "b"}]}
    client, _ = install(monkeypatch, ai_config, {"a": CONTENT_FILTER_ERROR, "b": "答案"})

    link = Link(FakeTelegramClient())
    answer, by = asyncio.run(link.gpt("问题"))

    assert answer == "答案"
    assert by == "zhipu:b"
    assert [model for model, _ in client.calls] == ["a", "b"]


# --- OpenAI 兼容 HTTP 传输 ---


@pytest.mark.parametrize(
    ("base_url", "environment_url", "expected_base_url", "expected_provider"),
    [
        (None, None, DEFAULT_BASE_URL, "zhipu"),
        ("", None, DEFAULT_BASE_URL, "zhipu"),
        (None, "https://environment.example.test/v1/", "https://environment.example.test/v1", "environment"),
        (
            "https://configured.example.test/v1/",
            "https://environment.example.test/v1",
            "https://configured.example.test/v1",
            "configured",
        ),
    ],
)
def test_endpoint_selection_works_without_zai(
    monkeypatch, base_url, environment_url, expected_base_url, expected_provider
):
    if environment_url is not None:
        monkeypatch.setenv("ZAI_BASE_URL", environment_url)
    ai_config = {"api_key": "test-api-key", "base_url": base_url}

    result, by, client, requested = run_visual(monkeypatch, ai_config, {DEFAULT_MODEL: OK})

    assert sys.modules["zai"] is None
    assert result == "选项A"
    assert by == f"{expected_provider}:{DEFAULT_MODEL}"
    assert requested == [("test-api-key", expected_base_url)]
    assert len(client.http_requests) == 1
    request = client.http_requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{expected_base_url}/chat/completions"
    assert request.headers["authorization"] == "Bearer test-api-key"
    assert json.loads(request.content)["model"] == DEFAULT_MODEL
    assert client.http_clients[0].is_closed


@pytest.mark.parametrize("base_url", ["https://api.example.test/v1", "https://api.example.test/v1/"])
def test_visual_custom_endpoint_preserves_serialized_image_and_credentials(monkeypatch, base_url):
    model = "PaddlePaddle/PaddleOCR-VL-1.5"
    ai_config = {
        "api_key": "test-api-key",
        "base_url": base_url,
        "model_id": model,
        "timeout": 2.5,
    }
    result, by, client, requested = run_visual(monkeypatch, ai_config, {model: OK})

    assert result == "选项A"
    assert by == f"example:{model}"
    assert requested == [("test-api-key", "https://api.example.test/v1")]
    assert len(client.http_requests) == 1
    request = client.http_requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.example.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-api-key"
    assert request.headers["content-type"] == "application/json"
    assert request.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 2.5)
    payload = json.loads(request.content)
    assert payload["model"] == model
    assert payload["messages"][0]["role"] == "user"
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": client.calls[0][1]}
    assert content[1]["type"] == "image_url"
    image_url = content[1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1], validate=True) == b"fake-image-bytes"
    assert len(client.http_clients) == 1
    assert client.http_clients[0].is_closed


@pytest.mark.parametrize(
    "image_url",
    ["data:image/jpeg;base64,ZmFrZS1pbWFnZS1ieXRlcw==", "https://images.example.test/sample.jpg"],
)
def test_custom_endpoint_keeps_supplied_image_urls(monkeypatch, image_url):
    ai_config = {"api_key": "test-api-key", "base_url": "https://api.example.test/v1", "model_id": "a"}
    client, _ = install(monkeypatch, ai_config, {"a": OK})
    link = Link(FakeTelegramClient())
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "识别图片内容"},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    content = asyncio.run(
        link._request_ai_backend(link._build_ai_backends(ai_config)[0], messages, name="视觉问题解答")
    )

    assert content == OK
    assert len(client.http_requests) == 1
    payload = json.loads(client.http_requests[0].content)
    assert payload["messages"][0]["content"][1]["image_url"]["url"] == image_url
    assert messages[0]["content"][1]["image_url"]["url"] == image_url


@pytest.mark.parametrize("status", [400, 429, 503])
def test_visual_custom_endpoint_falls_back_on_http_error(monkeypatch, status):
    ai_config = {
        "api_key": "test-api-key",
        "base_url": "https://api.example.test/v1",
        "model_id": "a",
        "fallbacks": [{"model_id": "b"}],
    }
    rejected_response = httpx.Response(
        status,
        json={"error": {"message": "request rejected"}, "choices": [{"message": {"content": OK}}]},
    )
    result, by, client, _ = run_visual(monkeypatch, ai_config, {"a": rejected_response, "b": OK})

    assert result == "选项A"
    assert by == "example:b"
    assert [model for model, _ in client.calls] == ["a", "b"]
    assert len(client.http_requests) == 2
    assert len(client.http_clients) == 2
    assert all(instance.is_closed for instance in client.http_clients)


@pytest.mark.parametrize("timeout_kind", ["httpx", "overall"])
def test_visual_custom_endpoint_timeout_cleans_up_before_fallback(monkeypatch, timeout_kind):
    async def run():
        finished = asyncio.Event()
        cancelled = asyncio.Event()

        async def delayed_response(request):
            try:
                if timeout_kind == "httpx":
                    raise httpx.ReadTimeout("test read timeout", request=request)
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finally:
                finished.set()

        async def fallback_response(request):
            assert finished.is_set()
            assert client.http_clients[0].is_closed
            return httpx.Response(200, json={"choices": [{"message": {"content": OK}}]})

        ai_config = {
            "api_key": "test-api-key",
            "base_url": "https://api.example.test/v1",
            "model_id": "a",
            "timeout": 0.05,
            "fallbacks": [{"model_id": "b"}],
        }
        client, _ = install(monkeypatch, ai_config, {"a": delayed_response, "b": fallback_response})
        link = Link(FakeTelegramClient())

        result, by = await asyncio.wait_for(link.visual("photo-id", ["选项A", "选项B"]), timeout=1)

        assert result == "选项A"
        assert by == "example:b"
        assert [model for model, _ in client.calls] == ["a", "b"]
        assert finished.is_set()
        assert cancelled.is_set() == (timeout_kind == "overall")
        assert len(client.http_clients) == 2
        assert all(instance.is_closed for instance in client.http_clients)

    asyncio.run(run())


def test_visual_custom_endpoint_cancellation_closes_client_without_fallback(monkeypatch):
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def delayed_response(request):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        ai_config = {
            "api_key": "test-api-key",
            "base_url": "https://api.example.test/v1",
            "model_id": "a",
            "fallbacks": [{"model_id": "b"}],
        }
        client, _ = install(monkeypatch, ai_config, {"a": delayed_response, "b": OK})
        link = Link(FakeTelegramClient())
        task = asyncio.create_task(link.visual("photo-id", ["选项A", "选项B"]))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert cancelled.is_set()
        assert [model for model, _ in client.calls] == ["a"]
        assert len(client.http_clients) == 1
        assert client.http_clients[0].is_closed

    asyncio.run(run())


def test_gpt_custom_endpoint_serializes_text_message(monkeypatch):
    ai_config = {"api_key": "test-api-key", "base_url": "https://api.example.test/v1", "model_id": "a"}
    client, _ = install(monkeypatch, ai_config, {"a": "答案"})
    link = Link(FakeTelegramClient())

    answer, by = asyncio.run(link.gpt("问题"))

    assert answer == "答案"
    assert by == "example:a"
    assert len(client.http_requests) == 1
    assert json.loads(client.http_requests[0].content) == {
        "model": "a",
        "messages": [{"role": "user", "content": "问题"}],
    }
    assert client.http_clients[0].is_closed


@pytest.mark.parametrize("base_url", [None, "https://api.example.test/v1"])
@pytest.mark.parametrize(
    ("operation", "response_content", "expected_answer"),
    [
        ("gpt", "答案", "答案"),
        ("gpt", [{"type": "text", "text": "答"}, {"type": "text", "text": "案"}], "答案"),
        ("visual", OK, "选项A"),
        (
            "visual",
            [{"type": "text", "text": "[ANSWER]"}, {"type": "text", "text": "选项A[/ANSWER]"}],
            "选项A",
        ),
    ],
)
def test_default_and_custom_endpoints_accept_text_and_content_parts(
    monkeypatch, base_url, operation, response_content, expected_answer
):
    ai_config = {"api_key": "test-api-key", "base_url": base_url, "model_id": "a"}
    client, _ = install(monkeypatch, ai_config, {"a": response_content})
    link = Link(FakeTelegramClient())

    if operation == "gpt":
        answer, by = asyncio.run(link.gpt("问题"))
    else:
        answer, by = asyncio.run(link.visual("photo-id", ["选项A", "选项B"]))

    assert answer == expected_answer
    assert by == ("example:a" if base_url else "zhipu:a")
    assert len(client.http_requests) == 1
    assert str(client.http_requests[0].url) == f"{base_url or DEFAULT_BASE_URL}/chat/completions"
    assert client.http_clients[0].is_closed


@pytest.mark.parametrize("operation", ["gpt", "visual"])
@pytest.mark.parametrize(
    "response_body",
    [
        {},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": {"text": "答案"}}}]},
        {"choices": [{"message": {"content": 42}}]},
        {"choices": [{"message": {"content": [{"type": "text", "text": 42}]}}]},
        {"choices": [{"message": {"content": [{"type": "image_url", "image_url": {"url": "image"}}]}}]},
    ],
)
def test_invalid_completion_response_falls_back(monkeypatch, operation, response_body):
    ai_config = {"api_key": "test-api-key", "model_id": "a", "fallbacks": [{"model_id": "b"}]}
    fallback_content = "答案" if operation == "gpt" else OK
    client, _ = install(
        monkeypatch, ai_config, {"a": httpx.Response(200, json=response_body), "b": fallback_content}
    )
    link = Link(FakeTelegramClient())

    if operation == "gpt":
        answer, by = asyncio.run(link.gpt("问题"))
    else:
        answer, by = asyncio.run(link.visual("photo-id", ["选项A", "选项B"]))

    assert answer == ("答案" if operation == "gpt" else "选项A")
    assert by == "zhipu:b"
    assert [model for model, _ in client.calls] == ["a", "b"]
    assert len(client.http_clients) == 2
    assert all(instance.is_closed for instance in client.http_clients)


# --- 内容审核识别 ---


def test_content_filter_error_is_recognised():
    assert Link._is_content_filter_error(CONTENT_FILTER_ERROR)
    assert Link._is_content_filter_error(Exception("系统检测到敏感内容"))
    assert not Link._is_content_filter_error(Exception("Connection reset by peer"))
    assert not Link._is_content_filter_error(TimeoutError())


@pytest.mark.parametrize(
    ("body", "filtered"),
    [
        ({"contentFilter": [{"level": 2, "role": "user"}]}, True),
        ({"error": {"code": "1301", "message": "input rejected"}}, True),
        ({"error": {"message": "invalid request"}}, False),
    ],
)
def test_content_filter_error_reads_http_response_body(body, filtered):
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(400, request=request, json=body)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert Link._is_content_filter_error(exc_info.value) is filtered
