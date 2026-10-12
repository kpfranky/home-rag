# Home RAG — evidence-first v0.1.0

Zmiana mechanizmu po regresji L02: dotychczas assessment wybrał źródło, które nie potwierdzało żądanej klasyfikacji, a synteza zamieniła listę czterech substancji w błędną parę. Dla tabel synteza parafrazowała poprawne nazwy kolumn i zmieniała relację.

## Nowy domyślny przepływ

ask 0.2.0: retrieval -> assess_evidence -> answer_question w trybie evidence-first. evaluate_rag 0.2.0 korzysta z tego samego przepływu i zapisuje answer_mode w konfiguracji. Można jawnie wybrać --answer-mode two-stage, żeby porównać stary mechanizm.

Dla rozpoznanego wiersza tabeli, gdy pytanie jawnie wymienia żądane kolumny:
- Program odczytuje mapowanie kolumn z nagłówka i wartości z kompletnego wiersza.
- Tworzy twierdzenia: „Według tabeli dla <etykieta>: <nazwa kolumny> — <wartość>”.
- Dołącza dokładny cytat nagłówka i wiersza. Nie wywołuje modelu podczas oceny ani składania takiej odpowiedzi.
- Sprzeczne dopasowane wiersze są błędem, nie wyborem dowolnej wersji. Brak nagłówka, niekompletność lub zbyt długi wiersz powodują przejście do wyboru cytatów.
- Nadal obowiązuje ograniczona heurystyka odmiany polskich nazw wierszy. Nie jest pełnym analizatorem języka ani gwarancją poprawności OCR.

Dla tekstu:
- Model wybiera identyfikatory oryginalnych cytatów ze wszystkich znalezionych źródeł, oddzielnie direct_ids i context_ids.
- Cytaty bezpośrednie mają odpowiadać na żądaną właściwość lub kategorię. Kontekst zostaje zapisany w audycie, ale nie trafia do odpowiedzi.
- Program zwraca „Według fragmentu: <dosłowny cytat>”. Nie ma modelowej ekstrakcji faktów ani syntezy/parafrazy.
- Lista kontekstowych dowodów bez bezpośrednich dowodów daje odmowę.

To jest bardziej zachowawczy tryb oparty na cytatach. Może zwracać dłuższy fragment zawierający informacje poboczne, np. stężenie obok nazwy substancji; nie jest redakcją idealnie krótkiej odpowiedzi. Model nadal może wybrać niewłaściwy cytat lub pominąć właściwy. Ograniczamy dopisywanie nowych twierdzeń podczas składania odpowiedzi; nie zapewniamy automatycznej oceny znaczenia ani jakości źródła. Ewaluacja i ręczny przegląd nadal są wymagane.

Źródła, indeks i raporty historyczne nie są zmieniane. Assessment zachowuje dotychczasowy format decyzji sufficient/source_ids/reason i hashe, dodaje evidence_selection lub structured_table. Answer 0.4.0 ponownie sprawdza zgodność decyzji, źródeł i wybranych dowodów; ponownie wylicza odpowiedź tabelaryczną z oryginału. composition zapisuje structured-table lub verbatim-evidence. Dla tekstu nie ma końcowego wywołania modelu; model/digest są zapisane w raporcie oceny.

## Instalacja i retest

Pakiet wymaga wcześniejszych aktualizacji, w tym table_scope.py oraz aktualnego zestawu ewaluacyjnego. Nie wymaga nowego modelu, zależności, embeddingów ani przebudowania Dockera.

```bash
cd ~/projects/home-rag
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
pipenv run python scripts/evaluate_rag.py --case L02 --case T02P --case N06 --case L01 --case R01
```

Oczekiwane 145 testów: dziewięć nowych plus poprzednie 136. Lokalnie przeszły 84 powiązane testy; rzeczywisty wybór dowodów Qwena nie był tu wykonywany. Po przeglądzie retestu trzeba wykonać pełny zestaw przed oznaczeniem tej wersji jako zaliczonej.

Przykład ręczny:

```bash
pipenv run python scripts/ask.py "Jakie dwa główne związki izoksazolowe zawarte w grzybie wymienia książka?"
```

Poprzedni tryb pozostaje dostępny:

```bash
pipenv run python scripts/ask.py "Pytanie" --answer-mode two-stage
```

Wyniki data/runs/ i data/evaluations/ nadal pozostają poza commitem.
