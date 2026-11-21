"""Warstwa LLM: konfiguracja, NullClient, ClaudeClient na fałszywym SDK (bez sieci)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from app.assistant.llm import (
    LLMConfig,
    LLMError,
    LLMIncomplete,
    LLMRateLimited,
    LLMRefusal,
    LLMUnavailable,
    NullClient,
    build_client,
    generator_id,
)
from app.assistant.llm.base import LLMClient
from app.assistant.llm.claude import FALLBACK_BETA, ClaudeClient
from app.assistant.llm.config import TaskConfig
from app.assistant.llm.prompts import load_prompt
from app.assistant.services import services
from app.settings import ROOT

CONFIG = LLMConfig(provider="anthropic", tasks={"split_note": TaskConfig(model="claude-opus-5-5", effort="low")})


class Split(BaseModel):
    strengths: list[str]
    improvements: list[str]


def response(*, stop_reason="end_turn", parsed=None, text="", category=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        parsed_output=parsed,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
        model="claude-opus-5-5",
        _request_id="req_test",
    )


class FakeSDK:
    """Udaje `anthropic.Anthropic()`: zapisuje kwargs i zwraca przygotowaną odpowiedź."""

    def __init__(self, result=None, *, raises: Exception | None = None, chunks=("Dzień ", "dobry")) -> None:
        self.result = result or response()
        self.raises = raises
        self.chunks = chunks
        self.calls: list[tuple[str, dict]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse, create=self._create, stream=self._stream))

    def _call(self, name, kwargs):
        self.calls.append((name, kwargs))
        if self.raises:
            raise self.raises
        return self.result

    def _parse(self, **kwargs):
        return self._call("parse", kwargs)

    def _create(self, **kwargs):
        return self._call("create", kwargs)

    @contextmanager
    def _stream(self, **kwargs):
        self._call("stream", kwargs)
        yield SimpleNamespace(text_stream=iter(self.chunks), get_final_message=lambda: self.result)


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# --- konfiguracja ------------------------------------------------------------------------


def test_repo_config_loads_all_tasks():
    cfg = LLMConfig.load(ROOT / "config")
    assert cfg.provider == "anthropic" and cfg.refusal_fallback
    assert cfg.tasks["summarize_cycle"].effort == "high"
    assert {"split_note", "classify_note", "roleplay", "procedure_qa"} <= set(cfg.tasks)
    assert all(t.model == "claude-opus-5-5" for t in cfg.tasks.values())


def test_invalid_effort_rejected():
    with pytest.raises(ValueError):
        TaskConfig(model="m", effort="turbo")


def test_build_client_without_key_is_null():
    client = build_client(CONFIG)
    assert isinstance(client, NullClient) and not client.available("split_note")


def test_build_client_with_key_is_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = build_client(CONFIG)
    assert isinstance(client, ClaudeClient) and isinstance(client, LLMClient)
    assert client.available("split_note") and not client.available("roleplay")


def test_container_without_key_has_null_llm(container):
    assert isinstance(services(container).llm, NullClient)


def test_null_client_raises_unavailable():
    with pytest.raises(LLMUnavailable):
        NullClient().structured("split_note", "s", "u", Split)


def test_generator_id():
    client = ClaudeClient(CONFIG, client=FakeSDK())
    assert generator_id(client, "split_note", "v1") == "claude-opus-5-5:split_note:v1"


def test_load_prompt(tmp_path):
    (tmp_path / "split_note").mkdir()
    (tmp_path / "split_note" / "v1.md").write_text("  Stały prompt.\n", encoding="utf-8")
    prompt = load_prompt("split_note", "v1", tmp_path)
    assert (prompt.task, prompt.version, prompt.text) == ("split_note", "v1", "Stały prompt.")


# --- ClaudeClient --------------------------------------------------------------------------


def test_structured_request_shape():
    sdk = FakeSDK(response(parsed=Split(strengths=["a"], improvements=[])))
    result = ClaudeClient(CONFIG, client=sdk).structured("split_note", "SYSTEM", "dane", Split)
    assert result.strengths == ["a"]
    name, kwargs = sdk.calls[0]
    assert name == "parse" and kwargs["output_format"] is Split
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"] == [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["messages"] == [{"role": "user", "content": "dane"}]
    assert kwargs["output_config"] == {"effort": "low"}
    assert kwargs["betas"] == [FALLBACK_BETA] and kwargs["fallbacks"] == "default"
    # na claude-opus-5-5 te parametry dają 400
    assert "temperature" not in kwargs and "thinking" not in kwargs


def test_fallback_can_be_disabled():
    cfg = LLMConfig(provider="anthropic", refusal_fallback=False, tasks=CONFIG.tasks)
    sdk = FakeSDK(response(text="ok"))
    ClaudeClient(cfg, client=sdk).text("split_note", "S", [{"role": "user", "content": "x"}])
    assert "fallbacks" not in sdk.calls[0][1] and "betas" not in sdk.calls[0][1]


def test_refusal_raises_with_category_and_hr_message():
    sdk = FakeSDK(response(stop_reason="refusal", category="cyber"))
    with pytest.raises(LLMRefusal) as err:
        ClaudeClient(CONFIG, client=sdk).structured("split_note", "S", "u", Split)
    assert err.value.category == "cyber"
    assert "Wydziałem Kadr" in err.value.user_message


def test_max_tokens_is_incomplete():
    sdk = FakeSDK(response(stop_reason="max_tokens", text="ucięte"))
    with pytest.raises(LLMIncomplete):
        ClaudeClient(CONFIG, client=sdk).text("split_note", "S", [{"role": "user", "content": "x"}])


def test_missing_parsed_output_is_incomplete():
    with pytest.raises(LLMIncomplete):
        ClaudeClient(CONFIG, client=FakeSDK(response(parsed=None))).structured("split_note", "S", "u", Split)


def test_text_joins_text_blocks_only():
    sdk = FakeSDK(response(text="Odpowiedź"))
    assert ClaudeClient(CONFIG, client=sdk).text("split_note", "S", [{"role": "user", "content": "x"}]) == "Odpowiedź"


def test_stream_yields_chunks_then_checks_refusal():
    client = ClaudeClient(CONFIG, client=FakeSDK(response()))
    assert "".join(client.stream("split_note", "S", [{"role": "user", "content": "x"}])) == "Dzień dobry"

    refusing = ClaudeClient(CONFIG, client=FakeSDK(response(stop_reason="refusal")))
    chunks = []
    with pytest.raises(LLMRefusal):
        for chunk in refusing.stream("split_note", "S", [{"role": "user", "content": "x"}]):
            chunks.append(chunk)
    assert chunks == ["Dzień ", "dobry"]


def test_disabled_task_is_unavailable():
    with pytest.raises(LLMUnavailable):
        ClaudeClient(CONFIG, client=FakeSDK()).text("roleplay", "S", [{"role": "user", "content": "x"}])


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (anthropic.RateLimitError("limit", response=httpx2.Response(429, request=_request()), body=None), LLMRateLimited),
        (anthropic.AuthenticationError("key", response=httpx2.Response(401, request=_request()), body=None), LLMUnavailable),
        (anthropic.InternalServerError("boom", response=httpx2.Response(500, request=_request()), body=None), LLMError),
        (anthropic.APIConnectionError(request=_request()), LLMError),
    ],
)
def test_sdk_errors_are_translated(exc, expected):
    with pytest.raises(expected) as err:
        ClaudeClient(CONFIG, client=FakeSDK(raises=exc)).structured("split_note", "S", "u", Split)
    assert err.value.user_message  # zawsze jest komunikat do UI
    assert isinstance(err.value.__cause__, anthropic.AnthropicError)
