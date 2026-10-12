# Home RAG — format liczności i nazwy kolumn v0.1.0

Przegląd evaluation(2).md: wszystkie cztery odpowiedzi mają poprawne wartości i cytują właściwy wiersz tabeli PDF 97. Nie dodają innych kondycji. Dwa alarmy były wynikiem nieakceptowania jednostek w nawiasach, np. 61 osób. T02P dodatkowo parafrazuje „Brak wyników” jako „brakujące wyniki”, co może sugerować brak danych; odpowiedź wymaga precyzyjniejszej nazwy kolumny. Nie traktujemy sygnałów regex jako oceny znaczenia.

Zestaw rewizja 3 akceptuje osoby/osób/osoba po liczności oraz opcjonalny prawidłowy mianownik. Nadal odrzuca złe procenty, liczności lub mianowniki. Kryteria treści źródeł tabeli bez zmian. Ponowne zastosowanie nowych wzorców do samych twierdzeń w istniejącym raporcie daje poprawne dopasowanie dla wszystkich czterech przypadków; nie potrzeba ponownego modelu, żeby sprawdzić format.

answer_question 0.3.4 instruuje ekstrakcję i syntezę, żeby zachować nazwy kolumn bez parafraz. To instrukcja modelu, nie gwarancja automatycznej walidacji znaczenia. Nie zmienia rankingów, źródeł, embeddingów ani wartości.

Jeden nowy test sprawdza wiele poprawnych formatów i odrzucanie błędnych wartości. Łącznie 75 powiązanych testów przeszło lokalnie; spodziewane 136 w pełnym repo.

```bash
cd ~/projects/home-rag
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
pipenv run python scripts/evaluate_rag.py
```

Po pełnym reteście należy przejrzeć wszystkie 15 odpowiedzi przed commitem. Stare raporty pozostają z ich oryginalnymi wzorcami i hashami; nie nadpisujemy ich. Dane wykonania w data/evaluations/ i data/runs/ pozostają poza commitem.
