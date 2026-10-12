import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import evaluate_rag as ev


class EvaluationTests(unittest.TestCase):
    def case(self, answerable=True):
        return dict(id='A1', question='Pytanie?', answerable=answerable, expected_answer='59% (61)',
                    answer_patterns=[r'59\s*%\s*\(61\)'] if answerable else [],
                    source_patterns=['alergia'] if answerable else [])

    def results(self):
        source = dict(source_id='S2', chunk_id='chunk1', chunk={'text':'alergia 59% (61)'})
        answer = dict(query='Pytanie?', sources=[source], rendered_answer='59% (61) [S2]',
                      answer=dict(answerable=True, claims=[dict(text='59% (61)',
                      evidence=[dict(source_id='S2', quote='alergia 59% (61)')])]))
        return answer, dict(query='Pytanie?', results=[source])

    def test_checks_claims_only_not_rendered_quotes(self):
        answer, search = self.results()
        self.assertTrue(ev.inspect_result(self.case(), answer, search)['signals_ok'])
        answer['answer']['claims'][0]['text']='Efekty pozytywne.'
        self.assertFalse(ev.inspect_result(self.case(), answer, search)['signals_ok'])

    def test_wrong_quote_and_absent_retrieval_rejected(self):
        answer, search = self.results()
        answer['answer']['claims'][0]['evidence'][0]['quote']='zmyślony cytat'
        checks = ev.inspect_result(self.case(), answer, {'results':[]})
        self.assertFalse(checks['quotes_present_in_sources'])
        self.assertEqual(checks['missing_retrieval_patterns'], ['alergia'])

    def test_refusal_and_false_positive_answer(self):
        answer, search = self.results()
        self.assertFalse(ev.inspect_result(self.case(False), answer, search)['signals_ok'])
        answer['answer']=dict(answerable=False, claims=[])
        self.assertTrue(ev.inspect_result(self.case(False), answer, search)['signals_ok'])

    def test_suite_rejects_duplicate_and_path_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'suite.json'
            for cases in ([self.case(), self.case()], [{**self.case(), 'id':'../escape'}]):
                p.write_text(json.dumps(dict(schema_name='home-rag-evaluation-suite',schema_version=1,cases=cases)))
                with self.assertRaises(ValueError): ev.load_suite(p)

    def test_pipeline_failure_continues_and_report_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            suite=dict(schema_name='home-rag-evaluation-suite',schema_version=1,
                       cases=[self.case(), {**self.case(), 'id':'A2'}])
            (root/'suite.json').write_text(json.dumps(suite))
            args=argparse.Namespace(suite=Path('suite.json'),case=None,output_dir=Path('evaluation'),
                 index_dir=Path('index'),model='local',think='false',top_k=5,api_url='http://localhost',
                 timeout=600,embedding_image='image')
            calls=[]
            def fake(config, **kwargs):
                calls.append(config.question)
                if len(calls)==1: raise RuntimeError('failed stage')
                config.output_dir.mkdir()
                a,s=self.results()
                (config.output_dir/'answer.json').write_text(json.dumps(a))
                (config.output_dir/'search.json').write_text(json.dumps(s))
            self.assertEqual(ev.evaluate(args,root,fake),2)
            report=json.loads((root/'evaluation/evaluation.json').read_text())
            self.assertEqual([c['status'] for c in report['cases']],['error','completed'])
            self.assertEqual(report['summary']['human_reviews_pending'],2)
            with self.assertRaises(FileExistsError): ev.evaluate(args,root,fake)

    def test_delivered_suite_has_fifteen_unique_cases(self):
        suite=ev.load_suite(SCRIPTS.parent/'config/evaluation/sample_book_100_v1.json')
        self.assertEqual(len(suite['cases']),15)
        self.assertEqual(sum(not c['answerable'] for c in suite['cases']),4)


if __name__=='__main__': unittest.main()
