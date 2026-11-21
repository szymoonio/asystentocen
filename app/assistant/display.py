"""Wspólne elementy widoków B: czas słownie, średnie z suwaków w kolorze poziomu, dane do wykresów.

Średnie liczymy na `Fraction`; kolor bierzemy z przedziałów § 11 (config/regulation/…/scale.yaml).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from app.contracts.enums import LEVEL_LABELS, Level
from app.contracts.models import Note
from app.contracts.regulation import Scale

TONES = {
    Level.ZNACZNIE_PONIZEJ: "l1", Level.PONIZEJ: "l2", Level.NA_POZIOMIE: "l3",
    Level.POWYZEJ: "l4", Level.ZNACZNIE_POWYZEJ: "l5",
}  # fmt: skip


def plural(n: int, one: str, few: str, many: str) -> str:
    """1 notatka · 2 notatki · 5 notatek · 22 notatki · 12 notatek."""
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def ago(day: date | None, today: date) -> str:
    """„dziś”, „wczoraj”, „5 dni temu”, „3 tygodnie temu”, „2 miesiące temu”, „ponad rok temu”."""
    if day is None:
        return "brak notatek"
    days = (today - day).days
    if days <= 0:
        return "dziś"
    if days == 1:
        return "wczoraj"
    if days < 14:
        return f"{days} dni temu"
    if days < 60:
        weeks = days // 7
        return f"{weeks} {plural(weeks, 'tydzień', 'tygodnie', 'tygodni')} temu"
    if days < 365:
        months = days // 30
        return f"{months} {plural(months, 'miesiąc', 'miesiące', 'miesięcy')} temu"
    return "ponad rok temu"


def fmt(value: Fraction | float | None) -> str:
    if value is None:
        return "—"
    return f"{round(float(value), 1):g}".replace(".", ",")


@dataclass(frozen=True)
class Mean:
    value: Fraction
    n: int
    tone: str
    label: str  # słownie: poziom z § 11

    @property
    def text(self) -> str:
        return fmt(self.value)

    @property
    def count(self) -> str:
        return f"{self.n} {plural(self.n, 'ocena', 'oceny', 'ocen')}"


def mean_of(values: Sequence[int], scale: Scale) -> Mean | None:
    if not values:
        return None
    value = Fraction(sum(values), len(values))
    band = next(b for b in scale.levels if b.contains(value))
    return Mean(value, len(values), TONES[band.level], LEVEL_LABELS[band.level])


def ratings_by_criterion(notes: Iterable[Note]) -> dict[str, list[tuple[date, int, str]]]:
    """kod → [(data, punkty, id notatki)] posortowane po dacie."""
    out: dict[str, list[tuple[date, int, str]]] = {}
    for n in notes:
        for r in n.ratings:
            out.setdefault(r.criterion_code, []).append((n.observed_on, r.value, n.id))
    for items in out.values():
        items.sort()
    return out


def trend(items: Sequence[tuple[date, int, str]], *, threshold: Fraction = Fraction(1)) -> str:
    """'up' / 'down' / '' — średnia z drugiej połowy obserwacji vs pierwszej (min. 2 + 2)."""
    if len(items) < 4:
        return ""
    half = len(items) // 2
    first = Fraction(sum(v for _, v, _ in items[:half]), half)
    second = Fraction(sum(v for _, v, _ in items[half:]), len(items) - half)
    if second - first >= threshold:
        return "up"
    if first - second >= threshold:
        return "down"
    return ""


def chart_series(notes: Iterable[Note], names: dict[str, str]) -> dict:
    """Dane dla static/assistant/charts.js: punkty w czasie per kryterium + średnia z notatki."""
    notes = sorted(notes, key=lambda n: n.observed_on)
    by_code = ratings_by_criterion(notes)
    series = {code: [[d.isoformat(), v, nid] for d, v, nid in items] for code, items in by_code.items()}
    overall = [
        [n.observed_on.isoformat(), round(sum(r.value for r in n.ratings) / len(n.ratings), 2), n.id]
        for n in notes if n.ratings
    ]  # fmt: skip
    order = [code for code in names if code in series] + sorted(c for c in series if c not in names)
    return {
        "criteria": [{"code": "", "name": "Średnia z notatki"}]
        + [{"code": code, "name": names.get(code, code)} for code in order],
        "series": {"": overall, **series},
    }
