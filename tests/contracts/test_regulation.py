"""Testy konfiguracji przepisów i katalogu kryteriów — ZAMROŻONE (krok 0)."""

from __future__ import annotations

from fractions import Fraction

from app.contracts.enums import Level, SheetType
from app.contracts.ports import CriteriaCatalog
from app.contracts.regulation import load_scale


def test_catalog_implements_port(catalog):
    assert isinstance(catalog, CriteriaCatalog)


def test_fourteen_criteria(catalog):
    assert len(catalog.all()) == 14
    assert len({c.code for c in catalog.all()}) == 14


def test_mandatory_counts(catalog):
    assert len(catalog.mandatory_for(SheetType.A)) == 6
    assert len(catalog.mandatory_for(SheetType.B)) == 5
    assert len(catalog.mandatory_for(SheetType.C)) == 5


def test_sheet_c_mandatory_differs_from_b(catalog):
    c_codes = {c.code for c in catalog.mandatory_for(SheetType.C)}
    assert {"WYKORZYSTYWANIE_WIEDZY", "RZETELNOSC"} <= c_codes
    assert "ZARZADZANIE_LUDZMI" not in c_codes


def test_additional_excludes_mandatory(catalog):
    for sheet in SheetType:
        mandatory = {c.code for c in catalog.mandatory_for(sheet)}
        additional = {c.code for c in catalog.additional_for(sheet)}
        assert not mandatory & additional
        assert len(mandatory) + len(additional) == 14


def test_by_name_handles_aliases_and_nbsp(catalog):
    assert catalog.by_name("Negocjacje").code == "NEGOCJOWANIE"
    assert catalog.by_name("organizacja pracy i\xa0orientacja na osiąganie celów").code == "ORGANIZACJA_PRACY"
    assert catalog.by_name("nie ma takiego") is None


def test_sheet_differences(catalog):
    sheets = catalog.sheets
    assert sheets[SheetType.A].has_org_unit is False
    assert sheets[SheetType.A].objection_addressee is None
    assert sheets[SheetType.C].objection_addressee == "dyrektora generalnego urzędu"


def test_scale_bands_are_exclusive_at_lower_bound(settings):
    scale = load_scale(settings.regulation_dir)
    by_level = {b.level: b for b in scale.levels}
    assert by_level[Level.PONIZEJ].contains(Fraction(4))
    assert not by_level[Level.NA_POZIOMIE].contains(Fraction(4))
    assert by_level[Level.ZNACZNIE_PONIZEJ].contains(Fraction(1))
    assert by_level[Level.ZNACZNIE_POWYZEJ].contains(Fraction(9))
    # każda możliwa średnia trafia do dokładnie jednego przedziału
    for num in range(7, 64):
        value = Fraction(num, 7)
        assert sum(b.contains(value) for b in scale.levels) == 1
