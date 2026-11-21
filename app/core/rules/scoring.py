"""Wynik oceny — § 11 ust. 1 rozporządzenia. Wyłącznie na ułamkach (Fraction)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from app.contracts.enums import Level, Outcome
from app.contracts.regulation import Scale, load_scale
from app.settings import Settings


@dataclass(frozen=True)
class ScoreResult:
    mean: Fraction
    level: Level
    outcome: Outcome
    forced_negative: bool  # negatywna mimo poziomu ≥ „na poziomie” (cząstkowa = 1)


@lru_cache(maxsize=4)
def _scale(regulation_dir: Path) -> Scale:
    return load_scale(regulation_dir)


def default_scale() -> Scale:
    return _scale(Settings.from_env().regulation_dir)


def level_for(mean: Fraction, scale: Scale | None = None) -> Level:
    scale = scale or default_scale()
    for band in scale.levels:
        if band.contains(mean):
            return band.level
    raise ValueError(f"średnia {mean} poza skalą")


def score(points: Sequence[int], scale: Scale | None = None) -> ScoreResult:
    scale = scale or default_scale()
    if not points:
        raise ValueError("brak ocen cząstkowych")
    invalid = [p for p in points if p not in scale.partial_points]
    if invalid:
        raise ValueError(f"niedozwolone oceny cząstkowe: {invalid}")
    mean = Fraction(sum(points), len(points))
    level = level_for(mean, scale)
    has_floor = scale.negative_if_any_partial_equals in points
    positive = level in scale.positive_levels and not has_floor
    return ScoreResult(
        mean=mean,
        level=level,
        outcome=Outcome.POZYTYWNA if positive else Outcome.NEGATYWNA,
        forced_negative=has_floor and level in scale.positive_levels,
    )


def format_mean(mean: Fraction) -> str:
    """Wyświetlanie: 2 miejsca po przecinku, zaokrąglenie połówkowe w górę (np. 27/7 → „3,86”).

    Klasyfikacja zawsze na wartości dokładnej. Sposób wyświetlania do potwierdzenia z KPRM —
    przykładowe arkusze są niespójne (obcięcie „3,8” vs „6,25”).
    """
    hundredths = (mean * 100 + Fraction(1, 2)).__floor__()
    whole, frac = divmod(hundredths, 100)
    text = f"{whole},{frac:02d}".rstrip("0").rstrip(",")
    return text
