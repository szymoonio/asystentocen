"""Prompty w plikach `prompts/<zadanie>/<wersja>.md` — wersjonowane, logowane z nazwą modelu.

Plik promptu to stały prompt systemowy (bez dat, ID ani danych osobowych — inaczej psuje
prompt caching i prywatność). Zmienne dane idą w wiadomości użytkownika.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.settings import ROOT

PROMPTS_DIR = ROOT / "prompts"


@dataclass(frozen=True)
class Prompt:
    task: str
    version: str
    text: str


@lru_cache(maxsize=64)
def load_prompt(task: str, version: str = "v1", prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    path = prompts_dir / task / f"{version}.md"
    return Prompt(task=task, version=version, text=path.read_text(encoding="utf-8").strip())
