# Jedno polecenie Home RAG — 0.1.0

## Instalacja

```bash
cd ~/projects/home-rag
unzip -o ~/Downloads/home_rag_ask_v0.1.0.zip
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v
```

Pakiet dodaje scripts/ask.py i tests/test_ask.py. Nie zastępuje istniejących
skryptów ani danych. Skrypt działa z biblioteką standardową; nie wymaga
instalowania nowych pakietów Python.

## Zadawanie pytania

```bash
pipenv run python scripts/ask.py \
  "Jakie wartości podaje tabela dla alergii w kolumnach pozytywne efekty, brak wyników i negatywne efekty?"
```

Domyślne ustawienia:
- indeks data/pages/sample_book_100_ocr/table_v010;
- model qwen3.5:4b;
- think false;
- top-k 5;
- generowanie two-stage;
- lokalna Ollama http://127.0.0.1:11434;
- obraz embeddingów home-rag-embedding:0.1.0.

Docker Desktop i ollama2 muszą być uruchomione. Jeśli ollama2 jest zatrzymana:

```bash
docker start ollama2
```

Docling nie jest potrzebny do zadawania pytań.
Wyszukiwanie używa istniejącego obrazu i lokalnych modeli, z --network none
i --pull never. Skrypt nie uruchamia Docling, nie pobiera modeli ani obrazów,
nie liczy ponownie embeddingów i nie zmienia indeksu.

## Wyniki

Każde pytanie tworzy nowy katalog data/runs/<czas_UTC>_<unikalny_id>:
- search.json — ranking źródeł;
- assessment.json — decyzja o możliwości odpowiedzi i wybrane źródła;
- answer.json — odpowiedź, cytaty i zapis etapów generatora;
- run.json — parametry, ścieżki, polecenia, wynik etapów i status całego przebiegu;
- retrieval.log, assessment.log, answer.log — wyjście i błędy poszczególnych skryptów.

Terminal pokazuje postęp trzech etapów, finalną odpowiedź oraz ścieżkę wyników.
Domyślny model pytań i odpowiedzi jest taki sam jak przy ręcznym przepływie.
Ocena źródeł i odpowiedź korzystają z interpretera, którym uruchomiono ask.py,
czyli z pipenv przy powyższym poleceniu. Wyszukiwanie działa w Dockerze.

Indeks i raport są jawnie przekazane każdemu etapowi, ponieważ wyniki leżą
w innym katalogu. Istniejące skrypty zachowują swoje sprawdzenia checksum,
zgodności pytania, źródeł, modelu i cytatów.

Gdy sufficient=false, generator otrzymuje zapisaną ocenę i korzysta z
dotychczasowej ścieżki odmowy, bez ekstrakcji i syntezy. Powstaje pełny answer.json.
Odmowa jest ukończonym przebiegiem, a nie awarią.

Gdy etap kończy się błędem albo nie tworzy poprawnego wyniku, skrypt zatrzymuje
przepływ. run.json ma status failed, a komunikat wskazuje diagnostykę.
Nie przechodzimy do generowania na podstawie brakujących lub starych plików.

## Opcje

```bash
pipenv run python scripts/ask.py "Kto podpisał słowo wstępu?" \
  --output-dir data/runs/podpis_01

pipenv run python scripts/ask.py "Jak założyć winnicę?"

pipenv run python scripts/ask.py "Moje pytanie" \
  --index-dir data/pages/sample_book_100_ocr/metadata_v011 \
  --model qwen3.5:4b --top-k 5 --think false
```

Jawny --output-dir musi wskazywać nowy katalog. Nie nadpisujemy wcześniejszych
przebiegów. Ścieżki indeksu i wyników muszą być wewnątrz projektu montowanego
w Dockerze. Ścieżki względne liczymy od katalogu projektu, w którym leży ask.py,
a nie od bieżącego katalogu terminala. Pytanie jest przekazywane jako osobny
argument subprocess, bez wykonania przez powłokę.

Pozostałe opcje: --api-url, --timeout i --embedding-image; pełna lista w --help.

## Weryfikacja

7 testów z kontrolowanymi procesami etapów sprawdza kolejność, wspólny indeks,
przekazanie pytania, interpreter, odmowę, zatrzymanie po błędzie, odrzucenie
wyniku innego pytania, ochronę wcześniejszych danych i walidację ścieżek.
Nie uruchomiono Dockera i Qwena w tym środowisku.

Pierwszy lokalny test: T01, oczekiwane dane alergii 59% (61), 41% (43), 0% (0),
cytowanie tabeli na stronie PDF 97 bez innych kondycji. Potem sprawdź odmowę
dla winnicy, aby potwierdzić przepływ sufficient=false w całym poleceniu.
