"""Zestawienia z suwaków (§ 5.2) — czyste funkcje."""

from __future__ import annotations

from datetime import date, datetime

from app.assistant.notes.stats import compute_stats, period_midpoint, uncovered
from app.contracts.models import CriterionRating, Note


def note(observed_on: date, **ratings: int) -> Note:
    return Note(
        id=f"N-{observed_on.isoformat()}",
        author_id="E05",
        subject_id="E06",
        observed_on=observed_on,
        created_at=datetime.combine(observed_on, datetime.min.time()),
        body="x",
        ratings=[CriterionRating(criterion_code=k, value=v) for k, v in ratings.items()],
    )


def by_code(stats):
    return {s.criterion_code: s for s in stats}


def test_median_distribution_and_last_rated():
    notes = [note(date(2026, 1, 10), A=3), note(date(2026, 2, 10), A=9), note(date(2026, 3, 10), A=5)]
    s = by_code(compute_stats(notes))["A"]
    assert s.n_ratings == 3
    assert s.distribution == {3: 1, 5: 1, 9: 1}
    assert s.median == 5
    assert s.last_rated_on == date(2026, 3, 10)


def test_even_count_median_is_midpoint():
    notes = [note(date(2026, 1, 1), A=5), note(date(2026, 2, 1), A=7)]
    assert by_code(compute_stats(notes))["A"].median == 6


def test_halves_follow_evaluation_period_not_note_count():
    # okres 1.01–31.12, połowa 2.07; trzy notatki w pierwszej połowie, jedna w drugiej
    notes = [
        note(date(2026, 2, 1), A=3),
        note(date(2026, 3, 1), A=3),
        note(date(2026, 4, 1), A=5),
        note(date(2026, 10, 1), A=9),
    ]
    s = by_code(compute_stats(notes, period_from=date(2026, 1, 1), due_date=date(2026, 12, 31)))["A"]
    assert s.first_half_mean == (3 + 3 + 5) / 3
    assert s.second_half_mean == 9


def test_all_ratings_in_one_half_leaves_other_empty():
    notes = [note(date(2026, 10, 1), A=5), note(date(2026, 11, 1), A=7)]
    s = by_code(compute_stats(notes, period_from=date(2026, 1, 1), due_date=date(2026, 12, 31)))["A"]
    assert s.first_half_mean is None
    assert s.second_half_mean == 6


def test_without_period_split_between_first_and_last_observation():
    notes = [note(date(2026, 1, 1), A=3), note(date(2026, 1, 2), A=3), note(date(2026, 3, 1), A=9)]
    s = by_code(compute_stats(notes))["A"]
    assert s.first_half_mean == 3
    assert s.second_half_mean == 9


def test_single_rating_has_no_first_half():
    s = by_code(compute_stats([note(date(2026, 5, 5), A=7)]))["A"]
    assert s.first_half_mean is None and s.second_half_mean == 7


def test_criteria_without_ratings_are_reported_as_uncovered_and_extras_come_last():
    notes = [note(date(2026, 1, 1), A=5, Z=7)]
    stats = compute_stats(notes, criteria_codes=["A", "B"])
    assert [s.criterion_code for s in stats] == ["A", "B", "Z"]
    assert by_code(stats)["B"].n_ratings == 0 and by_code(stats)["B"].median is None
    assert uncovered(stats) == ["B"]


def test_period_midpoint():
    assert period_midpoint(date(2026, 6, 18), date(2026, 12, 15)) == date(2026, 9, 16)
    assert period_midpoint(None, date(2026, 12, 15)) is None
    assert period_midpoint(date(2026, 1, 1), date(2026, 1, 1)) is None
