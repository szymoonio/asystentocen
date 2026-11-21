# Agent A — rdzeń procesu i formularze (`app/core/`)

Deterministyczna część systemu: **bez LLM**. Kontekst: `docs/ARCHITEKTURA.md` § 1, 3, 4.
Przepisy: `context/1. Akty prawne/`, schematy pól: `context/4. Formularze ocen/*/schemat pól formularza.docx`.

## Twoje pliki
`app/core/`, `templates/core/`, `static/core/`, `tests/core/`, `docs/core/`, `config/reminders.yaml`, `requirements-core.txt`. Reszta jest zamrożona (zob. `CLAUDE.md`).

## Co masz gotowe z kroku 0
- `app/contracts/`: modele, enumy, porty, katalog kryteriów (`c.catalog`), skala (`load_scale`), arkusze (`c.catalog.sheets`).
- `c.notes` (FakeNotesReader) i `c.drafts` (NullDraftProvider): to, co dostarczy B. Do czasu merge'u działają na seedzie.
- `seed/office.yaml`: fikcyjny urząd, 12 osób, historia ocen, nieobecności. Komentarze w pliku opisują przypadki demo.
- `tests/golden/`: testy, które masz zazielenić. Do czasu powstania modułów są pomijane.

## Priorytety (po kolei; każdy kończ działającym demo i testami)

### 1. Reguły (czyste funkcje, `app/core/rules/`)
API wymagane przez `tests/golden/`:
```python
# app/core/rules/calendar_pl.py
holidays(year: int) -> set[date]          # w tym Wielkanoc algorytmicznie, 24.12 od 2025 r.
is_working_day(d: date) -> bool           # sobota, niedziela i święta = wolne
add_months(d: date, n: int) -> date       # obcięcie do ostatniego dnia miesiąca, BEZ przesunięcia
shift_to_working_day(d: date) -> date     # koniec terminu w dzień wolny/sobotę → następny roboczy
deadline_in_days(event: date, n: int) -> date    # dzień zdarzenia się nie liczy, potem shift
deadline_in_months(start: date, n: int) -> date  # add_months, potem shift
# app/core/rules/deadlines.py
merge_absences(periods: list[tuple[date, date]]) -> list[tuple[date, date]]  # łączenie przez dni wolne
is_longer_than_month(start: date, end: date) -> bool
# app/core/rules/scoring.py
score(points: Sequence[int]) -> ScoreResult   # .mean: Fraction, .level: Level, .outcome: Outcome
```
Dodatkowo (z własnymi testami w `tests/core/`):
- wybór arkusza z `Position`;
- termin oceny: 24 mies. od poprzedniej oceny albo od zatrudnienia na czas nieokreślony, + przedłużenie o nieobecność > 1 mies. (art. 81 ust. 7), 6 mies. po zapoznaniu z negatywną (ust. 9);
- termin kryteriów (§ 7);
- zmiana stanowiska (§ 9, art. 81 ust. 6);
- dopuszczalność zmiany terminu (art. 81 ust. 8: tylko gdy minęło > 6 mies.);
- obligatoryjny stopień (art. 89 ust. 2: 2 kolejne oceny POWYZEJ/ZNACZNIE_POWYZEJ od ostatniego stopnia, 30 dni od zapoznania);
- sprzeciw (art. 83: 7 dni, rozpatrzenie 14 dni).

Każda funkcja zwraca też **podstawę prawną** (np. `"art. 81 ust. 9 ustawy"`), żeby UI mógł ją pokazać.

Sprawdzenie: wyliczone terminy dla seedu są równe `due_date` / `criteria_due_date` z `seed/office.yaml`.

### 2. Dane w bazie i prawdziwe porty
- Tabele `core_*` (pracownicy, jednostki, nieobecności, oceny, zdarzenia/audyt, przypomnienia).
- Import `seed/office.yaml` przy pustej bazie.
- `DbEmployeeDirectory`, `DbEvaluationReader`, `DbReminderSink`, podpięte w `app/core/__init__.py::register`.
- Testy portów z `tests/core/`. Dobra praktyka: te same asercje co w `tests/contracts/test_fakes_and_seed.py` powinny przejść na Twoich implementacjach.

