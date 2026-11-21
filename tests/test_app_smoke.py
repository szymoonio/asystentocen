"""Smoke test całej aplikacji — ZAMROŻONE (krok 0). Musi przechodzić na każdej gałęzi."""

from __future__ import annotations

from app.container import Container
from app.contracts.ports import (
    CriteriaCatalog,
    DraftProvider,
    EmployeeDirectory,
    EvaluationReader,
    NotesReader,
    ReminderProvider,
    ReminderSink,
)


def test_container_ports(container: Container):
    assert isinstance(container.catalog, CriteriaCatalog)
    assert isinstance(container.employees, EmployeeDirectory)
    assert isinstance(container.evaluations, EvaluationReader)
    assert isinstance(container.reminder_sink, ReminderSink)
    assert isinstance(container.drafts, DraftProvider)
    assert isinstance(container.notes, NotesReader)
    for provider in container.reminder_providers:
        assert isinstance(provider, ReminderProvider)


def test_pages_render(client):
    for url in ["/core/", "/core/oceny", "/core/kadry", "/asystent/teczka", "/asystent/teczka/E06", "/asystent/hr"]:
        response = client.get(url)
        assert response.status_code == 200, url


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303


def test_demo_login_switches_user(client):
    client.get("/login/E11")
    page = client.get("/core/").text
    assert "Magda Kadrowa" in page


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
