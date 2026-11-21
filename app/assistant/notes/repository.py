"""Zapis i odczyt notatek. Każda operacja jest w imieniu autora — cudzych notatek nie ma jak pobrać."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import aliased, sessionmaker

from app.assistant.notes.models import CriteriaHintRow, NoteRow
from app.contracts.enums import NoteSource
from app.contracts.models import CriterionRating, Note


class NoteNotFound(LookupError):
    """Brak notatki albo notatka innego autora (celowo nie rozróżniamy)."""


class NoteAlreadyRevised(ValueError):
    """Próba edycji wersji, która ma już następczynię."""


@dataclass
class NoteInput:
    """Treść notatki z formularza (przed nadaniem ID i wersji)."""

    observed_on: date
    body: str = ""
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    ratings: list[CriterionRating] = field(default_factory=list)
    source: NoteSource = NoteSource.TEXT

    def is_empty(self) -> bool:
        return not (self.body.strip() or self.strengths or self.improvements)


def _to_model(row: NoteRow) -> Note:
    return Note(
        id=row.id,
        author_id=row.author_id,
        subject_id=row.subject_id,
        evaluation_id=row.evaluation_id,
        observed_on=row.observed_on,
        created_at=row.created_at,
        source=NoteSource(row.source),
        body=row.body or "",
        strengths=list(row.strengths or []),
        improvements=list(row.improvements or []),
        ratings=[CriterionRating(**r) for r in row.ratings or []],
        version=row.version,
        supersedes_id=row.supersedes_id,
    )


def _row_from_model(note: Note) -> NoteRow:
    return NoteRow(
        id=note.id,
        author_id=note.author_id,
        subject_id=note.subject_id,
        evaluation_id=note.evaluation_id,
        observed_on=note.observed_on,
        created_at=note.created_at,
        source=note.source.value,
        body=note.body,
        strengths=list(note.strengths),
        improvements=list(note.improvements),
        ratings=[r.model_dump() for r in note.ratings],
        version=note.version,
        supersedes_id=note.supersedes_id,
    )


def new_note_id() -> str:
    return f"N-{uuid.uuid4().hex[:10]}"


class NotesRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    # --- odczyt -----------------------------------------------------------------------

    def current(self, author_id: str, subject_id: str | None = None) -> list[Note]:
        """Bieżące wersje notatek autora (opcjonalnie o jednej osobie), chronologicznie."""
        newer = aliased(NoteRow)
        stmt = (
            select(NoteRow)
            .where(NoteRow.author_id == author_id)
            .where(~select(newer.id).where(newer.supersedes_id == NoteRow.id).exists())
            .order_by(NoteRow.observed_on, NoteRow.created_at)
        )
        if subject_id is not None:
            stmt = stmt.where(NoteRow.subject_id == subject_id)
        with self._sf() as s:
            return [_to_model(r) for r in s.scalars(stmt)]

    def get(self, author_id: str, note_id: str) -> Note:
        with self._sf() as s:
            row = s.get(NoteRow, note_id)
            if row is None or row.author_id != author_id:
                raise NoteNotFound(note_id)
            return _to_model(row)

    def history(self, author_id: str, note_id: str) -> list[Note]:
        """Wszystkie wersje notatki, od najnowszej do pierwszej."""
        chain: list[Note] = []
        current: str | None = note_id
        while current:
            note = self.get(author_id, current)
            chain.append(note)
            current = note.supersedes_id
        return chain

    def is_current(self, note_id: str) -> bool:
        with self._sf() as s:
            return s.scalar(select(func.count()).where(NoteRow.supersedes_id == note_id)) == 0

    # --- zapis ------------------------------------------------------------------------

    def create(
        self, *, author_id: str, subject_id: str, evaluation_id: str | None, data: NoteInput, now: datetime
    ) -> Note:
        note = Note(
            id=new_note_id(),
            author_id=author_id,
            subject_id=subject_id,
            evaluation_id=evaluation_id,
            observed_on=data.observed_on,
            created_at=now,
            source=data.source,
            body=data.body.strip(),
            strengths=data.strengths,
            improvements=data.improvements,
            ratings=data.ratings,
        )
        with self._sf.begin() as s:
            s.add(_row_from_model(note))
        return note

    def revise(self, *, author_id: str, note_id: str, data: NoteInput, now: datetime) -> Note:
        """Edycja = nowa wersja. Poprzednia zostaje w bazie i w historii notatki."""
        previous = self.get(author_id, note_id)
        if not self.is_current(note_id):
            raise NoteAlreadyRevised(note_id)
        note = previous.model_copy(
            update={
                "id": new_note_id(),
                "observed_on": data.observed_on,
                "created_at": now,
                "body": data.body.strip(),
                "strengths": data.strengths,
                "improvements": data.improvements,
                "ratings": data.ratings,
                "version": previous.version + 1,
                "supersedes_id": previous.id,
            }
        )
        with self._sf.begin() as s:
            s.add(_row_from_model(note))
        return note

    # --- podpowiedzi kryteriów (LLM) ------------------------------------------------------

    def save_hints(self, note_id: str, hints: list[dict], generator: str, now: datetime) -> None:
        with self._sf.begin() as s:
            s.add(CriteriaHintRow(note_id=note_id, hints=list(hints), generator=generator, created_at=now))

    def hints_for(self, note_ids: Iterable[str]) -> dict[str, list[dict]]:
        """Najnowsza podpowiedź dla każdej notatki (brak wpisu = notatka niesklasyfikowana)."""
        ids = list(note_ids)
        if not ids:
            return {}
        stmt = select(CriteriaHintRow).where(CriteriaHintRow.note_id.in_(ids)).order_by(CriteriaHintRow.id)
        with self._sf() as s:
            return {row.note_id: list(row.hints or []) for row in s.scalars(stmt)}

    # --- seed -------------------------------------------------------------------------

    def is_empty(self) -> bool:
        with self._sf() as s:
            return s.scalar(select(func.count()).select_from(NoteRow)) == 0

    def import_notes(self, notes: Iterable[Note]) -> int:
        rows = [_row_from_model(n) for n in notes]
        with self._sf.begin() as s:
            s.add_all(rows)
        return len(rows)


def import_seed_if_empty(repo: NotesRepository, notes: Iterable[Note]) -> int:
    if not repo.is_empty():
        return 0
    return repo.import_notes(notes)
