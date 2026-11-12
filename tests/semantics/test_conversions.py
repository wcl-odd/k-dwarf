"""Integer conversion preserves representable values and truncates narrow targets."""
from pathlib import Path
import json
import subprocess
import sys

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty


TYPES = {"1": ty("s8", "DW_ATE_signed", 8, 1),
         "2": ty("u8", "DW_ATE_unsigned", 8, 1),
         "3": ty("s16", "DW_ATE_signed", 16, 2),
         "4": ty("other-s8", "DW_ATE_signed", 8, 2),
         "5": ty("s3", "DW_ATE_signed", 3, 1),
         "6": ty("u3", "DW_ATE_unsigned", 3, 2),
         "7": ty("bool8", "DW_ATE_boolean", 8, 1),
         "8": ty("s64", "DW_ATE_signed", 64, 8)}


def value(number, reference):
    return {"value": number, "type": {"id": TYPES[str(reference)]["id"]}}


class ConversionTests(DwarfTestCase):
    def raw(self, source, ctx, **kwargs):
        path = Path(self.temp.name) / "expression.hex"
        path.write_text(source)
        return dwarf.evaluate(path, ctx, self.definition, input_format="hex", **kwargs)

    def test_convert_numeric_preservation(self):
        cases = [(127, "g", 1, value(127, 1)), (255, "g", 2, value(255, 2)),
                 (-1, "g", 0, g(2**64-1)), (-128, 1, 3, value(-128, 3)),
                 (255, 2, 3, value(255, 3)), (127, 3, 1, value(127, 1)),
                 (42, 1, 0, g(42)), (-1, 5, 3, value(-1, 3))]
        for number, source, target, expected in cases:
            with self.subTest(case=(number, source, target)):
                ctx = snapshot(types=TYPES, initial_stack=[g(17), {"value": number, "type": source}])
                result = self.complete(f"DW_OP_convert {target}, DW_OP_stack_value", [g(17), expected], ctx)
                self.assertEqual(result["result"], {"kind": "value", **expected})

    def test_integer_narrowing_and_generic_source_interpretation(self):
        for number,source,target,expected in [(128,"g",1,value(-128,1)),(256,"g",2,value(0,2)),
                (-1,1,2,value(255,2)),(-1,1,0,g(2**64-1)),(128,3,1,value(-128,1)),
                (2**64-1,"g",3,value(-1,3))]:
            ctx=snapshot(types=TYPES,initial_stack=[g(41),{"value":number,"type":source}])
            self.complete(f"DW_OP_convert {target}, DW_OP_stack_value",[g(41),expected],ctx)

    def test_convert_failures_keep_entire_state(self):
        for number, source, target in [(1, "g", 99),
                                       (1, "g", -1), (1, "g", 7), (2, 7, 2)]:
            with self.subTest(case=(number, source, target)):
                stack = [g(41), {"value": number, "type": source}]
                ctx = snapshot(types=TYPES, initial_stack=stack)
                prefix = "DW_OP_lit1, DW_OP_drop"
                before = self.execute(prefix + f", DW_OP_convert {target}", ctx, depth=2)
                stopped = self.incomplete(prefix + f", DW_OP_convert {target}", ctx, position=2)
                self.assert_preserved(before, stopped)
                self.assertEqual(stopped["stack"], [g(41), g(number) if source == "g" else value(number, source)])
        self.incomplete("DW_OP_convert 0")

    def test_reinterpret_bits_identity_and_storage_size(self):
        cases = [(-1, 1, 2, value(255, 2)), (255, 2, 1, value(-1, 1)),
                 (-1, 1, 4, value(-1, 4)), (-1, 5, 6, value(7, 6)),
                 (-1, 8, 0, g(-1)), (-1, "g", 8, value(-1, 8)),
                 (2, 2, 7, value(2, 7)), (255, 7, 1, value(-1, 1))]
        for number, source, target, expected in cases:
            with self.subTest(case=(number, source, target)):
                self.complete(f"DW_OP_reinterpret {target}", [expected],
                              snapshot(types=TYPES, initial_stack=[{"value": number, "type": source}]))
        for source, target in [(1, 3), (1, 0), (1, 99), (1, -1)]:
            ctx = snapshot(types=TYPES, initial_stack=[{"value": -1, "type": source}])
            result = self.incomplete(f"DW_OP_reinterpret {target}", ctx)
            self.assertEqual(result["stack"], [value(-1, source)])
        self.incomplete("DW_OP_reinterpret 0")

    def test_both_opcodes_decode_and_leb_boundaries(self):
        for text, raw in [("DW_OP_convert 0x2", "a8 82 00"),
                          ("DW_OP_reinterpret 0X8", "a9 88 00")]:
            ctx = snapshot(types=TYPES, initial_stack=[g(127)])
            a, b = self.execute(text, ctx), self.raw(raw, ctx)
            self.assertEqual(a["stack"], b["stack"])
            self.assertEqual(b["status"], "completed")
            self.assertEqual(b["position"], 3)
        large = 2**70
        ctx = snapshot(types={str(large): ty("wide-ref", "DW_ATE_unsigned", 8, 1)}, initial_stack=[g(7)])
        result = self.raw("a8 " + "80 " * 10 + "01", ctx)
        self.assertEqual(result["stack"], [{"value": 7, "type": {"id": "wide-ref"}}])
        for raw in ("a8", "a8 80", "a9", "a9 80", "a8 ff ff"):
            result = self.raw("31 " + raw, snapshot())
            self.assertEqual((result["status"], result["position"], result["stack"]),
                             ("incomplete", 1, [g(1)]))

    def test_budget_positions_and_fixed_inputs(self):
        ctx = snapshot(types=TYPES)
        states = [self.raw("31 a8 01 9f", ctx, depth=depth) for depth in (0, 1, 2, 3)]
        self.assertEqual([r["position"] for r in states], [0, 1, 3, 4])
        self.assertEqual([r["status"] for r in states], ["incomplete"] * 3 + ["completed"])
        self.assertEqual(self.fixed_inputs(states[1]), self.fixed_inputs(states[3]))
        for result in states[1:]:
            self.assertEqual(dwarf.find_cell(result["configuration"]["term"], "fragments"),
                             dwarf.find_cell(states[1]["configuration"]["term"], "fragments"))

    def test_typed_reads_then_conversion_and_composition(self):
        for endian, memory in [("little", {"0": 254, "1": 255}),
                               ("big", {"0": 255, "1": 254})]:
            ctx = snapshot(types=TYPES, memory=memory, endianness=endian)
            result = self.complete("DW_OP_addr 0, DW_OP_deref_type 2 3, DW_OP_convert 8, DW_OP_stack_value",
                                   [value(-2, 8)], ctx)
            self.assertEqual(result["result"]["value"], -2)
        ctx = snapshot(types=TYPES, architecture="x86_64")
        result = self.execute("DW_OP_lit7, DW_OP_convert 2, DW_OP_lit1, DW_OP_convert 2, "
                              "DW_OP_plus, DW_OP_stack_value, DW_OP_piece 1", ctx)
        self.assertEqual(result["result"]["bits"], "00001000")
        self.assertEqual(result["stack"], [])

    def test_nonzero_offsets_and_cli_exit_codes(self):
        path = Path(self.temp.name) / "offset.dwarf"
        path.write_text("-0x4: DW_OP_lit1, -2: DW_OP_convert 0, 0")
        result = dwarf.evaluate(path, snapshot(), self.definition)
        self.assertEqual((result["status"], result["position"], result["stack"]), ("completed", 0, [g(1)]))
        context_file = Path(self.temp.name) / "context.json"
        context_file.write_text(json.dumps(snapshot()))
        for text, code in [("0: DW_OP_convert 0, 1", 1),
                           ("0: DW_OP_lit1, 1: DW_OP_convert 0, 2", 0),
                           ("0: DW_OP_convert, 1", 2)]:
            path.write_text(text)
            process = subprocess.run([sys.executable, ROOT / "run.py", path,
                        "--definition", self.definition, "--context", context_file], capture_output=True, text=True)
            self.assertEqual(process.returncode, code, process.stderr)

    def test_generic_unsigned_widening_and_representatives(self):
        types = {**TYPES, "9": ty("u16", "DW_ATE_unsigned", 16, 2)}
        for number in (0, 127, 128, 255, -1, -128):
            expected_number = {0: 0, 127: 127, 128: 128, 255: 255, -1: 255, -128: 128}[number]
            for reference, identity in ((3, "s16"), (9, "u16")):
                with self.subTest(number=number, target=identity):
                    context = snapshot(address_width=8, types=types, initial_stack=[g(17), g(number)])
                    expected = {"value": expected_number, "type": {"id": identity}}
                    text = self.complete(f"DW_OP_convert {reference}, DW_OP_stack_value", [g(17), expected], context)
                    raw = self.raw(f"a8 {reference:02x} 9f", context)
                    self.assertEqual(raw["result"], {"kind": "value", **expected})
                    self.assertEqual(raw["stack"], text["stack"])
                    self.assertEqual((raw["status"], raw["position"], raw["end"]), ("completed", 3, 3))

    def test_generic_literal_conversion_uses_address_width(self):
        # const1s first creates a generic bit pattern; it is not a signed8 type.
        context = snapshot(address_width=32, types=TYPES, initial_stack=[g(17)])
        expected = {"value": 4294967295, "type": {"id": "s64"}}
        text = self.complete("DW_OP_const1s -1, DW_OP_convert 8, DW_OP_stack_value", [g(17), expected], context)
        raw = self.raw("09 ff a8 08 9f", context)
        self.assertEqual(raw["result"], {"kind": "value", **expected})
        self.assertEqual(raw["stack"], text["stack"])
        # Explicit signed8 still sign-extends, even when the target is wider.
        self.complete("DW_OP_const_type 1 [0xff], DW_OP_convert 8, DW_OP_stack_value",
                      [g(17), {"value": -1, "type": {"id": "s64"}}], context)
        types = {"1": ty("s128", "DW_ATE_signed", 128, 16)}
        for number in (-1, 18446744073709551615):
            with self.subTest(address_width=64, representative=number):
                context = snapshot(types=types, initial_stack=[g(17), g(number)])
                expected = {"value": 18446744073709551615, "type": {"id": "s128"}}
                self.complete("DW_OP_convert 1, DW_OP_stack_value", [g(17), expected], context)

    def test_generic_unsigned_convert_and_budget(self):
        context = snapshot(address_width=8, types=TYPES, initial_stack=[g(17), g(-1)])
        expected = {"value": 255, "type": {"id": "s16"}}
        for name, byte in (("DW_OP_convert", "a8"),):
            with self.subTest(name=name):
                self.complete(f"{name} 3, DW_OP_stack_value", [g(17), expected], context)
                before = self.raw(f"{byte} 03 9f", context, depth=1)
                after = self.raw(f"{byte} 03 9f", context, depth=2)
                self.assertEqual((before["status"], before["position"], before["stack"]),
                                 ("incomplete", 2, [g(17), expected]))
                self.assertEqual((after["status"], after["position"], after["result"]),
                                 ("completed", 3, {"kind": "value", **expected}))
                self.assertEqual(self.fixed_inputs(before), self.fixed_inputs(after))
                self.assertEqual(dwarf.find_cell(before["configuration"]["term"], "fragments"),
                                 dwarf.find_cell(after["configuration"]["term"], "fragments"))
