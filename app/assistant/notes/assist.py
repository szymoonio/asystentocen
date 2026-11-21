"""Notatki z pomocą LLM (§ 5.3).

- `split_note`: opis/transkrypt → propozycja zalet i obszarów do poprawy. Przełożony ją przyjmuje
  albo poprawia w formularzu; nic nie zapisuje się bez jego kliknięcia.
- `classify_note`: w tle, po zapisie, punkty notatki → kryteria. Wynik to tylko podpowiedź
  (`asst_criteria_hints`), nie część notatki. LLM nigdy nie ustawia suwaków.

Przed każdym wywołaniem: detektor danych wrażliwych (trafienie = nie wysyłamy), potem
pseudonimizacja; odpowiedź de-pseudonimizujemy lokalnie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from app.assistant.llm import LLMError, generator_id
from app.assistant.llm.prompts import load_prompt
from app.assistant.privacy import detect, note_text
from app.assistant.services import AssistantServices
from app.contracts.models import Employee, Note
from app.contracts.ports import CriteriaCatalog

log = logging.getLogger("asystent.notes")

SPLIT_TASK = "split_note"
CLASSIFY_TASK = "classify_note"


# --- split_note --------------------------------------------------------------------------


class SplitProposal(BaseModel):
    strengths: list[str] = Field(description="Co poszło dobrze — krótkie punkty.")
    improvements: list[str] = Field(description="Obszary do poprawy — krótkie punkty.")


@dataclass
class SplitOutcome:
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def empty(self) -> bool:
        return not self.strengths and not self.improvements


def _clean(items: list[str], restore) -> list[str]:
    out: list[str] = []
    for item in items:
        text = restore(item).strip().lstrip("-•* ").strip()
        if text and text not in out:
            out.append(text)
    return out


def sensitive_message(text: str) -> str | None:
    hits = detect(text)
    if not hits:
        return None
    labels = ", ".join(sorted({h.label for h in hits}))
    return (
        f"Opis może zawierać dane wrażliwe ({labels}), więc asystent go nie wysłał. "
        "Takie informacje nie powinny być podstawą oceny — usuń je albo rozdziel punkty ręcznie."
    )


def split_note(svc: AssistantServices, subject: Employee, text: str) -> SplitOutcome:
    if not text.strip():
        return SplitOutcome(error="Wpisz opis sytuacji, żeby asystent mógł go podzielić.")
    if blocked := sensitive_message(text):
        return SplitOutcome(error=blocked)
    session = svc.pseudonymizer().session()
    session.label_for(subject)
    prompt = load_prompt(SPLIT_TASK)
    try:
        proposal = svc.llm.structured(SPLIT_TASK, prompt.text, session.apply(text), SplitProposal)
    except LLMError as err:
        return SplitOutcome(error=err.user_message)
    return SplitOutcome(
        strengths=_clean(proposal.strengths, session.restore),
        improvements=_clean(proposal.improvements, session.restore),
    )


# --- classify_note -----------------------------------------------------------------------


class ItemCriteria(BaseModel):
    id: str = Field(description="Identyfikator punktu z wejścia, np. B, S1, I2.")
    criteria: list[str] = Field(description="Kody kryteriów z katalogu, najwyżej dwa.")


class Classification(BaseModel):
    items: list[ItemCriteria]


def catalog_prompt(catalog: CriteriaCatalog) -> str:
    """Katalog 14 kryteriów z zał. 1 — stały, więc może być w (cache'owanym) prompcie systemowym."""
    lines = ["## Katalog kryteriów (zał. 1 do rozporządzenia)"]
    for c in catalog.all():
        lines.append(f"\n### {c.code} — {c.name}")
        lines += [f"- {d}" for d in c.description]
    return "\n".join(lines)


def note_items(note: Note) -> list[tuple[str, str, str]]:
    """(id, rodzaj, tekst) — punkty notatki do klasyfikacji."""
    items: list[tuple[str, str, str]] = []
    if note.body.strip():
        items.append(("B", "body", note.body.strip()))
    items += [(f"S{i}", "strength", s) for i, s in enumerate(note.strengths, 1)]
    items += [(f"I{i}", "improvement", s) for i, s in enumerate(note.improvements, 1)]
    return items


def classify_note(
    svc: AssistantServices, catalog: CriteriaCatalog, note: Note, subject: Employee, now: datetime
) -> list[dict] | None:
    """Zapisuje podpowiedź kryteriów dla notatki. Zwraca zapisane wpisy albo None, gdy pominięto."""
    if not svc.llm.available(CLASSIFY_TASK):
        return None
    if detect(note_text(note)):
        log.info("classify_note: notatka %s pominięta (dane wrażliwe)", note.id)
        return None
    items = note_items(note)
    if not items:
        return None
    session = svc.pseudonymizer().session()
    session.label_for(subject)
    user = "\n".join(f"{item_id}: {session.apply(text)}" for item_id, _, text in items)
    prompt = load_prompt(CLASSIFY_TASK)
    system = f"{prompt.text}\n\n{catalog_prompt(catalog)}"
    try:
        result = svc.llm.structured(CLASSIFY_TASK, system, user, Classification)
    except LLMError as err:
        log.warning("classify_note %s: %s", note.id, err)
        return None

    valid = {c.code for c in catalog.all()}
    by_id = {item_id: (kind, text) for item_id, kind, text in items}
    hints: list[dict] = []
    for entry in result.items:
        if entry.id not in by_id:
            continue
        kind, text = by_id[entry.id]
        for code in [c for c in entry.criteria if c in valid][:2]:
            hints.append({"item": text, "kind": kind, "criterion_code": code})
    svc.notes_repo.save_hints(note.id, hints, generator_id(svc.llm, CLASSIFY_TASK, prompt.version), now)
    return hints
