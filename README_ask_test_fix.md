# Poprawka testu ścieżek na macOS

Pakiet zastępuje tylko tests/test_ask.py. Kod ask.py nie zmienia się.

Test porównywał literalną ścieżkę /var/folders/... z kanoniczną ścieżką
/private/var/folders/.... Na macOS obie wskazują ten sam katalog. Skrypt
poprawnie rozwiązywał dowiązanie, a oczekiwanie testu nie uwzględniało go.
Teraz test porównuje obie ścieżki po Path.resolve(), zachowując kontrolę,
że ocena i odpowiedź korzystają z tego samego pliku embeddingów.

```bash
cd ~/projects/home-rag
unzip -o ~/Downloads/home_rag_ask_test_fix_v0.1.1.zip
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
```

Oczekujemy 118 testów bez błędów. Nie dodano ani nie usunięto testów.
Sprawdzono wszystkie siedem testów ask.py oraz ten sam przepływ z katalogiem
dostępnym przez dowiązanie symbolicze. Dowiązanie odtwarza różne zapisy ścieżki
ujawnione na macOS. Nie wykonywano kolejnego generowania przez lokalny model.

Przesłany log potwierdził poprawne wykonanie wszystkich trzech etapów ask.py
dla alergii. Po przejściu testów pozostaje sprawdzić ścieżkę odmowy:

```bash
pipenv run python scripts/ask.py "Jak założyć winnicę?"
```
