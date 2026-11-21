"""Repozytorium notatek, wersjonowanie i DbNotesReader na seedzie."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.assistant.notes.reader import DbNotesReader
from app.assistant.notes.repository import NoteAlreadyRevised, NoteInput, NoteNotFound
from app.assistant.services import services
from app.container import build_container
from app.contracts.models import CriterionRating
from app.contracts.ports import NotesReader

NOW = datetime(2026, 11, 21, 10, 0)


@pytest.fixture
def repo(container):
    return services(container).notes_repo


def test_container_uses_db_reader(container):
    assert isinstance(container.notes, DbNotesReader)
    assert isinstance(container.notes, NotesReader)


def test_seed_notes_imported_once(settings, container, seed):
    assert len(services(container).notes_repo.current("E05")) == len([n for n in seed.notes if n.author_id == "E05"])
    again = build_container(settings)  # ta sama baza → bez ponownego importu
    assert len(services(again).notes_repo.current("E05")) == 8


def test_only_author_sees_notes(container):
    assert len(container.notes.notes_for("E05", "E06")) == 5
    assert container.notes.notes_for("E04", "E06") == []
    assert len(container.notes.notes_for("E04", "E10")) == 1


def test_notes_for_date_filters(container):
    notes = container.notes.notes_for("E05", "E06", since=date(2026, 9, 1), until=date(2026, 10, 31))
    assert [n.id for n in notes] == ["N003", "N004"]


def test_get_other_authors_note_is_not_found(repo):
    with pytest.raises(NoteNotFound):
        repo.get("E04", "N001")


def test_revise_creates_new_version_and_keeps_history(repo):
    data = NoteInput(observed_on=date(2026, 7, 8), body="Poprawiony opis", strengths=["Samodzielność"])
    v2 = repo.revise(author_id="E05", note_id="N001", data=data, now=NOW)
    assert v2.version == 2 and v2.supersedes_id == "N001"
    assert v2.evaluation_id == "EV-E06-2026R" and v2.subject_id == "E06"

    current_ids = [n.id for n in repo.current("E05", "E06")]
    assert v2.id in current_ids and "N001" not in current_ids
    assert len(current_ids) == 5
    assert [n.version for n in repo.history("E05", v2.id)] == [2, 1]

    with pytest.raises(NoteAlreadyRevised):
        repo.revise(author_id="E05", note_id="N001", data=data, now=NOW)


def test_create_note(repo):
    data = NoteInput(
        observed_on=date(2026, 11, 20),
        improvements=["Dopytać o terminy"],
        ratings=[CriterionRating(criterion_code="KOMUNIKACJA", value=3)],
    )
    note = repo.create(author_id="E05", subject_id="E06", evaluation_id="EV-E06-2026R", data=data, now=NOW)
    assert note.id.startswith("N-") and note.version == 1
    assert repo.get("E05", note.id).ratings[0].value == 3


def test_stats_for_grzegorz_current_cycle(container):
    stats = {s.criterion_code: s for s in container.notes.stats_for("E05", "E06", "EV-E06-2026R")}
    # wszystkie 7 kryteriów oceny, także bez pokrycia
    assert set(stats) == {
        "WYKORZYSTYWANIE_WIEDZY", "RZETELNOSC", "ORGANIZACJA_PRACY", "WSPOLPRACA",
        "KOMUNIKACJA", "ORIENTACJA_NA_KLIENTA", "KREATYWNOSC",
    }  # fmt: skip
    assert stats["ORGANIZACJA_PRACY"].n_ratings == 0
    # okres 18.06–15.12.2026, połowa 16.09
    wsp = stats["WSPOLPRACA"]
    assert (wsp.n_ratings, wsp.median, wsp.first_half_mean, wsp.second_half_mean) == (2, 6, 5, 7)
    kom = stats["KOMUNIKACJA"]
    assert (kom.first_half_mean, kom.second_half_mean, kom.last_rated_on) == (3, 5, date(2026, 11, 4))
    assert stats["ORIENTACJA_NA_KLIENTA"].distribution == {3: 1, 5: 1}


def test_stats_for_open_cycle_uses_mandatory_criteria(container):
    stats = container.notes.stats_for("E05", "E09", "EV-E09-2026")
    assert [s.criterion_code for s in stats] == [
        "WYKORZYSTYWANIE_WIEDZY", "RZETELNOSC", "ORGANIZACJA_PRACY", "WSPOLPRACA", "KOMUNIKACJA",
    ]  # fmt: skip
    assert all(s.n_ratings == 0 for s in stats)


def test_stats_for_unknown_evaluation_is_empty(container):
    assert container.notes.stats_for("E05", "E06", "EV-NOPE") == []
