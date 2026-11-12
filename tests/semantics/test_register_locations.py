"""DWARF 5 §2.6.1.1.3: reg names a location, never a stack value."""
import json
from pathlib import Path
import re
import subprocess
import sys

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty


class RegisterLocationTests(DwarfTestCase):
    def input(self, source, mode="text", ctx=None, **kwargs):
        path = Path(self.temp.name) / ("register." + mode)
        path.write_text(source)
        return dwarf.evaluate(path, snapshot() if ctx is None else ctx,
                              self.definition, input_format=mode, **kwargs)

    def success(self, source, number, mode="text", ctx=None, expected=None, **kwargs):
        result = self.input(source, mode, ctx, **kwargs)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], {"kind": "register", "register": number})
        self.assertEqual(result["stack"], [] if expected is None else expected)
        self.assertEqual(result["position"], result["end"])
        return result

    def test_all_33_names_and_name_inventory(self):
        # Register descriptions cannot be appended to the 111-name stack program.
        # Check the exact partition, then execute each new name in both entries.
        syntax = (ROOT / "semantics/frontend/syntax.k").read_text()
        normalization = (ROOT / "semantics/frontend/normalization.k").read_text()
        decoding = (ROOT / "semantics/frontend/decoding.k").read_text()
        names = set(re.findall(r'"(DW_OP_\w+)"', syntax))
        new = {f"DW_OP_reg{n}" for n in range(32)} | {"DW_OP_regx"}
        self.assertEqual(len(names), 164)
        self.assertEqual(len(names - new), 131)
        self.assertEqual(names, set(re.findall(r'normalize\((DW_OP_\w+)', normalization)))
        # Typed blocks decode directly into shared operations;
        # their two-entry execution is checked by test_typed_values.py.
        direct = {"DW_OP_const_type", "DW_OP_regval_type", "DW_OP_call2", "DW_OP_call4",
                  "DW_OP_call_ref", "DW_OP_entry_value", "DW_OP_form_tls_address",
                  "DW_OP_xderef", "DW_OP_xderef_size", "DW_OP_xderef_type",
                  "DW_OP_implicit_pointer"}
        self.assertEqual(names - direct, set(re.findall(r'normalize\((DW_OP_\w+)', decoding)))
        for n in range(32):
            for mode, source in [("hex", f"{0x50+n:02x}"),
                                 ("text", f"0: DW_OP_reg{n}, 1")]:
                with self.subTest(n=n, mode=mode):
                    result = self.success(source, n, mode)
                    self.assertEqual(result["end"], 1)
        for mode, source in [("hex", "90 40"), ("text", "0: DW_OP_regx 64, 2")]:
            self.success(source, 64, mode)

    def test_regx_arbitrary_precision_nonminimal_and_endianness(self):
        # Literal fixture: 80-bit continuation at bit 70 represents 2^70.
        fixtures = [("90 00", 0), ("90 1f", 31), ("90 20", 32),
                    ("90 80 01", 128), ("90 80 00", 0),
                    ("90 ff ff ff ff ff ff ff ff ff 7f", (1 << 70)-1),
                    ("90 80 80 80 80 80 80 80 80 80 80 01", 1 << 70)]
        for raw, number in fixtures:
            with self.subTest(raw=raw):
                result = self.success(raw, number, "hex")
                self.assertEqual(result["end"], len(raw.split()))
        for endian in ("little", "big"):
            self.success("90 80 01", 128, "hex", snapshot(address_width=32, endianness=endian))
        for number in (0, 32, (1 << 70)):
            self.success(f"0: DW_OP_regx 0X{number:X}, 9", number)

    def test_context_and_arbitrary_initial_stack_preserved(self):
        entries = [g(9), {"value": -2, "type": 1}, {"value": 7, "type": 2}]
        ctx = snapshot(types={"1": ty("signed"), "2": ty("unsigned", "DW_ATE_unsigned", 3, 1)},
                       registers={"0": -1, "3": 42}, memory={"10": 255}, framebase=123,
                       initial_stack=entries)
        expected = [g(9), {"value": -2, "type": {"id": "signed"}},
                    {"value": 7, "type": {"id": "unsigned"}}]
        for mode, source in [("hex", "53"), ("text", "-5: DW_OP_reg3, 0")]:
            before = self.input(source, mode, ctx, depth=0)
            result = self.success(source, 3, mode, ctx, expected=expected)
            self.assert_initialized_inputs_preserved(before, result, ctx)
        # Neither a register mapping nor any specific register contents are required.
        for width, regs in [(8, {}), (32, {"0": 1}), (64, {"0": 999})]:
            self.success("0: DW_OP_regx 999, 1", 999, ctx=snapshot(address_width=width, registers=regs))

    def test_nonstandalone_descriptions_keep_preoperation_state(self):
        fixtures = [
            ("50 96", "0: DW_OP_reg0, 1: DW_OP_nop, 2", 0, 0, [g(7)]),
            ("50 9f", "0: DW_OP_reg0, 1: DW_OP_stack_value, 2", 0, 0, [g(7)]),
            ("50 51", "0: DW_OP_reg0, 1: DW_OP_reg1, 2", 0, 0, [g(7)]),
            ("31 50", "0: DW_OP_lit1, 1: DW_OP_reg0, 2", 1, 1, [g(7), g(1)]),
            ("96 90 00", "0: DW_OP_nop, 1: DW_OP_regx 0, 3", 1, 1, [g(7)]),
            ("2f 00 00 50", "0: DW_OP_skip 0, 3: DW_OP_reg0, 4", 1, 3, [g(7)]),
        ]
        ctx = snapshot(initial_stack=[g(7)], registers={"0": 99})
        for raw, text, depth, position, values in fixtures:
            for mode, source in [("hex", raw), ("text", text)]:
                with self.subTest(source=source):
                    before = self.input(source, mode, ctx, depth=depth)
                    stopped = self.input(source, mode, ctx)
                    self.assertEqual((stopped["status"], stopped["position"], stopped["stack"]),
                                     ("incomplete", position, values))
                    self.assertIsNone(stopped["result"])
                    if depth or dwarf.label(before["configuration"]["term"]) != "initGeneratedTopCell":
                        self.assert_preserved(before, stopped)
                    self.assert_initialized_inputs_preserved(before, stopped, ctx)

    def test_failed_parameters_and_truncated_bytes_preserve_state(self):
        for mode, source, position in [
            ("text", "-5: DW_OP_regx -0x1, 0", -5),
            ("hex", "90", 0), ("hex", "90 80", 0), ("hex", "90 ff ff", 0),
            ("hex", "37 90 80", 1),
        ]:
            with self.subTest(source=source):
                ctx = snapshot(initial_stack=[g(8)])
                stopped = self.input(source, mode, ctx)
                self.assertEqual((stopped["status"], stopped["position"]), ("incomplete", position))
                self.assertEqual(stopped["stack"], [g(8), g(7)] if position == 1 else [g(8)])
                self.assertIsNone(stopped["result"])
                before = self.input(source, mode, ctx, depth=1 if position == 1 else 0)
                self.assert_initialized_inputs_preserved(before, stopped, ctx)
                if position == 1:
                    self.assert_preserved(before, stopped)

    def test_declared_offsets_and_one_rewrite_completion(self):
        for source, mode, start, end in [("50", "hex", 0, 1),
                                         ("0x10: DW_OP_reg0, 0x20", "text", 16, 32),
                                         ("-3: DW_OP_reg0, 0", "text", -3, 0)]:
            for depth in (0, 1):
                with self.subTest(source=source, depth=depth):
                    result = self.input(source, mode, snapshot(initial_stack=[g(3)]), depth=depth)
                    self.assertEqual(result["stack"], [g(3)])
                    if depth:
                        self.assertEqual((result["status"], result["position"], result["end"]), ("completed", end, end))
                        self.assertEqual(result["result"], {"kind": "register", "register": 0})
                    else:
                        self.assertEqual(result["status"], "incomplete")
                        self.assertIsNone(result["result"])
                        initial = dwarf.label(result["configuration"]["term"]) == "initGeneratedTopCell"
                        self.assertEqual((result["position"], result["end"]), (0, 0) if initial else (start, end))

    def test_register_cli(self):
        context = Path(self.temp.name) / "context.json"
        context.write_text(json.dumps(snapshot()))
        path = Path(self.temp.name) / "cli-input"
        for mode, source, code, number in [("text", "0: DW_OP_reg31, 1", 0, 31),
                                           ("hex", "90 80 01", 0, 128),
                                           ("text", "0: DW_OP_regx -1, 2", 1, None),
                                           ("hex", "90 80", 1, None),
                                           ("text", "DW_OP_reg0", 2, None)]:
            with self.subTest(mode=mode, source=source):
                path.write_text(source)
                process = subprocess.run([sys.executable, str(ROOT / "run.py"), str(path),
                    "--format", mode, "--context", str(context), "--definition", str(self.definition)],
                    capture_output=True, text=True)
                self.assertEqual(process.returncode, code, process.stderr)
                if code != 2:
                    self.assertEqual(json.loads(process.stdout)["result"],
                        None if code else {"kind": "register", "register": number})
