"""Run offline retrieval, source assessment and cited answering in one command."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

VERSION = '0.2.0'
DEFAULT_INDEX = 'data/pages/sample_book_100_ocr/table_v010'


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('question')
    result.add_argument('--index-dir', default=DEFAULT_INDEX, type=Path)
    result.add_argument('--output-dir', type=Path, help='New run directory inside the project')
    result.add_argument('--answer-mode', choices=('evidence-first', 'two-stage'), default='evidence-first')
    result.add_argument('--model', default='qwen3.5:4b')
    result.add_argument('--think', choices=('false', 'true', 'auto'), default='false')
    result.add_argument('--top-k', type=int, default=8)
    result.add_argument('--api-url', default='http://127.0.0.1:11434')
    result.add_argument('--timeout', type=int, default=600, help='Ollama request timeout')
    result.add_argument('--embedding-image', default='home-rag-embedding:0.1.0')
    return result


def within(root, path):
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Index/output must stay inside the project mounted in Docker')
    return resolved


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_pipeline(args, root=None, runner=None):
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    runner = runner or subprocess.run
    if not args.question.strip() or len(args.question) > 2000:
        raise ValueError('Question must contain 1–2000 characters')
    if args.top_k < 1 or args.timeout < 1:
        raise ValueError('top-k and timeout must be positive')
    index = within(root, args.index_dir)
    embeddings, report = index / 'embeddings.jsonl', index / 'embedding_report.json'
    assessor = 'assess_evidence.py' if args.answer_mode == 'evidence-first' else 'assess_sources.py'
    scripts = ['search_chunks.py', assessor, 'assess_sources.py', 'answer_question.py']
    required = [embeddings, report, *[root / 'scripts' / script for script in scripts]]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise ValueError('Missing required files: ' + ', '.join(missing))
    automatic = Path('data/runs') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
                                    + '_' + uuid.uuid4().hex[:8])
    output = within(root, args.output_dir or automatic)
    output.mkdir(parents=True, exist_ok=False)
    search, assessment, answer = [output / name for name in ('search.json', 'assessment.json', 'answer.json')]
    def docker_path(path):
        return '/work/' + path.relative_to(root).as_posix()
    common = ['--model', args.model, '--think', args.think, '--top-k', str(args.top_k),
              '--api-url', args.api_url, '--timeout', str(args.timeout),
              '--embeddings', str(embeddings), '--embedding-report', str(report)]
    commands = [
        ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--user', f'{os.getuid()}:{os.getgid()}',
         '-e', 'HOME=/tmp', '-v', str(root) + ':/work', '-w', '/work', args.embedding_image,
         'scripts/search_chunks.py', docker_path(embeddings), '--embedding-report', docker_path(report),
         '--query', args.question, '--prefer-table-rows', '--top-k', str(args.top_k), '--output', docker_path(search)],
        [sys.executable, str(root / 'scripts' / assessor), str(search),
         *common, '--output', str(assessment)],
        [sys.executable, str(root / 'scripts/answer_question.py'), str(search),
         *common, '--assessment', str(assessment), '--mode', args.answer_mode, '--output', str(answer)],
    ]
    manifest = {'schema_name': 'home-rag-run', 'schema_version': 1, 'runner_version': VERSION,
                'status': 'running', 'query': args.question, 'index_dir': str(index),
                'model': args.model, 'think': args.think, 'top_k': args.top_k, 'answer_mode': args.answer_mode,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'outputs': {'search': str(search), 'assessment': str(assessment), 'answer': str(answer)},
                'stages': []}
    manifest_path = output / 'run.json'
    write(manifest_path, manifest)
    try:
        for position, (name, command, target, schema, statuses) in enumerate(zip(
                ['retrieval', 'assessment', 'answer'], commands, [search, assessment, answer],
                ['home-rag-search', 'home-rag-answerability', 'home-rag-answer'],
                [None, {'assessed'}, {'answered', 'insufficient_evidence', 'no_sources'}]), 1):
            print(f'[{position}/3] {name}', flush=True)
            log = output / (name + '.log')
            stage = {'name': name, 'command': command, 'log': str(log), 'status': 'running'}
            manifest['stages'].append(stage)
            write(manifest_path, manifest)
            with log.open('w', encoding='utf-8') as handle:
                completed = runner(command, cwd=str(root), stdout=handle, stderr=subprocess.STDOUT,
                                   check=False)
            stage['exit_code'] = completed.returncode
            if completed.returncode != 0:
                raise RuntimeError(f'{name} failed (exit {completed.returncode}); log: {log}')
            value = json.loads(target.read_text(encoding='utf-8'))
            if (value.get('schema_name') != schema or value.get('query') != args.question
                    or (statuses is not None and value.get('status') not in statuses)):
                raise ValueError(f'{name} did not produce a valid completed result: {target}')
            if name == 'answer' and not isinstance(value.get('rendered_answer'), str):
                raise ValueError('Answer is missing rendered_answer')
            stage['status'] = 'completed'
            write(manifest_path, manifest)
        manifest.update(status='completed', answer_status=value['status'],
                        index_sha256=value.get('index_sha256'),
                        completed_at=datetime.now(timezone.utc).isoformat())
        write(manifest_path, manifest)
    except (Exception, KeyboardInterrupt) as error:
        if manifest['stages']:
            manifest['stages'][-1]['status'] = 'failed'
        manifest.update(status='failed', error=str(error))
        write(manifest_path, manifest)
        raise RuntimeError(f'{error}\nDiagnostic: {manifest_path}') from error
    print('\n' + value['rendered_answer'])
    print('\nSaved:', output)
    return output


def main():
    args = parser().parse_args()
    try:
        run_pipeline(args)
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))


if __name__ == '__main__':
    main()
