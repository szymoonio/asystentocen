"""Zakładka Analiza: /asystent/analiza?widok=zespol|osoba&osoba=E07.

Zestawienia i wykresy są deterministyczne i liczą się zawsze. Słowne podsumowanie (LLM)
generuje się tylko na przycisk i jest zapisywane — wejście na stronę nie wywołuje API.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.assistant.analysis import data as analysis_data
from app.assistant.analysis import llm as analysis_llm
from app.assistant.display import grouped_points
from app.assistant.llm import LLMError
from app.assistant.pages import PageError, html_errors
from app.assistant.services import services
from app.contracts.enums import LEVEL_LABELS
from app.contracts.models import Note
from app.contracts.regulation import load_scale
from app.deps import get_container, get_current_user
from app.templating import render

router = APIRouter()


def _context(request: Request):
    c = get_container(request)
    user = get_current_user(request)
    subordinates = c.employees.subordinates(user.employee_id)
    if not subordinates:
        raise PageError(403, "Analiza jest dostępna dla przełożonych — nie masz podwładnych w systemie.")
    svc = services(c)
    notes: dict[str, list[Note]] = {}
    for n in svc.notes_repo.current(user.employee_id):
        notes.setdefault(n.subject_id, []).append(n)
    scale = load_scale(c.settings.regulation_dir)
    return c, user, svc, subordinates, notes, scale


def _scale_labels(scale):
    return lambda value: LEVEL_LABELS[scale.partial_points[value]]


def _team(c, svc, subordinates, notes, scale):
    return analysis_data.team_data(c, notes, subordinates, scale, c.clock.today(), svc.nudges.no_note_after_days)


def _person(c, subordinates, notes, scale, osoba: str):
    employee = next((e for e in subordinates if e.id == osoba), None)
    if employee is None:
        raise PageError(403, "Analizę można zobaczyć tylko dla swoich bezpośrednich podwładnych.")
    return analysis_data.person_data(c, notes.get(employee.id, []), employee, scale, c.clock.today())


@router.get("/analiza")
@html_errors
def analiza(request: Request, widok: str = "zespol", osoba: str = ""):
    c, user, svc, subordinates, notes, scale = _context(request)
    widok = "osoba" if widok == "osoba" or osoba else "zespol"
    people = sorted(subordinates, key=lambda e: (e.last_name, e.first_name))
    ctx: dict = {"widok": widok, "people": people, "error": request.query_params.get("blad")}
    if widok == "zespol":
        team = _team(c, svc, subordinates, notes, scale)
        scope, task = "zespol", analysis_llm.TEAM_TASK
        key = analysis_llm.input_key([n for p in team.people for n in p.notes])
        ctx.update(team=team, title="Analiza zespołu")
    else:
        osoba = osoba or people[0].id
        person = _person(c, subordinates, notes, scale, osoba)
        scope, task = f"osoba:{osoba}", analysis_llm.PERSON_TASK
        key = analysis_llm.input_key(person.notes)
        ctx.update(person=person, chart=analysis_data.person_chart(c, person),
                   pros=grouped_points(person.notes, "strengths"), cons=grouped_points(person.notes, "improvements"),
                   person_activity=analysis_data.activity(person.all_notes, c.clock.today()),
                   teczka=c.notes.teczka_url(osoba), title=f"Analiza · {person.employee.full_name}")
    stored = svc.analyses.latest(user.employee_id, scope) if svc.analyses else None
    ctx.update(
        stored=stored, outdated=bool(stored and stored.input_key != key), scope=scope,
        llm_available=svc.llm.available(task), osoba=osoba,
        names={e.id: e.full_name for e in subordinates},
    )
    return render(request, "assistant/analiza.html", **ctx)


def _safe_back(value: str) -> str | None:
    """Tylko ścieżki w obrębie aplikacji (bez otwartego przekierowania na inną domenę)."""
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else None


@router.get("/analiza/fragment")
@html_errors
def fragment(request: Request, osoba: str = "", wroc: str = ""):
    """Podsumowanie notatek o osobie do osadzenia na innej stronie (np. ocena okresowa w module A)."""
    c, user, svc, subordinates, notes, scale = _context(request)
    person = _person(c, subordinates, notes, scale, osoba)
    stored = svc.analyses.latest(user.employee_id, f"osoba:{osoba}") if svc.analyses else None
    return render(
        request, "assistant/_analiza_wynik.html", stored=stored,
        outdated=bool(stored and stored.input_key != analysis_llm.input_key(person.notes)),
        llm_available=svc.llm.available(analysis_llm.PERSON_TASK), widok="osoba", osoba=osoba,
        names={e.id: e.full_name for e in subordinates}, wroc=_safe_back(wroc),
    )


@router.post("/analiza/generuj")
@html_errors
async def generuj(request: Request):
    c, user, svc, subordinates, notes, scale = _context(request)
    form = await request.form()
    widok, osoba = str(form.get("widok", "zespol")), str(form.get("osoba", ""))
    back = "/asystent/analiza?widok=zespol" if widok != "osoba" else f"/asystent/analiza?widok=osoba&osoba={osoba}"
    return_to = _safe_back(str(form.get("wroc", "")))
    pseudonymizer = svc.pseudonymizer()
    if widok == "osoba":
        person = _person(c, subordinates, notes, scale, osoba)
        task, scope, scoped = analysis_llm.PERSON_TASK, f"osoba:{osoba}", person.notes
        req = analysis_llm.build_person_request(person, pseudonymizer, _scale_labels(scale))
    else:
        team = _team(c, svc, subordinates, notes, scale)
        task, scope, scoped = analysis_llm.TEAM_TASK, "zespol", [n for p in team.people for n in p.notes]
        req = analysis_llm.build_team_request(team, pseudonymizer, _scale_labels(scale))
    try:
        result = analysis_llm.run(task, req, svc.llm)
    except LLMError as err:
        if return_to:
            sep = "&" if "?" in return_to else "?"
            return RedirectResponse(f"{return_to}{sep}error={quote(err.user_message)}#asystent-podsumowanie", status_code=303)
        return RedirectResponse(f"{back}&blad={quote(err.user_message)}", status_code=303)
    svc.analyses.save(user.employee_id, scope, analysis_llm.input_key(scoped), result, c.clock.now())
    if return_to:
        return RedirectResponse(return_to + "#asystent-podsumowanie", status_code=303)
    return RedirectResponse(back + "#claude", status_code=303)
