"""„Odłóż o 2 tygodnie” i przywrócenie przypomnień o osobie."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.assistant.pages import PageError, html_errors
from app.assistant.services import services
from app.deps import get_container, get_current_user

router = APIRouter()


def _check_subordinate(request: Request, subject_id: str) -> tuple[str, str]:
    c = get_container(request)
    user = get_current_user(request)
    if not any(e.id == subject_id for e in c.employees.subordinates(user.employee_id)):
        raise PageError(403, "Przypomnienia możesz odkładać tylko dla swoich podwładnych.")
    return user.employee_id, subject_id


@router.post("/teczka/{subject_id}/odloz")
@html_errors
def odloz(subject_id: str, request: Request):
    c = get_container(request)
    supervisor_id, _ = _check_subordinate(request, subject_id)
    svc = services(c)
    svc.snoozes.snooze(supervisor_id, subject_id, c.clock.today() + timedelta(days=svc.nudges.snooze_days))
    return RedirectResponse("/asystent/teczka#przypomnienia", status_code=303)


@router.post("/teczka/{subject_id}/przywroc")
@html_errors
def przywroc(subject_id: str, request: Request):
    c = get_container(request)
    supervisor_id, _ = _check_subordinate(request, subject_id)
    services(c).snoozes.cancel(supervisor_id, subject_id)
    return RedirectResponse("/asystent/teczka#przypomnienia", status_code=303)
