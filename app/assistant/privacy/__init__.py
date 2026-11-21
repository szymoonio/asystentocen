"""Prywatność przed każdym wywołaniem LLM (§ 6.3): wykluczenie wrażliwych → pseudonimizacja."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.assistant.privacy.pseudonymize import Pseudonymizer, PseudonymSession, name_forms
from app.assistant.privacy.sensitive import SensitiveHit, detect, is_sensitive, warning
from app.contracts.models import Note

__all__ = [
    "ExcludedNote",
    "PseudonymSession",
    "Pseudonymizer",
    "ScreenResult",
    "SensitiveHit",
    "detect",
    "is_sensitive",
    "name_forms",
    "note_text",
    "screen_notes",
    "warning",
]


def note_text(note: Note) -> str:
    return "\n".join([note.body, *note.strengths, *note.improvements])


@dataclass(frozen=True)
class ExcludedNote:
    note: Note
    hits: list[SensitiveHit]

    @property
    def warning(self) -> str:
        return warning(self.hits)


@dataclass
class ScreenResult:
    included: list[Note] = field(default_factory=list)
    excluded: list[ExcludedNote] = field(default_factory=list)


def screen_notes(notes: Sequence[Note]) -> ScreenResult:
    """Dzieli notatki na bezpieczne do wysłania i wykluczone (z ostrzeżeniem dla przełożonego)."""
    result = ScreenResult()
    for note in notes:
        hits = detect(note_text(note))
        if hits:
            result.excluded.append(ExcludedNote(note, hits))
        else:
            result.included.append(note)
    return result
