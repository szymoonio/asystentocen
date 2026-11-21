"""`DbNotesReader` — implementacja portu `NotesReader` na tabelach `asst_*`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.assistant.notes.criteria import criteria_for
from app.assistant.notes.repository import NotesRepository
from app.assistant.notes.stats import compute_stats
from app.contracts.models import CriterionStats, Note
from app.contracts.ports import CriteriaCatalog, EvaluationReader


class DbNotesReader:
    """Zawsze w imieniu autora — notatki innych przełożonych są niewidoczne.

    `evaluations` to funkcja, a nie obiekt, bo port ocen może zostać podmieniony
    w kontenerze już po rejestracji modułu.
    """

    def __init__(
        self,
        repo: NotesRepository,
        evaluations: Callable[[], EvaluationReader],
        catalog: CriteriaCatalog,
    ) -> None:
        self._repo = repo
        self._evaluations = evaluations
        self._catalog = catalog

    def notes_for(
        self, author_id: str, subject_id: str, *, since: date | None = None, until: date | None = None
    ) -> list[Note]:
        notes = self._repo.current(author_id, subject_id)
        if since:
            notes = [n for n in notes if n.observed_on >= since]
        if until:
            notes = [n for n in notes if n.observed_on <= until]
        return notes

    def stats_for(self, author_id: str, subject_id: str, evaluation_id: str) -> list[CriterionStats]:
        """Zestawienie suwaków dla cyklu oceny.

        Zawiera każde kryterium oceny (także z `n_ratings == 0` — brak pokrycia), a na końcu
        kryteria ocenione w notatkach, choć nie należą do oceny.
        """
        try:
            evaluation = self._evaluations().get(evaluation_id)
        except KeyError:
            evaluation = None
        notes = [n for n in self._repo.current(author_id, subject_id) if n.evaluation_id == evaluation_id]
        return compute_stats(
            notes,
            criteria_codes=criteria_for(evaluation, self._catalog).current_codes,
            period_from=evaluation.period_from if evaluation else None,
            due_date=evaluation.due_date if evaluation else None,
        )

    def teczka_url(self, subject_id: str) -> str:
        return f"/asystent/teczka/{subject_id}"
