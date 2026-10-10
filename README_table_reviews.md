# Korekta tabeli PDF 97 — 0.1.0

## Instalacja i przygotowanie

Pakiet dodaje skrypt, testy i plik potwierdzeń. Nie zastępuje istniejących
skryptów chunkingu, embeddingów ani generowania odpowiedzi.
Wymaga obecnego scripts/chunk_document.py z table_groups i render_cells.

```bash
cd ~/projects/home-rag
unzip -o ~/Downloads/home_rag_table_reviews_v0.1.0.zip
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v

pipenv run python scripts/apply_table_reviews.py \
  data/pages/sample_book_100_ocr/metadata_v011/chunks.jsonl \
  --document data/pages/sample_book_100_ocr/document.json \
  --review config/table_reviews/sample_book_100_p97.json \
  --max-table-chars 800 \
  --output-dir data/pages/sample_book_100_ocr/table_v010
```

Katalog wyjściowy musi być nowy. Otrzymasz chunks.jsonl i
table_review_report.json. Obecny indeks metadata_v011 pozostaje zachowany.
Nowy plik jest przeznaczony do ponownego wyliczenia embeddingów; liczba
chunków może wzrosnąć wskutek dodania nagłówków i podziału tabeli na fragmenty.

## Sprawdzenie limitu tokenów

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work home-rag-embedding:0.1.0 \
  scripts/embed_chunks.py \
  data/pages/sample_book_100_ocr/table_v010/chunks.jsonl \
  --check-only \
  --output data/pages/sample_book_100_ocr/table_v010/embeddings.jsonl
```

Ten krok korzysta z lokalnego tokenizera, ale nie generuje wektorów.
Oczekujemy overflow: [] i komunikatu PASS. Jeśli są przekroczenia w zmienionej
tabeli, uruchom skrypt korekty ponownie z mniejszym --max-table-chars i innym,
nowym katalogiem wyjściowym, po czym powtórz kontrolę. Niczego nie ucinamy.

## Embeddingi — po PASS kontroli tokenów

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work home-rag-embedding:0.1.0 \
  scripts/embed_chunks.py \
  data/pages/sample_book_100_ocr/table_v010/chunks.jsonl \
  --output data/pages/sample_book_100_ocr/table_v010/embeddings.jsonl
```

Domyślny embedding_report.json zostanie utworzony w tym samym katalogu.
Nie kopiuj starego raportu do nowego indeksu. Wszystkie wektory wyliczamy
ponownie obecnym sprawdzonym skryptem, ponieważ zmienił się tekst tabeli.
Docling i Ollama nie są potrzebne do korekty i embeddingów.

## Co poprawiono i jak zachowano źródło

- Nagłówki ze skanu: Kondycja, Pozytywne efekty, Brak wyników, Negatywne efekty.
- Pierwszy wiersz, druga kolumna: 9% (61) -> 59% (61).
- W każdym fragmencie tabeli dodano mapowanie c1–c4 do nazw kolumn także do
  pola text, które widzą modele oceniające źródła i generujące odpowiedź.
- Nagłówki są oznaczone jako verified_scan_header. Nie tworzymy fikcyjnych
  współrzędnych ani indeksów komórek nagłówka, którego ekstrakcja nie zawierała.
- Oryginalne 100 komórek, ich pochodzenie i współrzędne pozostają zachowane;
  zmienia się wyłącznie potwierdzony tekst jednej komórki. Nagłówki zapisano
  osobno; nie przesuwamy numerów wierszy z oryginalnej ekstrakcji.
- Pełna tabela przed i po korekcie, powody, hash skanu i dane potwierdzenia
  pozostają w raporcie. Zmienione chunki mają nowe ID i historię korekty.
- Inne chunki zachowują zawartość i ID, także metadane numerów stron.
- document.json, normalized_blocks.jsonl i decyzje dotyczące tekstu przy
  obrazach pozostają oryginalne. Przy przyszłym przebudowaniu indeksu korektę
  należy ponownie zastosować tym skryptem do nowych chunków przed embeddingami.
- To nie jest weryfikacja wszystkich danych tabeli. Niespójności występujące
  także w książce, np. Oparzenia (22) / 3% (25), pozostają bez zmian.

Powiązanie z SHA-256 dokumentu i całej wyodrębnionej tabeli oraz kontrola
poprzedniej treści komórki chronią przed korektą innego skanu. Skrypt wymaga
pełnego pokrycia komórek oryginalnymi chunkami; odrzuca zmienione komórki,
tekst lub ponowne zastosowanie tej samej korekty.

## Kontrola wyszukiwania po embeddingach

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work home-rag-embedding:0.1.0 \
  scripts/search_chunks.py \
  data/pages/sample_book_100_ocr/table_v010/embeddings.jsonl \
  --query "Jakie wartości podaje tabela dla alergii w kolumnach pozytywne efekty, brak wyników i negatywne efekty?" \
  --top-k 5 \
  --output data/pages/sample_book_100_ocr/table_v010/search_T01.json
```

Wzorcem T01 jest: alergia (104), pozytywne efekty 59% (61), brak wyników
41% (43), negatywne efekty 0% (0). Są to dane przedstawione w książce,
nie potwierdzenie skuteczności medycznej. Ocenę źródeł i odpowiedź wykonamy
po kontroli, czy wyszukiwanie dostarczyło poprawiony fragment tabeli.

## Weryfikacja pakietu

6 testów jednostkowych: korekta i nagłówki, pełne pokrycie komórek, historia,
deterministyczność, brak zmian innych chunków i odrzucanie niezgodnych danych.
Na przesłanej tabeli sprawdzono zachowanie 100 komórek przy limitach
900, 1000 i 1200 znaków. Nie uruchomiono tokenizera ani embeddingów
rzeczywistego indeksu z MacBooka; powyższe kroki wykonują tę kontrolę lokalnie.
