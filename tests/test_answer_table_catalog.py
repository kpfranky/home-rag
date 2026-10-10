from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from answer_question import evidence_catalog, extraction_schema, validate_extraction


def source():
    return {'source_id': 'S2', 'chunk_id': 'table', 'chunk': {
        'chunk_type': 'table', 'text':
        'Kolumny: c1: Kondycja | c2: Pozytywne efekty | c3: Brak wyników | c4: Negatywne efekty\n'
        'r1 c1: alergia (104)\nr1 c2: 59% (61)\nr1 c3: 41% (43)\nr1 c4: 0% (0)\n'
        'r2 c1: Leki przeciwdepresyjne (47)\nr2 c2: 89% (42)\nr2 c3: 11% (5)\nr2 c4: 0% (0)',
        'source_id': 'book', 'page_numbers': [97]}}


class TableCatalogTests(unittest.TestCase):
    def assert_lossless(self, item, catalog):
        text = item['chunk']['text']
        covered = set()
        for evidence in catalog:
            left, right = evidence['text_span']['start'], evidence['text_span']['end']
            self.assertEqual(evidence['quote'], text[left:right])
            self.assertLessEqual(right-left, 320)
            self.assertFalse(covered.intersection(range(left, right)))
            covered.update(range(left, right))
        self.assertTrue(all(i in covered or character.isspace() for i, character in enumerate(text)))

    def test_row_does_not_mix_adjacent_condition_and_keeps_header(self):
        item = source()
        before = deepcopy(item)
        catalog = evidence_catalog(item)
        self.assertEqual(len(catalog), 2)
        self.assertIn('Kolumny:', catalog[0]['quote'])
        self.assertIn('r1 c4: 0% (0)', catalog[0]['quote'])
        self.assertNotIn('r2', catalog[0]['quote'])
        self.assertNotIn('r1', catalog[1]['quote'])
        self.assertEqual(item, before)
        self.assert_lossless(item, catalog)

    def test_selected_row_resolves_exact_quote_with_original_source_id(self):
        item = source()
        result = validate_extraction({'items': [{
            'text': 'Według tabeli: alergia — 59% (61), 41% (43), 0% (0).',
            'evidence_id': 'S2:E1'}]}, item)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['source_id'], 'S2')
        self.assertNotIn('Leki przeciwdepresyjne', result[0]['quote'])
        enum = extraction_schema(item)['properties']['items']['items']['properties']['evidence_id']['enum']
        self.assertEqual(enum, ['S2:E1', 'S2:E2'])

    def test_long_row_uses_lossless_fallback(self):
        item = source()
        item['chunk']['text'] += '\nr3 c1: ' + 'długi opis ' * 80
        catalog = evidence_catalog(item)
        self.assert_lossless(item, catalog)

    def test_prose_with_row_like_text_uses_original_splitter(self):
        item = source()
        item['chunk']['chunk_type'] = 'text'
        catalog = evidence_catalog(item)
        self.assert_lossless(item, catalog)
        self.assertEqual(len(catalog), 1)


if __name__ == '__main__':
    unittest.main()
