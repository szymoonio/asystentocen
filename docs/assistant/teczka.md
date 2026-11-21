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

## Strony

- `/asystent/teczka` — podwładni, liczba notatek w cyklu, ostatnia obserwacja, znacznik po `no_note_after_days` z `config/nudges.yaml`.
- `/asystent/teczka/{id}` — zestawienie suwaków bieżącego cyklu, oś czasu z filtrami (`cykl`, `rodzaj=zalety|obszary`, `kryterium`, `q`), historia wersji.
- `/asystent/teczka/{id}/nowa`, `/asystent/teczka/{id}/notatka/{note_id}/edytuj` — formularz (§ 5.1). Suwaki domyślnie „—”.
