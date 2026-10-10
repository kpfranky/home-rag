import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('visual_chunker', Path(__file__).resolve().parents[1] / 'scripts/chunk_document.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def record(rid='text', kind='text', subtype='text', box=(.2, .2, .4, .4)):
    return {'record_id': rid, 'record_type': kind, 'subtype': subtype,
            'text': '60%', 'source_id': 'source', 'source_sha256': 'abc',
            'page_numbers': [1], 'page_role': 'body', 'block_ids': [rid],
            'section_path': ['Rozdział'], 'provenance': [{'page_number': 1,
             'bbox_normalized': dict(zip(('left', 'top', 'right', 'bottom'), box))}],
            'quality': {'page_status': 'pass', 'content_status': 'not_semantically_validated'}}


def picture():
    return record('picture', 'picture', 'picture', (.1, .1, .9, .9))


class VisualTextTests(unittest.TestCase):
    def test_inside_quarantined_with_picture_link(self):
        chunks, report = c.build_chunks([record(), picture()], exclude_picture_text=True)
        self.assertEqual(chunks, [])
        item = report['skipped_records'][0]
        self.assertEqual(item['reason'], 'text_inside_picture_pending_vision')
        self.assertEqual(item['picture_record_ids'], ['picture'])
        self.assertEqual(item['minimum_text_area_coverage'], 1)

    def test_option_disabled_retains_text(self):
        chunks, report = c.build_chunks([record(), picture()])
        self.assertEqual(chunks[0]['text'], '60%')
        self.assertEqual(report['visual_text_review_records'], [])

    def test_outside_and_captions_retained_heading_context(self):
        outside = record('outside', box=(.1, .91, .9, .99))
        caption = record('caption', subtype='caption')
        heading = record('heading', subtype='section_header')
        chunks, report = c.build_chunks([outside, caption, heading, picture()], exclude_picture_text=True)
        self.assertEqual([x['record_ids'] for x in chunks], [['outside'], ['caption']])
        self.assertEqual(report['skipped_counts']['heading_used_as_context'], 1)

    def test_partial_overlap_retained_and_reported(self):
        chunks, report = c.build_chunks([record(box=(.8, .8, 1., 1.)), picture()], exclude_picture_text=True)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(report['visual_text_review_records'][0]['record_id'], 'text')

    def test_all_provenance_boxes_must_be_inside(self):
        r = record(); r['provenance'].append(record(box=(.1, .91, .9, .99))['provenance'][0])
        chunks, report = c.build_chunks([r, picture()], exclude_picture_text=True)
        self.assertEqual(len(chunks), 1)
        self.assertNotIn('text_inside_picture_pending_vision', report['skipped_counts'])

    def test_missing_invalid_bbox_not_silently_removed(self):
        for bad in (None, {'left': float('nan'), 'top': 0, 'right': 1, 'bottom': 1},
                    {'left': 1, 'top': 0, 'right': 0, 'bottom': 1}):
            r = record(); r['provenance'][0]['bbox_normalized'] = bad
            chunks, report = c.build_chunks([r, picture()], exclude_picture_text=True)
            self.assertEqual(len(chunks), 1)
            self.assertEqual(len(report['visual_text_review_records']), 1)

    def test_source_and_page_separation(self):
        for field, value in [('source_id', 'other'), ('source_sha256', 'other'), ('page_numbers', [2])]:
            p = picture(); p[field] = value
            if field == 'page_numbers': p['provenance'][0]['page_number'] = 2
            chunks, _ = c.build_chunks([record(), p], exclude_picture_text=True)
            self.assertEqual(len(chunks), 1)

    def test_determinism_and_no_input_mutation(self):
        rs = [record(), picture()]; before = copy.deepcopy(rs)
        first = c.build_chunks(rs, exclude_picture_text=True)
        self.assertEqual(first, c.build_chunks(rs, exclude_picture_text=True))
        self.assertEqual(rs, before)
        with self.assertRaises(ValueError): c.build_chunks(rs, exclude_picture_text='yes')


if __name__ == '__main__':
    unittest.main()
