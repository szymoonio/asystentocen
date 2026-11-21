"""Sygnały dla kierownika (§ 7.2) — deterministyczne, jako PYTANIE do kierownika, nie diagnoza.

Każdy sygnał ma „dlaczego” (dane, z których wynika) i podpowiedź z playbooka. Nie używamy
przyczyn nieobecności ani niczego, co przypominałoby „predyktor wypalenia”.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.assistant.config import NudgesConfig
from app.assistant.notes.repository import NotesRepository
from app.assistant.nudges.rules import ACTIVE_STATES, count, cycle_start, pl_date
from app.contracts.models import Absence, Employee, Note
from app.contracts.ports import EmployeeDirectory, EvaluationReader


@dataclass(frozen=True)
class Signal:
    code: str
    question: str
    why: str
    action: str


@dataclass(frozen=True)
class PersonSignals:
    employee: Employee
    signals: list[Signal]


def no_feedback(notes: Sequence[Note], start: date | None, today: date, cfg: NudgesConfig) -> list[Signal]:
    last = max((n.observed_on for n in notes), default=None)
    ref = last or start
    if ref is None or (today - ref).days <= cfg.no_note_after_days:
        return []
    days = (today - ref).days
    why = f"Ostatnia notatka: {pl_date(last)}." if last else f"Brak notatek od początku cyklu ({pl_date(start)})."
    return [
        Signal(
            "DLUGO_BEZ_INFORMACJI",
            f"Od {count(days, 'dnia', 'dni', 'dni')} nie ma śladu rozmowy o bieżącej pracy. Kiedy ostatnio rozmawialiście o zadaniach i postępach?",
            why,
            "Standardy ZZL: informacja zwrotna bieżąca i cykliczna (np. kwartalnie). Wystarczy krótka rozmowa 1:1.",
        )
    ]


def no_appreciation(notes: Sequence[Note], today: date, cfg: NudgesConfig) -> list[Signal]:
    if not notes:
        return []
    last = max((n.observed_on for n in notes if n.strengths), default=None)
    if last is not None and (today - last).days <= cfg.no_positive_after_days:
        return []
    why = f"Ostatnia notatka z zaletami: {pl_date(last)}." if last else "Żadna notatka w tym cyklu nie zawiera zalet."
    return [
        Signal(
            "BRAK_DOCENIENIA",
            "Czy w ostatnich miesiącach była okazja docenić coś konkretnego w tej pracy?",
            why,
            "Konkretna pochwała w modelu FUKO: fakt, Twoje odczucie, skutek dla zespołu, oczekiwanie na przyszłość.",
        )
    ]


def tone_trend(notes: Sequence[Note], window: int = 3) -> list[Signal]:
    """Ostatnie `window` notatek wyłącznie o obszarach do poprawy, a wcześniej było inaczej."""
    ordered = sorted(notes, key=lambda n: n.observed_on)
    if len(ordered) < window + 1:
        return []
    recent, earlier = ordered[-window:], ordered[:-window]

    def critical(n: Note) -> bool:
        return bool(n.improvements) and not n.strengths

    if not all(critical(n) for n in recent) or all(critical(n) for n in earlier):
        return []
    return [
        Signal(
            "TREND_TONU",
            "Ostatnie notatki dotyczą wyłącznie obszarów do poprawy. Czy warto porozmawiać wspierająco, zanim sprawa urośnie?",
            f"{window} ostatnie notatki (od {pl_date(recent[0].observed_on)}) bez zalet, wcześniejsze były mieszane.",
            "Rozmowa wspierająca: zapytaj o przeszkody, ustal jedno konkretne oczekiwanie i termin ponownej rozmowy.",
        )
    ]


def after_absence(absences: Sequence[Absence], notes: Sequence[Note], today: date, cfg: NudgesConfig) -> list[Signal]:
    for absence in sorted(absences, key=lambda a: a.end, reverse=True):
        length = (absence.end - absence.start).days + 1
        if length < cfg.return_min_absence_days or not 0 < (today - absence.end).days <= cfg.return_window_days:
            continue
        if any(n.observed_on > absence.end for n in notes):
            return []
        return [
            Signal(
                "POWROT",
                "Czy po powrocie odbyła się rozmowa powitalna i aktualizacja zadań?",
                f"Nieobecność do {pl_date(absence.end)} ({count(length, 'dzień', 'dni', 'dni')}). Przyczyny nie znamy i o nią nie pytamy.",
                "Rozmowa powitalna: co się zmieniło w zespole, priorytety na najbliższe tygodnie, czy czegoś potrzeba do pracy.",
            )
        ]
    return []


def signals_for(
    supervisor_id: str,
    today: date,
    *,
    employees: EmployeeDirectory,
    evaluations: EvaluationReader,
    repo: NotesRepository,
    cfg: NudgesConfig,
) -> list[PersonSignals]:
    out = []
    for evaluation in evaluations.for_evaluator(supervisor_id):
        if evaluation.state not in ACTIVE_STATES:
            continue
        try:
            person = employees.get(evaluation.employee_id)
        except KeyError:
            continue
        all_notes = repo.current(supervisor_id, person.id)
        notes = [n for n in all_notes if n.evaluation_id == evaluation.id]
        start = cycle_start(evaluation, evaluations.history(person.id), person)
        found = [
            *no_feedback(notes, start, today, cfg),
            *no_appreciation(notes, today, cfg),
            *tone_trend(notes),
            *after_absence(employees.absences(person.id), all_notes, today, cfg),
        ]
        if found:
            out.append(PersonSignals(person, found))
    return out
