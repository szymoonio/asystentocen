"""Przygotowanie do rozmowy (§ 7.1, § 7.3): checklista z przepisów (deterministyczna) + podpowiedzi LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.assistant.hr.boundaries import BoundaryHit, HrConfig, check
from app.assistant.llm import LLMClient, LLMError
from app.assistant.llm.prompts import load_prompt
from app.assistant.privacy import PseudonymSession, Pseudonymizer, screen_notes
from app.contracts.models import Employee, Note

TASK = "conversation_prep"

KINDS = {
    "trudna": "Trudna rozmowa (np. problem z jakością pracy lub zachowaniem)",
    "oceniajaca": "Rozmowa oceniająca (§ 10 rozporządzenia)",
    "rozpoczynajaca": "Rozmowa rozpoczynająca okres oceny (§ 5 rozporządzenia)",
    "informacja": "Bieżąca informacja zwrotna (pochwała lub uwaga)",
    "powrot": "Rozmowa po powrocie z dłuższej nieobecności",
}

# Checklisty z przepisów — działają bez LLM.
CHECKLISTS: dict[str, tuple[str, list[str]]] = {
    "oceniajaca": (
        "§ 10 rozporządzenia — omów z ocenianym:",
        [
            "główne obowiązki w okresie oceny i sposób ich realizacji, z uwzględnieniem ustalonych kryteriów",
            "sposób realizacji celów, jeśli zostały wyznaczone",
            "kierunki dalszego rozwoju zawodowego i potrzeby w zakresie podnoszenia kwalifikacji (→ wnioski IPRZ)",
            "przygotuj fakty z całego okresu, nie tylko z ostatnich tygodni (notatki, podsumowanie cyklu)",
        ],
    ),
    "rozpoczynajaca": (
        "§ 5 rozporządzenia — omów z ocenianym:",
        [
            "główne obowiązki wynikające z opisu stanowiska",
            "kryteria obowiązkowe i — jeśli wybierasz — najwyżej 3 kryteria dodatkowe",
            "Twoje oczekiwania co do sposobu spełniania kryteriów",
            "cele na okres oceny (jeśli uzasadnione) i sposób ich realizacji",
            "po rozmowie: wpisz kryteria dodatkowe i termin oceny w części I arkusza; oceniany potwierdza zapoznanie (§ 6)",
        ],
    ),
    "trudna": (
        "Przed trudną rozmową:",
        [
            "spisz 2–3 konkretne fakty (kiedy, co, jaki skutek) — bez ocen osoby",
            "ustal jedno najważniejsze oczekiwanie na przyszłość",
            "zaplanuj spokojne miejsce i czas bez pośpiechu",
            "nie pytaj o zdrowie ani sprawy prywatne",
            "na koniec ustal konkretny następny krok i termin ponownej rozmowy",
        ],
    ),
    "informacja": (
        "Informacja zwrotna w modelu FUKO:",
        ["Fakty", "Uczucia (Twoje odczucia, w 1. osobie)", "Konsekwencje dla zadania lub zespołu", "Oczekiwania na przyszłość"],
    ),
    "powrot": (
        "Rozmowa po powrocie:",
        [
            "nie pytaj o przyczynę nieobecności",
            "co się zmieniło w zespole i zadaniach",
            "priorytety na najbliższe tygodnie i ewentualne odciążenie na start",
            "czy pracownik czegoś potrzebuje do pracy",
        ],
    ),
}


class Reaction(BaseModel):
    reaction: str
    response: str


class RoleplayCard(BaseModel):
    persona: str = Field(description="Kim jest pracownik w tej sytuacji (bez imienia).")
    goal: str = Field(description="Czego chce w rozmowie.")
    resistance: str = Field(description="Na czym polega jego opór.")
    phrases: list[str] = Field(description="3 typowe zdania pracownika.")


class PrepPlan(BaseModel):
    goal: str
    opening: str
    questions: list[str]
    reactions: list[Reaction]
    avoid: list[str]
    roleplay: RoleplayCard


@dataclass
class PrepOutcome:
    plan: PrepPlan | None = None
    error: str | None = None
    boundary: BoundaryHit | None = None
    excluded_notes: int = 0
    used_notes: int = 0
    notices: list[str] = field(default_factory=list)


def _restore_plan(plan: PrepPlan, session: PseudonymSession) -> PrepPlan:
    r = session.restore
    return PrepPlan(
        goal=r(plan.goal),
        opening=r(plan.opening),
        questions=[r(q) for q in plan.questions],
        reactions=[Reaction(reaction=r(x.reaction), response=r(x.response)) for x in plan.reactions],
        avoid=[r(a) for a in plan.avoid],
        roleplay=plan.roleplay,  # karta bez osób — nie de-pseudonimizujemy
    )


def prepare(
    *,
    kind: str,
    situation: str,
    llm: LLMClient,
    hr: HrConfig,
    people: list[Employee],
    pseudonymizer: Pseudonymizer,
    subject: Employee | None = None,
    notes: list[Note] | None = None,
) -> PrepOutcome:
    if boundary := check(situation, hr, people):
        return PrepOutcome(boundary=boundary)
    session = pseudonymizer.session()
    if subject is not None:
        session.label_for(subject)
    lines = [f"Rodzaj rozmowy: {KINDS.get(kind, kind)}.", "", "Opis sytuacji od kierownika:", session.apply(situation.strip())]
    outcome = PrepOutcome()
    if notes:
        screened = screen_notes(notes)
        outcome.excluded_notes = len(screened.excluded)
        outcome.used_notes = len(screened.included)
        if screened.included:
            lines += ["", "Punkty z notatek kierownika (dane):", "<notatki>"]
            for n in screened.included[-12:]:
                pts = [*(f"+ {s}" for s in n.strengths), *(f"- {s}" for s in n.improvements)] or [n.body]
                lines += [f"{n.observed_on.strftime('%d.%m.%Y')}: " + " | ".join(session.apply(p) for p in pts)]
            lines.append("</notatki>")
    try:
        plan = llm.structured(TASK, load_prompt(TASK).text, "\n".join(lines), PrepPlan)
    except LLMError as err:
        outcome.error = err.user_message
        return outcome
    outcome.plan = _restore_plan(plan, session)
    return outcome
