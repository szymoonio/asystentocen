"""Moduł ASSISTANT — agent B. Teczka (notatki), przypomnienia o notatkach, LLM, HR partner.

Kontrakt z resztą aplikacji (nie zmieniać nazw):
    router                      — APIRouter montowany pod /asystent
    register(c: Container)      — podmienia porty B na prawdziwe implementacje,
                                  rejestruje ReminderProvider-y i importuje modele bazy.

Zakres i definicja ukończenia: docs/AGENT_B.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.assistant.api import router

if TYPE_CHECKING:
    from app.container import Container

__all__ = ["register", "router"]


def register(c: Container) -> None:
    from app.assistant.config import NudgesConfig
    from app.assistant.notes import models
    from app.assistant.notes.reader import DbNotesReader
    from app.assistant.notes.repository import NotesRepository, import_seed_if_empty
    from app.assistant.services import AssistantServices, attach

    # Tabele asst_* zakładamy od razu (create_all w kontenerze jest dopiero po register),
    # bo przy pustej bazie importujemy notatki z seedu.
    models.Base.metadata.create_all(c.engine, tables=[models.NoteRow.__table__, models.CriteriaHintRow.__table__])
    repo = NotesRepository(c.session_factory)
    import_seed_if_empty(repo, c.seed.notes)

    attach(c, AssistantServices(notes_repo=repo, nudges=NudgesConfig.load(c.settings.config_dir)))
    c.notes = DbNotesReader(repo, lambda: c.evaluations, c.catalog)
    # Kolejne kroki (docs/AGENT_B.md):
    #   c.drafts = AssistantDraftProvider(c)
    #   c.reminder_providers.append(NoteNudges(c))
