import importlib.util
from copy import deepcopy
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'normalize_document.py'
spec = importlib.util.spec_from_file_location('normalize_document', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    block = {'id': '#/texts/0', 'type': 'text', 'subtype': 'text',
             'text': 'receptorów GABA, wy-', 'page_numbers': [1],
             'provenance': [{'page_number': 1, 'charspan': [0, 19]}]}
    other = deepcopy(block)
    other.update(id='#/texts/1', text='kazującym podobieństwo')
    doc = {'schema_name': 'home-rag-book',
           'source': {'sha256': 'abc', 'filename': 'sample_ocr.pdf'},
           'pages': [{'page_number': 1, 'block_ids': [block['id'], other['id']]}],
           'blocks': [block, other]}
    report = {'schema_name': 'home-rag-page-analysis', 'source': {'sha256': 'abc'},
              'pages': [{'page_number': 1, 'role': 'body', 'quality': {'status': 'pass'}}]}
    return doc, report


class NormalizationTests(unittest.TestCase):
    def test_join_and_preserve_compounds(self):
        self.assertEqual(module.join_split_word('receptorów GABA, wy-', 'kazującym podobieństwo'),
                         'receptorów GABA, wykazującym podobieństwo')
        self.assertEqual(module.join_split_word('efekty są po-', 'zytywne'), 'efekty są pozytywne')
        self.assertIsNone(module.join_split_word('układ polsko-niemiecki', 'Pozostaje aktualny.'))
        self.assertIsNone(module.join_split_word('abc-', 'Nowe zdanie'))
        self.assertIsNone(module.join_split_word('123-', 'abc'))

    def test_merge_keeps_sources_and_audit(self):
        doc, report = fixture()
        records, skipped = module.export_document(doc, report)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(records[0]['block_ids']), 2)
        self.assertEqual(len(records[0]['provenance']), 2)
        self.assertTrue(records[0]['normalization_actions'][0]['requires_review'])
        self.assertEqual(skipped, [])
        self.assertEqual(len(module.export_document(doc, report, join_hyphens=False)[0]), 2)

    def test_source_mismatch(self):
        doc, report = fixture()
        report['source']['sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            module.export_document(doc, report)

    def test_review_page_is_excluded(self):
        doc, report = fixture()
        report['pages'][0]['quality']['status'] = 'review'
        self.assertEqual(module.export_document(doc, report), ([], [1]))

    def test_multipage_offsets_and_nonwhitespace_gap(self):
        block = {'id': 'multi', 'text': 'abc def', 'page_numbers': [1, 2],
                 'provenance': [{'page_number': 1, 'charspan': [0, 3]},
                                {'page_number': 2, 'charspan': [4, 7]}]}
        self.assertEqual(module.text_fragments(block), {1: 'abc', 2: 'def'})
        block['text'] = 'abcXdef'
        with self.assertRaises(ValueError):
            module.text_fragments(block)

    def test_overlap_rejected(self):
        block = {'id': 'multi', 'text': 'abcdef', 'page_numbers': [1, 2],
                 'provenance': [{'page_number': 1, 'charspan': [0, 4]},
                                {'page_number': 2, 'charspan': [3, 6]}]}
        with self.assertRaises(ValueError):
            module.text_fragments(block)

    def test_no_join_across_page_or_picture(self):
        doc, report = fixture()
        doc['blocks'][1]['page_numbers'] = [2]
        doc['blocks'][1]['provenance'][0]['page_number'] = 2
        doc['pages'] = [{'page_number': 1, 'block_ids': ['#/texts/0']},
                        {'page_number': 2, 'block_ids': ['#/texts/1']}]
        report['pages'].append({'page_number': 2, 'role': 'body', 'quality': {'status': 'pass'}})
        self.assertEqual(len(module.export_document(doc, report)[0]), 2)
        doc, report = fixture()
        picture = {'id': 'picture', 'type': 'picture', 'page_numbers': [1],
                   'provenance': [{'page_number': 1}], 'asset': 'a.png'}
        doc['blocks'].append(picture)
        doc['pages'][0]['block_ids'].insert(1, 'picture')
        records, _ = module.export_document(doc, report)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[1]['quality']['content_status'], 'needs_vision')

    def test_table_is_preserved(self):
        doc, report = fixture()
        block = doc['blocks'][0]
        block.update(type='table', subtype='document_index',
                     data={'rows': 1, 'columns': 2, 'cells': [{'text': 'x-y', 'col_span': 2}]})
        records, _ = module.export_document(doc, report)
        self.assertEqual(records[0]['table_data'], block['data'])


if __name__ == '__main__':
    unittest.main()
