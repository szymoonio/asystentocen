# Cyfrowy Asystent Ocen Okresowych — architektura

Dokument roboczy zespołu. Opiera się na materiałach z `context/` (opis wyzwania KPRM, rozporządzenie PRM z 4.04.2016, ustawa o s.c. art. 81–83 i 89, use case'y, BPMN, schematy pól A/B/C, 13 przykładowych arkuszy, Poradnik, „liczenie terminów”).

Priorytet: **ocena okresowa** — terminy, formularze, notatki przełożonego i podsumowanie ich pracą LLM.

---

## 1. Najważniejsze wnioski z materiałów

### 1.1 Arkusze A/B/C to jeden formularz z trzema konfiguracjami

Po porównaniu schematów pól (`4. Formularze ocen/*/schemat pól formularza.docx`) arkusze różnią się tylko trzema rzeczami:

| | A (kierownik urzędu) | B (bezpośrednie kierowanie ludźmi) | C (pozostali) |
|---|---|---|---|
| Kryteria obowiązkowe | 6: zarządzanie ludźmi, podejmowanie decyzji i odpowiedzialność, organizacja pracy…, współpraca, komunikacja, **zarządzanie strategiczne** | 5: jak A bez zarządzania strategicznego | 5: **wykorzystywanie wiedzy i doskonalenie zawodowe**, **rzetelność**, organizacja pracy…, współpraca, komunikacja |
| Pole „Komórka organizacyjna” | brak | jest | jest |
| Pouczenie – sprzeciw do | **pole edytowalne** (kierownik urzędu nie ma nad sobą DG) | „dyrektora generalnego urzędu” | „dyrektora generalnego urzędu” |

Reszta (Część I, II, III, matryca 1/3/5/7/9, średnia, poziom, POZYTYWNA/NEGATYWNA, uzasadnienie, IPRZ, poprzednia ocena, wniosek o stopień) jest identyczna.

**Wniosek:** jeden silnik formularzy + trzy deklaratywne definicje (YAML). Zmiana przepisów to nowa wersja pliku z datą wejścia w życie, bez zmian w kodzie. Wymaganie z przypisu 3 opisu wyzwania dostajemy w ten sposób za darmo. Wybór wersji robimy według reguły przejściowej z § 13: liczy się data zapoznania z kryteriami.

### 1.2 Schemat pól to gotowa specyfikacja maszyny stanów

Każde pole ma opisane, w którym etapie jest edytowalne, kiedy się blokuje i że później zmienia je tylko „administrator w trybie korekty błędów”. Wynika z tego, że:
- uprawnienia do pól wyliczamy z pary **(stan oceny, rola)** i nie programujemy ich osobno dla każdego pola,
- korekta administratora to osobna, logowana operacja (audit trail).

### 1.3 Co da się zrobić deterministycznie (prawie wszystko poza tekstem)

| Element | Reguła | Źródło |
|---|---|---|
| Wybór arkusza | kierownik urzędu → A; bezpośrednio kieruje pracownikami → B; inaczej C | § 3 |
| Kryteria obowiązkowe | stała lista z definicji arkusza | § 4 |
| Kryteria dodatkowe | 0–3, bez powtórzeń, z katalogu 14 kryteriów (zał. 1) minus obowiązkowe | § 5 ust. 2 |
| Termin oceny | +24 mies. od poprzedniej oceny / zatrudnienia na czas nieokreślony; + czas nieobecności > 1 mies.; po ocenie negatywnej +6 mies. od zapoznania | art. 81 ust. 4, 7, 9 |
| Termin ustalenia kryteriów | 30 dni (7 dni po ocenie negatywnej) | § 7 |
| Zmiana stanowiska ≤ 6 mies. | ponownie § 5–6 w ciągu 30 dni, termin oceny bez zmian | § 9 ust. 1 |
| Zmiana stanowiska > 6 mies. | ocena od −7 do +30 dni względem zmiany | art. 81 ust. 6, § 9 ust. 2 |
| Zmiana terminu przez oceniającego / na wniosek | dopuszczalna tylko, gdy minęło > 6 mies. | art. 81 ust. 8 |
| Średnia, poziom, wynik | średnia arytmetyczna; przedziały 1–2 / >2–4 / >4–6 / >6–8 / >8–9; **każda cząstkowa = 1 → NEGATYWNA** | § 11 ust. 1 |
| Uzasadnienie | obowiązkowe przy negatywnej (blokada zatwierdzenia) | § 11 ust. 3 |
| Wnioski IPRZ | zawsze obowiązkowe (blokada zatwierdzenia) | art. 81 ust. 5 |
| Część III | tylko urzędnik + pozytywna + „TAK”; stopień 9 → komunikat o blokadzie; „wnioskuję o przyznanie **drugiego**…” wyliczane | § 11 ust. 5, art. 89 |
| Obligatoryjny stopień | 2 kolejne pozytywne na poziomie „powyżej” lub „znacznie powyżej” od ostatniego stopnia → przypomnienie dla kadr, 30 dni od zapoznania | art. 89 ust. 2 |
| Sprzeciw | 7 dni od zapoznania; rozpatrzenie 14 dni; uwzględniony → zmiana albo ponowne sporządzenie (powrót do etapu „rozmowa oceniająca”) | art. 83 |
| Liczenie terminów | miesiące z obcięciem do ostatniego dnia miesiąca; koniec w sobotę lub dzień wolny przesuwa się na następny dzień roboczy; dzień zdarzenia się nie liczy; nieobecności łączone przez dni wolne | „liczenie terminów.docx” |

**Pułapki znalezione w danych:**
- **Precyzja średniej.** Porównujemy ułamki (`fractions.Fraction` albo suma vs. `n × próg`), nie floaty. Granice są „od … do” i „powyżej”: średnia dokładnie 4,0 to „poniżej oczekiwań”, a 6,0 to „na poziomie”.
- **Zaokrąglanie w przykładach jest niespójne.** Arkusz 12 ma 27/7 = 3,857 i pokazuje „3,8” (obcięcie), arkusz 13 pokazuje „6,25” (2 miejsca). Proponujemy klasyfikację na wartości dokładnej i wyświetlanie 2 miejsc po przecinku. **Pytanie do mentorów KPRM.**
- W przykładowym arkuszu jest literówka w dacie („14.046.2024”), więc walidacja dat w UI jest konieczna.
- Arkusz 12 ma 5 kryteriów obowiązkowych i 2 dodatkowe (n = 7), więc liczba kryteriów jest zmienna i nie wolno jej zakładać na sztywno.

Kalendarz świąt PL: 1.01, 6.01, Wielkanoc (niedziela i poniedziałek), 1.05, 3.05, Zielone Świątki, Boże Ciało, 15.08, 1.11, 11.11, **24.12 (od 2025)**, 25.12, 26.12. Wielkanoc liczymy algorytmicznie, a listę trzymamy w configu, żeby dało się ją zaktualizować bez wydania nowej wersji.

### 1.4 Notatki mają oparcie w Poradniku

Poradnik (s. 24) wprost zaleca prowadzenie **nieformalnej „teczki pracowniczej”** z bieżącymi, pisemnymi obserwacjami oraz cyklicznych (miesięcznych lub kwartalnych) podsumowań. Celem jest uniknięcie zniekształcenia ocen przez ostatnie zdarzenia. Standardy ZZL (zarządzenie nr 6 SSC, rozdz. 6) mówią o informacji zwrotnej bieżącej i cyklicznej (np. kwartalnej). Nasz moduł notatek i przypomnień to więc **cyfrowa realizacja zaleceń KPRM**, a nie dodatek. Warto to podkreślić w prezentacji.

---

## 2. Architektura — widok ogólny

```
┌──────────────────────────────────────────────────────────────────────────┐
│ web (FastAPI + Jinja/HTMX) — routery montowane przez każdy moduł         │
├────────────────────────────────┬─────────────────────────────────────────┤
│  CORE  (Agent A)               │  ASSISTANT  (Agent B)                   │
│  deterministyczne, bez AI      │  notatki + AI, działa „obok” core       │
│                                │                                         │
│  hr_data   – pracownicy,       │  notes      – teczka: tekst + głos,     │
│              struktura,        │               historia, wersje, tagi     │
│              nieobecności      │  stt        – Whisper lokalnie          │
│  rules     – kalendarz PL,     │  nudges     – przypomnienia o notatkach │
│              terminy, scoring, │  privacy    – pseudonimizacja,          │
│              stopnie           │               detektor danych wrażliwych │
│  forms     – definicje A/B/C,  │  llm        – gateway (Claude/wymienny) │
│              silnik pól,       │               + provider „none”          │
│              PDF/druk          │  summarize  – podsumowanie z cytatami   │
│  workflow  – maszyna stanów,   │               + walidator               │
│              blokady, audit    │  prep       – przygotowanie do rozmów   │
│  reminders – terminy procesu   │  hr_partner – sygnały + playbooki       │
│  notify    – outbox, e-mail,   │                                         │
│              in-app, .ics      │                                         │
│  scheduler – jeden runner      │                                         │
├────────────────────────────────┴─────────────────────────────────────────┤
│ contracts/  — WSPÓLNE, zamrożone przed startem (modele, porty, eventy)   │
├──────────────────────────────────────────────────────────────────────────┤
│ DB: SQLite (mały urząd) / PostgreSQL (duży) — każdy moduł ma swoje tabele│
└──────────────────────────────────────────────────────────────────────────┘
        LLM: Claude API (prototyp) → później wymienny na model lokalny; Whisper lokalnie
```

**Zasada: rdzeń formalny nie zależy od LLM, ale wartość asystenta w dużej mierze z niego wynika.** Proces, terminy, formularze, notatki strukturalne i ich deterministyczne zestawienia działają bez modelu, więc brak lub awaria LLM nie blokuje oceny (kryterium „potencjał wdrożeniowy”, 30%). LLM jest kluczowy dla klasyfikacji notatek, podsumowań, przygotowania do rozmów i całego modułu HR partnera.

### Stos (rekomendacja, do zmiany)
- Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic, `anthropic` (oficjalne SDK Claude).
- UI: Jinja2 + HTMX, bez kroku budowania frontu i z prostym wdrożeniem. Wydruk: HTML → PDF (WeasyPrint) z szablonów 1:1 z załącznikami rozporządzenia.
- Scheduler: APScheduler w procesie aplikacji (jeden kontener) albo cron + CLI `python -m app.scheduler run-daily`.
- Wdrożenie: `docker compose up` (app + db), profil `--profile ai` dokłada faster-whisper; klucz Claude API przez zmienną środowiskową `ANTHROPIC_API_KEY` (sekret, nigdy w repo).
- Licencje wyłącznie otwarte, zgodnie z wymogiem „niewymagające płatnych licencji”.

---

## 3. Kontrakty (krok 0 — robimy sekwencyjnie PRZED rozdzieleniem agentów)

To jedyna część, której agenci nie mogą zmieniać bez uzgodnienia. Dzięki niej merge sprowadza się do złożenia dwóch rozłącznych katalogów.

```
app/contracts/
  enums.py      SheetType(A,B,C), EmploymentType(URZEDNIK, PRACOWNIK),
                EvaluationState, Role(OCENIAJACY, OCENIANY, KADRY, ADMIN, ZARZADZAJACY),
                Level(ZNACZNIE_PONIZEJ..ZNACZNIE_POWYZEJ), Outcome(POZYTYWNA, NEGATYWNA)
  models.py     Employee, Position, OrgUnit, Absence,
                EvaluationSummary (id, employee_id, evaluator_id, sheet, state,
                                   criteria: list[CriterionRef], period_from, due_date),
                CriterionRef (code, name, mandatory: bool),
                Note (id, author_id, subject_id, evaluation_id|None, observed_on,
                      created_at, source: TEXT|VOICE, body,
                      strengths: list[str], improvements: list[str],
                      ratings: list[CriterionRating], version, supersedes_id),  ← § 5.1
                CriterionRating (criterion_code, value ∈ {1,3,5,7,9}),
                CriterionStats (criterion_code, n_ratings, distribution, median,
                                first_half_mean, second_half_mean,
                                last_rated_on),                               ← § 5.2
                Reminder (recipient_id, kind, subject_id, due, message, dedupe_key),
                DraftSuggestion (evaluation_id, field_id, text, citations: list[note_id],
                                 generator, created_at)
  ports.py      class CriteriaCatalog(Protocol)     # katalog z zał. 1 + kryteria obowiązkowe
                                                    # arkusza; czyta config/regulation/
                class EmployeeDirectory(Protocol)   # A implementuje, B używa
                class EvaluationReader(Protocol)    # A implementuje, B używa
                class ReminderSink(Protocol)        # A implementuje (notify), B używa
                class ReminderProvider(Protocol):   # obaj implementują; scheduler woła
                    def due(self, today: date) -> list[Reminder]
                class DraftProvider(Protocol)       # B implementuje, A wyświetla w formularzu
                class NotesReader(Protocol)         # B implementuje, A używa: link do teczki
                                                    # + CriterionStats do panelu w Części II
  fakes.py      proste implementacje in-memory wszystkich portów → każdy agent
                testuje swój moduł bez kodu drugiego
app/main.py     montuje routery core.* i assistant.*; rejestruje providery
                (napisany w kroku 0 i potem już nieruszany)
config/regulation/v2016/
                criteria.yaml (14 kryteriów z kodami, np. WSPOLPRACA, RZETELNOSC),
                sheets.yaml (kryteria obowiązkowe A/B/C), scale.yaml (1/3/5/7/9 + przedziały)
seed/           fikcyjny urząd „Generalna Dyrekcja Przekładów i Przykładów”
                (osoby z przykładowych arkuszy), 20–30 pracowników, historia ocen
tests/golden/   oczekiwane wyniki z 13 przykładowych arkuszy + przykłady
                z „liczenie terminów”
```

Stany oceny (`EvaluationState`), zgodne z BPMN i use case'ami:

```
CYCLE_OPEN ─(oceniający: kryteria+termin, rozmowa)→ CRITERIA_CONFIRMED
  ─(oceniany potwierdza)→ OBSERVATION            ← tu żyją notatki
  ─(oceniający: rozmowa oceniająca)→ INTERVIEW_HELD
  ─(oceniający: zatwierdza ocenę)→ AWAITING_ACK
  ─(oceniany potwierdza | „fikcja zapoznania”)→ ACKNOWLEDGED
  ─(7 dni bez sprzeciwu)→ FINAL
  ACKNOWLEDGED ─(sprzeciw)→ OBJECTION ─(uwzgl.: zmiana)→ FINAL
                                       ─(uwzgl.: ponownie)→ INTERVIEW_HELD
                                       ─(nieuwzgl.)→ FINAL
FINAL → automatycznie tworzy kolejny cykl (CYCLE_OPEN)
```

Zmiana terminu (nieobecność, zmiana oceniającego, wniosek ocenianego) nie zmienia stanu. To zdarzenie `DueDateChanged` z powodem i podstawą prawną, które wysyła powiadomienie (§ 8).

---

## 4. Podział na dwóch agentów

### Agent A — „Rdzeń procesu i formularze” (`app/core/`)
Całkowicie deterministyczny, bez zależności od AI.

1. `core/rules/calendar_pl.py`: święta, dni robocze, `add_months()` z obcięciem, przesunięcie końca terminu, scalanie nieobecności.
2. `core/rules/deadlines.py`: wszystkie terminy z tabeli 1.3. Funkcje czyste: `(historia, nieobecności, zdarzenia) → terminy` z uzasadnieniem w postaci podstawy prawnej.
3. `core/rules/scoring.py`: średnia na `Fraction`, poziom, wynik, reguła „jedna jedynka”, obligatoryjny stopień.
4. `core/forms/definitions/{A,B,C}.v2016.yaml` i `engine.py`: pola, źródła autouzupełnienia, reguły edytowalności (stan × rola), walidacje blokujące zatwierdzenie. W Części II obok matrycy ocen cząstkowych panel „Twoje obserwacje” zasilany z `NotesReader` (tylko do wglądu, bez wypełniania matrycy) i ostrzeżenie o rozbieżności (§ 5.2).
5. `core/workflow/`: maszyna stanów, potwierdzenia, fikcja zapoznania, korekta admina z audytem, odwołanie i ponowne sporządzenie.
6. `core/forms/render/`: widok HTML i PDF zgodny z wzorem z rozporządzenia; Część III drukowana tylko, gdy dotyczy (przypis 16).
7. `core/hr_data/`: CRUD pracowników, podległość, zastępstwa, nieobecności, import CSV (żeby każdy urząd mógł zacząć od eksportu z systemu kadrowego), wprowadzanie ocen historycznych.
8. `core/reminders/process_rules.py` jako `ReminderProvider`: kryteria (T−14, T−7, T−1), termin oceny (T−60, −30, −14, −7, −1), po terminie codziennie + eskalacja do kadr, obligatoryjny stopień, termin na sprzeciw. Harmonogram w `config/reminders.yaml`.
9. `core/notify/`: outbox, kanały in-app, e-mail (SMTP) i plik `.ics` z zaproszeniem na rozmowę; deduplikacja po `dedupe_key`.
10. Testy: golden z 13 arkuszy, przykłady terminów, property-based (Hypothesis) dla scoringu i dat.

### Agent B — „Teczka, przypomnienia o notatkach, AI” (`app/assistant/`)

1. `assistant/notes/`: notatki strukturalne (opis, zalety, obszary do poprawy, opcjonalne suwaki per kryterium) i głosowe; zestawienia deterministyczne `CriterionStats`; oś czasu per pracownik z filtrami (cykl, zalety/obszary, kryterium z suwaka), wyszukiwanie. **Edycja tworzy nową wersję** (nic nie znika po cichu, co chroni obiektywność). Szczegóły w § 5.
2. `assistant/stt/`: faster-whisper lokalnie. Nagranie → transkrypt do akceptacji → **audio kasowane po zatwierdzeniu** transkryptu.
3. `assistant/nudges/` jako `ReminderProvider` (szczegóły w § 5).
4. `assistant/privacy/`: pseudonimizator i detektor danych wrażliwych (§ 6.3).
5. `assistant/llm/`: interfejs `LLMClient` z implementacją `ClaudeClient` (oficjalne SDK `anthropic`) i konfiguracją per zadanie w `config/llm.yaml`; wyłączone zadanie = funkcja ukryta w UI. Do tego logowanie promptów po pseudonimizacji, limity, timeouty, prompty w `prompts/` i zestaw porównawczy `evals/` (§ 6.4).
6. `assistant/summarize/`: podsumowanie z cytatami, walidator, `DraftProvider` dla pól „Uzasadnienie” i „Wnioski IPRZ”.
7. `assistant/prep/`: przygotowanie do rozmowy rozpoczynającej i oceniającej. Obowiązkowe tematy z § 5 i § 10 jako checklista deterministyczna, a pytania i podpowiedzi z LLM oparte na notatkach.
8. `assistant/hr_partner/`: codzienne wsparcie na żądanie, sygnały, playbooki i twarde granice odpowiedzialności (§ 7).
9. Testy: walidator cytowań, pseudonimizacja (round-trip), detektor wrażliwych, reguły nudge. LLM mockowany.

### Zasady pracy równoległej
- Agent A pisze tylko w `app/core/`, `templates/core/`, `config/reminders.yaml`; agent B tylko w `app/assistant/`, `templates/assistant/`, `config/llm.yaml`, `config/nudges.yaml`, `prompts/`, `evals/`. `app/contracts/`, `config/regulation/` i `app/main.py` są zamrożone.
- Każdy moduł ma własne tabele i migracje (osobne gałęzie Alembic albo prefiksy tabel `core_*`, `asst_*`).
- Każdy agent testuje się na `contracts/fakes.py`. Prawdziwe implementacje każdy moduł sam wstawia do kontenera w swoim `register(c)` (`app/core/__init__.py`, `app/assistant/__init__.py`), więc przy integracji nie zmienia się ani `main.py`, ani `container.py`. Szczegóły: `docs/PRACA_ROWNOLEGLA.md`.
- Najlepiej w osobnych worktree/gałęziach: `feat/core`, `feat/assistant`.
- Integracja (po merge'u): test end-to-end całego procesu na seedzie, od nowego pracownika do potwierdzenia oceny i wniosku o stopień. Ten sam scenariusz pokazujemy na demo (pkt 6 opisu wyzwania).

---

## 5. Teczka: notatki strukturalne

### 5.1 Struktura notatki pisemnej

Układ jest stały, ale wymagane minimum jest małe, żeby notatka zajmowała 30 sekund, a nie 5 minut.

| Pole | Wymagane | Opis |
|---|---|---|
| Kogo dotyczy | tak | podwładny; notatka wiąże się z bieżącym cyklem oceny |
| Data zdarzenia | tak (domyślnie dziś) | kiedy to się wydarzyło, nie kiedy zapisano; potrzebne do rozkładu w czasie |
| Opis sytuacji | co najmniej jedno z trzech pól tekstowych | co się wydarzyło, fakty |
| Zalety / co poszło dobrze | | lista krótkich punktów, bez przypisywania kryteriów |
| Obszary do poprawy | | lista krótkich punktów, bez przypisywania kryteriów |
| Suwaki per kryterium | nie | zob. niżej |

**Suwaki ocen (opcjonalne):**
- **Lista kryteriów** to kryteria bieżącej oceny: obowiązkowe z arkusza i wybrane dodatkowe. Przed ustaleniem kryteriów (stan `CYCLE_OPEN`) pokazujemy tylko obowiązkowe. Rozwijana sekcja „inne kryteria” pokazuje resztę katalogu z zał. 1; przy okazji pomaga to wybrać kryteria dodatkowe na następny cykl.
- **Skala identyczna jak w arkuszu:** 5 pozycji 1/3/5/7/9 z etykietami od „znacznie poniżej” do „znacznie powyżej oczekiwań”, bez wartości pośrednich. Dzięki temu dane z notatek da się wprost porównać z oceną.
- **Domyślnie suwak jest nieustawiony („—”), a nie na 5.** Nieruszony suwak oznacza brak danych, a nie ocenę „na poziomie oczekiwań”. Jest przycisk „wyczyść”.
- **Ocenia się sytuację, nie całego pracownika.** Nad suwakami jest pytanie „Jak w tej sytuacji wypadło…?”. To ogranicza efekt aureoli i przenoszenie jednego wrażenia na wszystkie kryteria.

**Notatka głosowa:** transkrypt trafia do pola „Opis sytuacji”. Przełożony może od razu rozbić go na zalety i obszary, ręcznie albo z podpowiedzią LLM (§ 5.3). Suwaki zawsze ustawia człowiek.

**Zmiana kryteriów w trakcie cyklu** (§ 9 rozporządzenia): oceny suwakami dla kryteriów, które wypadły z oceny, zostają w teczce z oznaczeniem „poza kryteriami bieżącej oceny”.

### 5.2 Zestawienia deterministyczne (bez LLM)

Z suwaków liczymy dla każdego kryterium (`CriterionStats`):
- liczbę ocen, rozkład (ile razy 1/3/5/7/9) i medianę;
- trend, czyli średnią z pierwszej i drugiej połowy okresu oceny;
- datę ostatniej oceny suwakiem;
- pokrycie, czyli kryteria bez żadnej oceny suwakiem.

Zalety i obszary do poprawy nie mają kryteriów, więc bez LLM pokazujemy je chronologicznie. Przypisanie ich do kryteriów robi LLM na etapie podsumowania (§ 5.3).

Mediana jest główną miarą, bo skala jest porządkowa, a mediana jest odporna na jedną skrajną sytuację. Średnią pokazujemy pomocniczo, bo tak liczy arkusz.

Wykorzystanie:
1. **Panel „Twoje obserwacje” w Części II formularza**, obok matrycy ocen cząstkowych. Pokazuje rozkład ocen z suwaków, a kliknięcie otwiera notatki źródłowe. **Matryca nie jest wypełniana automatycznie.** Gdyby system wpisywał medianę, przełożony najczęściej by ją tylko zatwierdzał. Ocena przestałaby być jego decyzją, co jest słabym punktem przy sprzeciwie.
2. **Ostrzeżenie o rozbieżności:** pojawia się, gdy przy co najmniej 3 obserwacjach ocena cząstkowa różni się od mediany o 2 lub więcej stopnie skali (np. mediana 7, wpisane 3). Komunikat: „Twoje notatki wskazują wyżej. Jeśli ocena jest świadoma, warto to uzasadnić”. Ostrzeżenie nie blokuje zatwierdzenia.
3. **Szkielet uzasadnienia i IPRZ:** zalety i obszary chronologicznie, do przeniesienia do pól formularza; z LLM pogrupowane według kryteriów (§ 6). Kryteria z oceną cząstkową ≤ 3 wskazują pozycje z katalogu działań rozwojowych.
4. **Przypomnienia** (§ 5.4): rozkład notatek w czasie liczymy z dat zdarzeń, a pokrycie kryteriów z suwaków. Bez LLM pokrycie jest więc zaniżone, bo notatki bez suwaków się do niego nie liczą. Z LLM doliczamy też przypisania z treści.

### 5.3 LLM nad notatkami
- **Przy zapisie (opcjonalnie):** model proponuje rozbicie opisu lub transkryptu na zalety i obszary do poprawy. Przełożony przyjmuje albo poprawia propozycję. Nic więcej nie musi robić.
- **Przypisanie do kryteriów robi LLM w tle**, bez udziału przełożonego. Wynik jest zapisywany jako podpowiedź (`criteria_hint`, z wersją modelu) i służy do przypomnień o pokryciu oraz do podsumowania. Nie jest częścią notatki.
- **Przy podsumowaniu na koniec cyklu** (§ 6) przełożony widzi punkty pogrupowane według kryteriów z odnośnikami do notatek i może przenieść punkt do innego kryterium. Weryfikacja przypisań odbywa się więc raz, przy ocenie, a nie przy każdej notatce.
- **LLM nie ustawia suwaków** ani nie proponuje ich wartości.
- **Bez LLM** wszystko działa poza grupowaniem punktów według kryteriów.

### 5.4 Przypomnienia o notatkach (nudges)

Reguły są deterministyczne, konfigurowalne w `config/nudges.yaml`, a wszystkie trafiają do wspólnego outboxu i deduplikacji z core.

| Wyzwalacz | Przykładowy komunikat | Domyślnie |
|---|---|---|
| Brak notatki o osobie X od N dni | „Od 47 dni nie zapisałeś obserwacji o pracy Anny K.” | N = 45 (kwartał/2) |
| Kryterium bez pokrycia | „Brak obserwacji dot. *Współpracy* u 3 osób” | sprawdzane co miesiąc |
| Skupienie w czasie (recency bias) | „80% notatek o Janie pochodzi z ostatnich 3 miesięcy” | 90 dni przed terminem |
| Przed rozmową oceniającą | „Za 30 dni ocena Jana: 6 notatek, 2 kryteria bez obserwacji” | T−60, T−30 |
| Długo bez pozytywnej notatki | „Ostatnia pozytywna obserwacja o Ewie: 5 mies. temu. Może warto docenić?” | 120 dni |
| Powrót z długiej nieobecności / zmiana stanowiska | „Ewa wróciła po 3 mies. Może krótka rozmowa?” | zdarzenie z hr_data |

UX:
- **Jeden tygodniowy digest per przełożony** zamiast spamu per pracownik, opcja „odłóż o 2 tygodnie”.
- Notatkę da się dodać prosto z przypomnienia, łącznie z nagraniem głosowym jednym kliknięciem.
- Bez gamifikacji „liczby notatek”, bo to zachęca do sztucznego produkowania obserwacji.

**Dostęp do historii:** przełożony widzi wszystkie swoje notatki o podwładnym ze wszystkich cykli. Do decyzji (zob. § 9):
- czy po zmianie oceniającego (§ 9 ust. 3) notatki przechodzą na następcę,
- jak długo je przechowujemy.

---

## 6. Podsumowanie pracy przez LLM — jak to zrobić bezpiecznie

### 6.1 Rola AI: asystent dokumentujący, nie oceniający
- **LLM nie proponuje ocen cząstkowych ani wyniku.** Ocenę dokonuje oceniający (§ 2 rozporządzenia), a punkty wpisuje człowiek.
- LLM robi trzy rzeczy:
  1. **Zestawienie dowodów per kryterium:** co wynika z notatek, z odnośnikami do konkretnych notatek, plus luki („brak obserwacji”).
  2. **Projekt tekstu** pól „Uzasadnienie” i „Wnioski IPRZ” *po tym*, jak oceniający wpisał punkty, spójny z jego decyzją.
  3. **Kontrolę spójności tekstu.** Rozbieżności liczbowe między suwakami a oceną wykrywa już deterministycznie panel z § 5.2. LLM dodatkowo sprawdza, czy projekt uzasadnienia nie przeczy notatkom i wpisanym ocenom. To ostrzeżenie, nie korekta.
- AI Act: systemy oceniające wyniki pracowników są w **załączniku III pkt 4 (wysokie ryzyko)**. Projektujemy więc tak, jakby obowiązki wysokiego ryzyka miały zastosowanie: nadzór człowieka, logi, przejrzystość wobec ocenianego, dokumentacja. Wyjątek z art. 6 ust. 3 (zadanie przygotowawcze) jest wątpliwy, bo podsumowanie pracy konkretnej osoby to profilowanie. Terminy stosowania tych przepisów były przesuwane (pakiet Digital Omnibus), więc **przed prezentacją sprawdźcie aktualny stan**.
- **Zakaz z art. 5 ust. 1 lit. f AI Act:** rozpoznawanie emocji w miejscu pracy. Z nagrań głosowych robimy **wyłącznie transkrypcję**, bez analizy tonu i emocji. Analiza dotyczy zresztą głosu przełożonego, a nie pracownika, ale to też trzeba jasno zapisać.

### 6.2 Pipeline

```
notatki z cyklu (tylko autor = oceniający, tylko dany oceniany)
  │
  ├─1. detektor danych wrażliwych (deterministyczny: słowniki + regex + NER)
  │     zdrowie/diagnozy, ciąża, rodzina, związki zawodowe, religia, poglądy,
  │     orientacja, pochodzenie → notatka WYKLUCZONA z wejścia LLM
  │     + ostrzeżenie dla przełożonego (art. 9 RODO, art. 18³a KP)
  │
  ├─2. pseudonimizacja lokalna (zawsze, nawet przy modelu lokalnym)
  │     • znane osoby z EmployeeDirectory → [OSOBA_1], [OSOBA_2] (deterministycznie)
  │     • NER dla nieznanych nazwisk, regex: PESEL, tel., e-mail, sygnatury spraw
  │     • mapa tokenów zostaje w pamięci procesu, nigdy nie jest wysyłana
  │
  ├─3. map: każdy punkt (opis / zaleta / obszar) → kryteria (JSON schema);
  │     użyj criteria_hint z § 5.3, jeśli jest; suwaki idą jako kontekst,
  │     ale model nie zwraca liczb (24 mies. notatek nie musi mieścić się
  │     w jednym kontekście)
  │
  ├─4. reduce: per kryterium → lista twierdzeń {claim, note_ids[]}
  │
  ├─5. walidator (deterministyczny, odrzuca zamiast „naprawiać”):
  │     • każde twierdzenie ma ≥1 cytat, każdy note_id istnieje i należy do cyklu
  │     • liczby, daty i tokeny [OSOBA_n] w twierdzeniu występują w cytowanych notatkach
  │     • brak liczb punktowych, słów „ocena pozytywna/negatywna”, brak diagnoz
  │     • limit długości; niezaliczone twierdzenie → usunięte i oznaczone
  │
  ├─6. de-pseudonimizacja lokalnie
  │
  └─7. UI: tekst obok źródeł (klik w cytat → notatka), każdy akapit
        „przyjmij / edytuj / odrzuć”; pole oznaczone „projekt AI” do edycji;
        zapis: co wygenerował model vs. co zatwierdził człowiek (audit)
```

Dodatkowo:
- Notatki traktujemy jako **dane, nie instrukcje** (ochrona przed prompt injection, np. przy wklejonych mailach).
- Prompt systemowy zawiera katalog kryteriów z zał. 1 i definicje poziomów.
- Wymuszony format odpowiedzi (structured outputs), prompty wersjonowane w repo. Parametru `temperature` nie ustawiamy, bo aktualne modele Claude go nie przyjmują. Powtarzalność zapewniają więc walidator i zapis wyniku, a nie deterministyczne próbkowanie.
- Deterministyczny szkielet IPRZ: kryteria z oceną ≤ 3 → pozycje z katalogu działań rozwojowych (tabela edytowalna przez kadry). LLM tylko je „ubiera” w tekst, więc działa to także bez LLM.

### 6.3 Gdzie liczyć — odpowiedź na obawy pracowników

**Rekomendacja: model działa w infrastrukturze publicznej, a pseudonimizacja jest dodatkową warstwą ochrony, a nie głównym zabezpieczeniem.**

Dlaczego nie oprzeć się na samej anonimizacji:
- Imiona i nazwiska podmienimy niezawodnie, bo znamy je z bazy kadrowej. Jednak **treść notatki o pracy sama identyfikuje osobę** („jako jedyna w wydziale prowadziła przetarg na system X”). Takie dane są spseudonimizowane, a nie zanonimizowane (motyw 26 RODO), więc **dalej są danymi osobowymi**: transfer poza EOG i umowa powierzenia nadal obowiązują.
- Dostawcy z USA podlegają CLOUD Act także w regionach UE, a to dokładnie ta obawa, którą zgłaszają pracownicy.

**Stan na prototyp: Claude API (§ 6.4), wyłącznie z danymi fikcyjnymi.** Trzeba uczciwie zapisać, co to oznacza dla danych produkcyjnych (do potwierdzenia w aktualnej dokumentacji i umowie z Anthropic):
- **Lokalizacja przetwarzania.** API Anthropic pozwala wybrać miejsce przetwarzania parametrem `inference_geo`, ale dostępne są tylko `"global"` (domyślnie) i `"us"`. **Nie ma opcji „tylko UE”**, więc dane mogą być przetwarzane poza Europą, a to dokładnie obawa pracowników.
- **Claude w chmurach z regionami UE.** Claude jest dostępny także przez Google Cloud Vertex AI i Amazon Bedrock, gdzie wybiera się region chmury, również europejski. Dostępność danego modelu w regionie trzeba sprawdzić. Dostawcy są jednak firmami z USA, więc pytanie o CLOUD Act zostaje. Zmiana dostawcy to w SDK `anthropic` inna klasa klienta (`AnthropicVertex`, `AnthropicBedrockMantle`), bez zmian w interfejsie `LLMClient`.
- **Retencja danych.** Zero data retention jest dostępne tylko w ramach umowy z Anthropic i nie dla wszystkich modeli i funkcji. Np. modele Claude Fable wymagają 30-dniowej retencji, a message threads nie kwalifikują się do ZDR (dlatego ich nie używamy). Dla wybranego modelu trzeba to potwierdzić.
- **Wniosek:** Claude jest dobry do prototypu i demo. O użyciu z prawdziwymi danymi decydują KPRM i IOD. Interfejs `LLMClient` sprawia, że ta decyzja nie wymaga przepisywania aplikacji.

Warianty wdrożenia (konfiguracja w urzędzie, zob. § 6.4):

| Wariant | Uwagi |
|---|---|
| **0. Bez LLM** | rdzeń formalny, notatki strukturalne, zestawienia z § 5.2, przypomnienia, szkielety IPRZ z katalogu; HR partner wyłączony |
| **1. Lokalnie w urzędzie** | dla urzędów z własnym serwerem; podsumowania mogą liczyć się w nocy, ale codzienny HR partner wymaga szybkich odpowiedzi, czyli GPU |
| **2. Centralnie w infrastrukturze rządowej** | kierunek rekomendowany: jeden endpoint dla wszystkich urzędów, ekonomia skali GPU, dane w PL. **Do ustalenia z KPRM, co jest dostępne** |
| 3. Komercyjne API (np. Claude: bezpośrednio albo przez Vertex AI / Bedrock w regionie UE) | **wariant prototypu**; z danymi produkcyjnymi tylko po decyzji IOD: umowa powierzenia, ustalona retencja, pseudonimizacja obowiązkowa |

Pochodzenie wag modelu to nie to samo co miejsce przetwarzania danych. Otwarty model uruchomiony na serwerze rządowym niczego nie wysyła do swojego producenta. Warto to jasno komunikować pracownikom.

**Głos:** transkrypcja wyłącznie lokalnie (np. faster-whisper / whisper.cpp; silnik STT też za interfejsem, wymienny). Audio nigdy nie opuszcza serwera urzędu.

### 6.4 Warstwa LLM: na start Claude API, z możliwością podmiany

Na etapie prototypu używamy Claude API przez oficjalne SDK `anthropic`. Docelowy model i infrastruktura są jeszcze otwarte (dopytujemy KPRM), więc **logika domenowa nie zależy od Claude**. Zależy tylko od naszego interfejsu.

**Interfejs (w `assistant/llm/`):**

```python
class LLMClient(Protocol):
    def structured(self, task: str, system: str, user: str, schema: type[T]) -> T: ...
    def text(self, task: str, system: str, messages: list[Msg]) -> str: ...
    def stream(self, task: str, system: str, messages: list[Msg]) -> Iterator[str]: ...  # próba rozmowy
```

Implementacje:
- `ClaudeClient` teraz.
- `LocalClient` później (np. serwer modelu lokalnego), z tymi samymi sygnaturami.
- `NullClient`, gdy LLM jest wyłączony.

Moduły `notes`, `summarize`, `prep` i `hr_partner` znają tylko `LLMClient`.

**Konfiguracja per zadanie** (`config/llm.yaml`):

```yaml
llm:
  provider: anthropic            # później: local | none
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    refusal_fallback: true       # zob. niżej
  tasks:
    split_note:        { model: claude-opus-5-5, effort: low }
    classify_note:     { model: claude-opus-5-5, effort: low }
    rewrite_feedback:  { model: claude-opus-5-5, effort: medium }
    procedure_qa:      { model: claude-opus-5-5, effort: medium }
    conversation_prep: { model: claude-opus-5-5, effort: medium }
    roleplay:          { model: claude-opus-5-5, effort: medium }
    summarize_cycle:   { model: claude-opus-5-5, effort: high }
```

Zadanie usunięte z listy oznacza funkcję ukrytą w UI, a nie błąd. Na start wszędzie jest `claude-opus-5-5`. Tańszy model (np. `claude-haiku-5-5`) dla prostych zadań, takich jak `split_note` czy `classify_note`, wprowadzamy dopiero wtedy, gdy `evals/` pokaże, że jakość się utrzymuje.

**Jak `ClaudeClient` korzysta z API:**
- **Structured outputs:** `client.messages.parse(..., output_format=<model Pydantic>)` zwraca zwalidowany obiekt w `response.parsed_output`. Nasz walidator cytowań z § 6.2 i tak działa niezależnie, bo sprawdza treść, a nie tylko format.
- **Prompt caching:** stały prompt systemowy (zasady, katalog 14 kryteriów z zał. 1, skala, przykłady z Poradnika) idzie na początek z `cache_control`, a zmienne dane (notatki, pytanie) po nim. W prompcie systemowym nie może być niczego zmiennego, np. daty czy ID. Trafienia w cache sprawdzamy przez `usage.cache_read_input_tokens`.
- **Effort i thinking:** na `claude-opus-5-5` myślenie jest zawsze włączone, a głębokość ustawia `output_config.effort` (domyślnie `medium`), więc podajemy go jawnie z configu. Nie wysyłamy `thinking: disabled` ani `temperature`, bo oba zwracają błąd 400.
- **Streaming** (`messages.stream(...)`) dla próby rozmowy i przygotowania do rozmów, żeby tekst pojawiał się na bieżąco.
- **Odmowy modelu:** zawsze sprawdzamy `stop_reason` przed odczytem treści. Przy `"refusal"` logujemy `stop_details.category` i pokazujemy komunikat „asystent nie może pomóc w tej sprawie, skontaktuj się z kadrami”. Dodatkowo włączamy serwerowy fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`), który przy odmowie automatycznie ponawia zapytanie na innym modelu. Przy implementacji trzeba sprawdzić w dokumentacji SDK, jak łączy się to z `messages.parse`.
- **Błędy:** łapiemy konkretne wyjątki SDK od najbardziej szczegółowego (`RateLimitError`, potem `APIStatusError`, potem `APIConnectionError`), a nie jeden ogólny. SDK sam ponawia 429 i 5xx (domyślnie 2 razy).
- **Celowo nie używamy funkcji, które przywiązałyby nas do Claude:** wbudowanych cytowań (mamy własne ID notatek), message threads, Managed Agents ani narzędzi serwerowych. Dzięki temu `LocalClient` będzie miał co zaimplementować w kilka dni, a nie tygodni.

**Co zostaje niezależne od dostawcy:**
- pseudonimizacja i detektor danych wrażliwych przed każdym wywołaniem;
- prompty w plikach `prompts/<zadanie>/v1.md`, wersjonowane i logowane z nazwą modelu;
- walidatory wyników po naszej stronie;
- `evals/`: notatki z oczekiwanymi kryteriami (do wyciągnięcia z uzasadnień w 13 przykładowych arkuszach), scenariusze rozmów i pytania o procedury z oczekiwanym paragrafem. Ten sam zestaw posłuży później do porównania Claude z modelem lokalnym (Bielik, PLLuM i inne).

---

## 7. Wirtualny HR partner — jak to mogłoby działać

**Jaki problem rozwiązujemy.** Kierownikami w służbie cywilnej często zostają eksperci merytoryczni bez przygotowania menedżerskiego, a w małych urzędach nie ma nikogo, kogo można zapytać „jak to rozegrać?”. Asystent nie zastępuje kompetencji międzyludzkich. Zastępuje brak osoby, z którą można się przygotować.

Zasady:
- **Asystent działa przed rozmową i po niej, nigdy zamiast niej.**
- **Reguły wykrywają, playbook podpowiada, LLM formułuje i prowadzi ćwiczenie.**
- **Nie budujemy „predyktora wypalenia”.** Byłby nieweryfikowalny, wysokiego ryzyka i łatwo przy nim o konflikt z art. 9 RODO i z zakazem rozpoznawania emocji.

### 7.1 Codzienne wsparcie na żądanie (wymaga LLM)

| Scenariusz | Jak działa | Dane osobowe |
|---|---|---|
| **Przygotowanie do trudnej rozmowy** | kierownik opisuje sytuację; dostaje cel rozmowy, zdanie otwierające w modelu FUKO, prawdopodobne reakcje i odpowiedzi, czego nie mówić, granice (np. nie pytać o zdrowie) | niepotrzebne, sytuację można opisać ogólnie |
| **Próba rozmowy** | LLM gra pracownika według krótkiej „karty postaci” (cel, opór, typowe zdania), limit kilkunastu wymian, na końcu krótka informacja zwrotna dla kierownika | niepotrzebne |
| **Notatka → informacja zwrotna** | przeredagowanie oceny („nie da się na nim polegać”) w opis zachowania i skutków, gotowy do powiedzenia; uczy pisać fakty zamiast opinii | treść notatki po pseudonimizacji |
| **Pytania o procedury** | odpowiedź oparta na fragmentach ustawy, rozporządzenia, Poradnika i Standardów ZZL, zawsze z paragrafem; bez źródła odpowiedź „zapytaj kadry” | niepotrzebne |
| **Domknięcie po rozmowie** | kierownik dyktuje, jak poszło; powstaje notatka (§ 5.1), lista ustaleń i przypomnienie o sprawdzeniu ich za X tygodni | jak w notatkach |

Większość codziennej pomocy nie dotyka danych konkretnych pracowników. To dobry argument dla sceptycznych pracowników.

### 7.2 Sygnały (deterministyczne, każdy z wyjaśnieniem „dlaczego”)

Sygnały formułujemy jako **pytanie do kierownika, a nie diagnozę o pracowniku**. Zamiast „Anna jest przeciążona” system pyta: „Anna od 3 miesięcy zastępuje dwie osoby. Kiedy ostatnio rozmawialiście o jej obciążeniu?”.

| Sygnał | Dane | Działanie z playbooka |
|---|---|---|
| Przeciążenie przez zastępstwa | liczba i długość zastępstw pełnionych przez osobę (hr_data) | rozważ podział zadań, rozmowa o priorytetach |
| Zmiana zakresu obowiązków | zmiana stanowiska/opisu w trakcie cyklu | § 9: ponowne kryteria w 30 dni + rozmowa wdrażająca |
| Długo bez informacji zwrotnej | brak notatek / rozmów cyklicznych | Standardy ZZL: informacja cykliczna (kwartał) |
| Brak docenienia | brak pozytywnych notatek od N mies. | kultura doceniania: konkretna pochwała (FUKO/SBI) |
| Trend tonu notatek przełożonego | proporcja negatywnych notatek rośnie | rozmowa wspierająca przed eskalacją |
| IPRZ bez realizacji | działania rozwojowe z poprzedniej oceny bez śladu w notatkach | przypomnienie o planie rozwoju |
| Powrót po długiej nieobecności | koniec nieobecności > 1 mies. | rozmowa powitalna, aktualizacja celów |

**Celowo NIE używamy przyczyn nieobecności** (L4 to dane o zdrowiu). Liczymy najwyżej łączny czas nieobecności, i to wyłącznie do terminów.

### 7.3 Wsparcie rozmów w procesie oceny
- **Rozmowa rozpoczynająca:** checklista § 5 (obowiązki, kryteria, oczekiwania, cele) + podpowiedź kryteriów dodatkowych na podstawie opisu stanowiska (LLM lub mapowanie słów kluczowych → kryteria) + szablon celów SMART.
- **Rozmowa oceniająca:** checklista § 10 + zestawienie dowodów z § 6 + pytania otwarte + „trudne sytuacje” (ocena negatywna, obrona przed sprzeciwem) z playbooka. Playbook to statyczna baza wiedzy: Poradnik, Standardy ZZL, modele FUKO/SBI.
- **Bieżąca informacja zwrotna:** szablon FUKO wypełniany z notatki („Zamień tę notatkę w informację zwrotną”).

### 7.4 Statystyki dla kadr i kierownictwa
Terminowość, rozkład poziomów per komórka, odsetek ocen negatywnych, odsetek pól IPRZ do szkoleń. **Tylko agregaty, z progiem minimalnej liczebności grupy** (np. ≥ 5), żeby nie dało się zidentyfikować osób.

### 7.5 Granice odpowiedzialności (zakodowane na sztywno, nie w prompcie)
Mobbing i dyskryminacja, kryzys psychiczny lub zagrożenie życia, sprawy dyscyplinarne i spory prawne, dane o zdrowiu: asystent nie doradza. Wykrycie takiego tematu (słowniki + klasyfikator) pokazuje stały komunikat z kontaktem do kadr, IOD lub wsparcia psychologicznego, jeśli urząd je zapewnia. Lista tematów i kontakty są w configu urzędu.

### 7.6 Adopcja
Kierownik nie będzie codziennie otwierał kolejnej aplikacji, więc „na co dzień” musi przychodzić do niego:
- przez cotygodniowe podsumowanie przypomnień o notatkach (§ 5.4), które jest naturalnym punktem wejścia;
- przez kalendarz: przed spotkaniem 1:1 pojawia się karta przygotowania (integracja z `.ics` lub pocztą);
- przez notatkę głosową w 20 sekund z telefonu.

Na demo pokazujemy 2–3 dopracowane scenariusze (przygotowanie z próbą rozmowy, notatka → informacja zwrotna, pytanie o procedurę ze źródłem) zamiast ogólnego czatu.

---

## 8. Bezpieczeństwo i RODO (wspólne)
- Role i uprawnienia: oceniający widzi swoich podwładnych; oceniany widzi swój arkusz; kadry widzą arkusze, ale nie notatki; zarządzający widzi agregaty.
- Notatki są prywatne dla autora. **Uwaga: zgodnie z art. 15 RODO oceniany może zażądać dostępu do danych o sobie, także do notatek.** Należy to komunikować przełożonym („pisz fakty, nie opinie”), co zresztą zgadza się z Poradnikiem.
- Retencja notatek: do końca cyklu + 7 dni (sprzeciw) + 14 dni + 14 dni (sąd pracy) albo do prawomocnego zakończenia sporu, potem automatyczne usunięcie. Wartości w configu, do zatwierdzenia przez IOD.
- Pełny audyt: zmiany stanów, korekty admina, wywołania LLM (wejście po pseudonimizacji, wyjście, wersja promptu i modelu).
- Podpisy: na start „potwierdzenie w systemie” (login + znacznik czasu, tak jak `<podpisano elektronicznie>` w przykładach); docelowo integracja z EZD RP i podpisem kwalifikowanym/zaufanym.

---

## 9. Decyzje / pytania do mentorów KPRM
1. Zaokrąglanie wyświetlanej średniej (przykłady pokazują raz obcięcie, raz 2 miejsca).
2. Czy notatki przechodzą na nowego oceniającego przy zmianie przełożonego?
3. Czy „fikcja zapoznania” wymaga potwierdzenia przez kadry, czy wystarczy oceniający?
4. Kto jest adresatem sprzeciwu dla arkusza A (pole edytowalne): preset per urząd?
5. Czy jest centralna infrastruktura (COI/KPRM), na której mógłby działać współdzielony model? Jakie modele i dostawcy są dopuszczalni (polskie, otwarte, komercyjne w UE)?
6. Co kadry rozumieją przez „asystenta na co dzień”? Hipoteza: głównie odciążenie ich z powtarzalnych pytań o procedury i przygotowanie kierowników do trudnych rozmów.
7. Czy oceny suwakami w notatkach (§ 5.1) mogą być widoczne dla kadr, czy zostają wyłącznie u autora?
