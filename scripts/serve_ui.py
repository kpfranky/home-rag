"""Serve the Home RAG interface on loopback using only Python's standard library."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid

VERSION = '0.1.0'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def present_answer(value):
    if value.get('schema_name') != 'home-rag-answer' or value.get('status') not in {
            'answered', 'insufficient_evidence', 'no_sources'}:
        raise ValueError('Niepoprawny format odpowiedzi backendu.')
    answer = value['answer']
    if type(answer['answerable']) is not bool or not isinstance(answer['claims'], list):
        raise ValueError('Niepoprawne twierdzenia w odpowiedzi.')
    lookup = {source['source_id']: source for source in value['sources']}
    used, claims = {}, []
    for claim in answer['claims']:
        if not isinstance(claim['text'], str) or not claim['evidence']:
            raise ValueError('Brak treści lub dowodów twierdzenia.')
        ids = []
        for evidence in claim['evidence']:
            sid = evidence['source_id']; source = lookup[sid]; quote = evidence['quote']
            if not isinstance(quote, str) or not quote.strip() or ' '.join(quote.split()) not in ' '.join(source['chunk']['text'].split()):
                raise ValueError('Cytat nie występuje w podanym źródle.')
            if sid not in used:
                chunk = source['chunk']
                used[sid] = dict(id=sid, document=chunk.get('source_id', 'Dokument'),
                    pdf_pages=chunk.get('page_numbers', []), printed_pages=chunk.get('printed_page_labels', []),
                    label_status=chunk.get('printed_page_label_status', 'unverified_ocr'),
                    section=chunk.get('section_path', []), chunk_id=source.get('chunk_id'), quotes=[])
            if quote not in used[sid]['quotes']: used[sid]['quotes'].append(quote)
            if sid not in ids: ids.append(sid)
        claims.append({'text': claim['text'], 'source_ids': ids})
    if answer['answerable'] != bool(claims):
        raise ValueError('Niespójna odpowiedź i lista twierdzeń.')
    return {'answerable': answer['answerable'], 'claims': claims, 'sources': list(used.values()),
            'composition': value.get('composition'), 'query': value['query']}


class Jobs:
    def __init__(self, root, options):
        self.root = root.resolve(); self.options = options
        self.token = secrets.token_urlsafe(32); self.nonce = secrets.token_urlsafe(24)
        self.lock = threading.Lock(); self.jobs = {}; self.active = None; self.stopping = False

    def submit(self, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError('Wpisz pytanie o długości od 1 do 2000 znaków.')
        with self.lock:
            if self.stopping or self.active is not None:
                raise RuntimeError('Trwa już przetwarzanie pytania. Poczekaj na wynik.')
            ident = uuid.uuid4().hex
            output = self.root / 'data/runs' / ('ui_' + ident)
            output.parent.mkdir(parents=True, exist_ok=True)
            # ask.py itself creates output; keep the launcher log beside it.
            job = dict(id=ident, question=question.strip(), status='running', started=time.monotonic(),
                       output=output, log=output.with_suffix('.log'), process=None)
            self.jobs[ident] = job; self.active = ident
            threading.Thread(target=self._execute, args=(ident,), daemon=True).start()
            return ident

    def _execute(self, ident):
        job = self.jobs[ident]
        try:
            script = 'ui_demo_backend.py' if self.options.demo else 'ask.py'
            command = [sys.executable, str(self.root/'scripts'/script), job['question'],
                       '--output-dir', str(job['output'])]
            if not self.options.demo:
                command += ['--index-dir', str(self.options.index_dir), '--model', self.options.model,
                            '--answer-mode', 'evidence-first', '--top-k', str(self.options.top_k),
                            '--api-url', self.options.api_url, '--timeout', str(self.options.timeout),
                            '--think', 'false']
            with job['log'].open('w', encoding='utf-8') as handle:
                with self.lock:
                    if self.stopping: raise RuntimeError('Serwer został zatrzymany.')
                    process = subprocess.Popen(command, cwd=self.root, stdout=handle, stderr=subprocess.STDOUT,
                                               start_new_session=True)
                    job['process'] = process
                code = process.wait()
            if code != 0:
                raise RuntimeError(f'Backend zakończył pracę z kodem {code}. Szczegóły są w logu wykonania.')
            result = read_json(job['output']/'answer.json')
            manifest = read_json(job['output']/'run.json')
            if manifest.get('status') != 'completed' or result.get('query') != job['question']:
                raise ValueError('Backend nie zapisał zgodnego, zakończonego wyniku.')
            presented = present_answer(result)
            with self.lock: job.update(status='completed', result=presented)
        except Exception as error:
            with self.lock: job.update(status='failed', error=str(error))
        finally:
            with self.lock:
                job['finished'] = time.monotonic()
                if self.active == ident: self.active = None

    def snapshot(self, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if job is None: return None
            response = {key: job[key] for key in ('id', 'question', 'status', 'result', 'error') if key in job}
            response['elapsed_seconds'] = round(job.get('finished', time.monotonic())-job['started'], 1)
            output = job['output']
        try:
            manifest = read_json(output/'run.json')
            response['stages'] = [{k: stage[k] for k in ('name','status') if k in stage}
                                  for stage in manifest.get('stages', [])]
        except (OSError, ValueError, TypeError): response['stages'] = []
        return response

    def stop(self):
        with self.lock:
            self.stopping = True
            processes = [j['process'] for j in self.jobs.values() if j['process'] is not None]
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except ProcessLookupError: pass
                except subprocess.TimeoutExpired:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, jobs):
        self.jobs = jobs
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send(self, code, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'nonce-" +
                         self.server.jobs.nonce + "'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers(); self.wfile.write(body)

    def allowed(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        return self.headers.get('Host') in hosts

    def do_GET(self):
        if not self.allowed(): return self.send(403, {'error':'Niedozwolony host.'})
        path = urlsplit(self.path).path
        jobs = self.server.jobs
        if path == '/':
            html = (jobs.root/'web/index.html').read_text(encoding='utf-8')
            html = html.replace('{{TOKEN}}', jobs.token).replace('{{NONCE}}', jobs.nonce)
            return self.send(200, html.encode(), 'text/html; charset=utf-8')
        if path == '/api/config':
            return self.send(200, {'demo': jobs.options.demo, 'model': jobs.options.model,
                                   'version': VERSION})
        match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})(/answer|/log)?', path)
        if match:
            ident, kind = match.groups(); snapshot = jobs.snapshot(ident)
            if snapshot is None: return self.send(404, {'error':'Nie znaleziono wykonania w tej sesji serwera.'})
            if kind:
                with jobs.lock: job = jobs.jobs[ident]
                target = job['output']/'answer.json' if kind == '/answer' else job['log']
                if kind == '/answer' and snapshot['status'] != 'completed':
                    return self.send(409, {'error':'Odpowiedź nie jest jeszcze gotowa.'})
                try: raw = target.read_bytes()
                except OSError: return self.send(404, {'error':'Plik nie jest jeszcze dostępny.'})
                return self.send(200, raw, 'application/json; charset=utf-8' if kind=='/answer' else 'text/plain; charset=utf-8')
            return self.send(200, snapshot)
        self.send(404, {'error':'Nie znaleziono zasobu.'})

    def do_POST(self):
        jobs = self.server.jobs
        if not self.allowed(): return self.send(403, {'error':'Niedozwolony host.'})
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'}:
            return self.send(403, {'error':'Niedozwolone pochodzenie żądania.'})
        if self.headers.get('X-Home-RAG-Token') != jobs.token:
            return self.send(403, {'error':'Odśwież stronę i spróbuj ponownie.'})
        if self.path != '/api/jobs': return self.send(404, {'error':'Nie znaleziono zasobu.'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 1 <= length <= 12000: raise ValueError('Niepoprawny rozmiar pytania.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or set(payload) != {'question'}:
                raise ValueError('Niepoprawny format żądania.')
            ident = jobs.submit(payload['question'])
        except (ValueError, UnicodeError) as error: return self.send(400, {'error':str(error)})
        except RuntimeError as error: return self.send(409, {'error':str(error)})
        except OSError: return self.send(500, {'error':'Nie można zapisać wykonania w katalogu projektu.'})
        self.send(202, {'id':ident})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--demo',action='store_true',help='Synthetic UI demo; no Docker or LLM')
    parser.add_argument('--index-dir',type=Path,default=Path('data/pages/sample_book_100_ocr/table_v010'))
    parser.add_argument('--model',default='qwen3.5:4b')
    parser.add_argument('--top-k',type=int,default=8)
    parser.add_argument('--api-url',default='http://127.0.0.1:11434')
    parser.add_argument('--timeout',type=int,default=600)
    args = parser.parse_args()
    if not 1<=args.port<=65535 or args.top_k<1 or args.timeout<1: parser.error('Niepoprawne parametry.')
    root = Path(__file__).resolve().parents[1]
    required = [root/'web/index.html',root/'scripts'/('ui_demo_backend.py' if args.demo else 'ask.py')]
    if not args.demo:
        index = (root/args.index_dir).resolve()
        if not index.is_relative_to(root): parser.error('Indeks musi znajdować się w projekcie.')
        required += [index/'embeddings.jsonl', index/'embedding_report.json']
    missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
    if missing: parser.error('Brak plików: '+', '.join(missing))
    jobs = Jobs(root,args)
    try: server = Server(('127.0.0.1',args.port),jobs)
    except OSError as error: parser.error(str(error))
    print(f'Home RAG {VERSION}: http://127.0.0.1:{args.port}',flush=True)
    print('Tryb: '+('DEMO — dane syntetyczne, bez modelu' if args.demo else 'lokalny indeks, evidence-first'),flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        jobs.stop();server.server_close()


if __name__ == '__main__': main()
