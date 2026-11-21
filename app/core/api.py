"""Router modułu CORE (agent A). Stub z kroku 0 — agent A rozwija dowolnie."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import get_container, get_current_user
from app.templating import render

router = APIRouter()


@router.get("/")
def pulpit(request: Request):
    c = get_container(request)
    user = get_current_user(request)
    rows = []
    for employee in c.employees.subordinates(user.employee_id):
        rows.append((employee, c.evaluations.current_for(employee.id)))
    return render(
        request,
        "core/pulpit.html",
        title="Pulpit",
        rows=rows,
        inbox=c.reminder_sink.inbox(user.employee_id),
    )


@router.get("/oceny")
def oceny(request: Request):
    return render(
        request,
        "placeholder.html",
        title="Oceny",
        owner="A",
        what="Lista ocen, formularze A/B/C krok po kroku, wydruk PDF.",
    )


@router.get("/kadry")
def kadry(request: Request):
    return render(
        request,
        "placeholder.html",
        title="Kadry",
        owner="A",
        what="Dane pracowników, podległość, nieobecności, import CSV, terminy całego urzędu, statystyki.",
    )
