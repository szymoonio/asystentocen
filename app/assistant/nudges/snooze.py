"""„Odłóż o 2 tygodnie” — wyciszenie przypomnień o jednej osobie dla jednego przełożonego."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer, String, delete, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.db import Base


class SnoozeRow(Base):
    __tablename__ = "asst_nudge_snoozes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supervisor_id: Mapped[str] = mapped_column(String(20), index=True)
    subject_id: Mapped[str] = mapped_column(String(20))
    until: Mapped[date] = mapped_column(Date)  # włącznie


class SnoozeRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def snooze(self, supervisor_id: str, subject_id: str, until: date) -> None:
        with self._sf.begin() as s:
            s.execute(
                delete(SnoozeRow).where(SnoozeRow.supervisor_id == supervisor_id, SnoozeRow.subject_id == subject_id)
            )
            s.add(SnoozeRow(supervisor_id=supervisor_id, subject_id=subject_id, until=until))

    def cancel(self, supervisor_id: str, subject_id: str) -> None:
        with self._sf.begin() as s:
            s.execute(
                delete(SnoozeRow).where(SnoozeRow.supervisor_id == supervisor_id, SnoozeRow.subject_id == subject_id)
            )

    def active(self, supervisor_id: str, today: date) -> dict[str, date]:
        stmt = select(SnoozeRow).where(SnoozeRow.supervisor_id == supervisor_id, SnoozeRow.until >= today)
        with self._sf() as s:
            return {r.subject_id: r.until for r in s.scalars(stmt)}
