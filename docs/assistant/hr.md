# Asystent HR (moduł B) — `/asystent/hr`

ARCHITEKTURA § 7. Zasada: asystent działa przed rozmową i po niej, nigdy zamiast niej.

| Funkcja | Strona | Bez LLM | Z LLM (zadanie w `config/llm.yaml`) |
|---|---|---|---|
| Sygnały w zespole | `/asystent/hr` | ✔ (deterministyczne) | — |
| Przygotowanie rozmowy | `/asystent/hr/przygotowanie` | checklista z § 5 / § 10 rozporządzenia | plan: cel, otwarcie FUKO, pytania, reakcje, czego unikać, karta postaci (`conversation_prep`) |
| Próba rozmowy | `/asystent/hr/proba/…` | — | LLM gra pracownika, strumieniowo, limit wypowiedzi, informacja zwrotna (`roleplay`, `roleplay_feedback`) |
| Notatka → FUKO | `/asystent/hr/fuko?notatka=ID` | — | fakty, uczucia, konsekwencje, oczekiwania, tekst do powiedzenia, opinie → fakty (`rewrite_feedback`) |
| Pytania o procedury | `/asystent/hr/procedury` | wyszukiwanie fragmentów przepisów | odpowiedź tylko z fragmentów, z paragrafem; bez poprawnego źródła — „zapytaj kadry” (`procedure_qa`) |

## Granice (§ 7.5) — `app/assistant/hr/hr.yaml`, sprawdzane w kodzie przed LLM

Mobbing/dyskryminacja, kryzys i zagrożenie życia (dodatkowo 112 i 116 123), sprawy dyscyplinarne i spory prawne, zdrowie (wzorce z detektora danych wrażliwych). Trafienie = stały komunikat z kontaktem do Wydziału Kadr (osoby z rolą `KADRY`), IOD i wsparcia. Model nie dostaje tej treści.

## Sygnały (§ 7.2) — pytania do kierownika, nie diagnozy

Długo bez informacji zwrotnej, brak docenienia, trend tonu notatek (ostatnie 3 wyłącznie krytyczne, wcześniej mieszane), powrót po nieobecności (bez przyczyny). Każdy ma „dlaczego” i podpowiedź z playbooka. Zastępstw i zmian zakresu obowiązków jeszcze nie liczymy — nie ma ich w danych z kontraktu.

## Baza wiedzy — `docs/assistant/wiedza/*.md`

Wygenerowana z `context/` skryptem `python -m app.assistant.hr.knowledge_build` (wymaga `pypdf`): rozporządzenie po paragrafach + zał. 1, wyciąg z ustawy po artykułach (81, 82, 83, 89), Poradnik KPRM po stronach. **Standardy ZZL pominięte** — PDF ma uszkodzone kodowanie fontów, tekst nie daje się wyciągnąć. Ekstrakcja PDF zostawia drobne artefakty (np. „wybi erane”). Wyszukiwanie: BM25 na rdzeniach słów (6 pierwszych liter).

## Prywatność

Opisy sytuacji, wypowiedzi w próbie rozmowy i notatki przechodzą granice, detektor danych wrażliwych (notatki i FUKO) i pseudonimizację. Karta postaci nie zawiera imion. Próby rozmów (`asst_roleplays`) widzi tylko kierownik, który je utworzył; w bazie trzymamy tekst wysłany do LLM i osobno tekst do wyświetlenia.
