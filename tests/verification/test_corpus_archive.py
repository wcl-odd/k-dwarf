"""Portable fixtures must not borrow evidence or oracles from the old machine."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from verification import assertions
from verification.corpus import load_cases
from verification.corpus_archive import PATH_FORMAT, local_path, read_prepared, evaluate_scope, scope_summary
from verification.corpus_integrity import canonical_hash, digest, input_identity, validate_archive
from verification.model import Case
SCRATCH = Path('/tmp/scratch') / ('kframework-portable-tests-' + str(os.getpid()))

def seal(root):
    base = root / 'gdb-17.1'
    preparation = json.loads((base / 'preparation.json').read_text())
    preparation['corpus']['sha256'] = digest(base / 'cases.json')
    (base / 'preparation.json').write_text(json.dumps(preparation))
    manifest = {'schema': 1, 'path_format': PATH_FORMAT, 'datasets': {'gdb': {'directory': 'gdb-17.1', 'version': '17.1', 'tasks': {'semantic': 1}}}, 'files': [{'path': p.relative_to(root).as_posix(), 'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'manifest.json']}
    manifest['archive_sha256'] = canonical_hash(manifest)
    (root / 'manifest.json').write_text(json.dumps(manifest))

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))

class PortableCorpusTests(unittest.TestCase):

    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'corpus'
        self.root.mkdir()
        self.base = self.root / 'gdb-17.1'
        source = self.base / 'sources/gdb/suite.exp'
        source.parent.mkdir(parents=True)
        source.write_text('gdb_test "print a" " = 13"\n')
        expected = {'id': 'a', 'source': {'project': 'gdb', 'version': '17.1', 'file': 'suite.exp', 'sha256': digest(source), 'line': 1, 'text': source.read_text().strip(), 'parameter': 'single'}, 'target': 'object', 'expected': {'fields': [{'offset': 0, 'size': 32, 'integer': 13}]}, 'mapping': 'Original object predicate; independent location evidence is separate.'}
        snapshot = {'pid': 12, 'command': 'print a', 'frame': {'pc': 4096}}
        write(self.base / 'evidence/snapshot.json', snapshot)
        location = {'suite': 'suite', 'snapshot_sha256': digest(self.base / 'evidence/snapshot.json'), 'same_stop': True, 'registers_unchanged': True, 'settings_restored': True, 'before': {'pid': 12, 'level': 0, 'pc': 4096}, 'observations': [{'id': 'a', 'role': 'root', 'address': 8192, 'variable': 'a'}]}
        write(self.base / 'evidence/location.json', location)
        origin = {'project': 'gdb', 'version': '17.1', 'file': 'suite.exp', 'sha256': digest(source), 'test': 'print a', 'assertion': source.read_text().strip(), 'migration': 'Original fixture', 'snapshot': 'evidence/snapshot.json', 'location_oracle': {'path': 'evidence/location.json', 'sha256': digest(self.base / 'evidence/location.json'), 'target': {'suite': 'suite', 'command': 'print a', 'frame_level': 0, 'role': 'root', 'original_root_bytes': [49]}}}
        case = Case(id='a', bytes=[49], address_width=64, endianness='little', dwarf_version=5, delegate=True, object_size=4, origin=origin, compare=['object'], upstream_assertions=[expected])
        self.case = case
        write(self.base / 'cases.json', {'schema': 1, 'cases': [case.document()]})
        write(self.base / 'preparation.json', {'schema': 1, 'path_format': PATH_FORMAT, 'source': 'gdb', 'corpus': {'path': 'cases.json', 'sha256': digest(self.base / 'cases.json')}, 'source_roots': {'gdb': 'sources/gdb'}, 'source_files': [{'path': 'sources/gdb/suite.exp', 'sha256': digest(source)}], 'artifacts': [{'path': 'evidence/snapshot.json', 'sha256': digest(self.base / 'evidence/snapshot.json')}, {'path': 'evidence/location.json', 'sha256': digest(self.base / 'evidence/location.json')}]})
        self.scope = {'id': 'a', 'project': 'gdb', 'scope': 'semantic', 'observation': 'standalone-location-identity', 'input_identity': input_identity(case), 'assertions_sha256': canonical_hash(case.upstream_assertions), 'auxiliary_requirements': []}
        write(self.root / 'scope.json', {'schema': 1, 'cases': [self.scope]})
        seal(self.root)

    def test_two_relocations_resolve_local_evidence_only(self):
        for name in ('relocated-one', 'relocated-two'):
            target = self.root.parent / name
            shutil.copytree(self.root, target)
            (cases, preparation, scope) = read_prepared(target / 'gdb-17.1')
            self.assertEqual(input_identity(cases[0]), input_identity(self.case))
            self.assertEqual(cases[0].upstream_assertions, self.case.upstream_assertions)
            self.assertTrue(cases[0].origin['snapshot'].startswith(str(target)))
            self.assertEqual(preparation['source_roots']['gdb'], str(target / 'gdb-17.1/sources/gdb'))
            from verification.locations import check_archived
            checked = check_archived(cases[0], {'result': {'kind': 'memory', 'address': 8192}})
            self.assertEqual(checked['status'], 'pass')
            self.assertEqual(evaluate_scope({'execution': 'success', 'checks': [], 'location_check': checked}, scope['a'])['status'], 'pass')

    def test_missing_file_and_unexpected_file_rejected(self):
        (self.base / 'evidence/snapshot.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            validate_archive(self.root)

    def test_extra_file_rejected(self):
        (self.root / 'unexpected.txt').write_text('not inventoried')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            validate_archive(self.root)

    def test_input_and_expectation_drift_rejected(self):
        p = self.base / 'cases.json'
        document = json.loads(p.read_text())
        document['cases'][0]['upstream_assertions'][0]['expected']['fields'][0]['integer'] = 14
        p.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'file changed'):
            validate_archive(self.root)
        seal(self.root)
        with self.assertRaisesRegex(ValueError, 'assertion identity'):
            validate_archive(self.root)

    def test_context_drift_rejected_after_inventory_reseal(self):
        p = self.base / 'cases.json'
        document = json.loads(p.read_text())
        document['cases'][0]['context'] = {'registers': {'0': 3}}
        p.write_text(json.dumps(document))
        seal(self.root)
        with self.assertRaisesRegex(ValueError, 'input or assertion identity'):
            validate_archive(self.root)

    def test_missing_or_drifting_source_or_snapshot_is_rejected(self):
        p = self.base / 'evidence/snapshot.json'
        p.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'file changed'):
            validate_archive(self.root)
        seal(self.root)
        with self.assertRaisesRegex(ValueError, 'source or evidence changed'):
            validate_archive(self.root)

    def test_manifest_drift_rejected(self):
        p = self.root / 'manifest.json'
        d = json.loads(p.read_text())
        d['datasets']['gdb']['version'] = 'invented'
        p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError, 'manifest identity'):
            validate_archive(self.root)

    def test_escape_paths_rejected_even_after_reseal(self):
        p = self.base / 'cases.json'
        d = json.loads(p.read_text())
        d['cases'][0]['origin']['snapshot'] = '../outside.json'
        p.write_text(json.dumps(d))
        seal(self.root)
        with self.assertRaisesRegex(ValueError, 'invalid corpus-relative'):
            read_prepared(self.base)
        for name in ('/tmp/outside', '../outside', 'x/../../outside', './evidence/snapshot.json', 'x\\y'):
            with self.subTest(path=name), self.assertRaises(ValueError):
                local_path(self.base, name)

    def test_symlinks_cannot_supply_evidence(self):
        p = self.base / 'evidence/snapshot.json'
        p.unlink()
        p.symlink_to(self.base / 'evidence/location.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            validate_archive(self.root)

    def test_source_root_escape_rejected(self):
        p = self.base / 'preparation.json'
        d = json.loads(p.read_text())
        d['source_roots']['gdb'] = '/home/foreign-source'
        p.write_text(json.dumps(d))
        seal(self.root)
        with self.assertRaisesRegex(ValueError, 'invalid corpus-relative'):
            read_prepared(self.base)

    def test_unknown_profile_and_scope_membership_rejected(self):
        p = self.base / 'preparation.json'
        d = json.loads(p.read_text())
        d['path_format'] = 'unknown'
        p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError, 'unknown preparation'):
            read_prepared(self.base)

    def test_location_oracle_mutation_and_negative_control(self):
        from verification.locations import check_archived
        (cases, _, scope) = read_prepared(self.base)
        case = cases[0]
        payload = {'status': 'completed', 'result': {'kind': 'memory', 'address': 8192}}
        self.assertEqual(check_archived(case, payload)['status'], 'pass')
        self.assertEqual(check_archived(case, {'result': {'kind': 'memory', 'address': 8193}})['status'], 'fail')
        unrelated = replace(case, context={'registers': {'0': 99}})
        self.assertEqual(check_archived(unrelated, payload)['status'], 'pass')
        changed = replace(case, origin=deepcopy(case.origin))
        changed.origin['location_oracle']['target']['original_root_bytes'] = [50]
        self.assertEqual(check_archived(changed, payload)['status'], 'tool_error')

    def test_expected_memory_and_register_mutations_are_detected(self):
        case = replace(self.case, context={'memory': {str(8192 + i): b for (i, b) in enumerate([13, 0, 0, 0])}})
        payload = {'status': 'completed', 'result': {'kind': 'memory', 'address': 8192}}
        self.assertEqual(assertions.check(case, payload)[0]['status'], 'pass')
        changed = replace(case, context={'memory': {str(8192 + i): b for (i, b) in enumerate([14, 0, 0, 0])}})
        self.assertEqual(assertions.check(changed, payload)[0]['status'], 'fail')
        register = replace(case, context={'registers': {'0': 13}})
        self.assertEqual(assertions.check(register, {'status': 'completed', 'result': {'kind': 'register', 'register': 0}})[0]['status'], 'pass')
        self.assertEqual(assertions.check(replace(register, context={'registers': {'0': 14}}), {'status': 'completed', 'result': {'kind': 'register', 'register': 0}})[0]['status'], 'fail')

    def test_portable_replay_uses_final_comparison_scope(self):
        from verification import acceptance
        from verification.model import Observation
        definition = self.root.parent / 'definition'
        definition.mkdir()
        (definition / 'compiled.bin').write_bytes(b'mocked definition')
        options = SimpleNamespace(inputs=self.base, output=self.root.parent / 'first-results', definition=definition, depth=10000, timeout=120, jobs=1, require_complete=True)
        native = {'status': 'completed', 'result': {'kind': 'memory', 'address': 8192}}
        with patch('verification.acceptance.k.run', return_value=Observation('k', 'success', native=native)):
            result = acceptance.test(options)
        self.assertEqual(result['corpus_scope']['core']['status']['pass'], 1)
        self.assertEqual(result['corpus_scope']['auxiliary']['total'], 0)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['source_requirements_exit_code'], 1)

    def test_dataset_version_and_scope_denominator_drift_rejected(self):
        p = self.root / 'manifest.json'
        document = json.loads(p.read_text())
        document['datasets']['gdb']['version'] = '18.1'
        document['archive_sha256'] = canonical_hash({k: v for (k, v) in document.items() if k != 'archive_sha256'})
        p.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'source or version'):
            read_prepared(self.base)
        seal(self.root)
        p = self.root / 'scope.json'
        document = json.loads(p.read_text())
        document['cases'].append(deepcopy(document['cases'][0]))
        p.write_text(json.dumps(document))
        seal(self.root)
        with self.assertRaisesRegex(ValueError, 'duplicate corpus scope'):
            read_prepared(self.base)

    def test_mutated_expected_value_fails_with_unchanged_K_output(self):
        case = replace(self.case, context={'memory': {str(8192 + i): b for (i, b) in enumerate([13, 0, 0, 0])}}, upstream_assertions=deepcopy(self.case.upstream_assertions))
        case.upstream_assertions[0]['expected']['fields'][0]['integer'] = 14
        result = assertions.check(case, {'status': 'completed', 'result': {'kind': 'memory', 'address': 8192}})
        self.assertEqual(result[0]['status'], 'fail')

    def test_missing_rule_still_difference_and_auxiliary_separate(self):
        record = {'execution': 'incomplete', 'checks': [{'target': 'result', 'status': 'fail', 'semantic_check_complete': True}]}
        scope = {**self.scope, 'observation': 'source-semantic-requirements'}
        result = evaluate_scope(record, scope)
        self.assertEqual(result['status'], 'fail')
        summary = scope_summary([{**record, 'corpus_evaluation': result}, {'execution': 'incomplete', 'corpus_evaluation': {**result, 'scope': 'auxiliary', 'status': 'uncheckable', 'fully_checked': False}}])
        self.assertEqual(summary['core']['total'], 1)
        self.assertEqual(summary['auxiliary']['total'], 1)
        self.assertEqual(summary['exit_code'], 1)
        result.update(status='uncheckable', fully_checked=False)
        records = [{**record, 'corpus_evaluation': result}]
        self.assertEqual(scope_summary(records)['exit_code'], 0)
        self.assertEqual(scope_summary(records, True)['exit_code'], 1)
    def test_runtime_reader_keeps_hashes_as_inert_provenance(self):
        p=self.root/'scope.json';doc=json.loads(p.read_text())
        doc['cases'][0].update(input_identity='historical',assertions_sha256='historical')
        write(p,doc)
        cases,_,scope=read_prepared(self.base)
        self.assertEqual(cases[0].bytes,[49]);self.assertEqual(scope['a']['input_identity'],'historical')

    def test_runtime_reader_rejects_missing_evidence(self):
        (self.base/'evidence/snapshot.json').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):read_prepared(self.base)

    def test_runtime_keeps_exact_source_assertion_anchor(self):
        from verification.corpus import source_evidence
        roots={'gdb':self.base/'sources/gdb'}
        self.assertEqual(source_evidence(self.case,roots)['status'],'match')
        (roots['gdb']/'suite.exp').write_text('changed assertion\n')
        self.assertEqual(source_evidence(self.case,roots)['status'],'changed')

if __name__ == '__main__':
    unittest.main()
