"""The minimal paper runner consumes only expression, interface and requirements."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "tools/artifact-runtime"


class ExpressionCaseTests(unittest.TestCase):
    def setUp(self):
        names = (
            "cases",
            "requirements",
            "dependencies",
            "k",
            "runner",
            "processes",
            "experiment",
        )
        previous = {n: sys.modules.pop(n, None) for n in names}
        sys.path.insert(0, str(RUNTIME))

        def restore():
            sys.path.remove(str(RUNTIME))
            for n, old in previous.items():
                sys.modules.pop(n, None)
                if old is not None:
                    sys.modules[n] = old

        self.addCleanup(restore)
        self.cases = importlib.import_module("cases")
        self.exp = importlib.import_module("experiment")
        self.req = importlib.import_module("requirements")
        self.k = importlib.import_module("k")
        self.runner = importlib.import_module("runner")
        scratch = Path("/tmp/scratch")
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="kframework-expression-tests-", dir=scratch
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = {
            "id": "lldb-001",
            "tool": "lldb",
            "group": "core",
            "source": {"file": "/must/not/open/source.cpp", "test": "original"},
            "expression": {"bytecode": "31", "purpose": "location"},
            "interface": {"address_width": 32, "endianness": "little", "state": None},
            "requirements": {
                "observation": "source-semantic-requirements",
                "layout": {"byte_size": 4},
                "predicates": [
                    {
                        "target": "stack_top",
                        "expected": {"integer": 1},
                        "mapping": "Original requirement.",
                    }
                ],
            },
        }
        self.options = SimpleNamespace(
            timeout=120,
            depth=10000,
            jobs=4,
            statistics=True,
            definition=self.root / "definition",
        )

    def load(self, rows=None):
        file = self.root / "lldb.json"
        file.write_text(json.dumps({"cases": rows or [self.row]}))
        return self.cases.load_cases(file)

    def call(self, case, directory, options, *, value=1, status="completed", steps=10):
        target = directory / "k"
        target.mkdir()
        (target / "exit.json").write_text(
            json.dumps({"returncode": int(status != "completed")})
        )
        (target / "command.json").write_text(
            json.dumps({"argv": ["runner.py", "--depth", str(options.depth)]})
        )
        (target / "stderr.txt").write_text(f"{steps} rewrites")
        return SimpleNamespace(
            state="success" if status == "completed" else "incomplete",
            diagnostic="",
            outcome={
                "status": status,
                "stack": [{"value": value, "type": "g"}],
                "result": {"kind": "memory", "address": value},
                "position": 1,
                "end": 1,
                "configuration": {"term": "same"},
                "rewrite_statistics": {"raw": f"{steps} rewrites"},
            },
        )

    def test_case_source_is_documentation_only(self):
        case = self.load()[0]
        self.assertFalse(hasattr(case, "source"))
        del self.row["source"]
        self.assertEqual(case, self.load()[0])
        self.assertEqual(case.bytes, [49])
        self.assertEqual(case.predicates[0]["expected"], {"integer": 1})

    def write_source_files(self):
        core = deepcopy(self.row)
        auxiliary = deepcopy(self.row)
        auxiliary.update(id="lldb-002", group="auxiliary")
        gdb = deepcopy(self.row)
        gdb.update(id="gdb-001", tool="gdb")
        (self.root / "lldb.json").write_text(json.dumps({"cases": [core, auxiliary]}))
        (self.root / "gdb.json").write_text(json.dumps({"cases": [gdb]}))
        return core, auxiliary, gdb

    def test_source_files_preserve_cases_and_groups(self):
        originals = self.write_source_files()
        actual = self.cases.load_corpus(self.root)
        self.assertEqual([c.id for c in actual], [r["id"] for r in originals])
        self.assertEqual([c.group for c in actual], ["core", "auxiliary", "core"])
        for case, row in zip(actual, originals):
            for field in ("expression", "interface", "requirements"):
                self.assertEqual(getattr(case, field), row[field])

    def test_source_selection_does_not_open_unselected_file(self):
        self.write_source_files()
        (self.root / "gdb.json").write_text("invalid JSON")
        self.assertEqual(len(self.cases.load_corpus(self.root, "lldb")), 2)
        with self.assertRaises(ValueError):
            self.cases.load_corpus(self.root)
        self.write_source_files()
        (self.root / "lldb.json").unlink()
        self.assertEqual(len(self.cases.load_corpus(self.root, "gdb")), 1)
        with self.assertRaises(FileNotFoundError):
            self.cases.load_corpus(self.root)

    def test_misfiled_source_and_mismatched_identity_are_rejected(self):
        _, _, gdb = self.write_source_files()
        (self.root / "lldb.json").write_text(json.dumps({"cases": [gdb]}))
        with self.assertRaisesRegex(ValueError, "source differs"):
            self.cases.load_corpus(self.root, "lldb")
        self.row["tool"] = "gdb"
        (self.root / "gdb.json").write_text(json.dumps({"cases": [self.row]}))
        with self.assertRaisesRegex(ValueError, "source differs"):
            self.cases.load_corpus(self.root, "gdb")

    def test_cli_source_selection_and_default_are_unchanged(self):
        self.assertEqual(self.invoke(source=None), 0)
        result = self.last_summary
        self.assertEqual(result["tasks_completed"], 2)
        self.assertEqual(set(result["sources"]), {"lldb", "gdb"})

    def test_cli_gdb_source_reads_only_gdb_cases(self):
        self.assertEqual(self.invoke(("--source", "gdb")), 0)
        result = self.last_summary
        self.assertEqual(result["tasks_completed"], 1)
        self.assertEqual(set(result["sources"]), {"gdb"})

    def test_empty_expression_and_deliberately_unknown_interface_are_valid(self):
        self.row["expression"]["bytecode"] = ""
        case = self.load()[0]
        self.assertEqual(case.bytes, [])
        self.assertIsNone(case.context)

    def test_invalid_duplicate_or_unsafe_cases_are_rejected(self):
        for field, value in [
            ("id", "../outside"),
            ("group", "unknown"),
            ("tool", "other"),
        ]:
            original = deepcopy(self.row)
            self.row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load()
            self.row = original
        with self.assertRaises(ValueError):
            self.load([self.row, self.row])
        self.row["expression"]["bytecode"] = "310"
        with self.assertRaises(ValueError):
            self.load()

    def test_dependency_order_and_cycles_are_rejected(self):
        self.row["expression"]["dependencies"] = [
            {
                "id": "size",
                "phase": "before",
                "bytes": [49],
                "purpose": "value",
                "bind": {"object_address": "root"},
            }
        ]
        with self.assertRaisesRegex(ValueError, "dependency"):
            self.load()

    def test_expected_value_mutation_changes_verdict_not_completion(self):
        case = self.load()[0]
        with patch.object(self.k, "run", side_effect=self.call):
            record = self.exp.evaluate_case(case, self.root, self.options)
        self.assertEqual(record["verdict"], "consistent")
        changed = self.cases.replace_case(
            case,
            id="lldb-002",
            predicates=[
                {
                    "target": "stack_top",
                    "expected": {"integer": 2},
                    "mapping": "Mutated expectation.",
                }
            ],
        )
        with patch.object(self.k, "run", side_effect=self.call):
            record = self.exp.evaluate_case(changed, self.root, self.options)
        self.assertEqual(record["verdict"], "inconsistent")
        summary = self.exp.write_report(self.root, [record], self.options)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["total"]["inconsistent"], 1)

    def test_location_identity_uses_independent_expected_address(self):
        self.row["requirements"]["location"] = {
            "role": "root",
            "expected": {"kind": "memory", "address": 7},
        }
        case = self.load()[0]
        result = self.req.check_requirements(
            case,
            {"status": "completed", "result": {"kind": "memory", "address": 8}},
            "success",
        )
        self.assertEqual(result["verdict"], "inconsistent")
        self.assertEqual(result["checks"][-1]["target"], "location_identity")

    def test_expected_abnormal_termination_requires_stability_and_counts(self):
        self.row["requirements"]["predicates"] = [
            {
                "target": "stopped",
                "expected": {
                    "position": 1,
                    "stack": [{"value": 1, "type": "g"}],
                    "stable": True,
                },
                "mapping": "Original stop.",
            }
        ]
        case = self.load()[0]

        def stopped(c, d, o):
            return self.call(c, d, o, status="incomplete")

        with patch.object(self.k, "run", side_effect=stopped):
            record = self.exp.evaluate_case(case, self.root, self.options)
        self.assertEqual(record["verdict"], "consistent")
        self.assertEqual(record["execution_faults"], [])
        self.assertTrue((self.root / case.id / "stability.json").is_file())

    def test_budget_exhaustion_is_not_expected_semantic_failure(self):
        case = self.load()[0]

        def exhausted(c, d, o):
            return self.call(c, d, o, status="incomplete", steps=o.depth)

        with patch.object(self.k, "run", side_effect=exhausted):
            record = self.exp.evaluate_case(case, self.root, self.options)
        self.assertEqual(record["verdict"], "undetermined")
        self.assertEqual(record["execution_faults"][0]["kind"], "budget_exhausted")
        self.assertEqual(
            self.exp.write_report(self.root, [record], self.options)["exit_code"], 1
        )

    def test_timeout_receipt_and_missing_prerequisite_are_execution_faults(self):
        case = self.load()[0]

        def timeout(c, d, o):
            p = d / "k"
            p.mkdir()
            (p / "exit.json").write_text('{"timeout":true}')
            raise self.exp.ToolFailure("timeout")

        with patch.object(self.k, "run", side_effect=timeout):
            record = self.exp.evaluate_case(case, self.root, self.options)
        self.assertEqual(record["verdict"], "undetermined")
        self.assertIn("timeout", {f["kind"] for f in record["execution_faults"]})

    def test_root_and_auxiliary_denominators_are_separate(self):
        records = [
            {
                "id": "lldb-001",
                "tool": "lldb",
                "group": "core",
                "verdict": "inconsistent",
                "execution_faults": [],
                "checks": [],
            },
            {
                "id": "lldb-002",
                "tool": "lldb",
                "group": "auxiliary",
                "verdict": "uncheckable",
                "execution_faults": [],
                "checks": [],
            },
        ]
        summary = self.exp.write_report(self.root, records, self.options)
        self.assertEqual(summary["total"]["cases"], 1)
        self.assertEqual(summary["sources"]["lldb"]["auxiliary"]["cases"], 1)
        self.assertEqual(summary["tasks_completed"], 2)

    def invoke(self, args=(), *, interrupt=False, crash=False, source="lldb"):
        (self.root / "test-corpus").mkdir(exist_ok=True)
        (self.root / "test-corpus/lldb.json").write_text(
            json.dumps({"cases": [self.row]})
        )
        gdb = deepcopy(self.row)
        gdb.update(id="gdb-001", tool="gdb")
        (self.root / "test-corpus/gdb.json").write_text(json.dumps({"cases": [gdb]}))
        original_report = self.exp.write_report
        self.last_summary = None

        def report(*args, **kwargs):
            self.last_summary = original_report(*args, **kwargs)
            return self.last_summary

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(self.exp, "write_report", side_effect=report)
            )
            stack.enter_context(patch.object(self.exp, "ROOT", self.root))
            stack.enter_context(patch.object(self.exp, "preflight"))
            stack.enter_context(
                patch.object(
                    self.k,
                    "run",
                    side_effect=(
                        KeyboardInterrupt
                        if interrupt
                        else AttributeError("adapter defect") if crash else self.call
                    ),
                )
            )
            stack.enter_context(patch.dict(os.environ))
            stack.enter_context(patch.object(os, "sched_setaffinity"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            selection = [] if source is None else ["--source", source]
            return self.exp.main(
                ["--output", str(self.root / "fresh"), *selection, *args]
            )

    def test_runner_never_reads_reference_results_or_source_files(self):
        (self.root / "results").mkdir()
        (self.root / "results/report.md").write_text("unreadable reference report")
        original = Path.open

        def guarded(path, *a, **kw):
            if path.is_relative_to(self.root / "results") or str(path).startswith(
                "/must/not/open"
            ):
                raise AssertionError("reference file read")
            return original(path, *a, **kw)

        with patch.object(Path, "open", guarded):
            self.assertEqual(self.invoke(), 0)
        self.assertFalse((self.root / "fresh/comparison.json").exists())
        self.assertEqual(self.last_summary["total"]["consistent"], 1)
        self.assertEqual(self.invoke(), 2)

    def test_interrupt_is_reported_and_budget_limits_are_explicit(self):
        self.assertEqual(self.invoke(interrupt=True), 130)
        summary = self.last_summary
        self.assertTrue(summary["interrupted"])
        self.assertIn("Interrupted: yes", (self.root / "fresh/report.md").read_text())
        self.assertEqual(summary["missing_cases"], ["lldb-001"])
        self.assertEqual(summary["tasks_expected"], 1)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.exp.main(["--output", "unused", "--jobs", "17"])

    def test_unexpected_worker_failure_reports_unexecuted_required_task(self):
        self.assertEqual(self.invoke(crash=True), 1)
        summary = self.last_summary
        self.assertEqual(summary["exit_code"], 1)
        self.assertEqual(summary["missing_cases"], ["lldb-001"])
        self.assertEqual(summary["execution_faults"][0]["kind"], "not_run")
        self.assertIn("adapter defect", (self.root / "fresh/report.md").read_text())

    def test_report_replaces_summary_and_records_completion_settings(self):
        self.assertEqual(self.invoke(source=None), 0)
        output = self.root / "fresh"
        self.assertFalse((output / "summary.json").exists())
        self.assertFalse((output / "README.md").exists())
        text = (output / "report.md").read_text()
        for expected in (
            "Completed tasks: 2 / 2",
            "Timeout: 120 seconds",
            "Rewrite budget: 10000",
            "Concurrency: 4 cases",
            "Interrupted: no",
            "Exit code: 0",
            "## Auxiliary checks",
            "## Unexecuted tasks",
            "## Execution faults",
        ):
            self.assertIn(expected, text)
        self.assertTrue((output / "checks.csv").is_file())
        self.assertTrue((output / "expressions.csv").is_file())

    def test_reports_retain_fault_diagnostics_and_escape_table_cells(self):
        self.options.case_ids = ["lldb-001", "gdb-001"]
        record = {
            "id": "lldb-001",
            "tool": "lldb",
            "group": "core",
            "verdict": "undetermined",
            "execution_faults": [
                {"call": "k", "kind": "timeout", "diagnostic": "line one|two\nnext"}
            ],
            "checks": [],
        }
        summary = self.exp.write_report(
            self.root, [record], self.options, interrupted=True
        )
        self.assertEqual(summary["exit_code"], 130)
        text = (self.root / "report.md").read_text()
        for expected in (
            "Interrupted: yes",
            "Completed tasks: 1 / 2",
            "gdb-001",
            "timeout",
            "line one\\|two<br>next",
            "not_run",
            "Exit code: 130",
        ):
            self.assertIn(expected, text)
        self.assertFalse((self.root / "summary.json").exists())

    def test_interface_validation_accepts_unknowns_without_serializing(self):
        document = {
            "address_width": 64,
            "endianness": "little",
            "register_widths": {"0": 64},
            "memory": {},
            "types": {
                "1": {
                    "id": "signed",
                    "encoding": "DW_ATE_signed",
                    "bit_width": 32,
                    "byte_size": 4,
                }
            },
            "initial_stack": [{"value": -1, "type": 1}],
            "entry_context": {"memory": {}},
            "die_locations": {
                "2": {
                    "bytes": [],
                    "raw_types": {
                        "3": {
                            "id": "opaque",
                            "tag": "DW_TAG_base_type",
                            "encoding": "DW_ATE_numeric_string",
                        }
                    },
                }
            },
        }
        original = deepcopy(document)
        with patch.object(
            self.runner,
            "configuration_ast",
            side_effect=AssertionError("serialization during validation"),
        ):
            self.assertIsNone(self.runner.validate_interface(document))
        self.assertEqual(document, original)
        context, stack = self.runner.configuration_ast(document)
        self.assertIsInstance(context, dict)
        self.assertIsInstance(stack, dict)

    def test_invalid_interface_and_nested_context_remain_rejected(self):
        base = {"address_width": 64, "endianness": "little"}
        invalid = [
            {"memory": {"0": 256}},
            {"memory": {str(1 << 64): 0}},
            {"registers": {"0": 1 << 64}},
            {"register_widths": {"0": 0}},
            {"framebase": -1},
            {"endianness": "invalid"},
            {"initial_stack": [{"value": 0, "type": 9}]},
            {
                "types": {
                    "1": {
                        "id": "x",
                        "encoding": "DW_ATE_signed",
                        "bit_width": 65,
                        "byte_size": 8,
                    }
                }
            },
            {
                "types": {
                    "1": {
                        "id": "x",
                        "encoding": "DW_ATE_float",
                        "bit_width": 16,
                        "byte_size": 2,
                    }
                }
            },
            {
                "raw_types": {
                    "1": {"id": "x", "tag": "DW_TAG_base_type", "byte_size": True}
                }
            },
            {"memory_requests": [{"address": 0, "size": 2, "bytes": [1]}]},
            {"memory_requests": [{"address": 0, "size": 1, "bytes": [1]}] * 2},
            {"entry_context": {"memory": {"0": 256}}},
            {"address_spaces": {"0": {"0": 256}}},
            {"die_locations": {"1": {"bytes": [256]}}},
        ]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.runner.validate_interface({**base, **change})

    def test_type_identity_conflicts_and_register_unknowns_remain_distinct(self):
        typ = {
            "id": "shared",
            "encoding": "DW_ATE_signed",
            "bit_width": 32,
            "byte_size": 4,
        }
        document = {
            "address_width": 64,
            "endianness": "little",
            "types": {"1": typ, "2": dict(typ)},
            "register_widths": {"0": 64},
        }
        self.runner.validate_interface(document)
        context, _ = self.runner.configuration_ast(document)
        self.assertIn("unavailableRegister", json.dumps(context))
        document["types"]["2"]["encoding"] = "DW_ATE_unsigned"
        with self.assertRaisesRegex(ValueError, "conflicting metadata"):
            self.runner.validate_interface(document)

    def test_process_execution_preserves_separate_outputs_and_receipt(self):
        processes = importlib.import_module("processes")

        class Child:
            returncode = 0

            def communicate(self, **kwargs):
                return "output", "diagnostic"

        with patch.object(processes.subprocess, "Popen", return_value=Child()) as start:
            result = processes.execute(["fake-runner"], self.root / "call", 3)
        self.assertEqual((result.stdout, result.stderr), ("output", "diagnostic"))
        self.assertEqual((self.root / "call/stdout.txt").read_text(), "output")
        self.assertEqual((self.root / "call/stderr.txt").read_text(), "diagnostic")
        receipt = json.loads((self.root / "call/exit.json").read_text())
        self.assertEqual(receipt, {"returncode": 0})
        start.assert_called_once()

    def test_process_timeout_and_interrupt_preserve_partial_evidence(self):
        processes = importlib.import_module("processes")
        for name, error, expected in [
            (
                "timeout",
                processes.subprocess.TimeoutExpired("fake", 1),
                processes.ToolFailure,
            ),
            ("interrupt", KeyboardInterrupt(), KeyboardInterrupt),
        ]:
            from unittest.mock import Mock

            child = Mock()
            child.communicate.side_effect = [error, ("partial", "diagnostic")]
            with (
                patch.object(processes.subprocess, "Popen", return_value=child),
                patch.object(processes, "kill_tree") as kill,
            ):
                with self.assertRaises(expected):
                    processes.execute(["fake-runner"], self.root / name, 1)
            kill.assert_called_once_with(child)
            receipt = json.loads((self.root / name / "exit.json").read_text())
            self.assertTrue(receipt["timeout" if name == "timeout" else "interrupted"])
            self.assertEqual((self.root / name / "stdout.txt").read_text(), "partial")
            self.assertFalse(processes._children)

    def test_process_launch_error_is_retained(self):
        processes = importlib.import_module("processes")
        with patch.object(
            processes.subprocess,
            "Popen",
            side_effect=FileNotFoundError("missing runner"),
        ):
            with self.assertRaises(processes.ToolFailure):
                processes.execute(["fake-runner"], self.root / "missing", 1)
        self.assertIn(
            "missing runner",
            json.loads((self.root / "missing/exit.json").read_text())["launch_error"],
        )

    def test_interface_identity_helpers_survive_runtime_pruning(self):
        token = {"node": "KToken", "sort": {"name": "Int"}, "token": "1"}
        self.assertEqual(self.runner.canonical_term(token), ("Int", "1"))
        wrapped = {
            "node": "KApply",
            "label": {"name": "preparedDIE"},
            "args": [token, {}],
        }
        self.assertEqual(self.runner.source_context(wrapped), token)


if __name__ == "__main__":
    unittest.main()
