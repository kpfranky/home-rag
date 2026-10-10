"""Apply scan-bound table corrections to a copy of existing chunks (stdlib)."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from chunk_document import table_groups, render_cells


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def apply_review(document, chunks, review, max_table_chars=None):
    if document.get('schema_name') != 'home-rag-book' or review.get('schema_name') != 'home-rag-table-review':
        raise ValueError('Unexpected document/review schema')
    source_sha = document['source']['sha256']
    if review.get('source_sha256') != source_sha:
        raise ValueError('Review belongs to a different scan')
    blocks = [b for b in document['blocks'] if b['id'] == review['block_id']]
    if len(blocks) != 1 or blocks[0]['type'] != 'table' or blocks[0]['page_numbers'] != [review['page_number']]:
        raise ValueError('Table identity/page mismatch')
    original = blocks[0]['data']
    if digest(original) != review['table_data_sha256']:
        raise ValueError('Original table data checksum mismatch')
    if any(c.get('column_header') for c in original['cells']):
        raise ValueError('Review expects missing extracted column headers')
    headers = review['column_headers']
    if (len(headers) != original['columns'] or
            any(h.get('column_index') != i or not isinstance(h.get('text'), str) or not h['text'].strip()
                for i, h in enumerate(headers)) or not review.get('evidence')):
        raise ValueError('Incomplete ordered headers/evidence')
    data = deepcopy(original)
    edited = set()
    for edit in review['cell_edits']:
        key = (edit['row_index'], edit['column_index'])
        if key in edited:
            raise ValueError('Duplicate cell correction')
        edited.add(key)
        matched = [c for c in data['cells'] if
                   (c['start_row_offset_idx'], c['start_col_offset_idx']) == key]
        if (len(matched) != 1 or matched[0]['text'] != edit['before']
                or not isinstance(edit.get('after'), str) or not edit.get('reason')):
            raise ValueError('Cell correction before/coordinate/reason mismatch')
        matched[0]['text'] = edit['after']
    ids, targets, seen_cells = set(), [], []
    for chunk in chunks:
        cid = chunk.get('chunk_id')
        if not cid or cid in ids:
            raise ValueError('Missing/duplicate chunk ID')
        ids.add(cid)
        if review['block_id'] not in (chunk.get('block_ids') or []):
            continue
        if (chunk.get('chunk_type') != 'table' or chunk.get('source_sha256') != source_sha
                or chunk.get('page_numbers') != [review['page_number']]
                or chunk['block_ids'] != [review['block_id']]
                or chunk.get('table_column_headers')):
            raise ValueError('Unexpected target table chunk identity/headers')
        indices = chunk['table_cell_indices']
        if (not indices or any(type(i) is not int or not 0 <= i < len(original['cells']) for i in indices)
                or chunk['table_cells'] != [original['cells'][i] for i in indices]
                or chunk['text'] != render_cells(original, indices)):
            raise ValueError('Chunk cells/text differ from original table')
        seen_cells.extend(indices)
        targets.append(chunk)
    if not targets or sorted(seen_cells) != list(range(len(original['cells']))):
        raise ValueError('Table chunks must cover every original cell exactly once')
    template = targets[0]
    if any(c['configuration'] != template['configuration'] or c['record_ids'] != template['record_ids']
           for c in targets):
        raise ValueError('Mixed table chunk configurations/records')
    maximum = template['configuration']['max_chars']
    if max_table_chars is not None:
        if type(max_table_chars) is not int or max_table_chars < 1:
            raise ValueError('max_table_chars must be a positive integer')
        maximum = min(maximum, max_table_chars)
    prefix = 'Kolumny: ' + ' | '.join(f"c{i+1}: {h['text']}" for i, h in enumerate(headers)) + '\n'
    if type(maximum) is not int or maximum <= len(prefix):
        raise ValueError('Chunk size cannot accommodate header context')
    new = []
    for part, (left, right, indices) in enumerate(table_groups(data, maximum - len(prefix))):
        chunk = deepcopy(template)
        for key in ('chunk_id', 'text', 'table_row_range', 'table_cell_indices', 'table_cells',
                    'table_column_headers', 'part_index', 'oversized'):
            chunk.pop(key, None)
        text = prefix + render_cells(data, indices)
        chunk.update(text=text, table_row_range=[left, right], table_cell_indices=indices,
                     table_cells=deepcopy([data['cells'][i] for i in indices]),
                     table_column_headers=deepcopy(headers), part_index=part,
                     oversized=len(text) > maximum,
                     table_review=deepcopy(review),
                     table_review_max_chars=maximum,
                     table_review_original_chunk_ids=[c['chunk_id'] for c in targets])
        chunk['chunk_id'] = (f"{chunk['source_id']}:p{review['page_number']:04d}:c"
                             + digest(chunk)[:24])
        new.append(chunk)
    result, inserted = [], False
    target_ids = {c['chunk_id'] for c in targets}
    for chunk in chunks:
        if chunk['chunk_id'] in target_ids:
            if not inserted:
                result.extend(new)
                inserted = True
        else:
            result.append(deepcopy(chunk))
    if len({c['chunk_id'] for c in result}) != len(result):
        raise ValueError('Output chunk identity collision')
    audit = {'schema_name': 'home-rag-table-review-report', 'version': '0.1.0',
             'review': deepcopy(review), 'table_data_original': deepcopy(original),
             'table_data_corrected': data,
             'original_chunk_ids': [c['chunk_id'] for c in targets],
             'corrected_chunk_ids': [c['chunk_id'] for c in new],
             'input_chunks': len(chunks), 'output_chunks': len(result),
             'other_chunks_unchanged': True,
             'oversized_chunks': sum(c.get('oversized', False) for c in new),
             'requires_new_embeddings': True}
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('chunks', type=Path)
    parser.add_argument('--document', required=True, type=Path)
    parser.add_argument('--review', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--max-table-chars', type=int,
                        help='Optional smaller size for reviewed table chunks')
    args = parser.parse_args()
    raw = args.chunks.read_bytes()
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    chunks, audit = apply_review(read(args.document),
        [json.loads(line) for line in raw.decode().splitlines() if line.strip()], read(args.review),
        args.max_table_chars)
    content = ''.join(json.dumps(c, ensure_ascii=False, sort_keys=True) + '\n' for c in chunks).encode()
    audit['input_chunks_sha256'] = hashlib.sha256(raw).hexdigest()
    audit['output_chunks_sha256'] = hashlib.sha256(content).hexdigest()
    outputs = [args.output_dir / 'chunks.jsonl', args.output_dir / 'table_review_report.json']
    inputs = {p.resolve() for p in (args.chunks, args.document, args.review)}
    if any(p.exists() or p.resolve() in inputs for p in outputs):
        parser.error('Use a new output directory; inputs/existing files will not be overwritten')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs[0].write_bytes(content)
    outputs[1].write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"PASS: {audit['input_chunks']} -> {audit['output_chunks']} chunks; "
          f"table {len(audit['original_chunk_ids'])} -> {len(audit['corrected_chunk_ids'])} chunks")
    print(f"Other chunks unchanged; oversized table chunks: {audit['oversized_chunks']}")
    print(f'Output: {args.output_dir}; new embeddings required')


if __name__ == '__main__':
    main()
