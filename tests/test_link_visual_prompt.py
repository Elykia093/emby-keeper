import asyncio
import io
import types

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


class ScriptedZhipuClient:
    """按 model_id 决定返回内容或抛出异常, 避免测试触达真实接口."""

    def __init__(self, behaviors):
        self.behaviors = behaviors
        self.calls = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, model, messages):
        content = messages[0]["content"]
        prompt = content[0]["text"] if isinstance(content, list) else content
        self.calls.append((model, prompt))
        behavior = self.behaviors.get(model)
        if isinstance(behavior, BaseException):
            raise behavior
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=behavior))]
        )


def install(monkeypatch, ai_config, behaviors):
    client = ScriptedZhipuClient(behaviors)
    requested = []

    def fake_get(self, api_key, base_url=None):
        requested.append((api_key, base_url))
        return client

    monkeypatch.setattr(Link, "_get_local_ai_config", lambda self: ai_config)
    monkeypatch.setattr(Link, "_get_zhipu_client", fake_get)
    return client, requested


def run_visual(monkeypatch, ai_config, behaviors, options=("选项A", "选项B"), question=None):
    client, requested = install(monkeypatch, ai_config, behaviors)
    link = Link(FakeTelegramClient())
    result, by = asyncio.run(link.visual("photo-id", list(options), question=question))
    return result, by, client, requested


DEFAULT_MODEL = "glm-4.1v-thinking-flashx"
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
        monkeypatch, {"api_key": "k", "llm_prompt": "自定义开场白。"}, {DEFAULT_MODEL: OK}
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


# --- 内容审核识别 ---


def test_content_filter_error_is_recognised():
    assert Link._is_content_filter_error(CONTENT_FILTER_ERROR)
    assert Link._is_content_filter_error(Exception("系统检测到敏感内容"))
    assert not Link._is_content_filter_error(Exception("Connection reset by peer"))
    assert not Link._is_content_filter_error(TimeoutError())
