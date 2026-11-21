"""Porty (interfejsy) między modułami. ZAMROŻONE (krok 0).

Kto implementuje / kto używa:
    CriteriaCatalog    — krok 0 (app/contracts/regulation.py) / A i B
    EmployeeDirectory  — A / B (i powłoka aplikacji)
    EvaluationReader   — A / B
    ReminderSink       — A / B (B wysyła przez nie przypomnienia o notatkach)
    ReminderProvider   — A i B / scheduler A
    DraftProvider      — B / A (formularz pokazuje projekty tekstów)
    NotesReader        — B / A (panel „Twoje obserwacje” w Części II)

Do czasu merge'u każdy moduł działa na implementacjach z app/contracts/fakes.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from app.contracts.enums import DraftField, SheetType
from app.contracts.models import (
    Absence,
    CriterionDef,
    CriterionStats,
    DraftSuggestion,
    Employee,
    EvaluationSummary,
    Note,
    Office,
    OrgUnit,
    Reminder,
)


@runtime_checkable
class CriteriaCatalog(Protocol):
    def all(self) -> list[CriterionDef]: ...
    def get(self, code: str) -> CriterionDef: ...  # KeyError, gdy brak
    def by_name(self, name: str) -> CriterionDef | None: ...  # nazwa lub alias, bez wielkości liter
    def mandatory_for(self, sheet: SheetType) -> list[CriterionDef]: ...
    def additional_for(self, sheet: SheetType) -> list[CriterionDef]: ...  # katalog minus obowiązkowe


@runtime_checkable
class EmployeeDirectory(Protocol):
    def office(self) -> Office: ...
    def org_unit(self, unit_id: str) -> OrgUnit: ...
    def get(self, employee_id: str) -> Employee: ...  # KeyError, gdy brak
    def all(self) -> list[Employee]: ...
    def subordinates(self, evaluator_id: str) -> list[Employee]: ...
    def absences(self, employee_id: str) -> list[Absence]: ...


@runtime_checkable
class EvaluationReader(Protocol):
    def get(self, evaluation_id: str) -> EvaluationSummary: ...  # KeyError, gdy brak
    def current_for(self, employee_id: str) -> EvaluationSummary | None: ...  # trwający cykl
    def for_evaluator(self, evaluator_id: str) -> list[EvaluationSummary]: ...  # trwające cykle
    def history(self, employee_id: str) -> list[EvaluationSummary]: ...  # zakończone, od najstarszej


@runtime_checkable
class ReminderSink(Protocol):
    def emit(self, reminders: Sequence[Reminder]) -> int: ...  # zwraca liczbę nowych (po dedupe)
    def inbox(self, recipient_id: str) -> list[Reminder]: ...


@runtime_checkable
class ReminderProvider(Protocol):
    name: str

    def due(self, today: date) -> list[Reminder]: ...


@runtime_checkable
class DraftProvider(Protocol):
    def available(self) -> bool: ...
    def drafts(self, evaluation_id: str, field: DraftField) -> list[DraftSuggestion]: ...


@runtime_checkable
class NotesReader(Protocol):
    """Zawsze w imieniu autora: notatki są prywatne dla przełożonego, który je napisał."""

    def notes_for(
        self,
        author_id: str,
        subject_id: str,
        *,
        since: date | None = None,
        until: date | None = None,
    ) -> list[Note]: ...

    def stats_for(self, author_id: str, subject_id: str, evaluation_id: str) -> list[CriterionStats]: ...

    def teczka_url(self, subject_id: str) -> str: ...
