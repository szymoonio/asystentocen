"""Ładowanie konfiguracji przepisów (config/regulation/<wersja>/). ZAMROŻONE (krok 0).

Zawiera implementację portu CriteriaCatalog używaną przez oba moduły.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import yaml

from app.contracts.enums import Level, SheetType
from app.contracts.models import CriterionDef


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().casefold()


@dataclass(frozen=True)
class SheetDef:
    sheet: SheetType
    title: str
    applies_to: str
    mandatory: tuple[str, ...]
    has_org_unit: bool
    objection_addressee: str | None  # None = pole edytowalne


@dataclass(frozen=True)
class LevelBand:
    level: Level
    lower: Fraction
    lower_inclusive: bool
    upper: Fraction  # zawsze włącznie

    def contains(self, value: Fraction) -> bool:
        above = value >= self.lower if self.lower_inclusive else value > self.lower
        return above and value <= self.upper


@dataclass(frozen=True)
class Scale:
    partial_points: dict[int, Level]
    levels: tuple[LevelBand, ...]
    positive_levels: frozenset[Level]
    negative_if_any_partial_equals: int
    promotion_levels: frozenset[Level]
    max_grade: int


class YamlCriteriaCatalog:
    """Implementacja CriteriaCatalog na plikach YAML."""

    def __init__(self, regulation_dir: Path) -> None:
        data = yaml.safe_load((regulation_dir / "criteria.yaml").read_text(encoding="utf-8"))
        self._criteria = [CriterionDef(**c) for c in data["criteria"]]
        self._by_code = {c.code: c for c in self._criteria}
        self._by_name: dict[str, CriterionDef] = {}
        for c in self._criteria:
            for name in (c.name, *c.aliases):
                self._by_name[_norm(name)] = c
        self.sheets = load_sheets(regulation_dir)

    def all(self) -> list[CriterionDef]:
        return list(self._criteria)

    def get(self, code: str) -> CriterionDef:
        return self._by_code[code]

    def by_name(self, name: str) -> CriterionDef | None:
        return self._by_name.get(_norm(name))

    def mandatory_for(self, sheet: SheetType) -> list[CriterionDef]:
        return [self._by_code[code] for code in self.sheets[sheet].mandatory]

    def additional_for(self, sheet: SheetType) -> list[CriterionDef]:
        mandatory = set(self.sheets[sheet].mandatory)
        return [c for c in self._criteria if c.code not in mandatory]


def load_sheets(regulation_dir: Path) -> dict[SheetType, SheetDef]:
    data = yaml.safe_load((regulation_dir / "sheets.yaml").read_text(encoding="utf-8"))
    return {
        SheetType(key): SheetDef(
            sheet=SheetType(key),
            title=value["title"],
            applies_to=value["applies_to"],
            mandatory=tuple(value["mandatory"]),
            has_org_unit=value["has_org_unit"],
            objection_addressee=value.get("objection_addressee"),
        )
        for key, value in data["sheets"].items()
    }


def load_scale(regulation_dir: Path) -> Scale:
    data = yaml.safe_load((regulation_dir / "scale.yaml").read_text(encoding="utf-8"))
    return Scale(
        partial_points={int(k): Level(v) for k, v in data["partial_points"].items()},
        levels=tuple(
            LevelBand(
                level=Level(b["level"]),
                lower=Fraction(b["lower"]),
                lower_inclusive=b["lower_inclusive"],
                upper=Fraction(b["upper"]),
            )
            for b in data["levels"]
        ),
        positive_levels=frozenset(Level(x) for x in data["positive_levels"]),
        negative_if_any_partial_equals=data["negative_if_any_partial_equals"],
        promotion_levels=frozenset(Level(x) for x in data["promotion_levels"]),
        max_grade=data["max_grade"],
    )
