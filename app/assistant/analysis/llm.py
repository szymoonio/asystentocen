"""Słowna analiza zespołu lub osoby z LLM (§ 6).

Pipeline jak przy podsumowaniu cyklu: detektor danych wrażliwych → pseudonimizacja →
jedno wywołanie structured → sprawdzenie odwołań do notatek → de-pseudonimizacja lokalnie.
Mocne i słabe strony bez poprawnego odwołania do notatki odrzucamy (nie pokazujemy).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.assistant.analysis.data import PersonData, TeamData
from app.assistant.llm import LLMClient, LLMError, generator_id
from app.assistant.llm.prompts import load_prompt
from app.assistant.privacy import PseudonymSession, Pseudonymizer, screen_notes
from app.contracts.models import Note

TEAM_TASK = "analyze_team"
PERSON_TASK = "analyze_person"
MAX_NOTES_PER_PERSON_TEAM = 8


class Point(BaseModel):
    text: str = Field(description="Jedno zdanie lub dwa.")
    note_refs: list[str] = Field(default_factory=list, description="Identyfikatory notatek, np. N3.")


class Analysis(BaseModel):
    summary: str = Field(description="3–5 zdań podsumowania.")
    strengths: list[Point]
    weaknesses: list[Point]
    recommendations: list[Point]


@dataclass(frozen=True)
class Ref:
    subject_id: str
    note_id: str
    alias: str


@dataclass
class AnalysisPoint:
    text: str
    refs: list[Ref] = field(default_factory=list)


@dataclass
class AnalysisResult:
    generator: str
    summary: str = ""
    strengths: list[AnalysisPoint] = field(default_factory=list)
    weaknesses: list[AnalysisPoint] = field(default_factory=list)
    recommendations: list[AnalysisPoint] = field(default_factory=list)
    used_notes: int = 0
    excluded_notes: int = 0
    dropped: int = 0  # punkty bez poprawnego źródła


def input_key(notes: list[Note]) -> str:
    raw = "|".join(sorted(f"{n.id}:{n.version}" for n in notes))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _pl(d) -> str:
    return d.strftime("%d.%m.%Y")


def _note_block(alias: str, note: Note, session: PseudonymSession, names: dict[str, str], scale_labels) -> list[str]:
    lines = [f'<notatka id="{alias}" data="{_pl(note.observed_on)}">']
    if note.body:
        lines.append("Opis: " + session.apply(note.body))
    lines += [f"+ {session.apply(s)}" for s in note.strengths]
    lines += [f"- {session.apply(s)}" for s in note.improvements]
    if note.ratings:
        lines.append("Suwaki: " + ", ".join(
            f"{names.get(r.criterion_code, r.criterion_code)} — {scale_labels(r.value)}" for r in note.ratings))
    lines.append("</notatka>")
    return lines


def _criteria_lines(person: PersonData) -> list[str]:
    out = []
    for r in person.criteria:
        if r.mean:
            t = {"up": ", rośnie", "down": ", spada"}.get(r.trend, "")
            out.append(f"- {r.name}: średnia {r.mean.text} ({r.mean.label}), {r.mean.count}{t}")
        else:
            out.append(f"- {r.name}: brak ocen z suwaków")
    return out


@dataclass
class _Request:
    system: str
    user: str
    session: PseudonymSession
    refs: dict[str, Ref]
    used: int
    excluded: int


def build_person_request(person: PersonData, pseudonymizer: Pseudonymizer, scale_labels) -> _Request:
    session = pseudonymizer.session()
    label = session.label_for(person.employee)
    screened = screen_notes(person.notes)
    names = {r.code: r.name for r in person.criteria}
    lines = [
        f"Osoba: {label}. Zakres: {person.scope}. Notatek w zakresie: {len(person.notes)}.",
        "Średnie z suwaków w notatkach (skala 1–9):", *_criteria_lines(person),
    ]
    if screened.excluded:
        lines.append(f"Pominięto {len(screened.excluded)} notatki z danymi wrażliwymi — nie odwołuj się do nich.")
    lines.append("\nNotatki przełożonego (dane):")
    refs: dict[str, Ref] = {}
    for i, note in enumerate(screened.included, 1):
        alias = f"N{i}"
        refs[alias] = Ref(note.subject_id, note.id, alias)
        lines += _note_block(alias, note, session, names, scale_labels)
    prompt = load_prompt(PERSON_TASK)
    return _Request(prompt.text, "\n".join(lines), session, refs, len(screened.included), len(screened.excluded))


def build_team_request(team: TeamData, pseudonymizer: Pseudonymizer, scale_labels) -> _Request:
    session = pseudonymizer.session()
    lines = [f"Zespół: {len(team.people)} osób. Notatek w bieżących okresach oceny: {team.notes_count}."]
    lines.append("Średnie zespołu z suwaków (skala 1–9):")
    lines += [f"- {r.name}: {r.mean.text} ({r.mean.label}), {r.mean.count}" if r.mean else f"- {r.name}: brak ocen"
              for r in team.criteria]
    refs: dict[str, Ref] = {}
    used = excluded = 0
    k = 0
    for person in team.people:
        label = session.label_for(person.employee)
        screened = screen_notes(person.notes)
        used += min(len(screened.included), MAX_NOTES_PER_PERSON_TEAM)
        excluded += len(screened.excluded)
        lines += ["", f"## {label} — notatek: {len(person.notes)}, ostatnia: {person.when}"]
        lines += _criteria_lines(person)
        names = {r.code: r.name for r in person.criteria}
        for note in screened.included[-MAX_NOTES_PER_PERSON_TEAM:]:
            k += 1
            alias = f"N{k}"
            refs[alias] = Ref(note.subject_id, note.id, alias)
            lines += _note_block(alias, note, session, names, scale_labels)
    if excluded:
        lines.append(f"\nPominięto {excluded} notatki z danymi wrażliwymi.")
    prompt = load_prompt(TEAM_TASK)
    return _Request(prompt.text, "\n".join(lines), session, refs, used, excluded)


def _points(items: list[Point], req: _Request, *, need_refs: bool) -> tuple[list[AnalysisPoint], int]:
    out, dropped = [], 0
    for p in items:
        refs = [req.refs[r] for r in dict.fromkeys(p.note_refs) if r in req.refs]
        if need_refs and not refs:
            dropped += 1
            continue
        text = req.session.restore(p.text.strip())
        if text:
            out.append(AnalysisPoint(text, refs))
    return out, dropped


def run(task: str, req: _Request, llm: LLMClient) -> AnalysisResult:
    """Rzuca `LLMError` z `user_message`."""
    if not req.refs:
        raise LLMError("brak notatek", user_message="Brak notatek, na których asystent mógłby oprzeć analizę.")
    output = llm.structured(task, req.system, req.user, Analysis)
    result = AnalysisResult(generator=generator_id(llm, task, load_prompt(task).version),
                            summary=req.session.restore(output.summary.strip()),
                            used_notes=req.used, excluded_notes=req.excluded)
    result.strengths, d1 = _points(output.strengths, req, need_refs=True)
    result.weaknesses, d2 = _points(output.weaknesses, req, need_refs=True)
    result.recommendations, _ = _points(output.recommendations, req, need_refs=False)
    result.dropped = d1 + d2
    return result
