"""Walidator cytowań (§ 6.2 krok 5) — deterministyczny, odrzuca zamiast „naprawiać”.

Sprawdza akapit na tekście PO pseudonimizacji (tak, jak widział go model):
- co najmniej jeden cytat, każdy cytat to notatka z tego cyklu;
- etykiety [OSOBA_n] / [EMAIL_n] … (poza ocenianym) i liczby w akapicie występują w cytowanych notatkach;
- brak słów o wyniku oceny, punktach i danych wrażliwych;
- limit długości.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.assistant.privacy import detect
from app.assistant.privacy.pseudonymize import LABEL

MAX_CHARS = 1500
NUMBER = re.compile(r"\d+")
FORBIDDEN = [
    (re.compile(r"ocen\w*\s+(pozytywn|negatywn)\w*", re.IGNORECASE), "wynik oceny (pozytywna/negatywna)"),
    (re.compile(r"\b(pozytywn|negatywn)\w*\s+ocen", re.IGNORECASE), "wynik oceny (pozytywna/negatywna)"),
    (re.compile(r"\bpkt\b|\bpunkt(y|ów|ach|ami)\b", re.IGNORECASE), "punkty oceny"),
    (re.compile(r"\bśredni[aąej]\b", re.IGNORECASE), "średnia ocen"),
]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: tuple[str, ...] = ()


def validate_paragraph(
    text: str, refs: Sequence[str], sources: Mapping[str, str], *, subject_label: str = "[OSOBA_1]"
) -> Verdict:
    """`sources`: alias notatki (np. N3) → jej pseudonimizowany tekst wraz z datą.

    Etykieta ocenianego (`subject_label`) jest zawsze dozwolona — każda notatka dotyczy jego.
    """
    reasons: list[str] = []
    text = text.strip()
    if not text:
        return Verdict(False, ("pusty akapit",))
    if len(text) > MAX_CHARS:
        reasons.append(f"za długi akapit ({len(text)} znaków)")
    cited = [r for r in dict.fromkeys(refs)]
    if not cited:
        reasons.append("brak cytowanej notatki")
    unknown = [r for r in cited if r not in sources]
    if unknown:
        reasons.append(f"cytat spoza cyklu: {', '.join(unknown)}")
    corpus = "\n".join(sources[r] for r in cited if r in sources)
    known = {m.group(0) for m in LABEL.finditer(corpus)} | {subject_label}
    missing_labels = sorted({m.group(0) for m in LABEL.finditer(text)} - known)
    if missing_labels:
        reasons.append(f"osoby spoza cytowanych notatek: {', '.join(missing_labels)}")
    corpus_numbers = set(NUMBER.findall(corpus))
    stray = sorted({n for n in NUMBER.findall(LABEL.sub("", text)) if n not in corpus_numbers})
    if stray:
        reasons.append(f"liczby spoza cytowanych notatek: {', '.join(stray)}")
    for pattern, label in FORBIDDEN:
        if pattern.search(text):
            reasons.append(f"niedozwolona treść: {label}")
    if detect(text):
        reasons.append("dane wrażliwe")
    return Verdict(not reasons, tuple(reasons))
