import importlib.util
from copy import deepcopy
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'embed_chunks', Path(__file__).resolve().parents[1] / 'scripts' / 'embed_chunks.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


def chunk(text='Tekst źródła'):
    return {'schema_name': 'home-rag-chunk', 'chunk_id': 'c1', 'chunk_type': 'text',
            'text': text, 'source_id': 's', 'source_sha256': 'abc', 'record_ids': ['r1'],
            'block_ids': ['b1'], 'page_numbers': [9], 'provenance': [{'page_number': 9}],
            'section_path': ['Sekcja'],
            'quality': {'page_status': 'pass', 'content_status': 'not_semantically_validated'}}


class FakeTokenizer:
    # Character counter is ONLY a test double, never used for actual token validation.
    def __call__(self, text, **kwargs):
        assert kwargs['truncation'] is False
        assert kwargs['add_special_tokens'] is True
        return {'input_ids': list(range(len(text) + 2))}


class EmbeddingTests(unittest.TestCase):
    def test_passage_prefix_section_and_unchanged_source(self):
        c = chunk()
        before = deepcopy(c)
        self.assertEqual(e.prepare_inputs([c]), ['passage: Sekcja\nTekst źródła'])
        self.assertEqual(c, before)

    def test_table_header_context(self):
        c = chunk()
        c.update(chunk_type='table', table_column_headers=[{'text': 'Nazwa'}, {'text': 'Wartość'}])
        self.assertEqual(e.prepare_inputs([c])[0],
                         'passage: Sekcja\nKolumny: Nazwa | Wartość\nTekst źródła')

    def test_duplicate_and_missing_provenance(self):
        c = chunk()
        with self.assertRaises(ValueError):
            e.prepare_inputs([c, deepcopy(c)])
        c['provenance'] = []
        with self.assertRaises(ValueError):
            e.prepare_inputs([c])

    def test_image_and_empty_rejected(self):
        c = chunk()
        c['chunk_type'] = 'picture'
        with self.assertRaises(ValueError):
            e.prepare_inputs([c])
        with self.assertRaises(ValueError):
            e.prepare_inputs([chunk(' ')])
        with self.assertRaises(ValueError):
            e.prepare_inputs([])

    def test_token_guard_counts_prefix_and_special_tokens(self):
        c = chunk()
        texts, counts, report = e.count_tokens([c], FakeTokenizer(), max_tokens=5)
        self.assertEqual(counts[0], len(texts[0]) + 2)
        self.assertEqual(report['overflow'][0]['chunk_id'], 'c1')
        self.assertEqual(e.count_tokens([c], FakeTokenizer(), counts[0])[2]['overflow'], [])

    def test_vector_dimensions_norm_and_count(self):
        good = [1.0] + [0.0] * 383
        self.assertEqual(e.validate_vectors([good], 1), [good])
        for vectors, count in (([good], 2), ([[1.0]], 1), ([[0.0] * 384], 1),
                               ([[float('nan')] + [0.0] * 383], 1),
                               ([[2.0] + [0.0] * 383], 1)):
            with self.assertRaises(ValueError):
                e.validate_vectors(vectors, count)

    def test_page_mismatch_and_review_rejected(self):
        c = chunk()
        c['provenance'][0]['page_number'] = 10
        with self.assertRaises(ValueError):
            e.prepare_inputs([c])
        c = chunk()
        c['quality']['page_status'] = 'review'
        with self.assertRaises(ValueError):
            e.prepare_inputs([c])


if __name__ == '__main__':
    unittest.main()
