"""Przebieg procesu przez HTTP — scenariusz demo z docs/AGENT_A.md."""

from __future__ import annotations

from datetime import date

import pytest

from app.clock import Clock
from app.contracts.enums import EvaluationState, ReminderKind
from app.core import scheduler


def login(client, employee_id: str) -> None:
    client.get(f"/login/{employee_id}")


def state(container, evaluation_id: str) -> EvaluationState:
    return container.evaluations.get(evaluation_id).state


def post(client, url: str, data: dict | None = None):
    r = client.post(url, data=data or {}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"]


# --- część I --------------------------------------------------------------------------------


def test_criteria_flow_for_new_employee(client, container):
    login(client, "E05")
    loc = post(client, "/core/oceny/EV-E09-2026/kryteria", {
        "additional_0": "ORIENTACJA_NA_KLIENTA", "additional_1": "", "additional_2": "",
        "due_date": "2028-10-20", "place": "Warszawa", "confirm": "1",
    })
    assert "error" not in loc
    assert state(container, "EV-E09-2026") == EvaluationState.CRITERIA_CONFIRMED

    login(client, "E09")
    post(client, "/core/oceny/EV-E09-2026/kryteria/potwierdz", {"place": "Warszawa"})
    ev = container.evaluations.get("EV-E09-2026")
    assert ev.state == EvaluationState.OBSERVATION
    assert ev.period_from == date(2026, 11, 21)
    assert [c.code for c in ev.criteria if not c.mandatory] == ["ORIENTACJA_NA_KLIENTA"]


@pytest.mark.parametrize(
    ("additional", "error"),
    [
        (["KREATYWNOSC", "KREATYWNOSC", ""], "powtarzać"),
        (["RZETELNOSC", "", ""], "nie jest kryterium dodatkowym"),  # obowiązkowe w arkuszu C
    ],
)
def test_criteria_validation(client, container, additional, error):
    login(client, "E05")
    loc = post(client, "/core/oceny/EV-E09-2026/kryteria", {f"additional_{i}": a for i, a in enumerate(additional)})
    assert "error=" in loc
    assert state(container, "EV-E09-2026") == EvaluationState.CYCLE_OPEN


def test_only_evaluator_can_set_criteria(client, container):
    login(client, "E09")
    loc = post(client, "/core/oceny/EV-E09-2026/kryteria", {"additional_0": "KREATYWNOSC"})
    assert "error=" in loc


def test_other_employee_cannot_view(client):
    login(client, "E06")
    assert client.get("/core/oceny/EV-E07-2024").status_code == 403


# --- część II -------------------------------------------------------------------------------

EWA_POINTS = {"p_WYKORZYSTYWANIE_WIEDZY": "7", "p_RZETELNOSC": "7", "p_ORGANIZACJA_PRACY": "5",
              "p_WSPOLPRACA": "7", "p_KOMUNIKACJA": "5", "p_ORIENTACJA_NA_KLIENTA": "9"}


def _assess_ewa(client, **extra):
    login(client, "E05")
    post(client, "/core/oceny/EV-E07-2024/rozmowa", {"interview_date": "2026-11-20"})
    return post(client, "/core/oceny/EV-E07-2024/ocena", {**EWA_POINTS, "iprz": "Szkolenie z terminologii UE.", **extra})


def test_full_assessment_flow(client, container):
    _assess_ewa(client)
    assert state(container, "EV-E07-2024") == EvaluationState.INTERVIEW_HELD
    page = client.get("/core/oceny/EV-E07-2024").text
    assert "Twoje obserwacje" in page and "6,67" in page  # 40/6

    loc = post(client, "/core/oceny/EV-E07-2024/ocena", {**EWA_POINTS, "iprz": "Szkolenie z terminologii UE.", "submit": "1"})
    assert "error" not in loc
    ev = container.evaluations.get("EV-E07-2024")
    assert ev.state == EvaluationState.AWAITING_ACK
    assert ev.result.level == "POWYZEJ" and ev.result.outcome == "POZYTYWNA"
    assert ev.result.promotion_requested is None  # pracownik s.c.

    login(client, "E07")
    post(client, "/core/oceny/EV-E07-2024/zapoznanie", {"place": "Warszawa"})
    assert state(container, "EV-E07-2024") == EvaluationState.ACKNOWLEDGED

    # po 7 dniach bez sprzeciwu → ostateczna + nowy cykl
    container.clock = Clock(date(2026, 12, 1))
    report = scheduler.run(container)
    assert report.finalized == ["EV-E07-2024"]
    new = container.evaluations.current_for("E07")
    assert new.state == EvaluationState.CYCLE_OPEN and new.id != "EV-E07-2024"
    assert new.criteria_due_date == date(2026, 12, 21)  # 30 dni od 21.11.2026
    assert new.due_date == date(2028, 11, 21)


def test_negative_requires_justification(client, container):
    loc = _assess_ewa(client, p_KOMUNIKACJA="1", submit="1")
    assert "error=" in loc and "uzasadnienie" in loc.lower().replace("%20", " ")
    assert state(container, "EV-E07-2024") == EvaluationState.INTERVIEW_HELD


def test_iprz_is_mandatory(client, container):
    login(client, "E05")
    post(client, "/core/oceny/EV-E07-2024/rozmowa", {"interview_date": "2026-11-20"})
    loc = post(client, "/core/oceny/EV-E07-2024/ocena", {**EWA_POINTS, "submit": "1"})
    assert "error=" in loc


def test_urzednik_promotion_part3(client, container):
    """Grzegorz (urzędnik, 2. stopień): pozytywna + TAK → część III, 'trzeciego' stopnia."""
    login(client, "E05")
    post(client, "/core/oceny/EV-E06-2026R/rozmowa", {"interview_date": "2026-11-20"})
    pts = {f"p_{c}": "7" for c in ["WYKORZYSTYWANIE_WIEDZY", "RZETELNOSC", "ORGANIZACJA_PRACY", "WSPOLPRACA",
                                   "KOMUNIKACJA", "ORIENTACJA_NA_KLIENTA", "KREATYWNOSC"]}
    # bez decyzji TAK/NIE — blokada
    loc = post(client, "/core/oceny/EV-E06-2026R/ocena", {**pts, "iprz": "x", "submit": "1"})
    assert "error=" in loc
    loc = post(client, "/core/oceny/EV-E06-2026R/ocena", {
        **pts, "iprz": "Rozwój kompetencji komunikacyjnych.", "promotion_choice": "TAK",
        "p3_appointed_year": "2019", "p3_grade": "2", "p3_grade_granted_on": "2021-07-01",
        "p3_motivation": "Wyraźna poprawa po ocenie negatywnej.", "submit": "1",
    })
    assert "error" not in loc
    ev = container.evaluations.get("EV-E06-2026R")
    assert ev.result.promotion_requested is True
    printed = client.get("/core/oceny/EV-E06-2026R/druk").text
    assert "CZĘŚĆ III" in printed and "trzeciego" in printed
    # dane poprzedniej oceny uzupełnione z historii
    assert "negatywna" in printed and "28.04.2026" not in printed


def test_deemed_acknowledgement_and_objection_redo(client, container):
    _assess_ewa(client)
    post(client, "/core/oceny/EV-E07-2024/ocena", {**EWA_POINTS, "iprz": "x", "submit": "1"})
    post(client, "/core/oceny/EV-E07-2024/fikcja-zapoznania", {"note": "przekazano osobiście, odmowa podpisu"})
    assert state(container, "EV-E07-2024") == EvaluationState.ACKNOWLEDGED

    login(client, "E07")
    post(client, "/core/oceny/EV-E07-2024/sprzeciw", {"text": "Nie zgadzam się z oceną komunikacji."})
    assert state(container, "EV-E07-2024") == EvaluationState.OBJECTION

    login(client, "E11")  # kadry
    loc = post(client, "/core/oceny/EV-E07-2024/sprzeciw/decyzja", {"decision": "REDO", "note": "ponownie"})
    assert state(container, "EV-E07-2024") == EvaluationState.CANCELLED
    new_id = loc.split("/core/oceny/")[1].split("?")[0]
    assert state(container, new_id) == EvaluationState.OBSERVATION


@pytest.mark.parametrize(("day", "allowed"), [(date(2026, 11, 30), True), (date(2026, 12, 1), False)])
def test_objection_deadline(client, container, day, allowed):
    """Zapoznanie 21.11 → 7 dni = 28.11 (sobota) → termin 30.11 (art. 83 ust. 1)."""
    _assess_ewa(client)
    post(client, "/core/oceny/EV-E07-2024/ocena", {**EWA_POINTS, "iprz": "x", "submit": "1"})
    login(client, "E07")
    post(client, "/core/oceny/EV-E07-2024/zapoznanie", {})
    container.clock = Clock(day)
    loc = post(client, "/core/oceny/EV-E07-2024/sprzeciw", {"text": "x"})
    assert ("error=" not in loc) is allowed


# --- terminy, przypomnienia, kadry -----------------------------------------------------------


def test_due_date_change_requires_six_months(client, container):
    login(client, "E05")
    loc = post(client, "/core/oceny/EV-E06-2026R/termin", {"new_date": "2027-01-15", "reason": "WNIOSEK_OCENIANEGO"})
    assert "error=" in loc  # cykl od 12.06.2026 — mniej niż 6 mies.
    loc = post(client, "/core/oceny/EV-E07-2024/termin", {"new_date": "2027-01-15", "reason": "WNIOSEK_OCENIANEGO"})
    assert "error" not in loc
    assert container.evaluations.get("EV-E07-2024").due_date == date(2027, 1, 15)
    assert any(r.kind == ReminderKind.DUE_DATE_CHANGED for r in container.reminder_sink.inbox("E07"))


def test_scheduler_reminders_on_demo_day(container):
    report = scheduler.run(container, date(2026, 11, 21))
    assert report.emitted["core.process"] > 0
    henryk = {r.kind for r in container.reminder_sink.inbox("E05")}
    assert ReminderKind.CRITERIA_OVERDUE in henryk  # Zofia
    assert ReminderKind.ASSESSMENT_DUE in henryk  # Ewa (10.12) i Grzegorz (15.12)
    magda = container.reminder_sink.inbox("E11")
    assert any(r.kind == ReminderKind.PROMOTION_DUE and r.subject_id == "E08" for r in magda)
    # ponowne uruchomienie tego samego dnia nie dubluje
    assert scheduler.run(container, date(2026, 11, 21)).emitted["core.process"] == 0


def test_absence_extends_due_date(client, container):
    login(client, "E11")
    loc = post(client, "/core/kadry/nieobecnosc", {"employee_id": "E05", "start": "2026-09-01", "end": "2026-10-15"})
    assert "przed%C5%82u%C5%BCony" in loc or "przedłużony" in loc
    # 03.03.2027 + 45 dni = 17.04.2027 (sobota) → 19.04.2027
    assert container.evaluations.current_for("E05").due_date == date(2027, 4, 19)


def test_hr_grants_obligatory_grade(client, container):
    login(client, "E11")
    post(client, "/core/kadry/E08/stopien", {"granted_on": "2026-11-21"})
    piotr = container.employees.get("E08")
    assert piotr.grade == 5
    from app.core.rules.careers import obligatory_promotion

    assert obligatory_promotion(piotr, container.evaluations.history("E08")) is None


def test_kadry_page_for_hr(client):
    login(client, "E11")
    page = client.get("/core/kadry").text
    assert "obligatoryjny stopień" in page and "Krzysztof Długi" in page
    assert client.get("/core/kadry?filtr=zalegle").status_code == 200


def test_print_view_sheet_a_has_no_org_unit(client):
    login(client, "E11")  # oceniający E01 jest spoza urzędu → kadry mają dostęp
    page = client.get("/core/oceny/EV-E01-2025/druk").text
    assert "ARKUSZ A" in page and "Komórka organizacyjna" not in page
