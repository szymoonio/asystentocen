# Teczka (moduł B) — notatki dla agenta A i zespołu

## `c.notes` = `DbNotesReader`

- `notes_for(author_id, subject_id, since=, until=)` — tylko **bieżące wersje** notatek tego autora, chronologicznie po dacie zdarzenia. Notatki innych przełożonych są niewidoczne.
- `stats_for(author_id, subject_id, evaluation_id)` zwraca `CriterionStats`:
  - **każde kryterium oceny**, także bez suwaków (`n_ratings == 0` = brak pokrycia); przed ustaleniem kryteriów (`CYCLE_OPEN`) są to obowiązkowe kryteria arkusza;
  - na końcu kryteria ocenione w notatkach, choć nie należą do oceny (np. po zmianie kryteriów);
  - `median` — główna miara; `first_half_mean` / `second_half_mean` — połowy **okresu oceny** (`period_from` → `due_date`), nie połowy listy notatek;
  - `distribution` zawiera tylko punkty, które wystąpiły.
  - Panel „Twoje obserwacje” może odfiltrować `n_ratings == 0`, jeśli nie chce pokazywać pokrycia.
- `teczka_url(subject_id)` → `/asystent/teczka/{id}`; filtr kryterium: `?kryterium=KOD`.

## Dane

- Tabele `asst_notes` (wersje: edycja = nowy wiersz z `supersedes_id`) i `asst_criteria_hints` (podpowiedzi LLM, osobno od notatki).
- Przy pustej bazie notatki importują się z `seed/office.yaml`. Reset demo: usuń `data/app.db`.

## Przypomnienia o notatkach (`NoteNudges`)

- Zarejestrowane w `c.reminder_providers` (`name = "assistant.note_nudges"`). Scheduler A woła `due(today)`.
- **Jedno zestawienie tygodniowo na przełożonego:** `Reminder(kind=NOTE_NUDGE, dedupe_key="nudge:<id>:<rok>-W<tydzień>", link="/asystent/teczka")`, treść w liniach `• Osoba: komunikat`. Codzienne wywołania w tym samym tygodniu deduplikuje sink.
- Reguły (`app/assistant/nudges/rules.py`, progi w `config/nudges.yaml`) dla ocen w stanach `CYCLE_OPEN`, `CRITERIA_CONFIRMED`, `OBSERVATION`:
  - brak notatki od N dni (bez notatek — liczone od początku cyklu, a przed ustaleniem kryteriów od zapoznania z poprzednią oceną);
  - przed oceną (okno 60 dni): liczba notatek i kryteria bez obserwacji;
  - kryteria bez obserwacji (gdy cykl trwa ≥ 30 dni i są jakieś notatki; poza oknem przed oceną);
  - skupienie w czasie (≥ 80% notatek z ostatnich 90 dni, w ostatnich 90 dniach przed terminem, min. 3 notatki);
  - brak pozytywnej obserwacji od 120 dni;
  - powrót z nieobecności ≥ 30 dni (do 30 dni po powrocie, jeśli od powrotu nie ma notatki).
- „Odłóż o 14 dni” wycisza osobę u danego przełożonego (`asst_nudge_snoozes`).
- Ten sam przegląd widać na `/asystent/teczka` (liczony na bieżąco), z przyciskiem „+ Notatka”.

## Strony

- `/asystent/teczka` — podwładni, liczba notatek w cyklu, ostatnia obserwacja, znacznik po `no_note_after_days` z `config/nudges.yaml`.
- `/asystent/teczka/{id}` — zestawienie suwaków bieżącego cyklu, oś czasu z filtrami (`cykl`, `rodzaj=zalety|obszary`, `kryterium`, `q`), historia wersji.
- `/asystent/teczka/{id}/nowa`, `/asystent/teczka/{id}/notatka/{note_id}/edytuj` — formularz (§ 5.1). Suwaki domyślnie „—”.
