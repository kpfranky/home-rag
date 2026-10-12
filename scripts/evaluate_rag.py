"""Run a small local RAG evaluation; lexical checks are signals, not semantic grading."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid
import ask

VERSION = '0.2.0'


def normalized(value):
    return ' '.join(value.casefold().split())


def load_suite(path):
    suite = json.loads(path.read_text(encoding='utf-8'))
    if suite.get('schema_name') != 'home-rag-evaluation-suite' or suite.get('schema_version') != 1:
        raise ValueError('Invalid suite schema')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Suite must contain cases')
    ids = set()
    for case in cases:
        ident = case.get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', ident) or ident in ids:
            raise ValueError('Invalid or duplicate case ID')
        ids.add(ident)
        if not isinstance(case.get('question'), str) or not 1 <= len(case['question'].strip()) <= 2000:
            raise ValueError('Invalid question')
        if type(case.get('answerable')) is not bool:
            raise ValueError('Missing expected answerability')
        if not isinstance(case.get('expected_answer'), str):
            raise ValueError('Missing reference answer')
        for field in ('answer_patterns', 'source_patterns'):
            if not isinstance(case.get(field), list) or not all(isinstance(p, str) and p for p in case[field]):
                raise ValueError('Invalid check patterns')
            for pattern in case[field]:
                re.compile(pattern)
    return suite


def inspect_result(case, answer, search):
    claims = answer['answer']['claims']
    text = normalized(' '.join(claim['text'] for claim in claims))
    sources = {source['source_id']: source for source in answer['sources']}
    quotes_valid = not answer['answer']['answerable'] or bool(claims)
    cited = []
    for claim in claims:
        if not claim.get('evidence'):
            quotes_valid = False
        for evidence in claim.get('evidence', []):
            source = sources.get(evidence.get('source_id'))
            quote = evidence.get('quote')
            if (source is None or not isinstance(quote, str) or not quote.strip()
                    or ' '.join(quote.split()) not in ' '.join(source['chunk']['text'].split())):
                quotes_valid = False
            elif source not in cited:
                cited.append(source)
    def missing(patterns, value):
        return [p for p in patterns if re.search(p, value) is None]
    retrieved_text = normalized(' '.join(s['chunk']['text'] for s in search['results']))
    cited_text = normalized(' '.join(s['chunk']['text'] for s in cited))
    expected = case['answerable']
    decision_ok = answer['answer']['answerable'] is expected
    if not expected and claims:
        decision_ok = False
    checks = {'answerability_matches': decision_ok,
              'quotes_present_in_sources': quotes_valid,
              'missing_answer_patterns': missing(case['answer_patterns'], text),
              'missing_retrieval_patterns': missing(case['source_patterns'], retrieved_text),
              'missing_cited_source_patterns': missing(case['source_patterns'], cited_text)}
    checks['signals_ok'] = (decision_ok and quotes_valid and not any(checks[key] for key in
        ('missing_answer_patterns', 'missing_retrieval_patterns', 'missing_cited_source_patterns')))
    return checks


def write_report(output, report):
    ask.write(output / 'evaluation.json', report)
    lines = ['# Home RAG — ewaluacja', '',
             f"Wersja: {VERSION}. Przypadki: {len(report['cases'])}.", '',
             'Sprawdzenia leksykalne i obecność cytatów nie dowodzą poprawności znaczenia.',
             'Każdą odpowiedź należy ocenić w review.json: pass / fail oraz komentarz.', '']
    for item in report['cases']:
        lines += [f"## {item['id']}", '', item['question'], '',
                  '**Wzorzec:** ' + item['expected_answer'], '',
                  f"**Czas:** {item['elapsed_seconds']:.2f} s. **Status:** {item['status']}", '']
        if 'checks' in item:
            lines += ['**Sprawdzenia:** ' + json.dumps(item['checks'], ensure_ascii=False), '',
                      '**Czasy etapów:** ' + json.dumps(item['stage_seconds']), '',
                      '**Odpowiedź:**', '', item['rendered_answer'], '']
        else:
            lines += ['**Błąd:** ' + item['error'], '']
    (output / 'evaluation.md').write_text('\n'.join(lines), encoding='utf-8')


def evaluate(args, root=None, pipeline=None):
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    suite_path = ask.within(root, args.suite)
    suite = load_suite(suite_path)
    selected = set(args.case or [])
    unknown = selected - {c['id'] for c in suite['cases']}
    if unknown:
        raise ValueError('Unknown case IDs: ' + ', '.join(sorted(unknown)))
    cases = [c for c in suite['cases'] if not selected or c['id'] in selected]
    output = ask.within(root, args.output_dir or Path('data/evaluations') / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]))
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema_name': 'home-rag-evaluation', 'schema_version': 1,
              'evaluator_version': VERSION, 'suite_sha256': hashlib.sha256(suite_path.read_bytes()).hexdigest(),
              'suite': suite, 'config': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'cases': []}
    pipeline = pipeline or ask.run_pipeline
    review = []
    for number, case in enumerate(cases, 1):
        print(f"[{number}/{len(cases)}] {case['id']}: {case['question']}", flush=True)
        run = output / case['id']
        item = {**case, 'run_dir': str(run)}
        started = time.perf_counter()
        stages = []
        def timed_runner(command, **kwargs):
            before = time.perf_counter()
            try:
                return subprocess.run(command, **kwargs)
            finally:
                stages.append(round(time.perf_counter() - before, 3))
        config = ask.parser().parse_args([case['question'], '--output-dir', str(run),
            '--index-dir', str(args.index_dir), '--model', args.model, '--think', args.think,
            '--top-k', str(args.top_k), '--api-url', args.api_url, '--timeout', str(args.timeout),
            '--embedding-image', args.embedding_image,
            '--answer-mode', getattr(args, 'answer_mode', 'evidence-first')])
        try:
            with (output / (case['id'] + '.log')).open('w', encoding='utf-8') as handle, redirect_stdout(handle):
                pipeline(config, root=root, runner=timed_runner)
            answer = json.loads((run / 'answer.json').read_text(encoding='utf-8'))
            search = json.loads((run / 'search.json').read_text(encoding='utf-8'))
            if answer.get('query') != case['question'] or search.get('query') != case['question']:
                raise ValueError('Result question mismatch')
            item.update(status='completed', checks=inspect_result(case, answer, search),
                        rendered_answer=answer['rendered_answer'], index_sha256=answer.get('index_sha256'),
                        stage_seconds=dict(zip(('retrieval', 'assessment', 'answer'), stages)))
        except Exception as error:
            item.update(status='error', error=str(error))
        item['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        report['cases'].append(item)
        review.append({'id': case['id'], 'verdict': 'pending', 'comment': '',
                       'criteria': 'Odpowiedź poprawna, kompletna, w zakresie pytania; cytaty ją uzasadniają; poprawne kolumny i liczności.'})
        write_report(output, report)
        ask.write(output / 'review.json', review)
    errors = sum(c['status'] == 'error' for c in report['cases'])
    alerts = sum(c.get('checks', {}).get('signals_ok') is False for c in report['cases'])
    report.update(status='completed', summary={'errors': errors, 'signal_alerts': alerts,
                                              'human_reviews_pending': len(cases)})
    write_report(output, report)
    print(f'Errors: {errors}; signal alerts: {alerts}; manual review: {len(cases)}')
    print('Saved:', output)
    return 2 if errors else (1 if alerts else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, default=Path('config/evaluation/sample_book_100_v1.json'))
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--case', action='append', help='Run only this ID (repeatable)')
    parser.add_argument('--index-dir', type=Path, default=Path(ask.DEFAULT_INDEX))
    parser.add_argument('--answer-mode', choices=('evidence-first', 'two-stage'), default='evidence-first')
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--think', choices=('false', 'true', 'auto'), default='false')
    parser.add_argument('--top-k', type=int, default=8)
    parser.add_argument('--api-url', default='http://127.0.0.1:11434')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--embedding-image', default='home-rag-embedding:0.1.0')
    args = parser.parse_args()
    if args.top_k < 1 or args.timeout < 1:
        parser.error('top-k and timeout must be positive')
    try:
        code = evaluate(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
