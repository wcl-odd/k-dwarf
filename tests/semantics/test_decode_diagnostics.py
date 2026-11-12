"""Observe K decoding evidence without implementing a Python DWARF decoder."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot


def apply(name, *args):
    return {"node": "KApply", "label": {"name": name}, "args": list(args)}


def number(value):
    return {"node": "KToken", "token": str(value)}


def state(raw, entries=(), *, end=None, start=0):
    block = apply("emptyBytes")
    for byte in reversed(raw):
        block = apply("byteCons", number(byte), block)
    code = apply("emptyInstructions")
    for offset, following in reversed(entries):
        code = apply("decodedInstruction", number(offset), apply("unusedOperation"), number(following), code)
    expression = apply("decodedExpression", number(start), number(len(raw) if end is None else end), code, block)
    return apply("evaluation", expression)


class DecodeDiagnosticObservationTests(unittest.TestCase):
    def test_partial_prefix_exposes_bytes_without_guessing_operand_shape(self):
        current = state([0x37, 0x0e, 0x01], [(0, 1)])
        before = copy.deepcopy(current)
        diagnostic = dwarf.decode_diagnostic(current, 1)
        self.assertEqual({key: diagnostic[key] for key in
                          ("position", "opcode_byte", "remaining_byte_count", "reason")},
                         {"position": 1, "opcode_byte": 0x0e, "remaining_byte_count": 2,
                          "reason": "no_complete_instruction"})
        self.assertEqual(current, before)
        self.assertNotIn("expected_bytes", diagnostic)

    def test_unknown_and_unterminated_encodings_are_not_claimed_invalid(self):
        for raw in ([0xff], [0x10, 0x80], [0x0e, 0x01]):
            with self.subTest(raw=raw):
                diagnostic = dwarf.decode_diagnostic(state(raw), 0)
                self.assertEqual(diagnostic["reason"], "no_complete_instruction")
                self.assertNotIn("invalid", diagnostic)
                self.assertNotIn("truncated_operand", diagnostic.values())

    def test_decoded_current_instruction_is_not_a_decoding_failure(self):
        current = state([0x37, 0x06, 0x0e, 0x01], [(0, 1), (1, 2)])
        self.assertIsNone(dwarf.decode_diagnostic(current, 0))
        self.assertIsNone(dwarf.decode_diagnostic(current, 1))
        self.assertIsNotNone(dwarf.decode_diagnostic(current, 2))

    def test_text_and_unavailable_byte_evidence_do_not_gain_a_diagnosis(self):
        for current in (state([], [(0, 1)], end=3), state([0x37], [(0, 1)], end=3),
                        state([256], end=1)):
            self.assertIsNone(dwarf.decode_diagnostic(current, 1 if current["args"][0]["args"][1]["token"] == "3" else 0))

    def test_arbitrary_core_gaps_and_operand_positions_are_not_decode_errors(self):
        for current, position in ((state([0]*4, [(0, 1), (2, 3)]), 1),
                                  (state([0]*4, [(0, 3)]), 1),
                                  (state([0]*4, [(0, 1)]), 2),
                                  (state([0]*4, [(1, 2)], start=1), 2)):
            self.assertIsNone(dwarf.decode_diagnostic(current, position))

    def test_end_and_completed_or_uninitialized_states_are_not_decode_errors(self):
        current = state([0x37, 0xff], [(0, 1)])
        self.assertIsNone(dwarf.decode_diagnostic(current, 2))
        self.assertIsNone(dwarf.decode_diagnostic(current, -1))
        self.assertIsNone(dwarf.decode_diagnostic({**current, "label": {"name": "finishedEvaluation"}}, 1))
        self.assertIsNone(dwarf.decode_diagnostic(apply("initGeneratedTopCell"), 0))


class DecodeDiagnosticIntegrationTests(DwarfTestCase):
    def raw(self, source, context=None, **options):
        path = Path(self.temp.name)/"diagnostic.hex"
        path.write_text(source)
        return dwarf.evaluate(path, snapshot() if context is None else context,
                              self.definition, input_format="hex", **options)

    def test_reached_truncated_operand_preserves_state_and_budget(self):
        before = self.raw("37 0e 01", depth=1)
        after = self.raw("37 0e 01", depth=10)
        self.assertEqual((after["status"], after["position"], after["end"], after["stack"], after["result"]),
                         ("incomplete", 1, 3, [g(7)], None))
        self.assertEqual(after["decode_error"], before["decode_error"])
        self.assertEqual(before["configuration"], after["configuration"])
        self.assertIsNone(after["stop_reason"])

    def test_missing_memory_and_valid_instruction_budget_stop_are_not_decode_errors(self):
        missing = self.raw("37 06 0e 01", depth=10)
        self.assertEqual((missing["status"], missing["position"]), ("incomplete", 1))
        self.assertNotIn("decode_error", missing)
        budget = self.raw("37 38 22", depth=1)
        self.assertEqual((budget["status"], budget["position"]), ("incomplete", 1))
        self.assertNotIn("decode_error", budget)

    def test_skipped_bad_suffix_does_not_prevent_normal_completion(self):
        result = self.raw("2f 02 00 ff 96", snapshot(initial_stack=[g(7)]), depth=10)
        self.assertEqual((result["status"], result["result"]), ("completed", {"kind": "memory", "address": 7}))
        self.assertNotIn("decode_error", result)

    def test_nested_failure_uses_active_child_byte_evidence(self):
        result = self.raw("98 20 00 9f", snapshot(die_locations={"32": {"bytes": [0x37, 0x0e, 0x01]}}), depth=10)
        self.assertEqual((result["status"], result["position"], result["end"], result["stack"]),
                         ("incomplete", 1, 3, [g(7)]))
        self.assertEqual(result["decode_error"]["opcode_byte"], 0x0e)
        self.assertEqual(result["decode_error"]["remaining_byte_count"], 2)
        self.assertEqual(dwarf.label(dwarf.root_inputs(result["configuration"]["term"])[0]), "decodedExpression")

    def test_cli_exposes_diagnostic_and_keeps_exit_one(self):
        expression = Path(self.temp.name)/"cli.hex"
        context = Path(self.temp.name)/"context.json"
        expression.write_text("0e 01\n")
        context.write_text(json.dumps(snapshot()))
        process = subprocess.run([sys.executable, str(ROOT/"run.py"), str(expression),
                                  "--format", "hex", "--context", str(context),
                                  "--definition", str(self.definition), "--depth", "10"],
                                 capture_output=True, text=True, timeout=45)
        self.assertEqual(process.returncode, 1, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual((result["status"], result["position"], result["result"]), ("incomplete", 0, None))
        self.assertEqual(result["decode_error"]["reason"], "no_complete_instruction")
        self.assertEqual(result["decode_error"]["remaining_byte_count"], 2)
        self.assertIsNone(result["stop_reason"])
