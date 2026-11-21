"""Strony teczki: /asystent/teczka, oś czasu osoby, formularz notatki (§ 5.1)."""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.assistant.notes.assist import CLASSIFY_TASK, SPLIT_TASK, classify_note, split_note
from app.assistant.notes.criteria import criteria_for
from app.assistant.notes.repository import NoteAlreadyRevised, NoteInput, NoteNotFound
from app.assistant.notes.stats import compute_stats
from app.assistant.pages import PageError, html_errors
from app.assistant.services import services
from app.assistant.stt import TranscriptionError
from app.container import Container
from app.contracts.enums import LEVEL_LABELS, PARTIAL_POINTS, EvaluationState, NoteSource
from app.contracts.models import CriterionRating, Employee, EvaluationSummary, Note, UserContext
from app.contracts.regulation import load_scale
from app.deps import get_container, get_current_user
from app.templating import render

router = APIRouter()

MONTHS = [
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
]  # fmt: skip

STATE_LABELS = {
    EvaluationState.CYCLE_OPEN: "kryteria do ustalenia",
    EvaluationState.CRITERIA_CONFIRMED: "kryteria ustalone",
    EvaluationState.OBSERVATION: "okres oceny",
    EvaluationState.INTERVIEW_HELD: "po rozmowie oceniającej",
    EvaluationState.AWAITING_ACK: "czeka na zapoznanie",
    EvaluationState.ACKNOWLEDGED: "zapoznano",
    EvaluationState.OBJECTION: "sprzeciw",
    EvaluationState.FINAL: "zakończona",
    EvaluationState.CANCELLED: "anulowana",
}


def _point_labels(c: Container) -> dict[int, str]:
    scale = load_scale(c.settings.regulation_dir)
    return {p: LEVEL_LABELS[scale.partial_points[p]] for p in PARTIAL_POINTS}


def _criterion_name(c: Container, code: str) -> str:
    try:
        return c.catalog.get(code).name
    except KeyError:
        return code


# --- dostęp ---------------------------------------------------------------------------


def _employee_or_404(c: Container, employee_id: str) -> Employee:
    try:
        return c.employees.get(employee_id)
    except KeyError as exc:
        raise PageError(404, "Nie ma takiej osoby.") from exc


def _is_subordinate(c: Container, user: UserContext, subject_id: str) -> bool:
    return any(e.id == subject_id for e in c.employees.subordinates(user.employee_id))


def _require_subordinate(c: Container, user: UserContext, subject_id: str) -> Employee:
    subject = _employee_or_404(c, subject_id)
    if not _is_subordinate(c, user, subject_id):
        raise PageError(403, "Notatki można dodawać tylko o swoich bezpośrednich podwładnych.")
    return subject


# --- lista podwładnych ----------------------------------------------------------------


@dataclass
class TeczkaRow:
    employee: Employee
    evaluation: EvaluationSummary | None
    n_notes: int
    last_note_on: date | None
    days_since: int | None
    stale: bool


@router.get("/teczka")
@html_errors
def teczka(request: Request):
    c = get_container(request)
    user = get_current_user(request)
    svc = services(c)
    today = c.clock.today()
    rows = []
    for employee in c.employees.subordinates(user.employee_id):
        evaluation = c.evaluations.current_for(employee.id)
        notes = svc.notes_repo.current(user.employee_id, employee.id)
        if evaluation:
            notes = [n for n in notes if n.evaluation_id == evaluation.id]
        last = max((n.observed_on for n in notes), default=None)
        days = (today - last).days if last else None
        rows.append(
            TeczkaRow(
                employee=employee,
                evaluation=evaluation,
                n_notes=len(notes),
                last_note_on=last,
                days_since=days,
                stale=evaluation is not None and (days is None or days > svc.nudges.no_note_after_days),
            )
        )
    digest = svc.note_nudges.digest_for(user.employee_id, today)
    names = {e.id: e.full_name for e in c.employees.subordinates(user.employee_id)}
    return render(
        request,
        "assistant/teczka_lista.html",
        title="Teczka",
        rows=rows,
        digest=digest,
        snoozed=[(sid, names.get(sid, sid), until) for sid, until in digest.snoozed.items()],
        snooze_days=svc.nudges.snooze_days,
        threshold=svc.nudges.no_note_after_days,
        state_labels=STATE_LABELS,
    )


