"""Tabele modułu CORE (prefiks core_)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OfficeRow(Base):
    __tablename__ = "core_office"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    objection_addressee_head: Mapped[str | None] = mapped_column(String(300))


class OrgUnitRow(Base):
    __tablename__ = "core_org_units"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    parent_id: Mapped[str | None] = mapped_column(String(40))
    city: Mapped[str | None] = mapped_column(String(120))


class EmployeeRow(Base):
    __tablename__ = "core_employees"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    org_unit_id: Mapped[str] = mapped_column(String(40))
    is_head_of_office: Mapped[bool] = mapped_column(Boolean, default=False)
    manages_people: Mapped[bool] = mapped_column(Boolean, default=False)
    basis: Mapped[str] = mapped_column(String(40))
    indefinite_since: Mapped[date | None] = mapped_column(Date)
    appointed_year: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[int | None] = mapped_column(Integer)
    grade_granted_on: Mapped[date | None] = mapped_column(Date)
    supervisor_id: Mapped[str | None] = mapped_column(String(40))
    extra_roles: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AbsenceRow(Base):
    """Tylko daty — bez przyczyny nieobecności (dane o zdrowiu, art. 9 RODO)."""

    __tablename__ = "core_absences"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(String(40), index=True)
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    justified: Mapped[bool] = mapped_column(Boolean, default=True)


class EvaluationRow(Base):
    __tablename__ = "core_evaluations"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(40), index=True)
    evaluator_id: Mapped[str | None] = mapped_column(String(40), index=True)
    sheet: Mapped[str] = mapped_column(String(1))
    state: Mapped[str] = mapped_column(String(30), index=True)
    regulation_version: Mapped[str] = mapped_column(String(20), default="2016")
    additional: Mapped[list] = mapped_column(JSON, default=list)  # kody kryteriów dodatkowych
    cycle_start: Mapped[date | None] = mapped_column(Date)  # poprzednia ocena / zatrudnienie
    after_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    criteria_due_date: Mapped[date | None] = mapped_column(Date)
    criteria_set_on: Mapped[date | None] = mapped_column(Date)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_basis: Mapped[str | None] = mapped_column(String(200))
    # pola formularza (miejscowości, daty potwierdzeń, oceny cząstkowe, teksty, część III)
    form: Mapped[dict] = mapped_column(JSON, default=dict)
    # wynik (wypełniany przy zatwierdzeniu)
    mean_numerator: Mapped[int | None] = mapped_column(Integer)
    mean_denominator: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[str | None] = mapped_column(String(30))
    outcome: Mapped[str | None] = mapped_column(String(20))
    assessed_on: Mapped[date | None] = mapped_column(Date)
    acknowledged_on: Mapped[date | None] = mapped_column(Date)
    ack_deemed: Mapped[bool] = mapped_column(Boolean, default=False)  # fikcja zapoznania
    promotion_requested: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class EventRow(Base):
    """Audyt: każda zmiana stanu, korekta administratora, zmiana terminu."""

    __tablename__ = "core_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(60), index=True)
    employee_id: Mapped[str | None] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime)
    actor_id: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class ReminderRow(Base):
    __tablename__ = "core_reminders"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    recipient_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    due: Mapped[date | None] = mapped_column(Date)
    subject_id: Mapped[str | None] = mapped_column(String(40))
    evaluation_id: Mapped[str | None] = mapped_column(String(60))
    link: Mapped[str | None] = mapped_column(String(300))
    channel: Mapped[str] = mapped_column(String(20), default="IN_APP")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class MetaRow(Base):
    """Klucz–wartość (np. data ostatniego uruchomienia przypomnień)."""

    __tablename__ = "core_meta"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(300))
