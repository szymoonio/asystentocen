# Asystent Ocen — instrukcje dla agentów

Projekt na hackathon KPRM: cyfrowy asystent ocen okresowych w służbie cywilnej.
Architektura: `docs/ARCHITEKTURA.md`. Materiały źródłowe (przepisy, wzory arkuszy): `context/` — tylko do odczytu.

## Dwóch agentów, jedno repo

Praca idzie równolegle na dwóch laptopach. **Najpierw ustal, którym agentem jesteś:**

- gałąź `feat/core*` → **agent A** → przeczytaj `docs/AGENT_A.md`
- gałąź `feat/assistant*` → **agent B** → przeczytaj `docs/AGENT_B.md`
- inna gałąź → zapytaj użytkownika

Proces (gałęzie, synchronizacja, merge): `docs/PRACA_ROWNOLEGLA.md`.

## Własność plików — twarda zasada

| Kto | Może zmieniać |
|---|---|
| A | `app/core/`, `templates/core/`, `static/core/`, `tests/core/`, `docs/core/`, `config/reminders.yaml`, `requirements-core.txt` |
| B | `app/assistant/`, `templates/assistant/`, `static/assistant/`, `tests/assistant/`, `docs/assistant/`, `config/llm.yaml`, `config/nudges.yaml`, `prompts/`, `evals/`, `requirements-assistant.txt` |
| nikt (zamrożone) | wszystko inne: `app/contracts/`, `app/main.py`, `app/container.py`, `app/deps.py`, `app/templating.py`, `app/shell.py`, `app/db.py`, `app/settings.py`, `app/clock.py`, `config/regulation/`, `seed/`, `templates/base.html`, `templates/placeholder.html`, `static/base.css`, `tests/contracts/`, `tests/golden/`, `tests/conftest.py`, `tests/test_app_smoke.py`, `pyproject.toml`, `scripts/`, `.github/`, `CLAUDE.md`, `docs/*.md` |

Przed commitem: `python scripts/check_ownership.py`. Jeśli potrzebujesz zmiany w pliku zamrożonym (np. nowe pole w modelu kontraktu), **nie zmieniaj go na swojej gałęzi** — opisz potrzebną zmianę użytkownikowi; trafi osobnym PR `contracts/<opis>` do main.

## Komendy

```bash
source .venv/bin/activate
pip install -e '.[dev]' -r requirements-core.txt -r requirements-assistant.txt
DEMO_TODAY=2026-11-21 uvicorn app.main:app --reload   # http://127.0.0.1:8000
pytest                                                 # wszystko
pytest tests/core tests/golden tests/contracts         # agent A
pytest tests/assistant tests/contracts                 # agent B
```

## Zasady

- Interfejs i komunikaty po polsku. Kod, nazwy w kodzie i commity — po angielsku albo polsku, byle spójnie w module.
- Wszystko, co zależy od „dziś”, bierze datę z `container.clock.today()`, nigdy `date.today()`.
- Średnie i progi ocen liczymy na `fractions.Fraction`, nie na float.
- Dane wyłącznie fikcyjne (`seed/`). Nie wpisujemy prawdziwych danych osobowych.
- Testy nie wołają sieci: klient LLM w testach jest mockowany.
- `tests/golden/` i `tests/test_app_smoke.py` muszą przechodzić (lub być pominięte przez `importorskip`) na każdej gałęzi.
