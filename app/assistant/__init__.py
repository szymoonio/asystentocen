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
    # Krok 0: nic nie podmieniamy — działają fake'i z app/contracts/fakes.py.
    # Agent B docelowo:
    #   from app.assistant import models  # noqa: F401  (tabele asst_*)
    #   c.notes = DbNotesReader(c.session_factory)
    #   c.drafts = AssistantDraftProvider(c)
    #   c.reminder_providers.append(NoteNudges(c))
    return None
