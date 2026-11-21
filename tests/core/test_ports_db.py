"""Prawdziwe porty A — te same oczekiwania co dla fake'ów z kroku 0."""

from __future__ import annotations

from fractions import Fraction

from app.contracts.enums import EvaluationState, Level
from app.contracts.ports import EmployeeDirectory, EvaluationReader, ReminderSink
from app.core.repo import DbEmployeeDirectory, DbEvaluationReader, DbReminderSink


def test_container_uses_db_ports(container):
    assert isinstance(container.employees, DbEmployeeDirectory) and isinstance(container.employees, EmployeeDirectory)
    assert isinstance(container.evaluations, DbEvaluationReader) and isinstance(container.evaluations, EvaluationReader)
    assert isinstance(container.reminder_sink, DbReminderSink) and isinstance(container.reminder_sink, ReminderSink)


def test_directory(container):
    d = container.employees
    assert {e.id for e in d.subordinates("E05")} == {"E06", "E07", "E09", "E12"}
    assert d.get("E06").is_urzednik and d.get("E06").grade == 2
    assert d.office().name == "Generalna Dyrekcja Przekładów i Przykładów"
    assert d.org_unit("U-RP").name == "Referat Przekładów"
    assert len(d.absences("E07")) == 2


def test_reader_matches_seed(container, seed, catalog):
    from app.contracts.fakes import FakeEvaluationReader

    fake = FakeEvaluationReader(seed, catalog)
    real = container.evaluations
    for emp in container.employees.all():
        f, r = fake.current_for(emp.id), real.current_for(emp.id)
        assert (f.id if f else None) == (r.id if r else None), emp.id
        if r:
            assert r.criteria == f.criteria and r.due_date == f.due_date and r.state == f.state
        assert [h.id for h in fake.history(emp.id)] == [h.id for h in real.history(emp.id)]
    hist = real.history("E06")
    assert hist[-1].result.mean == Fraction(27, 7) and hist[-1].result.level == Level.PONIZEJ
    assert real.current_for("E09").state == EvaluationState.CYCLE_OPEN


def test_import_is_idempotent(container):
    from app.core.repo import import_seed

    assert import_seed(container.session_factory, container.seed) is False
