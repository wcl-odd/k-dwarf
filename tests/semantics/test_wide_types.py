"""Base-type stack widths are independent of the address-sized generic type."""
from pathlib import Path

from test_basic import DwarfTestCase, dwarf, g, snapshot, ty


class WideTypeTests(DwarfTestCase):
    def raw(self, source, ctx):
        path = Path(self.temp.name) / "wide.hex"
        path.write_text(source)
        return dwarf.evaluate(path, ctx, self.definition, input_format="hex")

    def test_validation_uses_type_storage_not_address_width(self):
        for bits in (33, 64, 128, 257):
            for encoding, number in (("DW_ATE_unsigned", (1 << bits) - 1),
                                     ("DW_ATE_signed", -(1 << (bits - 1)))):
                record = ty("wide", encoding, bits, (bits + 7) // 8)
                ctx = snapshot(address_width=32, types={"1": record},
                               initial_stack=[{"value": number, "type": 1}])
                dwarf.prepare_context(ctx)
                ctx["initial_stack"][0]["value"] = 1 << bits
                with self.assertRaises(ValueError):
                    dwarf.prepare_context(ctx)
        for bits, size in ((0, 1), (129, 16), (1, 0)):
            with self.assertRaises(ValueError):
                dwarf.prepare_context(snapshot(address_width=32, types={"1": ty(bits=bits, size=size)}))

    def test_wide_typed_read_both_entries_and_byte_orders(self):
        number = (1 << 100) + 123
        for endian in ("little", "big"):
            data = number.to_bytes(16, endian)
            ctx = snapshot(address_width=32, endianness=endian,
                           types={"1": ty("u128", "DW_ATE_unsigned", 128, 16)},
                           memory={str(16 + i): b for i, b in enumerate(data)})
            expected = [{"value": number, "type": {"id": "u128"}}]
            text = self.complete("DW_OP_addr 16, DW_OP_deref_type 16 1, DW_OP_stack_value", expected, ctx)
            address = "10 00 00 00" if endian == "little" else "00 00 00 10"
            raw = self.raw("03 " + address + " a6 10 01 9f", ctx)
            self.assertEqual(raw["result"], text["result"])
            self.assertEqual(raw["stack"], expected)
            self.assertEqual(raw["position"], 9)
        # Generic reading keeps its own address-sized capacity constraint.
        stopped = self.incomplete("DW_OP_addr 16, DW_OP_deref_size 16", ctx, position=1)
        self.assertEqual(stopped["stack"], [g(16)])

    def test_mixed_stack_preserves_wide_values_and_type_identity(self):
        number = (1 << 128) + 17
        ctx = snapshot(address_width=32,
                       types={"1": ty("s128", "DW_ATE_signed", 128, 16),
                              "2": ty("u129", "DW_ATE_unsigned", 129, 17)},
                       initial_stack=[{"value": -(1 << 100), "type": 1}, {"value": number, "type": 2}])
        expected = [{"value": -(1 << 100), "type": {"id": "s128"}},
                    {"value": number, "type": {"id": "u129"}}]
        self.complete("DW_OP_dup, DW_OP_drop, DW_OP_stack_value", expected, ctx)

    def test_arithmetic_and_reinterpret_use_the_base_type_width(self):
        types = {"1": ty("u128", "DW_ATE_unsigned", 128, 16),
                 "2": ty("s128", "DW_ATE_signed", 128, 16)}
        number = (1 << 127) + 3
        ctx = snapshot(address_width=32, types=types, initial_stack=[{"value": number, "type": 1}])
        self.complete("DW_OP_plus_uconst 1, DW_OP_reinterpret 2, DW_OP_stack_value",
                      [{"value": number + 1 - (1 << 128), "type": {"id": "s128"}}], ctx)
        ctx["initial_stack"] = [{"value": (1 << 128) - 1, "type": 1}, {"value": 1, "type": 1}]
        self.complete("DW_OP_plus", [{"value": 0, "type": {"id": "u128"}}], ctx)

    def test_widening_and_generic_narrowing_have_separate_conditions(self):
        ctx = snapshot(address_width=32, types={"1": ty("u128", "DW_ATE_unsigned", 128, 16)})
        number = (1 << 100) + 42
        prefix = f"DW_OP_constu 42, DW_OP_convert 1, DW_OP_plus_uconst {1 << 100}"
        self.complete(prefix + ", DW_OP_stack_value", [{"value": number, "type": {"id": "u128"}}], ctx)
        # Only this explicit conversion narrows the already-wide value. It
        # truncates to the generic target width; constructing/using u128 above
        # does not silently impose an address-width limit on the typed stack.
        self.complete(prefix + ", DW_OP_convert 0, DW_OP_stack_value", [g(42)], ctx)
        # Literal generic constants still truncate to A bits, before conversion.
        self.complete(f"DW_OP_constu {number}, DW_OP_convert 1", [{"value": 42, "type": {"id": "u128"}}], ctx)

    def test_wide_direct_value_piece_keeps_all_bits(self):
        number = (1 << 100) + 17
        ctx = snapshot(address_width=32, architecture="i386",
                       types={"1": ty("u128", "DW_ATE_unsigned", 128, 16)},
                       memory={str(16 + i): b for i, b in enumerate(number.to_bytes(16, "little"))})
        result = self.execute("DW_OP_addr 16, DW_OP_deref_type 16 1, DW_OP_stack_value, DW_OP_piece 16", ctx)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["bit_size"], 128)
        self.assertEqual(result["result"]["bits"], f"{number:0128b}")
        self.assertEqual(result["stack"], [])
