"""Testy fake'ów i spójności seed — ZAMROŻONE (krok 0).

Pilnują, że obie strony mogą polegać na tych samych danych demo.
"""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction

from app.contracts.enums import EvaluationState, Level, ReminderKind, Role, SheetType
from app.contracts.fakes import (
    CollectingReminderSink,
    FakeEmployeeDirectory,
    FakeEvaluationReader,
    FakeNotesReader,
    NullDraftProvider,
    roles_for,
)
from app.contracts.models import Reminder
from app.contracts.ports import DraftProvider, EmployeeDirectory, EvaluationReader, NotesReader, ReminderSink


def test_fakes_implement_ports(seed, catalog):
    assert isinstance(FakeEmployeeDirectory(seed), EmployeeDirectory)
    assert isinstance(FakeEvaluationReader(seed, catalog), EvaluationReader)
    assert isinstance(CollectingReminderSink(), ReminderSink)
    assert isinstance(NullDraftProvider(), DraftProvider)
    assert isinstance(FakeNotesReader(seed), NotesReader)


def test_seed_references_are_consistent(seed, catalog):
    ids = {e.id for e in seed.employees}
    units = {u.id for u in seed.org_units}
    for e in seed.employees:
        assert e.supervisor_id is None or e.supervisor_id in ids
        assert e.position.org_unit_id in units
    for r in seed.evaluations:
        assert r["employee_id"] in ids
        for code in r.get("additional", []):
            catalog.get(code)
        assert len(r.get("additional", [])) <= 3
    for n in seed.notes:
        assert n.author_id in ids and n.subject_id in ids


def test_sheet_matches_position(seed, catalog):
    reader = FakeEvaluationReader(seed, catalog)
    directory = FakeEmployeeDirectory(seed)
    for ev in reader._evals:  # noqa: SLF001 — test spójności danych
        pos = directory.get(ev.employee_id).position
        expected = SheetType.A if pos.is_head_of_office else SheetType.B if pos.manages_people else SheetType.C
        assert ev.sheet == expected, ev.id


def test_seed_results_match_partial_points(seed, catalog):
    reader = FakeEvaluationReader(seed, catalog)
    for ev in reader._evals:  # noqa: SLF001
        if not ev.result:
            continue
        points = list(ev.result.partial_points.values())
        assert ev.result.mean == Fraction(sum(points), len(points)), ev.id
        assert set(ev.result.partial_points) == {c.code for c in ev.criteria}, ev.id


def test_directory_and_reader(seed, catalog):
    directory = FakeEmployeeDirectory(seed)
    reader = FakeEvaluationReader(seed, catalog)
    henryk = {e.id for e in directory.subordinates("E05")}
    assert henryk == {"E06", "E07", "E09", "E12", "E13", "E14", "E15"}
    assert reader.current_for("E12") is None  # umowa na czas określony
    current = reader.current_for("E06")
    assert current.id == "EV-E06-2026R" and current.after_negative
    assert [c.code for c in current.criteria if not c.mandatory] == ["ORIENTACJA_NA_KLIENTA", "KREATYWNOSC"]
    history = reader.history("E08")
    assert [h.result.level for h in history] == [Level.POWYZEJ, Level.POWYZEJ]
    assert reader.current_for("E09").state == EvaluationState.CYCLE_OPEN


def test_roles(seed):
    directory = FakeEmployeeDirectory(seed)
    assert Role.OCENIAJACY in roles_for(directory.get("E05"), directory)
    assert Role.OCENIAJACY not in roles_for(directory.get("E06"), directory)
    assert Role.KADRY in roles_for(directory.get("E11"), directory)


def test_notes_are_private_to_author(seed):
    notes = FakeNotesReader(seed)
    assert len(notes.notes_for("E05", "E06")) == 5
    assert notes.notes_for("E04", "E06") == []  # inny przełożony nie widzi notatek


def test_notes_stats(seed):
    stats = {s.criterion_code: s for s in FakeNotesReader(seed).stats_for("E05", "E06", "EV-E06-2026R")}
    assert stats["KOMUNIKACJA"].n_ratings == 2
    assert stats["KOMUNIKACJA"].distribution == {3: 1, 5: 1}
    assert stats["ORIENTACJA_NA_KLIENTA"].last_rated_on == date(2026, 11, 4)


def test_reminder_sink_dedupes():
    sink = CollectingReminderSink()
    r = Reminder(recipient_id="E05", kind=ReminderKind.NOTE_NUDGE, message="x", dedupe_key="k1")
    assert sink.emit([r, r]) == 1
    assert sink.emit([r]) == 0
    assert sink.inbox("E05") == [r]


def test_rating_scale_enforced():
    import pytest
    from pydantic import ValidationError

    from app.contracts.models import CriterionRating, Note

    with pytest.raises(ValidationError):
        CriterionRating(criterion_code="KOMUNIKACJA", value=4)
    Note(id="n", author_id="E05", subject_id="E06", observed_on=date(2026, 1, 1), created_at=datetime(2026, 1, 1))


def test_demo_team_has_history_for_charts(seed, catalog):
    """E13–E15: kilka lat pracy, oceny za sobą i dziesiątki notatek — wykresy i analiza mają na czym pracować."""
    reader = FakeEvaluationReader(seed, catalog)
    notes = FakeNotesReader(seed)
    for employee_id, n_history, min_notes in [("E13", 2, 30), ("E14", 2, 40), ("E15", 1, 15)]:
        assert len(reader.history(employee_id)) == n_history, employee_id
        assert len(notes.notes_for("E05", employee_id)) >= min_notes, employee_id
    assert reader.current_for("E13").state == EvaluationState.INTERVIEW_HELD
