"""Deterministyczny szkielet uzasadnienia i IPRZ — działa bez LLM (§ 5.2 pkt 3, § 6.2).

Zalety i obszary do poprawy chronologicznie; kryteria z oceną ≤ 3 → pozycje z katalogu
działań rozwojowych. Każdy akapit ma listę notatek źródłowych.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.assistant.summarize.evidence import CycleEvidence

GENERATOR = "deterministic:v1"


@dataclass(frozen=True)
class Paragraph:
    text: str
    note_ids: tuple[str, ...]


def _pl(d) -> str:
    return d.strftime("%d.%m.%Y")


def _points(evidence: CycleEvidence, kind: str) -> tuple[list[str], list[str]]:
    lines, ids = [], []
    for item in evidence.items:
        if item.kind != kind:
            continue
        note = evidence.note(item.note_id)
        lines.append(f"– {item.text} ({_pl(note.observed_on)})")
        if item.note_id not in ids:
            ids.append(item.note_id)
    return lines, ids


def justification(evidence: CycleEvidence) -> list[Paragraph]:
    paragraphs = []
    strengths, s_ids = _points(evidence, "strength")
    if strengths:
        paragraphs.append(Paragraph("W ocenianym okresie odnotowano w szczególności:\n" + "\n".join(strengths), tuple(s_ids)))
    improvements, i_ids = _points(evidence, "improvement")
    if improvements:
        paragraphs.append(Paragraph("Obszary wymagające poprawy:\n" + "\n".join(improvements), tuple(i_ids)))
    return paragraphs


def development(evidence: CycleEvidence, actions: dict[str, list[str]]) -> list[Paragraph]:
    names = {c.code: c.name for c in evidence.criteria}
    lines, ids = [], []
    for code in evidence.low_criteria:
        catalog = actions.get(code)
        if not catalog:
            continue
        lines.append(f"– {names.get(code, code).lower()}: {'; '.join(catalog)}")
        for note in evidence.notes:
            if any(r.criterion_code == code and r.value <= 3 for r in note.ratings) and note.id not in ids:
                ids.append(note.id)
        for item in evidence.items:
            if code in item.criteria and item.kind == "improvement" and item.note_id not in ids:
                ids.append(item.note_id)
    paragraphs = []
    if lines:
        intro = (
            "Proponuję podjęcie działań rozwojowych w kierunku:"
            if evidence.low_source == "ocena"
            else "Na podstawie notatek (do potwierdzenia po wpisaniu ocen cząstkowych) proponuję działania rozwojowe w kierunku:"
        )
        paragraphs.append(Paragraph(intro + "\n" + "\n".join(lines), tuple(ids)))
    improvements, i_ids = _points(evidence, "improvement")
    if improvements:
        paragraphs.append(
            Paragraph("Obszary do rozwoju wskazane w notatkach:\n" + "\n".join(improvements), tuple(i_ids))
        )
    return paragraphs
