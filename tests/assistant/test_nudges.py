"""Przypomnienia o notatkach (§ 5.4): reguły, tygodniowe zestawienie, odkładanie."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.assistant.config import NudgesConfig
from app.assistant.notes.repository import NoteInput
from app.assistant.nudges import rules
from app.assistant.nudges.provider import NoteNudges, week_key
from app.assistant.services import services
from app.contracts.enums import EvaluationState, ReminderKind, SheetType
from app.contracts.models import Absence, CriterionDef, CriterionRating, EvaluationSummary, Note
from app.contracts.ports import ReminderProvider

TODAY = date(2026, 11, 21)
CFG = NudgesConfig()


def note(days_ago: int, *, strengths=(), ratings=None) -> Note:
    d = TODAY - timedelta(days=days_ago)
    return Note(
        id=f"N{days_ago}",
        author_id="E05",
        subject_id="E06",
        observed_on=d,
        created_at=datetime.combine(d, datetime.min.time()),
        body="x",
        strengths=list(strengths),
        ratings=[CriterionRating(criterion_code=k, value=v) for k, v in (ratings or {}).items()],
    )


def kinds(findings):
    return [f.kind for f in findings]


# --- reguły ----------------------------------------------------------------------------


def test_plural():
    assert [rules.count(n, "notatka", "notatki", "notatek") for n in (1, 2, 5, 12, 22)] == [
        "1 notatka", "2 notatki", "5 notatek", "12 notatek", "22 notatki",
    ]  # fmt: skip


def test_no_note_after_threshold():
    assert rules.no_note([note(46)], None, TODAY, CFG, "E06")[0].text.startswith("Brak notatki od 46 dni")
    assert rules.no_note([note(45)], None, TODAY, CFG, "E06") == []


def test_no_note_without_notes_counts_from_cycle_start():
    old = rules.no_note([], TODAY - timedelta(days=100), TODAY, CFG, "E06")
    assert "Brak notatek w tym cyklu" in old[0].text
    assert rules.no_note([], TODAY - timedelta(days=30), TODAY, CFG, "E06") == []


def test_no_positive():
    assert kinds(rules.no_positive([note(130, strengths=["x"])], None, TODAY, CFG, "E06")) == [
        ReminderKind.APPRECIATION_NUDGE
    ]
    assert rules.no_positive([note(130, strengths=["x"]), note(10, strengths=["y"])], None, TODAY, CFG, "E06") == []
    # notatki bez zalet przez cały długi cykl
    assert rules.no_positive([note(5)], TODAY - timedelta(days=200), TODAY, CFG, "E06")
    # brak notatek w ogóle obsługuje no_note
    assert rules.no_positive([], TODAY - timedelta(days=200), TODAY, CFG, "E06") == []


def test_recency_bias():
    notes = [note(200), note(60), note(40), note(20), note(5)]
    due_soon = TODAY + timedelta(days=30)
    found = rules.recency(notes, due_soon, TODAY, CFG, "E06")
    assert "80% notatek pochodzi z ostatnich 3 mies." in found[0].text
    assert rules.recency(notes, TODAY + timedelta(days=200), TODAY, CFG, "E06") == []  # za wcześnie
    assert rules.recency(notes[:1] + notes[-1:], due_soon, TODAY, CFG, "E06") == []  # za mało notatek
    assert rules.recency([note(200), note(150), note(5)], due_soon, TODAY, CFG, "E06") == []


def test_pre_interview_lists_uncovered_criteria():
    gap = rules.CoverageGap("E06", CriterionDef(code="RZETELNOSC", name="Rzetelność"))
    found = rules.pre_interview([note(5)], [gap], TODAY + timedelta(days=24), TODAY, CFG, "E06")
    assert found[0].text == "Ocena za 24 dni (15.12.2026): 1 notatka, bez obserwacji: Rzetelność."
    assert rules.pre_interview([], [], TODAY + timedelta(days=61), TODAY, CFG, "E06") == []
    assert rules.pre_interview([], [], TODAY - timedelta(days=1), TODAY, CFG, "E06") == []


def test_coverage_needs_notes_and_some_cycle_age():
    crit = [CriterionDef(code="A", name="A"), CriterionDef(code="B", name="B")]
    rated = [note(5, ratings={"A": 5})]
    assert [g.criterion.code for g in rules.coverage_gaps(rated, crit, TODAY - timedelta(days=60), TODAY, CFG, "E06")] == ["B"]
    assert rules.coverage_gaps(rated, crit, TODAY - timedelta(days=10), TODAY, CFG, "E06") == []
    assert rules.coverage_gaps([], crit, TODAY - timedelta(days=60), TODAY, CFG, "E06") == []


def test_return_from_absence():
    long_absence = Absence(employee_id="E10", start=date(2026, 8, 3), end=date(2026, 10, 30))
    found = rules.returned_from_absence([long_absence], [], TODAY, CFG, "E10")
    assert "Powrót po nieobecności (89 dni, do 30.10.2026)" in found[0].text
    # notatka po powrocie wycisza
    assert rules.returned_from_absence([long_absence], [note(18)], TODAY, CFG, "E10") == []
    short = Absence(employee_id="E10", start=date(2026, 11, 2), end=date(2026, 11, 13))
    assert rules.returned_from_absence([short], [], TODAY, CFG, "E10") == []


def test_closed_or_interview_states_are_skipped(seed):
    ev = EvaluationSummary(
        id="X", employee_id="E06", evaluator_id="E05", sheet=SheetType.C, state=EvaluationState.INTERVIEW_HELD,
        period_from=date(2025, 1, 1), due_date=TODAY + timedelta(days=5),
    )  # fmt: skip
    employee = next(e for e in seed.employees if e.id == "E06")
    check = rules.check_subject(
        subject=employee, evaluation=ev, history=[], notes=[], all_notes=[], criteria=[], absences=[],
        today=TODAY, cfg=CFG,
    )  # fmt: skip
    assert check.findings == []


# --- provider na seedzie ---------------------------------------------------------------


@pytest.fixture
def nudges(container) -> NoteNudges:
    return services(container).note_nudges


def test_registered_as_reminder_provider(container, nudges):
    assert nudges in container.reminder_providers
    assert isinstance(nudges, ReminderProvider)


def test_weekly_digest_for_henryk(nudges):
    reminders = {r.recipient_id: r for r in nudges.due(TODAY)}
    henryk = reminders["E05"]
    assert henryk.dedupe_key == "nudge:E05:2026-W47"
    assert henryk.kind == ReminderKind.NOTE_NUDGE and henryk.link == "/asystent/teczka"
    msg = henryk.message
    assert "Ewa Rzetelna: Brak notatki od 220 dni (ostatnia: 15.04.2026)." in msg
    assert "Ewa Rzetelna: Ostatnia pozytywna obserwacja: 15.04.2026" in msg
    assert "Grzegorz Wzór: Ocena za 24 dni (15.12.2026): 5 notatek, bez obserwacji: Organizacja pracy" in msg
    assert "Ewa Rzetelna: Ocena za 19 dni" in msg and "bez obserwacji: Rzetelność" in msg
    assert "Zofia" not in msg  # nowa osoba, cykl od 32 dni
    assert "Tomasz" not in msg  # nie podlega ocenie


def test_one_digest_per_supervisor_per_week(container, nudges):
    reminders = nudges.due(TODAY)
    assert len({r.recipient_id for r in reminders}) == len(reminders)
    sink = container.reminder_sink
    first = sink.emit(nudges.due(TODAY))
    assert first == len(reminders)
    assert sink.emit(nudges.due(TODAY + timedelta(days=1))) == 0  # ten sam tydzień
    assert sink.emit(nudges.due(TODAY + timedelta(days=7))) > 0  # następny tydzień
    assert week_key(TODAY + timedelta(days=7)) == "2026-W48"


def test_krzysztof_note_after_return_silences_return_nudge(nudges):
    msg = {r.recipient_id: r for r in nudges.due(TODAY)}["E04"].message
    assert "Powrót po nieobecności" not in msg  # N009 z 03.11 — rozmowa po powrocie była
    assert "Krzysztof Długi: Żadne kryterium oceny nie ma jeszcze obserwacji z suwakiem." in msg


def test_new_note_clears_no_note_nudge(container, nudges):
    services(container).notes_repo.create(
        author_id="E05", subject_id="E07", evaluation_id="EV-E07-2024",
        data=NoteInput(observed_on=TODAY, strengths=["Dobre tłumaczenie"], ratings=[CriterionRating(criterion_code="RZETELNOSC", value=7)]),
        now=datetime(2026, 11, 21, 12, 0),
    )  # fmt: skip
    digest = nudges.digest_for("E05", TODAY)
    ewa = next(p for p in digest.people if p.employee.id == "E07")
    assert kinds(ewa.findings) == [ReminderKind.PRE_INTERVIEW_NUDGE]
    assert "bez obserwacji" not in ewa.findings[0].text


def test_snooze_hides_person_for_two_weeks(container, nudges):
    services(container).snoozes.snooze("E05", "E07", TODAY + timedelta(days=14))
    digest = nudges.digest_for("E05", TODAY)
    assert "E07" not in {p.employee.id for p in digest.people}
    assert digest.snoozed == {"E07": TODAY + timedelta(days=14)}
    later = nudges.digest_for("E05", TODAY + timedelta(days=15))
    assert "E07" in {p.employee.id for p in later.people}


# --- strony ----------------------------------------------------------------------------


def test_snooze_and_restore_routes(client, container):
    response = client.post("/asystent/teczka/E07/odloz", follow_redirects=False)
    assert response.status_code == 303
    digest = services(container).note_nudges.digest_for("E05", TODAY)
    assert "E07" in digest.snoozed
    client.post("/asystent/teczka/E07/przywroc")
    assert "E07" not in services(container).note_nudges.digest_for("E05", TODAY).snoozed


def test_cannot_snooze_someone_elses_subordinate(client):
    assert client.post("/asystent/teczka/E10/odloz").status_code == 403
