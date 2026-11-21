"""Router modułu ASSISTANT (agent B), montowany pod /asystent."""

from __future__ import annotations

from fastapi import APIRouter

from app.assistant.hr.views import router as hr_router
from app.assistant.notes.views import router as notes_router
from app.assistant.nudges.views import router as nudges_router
from app.assistant.summarize.views import router as summary_router

router = APIRouter()
router.include_router(notes_router)
router.include_router(nudges_router)
router.include_router(summary_router)
router.include_router(hr_router)
