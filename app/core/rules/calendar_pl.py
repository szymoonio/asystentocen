"""Kalendarz polski i liczenie terminów.

Zasady (context/6. Materiały dodatkowe/liczenie terminów.docx, art. 110–115 KC):
- termin w miesiącach kończy się w dniu odpowiadającym dniowi początkowemu, a gdy go brak —
  w ostatnim dniu miesiąca (`add_months`);
- termin w dniach: dnia zdarzenia nie wlicza się (`deadline_in_days`);
- koniec terminu w sobotę lub dzień ustawowo wolny przesuwa się na najbliższy dzień
  roboczy (`shift_to_working_day`).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import lru_cache

# 24 grudnia jest dniem wolnym od pracy od 2025 r. (ustawa z 6.12.2024 zmieniająca
# ustawę o dniach wolnych od pracy).
CHRISTMAS_EVE_FROM_YEAR = 2025


def easter_sunday(year: int) -> date:
    """Wielkanoc wg algorytmu Meeusa/Jonesa/Butchera (kalendarz gregoriański)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    """Dni ustawowo wolne od pracy w Polsce (ustawa z 18.01.1951 o dniach wolnych od pracy)."""
    easter = easter_sunday(year)
    days = {
        date(year, 1, 1),  # Nowy Rok
        date(year, 1, 6),  # Trzech Króli
        easter,
        easter + timedelta(days=1),  # Poniedziałek Wielkanocny
        date(year, 5, 1),
        date(year, 5, 3),
        easter + timedelta(days=49),  # Zielone Świątki
        easter + timedelta(days=60),  # Boże Ciało
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    if year >= CHRISTMAS_EVE_FROM_YEAR:
        days.add(date(year, 12, 24))
    return frozenset(days)


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def add_months(d: date, months: int) -> date:
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def shift_to_working_day(d: date) -> date:
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


def deadline_in_days(event: date, days: int) -> date:
    return shift_to_working_day(event + timedelta(days=days))


def deadline_in_months(start: date, months: int) -> date:
    return shift_to_working_day(add_months(start, months))
