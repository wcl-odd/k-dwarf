"""DWARF 5 branches: byte-relative targets, atomic failure and bounded loops."""

from pathlib import Path

from test_basic import DwarfTestCase, dwarf, g, snapshot, ty


class ControlFlowTests(DwarfTestCase):
    def run_input(self, source, mode="hex", ctx=None, **kwargs):
        path = Path(self.temp.name) / ("control-flow." + mode)
        path.write_text(source)
        return dwarf.evaluate(path, snapshot() if ctx is None else ctx,
                              self.definition, input_format=mode, **kwargs)

    def success(self, source, expected, mode="hex", ctx=None, kind="value", **kwargs):
        result = self.run_input(source, mode, ctx, **kwargs)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["position"], result["end"])
        self.assertEqual(result["stack"], expected)
        wanted = ({"kind": "value", **expected[-1]} if kind == "value"
                  else {"kind": "memory", "address": expected[-1]["value"]})
        self.assertEqual(result["result"], wanted)
        return result

    def unchanged_failure(self, source, position, stack, budget, mode="hex", ctx=None):
        before = self.run_input(source, mode, ctx, depth=budget)
        after = self.run_input(source, mode, ctx)
        self.assertEqual((after["status"], after["position"], after["stack"]),
                         ("incomplete", position, stack))
        self.assertIsNone(after["result"])
        self.assert_preserved(before, after)
        return after

    def test_nop_preserves_mixed_stack_and_allows_empty_stack(self):
        ctx = snapshot(types={"1": ty()}, initial_stack=[g(7), {"value": -2, "type": 1}])
        values = [g(7), {"value": -2, "type": {"id": "cu0:s16"}}]
        for mode, source in [("hex", "96"), ("text", "10: DW_OP_nop, 20")]:
            with self.subTest(mode=mode):
                pending = self.run_input(source, mode, ctx, depth=1)
                result = self.success(source, values, mode, ctx, kind="memory", depth=2)
                self.assertEqual((pending["status"], pending["position"], pending["stack"]),
                                 ("incomplete", result["end"], values))
                self.assertEqual(self.fixed_inputs(pending), self.fixed_inputs(result))
                empty = self.run_input(source, mode)
                self.assertEqual((empty["status"], empty["position"], empty["stack"]),
                                 ("incomplete", result["end"], []))

    def test_forward_skip_and_end_do_not_execute_skipped_operations(self):
        for mode, source in [
            ("hex", "37 2f 01 00 13 9f"),
            ("text", "0: DW_OP_lit7, 1: DW_OP_skip 1, 4: DW_OP_drop, 5: DW_OP_stack_value, 6"),
        ]:
            with self.subTest(mode=mode):
                result = self.success(source, [g(7)], mode)
                at_jump = self.run_input(source, mode, depth=1)
                landed = self.run_input(source, mode, depth=2)
                self.assertEqual((landed["status"], landed["position"], landed["stack"]),
                                 ("incomplete", 5, [g(7)]))
                self.assertEqual(self.fixed_inputs(at_jump), self.fixed_inputs(result))
        # END is a legal target even when skipped bytes cannot be decoded.
        result = self.success("37 2f 01 00 ff", [g(7)], kind="memory")
        self.assertEqual(result["end"], 5)
        self.success("37 2f 00 00", [g(7)], kind="memory")

    def test_backward_skip_and_target_endianness(self):
        # Upstream LLDB DW_OP_skip_backward: 0 -> 8 -> 3 -> 5 -> END.
        for endian, raw in [
            ("little", "2f 05 00 08 42 2f 03 00 2f f8 ff"),
            ("big", "2f 00 05 08 42 2f 00 03 2f ff f8"),
        ]:
            with self.subTest(endian=endian):
                ctx = snapshot(address_width=32, endianness=endian)
                self.success(raw, [g(66)], ctx=ctx, kind="memory")
                states = [self.run_input(raw, ctx=ctx, depth=d) for d in (1, 2, 3, 4)]
                self.assertEqual([x["position"] for x in states], [8, 3, 5, 11])
                self.assertTrue(all(x["status"] == "incomplete" for x in states))
                self.assertTrue(all(self.fixed_inputs(x) == self.fixed_inputs(states[0]) for x in states))

    def test_bra_conditions_and_comparison(self):
        for raw in ("37 31 28 01 00 39 9f", "37 11 7f 28 01 00 39 9f",
                    "37 32 33 2d 28 01 00 39 9f", "37 30 28 63 00 9f"):
            with self.subTest(raw=raw):
                self.success(raw, [g(7)])
        # False does not validate the unused target, even with a negative displacement.
        self.success("37 30 28 00 80 9f", [g(7)])
        self.success("37 30 28 80 00 9f", [g(7)], ctx=snapshot(endianness="big"))
        self.success("0: DW_OP_lit7, 1: DW_OP_lit0, 2: DW_OP_bra 32767, 5: DW_OP_stack_value, 6",
                     [g(7)], "text")

    def test_bra_accepts_integer_types_without_boolean_conversion(self):
        for encoding, number in [("DW_ATE_signed", -1), ("DW_ATE_unsigned", 7),
                                  ("DW_ATE_boolean", 2), ("DW_ATE_signed", 0)]:
            with self.subTest(encoding=encoding, number=number):
                ctx = snapshot(types={"1": ty("condition", encoding, 3, 1)},
                               initial_stack=[g(7), {"value": number, "type": 1}])
                # Both branches land at END, consuming the entire condition Value.
                result = self.success("28 00 00", [g(7)], ctx=ctx, kind="memory")
                pending = self.run_input("28 00 00", ctx=ctx, depth=1)
                self.assertEqual((pending["position"], pending["stack"], pending["status"]),
                                 (3, [g(7)], "incomplete"))
                self.assertEqual(self.fixed_inputs(pending), self.fixed_inputs(result))

    def test_invalid_targets_and_truncation_preserve_full_scene(self):
        for suffix in ("2f ff ff", "2f fb ff", "2f 01 00", "2f", "2f 00", "28", "28 00"):
            with self.subTest(suffix=suffix):
                self.unchanged_failure("37 " + suffix, 1, [g(7)], 1)
        for raw in ("37 31 28 ff ff", "37 31 28 fa ff", "37 31 28 01 00"):
            with self.subTest(raw=raw):
                self.unchanged_failure(raw, 2, [g(7), g(1)], 2)
        self.unchanged_failure("28 00 00", 0, [], 1)
        self.unchanged_failure("0: DW_OP_lit7, 1: DW_OP_skip -1, 10: DW_OP_stack_value, 11",
                               1, [g(7)], 1, "text")
        self.unchanged_failure("0: DW_OP_lit7, 1: DW_OP_bra -1, 10: DW_OP_stack_value, 11",
                               1, [g(7)], 1, "text")
        # A target at an unknown opcode is an established boundary; evaluation then stops there.
        self.unchanged_failure("37 2f 00 00 ff", 4, [g(7)], 2)

    def test_displacement_source_range_is_signed_16_bits(self):
        for op in ("skip", "bra"):
            for displacement in (-32769, 32768):
                with self.subTest(op=op, displacement=displacement):
                    self.unchanged_failure(f"0: DW_OP_lit7, 1: DW_OP_{op} {displacement}, 4",
                                           1, [g(7)], 1, "text")
        # Even a false condition cannot bypass an invalid source encoding range.
        self.unchanged_failure("0: DW_OP_lit0, 1: DW_OP_bra 0x8000, 4", 1, [g(0)], 1, "text")

    def test_declared_offsets_negative_end_and_no_pc_wrapping(self):
        self.success("-9: DW_OP_lit7, -8: DW_OP_skip 0x1, -2: DW_OP_lit9, -1: DW_OP_stack_value, 0",
                     [g(7)], "text")
        # Sparse text positions intentionally disagree with real instruction lengths.
        # This path uses both extremal signed-16-bit displacements and an 8-bit stack type;
        # expression positions are mathematical offsets, not address-width machine numbers.
        source = ("0: DW_OP_skip 32765, 3: DW_OP_lit7, 4: DW_OP_skip 32767, "
                  "5: DW_OP_nop, 32768: DW_OP_skip -0x8000, 32771: DW_OP_nop, "
                  "32772: DW_OP_stack_value, 32773")
        self.success(source, [g(7)], "text", snapshot(address_width=8))

    def test_backward_bra_finite_loop_and_rewrite_budget(self):
        # Countdown: 3; loop { lit1; minus; dup; bra loop }; stack_value.
        for mode, source in [
            ("hex", "33 31 1c 12 28 fa ff 9f"),
            ("text", "0: DW_OP_lit3, 1: DW_OP_lit1, 2: DW_OP_minus, 3: DW_OP_dup, 4: DW_OP_bra -6, 7: DW_OP_stack_value, 8"),
        ]:
            with self.subTest(mode=mode):
                states = [self.run_input(source, mode, depth=d) for d in (5, 9, 13, 14)]
                self.assertEqual([(x["position"], x["stack"], x["status"]) for x in states],
                                 [(1, [g(2)], "incomplete"), (1, [g(1)], "incomplete"),
                                  (7, [g(0)], "incomplete"), (8, [g(0)], "completed")])
                self.assertEqual(states[-1]["result"], {"kind": "value", **g(0)})
                self.assertTrue(all(self.fixed_inputs(x) == self.fixed_inputs(states[0]) for x in states))

    def test_self_loop_and_reached_stack_value_restriction(self):
        for mode, source in [("hex", "37 2f fd ff"),
                             ("text", "0: DW_OP_lit7, 1: DW_OP_skip -3, 4")]:
            with self.subTest(mode=mode):
                for depth in (2, 5):
                    result = self.run_input(source, mode, depth=depth)
                    self.assertEqual((result["status"], result["position"], result["stack"], result["result"]),
                                     ("incomplete", 1, [g(7)], None))
        # Skipping a nonterminal marker is permitted; reaching one still cannot finish.
        self.success("37 2f 01 00 9f 9f", [g(7)])
        self.unchanged_failure("37 2f 00 00 9f 96", 4, [g(7)], 2)
