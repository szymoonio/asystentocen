"""Asystent HR: granice, sygnały, baza wiedzy, przygotowanie, próba rozmowy, FUKO, procedury."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.assistant.config import NudgesConfig
from app.assistant.hr import fuko as fuko_mod
from app.assistant.hr import prep as prep_mod
from app.assistant.hr import qa as qa_mod
from app.assistant.hr import roleplay as rp
from app.assistant.hr.boundaries import HrConfig, check
from app.assistant.hr.knowledge import default_knowledge
from app.assistant.hr.signals import after_absence, signals_for, tone_trend
from app.assistant.llm import LLMRefusal
from app.assistant.services import services
from app.contracts.models import Absence, Note

TODAY = date(2026, 11, 21)
NOW = datetime(2026, 11, 21, 12, 0)


@pytest.fixture
def svc(container):
    return services(container)


@pytest.fixture
def people(container):
    return container.employees.all()


def plan(**kw):
    data = {
        "goal": "Ustalić z [OSOBA_1] zasady informowania o opóźnieniach.",
        "opening": "Chcę porozmawiać o sytuacji z 19 sierpnia.",
        "questions": ["Jak to wyglądało z Twojej perspektywy?"],
        "reactions": [{"reaction": "To nie moja wina", "response": "Rozumiem, skupmy się na tym, co możemy zmienić."}],
        "avoid": ["Nie mów „zawsze”."],
        "roleplay": {"persona": "Specjalista od lat w referacie", "goal": "Obronić się", "resistance": "Zrzuca winę", "phrases": ["Nikt mi nie powiedział."]},
    }
    data.update(kw)
    return prep_mod.PrepPlan.model_validate(data)


# --- granice -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Pracownica twierdzi, że jest ofiarą mobbingu ze strony kolegi.", "MOBBING_DYSKRYMINACJA"),
        ("Powiedział, że nie chce mu się żyć.", "KRYZYS"),
        ("Chcę go zwolnić dyscyplinarnie.", "DYSCYPLINARNE_PRAWNE"),
        ("Złożyła pozew do sądu pracy.", "DYSCYPLINARNE_PRAWNE"),
        ("Od miesiąca jest na L4 i nie wiem, co z zadaniami.", "ZDROWIE"),
        ("Jest w ciąży, jak to wpływa na ocenę?", "ZDROWIE"),
    ],
)
def test_boundaries_detect_topics(text, code, people):
    hit = check(text, HrConfig.load(), people)
    assert hit is not None and hit.topic.code == code
    assert any("Magda Kadrowa" in c.label for c in hit.contacts)


def test_crisis_adds_emergency_numbers(people):
    hit = check("Mówił o samobójstwie.", HrConfig.load(), people)
    assert [c.value for c in hit.contacts][:2] == ["112", "116 123"]


def test_ordinary_work_topics_pass(people):
    for text in ["Spóźnia się z tłumaczeniami i nie informuje o ryzyku.", "Jak pochwalić za dobrą robotę?", "Kiedy mija termin oceny?"]:
        assert check(text, HrConfig.load(), people) is None


# --- sygnały -------------------------------------------------------------------------------


def test_signals_for_henryk(svc, container):
    result = {p.employee.id: [s.code for s in p.signals] for p in signals_for(
        "E05", TODAY, employees=container.employees, evaluations=container.evaluations, repo=svc.notes_repo, cfg=svc.nudges
    )}  # fmt: skip
    assert result["E07"] == ["DLUGO_BEZ_INFORMACJI", "BRAK_DOCENIENIA"]
    assert "E06" not in result  # Grzegorz: notatki na bieżąco, ostatnia pozytywna 04.11
    assert "E09" not in result  # Zofia: cykl od 32 dni


def _note(day: int, *, strengths=(), improvements=()) -> Note:
    d = TODAY - timedelta(days=day)
    return Note(id=f"N{day}", author_id="E05", subject_id="E06", observed_on=d, created_at=datetime.combine(d, datetime.min.time()),
                strengths=list(strengths), improvements=list(improvements))  # fmt: skip


def test_tone_trend():
    mixed = [_note(100, strengths=["a"]), _note(60, improvements=["x"]), _note(30, improvements=["y"]), _note(5, improvements=["z"])]
    assert [s.code for s in tone_trend(mixed)] == ["TREND_TONU"]
    always_critical = [_note(d, improvements=["x"]) for d in (100, 60, 30, 5)]
    assert tone_trend(always_critical) == []
    assert tone_trend(mixed[1:]) == []  # za mało notatek


def test_after_absence_never_mentions_reason():
    absence = Absence(employee_id="E10", start=date(2026, 8, 3), end=date(2026, 10, 30))
    signal = after_absence([absence], [], TODAY, NudgesConfig())[0]
    assert "Przyczyny nie znamy" in signal.why
    assert after_absence([absence], [_note(10)], TODAY, NudgesConfig()) == []


# --- baza wiedzy -----------------------------------------------------------------------------


def test_knowledge_base_has_regulation_and_finds_objection_deadline():
    kb = default_knowledge()
    labels = [c.label for c in kb.chunks]
    assert "§ 10 rozporządzenia" in labels and "art. 83 ustawy o służbie cywilnej" in labels
    assert any(label.startswith("Poradnik KPRM, s. 24") for label in labels)
    top = [c.label for c in kb.search("ile dni ma pracownik na sprzeciw od oceny", 4)]
    assert "art. 83 ustawy o służbie cywilnej" in top
    assert "§ 5 rozporządzenia" in [c.label for c in kb.search("ile kryteriów dodatkowych mogę wybrać", 4)]


# --- przygotowanie -----------------------------------------------------------------------------


def test_prepare_with_notes_pseudonymizes_and_restores(svc, people, container, fake_llm):
    svc.llm = fake_llm({"conversation_prep": plan()})
    grzegorz = container.employees.get("E06")
    notes = svc.notes_repo.current("E05", "E06")
    sensitive = notes[0].model_copy(update={"id": "NX", "body": "Był u psychiatry."})
    outcome = prep_mod.prepare(
        kind="oceniajaca", situation="Grzegorz Wzór nie informuje o opóźnieniach.", llm=svc.llm, hr=svc.hr,
        people=people, pseudonymizer=svc.pseudonymizer(), subject=grzegorz, notes=[*notes, sensitive],
    )  # fmt: skip
    user = svc.llm.calls[0]["user"]
    assert "Grzegorz" not in user and "[OSOBA_1] nie informuje" in user
    assert "<notatki>" in user and "psychiatr" not in user
    assert outcome.excluded_notes == 1 and outcome.used_notes == 5
    assert outcome.plan.goal.startswith("Ustalić z Grzegorz Wzór")


def test_prepare_boundary_skips_llm(svc, people, fake_llm):
    svc.llm = fake_llm({"conversation_prep": plan()})
    outcome = prep_mod.prepare(kind="trudna", situation="Zarzuca mi mobbing.", llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())
    assert outcome.boundary and svc.llm.calls == []


# --- próba rozmowy -----------------------------------------------------------------------------


def test_roleplay_flow(svc, people, fake_llm):
    svc.llm = fake_llm({"roleplay": ["Ale ", "nikt mi ", "nie powiedział."], "roleplay_feedback": "Dobrze zacząłeś od faktów."})
    session = svc.roleplays.create("E05", {"persona": "Specjalista", "goal": "Obronić się", "resistance": "", "phrases": [], "difficulty": "trudna"}, NOW)
    chunks = rp.reply(svc.roleplays, session, "Grzegorz, porozmawiajmy o 19 sierpnia.", llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())
    assert "".join(chunks) == "Ale nikt mi nie powiedział."
    call = svc.llm.calls[0]
    assert "Grzegorz" not in call["messages"][-1]["content"]
    assert "Trudność: trudna" in call["system"] and "Kim jesteś: Specjalista" in call["system"]

    saved = svc.roleplays.get("E05", session.id)
    assert [m["role"] for m in saved.messages] == ["user", "assistant"]
    assert saved.messages[0]["display"] == "Grzegorz, porozmawiajmy o 19 sierpnia."
    assert saved.turns == 1

    assert rp.finish(svc.roleplays, saved, llm=svc.llm) == "Dobrze zacząłeś od faktów."
    assert "<rozmowa>" in svc.llm.calls[-1]["messages"][0]["content"]
    assert svc.roleplays.get("E04", session.id) is None  # cudze ćwiczenie niewidoczne


def test_roleplay_limits_and_boundaries(svc, people, fake_llm):
    svc.llm = fake_llm({"roleplay": ["ok"]})
    session = svc.roleplays.create("E05", {"persona": "P", "phrases": []}, NOW)
    with pytest.raises(rp.RoleplayError, match="nie doradza"):
        rp.reply(svc.roleplays, session, "Czy to mobbing?", llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())
    assert svc.llm.calls == []
    svc.hr.roleplay_max_turns = 1
    list(rp.reply(svc.roleplays, session, "Dzień dobry", llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer()))
    with pytest.raises(rp.RoleplayError, match="limit"):
        rp.reply(svc.roleplays, svc.roleplays.get("E05", session.id), "Jeszcze", llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())


def test_roleplay_llm_error_is_not_saved(svc, people, fake_llm):
    svc.llm = fake_llm({"roleplay": LLMRefusal("x")})
    session = svc.roleplays.create("E05", {"persona": "P", "phrases": []}, NOW)
    out = "".join(rp.reply(svc.roleplays, session, "Dzień dobry", llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer()))
    assert "Wydziałem Kadr" in out
    assert svc.roleplays.get("E05", session.id).messages == []


# --- FUKO ----------------------------------------------------------------------------------------


def fuko_result():
    return fuko_mod.Fuko.model_validate({
        "facts": "19 sierpnia [OSOBA_1] nie przekazał informacji o opóźnieniu.",
        "feelings": "Zaniepokoiło mnie to.", "consequences": "Klient dowiedział się pierwszy.",
        "expectations": "Informuj mnie o ryzyku z wyprzedzeniem.", "ready_text": "Chcę porozmawiać o 19 sierpnia.",
        "opinions": [{"opinion": "nie da się na nim polegać", "fact_based": "dwa razy oddał tłumaczenie po terminie"}],
    })  # fmt: skip


def test_fuko_rewrite(svc, people, container, fake_llm):
    svc.llm = fake_llm({"rewrite_feedback": fuko_result()})
    out = fuko_mod.rewrite("Grzegorz znowu nie uprzedził. Nie da się na nim polegać.", llm=svc.llm, hr=svc.hr,
                           people=people, pseudonymizer=svc.pseudonymizer(), subject=container.employees.get("E06"))  # fmt: skip
    assert "Grzegorz" not in svc.llm.calls[0]["user"] and svc.llm.calls[0]["user"].startswith("<notatka>")
    assert out.fuko.facts.startswith("19 sierpnia Grzegorz Wzór")
    assert out.fuko.opinions[0].opinion == "nie da się na nim polegać"


def test_fuko_blocks_sensitive_and_health(svc, people, fake_llm):
    svc.llm = fake_llm({"rewrite_feedback": fuko_result()})
    kw = {"llm": svc.llm, "hr": svc.hr, "people": people, "pseudonymizer": svc.pseudonymizer()}
    out = fuko_mod.rewrite("Wychodzi wcześniej na mszę i nie kończy zadań.", **kw)
    assert out.error and "dane wrażliwe" in out.error
    assert fuko_mod.rewrite("Spóźnia się, bo chodzi na terapię.", **kw).boundary.topic.code == "ZDROWIE"
    assert svc.llm.calls == []


# --- procedury -----------------------------------------------------------------------------------


def _art83_id():
    return next(c.id for c in default_knowledge().chunks if c.label.startswith("art. 83"))


def test_qa_answer_with_valid_source(svc, people, fake_llm):
    svc.llm = fake_llm({"procedure_qa": lambda **kw: qa_mod.QaAnswer(answer="7 dni od zapoznania (art. 83 ust. 1 ustawy).", sources=[_art83_id(), "K9999"], found=True)})
    out = qa_mod.answer("Ile dni na sprzeciw od oceny?", kb=default_knowledge(), llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())
    assert out.answer.startswith("7 dni") and [c.label for c in out.sources] == ["art. 83 ustawy o służbie cywilnej"]
    assert f'id="{_art83_id()}"' in svc.llm.calls[0]["user"]


@pytest.mark.parametrize("answer", [
    qa_mod.QaAnswer(answer="Nie wiem.", sources=[], found=False),
    qa_mod.QaAnswer(answer="Zmyślone.", sources=["K9999"], found=True),
])  # fmt: skip
def test_qa_without_valid_source_sends_to_hr(svc, people, fake_llm, answer):
    svc.llm = fake_llm({"procedure_qa": answer})
    out = qa_mod.answer("Ile dni na sprzeciw?", kb=default_knowledge(), llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())
    assert out.answer is None and "Zapytaj kadry" in out.not_found and "Magda Kadrowa" in out.not_found


def test_qa_without_llm_returns_fragments(svc, people):
    out = qa_mod.answer("sprzeciw od oceny", kb=default_knowledge(), llm=svc.llm, hr=svc.hr, people=people, pseudonymizer=svc.pseudonymizer())
    assert out.fragments and out.answer is None and out.not_found is None


# --- strony --------------------------------------------------------------------------------------


def test_hr_index(client):
    page = client.get("/asystent/hr").text
    assert "Sygnały w Twoim zespole" in page and "Ewa Rzetelna" in page
    assert "Kiedy ostatnio rozmawialiście" in page


def test_prep_page_without_llm_shows_checklist(client):
    page = client.get("/asystent/hr/przygotowanie?rodzaj=oceniajaca&osoba=E06").text
    assert "§ 10 rozporządzenia" in page and "wymaga asystenta LLM" in page
    assert client.get("/asystent/hr/przygotowanie?osoba=E10").status_code == 403


def test_prep_and_roleplay_pages(client, container, fake_llm):
    services(container).llm = fake_llm({"conversation_prep": plan(), "roleplay": ["Nikt mi ", "nie powiedział."], "roleplay_feedback": "Brawo."})
    page = client.post("/asystent/hr/przygotowanie", data={"rodzaj": "trudna", "opis": "Nie informuje o opóźnieniach.", "osoba": "E06", "teczka": "1"}).text
    assert "Plan rozmowy" in page and "Rozpocznij próbę rozmowy" in page

    response = client.post("/asystent/hr/proba", data={"persona": "Specjalista", "goal": "Obronić się", "phrases": "Nikt mi nie powiedział."}, follow_redirects=False)
    assert response.status_code == 303
    url = response.headers["location"]
    roleplay_id = url.rsplit("/", 1)[-1]

    streamed = client.post(f"{url}/wiadomosc", data={"tekst": "Dzień dobry"}, headers={"X-Stream": "1"})
    assert streamed.text == "Nikt mi nie powiedział."
    client.post(f"{url}/wiadomosc", data={"tekst": "Porozmawiajmy"})  # bez JS
    page = client.get(url).text
    assert page.count("Nikt mi nie powiedział.") >= 2 and "Wypowiedzi: <span id=\"tury\">2</span>" in page

    client.post(f"{url}/koniec")
    assert "Brawo." in client.get(url).text
    client.get("/login/E04")
    assert client.get(f"/asystent/hr/proba/{roleplay_id}").status_code == 404


def test_roleplay_requires_llm(client):
    assert client.post("/asystent/hr/proba", data={"persona": "x"}).status_code == 403


def test_fuko_page_prefills_from_note(client, container, fake_llm):
    page = client.get("/asystent/hr/fuko?notatka=N002").text
    assert "nie przekazał informacji o opóźnieniu" in page
    services(container).llm = fake_llm({"rewrite_feedback": fuko_result()})
    page = client.post("/asystent/hr/fuko", data={"notatka": "N002", "tekst": "Nie przekazał informacji."}).text
    assert "Gotowe do powiedzenia" in page and "Opinie zamiast faktów" in page
    assert "→ informacja zwrotna" in client.get("/asystent/teczka/E06").text
    client.get("/login/E04")
    assert client.get("/asystent/hr/fuko?notatka=N002").status_code == 404


def test_procedures_page(client, container, fake_llm):
    page = client.get("/asystent/hr/procedury?q=sprzeciw od oceny").text
    assert "art. 83 ustawy o służbie cywilnej" in page
    services(container).llm = fake_llm({"procedure_qa": qa_mod.QaAnswer(answer="W terminie 7 dni (art. 83 ust. 1 ustawy).", sources=[_art83_id()], found=True)})
    page = client.post("/asystent/hr/procedury", data={"q": "Ile dni na sprzeciw?"}).text
    assert "W terminie 7 dni" in page and "AI na podstawie źródeł" in page
    page = client.post("/asystent/hr/procedury", data={"q": "Czy to już mobbing?"}).text
    assert "asystent nie doradza" in page
