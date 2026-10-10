import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('layout_analyzer', Path(__file__).resolve().parents[1] / 'scripts/analyze_pages.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def block(kind='text', text='A' * 1000, top=0.1, subtype='text'):
    return {'id': '#/x/0', 'type': kind, 'subtype': subtype, 'text': text,
            'page_numbers': [1], 'provenance': [{'page_number': 1, 'charspan': [0, len(text)],
             'bbox_normalized': {'left': .1, 'right': .9, 'top': top, 'bottom': .95}}]}


def document(blocks=None):
    blocks = blocks or []
    return {'source': {'sha256': 'abc'}, 'pages': [{'page_number': 1, 'block_ids': [b['id'] for b in blocks]}], 'blocks': blocks}


def reviews(layout, **extra):
    return {'schema_name': 'home-rag-page-reviews', 'schema_version': 1, 'source_sha256': 'abc',
            'pages': [{'page_number': 1, 'confirmed': True, 'layout': layout, 'note': 'Owner checked layout', **extra}]}


class LayoutTests(unittest.TestCase):
    def test_unconfirmed_empty_still_fails(self):
        self.assertEqual(a.analyze_document(document())['status'], 'fail')

    def test_confirmed_blank_and_audit(self):
        page = a.analyze_document(document(), reviews('blank'))['pages'][0]
        self.assertEqual(page['quality']['status'], 'pass')
        self.assertEqual(page['role'], 'body')
        self.assertEqual(page['quality']['waived_layout_issues'][0]['code'], 'NO_BODY_TEXT')
        self.assertEqual(page['layout_review']['note'], 'Owner checked layout')

    def test_blank_cannot_hide_short_text_or_image(self):
        for b in (block(text='x'), block(kind='picture', text='')):
            with self.subTest(kind=b['type']):
                report = a.analyze_document(document([b]), reviews('blank'))
                self.assertNotEqual(report['status'], 'pass')
                self.assertIn('REVIEW_LAYOUT_MISMATCH', [i['code'] for i in report['pages'][0]['quality']['issues']])

    def test_source_unknown_duplicate_unconfirmed_rejected(self):
        r = reviews('blank')
        variants = []
        for key, value in [('source_sha256', 'other'), ('schema_version', True)]:
            v = copy.deepcopy(r); v[key] = value; variants.append(v)
        for key, value in [('page_number', 2), ('page_number', True), ('confirmed', False), ('layout', 'guess'), ('note', '')]:
            v = copy.deepcopy(r); v['pages'][0][key] = value; variants.append(v)
        v = copy.deepcopy(r); v['pages'] *= 2; variants.append(v)
        for v in variants:
            with self.subTest(review=v), self.assertRaises(ValueError):
                a.analyze_document(document(), v)

    def test_dedication_is_front_matter(self):
        report = a.analyze_document(document([block(text='Dedykowane Jamesowi Fadimanowi', top=.85)]), reviews('dedication'))
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['pages'][0]['role'], 'front_matter')

    def test_visual_layout_does_not_need_body_text(self):
        r = a.analyze_document(document([block(kind='picture', text='')]), reviews('visual_page'))
        self.assertEqual(r['status'], 'pass')
        self.assertEqual(r['pages'][0]['metrics']['picture_blocks'], 1)
        self.assertTrue(r['limitations'])

    def test_illustrated_layout_needs_picture(self):
        report = a.analyze_document(document([block()]), reviews('illustrated_opener'))
        self.assertEqual(report['status'], 'review')

    def test_table_expectations(self):
        b = block(kind='table', text=''); b['data'] = {'rows': 25, 'columns': 4, 'cell_count': 100}
        d = document([b])
        self.assertEqual(a.analyze_document(d, reviews('table_page', expected_tables=1, expected_table_columns=4))['status'], 'pass')
        for extra in ({'expected_tables': 2}, {'expected_table_columns': 3}):
            self.assertNotEqual(a.analyze_document(d, reviews('table_page', **extra))['status'], 'pass')

    def test_overlap_not_waived(self):
        b = block(text='x' * 50); b['provenance'].append(copy.deepcopy(b['provenance'][0]))
        picture = block(kind='picture', text=''); picture['id'] = '#/picture/0'
        r = a.analyze_document(document([b, picture]), reviews('mixed_visual'))
        self.assertEqual(r['status'], 'review')
        self.assertEqual(r['pages'][0]['quality']['issues'][0]['code'], 'OVERLAPPING_TEXT_REGIONS')

    def test_determinism_and_inputs_not_mutated(self):
        d = document(); r = reviews('blank'); before = copy.deepcopy((d, r))
        first = a.analyze_document(d, r)
        self.assertEqual(first, a.analyze_document(d, r))
        self.assertEqual((d, r), before)


if __name__ == '__main__':
    unittest.main()
