# Notatki głosowe (moduł B)

- **Włączenie:** `pip install faster-whisper`. Model (`stt.model` w `config/llm.yaml`, domyślnie `small`) pobiera się przy pierwszym nagraniu. Bez pakietu przyciski są ukryte, a `POST /asystent/teczka/{id}/glos` odpowiada „Notatki głosowe są wyłączone”.
- **W formularzu nowej notatki:**
  - „● Nagraj notatkę głosową” — MediaRecorder w przeglądarce, auto-stop po `stt.max_seconds`; transkrypt trafia do pola „Opis sytuacji”, notatka zapisuje się ze źródłem `VOICE`;
  - „Masz nagranie z telefonu? Wgraj je” — zwykły upload bez JS (limit `stt.max_upload_mb`).
- **Prywatność:** audio jest zapisywane do pliku tymczasowego tylko na czas transkrypcji i kasowane w `finally` (także przy błędzie). Nic nie trafia do LLM, dopóki przełożony nie użyje „Podziel opis…” (wtedy z pseudonimizacją).
- **AI Act art. 5 ust. 1 lit. f:** wyłącznie transkrypcja — bez analizy tonu i emocji.
- **Silnik wymienny:** `app/assistant/stt/` (`Transcriber`: `available()`, `transcribe(path)`), np. whisper.cpp w przyszłości.
- **Nie sprawdzone na prawdziwym modelu** (pakiet nie jest zainstalowany w repo); testy używają atrapy modułu `faster_whisper`.
