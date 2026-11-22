"""Implementacje portów na bazie danych + import seedu."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.enums import EvaluationState, Level, Outcome, SheetType
from app.contracts.fakes import Seed
from app.contracts.models import (
    Absence,
    CriterionRef,
    Employee,
    EvaluationResult,
    EvaluationSummary,
    Office,
    OrgUnit,
    Position,
    Reminder,
)
from app.contracts.ports import CriteriaCatalog
from app.core.models import (
    AbsenceRow,
    EmployeeRow,
    EvaluationRow,
    EventRow,
    OfficeRow,
    OrgUnitRow,
    ReminderRow,
)
from app.core.rules.calendar_pl import add_months

CLOSED_STATES = (EvaluationState.FINAL.value, EvaluationState.CANCELLED.value)


# --- mapowanie wierszy na kontrakty ------------------------------------------------------


def employee_from_row(r: EmployeeRow) -> Employee:
    return Employee(
        id=r.id,
        first_name=r.first_name,
        last_name=r.last_name,
        email=r.email,
        position=Position(
            title=r.title,
            org_unit_id=r.org_unit_id,
            is_head_of_office=r.is_head_of_office,
            manages_people=r.manages_people,
        ),
        basis=r.basis,
        indefinite_since=r.indefinite_since,
        appointed_year=r.appointed_year,
        grade=r.grade,
        grade_granted_on=r.grade_granted_on,
        supervisor_id=r.supervisor_id,
        extra_roles=list(r.extra_roles or []),
        active=r.active,
    )


def result_from_row(r: EvaluationRow) -> EvaluationResult | None:
    if r.mean_numerator is None or r.assessed_on is None:
        return None
    return EvaluationResult(
        partial_points=dict((r.form or {}).get("partial_points", {})),
        mean_numerator=r.mean_numerator,
        mean_denominator=r.mean_denominator or 1,
        level=Level(r.level),
        outcome=Outcome(r.outcome),
        assessed_on=r.assessed_on,
        acknowledged_on=r.acknowledged_on,
        promotion_requested=r.promotion_requested,
    )


def criteria_for(sheet: SheetType, additional: Sequence[str], catalog: CriteriaCatalog) -> list[CriterionRef]:
    refs = [CriterionRef(code=c.code, name=c.name, mandatory=True) for c in catalog.mandatory_for(sheet)]
    refs += [CriterionRef(code=code, name=catalog.get(code).name, mandatory=False) for code in additional]
    return refs


def summary_from_row(r: EvaluationRow, catalog: CriteriaCatalog) -> EvaluationSummary:
    sheet = SheetType(r.sheet)
    return EvaluationSummary(
        id=r.id,
        employee_id=r.employee_id,
        evaluator_id=r.evaluator_id,
        sheet=sheet,
        state=EvaluationState(r.state),
        criteria=criteria_for(sheet, r.additional or [], catalog),
        criteria_set_on=r.criteria_set_on,
        period_from=r.period_from,
        due_date=r.due_date,
        criteria_due_date=r.criteria_due_date,
        after_negative=r.after_negative,
        result=result_from_row(r),
    )


# --- porty ---------------------------------------------------------------------------------


class DbEmployeeDirectory:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def office(self) -> Office:
        with self._sf() as s:
            r = s.get(OfficeRow, 1)
            return Office(name=r.name, city=r.city, objection_addressee_head=r.objection_addressee_head)

    def org_unit(self, unit_id: str) -> OrgUnit:
        with self._sf() as s:
            r = s.get(OrgUnitRow, unit_id)
            if r is None:
                raise KeyError(unit_id)
            return OrgUnit(id=r.id, name=r.name, parent_id=r.parent_id, city=r.city)

    def org_units(self) -> list[OrgUnit]:
        with self._sf() as s:
            rows = s.scalars(select(OrgUnitRow).order_by(OrgUnitRow.id)).all()
            return [OrgUnit(id=r.id, name=r.name, parent_id=r.parent_id, city=r.city) for r in rows]

    def get(self, employee_id: str) -> Employee:
        with self._sf() as s:
            r = s.get(EmployeeRow, employee_id)
            if r is None:
                raise KeyError(employee_id)
            return employee_from_row(r)

    def all(self) -> list[Employee]:
        with self._sf() as s:
            return [employee_from_row(r) for r in s.scalars(select(EmployeeRow).order_by(EmployeeRow.id))]

    def subordinates(self, evaluator_id: str) -> list[Employee]:
        with self._sf() as s:
            rows = s.scalars(
                select(EmployeeRow)
                .where(EmployeeRow.supervisor_id == evaluator_id, EmployeeRow.active.is_(True))
                .order_by(EmployeeRow.id)
            )
            return [employee_from_row(r) for r in rows]

    def absences(self, employee_id: str) -> list[Absence]:
        with self._sf() as s:
            rows = s.scalars(
                select(AbsenceRow).where(AbsenceRow.employee_id == employee_id).order_by(AbsenceRow.start)
            )
            return [Absence(employee_id=r.employee_id, start=r.start, end=r.end, justified=r.justified) for r in rows]


class DbEvaluationReader:
    def __init__(self, session_factory: sessionmaker, catalog: CriteriaCatalog) -> None:
        self._sf = session_factory
        self._catalog = catalog

    def get(self, evaluation_id: str) -> EvaluationSummary:
        with self._sf() as s:
            r = s.get(EvaluationRow, evaluation_id)
            if r is None:
                raise KeyError(evaluation_id)
            return summary_from_row(r, self._catalog)

    def current_for(self, employee_id: str) -> EvaluationSummary | None:
        with self._sf() as s:
            r = s.scalars(
                select(EvaluationRow)
                .where(EvaluationRow.employee_id == employee_id, EvaluationRow.state.not_in(CLOSED_STATES))
                .order_by(EvaluationRow.created_at.desc(), EvaluationRow.id.desc())
            ).first()
            return summary_from_row(r, self._catalog) if r else None

    def for_evaluator(self, evaluator_id: str) -> list[EvaluationSummary]:
        with self._sf() as s:
            rows = s.scalars(
                select(EvaluationRow)
                .where(EvaluationRow.evaluator_id == evaluator_id, EvaluationRow.state.not_in(CLOSED_STATES))
                .order_by(EvaluationRow.due_date)
            )
            return [summary_from_row(r, self._catalog) for r in rows]

    def history(self, employee_id: str) -> list[EvaluationSummary]:
        with self._sf() as s:
            rows = s.scalars(
                select(EvaluationRow)
                .where(EvaluationRow.employee_id == employee_id, EvaluationRow.state == EvaluationState.FINAL.value)
                .order_by(EvaluationRow.assessed_on)
            )
            return [summary_from_row(r, self._catalog) for r in rows]

    def open_all(self) -> list[EvaluationSummary]:
        with self._sf() as s:
            rows = s.scalars(
                select(EvaluationRow).where(EvaluationRow.state.not_in(CLOSED_STATES)).order_by(EvaluationRow.due_date)
            )
            return [summary_from_row(r, self._catalog) for r in rows]

    def all_rows_summary(self) -> list[EvaluationSummary]:
        with self._sf() as s:
            return [summary_from_row(r, self._catalog) for r in s.scalars(select(EvaluationRow))]


class DbReminderSink:
    def __init__(self, session_factory: sessionmaker, clock) -> None:
        self._sf = session_factory
        self._clock = clock

    def emit(self, reminders: Sequence[Reminder]) -> int:
        new = 0
        with self._sf() as s:
            existing = set(s.scalars(select(ReminderRow.dedupe_key)))
            for r in reminders:
                if r.dedupe_key in existing:
                    continue
                existing.add(r.dedupe_key)
                s.add(
                    ReminderRow(
                        dedupe_key=r.dedupe_key,
                        recipient_id=r.recipient_id,
                        kind=r.kind.value,
                        message=r.message,
                        due=r.due,
                        subject_id=r.subject_id,
                        evaluation_id=r.evaluation_id,
                        link=r.link,
                        channel=r.channel.value,
                        created_at=self._clock.now(),
                    )
                )
                new += 1
            s.commit()
        return new

    def inbox(self, recipient_id: str) -> list[Reminder]:
        with self._sf() as s:
            rows = s.scalars(
                select(ReminderRow)
                .where(ReminderRow.recipient_id == recipient_id, ReminderRow.read.is_(False))
                .order_by(ReminderRow.due.is_(None), ReminderRow.due, ReminderRow.id)
            )
            return [
                Reminder(
                    recipient_id=r.recipient_id,
                    kind=r.kind,
                    message=r.message,
                    dedupe_key=r.dedupe_key,
                    due=r.due,
                    subject_id=r.subject_id,
                    evaluation_id=r.evaluation_id,
                    link=r.link,
                    channel=r.channel,
                )
                for r in rows
            ]

    def mark_read(self, recipient_id: str, dedupe_key: str) -> None:
        with self._sf() as s:
            r = s.scalars(
                select(ReminderRow).where(ReminderRow.dedupe_key == dedupe_key, ReminderRow.recipient_id == recipient_id)
            ).first()
            if r:
                r.read = True
                s.commit()


def log_event(
    s: Session,
    *,
    at: datetime,
    action: str,
    actor_id: str | None,
    evaluation_id: str | None = None,
    employee_id: str | None = None,
    **details: object,
) -> None:
    s.add(
        EventRow(
            evaluation_id=evaluation_id,
            employee_id=employee_id,
            at=at,
            actor_id=actor_id,
            action=action,
            details={k: (v.isoformat() if isinstance(v, date) else v) for k, v in details.items()},
        )
    )


# --- import seedu -------------------------------------------------------------------------


def import_seed(session_factory: sessionmaker, seed: Seed) -> bool:
    """Wypełnia pustą bazę danymi z seed/office.yaml. Zwraca True, jeśli importował."""
    with session_factory() as s:
        if s.scalars(select(EmployeeRow.id)).first() is not None:
            return False
        office = seed.office
        s.add(OfficeRow(id=1, name=office.name, city=office.city, objection_addressee_head=office.objection_addressee_head))
        for u in seed.org_units:
            s.add(OrgUnitRow(id=u.id, name=u.name, parent_id=u.parent_id, city=u.city))
        for e in seed.employees:
            s.add(
                EmployeeRow(
                    id=e.id,
                    first_name=e.first_name,
                    last_name=e.last_name,
                    email=e.email,
                    title=e.position.title,
                    org_unit_id=e.position.org_unit_id,
                    is_head_of_office=e.position.is_head_of_office,
                    manages_people=e.position.manages_people,
                    basis=e.basis.value,
                    indefinite_since=e.indefinite_since,
                    appointed_year=e.appointed_year,
                    grade=e.grade,
                    grade_granted_on=e.grade_granted_on,
                    supervisor_id=e.supervisor_id,
                    extra_roles=[r.value for r in e.extra_roles],
                    active=e.active,
                )
            )
        for a in seed.absences:
            s.add(AbsenceRow(employee_id=a.employee_id, start=a.start, end=a.end, justified=a.justified))

        employees = {e.id: e for e in seed.employees}
        last_assessed: dict[str, date] = {}
        records = sorted(seed.evaluations, key=lambda r: (r["employee_id"], r.get("due_date") or date.max))
        for i, rec in enumerate(records):
            result = rec.get("result")
            emp = employees[rec["employee_id"]]
            prev = last_assessed.get(rec["employee_id"])
            if prev:
                cycle_start = prev
            elif emp.indefinite_since and rec.get("due_date") and add_months(emp.indefinite_since, 24) >= rec["due_date"]:
                cycle_start = emp.indefinite_since
            elif rec.get("due_date"):
                cycle_start = add_months(rec["due_date"], -24)  # przybliżenie dla historii sprzed systemu
            else:
                cycle_start = None
            form: dict = {}
            row = EvaluationRow(
                id=rec["id"],
                employee_id=rec["employee_id"],
                evaluator_id=rec.get("evaluator_id"),
                sheet=rec["sheet"],
                state=rec["state"],
                additional=list(rec.get("additional", [])),
                cycle_start=cycle_start,
                after_negative=bool(rec.get("after_negative", False)),
                criteria_due_date=rec.get("criteria_due_date"),
                criteria_set_on=rec.get("criteria_set_on"),
                period_from=rec.get("period_from"),
                due_date=rec.get("due_date"),
                created_at=datetime(2000, 1, 1, 0, 0, 0, i),  # kolejność importu
            )
            if rec.get("criteria_set_on"):
                confirmed = rec["criteria_set_on"].isoformat()
                form.update(part1_confirmed_by_evaluator_on=confirmed, part1_confirmed_by_employee_on=confirmed,
                            part1_place_evaluator=office.city, part1_place_employee=office.city)
            # arkusz z seedu (np. wersja robocza po rozmowie, uzasadnienie przeszłej oceny); daty jako ISO
            form.update({k: v.isoformat() if isinstance(v, date) else v for k, v in (rec.get("form") or {}).items()})
            if result:
                form["partial_points"] = dict(result["partial_points"])
                form["imported"] = True
                row.mean_numerator = result["mean_numerator"]
                row.mean_denominator = result["mean_denominator"]
                row.level = result["level"]
                row.outcome = result["outcome"]
                row.assessed_on = result["assessed_on"]
                row.acknowledged_on = result.get("acknowledged_on")
                row.promotion_requested = result.get("promotion_requested")
                row.period_to = result["assessed_on"]
                last_assessed[rec["employee_id"]] = result["assessed_on"]
            row.form = form
            s.add(row)
        s.commit()
    return True
