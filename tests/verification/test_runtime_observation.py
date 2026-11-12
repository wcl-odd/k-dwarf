"""Runtime metadata is supplied; referenced expressions still execute in K."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from verification import assertions, dependencies
from verification.context import validate
from verification.model import Case, Observation

class RuntimeObservationTests(TestCase):

    def setUp(self):
        self.case = Case('runtime', [160, 32, 0, 0, 0, 0], 64, 'little', 5, True, 1, {'project': 'gdb', 'version': 'pinned', 'file': 'test.exp', 'test': 'original', 'assertion': 'original', 'migration': 'test fixture'}, ['object'], context={})

    def test_uninitialized_predicate_is_independent_of_object_bits(self):
        source = {'project': 'gdb', 'version': 'pinned', 'file': 'test.exp', 'sha256': '0' * 64, 'line': 1, 'text': 'original', 'parameter': 'single'}
        checks = [{'id': 'marker', 'source': source, 'target': 'result', 'expected': {'uninitialized': True}, 'mapping': 'original marker predicate'}]
        assertions.validate_assertions(checks)
        case = replace(self.case, upstream_assertions=checks)
        payload = {'status': 'completed', 'result': {'kind': 'value', 'value': 42, 'type': 'g', 'uninitialized': True}}
        self.assertEqual(assertions.check(case, payload)[0]['status'], 'pass')
        payload['result'].pop('uninitialized')
        self.assertEqual(assertions.check(case, payload)[0]['status'], 'fail')

    def test_reference_constant_and_offset_use_original_metadata(self):
        case = replace(self.case, origin={**self.case.origin, 'referent_constants': {'32': [11, 22, 33]}, 'projection_byte_offset': -1})
        payload = {'result': {'kind': 'implicit_pointer', 'reference': 32, 'offset': 2}}
        context = {'die_locations': {'32': {'bytes': []}}}
        evidence = []
        dependencies.implicit_observation(case, payload, context, Path('.'), None, evidence)
        self.assertEqual(payload['result']['kind'], 'implicit_pointer')
        self.assertEqual(payload['object_location'], {'kind': 'bytes', 'bytes': [11, 22, 33]})
        self.assertEqual(payload['object_bit_offset'], 8)
        (bits, _, gap) = assertions.materialize(case, payload)
        self.assertIsNone(gap)
        self.assertEqual(int(bits[::-1], 2), 22)

    def test_referenced_location_is_not_evaluated_by_python(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dependencies').mkdir()
            body = {'bytes': [8, 100], 'address_width': 64, 'unit_offset': 20}
            context = {'die_locations': {'32': body}, 'memory': {'101': 42}}
            payload = {'result': {'kind': 'implicit_pointer', 'reference': 32, 'offset': 1}}
            with patch('verification.dependencies.k.run', return_value=Observation('k', 'success', native={'status': 'completed', 'result': {'kind': 'memory', 'address': 100}})) as evaluator:
                evidence = []
                dependencies.implicit_observation(self.case, payload, context, root, SimpleNamespace(), evidence)
                called = evaluator.call_args.args[0]
                self.assertEqual(called.bytes, body['bytes'])
                self.assertEqual(called.context['compilation_unit_offset'], 20)
                self.assertEqual(payload['object_location'], {'kind': 'memory', 'address': 101})

    def test_missing_pointer_snapshot_is_a_gap_not_zero(self):
        case = replace(self.case, origin={**self.case.origin, 'snapshot': 'archived', 'pointer_root_size': 8})
        with self.assertRaises(dependencies.ObservationGap):
            dependencies.root_observation(case, {'result': {'kind': 'memory', 'address': 100}}, {}, [])
