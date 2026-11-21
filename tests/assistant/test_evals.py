"""Harness evali: wyrocznia daje 100%, pusty baseline przegrywa, oceniacze odrzucają złe odpowiedzi.

Bez sieci — tryb live nie jest tu uruchamiany.
"""

from __future__ import annotations

import json

from evals import run
from evals.suites import ALL, ClassifySuite, QaSuite, SplitSuite, calls_per_rep


def _run(tmp_path, mode, suites="all"):
    out = tmp_path / mode
    assert run.main(["--mode", mode, "--suites", suites, "--out", str(out)]) == 0
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    errors = (out / "errors.jsonl").read_text(encoding="utf-8").splitlines()
    return rows, errors, (out / "summary.md").read_text(encoding="utf-8")


def test_offline_runs_only_free_suites(tmp_path):
    rows, errors, summary = _run(tmp_path, "offline")
    assert {r["suite"] for r in rows} == {"boundaries", "retrieval"}
    assert all(r["grade"]["pass"] for r in rows) and errors == []
    assert "allowed_when_should: 100%" in summary


def test_oracle_scores_everything(tmp_path):
    rows, errors, _ = _run(tmp_path, "oracle")
    assert errors == []
    assert {r["suite"] for r in rows} == set(ALL)
    failed = [(r["suite"], r["case"]) for r in rows if not r["grade"]["pass"]]
    assert failed == []


def test_null_baseline_fails_positive_cases(tmp_path):
    rows, errors, summary = _run(tmp_path, "null", "classify,split,procedure_qa,conversations,summarize")
    assert errors == []
    by_suite = {}
    for r in rows:
        by_suite.setdefault(r["suite"], []).append(r)
    # puste odpowiedzi przechodzą tylko przypadki ujemne („nic nie pasuje” / „poza bazą wiedzy”)
    assert all(r["grade"]["pass"] == r["grade"]["negative"] for r in by_suite["classify"])
    assert all(r["grade"]["pass"] == r["grade"]["negative"] for r in by_suite["procedure_qa"])
    assert not any(r["grade"]["pass"] for r in by_suite["conversations"] + by_suite["summarize"])
    assert "majority_baseline" in summary


def test_graders_reject_plausible_wrong_answers():
    classify = ClassifySuite()
    case = next(c for c in classify.cases() if c["id"] == "c01")
    assert not classify.grade(case, {"predicted": ["WSPOLPRACA"]})["pass"]
    negative = next(c for c in classify.cases() if c["id"] == "n01")
    assert not classify.grade(negative, {"predicted": ["KOMUNIKACJA"]})["pass"]

    qa = QaSuite()
    q01 = next(c for c in qa.cases() if c["id"] == "q01")
    wrong_fact = {"answer": "W terminie 14 dni.", "cited": ["art. 83 ustawy o służbie cywilnej"], "not_found": False}
    wrong_source = {"answer": "W terminie 7 dni.", "cited": ["§ 11 rozporządzenia"], "not_found": False}
    assert not qa.grade(q01, wrong_fact)["pass"] and not qa.grade(q01, wrong_source)["pass"]
    x01 = next(c for c in qa.cases() if c["id"] == "x01")
    assert not qa.grade(x01, {"answer": "26 dni.", "cited": [], "not_found": False})["pass"]

    split = SplitSuite()
    s02 = next(c for c in split.cases() if c["id"] == "s02")
    invented = {"strengths": [], "improvements": ["Brak zaangażowania w projekty unijne"]}
    assert not split.grade(s02, invented)["grounded"]


def test_live_mode_requires_key(tmp_path, capsys):
    assert run.main(["--mode", "live", "--out", str(tmp_path / "live")]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_planned_calls_are_reported():
    assert calls_per_rep(ALL["boundaries"]) == 0
    assert calls_per_rep(ALL["classify"]) == len(ALL["classify"].cases())
    assert calls_per_rep(ALL["conversations"]) == sum(2 + len(c["manager_turns"]) for c in ALL["conversations"].cases())


def test_labelled_cases_record_provenance():
    for name in ("classify", "split"):
        assert all(c.get("source") for c in ALL[name].cases()), name
