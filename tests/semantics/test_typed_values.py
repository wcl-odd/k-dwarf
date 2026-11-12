"""DWARF 5 2.5.1.1/2: explicit types are independent of address width."""
from pathlib import Path

from test_basic import DwarfTestCase, g, snapshot, ty
import run as dwarf


class TypedValueTests(DwarfTestCase):
    def raw(self, source, ctx, **kwargs):
        path = Path(self.temp.name) / "typed.hex"
        path.write_text(source)
        return dwarf.evaluate(path, ctx, self.definition, input_format="hex", **kwargs)

    def test_constants_both_entries_width_identity_and_byte_order(self):
        for endian, data, expected in [("little", "ff 80", -32513), ("big", "ff 80", -128)]:
            ctx = snapshot(address_width=8, endianness=endian, types={"1": ty("s16", "DW_ATE_signed", 16, 2)})
            value = {"value": expected, "type": {"id": "s16"}}
            for name, opcode in [("DW_OP_const_type", "a4")]:
                text = self.complete(f"{name} 1 [0xff 0x80], DW_OP_stack_value", [value], ctx)
                raw = self.raw(f"{opcode} 81 00 02 {data} 9f", ctx)
                self.assertEqual(raw["result"], text["result"])
                self.assertEqual(raw["position"], 7)
        ctx = snapshot(address_width=32, types={"1": ty("u128", "DW_ATE_unsigned", 128, 16)})
        value = {"value": 2**128-1, "type": {"id": "u128"}}
        self.assertEqual(self.raw("a4 01 10 " + "ff "*16, ctx)["stack"], [value])

    def test_register_values_physical_width_and_missing_values(self):
        types = {"1": ty("s8", "DW_ATE_signed", 8, 1), "2": ty("u128", "DW_ATE_unsigned", 128, 16)}
        ctx = snapshot(address_width=32, types=types, registers={"0":255, "17":2**127+3}, register_widths={"17":128})
        for name, opcode in [("DW_OP_regval_type", "a5")]:
            self.complete(f"{name} 0 1", [{"value":-1,"type":{"id":"s8"}}], ctx)
            expected = {"value":2**127+3,"type":{"id":"u128"}}
            self.complete(f"{name} 17 2", [expected], ctx)
            self.assertEqual(self.raw(f"{opcode} 91 00 82 00",ctx)["stack"],[expected])
            for r,t in [(1,1),(0,2),(0,0),(0,99),(-1,1)]:
                self.incomplete(f"{name} {r} {t}", ctx)
        # Address-producing register operations still use the target address size.
        self.complete("DW_OP_bregx 17 0", [g(3)], ctx)

    def test_invalid_sizes_references_and_truncations_preserve_prefix(self):
        ctx = snapshot(types={"1":ty("u16","DW_ATE_unsigned",16,2)})
        for source in ["a4", "a4 80", "a4 01", "a4 01 02 ff", "a4 01 01 ff", "a4 00 02 ff ff", "a5", "a5 00", "a5 00 80"]:
            result = self.raw("31 " + source,ctx)
            self.assertEqual((result["status"], result["position"], result["stack"]),("incomplete",1,[g(1)]))
        for source in ["DW_OP_const_type 1 []", "DW_OP_const_type 1 [1]", "DW_OP_const_type 0 [1 2]", "DW_OP_const_type -1 [1 2]", "DW_OP_const_type 1 [256 0]"]:
            self.incomplete(source,ctx)

    def test_budget_and_fixed_inputs(self):
        ctx = snapshot(types={"1":ty("u8","DW_ATE_unsigned",8,1)}, initial_stack=[g(7)])
        states = [self.raw("a4 01 01 ff 9f",ctx,depth=d) for d in (0,1,2)]
        self.assertEqual([s["position"] for s in states],[0,4,5])
        self.assertEqual([s["status"] for s in states],["incomplete","incomplete","completed"])
        self.assertEqual(self.fixed_inputs(states[1]),self.fixed_inputs(states[2]))
        self.assertEqual(states[2]["stack"],[g(7),{"value":255,"type":{"id":"u8"}}])
