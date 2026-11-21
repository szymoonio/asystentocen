"""Deterministyczne zestawienia do zakładki Analiza (bez LLM).

Zakres notatek osoby: notatki z jej bieżącego okresu oceny; gdy nie podlega ocenie —
ostatnie 12 miesięcy. Notatki są zawsze notatkami zalogowanego przełożonego (autora).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.assistant.display import Mean, ago, chart_series, mean_of, ratings_by_criterion, trend
from app.assistant.notes.criteria import criteria_for
from app.contracts.models import Employee, EvaluationSummary, Note
from app.contracts.regulation import Scale

MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


@dataclass
class CriterionRow:
    code: str
    name: str
    mean: Mean | None
    trend: str = ""


@dataclass
class PersonData:
    employee: Employee
    evaluation: EvaluationSummary | None
    notes: list[Note]  # zakres analizy, chronologicznie
    all_notes: list[Note]
    last: date | None
    when: str
    criteria: list[CriterionRow]
    overall: Mean | None
    scope: str  # opis zakresu dla UI

    @property
    def by_code(self) -> dict[str, CriterionRow]:
        return {r.code: r for r in self.criteria}

    @property
    def strengths(self) -> list[tuple[date, str, str]]:
        return [(n.observed_on, s, n.id) for n in reversed(self.notes) for s in n.strengths]

    @property
    def improvements(self) -> list[tuple[date, str, str]]:
        return [(n.observed_on, s, n.id) for n in reversed(self.notes) for s in n.improvements]


def _months_back(today: date, n: int) -> list[tuple[int, int]]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return list(reversed(out))


def activity(notes: list[Note], today: date, months: int = 12) -> list[tuple[str, int, str]]:
    """[(etykieta, liczba notatek, podpowiedź)] dla ostatnich `months` miesięcy."""
    counts: dict[tuple[int, int], int] = {}
    for n in notes:
        key = (n.observed_on.year, n.observed_on.month)
        counts[key] = counts.get(key, 0) + 1
    out = []
    for y, m in _months_back(today, months):
        label = MONTHS_SHORT[m - 1] + (f" {str(y)[2:]}" if m == 1 or (y, m) == _months_back(today, months)[0] else "")
        out.append((label, counts.get((y, m), 0), f"{MONTHS_SHORT[m - 1]} {y}"))
    return out


def person_data(c, notes_all: list[Note], employee: Employee, scale: Scale, today: date) -> PersonData:
    evaluation = c.evaluations.current_for(employee.id)
    if evaluation:
        notes = [n for n in notes_all if n.evaluation_id == evaluation.id]
        start = evaluation.period_from or evaluation.criteria_set_on
        scope = f"bieżący okres oceny{f' (od {start:%d.%m.%Y})' if start else ''}"
    else:
        notes = [n for n in notes_all if (today - n.observed_on).days <= 365]
        scope = "ostatnie 12 miesięcy"
    choice = criteria_for(evaluation, c.catalog)
    by_code = ratings_by_criterion(notes)
    codes = list(choice.current_codes) + sorted(code for code in by_code if code not in choice.current_codes)
    rows = []
    for code in codes:
        items = by_code.get(code, [])
        try:
            name = c.catalog.get(code).name
        except KeyError:
            name = code
        rows.append(CriterionRow(code, name, mean_of([v for _, v, _ in items], scale), trend(items)))
    all_values = [v for items in by_code.values() for _, v, _ in items]
    last = max((n.observed_on for n in notes_all), default=None)
    return PersonData(employee, evaluation, notes, notes_all, last, ago(last, today), rows,
                      mean_of(all_values, scale), scope)


def person_chart(c, person: PersonData) -> dict:
    names = {r.code: r.name for r in person.criteria}
    return chart_series(person.all_notes, names)


@dataclass
class TeamData:
    people: list[PersonData]
    criteria: list[CriterionRow]  # średnia zespołu per kryterium
    activity: list[tuple[str, int, str]]
    stale: list[PersonData] = field(default_factory=list)

    @property
    def notes_count(self) -> int:
        return sum(len(p.notes) for p in self.people)

    @property
    def max_activity(self) -> int:
        return max((n for _, n, _ in self.activity), default=0) or 1


def team_data(c, notes_by_subject: dict[str, list[Note]], subordinates: list[Employee], scale: Scale,
              today: date, stale_after_days: int) -> TeamData:
    people = [person_data(c, notes_by_subject.get(e.id, []), e, scale, today) for e in subordinates]
    people.sort(key=lambda p: (p.employee.last_name, p.employee.first_name))
    order: list[str] = [cr.code for cr in c.catalog.all()]
    pooled: dict[str, list[int]] = {}
    for p in people:
        for code, items in ratings_by_criterion(p.notes).items():
            pooled.setdefault(code, []).extend(v for _, v, _ in items)
    used = {r.code for p in people for r in p.criteria}
    criteria = [
        CriterionRow(code, c.catalog.get(code).name, mean_of(pooled.get(code, []), scale))
        for code in order if code in used or code in pooled
    ]  # fmt: skip
    all_notes = [n for p in people for n in p.all_notes]
    stale = [p for p in people if p.evaluation and (p.last is None or (today - p.last).days > stale_after_days)]
    return TeamData(people, criteria, activity(all_notes, today), stale)
