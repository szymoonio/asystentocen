# Moduł CORE — decyzje i interpretacje

Rzeczy, które warto potwierdzić z mentorami KPRM albo o których powinien wiedzieć agent B.

## Interpretacje przepisów (do potwierdzenia)
- **Wyświetlanie średniej:** klasyfikacja zawsze na ułamku dokładnym, wyświetlanie z 2 miejscami i zaokrągleniem (27/7 → „3,86”). Przykładowe arkusze obcinają do 1 miejsca („3,8”, „7,8”) albo pokazują 2 („6,25”).
- **„Nieobecność dłuższa niż miesiąc”:** uznajemy, gdy obejmuje dzień odpowiadający dniowi początkowemu w następnym miesiącu (`is_longer_than_month`).
- **Przedłużenie terminu o nieobecność** (art. 81 ust. 7) dotyczy tylko terminu 24-miesięcznego, nie ponownej oceny po negatywnej (ust. 9). Wydłużenie liczone w dniach kalendarzowych nieobecności, a koniec terminu przesuwany na dzień roboczy.
- **Oceniający spoza urzędu** (arkusz A — kierownik urzędu): jego czynności w systemie wprowadzają kadry.
- **Sprzeciw rozpatruje** dyrektor generalny; w systemie robi to rola KADRY albo ZARZADZAJACY.
- **„Data do” okresu oceny:** dzień wprowadzenia rozmowy oceniającej albo termin oceny, jeśli wypełniana po jego upływie (schemat pól).

## Odstępstwa od docs/AGENT_A.md
- **Definicje formularza:** zamiast trzech plików `{A,B,C}.v2016.yaml` jest jeden `app/core/forms/definitions/common.v2016.yaml`. Różnice A/B/C (kryteria obowiązkowe, komórka organizacyjna, adresat sprzeciwu) już są w `config/regulation/v2016/sheets.yaml`, więc osobne pliki tylko by je dublowały.
- **Strona `/core/kadry`** dla osób spoza kadr zwraca 200 z informacją o braku dostępu, a nie 403, bo tego wymaga zamrożony test smoke. Akcje POST kadr są chronione (403).
- **PDF:** zamiast WeasyPrint jest widok do druku HTML z `@media print` (przeglądarka: „Zapisz jako PDF”). Bez zależności systemowych, łatwiej wdrożyć w każdym urzędzie.
- **Scheduler** uruchamia się przy pierwszym wejściu na pulpit danego dnia, ręcznie z przycisku albo z crona (`python -m app.core.scheduler`); nie ma osobnego procesu w tle.

## Dla agenta B
- `c.evaluations.current_for(id).criteria` zwraca obowiązkowe + dodatkowe kryteria trwającego cyklu. Przed ustaleniem kryteriów (stan `CYCLE_OPEN`) lista zawiera tylko obowiązkowe.
- Panel „Twoje obserwacje” woła `c.notes.stats_for(author_id=evaluator_id, subject_id, evaluation_id)`. Ostrzeżenie o rozbieżności pojawia się przy ≥ 3 obserwacjach i różnicy ≥ 4 pkt.
- Projekty tekstów: formularz pokazuje `c.drafts.drafts(evaluation_id, field)` dla `UZASADNIENIE`, `WNIOSKI_IPRZ`, `UMOTYWOWANIE_WNIOSKU`, tylko gdy `c.drafts.available()` i ocena jest w stanie `INTERVIEW_HELD`.
- Scheduler A wywołuje `due(today)` każdego `ReminderProvider` z `c.reminder_providers`. Wyjątek w jednym providerze jest logowany i nie zatrzymuje pozostałych.
