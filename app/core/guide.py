"""Podpowiedzi bez LLM: „Do zrobienia” na pulpicie, panel obserwacji, porady asystenta przy ocenie
i przygotowanie do rozmowy oceniającej (§ 10). Wszystko deterministyczne — z terminów i z notatek
(port NotesReader). Teksty mają być krótkie: jedna linijka na rzecz do zrobienia.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Any

from app.contracts.enums import EvaluationState, Level, Role
from app.contracts.models import CriterionRef, CriterionStats, EvaluationSummary, Note, UserContext
from app.core.rules import careers
from app.core.rules.scoring import level_for

# Adresy stron modułu B, do których prowadzimy (poza kontraktem — trzymamy je w jednym miejscu).
B_NEW_NOTE = "{teczka}/nowa"
B_HR_PREP = "/asystent/hr/przygotowanie?rodzaj={kind}&osoba={employee_id}"
B_NOTES_SUMMARY = "/asystent/analiza/fragment?osoba={employee_id}&wroc={back}"  # podsumowanie LLM do osadzenia


def new_note_url(c, employee_id: str) -> str:
    return B_NEW_NOTE.format(teczka=c.notes.teczka_url(employee_id))


def hr_prep_url(kind: str, employee_id: str) -> str:
    return B_HR_PREP.format(kind=kind, employee_id=employee_id)


def notes_summary_url(employee_id: str, back: str) -> str:
    from urllib.parse import quote

    return B_NOTES_SUMMARY.format(employee_id=employee_id, back=quote(back, safe=""))


@dataclass(frozen=True)
class NotePoint:
    """Zaleta albo obszar do poprawy z notatek, zgrupowany po treści (×N = w ilu notatkach)."""

    text: str
    count: int
    last: date
    note_id: str


def grouped_points(notes: Sequence[Note], attr: str) -> list[NotePoint]:
    groups: dict[str, list] = {}
    for n in notes:
        for text in getattr(n, attr):
            key = " ".join(text.split()).casefold()
            if not key:
                continue
            g = groups.setdefault(key, [text.strip(), 0, n.observed_on, n.id])
            g[1] += 1
            if n.observed_on >= g[2]:
                g[0], g[2], g[3] = text.strip(), n.observed_on, n.id
    points = [NotePoint(t, c, d, nid) for t, c, d, nid in groups.values()]
    return sorted(points, key=lambda p: (-p.count, -p.last.toordinal(), p.text))


# --- liczebniki i czas ------------------------------------------------------------------------


def plural(n: int, one: str, few: str, many: str) -> str:
    """1 ocena · 2 oceny · 5 ocen · 22 oceny · 12 ocen."""
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def ago(day: date | None, today: date) -> str:
    """Ile czasu minęło, słownie: „wczoraj”, „5 dni temu”, „3 tygodnie temu”, „2 miesiące temu”."""
    if day is None:
        return "brak notatek"
    days = (today - day).days
    if days <= 0:
        return "dziś"
    if days == 1:
        return "wczoraj"
    if days < 14:
        return f"{days} dni temu"
    if days < 60:
        weeks = days // 7
        return f"{weeks} {plural(weeks, 'tydzień', 'tygodnie', 'tygodni')} temu"
    if days < 365:
        months = days // 30
        return f"{months} {plural(months, 'miesiąc', 'miesiące', 'miesięcy')} temu"
    return "ponad rok temu"


def until(day: date, today: date) -> str:
    days = (day - today).days
    if days < 0:
        late = -days
        return f"{late} {plural(late, 'dzień', 'dni', 'dni')} po terminie"
    if days == 0:
        return "dziś"
    if days == 1:
        return "jutro"
    return f"za {days} dni"


def tone_for_due(day: date, today: date) -> str:
    left = (day - today).days
    return "danger" if left < 0 else "warn" if left <= 30 else ""


# --- pulpit: do zrobienia -------------------------------------------------------------------


@dataclass(frozen=True)
class Todo:
    who: str
    what: str
    due: date | None
    when: str
    url: str
    tone: str = ""


def _evaluator_todo(ev: EvaluationSummary, name: str, today: date) -> Todo | None:
    url = f"/core/oceny/{ev.id}"
    if ev.state == EvaluationState.CYCLE_OPEN and ev.criteria_due_date:
        due, what, url = ev.criteria_due_date, "ustal kryteria oceny", url + "#czesc-1"
    elif ev.state == EvaluationState.OBSERVATION and ev.due_date:
        due, what, url = ev.due_date, "rozmowa i ocena", url + "/przygotowanie"
    elif ev.state == EvaluationState.INTERVIEW_HELD and ev.due_date:
        due, what, url = ev.due_date, "dokończ arkusz oceny", url + "#czesc-2"
    else:
        return None
    return Todo(name, what, due, until(due, today), url, tone_for_due(due, today))


def _own_todo(ev: EvaluationSummary, today: date) -> Todo | None:
    url = f"/core/oceny/{ev.id}"
    if ev.state == EvaluationState.CRITERIA_CONFIRMED:
        return Todo("Twoja ocena", "potwierdź kryteria", None, "teraz", url + "#czesc-1", "warn")
    if ev.state == EvaluationState.AWAITING_ACK:
        return Todo("Twoja ocena", "zapoznaj się z oceną", None, "teraz", url + "#czesc-2", "warn")
    return None


def todo_evaluations(c, user: UserContext, today: date) -> list[Todo]:
    """Najbliższe kroki ocen, w których to użytkownik ma coś zrobić — od najpilniejszych."""
    items: list[Todo] = []
    own = c.evaluations.current_for(user.employee_id)
    if own and (t := _own_todo(own, today)):
        items.append(t)
    people = {e.id: e for e in c.employees.all()}
    for ev in c.evaluations.for_evaluator(user.employee_id):
        if t := _evaluator_todo(ev, people[ev.employee_id].full_name, today):
            items.append(t)
    if user.has(Role.KADRY):
        for emp in people.values():
            promo = careers.obligatory_promotion(emp, c.evaluations.history(emp.id))
            if promo:
                due = promo.deadline.date
                items.append(Todo(emp.full_name, "przyznaj kolejny stopień", due, until(due, today),
                                  "/core/kadry", tone_for_due(due, today)))
    return sorted(items, key=lambda t: (t.due is not None, t.due or date.min))


@dataclass(frozen=True)
class NoteTodo:
    who: str
    position: str
    last: date | None
    when: str
    url: str
    teczka: str


def last_note_dates(c, author_id: str) -> dict[str, date | None]:
    out: dict[str, date | None] = {}
    for emp in c.employees.subordinates(author_id):
        notes = c.notes.notes_for(author_id, emp.id)
        out[emp.id] = max((n.observed_on for n in notes), default=None)
    return out


def todo_notes(c, user: UserContext, today: date) -> list[NoteTodo]:
    """Podwładni, o których najdawniej nie było notatki (brak notatek = najpierw)."""
    people = {e.id: e for e in c.employees.subordinates(user.employee_id)}
    lasts = last_note_dates(c, user.employee_id)
    rows = [
        NoteTodo(people[i].full_name, people[i].position.title, d, ago(d, today),
                 new_note_url(c, i), c.notes.teczka_url(i))
        for i, d in lasts.items()
    ]
    return sorted(rows, key=lambda r: (r.last is not None, r.last or date.min, r.who))


# --- panel obserwacji ----------------------------------------------------------------------

LEVEL_TONE = {
    Level.ZNACZNIE_PONIZEJ: "l1", Level.PONIZEJ: "l2", Level.NA_POZIOMIE: "l3",
    Level.POWYZEJ: "l4", Level.ZNACZNIE_POWYZEJ: "l5",
}  # fmt: skip


def mean_of(st: CriterionStats) -> Fraction | None:
    counts = {p: n for p, n in st.distribution.items() if n > 0}
    total = sum(counts.values())
    if st.n_ratings <= 0 or total == 0:
        return None
    return Fraction(sum(p * n for p, n in counts.items()), total)


def fmt_num(value: Fraction | float) -> str:
    return f"{round(float(value), 1):g}".replace(".", ",")


def stats_view(st: CriterionStats) -> dict[str, Any] | None:
    """Jedno kryterium w panelu: średnia z suwaków w kolorze poziomu i liczba ocen.
    Kontrakt dopuszcza None w medianie i średnich połówek oraz wpisy z n_ratings == 0."""
    mean = mean_of(st)
    if mean is None:
        return None
    n = sum(v for v in st.distribution.values() if v > 0)
    trend = ""
    first, second = st.first_half_mean, st.second_half_mean
    if first is not None and second is not None and abs(second - first) >= 1:
        trend = "up" if second > first else "down"
    return {
        "mean": fmt_num(mean), "value": mean, "tone": LEVEL_TONE[level_for(mean)],
        "count": f"{n} {plural(n, 'ocena', 'oceny', 'ocen')}", "trend": trend,
    }


# --- porady asystenta HR przy ocenie ----------------------------------------------------------


@dataclass
class Tips:
    headline: str
    tips: list[str] = field(default_factory=list)
    actions: list[tuple[str, str, bool]] = field(default_factory=list)  # (etykieta, url, główny)


def tips_for(
    *, ev: EvaluationSummary, role: str | None, today: date, notes: Sequence[Note] | None,
    warnings: int = 0, objection_until: date | None = None, new_note: str | None = None,
) -> Tips | None:
    """Krótkie, proaktywne porady zależne od etapu i roli. Bez LLM — z przepisów i terminów."""
    url = f"/core/oceny/{ev.id}"
    s = ev.state
    if role == "EVALUATOR":
        if s == EvaluationState.CYCLE_OPEN:
            due = ev.criteria_due_date
            t = Tips(f"Ustal kryteria{f' do {due:%d.%m}' if due else ''} — po rozmowie z ocenianym (§ 5).")
            t.tips = ["Wybierz najwyżej 3 kryteria dodatkowe — te, które najlepiej opisują obowiązki na stanowisku.",
                      "Powiedz wprost, czego oczekujesz w każdym kryterium. To punkt odniesienia przy ocenie."]
            t.actions = [("Przygotuj rozmowę rozpoczynającą", hr_prep_url("rozpoczynajaca", ev.employee_id), True),
                         ("Do części I", url + "#czesc-1", False)]
            return t
        if s == EvaluationState.CRITERIA_CONFIRMED:
            return Tips("Czeka na potwierdzenie kryteriów przez ocenianego.",
                        ["Okres oceny zacznie się w dniu potwierdzenia. Warto przypomnieć o tym ocenianemu."])
        if s == EvaluationState.OBSERVATION:
            left = (ev.due_date - today).days if ev.due_date else None
            notes = list(notes or [])
            last = max((n.observed_on for n in notes), default=None)
            if left is not None and left <= 45:
                head = f"Termin oceny {until(ev.due_date, today)} — czas umówić rozmowę oceniającą."
            else:
                head = "Trwa okres oceny — zbieraj krótkie notatki na bieżąco."
            t = Tips(head)
            t.tips.append(f"Masz {len(notes)} {plural(len(notes), 'notatkę', 'notatki', 'notatek')} z tego okresu"
                          + (f", ostatnią {ago(last, today)}." if last else "."))
            if notes and all((today - n.observed_on).days <= 60 for n in notes) and len(notes) < 4:
                t.tips.append("Notatki są tylko z ostatnich tygodni — przypomnij sobie też początek okresu.")
            t.actions = [("Pomóż mi przygotować się do rozmowy", url + "/przygotowanie", True)]
            if new_note:
                t.actions.append(("Dodaj notatkę", new_note, False))
            return t
        if s == EvaluationState.INTERVIEW_HELD:
            t = Tips(f"Sporządź ocenę{f' do {ev.due_date:%d.%m}' if ev.due_date else ''}.")
            if warnings:
                t.tips.append(f"W {warnings} {plural(warnings, 'kryterium', 'kryteriach', 'kryteriach')} ocena odbiega "
                              "od Twoich notatek (⚠). Jeśli świadomie — uzasadnij.")
            t.tips += ["Oceniaj cały okres, nie tylko ostatnie tygodnie.",
                       "Wnioski do IPRZ są obowiązkowe — wpisz to, o czym rozmawialiście."]
            t.actions = [("Do arkusza", url + "#czesc-2", True), ("Ściąga z rozmowy", url + "/przygotowanie", False)]
            return t
        if s == EvaluationState.AWAITING_ACK:
            return Tips("Przekaż ocenę ocenianemu do zapoznania.",
                        ["Jeśli nie może lub nie chce potwierdzić — stwierdź fikcję zapoznania (opis poniżej)."])
        if s == EvaluationState.ACKNOWLEDGED and objection_until:
            return Tips(f"Oceniany może wnieść sprzeciw do {objection_until:%d.%m.%Y}.",
                        ["Bez sprzeciwu ocena stanie się ostateczna automatycznie."])
        if s == EvaluationState.FINAL:
            t = Tips("Ocena jest ostateczna. Nowy okres oceny już trwa.")
            if new_note:
                t.actions = [("Pierwsza notatka w nowym okresie", new_note, False)]
            return t
        return None
    if role == "EMPLOYEE":
        if s == EvaluationState.CRITERIA_CONFIRMED:
            return Tips("Potwierdź, że znasz kryteria i termin oceny.", [],
                        [("Potwierdź", url + "#czesc-1", True)])
        if s == EvaluationState.OBSERVATION:
            return Tips("Trwa okres oceny.",
                        ["Możesz w każdej chwili poprosić przełożonego o rozmowę o postępach."])
        if s == EvaluationState.AWAITING_ACK:
            return Tips("Zapoznaj się z oceną.",
                        ["Od dnia zapoznania masz 7 dni na sprzeciw (art. 83 ust. 1 ustawy)."],
                        [("Przejdź do oceny", url + "#czesc-2", True)])
        if s == EvaluationState.ACKNOWLEDGED and objection_until:
            return Tips(f"Sprzeciw możesz wnieść do {objection_until:%d.%m.%Y}.")
    return None


# --- przygotowanie do rozmowy oceniającej ------------------------------------------------------


@dataclass
class Prep:
    notes_count: int
    last_note: str
    criteria: list[tuple[CriterionRef, dict[str, Any] | None]]
    strengths: list[NotePoint]
    improvements: list[NotePoint]
    topics: list[str]
    outline: list[tuple[str, str, list[str]]]


OUTLINE_BASE = [
    ("Otwarcie", "3 min", ["Cel rozmowy: podsumowanie okresu i plan rozwoju.",
                            "Ocena nie jest jeszcze wpisana — najpierw rozmowa."]),
    ("Spojrzenie ocenianego", "5–10 min", ["Co uważa za swój największy sukces w tym okresie?",
                                            "Co było najtrudniejsze i czego zabrakło?"]),
    ("Obowiązki i kryteria", "15–20 min", []),  # uzupełniane kryteriami
    ("Rozwój zawodowy (IPRZ)", "5–10 min", ["Jakie umiejętności chce rozwijać?",
                                             "Jakie szkolenia lub zadania by w tym pomogły?"]),
    ("Zamknięcie", "3 min", ["Podsumuj ustalenia i następne kroki.",
                              "Powiedz, kiedy dostanie arkusz do zapoznania i że ma 7 dni na sprzeciw."]),
]


def prepare(
    *, ev: EvaluationSummary, criteria: Sequence[CriterionRef],
    stats: dict[str, CriterionStats], notes: Sequence[Note], today: date,
) -> Prep:
    notes = sorted(notes, key=lambda n: n.observed_on, reverse=True)
    views = [(cr, stats_view(stats[cr.code]) if cr.code in stats else None) for cr in criteria]
    strengths = grouped_points(notes, "strengths")
    improvements = grouped_points(notes, "improvements")

    topics: list[str] = []
    if ev.after_negative:
        topics.append("To ponowna ocena po negatywnej — omów, co się zmieniło od poprzedniej oceny.")
    missing, strong = [], []
    for cr, view in views:
        if view is None:
            missing.append(cr.name)
        elif view["value"] <= 4:
            topics.append(f"{cr.name}: średnia z notatek {view['mean']} — zapytaj, co przeszkadza i jakie wsparcie pomoże.")
        elif view["trend"] == "down":
            topics.append(f"{cr.name}: spadek w drugiej połowie okresu — zapytaj o przyczynę.")
        elif view["value"] >= 7:
            strong.append(cr.name)
    if strong:
        topics.append("Doceń konkretnym przykładem: " + ", ".join(strong) + ".")
    if missing:
        topics.append("Brak Twoich obserwacji: " + ", ".join(missing) + " — poproś o przykłady, zanim ocenisz.")
    for p in improvements[:2]:
        topics.append(f"Wróć do: „{p.text}”{f' (w {p.count} notatkach)' if p.count > 1 else ''} — czy jest poprawa?")
    if notes and (today - notes[-1].observed_on).days <= 60:
        topics.append("Wszystkie notatki są z ostatnich tygodni — przypomnij sobie początek okresu.")
    topics.append("Zapytaj o potrzeby szkoleniowe — z tego powstaną obowiązkowe wnioski do IPRZ.")

    outline = []
    for title, minutes, points in OUTLINE_BASE:
        if not points:
            points = ["Przejdź kolejno przez kryteria: " + ", ".join(cr.name for cr in criteria) + ".",
                      "Przy każdym: fakt z notatek → pytanie o perspektywę ocenianego → oczekiwanie na przyszłość."]
        outline.append((title, minutes, points))

    last = notes[0].observed_on if notes else None
    return Prep(len(notes), ago(last, today), views, strengths, improvements, topics, outline)
