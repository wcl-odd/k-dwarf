"""Floating external sources, object transport and atomic failure scenes."""
from test_basic import DwarfTestCase, snapshot, ty, g
from test_floating import FORMATS, ctx, v


class FloatingContextTests(DwarfTestCase):
    def test_wide_registers_address_spaces_value_and_pieces(self):
        for w,(one,*_) in FORMATS.items():
            record=ty(f'f{w}','DW_ATE_float',w,w//8)
            context=snapshot(address_width=32,types={'1':record},registers={'0':one},register_widths={'0':w})
            result=self.complete('DW_OP_regval_type 0 1, DW_OP_stack_value',[v(one,w)],context)
            self.assertEqual(result['result'],{'kind':'value',**v(one,w)})
            data=list(one.to_bytes(w//8,'little'))
            context=snapshot(address_width=32,types={'1':record},address_spaces={'1':{str(i):b for i,b in enumerate(data)}})
            self.complete(f'DW_OP_lit1, DW_OP_lit0, DW_OP_xderef_type {w//8} 1, DW_OP_stack_value',[v(one,w)],context)
            context=snapshot(architecture='x86_64',types={'1':record})
            block=' '.join(str(b) for b in data)
            result=self.execute(f'DW_OP_const_type 1 [{block}], DW_OP_stack_value, DW_OP_piece {w//8}',context)
            self.assertEqual(result['result']['bits'],f'{one:0{w}b}')
            self.assertEqual(result['stack'],[])
            context=ctx(w,[one])
            scalar=self.execute('DW_OP_neg',context,purpose='value')
            self.assertEqual(scalar['result'],{'kind':'scalar',**v(one|(1 << (w-1)),w)})

    def test_conversion_and_integer_precondition_failures_are_atomic(self):
        for op,context in [('DW_OP_convert 1',ctx(32,[0x7fc00000])),
            ('DW_OP_convert 2',ctx(32,[0xbf800000])),
            ('DW_OP_convert 3',ctx(32,[0x3f800000])),
            ('DW_OP_reinterpret 64',ctx(32,[0x3f800000])),
            ('DW_OP_plus_uconst 1',ctx(32,[0x3f800000]))]:
            program='DW_OP_lit1, DW_OP_drop, '+op
            before=self.execute(program,context,depth=2)
            stopped=self.incomplete(program,context,position=2)
            self.assert_preserved(before,stopped)

    def test_unrecognized_encodings_do_not_fall_back_to_integer(self):
        for encoding,width in [('DW_ATE_float',16),('DW_ATE_decimal_float',64),('DW_ATE_unknown_255',32)]:
            context=snapshot(raw_types={'1':{'id':'unsupported','tag':'DW_TAG_base_type','encoding':encoding,
                'bit_width':width,'byte_size':width//8}},initial_stack=[g(42)])
            result=self.incomplete('DW_OP_convert 1',context)
            self.assertEqual(result['stack'],[g(42)])
            self.assertEqual(result['stop_reason'], None)

    def test_float_address_operands_rejected_before_memory_read(self):
        for w in FORMATS:
            context=ctx(w,[0],memory={str(i):b for i,b in enumerate([0,0,128,63,0,0,0,0])})
            for op in ['DW_OP_deref','DW_OP_deref_size 1','DW_OP_deref_type 4 32']:
                program='DW_OP_lit1, DW_OP_drop, '+op
                before=self.execute(program,context,depth=2)
                stopped=self.incomplete(program,context,position=2)
                self.assert_preserved(before,stopped)
                self.assertEqual(stopped['stop_reason'], None)
