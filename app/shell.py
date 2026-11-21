"""Powłoka aplikacji: strona główna, przełączanie użytkownika demo, health. ZAMROŻONE (krok 0)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.deps import DEMO_COOKIE

router = APIRouter()


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/core/", status_code=303)


@router.get("/login/{employee_id}")
def login_as(employee_id: str, request: Request) -> RedirectResponse:
    response = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    response.set_cookie(DEMO_COOKIE, employee_id, httponly=True, samesite="lax")
    return response


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
