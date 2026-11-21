"""Zapis analiz LLM (`asst_analyses`). Analizę uruchamia człowiek przyciskiem — wyświetlenie strony
nie kosztuje wywołania API. Wynik jest „aktualny”, dopóki nie zmienią się notatki w zakresie.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.assistant.analysis.llm import AnalysisPoint, AnalysisResult, Ref
from app.db import Base


class AnalysisRow(Base):
    __tablename__ = "asst_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[str] = mapped_column(String(20), index=True)
    scope: Mapped[str] = mapped_column(String(40))  # "zespol" | "osoba:E07"
    input_key: Mapped[str] = mapped_column(String(40))
    generator: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


@dataclass(frozen=True)
class StoredAnalysis:
    input_key: str
    created_at: datetime
    result: AnalysisResult


def _points(items: list[dict]) -> list[AnalysisPoint]:
    return [AnalysisPoint(p["text"], [Ref(**r) for r in p.get("refs", [])]) for p in items]


class AnalysisStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def save(self, author_id: str, scope: str, key: str, result: AnalysisResult, now: datetime) -> None:
        payload = asdict(result)
        payload.pop("generator")
        with self._sf.begin() as s:
            s.add(AnalysisRow(author_id=author_id, scope=scope, input_key=key, generator=result.generator,
                              payload=payload, created_at=now))

    def latest(self, author_id: str, scope: str) -> StoredAnalysis | None:
        stmt = (select(AnalysisRow).where(AnalysisRow.author_id == author_id, AnalysisRow.scope == scope)
                .order_by(AnalysisRow.id.desc()).limit(1))  # fmt: skip
        with self._sf() as s:
            row = s.scalars(stmt).first()
        if row is None:
            return None
        p = row.payload or {}
        result = AnalysisResult(
            generator=row.generator, summary=p.get("summary", ""),
            strengths=_points(p.get("strengths", [])), weaknesses=_points(p.get("weaknesses", [])),
            recommendations=_points(p.get("recommendations", [])),
            used_notes=p.get("used_notes", 0), excluded_notes=p.get("excluded_notes", 0), dropped=p.get("dropped", 0),
        )  # fmt: skip
        return StoredAnalysis(row.input_key, row.created_at, result)
