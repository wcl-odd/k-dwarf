"""Fresh experiments check original requirements without reading saved results or running K."""
from contextlib import redirect_stderr, redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from verification import assertions, cli, reproduction as repro
from verification.model import Case
from verification.process import ToolFailure, execute


class ReproductionTests(unittest.TestCase):
    def setUp(self):
        scratch = Path('/tmp/scratch/kframework-artifact-rerun-tests-' + str(os.getpid()))
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.definition = self.root/'build/llvm-kompiled'
        self.definition.mkdir(parents=True)
        (self.definition/'compiled.bin').write_bytes(b'existing LLVM definition')
        self.expected = 1
        self.state = 'success'
        self.steps = 10
        self.skip = set()
        self.extra_calls = []
        self.receipt_mutator = None
        self.seen = []
        self.scope = {project+'-'+name: {'project': project, 'scope': scope}
                      for project, names in [('lldb', [('core', 'semantic'), ('aux', 'auxiliary')]),
                                             ('gdb', [('core', 'semantic')])]
                      for name, scope in names}
        self.manifest = {'archive_sha256': 'frozen', 'datasets': {
            'lldb': {'directory': 'lldb', 'tasks': {'semantic': 1, 'auxiliary': 1}},
            'gdb': {'directory': 'gdb', 'tasks': {'semantic': 1}}}}

    def call(self, base, options, *, status=0, steps=10, budget=None, **receipt):
        base.mkdir(parents=True)
        (base/'exit.json').write_text(json.dumps({'returncode': status, **receipt}))
        (base/'command.json').write_text(json.dumps({'argv': [sys.executable, 'run.py',
            '--depth', str(options.depth if budget is None else budget), '--statistics']}))
        (base/'stderr.txt').write_text(str(steps) + ' rewrites')
        (base/'stdout.txt').write_text(json.dumps({'status': 'completed' if status == 0 else 'incomplete',
                                                'configuration': {'term': 'mock K output'}}))

    def fake_acceptance(self, options):
        self.seen.append(options)
        options.output.mkdir(parents=True)
        project = options.output.name
        records = []
        for name, row in self.scope.items():
            if row['project'] != project or name in self.skip:
                continue
            source = {'project': project, 'version': 'test', 'file': 'fixture',
                      'sha256': 'a'*64, 'line': 1, 'text': 'original assertion', 'parameter': 'single'}
            assertion = {'id': name+'-check', 'source': source, 'target': 'stack_top',
                         'expected': {'integer': self.expected}, 'mapping': 'original source predicate'}
            case = Case(name, [49], 64, 'little', 5, True, 8,
                        {'project': project}, ['numeric'], upstream_assertions=[assertion])
            checks = assertions.check(case, {'status': 'completed', 'stack': [{'value': 1, 'type': 'g'}]})
            outcome = checks[0]['status']
            if row['scope'] == 'auxiliary':
                outcome = 'uncheckable'
            evaluated = {'scope': row['scope'], 'status': outcome,
                'fully_checked': row['scope'] == 'semantic', 'entered_k': self.state != 'not_run',
                'checks': checks}
            record = {'id': name, 'execution': self.state, 'diagnostic': 'mock execution',
                'corpus_evaluation': evaluated, 'budget_exhausted': False, 'input_identity': 'frozen'}
            if self.state not in {'tool_error', 'not_run'}:
                self.call(options.output/name/'k', options,
                          status=int(self.state == 'incomplete'), steps=self.steps)
            for path, fields in self.extra_calls:
                self.call(options.output/name/path/'k', options, **fields)
            if self.receipt_mutator is not None:
                self.receipt_mutator(options.output/name)
            records.append(record)
        exit_code = int(any(r['corpus_evaluation']['status'] == 'fail' for r in records))
        (options.output/'report.json').write_text(json.dumps({'cases': records,
            'summary': {'attribute_invocations': len(self.extra_calls), 'exit_code': exit_code}}))

    def invoke(self, args=(), *, target=None):
        target = self.root/'fresh' if target is None else target
        with patch.object(repro, 'ROOT', self.root), patch.object(cli, 'ROOT', self.root), \
             patch('verification.common.ROOT', self.root), \
             patch.object(repro, 'preflight', return_value={'k_version': 'mock v7.1.337'}) as preflight, \
             patch.object(cli, 'validate_archive', return_value=(self.manifest, self.scope)), \
             patch.object(cli.acceptance, 'test', side_effect=self.fake_acceptance), \
             patch.object(repro.subprocess, 'run', side_effect=AssertionError('unexpected subprocess')), \
             redirect_stdout(io.StringIO()):
            self.preflight_mock = preflight
            return repro.main(['--output', str(target), *args])

    def summary(self, target=None):
        return json.loads(((target or self.root/'fresh')/'summary.json').read_text())

    def test_fresh_results_are_direct_and_auxiliary_counts_are_separate(self):
        self.assertEqual(self.invoke(), 0)
        result = self.summary()
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['assertion_exit_code'], 0)
        self.assertEqual(result['sources']['lldb']['core']['total'], 1)
        self.assertEqual(result['sources']['lldb']['auxiliary']['total'], 1)
        for name in ('README.md', 'expressions.csv', 'checks.csv', 'environment.json',
                     'lldb/report.json', 'gdb/report.json', 'lldb/lldb-core/k/stdout.txt'):
            self.assertTrue((self.root/'fresh'/name).is_file(), name)
        self.assertFalse((self.root/'fresh/verification').exists())
        self.assertFalse((self.root/'fresh/comparison.json').exists())
        self.assertFalse((self.root/'fresh/comparison.csv').exists())
        with (self.root/'fresh/expressions.csv').open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 3)

    def test_missing_and_corrupt_saved_results_are_never_read(self):
        original_open = Path.open
        forbidden = self.root/'results'
        def guarded(path, *args, **kwargs):
            if path.is_relative_to(forbidden):
                raise AssertionError('saved results were accessed')
            return original_open(path, *args, **kwargs)
        for corrupt in (False, True):
            if corrupt:
                forbidden.mkdir()
                (forbidden/'summary.json').write_text('broken JSON')
                (forbidden/'evidence.jsonl.gz').write_bytes(b'not gzip')
            with patch.object(Path, 'open', guarded):
                self.assertEqual(self.invoke(target=self.root/('corrupt' if corrupt else 'absent')), 0)

    def test_original_expectation_mutation_fails_check_but_experiment_completes(self):
        self.expected = 2
        self.assertEqual(self.invoke(), 0)
        result = self.summary()
        self.assertEqual(result['assertion_exit_code'], 1)
        self.assertEqual(result['sources']['gdb']['core']['status']['fail'], 1)
        self.assertEqual(result['sources']['gdb']['core']['pass_rate'], 0)
        self.assertEqual(result['execution_faults'], [])
        with (self.root/'fresh/checks.csv').open() as stream:
            self.assertTrue(all(r['status'] == 'fail' for r in csv.DictReader(stream)))

    def test_development_verifier_keeps_assertion_exit_policy(self):
        self.expected = 2
        options = SimpleNamespace(corpus=self.root/'test-corpus', output=self.root/'development',
            definition=self.definition, source='all', timeout=120, depth=10000, jobs=4, require_complete=False)
        with patch.object(cli, 'validate_archive', return_value=(self.manifest, self.scope)), \
             patch.object(cli.acceptance, 'test', side_effect=self.fake_acceptance), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run(options), 1)
        self.assertNotIn('assertion_exit_code', self.summary(options.output))

    def test_source_selection_and_custom_limits_are_forwarded_without_subprocess(self):
        for source in ('lldb', 'gdb'):
            target = self.root/source
            self.seen = []
            self.assertEqual(self.invoke(['--source', source, '--definition', str(self.definition),
                '--timeout', '7', '--depth', '42', '--jobs', '2'], target=target), 0)
            self.assertEqual(set(self.summary(target)['sources']), {source})
            self.assertEqual(len(self.seen), 1)
            options = self.seen[0]
            self.assertEqual((options.timeout, options.depth, options.jobs), (7, 42, 2))
            self.assertEqual(options.definition, self.definition)

    def test_natural_incomplete_state_is_not_an_execution_fault(self):
        self.state = 'incomplete'
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.summary()['execution_faults'], [])

    def test_root_budget_exhaustion_is_an_execution_fault(self):
        self.state = 'incomplete'
        self.steps = 10000
        self.assertEqual(self.invoke(), 1)
        self.assertTrue(all(r['kind'] == 'budget_exhausted' for r in self.summary()['execution_faults']))

    def test_dependency_and_probe_faults_use_their_own_budgets(self):
        for label, path, fields, code in [
            ('dependency', 'dependencies/bound', {'status': 1, 'steps': 10000}, 1),
            ('probe-natural', 'stability-probe', {'status': 1, 'steps': 10000, 'budget': 20000}, 0),
            ('probe-exhausted', 'stability-probe', {'status': 1, 'steps': 20000, 'budget': 20000}, 1),
            ('timeout', 'dependencies/bound', {'timeout': True}, 1),
            ('bad-exit', 'dependencies/bound', {'status': 2}, 1)]:
            with self.subTest(label=label):
                self.extra_calls = [(path, fields)]
                self.assertEqual(self.invoke(target=self.root/label), code)

    def test_missing_statistics_and_damaged_new_receipts_are_tool_faults(self):
        self.state = 'incomplete'
        for label, mutate in [
            ('statistics', lambda p: (p/'k/stderr.txt').write_text('no rewrite counts')),
            ('bad-receipt', lambda p: (p/'k/exit.json').write_text('broken JSON')),
            ('missing-command', lambda p: (p/'k/command.json').unlink()),
            ('missing-root', lambda p: (p/'k/exit.json').unlink())]:
            with self.subTest(label=label):
                self.receipt_mutator = mutate
                self.assertEqual(self.invoke(target=self.root/label), 1)
                self.assertTrue(self.summary(self.root/label)['execution_faults'])

    def test_tool_failure_and_not_run_are_execution_faults(self):
        for state in ('tool_error', 'not_run'):
            self.state = state
            self.assertEqual(self.invoke(target=self.root/state), 1)
            self.assertTrue(self.summary(self.root/state)['execution_faults'])

    def test_missing_required_task_is_not_silently_successful(self):
        self.skip.add('gdb-core')
        self.assertEqual(self.invoke(), 1)
        self.assertIn('gdb-core', [r['id'] for r in self.summary()['execution_faults']])

    def test_existing_output_and_invalid_arguments_are_refused(self):
        for args in ([], ['--timeout', '0'], ['--depth', '-1'], ['--jobs', '9'], ['--check-only']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                repro.main(args)
            self.assertEqual(error.exception.code, 2)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke(target=self.root), 2)

    def test_missing_definition_does_not_execute_or_compile(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke(['--definition', str(self.root/'missing')]), 2)
        self.preflight_mock.assert_not_called()
        self.assertFalse((self.root/'fresh').exists())

    def test_output_symlink_parent_segments_and_definition_overlap_are_refused(self):
        frozen = self.root/'test-corpus'
        frozen.mkdir()
        (self.root/'alias').symlink_to(frozen)
        for output in (self.root/'alias/new', self.root/'unused/../test-corpus/new', self.definition/'new'):
            with self.subTest(output=output), redirect_stderr(io.StringIO()):
                self.assertEqual(self.invoke(target=output), 2)
        self.assertFalse((frozen/'new').exists())

    def test_environment_is_restored_and_runtime_scratch_is_removed(self):
        previous = {name: os.environ.get(name) for name in ('TMPDIR', 'DWARF_INPUT_TMPDIR', 'K_OPTS')}
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(previous, {name: os.environ.get(name) for name in previous})
        self.assertEqual(list((self.root/'build/tmp').iterdir()), [])
        self.assertTrue((self.root/'build/verification.lock').is_file())

    def test_interruption_cleans_up_and_preserves_130(self):
        with patch.object(repro, 'ROOT', self.root), patch.object(cli, 'ROOT', self.root), \
             patch('verification.common.ROOT', self.root), \
             patch.object(repro, 'preflight', side_effect=KeyboardInterrupt), patch.object(repro, 'stop_children') as stop:
            self.assertEqual(repro.main(['--output', str(self.root/'fresh')]), 130)
        stop.assert_called_once()
        self.assertEqual(list((self.root/'build/tmp').iterdir()), [])

    def test_missing_dependency_is_reported_before_creating_output(self):
        with patch.object(repro.shutil, 'which', return_value=None), patch.object(repro.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'missing system dependencies.*krun'):
                repro.preflight()
        command.assert_not_called()

    def test_version_preflight_only_queries_version_and_never_builds(self):
        with patch.object(repro.shutil, 'which', side_effect=lambda name: '/tools/'+name), \
             patch.object(repro.subprocess, 'run', return_value=SimpleNamespace(
                 returncode=0, stdout='K version v7.1.337', stderr='')) as command:
            self.assertIn('v7.1.337', repro.preflight()['k_version'])
        self.assertEqual(command.call_args.args[0], ['/tools/krun', '--version'])

    def test_timeout_kills_descendant_with_its_own_session(self):
        script = 'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],start_new_session=True); print(p.pid,flush=True); time.sleep(60)'
        target = self.root/'detached-timeout'
        with self.assertRaises(ToolFailure):
            execute([sys.executable, '-c', script], target, 0.3)
        pid = int((target/'stdout.txt').read_text().strip())
        stat = Path(f'/proc/{pid}/stat')
        self.assertTrue(not stat.exists() or stat.read_text().split()[2] == 'Z')
