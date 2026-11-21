"""Implementacje portów w pamięci, oparte na seed/office.yaml. ZAMROŻONE (krok 0).

Służą do pracy równoległej: agent A testuje na FakeNotesReader / NullDraftProvider,
agent B na FakeEmployeeDirectory / FakeEvaluationReader / CollectingReminderSink.
Po merge'u prawdziwe implementacje podmieniają je w `register()` modułów.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from app.contracts.enums import DraftField, EvaluationState, Role
from app.contracts.models import (
    Absence,
    CriterionRef,
    CriterionStats,
    DraftSuggestion,
    Employee,
    EvaluationResult,
    EvaluationSummary,
    Note,
    Office,
    OrgUnit,
    Reminder,
)
from app.contracts.ports import CriteriaCatalog

_CLOSED = {EvaluationState.FINAL, EvaluationState.CANCELLED}


@dataclass
class Seed:
    office: Office
    org_units: list[OrgUnit]
    employees: list[Employee]
    absences: list[Absence]
    evaluations: list[dict]  # surowe rekordy; EvaluationSummary budowane z katalogiem kryteriów
    notes: list[Note] = field(default_factory=list)


def load_seed(path: Path) -> Seed:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Seed(
        office=Office(**data["office"]),
        org_units=[OrgUnit(**u) for u in data["org_units"]],
        employees=[Employee(**e) for e in data["employees"]],
        absences=[Absence(**a) for a in data.get("absences", [])],
        evaluations=list(data.get("evaluations", [])),
        notes=[Note(**n) for n in data.get("notes", [])],
    )


def evaluation_from_record(record: dict, catalog: CriteriaCatalog) -> EvaluationSummary:
    from app.contracts.enums import SheetType

    sheet = SheetType(record["sheet"])
    criteria = [CriterionRef(code=c.code, name=c.name, mandatory=True) for c in catalog.mandatory_for(sheet)]
    criteria += [
        CriterionRef(code=code, name=catalog.get(code).name, mandatory=False) for code in record.get("additional", [])
    ]
    fields = {k: v for k, v in record.items() if k not in {"additional", "result"}}
    result = EvaluationResult(**record["result"]) if record.get("result") else None
    return EvaluationSummary(**fields, criteria=criteria, result=result)


class FakeEmployeeDirectory:
    def __init__(self, seed: Seed) -> None:
        self._seed = seed
        self._by_id = {e.id: e for e in seed.employees}
        self._units = {u.id: u for u in seed.org_units}

    def office(self) -> Office:
        return self._seed.office

    def org_unit(self, unit_id: str) -> OrgUnit:
        return self._units[unit_id]

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]

    def all(self) -> list[Employee]:
        return list(self._seed.employees)

    def subordinates(self, evaluator_id: str) -> list[Employee]:
        return [e for e in self._seed.employees if e.supervisor_id == evaluator_id and e.active]

    def absences(self, employee_id: str) -> list[Absence]:
        return [a for a in self._seed.absences if a.employee_id == employee_id]


class FakeEvaluationReader:
    def __init__(self, seed: Seed, catalog: CriteriaCatalog) -> None:
        self._evals = [evaluation_from_record(r, catalog) for r in seed.evaluations]
        self._by_id = {e.id: e for e in self._evals}

    def get(self, evaluation_id: str) -> EvaluationSummary:
        return self._by_id[evaluation_id]

    def current_for(self, employee_id: str) -> EvaluationSummary | None:
        open_ = [e for e in self._evals if e.employee_id == employee_id and e.state not in _CLOSED]
        return open_[-1] if open_ else None

    def for_evaluator(self, evaluator_id: str) -> list[EvaluationSummary]:
        return [e for e in self._evals if e.evaluator_id == evaluator_id and e.state not in _CLOSED]

    def history(self, employee_id: str) -> list[EvaluationSummary]:
        done = [e for e in self._evals if e.employee_id == employee_id and e.state == EvaluationState.FINAL]
        return sorted(done, key=lambda e: e.result.assessed_on if e.result else date.min)


class CollectingReminderSink:
    """Zbiera przypomnienia w pamięci z deduplikacją po `dedupe_key`."""

    def __init__(self) -> None:
        self.items: list[Reminder] = []
        self._keys: set[str] = set()

    def emit(self, reminders: Sequence[Reminder]) -> int:
        new = 0
        for r in reminders:
            if r.dedupe_key in self._keys:
                continue
            self._keys.add(r.dedupe_key)
            self.items.append(r)
            new += 1
        return new

    def inbox(self, recipient_id: str) -> list[Reminder]:
        return [r for r in self.items if r.recipient_id == recipient_id]


class NullDraftProvider:
    """Brak asystenta: formularz działa, po prostu nie pokazuje projektów tekstu."""

    def available(self) -> bool:
        return False

    def drafts(self, evaluation_id: str, field: DraftField) -> list[DraftSuggestion]:
        return []


class FakeNotesReader:
    def __init__(self, seed: Seed) -> None:
        self._notes = list(seed.notes)

    def notes_for(
        self, author_id: str, subject_id: str, *, since: date | None = None, until: date | None = None
    ) -> list[Note]:
        notes = [n for n in self._notes if n.author_id == author_id and n.subject_id == subject_id]
        if since:
            notes = [n for n in notes if n.observed_on >= since]
        if until:
            notes = [n for n in notes if n.observed_on <= until]
        return sorted(notes, key=lambda n: n.observed_on)

    def stats_for(self, author_id: str, subject_id: str, evaluation_id: str) -> list[CriterionStats]:
        notes = [n for n in self.notes_for(author_id, subject_id) if n.evaluation_id == evaluation_id]
        by_code: dict[str, list[tuple[date, int]]] = {}
        for n in notes:
            for r in n.ratings:
                by_code.setdefault(r.criterion_code, []).append((n.observed_on, r.value))
        stats = []
        for code, items in sorted(by_code.items()):
            items.sort()
            values = [v for _, v in items]
            half = len(values) // 2
            stats.append(
                CriterionStats(
                    criterion_code=code,
                    n_ratings=len(values),
                    distribution={p: values.count(p) for p in sorted(set(values))},
                    median=float(statistics.median(values)),
                    first_half_mean=statistics.fmean(values[:half]) if half else None,
                    second_half_mean=statistics.fmean(values[half:]),
                    last_rated_on=items[-1][0],
                )
            )
        return stats

    def teczka_url(self, subject_id: str) -> str:
        return f"/asystent/teczka/{subject_id}"


def roles_for(employee: Employee, directory: FakeEmployeeDirectory | object) -> frozenset[Role]:
    """Role użytkownika demo: OCENIANY zawsze, OCENIAJACY gdy ma podwładnych, plus extra_roles."""
    roles = {Role.OCENIANY, *employee.extra_roles}
    if directory.subordinates(employee.id):  # type: ignore[attr-defined]
        roles.add(Role.OCENIAJACY)
    return frozenset(roles)
