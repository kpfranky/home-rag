from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ask import parser, run_pipeline


class AskTests(unittest.TestCase):
    def fixture(self, root, question='Pytanie?'):
        index = root / 'index with spaces'
        index.mkdir()
        for name in ['embeddings.jsonl', 'embedding_report.json']:
            (index / name).write_text('{}', encoding='utf-8')
        (root / 'scripts').mkdir()
        for name in ['search_chunks.py', 'assess_sources.py', 'answer_question.py']:
            (root / 'scripts' / name).write_text('', encoding='utf-8')
        return parser().parse_args([question, '--index-dir', 'index with spaces',
                                   '--output-dir', 'runs/test'])

    def runner(self, root, question, calls, fail=None, refusal=False, malformed=False):
        def execute(command, **kwargs):
            position = len(calls)
            calls.append(command)
            if position == fail:
                kwargs['stdout'].write('failure details')
                return SimpleNamespace(returncode=7)
            value = {'schema_name': ['home-rag-search', 'home-rag-answerability', 'home-rag-answer'][position],
                     'query': question, 'status': ['unused', 'assessed',
                         'insufficient_evidence' if refusal else 'answered'][position]}
            if position == 1:
                value['decision'] = {'sufficient': not refusal, 'source_ids': [] if refusal else ['S1']}
            if position == 2:
                value['rendered_answer'] = 'Brak odpowiedzi w dostarczonych źródłach.' if refusal else 'Odpowiedź [S1]'
            if malformed:
                value['query'] = 'different question'
            target = command[command.index('--output') + 1]
            path = root / target.removeprefix('/work/') if position == 0 else Path(target)
            path.write_text(json.dumps(value), encoding='utf-8')
            return SimpleNamespace(returncode=0)
        return execute

    def test_all_stages_use_same_index_and_python_and_preserve_question(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp)
            question = 'Czy "tekst" i $(touch NIE) mają znaczenie?'
            args = self.fixture(root, question)
            calls = []
            output = run_pipeline(args, root, self.runner(root, question, calls))
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0][calls[0].index('--query')+1], question)
            self.assertEqual(calls[0][calls[0].index('--network')+1], 'none')
            for command in calls[1:]:
                self.assertEqual(command[0], sys.executable)
                self.assertEqual(Path(command[command.index('--embeddings')+1]).resolve(),
                                 (root/'index with spaces/embeddings.jsonl').resolve())
            self.assertIn('--assessment', calls[2])
            manifest = json.loads((output/'run.json').read_text())
            self.assertEqual(manifest['status'], 'completed')
            self.assertTrue(all(s['status']=='completed' for s in manifest['stages']))

    def test_refusal_still_produces_audited_answer(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as stream:
            root = Path(tmp); args = self.fixture(root); calls = []
            output = run_pipeline(args, root, self.runner(root, args.question, calls, refusal=True))
            self.assertEqual(len(calls), 3)
            self.assertIn('Brak odpowiedzi', stream.getvalue())
            self.assertEqual(json.loads((output/'run.json').read_text())['answer_status'], 'insufficient_evidence')

    def test_failed_stage_stops_later_stages_and_saves_diagnostic(self):
        for fail in [0, 1]:
            with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
                root = Path(tmp); args = self.fixture(root); calls = []
                with self.assertRaises(RuntimeError):
                    run_pipeline(args, root, self.runner(root, args.question, calls, fail=fail))
                self.assertEqual(len(calls), fail+1)
                manifest = json.loads((root/'runs/test/run.json').read_text())
                self.assertEqual(manifest['status'], 'failed')
                self.assertEqual(manifest['stages'][-1]['exit_code'], 7)
                self.assertFalse((root/'runs/test/answer.json').exists())

    def test_success_exit_with_wrong_result_does_not_continue(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp); args = self.fixture(root); calls = []
            with self.assertRaises(RuntimeError):
                run_pipeline(args, root, self.runner(root, args.question, calls, malformed=True))
            self.assertEqual(len(calls), 1)

    def test_existing_run_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp); args = self.fixture(root); calls = []
            (root/'runs/test').mkdir(parents=True)
            (root/'runs/test/answer.json').write_text('keep')
            with self.assertRaises(FileExistsError):
                run_pipeline(args, root, self.runner(root, args.question, calls))
            self.assertEqual(calls, [])
            self.assertEqual((root/'runs/test/answer.json').read_text(), 'keep')

    def test_missing_index_or_paths_outside_project_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self.fixture(root); calls = []
            args.index_dir = Path('../outside')
            with self.assertRaises(ValueError): run_pipeline(args, root, self.runner(root,args.question,calls))
            args.index_dir = Path('missing')
            with self.assertRaises(ValueError): run_pipeline(args, root, self.runner(root,args.question,calls))
            self.assertEqual(calls, [])

    def test_empty_question_and_bad_parameters_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self.fixture(root); calls = []
            args.question = ' '
            with self.assertRaises(ValueError): run_pipeline(args, root, self.runner(root,args.question,calls))
            args.question = 'Pytanie'; args.top_k = 0
            with self.assertRaises(ValueError): run_pipeline(args, root, self.runner(root,args.question,calls))
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
