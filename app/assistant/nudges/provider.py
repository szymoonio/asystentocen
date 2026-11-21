"""`NoteNudges` — `ReminderProvider` z tygodniowym zestawieniem na przełożonego (§ 5.4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.assistant.config import NudgesConfig
from app.assistant.notes.criteria import criteria_for
from app.assistant.notes.repository import NotesRepository
from app.assistant.nudges.rules import Finding, check_subject, count
from app.assistant.nudges.snooze import SnoozeRepository
from app.contracts.enums import ReminderKind
from app.contracts.models import Employee, Reminder
from app.contracts.ports import CriteriaCatalog, EmployeeDirectory, EvaluationReader


@dataclass
class PersonNudges:
    employee: Employee
    findings: list[Finding]


@dataclass
class Digest:
    supervisor_id: str
    today: date
    people: list[PersonNudges] = field(default_factory=list)
    snoozed: dict[str, date] = field(default_factory=dict)  # subject_id → do kiedy

    @property
    def empty(self) -> bool:
        return not self.people

    @property
    def n_items(self) -> int:
        return sum(len(p.findings) for p in self.people)

    def lines(self) -> list[str]:
        return [f"{p.employee.full_name}: {f.text}" for p in self.people for f in p.findings]


def week_key(today: date) -> str:
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


class NoteNudges:
    name = "assistant.note_nudges"

    def __init__(
        self,
        *,
        employees: Callable[[], EmployeeDirectory],
        evaluations: Callable[[], EvaluationReader],
        catalog: CriteriaCatalog,
        notes: NotesRepository,
        snoozes: SnoozeRepository,
        config: NudgesConfig,
    ) -> None:
        # porty jako funkcje: kontener może je podmienić po rejestracji modułu
        self._employees = employees
        self._evaluations = evaluations
        self._catalog = catalog
        self._notes = notes
        self._snoozes = snoozes
        self.config = config

    def digest_for(self, supervisor_id: str, today: date) -> Digest:
        employees = self._employees()
        evaluations = self._evaluations()
        digest = Digest(supervisor_id=supervisor_id, today=today, snoozed=self._snoozes.active(supervisor_id, today))
        for evaluation in evaluations.for_evaluator(supervisor_id):
            if evaluation.employee_id in digest.snoozed:
                continue
            try:
                subject = employees.get(evaluation.employee_id)
            except KeyError:
                continue
            all_notes = self._notes.current(supervisor_id, subject.id)
            check = check_subject(
                subject=subject,
                evaluation=evaluation,
                history=evaluations.history(subject.id),
                notes=[n for n in all_notes if n.evaluation_id == evaluation.id],
                all_notes=all_notes,
                criteria=criteria_for(evaluation, self._catalog).current,
                absences=employees.absences(subject.id),
                today=today,
                cfg=self.config,
            )
            if check.findings:
                digest.people.append(PersonNudges(subject, check.findings))
        return digest

    def due(self, today: date) -> list[Reminder]:
        reminders = []
        evaluations = self._evaluations()
        for supervisor in self._employees().all():
            if not evaluations.for_evaluator(supervisor.id):
                continue
            digest = self.digest_for(supervisor.id, today)
            if digest.empty:
                continue
            header = f"Teczka — przegląd tygodnia ({count(digest.n_items, 'sprawa', 'sprawy', 'spraw')}):"
            reminders.append(
                Reminder(
                    recipient_id=supervisor.id,
                    kind=ReminderKind.NOTE_NUDGE,
                    message="\n".join([header, *(f"• {line}" for line in digest.lines())]),
                    dedupe_key=f"nudge:{supervisor.id}:{week_key(today)}",
                    due=today,
                    link="/asystent/teczka",
                )
            )
        return reminders
