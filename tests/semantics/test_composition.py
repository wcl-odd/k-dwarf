"""Independent fragments, source bounds and K-owned object assembly."""
from pathlib import Path
import json
import subprocess
import sys
from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty


class CompositionTests(DwarfTestCase):
    def input(self, source, mode="hex", ctx=None, **options):
        path = Path(self.temp.name) / ("composition." + mode)
        path.write_text(source)
        return dwarf.evaluate(path, ctx or snapshot(architecture="x86_64"),
                              self.definition, input_format=mode, **options)

    def assembled(self, source, bits, mode="hex", ctx=None, **options):
        result = self.input(source, mode, ctx, **options)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["result"]["kind"], "composite")
        self.assertEqual(result["result"]["bits"], bits)
        self.assertEqual(result["result"]["bit_size"], len(bits))
        self.assertEqual(result["stack"], [])
        return result

    def test_implicit_bytes_two_entries_and_arbitrary_stack(self):
        for raw, text, data in [
            ("9e 00", "-3: DW_OP_implicit_value [], 0", []),
            ("9e 02 11 22", "0x10: DW_OP_implicit_value [0x11 34], 0x20", [17,34]),
            ("9e 80 00", "0: DW_OP_implicit_value [], 8", []),
            ("9e 0a 00 01 02 03 04 05 06 07 08 09", "0: DW_OP_implicit_value [0 1 2 3 4 5 6 7 8 9], 12", list(range(10))),
        ]:
            for mode, source in [("hex", raw), ("text", text)]:
                ctx = snapshot(initial_stack=[g(-1)])
                before = self.input(source, mode, ctx, depth=0)
                result = self.input(source, mode, ctx, depth=1)
                self.assertEqual(result["result"], {"kind":"bytes", "bytes":data})
                self.assertEqual(result["stack"], [g(-1)])
                self.assert_initialized_inputs_preserved(before, result, ctx)

    def test_piece_order_metadata_and_target_profiles(self):
        raw = "9e 01 11 93 01 9e 01 22 93 01"
        text = "-5: DW_OP_implicit_value [0x11], -4: DW_OP_piece 1, -3: DW_OP_implicit_value [0x22], -2: DW_OP_piece 1, 0"
        for target, width in [("i386",32),("x86_64",64),("aarch64",64)]:
            ctx = snapshot(address_width=width, architecture=target)
            for mode, source in [("hex",raw),("text",text)]:
                r=self.assembled(source,"0010001000010001",mode,ctx)
                self.assertEqual(r['result']['pieces'], [
                    {'kind':'piece','byte_size':1,'location':{'kind':'bytes','bytes':[17]}},
                    {'kind':'piece','byte_size':1,'location':{'kind':'bytes','bytes':[34]}}])

    def test_mixed_sources_and_clear_entire_stack(self):
        ctx=snapshot(architecture='x86_64',registers={'0':0x1234}, memory={'256':0xab,'257':0xcd})
        raw='50 93 01 0a 00 01 93 02 33 34 9f 9d 03 00'
        r=self.assembled(raw,'100110011011010101100110100',ctx=ctx)
        self.assertEqual([p['location']['kind'] for p in r['result']['pieces']],['register','memory','value'])
        # Both values from the preceding fragment must disappear; drop cannot use them.
        bad=self.input('31 32 93 00 13 93 00')
        self.assertEqual((bad['status'],bad['position'],bad['stack']),('incomplete',4,[]))

    def test_bit_offsets_memory_and_partial_unknown(self):
        self.assembled('50 9d 04 04','1010',ctx=snapshot(architecture='aarch64',registers={'0':0xab}))
        self.assembled('9e 02 ab cd 9d 09 04','011011010')
        self.assembled('0: DW_OP_implicit_value [0xAB 0xCD], 0x4: DW_OP_bit_piece 0x9 0x4, 0x7', '011011010', 'text')
        self.assembled('09 ff 9f 9d 03 01','111')
        self.assembled('0a 00 01 9d 0c 04','????????1010',ctx=snapshot(architecture='x86_64',memory={'256':0xab}))
        self.assembled('50 93 01','????????',ctx=snapshot(architecture='i386',address_width=32))
        self.assembled('93 01 9d 03 7f','?'*11)
        self.assembled('0a 00 01 93 03','10111011????????10101010',ctx=snapshot(architecture='x86_64',memory={'256':0xaa,'258':0xbb}))

    def test_zero_size_and_missing_data_are_distinct_from_deref_failure(self):
        for raw in ('93 00','50 93 00','9e 00 93 00','9d 00 7f'):
            self.assembled(raw,'')
        self.assembled('31 1f 93 01', '?'*8, ctx=snapshot(architecture='x86_64', memory={str((1<<64)-1):255}))
        self.assembled('0e ff ff ff ff ff ff ff ff 93 02', '????????10101010', ctx=snapshot(architecture='x86_64', memory={str((1<<64)-1):170, '0':187}))
        failure=self.input('0a 00 01 06 93 01')
        self.assertEqual((failure['status'],failure['position'],failure['stack']),('incomplete',3,[g(256)]))
        self.assertIsNone(failure['result'])

    def test_source_bounds_nonempty_empty_stack_and_dangling_suffix(self):
        for raw, position, stack in [
            ('50 93 09',1,[]),('9e 01 01 93 02',3,[]),
            ('31 9f 9d 02 3f',2,[g(1)]),('31 13 93 01',2,[]),
            ('96 93 01',1,[]),('93 00 31',3,[g(1)]),
            ('50 96 93 01',0,[]),('96 50 93 01',1,[]),
            ('9e 00 96 93 01',0,[]),('31 9f 96 93 01',1,[g(1)]),
        ]:
            with self.subTest(raw=raw):
                r=self.input(raw)
                self.assertEqual((r['status'],r['position'],r['stack']),('incomplete',position,stack))
                self.assertIsNone(r['result'])
        r=self.input('31 93 01',ctx=snapshot(architecture='x86_64',initial_stack=[g(9)]))
        self.assertEqual((r['status'],r['position'],r['stack']),('incomplete',1,[g(9),g(1)]))
        # Memory/explicit-value fragments do not depend on an unstated ABI.
        r=self.input('31 9f 93 01',ctx=snapshot())
        self.assertEqual((r['status'],r['result']['bits']),('completed','00000001'))
        ctx=snapshot(architecture='x86_64',types={'1':ty('tiny','DW_ATE_unsigned',3,1)}, initial_stack=[])
        # Typed stack-value source has only its declared bits, not A bits.
        ctx['memory']={'0':7}
        self.assembled('30 a6 01 01 9f 9d 03 00','111',ctx=ctx)

    def test_truncation_decode_lengths_and_payload_boundaries(self):
        for raw in ('9e','9e 80','9e 02 11','93','93 80','9d','9d 01','9d 01 80'):
            r=self.input('37 '+raw)
            self.assertEqual((r['status'],r['position'],r['stack']),('incomplete',1,[g(7)]))
        r=self.input('2f 02 00 9e 02 aa bb') # target 5 is inside the byte block
        self.assertEqual((r['status'],r['position']),('incomplete',0))
        self.assembled('9e 01 aa 93 81 00','10101010')
        for source in ('0: DW_OP_piece -1, 1','0: DW_OP_bit_piece 1 -1, 1','0: DW_OP_implicit_value [256], 1'):
            r=self.input(source,'text')
            self.assertEqual((r['status'],r['position']),('incomplete',0))

    def test_local_branches_loops_and_execution_budget(self):
        # Jump to the separator is valid; crossing it or jumping into an older fragment is not.
        self.assembled('31 2f 01 00 13 93 00','')
        for raw, pc, stack in [('31 2f 02 00 93 00',1,[g(1)]),
                                ('93 00 2f fb ff 93 00',2,[])]:
            r=self.input(raw)
            self.assertEqual((r['status'],r['position'],r['stack']),('incomplete',pc,stack))
        r=self.input('2f fd ff 93 00',depth=3)
        self.assertEqual((r['status'],r['position']),('incomplete',0))
        for depth in (0,1,2,3):
            r=self.input('31 9f 93 01',depth=depth)
            self.assertEqual(r['status'],'completed' if depth==3 else 'incomplete')
        for source in ('9e 01 11','50 93 01','93 01'):
            r=self.input(source,depth=0)
            self.assertEqual(r['status'],'incomplete')
            self.assertIsNone(r['result'])

    def test_fixed_inputs_atomic_failure_and_nonzero_offsets(self):
        source='0x10: DW_OP_implicit_value [0x11], 0x20: DW_OP_piece 2, 0x30'
        ctx=snapshot(architecture='aarch64',registers={'0':-1},memory={'1':128})
        before=self.input(source,'text',ctx,depth=1)
        after=self.input(source,'text',ctx)
        self.assert_preserved(before, after)
        self.assertEqual(self.fixed_inputs(before),self.fixed_inputs(after))
        self.assembled('-5: DW_OP_piece 0, 0','','text',ctx)
        for invalid in (snapshot(architecture='invalid'),snapshot(architecture='i386'),snapshot(architecture='aarch64',endianness='big')):
            with self.assertRaises(ValueError): dwarf.prepare_context(invalid)

    def test_cli_complete_incomplete_and_input_error(self):
        ctx=Path(self.temp.name)/'context.json';ctx.write_text(json.dumps(snapshot(architecture='aarch64')))
        path=Path(self.temp.name)/'cli.hex'
        for raw, code in [('9e 00',0),('93 01',0),('9e 02 11',1),('zz',2)]:
            path.write_text(raw)
            p=subprocess.run([sys.executable,str(ROOT/'run.py'),str(path),'--format','hex','--context',str(ctx),'--definition',str(self.definition)],capture_output=True,text=True)
            self.assertEqual(p.returncode,code,p.stderr)
