"""`AssistantDraftProvider` — port `DraftProvider` dla formularza oceny (agent A).

`drafts(evaluation_id, field)` zwraca akapity projektu, każdy z `citations` (ID notatek):
- świeży projekt LLM, jeśli oceniający go przygotował i notatki/oceny się od tego nie zmieniły;
- w przeciwnym razie deterministyczny szkielet (`generator="deterministic:v1"`).
Działa więc także bez LLM. Nigdy nie wywołuje API — generowanie uruchamia człowiek.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.assistant.llm import LLMClient
from app.assistant.privacy import Pseudonymizer
from app.assistant.summarize import skeleton
from app.assistant.summarize.evidence import CycleEvidence, EvidenceBuilder
from app.assistant.summarize.llm_summary import SummaryResult, summarize
from app.assistant.summarize.store import DraftStore, StoredDraft
from app.contracts.enums import DraftField
from app.contracts.models import DraftSuggestion
from app.contracts.ports import CriteriaCatalog
from app.contracts.regulation import Scale

FIELDS = {DraftField.UZASADNIENIE: "justification", DraftField.WNIOSKI_IPRZ: "development"}


class AssistantDraftProvider:
    def __init__(
        self,
        *,
        builder: Callable[[], EvidenceBuilder],
        store: DraftStore,
        actions: dict[str, list[str]],
        now: Callable[[], datetime],
    ) -> None:
        self._builder = builder
        self._store = store
        self._actions = actions
        self._now = now

    def available(self) -> bool:
        return True

    def evidence(self, evaluation_id: str) -> CycleEvidence | None:
        return self._builder().build(evaluation_id)

    def stored(self, evaluation_id: str) -> StoredDraft | None:
        return self._store.latest(evaluation_id)

    def generate(
        self,
        evidence: CycleEvidence,
        *,
        llm: LLMClient,
        catalog: CriteriaCatalog,
        scale: Scale,
        pseudonymizer: Pseudonymizer,
        only: str | None = None,
    ) -> SummaryResult:
        """Projekt z LLM na żądanie oceniającego; zapisany staje się źródłem `drafts()`.
        Przy `only` (jedno pole) drugie pole bierzemy z poprzedniego świeżego projektu, jeśli był."""
        result = summarize(
            evidence, llm=llm, catalog=catalog, scale=scale, actions=self._actions, pseudonymizer=pseudonymizer,
            only=only,
        )
        if only:
            previous = self._store.latest(evidence.evaluation.id)
            if previous and previous.input_key == evidence.input_key:
                other = "development" if only == "justification" else "justification"
                setattr(result, other, getattr(previous.result, other))
        self._store.save(evidence.evaluation.id, evidence.input_key, result, self._now())
        return result

    def paragraphs(self, evidence: CycleEvidence, field: DraftField) -> tuple[list[skeleton.Paragraph], str, datetime]:
        """(akapity, generator, data powstania) — wspólne dla portu i strony podsumowania."""
        name = FIELDS[field]
        stored = self._store.latest(evidence.evaluation.id)
        if stored and stored.input_key == evidence.input_key:
            return getattr(stored.result, name), stored.generator, stored.created_at
        if name == "justification":
            paragraphs = skeleton.justification(evidence)
        else:
            paragraphs = skeleton.development(evidence, self._actions)
        return paragraphs, skeleton.GENERATOR, self._now()

    def drafts(self, evaluation_id: str, field: DraftField) -> list[DraftSuggestion]:
        if field not in FIELDS:
            return []
        evidence = self.evidence(evaluation_id)
        if evidence is None:
            return []
        paragraphs, generator, created_at = self.paragraphs(evidence, field)
        return [
            DraftSuggestion(
                evaluation_id=evaluation_id,
                field=field,
                text=p.text,
                citations=list(p.note_ids),
                generator=generator,
                created_at=created_at,
            )
            for p in paragraphs
        ]
