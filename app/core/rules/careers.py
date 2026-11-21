"""Arkusz właściwy dla stanowiska i stopnie służbowe."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.contracts.enums import Level, Outcome, SheetType
from app.contracts.models import Employee, EvaluationSummary, Position
from app.core.rules.deadlines import Deadline, promotion_deadline

PROMOTION_LEVELS = frozenset({Level.POWYZEJ, Level.ZNACZNIE_POWYZEJ})
MAX_GRADE = 9

ORDINALS = {
    1: "pierwszego", 2: "drugiego", 3: "trzeciego", 4: "czwartego", 5: "piątego",
    6: "szóstego", 7: "siódmego", 8: "ósmego", 9: "dziewiątego",
}  # fmt: skip


def sheet_for(position: Position) -> SheetType:
    """§ 3 rozporządzenia."""
    if position.is_head_of_office:
        return SheetType.A
    if position.manages_people:
        return SheetType.B
    return SheetType.C


def next_grade_text(current_grade: int | None) -> str | None:
    """„wnioskuję o przyznanie ____ stopnia służbowego” (część III)."""
    if current_grade is None or current_grade >= MAX_GRADE:
        return None
    return ORDINALS[current_grade + 1]


@dataclass(frozen=True)
class ObligatoryPromotion:
    employee_id: str
    evaluation_ids: tuple[str, str]
    deadline: Deadline
    next_grade: int


def obligatory_promotion(employee: Employee, history: Sequence[EvaluationSummary]) -> ObligatoryPromotion | None:
    """Art. 89 ust. 2: dwie kolejne pozytywne oceny na jednym z dwóch najwyższych poziomów,
    uzyskane od otrzymania ostatniego stopnia → kolejny stopień w 30 dni od zapoznania."""
    if not employee.is_urzednik or (employee.grade or 0) >= MAX_GRADE:
        return None
    since = employee.grade_granted_on or date.min
    results = [
        e for e in history
        if e.result and e.result.assessed_on >= since and e.result.acknowledged_on
    ]  # fmt: skip
    results.sort(key=lambda e: e.result.assessed_on)  # type: ignore[union-attr]
    if len(results) < 2:
        return None
    prev, last = results[-2], results[-1]
    if all(
        e.result.outcome == Outcome.POZYTYWNA and e.result.level in PROMOTION_LEVELS  # type: ignore[union-attr]
        for e in (prev, last)
    ):
        return ObligatoryPromotion(
            employee_id=employee.id,
            evaluation_ids=(prev.id, last.id),
            deadline=promotion_deadline(last.result.acknowledged_on),  # type: ignore[union-attr,arg-type]
            next_grade=(employee.grade or 0) + 1,
        )
    return None
