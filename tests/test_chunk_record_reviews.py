import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('reviewed_chunker', Path(__file__).resolve().parents[1] / 'scripts/chunk_document.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def record(rid, kind='text', box=(.8, .8, 1., 1.)):
    return {'record_id': rid, 'record_type': kind, 'subtype': kind,
            'text': 'Spójny akapit narracyjny.' if rid == 'paragraph' else '12% a.',
            'source_id': 'source', 'source_sha256': 'pdf', 'page_numbers': [1],
            'page_role': 'body', 'block_ids': [rid], 'section_path': ['Rozdział'],
            'provenance': [{'page_number': 1, 'bbox_normalized': dict(zip(('left', 'top', 'right', 'bottom'), box))}],
            'quality': {'page_status': 'pass', 'content_status': 'not_semantically_validated'}}


def records():
    return [record('paragraph'), record('label'), record('picture', 'picture', (.1, .1, .9, .9))]


def reviews():
    return {'schema_name': 'home-rag-visual-text-reviews', 'schema_version': 1,
            'input_sha256': 'normalized', 'records': [
                {'record_id': 'paragraph', 'decision': 'keep', 'note': 'Narrative text'},
                {'record_id': 'label', 'decision': 'defer_to_vision', 'note': 'Context-free fragment'}]}


def run(rs=None, r=None, sha='normalized'):
    return c.build_chunks(rs if rs is not None else records(), exclude_picture_text=True,
                          record_reviews=r if r is not None else reviews(), input_sha256=sha)


class RecordReviewTests(unittest.TestCase):
    def test_keep_and_defer_with_audit(self):
        chunks, report = run()
        self.assertEqual([x['record_ids'] for x in chunks], [['paragraph']])
        self.assertEqual(chunks[0]['text'], 'Spójny akapit narracyjny.')
        self.assertEqual(report['skipped_counts']['reviewed_text_pending_vision'], 1)
        self.assertEqual(report['visual_text_review_records'], [])
        self.assertEqual(report['record_reviews'], reviews())
        self.assertEqual(len(report['resolved_visual_text_reviews']), 2)

    def test_wrong_hash_schema_rejected(self):
        with self.assertRaises(ValueError): run(sha='changed')
        for key, value in [('schema_name', 'other'), ('schema_version', True)]:
            r = reviews(); r[key] = value
            with self.assertRaises(ValueError): run(r=r)

    def test_unknown_duplicate_missing_or_non_candidate_rejected(self):
        for variant in ('unknown', 'duplicate', 'missing', 'picture'):
            r = reviews()
            if variant == 'duplicate': r['records'].append(copy.deepcopy(r['records'][0]))
            elif variant == 'missing': r['records'].pop()
            else: r['records'][0]['record_id'] = variant
            with self.assertRaises(ValueError): run(r=r)

    def test_invalid_decision_and_note_rejected(self):
        for key, value in [('decision', 'delete'), ('note', '')]:
            r = reviews(); r['records'][0][key] = value
            with self.assertRaises(ValueError): run(r=r)

    def test_requires_picture_filter_and_without_reviews_stays_pending(self):
        with self.assertRaises(ValueError): c.build_chunks(records(), record_reviews=reviews(), input_sha256='normalized')
        chunks, report = c.build_chunks(records(), exclude_picture_text=True)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(report['visual_text_review_records']), 2)

    def test_deterministic_no_mutation_and_parameter_sensitive_ids(self):
        rs = records(); r = reviews(); before = copy.deepcopy((rs, r))
        first = run(rs, r)
        self.assertEqual(first, run(rs, r))
        self.assertEqual((rs, r), before)
        no_review, _ = c.build_chunks(rs, exclude_picture_text=True)
        self.assertNotEqual(first[0][0]['chunk_id'], no_review[0]['chunk_id'])


if __name__ == '__main__':
    unittest.main()
