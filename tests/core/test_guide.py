"""Pulpit „Do zrobienia”, porady asystenta przy ocenie i przygotowanie do rozmowy — bez LLM."""

from __future__ import annotations

from datetime import date

import pytest

from app.contracts.enums import EvaluationState
from app.core import guide


@pytest.mark.parametrize(
    ("day", "text"),
    [(None, "brak notatek"), (date(2026, 11, 21), "dziś"), (date(2026, 11, 20), "wczoraj"),
     (date(2026, 11, 14), "7 dni temu"), (date(2026, 11, 7), "2 tygodnie temu"),
     (date(2026, 10, 10), "6 tygodni temu"), (date(2026, 9, 1), "2 miesiące temu"),
     (date(2026, 3, 1), "8 miesięcy temu"), (date(2025, 1, 1), "ponad rok temu")],
)
def test_ago(day, text):
    assert guide.ago(day, date(2026, 11, 21)) == text


def test_until():
    today = date(2026, 11, 21)
    assert guide.until(date(2026, 12, 10), today) == "za 19 dni"
    assert guide.until(date(2026, 11, 22), today) == "jutro"
    assert guide.until(date(2026, 11, 20), today) == "1 dzień po terminie"


def test_plural():
    assert [guide.plural(n, "ocena", "oceny", "ocen") for n in (1, 2, 5, 12, 22, 25)] == [
        "ocena", "oceny", "ocen", "ocen", "oceny", "ocen"]


def login(client, employee_id):
    client.get(f"/login/{employee_id}")


def test_dashboard_todo_for_evaluator(client, container):
    login(client, "E05")
    todo = guide.todo_evaluations(container, container_user(container, "E05"), date(2026, 11, 21))
    assert todo == sorted(todo, key=lambda t: t.due)
    assert any(t.who == "Ewa Nowak" or "Ewa" in t.who for t in todo)
    page = client.get("/core/").text
    assert "Do zrobienia" in page and "Dodaj notatkę" in page and "Oceny okresowe" in page
    assert "/asystent/teczka/" in page and "/nowa" in page


def test_dashboard_notes_oldest_first(container):
    rows = guide.todo_notes(container, container_user(container, "E05"), date(2026, 11, 21))
    dates = [r.last for r in rows]
    missing = [d for d in dates if d is None]
    assert dates[: len(missing)] == missing  # bez notatek najpierw
    known = [d for d in dates if d is not None]
    assert known == sorted(known)
    assert all(r.url.endswith("/nowa") for r in rows)


def test_employee_sees_only_own_step(client):
    login(client, "E07")
    page = client.get("/core/").text
    assert "Dodaj notatkę" not in page  # nie jest oceniającym


def test_coach_card_and_print_button(client):
    login(client, "E05")
    page = client.get("/core/oceny/EV-E07-2024").text
    assert "Asystent HR" in page and "Pomóż mi przygotować się do rozmowy" in page
    assert "Drukuj arkusz" in page and 'id="czesc-2"' in page


def test_prep_page(client):
    login(client, "E05")
    page = client.get("/core/oceny/EV-E07-2024/przygotowanie")
    assert page.status_code == 200
    text = page.text
    assert "Tematy do poruszenia" in text and "Schemat rozmowy" in text and "IPRZ" in text
    assert "/asystent/hr/przygotowanie?rodzaj=oceniajaca&amp;osoba=E07" in text


def test_prep_page_only_for_evaluator(client):
    login(client, "E07")  # oceniana nie widzi prywatnych notatek przełożonego
    page = client.get("/core/oceny/EV-E07-2024/przygotowanie").text
    assert "Tematy do poruszenia" not in page


def test_tips_after_interview_mentions_warnings(container):
    ev = container.evaluations.get("EV-E07-2024").model_copy(update={"state": EvaluationState.INTERVIEW_HELD})
    tips = guide.tips_for(ev=ev, role="EVALUATOR", today=date(2026, 11, 21), notes=[], warnings=2)
    assert "2 kryteriach" in tips.tips[0]
    assert guide.tips_for(ev=ev, role=None, today=date(2026, 11, 21), notes=[]) is None


def container_user(container, employee_id):
    from app.contracts.models import UserContext

    emp = container.employees.get(employee_id)
    roles = set(emp.extra_roles)
    if container.employees.subordinates(employee_id):
        from app.contracts.enums import Role

        roles.add(Role.OCENIAJACY)
    return UserContext(employee_id=employee_id, roles=frozenset(roles))


def test_dashboard_has_no_other_notifications_section(client):
    login(client, "E05")
    assert "Inne powiadomienia" not in client.get("/core/").text


def test_stylesheets_are_versioned_against_stale_cache(client):
    login(client, "E05")
    page = client.get("/core/").text
    assert '/static/base.css?v=' in page and '/static/core/core.css?v=' in page


def test_dashboard_own_evaluation_box(client):
    login(client, "E05")
    page = client.get("/core/").text
    assert "Twoja ocena okresowa" in page and "03.03.2027" in page and "Szczegóły" in page
    assert '<p class="small"><a href="/asystent/teczka">Teczka</a></p>' not in page
