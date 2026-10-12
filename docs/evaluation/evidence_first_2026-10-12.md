# Home RAG — checkpoint evidence-first, 2026-10-12

## Zakres i wykonanie

Lokalny indeks sample_book_100_ocr/table_v010; tekst i sprawdzona tabela PDF 97. Domyślny przepływ evidence-first, top-k 8, lokalny Qwen qwen3.5:4b. Nie obejmuje pełnej obsługi wykresów ani wszystkich tabel. Wersje: ask 0.2.0, evaluate_rag 0.2.0, answer_question 0.4.0.

Poprzedni commit bazowy: e56f0b6. Wyniki tego checkpointu pochodzą ze zmian roboczych po tym commicie; nie przypisujemy ich do samego e56f0b6.

Użytkownik potwierdził 145 przechodzących testów kodu. Pełne wykonanie 15 pytań: 0 błędów, 0 automatycznych alarmów. Katalog wykonania na Macu: data/evaluations/20261012T105836_793df7ac. SHA-256 przesłanego evaluation.md: 2fa28d7d440574a1ad0c7d429d1354fd7e7307c368c840be32017e5e4ffd1444.

## Przegląd odpowiedzi

| Przypadki | Wynik przeglądu |
| --- | --- |
| T01, T01P, T02, T02P | Poprawne wartości, nazwy kolumn i cytaty nagłówka oraz właściwego wiersza PDF 97; bez dodatkowych kondycji. |
| N06, N06P | Cytat bezpośrednio określa potencjał generalizacji jako ograniczony. |
| P01, P01P | Poprawnie wybrany podpis mgr farm. Marcina Móla. |
| L01 | Cytaty zawierają wszystkie osiem oczekiwanych nazw substancji; pełne cytaty zawierają również informacje poboczne. |
| L02 | Pierwszy cytat poprawnie wskazuje kwas ibotenowy i muscymol. Drugi cytat opisuje cztery składniki i nie dowodzi ich klasyfikacji; pozostaje błąd odróżniania dowodu bezpośredniego od kontekstu. |
| N07 | Cytaty potwierdzają 107 pytań. |
| R01–R04 | Cztery poprawne odmowy dla pytań spoza tematyki źródła. |

Przegląd raportu potwierdza obecność poprawnej odpowiedzi w każdym przypadku. Nie oznacza pełnego zaliczenia rygorystycznego kryterium wyłącznie bezpośrednich dowodów: L02 pozostaje niezaliczony pod tym względem. Nie uzupełniono ani nie zmieniono oryginalnego review.json, który domyślnie zawiera pending. Ten dokument stanowi odrębny zapis przeglądu.

## Czasy tego przebiegu

- Cztery pytania tabelaryczne: 8,50–8,56 s na pytanie.
- Cały zestaw: 10.45 min; mediana: 44.69 s.
- Pozostałe pytania wymagają modelowego wyboru dowodów; tabela jest składana programowo bez wywołania LLM.

Czasy obejmują start kontenera oraz przygotowanie embeddingu pytania. To obserwacja jednego lokalnego przebiegu, nie benchmark modeli.

## Decyzja i ograniczenia

Zapisać checkpoint działającego przepływu CLI i mechanizmu składania odpowiedzi z oryginalnych dowodów. Zachować poprzedni tryb two-stage jako opcję. Domyślny tryb tekstowy zwraca dosłowne cytaty zamiast swobodnej syntezy; odpowiedzi mogą być długie i zawierać dodatkowy kontekst.

Pozostają: nieidealny wybór dowodów (L02), ograniczona heurystyka polskiej odmiany nazw wierszy, niezweryfikowane etykiety drukowanych stron z OCR (np. PDF 15 ma odczyt „5”), obsługa niesprawdzonych tabel i wykresów oraz ocena na nowych pytaniach i książkach. Wyniku 0 alarmów nie traktować jako gwarancji poprawności semantycznej.

Następny etap: prosty lokalny interfejs korzystający z istniejącego ask.py, z widocznymi źródłami i cytatami. Ulepszanie selekcji dowodów pozostaje osobnym zadaniem; checkpoint nie jest deklaracją gotowości produkcyjnej.

Do Git trafiają kod, testy, konfiguracja i dokumentacja. Wygenerowane data/runs/ oraz data/evaluations/ pozostają poza commitem.
