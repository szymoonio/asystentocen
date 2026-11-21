"""Fixtury modułu B. Testy nie wołają sieci: klucz API usuwamy, LLM to fake."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from pydantic import BaseModel

from app.assistant.llm.base import LLMUnavailable, Msg


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


class FakeLLMClient:
    """Skryptowany `LLMClient`: odpowiedzi podajemy per zadanie, wywołania są zapisywane."""

    def __init__(self, responses: dict[str, object] | None = None, *, model: str = "fake-model") -> None:
        self.responses = dict(responses or {})
        self.calls: list[dict] = []
        self.model = model

    def available(self, task: str) -> bool:
        return task in self.responses

    def model_for(self, task: str) -> str:
        return self.model

    def _answer(self, task: str, **call):
        self.calls.append({"task": task, **call})
        if task not in self.responses:
            raise LLMUnavailable(task)
        answer = self.responses[task]
        if isinstance(answer, Exception):
            raise answer
        return answer(**call) if callable(answer) else answer

    def structured(self, task: str, system: str, user: str, schema: type[BaseModel]):
        result = self._answer(task, system=system, user=user, schema=schema)
        return result if isinstance(result, schema) else schema.model_validate(result)

    def text(self, task: str, system: str, messages: Sequence[Msg]) -> str:
        return self._answer(task, system=system, messages=list(messages))

    def stream(self, task: str, system: str, messages: Sequence[Msg]) -> Iterator[str]:
        yield from self._answer(task, system=system, messages=list(messages))


@pytest.fixture
def fake_llm() -> type[FakeLLMClient]:
    return FakeLLMClient
