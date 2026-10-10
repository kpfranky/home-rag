"""Refresh citation metadata without changing embedding inputs or vectors."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from normalize_document import page_metadata, printed_label


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def serialize(items):
    return ''.join(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n'
                   for item in items).encode('utf-8')


def refresh(document, records, report, input_raw, reviews=None):
    if document.get('schema_name') != 'home-rag-book':
        raise ValueError('Expected home-rag-book')
    if (report.get('schema_name') != 'home-rag-embedding-report'
            or report.get('status') != 'pass' or report.get('output_sha256') != sha(input_raw)
            or not records or report.get('vectors') != len(records)):
        raise ValueError('Invalid embedding report/checksum/count')
    source_sha = document['source']['sha256']
    metadata = page_metadata(document)
    if reviews is not None:
        if reviews.get('source_sha256') != source_sha:
            raise ValueError('Review/source SHA-256 mismatch')
        seen = set()
        for review in reviews['reviews']:
            number = review['page_number']
            if number in seen or number not in metadata:
                raise ValueError('Duplicate/unknown reviewed page')
            seen.add(number)
            item = metadata[number]
            if review['before'] != item['printed_page_labels'] or not review.get('reason'):
                raise ValueError('Review before/reason mismatch')
            labels = review['after']
            if not isinstance(labels, list) or len(labels) > 1 or any(
                    not isinstance(x, str) or printed_label(x) != x for x in labels):
                raise ValueError('Invalid reviewed labels')
            item['printed_page_labels'] = labels
            item['printed_page_label_status'] = 'verified_scan' if labels else 'verified_absent'
            item['printed_page_label_review'] = deepcopy(review)
    result, seen = [], set()
    for record in records:
        chunk = record['chunk']
        pages = chunk['page_numbers']
        if (record.get('schema_name') != 'home-rag-embedding'
                or chunk.get('source_sha256') != source_sha
                or len(pages) != 1 or pages[0] not in metadata
                or record['chunk_id'] != chunk['chunk_id'] or record['chunk_id'] in seen):
            raise ValueError('Invalid embedding/source/page/chunk identity')
        seen.add(record['chunk_id'])
        updated = deepcopy(record)
        for key in ('printed_page_labels', 'page_footer_raw', 'printed_page_label_status',
                    'printed_page_label_review'):
            updated['chunk'].pop(key, None)
        updated['chunk'].update(deepcopy(metadata[pages[0]]))
        result.append(updated)
    chunks_raw = serialize([r['chunk'] for r in result])
    output_raw = serialize(result)
    updated_report = deepcopy(report)
    updated_report.update(input_sha256=sha(chunks_raw), output_sha256=sha(output_raw))
    updated_report['metadata_update'] = {
        'version': '0.1.0', 'source_sha256': source_sha,
        'previous_input_sha256': report.get('input_sha256'),
        'previous_output_sha256': report['output_sha256'],
        'embedding_inputs_and_vectors_unchanged': True,
        'reviews': deepcopy(reviews),
    }
    return chunks_raw, output_raw, updated_report, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document', type=Path)
    parser.add_argument('--embeddings', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--page-label-reviews', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    raw = args.embeddings.read_bytes()
    records = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    chunks, embeddings, report, metadata = refresh(
        read(args.document), records, read(args.report), raw,
        read(args.page_label_reviews) if args.page_label_reviews else None)
    files = {'chunks.jsonl': chunks, 'embeddings.jsonl': embeddings,
             'embedding_report.json': (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode(),
             'page_metadata_report.json': (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode()}
    inputs = {x.resolve() for x in (args.document, args.embeddings, args.report)}
    if args.page_label_reviews:
        inputs.add(args.page_label_reviews.resolve())
    targets = [args.output_dir / name for name in files]
    if any(path.resolve() in inputs or path.exists() for path in targets):
        parser.error('Use a new output directory; existing files will not be overwritten')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.output_dir / name).write_bytes(content)
    print(f'Updated {len(records)} chunks; vectors and embedding inputs unchanged.')
    print(f'Output: {args.output_dir}')


if __name__ == '__main__':
    main()
