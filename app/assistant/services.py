"""Usługi modułu B, których nie ma w (zamrożonym) kontenerze."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.assistant.analysis.store import AnalysisStore
    from app.assistant.config import NudgesConfig
    from app.assistant.hr.boundaries import HrConfig
    from app.assistant.hr.knowledge import KnowledgeBase
    from app.assistant.hr.roleplay import RoleplayStore
    from app.assistant.llm import LLMClient, LLMConfig
    from app.assistant.notes.repository import NotesRepository
    from app.assistant.nudges.provider import NoteNudges
    from app.assistant.nudges.snooze import SnoozeRepository
    from app.assistant.privacy import Pseudonymizer
    from app.assistant.stt import SttConfig, Transcriber
    from app.assistant.summarize.provider import AssistantDraftProvider
    from app.container import Container

_ATTR = "_assistant_services"


@dataclass
class AssistantServices:
    notes_repo: NotesRepository
    nudges: NudgesConfig
    snoozes: SnoozeRepository
    note_nudges: NoteNudges
    llm_config: LLMConfig
    llm: LLMClient  # w testach podmieniany na fake — testy nie wołają sieci
    pseudonymizer: Callable[[], Pseudonymizer]  # budowany na bieżąco z c.employees.all()
    drafts: AssistantDraftProvider
    hr: HrConfig
    roleplays: RoleplayStore
    knowledge: Callable[[], KnowledgeBase]  # leniwie — baza wiedzy ładowana przy pierwszym pytaniu
    stt_config: SttConfig
    stt: Transcriber  # w testach podmieniany na fake
    analyses: AnalysisStore | None = None  # zakładka Analiza (zapis wyników LLM)


def attach(c: Container, svc: AssistantServices) -> None:
    # Nie dopisujemy pola do zamrożonej klasy Container — usługi są atrybutem instancji.
    setattr(c, _ATTR, svc)


def services(c: Container) -> AssistantServices:
    return getattr(c, _ATTR)
