# Cyfrowy Asystent Ocen Okresowych

Prototyp na hackathon KPRM: asystent ocen okresowych w służbie cywilnej. Pilnuje terminów, prowadzi przez formularze A/B/C, zbiera notatki przełożonego i pomaga je podsumować. W zestawie wirtualny HR partner.

- Architektura: [docs/ARCHITEKTURA.md](docs/ARCHITEKTURA.md)
- Praca równoległa dwóch agentów: [docs/PRACA_ROWNOLEGLA.md](docs/PRACA_ROWNOLEGLA.md), [docs/AGENT_A.md](docs/AGENT_A.md), [docs/AGENT_B.md](docs/AGENT_B.md)
- Materiały źródłowe od KPRM: `context/`

## Start

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]' -r requirements-core.txt -r requirements-assistant.txt
pytest
DEMO_TODAY=2026-11-21 uvicorn app.main:app --reload
```

Aplikacja: http://127.0.0.1:8000. Użytkownika demo przełącza się w prawym górnym rogu. Wszystkie dane w `seed/` są fikcyjne.
