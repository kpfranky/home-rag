# Metadane numerów stron — poprawka 0.1.1

## Instalacja i aktualizacja obecnego indeksu

Rozpakuj scripts/ i tests/ do katalogu ~/projects/home-rag.
Pakiet zastępuje scripts/normalize_document.py i dodaje
scripts/refresh_page_metadata.py oraz testy. Wymaga tylko biblioteki standardowej.

```bash
cd ~/projects/home-rag
unzip -o ~/Downloads/home_rag_page_metadata_v0.1.1.zip
pipenv run python -m unittest discover -s tests -p 'test_*.py' -v

pipenv run python scripts/refresh_page_metadata.py \
  data/pages/sample_book_100_ocr/document.json \
  --embeddings data/pages/sample_book_100_ocr/embeddings.jsonl \
  --report data/pages/sample_book_100_ocr/embedding_report.json \
  --output-dir data/pages/sample_book_100_ocr/metadata_v011
```

Wyjście zawiera chunks.jsonl, embeddings.jsonl, embedding_report.json i
page_metadata_report.json. Jeśli pierwotny raport embeddingów zapisano pod inną
nazwą, podaj jego rzeczywistą ścieżkę w --report. Nowy raport zachowuje
konfigurację embeddingów i ma hashe nowych plików oraz historię aktualizacji.
Pole input_sha256 odpowiada nowemu chunks.jsonl. Stare pliki pozostają bez zmian.
Katalog wyjściowy musi być nowy; istniejące pliki nie są nadpisywane.

Ta operacja nie uruchamia Docling, Ollamy ani modelu embeddingów.
Wektory, tekst do embeddingów, kolejność i identyfikatory chunków pozostają takie
same. Aktualizowane są wyłącznie pola metadanych cytowania wewnątrz chunków.
Nie kopiuj starego embedding_report.json obok nowego indeksu: jego hash dotyczy
starego pliku. Nie kopiuj starego raportu chunkingu jako walidacji nowego pliku.

## Kontrola N06

Po aktualizacji uruchom wyszukiwanie z nowego indeksu:

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work home-rag-embedding:0.1.0 \
  scripts/search_chunks.py \
  data/pages/sample_book_100_ocr/metadata_v011/embeddings.jsonl \
  --query "Jak autorka określa potencjał generalizacji wyników badania?" \
  --top-k 5 \
  --output data/pages/sample_book_100_ocr/metadata_v011/search_N06.json
```

Nowy indeks i raport znajdują się razem pod domyślnymi nazwami.
Wyniki dla strony PDF 52 powinny mieć printed_page_labels: [].
Surowy cytat i nazwisko pozostaną w page_footer_raw. W istniejącym formacie
odpowiedzi oznaczenie drukowane będzie prezentowane jako „brak”.
Stare search_*.json i answer_*.json zawierają dawne metadane; należy ponownie
uruchomić wyszukiwanie i dalsze etapy, aby uzyskać nowe wyniki cytowania.

## Zasady

- Numer PDF i oznaczenie drukowane są niezależne.
- Akceptujemy cały tekst stopki będący cyframi arabskimi lub kanonicznym
  numerem rzymskim. Nie wydobywamy liczb z zdań, procentów lub nazwisk.
- Surowe stopki zachowują tekst, ID bloku i pochodzenie.
- Pojedynczy liczbowy odczyt OCR ma status unverified_ocr.
- Brak numeru ma status missing; kilka różnych numerów ma status ambiguous
  i nie jest prezentowanych jako ustalone oznaczenie strony.
- Na stronie PDF 15 odczyt „5” pozostaje kandydatem OCR. Nie zmieniamy go na
  „15” tylko na podstawie numeru PDF. Na stronie PDF 55 numeru nie dopisujemy.

## Korekty potwierdzone w skanie

refresh_page_metadata.py obsługuje --page-label-reviews ze ścieżką pliku JSON:

```json
{
  "source_sha256": "SHA-256 ze source.sha256 w document.json",
  "reviews": [
    {
      "page_number": 15,
      "before": ["5"],
      "after": ["15"],
      "reason": "Numer 15 potwierdzony przez właściciela w skanie"
    }
  ]
}
```

To przykład schematu, nie gotowa potwierdzona korekta. Wprowadź go dopiero po
sprawdzeniu skanu i wpisaniu rzeczywistego SHA-256. Przed korektą sprawdzamy
hash źródła, numer strony i poprzednią wartość; powód oraz poprzednia wartość
pozostają w metadanych i raporcie. Można też potwierdzić brak numeru przez
after: []. Korekty dotyczą wyłącznie oznaczeń stron, nie tekstu lub tabel.

## Następna normalizacja

normalize_document.py 0.1.1 zapisuje nowe pola również podczas przyszłych
eksportów. Nie uruchamiaj teraz normalizacji nad istniejącym
normalized_blocks.jsonl: plik decyzji dla chunkingu jest związany z jego
SHA-256. Zmiana schematu wymaga przeglądu i przeniesienia tych decyzji do
nowego eksportu. Obecny indeks aktualizujemy bez tego kroku.
Chunker obecnie przenosi printed_page_labels; dodatkowe pola stopki do
indeksu dołącza refresh_page_metadata.py. Uruchom go ponownie po przyszłym
chunkingu i embeddingach.

## Weryfikacja

15 testów: poprzednie 8 normalizatora oraz 7 testów regresji metadanych,
historii korekt, błędnego skanu/checksum i niezmienności wektorów.
Porównanie starej i nowej normalizacji dostarczonego document.json:
1573 rekordy, identyczne dane poza wersją normalizatora i polami metadanych.
Nie uruchomiono aktualizacji rzeczywistego 457-wektorowego indeksu z MacBooka:
nie jest dostępny w tym środowisku. Weryfikacja tego indeksu odbywa się
powyższym poleceniem lokalnie. Tabela ze strony 97 pozostaje osobnym krokiem.
