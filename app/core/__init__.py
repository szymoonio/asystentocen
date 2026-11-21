"""Moduł CORE — agent A. Proces oceny, terminy, formularze A/B/C, dane kadrowe, przypomnienia.

Kontrakt z resztą aplikacji (nie zmieniać nazw):
    router                      — APIRouter montowany pod /core
    register(c: Container)      — podmienia porty A na prawdziwe implementacje,
                                  rejestruje ReminderProvider-y i importuje modele bazy.

Zakres i definicja ukończenia: docs/AGENT_A.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.api import router

if TYPE_CHECKING:
    from app.container import Container

__all__ = ["register", "router"]


def register(c: Container) -> None:
    # Krok 0: nic nie podmieniamy — działają fake'i z app/contracts/fakes.py.
    # Agent A docelowo:
    #   from app.core import models  # noqa: F401  (tabele core_*)
    #   c.employees = DbEmployeeDirectory(c.session_factory)
    #   c.evaluations = DbEvaluationReader(c.session_factory, c.catalog)
    #   c.reminder_sink = DbReminderSink(c.session_factory)
    #   c.reminder_providers.append(ProcessReminders(c))
    return None
