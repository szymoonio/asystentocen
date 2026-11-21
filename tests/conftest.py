"""Wspólne fixtury testów. ZAMROŻONE (krok 0)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.container import Container, build_container
from app.contracts.fakes import load_seed
from app.contracts.regulation import YamlCriteriaCatalog
from app.main import create_app
from app.settings import Settings

DEMO_TODAY = date(2026, 11, 21)


@pytest.fixture
def settings(tmp_path) -> Settings:
    base = Settings.from_env()
    return replace(base, database_url=f"sqlite:///{tmp_path / 'test.db'}", demo_today=DEMO_TODAY)


@pytest.fixture
def catalog(settings) -> YamlCriteriaCatalog:
    return YamlCriteriaCatalog(settings.regulation_dir)


@pytest.fixture
def seed(settings):
    return load_seed(settings.seed_path)


@pytest.fixture
def container(settings) -> Container:
    return build_container(settings)


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))
