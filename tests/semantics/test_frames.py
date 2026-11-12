"""Fixed CFA/frame-base inputs remain distinct and read-only."""
from pathlib import Path
from test_basic import DwarfTestCase, dwarf, g, snapshot


class FrameTests(DwarfTestCase):
    def raw(self, source, ctx, **kwargs):
        path = Path(self.temp.name) / "frames.hex"
        path.write_text(source)
        return dwarf.evaluate(path, ctx, self.definition, input_format="hex", **kwargs)

    def test_two_entries_and_independent_frame_inputs(self):
        for width in (1, 8, 32, 64, 128):
            for cfa in (0, (1 << width) - 1):
                ctx = snapshot(address_width=width, cfa=cfa, framebase=0, initial_stack=[g(7 % (1 << width))])
                text = self.complete("DW_OP_call_frame_cfa, DW_OP_fbreg -1, DW_OP_stack_value",
                                     [g(7 % (1 << width)), g(cfa), g((1 << width)-1)], ctx)
                raw = self.raw("9c 91 7f 9f", ctx)
                self.assertEqual(raw["stack"], text["stack"])
                self.assertEqual(raw["result"], text["result"])
                self.assertEqual(raw["position"], 4)

    def test_missing_inputs_and_failure_atomicity(self):
        for ctx in (snapshot(), snapshot(framebase=42)):
            source = "DW_OP_lit7, DW_OP_call_frame_cfa"
            before = self.execute(source, ctx, depth=1)
            stopped = self.incomplete(source, ctx, position=1)
            self.assert_preserved(before, stopped)
        self.complete("DW_OP_call_frame_cfa", [g(42)], snapshot(cfa=42))
        self.incomplete("DW_OP_fbreg 0", snapshot(cfa=42))
        self.complete("DW_OP_fbreg 0", [g(17)], snapshot(framebase=17))

    def test_positions_budget_and_fixed_state(self):
        ctx = snapshot(cfa=42, framebase=99)
        results = [self.raw("9c 96", ctx, depth=n) for n in (0, 1, 2, 3)]
        self.assertEqual([r["status"] for r in results], ["incomplete"]*3 + ["completed"])
        self.assertEqual([r["position"] for r in results], [0, 1, 2, 2])
        self.assertEqual(self.fixed_inputs(results[1]), self.fixed_inputs(results[3]))
        self.assertEqual(dwarf.find_cell(results[1]["configuration"]["term"], "fragments"),
                         dwarf.find_cell(results[3]["configuration"]["term"], "fragments"))
        path = Path(self.temp.name) / "offsets.dwarf"
        path.write_text("-2: DW_OP_call_frame_cfa, 0")
        self.assertEqual(dwarf.evaluate(path, ctx, self.definition)["result"], {"kind":"memory", "address":42})

    def test_memory_and_composition(self):
        ctx = snapshot(architecture="x86_64", cfa=256, framebase=257, memory={"256":17,"257":34})
        self.complete("DW_OP_call_frame_cfa, DW_OP_deref_size 1, DW_OP_fbreg 0, DW_OP_deref_size 1",
                      [g(17), g(34)], ctx)
        result = self.execute("DW_OP_call_frame_cfa, DW_OP_piece 1, DW_OP_fbreg 0, DW_OP_piece 1", ctx)
        self.assertEqual(result["result"]["bits"], "0010001000010001")

    def test_context_validation_and_no_parameter_syntax(self):
        for field in ("cfa", "framebase"):
            for bad in (-1, 1 << 64, True, "0", None):
                with self.assertRaises(ValueError): dwarf.prepare_context(snapshot(**{field:bad}))
        path = Path(self.temp.name) / "bad.dwarf"
        path.write_text("0: DW_OP_call_frame_cfa 1, 2")
        with self.assertRaises(RuntimeError): dwarf.evaluate(path, snapshot(), self.definition)
