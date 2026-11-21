from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from app.contracts.enums import SheetType
from app.contracts.fakes import FakeEmployeeDirectory, FakeEvaluationReader
from app.core.rules import careers, deadlines
from app.core.rules.scoring import format_mean, score


@pytest.fixture
def directory(seed):
    return FakeEmployeeDirectory(seed)


@pytest.fixture
def reader(seed, catalog):
    return FakeEvaluationReader(seed, catalog)


# --- terminy zgodne z oczekiwaniami zapisanymi w seedzie --------------------------------


@pytest.mark.parametrize(
    ("evaluation_id", "cycle_start", "employee_id"),
    [
        ("EV-E07-2024", date(2024, 12, 10), "E07"),  # pierwsza ocena: od zatrudnienia
        ("EV-E09-2026", date(2026, 10, 20), "E09"),
        ("EV-E08-2028", date(2026, 11, 5), "E08"),  # od poprzedniej oceny
        ("EV-E04-2028", date(2026, 3, 2), "E04"),
        ("EV-E11-2025", date(2025, 6, 2), "E11"),
        ("EV-E10-2025", date(2025, 2, 3), "E10"),  # + 89 dni nieobecności, 03.05 → 04.05
    ],
)
def test_assessment_due_matches_seed(reader, directory, evaluation_id, cycle_start, employee_id):
    expected = reader.get(evaluation_id).due_date
    due = deadlines.assessment_due(cycle_start, directory.absences(employee_id))
    assert due.date == expected


def test_absence_extension_details(directory):
    due = deadlines.assessment_due(date(2025, 2, 3), directory.absences("E10"))
    assert due.basis == "art. 81 ust. 4 i 7 ustawy"
    assert due.extensions == ((date(2026, 8, 3), date(2026, 10, 30), 89),)


def test_short_absences_do_not_extend(directory):
    # Ewa: dwie nieobecności rozdzielone dniem roboczym, każda krótsza niż miesiąc
    due = deadlines.assessment_due(date(2024, 12, 10), directory.absences("E07"))
    assert due.date == date(2026, 12, 10) and not due.extensions


def test_reassessment_after_negative(reader):
    due = deadlines.assessment_due(date(2026, 6, 12), negative_acknowledged_on=date(2026, 6, 15))
    assert due.date == reader.get("EV-E06-2026R").due_date
    assert due.basis == "art. 81 ust. 9 ustawy"


def test_criteria_due_matches_seed(reader):
    assert deadlines.criteria_due(date(2026, 10, 20)).date == reader.get("EV-E09-2026").criteria_due_date
    assert deadlines.criteria_due(date(2026, 11, 5)).date == reader.get("EV-E08-2028").criteria_due_date
    neg = deadlines.criteria_due(date(2026, 6, 12), after_negative=True)
    assert neg.date == reader.get("EV-E06-2026R").criteria_due_date


def test_due_date_change_needs_six_months():
    assert deadlines.can_change_due_date(date(2026, 6, 18), date(2026, 11, 21))[0] is False
    assert deadlines.can_change_due_date(date(2024, 12, 20), date(2026, 11, 21))[0] is True


def test_position_change():
    early = deadlines.position_change_action(date(2026, 9, 1), reference=date(2026, 6, 18), first_assessment=False)
    assert early.kind == "REDO_CRITERIA" and early.window_end == date(2026, 10, 1)
    late = deadlines.position_change_action(date(2026, 9, 1), reference=date(2025, 6, 18), first_assessment=False)
    assert late.kind == "ASSESS_NOW" and late.window_start == date(2026, 8, 25)


# --- arkusz, stopnie -------------------------------------------------------------------


def test_sheet_for_matches_seed(reader, directory):
    for employee in directory.all():
        current = reader.current_for(employee.id)
        if current:
            assert careers.sheet_for(employee.position) == current.sheet


def test_obligatory_promotion_for_piotr(directory, reader):
    promo = careers.obligatory_promotion(directory.get("E08"), reader.history("E08"))
    assert promo is not None
    assert promo.deadline.date == date(2026, 12, 7)  # 06.12.2026 to niedziela
    assert promo.next_grade == 5


def test_no_promotion_for_non_urzednik_or_mixed_levels(directory, reader):
    assert careers.obligatory_promotion(directory.get("E04"), reader.history("E04")) is None  # pracownik s.c.
    assert careers.obligatory_promotion(directory.get("E06"), reader.history("E06")) is None


def test_next_grade_text():
    assert careers.next_grade_text(2) == "trzeciego"
    assert careers.next_grade_text(9) is None


# --- wynik -------------------------------------------------------------------------------


def test_forced_negative_flag():
    result = score([5, 1, 5, 5, 5])
    assert result.forced_negative and result.outcome == "NEGATYWNA"


@pytest.mark.parametrize(
    ("mean", "text"),
    [(Fraction(27, 7), "3,86"), (Fraction(25, 4), "6,25"), (Fraction(5), "5"), (Fraction(11, 2), "5,5")],
)
def test_format_mean(mean, text):
    assert format_mean(mean) == text


def test_sheet_c_mandatory(catalog):
    assert [c.code for c in catalog.mandatory_for(SheetType.C)][:2] == ["WYKORZYSTYWANIE_WIEDZY", "RZETELNOSC"]
