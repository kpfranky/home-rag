# Home RAG — poprawki po ewaluacji v0.1.0

Diagnoza na podstawie zapisanych search/assessment/answer: T01P pomijał istniejący pierwszy wiersz z alergią; P01 ignorował section_path przy krótkim podpisie; T02P i L01 nie miały wymaganych fragmentów w top-5; N06P wybierał informację poboczną i zmieniał czas gramatyczny.

Zmiany:
- assess_sources 0.1.3: etykiety wierszy jako kontekst pomocniczy, instrukcja sprawdzania pierwszego wiersza i podpisu w sekcji, wybierania bezpośrednich dowodów.
- answer_question 0.3.2: section_path i chunk_type dostępne ekstrakcji; typ źródła trafia z ekstrakcji do syntezy, zakres pytania i zachowanie czasu podkreślone. Atrybucja „według tabeli” tylko dla rzeczywistej tabeli.
- ask 0.1.1 oraz evaluate_rag 0.1.1: domyślne top-k=8 zamiast 5. Bez zmiany modelu, indeksu, algorytmu rankingu i limitów kontekstu. CLI nadal pozwala --top-k 5. Wywołanie search_chunks.py bez ask nadal domyślnie używa 5.
- Zestaw pytań, rewizja 2: akceptuje liczność „46 z 63” obok „46”, ale wymaga poprawnego mianownika. Kryterium źródła tabeli pozostaje zachowane.
- Cztery nowe testy, 58 powiązanych testów przeszło lokalnie. Oczekiwane 128 w pełnym repo użytkownika. Testy struktury danych nie potwierdzają skuteczności promptów na rzeczywistym modelu.

Szersze wyszukiwanie może zwiększyć czas i liczbę nieistotnych fragmentów. Nie wiemy jeszcze, czy wymagane fragmenty są w pierwszej ósemce. Nie ma gwarancji, że zmiany promptów wyeliminują błędne odmowy; wymagana jest ponowna ewaluacja. Przy przekroczeniu limitów program odmówi przetwarzania, bez ucinania źródeł.

```bash
cd ~/projects/home-rag
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
pipenv run python scripts/evaluate_rag.py \
  --case T01P --case P01 --case T02P --case L01 --case N06P \
  --case R01 --case R02
```

Pierwszy retest obejmuje pięć problematycznych przypadków i dwie odmowy. Po przeglądzie należy wykonać pełne 15 pytań, żeby sprawdzić regresje w pozostałych odpowiedziach. Wynik 0 nie zastępuje przeglądu znaczenia i poprawnego przypisania wartości do kolumn.

Stare wyniki nie są zmieniane. Każde uruchomienie zapisuje własne wzorce i hash zestawu w evaluation.json. Porównując dwa raporty pamiętaj o zmianie top-k i rewizji wzorca liczności. evaluation.md nie agreguje ręcznych werdyktów review.json.

Do następnego commitu dodaj wyłącznie skrypty, test, konfigurację i dokumentację. Nie dodawaj data/runs/ ani data/evaluations/.
