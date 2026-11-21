"""Router modułu ASSISTANT (agent B), montowany pod /asystent."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.assistant.notes.views import router as notes_router
from app.assistant.nudges.views import router as nudges_router
from app.assistant.summarize.views import router as summary_router
from app.templating import render

router = APIRouter()
router.include_router(notes_router)
router.include_router(nudges_router)
router.include_router(summary_router)


@router.get("/hr")
def hr_partner(request: Request):
    return render(
        request,
        "placeholder.html",
        title="Asystent HR",
        owner="B",
        what="Przygotowanie do trudnej rozmowy, próba rozmowy, notatka → informacja zwrotna, pytania o procedury.",
    )
