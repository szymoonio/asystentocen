"""Przypomnienia o terminach procesu (ReminderProvider) — harmonogram w config/reminders.yaml.

Zasada „kubełków”: dla terminu za N dni wysyłamy przypomnienie z najmniejszym progiem ≥ N
(np. progi 14/7/1 i 5 dni do terminu → kubełek 7). Dzięki dedupe po kluczu przypomnienie
nie zginie, gdy scheduler opuści dzień, i nie zostanie wysłane dwa razy.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import yaml

from app.contracts.enums import EvaluationState, ReminderKind, Role
from app.contracts.models import Employee, EvaluationSummary, Reminder
from app.core.rules.careers import obligatory_promotion
from app.core.rules.deadlines import objection_deadline

if TYPE_CHECKING:
    from app.container import Container

CRITERIA_PHASE = {EvaluationState.CYCLE_OPEN, EvaluationState.CRITERIA_CONFIRMED}
ASSESSMENT_PHASE = {EvaluationState.OBSERVATION, EvaluationState.INTERVIEW_HELD}


def _bucket(days_left: int, thresholds: list[int]) -> int | None:
    fitting = [t for t in sorted(thresholds) if t >= days_left]
    return fitting[0] if fitting else None


def _days(n: int) -> str:
    return "1 dzień" if n == 1 else f"{n} dni"


class ProcessReminders:
    name = "core.process"

    def __init__(self, c: Container) -> None:
        self._c = c
        self._cfg = yaml.safe_load((c.settings.config_dir / "reminders.yaml").read_text(encoding="utf-8"))

    def _hr_ids(self) -> list[str]:
        return [e.id for e in self._c.employees.all() if Role.KADRY in e.extra_roles]

    def due(self, today: date) -> list[Reminder]:
        c = self._c
        out: list[Reminder] = []
        hr = self._hr_ids()
        open_evals = c.evaluations.open_all() if hasattr(c.evaluations, "open_all") else []
        for ev in open_evals:
            employee = c.employees.get(ev.employee_id)
            out += self._for_evaluation(ev, employee, today, hr)
        for employee in c.employees.all():
            out += self._promotion(employee, today, hr)
        return out

    def _evaluator_recipients(self, ev: EvaluationSummary, hr: list[str]) -> list[str]:
        return [ev.evaluator_id] if ev.evaluator_id else hr  # oceniający spoza urzędu → kadry

    def _for_evaluation(self, ev: EvaluationSummary, emp: Employee, today: date, hr: list[str]) -> list[Reminder]:
        out: list[Reminder] = []
        link = f"/core/oceny/{ev.id}"
        who = emp.full_name

        def add(recipient: str, kind: ReminderKind, key: str, message: str, due: date | None) -> None:
            out.append(
                Reminder(
                    recipient_id=recipient, kind=kind, message=message, dedupe_key=f"{key}:{recipient}",
                    due=due, subject_id=emp.id, evaluation_id=ev.id, link=link,
                )
            )

        if ev.state in CRITERIA_PHASE and ev.criteria_due_date:
            left = (ev.criteria_due_date - today).days
            if left < 0:
                for r in self._evaluator_recipients(ev, hr):
                    add(r, ReminderKind.CRITERIA_OVERDUE, f"criteria-overdue:{ev.id}:{today}",
                        f"Minął termin ustalenia kryteriów oceny: {who} ({ev.criteria_due_date:%d.%m.%Y}).",
                        ev.criteria_due_date)
                for r in hr:
                    add(r, ReminderKind.CRITERIA_OVERDUE, f"criteria-overdue-hr:{ev.id}",
                        f"Zaległe ustalenie kryteriów: {who} — termin minął {ev.criteria_due_date:%d.%m.%Y}.",
                        ev.criteria_due_date)
            elif (bucket := _bucket(left, self._cfg["criteria"]["before_days"])) is not None:
                for r in self._evaluator_recipients(ev, hr):
                    add(r, ReminderKind.CRITERIA_DUE, f"criteria-due:{ev.id}:{bucket}",
                        f"Za {_days(left)} mija termin rozmowy i ustalenia kryteriów: {who} "
                        f"({ev.criteria_due_date:%d.%m.%Y}).", ev.criteria_due_date)
        if ev.state == EvaluationState.CRITERIA_CONFIRMED:
            add(emp.id, ReminderKind.ACK_PENDING, f"criteria-ack:{ev.id}",
                "Potwierdź odbycie rozmowy i zapoznanie się z kryteriami oceny.", None)

        if ev.state in ASSESSMENT_PHASE and ev.due_date:
            left = (ev.due_date - today).days
            if left < 0:
                for r in self._evaluator_recipients(ev, hr):
                    add(r, ReminderKind.ASSESSMENT_OVERDUE, f"assessment-overdue:{ev.id}:{today}",
                        f"Minął termin sporządzenia oceny: {who} ({ev.due_date:%d.%m.%Y}).", ev.due_date)
                for r in hr:
                    add(r, ReminderKind.ASSESSMENT_OVERDUE, f"assessment-overdue-hr:{ev.id}",
                        f"Zaległa ocena okresowa: {who} — termin minął {ev.due_date:%d.%m.%Y}.", ev.due_date)
            elif (bucket := _bucket(left, self._cfg["assessment"]["before_days"])) is not None:
                for r in self._evaluator_recipients(ev, hr):
                    add(r, ReminderKind.ASSESSMENT_DUE, f"assessment-due:{ev.id}:{bucket}",
                        f"Za {_days(left)} termin sporządzenia oceny: {who} ({ev.due_date:%d.%m.%Y}). "
                        "Zaplanuj rozmowę oceniającą.", ev.due_date)

        if ev.state == EvaluationState.AWAITING_ACK:
            add(emp.id, ReminderKind.ACK_PENDING, f"assessment-ack:{ev.id}",
                "Twoja ocena okresowa jest gotowa — zapoznaj się z nią i potwierdź.", None)
        if ev.state == EvaluationState.ACKNOWLEDGED and ev.result and ev.result.acknowledged_on:
            deadline = objection_deadline(ev.result.acknowledged_on)
            add(emp.id, ReminderKind.OBJECTION_WINDOW, f"objection-window:{ev.id}",
                f"Od oceny przysługuje sprzeciw do {deadline.date:%d.%m.%Y} ({deadline.basis}).", deadline.date)
        return out

    def _promotion(self, emp: Employee, today: date, hr: list[str]) -> list[Reminder]:
        promo = obligatory_promotion(emp, self._c.evaluations.history(emp.id))
        if promo is None:
            return []
        left = (promo.deadline.date - today).days
        bucket = "overdue" if left < 0 else _bucket(left, self._cfg["promotion"]["before_days"]) or "info"
        message = (
            f"{emp.full_name}: obligatoryjne przyznanie {promo.next_grade}. stopnia służbowego "
            f"do {promo.deadline.date:%d.%m.%Y} ({promo.deadline.basis}) — dwie kolejne oceny "
            "na jednym z dwóch najwyższych poziomów."
        )
        return [
            Reminder(
                recipient_id=r, kind=ReminderKind.PROMOTION_DUE, message=message,
                dedupe_key=f"promotion:{emp.id}:{promo.evaluation_ids[1]}:{bucket}:{r}",
                due=promo.deadline.date, subject_id=emp.id, evaluation_id=promo.evaluation_ids[1],
                link="/core/kadry",
            )
            for r in hr
        ]
