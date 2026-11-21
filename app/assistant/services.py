"""Usługi modułu B, których nie ma w (zamrożonym) kontenerze."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.assistant.config import NudgesConfig
    from app.assistant.notes.repository import NotesRepository
    from app.assistant.nudges.provider import NoteNudges
    from app.assistant.nudges.snooze import SnoozeRepository
    from app.container import Container

_ATTR = "_assistant_services"


@dataclass
class AssistantServices:
    notes_repo: NotesRepository
    nudges: NudgesConfig
    snoozes: SnoozeRepository
    note_nudges: NoteNudges


def attach(c: Container, svc: AssistantServices) -> None:
    # Nie dopisujemy pola do zamrożonej klasy Container — usługi są atrybutem instancji.
    setattr(c, _ATTR, svc)


def services(c: Container) -> AssistantServices:
    return getattr(c, _ATTR)
