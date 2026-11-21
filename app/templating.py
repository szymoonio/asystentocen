"""Wspólne renderowanie szablonów Jinja. ZAMROŻONE (krok 0).

Szablony modułów leżą w templates/core/ (A) i templates/assistant/ (B) i dziedziczą
po templates/base.html. Użycie w routerze:

    return render(request, "core/oceny.html", title="Oceny", evaluations=...)
"""

from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.contracts.enums import LEVEL_LABELS
from app.deps import get_container, get_current_user
from app.settings import ROOT

templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.globals["LEVEL_LABELS"] = LEVEL_LABELS
templates.env.filters["pl_date"] = lambda d: d.strftime("%d.%m.%Y") if d else "—"


def asset(path: str) -> str:
    """'/static/base.css' → '/static/base.css?v=<czas zmiany pliku>': przeglądarka pobiera plik od nowa po każdej zmianie."""
    try:
        version = int((ROOT / path.lstrip("/")).stat().st_mtime)
    except OSError:
        return path
    return f"{path}?v={version}"


templates.env.globals["asset"] = asset


def render(request: Request, template: str, **context: object):
    c = get_container(request)
    user = get_current_user(request)
    me = c.employees.get(user.employee_id)
    base = {
        "user": user,
        "me": me,
        "demo_users": c.employees.all(),
        "office": c.employees.office(),
        "today": c.clock.today(),
    }
    return templates.TemplateResponse(request, template, {**base, **context})
