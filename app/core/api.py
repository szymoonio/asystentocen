"""Router modułu CORE (agent A): pulpit, oceny (formularz A/B/C krok po kroku), wydruk, kadry."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.contracts.enums import DraftField, EvaluationState, Level, Role, SheetType
from app.core import guide, scheduler, workflow
from app.core.guide import stats_view  # noqa: F401  (używane w testach)
from app.core.models import EmployeeRow, EvaluationRow
from app.core.repo import criteria_for, employee_from_row, result_from_row, summary_from_row
from app.core.rules import careers, deadlines
from app.core.rules.scoring import format_mean, score
from app.core.workflow import EMPLOYEE, EVALUATOR, FORM, WorkflowError, actor_role, can_view
from app.deps import get_container, get_current_user
from app.templating import render

router = APIRouter()

STATE_LABELS = {
    EvaluationState.CYCLE_OPEN: "Ustalenie kryteriów",
    EvaluationState.CRITERIA_CONFIRMED: "Kryteria do potwierdzenia przez ocenianego",
    EvaluationState.OBSERVATION: "Okres oceny",
    EvaluationState.INTERVIEW_HELD: "Sporządzanie oceny",
    EvaluationState.AWAITING_ACK: "Do zapoznania przez ocenianego",
    EvaluationState.ACKNOWLEDGED: "Termin na sprzeciw",
    EvaluationState.OBJECTION: "Sprzeciw w rozpatrzeniu",
    EvaluationState.FINAL: "Ocena ostateczna",
    EvaluationState.CANCELLED: "Anulowana",
}
STEPS = [
    (EvaluationState.CYCLE_OPEN, "Kryteria"),
    (EvaluationState.CRITERIA_CONFIRMED, "Potwierdzenie kryteriów"),
    (EvaluationState.OBSERVATION, "Okres oceny"),
    (EvaluationState.INTERVIEW_HELD, "Rozmowa i ocena"),
    (EvaluationState.AWAITING_ACK, "Zapoznanie"),
    (EvaluationState.ACKNOWLEDGED, "Sprzeciw (7 dni)"),
    (EvaluationState.FINAL, "Ostateczna"),
]
EVENT_LABELS = {
    "PART1_SAVED": "zapisano część I",
    "CRITERIA_CONFIRMED": "oceniający potwierdził rozmowę i kryteria",
    "CRITERIA_ACKNOWLEDGED": "oceniany zapoznał się z kryteriami i terminem",
    "INTERVIEW_RECORDED": "odnotowano rozmowę oceniającą",
    "ASSESSMENT_SAVED": "zapisano wersję roboczą oceny",
    "ASSESSMENT_SUBMITTED": "ocena sporządzona i przekazana do zapoznania",
    "ASSESSMENT_ACKNOWLEDGED": "oceniany zapoznał się z oceną",
    "ACK_DEEMED": "stwierdzono fikcję zapoznania",
    "OBJECTION_FILED": "wniesiono sprzeciw",
    "OBJECTION_RESOLVED": "rozstrzygnięto sprzeciw",
    "FINALIZED": "ocena ostateczna",
    "CYCLE_OPENED": "otwarto cykl oceny",
    "DUE_DATE_CHANGED": "zmieniono termin oceny",
    "DUE_DATE_EXTENDED": "przedłużono termin (nieobecność)",
    "ADMIN_CORRECTION": "korekta administratora",
}
POINT_LABELS = {
    1: "znacznie poniżej oczekiwań", 3: "poniżej oczekiwań", 5: "na poziomie oczekiwań",
    7: "powyżej oczekiwań", 9: "znacznie powyżej oczekiwań",
}  # fmt: skip


def _ctx_common() -> dict[str, Any]:
    return {"STATE_LABELS": STATE_LABELS, "POINT_LABELS": POINT_LABELS, "EVENT_LABELS": EVENT_LABELS,
            "format_mean": format_mean, "pl_iso": pl_iso}


def pl_iso(value: str | None) -> str:
    """'2026-11-21' → '21.11.2026' (daty w polu JSON formularza są w ISO)."""
    return f"{value[8:10]}.{value[5:7]}.{value[0:4]}" if value else "—"


def _back(url: str, msg: str | None = None, *, error: bool = False) -> RedirectResponse:
    if msg:
        url += ("&" if "?" in url else "?") + ("error=" if error else "ok=") + quote(msg)
    return RedirectResponse(url, status_code=303)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def urgency(due: date | None, today: date) -> str:
    if not due:
        return ""
    left = (due - today).days
    return "danger" if left < 0 else "warn" if left <= 30 else ""


# --- pulpit ----------------------------------------------------------------------------------


@router.get("/")
def pulpit(request: Request):
    c = get_container(request)
    user = get_current_user(request)
    scheduler.run_if_needed(c)
    today = c.clock.today()
    evaluations = guide.todo_evaluations(c, user, today)
    notes = guide.todo_notes(c, user, today) if user.has(Role.OCENIAJACY) else []
    shown = {t.url.split("#")[0].split("/przygotowanie")[0] for t in evaluations}
    inbox = [r for r in c.reminder_sink.inbox(user.employee_id) if (r.link or "").split("#")[0] not in shown]
    own = c.evaluations.current_for(user.employee_id)
    return render(
        request, "core/pulpit.html", title="Pulpit", todo=evaluations[:3], todo_more=max(0, len(evaluations) - 3),
        notes_todo=notes[:3], note_people=notes, inbox=inbox, own=own, **_ctx_common(),
    )


@router.post("/scheduler/run")
def scheduler_run(request: Request):
    c = get_container(request)
    report = scheduler.run(c)
    total = sum(report.emitted.values())
    return _back("/core/", f"Przypomnienia uruchomione: {total} nowych, domknięte oceny: {len(report.finalized)}.")


@router.post("/przypomnienia/przeczytane")
async def reminder_read(request: Request):
    c = get_container(request)
    user = get_current_user(request)
    form = await request.form()
    if hasattr(c.reminder_sink, "mark_read"):
        c.reminder_sink.mark_read(user.employee_id, str(form.get("key", "")))
    return _back("/core/")


# --- lista ocen ------------------------------------------------------------------------------


@router.get("/oceny")
def oceny(request: Request):
    c = get_container(request)
    user = get_current_user(request)
    today = c.clock.today()
    as_evaluator = [
        (c.employees.get(ev.employee_id), ev, urgency(ev.due_date, today))
        for ev in c.evaluations.for_evaluator(user.employee_id)
    ]
    own = c.evaluations.current_for(user.employee_id)
    history = list(reversed(c.evaluations.history(user.employee_id)))
    return render(
        request, "core/oceny.html", title="Oceny okresowe", as_evaluator=as_evaluator, own=own, history=history,
        **_ctx_common(),
    )


# --- szczegóły oceny ---------------------------------------------------------------------------


def _load(request: Request, evaluation_id: str):
    c = get_container(request)
    user = get_current_user(request)
    with c.session_factory() as s:
        row = s.get(EvaluationRow, evaluation_id)
        if row is None:
            raise HTTPException(404, "Nie ma takiej oceny")
        if not can_view(row, user):
            raise HTTPException(403, "Brak dostępu do tej oceny")
        s.expunge(row)
        return c, user, row


def _observations(c, row: EvaluationRow, summary) -> dict[str, Any]:
    """Panel „Twoje obserwacje” (docs/ARCHITEKTURA.md § 5.2) — tylko do wglądu."""
    if not row.evaluator_id:
        return {"stats": {}, "views": {}, "warnings": {}, "url": None}
    stats = {s.criterion_code: s for s in c.notes.stats_for(row.evaluator_id, row.employee_id, row.id)}
    views = {code: v for code, st in stats.items() if (v := stats_view(st))}
    points = (row.form or {}).get("partial_points", {})
    warnings = {}
    for code, st in stats.items():
        if code in points and st.n_ratings >= 3 and st.median is not None and abs(points[code] - st.median) >= 4:
            direction = "wyżej" if st.median > points[code] else "niżej"
            warnings[code] = f"Twoje notatki wskazują {direction} (mediana {st.median:g}). Jeśli ocena jest świadoma, warto to uzasadnić."
    return {"stats": stats, "views": views, "warnings": warnings, "url": c.notes.teczka_url(row.employee_id)}


@router.get("/oceny/{evaluation_id}")
def ocena(evaluation_id: str, request: Request):
    c, user, row = _load(request, evaluation_id)
    today = c.clock.today()
    summary = summary_from_row(row, c.catalog)
    employee = c.employees.get(row.employee_id)
    evaluator = c.employees.get(row.evaluator_id) if row.evaluator_id else None
    role = actor_role(row, user)
    state = EvaluationState(row.state)
    sheet = SheetType(row.sheet)
    form = row.form or {}
    criteria = criteria_for(sheet, row.additional or [], c.catalog)

    points = form.get("partial_points", {})
    live = None
    if criteria and all(cr.code in points for cr in criteria):
        live = score([points[cr.code] for cr in criteria])
    result = result_from_row(row)
    issues = workflow.validate_for_submit(c, row, employee) if state == EvaluationState.INTERVIEW_HELD else []

    drafts = {}
    if role == EVALUATOR and state == EvaluationState.INTERVIEW_HELD and c.drafts.available():
        drafts = {f.value: c.drafts.drafts(row.id, f) for f in DraftField}

    with c.session_factory() as s:
        first = workflow.first_assessment(row, s)
    start = row.cycle_start or row.period_from or today
    can_change, change_basis = deadlines.can_change_due_date(start, today)
    objection = deadlines.objection_deadline(row.acknowledged_on) if row.acknowledged_on else None
    step_index = next((i for i, (st, _) in enumerate(STEPS) if st == state), len(STEPS) if state == EvaluationState.FINAL else 3)
    if state == EvaluationState.OBJECTION:
        step_index = 5
    p3 = form.get("part3") or {}
    obs = _observations(c, row, summary)
    period_notes = None
    if role == EVALUATOR and state == EvaluationState.OBSERVATION:
        period_notes = c.notes.notes_for(row.evaluator_id, row.employee_id, since=row.period_from or row.cycle_start)
    tips = guide.tips_for(
        ev=summary, role=role, today=today, notes=period_notes, warnings=len(obs["warnings"]),
        objection_until=objection.date if objection else None,
        new_note=guide.new_note_url(c, row.employee_id) if role == EVALUATOR and row.evaluator_id else None,
    )

    return render(
        request, "core/ocena.html", title=f"Ocena — {employee.full_name}",
        row=row, ev=summary, employee=employee, evaluator=evaluator, role=role, state=state, sheet=sheet,
        sheet_def=c.catalog.sheets[sheet], form=form, criteria=criteria, live=live, result=result, issues=issues,
        additional_options=c.catalog.additional_for(sheet), drafts=drafts,
        obs=obs, tips=tips, events=workflow.events_for(c, row.id),
        unit=c.employees.org_unit(employee.position.org_unit_id),
        evaluator_unit=c.employees.org_unit(evaluator.position.org_unit_id) if evaluator else None,
        office=c.employees.office(), today=today, steps=STEPS, step_index=step_index,
        can_change_due=can_change, change_basis=change_basis, change_reasons=deadlines.DUE_DATE_CHANGE_REASONS,
        objection=objection, first_assessment=first, p3=p3,
        next_grade=careers.next_grade_text(int(p3.get("grade") or employee.grade or 0) or None),
        ed=lambda field: FORM.can_edit(field, state, role), FORM=FORM, Role=Role, Level=Level,
        EVALUATOR=EVALUATOR, EMPLOYEE=EMPLOYEE, admin_fields=sorted(workflow.ADMIN_FIELDS),
        msg_ok=request.query_params.get("ok"), msg_error=request.query_params.get("error"),
        **_ctx_common(),
    )


@router.get("/oceny/{evaluation_id}/przygotowanie")
def przygotowanie(evaluation_id: str, request: Request):
    """„Pomóż mi przygotować się do rozmowy” — ściąga dla oceniającego (§ 10), bez LLM."""
    c, user, row = _load(request, evaluation_id)
    if actor_role(row, user) != EVALUATOR or not row.evaluator_id:
        return render(request, "core/brak_dostepu.html", title="Przygotowanie do rozmowy",
                      what="Przygotowanie do rozmowy widzi tylko oceniający — opiera się na jego prywatnych notatkach.")
    summary = summary_from_row(row, c.catalog)
    employee = c.employees.get(row.employee_id)
    criteria = criteria_for(SheetType(row.sheet), row.additional or [], c.catalog)
    since = row.period_from or row.cycle_start
    notes = c.notes.notes_for(row.evaluator_id, row.employee_id, since=since)
    stats = {s.criterion_code: s for s in c.notes.stats_for(row.evaluator_id, row.employee_id, row.id)}
    today = c.clock.today()
    prep = guide.prepare(ev=summary, criteria=criteria, stats=stats, notes=notes, today=today)
    return render(
        request, "core/przygotowanie.html", title=f"Przygotowanie do rozmowy — {employee.full_name}",
        row=row, ev=summary, employee=employee, prep=prep, since=since, state=EvaluationState(row.state),
        teczka=c.notes.teczka_url(row.employee_id), new_note=guide.new_note_url(c, row.employee_id),
        hr_url=guide.hr_prep_url("oceniajaca", row.employee_id), **_ctx_common(),
    )


@router.get("/oceny/{evaluation_id}/druk")
def druk(evaluation_id: str, request: Request):
    c, user, row = _load(request, evaluation_id)
    employee = c.employees.get(row.employee_id)
    evaluator = c.employees.get(row.evaluator_id) if row.evaluator_id else None
    sheet = SheetType(row.sheet)
    form = row.form or {}
    p3 = form.get("part3") or {}
    return render(
        request, "core/druk.html", title="Wydruk arkusza",
        row=row, employee=employee, evaluator=evaluator, sheet=sheet, sheet_def=c.catalog.sheets[sheet],
        form=form, mandatory=c.catalog.mandatory_for(sheet),
        additional=[c.catalog.get(code) for code in (row.additional or [])],
        result=result_from_row(row), office=c.employees.office(),
        unit=c.employees.org_unit(employee.position.org_unit_id),
        evaluator_unit=c.employees.org_unit(evaluator.position.org_unit_id) if evaluator else None,
        p3=p3, next_grade=careers.next_grade_text(int(p3.get("grade") or employee.grade or 0) or None),
        show_part3=employee.is_urzednik and form.get("promotion_choice") == "TAK",
        **_ctx_common(),
    )


# --- akcje -----------------------------------------------------------------------------------


async def _act(request: Request, evaluation_id: str, action, *, ok: str):
    c = get_container(request)
    user = get_current_user(request)
    data = await request.form()
    url = f"/core/oceny/{evaluation_id}"
    try:
        target = action(c, user, data)
    except (WorkflowError, ValueError) as exc:
        return _back(url, str(exc), error=True)
    if isinstance(target, str) and target != evaluation_id:
        url = f"/core/oceny/{target}"
    return _back(url, ok)


@router.post("/oceny/{evaluation_id}/kryteria")
async def post_part1(evaluation_id: str, request: Request):
    def action(c, user, data):
        workflow.save_part1(c, evaluation_id, user, additional=[data.get(f"additional_{i}", "") for i in range(3)],
                            due_date=_date(data.get("due_date")), place=data.get("place"))
        if data.get("confirm"):
            workflow.confirm_criteria(c, evaluation_id, user)
    return await _act(request, evaluation_id, action, ok="Zapisano część I.")


@router.post("/oceny/{evaluation_id}/kryteria/potwierdz")
async def post_ack_criteria(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.acknowledge_criteria(
        c, evaluation_id, u, place=d.get("place")), ok="Potwierdzono zapoznanie z kryteriami i terminem oceny.")


@router.post("/oceny/{evaluation_id}/rozmowa")
async def post_interview(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.record_interview(
        c, evaluation_id, u, interview_date=_date(d.get("interview_date"))), ok="Zapisano datę rozmowy oceniającej.")


def _assessment_data(data) -> dict[str, Any]:
    out: dict[str, Any] = {
        "partial_points": {k.removeprefix("p_"): v for k, v in data.items() if k.startswith("p_")},
    }
    for key in ("justification", "iprz", "promotion_choice", "objection_addressee", "part2_place_evaluator"):
        if key in data:
            out[key] = data.get(key)
    if data.get("period_from"):
        out["period_from"] = _date(data.get("period_from"))
    if data.get("period_to"):
        out["period_to"] = _date(data.get("period_to"))
    if "prev_outcome" in data:
        out["previous"] = {"outcome": data.get("prev_outcome") or None, "level": data.get("prev_level") or None,
                           "assessed_on": data.get("prev_assessed_on") or None, "from_history": False}
    if "p3_motivation" in data:
        out["part3"] = {"appointed_year": data.get("p3_appointed_year"), "grade": data.get("p3_grade"),
                        "grade_granted_on": data.get("p3_grade_granted_on"), "motivation": data.get("p3_motivation")}
    return out


@router.post("/oceny/{evaluation_id}/ocena")
async def post_assessment(evaluation_id: str, request: Request):
    def action(c, user, data):
        workflow.save_assessment(c, evaluation_id, user, _assessment_data(data))
        if data.get("submit"):
            workflow.submit_assessment(c, evaluation_id, user)
    data = await request.form()
    ok = "Ocena zatwierdzona i przekazana ocenianemu do zapoznania." if data.get("submit") else "Zapisano wersję roboczą."
    return await _act(request, evaluation_id, action, ok=ok)


@router.post("/oceny/{evaluation_id}/zapoznanie")
async def post_ack(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.acknowledge_assessment(
        c, evaluation_id, u, place=d.get("place")), ok="Potwierdzono zapoznanie z oceną.")


@router.post("/oceny/{evaluation_id}/fikcja-zapoznania")
async def post_deem(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.deem_acknowledged(
        c, evaluation_id, u, note=str(d.get("note", ""))), ok="Stwierdzono fikcję zapoznania.")


@router.post("/oceny/{evaluation_id}/sprzeciw")
async def post_objection(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.file_objection(
        c, evaluation_id, u, text=str(d.get("text", ""))), ok="Wniesiono sprzeciw.")


@router.post("/oceny/{evaluation_id}/sprzeciw/decyzja")
async def post_objection_decision(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.resolve_objection(
        c, evaluation_id, u, decision=str(d.get("decision", "")), note=str(d.get("note", ""))),
        ok="Zapisano rozstrzygnięcie sprzeciwu.")


@router.post("/oceny/{evaluation_id}/termin")
async def post_due_change(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.change_due_date(
        c, evaluation_id, u, new_date=_date(d.get("new_date")), reason=str(d.get("reason", ""))),
        ok="Zmieniono termin oceny; oceniany został zawiadomiony.")


@router.post("/oceny/{evaluation_id}/korekta")
async def post_admin_correct(evaluation_id: str, request: Request):
    return await _act(request, evaluation_id, lambda c, u, d: workflow.admin_correct(
        c, evaluation_id, u, field=str(d.get("field", "")), value=_date(d.get("value")),
        reason=str(d.get("reason", ""))), ok="Zapisano korektę (odnotowana w historii).")


# --- kadry ----------------------------------------------------------------------------------


def _require_hr(request: Request):
    user = get_current_user(request)
    if not (user.has(Role.KADRY) or user.has(Role.ZARZADZAJACY)):
        raise HTTPException(403, "Widok dostępny dla kadr i kierownictwa urzędu")
    return user


@router.get("/kadry")
def kadry(request: Request):
    user = get_current_user(request)
    if not (user.has(Role.KADRY) or user.has(Role.ZARZADZAJACY)):
        return render(request, "core/brak_dostepu.html", title="Kadry",
                      what="Ten widok jest dostępny dla komórki kadrowej i kierownictwa urzędu.")
    c = get_container(request)
    today = c.clock.today()
    filt = request.query_params.get("filtr", "")
    people = []
    for emp in c.employees.all():
        ev = c.evaluations.current_for(emp.id)
        next_due = None
        if ev:
            next_due = ev.criteria_due_date if ev.state == EvaluationState.CYCLE_OPEN else ev.due_date
        promo = careers.obligatory_promotion(emp, c.evaluations.history(emp.id))
        flag = urgency(next_due, today)
        if filt == "zalegle" and flag != "danger":
            continue
        if filt == "30dni" and flag not in ("danger", "warn"):
            continue
        people.append({
            "emp": emp, "ev": ev, "next_due": next_due, "flag": flag, "promo": promo,
            "unit": c.employees.org_unit(emp.position.org_unit_id),
            "absences": c.employees.absences(emp.id),
        })
    return render(
        request, "core/kadry.html", title="Kadry", people=people, filt=filt, stats=_stats(c),
        msg_ok=request.query_params.get("ok"), msg_error=request.query_params.get("error"), **_ctx_common(),
    )


MIN_GROUP = 5  # statystyki tylko dla grup ≥ 5 osób (anonimowość)


def _stats(c) -> dict[str, Any]:
    with c.session_factory() as s:
        rows = s.scalars(select(EvaluationRow)).all()
        open_rows = [r for r in rows if r.state not in ("FINAL", "CANCELLED")]
        final = [r for r in rows if r.state == "FINAL" and r.outcome]
    today = c.clock.today()
    by_state: dict[str, int] = {}
    for r in open_rows:
        by_state[STATE_LABELS[EvaluationState(r.state)]] = by_state.get(STATE_LABELS[EvaluationState(r.state)], 0) + 1
    overdue = sum(
        1 for r in open_rows
        if (r.state == "CYCLE_OPEN" and r.criteria_due_date and r.criteria_due_date < today)
        or (r.state in ("OBSERVATION", "INTERVIEW_HELD") and r.due_date and r.due_date < today)
    )  # fmt: skip
    levels: dict[str, int] | None = None
    if len(final) >= MIN_GROUP:
        levels = {}
        for r in final:
            label = Level(r.level).label
            levels[label] = levels.get(label, 0) + 1
    return {"open": len(open_rows), "overdue": overdue, "by_state": by_state, "levels": levels,
            "final_count": len(final), "min_group": MIN_GROUP}


@router.post("/kadry/nieobecnosc")
async def post_absence(request: Request):
    user = _require_hr(request)
    c = get_container(request)
    data = await request.form()
    try:
        new_due = workflow.add_absence(c, str(data.get("employee_id")), user,
                                       start=_date(data.get("start")), end=_date(data.get("end")))
    except (WorkflowError, ValueError, TypeError) as exc:
        return _back("/core/kadry", str(exc), error=True)
    msg = "Zapisano nieobecność."
    if new_due:
        msg += f" Termin oceny przedłużony do {new_due:%d.%m.%Y} (art. 81 ust. 7)."
    return _back("/core/kadry", msg)


@router.post("/kadry/{employee_id}/pierwszy-cykl")
async def post_first_cycle(employee_id: str, request: Request):
    user = _require_hr(request)
    c = get_container(request)
    try:
        new_id = workflow.open_first_cycle(c, employee_id, user)
    except WorkflowError as exc:
        return _back("/core/kadry", str(exc), error=True)
    return _back(f"/core/oceny/{new_id}", "Otwarto pierwszy cykl oceny.")


@router.post("/kadry/{employee_id}/stopien")
async def post_grade(employee_id: str, request: Request):
    """Odnotowanie przyznania stopnia (po obligatoryjnym albo fakultatywnym awansie)."""
    user = _require_hr(request)
    c = get_container(request)
    data = await request.form()
    try:
        granted = _date(data.get("granted_on")) or c.clock.today()
        with c.session_factory() as s:
            row = s.get(EmployeeRow, employee_id)
            emp = employee_from_row(row)
            if not emp.is_urzednik or (emp.grade or 0) >= careers.MAX_GRADE:
                raise WorkflowError("Tej osobie nie można przyznać kolejnego stopnia.")
            row.grade = (row.grade or 0) + 1
            row.grade_granted_on = granted
            from app.core.repo import log_event

            log_event(s, at=c.clock.now(), action="GRADE_GRANTED", actor_id=user.employee_id,
                      employee_id=employee_id, grade=row.grade, granted_on=granted)
            s.commit()
    except (WorkflowError, ValueError) as exc:
        return _back("/core/kadry", str(exc), error=True)
    return _back("/core/kadry", "Odnotowano przyznanie kolejnego stopnia służbowego.")
