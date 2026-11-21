"""Notatka → informacja zwrotna w modelu FUKO (§ 7.1, § 7.3)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.assistant.hr.boundaries import BoundaryHit, HrConfig, check
from app.assistant.llm import LLMClient, LLMError
from app.assistant.llm.prompts import load_prompt
from app.assistant.notes.assist import sensitive_message
from app.assistant.privacy import Pseudonymizer
from app.contracts.models import Employee

TASK = "rewrite_feedback"


class OpinionRewrite(BaseModel):
    opinion: str = Field(description="Sformułowanie z notatki będące opinią lub uogólnieniem.")
    fact_based: str = Field(description="Propozycja opisu zachowania i skutku.")


class Fuko(BaseModel):
    facts: str
    feelings: str
    consequences: str
    expectations: str
    ready_text: str
    opinions: list[OpinionRewrite]


@dataclass
class FukoOutcome:
    fuko: Fuko | None = None
    error: str | None = None
    boundary: BoundaryHit | None = None


def rewrite(
    text: str,
    *,
    llm: LLMClient,
    hr: HrConfig,
    people: list[Employee],
    pseudonymizer: Pseudonymizer,
    subject: Employee | None = None,
) -> FukoOutcome:
    if not text.strip():
        return FukoOutcome(error="Wpisz albo wybierz notatkę.")
    if boundary := check(text, hr, people):
        return FukoOutcome(boundary=boundary)
    if blocked := sensitive_message(text):
        return FukoOutcome(error=blocked)
    session = pseudonymizer.session()
    if subject is not None:
        session.label_for(subject)
    try:
        result = llm.structured(TASK, load_prompt(TASK).text, f"<notatka>\n{session.apply(text.strip())}\n</notatka>", Fuko)
    except LLMError as err:
        return FukoOutcome(error=err.user_message)
    r = session.restore
    return FukoOutcome(
        fuko=Fuko(
            facts=r(result.facts),
            feelings=r(result.feelings),
            consequences=r(result.consequences),
            expectations=r(result.expectations),
            ready_text=r(result.ready_text),
            opinions=[OpinionRewrite(opinion=r(o.opinion), fact_based=r(o.fact_based)) for o in result.opinions],
        )
    )
