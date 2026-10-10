from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


SCHEMA_NAME = "home-rag-page-analysis"
SCHEMA_VERSION = 1
ANALYZER_VERSION = "0.3.0"

MAX_BODY_TOP_GAP = 0.35
MAX_SECTION_OPENER_TOP_GAP = 0.55
MIN_TEXT_RATIO_TO_MEDIAN = 0.40
MIN_SUBSTANTIVE_CHARACTERS = 20
MIN_SUSPICIOUS_TEXT_REGION_OVERLAP = 0.50

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
    parser.add_argument(
        "--page-reviews", type=Path,
        help="Potwierdzone układy stron powiązane z SHA-256 źródłowego PDF.",
    )
    return parser.parse_args()


REVIEW_LAYOUTS = {
    "blank", "dedication", "part_divider", "illustrated_opener",
    "visual_page", "mixed_visual", "table_page",
}


def validate_page_reviews(document, review):
    """Confirmations describe layout only; they never certify OCR semantics."""
    if review is None:
        return {}
    if not isinstance(review, dict) or review.get("schema_name") != "home-rag-page-reviews":
        raise ValueError("Expected home-rag-page-reviews")
    if type(review.get("schema_version")) is not int or review["schema_version"] != 1:
        raise ValueError("Unsupported page-review schema version")
    sha = (document.get("source") or {}).get("sha256")
    if not sha or review.get("source_sha256") != sha:
        raise ValueError("Page reviews/source SHA-256 mismatch")
    if not isinstance(review.get("pages"), list):
        raise ValueError("Page reviews must contain a pages list")
    numbers = {p["page_number"] for p in document.get("pages") or []}
    result = {}
    for entry in review["pages"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid page review")
        number = entry.get("page_number")
        if type(number) is not int or number not in numbers or number in result:
            raise ValueError("Unknown or duplicate reviewed page")
        if entry.get("layout") not in REVIEW_LAYOUTS:
            raise ValueError("Unknown reviewed layout")
        if not isinstance(entry.get("note"), str) or not entry["note"].strip():
            raise ValueError("Page review needs a nonempty note")
        if entry.get("confirmed") is not True:
            raise ValueError("Page review must be explicitly confirmed")
        for key in ("expected_tables", "expected_table_columns"):
            if key in entry and (type(entry[key]) is not int or entry[key] < 1):
                raise ValueError("Invalid table expectation")
        result[number] = dict(entry)
    return result


def reviewed_layout_issues(page_number, blocks, review):
    ids = [b["id"] for b in blocks]
    layout = review["layout"]
    # Blank confirmations must not hide extracted content, even short text.
    nonempty = [b for b in blocks if b.get("type") in {"picture", "table"}
                or (b.get("type") == "text" and normalize_text(b.get("text")))]
    tables = [b for b in blocks if b.get("type") == "table"]
    mismatch = None
    if layout == "blank" and nonempty:
        mismatch = "Confirmed blank page contains extracted content."
    elif layout in {"illustrated_opener", "visual_page", "mixed_visual", "part_divider"} and not any(b.get("type") == "picture" for b in blocks):
        mismatch = "Reviewed illustrated layout has no extracted picture block."
    elif layout == "dedication" and not any(b.get("type") == "text" and normalize_text(b.get("text")) for b in blocks):
        mismatch = "Reviewed dedication has no extracted text."
    elif layout == "table_page" and not tables:
        mismatch = "Reviewed table page has no extracted table."
    if "expected_tables" in review and len(tables) != review["expected_tables"]:
        mismatch = "Extracted table count differs from the confirmed layout."
    if "expected_table_columns" in review and any((b.get("data") or {}).get("columns") != review["expected_table_columns"] for b in tables):
        mismatch = "Extracted table columns differ from the confirmed layout."
    return [make_issue("REVIEW_LAYOUT_MISMATCH", mismatch, page_number, ids)] if mismatch else []


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


def bbox_overlap_ratio(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    left = max(first["left"], second["left"])
    top = max(first["top"], second["top"])
    right = min(first["right"], second["right"])
    bottom = min(first["bottom"], second["bottom"])

    intersection_width = max(0.0, right - left)
    intersection_height = max(0.0, bottom - top)
    intersection_area = (
        intersection_width * intersection_height
    )

    first_area = max(
        0.0,
        (first["right"] - first["left"])
        * (first["bottom"] - first["top"]),
    )
    second_area = max(
        0.0,
        (second["right"] - second["left"])
        * (second["bottom"] - second["top"]),
    )

    smaller_area = min(first_area, second_area)

    if smaller_area <= 0:
        return 0.0

    return intersection_area / smaller_area


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


def find_overlapping_text_regions(
    blocks: list[dict[str, Any]],
    page_number: int,
) -> list[dict[str, Any]]:
    findings = []

    for block in blocks:
        entries = []

        for provenance in provenance_for_page(
            block,
            page_number,
        ):
            bbox = normalized_bbox(provenance)

            if bbox is not None:
                entries.append(
                    {
                        "charspan": (
                            provenance.get("charspan")
                        ),
                        "bbox": bbox,
                    }
                )

        for index, first in enumerate(entries):
            for second in entries[index + 1:]:
                ratio = bbox_overlap_ratio(
                    first["bbox"],
                    second["bbox"],
                )

                if (
                    ratio
                    < MIN_SUSPICIOUS_TEXT_REGION_OVERLAP
                ):
                    continue

                findings.append(
                    {
                        "block_id": block["id"],
                        "first_charspan": (
                            first["charspan"]
                        ),
                        "second_charspan": (
                            second["charspan"]
                        ),
                        "overlap_ratio": round(
                            ratio,
                            6,
                        ),
                    }
                )

    return findings


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

    overlapping_text_regions = (
        find_overlapping_text_regions(
            content_blocks,
            page_number,
        )
    )

    return {
        "picture_blocks": sum(b.get("type") == "picture" for b in blocks),
        "table_blocks": sum(b.get("type") == "table" for b in blocks),
        "caption_blocks": sum(b.get("subtype") == "caption" for b in blocks),
        "tables": [{"block_id": b["id"], "rows": (b.get("data") or {}).get("rows"),
                    "columns": (b.get("data") or {}).get("columns"),
                    "cell_count": (b.get("data") or {}).get("cell_count")}
                   for b in blocks if b.get("type") == "table"],
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
        "overlapping_text_regions": (
            overlapping_text_regions
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

    overlapping = metrics[
        "overlapping_text_regions"
    ]

    if overlapping:
        affected_block_ids = sorted(
            {
                finding["block_id"]
                for finding in overlapping
            }
        )
        maximum_overlap = max(
            finding["overlap_ratio"]
            for finding in overlapping
        )

        issues.append(
            make_issue(
                code="OVERLAPPING_TEXT_REGIONS",
                message=(
                    "Text regions within the same block "
                    "overlap suspiciously; reading order "
                    "may be corrupted. Maximum overlap: "
                    f"{maximum_overlap:.3f}."
                ),
                page_number=page_number,
                block_ids=affected_block_ids,
            )
        )

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
    page_reviews: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reviews = validate_page_reviews(document, page_reviews)
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
        number = page["page_number"]
        review = reviews.get(number)
        # Keep existing role values for downstream normalizer/chunker compatibility.
        # Blank pages keep their role so a chapter path is not reset at every blank.
        if review and review["layout"] == "dedication":
            page["role"] = "front_matter"
        page["layout"] = review["layout"] if review else "unconfirmed"
        page["layout_review"] = review
        page["quality"] = page_quality(
            page_number=page["page_number"],
            role=page["role"],
            metrics=page["metrics"],
            block_ids=page["block_ids"],
            body_median=body_median,
        )
        if review:
            blocks = blocks_for_page(document, {"block_ids": page["block_ids"]})
            conflicts = reviewed_layout_issues(number, blocks, review)
            if conflicts:
                page["quality"]["issues"].extend(conflicts)
                if page["quality"]["status"] != "fail":
                    page["quality"]["status"] = "review"
            else:
                # Only layout heuristics are superseded. Overlap checks stay active.
                layout_codes = {"NO_BODY_TEXT", "LARGE_EMPTY_TOP_AREA", "LOW_TEXT_VOLUME"}
                page["quality"]["waived_layout_issues"] = [
                    i for i in page["quality"]["issues"] if i["code"] in layout_codes]
                page["quality"]["issues"] = [
                    i for i in page["quality"]["issues"] if i["code"] not in layout_codes]
                page["quality"]["status"] = "review" if page["quality"]["issues"] else "pass"

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "scope": "role_aware_page_layout",
        "limitations": [
            "PASS covers page-layout checks, not semantic OCR correctness or completeness.",
            "Picture blocks may contain several photos or charts; interpretation is pending.",
            "Table counts and columns do not certify cell contents or reading order.",
            "Text volume on multipage blocks is estimated using provenance geometry.",
        ],
        "source": document.get("source"),
        "configuration": {
            "page_reviews": page_reviews,
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
            "min_suspicious_text_region_overlap": (
                MIN_SUSPICIOUS_TEXT_REGION_OVERLAP
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

    review = None
    if arguments.page_reviews:
        review = json.loads(arguments.page_reviews.read_text(encoding="utf-8"))
    report = analyze_document(document, review)

    output_path = (
        arguments.output
        or arguments.document_path.with_name(
            "page_analysis.json"
        )
    )

    if output_path.resolve() in {arguments.document_path.resolve(),
                                  arguments.page_reviews.resolve() if arguments.page_reviews else None}:
        raise ValueError("Output must not overwrite document or page reviews")

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
            f"układ={page['layout']:18} "
            f"status={page['quality']['status']:6} "
            f"top={page['metrics']['top_text_position']} "
            f"znaki={page['metrics']['text_characters']} "
            f"issues={issue_codes}"
        )


if __name__ == "__main__":
    main()
