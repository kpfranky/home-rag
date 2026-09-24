import argparse
import base64
import gzip
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf


DEFAULT_API_URL = "http://127.0.0.1:5001"

SCHEMA_NAME = "home-rag-book"
SCHEMA_VERSION = 1
PIPELINE_VERSION = "0.2.0"

KNOWN_COLLECTIONS = {
    "texts": "text",
    "tables": "table",
    "pictures": "picture",
    "key_value_items": "key_value",
    "form_items": "form",
    "groups": "group",
}

FURNITURE_LABELS = {
    "page_header",
    "page_footer",
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Przetwarza OCR-owany PDF przez Docling Serve "
            "i tworzy rozszerzalny model książki."
        )
    )
    parser.add_argument(
        "pdf_path",
        type=Path,
        help="PDF z warstwą tekstową OCR",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/pages"),
        help="Główny katalog wynikowy",
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


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as source:
        for chunk in iter(
            lambda: source.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def call_docling(
    pdf_path: Path,
    api_url: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint = f"{api_url.rstrip('/')}/v1/convert/file"

    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "1200",
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

    print(f"Przetwarzanie przez Docling: {pdf_path}")

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

    return payload, content


def get_reference(value: Any) -> str | None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            return reference

    if isinstance(value, str):
        return value

    return None


def get_references(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    references = []

    for item in value:
        reference = get_reference(item)

        if reference:
            references.append(reference)

    return references


def get_page_size(
    pages: dict[str, Any],
    page_number: int,
) -> tuple[float, float] | None:
    page = pages.get(str(page_number), {})
    size = page.get("size") or {}

    width = size.get("width")
    height = size.get("height")

    if width is None or height is None:
        return None

    return float(width), float(height)


def normalize_bbox(
    bbox: dict[str, Any],
    page_width: float,
    page_height: float,
) -> dict[str, float] | None:
    try:
        left = float(bbox["l"])
        right = float(bbox["r"])
        top = float(bbox["t"])
        bottom = float(bbox["b"])
    except (KeyError, TypeError, ValueError):
        return None

    x_min = min(left, right)
    x_max = max(left, right)

    origin = bbox.get("coord_origin", "TOPLEFT")

    if origin == "BOTTOMLEFT":
        y_min = page_height - max(top, bottom)
        y_max = page_height - min(top, bottom)
    else:
        y_min = min(top, bottom)
        y_max = max(top, bottom)

    return {
        "left": max(0.0, min(1.0, x_min / page_width)),
        "top": max(0.0, min(1.0, y_min / page_height)),
        "right": max(0.0, min(1.0, x_max / page_width)),
        "bottom": max(0.0, min(1.0, y_max / page_height)),
    }


def normalize_provenance(
    item: dict[str, Any],
    pages: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = []

    for provenance in item.get("prov") or []:
        page_number = provenance.get("page_no")
        original_bbox = provenance.get("bbox")

        entry: dict[str, Any] = {
            "page_number": page_number,
            "charspan": provenance.get("charspan"),
            "bbox_original": original_bbox,
            "bbox_normalized": None,
        }

        if (
            isinstance(page_number, int)
            and isinstance(original_bbox, dict)
        ):
            page_size = get_page_size(
                pages,
                page_number,
            )

            if page_size:
                entry["bbox_normalized"] = normalize_bbox(
                    original_bbox,
                    page_width=page_size[0],
                    page_height=page_size[1],
                )

        normalized.append(entry)

    return normalized


def get_page_numbers(
    provenance: list[dict[str, Any]],
) -> list[int]:
    return sorted(
        {
            entry["page_number"]
            for entry in provenance
            if isinstance(entry.get("page_number"), int)
        }
    )


def table_summary(
    item: dict[str, Any],
) -> dict[str, Any]:
    data = item.get("data") or {}
    cells = data.get("table_cells") or []

    max_row = 0
    max_column = 0

    for cell in cells:
        max_row = max(
            max_row,
            int(cell.get("end_row_offset_idx") or 0),
        )
        max_column = max(
            max_column,
            int(cell.get("end_col_offset_idx") or 0),
        )

    return {
        "rows": max_row,
        "columns": max_column,
        "cell_count": len(cells),
        "cells": cells,
    }


def canonicalize_item(
    item: dict[str, Any],
    block_type: str,
    collection_name: str,
    index: int,
    pages: dict[str, Any],
) -> dict[str, Any]:
    provenance = normalize_provenance(item, pages)

    block = {
        "id": item.get(
            "self_ref",
            f"#/{collection_name}/{index}",
        ),
        "type": block_type,
        "subtype": item.get(
            "label",
            item.get("name", block_type),
        ),
        "source_collection": collection_name,
        "content_layer": item.get("content_layer"),
        "page_numbers": get_page_numbers(provenance),
        "provenance": provenance,
        "relations": {
            "parent": get_reference(item.get("parent")),
            "children": get_references(
                item.get("children")
            ),
            "captions": get_references(
                item.get("captions")
            ),
            "references": get_references(
                item.get("references")
            ),
            "footnotes": get_references(
                item.get("footnotes")
            ),
        },
        "text": item.get("text"),
        "original_text": item.get("orig"),
        "formatting": item.get("formatting"),
        "hyperlink": item.get("hyperlink"),
        "meta": item.get("meta"),
        "asset": None,
        "data": None,
        "quality": {
            "status": "pending",
            "issues": [],
        },
    }

    if block_type == "table":
        block["data"] = table_summary(item)

    elif block_type == "picture":
        block["data"] = {
            "annotations": item.get("annotations") or [],
            "source_image": item.get("image"),
        }
        block["quality"]["status"] = "needs_vision"
        block["quality"]["issues"].append(
            "Picture has not been semantically described."
        )

    elif block_type in {"key_value", "form"}:
        block["data"] = item.get("data")

    elif block_type == "group":
        block["data"] = {
            "name": item.get("name"),
        }

    return block


def find_additional_collections(
    document: dict[str, Any],
) -> dict[str, str]:
    result = dict(KNOWN_COLLECTIONS)

    excluded = {
        "pages",
        "body",
        "furniture",
    }

    for name, value in document.items():
        if name in result or name in excluded:
            continue

        if not isinstance(value, list) or not value:
            continue

        if all(isinstance(item, dict) for item in value):
            result[name] = "unknown"

    return result


def build_blocks(
    docling_document: dict[str, Any],
) -> list[dict[str, Any]]:
    pages = docling_document.get("pages") or {}
    collections = find_additional_collections(
        docling_document
    )

    blocks = []

    for collection_name, block_type in collections.items():
        items = docling_document.get(collection_name) or []

        for index, item in enumerate(items):
            block = canonicalize_item(
                item=item,
                block_type=block_type,
                collection_name=collection_name,
                index=index,
                pages=pages,
            )

            if block_type == "unknown":
                block["quality"]["status"] = "review"
                block["quality"]["issues"].append(
                    "Unknown Docling collection."
                )

            blocks.append(block)

    return blocks


def extract_page_images(
    docling_document: dict[str, Any],
    pages_dir: Path,
) -> dict[int, str]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    result = {}

    for page_key, page in (
        docling_document.get("pages") or {}
    ).items():
        image = page.get("image") or {}
        uri = image.get("uri")

        if not isinstance(uri, str):
            continue

        if not uri.startswith("data:image/"):
            continue

        try:
            metadata, encoded = uri.split(",", 1)
            mimetype = metadata.split(";", 1)[0]
            extension = mimetype.split("/", 1)[1]
            image_bytes = base64.b64decode(encoded)
            page_number = int(page_key)
        except (ValueError, TypeError):
            continue

        if extension == "jpeg":
            extension = "jpg"

        target = pages_dir / (
            f"page_{page_number:04d}.{extension}"
        )
        target.write_bytes(image_bytes)

        result[page_number] = str(target)

    return result


def picture_clip(
    pdf_page: pymupdf.Page,
    provenance: dict[str, Any],
) -> pymupdf.Rect | None:
    bbox = provenance.get("bbox_original")

    if not isinstance(bbox, dict):
        return None

    try:
        left = float(bbox["l"])
        right = float(bbox["r"])
        top = float(bbox["t"])
        bottom = float(bbox["b"])
    except (KeyError, TypeError, ValueError):
        return None

    origin = bbox.get("coord_origin", "TOPLEFT")

    if origin == "BOTTOMLEFT":
        y0 = pdf_page.rect.height - max(top, bottom)
        y1 = pdf_page.rect.height - min(top, bottom)
    else:
        y0 = min(top, bottom)
        y1 = max(top, bottom)

    clip = pymupdf.Rect(
        min(left, right),
        y0,
        max(left, right),
        y1,
    )

    clip &= pdf_page.rect

    if clip.is_empty or clip.width < 1 or clip.height < 1:
        return None

    return clip


def extract_picture_assets(
    pdf_path: Path,
    blocks: list[dict[str, Any]],
    pictures_dir: Path,
) -> None:
    pictures_dir.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open(pdf_path)

    try:
        picture_number = 0

        for block in blocks:
            if block["type"] != "picture":
                continue

            provenance_entries = block.get("provenance") or []

            if not provenance_entries:
                continue

            provenance = provenance_entries[0]
            page_number = provenance.get("page_number")

            if not isinstance(page_number, int):
                continue

            if not 1 <= page_number <= document.page_count:
                continue

            page = document[page_number - 1]
            clip = picture_clip(page, provenance)

            if clip is None:
                continue

            picture_number += 1
            target = pictures_dir / (
                f"page_{page_number:04d}_"
                f"picture_{picture_number:03d}.png"
            )

            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(2, 2),
                clip=clip,
                alpha=False,
            )
            pixmap.save(target)

            block["asset"] = str(target)
    finally:
        document.close()


def build_pages(
    docling_document: dict[str, Any],
    blocks: list[dict[str, Any]],
    page_assets: dict[int, str],
) -> list[dict[str, Any]]:
    raw_pages = docling_document.get("pages") or {}
    pages = []

    for page_key in sorted(
        raw_pages,
        key=lambda value: int(value),
    ):
        page_number = int(page_key)
        raw_page = raw_pages[page_key]
        page_blocks = [
            block
            for block in blocks
            if page_number in block["page_numbers"]
        ]

        type_counts = Counter(
            block["type"]
            for block in page_blocks
        )
        subtype_counts = Counter(
            str(block["subtype"])
            for block in page_blocks
        )

        pages.append(
            {
                "page_number": page_number,
                "size": raw_page.get("size"),
                "image": {
                    "asset": page_assets.get(page_number),
                    "metadata": {
                        key: value
                        for key, value in (
                            raw_page.get("image") or {}
                        ).items()
                        if key != "uri"
                    },
                },
                "block_ids": [
                    block["id"]
                    for block in page_blocks
                ],
                "inventory": {
                    "total_blocks": len(page_blocks),
                    "by_type": dict(type_counts),
                    "by_subtype": dict(subtype_counts),
                },
            }
        )

    return pages


def build_clean_text(
    blocks: list[dict[str, Any]],
) -> str:
    paragraphs = []

    for block in blocks:
        if block["type"] != "text":
            continue

        if block["subtype"] in FURNITURE_LABELS:
            continue

        text = " ".join(
            str(block.get("text") or "").split()
        )

        if text:
            paragraphs.append(text)

    if not paragraphs:
        return ""

    return "\n\n".join(paragraphs) + "\n"


def build_quality_report(
    pages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    issues = []

    picture_blocks = [
        block
        for block in blocks
        if block["type"] == "picture"
    ]
    unknown_blocks = [
        block
        for block in blocks
        if block["type"] == "unknown"
    ]

    for block in picture_blocks:
        issues.append(
            {
                "severity": "review",
                "code": "PICTURE_NEEDS_VISION",
                "block_id": block["id"],
                "pages": block["page_numbers"],
                "message": (
                    "Illustration was extracted but has not "
                    "been semantically described."
                ),
            }
        )

    for block in unknown_blocks:
        issues.append(
            {
                "severity": "review",
                "code": "UNKNOWN_BLOCK_TYPE",
                "block_id": block["id"],
                "pages": block["page_numbers"],
                "message": (
                    "An unknown Docling element was preserved."
                ),
            }
        )

    status = "review" if issues else "pass"

    return {
        "schema_version": 1,
        "status": status,
        "scope": "structural_inventory",
        "limitations": [
            (
                "OCR completeness and reading order are not "
                "yet fully validated."
            ),
            (
                "Pictures require a separate vision analysis."
            ),
            (
                "Tables are preserved structurally but are "
                "not yet serialized for retrieval."
            ),
        ],
        "summary": {
            "pages": len(pages),
            "blocks": len(blocks),
            "pictures_needing_vision": len(picture_blocks),
            "unknown_blocks": len(unknown_blocks),
            "issues": len(issues),
        },
        "issues": issues,
        "pages": [
            {
                "page_number": page["page_number"],
                "inventory": page["inventory"],
            }
            for page in pages
        ],
    }


def save_raw_docling(
    path: Path,
    content: dict[str, Any],
) -> None:
    with gzip.open(
        path,
        mode="wt",
        encoding="utf-8",
    ) as target:
        json.dump(
            content,
            target,
            ensure_ascii=False,
            separators=(",", ":"),
        )


def save_json(
    path: Path,
    content: dict[str, Any],
) -> None:
    path.write_text(
        json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    arguments = parse_arguments()
    pdf_path = arguments.pdf_path

    if not pdf_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono pliku: {pdf_path}"
        )

    output_dir = (
        arguments.output_root / pdf_path.stem
    )
    assets_dir = output_dir / "assets"
    pages_dir = assets_dir / "pages"
    pictures_dir = assets_dir / "pictures"
    tables_dir = assets_dir / "tables"

    output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    payload, raw_document = call_docling(
        pdf_path=pdf_path,
        api_url=arguments.api_url,
    )

    raw_path = output_dir / "raw_docling.json.gz"
    save_raw_docling(raw_path, raw_document)

    blocks = build_blocks(raw_document)

    page_assets = extract_page_images(
        raw_document,
        pages_dir,
    )

    extract_picture_assets(
        pdf_path=pdf_path,
        blocks=blocks,
        pictures_dir=pictures_dir,
    )

    pages = build_pages(
        docling_document=raw_document,
        blocks=blocks,
        page_assets=page_assets,
    )

    clean_text = build_clean_text(blocks)
    quality_report = build_quality_report(
        pages=pages,
        blocks=blocks,
    )

    document_model = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "source": {
            "pdf_path": str(pdf_path),
            "filename": pdf_path.name,
            "sha256": calculate_sha256(pdf_path),
        },
        "processor": {
            "name": "docling-serve",
            "status": payload.get("status"),
            "processing_time_seconds": payload.get(
                "processing_time"
            ),
            "errors": payload.get("errors") or [],
            "docling_schema_name": raw_document.get(
                "schema_name"
            ),
            "docling_schema_version": raw_document.get(
                "version"
            ),
        },
        "statistics": {
            "pages": len(pages),
            "blocks": len(blocks),
            "clean_text_characters": len(clean_text),
            "by_type": dict(
                Counter(
                    block["type"]
                    for block in blocks
                )
            ),
            "by_subtype": dict(
                Counter(
                    str(block["subtype"])
                    for block in blocks
                )
            ),
        },
        "pages": pages,
        "blocks": blocks,
    }

    document_path = output_dir / "document.json"
    text_path = output_dir / "clean_text.txt"
    quality_path = output_dir / "quality_report.json"

    save_json(document_path, document_model)
    save_json(quality_path, quality_report)
    text_path.write_text(
        clean_text,
        encoding="utf-8",
    )

    print("\nZapisano:")
    print(raw_path)
    print(document_path)
    print(text_path)
    print(quality_path)
    print(assets_dir)

    print("\nInwentaryzacja:")
    print("Strony:", len(pages))
    print("Bloki:", len(blocks))

    for block_type, count in sorted(
        document_model["statistics"]["by_type"].items()
    ):
        print(f"- {block_type}: {count}")

    print(
        "\nWstępny status jakości:",
        quality_report["status"].upper(),
    )


if __name__ == "__main__":
    main()
