# Agent B — teczka, przypomnienia o notatkach, LLM, HR partner (`app/assistant/`)

Kontekst: `docs/ARCHITEKTURA.md` § 5 (notatki), § 6 (LLM, bezpieczeństwo), § 7 (HR partner).

## Twoje pliki
`app/assistant/`, `templates/assistant/`, `static/assistant/`, `tests/assistant/`, `docs/assistant/`, `config/llm.yaml`, `config/nudges.yaml`, `prompts/`, `evals/`, `requirements-assistant.txt`. Reszta jest zamrożona (zob. `CLAUDE.md`).

## Co masz gotowe z kroku 0
- `c.employees` (FakeEmployeeDirectory) i `c.evaluations` (FakeEvaluationReader) — to, co dostarczy A. Do czasu merge'u działają na `seed/office.yaml`:
  - Henryk (E05) ma podwładnych E06, E07, E09, E12;
  - E12 nie podlega ocenie.
- `c.reminder_sink`: tu wysyłasz przypomnienia (dedupe po `dedupe_key`).
- `c.catalog`: 14 kryteriów, obowiązkowe dla arkusza (`mandatory_for`), dodatkowe (`additional_for`).
- Modele `Note`, `CriterionRating` (walidacja 1/3/5/7/9), `CriterionStats`, `DraftSuggestion`.
- Przykładowe notatki w seedzie (`notes:`): 5 o Grzegorzu, 3 o Ewie, 1 o Krzysztofie.

## Priorytety (po kolei; każdy kończ działającym demo i testami)

### 1. Teczka bez LLM
- Tabele `asst_*`: notatki z wersjami (edycja = nowa wersja, `supersedes_id`) oraz `criteria_hint` (z LLM, osobno od notatki). Import notatek z seedu przy pustej bazie.
- `DbNotesReader` (port `NotesReader`):
  - `stats_for` liczy `CriterionStats` deterministycznie (§ 5.2: mediana, rozkład, połowy okresu oceny według `period_from` i `due_date`);
  - podepnij go w `app/assistant/__init__.py::register`.
- UI `/asystent/teczka`:
  - lista podwładnych z datą ostatniej notatki;
  - `/asystent/teczka/{id}` z osią czasu i filtrami;
  - formularz notatki (§ 5.1): opis, zalety, obszary (listy), **suwaki opcjonalne, domyślnie „—”**, kryteria z `c.evaluations.current_for(id).criteria` (przed ustaleniem kryteriów: `mandatory_for`) + „inne kryteria”.
- **Tylko autor widzi swoje notatki.**

### 2. Przypomnienia o notatkach
- `NoteNudges` (`ReminderProvider`) według `config/nudges.yaml` (§ 5.4): brak notatki od N dni, kryteria bez pokrycia, skupienie w czasie, przed rozmową, brak pozytywnej.
- Jeden tygodniowy digest na przełożonego. `dedupe_key` np. `nudge:E05:2026-W47`.
- Rejestracja: `c.reminder_providers.append(...)`. Scheduler A wywoła `due(today)`. Do czasu merge'u testuj bezpośrednio `due(date(2026, 11, 21))`.

### 3. Warstwa LLM (Claude API; § 6.4)
- `LLMClient` (Protocol: `structured`, `text`, `stream`) → `ClaudeClient` (SDK `anthropic`) i `NullClient`. Konfiguracja w `config/llm.yaml`. Moduły domenowe znają tylko `LLMClient`.
- Fakty o API (sprawdzone przy kroku 0; przy wątpliwościach zajrzyj do dokumentacji SDK, nie zgaduj):
  - model `claude-opus-5-5`, klucz z `ANTHROPIC_API_KEY`;
  - structured outputs: `client.messages.parse(..., output_format=<Pydantic>)` → `response.parsed_output`;
  - **nie wysyłać `temperature` ani `thinking: disabled`** — na tym modelu oba dają 400; głębokość przez `output_config={"effort": ...}`;
  - prompt caching: stały prompt systemowy z `cache_control` na początku, zmienne dane po nim;
  - zawsze sprawdzaj `stop_reason` (np. `"refusal"` → komunikat dla użytkownika);
  - wyjątki SDK łap od najbardziej szczegółowego (`RateLimitError`, `APIStatusError`, `APIConnectionError`).
