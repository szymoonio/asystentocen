"""Etapy oceny na stronie arkusza: 8 kroków w 4 fazach, osobny krok rozmowy oceniającej, panele asystenta HR."""

from __future__ import annotations

from datetime import date

from app.contracts.enums import EvaluationState
from app.core.api import STEPS


def login(client, employee_id):
    client.get(f"/login/{employee_id}")


def post(client, url, data=None):
    r = client.post(url, data=data or {}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert "error=" not in r.headers["location"], r.headers["location"]
    return r.headers["location"]


def test_steps_split_interview_from_assessment():
    assert STEPS == ["Rozmowa rozpoczynająca i kryteria", "Potwierdzenie kryteriów", "Okres oceny",
                     "Rozmowa oceniająca", "Ocena na piśmie", "Zapoznanie", "Sprzeciw (7 dni)", "Ostateczna"]


def test_stepper_phases_dates_and_tabs(client):
    login(client, "E05")
    page = client.get("/core/oceny/EV-E13-2026").text  # rozmowa 18.11.2026, ocena na piśmie w toku
    for phase in ("Początek", "W trakcie", "Zakończenie", "Po ocenie"):
        assert f'<div class="phase-name">{phase}</div>' in page
    assert "18.11.2026" in page.split('class="stepper"')[1].split("</nav>")[0]
    assert 'href="?krok=3"' in page and 'href="?krok=5"' not in page  # przyszłe kroki nie są zakładkami
    past = client.get("/core/oceny/EV-E13-2026?krok=3").text
    assert 'id="rozmowa"' in past and 'id="czesc-2"' not in past and "Oglądasz wcześniejszy etap" in past
    assert 'id="czesc-2"' in client.get("/core/oceny/EV-E13-2026?krok=7").text  # za daleko → bieżący krok


def test_criteria_step_collapsed_assistant_on_top_without_legal_refs(client):
    login(client, "E05")
    page = client.get("/core/oceny/EV-E09-2026").text
    main = page.split('<div class="main">')[1].split('<aside class="side">')[0]
    assert "Nazwa urzędu" not in main and "<dt>Oceniający</dt>" not in main
    assert "§" not in main and "art. " not in main
    assert "Do części I" not in page
    # asystent HR nad formularzem, domyślnie zwinięty (bez atrybutu open), w podsumowaniu tylko najważniejsze
    top = main.split('<details class="card coach hr-top" id="asystent-rozmowa">')[1].split("</details>")[0]
    assert main.index('id="asystent-rozmowa"') < main.index('id="czesc-1"')
    assert "Przeprowadź rozmowę rozpoczynającą" in top.split("</summary>")[0]
    assert "Jak poprowadzić rozmowę rozpoczynającą" in top and 'class="pipeline"' in top
    assert 'href="/asystent/hr/przygotowanie?rodzaj=rozpoczynajaca&amp;osoba=E09">Przygotuj szczegóły' in top
    assert "Jak poprowadzić" not in page.split('<aside class="side">')[1]
    assert "Rozmowa rozpoczynająca odbyła się" in main
    # trzy ponumerowane sekcje; kryteria obowiązkowe jako kafelki z opisem, dodatkowe jako karty do zaznaczenia
    form = main.split('id="part1"')[1].split("</form>")[0]
    assert form.count('class="p1-num"') == 3
    mandatory = form.split('<ul class="crit-tiles">')[1].split("</ul>")[0]
    assert mandatory.count('class="crit-tile"') >= 5 and 'class="crit-desc"' not in form  # same nazwy, opis w podpowiedzi
    assert form.count('type="checkbox" name="additional"') >= 5 and "<select" not in form


def test_confirmation_step_lists_criteria_separately(client, container):
    login(client, "E05")
    post(client, "/core/oceny/EV-E09-2026/kryteria", {
        "additional_0": "ORIENTACJA_NA_KLIENTA", "additional_1": "", "additional_2": "",
        "due_date": "2028-10-20", "place": "Warszawa", "confirm": "1",
    })
    login(client, "E09")
    page = client.get("/core/oceny/EV-E09-2026").text
    split = page.split('class="criteria-split"')[1]
    assert "Kryteria dodatkowe" in split and 'class="crit-tile extra"' in split and "Orientacja na klienta" in split
    coach = page.split('class="card coach"')[1].split("</section>")[0]
    assert "Potwierdź</a>" not in coach and "<a class=\"button" not in coach
    form = page.split('id="ack-criteria"')[1].split("</form>")[0]
    assert 'name="oswiadczenie" value="1" required' in form and "Oświadczam, że przeprowadzono ze mną rozmowę" in form
    assert ">Potwierdzam</button>" in form
    # bez zaznaczonego oświadczenia serwer nie przepuszcza dalej
    r = client.post("/core/oceny/EV-E09-2026/kryteria/potwierdz", data={"place": "Warszawa"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert container.evaluations.get("EV-E09-2026").state == EvaluationState.CRITERIA_CONFIRMED
    post(client, "/core/oceny/EV-E09-2026/kryteria/potwierdz", {"place": "Warszawa", "oswiadczenie": "1"})
    assert container.evaluations.get("EV-E09-2026").state == EvaluationState.OBSERVATION


def test_interview_is_its_own_step(client, container):
    login(client, "E05")
    ev = "EV-E07-2024"
    post(client, f"/core/oceny/{ev}/rozmowa/etap")
    assert container.evaluations.get(ev).state == EvaluationState.OBSERVATION  # rozmowa jeszcze się nie odbyła
    page = client.get(f"/core/oceny/{ev}").text
    assert 'id="rozmowa"' in page and "Umów termin z ocenianym" in page
    # panel asystenta HR na górze głównej kolumny (jak w „Okresie oceny”), rozwinięty
    main = page.split('<div class="main">')[1].split('<aside class="side">')[0]
    top = main.split('id="asystent-rozmowa"')[1].split("</details>")[0]
    assert main.index('id="asystent-rozmowa"') < main.index('id="rozmowa"')
    assert top.startswith(" open>")
    assert "Jak poprowadzić rozmowę oceniającą" in top and "rodzaj=oceniajaca" in top and "/przygotowanie" in top
    assert "Jak poprowadzić" not in page.split('<aside class="side">')[1]

    due = container.evaluations.get(ev).due_date
    planned = min(due, date(2026, 12, 1))
    post(client, f"/core/oceny/{ev}/rozmowa/termin", {"planned_on": planned.isoformat()})
    assert f"umówiona {planned:%d.%m.%Y}" in client.get(f"/core/oceny/{ev}").text
    login(client, "E07")
    assert f"{planned:%d.%m.%Y}" in client.get(f"/core/oceny/{ev}").text  # oceniany widzi termin

    login(client, "E05")
    post(client, f"/core/oceny/{ev}/rozmowa", {"interview_date": "2026-11-20",
                                              "interview_conclusions": "Chce rozwijać analizę danych."})
    assert container.evaluations.get(ev).state == EvaluationState.INTERVIEW_HELD
    page = client.get(f"/core/oceny/{ev}").text
    assert 'id="czesc-2"' in page and "Wnioski z rozmowy" in page and "Chce rozwijać analizę danych." in page
    login(client, "E07")  # wnioski z rozmowy są tylko dla oceniającego
    assert "Chce rozwijać analizę danych." not in client.get(f"/core/oceny/{ev}?krok=3").text


def test_interview_plan_validation(client):
    login(client, "E05")
    r = client.post("/core/oceny/EV-E07-2024/rozmowa/termin", data={"planned_on": "2026-01-01"}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_part1_checkbox_selection_saved(client, container):
    login(client, "E05")
    post(client, "/core/oceny/EV-E09-2026/kryteria", {"additional": ["ORIENTACJA_NA_KLIENTA", "KREATYWNOSC"],
                                                     "due_date": "2028-10-20", "place": "Warszawa"})
    ev = container.evaluations.get("EV-E09-2026")
    assert [c.code for c in ev.criteria if not c.mandatory] == ["ORIENTACJA_NA_KLIENTA", "KREATYWNOSC"]
    page = client.get("/core/oceny/EV-E09-2026").text
    assert 'value="KREATYWNOSC" checked' in page and "wybrano 2 z 3" in page
    r = client.post("/core/oceny/EV-E09-2026/kryteria", data={"additional": ["KREATYWNOSC", "ORIENTACJA_NA_KLIENTA",
                    "NEGOCJOWANIE", "MYSLENIE_ANALITYCZNE"]}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_print_has_empty_signature_space_after_part_two(client):
    login(client, "E05")
    page = client.get("/core/oceny/EV-E13-2026/druk").text
    sig = page.split('<section class="signatures"')[1].split("</section>")[0]
    assert "podpis oceniającego" in sig and "podpis ocenianego" in sig and sig.count('class="box"></div>') == 2
    assert page.index("CZĘŚĆ II") < page.index('<section class="signatures"')


def test_previous_assessment_filled_from_history(client, container):
    login(client, "E05")
    page = client.get("/core/oceny/EV-E13-2026").text  # urzędniczka, poprzednia ocena 02.12.2024
    box = page.split('class="prev-auto"')[1].split("Uzupełnione automatycznie")[0]
    assert "pozytywna" in box and "powyżej oczekiwań" in box and "02.12.2024" in box
    assert "Uzupełnione automatycznie z historii" in page and 'href="/core/oceny/EV-E13-2024"' in page
    assert 'name="prev_outcome"' not in page and 'name="prev_assessed_on"' not in page  # bez ręcznego wpisywania
    # ręcznie podesłane dane są ignorowane — przy zapisie liczymy je z historii
    post(client, "/core/oceny/EV-E13-2026/ocena", {"prev_outcome": "NEGATYWNA", "prev_assessed_on": "2020-01-01"})
    with container.session_factory() as s:
        from app.core.models import EvaluationRow
        prev = s.get(EvaluationRow, "EV-E13-2026").form["previous"]
    assert prev["outcome"] == "POZYTYWNA" and prev["assessed_on"] == "2024-12-02" and prev["from_history"]
    assert "02.12.2024" in client.get("/core/oceny/EV-E13-2026/druk").text
    # po zatwierdzeniu sekcja też jest widoczna (tylko do odczytu)
    post(client, "/core/oceny/EV-E13-2026/ocena", {
        **{f"p_{code}": "7" for code in ("WYKORZYSTYWANIE_WIEDZY", "RZETELNOSC", "ORGANIZACJA_PRACY", "WSPOLPRACA",
                                          "KOMUNIKACJA", "MYSLENIE_ANALITYCZNE")},
        "justification": "x", "iprz": "y", "promotion_choice": "NIE", "part2_place_evaluator": "Warszawa", "submit": "1"})
    page = client.get("/core/oceny/EV-E13-2026").text
    assert "Dane dotyczące poprzedniej oceny" in page and "02.12.2024" in page.split('class="prev-auto"')[1]
