"""Result publication uses case records and command receipts, never summaries."""

from contextlib import ExitStack, redirect_stderr
from copy import deepcopy
import csv
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import record_expression_results as exporter


class ResultExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="kframework-result-export-", dir="/tmp/scratch"
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.settings = {"jobs": 4, "timeout": 120, "depth": 10000}
        self.cases = [
            {
                "id": tool + "-001",
                "tool": tool,
                "group": "core",
                "expression": {"bytecode": "31"},
            }
            for tool in ("lldb", "gdb")
        ]
        self.records = []
        for case in self.cases:
            record = {
                "id": case["id"],
                "tool": case["tool"],
                "group": "core",
                "execution": "normal_completion",
                "verdict": "inconsistent" if case["tool"] == "lldb" else "consistent",
                "execution_faults": [],
                "fully_checked": True,
                "diagnostic": "",
                "checks": [],
            }
            self.records.append(record)
            base = self.run / case["id"]
            (base / "k").mkdir(parents=True)
            (base / "outcome.json").write_text(json.dumps(record))
            (base / "k/stdout.txt").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "configuration": {"term": {}},
                        "result": {"kind": "memory", "address": 1},
                    }
                )
            )
            (base / "k/exit.json").write_text('{"returncode":0}')
            (base / "k/stderr.txt").write_text("10 steps")
            self.command(base / "k/command.json")

    def command(self, file, depth=10000, timeout=120):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            json.dumps({"argv": ["runner", "--depth", str(depth)], "timeout": timeout})
        )

    def export(self):
        original = {
            "notes.json": b'{"original-lldb":"Expected failure; no change."}',
            "differences.csv": b"id,analysis\noriginal-lldb,Reviewed difference.\n",
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    exporter,
                    "export_cases",
                    return_value=(
                        {"cases": self.cases},
                        {"original-lldb": "lldb-001"},
                        {},
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    exporter, "export_original_results", return_value=(original, {})
                )
            )
            stack.enter_context(
                patch.object(
                    exporter.dwarf,
                    "root_inputs",
                    return_value=({"args": [None, None, None, [49]]}, None, None),
                )
            )
            stack.enter_context(
                patch.object(
                    exporter.dwarf, "decode_bytes", side_effect=lambda node: list(node)
                )
            )
            stack.enter_context(
                patch.object(
                    exporter, "instructions", return_value=([{"op": "DW_OP_lit1"}], [])
                )
            )
            return exporter.export(self.root, self.run, **self.settings)

    def test_four_files_recomputed_without_reading_markdown_or_summary(self):
        original_open = Path.open

        def guarded(path, *args, **kwargs):
            if path.name in {"summary.json", "report.md", "README.md"}:
                raise AssertionError("a summary or Markdown report was read")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            files = self.export()
        self.assertEqual(set(files), exporter.RESULT_FILES)
        report = files["report.md"].decode()
        self.assertIn("| LLDB | 1 | 0 | 1 | 0 | 0 | 0.00% |", report)
        self.assertIn("| GDB | 1 | 1 | 0 | 0 | 0 | 100.00% |", report)
        self.assertIn("Completed tasks: 2 / 2", report)
        self.assertIn("Exit code: 0", report)
        for name in ("expressions.csv", "differences.csv"):
            rows = list(csv.DictReader(io.StringIO(files[name].decode())))
            row = next(row for row in rows if row["id"] == "lldb-001")
            self.assertEqual(row["manual_remarks"], "Expected failure; no change.")
        evidence = [
            json.loads(line)
            for line in gzip.decompress(files["evidence.jsonl.gz"]).splitlines()
        ]
        self.assertEqual(len(evidence), 6)

    def test_timeout_and_rewrite_mismatches_are_rejected(self):
        command = self.run / "lldb-001/k/command.json"
        for depth, timeout, message in (
            (9999, 120, "rewrite budget differs"),
            (10000, 121, "timeout differs"),
        ):
            self.command(command, depth=depth, timeout=timeout)
            with (
                self.subTest(depth=depth, timeout=timeout),
                self.assertRaisesRegex(ValueError, message),
            ):
                self.export()

    def test_stability_probe_uses_the_larger_budget(self):
        probe = self.run / "lldb-001/stability-probe/k/command.json"
        self.command(probe, depth=20000)
        checked = exporter.check_invocation_settings(
            self.run, self.settings, {case["id"] for case in self.cases}
        )
        self.assertEqual(checked, {"commands": 3, "timeouts": 3, "budgets": 3})
        self.command(probe, depth=10000)
        with self.assertRaisesRegex(ValueError, "rewrite budget differs"):
            exporter.check_invocation_settings(
                self.run, self.settings, {case["id"] for case in self.cases}
            )

    def test_missing_or_duplicate_case_records_are_rejected(self):
        cases = {case["id"]: case for case in self.cases}
        for records in (self.records[:1], self.records + self.records[:1]):
            with (
                self.subTest(records=len(records)),
                self.assertRaisesRegex(ValueError, "incomplete or duplicate"),
            ):
                exporter.summarize_records(records, cases, self.settings)
        (self.run / "lldb-001/outcome.json").unlink()
        with self.assertRaisesRegex(
            ValueError, "incomplete expression-case experiment"
        ):
            self.export()

    def test_core_auxiliary_fault_and_interruption_states_remain_distinct(self):
        records = deepcopy(self.records)
        cases = {case["id"]: dict(case) for case in self.cases}
        cases["lldb-001"]["group"] = "auxiliary"
        records[0].update(group="auxiliary", verdict="uncheckable")
        records[1].update(
            verdict="undetermined",
            execution_faults=[{"call": "k", "kind": "budget_exhausted"}],
        )
        summary = exporter.summarize_records(records, cases, self.settings)
        self.assertEqual(summary["total"]["cases"], 1)
        self.assertEqual(summary["sources"]["lldb"]["auxiliary"]["uncheckable"], 1)
        self.assertEqual(summary["exit_code"], 1)
        summary = exporter.summarize_records(
            records,
            cases,
            self.settings,
            interrupted=True,
            diagnostic="Interrupted after final task.",
        )
        self.assertEqual(summary["exit_code"], 130)
        self.assertTrue(summary["interrupted"])
        self.assertEqual(
            summary["execution_faults"][-1]["diagnostic"],
            "Interrupted after final task.",
        )

    def test_settings_and_source_identity_are_validated(self):
        cases = {case["id"]: case for case in self.cases}
        for settings in (
            {"timeout": 120, "depth": 10000},
            {**self.settings, "jobs": 17},
            {**self.settings, "depth": 0},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                exporter.summarize_records(self.records, cases, settings)
        changed = deepcopy(self.records)
        changed[0]["group"] = "auxiliary"
        with self.assertRaisesRegex(ValueError, "source or group differs"):
            exporter.summarize_records(changed, cases, self.settings)

    def test_export_cli_requires_all_run_settings(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            exporter.main(
                ["--run", str(self.run), "--output", str(self.root / "output")]
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse((self.root / "output").exists())

    def test_invocation_without_a_selected_root_is_rejected(self):
        self.command(self.run / "unexpected/k/command.json")
        with self.assertRaisesRegex(ValueError, "without a selected case"):
            exporter.check_invocation_settings(
                self.run, self.settings, {case["id"] for case in self.cases}
            )
