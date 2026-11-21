#!/usr/bin/env python3
"""Sprawdza, czy gałąź zmienia tylko pliki swojego agenta. ZAMROŻONE (krok 0).

Użycie:
    python scripts/check_ownership.py            # agent z nazwy gałęzi, baza origin/main
    python scripts/check_ownership.py --agent A --base main

Nazwy gałęzi: feat/core* → A, feat/assistant* → B, contracts/* → zmiany kontraktów
(wolno ruszać pliki zamrożone, ale NIE kod modułów). Inne gałęzie nie są sprawdzane.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

OWNED = {
    "A": (
        "app/core/",
        "templates/core/",
        "static/core/",
        "tests/core/",
        "docs/core/",
        "config/reminders.yaml",
        "requirements-core.txt",
    ),
    "B": (
        "app/assistant/",
        "templates/assistant/",
        "static/assistant/",
        "tests/assistant/",
        "docs/assistant/",
        "config/llm.yaml",
        "config/nudges.yaml",
        "prompts/",
        "evals/",
        "requirements-assistant.txt",
    ),
}
MODULE_CODE = OWNED["A"] + OWNED["B"]


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def agent_from_branch(branch: str) -> str | None:
    if branch.startswith("feat/core"):
        return "A"
    if branch.startswith("feat/assistant"):
        return "B"
    if branch.startswith("contracts/"):
        return "CONTRACTS"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=["A", "B", "CONTRACTS"])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--branch")
    args = parser.parse_args()

    branch = args.branch or sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    agent = args.agent or agent_from_branch(branch)
    if agent is None:
        print(f"Gałąź „{branch}” nie jest gałęzią agenta — pomijam sprawdzenie.")
        return 0

    merge_base = sh("git", "merge-base", args.base, "HEAD")
    changed = [f for f in sh("git", "diff", "--name-only", merge_base, "HEAD").splitlines() if f]
    changed += [f for f in sh("git", "diff", "--name-only").splitlines() if f]
    changed += [f for f in sh("git", "diff", "--name-only", "--cached").splitlines() if f]
    changed += [f for f in sh("git", "ls-files", "--others", "--exclude-standard").splitlines() if f]
    changed = sorted(set(changed))

    if agent == "CONTRACTS":
        bad = [f for f in changed if f.startswith(MODULE_CODE)]
        reason = "PR kontraktów nie może zmieniać kodu modułów"
    else:
        bad = [f for f in changed if not f.startswith(OWNED[agent])]
        reason = f"agent {agent} może zmieniać tylko: {', '.join(OWNED[agent])}"

    if bad:
        print(f"✗ {reason}. Pliki poza zakresem:")
        for f in bad:
            print(f"   {f}")
        print("Zmiana kontraktu? Osobna gałąź contracts/<opis> → PR do main → obie gałęzie: git merge main.")
        return 1
    print(f"✓ {len(changed)} zmienionych plików, wszystkie w zakresie ({agent}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
