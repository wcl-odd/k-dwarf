"""Failed preconditions have no rewrite, including inside nested evaluations."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty


class StuckTests(DwarfTestCase):
    def raw(self, source, ctx, **options):
        path = Path(self.temp.name) / "stuck.hex"
        path.write_text(source)
        return dwarf.evaluate(path, ctx, self.definition, input_format="hex", **options)

    def test_abs_minimum_is_stuck_in_both_inputs(self):
        for width in (8, 32, 64):
            minimum = -(1 << (width - 1))
            for number in (minimum, minimum % (1 << width)):
                ctx = snapshot(address_width=width, initial_stack=[g(7), g(number)])
                for source, execute in (("DW_OP_nop, DW_OP_abs", self.execute),
                                        ("96 19", self.raw)):
                    with self.subTest(width=width, number=number, source=source):
                        before = execute(source, ctx, depth=1)
                        stopped = execute(source, ctx, depth=20)
                        self.assertEqual((stopped["status"], stopped["position"], stopped["stack"]),
                                         ("incomplete", 1, [g(7), g(number)]))
                        self.assertEqual(before["configuration"], stopped["configuration"])
                        self.assertIsNone(stopped["result"])
                        self.assertIsNone(stopped["stop_reason"])
            ctx = snapshot(address_width=width, initial_stack=[g(minimum + 1)])
            result = self.execute("DW_OP_abs, DW_OP_stack_value", ctx)
            self.assertEqual(result["result"], {"kind": "value", **g(-minimum - 1)})

    def test_typed_abs_uses_type_width_not_address_width(self):
        for width in (8, 16, 128):
            minimum = -(1 << (width - 1))
            record = ty(f"s{width}", "DW_ATE_signed", width, width // 8)
            ctx = snapshot(address_width=32, types={"1": record},
                           initial_stack=[g(7), {"value": minimum, "type": 1}])
            for source, execute in (("DW_OP_nop, DW_OP_abs", self.execute),
                                    ("96 19", self.raw)):
                before = execute(source, ctx, depth=1)
                stopped = execute(source, ctx, depth=20)
                self.assertEqual(stopped["stack"], [g(7), {"value": minimum, "type": {"id": f"s{width}"}}])
                self.assertEqual(before["configuration"], stopped["configuration"])
                self.assertEqual(stopped["status"], "incomplete")
                self.assertIsNone(stopped["stop_reason"])

    def test_decode_and_missing_context_preserve_executable_prefix(self):
        for suffix in ("ff", "10 80", "0e 00", "70 00", "06", "9c", "91 00"):
            source = "31 " + suffix
            before = self.raw(source, snapshot(), depth=1)
            stopped = self.raw(source, snapshot(), depth=20)
            self.assertEqual((stopped["status"], stopped["position"], stopped["stack"]),
                             ("incomplete", 1, [g(1)]))
            self.assertEqual(before["configuration"], stopped["configuration"])
            self.assertIsNone(stopped["stop_reason"])

    def test_native_statistics_have_no_failure_step(self):
        if self.definition.name.startswith("haskell"):
            self.skipTest("native rewrite count is exposed only by the LLVM runner")
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            stopped = self.raw("31 13 13", snapshot(), depth=20, statistics=True)
        self.assertIn("[2 steps]", output.getvalue())
        self.assertEqual((stopped["position"], stopped["stack"]), (2, []))

    def test_stuck_cli_exits_one_without_error_constructor(self):
        expression = Path(self.temp.name) / "cli.hex"
        expression.write_text("19")
        context = Path(self.temp.name) / "context.json"
        context.write_text(json.dumps(snapshot(address_width=8, initial_stack=[g(128)])))
        process = subprocess.run([sys.executable, str(ROOT / "run.py"), str(expression),
                                  "--context", str(context), "--definition", str(self.definition),
                                  "--format", "hex"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual((result["status"], result["stack"]), ("incomplete", [g(128)]))
        self.assertIsNone(result["stop_reason"])
        self.assertNotIn("stoppedEvaluation", process.stdout)
