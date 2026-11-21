"""Testy golden terminów — ZAMROŻONE (krok 0). Agent A ma je zazielenić.

Wymagane API (docs/AGENT_A.md):
    app.core.rules.calendar_pl: holidays(year) -> set[date], is_working_day(d) -> bool,
        add_months(d, n) -> date, shift_to_working_day(d) -> date,
        deadline_in_days(event, n) -> date, deadline_in_months(start, n) -> date
    app.core.rules.deadlines: merge_absences(list[tuple[date, date]]) -> list[tuple[date, date]],
        is_longer_than_month(start, end) -> bool

Dopóki moduł nie istnieje, testy są pomijane (skip), a nie czerwone.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

calendar_pl = pytest.importorskip("app.core.rules.calendar_pl")
deadlines = pytest.importorskip("app.core.rules.deadlines")

DATA = json.loads((Path(__file__).parent / "deadlines.json").read_text(encoding="utf-8"))
d = date.fromisoformat


def test_holidays_2026():
    assert calendar_pl.holidays(2026) == {d(x) for x in DATA["holidays"]["2026"]}


@pytest.mark.parametrize("case", DATA["is_working_day"], ids=lambda c: c["date"])
def test_is_working_day(case):
    assert calendar_pl.is_working_day(d(case["date"])) is case["expected"], case.get("why")


@pytest.mark.parametrize("case", DATA["add_months"], ids=lambda c: f'{c["start"]}+{c["months"]}m')
def test_add_months(case):
    assert calendar_pl.add_months(d(case["start"]), case["months"]) == d(case["expected"]), case.get("why")


@pytest.mark.parametrize("case", DATA["shift_to_working_day"], ids=lambda c: c["date"])
def test_shift_to_working_day(case):
    assert calendar_pl.shift_to_working_day(d(case["date"])) == d(case["expected"]), case.get("why")


@pytest.mark.parametrize("case", DATA["deadline_in_days"], ids=lambda c: f'{c["event"]}+{c["days"]}d')
def test_deadline_in_days(case):
    assert calendar_pl.deadline_in_days(d(case["event"]), case["days"]) == d(case["expected"]), case.get("why")


@pytest.mark.parametrize("case", DATA["deadline_in_months"], ids=lambda c: f'{c["start"]}+{c["months"]}m')
def test_deadline_in_months(case):
    assert calendar_pl.deadline_in_months(d(case["start"]), case["months"]) == d(case["expected"]), case.get("why")


@pytest.mark.parametrize("case", DATA["merge_absences"], ids=lambda c: c["periods"][0][0])
def test_merge_absences(case):
    periods = [(d(a), d(b)) for a, b in case["periods"]]
    expected = [(d(a), d(b)) for a, b in case["expected"]]
    assert deadlines.merge_absences(periods) == expected, case.get("why")


@pytest.mark.parametrize("case", DATA["is_longer_than_month"], ids=lambda c: c["start"])
def test_is_longer_than_month(case):
    assert deadlines.is_longer_than_month(d(case["start"]), d(case["end"])) is case["expected"], case.get("why")
