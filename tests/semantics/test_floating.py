"""Floating bit-pattern fixtures; expected encodings are independent constants.

No Python arithmetic is used to execute an OP. Values in the JSON interface
are the stored bits, and different base-type identities remain distinct.
"""
from test_basic import DwarfTestCase, snapshot, ty, g

FORMATS = {
    32: (0x3f800000, 0x40000000, 0x40400000, 0x40c00000, 0x3f000000, 0x7f800000, 0x7fc00000),
    64: (0x3ff0000000000000, 0x4000000000000000, 0x4008000000000000, 0x4018000000000000,
         0x3fe0000000000000, 0x7ff0000000000000, 0x7ff8000000000000),
    80: (0x3fff8000000000000000, 0x40008000000000000000, 0x4000c000000000000000,
         0x4001c000000000000000, 0x3ffe8000000000000000, 0x7fff8000000000000000, 0x7fffc000000000000000),
    128: (0x3fff0000000000000000000000000000, 0x40000000000000000000000000000000,
          0x40008000000000000000000000000000, 0x40018000000000000000000000000000,
          0x3ffe0000000000000000000000000000, 0x7fff0000000000000000000000000000,
          0x7fff8000000000000000000000000000),
}


def v(n, w):
    return {'value': n, 'type': {'id': f'f{w}'}}


