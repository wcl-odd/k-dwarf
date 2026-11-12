"""A natural stop needs the exact reviewed scene and independent K evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from verification import assertions
from verification.acceptance import verify_stopped_configuration
from verification.model import Case


class StuckObservationTests(unittest.TestCase):
    def setUp(self):
        self.expected = {"position": 2, "stack": [{"value": 7, "type": "g"}], "stable": True}
        source = {"project": "lldb", "version": "22.1.8", "file": "fixture.cpp",
                  "sha256": "a" * 64, "line": 1, "text": "original Failed()", "parameter": "single"}
        self.assertion = {"id": "stop", "source": source, "target": "stopped",
                          "expected": self.expected, "mapping": "Reviewed exact failure scene; no invented error constructor"}
        self.case = Case("stop", [0x37, 0x06], 32, "little", 5, True, 4,
                         {"project": "lldb", "version": "22.1.8", "file": "fixture.cpp",
                          "test": "failure", "assertion": "original", "migration": "reviewed"},
                         ["numeric"], upstream_assertions=[self.assertion])
        self.payload = {"status": "incomplete", "position": 2, "stack": deepcopy(self.expected["stack"]),
                        "stop_reason": None, "configuration": {"term": {"value": "actual K state"}},
                        "stability_evidence": {"same_configuration": True, "probe_status": "incomplete",
                                               "base_budget": 10000, "probe_budget": 20000, "probe_rewrite_steps": 1}}

    def checked(self, payload=None):
        assertions.validate_assertions([self.assertion])
        return assertions.check(self.case, self.payload if payload is None else payload)[0]

    def test_exact_scene_and_verified_stability_pass(self):
        self.assertEqual(self.checked()["status"], "pass")

    def test_position_and_stack_changes_fail(self):
        for field, value in (("position", 0), ("stack", [])):
            bad = deepcopy(self.payload)
            bad[field] = value
            self.assertEqual(self.checked(bad)["status"], "fail")

    def test_missing_replay_evidence_cannot_pass(self):
        bad = deepcopy(self.payload)
        del bad["stability_evidence"]
        self.assertEqual(self.checked(bad)["status"], "uncheckable")
        self.assertFalse(self.checked(bad)["semantic_check_complete"])

    def test_equal_configuration_at_periodic_loop_budget_cannot_pass(self):
        bad = deepcopy(self.payload)
        bad["stability_evidence"]["probe_rewrite_steps"] = 20000
        self.assertEqual(self.checked(bad)["status"], "fail")
        bad["stability_evidence"]["probe_rewrite_steps"] = None
        self.assertEqual(self.checked(bad)["status"], "uncheckable")

    def test_changed_or_completed_probe_and_nonincreased_budget_fail(self):
        for field, value in (("same_configuration", False), ("probe_status", "completed"), ("probe_budget", 10000)):
            bad = deepcopy(self.payload)
            bad["stability_evidence"][field] = value
            self.assertEqual(self.checked(bad)["status"], "fail")

    def test_legacy_reason_requirement_is_not_silently_ignored(self):
        self.expected["stop_reason"] = {"kind": "unavailable_memory"}
        self.assertEqual(self.checked()["status"], "fail")

    def test_malformed_stability_predicates_rejected(self):
        for value in (False, 1, "true"):
            self.expected["stable"] = value
            with self.assertRaises(ValueError):
                self.checked()
        self.expected["stable"] = True
        del self.expected["stack"]
        with self.assertRaises(ValueError):
            self.checked()

    def test_probe_preserves_options_and_saves_actual_configuration_evidence(self):
        options = SimpleNamespace(depth=10000, statistics=True)
        payload = deepcopy(self.payload)
        payload["rewrite_statistics"] = {"raw": "[1 steps]"}
        observation = SimpleNamespace(native=deepcopy(payload))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch("verification.acceptance.prepare_case"), patch("verification.acceptance.k.run", return_value=observation) as run:
                evidence = verify_stopped_configuration(self.case, directory, options, payload)
            self.assertEqual(options.depth, 10000)
            self.assertEqual(run.call_args.args[2].depth, 20000)
            self.assertTrue(evidence["same_configuration"])
            self.assertEqual(evidence["probe_rewrite_steps"], 1)
            self.assertEqual(evidence, json.loads((directory / "stability-evidence.json").read_text()))
