# Praca równoległa: agent A i agent B na dwóch laptopach

## Jednorazowo, na każdym laptopie

```bash
git clone git@github.com:szymoonio/asystentocen.git && cd asystentocen
python3.12 -m venv .venv   # albo python3.13; wymagany Python ≥ 3.12
source .venv/bin/activate
pip install -e '.[dev]' -r requirements-core.txt -r requirements-assistant.txt
cp .env.example .env       # agent B: wpisz ANTHROPIC_API_KEY
pytest                     # powinno być zielono (testy golden: skipped)
DEMO_TODAY=2026-11-21 uvicorn app.main:app --reload
```

Laptop A:
```bash
git switch -c feat/core origin/main
```

Laptop B:
```bash
git switch -c feat/assistant origin/main
```

Potem uruchom Claude Code w repo i napisz np. „Jesteś agentem A. Przeczytaj CLAUDE.md i docs/AGENT_A.md i zacznij od priorytetu 1.” (dla B analogicznie).

## Jak to działa bez konfliktów

- Katalogi są rozłączne (tabela w `CLAUDE.md`). `scripts/check_ownership.py` i CI tego pilnują.
- Moduły rozmawiają tylko przez porty z `app/contracts/ports.py`.
- Do czasu merge'u każdy widzi drugą stronę przez **fake'i** (`app/contracts/fakes.py`) zasilane z `seed/office.yaml`. Dzięki temu A widzi przykładowe notatki w panelu „Twoje obserwacje”, a B widzi pracowników i oceny, choć kod drugiej strony jeszcze nie istnieje.
- Każdy moduł sam podmienia swoje porty w `register(c)` (`app/core/__init__.py`, `app/assistant/__init__.py`). Po merge'u `main.py` i `container.py` zostają bez zmian.
- Tabele bazy mają prefiksy `core_*` (A) i `asst_*` (B). Wspólne jest tylko `Base` z `app/db.py`.

## Codziennie

```bash
pytest && python scripts/check_ownership.py
git add -A && git commit -m "..." && git push -u origin HEAD
```

**Merge'ujcie do main często** (co kilka godzin, gdy coś działa), a nie raz na końcu:
1. PR `feat/core` → `main` (CI: testy + kontrola własności), merge.
2. Druga osoba: `git fetch && git merge origin/main`, czyli dostaje prawdziwe implementacje portów drugiej strony zamiast fake'ów.

Konflikty nie powinny wystąpić, bo nikt nie rusza cudzych plików.

## Zmiana kontraktu (pliki zamrożone)

Zdarzy się, np. „B potrzebuje w `EvaluationSummary` pola X”.

1. Uzgodnijcie zmianę ustnie (A + B).
2. Jedna osoba: `git switch -c contracts/<opis> origin/main`, zmienia tylko pliki zamrożone (kontrakty, fake'i, seed, testy kontraktów), PR do main, merge.
3. Obie gałęzie: `git fetch && git merge origin/main`.

Zmiany kontraktów mają być **addytywne** (nowe pole z wartością domyślną, nowa metoda), żeby nie psuć kodu drugiej strony.

## Integracja na koniec

1. Obie gałęzie zmerge'owane do main.
2. `pytest` na main: zielono, testy golden już nie są pomijane.
3. Ręcznie przejść scenariusz demo (`docs/AGENT_A.md` i `docs/AGENT_B.md`, sekcje „Demo”) z `DEMO_TODAY=2026-11-21`.