# --- oś czasu osoby -------------------------------------------------------------------


@dataclass
class TimelineItem:
    note: Note
    previous_versions: list[Note]


def _evaluations_of(c: Container, subject_id: str) -> list[EvaluationSummary]:
    evaluations = list(c.evaluations.history(subject_id))
    current = c.evaluations.current_for(subject_id)
    if current:
        evaluations.append(current)
    return evaluations


def _filter_notes(notes: list[Note], *, cycle: str, kind: str, criterion: str, q: str) -> list[Note]:
    if cycle:
        notes = [n for n in notes if (n.evaluation_id or "") == cycle]
    if kind == "zalety":
        notes = [n for n in notes if n.strengths]
    elif kind == "obszary":
        notes = [n for n in notes if n.improvements]
    if criterion:
        notes = [n for n in notes if any(r.criterion_code == criterion for r in n.ratings)]
    if q:
        needle = q.casefold()
        notes = [
            n for n in notes if needle in " ".join([n.body, *n.strengths, *n.improvements]).casefold()
        ]
    return notes


@router.get("/teczka/{subject_id}")
@html_errors
def teczka_osoby(
    subject_id: str,
    request: Request,
    cykl: str | None = None,
    rodzaj: str = "",
    kryterium: str = "",
    q: str = "",
):
    c = get_container(request)
    user = get_current_user(request)
    svc = services(c)
    subject = _employee_or_404(c, subject_id)
    all_notes = svc.notes_repo.current(user.employee_id, subject_id)
    is_sub = _is_subordinate(c, user, subject_id)
    if not is_sub and not all_notes:
        raise PageError(403, "To nie jest Twój podwładny i nie masz o nim notatek.")

    evaluation = c.evaluations.current_for(subject_id)
    choice = criteria_for(evaluation, c.catalog)
    current_codes = set(choice.current_codes)
    stats = []
    if evaluation:
        cycle_notes = [n for n in all_notes if n.evaluation_id == evaluation.id]
        stats = compute_stats(
            cycle_notes,
            criteria_codes=choice.current_codes,
            period_from=evaluation.period_from,
            due_date=evaluation.due_date,
        )

    # domyślnie bieżący cykl; „wszystkie” = pusty parametr
    cycle = (evaluation.id if evaluation else "") if cykl is None else cykl
    notes = _filter_notes(all_notes, cycle=cycle, kind=rodzaj, criterion=kryterium, q=q.strip())
    items = [
        TimelineItem(
            note=n,
            previous_versions=svc.notes_repo.history(user.employee_id, n.id)[1:] if n.version > 1 else [],
        )
        for n in reversed(notes)
    ]
    groups: list[tuple[str, list[TimelineItem]]] = []
    for item in items:
        label = f"{MONTHS[item.note.observed_on.month - 1]} {item.note.observed_on.year}"
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(item)

    rated_codes = sorted({r.criterion_code for n in all_notes for r in n.ratings})
    hints = {
        note_id: list(dict.fromkeys(h["criterion_code"] for h in entries))
        for note_id, entries in svc.notes_repo.hints_for(n.id for n in notes).items()
    }
    return render(
        request,
        "assistant/teczka_osoba.html",
        title=f"Teczka · {subject.full_name}",
        subject=subject,
        is_subordinate=is_sub,
        evaluation=evaluation,
        evaluations=_evaluations_of(c, subject_id),
        state_labels=STATE_LABELS,
        stats=stats,
        groups=groups,
        n_total=len(all_notes),
        n_shown=len(notes),
        filters={"cykl": cycle, "rodzaj": rodzaj, "kryterium": kryterium, "q": q},
        rated_codes=rated_codes,
        current_codes=current_codes,
        criterion_name=lambda code: _criterion_name(c, code),
        point_labels=_point_labels(c),
        points=PARTIAL_POINTS,
        notice=request.query_params.get("zapisano"),
        hints=hints,
        fuko_available=svc.llm.available("rewrite_feedback"),
    )


