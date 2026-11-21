"""Deterministyczne zestawienia z suwaków — docs/ARCHITEKTURA.md § 5.2.

Liczymy na `Fraction`, do `float` zamieniamy dopiero na granicy kontraktu (`CriterionStats`).
Trend = średnia z pierwszej i drugiej połowy OKRESU OCENY (od `period_from` do `due_date`),
a nie połowy listy notatek: dzięki temu widać, czy oceny poprawiały się w czasie.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from fractions import Fraction

from app.contracts.enums import PARTIAL_POINTS
from app.contracts.models import CriterionStats, Note


def period_midpoint(period_from: date | None, due_date: date | None) -> date | None:
    if period_from is None or due_date is None or due_date <= period_from:
        return None
    return period_from + (due_date - period_from) / 2


def _median(values: Sequence[int]) -> Fraction:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return Fraction(ordered[mid])
    return Fraction(ordered[mid - 1] + ordered[mid], 2)


def _mean(values: Sequence[int]) -> Fraction | None:
    return Fraction(sum(values), len(values)) if values else None


def _f(value: Fraction | None) -> float | None:
    return float(value) if value is not None else None


def compute_stats(
    notes: Sequence[Note],
    *,
    criteria_codes: Sequence[str] = (),
    period_from: date | None = None,
    due_date: date | None = None,
) -> list[CriterionStats]:
    """Zestawienie per kryterium.

    `criteria_codes` — kryteria bieżącej oceny; każde pojawia się w wyniku, także bez ocen
    (`n_ratings == 0` = brak pokrycia). Kryteria ocenione w notatkach, ale spoza tej listy,
    dochodzą na końcu (np. kryterium, które wypadło z oceny po zmianie kryteriów).

    Gdy nie znamy okresu oceny, dzielimy w połowie między pierwszą a ostatnią obserwacją.
    """
    by_code: dict[str, list[tuple[date, int]]] = {code: [] for code in criteria_codes}
    for note in notes:
        for rating in note.ratings:
            by_code.setdefault(rating.criterion_code, []).append((note.observed_on, rating.value))

    midpoint = period_midpoint(period_from, due_date)
    result: list[CriterionStats] = []
    for code, items in by_code.items():
        items.sort()
        values = [v for _, v in items]
        if not values:
            result.append(CriterionStats(criterion_code=code, n_ratings=0, distribution={}))
            continue
        split = midpoint or period_midpoint(items[0][0], items[-1][0])
        if split is None:  # jedna data obserwacji — nie ma czego dzielić
            first, second = [], values
        else:
            first = [v for d, v in items if d < split]
            second = [v for d, v in items if d >= split]
        result.append(
            CriterionStats(
                criterion_code=code,
                n_ratings=len(values),
                distribution={p: values.count(p) for p in PARTIAL_POINTS if p in values},
                median=_f(_median(values)),
                first_half_mean=_f(_mean(first)),
                second_half_mean=_f(_mean(second)),
                last_rated_on=items[-1][0],
            )
        )
    return result


def uncovered(stats: Sequence[CriterionStats]) -> list[str]:
    """Kody kryteriów bez żadnej oceny suwakiem."""
    return [s.criterion_code for s in stats if s.n_ratings == 0]
