"""Execute frozen expressions with K and check original requirements offline."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import shutil
from types import SimpleNamespace

from . import acceptance
from .common import ROOT, BUILD_COMMAND, workspace_lock
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


def write_tables(output, summaries, rows, experiment=None):
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
    if experiment is not None:
        lines.extend(['', f"Experiment completion exit code: {experiment['exit_code']}. "
                      f"Original assertion-check exit code: {experiment['assertion_exit_code']}. "
                      f"Execution faults: {len(experiment['execution_faults'])}.", '',
                      'Semantic differences and uncheckable requirements remain in the tables; '
                      'they do not by themselves mean that the experiment failed to run. '
                      'No saved project results were read or compared.'])
    (output/'README.md').write_text('\n'.join(lines)+'\n')


def execution_faults(reports, output, scope):
    """Inspect this run's tasks and all K call receipts, including dependencies.

    A natural incomplete state is not a tool fault. Rewrite counts and each
    call's own budget distinguish it from budget exhaustion, including probes.
    """
    faults = {}
    def add(project, name, call, kind, diagnostic):
        faults[project, name, call, kind] = {'source': project, 'id': name,
            'call': call, 'kind': kind, 'diagnostic': diagnostic}
    for project, report in reports.items():
        records = report['cases']
        actual = {r['id'] for r in records}
        if len(actual) != len(records):
            raise ValueError('duplicate experiment task: ' + project)
        expected = {name for name, row in scope.items() if row['project'] == project}
        if actual - expected:
            raise ValueError('unexpected experiment task: ' + project)
        for name in sorted(expected - actual):
            add(project, name, '', 'not_run', 'required frozen task has no report')
        for record in records:
            name = record['id']
            base = output/project/name
            if record['execution'] in {'tool_error', 'not_run'}:
                add(project, name, 'k', record['execution'], record.get('diagnostic', ''))
            if record.get('budget_exhausted'):
                add(project, name, 'k', 'budget_exhausted', 'root rewrite budget exhausted')
            receipts = sorted(p for p in base.rglob('exit.json') if p.parent.name == 'k')
            if not (base/'k/exit.json').is_file() and record['execution'] not in {'tool_error', 'not_run'}:
                add(project, name, 'k', 'not_run', 'root expression has no execution receipt')
            for path in receipts:
                call = path.parent.relative_to(base).as_posix()
                try:
                    receipt = json.loads(path.read_text())
                    if receipt.get('timeout'):
                        add(project, name, call, 'timeout', 'K invocation timed out')
                    elif receipt.get('interrupted'):
                        add(project, name, call, 'interrupted', 'K invocation was interrupted')
                    elif receipt.get('launch_error') or receipt.get('returncode') not in (0, 1):
                        add(project, name, call, 'tool_error', receipt.get('launch_error', 'invalid K invocation exit code'))
                    elif receipt['returncode'] == 1:
                        command = json.loads((path.parent/'command.json').read_text())['argv']
                        budget = int(command[command.index('--depth') + 1])
                        statistics = (path.parent/'stderr.txt').read_text()
                        steps = re.search(r'([0-9]+)\s+(?:steps|rewrites)', statistics, re.I)
                        if steps is None:
                            add(project, name, call, 'tool_error', 'rewrite statistics missing for incomplete K invocation')
                        elif int(steps[1]) >= budget:
                            add(project, name, call, 'budget_exhausted', 'K invocation rewrite budget exhausted')
                except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                    add(project, name, call, 'tool_error', 'invalid K invocation receipt: ' + str(error))
    return list(faults.values())


def run(options, *, experiment=False):
    manifest, scope = validate_archive(options.corpus)
    output = options.output.absolute()
    if os.path.lexists(output):
        raise ValueError('output must not exist: '+str(output))
    if not (options.definition/'compiled.bin').is_file():
        raise ValueError('compiled K definition missing; run '+BUILD_COMMAND+' or specify --definition')
    if output == options.corpus or output.is_relative_to(options.corpus):
        raise ValueError('output cannot be inside the frozen corpus')
    output.mkdir(parents=True)
    if getattr(options, 'environment', None) is not None:
        write_json(output/'environment.json', options.environment)
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
        'definition':str(options.definition),
        'settings':{'timeout':options.timeout,'depth':options.depth,'jobs':options.jobs},
        'sources':summaries, 'exit_code':int(any(r['summary']['exit_code'] for r in reports.values()))}
    if experiment:
        faults = execution_faults(reports, output, scope)
        result.update(assertion_exit_code=result['exit_code'],
                      exit_code=int(bool(faults)), execution_faults=faults)
    write_json(output/'summary.json', result)
    write_tables(output, summaries, rows, result if experiment else None)
    for project, summary in summaries.items():
        print(project, json.dumps(summary['core'], sort_keys=True), flush=True)
    return result['exit_code']


@contextmanager
def execution_environment():
    """Keep runtime scratch and locks local, restoring the caller's environment."""
    temp_root = ROOT/'build/tmp'
    temp_root.mkdir(parents=True, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix='verification-', dir=temp_root)
    settings = dict(TMPDIR=scratch, DWARF_INPUT_TMPDIR=scratch, OMP_NUM_THREADS='1',
                    OPENBLAS_NUM_THREADS='1', GHCRTS='-N1', K_OPTS='-Xmx512m -Xss8m',
                    PYTHONDONTWRITEBYTECODE='1')
    previous = {key: os.environ.get(key) for key in settings}
    affinity = os.sched_getaffinity(0) if hasattr(os, 'sched_getaffinity') else None
    try:
        os.environ.update(settings)
        if affinity is not None:
            os.sched_setaffinity(0, sorted(affinity)[:16])
        with workspace_lock():
            yield
    finally:
        if affinity is not None:
            os.sched_setaffinity(0, affinity)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(scratch)


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
        with execution_environment():
            return run(options)
    except KeyboardInterrupt:
        from .process import stop_children
        stop_children()
        return 130
    except (ValueError,OSError,KeyError,TypeError) as error:
        print('verify: '+str(error),file=sys.stderr)
        return 2
