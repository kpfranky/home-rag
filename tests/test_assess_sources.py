import json
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from assess_sources import assessment_messages, main, validate_decision

SOURCES = [{'source_id': 'S1', 'chunk': {'text': 'Przykładowy fragment źródła.'}}]


class AssessmentTests(unittest.TestCase):
    def run_mock_assessment(self, extra_args, response):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'decision.json'
            args = ['assess_sources.py', str(Path(directory) / 'search.json'),
                    '--model', 'local', '--output', str(output), *extra_args]
            with patch.object(sys, 'argv', args), \
                    patch('assess_sources.load_sources', return_value=(
                        'Pytanie?', SOURCES, 'searchhash', {'output_sha256': 'indexhash'})), \
                    patch('assess_sources.local_model', return_value=('local', 'digest')), \
                    patch('assess_sources.api_request', return_value=response) as api, \
                    patch('builtins.print'):
                try:
                    main()
                except SystemExit:
                    saved = json.loads(output.read_text()) if output.exists() else None
                    return saved, api, True
            return json.loads(output.read_text()), api, False

    def test_thinking_modes_sent_at_request_top_level_and_audited(self):
        response = {'done': True, 'done_reason': 'stop', 'message': {
            'thinking': 'Internal trace', 'content': json.dumps({
                'sufficient': False, 'source_ids': [], 'reason': 'Brak informacji.'})}}
        for mode, expected in (('false', False), ('true', True), ('auto', None)):
            with self.subTest(mode=mode):
                saved, api, failed = self.run_mock_assessment(
                    ['--think', mode, '--num-predict', '2048'], response)
                self.assertFalse(failed)
                request = api.call_args.args[2]
                if mode == 'auto':
                    self.assertNotIn('think', request)
                else:
                    self.assertIs(request['think'], expected)
                self.assertNotIn('think', request['options'])
                self.assertEqual(request['options']['num_predict'], 2048)
                self.assertEqual(saved['thinking_mode'], mode)
                self.assertEqual(saved['raw_response'], response)

    def test_default_disables_thinking_and_keeps_generation_budget(self):
        response = {'done': True, 'done_reason': 'stop', 'message': {'content':
            json.dumps({'sufficient': False, 'source_ids': [], 'reason': 'Brak informacji.'})}}
        saved, api, failed = self.run_mock_assessment([], response)
        self.assertFalse(failed)
        self.assertIs(api.call_args.args[2]['think'], False)
        self.assertEqual(saved['options']['num_predict'], 512)

    def test_thinking_only_and_truncated_responses_rejected_with_raw_audit(self):
        for reason in ('stop', 'length'):
            response = {'done': True, 'done_reason': reason,
                        'message': {'thinking': 'Unfinished trace', 'content': ''}}
            saved, api, failed = self.run_mock_assessment(['--think', 'true'], response)
            self.assertTrue(failed)
            self.assertEqual(saved['status'], 'assessment_failed')
            self.assertEqual(saved['raw_response'], response)
            self.assertNotIn('decision', saved)

    def test_context_preserved_separately_from_source_text(self):
        sources = [{'source_id': 'S1', 'chunk': {
            'text': 'mgr farm. Marcin Mól', 'section_path': ['Słowo wstępu'],
            'chunk_type': 'text', 'page_role': 'body', 'page_numbers': [11],
            'printed_page_labels': ['17'], 'block_ids': ['#/texts/54']}}]
        before = deepcopy(sources)
        payload = json.loads(assessment_messages('Kto podpisał słowo wstępu?', sources)[1]['content'])
        fragment = payload['sources'][0]
        self.assertEqual(fragment['text'], before[0]['chunk']['text'])
        self.assertEqual(fragment['context'], {
            key: value for key, value in before[0]['chunk'].items() if key != 'text'})
        self.assertEqual(sources, before)
        minimal = json.loads(assessment_messages('Pytanie?', SOURCES)[1]['content'])
        self.assertEqual(minimal['sources'][0]['context'], {})

    def test_oversized_metadata_rejected_without_truncation(self):
        sources = deepcopy(SOURCES)
        sources[0]['chunk']['section_path'] = ['x' * 15000]
        with self.assertRaises(ValueError):
            assessment_messages('Pytanie?', sources)

    def test_positive_and_negative_schema(self):
        for sufficient, ids in ((True, ['S1']), (False, [])):
            value = {'sufficient': sufficient, 'source_ids': ids, 'reason': 'Uzasadnienie'}
            self.assertEqual(validate_decision(value, SOURCES), value)

    def test_contradictions_unknown_duplicate_and_wrong_types(self):
        for sufficient, ids in ((True, []), (False, ['S1']),
                                (True, ['S99']), (True, ['S1', 'S1']), (1, ['S1'])):
            with self.subTest(sufficient=sufficient, ids=ids), self.assertRaises(ValueError):
                validate_decision({'sufficient': sufficient, 'source_ids': ids,
                                   'reason': 'Uzasadnienie'}, SOURCES)

    def test_prompt_preserves_question_and_sources(self):
        messages = assessment_messages('Pytanie?', SOURCES)
        payload = json.loads(messages[1]['content'])
        self.assertEqual(payload['question'], 'Pytanie?')
        self.assertEqual(payload['sources'][0]['text'], SOURCES[0]['chunk']['text'])
        with self.assertRaises(ValueError):
            assessment_messages('x' * 2001, SOURCES)

    def test_cli_saves_decision_and_raw_response(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'decision.json'
            decision = {'sufficient': False, 'source_ids': [], 'reason': 'Brak informacji.'}
            response = {'done': True, 'done_reason': 'stop',
                        'message': {'content': json.dumps(decision)}}
            args = ['assess_sources.py', str(Path(directory) / 'search.json'),
                    '--model', 'local', '--output', str(output)]
            with patch.object(sys, 'argv', args), \
                    patch('assess_sources.load_sources', return_value=(
                        'Pytanie?', SOURCES, 'searchhash', {'output_sha256': 'indexhash'})), \
                    patch('assess_sources.local_model', return_value=('local', 'digest')), \
                    patch('assess_sources.api_request', return_value=response), \
                    patch('builtins.print'):
                main()
            saved = json.loads(output.read_text())
            self.assertEqual(saved['status'], 'assessed')
            self.assertEqual(saved['decision'], decision)
            self.assertEqual(saved['raw_response'], response)


if __name__ == '__main__':
    unittest.main()
