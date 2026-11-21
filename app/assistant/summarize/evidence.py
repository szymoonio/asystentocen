"""Materiał do podsumowania cyklu: notatki oceniającego o ocenianym z jednego cyklu oceny.

Wszystko tu jest deterministyczne. Dane wrażliwe są odfiltrowane od razu (`excluded`),
więc ani szkielet, ani LLM nie widzą wykluczonych notatek.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import yaml

from app.assistant.notes.criteria import criteria_for
from app.assistant.notes.repository import NotesRepository
from app.assistant.notes.stats import compute_stats
from app.assistant.privacy import ExcludedNote, screen_notes
from app.contracts.models import CriterionDef, CriterionStats, Employee, EvaluationSummary, Note
from app.contracts.ports import CriteriaCatalog, EmployeeDirectory, EvaluationReader

ACTIONS_PATH = Path(__file__).with_name("development_actions.yaml")
LOW_THRESHOLD = 3  # ocena cząstkowa ≤ 3 → kierunek rozwoju w IPRZ (§ 6.2)


def load_development_actions(path: Path = ACTIONS_PATH) -> dict[str, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {code: list(items) for code, items in (data.get("actions") or {}).items()}


@dataclass(frozen=True)
class EvidenceItem:
    note_id: str
    item_id: str  # B, S1, I2 — w obrębie notatki
    kind: str  # body | strength | improvement
    text: str
    criteria: tuple[str, ...]  # z podpowiedzi LLM, a bez nich z suwaków notatki (tylko opis)


@dataclass
class CycleEvidence:
    evaluation: EvaluationSummary
    subject: Employee
    author_id: str
    criteria: list[CriterionDef]
    notes: list[Note]  # bezpieczne do użycia, chronologicznie
    excluded: list[ExcludedNote]
    items: list[EvidenceItem]
    stats: list[CriterionStats]
    low_criteria: list[str]  # kody kryteriów do IPRZ
    low_source: str  # "ocena" (wpisane oceny cząstkowe) | "notatki" (mediana suwaków) | ""
    hints_used: bool = False
    _by_id: dict[str, Note] = field(default_factory=dict, repr=False)

    def note(self, note_id: str) -> Note:
        return self._by_id[note_id]

    def by_criterion(self) -> dict[str, list[EvidenceItem]]:
        groups: dict[str, list[EvidenceItem]] = {c.code: [] for c in self.criteria}
        for item in self.items:
            for code in item.criteria:
                groups.setdefault(code, []).append(item)
        return groups

    def unassigned(self) -> list[EvidenceItem]:
        return [i for i in self.items if not i.criteria]

    @property
    def input_key(self) -> str:
        """Zmienia się, gdy zmienią się notatki lub wpisane oceny — wtedy projekt LLM jest nieaktualny."""
        result = self.evaluation.result
        parts = [n.id for n in self.notes] + sorted(f"{k}={v}" for k, v in (result.partial_points if result else {}).items())
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class EvidenceBuilder:
    def __init__(
        self,
        *,
        repo: NotesRepository,
        evaluations: EvaluationReader,
        employees: EmployeeDirectory,
        catalog: CriteriaCatalog,
    ) -> None:
        self.repo = repo
        self.evaluations = evaluations
        self.employees = employees
        self.catalog = catalog

    def build(self, evaluation_id: str) -> CycleEvidence | None:
        """None, gdy nie ma oceny albo oceniającego z urzędu (wtedy nie ma też notatek)."""
        try:
            evaluation = self.evaluations.get(evaluation_id)
        except KeyError:
            return None
        if evaluation.evaluator_id is None:
            return None
        subject = self.employees.get(evaluation.employee_id)
        author = evaluation.evaluator_id
        cycle_notes = [n for n in self.repo.current(author, subject.id) if n.evaluation_id == evaluation.id]
        screened = screen_notes(cycle_notes)
        notes = screened.included
        hints = self.repo.hints_for(n.id for n in notes)
        criteria = criteria_for(evaluation, self.catalog).current
        stats = compute_stats(
            notes,
            criteria_codes=[c.code for c in criteria],
            period_from=evaluation.period_from,
            due_date=evaluation.due_date,
        )
        low, source = _low_criteria(evaluation, stats)
        return CycleEvidence(
            evaluation=evaluation,
            subject=subject,
            author_id=author,
            criteria=criteria,
            notes=notes,
            excluded=screened.excluded,
            items=[item for n in notes for item in _items(n, hints.get(n.id))],
            stats=stats,
            low_criteria=low,
            low_source=source,
            hints_used=bool(hints),
            _by_id={n.id: n for n in notes},
        )


def _items(note: Note, hints: list[dict] | None) -> list[EvidenceItem]:
    by_text: dict[str, list[str]] = {}
    for h in hints or []:
        by_text.setdefault(h["item"], []).append(h["criterion_code"])
    sliders = tuple(r.criterion_code for r in note.ratings)
    raw = []
    if note.body.strip():
        raw.append(("B", "body", note.body.strip()))
    raw += [(f"S{i}", "strength", s) for i, s in enumerate(note.strengths, 1)]
    raw += [(f"I{i}", "improvement", s) for i, s in enumerate(note.improvements, 1)]
    items = []
    for item_id, kind, text in raw:
        if hints is not None:
            criteria = tuple(dict.fromkeys(by_text.get(text, [])))
        else:
            criteria = sliders if kind == "body" else ()
        items.append(EvidenceItem(note.id, item_id, kind, text, criteria))
    return items


def _low_criteria(evaluation: EvaluationSummary, stats: list[CriterionStats]) -> tuple[list[str], str]:
    if evaluation.result:
        points = evaluation.result.partial_points
        return [code for code, value in points.items() if value <= LOW_THRESHOLD], "ocena"
    low = [s.criterion_code for s in stats if s.median is not None and Fraction(s.median) <= LOW_THRESHOLD]
    return low, ("notatki" if low else "")
