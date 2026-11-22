"""Podsumowanie cyklu: dowody, szkielet bez LLM, walidator cytowań, projekt LLM, DraftProvider."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.assistant.llm import LLMRateLimited
from app.assistant.notes.repository import NoteInput
from app.assistant.services import services
from app.assistant.summarize import skeleton
from app.assistant.summarize.evidence import _low_criteria
from app.assistant.summarize.llm_summary import CycleSummary
from app.assistant.summarize.provider import AssistantDraftProvider
from app.assistant.summarize.validate import validate_paragraph
from app.contracts.enums import DraftField, EvaluationState, Level, Outcome, SheetType
from app.contracts.models import CriterionRating, CriterionStats, EvaluationResult, EvaluationSummary
from app.contracts.ports import DraftProvider
from app.contracts.regulation import load_scale

NOW = datetime(2026, 11, 21, 12, 0)
GRZEGORZ_EV = "EV-E06-2026R"
EWA_EV = "EV-E07-2024"


@pytest.fixture
def svc(container):
    return services(container)


def add_note(svc, body, *, subject="E06", ev=GRZEGORZ_EV, **kw):
    return svc.notes_repo.create(
        author_id="E05", subject_id=subject, evaluation_id=ev, data=NoteInput(observed_on=date(2026, 11, 20), body=body, **kw), now=NOW
    )


# --- dowody i szkielet ---------------------------------------------------------------------


def test_evidence_for_grzegorz(svc):
    ev = svc.drafts.evidence(GRZEGORZ_EV)
    assert ev.author_id == "E05" and ev.subject.id == "E06"
    assert [n.id for n in ev.notes] == ["N001", "N002", "N003", "N004", "N005"]
    assert ev.excluded == [] and ev.low_criteria == []
    groups = ev.by_criterion()
    assert groups["ORGANIZACJA_PRACY"] == []  # brak obserwacji
    assert {i.note_id for i in groups["KOMUNIKACJA"]} == {"N002", "N005"}  # z suwaków (bez podpowiedzi LLM)


def test_evidence_excludes_sensitive_notes(svc):
    add_note(svc, "Spóźnienia wynikają z leczenia w szpitalu.")
    ev = svc.drafts.evidence(GRZEGORZ_EV)
    assert len(ev.notes) == 5 and len(ev.excluded) == 1
    assert all("szpital" not in i.text for i in ev.items)


def test_evidence_uses_criteria_hints(svc):
    svc.notes_repo.save_hints("N004", [{"item": "Terminowość", "kind": "strength", "criterion_code": "ORGANIZACJA_PRACY"}], "fake", NOW)
    ev = svc.drafts.evidence(GRZEGORZ_EV)
    assert [i.text for i in ev.by_criterion()["ORGANIZACJA_PRACY"]] == ["Terminowość"]
    assert ev.hints_used


def test_low_criteria_from_result_or_slider_median():
    ev = EvaluationSummary(id="X", employee_id="E06", evaluator_id="E05", sheet=SheetType.C, state=EvaluationState.INTERVIEW_HELD)
    with_result = ev.model_copy(
        update={
            "result": EvaluationResult(
                partial_points={"KOMUNIKACJA": 3, "WSPOLPRACA": 5}, mean_numerator=4, mean_denominator=1,
                level=Level.PONIZEJ, outcome=Outcome.POZYTYWNA, assessed_on=date(2026, 12, 1),
            )
        }
    )  # fmt: skip
    assert _low_criteria(with_result, []) == (["KOMUNIKACJA"], "ocena")
    stats = [CriterionStats(criterion_code="RZETELNOSC", n_ratings=2, distribution={3: 2}, median=3.0)]
    assert _low_criteria(ev, stats) == (["RZETELNOSC"], "notatki")


def test_skeleton_for_ewa_maps_low_criterion_to_catalog(svc):
    ev = svc.drafts.evidence(EWA_EV)
    assert ev.low_criteria == ["KOMUNIKACJA"] and ev.low_source == "notatki"
    paragraphs = skeleton.development(ev, {"KOMUNIKACJA": ["szkolenie A", "warsztat B"]})
    assert "komunikacja: szkolenie A; warsztat B" in paragraphs[0].text
    assert "do potwierdzenia po wpisaniu ocen" in paragraphs[0].text
    assert paragraphs[0].note_ids == ("N007",)


def test_input_key_changes_with_notes(svc):
    before = svc.drafts.evidence(GRZEGORZ_EV).input_key
    add_note(svc, "Oddał tłumaczenie przed terminem.")
    assert svc.drafts.evidence(GRZEGORZ_EV).input_key != before


# --- DraftProvider -------------------------------------------------------------------------


def test_container_uses_assistant_draft_provider(container):
    assert isinstance(container.drafts, AssistantDraftProvider)
    assert isinstance(container.drafts, DraftProvider) and container.drafts.available()


def test_deterministic_drafts_with_citations(container):
    uz = container.drafts.drafts(GRZEGORZ_EV, DraftField.UZASADNIENIE)
    assert [d.generator for d in uz] == ["deterministic:v1", "deterministic:v1"]
    assert uz[0].text.startswith("W ocenianym okresie odnotowano") and uz[0].citations == ["N001", "N003", "N004", "N005"]
    assert "Informować przełożonego o ryzyku" in uz[1].text and uz[1].citations == ["N002", "N005"]
    assert container.drafts.drafts(GRZEGORZ_EV, DraftField.WNIOSKI_IPRZ)
    assert container.drafts.drafts(GRZEGORZ_EV, DraftField.UMOTYWOWANIE_WNIOSKU) == []
    assert container.drafts.drafts("EV-NOPE", DraftField.UZASADNIENIE) == []
    assert container.drafts.drafts("EV-E01-2025", DraftField.UZASADNIENIE) == []  # oceniający spoza urzędu


# --- walidator ----------------------------------------------------------------------------

SOURCES = {"N1": "08.07.2026\n[OSOBA_1] sam zadzwonił do Wydziału Kadr i uzupełnił dokument w dwa dni", "N2": "19.08.2026\nNie przekazał informacji"}


@pytest.mark.parametrize(
    ("text", "refs", "reason"),
    [
        ("Osoba oceniana samodzielnie uzupełniła dokument.", [], "brak cytowanej notatki"),
        ("Osoba oceniana samodzielnie uzupełniła dokument.", ["N9"], "cytat spoza cyklu"),
        ("Współpracowała z [OSOBA_3].", ["N1"], "osoby spoza cytowanych notatek"),
        ("Sprawę zamknęła w 3 dni.", ["N1"], "liczby spoza cytowanych notatek"),
        ("Dlatego przyznaję ocenę negatywną.", ["N1"], "wynik oceny"),
        ("Za współpracę należy się 7 pkt.", ["N1"], "punkty oceny"),
        ("Problemy wynikały z depresji.", ["N1"], "dane wrażliwe"),
        ("x" * 1600, ["N1"], "za długi"),
    ],
)
def test_validator_rejects(text, refs, reason):
    verdict = validate_paragraph(text, refs, SOURCES)
    assert not verdict.ok and any(reason in r for r in verdict.reasons)


def test_subject_label_always_allowed():
    assert validate_paragraph("[OSOBA_1] nie przekazał informacji.", ["N2"], SOURCES).ok


def test_validator_accepts_grounded_paragraph():
    text = "W lipcu 2026 r. [OSOBA_1] sam uzupełnił dokument w Wydziale Kadr (08.07.2026), zamiast odsyłać wniosek."
    assert validate_paragraph(text, ["N1", "N1"], SOURCES).ok


# --- projekt LLM ---------------------------------------------------------------------------


def llm_summary(**kw):
    return CycleSummary.model_validate(
        {
            "justification": [
                {"text": "[OSOBA_1] samodzielnie uzupełnił dokument we współpracy z Wydziałem Kadr.", "note_refs": ["N1"]},
                {"text": "Dlatego przyznaję ocenę negatywną.", "note_refs": ["N2"]},
                {"text": "Zmyślony akapit.", "note_refs": ["N42"]},
            ],
            "development": [{"text": "Proponuję rozwój w kierunku komunikacji z przełożonym o ryzykach.", "note_refs": ["N2", "N5"]}],
        }
    )


def test_generate_validates_restores_and_stores(svc, container, fake_llm):
    svc.llm = fake_llm({"summarize_cycle": llm_summary})
    ev = svc.drafts.evidence(GRZEGORZ_EV)
    result = svc.drafts.generate(
        ev, llm=svc.llm, catalog=container.catalog, scale=load_scale(container.settings.regulation_dir),
        pseudonymizer=svc.pseudonymizer(),
    )  # fmt: skip

    call = svc.llm.calls[0]
    assert "Grzegorz" not in call["user"] and "Wzór" not in call["user"]
    assert '<notatka id="N1" data="08.07.2026">' in call["user"]
    assert "Oceny cząstkowe nie są jeszcze wpisane" in call["user"]
    assert "### RZETELNOSC" in call["system"]

    assert [p.text for p in result.justification] == [
        "Grzegorz Wzór samodzielnie uzupełnił dokument we współpracy z Wydziałem Kadr."
    ]
    assert result.justification[0].note_ids == ("N001",)
    assert result.development[0].note_ids == ("N002", "N005")
    assert {r.text for r in result.rejected} == {"Dlatego przyznaję ocenę negatywną.", "Zmyślony akapit."}

    drafts = container.drafts.drafts(GRZEGORZ_EV, DraftField.UZASADNIENIE)
    assert [d.generator for d in drafts] == ["fake-model:summarize_cycle:v1"]
    assert drafts[0].citations == ["N001"]

    add_note(svc, "Nowa obserwacja po projekcie.")  # projekt LLM traci aktualność → szkielet
    assert container.drafts.drafts(GRZEGORZ_EV, DraftField.UZASADNIENIE)[0].generator == "deterministic:v1"


def test_result_points_are_sent_as_words_not_numbers(svc, container, fake_llm):
    from app.assistant.summarize.llm_summary import build_request

    ev = svc.drafts.evidence(GRZEGORZ_EV)
    ev.evaluation = ev.evaluation.model_copy(
        update={
            "result": EvaluationResult(
                partial_points={"KOMUNIKACJA": 3}, mean_numerator=3, mean_denominator=1,
                level=Level.PONIZEJ, outcome=Outcome.NEGATYWNA, assessed_on=date(2026, 12, 15),
            )
        }
    )  # fmt: skip
    _, user, *_ = build_request(
        ev, catalog=container.catalog, scale=load_scale(container.settings.regulation_dir),
        actions={}, pseudonymizer=svc.pseudonymizer(),
    )  # fmt: skip
    assert "Komunikacja: poniżej oczekiwań" in user
    assert "NEGATYWNA" not in user


# --- strony --------------------------------------------------------------------------------


def test_summary_page_without_llm(client):
    page = client.get(f"/asystent/podsumowanie/{GRZEGORZ_EV}").text
    assert "Asystent nie proponuje ocen cząstkowych ani wyniku" in page
    assert "szkielet bez AI" in page and "brak obserwacji" in page
    assert "Przygotuj projekt z asystentem" not in page
    assert "Podsumowanie cyklu" in client.get("/asystent/teczka/E06").text


def test_summary_page_only_for_evaluator(client):
    assert client.get("/asystent/podsumowanie/EV-E10-2025").status_code == 403  # oceniającym jest E04
    assert client.get("/asystent/podsumowanie/EV-NOPE").status_code == 404
    client.get("/login/E04")
    assert client.get(f"/asystent/podsumowanie/{GRZEGORZ_EV}").status_code == 403


def test_generate_from_page(client, container, fake_llm):
    services(container).llm = fake_llm({"summarize_cycle": llm_summary})
    assert "Przygotuj projekt z asystentem" in client.get(f"/asystent/podsumowanie/{GRZEGORZ_EV}").text
    response = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/generuj", follow_redirects=False)
    assert response.status_code == 303
    page = client.get(f"/asystent/podsumowanie/{GRZEGORZ_EV}").text
    assert "projekt AI" in page and "Grzegorz Wzór samodzielnie uzupełnił" in page
    assert "Akapity odrzucone przez walidator (2)" in page


def test_generate_error_is_shown(client, container, fake_llm):
    services(container).llm = fake_llm({"summarize_cycle": LLMRateLimited("x")})
    response = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/generuj")
    assert response.status_code == 502 and "przeciążony" in response.text


def test_ratings_unchanged_by_summary(svc):
    assert svc.notes_repo.get("E05", "N002").ratings == [CriterionRating(criterion_code="KOMUNIKACJA", value=3)]


# --- krótkie sugestie do panelu asystenta przy polach arkusza (strona oceny, moduł A) ----------


def test_suggestions_json_with_llm(client, container, fake_llm):
    services(container).llm = fake_llm({"summarize_cycle": llm_summary})
    data = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie").json()
    assert data["ok"] and data["generator"] == "fake-model:summarize_cycle:v1"
    assert data["justification"][0]["text"].startswith("Grzegorz Wzór samodzielnie uzupełnił")
    assert data["justification"][0]["notes"][0]["url"].startswith("/asystent/teczka/E06?cykl=#")
    assert len(data["justification"]) == 1 and len(data["iprz"]) == 1  # jedna propozycja na pole


def test_suggestions_without_llm_are_short_skeleton(client):
    data = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie").json()
    assert data["ok"] and data["generator"].startswith("deterministic")
    assert len(data["justification"]) == 1 and len(data["iprz"]) == 1
    assert all(len(p["text"]) <= 602 for p in data["justification"] + data["iprz"])


def test_suggestions_only_for_evaluator_and_errors_as_json(client, container, fake_llm):
    client.get("/login/E04")
    r = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie")
    assert r.status_code == 403 and r.json()["ok"] is False
    client.get("/login/E05")
    services(container).llm = fake_llm({"summarize_cycle": LLMRateLimited("x")})
    r = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie")
    assert r.status_code == 502 and "przeciążony" in r.json()["error"]


def test_suggestion_for_one_field_only(client, container, fake_llm):
    svc = services(container)
    svc.llm = fake_llm({"summarize_cycle": llm_summary})
    data = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie?pole=iprz").json()
    assert data["ok"] and len(data["iprz"]) == 1 and "justification" not in data
    assert "TYLKO pole `development`, jako JEDEN" in svc.llm.calls[-1]["user"]
    # potem uzasadnienie: projekt IPRZ z poprzedniego wywołania zostaje w zapisanym projekcie
    data = client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie?pole=justification").json()
    assert data["justification"] and "iprz" not in data
    stored = svc.drafts.stored(GRZEGORZ_EV).result
    assert stored.justification and stored.development
    assert client.post(f"/asystent/podsumowanie/{GRZEGORZ_EV}/sugestie?pole=x").status_code == 400
