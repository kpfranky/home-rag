import argparse
import json
import os
import subprocess
from pathlib import Path

import pymupdf


DEFAULT_API_URL = "http://127.0.0.1:5001"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Porównuje ekstrakcję PyMuPDF z wynikiem "
            "Docling Serve."
        )
    )
    parser.add_argument(
        "pdf_path",
        type=Path,
        help="PDF zawierający warstwę tekstową OCR",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="Numer analizowanej strony, liczony od 1",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/docling"),
        help="Katalog wynikowy",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get(
            "DOCLING_API_URL",
            DEFAULT_API_URL,
        ),
        help="Adres Docling Serve",
    )
    return parser.parse_args()


def run_pymupdf(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
) -> None:
    document = pymupdf.open(pdf_path)

    try:
        if not 1 <= page_number <= document.page_count:
            raise ValueError(
                f"Strona {page_number} jest poza zakresem "
                f"1–{document.page_count}."
            )

        page = document[page_number - 1]
        raw_text = page.get_text("text", sort=False)
        sorted_text = page.get_text("text", sort=True)
    finally:
        document.close()

    prefix = pdf_path.stem

    raw_path = output_dir / (
        f"{prefix}_page_{page_number:02d}_pymupdf_raw.txt"
    )
    sorted_path = output_dir / (
        f"{prefix}_page_{page_number:02d}_pymupdf_sorted.txt"
    )

    raw_path.write_text(raw_text, encoding="utf-8")
    sorted_path.write_text(sorted_text, encoding="utf-8")

    print("\n" + "=" * 80)
    print("PYMUPDF: sort=False")
    print("=" * 80)
    print(raw_text.strip())

    print("\n" + "=" * 80)
    print("PYMUPDF: sort=True")
    print("=" * 80)
    print(sorted_text.strip())

    print("\nZapisano:")
    print(raw_path)
    print(sorted_path)


def run_docling(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
    api_url: str,
) -> None:
    endpoint = f"{api_url.rstrip('/')}/v1/convert/file"

    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "600",
        "--request",
        "POST",
        endpoint,
        "--form",
        (
            f"files=@{pdf_path.resolve()};"
            "type=application/pdf"
        ),
        "--form",
        "from_formats=pdf",
        "--form",
        "to_formats=json",
        "--form",
        "do_ocr=false",
    ]

    print("\nWysyłanie dokumentu do Docling Serve...")

    result = subprocess.run(
        command,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        error = result.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise RuntimeError(
            "Wywołanie Docling Serve nie powiodło się.\n"
            f"{error}\n"
            "Sprawdź, czy kontener działa na porcie 5001."
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Docling Serve nie zwrócił poprawnego JSON."
        ) from error

    if payload.get("status") != "success":
        raise RuntimeError(
            "Docling zgłosił niepowodzenie:\n"
            f"{payload.get('errors')}"
        )

    content = payload["document"].get("json_content")

    if content is None:
        raise RuntimeError(
            "Odpowiedź Doclinga nie zawiera json_content."
        )

    if isinstance(content, str):
        content = json.loads(content)

    prefix = pdf_path.stem
    response_path = output_dir / (
        f"{prefix}_docling_response.json"
    )
    document_path = output_dir / (
        f"{prefix}_docling.json"
    )

    response_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    document_path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 80)
    print(
        f"DOCLING: elementy przypisane do strony "
        f"{page_number}"
    )
    print("=" * 80)

    found_items = 0

    for item in content.get("texts", []):
        provenance = item.get("prov") or []
        pages = [
            entry.get("page_no")
            for entry in provenance
        ]

        if page_number not in pages:
            continue

        found_items += 1
        label = item.get("label", "unknown")
        text = " ".join(
            (item.get("text") or "").split()
        )

        print(
            f"\n[{found_items}] "
            f"label={label}, pages={pages}"
        )
        print(text)

    print("\n" + "=" * 80)
    print("PODSUMOWANIE DOCLING")
    print("=" * 80)
    print("Status:", payload.get("status"))
    print("Czas:", payload.get("processing_time"))
    print("Błędy:", payload.get("errors"))
    print("Liczba elementów strony:", found_items)
    print("Zapisano:")
    print(response_path)
    print(document_path)


def main() -> None:
    arguments = parse_arguments()

    pdf_path = arguments.pdf_path
    output_dir = arguments.output_dir

    if not pdf_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono pliku: {pdf_path}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    run_pymupdf(
        pdf_path=pdf_path,
        page_number=arguments.page,
        output_dir=output_dir,
    )
    run_docling(
        pdf_path=pdf_path,
        page_number=arguments.page,
        output_dir=output_dir,
        api_url=arguments.api_url,
    )


if __name__ == "__main__":
    main()
