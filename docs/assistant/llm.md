# Warstwa LLM i prywatność (moduł B)

## Interfejs

`app/assistant/llm/base.py` — `LLMClient` (zgodny z ARCHITEKTURA § 6.4):

| Metoda | Do czego |
|---|---|
| `available(task)` | czy zadanie jest włączone; `False` → UI ukrywa funkcję |
| `model_for(task)` | nazwa modelu do pola `generator` (`generator_id(client, task, "v1")`) |
| `structured(task, system, user, schema)` | zwalidowany obiekt Pydantic |
| `text(task, system, messages)` | zwykła odpowiedź |
| `stream(task, system, messages)` | fragmenty tekstu (próba rozmowy) |

Błędy dziedziczą po `LLMError` i mają `user_message` po polsku: `LLMUnavailable`, `LLMRefusal` (z `category`, komunikat odsyła do kadr), `LLMRateLimited`, `LLMIncomplete`.

Implementacje: `ClaudeClient` (SDK `anthropic`) i `NullClient`. Wybór w `build_client(config)`: bez klucza w `ANTHROPIC_API_KEY` (lub zmiennej z `config/llm.yaml`) zawsze `NullClient`. Klient jest w `services(c).llm`.

## `ClaudeClient` — jak woła API

- `client.beta.messages.parse(..., output_format=Schema)` / `.create` / `.stream`, model i `output_config.effort` z `config/llm.yaml`.
- Prompt systemowy jako blok z `cache_control: ephemeral`; dane zmienne w wiadomościach.
- Bez `temperature` i `thinking` (na `claude-opus-5-5` dają 400).
- `refusal_fallback: true` → `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`: przy odmowie serwer sam ponawia zapytanie na innym modelu. Beta `messages.parse` przyjmuje `fallbacks` razem z `output_format` (sprawdzone na SDK 2.12.0).
- `stop_reason` sprawdzany zawsze: `refusal` → `LLMRefusal`, `max_tokens` → `LLMIncomplete`.
- Wyjątki SDK tłumaczone od najbardziej szczegółowego; SDK sam ponawia 429/5xx (`max_retries`).
- Log `asystent.llm`: zadanie, model, tokeny, `cache_read_input_tokens`, `request_id`. Treść tylko na poziomie DEBUG (i tak już po pseudonimizacji).

## Prywatność (`app/assistant/privacy/`)

1. `screen_notes(notes)` → `included` / `excluded`. Notatka z danymi wrażliwymi (zdrowie, ciąża, życie prywatne, religia, poglądy, związki zawodowe, pochodzenie, nałogi, karalność, prywatne finanse) nie idzie do LLM; `ExcludedNote.warning` to gotowe ostrzeżenie dla przełożonego.
2. `services(c).pseudonymizer().session()`:
   - `label_for(employee)` — wywołaj najpierw dla ocenianego (dostaje `[OSOBA_1]`);
   - `apply(text)` — osoby z katalogu (pełne brzmienie, samo imię, samo nazwisko, z odmianą), e-mail, PESEL, telefon;
   - `restore(text)` — odwrócenie lokalnie; osoby wracają w pełnym brzmieniu (mianownik).
   Imię lub nazwisko noszone przez kilka osób zamieniamy tylko w pełnym brzmieniu.

## Testy

Testy nie wołają sieci: `tests/assistant/conftest.py` usuwa `ANTHROPIC_API_KEY`, a `ClaudeClient` dostaje fałszywe SDK. Do testów funkcji domenowych jest `FakeLLMClient` (fixture `fake_llm`).
