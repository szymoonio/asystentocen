"""Baza wiedzy do pytań o procedury: `docs/assistant/wiedza/*.md` (wyciąg z `context/`).

Wyszukiwanie deterministyczne (BM25 na uproszczonych rdzeniach słów), więc działa też bez LLM:
wtedy kierownik dostaje najbardziej pasujące fragmenty przepisów z paragrafem.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.settings import ROOT

KNOWLEDGE_DIR = ROOT / "docs" / "assistant" / "wiedza"
WORD = re.compile(r"[a-ząćęłńóśźż0-9]+", re.IGNORECASE)
STOP = {
    "oraz", "jest", "które", "który", "która", "jeżeli", "albo", "przez", "dnia", "tego", "jego", "tym", "się",
    "nie", "jak", "czy", "ile", "kiedy", "mam", "mogę", "można", "trzeba", "dla", "lub", "ich", "jej", "przy",
}  # fmt: skip
STEM = 6  # polska fleksja: porównujemy początki słów


@dataclass(frozen=True)
class Chunk:
    id: str  # np. K12
    source: str  # tytuł dokumentu
    label: str  # np. „§ 10 rozporządzenia”
    text: str


def _terms(text: str) -> list[str]:
    return [w.lower()[:STEM] for w in WORD.findall(text) if len(w) > 2 and w.lower() not in STOP]


def parse(path: Path) -> list[tuple[str, str, str]]:
    content = path.read_text(encoding="utf-8")
    title = content.splitlines()[0].lstrip("# ").strip() if content else path.stem
    parts = re.split(r"^## (.+)$", content, flags=re.MULTILINE)
    return [(title, parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


class KnowledgeBase:
    def __init__(self, directory: Path = KNOWLEDGE_DIR) -> None:
        self.chunks: list[Chunk] = []
        for path in sorted(directory.glob("*.md")):
            for title, label, text in parse(path):
                self.chunks.append(Chunk(f"K{len(self.chunks) + 1}", title, label, text))
        self._by_id = {c.id: c for c in self.chunks}
        self._tf = [Counter(_terms(f"{c.label} {c.text}")) for c in self.chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 1.0
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def get(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def search(self, query: str, k: int = 6, k1: float = 1.4, b: float = 0.75) -> list[Chunk]:
        terms = _terms(query)
        if not terms:
            return []
        scored = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    score += self._idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * self._len[i] / self._avg))
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [self.chunks[i] for _, i in scored[:k]]


@lru_cache(maxsize=1)
def default_knowledge() -> KnowledgeBase:
    return KnowledgeBase()
