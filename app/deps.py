"""Zależności FastAPI wspólne dla modułów. ZAMROŻONE (krok 0).

Logowanie jest demonstracyjne: użytkownika wybiera się z listy (cookie `demo_user`).
Prawdziwe uwierzytelnianie (np. SSO urzędu) — po hackathonie, w tym samym miejscu.
"""

from __future__ import annotations

from fastapi import Request

from app.container import Container
from app.contracts.fakes import roles_for
from app.contracts.models import UserContext

DEMO_COOKIE = "demo_user"
DEFAULT_DEMO_USER = "E05"  # Henryk Kowalczyk — kierownik referatu z podwładnymi do oceny


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_current_user(request: Request) -> UserContext:
    c = get_container(request)
    employee_id = request.cookies.get(DEMO_COOKIE, DEFAULT_DEMO_USER)
    try:
        employee = c.employees.get(employee_id)
    except KeyError:
        employee = c.employees.get(DEFAULT_DEMO_USER)
    return UserContext(employee_id=employee.id, roles=roles_for(employee, c.employees))
