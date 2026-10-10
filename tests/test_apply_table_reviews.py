from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from apply_table_reviews import apply_review, digest
from chunk_document import render_cells, table_groups


def fixture():
    data = {'rows': 2, 'columns': 4, 'cells': []}
    for row, values in enumerate([['alergia (104)', '9% (61)', '41% (43)', '0% (0)'],
                                  ['Oparzenia (22)', '77% (17)', '22% (5)', '3% (25)']]):
        for col, text in enumerate(values):
            data['cells'].append({'text': text, 'start_row_offset_idx': row,
                'end_row_offset_idx': row+1, 'start_col_offset_idx': col,
                'end_col_offset_idx': col+1, 'column_header': False})
    document = {'schema_name': 'home-rag-book', 'source': {'sha256': 'scan'},
                'blocks': [{'id': 'table', 'type': 'table', 'page_numbers': [97], 'data': data}]}
    table = {'chunk_id': 'table-old', 'chunk_type': 'table', 'source_id': 'book',
             'source_sha256': 'scan', 'block_ids': ['table'], 'record_ids': ['record'],
             'page_numbers': [97], 'printed_page_labels': ['97'],
             'page_footer_raw': [{'text': '97'}], 'configuration': {'max_chars': 210},
             'table_column_headers': [], 'table_cell_indices': list(range(8)),
             'table_cells': deepcopy(data['cells']), 'text': render_cells(data, range(8)),
             'table_dimensions': {'rows': 2, 'columns': 4}, 'table_row_range': [0, 2]}
    other = {'chunk_id': 'unchanged', 'block_ids': ['body'], 'text': 'tekst'}
    review = {'schema_name': 'home-rag-table-review', 'source_sha256': 'scan',
              'page_number': 97, 'block_id': 'table', 'table_data_sha256': digest(data),
              'column_headers': [{'column_index': i, 'text': t} for i, t in enumerate(
                   ['Kondycja', 'Pozytywne efekty', 'Brak wyników', 'Negatywne efekty'])],
              'cell_edits': [{'row_index': 0, 'column_index': 1, 'before': '9% (61)',
                              'after': '59% (61)', 'reason': 'Sprawdzono w skanie'}],
              'evidence': {'scan': 'p97.pdf'}}
    return document, [other, table], review


class TableReviewTests(unittest.TestCase):
    def test_headers_correction_coverage_audit_and_source_unchanged(self):
        doc, chunks, review = fixture()
        before = deepcopy((doc, chunks, review))
        result, audit = apply_review(doc, chunks, review)
        self.assertEqual((doc, chunks, review), before)
        self.assertEqual(result[0], chunks[0])
        self.assertEqual(sorted(i for c in result[1:] for i in c['table_cell_indices']), list(range(8)))
        for c in result[1:]:
            self.assertIn('c2: Pozytywne efekty', c['text'])
            self.assertEqual(c['printed_page_labels'], ['97'])
            self.assertEqual(c['page_footer_raw'], chunks[1]['page_footer_raw'])
            self.assertNotEqual(c['chunk_id'], chunks[1]['chunk_id'])
        self.assertIn('59% (61)', result[1]['text'])
        self.assertEqual(audit['table_data_original']['cells'][1]['text'], '9% (61)')
        self.assertEqual(audit['table_data_corrected']['cells'][1]['text'], '59% (61)')
        self.assertEqual(audit['table_data_corrected']['cells'][7]['text'], '3% (25)')

    def test_deterministic_and_changes_only_target(self):
        doc, chunks, review = fixture()
        self.assertEqual(apply_review(doc, chunks, review), apply_review(doc, chunks, review))

    def test_wrong_scan_or_changed_table_rejected(self):
        doc, chunks, review = fixture()
        review['source_sha256'] = 'other'
        with self.assertRaises(ValueError): apply_review(doc, chunks, review)
        review['source_sha256'] = 'scan'
        doc['blocks'][0]['data']['cells'][0]['text'] = 'other'
        with self.assertRaises(ValueError): apply_review(doc, chunks, review)

    def test_wrong_before_wrong_coordinate_duplicate_edit_rejected(self):
        for mutate in [lambda r: r['cell_edits'][0].update(before='x'),
                       lambda r: r['cell_edits'][0].update(column_index=2),
                       lambda r: r['cell_edits'].append(deepcopy(r['cell_edits'][0]))]:
            doc, chunks, review = fixture()
            mutate(review)
            with self.assertRaises(ValueError): apply_review(doc, chunks, review)

    def test_missing_cells_and_modified_source_text_rejected(self):
        doc, chunks, review = fixture()
        chunks[1]['table_cell_indices'].pop()
        with self.assertRaises(ValueError): apply_review(doc, chunks, review)
        doc, chunks, review = fixture()
        chunks[1]['text'] += ' invented'
        with self.assertRaises(ValueError): apply_review(doc, chunks, review)

    def test_incomplete_headers_and_repeat_correction_rejected(self):
        doc, chunks, review = fixture()
        review['column_headers'].pop()
        with self.assertRaises(ValueError): apply_review(doc, chunks, review)
        doc, chunks, review = fixture()
        corrected, _ = apply_review(doc, chunks, review)
        with self.assertRaises(ValueError): apply_review(doc, corrected, review)


if __name__ == '__main__':
    unittest.main()
