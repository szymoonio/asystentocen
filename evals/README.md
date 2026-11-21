# Evale asystenta (moduł B)

Zestawy wołają **prawdziwe wejścia aplikacji** (te same funkcje co UI: `classify_items`, `split_note`, `qa.answer`, `prep.prepare` + `roleplay.reply/finish`, `AssistantDraftProvider.generate`) na czystej bazie z seedu i oceniają wynik regułami.

| Zestaw | Zadanie LLM | Przypadki | Ocena |
|---|---|---|---|
| `boundaries` | — (darmowy) | 11 tematów do zablokowania + 7 zwykłych spraw | dokładny temat albo brak blokady |
| `retrieval` | — (darmowy) | 11 pytań o procedury | właściwy przepis w top 8 wyszukiwarki |
| `classify` | `classify_note` | 23 fragmenty z uzasadnień w `context/5.` (etykiety oceniających) + 3 ujemne | trafienie ≥ 1 kryterium oceniającego; ujemne: pusto |
| `split` | `split_note` | 8 opisów (seed + zespół) | właściwe listy niepuste, punkty ugruntowane w tekście, ≤ 25 słów |
| `procedure_qa` | `procedure_qa` | 11 pytań z oczekiwanym przepisem i faktem + 3 spoza bazy | cytat z właściwego przepisu i fakt w odpowiedzi; spoza bazy: odesłanie do kadr |
| `conversations` | `conversation_prep`, `roleplay`, `roleplay_feedback` | 3 scenariusze | plan kompletny, otwarcie bez „zawsze/nigdy”, karta bez imion, odpowiedzi „pracownika” krótkie i w roli, bez danych wrażliwych |
| `summarize` | `summarize_cycle` | cykl Grzegorza z seedu | są akapity obu pól, cytaty z cyklu, walidator odrzuca ≤ 50% |

Pochodzenie etykiet jest opisane w nagłówku każdego pliku `cases/*.yaml` i w polu `source`.

## Uruchamianie

```bash
python -m evals.run                     # offline: boundaries + retrieval (bez API)
python -m evals.run --mode oracle       # odpowiedzi wzorcowe: harness musi dać 100%
python -m evals.run --mode null         # puste odpowiedzi: przechodzą tylko przypadki ujemne
python -m evals.run --mode live --suites classify,procedure_qa --reps 3   # Claude API — płatne
```

- `live` pokazuje liczbę wywołań i pyta o zgodę (`--yes` pomija pytanie). Pełny przebieg to 63 wywołania na powtórzenie.
- Wyniki w `evals/results/<czas>-<tryb>/` (poza gitem): `results.jsonl` (wyjście, ocena, tokeny z `usage` API, model, który odpowiedział), `errors.jsonl` (błędy API, odmowy, ucięcia — **nie** liczone jako złe odpowiedzi), `summary.md`.
- Przy `--reps > 1` podsumowanie pokazuje rozrzut wyniku między powtórzeniami; różnice mniejsze niż ten rozrzut nie są istotne.
- Te same zestawy posłużą do porównania Claude z modelem lokalnym — wystarczy inna implementacja `LLMClient`.

## Czego te evale nie mierzą

- Jakości tekstu (trafności, tonu) — reguły sprawdzają ugruntowanie i format; treść rozmów i podsumowań trzeba przejrzeć w `results.jsonl`.
- Przypadki są w większości jednoznaczne; brakuje trudnych granicznych (punkt pasujący do 3 kryteriów).
- `classify` zalicza trafienie w jedno z kryteriów oceniającego — precyzja jest raportowana osobno.
