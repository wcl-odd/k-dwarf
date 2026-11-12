"""The execution core accepts decoded E/I and has no source-language dependencies."""
import json
import os
from pathlib import Path
import re
from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot


class CoreSeparationTests(DwarfTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        backend = "haskell" if "haskell" in str(cls.definition) else "llvm"
        cls.core = Path(os.environ.get("DWARF_CORE_DEFINITION", str(cls.definition.parent / ("core-" + backend + "-kompiled"))))
        if not (cls.core / "compiled.bin").exists():
            raise RuntimeError("Compile the independent DWARF-CORE definition")

    def raw(self, source, context=None, **options):
        path = Path(self.temp.name) / "input.hex"
        path.write_text(source)
        return dwarf.evaluate(path, snapshot() if context is None else context, self.definition,
                              input_format="hex", **options)

    def core_run(self, prepared, context, **options):
        expression, fixed_context, _ = dwarf.root_inputs(prepared["configuration"]["term"])
        path = Path(self.temp.name) / "decoded.json"
        path.write_text(json.dumps({"format":"KAST", "version":4, "term":expression}))
        return dwarf.evaluate_decoded(path, context, self.core, prepared_context=fixed_context, **options)

    def assert_same(self, left, right):
        for key in ("status", "position", "end", "stack", "result", "stop_reason"):
            self.assertEqual(left[key], right[key], key)
        self.assertEqual(dwarf.canonical_term(left["configuration"]["term"]),
                         dwarf.canonical_term(right["configuration"]["term"]))

    def test_core_dependency_closure_excludes_frontend(self):
        pending=[ROOT / "semantics/execution/core.k"]; seen=set()
        while pending:
            path=pending.pop().resolve()
            if path in seen: continue
            seen.add(path)
            source=path.read_text()
            self.assertNotIn(path.name, {"syntax.k", "decoding.k", "normalization.k", "frontend.k"})
            for dependency in re.findall(r'^requires "([^"]+)"', source, re.M):
                pending.append(path.parent / dependency)
        source=(ROOT / "semantics/execution/core.k").read_text()
        self.assertNotRegex(source, r"\b(?:rawBytes|sourceInstructionAt|readLEB|normalize)\(")

    def test_direct_algebraic_input_and_budget(self):
        path=Path(self.temp.name) / "direct.k"
        path.write_text("decoded(0, 3, codeAt(0, constOp(-1), 2, codeAt(2, stackValueOp, 3, .Instructions)), .Bytes)")
        context=snapshot(initial_stack=[g(7)])
        for depth in (0, 1, 2, 3):
            raw=self.raw("11 7f 9f", context, depth=depth)
            direct=dwarf.evaluate_decoded(path, context, self.core, depth=depth)
            for key in ("status", "position", "end", "stack", "result"):
                self.assertEqual(raw[key], direct[key], (depth,key))

    def test_three_entries_and_fixed_inputs(self):
        context=snapshot(initial_stack=[g(7)])
        raw=self.raw("11 7f 9f", context)
        path=Path(self.temp.name) / "input.text"
        path.write_text("0: DW_OP_consts -0x1, 2: DW_OP_stack_value, 3")
        text=dwarf.evaluate(path,context,self.definition)
        for key in ("status", "position", "end", "stack", "result"):
            self.assertEqual(raw[key],text[key])
        for depth in (1, 2, 3):
            self.assert_same(self.raw("11 7f 9f", context, depth=depth), self.core_run(raw, context, depth=depth))
        self.assertEqual(dwarf.label(dwarf.root_inputs(raw["configuration"]["term"])[0]), "decodedExpression")

    def test_bad_suffix_boundaries_and_prepared_nested_code(self):
        fixtures=[
            ("31 ff 9f", snapshot()),
            ("31 10 80", snapshot()),
            ("2f 02 00 ff 96", snapshot(initial_stack=[g(7)])),
            ("98 20 00 9f", snapshot(die_locations={"32":{"bytes":[0x31,0xff]}})),
            ("98 20 00 9f", snapshot(die_locations={"32":{"bytes":[0x31]}})),
            ("a3 01 50 9f", snapshot(entry_context={"registers":{"0":23}})),
            ("a3 02 31 ff 9f", snapshot(entry_context={})),
        ]
        for source,context in fixtures:
            with self.subTest(source=source):
                integrated=self.raw(source,context,depth=20)
                direct=self.core_run(integrated,context,depth=20)
                self.assert_same(integrated,direct)

    def test_text_declared_positions_and_unavailable_operands(self):
        for source in ("-3: DW_OP_lit7, -1: DW_OP_stack_value, 0",
                       "10: DW_OP_lit7, 99", "-3: DW_OP_lit7, -1",
                       "0: DW_OP_const1s 255, 2: DW_OP_stack_value, 3",
                       "0: DW_OP_skip 1, 3: DW_OP_const1s 255, 4"):
            path=Path(self.temp.name)/"input.text";path.write_text(source)
            context=snapshot(initial_stack=[g(7)])
            integrated=dwarf.evaluate(path,context,self.definition)
            self.assert_same(integrated,self.core_run(integrated,context))
