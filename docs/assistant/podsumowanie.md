# Podsumowanie cyklu i `DraftProvider` (moduł B)

## Dla agenta A: `c.drafts` = `AssistantDraftProvider`

- `available()` → zawsze `True` (bez LLM działa szkielet deterministyczny).
- `drafts(evaluation_id, DraftField.UZASADNIENIE | DraftField.WNIOSKI_IPRZ)` → **lista akapitów** (`DraftSuggestion`), każdy z `citations` (ID notatek). Formularz może pokazać akapity osobno („przyjmij / edytuj / odrzuć”) i linkować cytaty do `NotesReader.teczka_url(subject_id) + "#" + note_id`.
- `UMOTYWOWANIE_WNIOSKU` → `[]` (na razie).
- `generator`: `deterministic:v1` (szkielet) albo np. `claude-opus-5-5:summarize_cycle:v1` (projekt LLM).
- **`drafts()` nigdy nie wywołuje API** — czyta zapisany projekt. Projekt LLM przygotowuje oceniający przyciskiem na `/asystent/podsumowanie/{evaluation_id}`; gdy od tego czasu zmienią się notatki albo wpisane oceny cząstkowe (`EvaluationSummary.result.partial_points`), `drafts()` wraca do szkieletu.
- Źródło notatek: oceniający z `EvaluationSummary.evaluator_id`, notatki z `evaluation_id` tej oceny, bez notatek z danymi wrażliwymi.

## Pipeline (ARCHITEKTURA § 6.2)

1. `EvidenceBuilder` — notatki cyklu → detektor wrażliwych (wykluczone + ostrzeżenie) → punkty B/S/I z kryteriami (podpowiedzi LLM, a bez nich suwaki notatki) → statystyki suwaków → kryteria do IPRZ (ocena cząstkowa ≤ 3, a przed wpisaniem ocen mediana suwaków ≤ 3).
2. Szkielet (`skeleton.py`) — zalety i obszary chronologicznie; kryteria do IPRZ → pozycje z `app/assistant/summarize/development_actions.yaml` (do edycji przez kadry).
3. LLM (`llm_summary.py`, zadanie `summarize_cycle`) — pseudonimizacja, notatki w znacznikach `<notatka>` (dane, nie polecenia), oceny cząstkowe słownie, jedno wywołanie structured → akapity z `note_refs`.
4. Walidator (`validate.py`) — odrzuca akapit bez cytatu, z cytatem spoza cyklu, z osobami lub liczbami spoza cytowanych notatek, ze słowami o wyniku/punktach/średniej, z danymi wrażliwymi, za długi. Odrzucone są widoczne na stronie, nie trafiają do formularza.
5. De-pseudonimizacja lokalnie, zapis w `asst_drafts` z `input_key`.

Uproszczenie: jedno wywołanie zamiast map/reduce.
