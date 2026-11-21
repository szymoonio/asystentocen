"""Zestawy evali. Każdy woła PRAWDZIWE wejścia aplikacji (te same funkcje co UI), a ocenia regułami.

Zestaw definiuje: przypadki, uruchomienie, ocenę, odpowiedzi wzorcowe (oracle) i puste (null).
Wyjątek `LLMError` w `run` to błąd wywołania (trafia do errors.jsonl), a nie zła odpowiedź.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.assistant.hr import prep as prep_mod
from app.assistant.hr import qa as qa_mod
from app.assistant.hr import roleplay as rp
from app.assistant.hr.boundaries import check
from app.assistant.llm import LLMError
from app.assistant.notes.assist import classify_items, split_note
from app.assistant.privacy import detect
from app.assistant.services import AssistantServices
from app.container import Container
from app.contracts.models import Note
from app.contracts.regulation import load_scale

CASES = Path(__file__).parent / "cases"
NOW = datetime(2026, 11, 21, 12, 0)
WORD = re.compile(r"[a-ząćęłńóśźż]{4,}", re.IGNORECASE)


def load(name: str) -> list[dict]:
    return yaml.safe_load((CASES / f"{name}.yaml").read_text(encoding="utf-8"))["cases"]


def stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in WORD.findall(text)}


@dataclass
class Env:
    c: Container
    svc: AssistantServices

    @property
    def people(self):
        return self.c.employees.all()


class Suite:
    name = ""
    tasks: tuple[str, ...] = ()  # zadania LLM (puste = zestaw deterministyczny, darmowy)

    def cases(self) -> list[dict]:
        raise NotImplementedError

    def run(self, case: dict, env: Env) -> dict:
        raise NotImplementedError

    def grade(self, case: dict, out: dict) -> dict:
        raise NotImplementedError

    def oracle(self, case: dict) -> dict:
        return {}

    def null(self, case: dict) -> dict:
        return {}

    def metrics(self, rows: list[dict]) -> dict:
        passed = [r["grade"]["pass"] for r in rows]
        return {"n": len(rows), "pass_rate": sum(passed) / len(passed) if passed else None}


# --- classify_note ---------------------------------------------------------------------------


class ClassifySuite(Suite):
    name = "classify"
    tasks = ("classify_note",)

    def cases(self):
        return load("classify")

    def run(self, case, env):
        subject = env.c.employees.get("E06")
        note = Note(id=f"EVAL-{case['id']}", author_id="E05", subject_id="E06", observed_on=date(2026, 11, 20), created_at=NOW, body=case["text"])
        result = classify_items(env.svc, env.c.catalog, note, subject)
        if result is None:
            raise LLMError("klasyfikacja pominięta (dane wrażliwe albo zadanie wyłączone)")
        hints, generator = result
        return {"predicted": sorted({h["criterion_code"] for h in hints}), "generator": generator}

    def grade(self, case, out):
        expected, predicted = set(case["expected"]), set(out["predicted"])
        if not expected:
            return {"pass": not predicted, "negative": True}
        return {
            "pass": bool(expected & predicted),
            "negative": False,
            "precision": len(expected & predicted) / len(predicted) if predicted else 0.0,
        }

    def oracle(self, case):
        return {"classify_note": {"items": [{"id": "B", "criteria": case["expected"][:1]}]}}

    def null(self, case):
        return {"classify_note": {"items": []}}

    def metrics(self, rows):
        pos = [r for r in rows if not r["grade"]["negative"]]
        neg = [r for r in rows if r["grade"]["negative"]]
        cases = self.cases()
        majority = Counter(code for c in cases for code in c["expected"]).most_common(1)[0][0]
        baseline = sum(1 for c in cases if majority in c["expected"]) / len(cases)
        return {
            **super().metrics(rows),
            "recall_positive": sum(r["grade"]["pass"] for r in pos) / len(pos) if pos else None,
            "specificity_negative": sum(r["grade"]["pass"] for r in neg) / len(neg) if neg else None,
            "precision": sum(r["grade"]["precision"] for r in pos) / len(pos) if pos else None,
            "majority_baseline": f"zawsze {majority}: {baseline:.0%}",
        }


# --- split_note ------------------------------------------------------------------------------


class SplitSuite(Suite):
    name = "split"
    tasks = ("split_note",)

    def cases(self):
        return load("split")

    def run(self, case, env):
        outcome = split_note(env.svc, env.c.employees.get("E06"), case["text"])
        if outcome.error:
            raise LLMError(outcome.error)
        return {"strengths": outcome.strengths, "improvements": outcome.improvements}

    def grade(self, case, out):
        items = out["strengths"] + out["improvements"]
        source = stems(case["text"])
        grounded = [bool(stems(i) & source) for i in items]
        short = [len(i.split()) <= 25 for i in items]
        sides = bool(out["strengths"]) == case["strengths"] and bool(out["improvements"]) == case["improvements"]
        return {"pass": sides and all(grounded) and all(short), "sides_ok": sides, "grounded": all(grounded), "short": all(short)}

    def oracle(self, case):
        words = case["text"].split()
        return {"split_note": {
            "strengths": [" ".join(words[:8])] if case["strengths"] else [],
            "improvements": [" ".join(words[-8:])] if case["improvements"] else [],
        }}  # fmt: skip

    def null(self, case):
        return {"split_note": {"strengths": [], "improvements": []}}


# --- procedure_qa ----------------------------------------------------------------------------

FRAGMENT = re.compile(r'<fragment id="(K\d+)" zrodlo="([^"]+)">')


class QaSuite(Suite):
    name = "procedure_qa"
    tasks = ("procedure_qa",)

    def cases(self):
        return load("procedure_qa")

    def run(self, case, env):
        out = qa_mod.answer(case["question"], kb=env.svc.knowledge(), llm=env.svc.llm, hr=env.svc.hr, people=env.people, pseudonymizer=env.svc.pseudonymizer())
        if out.error:
            raise LLMError(out.error)
        return {"answer": out.answer, "cited": [c.label for c in out.sources], "not_found": bool(out.not_found), "boundary": bool(out.boundary)}

    def grade(self, case, out):
        if case.get("expect") == "not_found":
            return {"pass": out["not_found"] and not out["answer"], "negative": True}
        answer = (out["answer"] or "").lower()
        cited_ok = any(label.startswith(p) for label in out["cited"] for p in case["sources"])
        fact_ok = any(m.lower() in answer for m in case["must"])
        return {"pass": bool(out["answer"]) and cited_ok and fact_ok, "negative": False, "cited_ok": cited_ok, "fact_ok": fact_ok}

    def oracle(self, case):
        def answer(system, user):
            if case.get("expect") == "not_found":
                return {"answer": "Brak podstawy w podanych fragmentach.", "sources": [], "found": False}
            ids = [cid for cid, label in FRAGMENT.findall(user) if any(label.startswith(p) for p in case["sources"])]
            return {"answer": f"{case['must'][0]} ({case['sources'][0]}).", "sources": ids[:1], "found": True}

        return {"procedure_qa": answer}

    def null(self, case):
        return {"procedure_qa": {"answer": "", "sources": [], "found": True}}

    def metrics(self, rows):
        pos = [r for r in rows if not r["grade"]["negative"]]
        neg = [r for r in rows if r["grade"]["negative"]]
        return {
            **super().metrics(rows),
            "answered_correctly": sum(r["grade"]["pass"] for r in pos) / len(pos) if pos else None,
            "declined_out_of_scope": sum(r["grade"]["pass"] for r in neg) / len(neg) if neg else None,
        }


class RetrievalSuite(Suite):
    """Deterministyczne: czy wyszukiwarka podaje modelowi właściwy przepis (recall@8)."""

    name = "retrieval"

    def cases(self):
        return [c for c in load("procedure_qa") if c.get("expect") != "not_found"]

    def run(self, case, env):
        return {"top": [c.label for c in env.svc.knowledge().search(case["question"], qa_mod.TOP_K)]}

    def grade(self, case, out):
        ranks = [i for i, label in enumerate(out["top"]) if any(label.startswith(p) for p in case["sources"])]
        return {"pass": bool(ranks), "rank": ranks[0] + 1 if ranks else None}


# --- granice ---------------------------------------------------------------------------------


class BoundarySuite(Suite):
    name = "boundaries"

    def cases(self):
        return load("boundaries")

    def run(self, case, env):
        hit = check(case["text"], env.svc.hr, env.people)
        return {"topic": hit.topic.code if hit else None}

    def grade(self, case, out):
        return {"pass": out["topic"] == case["expect"], "negative": case["expect"] is None}

    def metrics(self, rows):
        pos = [r for r in rows if not r["grade"]["negative"]]
        neg = [r for r in rows if r["grade"]["negative"]]
        return {
            **super().metrics(rows),
            "blocked_when_should": sum(r["grade"]["pass"] for r in pos) / len(pos),
            "allowed_when_should": sum(r["grade"]["pass"] for r in neg) / len(neg),
        }


# --- rozmowy ---------------------------------------------------------------------------------

OUT_OF_ROLE = re.compile(r"jako (model|asystent|ai\b)|model językow|\bAI\b|^\s*[(*]|\*\*", re.IGNORECASE)
GENERALIZATION = re.compile(r"\b(zawsze|nigdy)\b", re.IGNORECASE)


class ConversationSuite(Suite):
    name = "conversations"
    tasks = ("conversation_prep", "roleplay", "roleplay_feedback")

    def cases(self):
        return load("conversations")

    def run(self, case, env):
        svc = env.svc
        prep = prep_mod.prepare(kind=case["kind"], situation=case["situation"], llm=svc.llm, hr=svc.hr, people=env.people, pseudonymizer=svc.pseudonymizer())
        if prep.error or prep.boundary or prep.plan is None:
            raise LLMError(prep.error or "przygotowanie zablokowane przez granice")
        card = {**prep.plan.roleplay.model_dump(), "difficulty": "srednia"}
        session = svc.roleplays.create("E05", card, NOW)
        replies = []
        for turn in case["manager_turns"]:
            replies.append("".join(rp.reply(svc.roleplays, svc.roleplays.get("E05", session.id), turn, llm=svc.llm, hr=svc.hr, people=env.people, pseudonymizer=svc.pseudonymizer())))
        # bez żadnej zapisanej wymiany nie ma czego oceniać — to zła odpowiedź modelu, nie błąd wywołania
        saved = svc.roleplays.get("E05", session.id)
        feedback = rp.finish(svc.roleplays, saved, llm=svc.llm) if saved.messages else ""
        return {"plan": prep.plan.model_dump(), "replies": replies, "feedback": feedback}

    def grade(self, case, out):
        plan = out["plan"]
        names = {p for p in ("Grzegorz", "Ewa", "Wzór", "Rzetelna", "[OSOBA")}
        card_text = " ".join([plan["roleplay"]["persona"], plan["roleplay"]["goal"], plan["roleplay"]["resistance"], *plan["roleplay"]["phrases"]])
        plan_text = " ".join([plan["goal"], plan["opening"], *plan["questions"], *plan["avoid"]])
        checks = {
            "plan_complete": bool(plan["goal"] and plan["opening"] and plan["avoid"]) and len(plan["questions"]) >= 3,
            "opening_no_generalization": not GENERALIZATION.search(plan["opening"]),
            "card_without_names": not any(n in card_text for n in names),
            "plan_no_sensitive": not detect(plan_text),
            "replies_present": all(r.strip() and not r.strip().startswith("[") for r in out["replies"]),
            "replies_short": all(len(r) <= 450 and len(re.findall(r"[.!?]+", r)) <= 4 for r in out["replies"]),
            "stays_in_role": not any(OUT_OF_ROLE.search(r) for r in out["replies"]),
            "replies_no_sensitive": not any(detect(r) for r in out["replies"]),
            "feedback_present": 0 < len(out["feedback"]) <= 2000,
        }
        return {"pass": all(checks.values()), **checks}

    def oracle(self, case):
        n = len(case["manager_turns"])
        return {
            "conversation_prep": {
                "goal": "Ustalić konkretne kolejne kroki.", "opening": "Chcę porozmawiać o sytuacji z ostatniego tygodnia.",
                "questions": ["Jak to wyglądało z Twojej strony?", "Co utrudniało?", "Czego potrzebujesz?"],
                "reactions": [{"reaction": "Zaprzeczenie", "response": "Spójrzmy na fakty."}],
                "avoid": ["Uogólnień."],
                "roleplay": {"persona": "Specjalista w referacie", "goal": "Obronić się", "resistance": "Bagatelizuje", "phrases": ["To nie moja wina."]},
            },
            "roleplay": [["Rozumiem. ", "Nikt mi wcześniej nie mówił, że to problem."]] * n,
            "roleplay_feedback": "Co zadziałało: konkretne fakty. Co poprawić: częściej pytaj o perspektywę.",
        }  # fmt: skip

    def null(self, case):
        return {
            "conversation_prep": {"goal": "", "opening": "", "questions": [], "reactions": [], "avoid": [],
                                  "roleplay": {"persona": "", "goal": "", "resistance": "", "phrases": []}},
            "roleplay": [[""]], "roleplay_feedback": "",
        }  # fmt: skip


# --- podsumowanie cyklu ------------------------------------------------------------------------


class SummarySuite(Suite):
    name = "summarize"
    tasks = ("summarize_cycle",)

    def cases(self):
        return [{"id": "g01", "evaluation_id": "EV-E06-2026R", "source": "seed (Grzegorz, 5 notatek)"}]

    def run(self, case, env):
        evidence = env.svc.drafts.evidence(case["evaluation_id"])
        result = env.svc.drafts.generate(evidence, llm=env.svc.llm, catalog=env.c.catalog, scale=load_scale(env.c.settings.regulation_dir), pseudonymizer=env.svc.pseudonymizer())
        return {
            "justification": [{"text": p.text, "note_ids": list(p.note_ids)} for p in result.justification],
            "development": [{"text": p.text, "note_ids": list(p.note_ids)} for p in result.development],
            "rejected": [{"text": r.text, "reasons": list(r.reasons)} for r in result.rejected],
            "cycle_notes": [n.id for n in evidence.notes],
        }

    def grade(self, case, out):
        accepted = out["justification"] + out["development"]
        total = len(accepted) + len(out["rejected"])
        cited_in_cycle = all(set(p["note_ids"]) <= set(out["cycle_notes"]) and p["note_ids"] for p in accepted)
        rejected_share = len(out["rejected"]) / total if total else 1.0
        return {
            "pass": bool(out["justification"]) and bool(out["development"]) and cited_in_cycle and rejected_share <= 0.5,
            "rejected_share": rejected_share,
            "cited_in_cycle": cited_in_cycle,
        }

    def oracle(self, case):
        return {"summarize_cycle": {
            "justification": [{"text": "Osoba oceniana samodzielnie uzupełniła dokument, kontaktując się z innym wydziałem.", "note_refs": ["N1"]}],
            "development": [{"text": "Proponuję rozwój w kierunku informowania przełożonego o ryzyku opóźnień.", "note_refs": ["N2"]}],
        }}  # fmt: skip

    def null(self, case):
        return {"summarize_cycle": {"justification": [], "development": []}}


ALL: dict[str, Suite] = {
    s.name: s
    for s in (BoundarySuite(), RetrievalSuite(), ClassifySuite(), SplitSuite(), QaSuite(), ConversationSuite(), SummarySuite())
}


def calls_per_rep(suite: Suite) -> int:
    """Szacunek liczby wywołań API (do potwierdzenia przed płatnym przebiegiem)."""
    if not suite.tasks:
        return 0
    cases = suite.cases()
    if isinstance(suite, ConversationSuite):
        return sum(2 + len(c["manager_turns"]) for c in cases)
    return len(cases)


def as_jsonable(value: Any) -> Any:
    return yaml.safe_load(yaml.safe_dump(value, allow_unicode=True)) if value is not None else None
