"""Source matcher promotion and partial-object observation regressions."""
from copy import deepcopy
from dataclasses import replace
import unittest

from verification import assertions
from verification.model import Case


class ScalarObservationTests(unittest.TestCase):
    def test_unsigned_widening_is_equality_not_actual_width_requirement(self):
        expected = {"bits": "1144201745", "width": 64, "signed": False}
        self.assertIs(assertions.scalar_equal(1144201745, 32, False, expected)[0], True)
        self.assertIs(assertions.scalar_equal(1144201744, 32, False, expected)[0], False)

    def test_signed_source_extends_before_comparison(self):
        expected = {"bits": str((1 << 64) - 1), "width": 64, "signed": True}
        self.assertIs(assertions.scalar_equal(255, 8, True, expected)[0], True)
        self.assertIs(assertions.scalar_equal(255, 8, False, expected)[0], False)

    def test_generic_signedness_only_blocks_sensitive_comparisons(self):
        expected = {"bits": str((1 << 32) - 1), "width": 32, "signed": False}
        self.assertIs(assertions.scalar_equal(-1, 32, None, expected)[0], True)
        expected["width"] = 64
        self.assertIsNone(assertions.scalar_equal(-1, 32, None, expected)[0])
        self.assertIs(assertions.scalar_equal(42, 32, None, expected)[0], False)

    def setUp(self):
        self.case = Case("partial", [0x93, 4], 64, "little", 5, True, 16,
            {"project": "gdb", "version": "17.1", "file": "test.exp", "test": "test",
             "assertion": "original", "migration": "original fixture"}, ["object"], context={})
        self.source = {"project": "gdb", "version": "17.1", "file": "test.exp",
                       "sha256": "a" * 64, "line": 1, "text": "original", "parameter": "single"}

    def checked(self, target, expected, payload):
        check = {"id": "check", "source": self.source, "target": target,
                 "expected": expected, "mapping": "source-reviewed predicate"}
        assertions.validate_assertions([check])
        return assertions.check(replace(self.case, upstream_assertions=[check]), payload)[0]

    def test_scalar_predicate_and_strict_width_remain_distinct(self):
        payload = {"status": "completed", "stack": [{"value": 42, "type": "g"}]}
        self.assertEqual(self.checked("stack_top", {"scalar": {"bits": 42, "width": 64, "signed": False}}, payload)["status"], "pass")
        self.assertEqual(self.checked("stack_top", {"width": 32}, payload)["status"], "fail")

    def test_invalid_scalar_predicates_rejected(self):
        for scalar in ({}, {"bits": True, "width": 32, "signed": False},
                       {"bits": 1, "width": 0, "signed": False},
                       {"bits": 1, "width": 32, "signed": 0},
                       {"bits": 1, "width": 32, "signed": False, "extra": 1}):
            with self.subTest(scalar=scalar), self.assertRaises(ValueError):
                self.checked("stack_top", {"scalar": scalar}, {})

    def test_partial_array_preserves_exact_unknown_tail(self):
        expected = {"fields": [{"offset": 0, "size": 32, "integer": 1779823878, "signed": True}]
                    + [{"offset": i * 32, "size": 32, "available": False} for i in range(1, 4)],
                    "availability": "0" * 96 + "1" * 32}
        payload = {"status": "completed", "result": {"kind": "composite", "bit_size": 32,
                   "bits": format(1779823878, "032b")}}
        self.assertEqual(self.checked("object", expected, payload)["status"], "pass")
        changed = deepcopy(payload)
        changed["result"]["bits"] = format(1779823879, "032b")
        self.assertEqual(self.checked("object", expected, changed)["status"], "fail")
        changed = deepcopy(payload)
        changed["result"].update(bit_size=128, bits="0" * 96 + changed["result"]["bits"])
        self.assertEqual(self.checked("object", expected, changed)["status"], "fail")
        changed = deepcopy(expected)
        changed["fields"][0]["integer"] += 1
        self.assertEqual(self.checked("object", changed, payload)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
