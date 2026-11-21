"""Detektor danych wrażliwych i pseudonimizacja (round-trip)."""

from __future__ import annotations

import pytest

from app.assistant.privacy import Pseudonymizer, detect, is_sensitive, name_forms, screen_notes


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Od tygodnia jest na L4.", "ZDROWIE"),
        ("Wspomniała, że jest w ciąży.", "CIAZA_RODZICIELSTWO"),
        ("Przechodzi rozwód, stąd gorszy okres.", "ZYCIE_PRYWATNE"),
        ("W piątki wychodzi wcześniej na mszę.", "RELIGIA"),
        ("Dyskutował o poglądach politycznych przy interesancie.", "POGLADY_POLITYCZNE"),
        ("Jest w związku zawodowym.", "ZWIAZKI_ZAWODOWE"),
        ("Komentował narodowość klienta.", "POCHODZENIE"),
        ("Przyszedł nietrzeźwy.", "NALOGI"),
        ("Ma sprawę w prokuraturze.", "KARALNOSC"),
        ("Komornik zajął mu pensję.", "FINANSE_PRYWATNE"),
        ("Wraca po leczeniu w szpitalu.", "ZDROWIE"),
    ],
)
def test_detects_sensitive_categories(text, category):
    assert category in {h.category for h in detect(text)}


@pytest.mark.parametrize(
    "text",
    [
        "Tłumaczenie umowy ramowej oddane w terminie, bez uwag weryfikatora.",
        "Wybór tłumacza przysięgłego do partii dokumentów.",
        "Długi termin realizacji, ale bez opóźnień.",
        "Pierwszy tydzień po powrocie z długiej nieobecności.",
        "Dobra organizacja pracy i współpraca z Wydziałem Kadr.",
    ],
)
def test_work_notes_are_not_flagged(text):
    assert not is_sensitive(text)


def test_seed_notes_are_clean_and_screening_excludes(seed):
    assert screen_notes(seed.notes).excluded == []
    risky = seed.notes[0].model_copy(update={"body": "Był na zwolnieniu lekarskim."})
    result = screen_notes([risky, seed.notes[1]])
    assert [n.id for n in result.included] == [seed.notes[1].id]
    assert "zdrowie" in result.excluded[0].warning


def test_name_forms():
    assert {"Grzegorza", "Grzegorzem", "Grzegorzowi"} <= name_forms("Grzegorz")
    assert {"Ewy", "Ewie", "Ewę", "Ewą"} <= name_forms("Ewa")
    assert {"Wzora", "Wzorem"} <= name_forms("Wzór")
    assert {"Marka", "Markiem"} <= name_forms("Marek")
    assert {"Rzetelnej", "Rzetelną"} <= name_forms("Rzetelna")
    assert {"Długiego", "Długim"} <= name_forms("Długi")
    assert "Magdzie" in name_forms("Magda") and "Barbarze" in name_forms("Barbara")


@pytest.fixture
def people(seed):
    return seed.employees


def test_round_trip_with_inflection_and_contacts(people):
    session = Pseudonymizer(people).session()
    grzegorz = next(e for e in people if e.id == "E06")
    assert session.label_for(grzegorz) == "[OSOBA_1]"  # oceniany zawsze pierwszy

    text = (
        "Rozmawiałem z Grzegorzem Wzorem i z Ewą. Pan Wzór zadzwonił do Magdy Kadrowej "
        "(tel. +48 601 234 567, magda.kadrowa@przyklady.example, PESEL 90010112345)."
    )
    out = session.apply(text)
    for leaked in ("Grzegorz", "Wzor", "Wzór", "Ewą", "Magd", "Kadrow", "601", "@", "90010112345"):
        assert leaked not in out, leaked
    assert out.count("[OSOBA_1]") == 2
    restored = session.restore("Podsumowanie: [OSOBA_1] współpracował z [OSOBA_2]. Kontakt: [TELEFON_1].")
    assert "Grzegorz Wzór" in restored and "+48 601 234 567" in restored
    assert session.restore("[OSOBA_99] bez zmian") == "[OSOBA_99] bez zmian"


def test_labels_are_stable_across_texts_in_session(people):
    session = Pseudonymizer(people).session()
    a = session.apply("Ewa przygotowała glosariusz.")
    b = session.apply("Ewie podziękowałem, a Grzegorz pomógł.")
    assert a.startswith("[OSOBA_1]") and b.startswith("[OSOBA_1]")
    assert "[OSOBA_2]" in b


def test_ambiguous_first_name_only_replaced_in_full(people):
    twin = people[5].model_copy(update={"id": "E99", "last_name": "Inny"})  # drugi Grzegorz
    session = Pseudonymizer([*people, twin]).session()
    out = session.apply("Grzegorz pomógł. Grzegorz Inny też.")
    assert out.startswith("Grzegorz pomógł") and "[OSOBA_1] też" in out