def ctx(w, values, **extra):
    types = {str(width): ty(f'f{width}', 'DW_ATE_float', width, width//8) for width in FORMATS}
    types.update({'1': ty('s32', 'DW_ATE_signed', 32, 4),
                  '2': ty('u32', 'DW_ATE_unsigned', 32, 4),
                  '3': ty('bool', 'DW_ATE_boolean', 8, 1)})
    return snapshot(types=types, initial_stack=[g(17)]+[{'value': n, 'type': w} for n in values], **extra)


class FloatingTests(DwarfTestCase):
    def execute(self, text, context=None, **kwargs):
        out=super().execute(text,context,**kwargs)
        import os, json
        from pathlib import Path
        evidence=os.environ.get('DWARF_FLOAT_EVIDENCE')
        if evidence:
            directory=Path(evidence)/self._testMethodName
            directory.mkdir(parents=True,exist_ok=True)
            index=len(list(directory.glob('*.json')))
            (directory/f'{index:04d}.json').write_text(json.dumps({
                'test':self.id(),'text':text,'context':context,'options':kwargs,'output':out},indent=2)+'\n')
        return out

    def check(self, op, w, operands, expected):
        return self.complete('DW_OP_'+op+', DW_OP_stack_value', [g(17), v(expected, w)], ctx(w, operands))

    def test_four_formats_arithmetic_and_unary(self):
        for w, (one,two,three,six,half,inf,nan) in FORMATS.items():
            with self.subTest(width=w):
                sign=1 << (w-1)
                for op, args, expected in [('plus',[one,two],three), ('minus',[three,one],two),
                    ('mul',[two,three],six), ('div',[one,two],half),
                    ('abs',[one|sign],one), ('neg',[one],one|sign)]:
                    self.check(op,w,args,expected)

    def test_all_float_comparisons_and_nan(self):
        for w, (one,two,three,six,half,inf,nan) in FORMATS.items():
            for op, expected in [('eq',0),('ne',1),('lt',1),('le',1),('gt',0),('ge',0)]:
                for operands, result in [([one,two],expected),([nan,one],int(op=='ne'))]:
                    with self.subTest(width=w, op=op, nan=operands[0]==nan):
                        out=self.complete('DW_OP_'+op+', DW_OP_stack_value',[g(17),g(result)],ctx(w,operands))
                        self.assertEqual(out['result'], {'kind':'value',**g(result)})
            self.complete('DW_OP_eq',[g(17),g(1)],ctx(w,[0,1 << (w-1)]))

    def test_ieee_specials_subnormal_rounding_and_overflow(self):
        for w, (one,two,three,six,half,inf,nan) in FORMATS.items():
            sign=1 << (w-1)
            for op,args,expected in [('div',[one,0],inf),('div',[0,0],nan),('mul',[inf,0],nan),
                ('minus',[inf,inf],nan),('plus',[sign,sign],sign),('neg',[0],sign),
                ('plus',[1,1],2),('div',[1,two],0),
                ('mul',[(0x7ffeffffffffffffffff if w==80 else inf-1),two],inf)]:
                with self.subTest(width=w,op=op,args=args):self.check(op,w,args,expected)
        # Exactly halfway between adjacent binary32 values, ties choose even.
        self.check('plus',32,[0x3f800000,0x33800000],0x3f800000)
        self.check('plus',32,[0x3f800001,0x33800000],0x3f800002)
        self.check('div',32,[0x3f800000,0x40400000],0x3eaaaaab)

    def test_conversions_and_reinterpretation(self):
        for w, (one,two,three,six,half,inf,nan) in FORMATS.items():
            self.complete(f'DW_OP_convert {w}, DW_OP_stack_value',[g(17),v(three,w)],{**ctx(w,[]),'initial_stack':[g(17),{'value':3,'type':1}]})
            self.complete('DW_OP_convert 1, DW_OP_stack_value',[g(17),{'value':3,'type':{'id':'s32'}}],ctx(w,[three]))
            for target in FORMATS:
                self.complete(f'DW_OP_convert {target}',[g(17),v(FORMATS[target][0],target)],ctx(w,[one]))
            # Same width conversion keeps payload rather than canonicalizing NaN.
            self.complete(f'DW_OP_convert {w}',[g(17),v(nan+123,w)],ctx(w,[nan+123]))
            for bits in [inf,nan,one|(1 << (w-1))]:
                self.incomplete('DW_OP_convert 2',ctx(w,[bits]))
        self.complete('DW_OP_convert 1',[g(17),{'value':-1,'type':{'id':'s32'}}],ctx(32,[0xbfc00000]))
        self.complete('DW_OP_reinterpret 2',[g(17),{'value':0x3f800000,'type':{'id':'u32'}}],ctx(32,[0x3f800000]))
        self.complete('DW_OP_reinterpret 32',[g(17),v(0x3f800000,32)],{**ctx(32,[]), 'initial_stack':[g(17),{'value':0x3f800000,'type':2}]})
        self.incomplete('DW_OP_reinterpret 64',ctx(32,[0x3f800000]))
        self.incomplete('DW_OP_convert 3',ctx(32,[0x3f800000]))

    def test_integer_only_ops_stop_and_preserve_all_state(self):
        for op in ['and','or','xor','mod','shl','shr','shra','not','plus_uconst 1']:
            binary=op not in ['not','plus_uconst 1']
            context=ctx(32,[0x3f800000]*(2 if binary else 1))
            before=self.execute('DW_OP_'+op,context,depth=0)
            stopped=self.incomplete('DW_OP_'+op,context)
            if not self.definition.name.startswith('haskell'):
                self.assert_preserved(before,stopped)
            self.assertEqual(stopped['stack'],[g(17)]+[v(0x3f800000,32)]*(2 if binary else 1))
            self.assertEqual(stopped['stop_reason'], None)

    def test_typed_transport_raw_decode_and_endianness(self):
        for w, (one,*_) in FORMATS.items():
            for order in ['little','big']:
                data=list(one.to_bytes(w//8,order));block=' '.join(str(b) for b in data)
                context=ctx(w,[],endianness=order,memory={str(i):b for i,b in enumerate(data)})
                self.complete(f'DW_OP_const_type {w} [{block}]',[g(17),v(one,w)],context)
                self.complete(f'DW_OP_lit0, DW_OP_deref_type {w//8} {w}',[g(17),v(one,w)],context)
            raw=self.temp.name+'/float.hex'
            from pathlib import Path
            from test_basic import dwarf
            # ref=1 ULEB, block length and byte order have independently fixed values.
            context=snapshot(types={'1':ty(f'f{w}','DW_ATE_float',w,w//8)})
            Path(raw).write_text('a4 01 '+f'{w//8:02x} '+' '.join(f'{b:02x}' for b in one.to_bytes(w//8,'little'))+' 9f')
            out=dwarf.evaluate(raw,context,self.definition,input_format='hex')
            self.assertEqual(out['result'],{'kind':'value',**v(one,w)})
            self.assertEqual(out['position'],w//8+4)
        context=ctx(32,[],registers={'0':0x3f800000})
        self.complete('DW_OP_regval_type 0 32, DW_OP_dup, DW_OP_swap, DW_OP_drop',[g(17),v(0x3f800000,32)],context)
        # Two identities with identical format must not compare as the same type.
        context=ctx(32,[0x3f800000]);context['types']['99']=ty('other-f32','DW_ATE_float',32,4)
        context['initial_stack'].append({'value':0x3f800000,'type':99})
        self.incomplete('DW_OP_eq',context)

    def test_raw_float_metadata_resolves_and_budget_edges(self):
        context=snapshot(raw_types={'1':{'id':'raw-f32','tag':'DW_TAG_base_type','encoding':'DW_ATE_float','bit_width':32,'byte_size':4}})
        self.complete('DW_OP_const_type 1 [0 0 128 63], DW_OP_stack_value',
                      [{'value':0x3f800000,'type':{'id':'raw-f32'}}],context)
        for depth,status,pos in [(0,'incomplete',0),(1,'incomplete',1),(2,'completed',2)]:
            result=self.execute('DW_OP_neg, DW_OP_stack_value',ctx(32,[0]),depth=depth)
            self.assertEqual(result['status'],status)
            self.assertEqual(result['position'],pos)
            if depth==0:self.assertIsNone(result['result'])

    def test_generic_unsigned_source_to_float(self):
        from pathlib import Path
        from test_basic import dwarf
        # Independently fixed encodings of +255 in the four supported formats.
        encodings = {32: 0x437f0000, 64: 0x406fe00000000000,
                     80: 0x4006ff00000000000000,
                     128: 0x4006fe00000000000000000000000000}
        for width, bits in encodings.items():
            for number in (255, -1):
                with self.subTest(width=width, representative=number):
                    context = {**ctx(width, [], address_width=8), "initial_stack": [g(17), g(number)]}
                    self.complete(f"DW_OP_convert {width}, DW_OP_stack_value", [g(17), v(bits, width)], context)
                    path = Path(self.temp.name) / "generic-float.hex"
                    ref = {32: "20", 64: "40", 80: "50", 128: "80 01"}[width]
                    path.write_text(f"a8 {ref} 9f")
                    result = dwarf.evaluate(path, context, self.definition, input_format="hex")
                    self.assertEqual(result["result"], {"kind": "value", **v(bits, width)})
                    self.assertEqual(result["stack"], [g(17), v(bits, width)])
        # A=32: signed literal -1 first becomes 0xffffffff:g, then +4294967295.0.
        context = ctx(64, [], address_width=32)
        expected = v(0x41efffffffe00000, 64)
        self.complete("DW_OP_const1s -1, DW_OP_convert 64, DW_OP_stack_value", [g(17), expected], context)
        path = Path(self.temp.name) / "generic-float.hex"
        path.write_text("09 ff a8 40 9f")
        result = dwarf.evaluate(path, context, self.definition, input_format="hex")
        self.assertEqual(result["result"], {"kind": "value", **expected})
        # An explicitly signed source is still negative.
        context["initial_stack"] = [g(17), {"value": -1, "type": 1}]
        self.complete("DW_OP_convert 64, DW_OP_stack_value", [g(17), v(0xbff0000000000000, 64)], context)
