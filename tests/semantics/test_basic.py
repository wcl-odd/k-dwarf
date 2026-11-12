"""Section 3.4 acceptance tests; compile the formal definition before running."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import run as dwarf


def g(number):
    return {"value": number, "type": "g"}


def ty(identity="cu0:s16", encoding="DW_ATE_signed", bits=16, size=2):
    return {"id": identity, "encoding": encoding, "bit_width": bits, "byte_size": size}


def snapshot(**extra):
    return {"address_width": 64, "endianness": "little", **extra}


def annotated(source):
    """Assign declared positions, deliberately without a DWARF encoder."""
    if not source.strip():
        return "0"
    operations = source.split(",")
    return ",\n".join(f"{i}: {op.strip()}" for i, op in enumerate(operations)) + f",\n{len(operations)}"


class DwarfTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition = Path(os.environ.get("DWARF_DEFINITION", dwarf.DEFAULT_DEFINITION)).resolve()
        if not (cls.definition / "compiled.bin").exists():
            raise RuntimeError("Compile semantics/dwarf.k before running these tests")
        scratch = Path(os.environ.get("DWARF_INPUT_TMPDIR", str(Path(tempfile.gettempdir()) / "scratch" / f"kframework-tests-{os.getpid()}")))
        scratch.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="basic-tests-", dir=scratch)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def execute(self, text, ctx=None, **kwargs):
        path = Path(self.temp.name) / "expression.dwarf"
        path.write_text(annotated(text))
        return dwarf.evaluate(path, snapshot() if ctx is None else ctx, self.definition, **kwargs)

    def complete(self, text, expected, ctx=None):
        result = self.execute(text, ctx)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["position"], result["end"])
        self.assertEqual(result["stack"], expected)
        self.assertEqual(dwarf.label(self.state(result)), "finishedEvaluation")
        self.assertIsNotNone(result["result"])
        return result

    def state(self, result):
        return dwarf.evaluation_term(result["configuration"]["term"])

    def fixed_inputs(self, result):
        term = result["configuration"]["term"]
        if dwarf.label(term) == "initGeneratedTopCell":
            return (dwarf.initializer_argument(term, "$PGM"),
                    dwarf.initializer_argument(term, "$CONTEXT"))
        return dwarf.root_inputs(term)[:2]

    def assert_initialized_inputs_preserved(self, before, after, context):
        """Check E/I identity across the Haskell zero-budget initialization boundary.

        A source Program and decoded E are different representations. Validate
        the original context, then test exact prepared E/I preservation from
        depth zero using the independent core; never decode DWARF in Python.
        """
        term = before["configuration"]["term"]
        if dwarf.label(term) != "initGeneratedTopCell":
            self.assertEqual(self.fixed_inputs(before), self.fixed_inputs(after))
            return
        expression, prepared, _ = dwarf.root_inputs(after["configuration"]["term"])
        original = dwarf.initializer_argument(term, "$CONTEXT")
        self.assertEqual(dwarf.canonical_term(original),
                         dwarf.canonical_term(dwarf.source_context(prepared)))
        self.assertEqual(dwarf.label(expression), "decodedExpression")
        source = dwarf.initializer_argument(term, "$PGM")
        # Original byte identity is provenance, not an opcode/operand decoder.
        if "HexProgram" in dwarf.label(source):
            values = []
            while source.get("args"):
                token, source = source["args"]
                values.append(int(token["token"], 16))
            self.assertEqual(values, dwarf.decode_bytes(expression["args"][3]))
        backend = "haskell" if "haskell" in str(self.definition) else "llvm"
        path = Path(self.temp.name) / "prepared-input.json"
        path.write_text(json.dumps({"format":"KAST", "version":4, "term":expression}))
        zero = dwarf.evaluate_decoded(path, context,
                    self.definition.parent / ("core-" + backend + "-kompiled"),
                    depth=0, prepared_context=prepared)
        self.assertEqual(tuple(dwarf.canonical_term(t) for t in self.fixed_inputs(zero)),
                         tuple(dwarf.canonical_term(t) for t in self.fixed_inputs(after)))

    def incomplete(self, text, ctx=None, position=0):
        result = self.execute(text, ctx)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["position"], position)
        self.assertEqual(dwarf.label(self.state(result)), "evaluation")
        self.assertIsNone(result["result"])
        return result

    def assert_preserved(self, before, after):
        """A failed precondition preserves the actual state without a diagnostic step."""
        self.assertEqual(self.fixed_inputs(before), self.fixed_inputs(after))
        self.assertEqual((before["position"], before["end"], before["stack"]),
                         (after["position"], after["end"], after["stack"]))
        self.assertEqual(self.state(before)["args"][-1], self.state(after)["args"][-1])
        self.assertEqual(dwarf.find_cell(before["configuration"]["term"], "fragments"),
                         dwarf.find_cell(after["configuration"]["term"], "fragments"))


class BasicTests(DwarfTestCase):
    def test_all_111_names_execute_and_preserve_inputs(self):
        operations, expected = [], []
        for value in range(32):
            operations.append(f"DW_OP_lit{value}")
            expected.append(g(value))
        for size in (1, 2, 4, 8):
            for suffix, value in (("u", 7), ("s", -7)):
                operations.append(f"DW_OP_const{size}{suffix} {value}")
                expected.append(g(value % (1 << 64)))
        for op, value in [("constu", (1 << 64) - 1), ("consts", -(1 << 63)), ("addr", 17)]:
            operations.append(f"DW_OP_{op} {value}")
            expected.append(g(value % (1 << 64)))
        operations.append("DW_OP_fbreg -4")
        expected.append(g(1996))
        for register in range(32):
            operations.append(f"DW_OP_breg{register} -3")
            expected.append(g(997 + register))
        operations.append("DW_OP_bregx 40 -8")
        expected.append(g(4992))
        for op, value in [("DW_OP_deref", g(65534)), ("DW_OP_deref_size 2", g(65534)),
                          ("DW_OP_deref_type 2 12", {"value": -2, "type": {"id": "cu0:s16"}})]:
            operations.extend(["DW_OP_addr 256", op])
            expected.append(value)
        operations.extend(["DW_OP_dup", "DW_OP_over", "DW_OP_pick 2", "DW_OP_drop", "DW_OP_swap", "DW_OP_rot"])
        expected += [{"value": -2, "type": {"id": "cu0:s16"}}] * 2
        # The existing stack stays below these independent computation cases.
        for source, value in [
            ("DW_OP_consts -7, DW_OP_abs", 7),
            ("DW_OP_constu 7, DW_OP_neg", -7),
            ("DW_OP_constu 5, DW_OP_not", (1 << 64) - 6),
            ("DW_OP_constu 5, DW_OP_plus_uconst 17", 22),
        ]:
            operations.extend(source.split(", "))
            expected.append(g(value))
        for op, value in [("and", 2), ("div", 3), ("minus", 4), ("mod", 0),
                          ("mul", 12), ("or", 6), ("plus", 8), ("shl", 24),
                          ("shr", 1), ("shra", 1), ("xor", 4),
                          ("eq", 0), ("ge", 1), ("gt", 1), ("le", 0), ("lt", 0), ("ne", 1)]:
            operations.extend(["DW_OP_lit6", "DW_OP_lit2", f"DW_OP_{op}"])
            expected.append(g(value))
        operations.extend(["DW_OP_nop", "DW_OP_skip 0", "DW_OP_lit0", "DW_OP_bra 0", "DW_OP_stack_value"])
        names = set(re.findall(r"DW_OP_\w+", ", ".join(operations)))
        self.assertEqual(len(names), 111)
        ctx = snapshot(registers={str(i): 1000 + i for i in range(32)} | {"40": 5000},
                       memory={str(256 + i): b for i, b in enumerate([254, 255, 0, 0, 0, 0, 0, 0])},
                       types={"12": ty()}, framebase=2000)
        before = self.complete("", [], ctx)
        source = ",\n".join(operations)
        running = self.execute(source, ctx, depth=1)
        self.assertEqual(running["status"], "incomplete")
        self.assertEqual(running["position"], 1)
        after = self.complete(source, expected, ctx)
        self.assertEqual(after["result"], {"kind": "value", **expected[-1]})
        self.assertEqual(self.fixed_inputs(before)[1], self.fixed_inputs(after)[1])
        self.assertEqual(self.fixed_inputs(running), self.fixed_inputs(after))
        self.assertEqual(self.state(running)["args"][2], self.state(after)["args"][2])
        for cell in ("pc", "stack"):
            self.assertIsNotNone(dwarf.find_cell(after["configuration"]["term"], cell))
        for obsolete in ("code", "context", "k", "phase", "end", "result"):
            self.assertIsNone(dwarf.find_cell(after["configuration"]["term"], obsolete))

    def test_constant_boundaries(self):
        operations, values = [], []
        for size in (1, 2, 4, 8):
            for suffix, number in [("u", (1 << (8 * size)) - 1), ("s", -(1 << (8 * size - 1)))]:
                operations.append(f"DW_OP_const{size}{suffix} {number}")
                values.append(g(number % (1 << 64)))
        self.complete(", ".join(operations), values)

    def test_constant_range_failures(self):
        for source in ("DW_OP_const1u 256", "DW_OP_const1u -1", "DW_OP_const1s 128",
                       "DW_OP_const1s -129", "DW_OP_constu -1",
                       f"DW_OP_addr {1 << 64}", "DW_OP_addr -1"):
            with self.subTest(source=source):
                self.incomplete(source)
        result = self.incomplete("DW_OP_lit3, DW_OP_const1u 256", position=1)
        self.assertEqual(result["stack"], [g(3)])

    def test_constant_extensions_and_truncation(self):
        self.complete("DW_OP_const2u 256, DW_OP_const1s -1", [g(256), g((1 << 64) - 1)])
        self.complete("DW_OP_const2u 256, DW_OP_const2s -129", [g(0), g(127)],
                      snapshot(address_width=8))
        self.complete("DW_OP_const8u 18446744073709551615, DW_OP_const8s -1",
                      [g((1 << 64) - 1), g((1 << 128) - 1)], snapshot(address_width=128))
        self.complete("DW_OP_lit31", [g(15)], snapshot(address_width=4))

    def test_unbounded_decoded_constants(self):
        self.complete(f"DW_OP_constu {(1 << 200) + 5}, "
                      f"DW_OP_consts {(1 << 200) + 7}, DW_OP_consts {-(1 << 200) - 9}",
                      [g(5), g(7), g(247)], snapshot(address_width=8))

    def test_offsets_wrap(self):
        self.complete("DW_OP_bregx 1 -8, DW_OP_fbreg -3", [g((1 << 64) - 4), g(97)],
                      snapshot(registers={"1": 4}, framebase=100))
        self.complete("DW_OP_breg1 1, DW_OP_bregx 1 -256, DW_OP_fbreg -1, DW_OP_fbreg 384",
                      [g(0), g(255), g(127), g(0)],
                      snapshot(address_width=8, registers={"1": 255}, framebase=128))
        self.complete(f"DW_OP_breg31 {(1 << 200) + 2}, "
                      f"DW_OP_bregx 31 {-(1 << 200) - 1}, DW_OP_fbreg {(1 << 200) + 129}, "
                      f"DW_OP_fbreg {-(1 << 200) - 129}",
                      [g(1), g(254), g(1), g(255)],
                      snapshot(address_width=8, registers={"31": 255}, framebase=128))
        # The external FB is already an unsigned A-bit machine number;
        # only adding the decoded offset can underflow or overflow.
        self.complete("DW_OP_fbreg 0, DW_OP_fbreg -1", [g(0), g(255)],
                      snapshot(address_width=8, framebase=0))
        self.complete("DW_OP_fbreg 0, DW_OP_fbreg 1", [g(255), g(0)],
                      snapshot(address_width=8, framebase=255))
        self.incomplete("DW_OP_bregx -1 0")

    def test_wrapped_addresses_read_memory(self):
        self.complete("DW_OP_const2u 256, DW_OP_deref_size 1, "
                      "DW_OP_breg0 1, DW_OP_deref_size 1, DW_OP_fbreg -1, DW_OP_deref_size 1",
                      [g(42), g(42), g(7)],
                      snapshot(address_width=8, registers={"0": 255}, framebase=0,
                               memory={"0": 42, "255": 7}))

    def test_endianness_and_type_identity(self):
        signed = ty()
        unsigned = ty("cu0:u16", "DW_ATE_unsigned")
        # A base type whose identity is "g" must remain distinct from generic.
        other = ty("g")
        for endian, generic, signed_value in [("little", 65534, -2), ("big", 65279, -257)]:
            ctx = snapshot(endianness=endian, memory={"256": 254, "257": 255},
                           types={"12": signed, "13": unsigned, "14": other})
            self.complete("DW_OP_addr 256, DW_OP_deref_size 2, "
                          "DW_OP_addr 256, DW_OP_deref_type 2 12, "
                          "DW_OP_addr 256, DW_OP_deref_type 2 13, "
                          "DW_OP_addr 256, DW_OP_deref_type 2 14",
                          [g(generic), {"value": signed_value, "type": {"id": "cu0:s16"}},
                           {"value": generic, "type": {"id": "cu0:u16"}},
                           {"value": signed_value, "type": {"id": "g"}}], ctx)

    def test_narrow_types_and_unsigned_boolean_reads(self):
        signed3 = ty("s3", "DW_ATE_signed", 3, 1)
        unsigned3 = ty("u3", "DW_ATE_unsigned", 3, 1)
        boolean = ty("bool8", "DW_ATE_boolean", 8, 1)
        ctx = snapshot(memory={"0": 255}, types={"1": signed3, "2": unsigned3, "3": boolean})
        # The same byte stays an unsigned integer for ordinary dereference;
        # only deref_type interprets its low bits using the requested type.
        self.complete("DW_OP_addr 0, DW_OP_deref_size 1, "
                      "DW_OP_addr 0, DW_OP_deref_type 1 1, DW_OP_addr 0, DW_OP_deref_type 1 2, "
                      "DW_OP_addr 0, DW_OP_deref_type 1 3",
                      [g(255), {"value": -1, "type": {"id": "s3"}}, {"value": 7, "type": {"id": "u3"}},
                       {"value": 255, "type": {"id": "bool8"}}], ctx)
        # A type may have wider storage than generic capacity, while its valid
        # bit width still fits A. The shared integer read must allow this.
        padded = snapshot(address_width=8, memory={"0": 255, "1": 255},
                          types={"1": ty("padded-s3", "DW_ATE_signed", 3, 2)})
        self.complete("DW_OP_addr 0, DW_OP_deref_type 2 1",
                      [{"value": -1, "type": {"id": "padded-s3"}}], padded)
        stopped = self.incomplete("DW_OP_addr 0, DW_OP_deref_size 2", padded, position=1)
        self.assertEqual(stopped["stack"], [g(0)])

    def test_default_zero_and_typed_address_reads(self):
        address_type = ty("addr", "DW_ATE_unsigned", 16, 2)
        ctx = snapshot(address_width=16, memory={"256": 42, "257": 0}, types={"1": address_type},
                       initial_stack=[{"value": 256, "type": 1}])
        self.complete("DW_OP_deref, DW_OP_addr 65535, DW_OP_deref_size 0", [g(42), g(0)], ctx)
        self.complete("DW_OP_addr 0, DW_OP_deref_size 0", [g(0)])
        self.incomplete("DW_OP_addr 0, DW_OP_deref", snapshot(address_width=7), position=1)

    def test_missing_context_and_size_conditions(self):
        cases = [
            ("DW_OP_breg0 0", snapshot(), 0),
            ("DW_OP_fbreg 0", snapshot(), 0),
            ("DW_OP_addr 0, DW_OP_deref_type 1 12", snapshot(memory={"0": 0}), 1),
            ("DW_OP_addr 0, DW_OP_deref_size 2", snapshot(memory={"0": 0}), 1),
            ("DW_OP_addr 0, DW_OP_deref_size 9", snapshot(), 1),
            ("DW_OP_addr 0, DW_OP_deref_type 1 12", snapshot(types={"12": ty()}), 1),
            ("DW_OP_addr 0, DW_OP_deref_type 0 12", snapshot(types={"12": ty()}), 1),
            ("DW_OP_addr 0, DW_OP_deref_type 2 12",
             snapshot(types={"12": ty()}, memory={"0": 255}), 1),
            ("DW_OP_addr 0, DW_OP_deref_size 256", snapshot(), 1),
            ("DW_OP_addr 0, DW_OP_deref_size -1", snapshot(), 1),
        ]
        for source, ctx, position in cases:
            with self.subTest(source=source):
                result = self.incomplete(source, ctx, position)
                self.assertEqual(result["stack"], [] if position == 0 else [g(0)])

    def test_stack_underflow_and_pick_bounds(self):
        for op in ("DW_OP_drop", "DW_OP_dup", "DW_OP_over", "DW_OP_swap", "DW_OP_rot", "DW_OP_deref",
                   "DW_OP_deref_type 2 12"):
            with self.subTest(op=op):
                self.assertEqual(self.incomplete(op)["stack"], [])
        ctx = snapshot(initial_stack=[g(i) for i in range(256)])
        self.complete("DW_OP_pick 255", ctx["initial_stack"] + [g(0)], ctx)
        for index in (-1, 256):
            self.assertEqual(self.incomplete(f"DW_OP_pick {index}", ctx)["stack"], ctx["initial_stack"])

    def test_mixed_type_reordering(self):
        a, b = ty("A"), ty("B")
        stack = [{"value": 1, "type": 1}, {"value": 2, "type": 2}, g(3)]
        ctx = snapshot(types={"1": a, "2": b}, initial_stack=stack)
        expected = [{"value": 1, "type": {"id": "A"}}, {"value": 2, "type": {"id": "B"}}, g(3)]
        before = self.complete("", expected, ctx)
        unstarted = self.execute("DW_OP_deref", ctx, depth=0)
        stopped = self.incomplete("DW_OP_deref", ctx)
        self.assertEqual(stopped["stack"], expected)
        self.assertEqual(self.fixed_inputs(before)[1], self.fixed_inputs(stopped)[1])
        self.assertEqual(self.fixed_inputs(unstarted), self.fixed_inputs(stopped))
        self.complete("DW_OP_swap, DW_OP_rot, DW_OP_over, DW_OP_drop",
                      [{"value": 2, "type": {"id": "B"}}, {"value": 1, "type": {"id": "A"}}, g(3)], ctx)

    def test_empty_multi_stack_and_depth_limit(self):
        self.complete("", [])
        ctx = snapshot(initial_stack=[g(3), g(-2)])
        self.complete("", ctx["initial_stack"], ctx)
        self.complete("DW_OP_dup, DW_OP_drop", ctx["initial_stack"], ctx)
        unstarted = self.execute("DW_OP_lit1", ctx, depth=0)
        self.assertEqual(unstarted["status"], "incomplete")
        self.assertEqual(unstarted["position"], 0)
        # Haskell may return its unexpanded initializer, before length is known.
        raw = dwarf.label(unstarted["configuration"]["term"]) == "initGeneratedTopCell"
        self.assertEqual(unstarted["end"], 0 if raw else 1)
        self.assertEqual(unstarted["stack"], ctx["initial_stack"])
        # Pure length/OP queries need no separate initialization rewrites.
        # Reaching P=END still needs one explicit completion rewrite.
        previous = None
        for depth, position, values in [(1, 1, [g(1)]), (2, 2, [g(1), g(2)])]:
            with self.subTest(depth=depth):
                stopped = self.execute("DW_OP_lit1, DW_OP_lit2", depth=depth)
                self.assertEqual(stopped["status"], "incomplete")
                self.assertEqual(stopped["position"], position)
                self.assertEqual(stopped["end"], 2)
                self.assertEqual(stopped["stack"], values)
                self.assertEqual(dwarf.label(self.state(stopped)), "evaluation")
                if previous is not None:
                    self.assertEqual(self.fixed_inputs(previous), self.fixed_inputs(stopped))
                previous = stopped
        finished = self.execute("DW_OP_lit1, DW_OP_lit2", depth=3)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["stack"], [g(1), g(2)])
        self.assertEqual(self.fixed_inputs(previous), self.fixed_inputs(finished))

    def test_reject_outside_syntax(self):
        for source in ("DW_OP_convert", "DW_OP_reinterpret", "DW_OP_plus 1",
                       "DW_OP_bra", "DW_OP_skip", "DW_OP_nop 1", "DW_OP_reg32", "DW_OP_GNU_uninit 1", "DW_OP_lit32",
                       "DW_OP_piece", "DW_OP_bit_piece 1", "DW_OP_stack_value 1",
                       "DW_OP_breg32 0",
                       "const(5); .Program", "DW_OP_constu(5)",
                       "DW_OP_constu", "DW_OP_bregx 1", "DW_OP_lit1 2",
                       "DW_OP_lit1 DW_OP_lit2", "DW_OP_deref_type 2, 12"):
            with self.subTest(source=source):
                with self.assertRaises(RuntimeError):
                    self.execute(source)

    def test_context_validation(self):
        cases = [snapshot(address_width=0), snapshot(address_width=True), snapshot(endianness="native"),
                 snapshot(memory={"0": 256}), snapshot(memory={"-1": 0}), snapshot(registers={"01": 1}),
                 snapshot(types={"1": ty(encoding="DW_ATE_numeric_string")}),
                 snapshot(types={"1": ty(bits=17, size=2)}),
                 snapshot(initial_stack=[{"value": 0, "type": 1}]),
                 snapshot(types={"1": ty(), "2": ty(encoding="DW_ATE_unsigned")}),
                 snapshot(entry={}), snapshot(debugaddr={}), snapshot(debugconst={}),
                 snapshot(initial_stack=[g(1 << 64)])]
        for width in (1, 8, 64, 128):
            cases.extend(snapshot(address_width=width, framebase=value)
                         for value in (-1, -(1 << (width - 1)), 1 << width,
                                       True, 1.0, "0", None))
            for value in (0, (1 << width) - 1):
                with self.subTest(width=width, framebase=value):
                    context, _ = dwarf.prepare_context(snapshot(address_width=width, framebase=value))
                    self.assertEqual(context,
                        f"ctx({width}, little, .Map, .Map, .Map, someInt({value}), "
                        "noInt, unspecified, .Map, 0, noInt)")
        for ctx in cases:
            with self.subTest(ctx=ctx):
                with self.assertRaises(ValueError):
                    dwarf.prepare_context(ctx)
        with self.assertRaises(ValueError):
            json.loads('{"memory": {}, "memory": {}}', object_pairs_hook=dwarf.unique_object)
        original = snapshot(types={"1": ty()}, initial_stack=[{"value": -1, "type": 1}])
        before = copy.deepcopy(original)
        dwarf.prepare_context(original)
        self.assertEqual(original, before)

    def test_cli_status_and_configuration(self):
        path = Path(self.temp.name) / "cli.dwarf"
        context = ROOT / "examples/expressions/context.json"
        for source, status, code, stack in [
            ("DW_OP_constu 42", "completed", 0, [g(42)]),
            ("DW_OP_drop", "incomplete", 1, []),
            ("DW_OP_addr 4096, DW_OP_deref_type 4 12", "completed", 0,
             [{"value": 42, "type": {"id": "cu0:int32"}}]),
        ]:
            path.write_text(annotated(source))
            process = subprocess.run([sys.executable, str(ROOT / "run.py"), str(path), "--context", str(context),
                                      "--definition", str(self.definition)], capture_output=True, text=True)
            self.assertEqual(process.returncode, code, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], status)
            self.assertEqual(result["stack"], stack)
            self.assertIn("configuration", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
