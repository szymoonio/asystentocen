"""Interfejs LLM niezależny od dostawcy (docs/ARCHITEKTURA.md § 6.4).

Moduły domenowe (notes, summarize, prep, hr_partner) znają tylko `LLMClient` i wyjątki z tego
pliku. Każdy wyjątek ma `user_message` — gotowy, polski komunikat do pokazania w UI.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Literal, Protocol, TypedDict, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Msg(TypedDict):
    role: Literal["user", "assistant"]
    content: str


HR_CONTACT = "Skontaktuj się z Wydziałem Kadr."


class LLMError(Exception):
    user_message = "Asystent jest chwilowo niedostępny. Spróbuj ponownie za chwilę."

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        super().__init__(detail or self.user_message)
        if user_message:
            self.user_message = user_message


class LLMUnavailable(LLMError):
    """Zadanie wyłączone w config/llm.yaml albo brak klucza — funkcja powinna być ukryta w UI."""

    user_message = "Ta funkcja asystenta jest wyłączona."


class LLMRefusal(LLMError):
    """Model odmówił (stop_reason == "refusal"), także po ewentualnym fallbacku."""

    user_message = f"Asystent nie może pomóc w tej sprawie. {HR_CONTACT}"

    def __init__(self, detail: str = "", *, category: str | None = None) -> None:
        super().__init__(detail)
        self.category = category


class LLMRateLimited(LLMError):
    user_message = "Asystent jest teraz przeciążony. Spróbuj ponownie za minutę."


class LLMIncomplete(LLMError):
    """Odpowiedź ucięta (max_tokens) albo niezgodna ze schematem."""

    user_message = "Asystent nie dokończył odpowiedzi. Spróbuj ponownie albo skróć dane wejściowe."


@runtime_checkable
class LLMClient(Protocol):
    def available(self, task: str) -> bool: ...

    def model_for(self, task: str) -> str: ...  # do pola `generator` (np. DraftSuggestion)

    def structured(self, task: str, system: str, user: str, schema: type[T]) -> T: ...

    def text(self, task: str, system: str, messages: Sequence[Msg]) -> str: ...

    def stream(self, task: str, system: str, messages: Sequence[Msg]) -> Iterator[str]: ...


def generator_id(client: LLMClient, task: str, prompt_version: str) -> str:
    """Np. "claude-opus-5-5:summarize_cycle:v1" — zapisywane przy wynikach LLM."""
    return f"{client.model_for(task)}:{task}:{prompt_version}"
