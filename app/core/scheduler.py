"""Scheduler: raz dziennie domyka cykle i zbiera przypomnienia ze wszystkich modułów.

Uruchamianie:
- automatycznie przy pierwszym wejściu na pulpit danego dnia (`run_if_needed`),
- ręcznie: przycisk na pulpicie (POST /core/scheduler/run),
- z crona: `python -m app.core.scheduler`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from app.core.models import MetaRow

if TYPE_CHECKING:
    from app.container import Container

log = logging.getLogger(__name__)
LAST_RUN_KEY = "scheduler.last_run"


@dataclass
class RunReport:
    day: date
    finalized: list[str] = field(default_factory=list)
    emitted: dict[str, int] = field(default_factory=dict)


def run(c: Container, today: date | None = None) -> RunReport:
    from app.core import workflow

    today = today or c.clock.today()
    report = RunReport(day=today)
    report.finalized = workflow.tick_all(c, today)
    for provider in c.reminder_providers:
        try:
            reminders = provider.due(today)
        except Exception:  # jeden zepsuty moduł nie może zatrzymać przypomnień o terminach
            log.exception("ReminderProvider %s failed", getattr(provider, "name", provider))
            continue
        report.emitted[getattr(provider, "name", type(provider).__name__)] = c.reminder_sink.emit(reminders)
    with c.session_factory() as s:
        row = s.get(MetaRow, LAST_RUN_KEY) or MetaRow(key=LAST_RUN_KEY, value="")
        row.value = today.isoformat()
        s.merge(row)
        s.commit()
    return report


def run_if_needed(c: Container) -> RunReport | None:
    today = c.clock.today()
    with c.session_factory() as s:
        row = s.get(MetaRow, LAST_RUN_KEY)
        if row and row.value >= today.isoformat():
            return None
    return run(c, today)


if __name__ == "__main__":
    from app.container import build_container

    logging.basicConfig(level=logging.INFO)
    r = run(build_container())
    print(f"{r.day}: domknięte {r.finalized}, przypomnienia {r.emitted}")
