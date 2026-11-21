"""Wspólne modele danych. ZAMROŻONE (krok 0) — zmiana tylko po uzgodnieniu A+B, osobnym PR do main.

To są obiekty wymieniane między modułami (DTO), a nie tabele bazy. Każdy moduł trzyma
własne tabele (prefiks `core_` / `asst_`) i mapuje je na te modele na granicy portu.
"""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.enums import (
    PARTIAL_POINTS,
    Channel,
    DraftField,
    EmploymentBasis,
    EvaluationState,
    Level,
    NoteSource,
    Outcome,
    ReminderKind,
    Role,
    SheetType,
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- regulacja -----------------------------------------------------------------------


class CriterionDef(_Model):
    code: str
    name: str
    description: list[str] = []
    aliases: list[str] = []


class CriterionRef(_Model):
    """Kryterium w konkretnej ocenie: obowiązkowe (z arkusza) albo dodatkowe (wybrane)."""

    code: str
    name: str
    mandatory: bool


# --- urząd i pracownicy --------------------------------------------------------------


class Office(_Model):
    name: str
    city: str | None = None
    # adresat sprzeciwu dla arkusza A (pole edytowalne); dla B/C jest stały w sheets.yaml
    objection_addressee_head: str | None = None


class OrgUnit(_Model):
    id: str
    name: str
    parent_id: str | None = None
    city: str | None = None


class Position(_Model):
    title: str
    org_unit_id: str
    is_head_of_office: bool = False  # → arkusz A
    manages_people: bool = False  # bezpośrednie kierowanie pracownikami → arkusz B


class Employee(_Model):
    id: str
    first_name: str
    last_name: str
    email: str | None = None
    position: Position
    basis: EmploymentBasis
    # data zatrudnienia na czas nieokreślony albo mianowania (start pierwszego cyklu)
    indefinite_since: date | None = None
    appointed_year: int | None = None  # rok mianowania (część III)
    grade: int | None = Field(default=None, ge=1, le=9)  # posiadany stopień służbowy
    grade_granted_on: date | None = None
    supervisor_id: str | None = None  # bezpośredni przełożony = oceniający
    extra_roles: list[Role] = []
    active: bool = True

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_urzednik(self) -> bool:
        return self.basis == EmploymentBasis.MIANOWANIE

    @property
    def subject_to_evaluation(self) -> bool:
        return self.basis in (EmploymentBasis.MIANOWANIE, EmploymentBasis.UMOWA_NIEOKRESLONY)


class Absence(_Model):
    """Nieobecność. Celowo BEZ przyczyny (L4 = dane o zdrowiu, art. 9 RODO) — tylko daty."""

    employee_id: str
    start: date
    end: date  # włącznie
    justified: bool = True


class UserContext(_Model):
    employee_id: str
    roles: frozenset[Role]

    def has(self, role: Role) -> bool:
        return role in self.roles


# --- oceny ---------------------------------------------------------------------------


class EvaluationResult(_Model):
    partial_points: dict[str, int]  # kod kryterium → 1/3/5/7/9
    mean_numerator: int
    mean_denominator: int
    level: Level
    outcome: Outcome
    assessed_on: date  # data sporządzenia oceny na piśmie
    acknowledged_on: date | None = None  # data zapoznania (lub fikcji zapoznania)
    promotion_requested: bool | None = None  # None = nie dotyczy (pracownik s.c.)

    @property
    def mean(self) -> Fraction:
        return Fraction(self.mean_numerator, self.mean_denominator)


class EvaluationSummary(_Model):
    id: str
    employee_id: str
    evaluator_id: str | None  # None = oceniający spoza urzędu (np. dla kierownika urzędu)
    sheet: SheetType
    state: EvaluationState
    criteria: list[CriterionRef] = []  # obowiązkowe + wybrane dodatkowe
    criteria_set_on: date | None = None  # data zapoznania z kryteriami = początek okresu
    period_from: date | None = None
    due_date: date | None = None  # termin sporządzenia oceny
    criteria_due_date: date | None = None  # termin na ustalenie kryteriów (§ 7)
    after_negative: bool = False  # cykl po ocenie negatywnej (art. 81 ust. 9)
    result: EvaluationResult | None = None


# --- notatki (teczka) ----------------------------------------------------------------


class CriterionRating(_Model):
    criterion_code: str
    value: int

    @field_validator("value")
    @classmethod
    def _on_scale(cls, value: int) -> int:
        if value not in PARTIAL_POINTS:
            raise ValueError(f"wartość suwaka musi być jedną z {PARTIAL_POINTS}")
        return value


class Note(_Model):
    """Notatka przełożonego o podwładnym — zob. docs/ARCHITEKTURA.md § 5.1."""

    id: str
    author_id: str
    subject_id: str
    evaluation_id: str | None = None
    observed_on: date  # data zdarzenia
    created_at: datetime
    source: NoteSource = NoteSource.TEXT
    body: str = ""
    strengths: list[str] = []
    improvements: list[str] = []
    ratings: list[CriterionRating] = []  # opcjonalne suwaki; brak = brak danych
    version: int = 1
    supersedes_id: str | None = None


class CriterionStats(_Model):
    """Deterministyczne zestawienie z suwaków — docs/ARCHITEKTURA.md § 5.2."""

    criterion_code: str
    n_ratings: int
    distribution: dict[int, int]  # punkty → liczba
    median: float | None = None
    first_half_mean: float | None = None
    second_half_mean: float | None = None
    last_rated_on: date | None = None


class DraftSuggestion(_Model):
    """Projekt tekstu pola formularza od asystenta (B), wyświetlany przez formularz (A)."""

    evaluation_id: str
    field: DraftField
    text: str
    citations: list[str] = []  # ID notatek
    generator: str  # np. "deterministic:v1" albo "claude-opus-5-5:summarize_cycle:v1"
    created_at: datetime


# --- przypomnienia -------------------------------------------------------------------


class Reminder(_Model):
    recipient_id: str
    kind: ReminderKind
    message: str
    dedupe_key: str  # ten sam klucz = to samo przypomnienie (nie wysyłamy drugi raz)
    due: date | None = None
    subject_id: str | None = None  # kogo dotyczy
    evaluation_id: str | None = None
    link: str | None = None
    channel: Channel = Channel.IN_APP
