"""Dane demo (seed/office.yaml): tylko zespół Henryka + robocze konto administratora, zwyczajne nazwiska.
Testy domyślnie używają pełnego zestawu z tests/fixtures/office_full.yaml — tu sprawdzamy sam seed demo."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.container import build_container
from app.contracts.fakes import load_seed
from app.main import create_app
from app.settings import ROOT, Settings

DEMO = ROOT / "seed" / "office.yaml"


def test_only_henryk_team_and_admin():
    seed = load_seed(DEMO)
    people = {e.id: e for e in seed.employees}
    assert set(people) == {"E05", "E06", "E07", "E09", "E12", "E13", "E14", "E15", "E16"}
    assert all(e.supervisor_id == "E05" for e in seed.employees if e.id not in ("E05", "E16"))
    admin = people["E16"]
    assert admin.position.title == "administrator systemu" and admin.extra_roles == []
    assert {e.full_name for e in seed.employees} >= {"Henryk Kowalczyk", "Grzegorz Wójcik", "Ewa Lewandowska"}
    text = DEMO.read_text(encoding="utf-8")
    for old in ("Pryncypał", "Wzór", "Rzetelna", "Wytrwała", "Rzeczowy", "Bystra", "Młodszy", "Kadrowa", "Naczelny"):
        assert old not in text


def test_seed_references_stay_consistent():
    seed = load_seed(DEMO)
    ids = {e.id for e in seed.employees}
    assert all(r["employee_id"] in ids and r.get("evaluator_id") in ids | {None} for r in seed.evaluations)
    assert all(n.author_id in ids and n.subject_id in ids for n in seed.notes)
    current = next(r for r in seed.evaluations if r["id"] == "EV-E13-2026")
    assert "justification" not in (current.get("form") or {})  # uzasadnienie do napisania od zera


def test_demo_app_starts(tmp_path):
    settings = replace(Settings.from_env(), seed_path=Path(DEMO), database_url=f"sqlite:///{tmp_path / 'demo.db'}")
    client = TestClient(create_app(build_container(settings)))
    page = client.get("/core/").text
    assert "Henryk" in page and 'class="emblem"' in page and 'class="brand-divider"' in page
    client.get("/login/E16")
    assert client.get("/core/").status_code == 200  # administrator może się zalogować, choć nic nie ocenia
