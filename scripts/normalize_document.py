"""Conservative, page-aware export of home-rag-book to JSONL (stdlib only)."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

VERSION = "0.1.1"
FURNITURE = {"page_header", "page_footer"}
LETTERS = r"[^\W\d_]"


def normalize_text(text):
    return " ".join(str(text or "").split())


def printed_label(text):
    """Accept only a whole Arabic or canonical Roman page label."""
    text = normalize_text(text)
    if re.fullmatch(r'[0-9]{1,6}', text):
        return text
    if (text and re.fullmatch(r'[IVXLCDMivxlcdm]+', text)
            and re.fullmatch(r'M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})', text.upper())):
        return text
    return None


def page_metadata(document):
    """Raw footer evidence is separate from accepted page-label candidates.

    Numeric OCR candidates are not automatically verified against the scan.
    PDF page indices are never substituted for printed labels.
    """
    blocks = {b['id']: b for b in document['blocks']}
    result = {}
    for page in document['pages']:
        raw = [{'block_id': bid, 'text': blocks[bid].get('text') or '',
                'provenance': deepcopy([p for p in blocks[bid].get('provenance') or []
                                        if p.get('page_number') == page['page_number']])}
               for bid in page['block_ids'] if blocks[bid].get('subtype') == 'page_footer']
        labels = list(dict.fromkeys(label for item in raw
                                   if (label := printed_label(item['text'])) is not None))
        result[page['page_number']] = {
            'printed_page_labels': labels if len(labels) == 1 else [],
            'page_footer_raw': raw,
            'printed_page_label_status': ('unverified_ocr' if len(labels) == 1
                                          else 'ambiguous' if labels else 'missing'),
        }
    return result


def join_split_word(left, right):
    left, right = normalize_text(left), normalize_text(right)
    if not re.search(rf"{LETTERS}+-$", left):
        return None
    word = re.match(rf"^({LETTERS}+)(.*)$", right, re.DOTALL)
    if not word or not word[1][0].islower():
        return None
    return left[:-1] + right


def text_fragments(block):
    """Validate original character offsets BEFORE whitespace normalization."""
    text = block.get("text") or ""
    pages = sorted(set(block.get("page_numbers") or []))
    provenance = block.get("provenance") or []
    if not pages or {p.get("page_number") for p in provenance} != set(pages):
        raise ValueError(f"Missing page provenance: {block['id']}")
    if len(pages) == 1:
        return {pages[0]: text}
    spans = []
    for p in provenance:
        span = p.get("charspan")
        if not (isinstance(span, list) and len(span) == 2
                and all(type(v) is int for v in span)
                and 0 <= span[0] < span[1] <= len(text)):
            raise ValueError(f"Invalid multipage charspan: {block['id']}")
        spans.append((span[0], span[1], p["page_number"]))
    spans.sort()
    end = 0
    last_page = -1
    fragments = {page: [] for page in pages}
    for start, stop, page in spans:
        if start < end or text[end:start].strip() or page < last_page:
            raise ValueError(f"Overlapping/uncovered/unordered charspan: {block['id']}")
        fragments[page].append(text[start:stop])
        end, last_page = stop, page
    if text[end:].strip():
        raise ValueError(f"Uncovered trailing text: {block['id']}")
    return {page: " ".join(parts) for page, parts in fragments.items()}


def export_document(document, analysis, source_id=None, join_hyphens=True):
    if document.get("schema_name") != "home-rag-book":
        raise ValueError("Expected home-rag-book document")
    if analysis.get("schema_name") != "home-rag-page-analysis":
        raise ValueError("Expected home-rag-page-analysis report")
    sha = (document.get("source") or {}).get("sha256")
    if not sha or sha != (analysis.get("source") or {}).get("sha256"):
        raise ValueError("Document/report source SHA-256 mismatch")
    pages = document["pages"]
    if len({p['page_number'] for p in pages}) != len(pages):
        raise ValueError("Duplicate document pages")
    reports = {p["page_number"]: p for p in analysis["pages"]}
    if len(reports) != len(analysis["pages"]) or set(reports) != {p['page_number'] for p in pages}:
        raise ValueError("Document/report page sets differ")
    blocks = {b['id']: b for b in document['blocks']}
    if len(blocks) != len(document['blocks']):
        raise ValueError("Duplicate block ids")
    source_id = source_id or Path(document['source']['filename']).stem.removesuffix('_ocr')
    records, skipped = [], []
    section = []
    previous_role = None
    fragments_cache = {}
    metadata = page_metadata(document)
    for page in sorted(pages, key=lambda p: p['page_number']):
        number = page['page_number']
        report = reports[number]
        role = report['role']
        if role != previous_role:
            section = []
        previous_role = role
        if report['quality']['status'] != 'pass':
            skipped.append(number)
            section = []
            continue
        ids = page['block_ids']
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate page block references: {number}")
        previous = None
        for position, block_id in enumerate(ids):
            block = blocks[block_id]
            kind, subtype = block['type'], block.get('subtype')
            if kind == 'group':
                previous = None
                continue
            if subtype in FURNITURE:
                previous = None
                continue
            if kind not in {'text', 'table', 'picture'}:
                raise ValueError(f"Unsupported block type: {kind} ({block_id})")
            provenance = deepcopy([p for p in block.get('provenance') or []
                                   if p.get('page_number') == number])
            if not provenance:
                raise ValueError(f"Missing provenance: {block_id}, page {number}")
            if kind == 'text':
                if block_id not in fragments_cache:
                    fragments_cache[block_id] = text_fragments(block)
                text = normalize_text(fragments_cache[block_id][number])
                if not text:
                    previous = None
                    continue
                if subtype == 'section_header' and role in {'body', 'document_index'}:
                    # No heading level in this schema: maintain a flat current heading.
                    section = [text]
            record = {
                'schema_version': 1,
                'normalizer_version': VERSION,
                'record_id': f'{source_id}:p{number:04d}:b{position:04d}',
                'source_id': source_id,
                'source_sha256': sha,
                'record_type': kind,
                'subtype': subtype,
                'page_numbers': [number],
                'page_role': role,
                **deepcopy(metadata[number]),
                'block_ids': [block_id],
                'section_path': section.copy(),
                'provenance': provenance,
                'relations': {block_id: deepcopy(block.get('relations') or {})},
                'normalization_actions': [],
                'quality': {'page_status': 'pass', 'content_status': 'not_semantically_validated'},
            }
            if kind == 'text':
                record['text'] = text
                record['source_fragments'] = [{'block_id': block_id, 'page_number': number,
                                             'text': fragments_cache[block_id][number]}]
                if (join_hyphens and previous and previous['record_type'] == 'text'
                        and previous['subtype'] == subtype == 'text'
                        and previous['section_path'] == section
                        and len(block.get('page_numbers') or []) == 1
                        and previous.pop('_single_page', False)):
                    joined = join_split_word(previous['text'], text)
                    if joined is not None:
                        previous['normalization_actions'].append({
                            'type': 'join_line_break_hyphen',
                            'before': [previous['text'], text], 'after': joined,
                            'block_ids': previous['block_ids'][-1:] + [block_id],
                            'requires_review': True,
                        })
                        previous['text'] = joined
                        previous['block_ids'].append(block_id)
                        previous['provenance'].extend(provenance)
                        previous['source_fragments'].extend(record['source_fragments'])
                        previous['relations'].update(record['relations'])
                        previous['quality']['content_status'] = 'review_normalization'
                        previous['_single_page'] = True
                        continue
                record['_single_page'] = len(block.get('page_numbers') or []) == 1
            elif kind == 'table':
                # Preserve offsets, spans, headers and original cell text verbatim.
                record['table_data'] = deepcopy(block.get('data'))
                record['asset_path'] = block.get('asset')
            else:
                record['asset_path'] = block.get('asset')
                record['picture_data'] = deepcopy(block.get('data'))
                record['quality']['content_status'] = 'needs_vision'
            records.append(record)
            previous = record
    for record in records:
        record.pop('_single_page', None)
    return records, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document_path', type=Path)
    parser.add_argument('--analysis', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-id')
    parser.add_argument('--no-join-hyphens', action='store_true')
    args = parser.parse_args()
    if args.output.resolve() in {args.document_path.resolve(), args.analysis.resolve()}:
        parser.error('Output must not overwrite an input')
    document = json.loads(args.document_path.read_text(encoding='utf-8'))
    analysis = json.loads(args.analysis.read_text(encoding='utf-8'))
    records, skipped = export_document(document, analysis, args.source_id, not args.no_join_hyphens)
    serialized = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding='utf-8')
    print(f'Zapisano: {args.output}; rekordy: {len(records)}; pominięte strony: {skipped}')
    print('SHA-256:', hashlib.sha256(serialized.encode('utf-8')).hexdigest())
    print('Połączenia wymagające przeglądu:', sum(len(r['normalization_actions']) for r in records))


if __name__ == '__main__':
    main()
