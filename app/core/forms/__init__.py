"""Silnik formularza: jeden dla arkuszy A/B/C.

Wspólne pola i reguły edytowalności: definitions/common.v<wersja>.yaml.
Różnice A/B/C (kryteria obowiązkowe, pole „Komórka organizacyjna”, adresat sprzeciwu) pochodzą
z config/regulation/<wersja>/sheets.yaml, więc zmiana przepisów to nowy plik, nie nowy kod.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.contracts.enums import EvaluationState, SheetType

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


@dataclass(frozen=True)
class FieldDef:
    id: str
    part: str
    label: str
    editable: frozenset[EvaluationState]
    by: str  # EVALUATOR | EMPLOYEE
    required_when: str | None = None
    visible_when: str | None = None
    sheets: frozenset[SheetType] | None = None
    note: str | None = None


@dataclass(frozen=True)
class FormDefinition:
    version: str
    fields: dict[str, FieldDef]

    def can_edit(self, field_id: str, state: EvaluationState, actor: str | None) -> bool:
        f = self.fields[field_id]
        return actor == f.by and state in f.editable

    def applies_to(self, field_id: str, sheet: SheetType) -> bool:
        f = self.fields[field_id]
        return f.sheets is None or sheet in f.sheets


@lru_cache(maxsize=4)
def load_definition(version: str = "2016") -> FormDefinition:
    data = yaml.safe_load((DEFINITIONS_DIR / f"common.v{version}.yaml").read_text(encoding="utf-8"))
    fields = {
        fid: FieldDef(
            id=fid,
            part=f["part"],
            label=f["label"],
            editable=frozenset(EvaluationState(s) for s in f["editable"]),
            by=f["by"],
            required_when=f.get("required_when"),
            visible_when=f.get("visible_when"),
            sheets=frozenset(SheetType(s) for s in f["sheets"]) if f.get("sheets") else None,
            note=f.get("note"),
        )
        for fid, f in data["fields"].items()
    }
    return FormDefinition(version=data["version"], fields=fields)
