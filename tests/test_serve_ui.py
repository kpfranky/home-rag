import argparse
import http.client
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from serve_ui import Jobs,Server,present_answer


def options(demo=True):
    return argparse.Namespace(demo=demo,index_dir=Path('index'),model='local',top_k=8,
                              api_url='http://127.0.0.1:11434',timeout=600)


class UITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'scripts').mkdir();(self.root/'web').mkdir()
        shutil.copy(ROOT/'scripts/ui_demo_backend.py',self.root/'scripts/ui_demo_backend.py')
        shutil.copy(ROOT/'web/index.html',self.root/'web/index.html')
        self.jobs=Jobs(self.root,options());self.server=Server(('127.0.0.1',0),self.jobs)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()

    def tearDown(self):
        self.jobs.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        data=json.dumps(body).encode() if body is not None else None
        h={'X-Home-RAG-Token':self.jobs.token,'Content-Type':'application/json'};h.update(headers or {})
        conn.request(method,path,data,h);r=conn.getresponse();raw=r.read();status=r.status
        result=(status,raw,dict(r.getheaders()));conn.close();return result

    def complete(self,question):
        status,raw,_=self.request('POST','/api/jobs',{'question':question})
        self.assertEqual(status,202)
        ident=json.loads(raw)['id'];deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            status,raw,_=self.request('GET','/api/jobs/'+ident);job=json.loads(raw)
            if job['status']!='running' and self.jobs.active is None:return ident,job
            time.sleep(.01)
        self.fail('Demo did not complete')

    def test_page_contains_session_token_and_restricts_scripts(self):
        status,raw,headers=self.request('GET','/')
        self.assertEqual(status,200);self.assertIn(self.jobs.token.encode(),raw)
        self.assertNotIn(b'{{TOKEN}}',raw);self.assertIn("script-src 'nonce-",headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET','/api/config')[0],200)

    def test_foreign_host_origin_and_missing_token_rejected(self):
        self.assertEqual(self.request('GET','/',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/jobs',{'question':'x'},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/jobs',{'question':'x'},headers={'X-Home-RAG-Token':'wrong'})[0],403)
        self.assertIsNone(self.jobs.active)

    def test_bad_questions_and_unknown_routes_rejected(self):
        for payload in ({'question':'  '},{'question':'a'*2001},{'question':[]},{'question':'x','model':'remote'}):
            self.assertEqual(self.request('POST','/api/jobs',payload)[0],400)
        self.assertEqual(self.request('GET','/api/jobs/../../README.md')[0],404)
        self.assertEqual(self.request('GET','/api/jobs/'+'a'*32)[0],404)

    def test_real_subprocess_demo_produces_cited_answer_and_download(self):
        ident,job=self.complete('Jakie kroki obejmuje przygotowanie dokumentów?')
        self.assertEqual(job['status'],'completed');self.assertTrue(job['result']['answerable'])
        self.assertEqual(len(job['result']['sources']),1)
        status,raw,_=self.request('GET','/api/jobs/'+ident+'/answer')
        self.assertEqual(status,200);self.assertTrue(json.loads(raw)['demo'])
        self.assertEqual(self.request('GET','/api/jobs/'+ident+'/log')[0],200)

    def test_refusal_is_successful_result_with_no_sources(self):
        _,job=self.complete('Jak założyć winnicę?')
        self.assertEqual(job['status'],'completed');self.assertFalse(job['result']['answerable'])
        self.assertEqual(job['result']['sources'],[])

    def test_backend_failure_is_visible_and_frees_worker(self):
        (self.root/'scripts/ask.py').write_text('raise SystemExit(7)\n')
        self.jobs.options.demo=False
        _,job=self.complete('Test błędu')
        self.assertEqual(job['status'],'failed');self.assertIn('7',job['error'])
        self.assertIsNone(self.jobs.active)

    def test_second_job_is_not_started_while_busy(self):
        with patch('threading.Thread.start'):
            self.jobs.submit('Pierwsze pytanie')
            with self.assertRaises(RuntimeError):self.jobs.submit('Drugie pytanie')
        self.assertEqual(len(self.jobs.jobs),1)

    def test_citations_validated_and_text_not_interpreted_as_html(self):
        quote='<script>alert(1)</script>'
        value={'schema_name':'home-rag-answer','status':'answered','query':'q',
               'answer':{'answerable':True,'claims':[{'text':quote,'evidence':[{'source_id':'S1','quote':quote}]}]},
               'sources':[{'source_id':'S1','chunk_id':'c','chunk':{'source_id':'demo','text':quote}}]}
        self.assertEqual(present_answer(value)['claims'][0]['text'],quote)
        value['answer']['claims'][0]['evidence'][0]['quote']='forged'
        with self.assertRaises(ValueError):present_answer(value)


if __name__=='__main__':unittest.main()
