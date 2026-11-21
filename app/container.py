"""Kontener zależności. ZAMROŻONE (krok 0).

Kolejność składania:
  1. domyślnie wszystkie porty = fake'i z app/contracts/fakes.py (dane z seed/),
  2. `app.core.register(c)`      — agent A podmienia swoje porty na prawdziwe,
  3. `app.assistant.register(c)` — agent B podmienia swoje porty na prawdziwe.

Dzięki temu po merge'u nie trzeba zmieniać tego pliku ani main.py: każdy moduł sam
„wkłada” swoje implementacje, a brakujące zostają fake'ami.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.clock import Clock
from app.contracts.fakes import (
    CollectingReminderSink,
    FakeEmployeeDirectory,
    FakeEvaluationReader,
    FakeNotesReader,
    NullDraftProvider,
    Seed,
    load_seed,
)
from app.contracts.ports import (
    CriteriaCatalog,
    DraftProvider,
    EmployeeDirectory,
    EvaluationReader,
    NotesReader,
    ReminderProvider,
    ReminderSink,
)
from app.contracts.regulation import YamlCriteriaCatalog
from app.db import Base, make_engine, make_session_factory
from app.settings import Settings


@dataclass
class Container:
    settings: Settings
    clock: Clock
    seed: Seed
    engine: Engine
    session_factory: sessionmaker
    catalog: CriteriaCatalog
    employees: EmployeeDirectory
    evaluations: EvaluationReader
    reminder_sink: ReminderSink
    drafts: DraftProvider
    notes: NotesReader
    reminder_providers: list[ReminderProvider] = field(default_factory=list)


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings.from_env()
    seed = load_seed(settings.seed_path)
    catalog = YamlCriteriaCatalog(settings.regulation_dir)
    engine = make_engine(settings.database_url)
    c = Container(
        settings=settings,
        clock=Clock(settings.demo_today),
        seed=seed,
        engine=engine,
        session_factory=make_session_factory(engine),
        catalog=catalog,
        employees=FakeEmployeeDirectory(seed),
        evaluations=FakeEvaluationReader(seed, catalog),
        reminder_sink=CollectingReminderSink(),
        drafts=NullDraftProvider(),
        notes=FakeNotesReader(seed),
    )

    from app import assistant, core

    core.register(c)
    assistant.register(c)
    Base.metadata.create_all(engine)
    return c
