"""Warstwa LLM (docs/ARCHITEKTURA.md § 6.4). Domena zna tylko `LLMClient` z `base.py`."""

from __future__ import annotations

import logging
import os

from app.assistant.llm.base import (
    LLMClient,
    LLMError,
    LLMIncomplete,
    LLMRateLimited,
    LLMRefusal,
    LLMUnavailable,
    Msg,
    generator_id,
)
from app.assistant.llm.config import LLMConfig
from app.assistant.llm.null import NullClient

__all__ = [
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "LLMIncomplete",
    "LLMRateLimited",
    "LLMRefusal",
    "LLMUnavailable",
    "Msg",
    "NullClient",
    "build_client",
    "generator_id",
]

log = logging.getLogger("asystent.llm")


def build_client(config: LLMConfig) -> LLMClient:
    """Bez klucza w zmiennej z configu (domyślnie ANTHROPIC_API_KEY) aplikacja działa na NullClient."""
    if config.provider == "anthropic":
        if not os.environ.get(config.api_key_env):
            log.info("LLM wyłączony: brak %s", config.api_key_env)
            return NullClient(f"brak {config.api_key_env}")
        from app.assistant.llm.claude import ClaudeClient

        return ClaudeClient(config)
    return NullClient(f"provider={config.provider}")
