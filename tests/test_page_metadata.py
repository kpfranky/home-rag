import hashlib
import json
from pathlib import Path
import sys
import unittest
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from normalize_document import page_metadata, printed_label, export_document
from refresh_page_metadata import refresh, serialize


def fixture():
    doc = {'schema_name': 'home-rag-book', 'source': {'sha256': 'scan'},
           'pages': [{'page_number': 52, 'block_ids': ['quote', 'name', 'body']}],
           'blocks': [{'id': bid, 'type': 'text', 'subtype': subtype,
                       'text': text, 'page_numbers': [52],
                       'provenance': [{'page_number': 52}]}
                      for bid, subtype, text in [('quote', 'page_footer', '„Kreatywność to inteligencja”'),
                                                 ('name', 'page_footer', 'Albert Einstein'),
                                                 ('body', 'text', 'Wyniki mają ograniczony potencjał generalizacji.')]]}
    record = {'schema_name': 'home-rag-embedding', 'chunk_id': 'c52',
              'embedding': [1.0] + [0.0] * 383,
              'chunk': {'schema_name': 'home-rag-chunk', 'chunk_id': 'c52',
                        'source_sha256': 'scan', 'page_numbers': [52],
                        'text': 'Wyniki mają ograniczony potencjał generalizacji.',
                        'printed_page_labels': ['Albert Einstein']}}
    raw = serialize([record])
    report = {'schema_name': 'home-rag-embedding-report', 'status': 'pass', 'vectors': 1,
              'output_sha256': hashlib.sha256(raw).hexdigest(), 'input_sha256': 'old'}
    return doc, [record], report, raw


class MetadataTests(unittest.TestCase):
    def test_label_grammar(self):
        for label in ['15', '005', 'XIV', 'iv']:
            self.assertEqual(printed_label(label), label)
        for text in ['Albert Einstein', 'tekst 52', '59% (61)', 'IIII', '', '52\nAlbert Einstein']:
            self.assertIsNone(printed_label(text))

    def test_realistic_footer_and_missing_number(self):
        doc, _, _, _ = fixture()
        item = page_metadata(doc)[52]
        self.assertEqual(item['printed_page_labels'], [])
        self.assertEqual(item['printed_page_label_status'], 'missing')
        self.assertEqual(len(item['page_footer_raw']), 2)
        doc['pages'].append({'page_number': 55, 'block_ids': []})
        self.assertEqual(page_metadata(doc)[55]['printed_page_labels'], [])

    def test_normalizer_preserves_body_and_raw_evidence(self):
        doc, _, _, _ = fixture()
        doc['source']['filename'] = 'sample.pdf'
        analysis = {'schema_name': 'home-rag-page-analysis', 'source': {'sha256': 'scan'},
                    'pages': [{'page_number': 52, 'role': 'body', 'quality': {'status': 'pass'}}]}
        result, skipped = export_document(doc, analysis)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['text'], doc['blocks'][2]['text'])
        self.assertEqual(result[0]['printed_page_labels'], [])
        self.assertEqual(result[0]['page_footer_raw'][1]['text'], 'Albert Einstein')

    def test_refresh_vectors_content_identity_and_report(self):
        doc, records, report, raw = fixture()
        original = deepcopy(records)
        chunks_raw, output_raw, updated, metadata = refresh(doc, records, report, raw)
        result = json.loads(output_raw)
        self.assertEqual(records, original)
        self.assertEqual(result['embedding'], original[0]['embedding'])
        self.assertEqual(result['chunk']['text'], original[0]['chunk']['text'])
        self.assertEqual(result['chunk_id'], 'c52')
        self.assertEqual(result['chunk']['printed_page_labels'], [])
        self.assertEqual(updated['output_sha256'], hashlib.sha256(output_raw).hexdigest())
        self.assertEqual(updated['input_sha256'], hashlib.sha256(chunks_raw).hexdigest())
        self.assertEqual(refresh(doc, records, report, raw)[1], output_raw)

    def test_wrong_scan_or_checksum_rejected(self):
        doc, records, report, raw = fixture()
        with self.assertRaises(ValueError):
            refresh(doc, records, report, raw + b' ')
        records[0]['chunk']['source_sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            refresh(doc, records, report, raw)

    def test_review_is_bound_to_scan_and_before_value(self):
        doc, records, report, raw = fixture()
        review = {'source_sha256': 'scan', 'reviews': [
            {'page_number': 52, 'before': [], 'after': ['52'], 'reason': 'Confirmed in scan'}]}
        result = refresh(doc, records, report, raw, review)
        item = json.loads(result[1])['chunk']
        self.assertEqual(item['printed_page_labels'], ['52'])
        self.assertEqual(item['printed_page_label_status'], 'verified_scan')
        self.assertIn('printed_page_label_review', item)
        review['source_sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            refresh(doc, records, report, raw, review)
        review['source_sha256'] = 'scan'
        review['reviews'][0]['before'] = ['5']
        with self.assertRaises(ValueError):
            refresh(doc, records, report, raw, review)

    def test_ambiguous_numbers_are_not_silently_selected(self):
        doc, _, _, _ = fixture()
        doc['blocks'][0]['text'] = '51'
        doc['blocks'][1]['text'] = '52'
        item = page_metadata(doc)[52]
        self.assertEqual(item['printed_page_labels'], [])
        self.assertEqual(item['printed_page_label_status'], 'ambiguous')


if __name__ == '__main__':
    unittest.main()
