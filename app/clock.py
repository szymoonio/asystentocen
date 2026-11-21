"""Zegar aplikacji. ZAMROŻONE (krok 0).

Wszystko, co zależy od „dziś” (terminy, przypomnienia), bierze datę z Clock, a nie z
date.today(). Dzięki temu demo i testy mogą ustawić datę (DEMO_TODAY=2026-11-21).
"""

from __future__ import annotations

from datetime import date, datetime


class Clock:
    def __init__(self, fixed_today: date | None = None) -> None:
        self._fixed = fixed_today

    def today(self) -> date:
        return self._fixed or date.today()

    def now(self) -> datetime:
        if self._fixed:
            return datetime.combine(self._fixed, datetime.now().time())
        return datetime.now()
