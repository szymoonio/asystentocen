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
    one = stats_view(CriterionStats(criterion_code="K", n_ratings=1, distribution={3: 1}, median=3.0,
                                    first_half_mean=3.0, second_half_mean=None))
    assert (one["mean"], one["tone"], one["count"], one["trend"]) == ("3", "l2", "1 ocena", "")
    assert stats_view(CriterionStats(criterion_code="K", n_ratings=0, distribution={})) is None
    assert stats_view(CriterionStats(criterion_code="K", n_ratings=2, distribution={5: 0})) is None
    mixed = stats_view(CriterionStats(criterion_code="K", n_ratings=3, distribution={5: 1, 7: 2}, median=7.0,
                                      first_half_mean=5.0, second_half_mean=7.0))
    assert (mixed["mean"], mixed["tone"], mixed["count"], mixed["trend"]) == ("6,3", "l4", "3 oceny", "up")
    many = stats_view(CriterionStats(criterion_code="K", n_ratings=12, distribution={9: 12}))
    assert (many["tone"], many["count"]) == ("l5", "12 ocen")


def test_panel_renders_with_edge_case_stats(client, container):
    container.notes = EdgeCaseNotes()
    client.get("/login/E05")
    client.post("/core/oceny/EV-E07-2024/rozmowa", data={"interview_date": "2026-11-20"})
    page = client.get("/core/oceny/EV-E07-2024")
    assert page.status_code == 200
    assert 'class="score l2">3' in page.text and "1 ocena" in page.text
    assert 'class="score l4">6,3' in page.text and "brak ocen" in page.text