- **Prywatność przed każdym wywołaniem** (`app/assistant/privacy/`):
  - detektor danych wrażliwych (zdrowie, ciąża, związki, religia, poglądy itd.) — notatka wykluczona z wejścia + ostrzeżenie;
  - pseudonimizacja znanych osób z `c.employees.all()` → `[OSOBA_n]`, regex PESEL/tel./e-mail; odwrócenie lokalnie.
- Prompty w `prompts/<zadanie>/v1.md`. **Testy nie wołają API** (fake `LLMClient`).

### 4. Notatki z LLM
- `split_note`: opis/transkrypt → propozycja zalet i obszarów; przełożony akceptuje.
- `classify_note` w tle: punkty → kryteria (`criteria_hint`). Nie jest częścią notatki.

### 5. Podsumowanie cyklu → `DraftProvider`
- Pipeline z § 6.2: wykluczenie wrażliwych → pseudonimizacja → przypisanie punktów do kryteriów → twierdzenia z `note_ids` → **walidator cytowań** → de-pseudonimizacja.
- `AssistantDraftProvider.drafts(evaluation_id, field)` dla `UZASADNIENIE` i `WNIOSKI_IPRZ`, z `citations`. Pola projektu tekstu pokaże formularz A.
- Bez LLM: deterministyczny szkielet (zalety/obszary chronologicznie, kryteria z oceną ≤ 3 → katalog działań rozwojowych).
- LLM nigdy nie proponuje punktów ani wyniku.

### 6. HR partner `/asystent/hr` (§ 7)
Kolejność według wartości na demo:
1. przygotowanie do trudnej rozmowy;
2. **próba rozmowy** (streaming, karta postaci, limit wymian, krótka informacja zwrotna na końcu);
3. notatka → informacja zwrotna FUKO;
4. pytania o procedury z paragrafem (baza wiedzy: wyciągnij tekst przepisów/Poradnika z `context/` do `docs/assistant/wiedza/*.md`; `context/` zostaje nietknięty).

**Twarde granice** (§ 7.5): lista tematów w kodzie/configu, stały komunikat z kontaktem do kadr. Sygnały (§ 7.2) formułowane jako pytania do kierownika.

### 7. Notatki głosowe (opcjonalnie)
Nagranie w przeglądarce (MediaRecorder) → upload → faster-whisper lokalnie → transkrypt do akceptacji → audio usuwane. Gdy brak `faster-whisper`, przycisk ukryty.

### 8. `evals/`
Zestaw: notatki z oczekiwanymi kryteriami (z uzasadnień w `context/5. Przykładowe…`), pytania o procedury z oczekiwanym paragrafem, scenariusze rozmów. Skrypt uruchamiający zestaw na `LLMClient`.

## Demo (`DEMO_TODAY=2026-11-21`, użytkownik Henryk E05)
1. Teczka: lista podwładnych. **Ewa** — ostatnia notatka z kwietnia → przypomnienie. **Zofia** — brak notatek.
2. Henryk dyktuje albo pisze notatkę o Grzegorzu → podział na zalety i obszary → opcjonalnie suwaki.
3. Oś czasu Grzegorza: 6 notatek, zestawienie suwaków per kryterium.
4. HR partner: przygotowanie rozmowy z Grzegorzem przed ponowną oceną → próba rozmowy → informacja zwrotna.
5. Po merge'u z A: w formularzu oceny Grzegorza są projekty uzasadnienia i IPRZ z odnośnikami do notatek.

## Definicja ukończenia
- `pytest tests/assistant tests/contracts` zielone, bez wywołań sieci.
- Strony z `tests/test_app_smoke.py` działają.
- `python scripts/check_ownership.py` OK.
- Bez `ANTHROPIC_API_KEY` aplikacja działa: funkcje LLM ukryte lub z komunikatem, teczka i przypomnienia działają.