### 3. Proces i formularz A/B/C
- Maszyna stanów (`EvaluationState`, docs/ARCHITEKTURA.md § 3) z audytem każdej zmiany. „Fikcja zapoznania” jako osobna akcja.
- **Definicje formularzy** `app/core/forms/definitions/{A,B,C}.v2016.yaml`: pola, źródło autouzupełnienia, edytowalność (stan × rola), walidacje blokujące. Silnik jest jeden, wspólny dla trzech arkuszy. Spec pól: schematy w `context/4. Formularze ocen/`.
- **Część I:** 3 listy kryteriów dodatkowych bez powtórzeń (`c.catalog.additional_for(sheet)`), termin domyślnie wyliczony, potwierdzenie oceniającego, potem ocenianego.
- **Część II:**
  - matryca 1/3/5/7/9; średnia, poziom i POZYTYWNA/NEGATYWNA wyliczane automatycznie;
  - uzasadnienie obowiązkowe przy negatywnej; IPRZ zawsze obowiązkowe;
  - dane poprzedniej oceny z historii (tylko urzędnik);
  - TAK/NIE/NIE DOTYCZY według reguł ze schematu.
- **Część III:** tylko urzędnik + pozytywna + TAK; stopień 9 blokuje z komunikatem; „wnioskuję o przyznanie *trzeciego*…” wyliczane.
- **Panel „Twoje obserwacje”** obok matrycy: `c.notes.stats_for(author_id=oceniający, subject_id, evaluation_id)`.
  - Rozkład i mediana per kryterium, link `c.notes.teczka_url(subject_id)`.
  - Ostrzeżenie o rozbieżności, gdy |ocena − mediana| ≥ 4 pkt (2 stopnie) przy ≥ 3 obserwacjach.
  - **Matrycy nie wypełniamy automatycznie.**
- **Projekty tekstów:** gdy `c.drafts.available()`, przy polach UZASADNIENIE / WNIOSKI_IPRZ / UMOTYWOWANIE_WNIOSKU pokaż `c.drafts.drafts(evaluation_id, field)` z przyciskiem „wstaw do pola” (edytowalne, oznaczone „projekt asystenta”).

### 4. Przypomnienia i scheduler
- `ProcessReminders` (`ReminderProvider`) według `config/reminders.yaml`, rodzaje `ReminderKind.CRITERIA_*`, `ASSESSMENT_*`, `PROMOTION_DUE` itd.
- Scheduler: wywołuje `due(c.clock.today())` dla **wszystkich** `c.reminder_providers` (także B) i wysyła do `c.reminder_sink`.
- Na demo: przycisk „Uruchom przypomnienia” (`POST /core/scheduler/run`) + uruchomienie raz dziennie.
- Skrzynka przypomnień na pulpicie. E-mail (SMTP) i `.ics` opcjonalnie.

### 5. Wydruk
Widok do druku zgodny z wzorem z rozporządzenia (HTML + CSS `@media print`). Część III drukowana tylko, gdy dotyczy. PDF przez WeasyPrint opcjonalnie.

### 6. Kadry i statystyki
- Lista pracowników z terminami (filtr: zaległe / w ciągu 30 dni).
- Nieobecności (tylko daty, bez przyczyn).
- Zmiana terminu z wyborem podstawy (art. 81 ust. 8) i powiadomieniem (§ 8).
- Import CSV, wprowadzanie ocen historycznych.
- Statystyki tylko agregatami, z progiem ≥ 5 osób.

## Demo (scenariusz do przejścia na koniec, `DEMO_TODAY=2026-11-21`)
1. Henryk (E05) na pulpicie widzi:
   - **Zofię** z zaległym terminem ustalenia kryteriów (19.11);
   - **Ewę** z terminem oceny 10.12;
   - **Grzegorza** (ponowna ocena po negatywnej, 15.12).
2. Henryk ustala kryteria Zofii (Część I). Zofia (przełącz użytkownika) potwierdza.
3. Henryk przechodzi ocenę Ewy: rozmowa → matryca z panelem obserwacji → wynik liczy się sam → uzasadnienie/IPRZ → zatwierdzenie. Ewa potwierdza. Wydruk.
4. Magda (kadry, E11) widzi przypomnienie o obligatoryjnym stopniu dla Piotra (E08) do 07.12.2026 i termin Krzysztofa przedłużony do 04.05.2027 z powodu nieobecności.

## Definicja ukończenia
- `pytest tests/golden tests/contracts tests/core` zielone, golden **nie** pominięte.
- Strony z `tests/test_app_smoke.py` działają.
- `python scripts/check_ownership.py` OK.
- Scenariusz demo przechodzi ręcznie.
