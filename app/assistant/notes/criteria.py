"""Które kryteria pokazać przy suwakach notatki (§ 5.1)."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.enums import EvaluationState
from app.contracts.models import CriterionDef, EvaluationSummary
from app.contracts.ports import CriteriaCatalog


@dataclass(frozen=True)
class CriteriaChoice:
    current: list[CriterionDef]  # kryteria bieżącej oceny (przed ustaleniem: obowiązkowe z arkusza)
    other: list[CriterionDef]  # reszta katalogu — sekcja „inne kryteria”

    @property
    def current_codes(self) -> list[str]:
        return [c.code for c in self.current]


def criteria_for(evaluation: EvaluationSummary | None, catalog: CriteriaCatalog) -> CriteriaChoice:
    if evaluation is None:
        current: list[CriterionDef] = []
    elif evaluation.state == EvaluationState.CYCLE_OPEN or not evaluation.criteria:
        current = catalog.mandatory_for(evaluation.sheet)
    else:
        current = [catalog.get(ref.code) for ref in evaluation.criteria]
    codes = {c.code for c in current}
    return CriteriaChoice(current=current, other=[c for c in catalog.all() if c.code not in codes])
