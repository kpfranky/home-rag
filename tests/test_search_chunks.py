import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from embed_chunks import DIMENSION, MODEL, prepare_inputs
from search_chunks import load_index, prepare_query, rank_chunks


def vector(x=1.0, y=0.0):
    return [x, y] + [0.0] * (DIMENSION - 2)


def record(cid='a'):
    chunk = {'schema_name': 'home-rag-chunk', 'schema_version': 1,
             'chunk_id': cid, 'chunk_type': 'text', 'text': 'Tekst źródłowy.',
             'source_id': 'book', 'source_sha256': 'abc', 'record_ids': ['r1'],
             'block_ids': ['#/texts/1'], 'page_numbers': [11],
             'printed_page_labels': ['17'], 'section_path': ['Wstęp'],
             'quality': {'page_status': 'pass'},
             'provenance': [{'page_number': 11, 'charspan': [0, 15]}],
             'text_span': {'start': 0, 'end': 15}}
    return {'schema_name': 'home-rag-embedding', 'schema_version': 1,
            'chunk_id': cid, 'chunk': chunk, 'embedding': vector(),
            'model_id': MODEL, 'model_revision': 'pinned',
            'embedding_dimension': DIMENSION, 'normalized': True,
            'embedding_text': prepare_inputs([chunk])[0], 'token_count': 8}


class Tokenizer:
    def __init__(self, count=8):
        self.count = count
    def __call__(self, text, **kwargs):
        self.text, self.kwargs = text, kwargs
        return {'input_ids': list(range(self.count))}


class SearchTests(unittest.TestCase):
    def load(self, records=None, change_report=None):
        records = records if records is not None else [record()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'embeddings.jsonl'
            raw = ''.join(json.dumps(r) + '\n' for r in records).encode()
            path.write_bytes(raw)
            report = {'schema_name': 'home-rag-embedding-report', 'schema_version': 1,
                      'status': 'pass', 'output_sha256': hashlib.sha256(raw).hexdigest(),
                      'model': {'model_id': MODEL, 'revision': 'pinned'},
                      'dimension': DIMENSION, 'normalized': True,
                      'passage_prefix': 'passage: ', 'query_prefix': 'query: ',
                      'text_template_version': 1, 'vectors': len(records)}
            if change_report:
                report.update(change_report)
            report_path = Path(directory) / 'embedding_report.json'
            report_path.write_text(json.dumps(report))
            return load_index(path, report_path, {'revision': 'pinned'})

    def test_cosine_ranking_and_negative_scores(self):
        records = [record('opposite'), record('match'), record('orthogonal')]
        results = rank_chunks(records, [vector(-1), vector(), vector(0, 1)], vector(), 3)
        self.assertEqual([r['chunk_id'] for r in results], ['match', 'orthogonal', 'opposite'])
        self.assertEqual([r['score'] for r in results], [1, 0, -1])

    def test_ties_stable_and_top_k_capped(self):
        records = [record('b'), record('a')]
        results = rank_chunks(records, [vector(), vector()], vector(), 10)
        self.assertEqual([r['chunk_id'] for r in results], ['a', 'b'])
        self.assertEqual(len(rank_chunks(records, [vector(), vector()], vector(), 1)), 1)

    def test_citations_and_text_preserved_without_mutation(self):
        original = record()
        before = deepcopy(original)
        result = rank_chunks([original], [vector()], vector(), 1)[0]
        self.assertEqual(result['chunk'], original['chunk'])
        result['chunk']['provenance'][0]['page_number'] = 99
        self.assertEqual(original, before)

    def test_query_prefix_special_tokens_and_no_truncation(self):
        tokenizer = Tokenizer(512)
        self.assertEqual(prepare_query('  Pytanie?  ', tokenizer), ('query: Pytanie?', 512))
        self.assertTrue(tokenizer.kwargs['add_special_tokens'])
        self.assertFalse(tokenizer.kwargs['truncation'])
        with self.assertRaises(ValueError):
            prepare_query('Pytanie', Tokenizer(513))
        with self.assertRaises(ValueError):
            prepare_query('  ', tokenizer)

    def test_invalid_vectors_and_parameters_rejected(self):
        for bad in ([0.0] * DIMENSION, vector(float('nan')), [1.0], vector(2)):
            with self.assertRaises(ValueError):
                rank_chunks([record()], [vector()], bad, 1)
        for k in (0, -1, True):
            with self.assertRaises(ValueError):
                rank_chunks([record()], [vector()], vector(), k)
        with self.assertRaises(ValueError):
            rank_chunks([record()], [], vector(), 1)

    def test_valid_index_loads(self):
        records, vectors, report = self.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(vectors, [vector()])
        self.assertEqual(report['status'], 'pass')

    def test_checksum_count_and_report_settings_rejected(self):
        for changes in ({'output_sha256': 'wrong'}, {'vectors': 2},
                        {'status': 'tokens_pass'}, {'query_prefix': ''},
                        {'model': {'model_id': MODEL, 'revision': 'other'}},
                        {'text_template_version': 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load(change_report=changes)

    def test_record_model_and_embedded_text_mismatch_rejected(self):
        for key, value in (('model_revision', 'other'), ('chunk_id', 'other'),
                           ('embedding_text', 'changed'), ('normalized', False)):
            item = record()
            item[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load([item])

    def test_duplicate_and_unapproved_provenance_rejected(self):
        with self.assertRaises(ValueError):
            self.load([record(), record()])
        for change in ('review', 'page', 'missing'):
            item = record()
            if change == 'review':
                item['chunk']['quality']['page_status'] = 'review'
            elif change == 'page':
                item['chunk']['provenance'][0]['page_number'] = 10
            else:
                item['chunk']['provenance'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load([item])


if __name__ == '__main__':
    unittest.main()
