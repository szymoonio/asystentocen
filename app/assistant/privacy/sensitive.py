"""Detektor danych wrażliwych w notatkach (RODO art. 9 i 10 oraz życie prywatne) — § 6.3.

Notatka z trafieniem NIE trafia do LLM, a przełożony dostaje ostrzeżenie: takie informacje
nie powinny w ogóle być podstawą oceny okresowej. Detektor jest celowo „nadgorliwy” —
fałszywy alarm kosztuje jedno pominięcie notatki, przeoczenie kosztuje wyciek.

Wzorce to początki słów (polska fleksja), dopasowywane od granicy słowa, bez wielkości liter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ZDROWIE": (
        "zdrowie",
        (
            r"chorob", r"chor(y|a|e|ego|ej|ym|uje|ował|owała|owal)\b", r"zachorow", r"l-?4\b",
            r"zwolnieni\w* lekarsk", r"lekarz", r"lekarsk", r"szpital", r"diagnoz", r"depresj",
            r"nerwic", r"lęk(i|ow|owy|ów)\b", r"terapi", r"terapeut", r"psycholog", r"psychiatr",
            r"leczeni", r"leczy", r"lek(i|ów|ami)\b", r"nowotw", r"onkolog", r"cukrzyc",
            r"niepełnospraw", r"kontuzj", r"rehabilit", r"migren", r"operacj\w* (kolana|serca|biodra|kręgosłupa)",
            r"covid", r"grypa", r"grypy", r"zawał", r"udar",
        ),
    ),
    "CIAZA_RODZICIELSTWO": (
        "ciąża i rodzicielstwo",
        (r"ciąż", r"poród", r"porod", r"poronien", r"macierzyńsk", r"ojcowsk\w* urlop", r"urlop\w* ojcowsk",
         r"rodzicielsk", r"in vitro"),
    ),
    "ZYCIE_PRYWATNE": (
        "życie prywatne i intymne",
        (r"rozwod", r"rozwód", r"rozstani", r"romans", r"seksualn", r"homoseks", r"gej(e|a|em|u)?\b",
         r"lesbij", r"transpł", r"orientacj\w* seksualn", r"mąż\b", r"męż(a|em|owi|u)\b", r"żon(a|y|ie|ę|ą)\b",
         r"partner\w* życiow"),
    ),
    "RELIGIA": (
        "religia i światopogląd",
        (r"religi", r"wyznani", r"kości[oó]ł", r"kościel", r"msz(a|y|ę|e|ach)\b", r"modli", r"katoli",
         r"prawosław", r"protestan", r"muzułma", r"islam", r"żyd(a|ów|em|zi|owsk)?\b", r"judaiz",
         r"ramadan", r"świadk\w* jehow", r"ateist"),
    ),
    "POGLADY_POLITYCZNE": (
        "poglądy polityczne",
        (r"polityczn", r"partyjn", r"lewic", r"prawic", r"głosował", r"manifestacj"),
    ),
    "ZWIAZKI_ZAWODOWE": (
        "przynależność związkowa",
        (r"związ\w* zawodow", r"związkow", r"strajk"),
    ),
    "POCHODZENIE": (
        "pochodzenie etniczne lub rasowe",
        (r"narodowoś", r"etniczn", r"rasow", r"rasizm", r"romsk", r"imigran"),
    ),
    "NALOGI": (
        "nałogi i używki",
        (r"alkohol", r"pijan", r"nietrzeźw", r"uzależni", r"narkot", r"hazard"),
    ),
    "KARALNOSC": (
        "karalność i postępowania",
        (r"karan(y|a|ość)", r"wyrok", r"prokurat", r"policj", r"przestępst"),
    ),
    "FINANSE_PRYWATNE": (
        "prywatne finanse",
        (r"komornik", r"komornicz", r"zadłużeni", r"upadłoś\w* konsumenck", r"zajęci\w* wynagrodzeni"),
    ),
}

_COMPILED = {
    code: re.compile(r"(?<!\w)(?:" + "|".join(patterns) + r")\w*", re.IGNORECASE)
    for code, (_, patterns) in CATEGORIES.items()
}


@dataclass(frozen=True)
class SensitiveHit:
    category: str
    label: str
    match: str


def detect(text: str) -> list[SensitiveHit]:
    hits: list[SensitiveHit] = []
    for code, pattern in _COMPILED.items():
        for m in pattern.finditer(text):
            hits.append(SensitiveHit(category=code, label=CATEGORIES[code][0], match=m.group(0)))
    return hits


def is_sensitive(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED.values())


def warning(hits: list[SensitiveHit]) -> str:
    labels = sorted({h.label for h in hits})
    return (
        f"Notatka może zawierać dane wrażliwe ({', '.join(labels)}), więc asystent jej nie użył. "
        "Takie informacje nie powinny być podstawą oceny — rozważ poprawienie notatki."
    )
