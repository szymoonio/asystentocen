"""Wspólne enumy. ZAMROŻONE (krok 0) — zmiana tylko po uzgodnieniu A+B, osobnym PR do main."""

from __future__ import annotations

from enum import StrEnum


class SheetType(StrEnum):
    A = "A"  # kierownik urzędu (§ 3 ust. 2)
    B = "B"  # bezpośrednie kierowanie pracownikami (§ 3 ust. 3)
    C = "C"  # pozostałe stanowiska (§ 3 ust. 4)


class EmploymentBasis(StrEnum):
    MIANOWANIE = "MIANOWANIE"  # urzędnik służby cywilnej
    UMOWA_NIEOKRESLONY = "UMOWA_NIEOKRESLONY"  # pracownik s.c., podlega ocenie
    UMOWA_OKRESLONY = "UMOWA_OKRESLONY"  # pracownik s.c., NIE podlega ocenie (art. 81 ust. 1)


class Role(StrEnum):
    OCENIAJACY = "OCENIAJACY"
    OCENIANY = "OCENIANY"
    KADRY = "KADRY"
    ADMIN = "ADMIN"
    ZARZADZAJACY = "ZARZADZAJACY"  # dyrektor generalny / kierownik urzędu — statystyki


class EvaluationState(StrEnum):
    """Stany cyklu oceny — zob. docs/ARCHITEKTURA.md § 3."""

    CYCLE_OPEN = "CYCLE_OPEN"  # cykl otwarty, kryteria jeszcze nie ustalone
    CRITERIA_CONFIRMED = "CRITERIA_CONFIRMED"  # oceniający potwierdził kryteria i rozmowę
    OBSERVATION = "OBSERVATION"  # oceniany potwierdził; trwa okres oceny
    INTERVIEW_HELD = "INTERVIEW_HELD"  # odbyła się rozmowa oceniająca
    AWAITING_ACK = "AWAITING_ACK"  # ocena zatwierdzona, czeka na zapoznanie
    ACKNOWLEDGED = "ACKNOWLEDGED"  # zapoznanie (lub fikcja zapoznania); biegnie 7 dni na sprzeciw
    OBJECTION = "OBJECTION"  # wniesiono sprzeciw
    FINAL = "FINAL"  # ocena ostateczna
    CANCELLED = "CANCELLED"  # anulowana (np. ponowne sporządzenie po sprzeciwie)


class Level(StrEnum):
    """Ogólny poziom spełniania kryteriów (§ 11 ust. 1 pkt 2)."""

    ZNACZNIE_PONIZEJ = "ZNACZNIE_PONIZEJ"
    PONIZEJ = "PONIZEJ"
    NA_POZIOMIE = "NA_POZIOMIE"
    POWYZEJ = "POWYZEJ"
    ZNACZNIE_POWYZEJ = "ZNACZNIE_POWYZEJ"

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self]


LEVEL_LABELS: dict[Level, str] = {
    Level.ZNACZNIE_PONIZEJ: "znacznie poniżej oczekiwań",
    Level.PONIZEJ: "poniżej oczekiwań",
    Level.NA_POZIOMIE: "na poziomie oczekiwań",
    Level.POWYZEJ: "powyżej oczekiwań",
    Level.ZNACZNIE_POWYZEJ: "znacznie powyżej oczekiwań",
}

# Punkty ocen cząstkowych (§ 11 ust. 1 pkt 1) — tej samej skali używają suwaki w notatkach.
PARTIAL_POINTS: tuple[int, ...] = (1, 3, 5, 7, 9)


class Outcome(StrEnum):
    POZYTYWNA = "POZYTYWNA"
    NEGATYWNA = "NEGATYWNA"


class NoteSource(StrEnum):
    TEXT = "TEXT"
    VOICE = "VOICE"


class DraftField(StrEnum):
    """Pola formularza, do których asystent (B) może podsunąć projekt tekstu."""

    UZASADNIENIE = "UZASADNIENIE"
    WNIOSKI_IPRZ = "WNIOSKI_IPRZ"
    UMOTYWOWANIE_WNIOSKU = "UMOTYWOWANIE_WNIOSKU"  # część III


class ReminderKind(StrEnum):
    # proces (A)
    CRITERIA_DUE = "CRITERIA_DUE"
    CRITERIA_OVERDUE = "CRITERIA_OVERDUE"
    ASSESSMENT_DUE = "ASSESSMENT_DUE"
    ASSESSMENT_OVERDUE = "ASSESSMENT_OVERDUE"
    ACK_PENDING = "ACK_PENDING"
    DUE_DATE_CHANGED = "DUE_DATE_CHANGED"
    PROMOTION_DUE = "PROMOTION_DUE"  # obligatoryjny stopień (art. 89 ust. 2)
    OBJECTION_WINDOW = "OBJECTION_WINDOW"
    # notatki i HR partner (B)
    NOTE_NUDGE = "NOTE_NUDGE"
    COVERAGE_NUDGE = "COVERAGE_NUDGE"
    RECENCY_NUDGE = "RECENCY_NUDGE"
    APPRECIATION_NUDGE = "APPRECIATION_NUDGE"
    PRE_INTERVIEW_NUDGE = "PRE_INTERVIEW_NUDGE"
    RETURN_FROM_ABSENCE = "RETURN_FROM_ABSENCE"
    HR_SIGNAL = "HR_SIGNAL"


class Channel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
