import importlib.util
from copy import deepcopy
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'chunk_document', Path(__file__).resolve().parents[1] / 'scripts' / 'chunk_document.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def record(text='Pierwsze zdanie. Drugie zdanie. Trzecie zdanie.'):
    return {'record_id': 'source:p0001:b0001', 'record_type': 'text', 'subtype': 'text',
            'text': text, 'source_id': 'source', 'source_sha256': 'abc', 'page_numbers': [1],
            'page_role': 'body', 'block_ids': ['#/texts/1'], 'section_path': ['Sekcja'],
            'provenance': [{'page_number': 1, 'charspan': [0, len(text)]}],
            'quality': {'page_status': 'pass', 'content_status': 'not_semantically_validated'}}


def table():
    r = record()
    r.update(record_type='table', subtype='table', table_data={
        'rows': 3, 'columns': 2, 'cells': [
            {'start_row_offset_idx': 0, 'end_row_offset_idx': 2,
             'start_col_offset_idx': 0, 'end_col_offset_idx': 1, 'text': 'Scalona'},
            {'start_row_offset_idx': 0, 'end_row_offset_idx': 1,
             'start_col_offset_idx': 1, 'end_col_offset_idx': 2,
             'text': 'Nagłówek', 'column_header': True},
            {'start_row_offset_idx': 1, 'end_row_offset_idx': 2,
             'start_col_offset_idx': 1, 'end_col_offset_idx': 2, 'text': 'Wartość'},
            {'start_row_offset_idx': 2, 'end_row_offset_idx': 3,
             'start_col_offset_idx': 0, 'end_col_offset_idx': 2, 'text': 'Ostatni'}]})
    return r


class ChunkingTests(unittest.TestCase):
    def test_lossless_partition_and_limit(self):
        for text in ('Zdanie pierwsze. Zdanie drugie! Kolejne zdanie.', 'a ' * 80,
                     'x' * 80, 'mgr. Jan Kowalski ma dane. Następne zdanie.'):
            spans = list(c.text_spans(text, 25))
            self.assertEqual(''.join(text[a:b] for a, b, _ in spans), text)
            self.assertTrue(all(0 < b - a <= 25 for a, b, _ in spans))
            self.assertEqual(spans[0][0], 0)
            self.assertEqual(spans[-1][1], len(text))

    def test_sentence_boundary_preferred(self):
        self.assertEqual(list(c.text_spans('Pierwsze zdanie. Drugie długie zdanie.', 25))[0][2], 'sentence')

    def test_citations_and_offsets(self):
        r = record()
        chunks, _ = c.build_chunks([r], 22)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            span = chunk['text_span']
            self.assertEqual(chunk['text'], r['text'][span['start']:span['end']])
            self.assertEqual(chunk['provenance'], r['provenance'])
            self.assertEqual(chunk['record_ids'], [r['record_id']])
            self.assertEqual(chunk['page_numbers'], [1])

    def test_separate_pages_and_records(self):
        a, b = record(), record()
        b.update(record_id='other', page_numbers=[2], section_path=['Inna'])
        b['provenance'][0]['page_number'] = 2
        chunks, _ = c.build_chunks([a, b])
        self.assertEqual([x['page_numbers'] for x in chunks], [[1], [2]])
        self.assertEqual([x['section_path'] for x in chunks], [['Sekcja'], ['Inna']])

    def test_filters_and_audit(self):
        r = record()
        r['page_role'] = 'front_matter'
        self.assertEqual(c.build_chunks([r])[1]['skipped_counts'], {'page_role_excluded': 1})
        r['page_role'] = 'body'
        r['quality']['content_status'] = 'review_normalization'
        self.assertEqual(c.build_chunks([r])[0], [])
        self.assertEqual(len(c.build_chunks([r], allow_review=True)[0]), 1)
        r['record_type'] = 'picture'
        self.assertEqual(c.build_chunks([r], allow_review=True)[0], [])

    def test_heading_used_as_context(self):
        r = record()
        r['subtype'] = 'section_header'
        self.assertEqual(c.build_chunks([r])[1]['skipped_counts'], {'heading_used_as_context': 1})

    def test_table_spans_and_cell_coverage(self):
        r = table()
        chunks, report = c.build_chunks([r], 15)
        self.assertEqual([x['table_row_range'] for x in chunks], [[0, 2], [2, 3]])
        self.assertEqual([i for x in chunks for i in x['table_cell_indices']], [0, 1, 2, 3])
        self.assertTrue(chunks[0]['oversized'])
        self.assertEqual(chunks[0]['table_cells'], r['table_data']['cells'][:3])
        self.assertEqual(chunks[1]['table_column_headers'][0]['text'], 'Nagłówek')

    def test_invalid_input_rejected(self):
        r = record()
        with self.assertRaises(ValueError):
            c.build_chunks([r, deepcopy(r)])
        with self.assertRaises(ValueError):
            c.build_chunks([r], 0)
        r['provenance'][0]['page_number'] = 2
        with self.assertRaises(ValueError):
            c.build_chunks([r])
        t = table()
        t['table_data']['cells'][0]['end_row_offset_idx'] = 10
        with self.assertRaises(ValueError):
            c.build_chunks([t])

    def test_determinism_and_parameter_sensitive_ids(self):
        records = [record()]
        self.assertEqual(c.build_chunks(records, 22), c.build_chunks(records, 22))
        first = c.build_chunks(records, 22)[0][0]['chunk_id']
        self.assertNotEqual(first, c.build_chunks(records, 23)[0][0]['chunk_id'])


if __name__ == '__main__':
    unittest.main()
