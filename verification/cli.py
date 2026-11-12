"""Execute frozen expressions with K and check original requirements offline."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from . import acceptance
from .common import ROOT, fingerprint, workspace_lock
from .corpus_archive import validate_archive
from .input import write_json
from .metrics import count
from run import DEFAULT_DEFINITION


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return value


def summarize(reports):
    summaries = {}
    rows = []
    for project, report in reports.items():
        for record in report['cases']:
            result = record['corpus_evaluation']
            rows.append({'id': record['id'], 'source': project,
                         'execution': record['execution'], **result,
                         'budget_exhausted': record['budget_exhausted'],
                         'input_identity': record['input_identity']})
        selected = [r for r in rows if r['source'] == project]
        summaries[project] = {
            'core': count([r for r in selected if r['scope'] == 'semantic']),
            'auxiliary': count([r for r in selected if r['scope'] == 'auxiliary']),
            'execution': dict(Counter(r['execution'] for r in selected)),
            'attribute_invocations': report['summary']['attribute_invocations'],
            'exit_code': report['summary']['exit_code']}
    return summaries, rows


def write_tables(output, summaries, rows):
    columns = ['id','source','scope','execution','entered_k','fully_checked','status',
               'budget_exhausted','input_identity']
    with (output/'expressions.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    with (output/'checks.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['expression','source','scope','target','status','complete','evidence'])
        writer.writeheader()
        for row in rows:
            for check in row['checks']:
                writer.writerow({'expression':row['id'],'source':row['source'],'scope':row['scope'],
                    'target':check.get('target','location_identity'),'status':check['status'],
                    'complete':check.get('semantic_check_complete'),
                    'evidence':json.dumps(check, ensure_ascii=False)})
    lines = ['# Frozen corpus verification', '',
             'Core results count expressions. Auxiliary checks and attribute calls are separate.', '',
             '| Source | Core | Pass | Differences | Uncheckable | Not run | Tool errors |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for project, data in summaries.items():
        c=data['core']; s=c['status']
        lines.append(f"| {project} | {c['total']} | {s['pass']} | {s['fail']} | {s['uncheckable']} | {s['not_run']} | {s['tool_error']} |")
    lines.extend(['', 'A completed K evaluation is not automatically a passing check. Incomplete execution can satisfy only a reviewed, independently checked stopped-state predicate.', '',
                  'See `summary.json`, `expressions.csv`, `checks.csv` and each source report for auxiliary checks, dependencies, commands and full configurations.'])
    (output/'README.md').write_text('\n'.join(lines)+'\n')


def run(options):
    manifest, _ = validate_archive(options.corpus)
    output = options.output.absolute()
    if os.path.lexists(output):
        raise ValueError('output must not exist: '+str(output))
    if not (options.definition/'compiled.bin').is_file():
        raise ValueError('compiled K definition missing; run make llvm or specify --definition')
    if output == options.corpus or output.is_relative_to(options.corpus):
        raise ValueError('output cannot be inside the frozen corpus')
    output.mkdir(parents=True)
    reports = {}
    for project, dataset in manifest['datasets'].items():
        if options.source not in ('all', project):
            continue
        args = SimpleNamespace(inputs=options.corpus/dataset['directory'], output=output/project,
             definition=options.definition, timeout=options.timeout, depth=options.depth,
             jobs=options.jobs, require_complete=options.require_complete)
        acceptance.test(args)
        reports[project] = json.loads((output/project/'report.json').read_text())
    summaries, rows = summarize(reports)
    result = {'schema':1, 'unit':'original expression case', 'new_execution':True,
        'date':datetime.now(timezone.utc).isoformat(), 'corpus_sha256':manifest['archive_sha256'],
        'definition':fingerprint(options.definition/'compiled.bin'),
        'rule_source_sha256':{str(p.relative_to(ROOT)):fingerprint(p)['sha256'] for p in sorted((ROOT/'semantics').rglob('*.k'))},
        'checker_source_sha256':{str(p.relative_to(ROOT)):fingerprint(p)['sha256'] for p in [ROOT/'verify.py',ROOT/'run.py',*sorted((ROOT/'verification').rglob('*.py'))] if 'tests' not in p.parts},
        'settings':{'timeout':options.timeout,'depth':options.depth,'jobs':options.jobs},
        'sources':summaries, 'exit_code':int(any(r['summary']['exit_code'] for r in reports.values()))}
    write_json(output/'summary.json', result)
    write_tables(output, summaries, rows)
    for project, summary in summaries.items():
        print(project, json.dumps(summary['core'], sort_keys=True), flush=True)
    return result['exit_code']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['all','lldb','gdb'], default='all')
    parser.add_argument('--corpus', type=Path, default=ROOT/'test-corpus')
    parser.add_argument('--definition', type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=positive, default=120)
    parser.add_argument('--depth', type=positive, default=10000)
    parser.add_argument('--jobs', type=positive, choices=range(1,9), default=4)
    parser.add_argument('--require-complete', action='store_true')
    parser.add_argument('--check-corpus', action='store_true', help='verify the frozen inventory without executing K')
    options = parser.parse_args(argv)
    options.corpus=options.corpus.absolute();options.definition=options.definition.absolute()
    try:
        if options.check_corpus:
            manifest,_=validate_archive(options.corpus)
            print(json.dumps({'status':'verified','corpus_sha256':manifest['archive_sha256']}))
            return 0
        if options.output is None:
            parser.error('--output is required unless --check-corpus is used')
        Path('/tmp/scratch').mkdir(exist_ok=True)
        scratch = tempfile.mkdtemp(prefix='kframework-verify-', dir='/tmp/scratch')
        os.environ.update(TMPDIR=scratch,DWARF_INPUT_TMPDIR=scratch,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',GHCRTS='-N1',K_OPTS='-Xmx512m -Xss8m',PYTHONDONTWRITEBYTECODE='1')
        if hasattr(os,'sched_getaffinity'):
            os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:16])
        with workspace_lock():
            return run(options)
    except KeyboardInterrupt:
        from .process import stop_children
        stop_children()
        return 130
    except (ValueError,OSError,KeyError,TypeError) as error:
        print('verify: '+str(error),file=sys.stderr)
        return 2
