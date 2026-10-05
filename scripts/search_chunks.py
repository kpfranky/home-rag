"""Offline exact cosine retrieval over validated E5 embeddings."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

from embed_chunks import (DIMENSION, MAX_TOKENS, MODEL, cached_model,
                          prepare_inputs, save_json, validate_vectors)

VERSION = '0.1.0'


def load_index(path, report_path, manifest):
    raw = path.read_bytes()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if (report.get('schema_name') != 'home-rag-embedding-report'
            or report.get('schema_version') != 1 or report.get('status') != 'pass'
            or report.get('output_sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Invalid embedding report or embedding file checksum')
    if (report.get('model', {}).get('model_id') != MODEL
            or report['model'].get('revision') != manifest['revision']
            or report.get('dimension') != DIMENSION
            or report.get('normalized') is not True
            or report.get('passage_prefix') != 'passage: '
            or report.get('query_prefix') != 'query: '
            or report.get('text_template_version') != 1):
        raise ValueError('Embedding configuration differs from local query model')
    records = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if not records or report.get('vectors') != len(records):
        raise ValueError('Empty index or incorrect reported vector count')
    chunks = []
    for record in records:
        chunk = record.get('chunk') or {}
        if (record.get('schema_name') != 'home-rag-embedding'
                or record.get('schema_version') != 1
                or record.get('chunk_id') != chunk.get('chunk_id')
                or record.get('model_id') != MODEL
                or record.get('model_revision') != manifest['revision']
                or record.get('embedding_dimension') != DIMENSION
                or record.get('normalized') is not True):
            raise ValueError('Invalid embedding record or model mismatch')
        chunks.append(chunk)
    texts = prepare_inputs(chunks)
    if any(r.get('embedding_text') != text for r, text in zip(records, texts)):
        raise ValueError('Embedding text differs from stored chunk and context')
    vectors = validate_vectors([r.get('embedding') or [] for r in records], len(records))
    return records, vectors, report


def prepare_query(query, tokenizer):
    if not isinstance(query, str) or not query.strip():
        raise ValueError('Query must not be empty')
    text = 'query: ' + query.strip()
    count = len(tokenizer(text, add_special_tokens=True, truncation=False,
                          return_attention_mask=False,
                          return_token_type_ids=False)['input_ids'])
    if count > MAX_TOKENS:
        raise ValueError(f'Query has {count} tokens; limit is {MAX_TOKENS}. Shorten it.')
    return text, count


def rank_chunks(records, vectors, query_vector, top_k):
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError('top-k must be a positive integer')
    if not records or len(records) != len(vectors):
        raise ValueError('Index records and vectors must have equal nonzero counts')
    values = validate_vectors(vectors, len(records))
    query = validate_vectors([query_vector], 1)[0]
    scored = [(math.fsum(a * b for a, b in zip(vector, query)), record)
              for record, vector in zip(records, values)]
    scored.sort(key=lambda item: (-item[0], item[1]['chunk_id']))
    return [{'rank': rank, 'score': score, 'chunk_id': record['chunk_id'],
             'chunk': deepcopy(record['chunk'])}
            for rank, (score, record) in enumerate(scored[:top_k], 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_path', type=Path, help='embeddings.jsonl')
    parser.add_argument('--query', required=True)
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--embedding-report', type=Path)
    parser.add_argument('--model-dir', type=Path,
                        default=Path('data/models/multilingual-e5-small'))
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--output', type=Path, help='Optional search result JSON')
    args = parser.parse_args()
    if args.top_k < 1 or args.threads < 1:
        parser.error('top-k and threads must be positive')
    report_path = args.embedding_report or args.input_path.with_name('embedding_report.json')
    if args.output and args.output.resolve() in {
            args.input_path.resolve(), report_path.resolve(),
            (args.model_dir / 'model_manifest.json').resolve()}:
        parser.error('Output must differ from input, report and model manifest')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    snapshot, manifest = cached_model(args.model_dir.resolve())
    records, vectors, report = load_index(args.input_path, report_path, manifest)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True,
                                              trust_remote_code=False)
    query_text, token_count = prepare_query(args.query, tokenizer)
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    model = SentenceTransformer(str(snapshot), device='cpu', local_files_only=True,
                                trust_remote_code=False)
    model.default_prompt_name = None
    if (model.max_seq_length < MAX_TOKENS
            or model.get_sentence_embedding_dimension() != DIMENSION):
        raise ValueError('Unexpected query model dimension or sequence limit')
    model.eval()
    query_vector = model.encode([query_text], normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False,
                                prompt='')[0]
    results = rank_chunks(records, vectors, query_vector, args.top_k)
    output = {'schema_name': 'home-rag-search', 'schema_version': 1,
              'retriever_version': VERSION, 'query': args.query,
              'query_embedding_text': query_text, 'query_tokens': token_count,
              'model_id': MODEL, 'model_revision': manifest['revision'],
              'index_sha256': report['output_sha256'], 'index_chunks': len(records),
              'requested_top_k': args.top_k, 'metric': 'cosine_similarity',
              'results': results}
    if args.output:
        save_json(args.output, output)
    print(f'Query tokens: {token_count}; index chunks: {len(records)}')
    for result in results:
        chunk = result['chunk']
        print(f"\n#{result['rank']} score={result['score']:.6f} {result['chunk_id']}")
        print('Source:', chunk['source_id'], '| PDF pages:', chunk['page_numbers'])
        print('Section:', ' > '.join(chunk.get('section_path') or []))
        print(chunk['text'])
    if args.output:
        print('\nSaved:', args.output)


if __name__ == '__main__':
    main()
