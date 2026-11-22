"""Strony teczki: lista, oś czasu, formularz, edycja, dostęp."""

from __future__ import annotations

from app.assistant.services import services


def test_list_shows_subordinates_with_verbal_last_note(client):
    page = client.get("/asystent/teczka").text
    for name in ["Grzegorz Wzór", "Ewa Rzetelna", "Zofia Nowicka", "Tomasz Młodszy"]:
        assert name in page
    assert "7 miesięcy temu" in page  # Ewa: ostatnia notatka 15.04.2026
    assert "brak notatek" in page  # Zofia
    assert "nie podlega ocenie" in page  # Tomasz
    assert "Przypomnienia w tym tygodniu" not in page  # przypomnienia są na pulpicie, nie w teczce
    assert 'class="t-row t-stale"' in page and "/asystent/notatka/nowa?osoba=E07" in page


def _names_in_order(page, names):
    rows = page[page.index('id="t-rows"'):]  # pomijamy menu użytkowników demo w nagłówku
    return sorted(names, key=rows.index)


def test_list_search_and_sort(client):
    names = ["Grzegorz Wzór", "Ewa Rzetelna", "Zofia Nowicka", "Tomasz Młodszy"]
    alpha = client.get("/asystent/teczka").text
    assert _names_in_order(alpha, names) == ["Tomasz Młodszy", "Zofia Nowicka", "Ewa Rzetelna", "Grzegorz Wzór"]
    oldest = client.get("/asystent/teczka?sort=najdawniej").text
    first_two = _names_in_order(oldest, names)[:2]
    assert set(first_two) == {"Tomasz Młodszy", "Zofia Nowicka"}  # bez notatek najpierw
    newest = client.get("/asystent/teczka?sort=najnowsze").text
    assert _names_in_order(newest, names)[0] == "Grzegorz Wzór"
    found = client.get("/asystent/teczka?q=rzetel").text
    rows = found[found.index('id="t-rows"'):]
    assert "Ewa Rzetelna" in rows and "Zofia Nowicka" not in rows


def test_timeline_and_means(client):
    page = client.get("/asystent/teczka/E06").text
    assert "Pokazano 5 z 5 notatek" in page
    assert "Bieżący okres oceny" in page and 'class="t-score l' in page
    assert "brak obserwacji" in page  # Organizacja pracy bez suwaka
    assert "Oceny w czasie" not in page and "charts.js" not in page  # wykres tylko w Analizie zespołu
    assert ">Notatki</a>" in page and "← Notatki" in page and "<title>Notatki · " in page  # dawniej „Teczka”
    assert "głosowa" not in page  # notatek głosowych na razie nie wspieramy — bez znacznika


def test_quick_note_picker_then_form(client):
    page = client.get("/asystent/notatka/nowa").text
    assert "O kim?" in page and "/asystent/notatka/nowa?osoba=E07" in page
    assert 'name="body"' not in page  # formularz dopiero po wyborze osoby
    form = client.get("/asystent/notatka/nowa?osoba=E07").text
    assert 'action="/asystent/teczka/E07/nowa"' in form and 'aria-current="true"' in form
    assert client.get("/asystent/notatka/nowa?osoba=E10").status_code == 403  # nie podwładny


def test_form_shows_current_criteria_and_unset_sliders(client):
    page = client.get("/asystent/teczka/E06/nowa").text
    assert "Orientacja na klienta/interesanta" in page  # kryterium dodatkowe tej oceny
    assert 'name="rating_KOMUNIKACJA" value="" checked' in page  # domyślnie „brak”
    assert "Punktowa ocena kryteriów" in page and "brak danych — nie wlicza się do zestawienia" in page
    assert "Inne kryteria z katalogu" not in page and 'name="rating_KREATYWNOSC"' in page  # dodatkowe tej oceny
    assert 'name="rating_NEGOCJOWANIE"' not in page  # spoza oceny — bez suwaka


def test_form_before_criteria_set_shows_mandatory_only(client):
    page = client.get("/asystent/teczka/E09/nowa").text
    assert "Kryteria nie są jeszcze ustalone" in page
    assert "Inne kryteria z katalogu" not in page


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


def test_edit_keeps_rating_on_criterion_outside_evaluation(client, container):
    """Starsza notatka może mieć suwak spoza bieżącej oceny — poprawka nie może go skasować."""
    client.post("/asystent/teczka/E06/nowa", data={"observed_on": "2026-11-20", "body": "Rozmowa z kontrahentem.",
                                                   "rating_NEGOCJOWANIE": "7"})
    note = next(n for n in container.notes.notes_for("E05", "E06") if n.body == "Rozmowa z kontrahentem.")
    form = client.get(f"/asystent/teczka/E06/notatka/{note.id}/edytuj").text
    assert 'name="rating_NEGOCJOWANIE" value="7" checked' in form
    assert 'name="rating_ZARZADZANIE_LUDZMI"' not in form


def test_timeline_shows_evaluation_that_opened_current_cycle(client):
    page = client.get("/asystent/teczka/E06").text  # domyślnie bieżący cykl (ponowna ocena)
    assert 'id="EV-E06-2026"' in page and "Ocena okresowa" in page  # negatywna, która otworzyła ten cykl
    assert "Poniżej oczekiwań" in page and "średnia 3,86" in page and 'href="/core/oceny/EV-E06-2026"' in page
    assert 'id="EV-E06-2024"' not in page  # starsza — tylko przy „wszystkie”
    assert "Pokazano 5 z 5 notatek i 1 ocenę okresową" in page


def test_timeline_filter_periodic_evaluations_only(client):
    page = client.get("/asystent/teczka/E14?rodzaj=oceny").text
    assert 'value="oceny" selected' in page
    assert 'id="EV-E14-2023"' in page and 'id="EV-E14-2025"' in page
    assert 'class="t-note" id="N' not in page  # same oceny, bez notatek
    assert "2 oceny okresowe" in page
    everything = client.get("/asystent/teczka/E14?cykl=").text
    assert 'id="EV-E14-2023"' in everything and 'class="t-note" id="N' in everything


def test_criterion_filter_hides_evaluations(client):
    page = client.get("/asystent/teczka/E14?cykl=&kryterium=KOMUNIKACJA").text
    assert 'id="EV-E14-2023"' not in page
