"""Deterministic page-aware chunking of normalized Home RAG JSONL (stdlib)."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

VERSION = '0.1.0'
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


def build_chunks(records, max_chars=1200, roles=('body',), allow_review=False):
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError('max_chars must be a positive integer')
    if not roles or not set(roles) <= set(ROLES):
        raise ValueError('Unknown or empty page roles')
    chunks, skipped, seen = [], [], set()
    stats = Counter()
    config = {'max_chars': max_chars, 'roles': sorted(set(roles)),
              'allow_review_normalization': allow_review, 'overlap_chars': 0}
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
        if reason:
            stats[reason] += 1
            skipped.append({'record_id': rid, 'reason': reason})
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
              'skipped_counts': dict(stats), 'skipped_records': skipped}
    return chunks, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_path', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--max-chars', type=int, default=1200)
    parser.add_argument('--roles', nargs='+', choices=ROLES, default=['body'])
    parser.add_argument('--allow-review-normalization', action='store_true')
    args = parser.parse_args()
    report_path = args.report or args.output.with_name('chunk_report.json')
    paths = [args.input_path.resolve(), args.output.resolve(), report_path.resolve()]
    if len(set(paths)) != 3:
        parser.error('Input, output and report must have different paths')
    records = [json.loads(line) for line in args.input_path.read_text(encoding='utf-8').splitlines()
               if line.strip()]
    chunks, report = build_chunks(records, args.max_chars, args.roles,
                                  args.allow_review_normalization)
    payload = ''.join(json.dumps(c, ensure_ascii=False, sort_keys=True) + '\n' for c in chunks)
    report['input_sha256'] = hashlib.sha256(args.input_path.read_bytes()).hexdigest()
    report['output_sha256'] = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding='utf-8')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                           encoding='utf-8')
    print(f'Zapisano: {args.output}; chunki: {len(chunks)}; typy: {report["by_type"]}')
    print(f'Pominięte: {report["skipped_counts"]}; ponad limit: {report["oversized_chunks"]}')
    print('SHA-256:', report['output_sha256'])
    print('Raport:', report_path)


if __name__ == '__main__':
    main()
