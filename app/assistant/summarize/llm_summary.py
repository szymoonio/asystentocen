"""Projekt uzasadnienia i IPRZ z LLM (§ 6.2).

Pipeline: (notatki już po detektorze wrażliwych) → pseudonimizacja → jedno wywołanie
structured (akapity z `note_refs`) → walidator cytowań → de-pseudonimizacja lokalnie.
Przypisanie punktów do kryteriów bierzemy z `criteria_hint` (§ 5.3), jeśli jest.
Model nie dostaje ani nie zwraca liczb punktowych — wpisane oceny cząstkowe idą słownie.

Uproszczenie prototypu: jedno wywołanie zamiast map/reduce; 24 miesiące notatek jednej
osoby mieszczą się w kontekście modelu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.assistant.llm import LLMClient, LLMError, generator_id
from app.assistant.llm.prompts import load_prompt
from app.assistant.notes.assist import catalog_prompt
from app.assistant.privacy import Pseudonymizer
from app.assistant.summarize.evidence import CycleEvidence
from app.assistant.summarize.skeleton import Paragraph
from app.assistant.summarize.validate import validate_paragraph
from app.contracts.enums import LEVEL_LABELS
from app.contracts.ports import CriteriaCatalog
from app.contracts.regulation import Scale

TASK = "summarize_cycle"


class DraftParagraph(BaseModel):
    text: str = Field(description="Akapit projektu tekstu.")
    note_refs: list[str] = Field(description="Identyfikatory notatek źródłowych, np. N3.")


class CycleSummary(BaseModel):
    justification: list[DraftParagraph]
    development: list[DraftParagraph]


@dataclass(frozen=True)
class Rejected:
    field: str  # justification | development
    text: str
    reasons: tuple[str, ...]


@dataclass
class SummaryResult:
    generator: str
    justification: list[Paragraph] = field(default_factory=list)
    development: list[Paragraph] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)


def _pl(d) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def build_request(
    evidence: CycleEvidence,
    *,
    catalog: CriteriaCatalog,
    scale: Scale,
    actions: dict[str, list[str]],
    pseudonymizer: Pseudonymizer,
) -> tuple[str, str, dict[str, str], dict[str, str], object]:
    """Zwraca (system, user, alias→note_id, alias→tekst źródłowy, sesja pseudonimizacji)."""
    session = pseudonymizer.session()
    session.label_for(evidence.subject)
    ev = evidence.evaluation
    names = {c.code: c.name for c in evidence.criteria}

    lines = [
        f"Osoba oceniana: {session.label_for(evidence.subject)}. Arkusz {ev.sheet.value}.",
        f"Okres oceny: {_pl(ev.period_from)} – {_pl(ev.due_date)}.",
        "Kryteria tej oceny: " + "; ".join(f"{c.code} ({c.name})" for c in evidence.criteria) + ".",
    ]
    if ev.result:
        rated = [
            f"{names.get(code, code)}: {LEVEL_LABELS[scale.partial_points[value]]}"
            for code, value in ev.result.partial_points.items()
        ]
        lines.append("Oceny cząstkowe wpisane przez oceniającego: " + "; ".join(rated) + ".")
    else:
        lines.append("Oceny cząstkowe nie są jeszcze wpisane — opisz to, co wynika z notatek.")
    directions = [f"{names.get(code, code)}: {'; '.join(actions.get(code, []))}" for code in evidence.low_criteria]
    lines.append("Kierunki z katalogu działań rozwojowych: " + (" | ".join(directions) if directions else "brak") + ".")
    if evidence.excluded:
        lines.append(f"Pominięto {len(evidence.excluded)} notatki z danymi wrażliwymi — nie odwołuj się do nich.")

    aliases: dict[str, str] = {}
    sources: dict[str, str] = {}
    items_by_note: dict[str, list] = {}
    for item in evidence.items:
        items_by_note.setdefault(item.note_id, []).append(item)
    lines.append("\nNotatki:")
    for i, note in enumerate(evidence.notes, 1):
        alias = f"N{i}"
        aliases[alias] = note.id
        body = [f'<notatka id="{alias}" data="{_pl(note.observed_on)}">']
        content = [_pl(note.observed_on)]  # do walidatora: sama treść i data, bez identyfikatorów
        for item in items_by_note.get(note.id, []):
            text = session.apply(item.text)
            content.append(text)
            hint = f"  [kryteria: {', '.join(item.criteria)}]" if item.criteria else ""
            body.append(f"{item.item_id}: {text}{hint}")
        if note.ratings:
            sliders = ", ".join(
                f"{names.get(r.criterion_code, r.criterion_code)} — {LEVEL_LABELS[scale.partial_points[r.value]]}"
                for r in note.ratings
            )
            body.append(f"Suwaki w tej sytuacji: {sliders}")
        body.append("</notatka>")
        sources[alias] = "\n".join(content)
        lines += body

    prompt = load_prompt(TASK)
    system = f"{prompt.text}\n\n{catalog_prompt(catalog)}"
    return system, "\n".join(lines), aliases, sources, session


def summarize(
    evidence: CycleEvidence,
    *,
    llm: LLMClient,
    catalog: CriteriaCatalog,
    scale: Scale,
    actions: dict[str, list[str]],
    pseudonymizer: Pseudonymizer,
    only: str | None = None,
) -> SummaryResult:
    """Rzuca `LLMError` (z `user_message`), gdy wywołanie się nie uda.

    `only` = "justification" albo "development": model przygotowuje tylko to jedno pole
    (przycisk asystenta przy konkretnym polu arkusza)."""
    if not evidence.notes:
        raise LLMError("brak notatek", user_message="W tym cyklu nie ma notatek, z których asystent mógłby skorzystać.")
    system, user, aliases, sources, session = build_request(
        evidence, catalog=catalog, scale=scale, actions=actions, pseudonymizer=pseudonymizer
    )
    if only:
        other = "development" if only == "justification" else "justification"
        user += (f"\n\nTym razem przygotuj TYLKO pole `{only}`, jako JEDEN zwięzły akapit (2–4 zdania). "
                 f"Pole `{other}` zwróć jako pustą listę.")
    output = llm.structured(TASK, system, user, CycleSummary)
    subject_label = session.label_for(evidence.subject)
    result = SummaryResult(generator=generator_id(llm, TASK, load_prompt(TASK).version))
    for field_name, paragraphs in (("justification", output.justification), ("development", output.development)):
        if only and field_name != only:
            continue
        for p in paragraphs:
            verdict = validate_paragraph(p.text, p.note_refs, sources, subject_label=subject_label)
            if not verdict.ok:
                result.rejected.append(Rejected(field_name, session.restore(p.text), verdict.reasons))
                continue
            note_ids = tuple(aliases[r] for r in dict.fromkeys(p.note_refs))
            getattr(result, field_name).append(Paragraph(session.restore(p.text.strip()), note_ids))
    return result
