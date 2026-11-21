"""`ClaudeClient` — implementacja `LLMClient` na oficjalnym SDK `anthropic` (§ 6.4).

- Stały prompt systemowy idzie pierwszy, z `cache_control`; zmienne dane są w wiadomościach.
- Nie wysyłamy `temperature` ani `thinking` (na claude-opus-5-5 dają 400) — głębokość to
  `output_config.effort` z configu.
- `stop_reason` sprawdzamy zawsze przed odczytem treści. Przy włączonym `refusal_fallback`
  serwer sam ponawia odmowę na innym modelu (`fallbacks="default"`); jeśli i tak skończy się
  odmową, rzucamy `LLMRefusal` ze stałym komunikatem odsyłającym do kadr.
- Wyjątki SDK łapiemy od najbardziej szczegółowego. SDK sam ponawia 429/5xx (`max_retries`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from typing import Any

import anthropic

from app.assistant.llm.base import (
    LLMError,
    LLMIncomplete,
    LLMRateLimited,
    LLMRefusal,
    LLMUnavailable,
    Msg,
    T,
)
from app.assistant.llm.config import LLMConfig, TaskConfig

log = logging.getLogger("asystent.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
STREAM_MAX_TOKENS = 64000


class ClaudeClient:
    def __init__(self, config: LLMConfig, client: Any | None = None) -> None:
        self._config = config
        self._client = client  # wstrzykiwany w testach; inaczej tworzony leniwie
        self.last_usage: dict | None = None

    # --- konfiguracja -------------------------------------------------------------------

    def available(self, task: str) -> bool:
        return task in self._config.tasks

    def model_for(self, task: str) -> str:
        return self._task(task).model

    def _task(self, task: str) -> TaskConfig:
        try:
            return self._config.tasks[task]
        except KeyError as exc:
            raise LLMUnavailable(f"zadanie {task!r} nie jest włączone w config/llm.yaml") from exc

    def _sdk(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=os.environ.get(self._config.api_key_env) or None,
                timeout=self._config.timeout_s,
                max_retries=self._config.max_retries,
            )
        return self._client

    def _request(self, task: str, system: str, messages: Sequence[Msg], *, max_tokens: int | None = None) -> dict:
        cfg = self._task(task)
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": max_tokens or cfg.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "output_config": {"effort": cfg.effort},
        }
        if self._config.refusal_fallback:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    # --- odpowiedź ----------------------------------------------------------------------

    @staticmethod
    def _check_stop(task: str, response: Any) -> None:
        reason = getattr(response, "stop_reason", None)
        if reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            log.warning("llm refusal task=%s category=%s request_id=%s", task, category, _rid(response))
            raise LLMRefusal(f"odmowa modelu ({category})", category=category)
        if reason == "max_tokens":
            raise LLMIncomplete(f"odpowiedź ucięta (max_tokens) w zadaniu {task}")

    def _log_usage(self, task: str, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        # do evals/: tokeny z odpowiedzi API, nie szacowane
        self.last_usage = {
            "model": getattr(response, "model", None),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "stop_reason": getattr(response, "stop_reason", None),
        }
        log.info(
            "llm task=%s model=%s in=%s out=%s cache_read=%s request_id=%s",
            task,
            getattr(response, "model", "?"),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
            getattr(usage, "cache_read_input_tokens", None),
            _rid(response),
        )

    # --- LLMClient ----------------------------------------------------------------------

    def structured(self, task: str, system: str, user: str, schema: type[T]) -> T:
        kwargs = self._request(task, system, [{"role": "user", "content": user}])
        log.debug("llm structured task=%s user=%s", task, user)  # dane już po pseudonimizacji
        with _translate_errors(task):
            response = self._sdk().beta.messages.parse(**kwargs, output_format=schema)
        self._log_usage(task, response)
        self._check_stop(task, response)
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMIncomplete(f"brak sparsowanej odpowiedzi w zadaniu {task}")
        return parsed

    def text(self, task: str, system: str, messages: Sequence[Msg]) -> str:
        kwargs = self._request(task, system, messages)
        with _translate_errors(task):
            response = self._sdk().beta.messages.create(**kwargs)
        self._log_usage(task, response)
        self._check_stop(task, response)
        return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")

    def stream(self, task: str, system: str, messages: Sequence[Msg]) -> Iterator[str]:
        """Fragmenty tekstu na bieżąco. Odmowa w trakcie → LLMRefusal po ostatnim fragmencie."""
        kwargs = self._request(task, system, messages, max_tokens=STREAM_MAX_TOKENS)
        with _translate_errors(task):
            with self._sdk().beta.messages.stream(**kwargs) as stream:
                yield from stream.text_stream
                final = stream.get_final_message()
        self._log_usage(task, final)
        self._check_stop(task, final)


def _rid(response: Any) -> str | None:
    return getattr(response, "_request_id", None)


class _translate_errors:
    """Wyjątki SDK → nasze `LLMError` (od najbardziej szczegółowego)."""

    def __init__(self, task: str) -> None:
        self.task = task

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None or isinstance(exc, LLMError) or not isinstance(exc, anthropic.AnthropicError):
            return False
        log.warning("llm error task=%s: %s", self.task, exc)
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            raise LLMUnavailable("błędny klucz API lub brak uprawnień") from exc
        if isinstance(exc, anthropic.RateLimitError):
            raise LLMRateLimited(str(exc)) from exc
        if isinstance(exc, anthropic.BadRequestError):
            raise LLMError(f"błędne zapytanie: {exc}") from exc
        if isinstance(exc, anthropic.APIStatusError):
            raise LLMError(f"błąd API {exc.status_code}") from exc
        if isinstance(exc, anthropic.APIConnectionError):  # obejmuje APITimeoutError
            raise LLMError("brak połączenia z API") from exc
        raise LLMError(str(exc)) from exc
