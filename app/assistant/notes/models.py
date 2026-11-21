"""Tabele teczki (prefiks `asst_`). Mapowane na `app.contracts.models.Note` na granicy portu.

Edycja notatki NIE nadpisuje wiersza: powstaje nowa wersja z `supersedes_id` wskazującym
poprzednią (docs/ARCHITEKTURA.md § 4, B1). „Bieżąca” notatka to wersja, której nikt nie zastępuje.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NoteRow(Base):
    __tablename__ = "asst_notes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    author_id: Mapped[str] = mapped_column(String(20), index=True)
    subject_id: Mapped[str] = mapped_column(String(20), index=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    observed_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(10), default="TEXT")
    body: Mapped[str] = mapped_column(Text, default="")
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    improvements: Mapped[list] = mapped_column(JSON, default=list)
    # [{"criterion_code": "...", "value": 1|3|5|7|9}, ...]
    ratings: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("asst_notes.id"), nullable=True, unique=True
    )


class CriteriaHintRow(Base):
    """Przypisanie punktów notatki do kryteriów przez LLM (§ 5.3). Osobno od notatki — to tylko podpowiedź."""

    __tablename__ = "asst_criteria_hints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    note_id: Mapped[str] = mapped_column(String(40), ForeignKey("asst_notes.id"), index=True)
    # [{"item": "tekst punktu", "kind": "strength|improvement|body", "criterion_code": "..."}, ...]
    hints: Mapped[list] = mapped_column(JSON, default=list)
    generator: Mapped[str] = mapped_column(String(120))  # np. "claude-opus-5-5:classify_note:v1"
    created_at: Mapped[datetime] = mapped_column(DateTime)