# --- formularz notatki ----------------------------------------------------------------


def _lines(value: str) -> list[str]:
    return [line.strip(" \t-•*") for line in value.splitlines() if line.strip(" \t-•*")]


async def _parse_form(request: Request, today: date) -> tuple[NoteInput, dict[str, str], list[str]]:
    form = await request.form()
    raw = {k: str(v) for k, v in form.items()}
    errors: list[str] = []
    try:
        observed_on = date.fromisoformat(raw.get("observed_on", "")) if raw.get("observed_on") else today
    except ValueError:
        observed_on = today
        errors.append("Nieprawidłowa data zdarzenia.")
    if observed_on > today:
        errors.append("Data zdarzenia nie może być z przyszłości.")
    ratings = []
    for key, value in raw.items():
        if key.startswith("rating_") and value:
            try:
                ratings.append(CriterionRating(criterion_code=key.removeprefix("rating_"), value=int(value)))
            except ValueError:
                errors.append("Suwak może mieć tylko wartości 1, 3, 5, 7 albo 9.")
    data = NoteInput(
        observed_on=observed_on,
        body=raw.get("body", "").strip(),
        strengths=_lines(raw.get("strengths", "")),
        improvements=_lines(raw.get("improvements", "")),
        ratings=ratings,
        source=NoteSource.VOICE if raw.get("source") == NoteSource.VOICE.value else NoteSource.TEXT,
    )
    if data.is_empty():
        errors.append("Wpisz opis sytuacji albo przynajmniej jedną zaletę lub obszar do poprawy.")
    return data, raw, errors


def _form_page(
    request: Request,
    c: Container,
    subject: Employee,
    *,
    values: dict,
    errors: list[str],
    action: str,
    editing: Note | None = None,
    status_code: int = 200,
    assistant_notice: str | None = None,
    assistant_error: str | None = None,
):
    evaluation = c.evaluations.current_for(subject.id)
    if editing and editing.evaluation_id:
        try:
            evaluation = c.evaluations.get(editing.evaluation_id)
        except KeyError:
            pass
    choice = criteria_for(evaluation, c.catalog)
    ratings = values.get("ratings", {})
    other_open = any(code in ratings for code in (o.code for o in choice.other))
    response = render(
        request,
        "assistant/notatka_form.html",
        title=f"Notatka · {subject.full_name}",
        subject=subject,
        evaluation=evaluation,
        criteria_current=choice.current,
        criteria_other=choice.other,
        other_open=other_open,
        before_criteria=evaluation is not None and evaluation.state == EvaluationState.CYCLE_OPEN,
        values=values,
        ratings=ratings,
        errors=errors,
        action=action,
        editing=editing,
        point_labels=_point_labels(c),
        points=PARTIAL_POINTS,
        split_available=services(c).llm.available(SPLIT_TASK),
        voice_available=services(c).stt.available() and editing is None,
        max_upload_mb=services(c).stt_config.max_upload_mb,
        voice_max_seconds=services(c).stt_config.max_seconds,
        assistant_notice=assistant_notice,
        assistant_error=assistant_error,
    )
    response.status_code = status_code
    return response


def _merge_lines(existing: str, proposed: list[str]) -> str:
    lines = _lines(existing)
    lines += [p for p in proposed if p not in lines]
    return "\n".join(lines)


