"""Location identity is independent of source object contents and DW_OP text."""
import copy
import hashlib
import json
import os
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from verification.locations import native_location, queried_location, verify_binding, compare_location, check_archived

class LocationTests(unittest.TestCase):

    def test_native_pointer_and_register_storage(self):
        self.assertEqual(native_location({'address': '0'}), {'kind': 'memory', 'address': 0})
        self.assertEqual(native_location({'variable': 'a', 'queries': [{'command': 'output/x &(a)', 'error': False, 'output': '0x104\n'}]}), {'kind': 'memory', 'address': 260})
        record = {'variable': 'm', 'queries': [{'command': 'output/x &(m)', 'error': True, 'output': 'Address requested for identifier "m" which is in register $xmm2'}]}
        self.assertEqual(native_location(record)['register'], 19)
        record['queries'] = [{'command': 'info address m', 'error': False, 'output': 'Symbol "m" is a variable in $xmm2.\n'}]
        self.assertEqual(native_location(record)['register'], 19)
        self.assertFalse(native_location(record)['value_availability_proven'])

    def test_disassembly_and_unknown_register_are_not_oracles(self):
        for output in ('Symbol "a" is a complex DWARF expression: DW_OP_reg5', 'Symbol "a" is a variable in $unmapped.'):
            record = {'variable': 'a', 'queries': [{'command': 'info address a', 'error': False, 'output': output}]}
            self.assertEqual(native_location(record)['kind'], 'unknown')

    def test_derived_element_uses_k_data_and_bounds_not_root_descriptor(self):
        payload = {'status': 'completed', 'result': {'kind': 'memory', 'address': 800}, 'object_location': {'kind': 'memory', 'address': 100}, 'object_bit_offset': 32, 'properties': {'lower_bound': 1}}
        original = copy.deepcopy(payload)
        self.assertEqual(queried_location(None, payload, 'element'), {'kind': 'memory', 'address': 104})
        self.assertEqual(queried_location(None, payload, 'root'), {'kind': 'memory', 'address': 800})
        self.assertEqual(payload, original)

    def test_base_subobject_keeps_k_result_and_nonbyte_target_is_rejected(self):
        payload = {'result': {'kind': 'memory', 'address': 24}}
        self.assertEqual(queried_location(None, payload, 'base_subobject'), payload['result'])
        payload.update(object_location=payload['result'], object_bit_offset=3)
        with self.assertRaisesRegex(ValueError, 'byte aligned'):
            queried_location(None, payload, 'element')
        payload['observation_gap'] = {'diagnostic': 'missing bound'}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            queried_location(None, payload, 'element')

    def test_location_comparison_does_not_use_object_contents(self):
        expected = {'kind': 'memory', 'address': 100}
        self.assertEqual(compare_location(expected, expected)[0], 'match')
        self.assertEqual(compare_location({'kind': 'memory', 'address': 101}, expected)[0], 'difference')
        self.assertEqual(compare_location({'kind': 'register', 'register': 5}, expected)[0], 'difference')
        self.assertEqual(compare_location(expected, {'kind': 'unknown', 'reason': 'unavailable'})[0], 'uncheckable')

    def test_snapshot_frame_and_query_mutations_are_detected(self):
        scratch = Path(os.environ.get('DWARF_INPUT_TMPDIR', f'/tmp/scratch/kframework-location-tests-{os.getpid()}'))
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / 'snapshot.json'
            snapshot = {'pid': 8, 'frame': {'pc': '128'}, 'command': 'print a'}
            path.write_text(json.dumps(snapshot))
            evidence = {'snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'suite': 'test', 'before': {'pid': 8, 'pc': '128', 'level': 0}, 'same_stop': True, 'registers_unchanged': True, 'settings_restored': True}
            target = {'suite': 'test', 'command': 'print a', 'frame_level': 0}
            verify_binding(evidence, path, snapshot, target)
            for changed in ({'frame_level': 1}, {'command': 'print b'}, {'suite': 'other'}):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    verify_binding(evidence, path, snapshot, {**target, **changed})
            path.write_text(json.dumps({**snapshot, 'registers': {'0': '999'}}))
            with self.assertRaisesRegex(ValueError, 'snapshot identity'):
                verify_binding(evidence, path, snapshot, target)

    def test_oracle_mutation_fails_but_unrelated_metadata_is_ignored(self):
        actual = {'kind': 'register', 'register': 19}
        self.assertEqual(compare_location(actual, {**actual, 'note': 'unrelated'})[0], 'match')
        self.assertEqual(compare_location(actual, {'kind': 'register', 'register': 18})[0], 'difference')

    def test_offline_oracle_identity_and_projection(self):
        scratch = Path(os.environ.get('DWARF_INPUT_TMPDIR', f'/tmp/scratch/kframework-location-tests-{os.getpid()}'))
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps({'pid': 8, 'frame': {'pc': '128'}, 'command': 'print a(2)'}))
            target = {'suite': 'test', 'command': 'print a(2)', 'frame_level': 0, 'original_root_bytes': [49], 'role': 'element'}
            evidence = {'snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'suite': 'test', 'before': {'pid': 8, 'pc': '128', 'level': 0}, 'same_stop': True, 'registers_unchanged': True, 'settings_restored': True, 'observations': [{'id': 'example', 'variable': 'a', 'role': 'element', 'address': '104'}]}
            oracle = Path(directory) / 'oracle.json'
            oracle.write_text(json.dumps(evidence))
            case = SimpleNamespace(id='example', bytes=[49], origin={'snapshot': str(path), 'location_oracle': {'path': str(oracle), 'sha256': hashlib.sha256(oracle.read_bytes()).hexdigest(), 'target': target}})
            payload = {'result': {'kind': 'memory', 'address': 800}, 'object_location': {'kind': 'memory', 'address': 100}, 'object_bit_offset': 32}
            self.assertEqual(check_archived(case, payload)['status'], 'pass')
            self.assertEqual(check_archived(case, {**payload, 'object_bit_offset': 64})['status'], 'fail')
            oracle.write_text(json.dumps({**evidence, 'same_stop': False}))
            self.assertEqual(check_archived(case, payload)['status'], 'tool_error')
if __name__ == '__main__':
    unittest.main()
