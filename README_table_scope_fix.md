# Home RAG — wskazany wiersz tabeli v0.1.0

Retest: N06P, P01, L01, R01, R02 poprawne. T01P nadal dodawał wiersz leków przeciwdepresyjnych, choć automatyczne sprawdzenie nie zgłosiło alarmu. T02P podawał poprawne liczby z opisu PDF 88, ale nadal nie odpowiadał na prośbę odczytu tabeli.

## Zmiany

Nowy table_scope.py rozpoznaje jawne polskie pytania o tabelę oraz dopasowuje słowa z etykiet c1 do słów pytania z ograniczoną obsługą odmiany (bez nazw konkretnych chorób zapisanych w kodzie). Gdy nie znajduje dopasowania, zachowuje dotychczasowy przepływ. Nie jest pełnym analizatorem polszczyzny: synonimy i niektóre odmiany mogą nie pasować, podobne początki słów mogą dać fałszywe dopasowanie.

search_chunks.py 0.1.1: opcjonalne --prefer-table-rows priorytetyzuje pasujące tabele przed pozostałymi fragmentami, wewnątrz grup zachowuje ranking kosinusowy. score pozostaje podobieństwem kosinusowym, a ranking_strategy zapisuje nową regułę; wyniki mogą mieć rosnący score między grupami. Nie zmienia ani nie przelicza embeddingów.

ask.py 0.1.2 włącza --prefer-table-rows. Ręczne wywołanie search_chunks.py bez flagi zachowuje poprzednie sortowanie. Nie trzeba przebudowywać obrazu Dockera: skrypty uruchamiane są z zamontowanego katalogu projektu.

answer_question.py 0.3.3: dla pytań o tabelę, gdy w wybranych przez assessment źródłach rozpoznano żądany wiersz, ekstrakcja korzysta tylko z pasujących tabel i wskazanych wierszy. Nie przekazuje innych wierszy modelowi ani ich identyfikatorów jako dopuszczalnych dowodów. Zachowuje nagłówek jako kontekst kolumn. Cytaty są ciągłymi fragmentami oryginału, z oryginalnymi offsetami. Pełne źródła i pierwotny wybór assessment pozostają w audycie; extraction_source_ids pokazuje węższy wybór do ekstrakcji. Ta zmiana dotyczy trybu two-stage używanego przez ask; tryb single nadal działa jak wcześniej.

Ograniczenie do wskazanych wierszy zapobiega przekazywaniu modelowi nieistotnych danych tabelarycznych; nie jest weryfikacją znaczenia wszystkich twierdzeń. Model nadal może popełniać błędy. Assessment nadal musi poprawnie wybrać źródła.

## Weryfikacja

Siedem nowych testów: odmiana etykiet, pierwszy i drugi wiersz, wiele wierszy, oryginalne offsety, zakaz nieprzekazanych identyfikatorów, długie wiersze oraz sortowanie z zachowaniem score. Łącznie 74 powiązane testy przeszły lokalnie; spodziewane 135 w pełnym repo użytkownika.

```bash
cd ~/projects/home-rag
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
pipenv run python scripts/evaluate_rag.py --case T01 --case T01P --case T02 --case T02P
```

Po przeglądzie czterech odpowiedzi należy uruchomić pełne 15 pytań przed commitem i przejściem do interfejsu. Raportów nie nadpisujemy. Ręczny przegląd nadal musi wykrywać dodatkowe informacje spoza zakresu pytania, nawet jeśli signals_ok=true.