def _split_page(request: Request, c: Container, subject: Employee, raw: dict, action: str, editing: Note | None):
    """Akcja „Podziel opis”: propozycja LLM trafia do pól formularza, nic się nie zapisuje."""
    values = _values_from_raw(raw)
    outcome = split_note(services(c), subject, values["body"])
    notice = None
    if not outcome.error:
        values["strengths"] = _merge_lines(values["strengths"], outcome.strengths)
        values["improvements"] = _merge_lines(values["improvements"], outcome.improvements)
        notice = (
            f"Asystent zaproponował: zalety — {len(outcome.strengths)}, obszary do poprawy — "
            f"{len(outcome.improvements)}. Sprawdź i popraw punkty przed zapisem. Suwaki ustawiasz sam."
            if not outcome.empty
            else "Asystent nie znalazł w opisie wyraźnych zalet ani obszarów do poprawy."
        )
    return _form_page(
        request, c, subject, values=values, errors=[], action=action, editing=editing,
        assistant_notice=notice, assistant_error=outcome.error,
    )  # fmt: skip


def _classify_later(background: BackgroundTasks, c: Container, note: Note, subject: Employee) -> None:
    svc = services(c)
    if svc.llm.available(CLASSIFY_TASK):
        background.add_task(classify_note, svc, c.catalog, note, subject, c.clock.now())


def _values_from_note(note: Note) -> dict:
    return {
        "observed_on": note.observed_on.isoformat(),
        "body": note.body,
        "strengths": "\n".join(note.strengths),
        "improvements": "\n".join(note.improvements),
        "ratings": {r.criterion_code: r.value for r in note.ratings},
        "source": note.source.value,
    }


def _values_from_raw(raw: dict[str, str]) -> dict:
    return {
        "observed_on": raw.get("observed_on", ""),
        "body": raw.get("body", ""),
        "strengths": raw.get("strengths", ""),
        "improvements": raw.get("improvements", ""),
        "source": raw.get("source", NoteSource.TEXT.value),
        "ratings": {
            k.removeprefix("rating_"): int(v) for k, v in raw.items() if k.startswith("rating_") and v.isdigit()
        },
    }


@router.get("/teczka/{subject_id}/nowa")
@html_errors
def nowa_notatka(subject_id: str, request: Request):
    c = get_container(request)
    subject = _require_subordinate(c, get_current_user(request), subject_id)
    values = {"observed_on": c.clock.today().isoformat(), "ratings": {}}
    return _form_page(request, c, subject, values=values, errors=[], action=f"/asystent/teczka/{subject_id}/nowa")


@router.post("/teczka/{subject_id}/nowa")
@html_errors
async def zapisz_notatke(subject_id: str, request: Request, background: BackgroundTasks):
    c = get_container(request)
    user = get_current_user(request)
    subject = _require_subordinate(c, user, subject_id)
    data, raw, errors = await _parse_form(request, c.clock.today())
    if raw.get("akcja") == "podziel":
        return _split_page(request, c, subject, raw, f"/asystent/teczka/{subject_id}/nowa", None)
    if errors:
        return _form_page(
            request, c, subject, values=_values_from_raw(raw), errors=errors,
            action=f"/asystent/teczka/{subject_id}/nowa", status_code=422,
        )  # fmt: skip
    evaluation = c.evaluations.current_for(subject_id)
    note = services(c).notes_repo.create(
        author_id=user.employee_id,
        subject_id=subject_id,
        evaluation_id=evaluation.id if evaluation else None,
        data=data,
        now=c.clock.now(),
    )
    _classify_later(background, c, note, subject)
    return RedirectResponse(f"/asystent/teczka/{subject_id}?zapisano=1", status_code=303)


# --- notatka głosowa -------------------------------------------------------------------


async def _save_upload(upload: UploadFile, limit_bytes: int) -> Path:
    suffix = Path(upload.filename or "").suffix[:8] or ".webm"
    fd, name = tempfile.mkstemp(prefix="asst-voice-", suffix=suffix)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit_bytes:
                    raise TranscriptionError(f"Plik jest za duży. Limit: {limit_bytes // (1024 * 1024)} MB.")
                out.write(chunk)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    if size == 0:
        Path(name).unlink(missing_ok=True)
        raise TranscriptionError("Nagranie jest puste.")
    return Path(name)


