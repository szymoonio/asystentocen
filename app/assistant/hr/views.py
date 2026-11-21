"""Asystent HR — strony /asystent/hr (§ 7)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from app.assistant.hr import fuko as fuko_mod
from app.assistant.hr import prep as prep_mod
from app.assistant.hr import qa as qa_mod
from app.assistant.hr import roleplay as rp
from app.assistant.hr.boundaries import check
from app.assistant.hr.signals import signals_for
from app.assistant.llm import LLMError
from app.assistant.notes.repository import NoteNotFound
from app.assistant.pages import PageError, html_errors
from app.assistant.services import AssistantServices, services
from app.container import Container
from app.contracts.models import Employee, UserContext
from app.deps import get_container, get_current_user
from app.templating import render

router = APIRouter()


def _ctx(request: Request) -> tuple[Container, UserContext, AssistantServices]:
    c = get_container(request)
    return c, get_current_user(request), services(c)


def _subordinate(c: Container, user: UserContext, employee_id: str | None) -> Employee | None:
    if not employee_id:
        return None
    for e in c.employees.subordinates(user.employee_id):
        if e.id == employee_id:
            return e
    raise PageError(403, "Możesz wybrać tylko swojego bezpośredniego podwładnego.")


async def _form(request: Request) -> dict[str, str]:
    return {k: str(v) for k, v in (await request.form()).items()}


# --- strona główna -----------------------------------------------------------------------


@router.get("/hr")
@html_errors
def hr_index(request: Request):
    c, user, svc = _ctx(request)
    signals = signals_for(
        user.employee_id,
        c.clock.today(),
        employees=c.employees,
        evaluations=c.evaluations,
        repo=svc.notes_repo,
        cfg=svc.nudges,
    )
    return render(
        request,
        "assistant/hr_index.html",
        title="Asystent HR",
        signals=signals,
        llm={t: svc.llm.available(t) for t in (prep_mod.TASK, rp.TASK, fuko_mod.TASK, qa_mod.TASK)},
    )


# --- przygotowanie do rozmowy --------------------------------------------------------------


def _prep_page(request: Request, values: dict, outcome=None, status_code: int = 200):
    c, user, svc = _ctx(request)
    kind = values.get("rodzaj") or "trudna"
    response = render(
        request,
        "assistant/hr_przygotowanie.html",
        title="Przygotowanie do rozmowy",
        kinds=prep_mod.KINDS,
        checklist=prep_mod.CHECKLISTS.get(kind),
        subordinates=c.employees.subordinates(user.employee_id),
        values=values,
        outcome=outcome,
        llm_available=svc.llm.available(prep_mod.TASK),
        roleplay_available=svc.llm.available(rp.TASK),
    )
    response.status_code = status_code
    return response


@router.get("/hr/przygotowanie")
@html_errors
def przygotowanie(request: Request, rodzaj: str = "trudna", osoba: str = ""):
    c, user, _ = _ctx(request)
    _subordinate(c, user, osoba)
    return _prep_page(request, {"rodzaj": rodzaj, "osoba": osoba, "teczka": "1" if osoba else ""})


@router.post("/hr/przygotowanie")
@html_errors
async def przygotuj(request: Request):
    c, user, svc = _ctx(request)
    values = await _form(request)
    if not values.get("opis", "").strip():
        return _prep_page(request, values, prep_mod.PrepOutcome(error="Opisz krótko sytuację."), 422)
    subject = _subordinate(c, user, values.get("osoba"))
    notes = None
    if subject and values.get("teczka"):
        evaluation = c.evaluations.current_for(subject.id)
        notes = [
            n
            for n in svc.notes_repo.current(user.employee_id, subject.id)
            if evaluation is None or n.evaluation_id == evaluation.id
        ]
    outcome = prep_mod.prepare(
        kind=values.get("rodzaj", "trudna"),
        situation=values["opis"],
        llm=svc.llm,
        hr=svc.hr,
        people=c.employees.all(),
        pseudonymizer=svc.pseudonymizer(),
        subject=subject,
        notes=notes,
    )
    return _prep_page(request, values, outcome)


# --- próba rozmowy ------------------------------------------------------------------------


def _own_roleplay(request: Request, roleplay_id: str) -> rp.Roleplay:
    _, user, svc = _ctx(request)
    found = svc.roleplays.get(user.employee_id, roleplay_id)
    if found is None:
        raise PageError(404, "Nie ma takiego ćwiczenia.")
    return found


@router.get("/hr/proba/nowa")
@html_errors
def proba_nowa(request: Request):
    _, _, svc = _ctx(request)
    return render(
        request,
        "assistant/hr_proba_nowa.html",
        title="Nowa próba rozmowy",
        difficulties=rp.DIFFICULTIES,
        llm_available=svc.llm.available(rp.TASK),
    )


@router.post("/hr/proba")
@html_errors
async def proba_utworz(request: Request):
    c, user, svc = _ctx(request)
    if not svc.llm.available(rp.TASK):
        raise PageError(403, "Próba rozmowy wymaga asystenta LLM, który jest wyłączony.")
    values = await _form(request)
    card = {
        "persona": values.get("persona", "").strip() or "Pracownik merytoryczny w urzędzie",
        "goal": values.get("goal", "").strip(),
        "resistance": values.get("resistance", "").strip(),
        "phrases": [p.strip() for p in values.get("phrases", "").splitlines() if p.strip()][:5],
        "difficulty": values.get("difficulty", "srednia") if values.get("difficulty") in rp.DIFFICULTIES else "srednia",
    }
    blob = " ".join([card["persona"], card["goal"], card["resistance"], *card["phrases"]])
    if boundary := check(blob, svc.hr, c.employees.all()):
        return render(request, "assistant/hr_granica.html", title="Asystent HR", boundary=boundary)
    roleplay = svc.roleplays.create(user.employee_id, card, c.clock.now())
    return RedirectResponse(f"/asystent/hr/proba/{roleplay.id}", status_code=303)


@router.get("/hr/proba/{roleplay_id}")
@html_errors
def proba(roleplay_id: str, request: Request, blad: str = ""):
    _, _, svc = _ctx(request)
    roleplay = _own_roleplay(request, roleplay_id)
    return render(
        request,
        "assistant/hr_proba.html",
        title="Próba rozmowy",
        rp=roleplay,
        difficulties=rp.DIFFICULTIES,
        max_turns=svc.hr.roleplay_max_turns,
        error=blad,
    )


@router.post("/hr/proba/{roleplay_id}/wiadomosc")
@html_errors
async def proba_wiadomosc(roleplay_id: str, request: Request):
    """Z nagłówkiem `X-Stream: 1` (JS) — strumień tekstu; bez JS — czekamy na całość i wracamy na stronę."""
    c, _, svc = _ctx(request)
    roleplay = _own_roleplay(request, roleplay_id)
    values = await _form(request)
    streaming = request.headers.get("x-stream") == "1"
    try:
        chunks = rp.reply(
            svc.roleplays, roleplay, values.get("tekst", ""),
            llm=svc.llm, hr=svc.hr, people=c.employees.all(), pseudonymizer=svc.pseudonymizer(),
        )  # fmt: skip
    except rp.RoleplayError as err:
        if streaming:
            return StreamingResponse(iter([f"[{err.message}]"]), status_code=422, media_type="text/plain; charset=utf-8")
        return RedirectResponse(f"/asystent/hr/proba/{roleplay_id}?blad={quote(err.message)}#rozmowa", status_code=303)
    if streaming:
        return StreamingResponse(chunks, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache"})
    for _ in chunks:  # bez JS: konsumujemy strumień, odpowiedź zapisze się na końcu
        pass
    return RedirectResponse(f"/asystent/hr/proba/{roleplay_id}#rozmowa", status_code=303)


@router.post("/hr/proba/{roleplay_id}/koniec")
@html_errors
def proba_koniec(roleplay_id: str, request: Request):
    _, _, svc = _ctx(request)
    roleplay = _own_roleplay(request, roleplay_id)
    try:
        rp.finish(svc.roleplays, roleplay, llm=svc.llm)
    except LLMError as err:
        return RedirectResponse(f"/asystent/hr/proba/{roleplay_id}?blad={quote(err.user_message)}", status_code=303)
    return RedirectResponse(f"/asystent/hr/proba/{roleplay_id}#informacja-zwrotna", status_code=303)


# --- notatka → FUKO -----------------------------------------------------------------------


def _fuko_page(request: Request, values: dict, outcome=None, note=None, status_code: int = 200):
    _, _, svc = _ctx(request)
    response = render(
        request,
        "assistant/hr_fuko.html",
        title="Notatka → informacja zwrotna",
        values=values,
        outcome=outcome,
        note=note,
        llm_available=svc.llm.available(fuko_mod.TASK),
    )
    response.status_code = status_code
    return response


def _note_text(note) -> str:
    parts = [note.body]
    if note.strengths:
        parts.append("Zalety: " + "; ".join(note.strengths))
    if note.improvements:
        parts.append("Do poprawy: " + "; ".join(note.improvements))
    return "\n".join(p for p in parts if p)


def _own_note(svc: AssistantServices, user: UserContext, note_id: str):
    try:
        return svc.notes_repo.get(user.employee_id, note_id)
    except NoteNotFound as exc:
        raise PageError(404, "Nie ma takiej notatki.") from exc


@router.get("/hr/fuko")
@html_errors
def fuko(request: Request, notatka: str = ""):
    _, user, svc = _ctx(request)
    note = _own_note(svc, user, notatka) if notatka else None
    return _fuko_page(request, {"tekst": _note_text(note) if note else "", "notatka": notatka}, note=note)


@router.post("/hr/fuko")
@html_errors
async def fuko_przeredaguj(request: Request):
    c, user, svc = _ctx(request)
    values = await _form(request)
    note = _own_note(svc, user, values["notatka"]) if values.get("notatka") else None
    subject = c.employees.get(note.subject_id) if note else None
    outcome = fuko_mod.rewrite(
        values.get("tekst", ""),
        llm=svc.llm, hr=svc.hr, people=c.employees.all(), pseudonymizer=svc.pseudonymizer(), subject=subject,
    )  # fmt: skip
    return _fuko_page(request, values, outcome, note=note)


# --- pytania o procedury -------------------------------------------------------------------


@router.get("/hr/procedury")
@html_errors
def procedury(request: Request, q: str = ""):
    _, _, svc = _ctx(request)
    outcome = qa_mod.QaOutcome(question=q, fragments=svc.knowledge().search(q, qa_mod.TOP_K)) if q.strip() else None
    return render(
        request,
        "assistant/hr_procedury.html",
        title="Pytania o procedury",
        q=q,
        outcome=outcome,
        llm_available=svc.llm.available(qa_mod.TASK),
    )


@router.post("/hr/procedury")
@html_errors
async def procedury_odpowiedz(request: Request):
    c, _, svc = _ctx(request)
    values = await _form(request)
    outcome = qa_mod.answer(
        values.get("q", ""),
        kb=svc.knowledge(), llm=svc.llm, hr=svc.hr, people=c.employees.all(), pseudonymizer=svc.pseudonymizer(),
    )  # fmt: skip
    return render(
        request,
        "assistant/hr_procedury.html",
        title="Pytania o procedury",
        q=values.get("q", ""),
        outcome=outcome,
        llm_available=svc.llm.available(qa_mod.TASK),
    )
