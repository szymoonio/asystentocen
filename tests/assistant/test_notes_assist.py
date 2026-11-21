"""Notatki z LLM: podział na zalety/obszary i klasyfikacja do kryteriów (fake LLM, bez sieci)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.assistant.llm import LLMRefusal
from app.assistant.llm.prompts import load_prompt
from app.assistant.notes.assist import (
    Classification,
    SplitProposal,
    catalog_prompt,
    classify_note,
    note_items,
    split_note,
)
from app.assistant.notes.repository import NoteInput
from app.assistant.services import services

NOW = datetime(2026, 11, 21, 12, 0)


@pytest.fixture
def svc(container):
    return services(container)


@pytest.fixture
def grzegorz(container):
    return container.employees.get("E06")


# --- split_note ---------------------------------------------------------------------------


def test_split_pseudonymizes_input_and_restores_output(svc, grzegorz, fake_llm):
    svc.llm = fake_llm(
        {
            "split_note": SplitProposal(
                strengths=["[OSOBA_1] sam zgłosił ryzyko", "- Propozycja podziału pracy", "[OSOBA_1] sam zgłosił ryzyko"],
                improvements=["Uprzedzać [OSOBA_2] wcześniej"],
            )
        }
    )
    text = "Grzegorz sam zgłosił ryzyko opóźnienia i zaproponował podział pracy, ale Ewa dowiedziała się za późno."
    outcome = split_note(svc, grzegorz, text)

    call = svc.llm.calls[0]
    assert "Grzegorz" not in call["user"] and "Ewa" not in call["user"]
    assert call["user"].startswith("[OSOBA_1] sam zgłosił")
    assert call["system"] == load_prompt("split_note").text
    assert outcome.error is None
    assert outcome.strengths == ["Grzegorz Wzór sam zgłosił ryzyko", "Propozycja podziału pracy"]
    assert outcome.improvements == ["Uprzedzać Ewa Rzetelna wcześniej"]


def test_split_refuses_sensitive_text_without_calling_llm(svc, grzegorz, fake_llm):
    svc.llm = fake_llm({"split_note": SplitProposal(strengths=["x"], improvements=[])})
    outcome = split_note(svc, grzegorz, "Spóźnił się, bo był u lekarza z powodu depresji.")
    assert outcome.error and "dane wrażliwe" in outcome.error and "zdrowie" in outcome.error
    assert svc.llm.calls == []


def test_split_empty_text(svc, grzegorz, fake_llm):
    svc.llm = fake_llm({"split_note": SplitProposal(strengths=[], improvements=[])})
    assert split_note(svc, grzegorz, "   ").error.startswith("Wpisz opis")
    assert svc.llm.calls == []


def test_split_llm_error_becomes_user_message(svc, grzegorz, fake_llm):
    svc.llm = fake_llm({"split_note": LLMRefusal("x")})
    outcome = split_note(svc, grzegorz, "Oddał tłumaczenie w terminie.")
    assert "Wydziałem Kadr" in outcome.error


# --- classify_note ------------------------------------------------------------------------


def test_note_items_and_catalog_prompt(container, seed):
    note = next(n for n in seed.notes if n.id == "N005")
    assert [i[0] for i in note_items(note)] == ["B", "S1", "I1", "I2"]  # seed dzieli punkt N005 na dwa
    prompt = catalog_prompt(container.catalog)
    assert prompt.count("### ") == 14 and "WSPOLPRACA — Współpraca" in prompt


def test_classify_saves_valid_hints(svc, container, grzegorz, fake_llm):
    svc.llm = fake_llm(
        {
            "classify_note": Classification.model_validate(
                {
                    "items": [
                        {"id": "B", "criteria": ["WSPOLPRACA"]},
                        {"id": "S1", "criteria": ["WSPOLPRACA", "NIEISTNIEJACE", "ORGANIZACJA_PRACY", "RZETELNOSC"]},
                        {"id": "X9", "criteria": ["KOMUNIKACJA"]},
                    ]
                }
            )
        }
    )
    note = svc.notes_repo.get("E05", "N001")
    hints = classify_note(svc, container.catalog, note, grzegorz, NOW)

    call = svc.llm.calls[0]
    assert "### KOMUNIKACJA" in call["system"] and "Grzegorz" not in call["user"]
    assert call["user"].splitlines()[1].startswith("S1: Samodzielnie skontaktował się")
    assert [(h["kind"], h["criterion_code"]) for h in hints] == [
        ("body", "WSPOLPRACA"), ("strength", "WSPOLPRACA"), ("strength", "ORGANIZACJA_PRACY"),
    ]  # fmt: skip
    stored = svc.notes_repo.hints_for(["N001", "N002"])
    assert list(stored) == ["N001"] and stored["N001"] == hints


def test_classify_skips_sensitive_and_disabled(svc, container, grzegorz, fake_llm):
    svc.llm = fake_llm({"classify_note": Classification(items=[])})
    sensitive = svc.notes_repo.get("E05", "N001").model_copy(update={"body": "Wrócił ze szpitala."})
    assert classify_note(svc, container.catalog, sensitive, grzegorz, NOW) is None
    assert svc.llm.calls == []
    svc.llm = fake_llm({})  # zadanie wyłączone
    assert classify_note(svc, container.catalog, svc.notes_repo.get("E05", "N001"), grzegorz, NOW) is None


def test_hints_count_towards_coverage_nudge(svc, container):
    digest = svc.note_nudges.digest_for("E05", date(2026, 11, 21))
    before = next(p for p in digest.people if p.employee.id == "E06").findings[0].text
    assert "bez obserwacji: Organizacja pracy" in before
    svc.notes_repo.save_hints("N004", [{"item": "Terminowość", "kind": "strength", "criterion_code": "ORGANIZACJA_PRACY"}], "fake", NOW)
    digest = svc.note_nudges.digest_for("E05", date(2026, 11, 21))
    after = next(p for p in digest.people if p.employee.id == "E06").findings[0].text
    assert "bez obserwacji" not in after


# --- strony -------------------------------------------------------------------------------


def test_split_button_hidden_without_llm(client):
    assert "Podziel opis" not in client.get("/asystent/teczka/E06/nowa").text


def test_split_action_fills_form_without_saving(client, container, fake_llm):
    services(container).llm = fake_llm(
        {"split_note": SplitProposal(strengths=["Zgłosił ryzyko wcześnie"], improvements=["Dokładniejsze odpowiedzi"])}
    )
    assert "Podziel opis" in client.get("/asystent/teczka/E06/nowa").text
    response = client.post(
        "/asystent/teczka/E06/nowa",
        data={"akcja": "podziel", "observed_on": "2026-11-20", "body": "Zgłosił ryzyko.", "strengths": "Własny punkt"},
    )
    assert response.status_code == 200
    page = response.text
    assert "Własny punkt\nZgłosił ryzyko wcześnie</textarea>" in page
    assert "Dokładniejsze odpowiedzi</textarea>" in page
    assert "Sprawdź i popraw punkty przed zapisem" in page
    assert len(container.notes.notes_for("E05", "E06")) == 5  # nic nie zapisano


def test_split_action_shows_sensitive_warning(client, container, fake_llm):
    services(container).llm = fake_llm({"split_note": SplitProposal(strengths=["x"], improvements=[])})
    page = client.post(
        "/asystent/teczka/E06/nowa", data={"akcja": "podziel", "body": "Jest w ciąży, więc pracuje krócej."}
    ).text
    assert "dane wrażliwe" in page and "ciąża" in page


def test_save_classifies_in_background_and_shows_hint(client, container, fake_llm):
    svc = services(container)
    svc.llm = fake_llm(
        {"classify_note": Classification.model_validate({"items": [{"id": "S1", "criteria": ["KOMUNIKACJA"]}]})}
    )
    response = client.post(
        "/asystent/teczka/E06/nowa",
        data={"akcja": "zapisz", "observed_on": "2026-11-20", "strengths": "Jasno wyjaśnił procedurę interesantowi"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    new = container.notes.notes_for("E05", "E06")[-1]
    assert svc.notes_repo.hints_for([new.id])[new.id][0]["criterion_code"] == "KOMUNIKACJA"
    assert new.ratings == []  # LLM nie ustawia suwaków
    assert "Asystent: dotyczy Komunikacja" in client.get("/asystent/teczka/E06").text


def test_revision_is_classified_again(client, container, fake_llm):
    svc = services(container)
    svc.llm = fake_llm({"classify_note": Classification.model_validate({"items": [{"id": "B", "criteria": ["RZETELNOSC"]}]})})
    client.post(
        "/asystent/teczka/E06/notatka/N004/edytuj",
        data={"akcja": "zapisz", "observed_on": "2026-10-14", "body": "Umowa oddana w terminie."},
    )
    revised = container.notes.notes_for("E05", "E06")[3]
    assert revised.supersedes_id == "N004"
    assert svc.notes_repo.hints_for([revised.id])
