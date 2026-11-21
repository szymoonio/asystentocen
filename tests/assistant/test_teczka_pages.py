"""Strony teczki: lista, oś czasu, formularz, edycja, dostęp."""

from __future__ import annotations

from app.assistant.services import services


def test_list_shows_subordinates_and_stale_flags(client):
    page = client.get("/asystent/teczka").text
    for name in ["Grzegorz Wzór", "Ewa Rzetelna", "Zofia Nowicka", "Tomasz Młodszy"]:
        assert name in page
    assert "15.04.2026" in page  # ostatnia notatka Ewy
    assert "dawno bez notatki" in page  # Ewa: > 45 dni
    assert "zacznij teczkę" in page  # Zofia: brak notatek
    assert "nie podlega ocenie okresowej" in page  # Tomasz


def test_timeline_and_stats(client):
    page = client.get("/asystent/teczka/E06").text
    assert "Pokazano 5 z 5 notatek" in page
    assert "Zestawienie suwaków" in page
    assert "brak obserwacji" in page  # Organizacja pracy bez suwaka
    assert "głosowa" in page  # N003


def test_timeline_filters(client):
    assert "Pokazano 2 z 5" in client.get("/asystent/teczka/E06?rodzaj=obszary").text
    assert "Pokazano 2 z 5" in client.get("/asystent/teczka/E06?kryterium=KOMUNIKACJA").text
    assert "Pokazano 1 z 5" in client.get("/asystent/teczka/E06?q=szablon").text
    assert "Pokazano 0 z 5" in client.get("/asystent/teczka/E06?cykl=EV-E06-2024").text


def test_form_shows_current_criteria_and_unset_sliders(client):
    page = client.get("/asystent/teczka/E06/nowa").text
    assert "Orientacja na klienta/interesanta" in page  # kryterium dodatkowe tej oceny
    assert 'name="rating_KOMUNIKACJA" value="" checked' in page  # domyślnie „—”
    assert "Inne kryteria z katalogu (7)" in page


def test_form_before_criteria_set_shows_mandatory_only(client):
    page = client.get("/asystent/teczka/E09/nowa").text
    assert "Kryteria nie są jeszcze ustalone" in page
    assert "Inne kryteria z katalogu (9)" in page


def test_create_note_flow(client, container):
    response = client.post(
        "/asystent/teczka/E06/nowa",
        data={
            "observed_on": "2026-11-20",
            "body": "Sam zgłosił ryzyko opóźnienia dwa dni przed terminem.",
            "strengths": "Wczesna informacja o ryzyku\n- Propozycja rozwiązania",
            "improvements": "",
            "rating_KOMUNIKACJA": "7",
            "rating_RZETELNOSC": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    notes = container.notes.notes_for("E05", "E06")
    assert len(notes) == 6
    new = notes[-1]
    assert new.evaluation_id == "EV-E06-2026R"
    assert new.strengths == ["Wczesna informacja o ryzyku", "Propozycja rozwiązania"]
    assert [(r.criterion_code, r.value) for r in new.ratings] == [("KOMUNIKACJA", 7)]
    assert "Pokazano 6 z 6" in client.get("/asystent/teczka/E06").text


def test_empty_note_is_rejected(client, container):
    response = client.post("/asystent/teczka/E06/nowa", data={"observed_on": "2026-11-20", "body": "  "})
    assert response.status_code == 422
    assert "Wpisz opis sytuacji" in response.text
    assert len(container.notes.notes_for("E05", "E06")) == 5


def test_future_date_and_off_scale_rating_rejected(client):
    response = client.post(
        "/asystent/teczka/E06/nowa", data={"observed_on": "2026-12-01", "body": "x", "rating_KOMUNIKACJA": "4"}
    )
    assert response.status_code == 422
    assert "z przyszłości" in response.text and "1, 3, 5, 7 albo 9" in response.text


def test_edit_creates_version(client, container):
    page = client.get("/asystent/teczka/E06/notatka/N002/edytuj").text
    assert "wersja 2" in page
    response = client.post(
        "/asystent/teczka/E06/notatka/N002/edytuj",
        data={"observed_on": "2026-08-19", "body": "Poprawiony opis.", "improvements": "Informować wcześniej"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    timeline = client.get("/asystent/teczka/E06").text
    assert "Poprawiony opis." in timeline and "Poprzednie wersje (1)" in timeline
    # stara wersja nie jest już edytowalna
    assert client.get("/asystent/teczka/E06/notatka/N002/edytuj").status_code == 409
    assert len(services(container).notes_repo.history("E05", container.notes.notes_for("E05", "E06")[1].id)) == 2


def test_other_supervisor_cannot_see_or_add(client):
    client.get("/login/E04")
    assert client.get("/asystent/teczka/E06").status_code == 403
    assert client.post("/asystent/teczka/E06/nowa", data={"body": "x"}).status_code == 403
    assert client.get("/asystent/teczka/E06/notatka/N001/edytuj").status_code == 404


def test_unknown_person_is_404(client):
    response = client.get("/asystent/teczka/E99")
    assert response.status_code == 404
    assert "Nie ma takiej osoby" in response.text
