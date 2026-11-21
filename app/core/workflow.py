"""Maszyna stanów oceny okresowej (docs/ARCHITEKTURA.md § 3) z audytem każdej zmiany.

Każda akcja: sprawdza rolę i stan, zmienia wiersz, zapisuje zdarzenie w core_events,
ewentualnie wysyła powiadomienie. Błędy biznesowe → WorkflowError (komunikat dla użytkownika).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.enums import EvaluationState as S
from app.contracts.enums import Outcome, ReminderKind, Role, SheetType
from app.contracts.models import Reminder, UserContext
from app.core.forms import load_definition
from app.core.models import EmployeeRow, EvaluationRow, EventRow
from app.core.repo import employee_from_row, log_event, result_from_row
from app.core.rules import careers, deadlines
from app.core.rules.calendar_pl import add_months
from app.core.rules.scoring import score

if TYPE_CHECKING:
    from app.container import Container

EVALUATOR, EMPLOYEE = "EVALUATOR", "EMPLOYEE"
MAX_ADDITIONAL = 3


class WorkflowError(Exception):
    """Błąd biznesowy — komunikat pokazywany użytkownikowi."""


# --- pomocnicze ---------------------------------------------------------------------------


def actor_role(row: EvaluationRow, user: UserContext) -> str | None:
    """Rola użytkownika w danej ocenie. Gdy oceniający jest spoza urzędu (kierownik urzędu),
    jego czynności w systemie wprowadzają kadry."""
    if row.evaluator_id == user.employee_id:
        return EVALUATOR
    if row.employee_id == user.employee_id:
        return EMPLOYEE
    if row.evaluator_id is None and user.has(Role.KADRY):
        return EVALUATOR
    return None


def can_view(row: EvaluationRow, user: UserContext) -> bool:
    return actor_role(row, user) is not None or user.has(Role.KADRY) or user.has(Role.ADMIN)


@dataclass
class _Ctx:
    c: Container
    s: Session
    row: EvaluationRow
    user: UserContext
    today: date

    def log(self, action: str, **details: Any) -> None:
        log_event(self.s, at=self.c.clock.now(), action=action, actor_id=self.user.employee_id,
                  evaluation_id=self.row.id, employee_id=self.row.employee_id, **details)

    @property
    def form(self) -> dict:
        return dict(self.row.form or {})

    def set_form(self, **changes: Any) -> None:
        form = dict(self.row.form or {})
        form.update(changes)
        self.row.form = form  # nowy obiekt → SQLAlchemy zapisze zmianę JSON


def _open(c: Container, evaluation_id: str, user: UserContext, s: Session) -> _Ctx:
    row = s.get(EvaluationRow, evaluation_id)
    if row is None:
        raise WorkflowError("Nie ma takiej oceny.")
    return _Ctx(c=c, s=s, row=row, user=user, today=c.clock.today())


def _require(ctx: _Ctx, *, role: str, states: set[S]) -> None:
    if actor_role(ctx.row, ctx.user) != role:
        raise WorkflowError("Ta czynność należy do " + ("oceniającego." if role == EVALUATOR else "ocenianego."))
    if S(ctx.row.state) not in states:
        raise WorkflowError("Na tym etapie oceny ta czynność nie jest dostępna.")


def _employee(ctx: _Ctx):
    return employee_from_row(ctx.s.get(EmployeeRow, ctx.row.employee_id))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _notify(c: Container, reminders: list[Reminder]) -> None:
    if reminders:
        c.reminder_sink.emit(reminders)


# --- Część I: kryteria ------------------------------------------------------------------


def save_part1(c: Container, evaluation_id: str, user: UserContext, *, additional: list[str],
               due_date: date | None, place: str | None) -> None:
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EVALUATOR, states={S.CYCLE_OPEN})
        codes = [a for a in additional if a]
        if len(codes) > MAX_ADDITIONAL:
            raise WorkflowError("Można wybrać nie więcej niż 3 kryteria dodatkowe (§ 5 ust. 2).")
        if len(set(codes)) != len(codes):
            raise WorkflowError("Kryteria dodatkowe nie mogą się powtarzać.")
        allowed = {cdef.code for cdef in c.catalog.additional_for(SheetType(ctx.row.sheet))}
        if not set(codes) <= allowed:
            raise WorkflowError("Wybrano kryterium, które nie jest kryterium dodatkowym dla tego arkusza.")
        ctx.row.additional = codes
        if due_date:
            ctx.row.due_date = due_date
        ctx.set_form(part1_place_evaluator=place or ctx.form.get("part1_place_evaluator"))
        ctx.log("PART1_SAVED", additional=codes, due_date=due_date)
        s.commit()


def confirm_criteria(c: Container, evaluation_id: str, user: UserContext) -> None:
    """Oceniający potwierdza rozmowę (§ 5 ust. 1) i wpisuje kryteria oraz termin (§ 5 ust. 3)."""
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EVALUATOR, states={S.CYCLE_OPEN})
        if not ctx.row.due_date:
            raise WorkflowError("Uzupełnij termin sporządzenia oceny.")
        ctx.set_form(part1_confirmed_by_evaluator_on=_iso(ctx.today),
                     part1_place_evaluator=ctx.form.get("part1_place_evaluator") or _default_place(c))
        ctx.row.state = S.CRITERIA_CONFIRMED.value
        ctx.log("CRITERIA_CONFIRMED")
        s.commit()


def acknowledge_criteria(c: Container, evaluation_id: str, user: UserContext, *, place: str | None) -> None:
    """Oceniany potwierdza rozmowę i zapoznanie z kryteriami i terminem (§ 6 ust. 2)."""
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EMPLOYEE, states={S.CRITERIA_CONFIRMED})
        ctx.set_form(part1_confirmed_by_employee_on=_iso(ctx.today), part1_place_employee=place or _default_place(c))
        ctx.row.criteria_set_on = ctx.today
        ctx.row.period_from = ctx.today  # „Data od” = data zapoznania ocenianego z kryteriami
        ctx.row.state = S.OBSERVATION.value
        ctx.log("CRITERIA_ACKNOWLEDGED")
        s.commit()


# --- Część II: rozmowa i ocena ----------------------------------------------------------


def record_interview(c: Container, evaluation_id: str, user: UserContext, *, interview_date: date) -> None:
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EVALUATOR, states={S.OBSERVATION, S.INTERVIEW_HELD})
        if interview_date > ctx.today:
            raise WorkflowError("Data rozmowy oceniającej nie może być z przyszłości.")
        if ctx.row.period_from and interview_date < ctx.row.period_from:
            raise WorkflowError("Rozmowa oceniająca nie może się odbyć przed początkiem okresu oceny.")
        ctx.set_form(interview_date=_iso(interview_date))
        if not ctx.row.period_to:
            # „do” = data sporządzenia (dziś) albo termin oceny, gdy wypełniana po jego upływie
            ctx.row.period_to = min(ctx.today, ctx.row.due_date) if ctx.row.due_date else ctx.today
        if S(ctx.row.state) == S.OBSERVATION:
            ctx.row.state = S.INTERVIEW_HELD.value
            _prefill_previous(ctx)
            if ctx.row.sheet == SheetType.A.value and not ctx.form.get("objection_addressee"):
                ctx.set_form(objection_addressee=c.employees.office().objection_addressee_head)
        ctx.log("INTERVIEW_RECORDED", interview_date=interview_date)
        s.commit()


def _prefill_previous(ctx: _Ctx) -> None:
    """Dane poprzedniej oceny urzędnika — automatycznie z historii (schemat pól arkusza)."""
    emp = _employee(ctx)
    if not emp.is_urzednik or ctx.form.get("previous"):
        return
    prev = ctx.s.scalars(
        select(EvaluationRow)
        .where(EvaluationRow.employee_id == ctx.row.employee_id, EvaluationRow.state == S.FINAL.value,
               EvaluationRow.id != ctx.row.id)
        .order_by(EvaluationRow.assessed_on.desc())
    ).first()
    if prev and prev.assessed_on:
        ctx.set_form(previous={"outcome": prev.outcome, "level": prev.level,
                               "assessed_on": prev.assessed_on.isoformat(), "from_history": True})


def save_assessment(c: Container, evaluation_id: str, user: UserContext, data: dict[str, Any]) -> None:
    """Zapis roboczy Części II (i III). Nie zmienia stanu."""
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EVALUATOR, states={S.INTERVIEW_HELD})
        codes = {cr.code for cr in _criteria(ctx)}
        points = {k: int(v) for k, v in data.get("partial_points", {}).items() if k in codes and v not in ("", None)}
        bad = [v for v in points.values() if v not in (1, 3, 5, 7, 9)]
        if bad:
            raise WorkflowError("Ocena cząstkowa musi wynosić 1, 3, 5, 7 albo 9 punktów.")
        changes: dict[str, Any] = {"partial_points": points}
        for key in ("justification", "iprz", "promotion_choice", "objection_addressee", "part2_place_evaluator"):
            if key in data:
                changes[key] = (data[key] or "").strip() or None
        if "previous" in data and not (ctx.form.get("previous") or {}).get("from_history"):
            changes["previous"] = data["previous"]
        if "part3" in data:
            changes["part3"] = data["part3"]
        if data.get("period_from"):
            ctx.row.period_from = data["period_from"]
        if data.get("period_to"):
            ctx.row.period_to = data["period_to"]
        ctx.set_form(**changes)
        ctx.log("ASSESSMENT_SAVED")
        s.commit()


def _criteria(ctx: _Ctx):
    from app.core.repo import criteria_for

    return criteria_for(SheetType(ctx.row.sheet), ctx.row.additional or [], ctx.c.catalog)


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


def validate_for_submit(c: Container, row: EvaluationRow, employee) -> list[ValidationIssue]:
    """Blokady zatwierdzenia oceny — schemat pól arkusza + § 11 rozporządzenia."""
    from app.core.repo import criteria_for

    form = row.form or {}
    issues: list[ValidationIssue] = []
    criteria = criteria_for(SheetType(row.sheet), row.additional or [], c.catalog)
    points = form.get("partial_points", {})
    missing = [cr.name for cr in criteria if cr.code not in points]
    if missing:
        issues.append(ValidationIssue("partial_points", "Brak ocen cząstkowych: " + ", ".join(missing) + "."))
        return issues
    result = score([points[cr.code] for cr in criteria])
    if not form.get("interview_date"):
        issues.append(ValidationIssue("interview_date", "Wpisz datę rozmowy oceniającej (§ 10)."))
    if not (form.get("iprz") or "").strip():
        issues.append(ValidationIssue("iprz", "Wnioski dotyczące indywidualnego programu rozwoju zawodowego są obowiązkowe (art. 81 ust. 5)."))
    if result.outcome == Outcome.NEGATYWNA and not (form.get("justification") or "").strip():
        issues.append(ValidationIssue("justification", "Przy ocenie negatywnej uzasadnienie jest obowiązkowe (§ 11 ust. 3)."))
    choice = form.get("promotion_choice")
    if employee.is_urzednik:
        if result.outcome == Outcome.NEGATYWNA and choice == "TAK":
            issues.append(ValidationIssue("promotion_choice", "Wniosek o kolejny stopień wymaga oceny pozytywnej (art. 89 ust. 1)."))
        if result.outcome == Outcome.POZYTYWNA and choice not in ("TAK", "NIE"):
            issues.append(ValidationIssue("promotion_choice", "Wskaż, czy dołączasz wniosek o przyznanie kolejnego stopnia służbowego."))
        if choice == "TAK":
            p3 = form.get("part3") or {}
            grade = int(p3.get("grade") or employee.grade or 0)
            if grade >= careers.MAX_GRADE:
                issues.append(ValidationIssue("part3", "Ocenianemu nie można przyznać kolejnego stopnia służbowego. Oceniany posiada już najwyższy możliwy stopień służbowy."))
            if not (p3.get("motivation") or "").strip():
                issues.append(ValidationIssue("part3", "Uzupełnij umotywowanie wniosku o przyznanie kolejnego stopnia (część III)."))
    if row.sheet == SheetType.A.value and not (form.get("objection_addressee") or "").strip():
        issues.append(ValidationIssue("objection_addressee", "Wskaż, do kogo przysługuje sprzeciw (arkusz A)."))
    return issues


def submit_assessment(c: Container, evaluation_id: str, user: UserContext) -> None:
    """Sporządzenie oceny na piśmie (§ 11) i przekazanie ocenianemu do zapoznania (§ 12)."""
    from app.core.repo import criteria_for

    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EVALUATOR, states={S.INTERVIEW_HELD})
        emp = _employee(ctx)
        issues = validate_for_submit(c, ctx.row, emp)
        if issues:
            raise WorkflowError(" ".join(i.message for i in issues))
        criteria = criteria_for(SheetType(ctx.row.sheet), ctx.row.additional or [], c.catalog)
        points = ctx.form["partial_points"]
        result = score([points[cr.code] for cr in criteria])
        ctx.row.mean_numerator = result.mean.numerator
        ctx.row.mean_denominator = result.mean.denominator
        ctx.row.level = result.level.value
        ctx.row.outcome = result.outcome.value
        ctx.row.assessed_on = ctx.today
        ctx.row.period_to = ctx.row.period_to or ctx.today
        ctx.row.promotion_requested = (ctx.form.get("promotion_choice") == "TAK") if emp.is_urzednik else None
        if not emp.is_urzednik:
            ctx.set_form(promotion_choice="NIE_DOTYCZY")
        elif result.outcome == Outcome.NEGATYWNA:
            ctx.set_form(promotion_choice="NIE")
        ctx.set_form(part2_signed_by_evaluator_on=_iso(ctx.today),
                     part2_place_evaluator=ctx.form.get("part2_place_evaluator") or _default_place(c))
        ctx.row.state = S.AWAITING_ACK.value
        ctx.log("ASSESSMENT_SUBMITTED", level=result.level.value, outcome=result.outcome.value,
                mean=f"{result.mean.numerator}/{result.mean.denominator}")
        s.commit()


def acknowledge_assessment(c: Container, evaluation_id: str, user: UserContext, *, place: str | None) -> None:
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EMPLOYEE, states={S.AWAITING_ACK})
        ctx.row.acknowledged_on = ctx.today
        ctx.set_form(part2_signed_by_employee_on=_iso(ctx.today), part2_place_employee=place or _default_place(c))
        ctx.row.state = S.ACKNOWLEDGED.value
        ctx.log("ASSESSMENT_ACKNOWLEDGED")
        s.commit()


def deem_acknowledged(c: Container, evaluation_id: str, user: UserContext, *, note: str) -> None:
    """Fikcja zapoznania: informacja o ocenie dotarła, ale oceniany nie mógł/nie chciał potwierdzić."""
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        if not (actor_role(ctx.row, user) == EVALUATOR or user.has(Role.KADRY)):
            raise WorkflowError("Fikcję zapoznania stwierdza oceniający albo kadry.")
        if S(ctx.row.state) != S.AWAITING_ACK:
            raise WorkflowError("Fikcję zapoznania można stwierdzić tylko dla oceny czekającej na zapoznanie.")
        if not note.strip():
            raise WorkflowError("Opisz, jak doręczono informację o ocenie.")
        ctx.row.acknowledged_on = ctx.today
        ctx.row.ack_deemed = True
        ctx.set_form(ack_deemed_note=note.strip())
        ctx.row.state = S.ACKNOWLEDGED.value
        ctx.log("ACK_DEEMED", note=note.strip())
        s.commit()


# --- sprzeciw (art. 83) -------------------------------------------------------------------


def file_objection(c: Container, evaluation_id: str, user: UserContext, *, text: str) -> None:
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EMPLOYEE, states={S.ACKNOWLEDGED})
        deadline = deadlines.objection_deadline(ctx.row.acknowledged_on)
        if ctx.today > deadline.date:
            raise WorkflowError(f"Termin na sprzeciw minął {deadline.date:%d.%m.%Y} ({deadline.basis}).")
        review = deadlines.objection_review_deadline(ctx.today)
        ctx.set_form(objection={"filed_on": _iso(ctx.today), "text": text.strip(), "review_by": _iso(review.date)})
        ctx.row.state = S.OBJECTION.value
        ctx.log("OBJECTION_FILED")
        s.commit()
    hr = [e.id for e in c.employees.all() if Role.KADRY in e.extra_roles]
    _notify(c, [
        Reminder(recipient_id=r, kind=ReminderKind.OBJECTION_WINDOW,
                 message=f"Wniesiono sprzeciw od oceny — rozpatrzenie do {review.date:%d.%m.%Y} ({review.basis}).",
                 dedupe_key=f"objection-filed:{evaluation_id}:{r}", due=review.date,
                 evaluation_id=evaluation_id, link=f"/core/oceny/{evaluation_id}")
        for r in hr
    ])


def resolve_objection(c: Container, evaluation_id: str, user: UserContext, *, decision: str, note: str) -> str:
    """REJECT → ocena ostateczna; AMEND → oceniający zmienia ocenę; REDO → ocena sporządzana
    po raz drugi (anulowanie i powrót do etapu rozmowy oceniającej). Zwraca id oceny do dalszej pracy."""
    if not (user.has(Role.KADRY) or user.has(Role.ZARZADZAJACY)):
        raise WorkflowError("Sprzeciw rozpatruje dyrektor generalny urzędu (w systemie: kadry lub kierownictwo).")
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        if S(ctx.row.state) != S.OBJECTION:
            raise WorkflowError("Ta ocena nie ma wniesionego sprzeciwu.")
        objection = dict(ctx.form.get("objection") or {})
        objection.update(decision=decision, decided_on=_iso(ctx.today), note=note.strip())
        ctx.set_form(objection=objection)
        target = ctx.row.id
        if decision == "REJECT":
            ctx.row.state = S.FINAL.value
            _open_next_cycle(ctx)
        elif decision == "AMEND":
            ctx.row.state = S.INTERVIEW_HELD.value
            _clear_result(ctx.row)
        elif decision == "REDO":
            ctx.row.state = S.CANCELLED.value
            copy = EvaluationRow(
                id=_new_id(ctx.s, ctx.row.employee_id, ctx.today, suffix="P"),
                employee_id=ctx.row.employee_id, evaluator_id=ctx.row.evaluator_id, sheet=ctx.row.sheet,
                state=S.OBSERVATION.value, additional=list(ctx.row.additional or []),
                cycle_start=ctx.row.cycle_start, after_negative=ctx.row.after_negative,
                criteria_due_date=ctx.row.criteria_due_date, criteria_set_on=ctx.row.criteria_set_on,
                period_from=ctx.row.period_from, due_date=ctx.row.due_date, due_basis=ctx.row.due_basis,
                form={k: v for k, v in ctx.form.items() if k.startswith("part1_")} | {"redo_of": ctx.row.id},
                created_at=c.clock.now(),
            )
            ctx.s.add(copy)
            target = copy.id
        else:
            raise WorkflowError("Nieznana decyzja.")
        ctx.log("OBJECTION_RESOLVED", decision=decision, note=note.strip(), continued_as=target)
        s.commit()
        return target


def _clear_result(row: EvaluationRow) -> None:
    row.mean_numerator = row.mean_denominator = None
    row.level = row.outcome = None
    row.assessed_on = row.acknowledged_on = None
    row.ack_deemed = False


# --- domknięcie cyklu i nowy cykl ------------------------------------------------------------


def tick_all(c: Container, today: date) -> list[str]:
    """ACKNOWLEDGED + minął termin na sprzeciw → FINAL i otwarcie kolejnego cyklu."""
    finalized: list[str] = []
    with c.session_factory() as s:
        rows = s.scalars(select(EvaluationRow).where(EvaluationRow.state == S.ACKNOWLEDGED.value)).all()
        for row in rows:
            if row.acknowledged_on and today > deadlines.objection_deadline(row.acknowledged_on).date:
                ctx = _Ctx(c=c, s=s, row=row, user=UserContext(employee_id="SYSTEM", roles=frozenset()), today=today)
                row.state = S.FINAL.value
                ctx.log("FINALIZED", reason="upłynął termin na sprzeciw")
                _open_next_cycle(ctx)
                finalized.append(row.id)
        s.commit()
    return finalized


def _new_id(s: Session, employee_id: str, day: date, suffix: str = "") -> str:
    base = f"EV-{employee_id}-{day:%Y%m%d}{suffix}"
    candidate, n = base, 1
    while s.get(EvaluationRow, candidate) is not None:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _open_next_cycle(ctx: _Ctx) -> None:
    row = ctx.row
    emp_row = ctx.s.get(EmployeeRow, row.employee_id)
    emp = employee_from_row(emp_row)
    if not (emp.active and emp.subject_to_evaluation) or row.assessed_on is None:
        return
    negative = row.outcome == Outcome.NEGATYWNA.value
    absences = ctx.c.employees.absences(emp.id)
    due = deadlines.assessment_due(row.assessed_on, absences,
                                   negative_acknowledged_on=row.acknowledged_on if negative else None)
    crit = deadlines.criteria_due(row.assessed_on, after_negative=negative)
    new = EvaluationRow(
        id=_new_id(ctx.s, emp.id, row.assessed_on, suffix="N"),
        employee_id=emp.id, evaluator_id=emp.supervisor_id, sheet=careers.sheet_for(emp.position).value,
        state=S.CYCLE_OPEN.value, additional=[], cycle_start=row.assessed_on, after_negative=negative,
        criteria_due_date=crit.date, due_date=due.date, due_basis=due.basis, form={}, created_at=ctx.c.clock.now(),
    )
    ctx.s.add(new)
    log_event(ctx.s, at=ctx.c.clock.now(), action="CYCLE_OPENED", actor_id=None, evaluation_id=new.id,
              employee_id=emp.id, due_date=due.date, criteria_due_date=crit.date, basis=due.basis)


def open_first_cycle(c: Container, employee_id: str, user: UserContext) -> str:
    """Zatrudnienie na czas nieokreślony / mianowanie → pierwszy cykl (kadry)."""
    if not user.has(Role.KADRY):
        raise WorkflowError("Pierwszy cykl oceny otwierają kadry.")
    with c.session_factory() as s:
        emp = employee_from_row(s.get(EmployeeRow, employee_id))
        if not emp.subject_to_evaluation or not emp.indefinite_since:
            raise WorkflowError("Ocenie okresowej podlegają urzędnicy i pracownicy zatrudnieni na czas nieokreślony.")
        open_rows = s.scalars(select(EvaluationRow).where(
            EvaluationRow.employee_id == employee_id,
            EvaluationRow.state.not_in([S.FINAL.value, S.CANCELLED.value]))).first()
        if open_rows:
            raise WorkflowError("Ta osoba ma już trwający cykl oceny.")
        due = deadlines.assessment_due(emp.indefinite_since, c.employees.absences(emp.id))
        crit = deadlines.criteria_due(emp.indefinite_since)
        row = EvaluationRow(
            id=_new_id(s, emp.id, emp.indefinite_since, suffix="N"), employee_id=emp.id,
            evaluator_id=emp.supervisor_id, sheet=careers.sheet_for(emp.position).value,
            state=S.CYCLE_OPEN.value, additional=[], cycle_start=emp.indefinite_since,
            criteria_due_date=crit.date, due_date=due.date, due_basis=due.basis, form={}, created_at=c.clock.now(),
        )
        s.add(row)
        log_event(s, at=c.clock.now(), action="CYCLE_OPENED", actor_id=user.employee_id, evaluation_id=row.id,
                  employee_id=emp.id, due_date=due.date, basis=due.basis)
        s.commit()
        return row.id


# --- zmiany terminu ----------------------------------------------------------------------------


def change_due_date(c: Container, evaluation_id: str, user: UserContext, *, new_date: date, reason: str) -> None:
    """Art. 81 ust. 8 + § 8: zmiana terminu przez oceniającego, z zawiadomieniem ocenianego."""
    if reason not in deadlines.DUE_DATE_CHANGE_REASONS:
        raise WorkflowError("Wybierz podstawę zmiany terminu.")
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        _require(ctx, role=EVALUATOR, states={S.CRITERIA_CONFIRMED, S.OBSERVATION, S.INTERVIEW_HELD})
        start = ctx.row.cycle_start or ctx.row.period_from or ctx.today
        allowed, basis = deadlines.can_change_due_date(start, ctx.today)
        if not allowed:
            raise WorkflowError(f"Zmiana terminu niedopuszczalna — {basis}.")
        if new_date < ctx.today:
            raise WorkflowError("Nowy termin nie może być z przeszłości.")
        old = ctx.row.due_date
        ctx.row.due_date = new_date
        ctx.row.due_basis = deadlines.DUE_DATE_CHANGE_REASONS[reason]
        changes = list(ctx.form.get("due_date_changes", [])) + [
            {"on": _iso(ctx.today), "from": _iso(old), "to": _iso(new_date), "reason": reason}
        ]
        ctx.set_form(due_date_changes=changes)
        ctx.log("DUE_DATE_CHANGED", old=old, new=new_date, reason=reason)
        s.commit()
        employee_id = ctx.row.employee_id
    _notify(c, [Reminder(
        recipient_id=employee_id, kind=ReminderKind.DUE_DATE_CHANGED,
        message=f"Zmieniono termin sporządzenia Twojej oceny na {new_date:%d.%m.%Y} — "
                f"{deadlines.DUE_DATE_CHANGE_REASONS[reason]} (§ 8 rozporządzenia).",
        dedupe_key=f"due-changed:{evaluation_id}:{new_date}:{employee_id}", due=new_date,
        subject_id=employee_id, evaluation_id=evaluation_id, link=f"/core/oceny/{evaluation_id}",
    )])


def add_absence(c: Container, employee_id: str, user: UserContext, *, start: date, end: date) -> date | None:
    """Kadry wprowadzają nieobecność. Jeśli łącznie przekracza miesiąc — przeliczenie terminu
    (art. 81 ust. 7) i powiadomienie. Zwraca nowy termin albo None."""
    from app.core.models import AbsenceRow

    if not user.has(Role.KADRY):
        raise WorkflowError("Nieobecności wprowadzają kadry.")
    if end < start:
        raise WorkflowError("Koniec nieobecności nie może być przed jej początkiem.")
    with c.session_factory() as s:
        s.add(AbsenceRow(employee_id=employee_id, start=start, end=end, justified=True))
        log_event(s, at=c.clock.now(), action="ABSENCE_ADDED", actor_id=user.employee_id,
                  employee_id=employee_id, start=start, end=end)
        s.commit()
    return recompute_due_date(c, employee_id, actor_id=user.employee_id)


def recompute_due_date(c: Container, employee_id: str, *, actor_id: str | None) -> date | None:
    with c.session_factory() as s:
        row = s.scalars(select(EvaluationRow).where(
            EvaluationRow.employee_id == employee_id,
            EvaluationRow.state.in_([S.CYCLE_OPEN.value, S.CRITERIA_CONFIRMED.value, S.OBSERVATION.value]))).first()
        if row is None or row.after_negative or row.cycle_start is None:
            return None
        due = deadlines.assessment_due(row.cycle_start, c.employees.absences(employee_id))
        if due.date == row.due_date or not due.extensions:
            return None
        old, row.due_date, row.due_basis = row.due_date, due.date, due.basis
        log_event(s, at=c.clock.now(), action="DUE_DATE_EXTENDED", actor_id=actor_id, evaluation_id=row.id,
                  employee_id=employee_id, old=old, new=due.date, basis=due.basis, explanation=due.explanation)
        s.commit()
        evaluation_id, evaluator_id = row.id, row.evaluator_id
    message = f"Termin oceny przedłużony do {due.date:%d.%m.%Y}: {due.explanation} ({due.basis})."
    _notify(c, [
        Reminder(recipient_id=r, kind=ReminderKind.DUE_DATE_CHANGED, message=message,
                 dedupe_key=f"due-extended:{evaluation_id}:{due.date}:{r}", due=due.date, subject_id=employee_id,
                 evaluation_id=evaluation_id, link=f"/core/oceny/{evaluation_id}")
        for r in filter(None, [employee_id, evaluator_id])
    ])
    return due.date


# --- korekta administratora ------------------------------------------------------------------

ADMIN_FIELDS = {"due_date", "criteria_due_date", "period_from", "period_to", "criteria_set_on"}


def admin_correct(c: Container, evaluation_id: str, user: UserContext, *, field: str, value: date, reason: str) -> None:
    if not user.has(Role.ADMIN):
        raise WorkflowError("Korekta błędów jest dostępna tylko dla administratora.")
    if field not in ADMIN_FIELDS:
        raise WorkflowError("To pole nie podlega korekcie w tym trybie.")
    if not reason.strip():
        raise WorkflowError("Podaj powód korekty.")
    with c.session_factory() as s:
        ctx = _open(c, evaluation_id, user, s)
        old = getattr(ctx.row, field)
        setattr(ctx.row, field, value)
        ctx.log("ADMIN_CORRECTION", field=field, old=old, new=value, reason=reason.strip())
        s.commit()


# --- odczyt dla UI -----------------------------------------------------------------------------


def events_for(c: Container, evaluation_id: str) -> list[EventRow]:
    with c.session_factory() as s:
        return list(s.scalars(select(EventRow).where(EventRow.evaluation_id == evaluation_id).order_by(EventRow.at)))


def _default_place(c: Container) -> str | None:
    return c.employees.office().city


def mean_fraction(row: EvaluationRow) -> Fraction | None:
    r = result_from_row(row)
    return r.mean if r else None


def first_assessment(row: EvaluationRow, s: Session) -> bool:
    return s.scalars(select(EvaluationRow.id).where(
        EvaluationRow.employee_id == row.employee_id, EvaluationRow.state == S.FINAL.value)).first() is None


def six_months_since(d: date) -> date:
    return add_months(d, 6)


FORM = load_definition()
