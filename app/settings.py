"""Ustawienia z zmiennych środowiskowych. ZAMROŻONE (krok 0)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str
    regulation_dir: Path
    config_dir: Path
    seed_path: Path
    demo_today: date | None  # „podróż w czasie” na demo; None = prawdziwa data

    @classmethod
    def from_env(cls) -> Settings:
        today = os.getenv("DEMO_TODAY")
        return cls(
            database_url=os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'app.db'}"),
            regulation_dir=Path(os.getenv("REGULATION_DIR", ROOT / "config" / "regulation" / "v2016")),
            config_dir=Path(os.getenv("CONFIG_DIR", ROOT / "config")),
            seed_path=Path(os.getenv("SEED_PATH", ROOT / "seed" / "office.yaml")),
            demo_today=date.fromisoformat(today) if today else None,
        )
