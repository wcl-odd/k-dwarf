"""Upstream assertions must fail independently of debugger agreement."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from verification import acceptance, assertions
from verification.input import write_json
from verification.model import Case, Observation
from verification.process import execute, ToolFailure
from verification.corpus import load_cases

class AssertionTests(unittest.TestCase):

    def setUp(self):
        self.source = {'project': 'gdb', 'version': 'test', 'file': 'test.exp', 'sha256': 'a' * 64, 'line': 1, 'text': 'original assertion', 'parameter': 'single'}
        self.case = Case('sample', [49], 64, 'little', 5, True, 8, {'project': 'gdb', 'version': 'test', 'file': 'test.exp', 'test': 'test', 'assertion': 'one', 'migration': 'fixture'}, ['numeric'], context={})

    def checked(self, target, expected, payload, **extra):
        item = {'id': 'a', 'source': self.source, 'target': target, 'expected': expected, 'mapping': 'source predicate', **extra}
        case = replace(self.case, upstream_assertions=[item])
        assertions.validate_assertions(case.upstream_assertions)
        return assertions.check(case, payload)[0]

    def test_mathematical_integer_and_bit_pattern_are_distinct(self):
        payload = {'status': 'completed', 'stack': [{'value': -1, 'type': 'g'}]}
        self.assertEqual(self.checked('stack_top', {'integer': str((1 << 64) - 1)}, payload)['status'], 'fail')
        self.assertEqual(self.checked('stack_top', {'bits': str((1 << 64) - 1)}, payload)['status'], 'pass')

    def test_type_identity_and_effective_width_are_preserved(self):
        self.case = replace(self.case, context={'types': {'1': {'id': 'first', 'encoding': 'DW_ATE_signed', 'bit_width': 7, 'byte_size': 1}}})
        payload = {'status': 'completed', 'stack': [{'value': -1, 'type': {'id': 'first'}}]}
        self.assertEqual(self.checked('stack_top', {'type': {'id': 'second'}}, payload)['status'], 'fail')
        self.assertEqual(self.checked('stack_top', {'width': 7, 'signed': True}, payload)['status'], 'pass')

    def test_scalar_signedness_is_not_invented_for_generic(self):
        payload = {'status': 'completed', 'stack': [{'value': 1, 'type': 'g'}]}
        self.assertEqual(self.checked('stack_top', {'integer': '1', 'signed': False}, payload)['status'], 'uncheckable')

    def test_error_incomplete_is_not_an_equivalent_error(self):
        self.assertEqual(self.checked('uncheckable', {}, {'status': 'incomplete'})['status'], 'uncheckable')
        p = {'status': 'incomplete', 'position': 2, 'stack': []}
        self.assertEqual(self.checked('stopped', {'position': 2, 'stack': []}, p)['status'], 'pass')
        self.assertEqual(self.checked('stopped', {}, p)['status'], 'uncheckable')

    def test_failure_site_and_stack_are_both_checked(self):
        p = {'status': 'incomplete', 'position': 1, 'stack': [{'value': 1, 'type': 'g'}]}
        self.assertEqual(self.checked('stopped', {'position': 2, 'stack': []}, p)['status'], 'fail')

    def test_unknown_bits_are_not_wildcards(self):
        p = {'status': 'completed', 'result': {'kind': 'composite', 'bits': '????0001'}}
        self.case = replace(self.case, object_size=1)
        self.assertEqual(self.checked('object', {'fields': [{'offset': 0, 'size': 8, 'bits': 1}]}, p)['status'], 'fail')
        self.assertEqual(self.checked('object', {'fields': [{'offset': 0, 'size': 4, 'bits': 1}, {'offset': 4, 'size': 4, 'available': False}]}, p)['status'], 'pass')

    def test_large_objects_and_signed_nonbyte_fields(self):
        self.case = replace(self.case, object_size=17)
        p = {'status': 'completed', 'result': {'kind': 'bytes', 'bytes': [255] * 17}}
        self.assertEqual(self.checked('object', {'fields': [{'offset': 1, 'size': 131, 'integer': -1, 'signed': True}]}, p)['status'], 'pass')

    def test_exact_byte_buffer_assertion_checks_extent(self):
        self.case = replace(self.case, object_size=1)
        p = {'status': 'completed', 'result': {'kind': 'bytes', 'bytes': [1, 2]}}
        self.assertEqual(self.checked('object', {'object_bytes': [1]}, p)['status'], 'fail')

    def test_register_result_materializes_from_saved_fixture(self):
        self.case = replace(self.case, context={'registers': {'3': 42}})
        p = {'status': 'completed', 'result': {'kind': 'register', 'register': 3}}
        expected = {'kind': 'register', 'fields': [{'offset': 0, 'size': 64, 'bits': 42}]}
        self.assertEqual(self.checked('object', expected, p)['status'], 'pass')
        self.case = replace(self.case, context={'registers': {'3': 43}})
        self.assertEqual(self.checked('object', expected, p)['status'], 'fail')

    def test_wide_register_object_is_an_observation_gap_not_invented_unknown_bits(self):
        self.case = replace(self.case, object_size=16, context={'registers': {'3': 42, '4': 43}})
        p = {'status': 'completed', 'result': {'kind': 'register', 'register': 3}}
        result = self.checked('object', {'fields': [{'offset': 64, 'size': 64, 'bits': 43}]}, p)
        self.assertEqual(result['status'], 'uncheckable')
        self.assertIn('register-spanning', result['details'][0])

    def test_memory_mutation_missing_bytes_and_big_endian(self):
        self.case = replace(self.case, object_size=2, context={'memory': {'10': 1, '11': 2}})
        p = {'status': 'completed', 'result': {'kind': 'memory', 'address': 10}}
        expected = {'fields': [{'offset': 0, 'size': 16, 'bits': 513}]}
        self.assertEqual(self.checked('object', expected, p)['status'], 'pass')
        self.case = replace(self.case, context={'memory': {'10': 0, '11': 2}})
        self.assertEqual(self.checked('object', expected, p)['status'], 'fail')
        self.case = replace(self.case, context={'memory': {'10': 1}})
        self.assertEqual(self.checked('object', expected, p)['status'], 'fail')
        self.case = replace(self.case, endianness='big', context={'memory': {'10': 2, '11': 1}})
        self.assertEqual(self.checked('object', expected, p)['status'], 'pass')

    def test_live_memory_collection_gap_is_not_a_k_failure(self):
        self.case = replace(self.case, object_size=1, origin={**self.case.origin, 'snapshot': 'frozen.json'}, context={'memory': {}})
        p = {'status': 'completed', 'result': {'kind': 'memory', 'address': 10}}
        r = self.checked('object', {'fields': [{'offset': 0, 'size': 8, 'bits': 42}]}, p)
        self.assertEqual(r['status'], 'uncheckable')
        self.assertEqual(r['evidence']['reads'][0]['address'], '10')

    def test_partial_semantic_success_is_not_whole_assertion_pass(self):
        p = {'status': 'completed', 'stack': [{'value': 1, 'type': 'g'}]}
        r = self.checked('stack_top', {'integer': 1}, p, uncheckable=['native formatting'])
        self.assertEqual(r['status'], 'uncheckable')
        self.assertTrue(r['predicates_passed'])

    def test_bad_expectation_and_missing_source_identity_are_rejected(self):
        a = {'id': 'a', 'source': self.source, 'target': 'object', 'expected': {'surprise': 1}, 'mapping': 'source'}
        with self.assertRaises(ValueError):
            assertions.validate_assertions([a])
        a['expected'] = {}
        a['source'] = {}
        with self.assertRaises(ValueError):
            assertions.validate_assertions([a])

    def test_predicate_for_another_target_cannot_silently_pass(self):
        for (target, expected) in (('object', {'integer': 1}), ('stack_top', {'object_bytes': [1]}), ('object', {'fields': []}), ('object', {'availability': '1?'})):
            with self.assertRaises(ValueError):
                self.checked(target, expected, {'status': 'completed'})

    def test_register_identity_accepts_decimal_transport(self):
        p = {'status': 'completed', 'result': {'kind': 'register', 'register': 3}}
        self.assertEqual(self.checked('result', {'kind': 'register', 'register': '3'}, p)['status'], 'pass')
if __name__ == '__main__':
    unittest.main()
