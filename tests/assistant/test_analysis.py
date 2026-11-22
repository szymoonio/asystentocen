"""Zakładka Analiza i wspólne elementy widoków (czas słownie, średnie w kolorze poziomu)."""

from __future__ import annotations

import re
from datetime import date
from fractions import Fraction

import pytest

from app.assistant.display import ago, mean_of, trend
from app.assistant.llm import LLMRateLimited
from app.assistant.services import services
from app.contracts.regulation import load_scale

TODAY = date(2026, 11, 21)


@pytest.mark.parametrize(
    ("day", "text"),
    [(None, "brak notatek"), (TODAY, "dziś"), (date(2026, 11, 20), "wczoraj"), (date(2026, 11, 7), "2 tygodnie temu"),
     (date(2026, 10, 3), "7 tygodni temu"), (date(2026, 4, 15), "7 miesięcy temu"), (date(2025, 6, 1), "ponad rok temu")],
)
def test_ago(day, text):
    assert ago(day, TODAY) == text


def test_mean_tones_follow_paragraph_11_bands(container):
    scale = load_scale(container.settings.regulation_dir)
    assert mean_of([], scale) is None
    m = mean_of([5, 7, 7], scale)
    assert m.value == Fraction(19, 3) and m.text == "6,3" and m.tone == "l4" and m.count == "3 oceny"
    assert mean_of([1, 3], scale).tone == "l1"  # 2 → „znacznie poniżej” (przedział 1–2)
    assert mean_of([3, 5], scale).tone == "l2"  # 4 → „poniżej”
    assert mean_of([9], scale).tone == "l5"


def test_trend_needs_four_ratings():
    d = date(2026, 1, 1)
    assert trend([(d, 3, "a"), (d, 7, "b")]) == ""
    assert trend([(d, 3, "a"), (d, 3, "b"), (d, 7, "c"), (d, 7, "d")]) == "up"
    assert trend([(d, 7, "a"), (d, 7, "b"), (d, 5, "c"), (d, 7, "d")]) == "down"


# --- strony ------------------------------------------------------------------------------


def test_team_view_without_llm(client):
    page = client.get("/asystent/analiza").text
    assert "Analiza" in page and 'aria-current="page">Zespół' in page
    assert "Kryteria — średnia zespołu" in page and "Osoby × kryteria" in page
    assert "Notatki w czasie" in page
    widths = re.findall(r'class="a-bar l\d" style="width: ([^%]*)%"', page)
    assert widths and all(re.fullmatch(r"\d+(\.\d+)?", w) for w in widths)  # liczba, nie ułamek „700/9”
    assert "wymaga asystenta LLM" in page  # brak klucza → bez przycisku generowania
    assert "Wygeneruj analizę" not in page


def test_person_view(client):
    page = client.get("/asystent/analiza?widok=osoba&osoba=E06").text
    assert 'aria-current="page">Osoba' in page
    assert "Grzegorz Wzór" in page and "Oceny w czasie" in page and "Co poszło dobrze" in page


def test_only_own_subordinates(client):
    assert client.get("/asystent/analiza?widok=osoba&osoba=E10").status_code == 403
    client.get("/login/E07")  # bez podwładnych
    assert client.get("/asystent/analiza").status_code == 403


def _analysis(*, user: str, **_):
    assert "Grzegorz" not in user and "Wzór" not in user  # pseudonimizacja przed wysłaniem
    assert "[OSOBA_1]" in user
    return {
        "summary": "[OSOBA_1] wyraźnie poprawia komunikację.",
        "strengths": [{"text": "Rzetelne przygotowanie dokumentów.", "note_refs": ["N1"]},
                      {"text": "Zmyślona mocna strona.", "note_refs": []}],
        "weaknesses": [{"text": "Informowanie o opóźnieniach.", "note_refs": ["N2", "N99"]}],
        "recommendations": [{"text": "Krótka rozmowa o priorytetach.", "note_refs": []}],
    }


def test_generate_person_analysis(client, container, fake_llm):
    services(container).llm = fake_llm({"analyze_person": _analysis})
    page = client.get("/asystent/analiza?widok=osoba&osoba=E06").text
    assert "Poproś asystenta o podsumowanie" in page
    response = client.post("/asystent/analiza/generuj", data={"widok": "osoba", "osoba": "E06"}, follow_redirects=False)
    assert response.status_code == 303 and "blad" not in response.headers["location"]
    page = client.get("/asystent/analiza?widok=osoba&osoba=E06").text
    assert "Grzegorz Wzór wyraźnie poprawia komunikację." in page  # etykieta odwrócona lokalnie
    assert "Rzetelne przygotowanie dokumentów." in page
    assert "Zmyślona mocna strona." not in page  # bez źródła w notatkach — odrzucona
    assert "Odrzucono 1 punkty" in page
    assert "Odśwież podsumowanie" in page and "/asystent/teczka/E06?cykl=#" in page


