from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


SCHEMA_NAME = "home-rag-page-analysis"
SCHEMA_VERSION = 1
ANALYZER_VERSION = "0.1.0"

MAX_BODY_TOP_GAP = 0.35
MAX_SECTION_OPENER_TOP_GAP = 0.55
MIN_TEXT_RATIO_TO_MEDIAN = 0.40
MIN_SUBSTANTIVE_CHARACTERS = 20

FURNITURE_LABELS = {
    "page_header",
    "page_footer",
}

LEGAL_NOTICE_PHRASES = {
    "charakter wyłącznie informacyjny",
    "nie ponoszą odpowiedzialności",
    "zdrowie i bezpieczeństwo",
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analizuje role stron i wykrywa podejrzane "
            "braki treści."
        )
    )
    parser.add_argument(
        "document_path",
        type=Path,
        help="Ścieżka do document.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Opcjonalna ścieżka wyniku. Domyślnie "
            "page_analysis.json obok document.json."
        ),
    )
    return parser.parse_args()


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def provenance_for_page(
    block: dict[str, Any],
    page_number: int,
) -> list[dict[str, Any]]:
    return [
        entry
        for entry in block.get("provenance") or []
        if entry.get("page_number") == page_number
    ]


def normalized_bbox(
    provenance: dict[str, Any],
) -> dict[str, float] | None:
    bbox = provenance.get("bbox_normalized")

    if not isinstance(bbox, dict):
        return None

    try:
        return {
            "left": float(bbox["left"]),
            "top": float(bbox["top"]),
            "right": float(bbox["right"]),
            "bottom": float(bbox["bottom"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def provenance_height(
    provenance: dict[str, Any],
) -> float:
    bbox = normalized_bbox(provenance)

    if bbox is None:
        return 0.0

    return max(0.0, bbox["bottom"] - bbox["top"])


def estimated_characters_on_page(
    block: dict[str, Any],
    page_number: int,
) -> int:
    text_length = len(normalize_text(block.get("text")))

    if text_length == 0:
        return 0

    provenance = block.get("provenance") or []
    matching = provenance_for_page(block, page_number)

    if not matching:
        return 0

    total_height = sum(
        provenance_height(entry)
        for entry in provenance
    )
    matching_height = sum(
        provenance_height(entry)
        for entry in matching
    )

    if total_height <= 0:
        page_numbers = block.get("page_numbers") or []

        if not page_numbers:
            return text_length

        return round(text_length / len(page_numbers))

    ratio = matching_height / total_height
    return round(text_length * ratio)


def blocks_for_page(
    document: dict[str, Any],
    page: dict[str, Any],
) -> list[dict[str, Any]]:
    block_ids = set(page.get("block_ids") or [])

    return [
        block
        for block in document.get("blocks") or []
        if block.get("id") in block_ids
    ]


def substantive_text_blocks(
    blocks: list[dict[str, Any]],
    page_number: int,
) -> list[dict[str, Any]]:
    result = []

    for block in blocks:
        if block.get("type") != "text":
            continue

        subtype = block.get("subtype")

        if subtype in FURNITURE_LABELS:
            continue

        text = normalize_text(block.get("text"))

        if (
            len(text) < MIN_SUBSTANTIVE_CHARACTERS
            and subtype != "section_header"
        ):
            continue

        entries = provenance_for_page(
            block,
            page_number,
        )

        if not any(
            normalized_bbox(entry) is not None
            for entry in entries
        ):
            continue

        result.append(block)

    return result


def page_text(
    blocks: list[dict[str, Any]],
) -> str:
    return " ".join(
        normalize_text(block.get("text"))
        for block in blocks
        if block.get("type") == "text"
    ).lower()


def is_document_index(
    blocks: list[dict[str, Any]],
) -> bool:
    return any(
        block.get("type") == "table"
        and block.get("subtype") == "document_index"
        for block in blocks
    )


def is_legal_notice(
    blocks: list[dict[str, Any]],
) -> bool:
    text = page_text(blocks)

    return sum(
        phrase in text
        for phrase in LEGAL_NOTICE_PHRASES
    ) >= 2


def determine_roles(
    document: dict[str, Any],
) -> dict[int, str]:
    page_blocks = {
        page["page_number"]: blocks_for_page(
            document,
            page,
        )
        for page in document.get("pages") or []
    }

    index_pages = {
        page_number
        for page_number, blocks in page_blocks.items()
        if is_document_index(blocks)
    }

    first_index_page = (
        min(index_pages)
        if index_pages
        else None
    )

    roles = {}

    for page_number, blocks in page_blocks.items():
        if page_number in index_pages:
            role = "document_index"
        elif is_legal_notice(blocks):
            role = "legal_notice"
        elif (
            first_index_page is not None
            and page_number < first_index_page
        ):
            role = "front_matter"
        else:
            role = "body"

        roles[page_number] = role

    return roles


def calculate_metrics(
    blocks: list[dict[str, Any]],
    page_number: int,
) -> dict[str, Any]:
    content_blocks = substantive_text_blocks(
        blocks,
        page_number,
    )

    boxes = []

    for block in content_blocks:
        for entry in provenance_for_page(
            block,
            page_number,
        ):
            bbox = normalized_bbox(entry)

            if bbox is not None:
                boxes.append(bbox)

    top = min(
        (bbox["top"] for bbox in boxes),
        default=None,
    )
    bottom = max(
        (bbox["bottom"] for bbox in boxes),
        default=None,
    )

    text_characters = sum(
        estimated_characters_on_page(
            block,
            page_number,
        )
        for block in content_blocks
    )

    return {
        "text_characters": text_characters,
        "text_blocks": len(content_blocks),
        "top_text_position": top,
        "bottom_text_position": bottom,
        "vertical_coverage": (
            round(bottom - top, 6)
            if top is not None and bottom is not None
            else None
        ),
        "section_opener": any(
            block.get("subtype") == "section_header"
            for block in content_blocks
        ),
    }


def make_issue(
    code: str,
    message: str,
    page_number: int,
    block_ids: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "page_number": page_number,
        "block_ids": block_ids,
    }


def page_quality(
    page_number: int,
    role: str,
    metrics: dict[str, Any],
    block_ids: list[str],
    body_median: float | None,
) -> dict[str, Any]:
    issues = []

    if role == "body":
        if metrics["text_blocks"] == 0:
            issues.append(
                make_issue(
                    code="NO_BODY_TEXT",
                    message=(
                        "Body page contains no substantive "
                        "text blocks."
                    ),
                    page_number=page_number,
                    block_ids=block_ids,
                )
            )
            return {
                "status": "fail",
                "issues": issues,
            }

        top = metrics["top_text_position"]
        top_limit = (
            MAX_SECTION_OPENER_TOP_GAP
            if metrics["section_opener"]
            else MAX_BODY_TOP_GAP
        )

        if top is not None and top > top_limit:
            issues.append(
                make_issue(
                    code="LARGE_EMPTY_TOP_AREA",
                    message=(
                        "Body content starts unusually low "
                        f"on the page: {top:.3f}."
                    ),
                    page_number=page_number,
                    block_ids=block_ids,
                )
            )

        if (
            body_median
            and metrics["text_characters"]
            < body_median * MIN_TEXT_RATIO_TO_MEDIAN
        ):
            issues.append(
                make_issue(
                    code="LOW_TEXT_VOLUME",
                    message=(
                        "Estimated text volume is below "
                        f"{MIN_TEXT_RATIO_TO_MEDIAN:.0%} "
                        "of the body-page median."
                    ),
                    page_number=page_number,
                    block_ids=block_ids,
                )
            )

    return {
        "status": "review" if issues else "pass",
        "issues": issues,
    }


def document_status(
    pages: list[dict[str, Any]],
) -> str:
    statuses = {
        page["quality"]["status"]
        for page in pages
    }

    if "fail" in statuses:
        return "fail"

    if "review" in statuses:
        return "review"

    return "pass"


def analyze_document(
    document: dict[str, Any],
) -> dict[str, Any]:
    roles = determine_roles(document)
    prepared_pages = []

    for page in document.get("pages") or []:
        page_number = page["page_number"]
        blocks = blocks_for_page(document, page)
        metrics = calculate_metrics(
            blocks,
            page_number,
        )

        prepared_pages.append(
            {
                "page_number": page_number,
                "role": roles[page_number],
                "block_ids": page.get("block_ids") or [],
                "metrics": metrics,
            }
        )

    body_volumes = [
        page["metrics"]["text_characters"]
        for page in prepared_pages
        if page["role"] == "body"
        and page["metrics"]["text_characters"] > 0
    ]

    body_median = (
        median(body_volumes)
        if body_volumes
        else None
    )

    for page in prepared_pages:
        page["quality"] = page_quality(
            page_number=page["page_number"],
            role=page["role"],
            metrics=page["metrics"],
            block_ids=page["block_ids"],
            body_median=body_median,
        )

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "source": document.get("source"),
        "configuration": {
            "max_body_top_gap": MAX_BODY_TOP_GAP,
            "max_section_opener_top_gap": (
                MAX_SECTION_OPENER_TOP_GAP
            ),
            "min_text_ratio_to_median": (
                MIN_TEXT_RATIO_TO_MEDIAN
            ),
            "min_substantive_characters": (
                MIN_SUBSTANTIVE_CHARACTERS
            ),
        },
        "summary": {
            "pages": len(prepared_pages),
            "body_text_median": body_median,
            "issues": sum(
                len(page["quality"]["issues"])
                for page in prepared_pages
            ),
        },
        "status": document_status(prepared_pages),
        "pages": prepared_pages,
    }


def main() -> None:
    arguments = parse_arguments()

    if not arguments.document_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono pliku: "
            f"{arguments.document_path}"
        )

    document = json.loads(
        arguments.document_path.read_text(
            encoding="utf-8"
        )
    )

    report = analyze_document(document)

    output_path = (
        arguments.output
        or arguments.document_path.with_name(
            "page_analysis.json"
        )
    )

    output_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Zapisano: {output_path}")
    print(f"Status dokumentu: {report['status'].upper()}")

    for page in report["pages"]:
        issue_codes = [
            issue["code"]
            for issue in page["quality"]["issues"]
        ]

        print(
            f"strona={page['page_number']:02d} "
            f"rola={page['role']:16} "
            f"status={page['quality']['status']:6} "
            f"top={page['metrics']['top_text_position']} "
            f"znaki={page['metrics']['text_characters']} "
            f"issues={issue_codes}"
        )


if __name__ == "__main__":
    main()
