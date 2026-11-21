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
