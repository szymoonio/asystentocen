"""Konfiguracja modułu ASSISTANT: config/nudges.yaml (i później config/llm.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class NudgesConfig:
    no_note_after_days: int = 45
    coverage_min_cycle_days: int = 30
    recency_window_days: int = 90
    recency_share_threshold: float = 0.8
    recency_min_notes: int = 3
    pre_interview_days: tuple[int, ...] = (60, 30)
    no_positive_after_days: int = 120
    return_min_absence_days: int = 30
    return_window_days: int = 30
    snooze_days: int = 14
    digest: str = "weekly"
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: Path) -> NudgesConfig:
        path = config_dir / "nudges.yaml"
        if not path.exists():
            return cls()
        data = dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        names = {f.name for f in fields(cls)} - {"extra"}
        known = {k: data.pop(k) for k in list(data) if k in names}
        if "pre_interview_days" in known:
            known["pre_interview_days"] = tuple(known["pre_interview_days"])
        return cls(**known, extra=data)
