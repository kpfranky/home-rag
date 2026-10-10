"""Deterministic page-aware chunking of normalized Home RAG JSONL (stdlib)."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

VERSION = '0.2.1'
PICTURE_TEXT_COVERAGE = 0.90
ROLES = ('body', 'front_matter', 'document_index', 'legal_notice')
ABBREVIATIONS = {'np', 'mgr', 'dr', 'prof', 'inż', 'łac', 'itd', 'itp', 'm.in'}


def text_spans(text, max_chars):
    """Partition original text without changing/dropping characters."""
    if max_chars < 1:
        raise ValueError('max_chars must be positive')
    start = 0
    while start < len(text):
        limit = min(start + max_chars, len(text))
        if limit == len(text):
            yield start, limit, 'end'
            break
        minimum = start + max_chars // 2
        sentences = []
        for match in re.finditer(r'[.!?][”\"\u2019)]*\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9])', text[start:limit]):
            end = start + match.end()
            before = text[start:start + match.start()]
            last = re.search(r'([\w.]+)$', before)
            if match.group()[0] == '.' and last and (
                    last[1].lower() in ABBREVIATIONS or len(last[1]) == 1):
                continue
            if end >= minimum:
                sentences.append(end)
        if sentences:
            end, reason = sentences[-1], 'sentence'
        else:
            whitespace = [start + m.end() for m in re.finditer(r'\s+', text[start:limit])]
            if whitespace:
                end, reason = whitespace[-1], 'word'
            else:
                end, reason = limit, 'hard'
        yield start, end, reason
        start = end


def table_units(data):
    """Return row groups whose boundaries never cut a vertically merged cell."""
    rows, columns = data.get('rows'), data.get('columns')
    if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
        raise ValueError('Invalid table dimensions')
    cells = data.get('cells')
    if not isinstance(cells, list):
        raise ValueError('Missing table cells')
    cuts = set(range(1, rows))
    for cell in cells:
        r0, r1 = cell.get('start_row_offset_idx'), cell.get('end_row_offset_idx')
        c0, c1 = cell.get('start_col_offset_idx'), cell.get('end_col_offset_idx')
        if not (all(type(v) is int for v in (r0, r1, c0, c1))
                and 0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= columns):
            raise ValueError('Invalid cell offsets')
        cuts.difference_update(range(r0 + 1, r1))
    edges = [0] + sorted(cuts) + [rows]
    return [(left, right, [i for i, cell in enumerate(cells)
                           if left <= cell['start_row_offset_idx'] < right])
            for left, right in zip(edges, edges[1:])]


def render_cells(data, indices):
    # Explicit coordinates preserve association without guessing missing cells.
    lines = []
    for index in sorted(indices, key=lambda i: (
            data['cells'][i]['start_row_offset_idx'],
            data['cells'][i]['start_col_offset_idx'], i)):
        cell = data['cells'][index]
        value = ' '.join(str(cell.get('text') or '').split())
        lines.append(
            f"r{cell['start_row_offset_idx'] + 1} "
            f"c{cell['start_col_offset_idx'] + 1}: {value}"
        )
    return '\n'.join(lines)


def table_groups(data, max_chars):
    pending = None
    for left, right, indices in table_units(data):
        if pending is not None:
            combined = pending[2] + indices
            if len(render_cells(data, combined)) <= max_chars:
                pending = (pending[0], right, combined)
                continue
            yield pending
        pending = (left, right, indices)
    if pending is not None:
        yield pending


def valid_box(entry):
    value = entry.get('bbox_normalized')
    if not isinstance(value, dict):
        return None
    try:
        coords = [value[k] for k in ('left', 'top', 'right', 'bottom')]
        if any(isinstance(v, bool) for v in coords):
            return None
        left, top, right, bottom = map(float, coords)
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (left, top, right, bottom)):
            return None
        if left >= right or top >= bottom:
            return None
        return left, top, right, bottom
    except (KeyError, TypeError, ValueError):
        return None


def picture_text_candidates(records):
    """Quarantine plain OCR text geometrically contained in a picture region.

    This does not interpret charts, repair labels or associate values with series.
    Captions and headings remain eligible. No source record is modified.
    """
    pictures = {}
    for record in records:
        if record.get('record_type') != 'picture':
            continue
        key = (record.get('source_id'), record.get('source_sha256'))
        for entry in record.get('provenance') or []:
            box = valid_box(entry)
            if box:
                pictures.setdefault((*key, entry.get('page_number')), []).append(
                    (record.get('record_id'), box))
    found = {}
    uncertain = []
    for record in records:
        if record.get('record_type') != 'text' or record.get('subtype') != 'text':
            continue
        entries = record.get('provenance') or []
        matches, fractions = set(), []
        missing_box = False
        partial = False
        same_page_picture = False
        for entry in entries:
            key = (record.get('source_id'), record.get('source_sha256'), entry.get('page_number'))
            candidates = pictures.get(key, [])
            same_page_picture |= bool(candidates)
            box = valid_box(entry)
            if box is None:
                missing_box = True
                continue
            left, top, right, bottom = box
            area = (right - left) * (bottom - top)
            maximum = 0.0
            for rid, picture in candidates:
                pl, pt, pr, pb = picture
                intersection = max(0.0, min(right, pr) - max(left, pl)) * max(0.0, min(bottom, pb) - max(top, pt))
                ratio = intersection / area
                maximum = max(maximum, ratio)
                if ratio >= PICTURE_TEXT_COVERAGE:
                    matches.add(rid)
            fractions.append(maximum)
            partial |= 0 < maximum < PICTURE_TEXT_COVERAGE
        if entries and not missing_box and fractions and min(fractions) >= PICTURE_TEXT_COVERAGE:
            found[record.get('record_id')] = {
                'picture_record_ids': sorted(matches),
                'minimum_text_area_coverage': round(min(fractions), 6),
            }
        elif partial or (missing_box and same_page_picture):
            uncertain.append({'record_id': record.get('record_id'),
                              'reason': 'partial_picture_overlap_or_missing_bbox'})
    return found, uncertain


def validate_record_reviews(records, review, input_sha256, uncertain):
    if review is None:
        return {}
    if not isinstance(review, dict) or review.get('schema_name') != 'home-rag-visual-text-reviews':
        raise ValueError('Expected home-rag-visual-text-reviews')
    if type(review.get('schema_version')) is not int or review['schema_version'] != 1:
        raise ValueError('Unsupported record-review schema')
    if not input_sha256 or review.get('input_sha256') != input_sha256:
        raise ValueError('Record reviews/normalized input SHA-256 mismatch')
    entries = review.get('records')
    if not isinstance(entries, list):
        raise ValueError('Record review must contain records list')
    allowed = {x['record_id'] for x in uncertain}
    known = {r['record_id']: r for r in records}
    decisions = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid record review')
        rid = entry.get('record_id')
        if not isinstance(rid, str) or rid not in allowed or rid in decisions:
            raise ValueError('Unknown, non-candidate or duplicate reviewed record')
        if entry.get('decision') not in {'keep', 'defer_to_vision'}:
            raise ValueError('Unknown record-review decision')
        if not isinstance(entry.get('note'), str) or not entry['note'].strip():
            raise ValueError('Record-review note required')
        if known[rid].get('record_type') != 'text' or known[rid].get('subtype') != 'text':
            raise ValueError('Only plain text candidates can be reviewed')
        decisions[rid] = deepcopy(entry)
    if set(decisions) != allowed:
        raise ValueError('Record reviews must resolve every pending candidate')
    return decisions


def build_chunks(records, max_chars=1200, roles=('body',), allow_review=False,
                 exclude_picture_text=False, record_reviews=None, input_sha256=None):
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError('max_chars must be a positive integer')
    if not roles or not set(roles) <= set(ROLES):
        raise ValueError('Unknown or empty page roles')
    if type(exclude_picture_text) is not bool:
        raise ValueError('exclude_picture_text must be a boolean')
    candidates, uncertain = picture_text_candidates(records) if exclude_picture_text else ({}, [])
    if record_reviews is not None and not exclude_picture_text:
        raise ValueError('Record reviews require --exclude-picture-text')
    decisions = validate_record_reviews(records, record_reviews, input_sha256, uncertain)
    unresolved = [x for x in uncertain if x['record_id'] not in decisions]
    chunks, skipped, seen = [], [], set()
    stats = Counter()
    config = {'max_chars': max_chars, 'roles': sorted(set(roles)),
              'allow_review_normalization': allow_review, 'overlap_chars': 0,
              'exclude_picture_text': exclude_picture_text,
              'picture_text_min_coverage': PICTURE_TEXT_COVERAGE if exclude_picture_text else None,
              'record_reviews_sha256': hashlib.sha256(json.dumps(record_reviews, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest() if record_reviews is not None else None}
    for record in records:
        rid = record.get('record_id')
        if not rid or rid in seen:
            raise ValueError(f'Missing/duplicate record id: {rid}')
        seen.add(rid)
        for key in ('source_id', 'source_sha256', 'block_ids', 'provenance'):
            if not record.get(key):
                raise ValueError(f'Missing {key}: {rid}')
        pages = record.get('page_numbers') or []
        if len(pages) != 1 or type(pages[0]) is not int:
            raise ValueError(f'Expected one PDF page per normalized record: {rid}')
        if {p.get('page_number') for p in record['provenance']} != set(pages):
            raise ValueError(f'Provenance page mismatch: {rid}')
        kind = record.get('record_type')
        if kind not in {'text', 'table', 'picture'}:
            raise ValueError(f'Unsupported record type: {kind}')
        quality = record.get('quality') or {}
        reason = None
        if kind == 'picture':
            reason = 'picture_needs_separate_processing'
        elif record.get('page_role') not in roles:
            reason = 'page_role_excluded'
        elif quality.get('page_status') != 'pass':
            reason = 'page_not_pass'
        elif (quality.get('content_status') == 'review_normalization'
              or record.get('normalization_actions')) and not allow_review:
            reason = 'normalization_requires_review'
        elif record.get('subtype') == 'section_header':
            reason = 'heading_used_as_context'
        elif rid in decisions and decisions[rid]['decision'] == 'defer_to_vision':
            reason = 'reviewed_text_pending_vision'
        elif rid in candidates:
            reason = 'text_inside_picture_pending_vision'
        if reason:
            stats[reason] += 1
            skipped_entry = {'record_id': rid, 'reason': reason}
            if reason == 'text_inside_picture_pending_vision':
                skipped_entry.update(candidates[rid])
            if rid in decisions:
                skipped_entry['record_review'] = deepcopy(decisions[rid])
            skipped.append(skipped_entry)
            continue
        base = {key: deepcopy(record.get(key)) for key in (
            'source_id', 'source_sha256', 'page_numbers', 'printed_page_labels',
            'block_ids', 'section_path', 'page_role', 'provenance', 'relations', 'quality')}
        base.update(schema_name='home-rag-chunk', schema_version=1,
                    chunker_version=VERSION, record_ids=[rid], chunk_type=kind,
                    configuration=config.copy(), citation_precision='page_and_block')
        pieces = []
        if kind == 'text':
            text = record.get('text')
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f'Missing text: {rid}')
            for start, end, boundary in text_spans(text, max_chars):
                pieces.append({'text': text[start:end],
                               'text_span': {'record_id': rid, 'start': start, 'end': end},
                               'split_boundary': boundary, 'oversized': False})
        else:
            data = record.get('table_data')
            if not isinstance(data, dict):
                raise ValueError(f'Missing table_data: {rid}')
            headers = [{'cell_index': i, 'text': cell.get('text') or ''}
                       for i, cell in enumerate(data.get('cells') or [])
                       if cell.get('column_header')]
            for left, right, indices in table_groups(data, max_chars):
                text = render_cells(data, indices)
                pieces.append({'text': text,
                               'table_row_range': [left, right],
                               'table_cell_indices': indices,
                               'table_dimensions': {'rows': data['rows'], 'columns': data['columns']},
                               'table_cells': deepcopy([data['cells'][i] for i in indices]),
                               'table_column_headers': headers,
                               'oversized': len(text) > max_chars})
        for index, piece in enumerate(pieces):
            chunk = deepcopy(base)
            chunk.update(piece)
            digest = hashlib.sha256(json.dumps(chunk, ensure_ascii=False,
                                               sort_keys=True).encode('utf-8')).hexdigest()[:24]
            chunk['chunk_id'] = f'{record["source_id"]}:p{pages[0]:04d}:c{digest}'
            chunk['part_index'] = index
            chunks.append(chunk)
    report = {'schema_name': 'home-rag-chunk-report', 'schema_version': 1,
              'chunker_version': VERSION, 'configuration': config,
              'input_records': len(records), 'chunks': len(chunks),
              'by_type': dict(Counter(c['chunk_type'] for c in chunks)),
              'oversized_chunks': sum(c['oversized'] for c in chunks),
              'hard_splits': sum(c.get('split_boundary') == 'hard' for c in chunks),
              'skipped_counts': dict(stats), 'skipped_records': skipped,
              'visual_text_review_records': unresolved,
              'record_reviews': deepcopy(record_reviews),
              'resolved_visual_text_reviews': list(decisions.values()),
              'limitations': [
                  'Geometry filtering does not interpret charts or certify OCR correctness.',
                  'Captions remain source text; they do not validate visual conclusions.',
                  'Partially overlapping text is retained and listed for manual review.',
              ]}
    return chunks, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_path', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--max-chars', type=int, default=1200)
    parser.add_argument('--roles', nargs='+', choices=ROLES, default=['body'])
    parser.add_argument('--allow-review-normalization', action='store_true')
    parser.add_argument('--exclude-picture-text', action='store_true',
                        help='Odłóż tekst wewnątrz obrazów do analizy wizualnej (pokrycie >=90%).')
    parser.add_argument('--record-reviews', type=Path,
                        help='Decyzje dla tekstów na granicach obrazów, powiązane z SHA-256 normalizacji.')
    args = parser.parse_args()
    report_path = args.report or args.output.with_name('chunk_report.json')
    paths = [args.input_path.resolve(), args.output.resolve(), report_path.resolve()]
    if args.record_reviews and args.record_reviews.resolve() in {args.output.resolve(), report_path.resolve()}:
        parser.error('Output/report must not overwrite record reviews')
    if len(set(paths)) != 3:
        parser.error('Input, output and report must have different paths')
    input_bytes = args.input_path.read_bytes()
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    review = json.loads(args.record_reviews.read_text(encoding='utf-8')) if args.record_reviews else None
    records = [json.loads(line) for line in input_bytes.decode('utf-8').splitlines()
               if line.strip()]
    chunks, report = build_chunks(records, args.max_chars, args.roles,
                                  args.allow_review_normalization, args.exclude_picture_text,
                                  review, input_sha256)
    payload = ''.join(json.dumps(c, ensure_ascii=False, sort_keys=True) + '\n' for c in chunks)
    report['input_sha256'] = input_sha256
    report['output_sha256'] = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding='utf-8')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                           encoding='utf-8')
    print(f'Zapisano: {args.output}; chunki: {len(chunks)}; typy: {report["by_type"]}')
    print(f'Pominięte: {report["skipped_counts"]}; ponad limit: {report["oversized_chunks"]}')
    print('SHA-256:', report['output_sha256'])
    print('Teksty do kontroli granic obrazów:', len(report['visual_text_review_records']))
    print('Raport:', report_path)


if __name__ == '__main__':
    main()
