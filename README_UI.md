# Home RAG — lokalny interfejs v0.1.0

Pole pytania, trzy etapy postępu, odpowiedź, odnośniki do źródeł, rozwijane cytaty i eksport oryginalnego answer.json. UI korzysta z istniejącego scripts/ask.py w trybie evidence-first; nie zmienia indeksu, embeddingów, promptów ani reguł odpowiedzi. Jedno pytanie przetwarzane naraz. Każde pytanie jest niezależne — to nie jest czat z pamięcią rozmowy.

## Uruchomienie na obecnym projekcie

Wymagania: Python 3.11+, istniejące środowisko projektu, uruchomiony Docker i lokalna Ollama, model qwen3.5:4b, obraz home-rag-embedding:0.1.0 oraz indeks data/pages/sample_book_100_ocr/table_v010 wraz z embedding_report.json. Tak samo jak przy działającym ask.py. Pakiet nie instaluje zależności.

```bash
cd ~/projects/home-rag
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
pipenv run python scripts/serve_ui.py
```

Otwórz http://127.0.0.1:8765 w przeglądarce. Serwer działa wyłącznie na loopback. Ctrl+C w terminalu zatrzymuje serwer i aktywną grupę procesów backendu. Przy pierwszym uruchomieniu testów spodziewane 153 testy (dotychczasowe 145 + osiem nowych).

Strona nie korzysta z zewnętrznych skryptów, fontów, CDN ani analityki. Pytania i źródła w trybie rzeczywistym obsługuje lokalny backend. Adres Ollama można zmienić przez --api-url; domyślnie pozostaje localhost.

## Demonstracja dla osoby oglądającej repo

```bash
python3 scripts/serve_ui.py --demo
```

Tryb DEMO korzysta wyłącznie z syntetycznego dokumentu „Archiwum domowe”. Nie potrzebuje Pipenv, Dockera, modelu, OCR ani plików książki. Obsługuje przyciski przykładowe; inne pytania zwykle zwracają odmowę. To celowo prosty backend oparty na stałych przykładach i słowach kluczowych. Nie jest wyszukiwaniem semantycznym, inferencją LLM ani pomiarem jakości RAG. Interfejs stale pokazuje oznaczenie DEMO, odpowiedzi mają composition=demo-fixture, a pliki wykonania demo=true. Nie używaj czasu trybu demo jako benchmarku AI.

## Co pokazuje interfejs

- Trzy etapy są odczytywane z run.json istniejącego backendu; nie symulujemy procentowego postępu w trybie rzeczywistym.
- Odnośnik S1 przy odpowiedzi rozwija przypisane źródło. Wyświetlane są wyłącznie źródła użyte w odpowiedzi, a nie cała lista retrieval.
- Numery PDF są oddzielone od etykiet drukowanych. Niezweryfikowany odczyt OCR jest oznaczony.
- Odmowa jest poprawnym wynikiem, a błąd backendu osobnym stanem z odnośnikiem do logu.
- Pobierz JSON zwraca oryginalny answer.json z backendu.
- Odświeżenie strony przy działającym serwerze odtwarza ostatnie wykonanie w tej karcie. Po restarcie serwera stan sesji znika; pliki pozostają na dysku. Lista historii nie jest częścią tej wersji.

Domyślne parametry: --port 8765, --model qwen3.5:4b, --top-k 8, --timeout 600. Alternatywny indeks: --index-dir <katalog w projekcie>. Timeout dotyczy żądania Ollama, nie całego pytania. Jeśli port jest zajęty, użyj --port 8766. Nie uruchamiaj dwóch serwerów na tym samym porcie.

Wyniki: data/runs/ui_<id>/ z niezmienionymi plikami ask.py; log uruchomienia: data/runs/ui_<id>.log. UI nie udostępnia dowolnych plików projektu ani katalogu danych. Bez uwierzytelniania wieloużytkownikowego i bez wystawiania do sieci; publiczny hosting nie jest zakresem tego pakietu.

## Weryfikacja tej wersji

Osiem testów lokalnych obejmuje rzeczywisty serwer HTTP, proces backendu demonstracyjnego, odpowiedź i pobieranie pliku, odmowę, błąd procesu, pojedyncze aktywne zadanie, sprawdzenie cytatów i ograniczenia żądań. JavaScript sprawdzono składniowo. Testy akceptacyjne w przeglądarce na Macu wykonano 2026-10-16: tabela, tekst, odmowa, eksport JSON, odświeżenie po zakończeniu i w trakcie pracy oraz wszystkie trzy przykłady syntetyczne. Wyniki zweryfikowano na zrzutach, eksportach JSON i potwierdzeniach użytkownika. Szczegóły: [docs/UI_ACCEPTANCE.md](docs/UI_ACCEPTANCE.md).

Test akceptacyjny na Macu:

1. Uruchom serve_ui.py; otwórz adres w przeglądarce.
2. Kliknij Odczyt tabeli, następnie Zapytaj. Oczekuj 59% (61), 41% (43), 0% (0), PDF 97; rozwiń S1.
3. Pobierz JSON i porównaj pytanie oraz wartości z ekranem.
4. Zadaj pytanie o potencjał generalizacji: oczekuj cytatu z PDF 52.
5. Kliknij Brak odpowiedzi i Zapytaj: oczekuj odmowy bez źródeł.
6. Zrestartuj w --demo i sprawdź wszystkie trzy przyciski przykładowe.

Znane ograniczenia backendu pozostają: dobór nadmiarowych cytatów (L02), długie odpowiedzi cytatowe, ograniczona odmiana nazw wierszy, zakres sprawdzonych tabel i jakość OCR. UI ich nie usuwa.

## GitHub

Gotowa instrukcja prezentacji: docs/GITHUB_DEMO.md. Główny README.md opisuje aktualny przepływ i zawiera odnośniki do dokumentacji. Wygenerowane dane pozostają poza repo zgodnie z istniejącymi regułami projektu.

Do commitu dodaj wyłącznie kod UI, test, dokumentację i web/index.html. Wygenerowane data/runs/ pozostają poza commitem. Tryb demonstracyjny umożliwia pokazanie interfejsu bez publikowania skanów, embeddingów i cytatów z posiadanej książki. Publikację zmian do zdalnego repo wykonaj po teście na Macu.
