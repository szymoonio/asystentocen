"""Punkt wejścia aplikacji. ZAMROŻONE (krok 0) — przy integracji NIE trzeba go zmieniać.

Uruchomienie:  uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import assistant, core, shell
from app.container import Container, build_container
from app.settings import ROOT


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(title="Cyfrowy Asystent Ocen Okresowych")
    app.state.container = container or build_container()
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    app.include_router(shell.router)
    app.include_router(core.router, prefix="/core")  # agent A
    app.include_router(assistant.router, prefix="/asystent")  # agent B
    return app


app = create_app()
