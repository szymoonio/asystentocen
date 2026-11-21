# Prompty asystenta

Układ: `prompts/<zadanie>/<wersja>.md`, np. `prompts/split_note/v1.md`. Nazwy zadań jak w `config/llm.yaml`.

- Plik to **stały prompt systemowy**: zasady, katalog kryteriów, skala, przykłady. Bez dat, ID i danych osobowych — inaczej nie działa prompt caching, a dane mogłyby wyciec.
- Zmienne dane (notatki, pytanie) idą w wiadomości użytkownika, **po** pseudonimizacji (`app/assistant/privacy/`).
- Osoby występują jako `[OSOBA_n]`, kontakty jako `[EMAIL_n]`, `[TELEFON_n]`, `[PESEL_n]`. Prompt musi prosić model o przepisywanie etykiet bez zmian.
- Zmiana treści promptu = nowa wersja pliku (`v2.md`). Wersja trafia do pola `generator` wyników (np. `claude-opus-5-5:summarize_cycle:v1`) i do `evals/`.
