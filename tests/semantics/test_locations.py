"""Simple location results; stack_value ends the description without a stack step."""

import json
from pathlib import Path
import subprocess
import sys

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty, annotated


class LocationTests(DwarfTestCase):
    def test_memory_results(self):
        # Lower entries are retained, and an address needs no corresponding memory.
        result = self.complete("DW_OP_lit1, DW_OP_constu 4096", [g(1), g(4096)])
        self.assertEqual(result["result"], {"kind": "memory", "address": 4096})
        result = self.complete("DW_OP_lit7, DW_OP_neg", [g(-7)], snapshot(address_width=8))
        self.assertEqual(result["result"], {"kind": "memory", "address": -7})
        # Any supported top type supplies its numeric address, without coercion.
        for record, number in [(ty("s3", bits=3, size=1), -3),
                               (ty("u3", "DW_ATE_unsigned", 3, 1), 7),
                               (ty("bool8", "DW_ATE_boolean", 8, 1), 129)]:
            with self.subTest(record=record):
                ctx = snapshot(types={"1": record}, initial_stack=[g(42), {"value": number, "type": 1}])
                values = [g(42), {"value": number, "type": {"id": record["id"]}}]
                result = self.complete("DW_OP_dup, DW_OP_drop", values, ctx)
                self.assertEqual(result["result"], {"kind": "memory", "address": number})

    def test_direct_value_results(self):
        source = "DW_OP_lit1, DW_OP_constu 4096"
        memory = self.complete(source, [g(1), g(4096)])
        value = self.complete(source + ", DW_OP_stack_value", memory["stack"])
        self.assertEqual(value["result"], {"kind": "value", **g(4096)})
        self.assertEqual(self.fixed_inputs(memory)[1], self.fixed_inputs(value)[1])
        result = self.complete("DW_OP_lit7, DW_OP_neg, DW_OP_stack_value", [g(-7)])
        self.assertEqual(result["result"], {"kind": "value", **g(-7)})
        # Identity and negative signed representatives survive the result layer.
        for identity in ("A", "B", "g"):
            with self.subTest(identity=identity):
                ctx = snapshot(types={"1": ty(identity)},
                               initial_stack=[g(3), {"value": -2, "type": 1}])
                values = [g(3), {"value": -2, "type": {"id": identity}}]
                result = self.complete("DW_OP_stack_value", values, ctx)
                self.assertEqual(result["result"], {"kind": "value", **values[-1]})
        # Typed memory reads feed the same complete Value into the result.
        ctx = snapshot(types={"1": ty("s3", bits=3, size=1)}, memory={"0": 255})
        values = [{"value": -1, "type": {"id": "s3"}}]
        result = self.complete("DW_OP_addr 0, DW_OP_deref_type 1 1, DW_OP_stack_value", values, ctx)
        self.assertEqual(result["result"], {"kind": "value", **values[0]})

    def test_empty_descriptions_and_empty_final_stack(self):
        for values in ([], [g(1), g(-2)]):
            with self.subTest(values=values):
                result = self.complete("", values, snapshot(initial_stack=values))
                self.assertEqual(result["result"], {"kind": "unavailable"})
        for source, ctx, position in [
            ("DW_OP_lit1, DW_OP_drop", snapshot(), 2),
            ("DW_OP_drop", snapshot(initial_stack=[g(1)]), 1),
        ]:
            with self.subTest(source=source):
                result = self.incomplete(source, ctx, position)
                self.assertEqual(result["stack"], [])
                self.assertEqual(result["position"], result["end"])
                # Exhausting the code does not yield unavailable or memory(0).
                before = self.execute(source, ctx, depth=position)
                self.assert_preserved(before, result)

    def test_stack_value_failures_preserve_state(self):
        for source, values, position, expected in [
            ("DW_OP_stack_value", [], 0, []),
            ("DW_OP_lit1, DW_OP_drop, DW_OP_stack_value", [], 2, []),
            ("DW_OP_stack_value, DW_OP_lit2", [g(7)], 0, [g(7)]),
            ("DW_OP_lit1, DW_OP_stack_value, DW_OP_lit2", [], 1, [g(1)]),
            ("DW_OP_lit1, DW_OP_stack_value, DW_OP_stack_value", [], 1, [g(1)]),
        ]:
            with self.subTest(source=source):
                ctx = snapshot(initial_stack=values, registers={"1": 3}, framebase=7, memory={"0": 9})
                stopped = self.incomplete(source, ctx, position)
                self.assertEqual(stopped["stack"], expected)
                before = self.execute(source, ctx, depth=position)
                self.assertEqual(self.fixed_inputs(before), self.fixed_inputs(stopped))
                if position:
                    self.assert_preserved(before, stopped)

    def test_location_depth_limits(self):
        source = "DW_OP_lit1, DW_OP_stack_value"
        for depth in (0, 1, 2, 3):
            with self.subTest(depth=depth):
                result = self.execute(source, depth=depth)
                self.assertEqual(result["position"], min(depth, 2))
                self.assertEqual(result["stack"], [] if depth == 0 else [g(1)])
                self.assertEqual(result["status"], "incomplete" if depth < 2 else "completed")
                self.assertEqual(result["result"], None if depth < 2 else {"kind": "value", **g(1)})
        for source in ("", "DW_OP_lit1"):
            result = self.execute(source, snapshot(initial_stack=[g(-1)]), depth=0)
            self.assertEqual(result["status"], "incomplete")
            self.assertIsNone(result["result"])
            self.assertEqual(result["stack"], [g(-1)])
        result = self.execute("", depth=1)
        self.assertEqual(result["result"], {"kind": "unavailable"})
        ordinary = "DW_OP_lit1, DW_OP_lit2"
        self.assertIsNone(self.execute(ordinary, depth=2)["result"])
        self.assertEqual(self.execute(ordinary, depth=3)["result"], {"kind": "memory", "address": 2})

    def test_location_cli(self):
        path = Path(self.temp.name) / "cli-location.dwarf"
        context = Path(self.temp.name) / "context.json"
        context.write_text(json.dumps(snapshot()))
        for source, code, expected in [
            ("DW_OP_constu 42", 0, {"kind": "memory", "address": 42}),
            ("DW_OP_constu 42, DW_OP_stack_value", 0, {"kind": "value", **g(42)}),
            ("", 0, {"kind": "unavailable"}),
            ("DW_OP_lit1, DW_OP_drop", 1, None),
            ("DW_OP_lit1, DW_OP_stack_value, DW_OP_lit2", 1, None),
        ]:
            with self.subTest(source=source):
                path.write_text(annotated(source))
                process = subprocess.run([sys.executable, str(ROOT / "run.py"), str(path),
                                          "--context", str(context), "--definition", str(self.definition)],
                                         capture_output=True, text=True)
                self.assertEqual(process.returncode, code, process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(result["result"], expected)
                self.assertEqual(result["status"], "completed" if code == 0 else "incomplete")
                self.assertIn("configuration", result)
