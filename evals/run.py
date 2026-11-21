"""Uruchamianie evali asystenta.

    python -m evals.run                              # offline: tylko zestawy deterministyczne (darmowe)
    python -m evals.run --mode oracle                # odpowiedzi wzorcowe — harness musi dać ~100%
    python -m evals.run --mode null                  # puste odpowiedzi — oceniacze muszą odrzucić
    python -m evals.run --mode live --suites classify,procedure_qa --reps 3   # Claude API (płatne!)

Tryb `live` woła prawdziwy `ClaudeClient` z `config/llm.yaml` (wymaga ANTHROPIC_API_KEY), pokazuje
liczbę wywołań i czeka na potwierdzenie (albo `--yes`). Wyniki: evals/results/<czas>-<tryb>/
    results.jsonl  — wiersz na (przypadek, powtórzenie): wyjście, ocena, tokeny z API
    errors.jsonl   — wywołania, które nie dały odpowiedzi (błąd API, odmowa, ucięcie) — NIE są liczone jako złe
    summary.md     — metryki per zestaw
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from app.assistant.llm import LLMConfig, LLMError, LLMRefusal, build_client
from app.assistant.llm.claude import ClaudeClient
from app.assistant.services import services
from app.container import build_container
from app.settings import ROOT, Settings
from evals.clients import RecordingClient, ScriptedClient
from evals.suites import ALL, Env, Suite, as_jsonable, calls_per_rep

DEMO_TODAY = date(2026, 11, 21)  # seed jest przygotowany pod tę datę
MODES = ("offline", "oracle", "null", "live")


def fresh_env(client, workdir: Path, n: int) -> Env:
    """Czysty stan na każdy przypadek: nowa baza SQLite z seedu."""
    settings = replace(Settings.from_env(), database_url=f"sqlite:///{workdir / f'case-{n}.db'}", demo_today=DEMO_TODAY)
    c = build_container(settings)
    svc = services(c)
    if client is not None:
        svc.llm = client
    return Env(c=c, svc=svc)


def run_suite(suite: Suite, mode: str, reps: int, client, workdir: Path, results, errors) -> list[dict]:
    rows: list[dict] = []
    counter = 0
    for rep in range(1 if not suite.tasks else reps):
        for case in suite.cases():
            counter += 1
            if isinstance(client, ScriptedClient):
                client.script(**(suite.oracle(case) if mode == "oracle" else suite.null(case)))
            env = fresh_env(client, workdir, counter)
            started = time.monotonic()
            try:
                out = suite.run(case, env)
            except LLMError as err:
                calls = client.take_calls() if isinstance(client, RecordingClient) else []
                kind = "refusal" if isinstance(err, LLMRefusal) else type(err).__name__
                errors.write(json.dumps({"suite": suite.name, "case": case["id"], "rep": rep, "error": kind,
                                         "detail": str(err), "calls": calls}, ensure_ascii=False) + "\n")  # fmt: skip
                continue
            row = {
                "suite": suite.name,
                "case": case["id"],
                "rep": rep,
                "source": case.get("source"),
                "output": as_jsonable(out),
                "grade": suite.grade(case, out),
                "seconds": round(time.monotonic() - started, 2),
                "calls": client.take_calls() if isinstance(client, RecordingClient) else [],
            }
            results.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)
    return rows


def usage_totals(rows: list[dict]) -> dict:
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    totals = {k: sum((c.get(k) or 0) for r in rows for c in r["calls"]) for k in keys}
    mismatched = sum(1 for r in rows for c in r["calls"] if c.get("model") and c["model"] != c["requested_model"])
    return {**totals, "calls": sum(len(r["calls"]) for r in rows), "served_by_other_model": mismatched}


def summarize(per_suite: dict[str, tuple[Suite, list[dict]]], errors_path: Path, mode: str, reps: int) -> str:
    error_counts: dict[str, int] = {}
    if errors_path.exists():
        for line in errors_path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            error_counts[e["suite"]] = error_counts.get(e["suite"], 0) + 1
    lines = [f"# Evale asystenta — tryb `{mode}`, powtórzenia: {reps}", "", f"{datetime.now():%Y-%m-%d %H:%M}", ""]
    for name, (suite, rows) in per_suite.items():
        metrics = suite.metrics(rows) if rows else {"n": 0}
        lines.append(f"## {name}")
        for key, value in metrics.items():
            lines.append(f"- {key}: {f'{value:.0%}' if isinstance(value, float) else value}")
        if reps > 1 and suite.tasks and rows:
            by_rep = {}
            for r in rows:
                by_rep.setdefault(r["rep"], []).append(r["grade"]["pass"])
            rates = [sum(v) / len(v) for v in by_rep.values()]
            lines.append(f"- pass_rate per powtórzenie: min {min(rates):.0%}, max {max(rates):.0%}")
        lines.append(f"- błędy wywołań (poza oceną): {error_counts.get(name, 0)}")
        failed = sorted({r["case"] for r in rows if not r["grade"]["pass"]})
        if failed:
            lines.append(f"- niezaliczone przypadki: {', '.join(failed)}")
        if mode == "live" and rows:
            lines.append(f"- tokeny: {usage_totals(rows)}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=MODES, default="offline")
    parser.add_argument("--suites", default="all", help=f"lista po przecinku: {', '.join(ALL)}")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--yes", action="store_true", help="nie pytaj o potwierdzenie płatnego przebiegu")
    args = parser.parse_args(argv)

    names = list(ALL) if args.suites == "all" else [s.strip() for s in args.suites.split(",")]
    unknown = [n for n in names if n not in ALL]
    if unknown:
        parser.error(f"nieznane zestawy: {unknown}")
    suites = [ALL[n] for n in names]
    if args.mode == "offline":
        suites = [s for s in suites if not s.tasks]

    client = None
    if args.mode in ("oracle", "null"):
        client = ScriptedClient()
    elif args.mode == "live":
        inner = build_client(LLMConfig.load(ROOT / "config"))
        if not isinstance(inner, ClaudeClient):
            print("Tryb live wymaga ANTHROPIC_API_KEY (i provider: anthropic w config/llm.yaml).", file=sys.stderr)
            return 2
        planned = sum(calls_per_rep(s) for s in suites) * args.reps
        print(f"Płatny przebieg: ok. {planned} wywołań Claude API ({', '.join(s.name for s in suites)}; powtórzenia: {args.reps}).")
        if not args.yes and input("Kontynuować? [t/N] ").strip().lower() not in ("t", "tak", "y", "yes"):
            return 1
        client = RecordingClient(inner)

    out = args.out or ROOT / "evals" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.mode}"
    out.mkdir(parents=True, exist_ok=True)
    per_suite: dict[str, tuple[Suite, list[dict]]] = {}
    with tempfile.TemporaryDirectory(prefix="asst-evals-") as tmp, \
            (out / "results.jsonl").open("w", encoding="utf-8") as results, \
            (out / "errors.jsonl").open("w", encoding="utf-8") as errors:  # fmt: skip
        for suite in suites:
            per_suite[suite.name] = (suite, run_suite(suite, args.mode, args.reps, client, Path(tmp), results, errors))
    summary = summarize(per_suite, out / "errors.jsonl", args.mode, args.reps)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Wyniki: {out}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("DEMO_TODAY", DEMO_TODAY.isoformat())
    raise SystemExit(main())
