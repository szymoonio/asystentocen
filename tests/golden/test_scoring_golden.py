"""Testy golden wyniku oceny — ZAMROŻONE (krok 0). Agent A ma je zazielenić.

Dane: tests/golden/sample_sheets.json — oceny cząstkowe odczytane z 10 przykładowych
arkuszy KPRM, wynik wyliczony wg § 11 rozporządzenia (ułamki, nie floaty).

Wymagane API (docs/AGENT_A.md):
    app.core.rules.scoring.score(points: Sequence[int]) -> ScoreResult
        ScoreResult.mean: Fraction, .level: Level, .outcome: Outcome
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from app.contracts.enums import Level, Outcome

scoring = pytest.importorskip("app.core.rules.scoring")

DATA = json.loads((Path(__file__).parent / "sample_sheets.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["file"])
def test_sample_sheet(case):
    result = scoring.score([c["points"] for c in case["criteria"]])
    expected = case["expected"]
    assert result.mean == Fraction(expected["mean_numerator"], expected["mean_denominator"])
    assert result.level == Level(expected["level"])
    assert result.outcome == Outcome(expected["outcome"])


def test_mean_just_above_4_is_at_expectations():
    result = scoring.score([5, 5, 5, 3, 3])  # 21/5 = 4,2
    assert result.level == Level.NA_POZIOMIE
    assert result.outcome == Outcome.POZYTYWNA


def test_mean_exactly_4_is_below_expectations():
    # „powyżej 2 do 4” zawiera 4; „na poziomie” zaczyna się POWYŻEJ 4
    result = scoring.score([5, 3, 5, 3])
    assert result.mean == 4
    assert result.level == Level.PONIZEJ
    assert result.outcome == Outcome.NEGATYWNA


def test_mean_exactly_6_is_at_expectations():
    result = scoring.score([7, 5, 7, 5])
    assert result.mean == 6
    assert result.level == Level.NA_POZIOMIE


def test_any_partial_1_forces_negative():
    # średnia 7,4 („powyżej oczekiwań”), ale jedna cząstkowa = 1 → NEGATYWNA (§ 11 ust. 1 pkt 4)
    result = scoring.score([9, 9, 9, 9, 1])
    assert result.level == Level.POWYZEJ
    assert result.outcome == Outcome.NEGATYWNA


def test_rejects_values_outside_scale():
    with pytest.raises(ValueError):
        scoring.score([5, 4, 5])
    with pytest.raises(ValueError):
        scoring.score([])
