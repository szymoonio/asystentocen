"""Strona „Podsumowanie cyklu” dla oceniającego: materiał per kryterium i projekty tekstów."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.assistant.llm import LLMError
from app.assistant.pages import PageError, html_errors
from app.assistant.services import services
from app.assistant.summarize.evidence import CycleEvidence
from app.assistant.summarize.llm_summary import TASK
from app.assistant.summarize.skeleton import GENERATOR
from app.contracts.enums import LEVEL_LABELS, PARTIAL_POINTS, DraftField
from app.contracts.regulation import load_scale
from app.deps import get_container, get_current_user
from app.templating import render

router = APIRouter()

FIELD_TITLES = {
    DraftField.UZASADNIENIE: "Uzasadnienie przyznanej oceny okresowej",
    DraftField.WNIOSKI_IPRZ: "Wnioski dotyczące indywidualnego programu rozwoju zawodowego",
}


def _evidence_for_user(request: Request, evaluation_id: str) -> CycleEvidence:
    c = get_container(request)
    user = get_current_user(request)
    try:
        evaluation = c.evaluations.get(evaluation_id)
    except KeyError as exc:
        raise PageError(404, "Nie ma takiej oceny.") from exc
    if evaluation.evaluator_id != user.employee_id:
        raise PageError(403, "Podsumowanie cyklu widzi tylko oceniający.")
    evidence = services(c).drafts.evidence(evaluation_id)
    if evidence is None:
        raise PageError(404, "Nie ma takiej oceny.")
    return evidence


def _page(request: Request, evidence: CycleEvidence, *, error: str | None = None, status_code: int = 200):
    c = get_container(request)
    svc = services(c)
    scale = load_scale(c.settings.regulation_dir)
    drafts = {}
    for field, title in FIELD_TITLES.items():
        paragraphs, generator, created_at = svc.drafts.paragraphs(evidence, field)
        drafts[field] = {"title": title, "paragraphs": paragraphs, "generator": generator, "created_at": created_at}
    stored = svc.drafts.stored(evidence.evaluation.id)
    fresh = stored is not None and stored.input_key == evidence.input_key
    notes = {n.id: n for n in evidence.notes}
    response = render(
        request,
        "assistant/podsumowanie.html",
        title=f"Podsumowanie cyklu · {evidence.subject.full_name}",
        ev=evidence,
        evaluation=evidence.evaluation,
        subject=evidence.subject,
        by_criterion=evidence.by_criterion(),
        unassigned=evidence.unassigned(),
        stats={s.criterion_code: s for s in evidence.stats},
        criterion_name=lambda code: _name(c, code),
        notes=notes,
        drafts=drafts,
        deterministic=GENERATOR,
        rejected=stored.result.rejected if fresh else [],
        outdated=stored is not None and not fresh,
        llm_available=svc.llm.available(TASK),
        error=error,
        point_labels={p: LEVEL_LABELS[scale.partial_points[p]] for p in PARTIAL_POINTS},
    )
    response.status_code = status_code
    return response


def _name(c, code: str) -> str:
    try:
        return c.catalog.get(code).name
    except KeyError:
        return code


@router.get("/podsumowanie/{evaluation_id}")
@html_errors
def podsumowanie(evaluation_id: str, request: Request):
    return _page(request, _evidence_for_user(request, evaluation_id))


@router.post("/podsumowanie/{evaluation_id}/generuj")
@html_errors
def generuj(evaluation_id: str, request: Request):
    evidence = _evidence_for_user(request, evaluation_id)
    c = get_container(request)
    svc = services(c)
    if not svc.llm.available(TASK):
        raise PageError(403, "Asystent LLM jest wyłączony.")
    try:
        svc.drafts.generate(
            evidence,
            llm=svc.llm,
            catalog=c.catalog,
            scale=load_scale(c.settings.regulation_dir),
            pseudonymizer=svc.pseudonymizer(),
        )
    except LLMError as err:
        return _page(request, evidence, error=err.user_message, status_code=502)
    return RedirectResponse(f"/asystent/podsumowanie/{evaluation_id}#projekty", status_code=303)


# --- krótkie sugestie do pól arkusza (panel asystenta obok pola na stronie oceny, moduł A) ---------

MAX_CHARS = 600  # jedna propozycja na pole — cały projekt w jednym, krótkim tekście


def _short(text: str) -> str:
    """Akapit do panelu bocznego — przycięty na granicy zdania albo linii."""
    text = "\n".join(" ".join(line.split()) for line in text.strip().splitlines())
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("\n"))
    return (cut[: end + 1] if end > MAX_CHARS // 2 else cut.rsplit(" ", 1)[0]).rstrip() + " …"


PANEL_FIELDS = {"justification": DraftField.UZASADNIENIE, "iprz": DraftField.WNIOSKI_IPRZ}


def suggestions_payload(c, evidence: CycleEvidence, keys=("justification", "iprz")) -> dict:
    svc = services(c)
    out: dict = {"ok": True}
    for key in keys:
        field = PANEL_FIELDS[key]
        paragraphs, generator, _ = svc.drafts.paragraphs(evidence, field)
        out["generator"] = generator
        if not paragraphs:
            out[key] = []
            continue
        # jedna propozycja na pole: akapity sklejone w jeden tekst, źródła bez powtórzeń
        known = {n.id for n in evidence.notes}
        note_ids = list(dict.fromkeys(nid for p in paragraphs for nid in p.note_ids if nid in known))
        out[key] = [{
            "text": _short("\n\n".join(p.text.strip() for p in paragraphs)),
            "notes": [{"url": f"/asystent/teczka/{evidence.subject.id}?cykl=#{nid}",
                       "label": evidence.note(nid).observed_on.strftime("%d.%m")} for nid in note_ids],
        }]
    return out


@router.post("/podsumowanie/{evaluation_id}/sugestie")
def sugestie(evaluation_id: str, request: Request, pole: str = ""):
    """JSON dla panelu „Asystent HR” przy jednym polu arkusza (`pole` = justification | iprz; bez niego oba):
    generuje projekt LLM tylko tego pola (gdy LLM dostępny), a bez LLM zwraca deterministyczny szkic z notatek."""
    from fastapi.responses import JSONResponse

    if pole and pole not in PANEL_FIELDS:
        return JSONResponse({"ok": False, "error": "Nieznane pole."}, status_code=400)
    keys = (pole,) if pole else tuple(PANEL_FIELDS)

    try:
        evidence = _evidence_for_user(request, evaluation_id)
    except PageError as err:
        return JSONResponse({"ok": False, "error": err.message}, status_code=err.status)
    c = get_container(request)
    svc = services(c)
    if svc.llm.available(TASK):
        try:
            svc.drafts.generate(
                evidence, llm=svc.llm, catalog=c.catalog,
                scale=load_scale(c.settings.regulation_dir), pseudonymizer=svc.pseudonymizer(),
                only={"justification": "justification", "iprz": "development"}[pole] if pole else None,
            )
        except LLMError as err:
            return JSONResponse({"ok": False, "error": err.user_message}, status_code=502)
    return JSONResponse(suggestions_payload(c, evidence, keys))