@router.post("/teczka/{subject_id}/glos")
@html_errors
async def notatka_glosowa(subject_id: str, request: Request, audio: UploadFile = File(...)):
    """Nagranie → transkrypt do akceptacji. Audio kasujemy od razu po transkrypcji (także przy błędzie).

    `Accept: application/json` (nagrywanie w przeglądarce) → JSON; bez JS (plik z telefonu) → formularz notatki.
    """
    c = get_container(request)
    user = get_current_user(request)
    subject = _require_subordinate(c, user, subject_id)
    svc = services(c)
    wants_json = "application/json" in request.headers.get("accept", "")
    action = f"/asystent/teczka/{subject_id}/nowa"
    try:
        if not svc.stt.available():
            raise TranscriptionError("Notatki głosowe są wyłączone.")
        path = await _save_upload(audio, svc.stt_config.max_upload_mb * 1024 * 1024)
        try:
            text = await run_in_threadpool(svc.stt.transcribe, path)
        finally:
            path.unlink(missing_ok=True)
    except TranscriptionError as err:
        if wants_json:
            return JSONResponse({"error": err.message}, status_code=422)
        values = {"observed_on": c.clock.today().isoformat(), "ratings": {}}
        return _form_page(request, c, subject, values=values, errors=[], action=action, assistant_error=err.message, status_code=422)
    if wants_json:
        return JSONResponse({"text": text})
    values = {"observed_on": c.clock.today().isoformat(), "body": text, "source": NoteSource.VOICE.value, "ratings": {}}
    notice = "Transkrypt gotowy — sprawdź go i popraw przed zapisem. Nagranie zostało usunięte z serwera."
    return _form_page(request, c, subject, values=values, errors=[], action=action, assistant_notice=notice)


def _own_current_note(c: Container, user: UserContext, subject_id: str, note_id: str) -> Note:
    repo = services(c).notes_repo
    try:
        note = repo.get(user.employee_id, note_id)
    except NoteNotFound as exc:
        raise PageError(404, "Nie ma takiej notatki.") from exc
    if note.subject_id != subject_id:
        raise PageError(404, "Nie ma takiej notatki.")
    if not repo.is_current(note_id):
        raise PageError(409, "Ta wersja notatki została już poprawiona — edytuj najnowszą.")
    return note


@router.get("/teczka/{subject_id}/notatka/{note_id}/edytuj")
@html_errors
def edytuj_notatke(subject_id: str, note_id: str, request: Request):
    c = get_container(request)
    user = get_current_user(request)
    subject = _employee_or_404(c, subject_id)
    note = _own_current_note(c, user, subject_id, note_id)
    return _form_page(
        request, c, subject, values=_values_from_note(note), errors=[],
        action=f"/asystent/teczka/{subject_id}/notatka/{note_id}/edytuj", editing=note,
    )  # fmt: skip


@router.post("/teczka/{subject_id}/notatka/{note_id}/edytuj")
@html_errors
async def zapisz_poprawke(subject_id: str, note_id: str, request: Request, background: BackgroundTasks):
    c = get_container(request)
    user = get_current_user(request)
    subject = _employee_or_404(c, subject_id)
    note = _own_current_note(c, user, subject_id, note_id)
    data, raw, errors = await _parse_form(request, c.clock.today())
    action = f"/asystent/teczka/{subject_id}/notatka/{note_id}/edytuj"
    if raw.get("akcja") == "podziel":
        return _split_page(request, c, subject, raw, action, note)
    if errors:
        return _form_page(
            request, c, subject, values=_values_from_raw(raw), errors=errors,
            action=action, editing=note, status_code=422,
        )  # fmt: skip
    try:
        revised = services(c).notes_repo.revise(
            author_id=user.employee_id, note_id=note_id, data=data, now=c.clock.now()
        )
    except NoteAlreadyRevised as exc:
        raise PageError(409, "Ta wersja notatki została już poprawiona.") from exc
    _classify_later(background, c, revised, subject)
    return RedirectResponse(f"/asystent/teczka/{subject_id}?zapisano=1", status_code=303)
