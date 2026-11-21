"""Reguły przypomnień o notatkach (§ 5.4) — czyste funkcje, bez bazy i kontenera.

Komunikaty są bezosobowe („Brak notatki od…”), żeby nie zgadywać rodzaju gramatycznego.
Pokrycie kryteriów liczymy na razie tylko z suwaków; po dodaniu LLM doliczymy `criteria_hint`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.assistant.config import NudgesConfig
from app.assistant.notes.stats import compute_stats, uncovered
from app.contracts.enums import EvaluationState, ReminderKind
from app.contracts.models import Absence, CriterionDef, Employee, EvaluationSummary, Note

# Notatki mają sens do rozmowy oceniającej; później przypominanie o nich tylko przeszkadza.
ACTIVE_STATES = frozenset(
    {EvaluationState.CYCLE_OPEN, EvaluationState.CRITERIA_CONFIRMED, EvaluationState.OBSERVATION}
)


@dataclass(frozen=True)
class Finding:
    kind: ReminderKind
    subject_id: str
    text: str


@dataclass(frozen=True)
class CoverageGap:
    """Kryterium bez obserwacji u danej osoby — w zestawieniu grupujemy po kryterium."""

    subject_id: str
    criterion: CriterionDef


def pl_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def count(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


def cycle_start(evaluation: EvaluationSummary, history: Sequence[EvaluationSummary], employee: Employee) -> date | None:
    """Od kiedy liczyć „brak notatki”: początek okresu, a przed ustaleniem kryteriów — koniec poprzedniej oceny."""
    if evaluation.period_from:
        return evaluation.period_from
    if evaluation.criteria_set_on:
        return evaluation.criteria_set_on
    for previous in reversed(history):
        if previous.result:
            return previous.result.acknowledged_on or previous.result.assessed_on
    return employee.indefinite_since


def no_note(notes: Sequence[Note], start: date | None, today: date, cfg: NudgesConfig, subject_id: str) -> list[Finding]:
    last = max((n.observed_on for n in notes), default=None)
    if last is not None:
        days = (today - last).days
        if days > cfg.no_note_after_days:
            return [Finding(ReminderKind.NOTE_NUDGE, subject_id, f"Brak notatki od {days} dni (ostatnia: {pl_date(last)}).")]
        return []
    if start is not None and (today - start).days > cfg.no_note_after_days:
        days = (today - start).days
        text = f"Brak notatek w tym cyklu (trwa od {pl_date(start)}, {count(days, 'dzień', 'dni', 'dni')})."
        return [Finding(ReminderKind.NOTE_NUDGE, subject_id, text)]
    return []


def no_positive(
    notes: Sequence[Note], start: date | None, today: date, cfg: NudgesConfig, subject_id: str
) -> list[Finding]:
    if not notes:  # brak notatek w ogóle obsługuje no_note
        return []
    last_positive = max((n.observed_on for n in notes if n.strengths), default=None)
    if last_positive is not None:
        days = (today - last_positive).days
        if days > cfg.no_positive_after_days:
            months = days // 30
            text = (
                f"Ostatnia pozytywna obserwacja: {pl_date(last_positive)} ({months} mies. temu). Może warto docenić?"
            )
            return [Finding(ReminderKind.APPRECIATION_NUDGE, subject_id, text)]
        return []
    if start is not None and (today - start).days > cfg.no_positive_after_days:
        text = "W tym cyklu nie ma jeszcze pozytywnej obserwacji. Może warto docenić?"
        return [Finding(ReminderKind.APPRECIATION_NUDGE, subject_id, text)]
    return []


def recency(
    notes: Sequence[Note], due: date | None, today: date, cfg: NudgesConfig, subject_id: str
) -> list[Finding]:
    if due is None or not 0 <= (due - today).days <= cfg.recency_window_days:
        return []
    if len(notes) < cfg.recency_min_notes:
        return []
    since = today - timedelta(days=cfg.recency_window_days)
    recent = sum(1 for n in notes if n.observed_on >= since)
    share = recent / len(notes)
    if share < cfg.recency_share_threshold:
        return []
    months = round(cfg.recency_window_days / 30)
    text = (
        f"{round(share * 100)}% notatek pochodzi z ostatnich {months} mies. "
        "Przed oceną przypomnij sobie też początek okresu."
    )
    return [Finding(ReminderKind.RECENCY_NUDGE, subject_id, text)]


def pre_interview(
    notes: Sequence[Note], gaps: Sequence[CoverageGap], due: date | None, today: date, cfg: NudgesConfig, subject_id: str
) -> list[Finding]:
    if due is None or not cfg.pre_interview_days:
        return []
    days = (due - today).days
    if not 0 <= days <= max(cfg.pre_interview_days):
        return []
    text = f"Ocena za {count(days, 'dzień', 'dni', 'dni')} ({pl_date(due)}): {count(len(notes), 'notatka', 'notatki', 'notatek')}"
    if gaps:
        text += f", bez obserwacji: {_names(gaps)}"
    return [Finding(ReminderKind.PRE_INTERVIEW_NUDGE, subject_id, text + ".")]


def _names(gaps: Sequence[CoverageGap]) -> str:
    return ", ".join(g.criterion.name for g in gaps)


def coverage(gaps: Sequence[CoverageGap], n_criteria: int, subject_id: str) -> list[Finding]:
    if not gaps:
        return []
    if len(gaps) == n_criteria:
        text = "Żadne kryterium oceny nie ma jeszcze obserwacji z suwakiem."
    else:
        text = f"Kryteria bez obserwacji: {_names(gaps)}."
    return [Finding(ReminderKind.COVERAGE_NUDGE, subject_id, text)]


def coverage_gaps(
    notes: Sequence[Note],
    criteria: Sequence[CriterionDef],
    start: date | None,
    today: date,
    cfg: NudgesConfig,
    subject_id: str,
) -> list[CoverageGap]:
    """Kryteria bez suwaka. Bez notatek nie zgłaszamy (to robi no_note), w świeżym cyklu też nie."""
    if not notes or not criteria:
        return []
    if start is None or (today - start).days < cfg.coverage_min_cycle_days:
        return []
    stats = compute_stats(notes, criteria_codes=[c.code for c in criteria])
    missing = set(uncovered(stats))
    return [CoverageGap(subject_id, c) for c in criteria if c.code in missing]


def returned_from_absence(
    absences: Sequence[Absence], notes: Sequence[Note], today: date, cfg: NudgesConfig, subject_id: str
) -> list[Finding]:
    for absence in sorted(absences, key=lambda a: a.end, reverse=True):
        length = (absence.end - absence.start).days + 1
        since_return = (today - absence.end).days
        if length < cfg.return_min_absence_days or not 0 < since_return <= cfg.return_window_days:
            continue
        if any(n.observed_on > absence.end for n in notes):
            return []  # po powrocie już była notatka / rozmowa
        text = f"Powrót po nieobecności ({count(length, 'dzień', 'dni', 'dni')}, do {pl_date(absence.end)}). Może krótka rozmowa?"
        return [Finding(ReminderKind.RETURN_FROM_ABSENCE, subject_id, text)]
    return []


@dataclass(frozen=True)
class SubjectCheck:
    findings: list[Finding]
    gaps: list[CoverageGap]  # także zawarte w findings; osobno dla UI i statystyk


def check_subject(
    *,
    subject: Employee,
    evaluation: EvaluationSummary,
    history: Sequence[EvaluationSummary],
    notes: Sequence[Note],
    all_notes: Sequence[Note],
    criteria: Sequence[CriterionDef],
    absences: Sequence[Absence],
    today: date,
    cfg: NudgesConfig,
) -> SubjectCheck:
    """Wszystkie reguły dla jednej osoby. `notes` — z bieżącego cyklu, `all_notes` — wszystkie autora o tej osobie."""
    if evaluation.state not in ACTIVE_STATES:
        return SubjectCheck([], [])
    start = cycle_start(evaluation, history, subject)
    sid = subject.id
    gaps = coverage_gaps(notes, criteria, start, today, cfg, sid)
    before_interview = pre_interview(notes, gaps, evaluation.due_date, today, cfg, sid)
    findings = [
        *no_note(notes, start, today, cfg, sid),
        # przed rozmową braki pokrycia są już w komunikacie o ocenie
        *(before_interview or coverage(gaps, len(criteria), sid)),
        *recency(notes, evaluation.due_date, today, cfg, sid),
        *no_positive(notes, start, today, cfg, sid),
        *returned_from_absence(absences, all_notes, today, cfg, sid),
    ]
    return SubjectCheck(findings, gaps)
