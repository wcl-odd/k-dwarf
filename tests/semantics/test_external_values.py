"""Index/object contexts and ordinary expression value results are independent."""
from pathlib import Path
from test_basic import DwarfTestCase, dwarf, g, snapshot, ty

class ExternalValueTests(DwarfTestCase):
    def raw(self, source, ctx=None, **options):
        path=Path(self.temp.name)/'input.hex'
        path.write_text(source)
        return dwarf.evaluate(path, ctx or snapshot(), self.definition, input_format='hex', **options)

    def test_indices_object_and_two_inputs(self):
        ctx=snapshot(address_width=32, debug_addr={'0':0,'1':2**80+42}, debug_addr_load_bias=-2, object_address=0)
        text=self.execute('DW_OP_addrx 1, DW_OP_constx 1, DW_OP_push_object_address',ctx)
        raw=self.raw('a1 81 00 a2 01 97',ctx)
        self.assertEqual(text['stack'],[g(40),g(42),g(0)])
        self.assertEqual(text['stack'],raw['stack'])
        self.assertEqual(raw['position'],6)
        self.assertEqual(text['result'],raw['result'])
        huge=2**70
        ctx=snapshot(debug_addr={str(huge):9})
        self.assertEqual(self.execute(f'DW_OP_addrx {huge}',ctx)['stack'],[g(9)])
        self.assertEqual(self.raw('a1 80 80 80 80 80 80 80 80 80 80 01',ctx)['stack'],[g(9)])

    def test_missing_or_invalid_operation_is_atomic(self):
        for op in ('DW_OP_addrx 1','DW_OP_constx 1','DW_OP_push_object_address','DW_OP_addrx -1','DW_OP_constx -1'):
            before=self.execute('DW_OP_lit3, '+op,depth=1)
            after=self.incomplete('DW_OP_lit3, '+op,position=1)
            self.assert_preserved(before, after)
        for raw in ('33 a1','33 a1 80','33 a2 80','33 ff'):
            before=self.raw(raw,depth=1)
            after=self.raw(raw)
            self.assert_preserved(before, after)

    def test_value_mode_and_budget(self):
        ctx=snapshot(initial_stack=[g(7)])
        r=self.execute('',ctx,purpose='value')
        self.assertEqual(r['result'],{'kind':'scalar',**g(7)})
        self.assertEqual(self.execute('',purpose='value')['status'],'incomplete')
        results=[self.raw('31 32',depth=i,purpose='value') for i in (0,1,2,3)]
        self.assertEqual([r['status'] for r in results],['incomplete']*3+['completed'])
        self.assertEqual(results[-1]['result'],{'kind':'scalar',**g(2)})
        self.assertEqual(results[-1]['stack'],[g(1),g(2)])
        self.assertEqual(self.fixed_inputs(results[1]),self.fixed_inputs(results[-1]))
        for source in ('50','9e 00','31 9f','93 00'):
            self.assertEqual(self.raw(source,ctx,purpose='value')['status'],'incomplete')
        ctx=snapshot(types={'1':ty('wide','DW_ATE_unsigned',129,17)},initial_stack=[{'value':2**128,'type':1}])
        self.assertEqual(self.execute('',ctx,purpose='value')['result'],{'kind':'scalar','value':2**128,'type':{'id':'wide'}})

    def test_context_errors(self):
        for extra in ({'debug_addr':{'01':1}}, {'debug_addr':{'0':-1}}, {'debug_addr_load_bias':True}, {'object_address':-1}):
            with self.assertRaises(ValueError): dwarf.prepare_context(snapshot(**extra))
        with self.assertRaises(ValueError): self.execute('',purpose='invalid')

    def test_large_sparse_context_keeps_complete_configuration(self):
        ctx=snapshot(memory={str(i):i%256 for i in range(4096)})
        r=self.execute('DW_OP_lit1',ctx,purpose='value')
        self.assertEqual(r['result'],{'kind':'scalar',**g(1)})
        self.assertIsNotNone(dwarf.find_cell(r['configuration']['term'],'expr'))
        self.assertIsNone(dwarf.find_cell(r['configuration']['term'],'absent'))
