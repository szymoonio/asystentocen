"""Klienci LLM dla evali: skryptowany (wyrocznia / pusty baseline) i nakładka licząca tokeny z API."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

from pydantic import BaseModel

from app.assistant.llm import LLMClient, Msg


class ScriptedClient:
    """Odpowiada z kolejki ustawionej przez zestaw przed każdym przypadkiem.

    Element kolejki: gotowa wartość albo funkcja `(system, user|messages) -> wartość`.
    Służy do przebiegu „oracle” (odpowiedzi wzorcowe — harness musi dać ~100%) i „null”
    (puste odpowiedzi — oceniacze muszą odrzucić).
    """

    model = "scripted"

    def __init__(self) -> None:
        self.queue: dict[str, list[Any]] = {}
        self.last_usage: dict | None = None

    def script(self, **responses: Any) -> None:
        self.queue = {task: (r if isinstance(r, list) else [r]) for task, r in responses.items()}

    def available(self, task: str) -> bool:
        return True

    def model_for(self, task: str) -> str:
        return self.model

    def _next(self, task: str, *args: Any) -> Any:
        items = self.queue.get(task)
        if not items:
            raise AssertionError(f"brak skryptowanej odpowiedzi dla zadania {task}")
        item = items.pop(0) if len(items) > 1 else items[0]
        return item(*args) if callable(item) else item

    def structured(self, task: str, system: str, user: str, schema: type[BaseModel]):
        value = self._next(task, system, user)
        return value if isinstance(value, schema) else schema.model_validate(value)

    def text(self, task: str, system: str, messages: Sequence[Msg]) -> str:
        return self._next(task, system, messages)

    def stream(self, task: str, system: str, messages: Sequence[Msg]) -> Iterator[str]:
        yield from self._next(task, system, messages)


class RecordingClient:
    """Nakładka na prawdziwy `LLMClient`: zapisuje `usage` każdego wywołania (z odpowiedzi API)."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    def available(self, task: str) -> bool:
        return self.inner.available(task)

    def model_for(self, task: str) -> str:
        return self.inner.model_for(task)

    def _record(self, task: str) -> None:
        usage = getattr(self.inner, "last_usage", None)
        self.calls.append({"task": task, "requested_model": self.inner.model_for(task), **(usage or {})})

    def _wrap(self, task: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        finally:
            self._record(task)

    def structured(self, task, system, user, schema):
        return self._wrap(task, lambda: self.inner.structured(task, system, user, schema))

    def text(self, task, system, messages):
        return self._wrap(task, lambda: self.inner.text(task, system, messages))

    def stream(self, task, system, messages):
        try:
            yield from self.inner.stream(task, system, messages)
        finally:
            self._record(task)

    def take_calls(self) -> list[dict]:
        calls, self.calls = self.calls, []
        return calls
