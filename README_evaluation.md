# Home RAG — krótka ewaluacja v0.1.0

Wymaga aktualnego scripts/ask.py i działającego indeksu table_v010. Nie zmienia istniejącego przepływu ani indeksu. Pakiet dodaje evaluate_rag.py, 15 pytań oraz sześć testów.

## Uruchomienie

```bash
cd ~/projects/home-rag
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
pipenv run python scripts/evaluate_rag.py
```

Oczekiwane 124 testy po dodaniu sześciu do dotychczasowych 118. Są to testy kodu, a nie wynik ewaluacji lokalnego modelu.

Można najpierw uruchomić dwa przypadki:

```bash
pipenv run python scripts/evaluate_rag.py --case T01 --case R01
```

Każde wywołanie tworzy świeży katalog data/evaluations/<czas_UTC>_<id>. Pytania wykonywane są kolejno. Obejmuje to ponowne uruchomienie kontenera embeddingów dla każdego pytania; czasy uwzględniają start kontenera i ewentualne ładowanie modelu. Nie są porównaniem wydajności modeli. Timeout 600 s dotyczy pojedynczego żądania Ollama, nie całego zestawu. Nie ma instalowania nowych zależności ani pobierania modeli.

## Wyniki

- evaluation.md: pytanie, wzorzec, odpowiedź z cytatami, czas całkowity i czasy etapów.
- evaluation.json: konfiguracja, hash zestawu, hashe indeksu i wyniki sprawdzeń.
- review.json: miejsce na ręczne verdict pass/fail i comment; początkowo pending dla każdego przypadku.
- Podkatalogi przypadków: oryginalne search.json, assessment.json, answer.json, run.json i logi.

Wzorce pochodzą z dotychczasowych fragmentów książki i sprawdzonej tabeli PDF 97. Numery stron PDF to wskazówki do przeglądu. Zestaw nie obejmuje wykresów i pozostałych niesprawdzonych tabel. To mały zestaw regresyjny z pytaniami już używanymi i parafrazami; nie mierzy generalizacji na nowe książki.

Automatyczne sygnały sprawdzają oczekiwaną odpowiedź/odmowę, obecność słów i liczb w twierdzeniach, treść wyszukanych/cytowanych źródeł i obecność cytatów w źródle. Nie korzystają ze stałego rankingu ani S1/S2. Dopasowanie słów i liczb nie dowodzi poprawnego znaczenia, kolejności kolumn ani kompletności. Alternatywne sformułowania lub zapis liczności mogą dać fałszywy alarm.

Przejrzyj każdą odpowiedź: czy odpowiada na dokładne pytanie, podaje wszystkie oczekiwane informacje, poprawnie przypisuje wartości do kolumn, nie dodaje innych chorób/substancji i czy cytaty uzasadniają twierdzenia. Dla odmowy potwierdź, że źródła nie odpowiadają na pytanie. Zapisz werdykty w review.json; skrypt nie agreguje ręcznie uzupełnionych werdyktów i nie nadpisuje poprzednich katalogów.

Kod zakończenia: 0 = bez błędów i alarmów (nadal wymaga przeglądu), 1 = alarm sprawdzeń, 2 = błąd wykonania. Błąd pojedynczego przypadku nie zatrzymuje kolejnych. Ctrl+C przerywa uruchomienie; wyniki ukończonych przypadków pozostają zapisane ze statusem running.

## Git

Do repo dodaj skrypt, zestaw i testy oraz ten README. Wyniki data/evaluations/ pozostaw poza commitem, tak jak data/runs/. Nie używaj git add data/.
