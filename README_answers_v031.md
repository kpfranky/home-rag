# Odpowiedzi 0.3.1 — zakres pytania i cytaty tabelaryczne

T01 ujawnił błąd zakresu: poprawnie wyszukano i wybrano S2, ale ekstrakcja
przekazała osiem pozycji, a odpowiedź opisała osiem kondycji mimo pytania
wyłącznie o alergię. Procenty alergii były poprawne, ale zabrakło liczb w
nawiasach. Cytaty obejmowały sąsiednie wiersze i urywały się w środku komórek.

## Zmiana

- Instrukcje ekstrakcji rozróżniają listę kolumn od listy wierszy. Pytanie o
  jeden wiersz ma dostarczyć tylko jego dane, wraz z procentami i liczbami.
- Synteza ma ponownie ocenić zakres pytania i pomijać nieistotne items,
  zamiast automatycznie przenosić je wszystkie do odpowiedzi.
- Krótkie wiersze tabeli stanowią osobne, ciągłe wpisy w katalogu dowodów.
  Nagłówek i pierwszy wiersz są jednym cytatem. Dłuższe wiersze zachowują
  dotychczasowy podział z pełnym pokryciem tekstu i limitem 320 znaków.
- Cytaty pozostają dosłownymi fragmentami źródła, z prawdziwymi offsetami.
- Wersje promptów i katalogu są zapisane w wyniku JSON.
- Reguła kompletności list nazw pozostaje aktywna dla pytań wymagających list.

To doprecyzowanie instrukcji modelu, nie programowa gwarancja trafności
semantycznej. Walidator nadal sprawdza schemat, identyfikatory i dosłowność
cytatów. Skuteczność zmiany zakresu wymaga ponownego testu na lokalnym modelu.

## Instalacja i ponowienie T01

Pakiet zastępuje tylko scripts/answer_question.py i dodaje cztery testy
katalogu tabel. Pozostałych skryptów, indeksu i embeddingów nie zmienia.
Można ponownie użyć obecnego search_T01.json i assessment_T01.json, ponieważ
ich dane źródłowe i indeks pozostały takie same. Nowa odpowiedź ma inną nazwę.

```bash
cd ~/projects/home-rag
unzip -o ~/Downloads/home_rag_answers_v0.3.1.zip
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v

pipenv run python scripts/answer_question.py \
  data/pages/sample_book_100_ocr/table_v010/search_T01.json \
  --assessment data/pages/sample_book_100_ocr/table_v010/assessment_T01.json \
  --model qwen3.5:4b \
  --mode two-stage \
  --think false \
  --top-k 5 \
  --output data/pages/sample_book_100_ocr/table_v010/answer_T01_v031.json
```

Oczekiwany wynik: wyłącznie alergia, z wartościami pozytywne efekty 59% (61),
brak wyników 41% (43), negatywne efekty 0% (0), odniesieniem do tabeli,
cytowaniem S2 i strony PDF 97. Nie powinno być twierdzeń o innych kondycjach.
Wyciągnięta informacja powinna odnosić się tylko do alergii; liczba items
sama w sobie nie jest kryterium jakości.

## Weryfikacja

Przeszło 28 dotychczasowych testów odpowiedzi i 4 nowe testy tabel:
granice wierszy, zgodność dosłownych cytatów z offsetami, pełne pokrycie
tekstu, zachowanie ID źródła i awaryjny podział długiego wiersza.
Nie wykonano generowania Qwen3.5 w tym środowisku. Po T01 należy sprawdzić
również wcześniejszą listę substancji (kompletność listy) i podpis (krótka
odpowiedź), aby ocenić wpływ zmiany promptów na dotychczasowe przypadki.
