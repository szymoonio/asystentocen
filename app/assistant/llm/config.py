"""Konfiguracja LLM z config/llm.yaml. Zadanie nieobecne na liście = funkcja ukryta w UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class TaskConfig:
    model: str
    effort: str = "medium"
    max_tokens: int = 16000

    def __post_init__(self) -> None:
        if self.effort not in EFFORTS:
            raise ValueError(f"nieznany effort {self.effort!r}, dozwolone: {EFFORTS}")


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "none"  # anthropic | none (później: local)
    api_key_env: str = "ANTHROPIC_API_KEY"
    refusal_fallback: bool = True
    timeout_s: float = 120.0
    max_retries: int = 2
    tasks: dict[str, TaskConfig] = field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: Path) -> LLMConfig:
        path = config_dir / "llm.yaml"
        if not path.exists():
            return cls()
        data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("llm", {})
        anthropic = data.get("anthropic", {}) or {}
        return cls(
            provider=data.get("provider", "none"),
            api_key_env=anthropic.get("api_key_env", "ANTHROPIC_API_KEY"),
            refusal_fallback=anthropic.get("refusal_fallback", True),
            timeout_s=float(anthropic.get("timeout_s", 120.0)),
            max_retries=int(anthropic.get("max_retries", 2)),
            tasks={name: TaskConfig(**cfg) for name, cfg in (data.get("tasks") or {}).items()},
        )
