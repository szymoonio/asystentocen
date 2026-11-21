"""Próba rozmowy (§ 7.1): LLM gra pracownika według karty postaci, limit wymian, na końcu feedback.

Stan ćwiczenia jest w `asst_roleplays` (właściciel = kierownik). Karta nie zawiera imion ani
danych osobowych, a każda wypowiedź kierownika przechodzi granice z `boundaries.py`
i pseudonimizację przed wysłaniem.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.assistant.hr.boundaries import HrConfig, check
from app.assistant.llm import LLMClient, LLMError, Msg
from app.assistant.llm.prompts import load_prompt
from app.assistant.privacy import Pseudonymizer
from app.contracts.models import Employee
from app.db import Base

TASK = "roleplay"
FEEDBACK_TASK = "roleplay_feedback"
DIFFICULTIES = {"latwa": "łatwa", "srednia": "średnia", "trudna": "trudna"}


class RoleplayRow(Base):
    __tablename__ = "asst_roleplays"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(20), index=True)
    card: Mapped[dict] = mapped_column(JSON)
    # [{"role": "user"|"assistant", "content": tekst wysłany do LLM (po pseudonimizacji), "display": do UI}]
    messages: Mapped[list] = mapped_column(JSON, default=list)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


@dataclass
class Roleplay:
    id: str
    owner_id: str
    card: dict
    messages: list[dict]
    feedback: str | None
    created_at: datetime

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user")


def card_text(card: dict) -> str:
    phrases = "\n".join(f"- {p}" for p in card.get("phrases", []) if p.strip())
    return (
        "## Karta postaci\n"
        f"Kim jesteś: {card.get('persona', '').strip()}\n"
        f"Czego chcesz w tej rozmowie: {card.get('goal', '').strip()}\n"
        f"Twój opór: {card.get('resistance', '').strip()}\n"
        f"Trudność: {DIFFICULTIES.get(card.get('difficulty', 'srednia'), 'średnia')}\n"
        f"Typowe zdania:\n{phrases or '- (brak)'}"
    )


class RoleplayStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def create(self, owner_id: str, card: dict, now: datetime) -> Roleplay:
        row = RoleplayRow(id=f"R-{uuid.uuid4().hex[:10]}", owner_id=owner_id, card=card, messages=[], created_at=now)
        with self._sf.begin() as s:
            s.add(row)
        return self.get(owner_id, row.id)

    def get(self, owner_id: str, roleplay_id: str) -> Roleplay | None:
        with self._sf() as s:
            row = s.get(RoleplayRow, roleplay_id)
            if row is None or row.owner_id != owner_id:
                return None
            return Roleplay(row.id, row.owner_id, dict(row.card), list(row.messages or []), row.feedback, row.created_at)

    def append(self, roleplay_id: str, *messages: dict) -> None:
        with self._sf.begin() as s:
            row = s.get(RoleplayRow, roleplay_id)
            row.messages = [*(row.messages or []), *messages]

    def set_feedback(self, roleplay_id: str, feedback: str) -> None:
        with self._sf.begin() as s:
            s.get(RoleplayRow, roleplay_id).feedback = feedback


class RoleplayError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def reply(
    store: RoleplayStore,
    roleplay: Roleplay,
    text: str,
    *,
    llm: LLMClient,
    hr: HrConfig,
    people: list[Employee],
    pseudonymizer: Pseudonymizer,
) -> Iterator[str]:
    """Strumień odpowiedzi „pracownika”. Wypowiedź kierownika zapisujemy od razu, odpowiedź po końcu strumienia.

    Wyjątki przed rozpoczęciem strumienia (`RoleplayError`) zgłaszamy od razu, żeby widok mógł
    pokazać komunikat zamiast pustej odpowiedzi.
    """
    text = text.strip()
    if not text:
        raise RoleplayError("Napisz, co mówisz pracownikowi.")
    if roleplay.feedback is not None:
        raise RoleplayError("To ćwiczenie jest zakończone.")
    if roleplay.turns >= hr.roleplay_max_turns:
        raise RoleplayError(f"Osiągnięto limit {hr.roleplay_max_turns} wypowiedzi. Zakończ ćwiczenie, żeby dostać informację zwrotną.")
    if boundary := check(text, hr, people):
        raise RoleplayError(f"{boundary.message} " + "; ".join(f"{c.label}: {c.value}" for c in boundary.contacts))

    session = pseudonymizer.session()
    safe = session.apply(text)
    history: list[Msg] = [
        *({"role": m["role"], "content": m["content"]} for m in roleplay.messages),
        {"role": "user", "content": safe},
    ]
    system = f"{load_prompt(TASK).text}\n\n{card_text(roleplay.card)}"
    stream = llm.stream(TASK, system, history)

    def run() -> Iterator[str]:
        parts: list[str] = []
        try:
            for chunk in stream:
                parts.append(chunk)
                yield chunk
        except LLMError as err:
            yield f"\n[{err.user_message}]"
            return
        answer = "".join(parts).strip()
        if answer:
            store.append(
                roleplay.id,
                {"role": "user", "content": safe, "display": text},
                {"role": "assistant", "content": answer, "display": session.restore(answer)},
            )

    return run()


def finish(store: RoleplayStore, roleplay: Roleplay, *, llm: LLMClient) -> str:
    """Informacja zwrotna dla kierownika. Rzuca `LLMError`."""
    if roleplay.feedback is not None:
        return roleplay.feedback
    if not roleplay.messages:
        raise LLMError("pusta rozmowa", user_message="Najpierw przeprowadź choć jedną wymianę zdań.")
    transcript = "\n".join(
        f"{'Kierownik' if m['role'] == 'user' else 'Pracownik'}: {m['content']}" for m in roleplay.messages
    )
    user = f"{card_text(roleplay.card)}\n\n## Zapis rozmowy (dane)\n<rozmowa>\n{transcript}\n</rozmowa>"
    feedback = llm.text(FEEDBACK_TASK, load_prompt(FEEDBACK_TASK).text, [{"role": "user", "content": user}]).strip()
    store.set_feedback(roleplay.id, feedback)
    return feedback
