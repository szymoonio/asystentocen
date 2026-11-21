"""Wspólna baza SQLAlchemy. ZAMROŻONE (krok 0).

Każdy moduł definiuje WŁASNE tabele, dziedzicząc po `Base`, z prefiksem nazwy:
    core_*  — agent A (app/core/)
    asst_*  — agent B (app/assistant/)
Modele muszą zostać zaimportowane w `register()` modułu, wtedy `create_all` je założy.
Migracje (Alembic) — po hackathonie; na razie create_all na starcie.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
