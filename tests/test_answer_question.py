from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from answer_question import (NO_ANSWER, load_sources, local_model, messages_for,
                             MAX_CLAIMS, SCHEMA, main, render_answer, validate_answer,
                             validate_extraction, validate_selected_evidence,
                             evidence_catalog, resolve_answer, extraction_schema,
                             select_assessed_sources)


def source():
    return {'source_id': 'S1', 'chunk_id': 'chunk1', 'chunk': {
        'text': 'Słowo wstępu.\n\nmgr farm. Marcin Mól',
        'source_id': 'book', 'source_sha256': 'hash', 'page_numbers': [11],
        'printed_page_labels': ['17'], 'block_ids': ['#/texts/54'],
        'provenance': [{'page_number': 11, 'charspan': [0, 20]}]}}


def answer():
    return {'answerable': True, 'claims': [{
        'text': 'Słowo wstępu podpisał Marcin Mól.',
        'evidence': [{'source_id': 'S1', 'quote': 'mgr farm. Marcin Mól'}]}]}


class AnswerTests(unittest.TestCase):
    def test_renderer_deduplicates_exact_quotes_without_mutating_evidence(self):
        item = answer()
        item['claims'].append(deepcopy(item['claims'][0]))
        item['claims'][1]['text'] = 'Drugie twierdzenie z tym samym dowodem.'
        sources = [source()]
        before_answer, before_sources = deepcopy(item), deepcopy(sources)
        rendered = render_answer(item, sources)
        self.assertEqual(rendered.count('[S1] „mgr farm. Marcin Mól”'), 1)
        self.assertIn('Słowo wstępu podpisał Marcin Mól. [S1]', rendered)
        self.assertIn('Drugie twierdzenie z tym samym dowodem. [S1]', rendered)
        self.assertEqual(item, before_answer)
        self.assertEqual(sources, before_sources)
        self.assertEqual(render_answer(item, sources), rendered)

    def test_renderer_keeps_distinct_quotes_and_distinct_sources(self):
        first, second = source(), source()
        second['source_id'], second['chunk_id'] = 'S2', 'chunk2'
        item = answer()
        item['claims'][0]['evidence'].extend([
            {'source_id': 'S1', 'quote': 'Słowo wstępu.'},
            {'source_id': 'S2', 'quote': 'mgr farm. Marcin Mól'}])
        rendered = render_answer(validate_answer(item, [first, second]), [first, second])
        quotes = rendered.split('Cytaty uzasadniające:')[1]
        self.assertEqual(quotes.count('[S1] „mgr farm. Marcin Mól”'), 1)
        self.assertEqual(quotes.count('[S1] „Słowo wstępu.”'), 1)
        self.assertEqual(quotes.count('[S2] „mgr farm. Marcin Mól”'), 1)

    def test_list_longer_than_four_preserves_each_citation(self):
        sources = [{'source_id': 'S1', 'chunk_id': 'list', 'chunk': {
            'text': 'Pozycja A, Pozycja B, Pozycja C, Pozycja D, Pozycja E.'}}]
        item = {'answerable': True, 'claims': [
            {'text': f'Pozycja {letter}', 'evidence': [
                {'source_id': 'S1', 'quote': f'Pozycja {letter}'}]}
            for letter in 'ABCDE']}
        validated = validate_answer(item, sources)
        self.assertEqual(len(validated['claims']), 5)
        self.assertEqual(validated, item)

    def test_claim_limit_and_schema_agree(self):
        self.assertEqual(SCHEMA['properties']['claims']['maxItems'], MAX_CLAIMS)
        item = {'answerable': True, 'claims': [
            deepcopy(answer()['claims'][0]) for _ in range(MAX_CLAIMS)]}
        validate_answer(item, [source()])
        item['claims'].append(deepcopy(item['claims'][0]))
        with self.assertRaises(ValueError):
            validate_answer(item, [source()])

    def run_generation(self, generated, done_reason='stop', mode='single-pass', extracted=None,
                       extra_args=(), thinking=None, assessment_decision=None,
                       input_sources=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name) / 'answer.json'
        response = {'done': True, 'done_reason': done_reason,
                    'message': {'content': json.dumps(generated)}}
        if thinking is not None:
            response['message']['thinking'] = thinking
        arguments = ['answer_question.py', str(Path(directory.name) / 'search.json'),
                     '--model', 'local', '--mode', mode, '--output', str(output), *extra_args]
        sources = input_sources if input_sources is not None else [source()]
        if assessment_decision is not None:
            assessment_path = Path(directory.name) / 'assessment.json'
            assessment_path.write_text(json.dumps({
                'schema_name': 'home-rag-answerability', 'schema_version': 1,
                'status': 'assessed', 'query': 'Kto podpisał?', 'sources': sources,
                'search_sha256': 'searchhash', 'index_sha256': 'hash',
                'decision': assessment_decision}))
            arguments.extend(['--assessment', str(assessment_path)])
        responses = [response]
        if mode == 'two-stage':
            responses.insert(0, {'done': True, 'done_reason': 'stop',
                                 'message': {'content': json.dumps(extracted)}})
        report = {'output_sha256': 'hash', 'model': {'model_id': 'e5'}}
        with patch.object(sys, 'argv', arguments), \
                patch('answer_question.load_sources', return_value=(
                    'Kto podpisał?', sources, 'searchhash', report)), \
                patch('answer_question.local_model', return_value=('local', 'digest')) as model, \
                patch('answer_question.api_request', side_effect=responses) as api, \
                patch('builtins.print'):
            try:
                main()
            except SystemExit as error:
                self.last_requests = [call.args[2] for call in api.call_args_list]
                return json.loads(output.read_text()), error
        self.last_requests = [call.args[2] for call in api.call_args_list]
        self.last_model_calls = model.call_count
        return json.loads(output.read_text()), None

    def test_assessment_negative_bypasses_all_model_requests_and_retains_audit(self):
        result, error = self.run_generation(answer(), assessment_decision={
            'sufficient': False, 'source_ids': [], 'reason': 'Brak dowodów.'})
        self.assertIsNone(error)
        self.assertEqual(self.last_requests, [])
        self.assertEqual(self.last_model_calls, 0)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['retrieved_sources'], [source()])
        self.assertEqual(result['assessment']['report']['decision']['reason'], 'Brak dowodów.')
        self.assertEqual(result['stages'], [])

    def test_assessment_selected_source_only_reaches_extraction_and_synthesis(self):
        other = deepcopy(source())
        other['source_id'], other['chunk_id'], other['chunk']['text'] = 'S3', 'other', 'Paracelsus'
        generated = {'answerable': True, 'claims': [
            {'text': 'Podpisał Marcin Mól.', 'evidence_ids': ['S1:E1']}]}
        result, error = self.run_generation(generated, mode='two-stage', extracted={
            'items': [{'text': 'Marcin Mól', 'evidence_id': 'S1:E1'}]},
            assessment_decision={'sufficient': True, 'source_ids': ['S1'], 'reason': 'Podpis.'},
            input_sources=[source(), other])
        self.assertIsNone(error)
        self.assertEqual(result['selected_source_ids'], ['S1'])
        self.assertEqual(result['retrieved_sources'], [source(), other])
        self.assertEqual(result['sources'], [source()])
        self.assertEqual(len(self.last_requests), 2)
        self.assertTrue(all('Paracelsus' not in json.dumps(r) for r in self.last_requests))

    def test_assessment_mismatches_and_invalid_decisions_rejected(self):
        base = {'schema_name': 'home-rag-answerability', 'schema_version': 1,
                'status': 'assessed', 'query': 'Pytanie?', 'sources': [source()],
                'search_sha256': 'searchhash', 'index_sha256': 'indexhash',
                'decision': {'sufficient': True, 'source_ids': ['S1'], 'reason': 'Dowód.'}}
        changes = [('query', 'Inne?'), ('search_sha256', 'other'), ('index_sha256', 'other'),
                   ('sources', []), ('status', 'prepared'), ('schema_version', 2),
                   ('decision', {'sufficient': True, 'source_ids': ['S99'], 'reason': 'X'}),
                   ('decision', {'sufficient': False, 'source_ids': ['S1'], 'reason': 'X'}),
                   ('decision', {'sufficient': True, 'source_ids': ['S1', 'S1'], 'reason': 'X'})]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'assessment.json'
            for key, value in changes:
                candidate = deepcopy(base); candidate[key] = value
                path.write_text(json.dumps(candidate))
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    select_assessed_sources(path, 'Pytanie?', [source()], 'searchhash', 'indexhash')
            candidate = deepcopy(base); candidate['sources'][0]['chunk']['text'] = 'Changed text'
            path.write_text(json.dumps(candidate))
            with self.assertRaises(ValueError):
                select_assessed_sources(path, 'Pytanie?', [source()], 'searchhash', 'indexhash')

    def test_assessment_preserves_retrieval_order_and_original_source_ids(self):
        first, third = source(), deepcopy(source())
        third['source_id'], third['chunk_id'] = 'S3', 'chunk3'
        sources = [first, third]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'assessment.json'
            path.write_text(json.dumps({'schema_name': 'home-rag-answerability',
                'schema_version': 1, 'status': 'assessed', 'query': 'Q', 'sources': sources,
                'search_sha256': 's', 'index_sha256': 'i', 'decision': {
                    'sufficient': True, 'source_ids': ['S3', 'S1'], 'reason': 'Dowody.'}}))
            selected, audit = select_assessed_sources(path, 'Q', sources, 's', 'i')
            self.assertEqual([s['source_id'] for s in selected], ['S1', 'S3'])
            self.assertEqual(len(audit['sha256']), 64)

    def test_think_modes_apply_to_every_stage_and_preserve_trace(self):
        extracted = {'items': [{'text': 'Podpis: Marcin Mól', 'evidence_id': 'S1:E1'}]}
        synthesized = {'answerable': True, 'claims': [
            {'text': 'Podpisał Marcin Mól.', 'evidence_ids': ['S1:E1']}]}
        for mode in ('single-pass', 'two-stage'):
            for think in ('false', 'true', 'auto'):
                with self.subTest(mode=mode, think=think):
                    result, error = self.run_generation(
                        answer() if mode == 'single-pass' else synthesized,
                        mode=mode, extracted=extracted,
                        extra_args=['--think', think, '--num-predict', '4096'],
                        thinking='A trace that must not become the answer')
                    self.assertIsNone(error)
                    self.assertEqual(result['thinking_mode'], think)
                    self.assertEqual(len(self.last_requests), 1 if mode == 'single-pass' else 2)
                    for request in self.last_requests:
                        if think == 'auto':
                            self.assertNotIn('think', request)
                        else:
                            self.assertIs(request['think'], think == 'true')
                        self.assertNotIn('think', request['options'])
                        self.assertEqual(request['options']['num_predict'], 4096)
                    self.assertEqual(result['stages'][-1]['raw_response']['message']['thinking'],
                                     'A trace that must not become the answer')
                    self.assertNotIn('A trace', result['rendered_answer'])

    def test_default_think_false_and_original_generation_budget(self):
        result, error = self.run_generation(answer())
        self.assertIsNone(error)
        self.assertIs(self.last_requests[0]['think'], False)
        self.assertEqual(result['options']['num_predict'], 2048)

    def test_think_enabled_does_not_accept_truncated_response(self):
        result, error = self.run_generation(answer(), done_reason='length',
                                            extra_args=['--think', 'true'], thinking='Trace')
        self.assertIsNotNone(error)
        self.assertEqual(result['status'], 'validation_failed')
        self.assertEqual(result['stages'][0]['raw_response']['message']['thinking'], 'Trace')
        self.assertNotIn('rendered_answer', result)

    def test_generation_saves_validated_answer(self):
        result, error = self.run_generation(answer())
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['model_digest'], 'digest')
        self.assertIn('[S1]', result['rendered_answer'])

    def test_generation_rejects_bad_quote_and_truncated_response(self):
        bad = answer()
        bad['claims'][0]['evidence'][0]['quote'] = 'Nieobecny cytat'
        for item, reason in ((bad, 'stop'), (answer(), 'length')):
            result, error = self.run_generation(item, reason)
            self.assertIsNotNone(error)
            self.assertEqual(result['status'], 'validation_failed')
            self.assertNotIn('rendered_answer', result)
            self.assertEqual(result['stages'][-1]['raw_response']['message']['content'],
                             json.dumps(item))

    def test_extraction_checks_quotes(self):
        extracted = {'items': [{'text': 'Podpis: Marcin Mól', 'evidence_id': 'S1:E1'}]}
        items = validate_extraction(extracted, source())
        self.assertEqual(items[0]['source_id'], 'S1')
        self.assertEqual(validate_extraction({'items': []}, source()), [])
        self.assertEqual(items[0]['quote'], source()['chunk']['text'])
        extracted['items'][0]['evidence_id'] = 'S1:E99'
        with self.assertRaises(ValueError):
            validate_extraction(extracted, source())

    def test_two_stage_success_records_extraction_and_raw_response(self):
        extracted = {'items': [{'text': 'Podpis: Marcin Mól', 'evidence_id': 'S1:E1'}]}
        generated = {'answerable': True, 'claims': [
            {'text': 'Podpisał Marcin Mól.', 'evidence_ids': ['S1:E1']}]}
        result, error = self.run_generation(generated, mode='two-stage', extracted=extracted)
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual([s['stage'] for s in result['stages']], ['extraction', 'synthesis'])
        self.assertEqual(result['extracted_items'][0]['source_id'], 'S1')
        self.assertTrue(all('raw_response' in s for s in result['stages']))

    def test_empty_extraction_abstains_without_synthesis(self):
        result, error = self.run_generation(answer(), mode='two-stage', extracted={'items': []})
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(len(result['stages']), 1)

    def test_synthesis_cannot_cite_unselected_quote(self):
        items = [{'source_id': 'S1', 'text': 'Nagłówek', 'quote': 'Słowo wstępu.'}]
        with self.assertRaises(ValueError):
            validate_selected_evidence(answer(), items)
        generated = {'answerable': True, 'claims': [
            {'text': 'Podpisał Marcin Mól.', 'evidence_ids': ['S1:E99']}]}
        result, error = self.run_generation(generated, mode='two-stage', extracted={
            'items': [{'text': 'Podpis', 'evidence_id': 'S1:E1'}]})
        self.assertIsNotNone(error)
        self.assertEqual(result['status'], 'validation_failed')
        self.assertIn('unknown evidence_id', result['error'])

    def test_catalog_offsets_cover_nonwhitespace_without_rewriting(self):
        item = source()
        item['chunk']['text'] = ('To jest zdanie ze źródła. ' * 40) + 'mgr farm. Marcin Mól'
        catalog = evidence_catalog(item)
        covered = set()
        for evidence in catalog:
            start, end = evidence['text_span']['start'], evidence['text_span']['end']
            self.assertEqual(evidence['quote'], item['chunk']['text'][start:end])
            self.assertLessEqual(len(evidence['quote']), 320)
            self.assertFalse(covered.intersection(range(start, end)))
            covered.update(range(start, end))
        self.assertTrue(all(i in covered for i, ch in enumerate(item['chunk']['text'])
                            if not ch.isspace()))
        enum = extraction_schema(item)['properties']['items']['items']['properties']['evidence_id']['enum']
        self.assertEqual(enum, [e['evidence_id'] for e in catalog])

    def test_quote_is_resolved_by_program_not_generated_by_model(self):
        items = validate_extraction({'items': [
            {'text': 'Podpis', 'evidence_id': 'S1:E1'}]}, source())
        result = resolve_answer({'answerable': True, 'claims': [
            {'text': 'Podpisał Marcin Mól.', 'evidence_ids': ['S1:E1']}]}, items, [source()])
        self.assertEqual(result['claims'][0]['evidence'][0]['quote'], source()['chunk']['text'])

    def test_valid_answer_and_citations_from_metadata(self):
        sources = [source()]
        before = deepcopy(sources)
        validated = validate_answer(answer(), sources)
        rendered = render_answer(validated, sources)
        self.assertIn('[S1]', rendered)
        self.assertIn('strona PDF [11]', rendered)
        self.assertIn("['17']", rendered)
        self.assertIn('„mgr farm. Marcin Mól”', rendered)
        self.assertEqual(sources, before)

    def test_unknown_id_and_invented_quote_rejected(self):
        for key, value in (('source_id', 'S99'), ('quote', 'mgr farm. Jan Kowalski'),
                           ('quote', 'Słowo mgr farm. Marcin Mól'), ('quote', '')):
            item = answer()
            item['claims'][0]['evidence'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_answer(item, [source()])

    def test_whitespace_only_quote_normalization(self):
        item = answer()
        item['claims'][0]['evidence'][0]['quote'] = 'Słowo wstępu. mgr farm. Marcin Mól'
        validate_answer(item, [source()])
        item['claims'][0]['evidence'][0]['quote'] = 'slowo wstepu.'
        with self.assertRaises(ValueError):
            validate_answer(item, [source()])

    def test_abstention_and_contradictory_claims(self):
        empty = {'answerable': False, 'claims': []}
        self.assertEqual(render_answer(validate_answer(empty, []), []), NO_ANSWER)
        item = answer()
        item['answerable'] = False
        with self.assertRaises(ValueError):
            validate_answer(item, [source()])

    def test_schema_missing_evidence_and_forged_marker(self):
        invalid = [None, {'answerable': 1, 'claims': []},
                   {'answerable': True, 'claims': []}]
        for field, value in (('evidence', []), ('text', 'Tekst [S99]'), ('text', '')):
            item = answer()
            item['claims'][0][field] = value
            invalid.append(item)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_answer(item, [source()])

    def test_prompt_and_context_guard(self):
        messages = messages_for('Kto podpisał?', [source()])
        payload = json.loads(messages[1]['content'])
        self.assertEqual(payload['sources'][0]['text'], source()['chunk']['text'])
        self.assertEqual(messages[0]['role'], 'system')
        with self.assertRaises(ValueError):
            messages_for('Pytanie', [source()], max_context_chars=2)

    def test_installed_model_digest_and_cloud_rejection(self):
        with patch('answer_question.api_request', return_value={
                'models': [{'name': 'local:latest', 'digest': 'digest'}]}):
            self.assertEqual(local_model('http://localhost:11434', 'local', 1),
                             ('local:latest', 'digest'))
            with self.assertRaises(ValueError):
                local_model('http://localhost:11434', 'missing', 1)
        with patch('answer_question.api_request', return_value={
                'models': [{'name': 'remote-cloud', 'digest': 'digest'}]}):
            with self.assertRaises(ValueError):
                local_model('http://localhost:11434', 'remote-cloud', 1)

    def test_retrieval_index_and_original_chunk_match(self):
        report = {'output_sha256': 'hash', 'model': {'model_id': 'e5', 'revision': 'rev'}}
        record = {'chunk_id': 'chunk1', 'chunk': source()['chunk']}
        search = {'schema_name': 'home-rag-search', 'schema_version': 1,
                  'index_sha256': 'hash', 'index_chunks': 1,
                  'model_id': 'e5', 'model_revision': 'rev', 'query': 'Kto podpisał?',
                  'results': [{'chunk_id': 'chunk1', 'rank': 1, 'chunk': record['chunk']}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'search.json'
            report_path = Path(directory) / 'report.json'
            report_path.write_text(json.dumps(report))
            with patch('answer_question.load_index', return_value=([record], [], report)):
                path.write_text(json.dumps(search))
                query, sources, _, _ = load_sources(path, path, report_path, 3)
                self.assertEqual(query, 'Kto podpisał?')
                self.assertEqual(sources[0]['chunk'], record['chunk'])
                search['results'][0]['chunk'] = dict(record['chunk'], text='Changed')
                path.write_text(json.dumps(search))
                with self.assertRaises(ValueError):
                    load_sources(path, path, report_path, 3)

    def test_duplicate_retrieval_rejected(self):
        report = {'output_sha256': 'hash', 'model': {'model_id': 'e5', 'revision': 'rev'}}
        record = {'chunk_id': 'chunk1', 'chunk': source()['chunk']}
        search = {'schema_name': 'home-rag-search', 'schema_version': 1,
                  'index_sha256': 'hash', 'index_chunks': 1,
                  'model_id': 'e5', 'model_revision': 'rev', 'query': 'Pytanie',
                  'results': [{'chunk_id': 'chunk1', 'rank': i, 'chunk': record['chunk']}
                              for i in (1, 2)]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'search.json'
            rp = Path(directory) / 'report.json'
            path.write_text(json.dumps(search))
            rp.write_text(json.dumps(report))
            with patch('answer_question.load_index', return_value=([record], [], report)), \
                    self.assertRaises(ValueError):
                load_sources(path, path, rp, 1)


if __name__ == '__main__':
    unittest.main()
