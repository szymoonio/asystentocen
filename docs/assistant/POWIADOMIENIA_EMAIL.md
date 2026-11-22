# Powiadomienia e-mail „dawno bez notatki”

Przełożony dostaje maila, gdy o osobie w trwającym okresie oceny nie było notatki dłużej niż
`no_note_after_days` (domyślnie 45 dni). W mailu jest przycisk prosto do nowej notatki o tej osobie.
Maile nie są pokazywane w aplikacji — to wyłącznie przypominajka w skrzynce pocztowej.

- jeden mail na osobę; ponownie po `repeat_after_days` (21), jeśli nadal brak notatki;
- najwyżej `max_per_day` (3) dziennie na przełożonego; osoby „odłożone” w teczce są pomijane;
- w treści nie ma treści notatek — tylko imię i nazwisko, data ostatniej notatki, termin oceny i link.

Wysyłka idzie razem z codziennymi przypomnieniami (pierwsze wejście na pulpit danego dnia,
przycisk „odśwież przypomnienia” albo `python -m app.core.scheduler`).

## Podłączenie własnej skrzynki (demo)

Wszystko w pliku `.env` (jest w `.gitignore` — hasło nie trafia do repozytorium):

```
MAIL_TRANSPORT=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=twoj.adres@gmail.com
SMTP_PASSWORD=haslo-aplikacji
MAIL_REDIRECT_TO=twoj.adres@gmail.com
MAIL_ONLY_FOR=E05
APP_BASE_URL=http://127.0.0.1:8000
```

- `MAIL_REDIRECT_TO` — dane demo mają adresy `@przyklady.example`, które nie istnieją; wszystkie maile
  idą więc na Twój adres, a w temacie jest `[demo → Henryk Pryncypał]`.
- `MAIL_ONLY_FOR` — tylko przypomnienia dla tych przełożonych (id z `seed/office.yaml`); bez tego
  dostaniesz też maile Barbary, Tadeusza, Marka itd.
- Gmail: hasło aplikacji (nie zwykłe hasło) — wymaga włączonej weryfikacji dwuetapowej na koncie Google,
  potem „Hasła aplikacji” w ustawieniach bezpieczeństwa konta.
- Link w mailu prowadzi na `APP_BASE_URL` — działa na komputerze, na którym chodzi serwer.

Test podłączenia — od razu jeden mail o wybranej osobie (bez progów i limitów):

```
DEMO_TODAY=2026-11-21 python -m app.assistant.mail --osoba E07
```

Dzisiejsze przypomnienia „naprawdę” (jak scheduler):

```
DEMO_TODAY=2026-11-21 python -m app.assistant.mail
```

## Wdrożenie

`MAIL_TRANSPORT=smtp`, `SMTP_*` wskazują serwer pocztowy urzędu, bez `MAIL_REDIRECT_TO` i `MAIL_ONLY_FOR`,
a `APP_BASE_URL` to adres aplikacji w sieci urzędu. Adresy przełożonych pochodzą z danych kadrowych.
