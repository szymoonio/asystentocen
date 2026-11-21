"""Konfiguracja modułu ASSISTANT: config/nudges.yaml (i później config/llm.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class NudgesConfig:
    no_note_after_days: int = 45
    coverage_check_every_days: int = 30
    recency_window_days: int = 90
    recency_share_threshold: float = 0.8
    pre_interview_days: tuple[int, ...] = (60, 30)
    no_positive_after_days: int = 120
    digest: str = "weekly"
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: Path) -> NudgesConfig:
        path = config_dir / "nudges.yaml"
        if not path.exists():
            return cls()
        data = dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        known = {k: data.pop(k) for k in list(data) if k in cls.__dataclass_fields__ and k != "extra"}
        if "pre_interview_days" in known:
            known["pre_interview_days"] = tuple(known["pre_interview_days"])
        return cls(**known, extra=data)
