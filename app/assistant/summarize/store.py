"""Zapis projektów LLM (`asst_drafts`). Projekt jest „świeży”, dopóki nie zmienią się notatki ani oceny.

Generowanie z LLM uruchamia człowiek (przycisk na stronie podsumowania), a formularz oceny
tylko czyta zapisany wynik — dzięki temu wyświetlenie formularza nie kosztuje wywołania API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.assistant.summarize.llm_summary import Rejected, SummaryResult
from app.assistant.summarize.skeleton import Paragraph
from app.db import Base


class DraftRow(Base):
    __tablename__ = "asst_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[str] = mapped_column(String(40), index=True)
    input_key: Mapped[str] = mapped_column(String(40))
    generator: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


@dataclass(frozen=True)
class StoredDraft:
    evaluation_id: str
    input_key: str
    generator: str
    created_at: datetime
    result: SummaryResult


def _paragraphs(items: list[dict]) -> list[Paragraph]:
    return [Paragraph(p["text"], tuple(p["note_ids"])) for p in items]


class DraftStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def save(self, evaluation_id: str, input_key: str, result: SummaryResult, now: datetime) -> None:
        payload = {
            "justification": [{"text": p.text, "note_ids": list(p.note_ids)} for p in result.justification],
            "development": [{"text": p.text, "note_ids": list(p.note_ids)} for p in result.development],
            "rejected": [{"field": r.field, "text": r.text, "reasons": list(r.reasons)} for r in result.rejected],
        }
        with self._sf.begin() as s:
            s.add(
                DraftRow(
                    evaluation_id=evaluation_id,
                    input_key=input_key,
                    generator=result.generator,
                    payload=payload,
                    created_at=now,
                )
            )

    def latest(self, evaluation_id: str) -> StoredDraft | None:
        stmt = select(DraftRow).where(DraftRow.evaluation_id == evaluation_id).order_by(DraftRow.id.desc()).limit(1)
        with self._sf() as s:
            row = s.scalars(stmt).first()
        if row is None:
            return None
        p = row.payload or {}
        result = SummaryResult(
            generator=row.generator,
            justification=_paragraphs(p.get("justification", [])),
            development=_paragraphs(p.get("development", [])),
            rejected=[Rejected(r["field"], r["text"], tuple(r["reasons"])) for r in p.get("rejected", [])],
        )
        return StoredDraft(row.evaluation_id, row.input_key, row.generator, row.created_at, result)
