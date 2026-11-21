"""Panel „Twoje obserwacje” musi znieść każdą wartość dopuszczoną przez kontrakt CriterionStats.

Regresja z CI: implementacja B zwraca second_half_mean=None (wszystkie oceny w 1. połowie okresu)
i wpisy z n_ratings == 0 dla kryteriów bez obserwacji — fake z kroku 0 tego nie robił.
"""

from __future__ import annotations

from datetime import date

from app.contracts.models import CriterionStats
from app.core.api import stats_view


class EdgeCaseNotes:
    """NotesReader zwracający przypadki brzegowe kontraktu."""

    def notes_for(self, author_id, subject_id, *, since=None, until=None):
        return []

    def stats_for(self, author_id, subject_id, evaluation_id):
        return [
            CriterionStats(criterion_code="KOMUNIKACJA", n_ratings=1, distribution={3: 1}, median=3.0,
                           first_half_mean=3.0, second_half_mean=None, last_rated_on=date(2025, 6, 30)),
            CriterionStats(criterion_code="WSPOLPRACA", n_ratings=2, distribution={7: 2}, median=None,
                           first_half_mean=None, second_half_mean=7.0),
            CriterionStats(criterion_code="RZETELNOSC", n_ratings=0, distribution={}),
            CriterionStats(criterion_code="ORGANIZACJA_PRACY", n_ratings=3, distribution={5: 1, 7: 2},
                           median=7.0, first_half_mean=5.0, second_half_mean=7.0),
        ]

    def teczka_url(self, subject_id):
        return f"/asystent/teczka/{subject_id}"


def test_stats_view_edge_cases():
    first_only = stats_view(CriterionStats(criterion_code="K", n_ratings=1, distribution={3: 1}, median=3.0,
                                           first_half_mean=3.0, second_half_mean=None))
    assert first_only["summary"] == "1 obs. · mediana 3 · tylko w 1. połowie okresu"
    assert stats_view(CriterionStats(criterion_code="K", n_ratings=0, distribution={})) is None
    trend = stats_view(CriterionStats(criterion_code="K", n_ratings=3, distribution={5: 1, 7: 2}, median=7.0,
                                      first_half_mean=5.0, second_half_mean=6.666))
    assert trend["summary"] == "3 obs. · mediana 7 · trend 5 → 6,7"
    assert [h for _, _, h in trend["bars"]] == [4, 4, 50, 100, 4]


def test_panel_renders_with_edge_case_stats(client, container):
    container.notes = EdgeCaseNotes()
    client.get("/login/E05")
    client.post("/core/oceny/EV-E07-2024/rozmowa", data={"interview_date": "2026-11-20"})
    page = client.get("/core/oceny/EV-E07-2024")
    assert page.status_code == 200
    assert "tylko w 1. połowie okresu" in page.text
    assert "trend 5 → 7" in page.text
