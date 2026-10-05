"""Local CPU embeddings with E5 prefixes, token guard and pinned model snapshot."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path

VERSION = '0.1.0'
MODEL = 'intfloat/multilingual-e5-small'
DIMENSION = 384
MAX_TOKENS = 512


def prepare_inputs(chunks):
    texts, seen = [], set()
    if not chunks:
        raise ValueError('No chunks supplied')
    for chunk in chunks:
        cid = chunk.get('chunk_id')
        if not cid or cid in seen:
            raise ValueError(f'Missing/duplicate chunk_id: {cid}')
        seen.add(cid)
        if chunk.get('schema_name') != 'home-rag-chunk':
            raise ValueError(f'Unsupported chunk schema: {cid}')
        if chunk.get('chunk_type') not in {'text', 'table'}:
            raise ValueError(f'Unsupported chunk type: {cid}')
        if not chunk.get('text') or not chunk['text'].strip():
            raise ValueError(f'Empty chunk: {cid}')
        for key in ('source_id', 'source_sha256', 'record_ids', 'block_ids', 'provenance'):
            if not chunk.get(key):
                raise ValueError(f'Missing {key}: {cid}')
        pages = chunk.get('page_numbers') or []
        if len(pages) != 1 or {p.get('page_number') for p in chunk['provenance']} != set(pages):
            raise ValueError(f'Invalid page provenance: {cid}')
        quality = chunk.get('quality') or {}
        if quality.get('page_status') != 'pass' or quality.get('content_status') == 'needs_vision':
            raise ValueError(f'Unapproved page/image: {cid}')
        section = ' > '.join(chunk.get('section_path') or [])
        context = section + '\n' if section else ''
        if chunk['chunk_type'] == 'table':
            headers = chunk.get('table_column_headers') or []
            values = [str(h.get('text') or '').strip() for h in headers]
            if any(values):
                context += 'Kolumny: ' + ' | '.join(values) + '\n'
        texts.append('passage: ' + context + chunk['text'])
    return texts


def count_tokens(chunks, tokenizer, max_tokens=MAX_TOKENS):
    texts = prepare_inputs(chunks)
    counts = []
    for text in texts:
        encoded = tokenizer(text, add_special_tokens=True, truncation=False,
                            return_attention_mask=False, return_token_type_ids=False)
        counts.append(len(encoded['input_ids']))
    report = {'chunks': len(chunks), 'max_allowed_tokens': max_tokens,
              'min_tokens': min(counts), 'max_tokens': max(counts),
              'overflow': [{'chunk_id': c['chunk_id'], 'tokens': n}
                           for c, n in zip(chunks, counts) if n > max_tokens],
              'token_counts': [{'chunk_id': c['chunk_id'], 'tokens': n}
                               for c, n in zip(chunks, counts)]}
    return texts, counts, report


def validate_vectors(vectors, expected_count, dimension=DIMENSION):
    if len(vectors) != expected_count:
        raise ValueError('Vector count differs from chunk count')
    result = []
    for vector in vectors:
        values = [float(value) for value in vector]
        if len(values) != dimension or not all(math.isfinite(value) for value in values):
            raise ValueError('Invalid vector dimension or non-finite values')
        norm = math.sqrt(sum(v * v for v in values))
        if not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4):
            raise ValueError(f'Embedding is not unit normalized: {norm}')
        result.append(values)
    return result


def prepare_model(model_dir, revision):
    from huggingface_hub import model_info, snapshot_download
    info = model_info(MODEL, revision=revision)
    sha = info.sha
    if not sha:
        raise ValueError('Unable to resolve model revision')
    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot = Path(snapshot_download(
        MODEL, revision=sha, cache_dir=str(model_dir / 'hub'),
        allow_patterns=['*.json', '*.txt', '*.model', '*.safetensors', 'pytorch_model.bin'],
        ignore_patterns=['onnx/*', 'openvino/*']))
    manifest = {'model_id': MODEL, 'revision': sha,
                'snapshot_relative_path': str(snapshot.relative_to(model_dir.resolve())),
                'dimension': DIMENSION, 'max_tokens': MAX_TOKENS}
    (model_dir / 'model_manifest.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('Model ready:', MODEL, 'revision:', sha)
    print('Cache:', model_dir)


def cached_model(model_dir):
    path = model_dir / 'model_manifest.json'
    if not path.is_file():
        raise ValueError('Model not prepared. Run --prepare-model first.')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('model_id') != MODEL or not manifest.get('revision'):
        raise ValueError('Invalid model manifest')
    snapshot = (model_dir / manifest['snapshot_relative_path']).resolve()
    if not snapshot.is_relative_to(model_dir.resolve()) or not snapshot.is_dir():
        raise ValueError('Invalid/incomplete local model snapshot')
    return snapshot, manifest


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_path', type=Path, nargs='?')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--model-dir', type=Path, default=Path('data/models/multilingual-e5-small'))
    parser.add_argument('--prepare-model', action='store_true')
    parser.add_argument('--revision', default='main', help='Only for initial model preparation')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    args.model_dir = args.model_dir.resolve()
    if args.prepare_model:
        if args.input_path or args.output or args.check_only:
            parser.error('--prepare-model is a separate operation')
        prepare_model(args.model_dir, args.revision)
        return
    if not args.input_path or not args.output:
        parser.error('input_path and --output are required')
    if args.batch_size < 1 or args.threads < 1:
        parser.error('batch-size and threads must be positive')
    report_path = args.report or args.output.with_name('embedding_report.json')
    if len({p.resolve() for p in (args.input_path, args.output, report_path)}) != 3:
        parser.error('Input/output/report paths must differ')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    snapshot, manifest = cached_model(args.model_dir)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True,
                                              trust_remote_code=False)
    raw = args.input_path.read_bytes()
    chunks = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    texts, counts, token_report = count_tokens(chunks, tokenizer)
    report = {'schema_name': 'home-rag-embedding-report', 'schema_version': 1,
              'embedder_version': VERSION, 'model': manifest,
              'input_sha256': hashlib.sha256(raw).hexdigest(),
              'device': 'cpu', 'normalized': True, 'passage_prefix': 'passage: ',
              'query_prefix': 'query: ', 'text_template_version': 1,
              'batch_size': args.batch_size, 'threads': args.threads,
              'packages': {name: importlib.metadata.version(name) for name in
                           ('torch', 'transformers', 'sentence-transformers', 'numpy', 'huggingface-hub')},
              'token_validation': token_report}
    report['status'] = 'token_overflow' if token_report['overflow'] else 'tokens_pass'
    save_json(report_path, report)
    print('Chunks:', len(chunks), 'tokens min/max:', token_report['min_tokens'], token_report['max_tokens'])
    if token_report['overflow']:
        for item in token_report['overflow']:
            print('OVERFLOW:', item['chunk_id'], item['tokens'])
        raise SystemExit('No embeddings generated. Rechunk with a smaller --max-chars; no text was truncated.')
    if args.check_only:
        print('PASS: token validation. No embeddings generated.')
        return
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    model = SentenceTransformer(str(snapshot), device='cpu', local_files_only=True,
                                trust_remote_code=False)
    model.default_prompt_name = None
    if model.max_seq_length < MAX_TOKENS:
        raise ValueError(f'Model sequence limit {model.max_seq_length} differs from expected 512')
    if model.get_sentence_embedding_dimension() != DIMENSION:
        raise ValueError('Unexpected embedding dimension')
    model.eval()
    vectors = model.encode(texts, batch_size=args.batch_size, normalize_embeddings=True,
                           convert_to_numpy=True, show_progress_bar=True, prompt='')
    values = validate_vectors(vectors, len(chunks))
    records = []
    for chunk, text, count, vector in zip(chunks, texts, counts, values):
        records.append({'schema_name': 'home-rag-embedding', 'schema_version': 1,
                        'chunk_id': chunk['chunk_id'], 'chunk': deepcopy(chunk),
                        'embedding_text': text, 'token_count': count,
                        'model_id': MODEL, 'model_revision': manifest['revision'],
                        'embedding_dimension': DIMENSION, 'normalized': True,
                        'embedding': vector})
    serialized = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False) + '\n' for r in records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding='utf-8')
    report.update(status='pass', vectors=len(records), dimension=DIMENSION,
                  output_sha256=hashlib.sha256(serialized.encode('utf-8')).hexdigest())
    save_json(report_path, report)
    print(f'PASS: {len(records)} vectors x {DIMENSION}; finite and unit normalized')
    print('Saved:', args.output)
    print('Report:', report_path)


if __name__ == '__main__':
    main()
