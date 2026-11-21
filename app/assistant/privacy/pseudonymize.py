"""Pseudonimizacja przed wysłaniem do LLM i odwrócenie lokalnie (§ 6.3).

- Znane osoby z `EmployeeDirectory.all()` → `[OSOBA_n]` (imię i nazwisko, samo imię, samo nazwisko,
  z typowymi formami odmiany).
- E-mail, PESEL, telefon → `[EMAIL_n]`, `[PESEL_n]`, `[TELEFON_n]`.
- Etykiety są stałe w obrębie jednej sesji (np. wszystkie notatki do jednego podsumowania),
  a mapa etykieta → oryginał nie opuszcza serwera.

Odmiana jest przybliżona (reguły dla typowych polskich imion i nazwisk). Imię albo nazwisko
noszone przez kilka osób nie jest zamieniane samo, tylko w pełnym brzmieniu.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.contracts.models import Employee

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
PHONE = re.compile(
    r"(?<![\w+])(?:\+48[\s-]?)?(?:\d{3}[\s-]?\d{3}[\s-]?\d{3}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?!\w)"
)
LABEL = re.compile(r"\[(OSOBA|EMAIL|PESEL|TELEFON)_(\d+)\]")

_SOFTEN = {"d": "dzie", "r": "rze", "k": "ce", "g": "dze", "t": "cie", "ł": "le", "ch": "sze"}


def name_forms(name: str) -> set[str]:
    """Przybliżone formy fleksyjne imienia lub nazwiska (zawsze z formą podstawową)."""
    forms = {name}
    if len(name) < 3:
        return forms
    last = name[-1]
    if last == "a":  # Ewa, Zofia, Magda, Rzetelna, Nowicka, Kadrowa
        stem = name[:-1]
        forms |= {stem + s for s in ("y", "i", "ii", "ie", "ę", "ą", "o", "ej", "iej")}
        for end, soft in _SOFTEN.items():
            if stem.endswith(end):
                forms.add(stem[: -len(end)] + soft)
    elif last in "yi":  # Generalny, Młodszy, Długi
        stem = name[:-1]
        forms |= {stem + s for s in ("ego", "emu", "ym", "im", "iego", "iemu", "y", "i")}
    else:  # Grzegorz, Henryk, Marek, Piotr, Wzór, Pryncypał
        bases = {name}
        if "ó" in name[-3:]:
            idx = name.rfind("ó")
            bases.add(name[:idx] + "o" + name[idx + 1 :])
        if name.endswith(("ek", "ec")):
            bases.add(name[:-2] + name[-1])
        for base in bases:
            forms |= {base + s for s in ("a", "owi", "em", "iem", "u", "e", "ie", "ze")}
    return forms


def _alternation(forms: Iterable[str]) -> str:
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


@dataclass
class _Person:
    employee: Employee
    full: re.Pattern
    first: re.Pattern | None
    last: re.Pattern | None


class Pseudonymizer:
    def __init__(self, people: Sequence[Employee]) -> None:
        firsts = Counter(e.first_name for e in people)
        lasts = Counter(e.last_name for e in people)
        self._people: list[_Person] = []
        for e in people:
            fn, ln = _alternation(name_forms(e.first_name)), _alternation(name_forms(e.last_name))
            self._people.append(
                _Person(
                    employee=e,
                    full=re.compile(rf"(?<!\w)(?:{fn})\s+(?:{ln})(?!\w)"),
                    first=re.compile(rf"(?<!\w)(?:{fn})(?!\w)") if firsts[e.first_name] == 1 else None,
                    last=re.compile(rf"(?<!\w)(?:{ln})(?!\w)") if lasts[e.last_name] == 1 else None,
                )
            )

    def session(self) -> PseudonymSession:
        return PseudonymSession(self)


@dataclass
class PseudonymSession:
    """Jedno wywołanie LLM (lub ich seria) ze wspólną numeracją etykiet."""

    _pz: Pseudonymizer
    mapping: dict[str, str] = field(default_factory=dict)  # etykieta → oryginał
    _person_labels: dict[str, str] = field(default_factory=dict)  # employee_id → etykieta
    _counters: Counter = field(default_factory=Counter)

    def _new_label(self, kind: str, original: str) -> str:
        self._counters[kind] += 1
        label = f"[{kind}_{self._counters[kind]}]"
        self.mapping[label] = original
        return label

    def label_for(self, employee: Employee) -> str:
        """Etykieta osoby; wywołaj najpierw dla ocenianego, żeby był [OSOBA_1]."""
        if employee.id not in self._person_labels:
            self._person_labels[employee.id] = self._new_label("OSOBA", employee.full_name)
        return self._person_labels[employee.id]

    def apply(self, text: str) -> str:
        if not text:
            return text
        seen: dict[str, str] = {}

        def contact(kind: str):
            def repl(m: re.Match) -> str:
                value = m.group(0)
                if value not in seen:
                    seen[value] = self._new_label(kind, value)
                return seen[value]

            return repl

        text = EMAIL.sub(contact("EMAIL"), text)
        text = PESEL.sub(contact("PESEL"), text)
        text = PHONE.sub(contact("TELEFON"), text)
        for attr in ("full", "last", "first"):  # najpierw pełne brzmienie
            for person in self._pz._people:
                pattern = getattr(person, attr)
                if pattern is not None and pattern.search(text):
                    text = pattern.sub(self.label_for(person.employee), text)
        return text

    def restore(self, text: str) -> str:
        return LABEL.sub(lambda m: self.mapping.get(m.group(0), m.group(0)), text)