def test_generate_team_analysis(client, container, fake_llm):
    def team(*, user: str, **_):
        assert "Ewa" not in user and "Rzetelna" not in user
        return {"summary": "Zespół dobrze współpracuje.", "strengths": [], "weaknesses": [], "recommendations": []}

    services(container).llm = fake_llm({"analyze_team": team})
    client.post("/asystent/analiza/generuj", data={"widok": "zespol"})
    assert "Zespół dobrze współpracuje." in client.get("/asystent/analiza").text


def test_generate_error_is_shown(client, container, fake_llm):
    services(container).llm = fake_llm({"analyze_team": LLMRateLimited()})
    response = client.post("/asystent/analiza/generuj", data={"widok": "zespol"}, follow_redirects=False)
    assert "blad=" in response.headers["location"]
    page = client.get(response.headers["location"]).text
    assert "przeciążony" in page


def test_analysis_tasks_in_repo_config(container):
    from app.assistant.llm import LLMConfig

    cfg = LLMConfig.load(container.settings.config_dir)
    assert {"analyze_person", "analyze_team"} <= set(cfg.tasks)


def test_team_analysis_is_in_main_menu_not_in_teczka(client):
    page = client.get("/asystent/analiza").text
    assert '<a href="/asystent/analiza" aria-current="page">Analiza zespołu</a>' in page
    teczka = client.get("/asystent/teczka").text
    assert '<a href="/asystent/analiza">Analiza zespołu</a>' in teczka  # pozycja menu
    assert 'class="button secondary" href="/asystent/analiza"' not in teczka  # bez przycisku w teczce
    client.get("/login/E07")  # bez podwładnych — bez pozycji w menu
    assert "Analiza zespołu" not in client.get("/core/").text


def test_summary_details_are_collapsed_and_sections_foldable(client, container, fake_llm):
    services(container).llm = fake_llm({"analyze_person": _analysis})
    client.post("/asystent/analiza/generuj", data={"widok": "osoba", "osoba": "E06"})
    page = client.get("/asystent/analiza?widok=osoba&osoba=E06").text
    assert '<details class="more a-details">' in page  # szczegóły zwinięte, podsumowanie widoczne
    assert 'class="card fold' in page and 'id="osoba-wykres" open' in page


def test_fragment_for_evaluation_page_and_return(client, container, fake_llm):
    services(container).llm = fake_llm({"analyze_person": _analysis})
    frag = client.get("/asystent/analiza/fragment?osoba=E06&wroc=/core/oceny/EV-E06-2026R").text
    assert "<html" not in frag and 'name="wroc" value="/core/oceny/EV-E06-2026R"' in frag
    response = client.post("/asystent/analiza/generuj",
                           data={"widok": "osoba", "osoba": "E06", "wroc": "/core/oceny/EV-E06-2026R"}, follow_redirects=False)
    assert response.headers["location"] == "/core/oceny/EV-E06-2026R#asystent-podsumowanie"
    assert "Grzegorz Wzór wyraźnie poprawia komunikację." in client.get("/asystent/analiza/fragment?osoba=E06").text


def test_return_address_must_stay_in_app(client, container, fake_llm):
    services(container).llm = fake_llm({"analyze_person": _analysis})
    for bad in ["//evil.example/x", "https://evil.example", "/\\evil"]:
        response = client.post("/asystent/analiza/generuj", data={"widok": "osoba", "osoba": "E06", "wroc": bad},
                               follow_redirects=False)
        assert response.headers["location"].startswith("/asystent/analiza"), bad


def test_grouped_points_count_repeats():
    from datetime import datetime

    from app.assistant.display import grouped_points
    from app.contracts.models import Note

    def note(i, day, strengths):
        return Note(id=f"X{i}", author_id="E05", subject_id="E06", observed_on=day, created_at=datetime(2026, 1, 1),
                    strengths=strengths)

    pts = grouped_points([note(1, date(2026, 1, 5), ["Terminowość"]), note(2, date(2026, 3, 5), ["terminowość ", "Inicjatywa"]),
                          note(3, date(2026, 2, 5), ["Inicjatywa"]), note(4, date(2026, 4, 5), ["Dokładność"])], "strengths")
    assert [(p.text, p.count) for p in pts] == [("Inicjatywa", 2), ("terminowość", 2), ("Dokładność", 1)]
    assert pts[1].note_id == "X2"  # najnowsza notatka z tym punktem
