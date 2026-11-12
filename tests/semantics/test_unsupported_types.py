"""Unsupported numeric formats stay metadata, never integer operands."""
import json
from pathlib import Path
import subprocess
import sys

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty


class UnsupportedTypeTests(DwarfTestCase):
    def raw(self, source, ctx, **kwargs):
        path = Path(self.temp.name)/'unsupported.hex'
        path.write_text(source)
        return dwarf.evaluate(path, ctx, self.definition, input_format='hex', **kwargs)

    def context(self, **extra):
        return snapshot(raw_types={'1': {'id': 'raw-f16', 'tag': 'DW_TAG_base_type',
            'encoding': 'DW_ATE_float', 'bit_width': 16, 'byte_size': 2}},
            registers={'0': 0x40400000}, memory={str(i): b for i, b in enumerate([0, 0, 64, 64])},
            **extra)

    def test_strict_float_types_and_initial_values_are_input_errors(self):
        self.assertEqual(len(dwarf.ENCODINGS), 10)
        for width in (16, 24, 96, 256):
            for initial in ([], [{'value': 0, 'type': 1}]):
                with self.subTest(width=width, initial=bool(initial)):
                    with self.assertRaisesRegex(ValueError, 'unsupported floating format'):
                        dwarf.prepare_context(snapshot(types={'1': ty('f', 'DW_ATE_float', width, width//8)},
                                                       initial_stack=initial))
        path=Path(self.temp.name)/'empty.dwarf'; path.write_text('0')
        ctx=Path(self.temp.name)/'strict.json'
        ctx.write_text(json.dumps(snapshot(types={'1': ty('f', 'DW_ATE_float', 16, 2)})))
        proc=subprocess.run([sys.executable, str(ROOT/'run.py'), str(path), '--context', str(ctx),
            '--definition', str(self.definition)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn('unsupported floating format', proc.stderr)

    def test_raw_float_metadata_does_not_block_unrelated_integer_execution(self):
        ctx=self.context(initial_stack=[g(41)])
        source='DW_OP_lit1, DW_OP_plus, DW_OP_stack_value'
        before=self.execute(source, ctx, depth=1)
        result=self.complete(source, [g(42)], ctx)
        self.assertEqual(result['result'], {'kind': 'value', **g(42)})
        self.assertEqual(self.fixed_inputs(before), self.fixed_inputs(result))

    def test_typed_operations_reject_raw_float_without_consuming_the_scene(self):
        ctx=self.context(initial_stack=[g(41)])
        fixtures=[('DW_OP_const_type 1 [0 0 64 64]', 'a4 01 04 00 00 40 40', 2, [g(41)]),
                  ('DW_OP_regval_type 0 1', 'a5 00 01', 2, [g(41)]),
                  ('DW_OP_convert 1', 'a8 01', 2, [g(41)]),
                  ('DW_OP_reinterpret 1', 'a9 01', 2, [g(41)]),
                  ('DW_OP_lit0, DW_OP_deref_type 4 1', '30 a6 04 01', 3, [g(41), g(0)])]
        for text, raw, position, stack in fixtures:
            with self.subTest(text=text):
                program='DW_OP_lit1, DW_OP_drop, '+text
                before=self.execute(program, ctx, depth=position)
                stopped=self.incomplete(program, ctx, position=position)
                self.assert_preserved(before, stopped)
                self.assertEqual(stopped['stack'], stack)
                self.assertEqual(stopped['stop_reason'], None)
                raw_before=self.raw('31 13 '+raw, ctx, depth=position)
                raw_stopped=self.raw('31 13 '+raw, ctx)
                self.assert_preserved(raw_before, raw_stopped)
                self.assertEqual((raw_stopped['status'], raw_stopped['position'], raw_stopped['stack']),
                                 ('incomplete', position, stack))
                self.assertEqual(raw_stopped['stop_reason'], None)
                self.assertIsNone(raw_stopped['result'])

    def test_uninterpreted_object_bytes_and_lazy_locations_are_preserved(self):
        ctx=self.context(architecture='x86_64')
        result=self.execute('DW_OP_implicit_value [0 0 64 64], DW_OP_piece 4', ctx)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result']['bits'], f'{0x40400000:032b}')
        self.assertEqual(result['stack'], [])
        address=self.execute('DW_OP_lit0', ctx)
        self.assertEqual(address['result'], {'kind': 'memory', 'address': 0})
        register=self.execute('DW_OP_regx 999', ctx)
        self.assertEqual(register['result'], {'kind': 'register', 'register': 999})
