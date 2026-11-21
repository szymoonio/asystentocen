"""Granice odpowiedzialności asystenta HR (§ 7.5) — w kodzie, nie w prompcie.

Każdy tekst od kierownika przechodzi `check()` przed wywołaniem LLM. Trafienie = stały komunikat
z kontaktem do kadr (i innych osób z `hr.yaml`), bez wywołania modelu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.assistant.privacy.sensitive import _COMPILED as SENSITIVE_PATTERNS
from app.contracts.enums import Role
from app.contracts.models import Employee

CONFIG_PATH = Path(__file__).with_name("hr.yaml")


@dataclass(frozen=True)
class Contact:
    label: str
    value: str


@dataclass(frozen=True)
class Topic:
    code: str
    label: str
    pattern: re.Pattern | None
    sensitive: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        if self.pattern is not None and self.pattern.search(text):
            return True
        return any(SENSITIVE_PATTERNS[c].search(text) for c in self.sensitive)


@dataclass(frozen=True)
class BoundaryHit:
    topic: Topic
    contacts: tuple[Contact, ...]

    @property
    def message(self) -> str:
        return (
            f"W tej sprawie ({self.topic.label}) asystent nie doradza — to wymaga rozmowy z ludźmi, "
            "którzy mogą wziąć za nią odpowiedzialność. Skontaktuj się z:"
        )


@dataclass
class HrConfig:
    roleplay_max_turns: int = 12
    topics: list[Topic] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    crisis_contacts: list[Contact] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> HrConfig:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        topics = []
        for code, spec in (data.get("topics") or {}).items():
            patterns = spec.get("patterns") or []
            pattern = re.compile(r"(?<!\w)(?:" + "|".join(patterns) + ")", re.IGNORECASE) if patterns else None
            topics.append(Topic(code, spec["label"], pattern, tuple(spec.get("use_sensitive_categories") or ())))
        return cls(
            roleplay_max_turns=int(data.get("roleplay_max_turns", 12)),
            topics=topics,
            contacts=[Contact(**c) for c in data.get("contacts") or []],
            crisis_contacts=[Contact(**c) for c in data.get("crisis_contacts") or []],
        )


def hr_contacts(people: list[Employee]) -> list[Contact]:
    return [
        Contact(f"Wydział Kadr — {e.full_name}", e.email or e.position.title)
        for e in people
        if Role.KADRY in e.extra_roles and e.active
    ]


def check(text: str, config: HrConfig, people: list[Employee]) -> BoundaryHit | None:
    for topic in config.topics:
        if topic.matches(text):
            contacts = [*(config.crisis_contacts if topic.code == "KRYZYS" else []), *hr_contacts(people), *config.contacts]
            return BoundaryHit(topic, tuple(contacts))
    return None
