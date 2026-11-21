"""`NullClient` — LLM wyłączony: wszystkie zadania niedostępne, UI ukrywa funkcje."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from app.assistant.llm.base import LLMUnavailable, Msg, T


class NullClient:
    def __init__(self, reason: str = "LLM wyłączony") -> None:
        self.reason = reason

    def available(self, task: str) -> bool:
        return False

    def model_for(self, task: str) -> str:
        return "none"

    def structured(self, task: str, system: str, user: str, schema: type[T]) -> T:
        raise LLMUnavailable(self.reason)

    def text(self, task: str, system: str, messages: Sequence[Msg]) -> str:
        raise LLMUnavailable(self.reason)

    def stream(self, task: str, system: str, messages: Sequence[Msg]) -> Iterator[str]:
        raise LLMUnavailable(self.reason)
