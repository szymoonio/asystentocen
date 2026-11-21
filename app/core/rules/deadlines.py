"""Terminy procesu oceny. Każda funkcja zwraca termin razem z podstawą prawną.

Źródła: art. 81, 83, 89 ustawy o służbie cywilnej; § 7, § 9 rozporządzenia PRM z 4.04.2016.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.contracts.models import Absence
from app.core.rules.calendar_pl import (
    add_months,
    deadline_in_days,
    deadline_in_months,
    is_working_day,
    shift_to_working_day,
)

CYCLE_MONTHS = 24  # art. 81 ust. 4
REASSESSMENT_AFTER_NEGATIVE_MONTHS = 6  # art. 81 ust. 9
CHANGE_ALLOWED_AFTER_MONTHS = 6  # art. 81 ust. 6 i 8, § 9 ust. 1
CRITERIA_DAYS = 30  # § 7 pkt 1
CRITERIA_DAYS_AFTER_NEGATIVE = 7  # § 7 pkt 2
OBJECTION_DAYS = 7  # art. 83 ust. 1
OBJECTION_REVIEW_DAYS = 14  # art. 83 ust. 3
PROMOTION_DAYS = 30  # art. 89 ust. 2


@dataclass(frozen=True)
class Deadline:
    date: date
    basis: str  # podstawa prawna, do pokazania w UI
    explanation: str = ""
    extensions: tuple[tuple[date, date, int], ...] = field(default=())  # (od, do, dni) nieobecności


# --- nieobecności --------------------------------------------------------------------


def merge_absences(periods: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    """Łączy okresy, między którymi są wyłącznie dni wolne od pracy (ciągłość nieobecności)."""
    merged: list[tuple[date, date]] = []
    for start, end in sorted(periods):
        if merged:
            prev_start, prev_end = merged[-1]
            gap = prev_end + timedelta(days=1)
            while gap < start and not is_working_day(gap):
                gap += timedelta(days=1)
            if gap >= start:
                merged[-1] = (prev_start, max(prev_end, end))
                continue
        merged.append((start, end))
    return merged


def is_longer_than_month(start: date, end: date) -> bool:
    """Nieobecność trwa dłużej niż miesiąc, jeśli obejmuje dzień odpowiadający dniowi początkowemu
    w następnym miesiącu (np. 05.10–05.11 to już „dłużej niż miesiąc”).

    Interpretacja graniczna do potwierdzenia z KPRM; przypadki z materiałów są jednoznaczne.
    """
    return end >= add_months(start, 1)


def long_absences(absences: Sequence[Absence]) -> list[tuple[date, date]]:
    """Usprawiedliwione, ciągłe nieobecności dłuższe niż miesiąc (art. 81 ust. 7)."""
    periods = merge_absences((a.start, a.end) for a in absences if a.justified)
    return [(s, e) for s, e in periods if is_longer_than_month(s, e)]


# --- termin oceny ----------------------------------------------------------------------


def assessment_due(
    cycle_start: date,
    absences: Sequence[Absence] = (),
    *,
    negative_acknowledged_on: date | None = None,
) -> Deadline:
    """Termin sporządzenia oceny na piśmie.

    - zwykły cykl: 24 mies. od poprzedniej oceny albo od zatrudnienia na czas nieokreślony
      (art. 81 ust. 4), przedłużony o czas usprawiedliwionej nieobecności > 1 mies. (ust. 7);
    - po ocenie negatywnej: 6 mies. od zapoznania się z oceną (ust. 9) — przedłużenie z ust. 7
      dotyczy tylko terminu z ust. 4, więc go tu nie stosujemy.
    """
    if negative_acknowledged_on:
        return Deadline(
            date=deadline_in_months(negative_acknowledged_on, REASSESSMENT_AFTER_NEGATIVE_MONTHS),
            basis="art. 81 ust. 9 ustawy",
            explanation="ponowna ocena 6 miesięcy od zapoznania się z oceną negatywną",
        )

    base = add_months(cycle_start, CYCLE_MONTHS)
    end = base
    used: list[tuple[date, date, int]] = []
    # Nieobecność przesuwa koniec okresu, więc kolejne nieobecności mogą wpaść w wydłużony okres.
    for start, stop in long_absences(absences):
        if stop < cycle_start or start > end:
            continue
        overlap_start = max(start, cycle_start)
        days = (stop - overlap_start).days + 1
        used.append((overlap_start, stop, days))
        end += timedelta(days=days)

    if used:
        total = sum(d for _, _, d in used)
        return Deadline(
            date=shift_to_working_day(end),
            basis="art. 81 ust. 4 i 7 ustawy",
            explanation=f"24 miesiące od {cycle_start:%d.%m.%Y}, przedłużone o {total} dni nieobecności",
            extensions=tuple(used),
        )
    return Deadline(
        date=shift_to_working_day(base),
        basis="art. 81 ust. 4 ustawy",
        explanation=f"24 miesiące od {cycle_start:%d.%m.%Y}",
    )


def criteria_due(cycle_start: date, *, after_negative: bool = False) -> Deadline:
    """Termin rozmowy i ustalenia kryteriów (§ 5–6) — § 7 rozporządzenia."""
    if after_negative:
        return Deadline(
            date=deadline_in_days(cycle_start, CRITERIA_DAYS_AFTER_NEGATIVE),
            basis="§ 7 pkt 2 rozporządzenia",
            explanation="7 dni od sporządzenia oceny negatywnej",
        )
    return Deadline(
        date=deadline_in_days(cycle_start, CRITERIA_DAYS),
        basis="§ 7 pkt 1 rozporządzenia",
        explanation="30 dni od sporządzenia poprzedniej oceny albo od zatrudnienia na czas nieokreślony",
    )


def objection_deadline(acknowledged_on: date) -> Deadline:
    return Deadline(
        date=deadline_in_days(acknowledged_on, OBJECTION_DAYS),
        basis="art. 83 ust. 1 ustawy",
        explanation="sprzeciw do dyrektora generalnego urzędu w terminie 7 dni od zapoznania",
    )


def objection_review_deadline(filed_on: date) -> Deadline:
    return Deadline(
        date=deadline_in_days(filed_on, OBJECTION_REVIEW_DAYS),
        basis="art. 83 ust. 3 ustawy",
        explanation="sprzeciw rozpatruje się w terminie 14 dni od wniesienia",
    )


def promotion_deadline(acknowledged_on: date) -> Deadline:
    return Deadline(
        date=deadline_in_days(acknowledged_on, PROMOTION_DAYS),
        basis="art. 89 ust. 2 ustawy",
        explanation="kolejny stopień służbowy w terminie 30 dni od zapoznania z oceną",
    )


# --- zmiany w trakcie cyklu --------------------------------------------------------------


def more_than_six_months(since: date, on: date) -> bool:
    return on > add_months(since, CHANGE_ALLOWED_AFTER_MONTHS)


def can_change_due_date(cycle_start: date, today: date) -> tuple[bool, str]:
    """Art. 81 ust. 8: zmiana terminu tylko gdy od ostatniej oceny (albo — przy pierwszej
    ocenie — od początku okresu podlegającego ocenie) upłynęło więcej niż 6 miesięcy."""
    if more_than_six_months(cycle_start, today):
        return True, "art. 81 ust. 8 ustawy"
    return False, "art. 81 ust. 8 ustawy: od początku okresu nie upłynęło jeszcze 6 miesięcy"


DUE_DATE_CHANGE_REASONS: dict[str, str] = {
    "ZMIANA_OCENIAJACEGO": "zmiana na stanowisku oceniającego (art. 81 ust. 8 pkt 1)",
    "NIEOBECNOSC_OCENIANEGO": "przewidywana dłuższa usprawiedliwiona nieobecność ocenianego (art. 81 ust. 8 pkt 2)",
    "NIEOBECNOSC_OCENIAJACEGO": "przewidywana dłuższa usprawiedliwiona nieobecność oceniającego (art. 81 ust. 8 pkt 3)",
    "WNIOSEK_OCENIANEGO": "wniosek ocenianego o zmianę terminu (art. 81 ust. 8 pkt 4)",
}


@dataclass(frozen=True)
class PositionChangeAction:
    kind: str  # "REDO_CRITERIA" albo "ASSESS_NOW"
    window_start: date
    window_end: date
    basis: str
    explanation: str


def position_change_action(
    changed_on: date, *, reference: date, first_assessment: bool
) -> PositionChangeAction:
    """Zmiana stanowiska wiążąca się z istotną zmianą zakresu obowiązków.

    `reference` = data ustalenia kryteriów (pierwsza ocena) albo sporządzenia ostatniej oceny.
    - w ciągu 6 mies. od `reference`: ponownie kryteria w 30 dni, termin bez zmian (§ 9 ust. 1);
    - później: ocena od 7 dni przed do 30 dni po zmianie (art. 81 ust. 6, § 9 ust. 2).
    """
    if not more_than_six_months(reference, changed_on):
        return PositionChangeAction(
            kind="REDO_CRITERIA",
            window_start=changed_on,
            window_end=deadline_in_days(changed_on, CRITERIA_DAYS),
            basis="§ 9 ust. 1 rozporządzenia",
            explanation="ponowna rozmowa i kryteria w 30 dni od zmiany stanowiska; termin oceny bez zmian",
        )
    return PositionChangeAction(
        kind="ASSESS_NOW",
        window_start=changed_on - timedelta(days=7),
        window_end=deadline_in_days(changed_on, CRITERIA_DAYS),
        basis="art. 81 ust. 6 ustawy, § 9 ust. 2 rozporządzenia",
        explanation=(
            "ocenę sporządza się nie wcześniej niż 7 dni przed i nie później niż 30 dni po zmianie stanowiska"
            + (" (pierwsza ocena: okres oceny dłuższy niż 6 miesięcy)" if first_assessment else "")
        ),
    )
