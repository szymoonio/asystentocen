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
    from app.core import models  # noqa: F401 — rejestruje tabele core_* w Base.metadata
    from app.core.reminders import ProcessReminders
    from app.core.repo import DbEmployeeDirectory, DbEvaluationReader, DbReminderSink, import_seed
    from app.db import Base

    core_tables = [t for name, t in Base.metadata.tables.items() if name.startswith("core_")]
    Base.metadata.create_all(c.engine, tables=core_tables)
    import_seed(c.session_factory, c.seed)

    c.employees = DbEmployeeDirectory(c.session_factory)
    c.evaluations = DbEvaluationReader(c.session_factory, c.catalog)
    c.reminder_sink = DbReminderSink(c.session_factory, c.clock)
    c.reminder_providers.append(ProcessReminders(c))
