"""Pytania o procedury (§ 7.1): odpowiedź tylko z fragmentów przepisów, zawsze z paragrafem.

Wyszukiwanie fragmentów jest deterministyczne; LLM tylko formułuje odpowiedź z podanych
fragmentów. Cytaty sprawdzamy: odpowiedź bez poprawnego źródła zastępujemy stałym
„zapytaj kadry”.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.assistant.hr.boundaries import BoundaryHit, HrConfig, check, hr_contacts
from app.assistant.hr.knowledge import Chunk, KnowledgeBase
from app.assistant.llm import LLMClient, LLMError
from app.assistant.llm.prompts import load_prompt
from app.assistant.privacy import Pseudonymizer
from app.contracts.models import Employee

TASK = "procedure_qa"
TOP_K = 8


class QaAnswer(BaseModel):
    answer: str
    sources: list[str] = Field(description="Identyfikatory fragmentów, np. K12.")
    found: bool


@dataclass
class QaOutcome:
    question: str
    fragments: list[Chunk] = field(default_factory=list)  # wynik wyszukiwania (pokazywany też bez LLM)
    answer: str | None = None
    sources: list[Chunk] = field(default_factory=list)
    not_found: str | None = None
    error: str | None = None
    boundary: BoundaryHit | None = None


def not_found_message(people: list[Employee]) -> str:
    who = "; ".join(f"{c.label} ({c.value})" for c in hr_contacts(people)) or "Wydział Kadr"
    return f"Nie znalazłem podstawy w przepisach ani w Poradniku KPRM. Zapytaj kadry: {who}."


def answer(
    question: str,
    *,
    kb: KnowledgeBase,
    llm: LLMClient,
    hr: HrConfig,
    people: list[Employee],
    pseudonymizer: Pseudonymizer,
) -> QaOutcome:
    question = question.strip()
    outcome = QaOutcome(question=question)
    if not question:
        outcome.error = "Wpisz pytanie."
        return outcome
    if boundary := check(question, hr, people):
        outcome.boundary = boundary
        return outcome
    outcome.fragments = kb.search(question, TOP_K)
    if not llm.available(TASK):
        return outcome  # same fragmenty
    if not outcome.fragments:
        outcome.not_found = not_found_message(people)
        return outcome
    session = pseudonymizer.session()
    context = "\n\n".join(f'<fragment id="{c.id}" zrodlo="{c.label}">\n{c.text}\n</fragment>' for c in outcome.fragments)
    user = f"Pytanie kierownika: {session.apply(question)}\n\nFragmenty źródeł:\n{context}"
    try:
        result = llm.structured(TASK, load_prompt(TASK).text, user, QaAnswer)
    except LLMError as err:
        outcome.error = err.user_message
        return outcome
    allowed = {c.id: c for c in outcome.fragments}
    sources = [allowed[s] for s in dict.fromkeys(result.sources) if s in allowed]
    if not result.found or not sources:
        outcome.not_found = not_found_message(people)
        return outcome
    outcome.answer = session.restore(result.answer.strip())
    outcome.sources = sources
    return outcome
