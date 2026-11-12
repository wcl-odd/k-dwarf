"""K-owned input parsing and DWARF 5 byte decoding; fixtures are explicit bytes."""

import json
from pathlib import Path
import re
import subprocess
import sys

from test_basic import DwarfTestCase, ROOT, dwarf, g, snapshot, ty


class DecodingTests(DwarfTestCase):
    def input(self, source, mode="text", ctx=None, **kwargs):
        path = Path(self.temp.name) / ("input." + mode)
        path.write_text(source)
        return dwarf.evaluate(path, snapshot() if ctx is None else ctx,
                              self.definition, input_format=mode, **kwargs)

    def success(self, source, values, mode="text", ctx=None, end=None):
        result = self.input(source, mode, ctx)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["stack"], values)
        self.assertEqual(result["position"], result["end"])
        if end is not None:
            self.assertEqual(result["end"], end)
        return result

    def test_all_111_raw_and_text_names(self):
        # Each fixture provides concrete bytes, independently of the production
        # decoder. Counting fixture bytes assigns text offsets; it is not encoding.
        chunks, expected = [], []
        def emit(text, raw):
            chunks.append((text, raw))
        for n in range(32):
            emit(f"DW_OP_lit{n}", f"{0x30+n:02x}")
            expected.append(g(n))
        for name, raw, value in [
            ("const1u 7", "08 07", 7), ("const1s -7", "09 f9", (1<<64)-7),
            ("const2u 7", "0a 07 00", 7), ("const2s -7", "0b f9 ff", (1<<64)-7),
            ("const4u 7", "0c 07 00 00 00", 7), ("const4s -7", "0d f9 ff ff ff", (1<<64)-7),
            ("const8u 7", "0e 07 00 00 00 00 00 00 00", 7),
            ("const8s -7", "0f f9 ff ff ff ff ff ff ff", (1<<64)-7),
            ("constu 7", "10 07", 7), ("consts -7", "11 79", (1<<64)-7),
            ("addr 17", "03 11 00 00 00 00 00 00 00", 17),
            ("fbreg -4", "91 7c", 1996),
        ]:
            emit("DW_OP_"+name, raw)
            expected.append(g(value))
        for n in range(32):
            emit(f"DW_OP_breg{n} -3", f"{0x70+n:02x} 7d")
            expected.append(g(997+n))
        emit("DW_OP_bregx 40 -8", "92 28 78")
        expected.append(g(4992))
        typed = {"value":-2, "type":{"id":"cu0:s16"}}
        for text, raw, value in [("DW_OP_deref","06",g(65534)),
                                  ("DW_OP_deref_size 2","94 02",g(65534)),
                                  ("DW_OP_deref_type 2 12","a6 02 0c",typed)]:
            emit("DW_OP_addr 256", "03 00 01 00 00 00 00 00 00")
            emit(text, raw)
            expected.append(value)
        for text, raw in [("dup","12"),("over","14"),("pick 2","15 02"),
                          ("drop","13"),("swap","16"),("rot","17")]:
            emit("DW_OP_"+text,raw)
        expected += [typed]*2
        for prefix, raw_prefix, op, raw_op, value in [
            ("DW_OP_consts -7","11 79","abs","19",7),
            ("DW_OP_lit7","37","neg","1f",-7),
            ("DW_OP_lit5","35","not","20",(1<<64)-6),
            ("DW_OP_lit5","35","plus_uconst 17","23 11",22),
        ]:
            emit(prefix,raw_prefix)
            emit("DW_OP_"+op,raw_op)
            expected.append(g(value))
        for name, opcode, value in [
            ("and","1a",2),("div","1b",3),("minus","1c",4),("mod","1d",0),
            ("mul","1e",12),("or","21",6),("plus","22",8),("shl","24",24),
            ("shr","25",1),("shra","26",1),("xor","27",4),
            ("eq","29",0),("ge","2a",1),("gt","2b",1),("le","2c",0),
            ("lt","2d",0),("ne","2e",1),
        ]:
            emit("DW_OP_lit6","36")
            emit("DW_OP_lit2","32")
            emit("DW_OP_"+name,opcode)
            expected.append(g(value))
        emit("DW_OP_nop", "96")
        emit("DW_OP_skip 0", "2f 00 00")
        emit("DW_OP_lit0", "30")
        emit("DW_OP_bra 0", "28 00 00")
        emit("DW_OP_stack_value","9f")
        self.assertEqual(len(set(re.findall(r"DW_OP_\w+", " ".join(t for t,_ in chunks)))),111)
        pos, annotated = 0, []
        for text, raw in chunks:
            annotated.append(f"{pos}: {text}")
            pos += len(raw.split())
        text = ", ".join(annotated+[str(pos)])
        raw = " ".join(b for _,b in chunks)
        ctx=snapshot(registers={str(i):1000+i for i in range(32)}|{"40":5000},
                     framebase=2000, types={"12":ty()},
                     memory={str(256+i):b for i,b in enumerate([254,255,0,0,0,0,0,0])})
        left=self.success(raw,expected,"hex",ctx,end=pos)
        right=self.success(text,expected,"text",ctx,end=pos)
        self.assertEqual(left["result"],{"kind":"value",**expected[-1]})
        self.assertEqual(left["result"],right["result"])
        for mode, source in [("hex",raw),("text",text)]:
            before=self.input(source,mode,ctx,depth=1)
            after=left if mode=="hex" else right
            self.assertEqual(before["position"],1)
            self.assertEqual(self.fixed_inputs(before),self.fixed_inputs(after))

    def test_text_numbers_and_declared_positions(self):
        values=[g((1<<64)-1),g(255),g(16)]
        source="0X10: DW_OP_const1s -0X1, 17: DW_OP_const1u 0xff, 0x30: DW_OP_constu 16, 49"
        result=self.success(source,values,end=49)
        self.assertEqual(self.input(source,depth=0)["status"],"incomplete")
        # These deliberately disagree with encoding lengths and include negative offsets.
        self.success("-0x3: DW_OP_lit7, -1: DW_OP_stack_value, 0",[g(7)],end=0)
        self.success("-3: DW_OP_lit7, -1",[g(7)],end=-1)
        self.success("10: DW_OP_lit7, 11",[g(7)],end=11)
        bad=self.input("0: DW_OP_const1s 0xff, 2")
        self.assertEqual((bad["status"],bad["position"],bad["stack"]),("incomplete",0,[]))
        self.assertIsNone(bad["result"])
        for source in ("0: DW_OP_const1u 0x100, 3", "0: DW_OP_constu -0x1, 2"):
            self.assertEqual(self.input(source)["status"],"incomplete")

    def test_input_structure_rejection(self):
        for source in ("0: DW_OP_lit1, 0", "0x10: DW_OP_lit1, 16",
                       "2: DW_OP_lit1, 1", "0: DW_OP_lit1, 2: DW_OP_lit2, 1", "7", "-1"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.input(source)
        for source in ("DW_OP_lit1", "", "0: DW_OP_lit1", "end: 0",
                       "0x: DW_OP_lit1, 2", "0: DW_OP_constu 0xgg, 2",
                       "0: DW_OP_lit1, 0x", "0: DW_OP_constu --1, 2"):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                self.input(source)
        for source in ("117f", "f", "100", "0x1", "0x100"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.input(source,"hex")
        for source in ("gg", "-01", "11, 7f", "0x", "11_7f"):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                self.input(source,"hex")

    def test_fixed_width_endianness_and_addresses(self):
        fixtures=[
            ("08 ff 09 ff 0a 34 12 0b 00 80 0c 78 56 34 12 0d 00 00 00 80 "
             "0e 08 07 06 05 04 03 02 01 0f 00 00 00 00 00 00 00 80",
             [255,(1<<64)-1,0x1234,(1<<64)-32768,0x12345678,(1<<64)-(1<<31),
              0x0102030405060708,1<<63],"little"),
            ("08 ff 09 ff 0a 12 34 0b 80 00 0c 12 34 56 78 0d 80 00 00 00 "
             "0e 01 02 03 04 05 06 07 08 0f 80 00 00 00 00 00 00 00",
             [255,(1<<64)-1,0x1234,(1<<64)-32768,0x12345678,(1<<64)-(1<<31),
              0x0102030405060708,1<<63],"big"),
        ]
        for raw,values,endian in fixtures:
            with self.subTest(endian=endian):
                self.success(raw,[g(v) for v in values],"hex",snapshot(endianness=endian),end=38)
        for width,raw in [(32,"03 78 56 34 12"),(64,"03 78 56 34 12 00 00 00 00")]:
            self.success(raw,[g(0x12345678)],"hex",snapshot(address_width=width),end=1+width//8)
        self.success("03 12 34 56 78",[g(0x12345678)],"hex",snapshot(address_width=32,endianness="big"),end=5)
        self.success("0a 00 01 09 ff",[g(0),g(255)],"hex",snapshot(address_width=8),end=5)
        for width in (1,7,9):
            self.assertEqual(self.input("03 00 00","hex",snapshot(address_width=width))["status"],"incomplete")
            self.success("31 32 22",[g(3 % (1<<width))],"hex",snapshot(address_width=width),end=3)

    def test_leb128_values_lengths_and_nonminimal(self):
        # DWARF 5 tables 7.7/7.8 and Appendix C examples.
        raw="10 02 10 7f 10 80 01 10 81 01 10 b9 64 11 7e 11 ff 00 11 81 7f 11 80 7f 11 ff 7e"
        nums=[2,127,128,129,12857,-2,127,-127,-128,-129]
        for endian in ("little","big"):
            self.success(raw,[g(n % (1<<64)) for n in nums],"hex",snapshot(endianness=endian),end=27)
        self.success("10 80 00 11 ff 7f 11 80 00",[g(0),g((1<<64)-1),g(0)],"hex",end=9)
        # 203-bit numbers: complete input, no fixed machine-width decoding bound.
        positive="10 "+"80 "*28+"01"
        negative="11 "+"80 "*28+"7f"
        self.success(positive+" "+negative,[g((1<<196)%(1<<64)),g((-(1<<196))%(1<<64))],"hex",end=60)
        self.success("0X11 0x7F 0x9f",[g((1<<64)-1)],"hex",end=3)

    def test_multi_operand_memory_and_missing_context(self):
        ctx=snapshot(registers={"128":4},framebase=0,types={"128":ty()},memory={"0":254,"1":255})
        source="92 80 01 78 91 7f 30 a6 02 80 01 9f"
        values=[g((1<<64)-4),g((1<<64)-1),{"value":-2,"type":{"id":"cu0:s16"}}]
        self.success(source,values,"hex",ctx,end=12)
        self.success("30 94 00",[g(0)],"hex",end=3)
        for raw,position,values in [("92 80 01 78",0,[]),("91 00",0,[]),
                                    ("30 94 01",1,[g(0)]),("30 a6 02 80 01",1,[g(0)])]:
            stopped=self.input(raw,"hex")
            self.assertEqual((stopped["status"],stopped["position"],stopped["stack"]),("incomplete",position,values))

    def test_truncated_and_unsupported_preserve_current_state(self):
        for suffix in ("03", "03 00", "08", "09", "0a 01", "0b ff", "0c 00 00 00",
                       "0d 00", "0e 00 00", "0f 00", "10", "10 80", "11 ff", "15",
                       "23 80", "70 80", "91 80", "92", "92 80", "92 01", "92 01 80",
                       "94", "a6", "a6 02", "a6 02 80", "00", "ff", "28", "28 00", "2f", "2f 00",
                       "a1 00", "a2 00", "a4 00"):
            with self.subTest(suffix=suffix):
                source="37 "+suffix
                stopped=self.input(source,"hex")
                before=self.input(source,"hex",depth=1)
                self.assertEqual((stopped["status"],stopped["position"],stopped["stack"]),("incomplete",1,[g(7)]))
                self.assert_preserved(before, stopped)
                self.assertIsNone(stopped["result"])

    def test_results_and_rewrite_budget(self):
        source="10 80 01 32"
        for mode,text in [("hex",source),("text","0: DW_OP_constu 128, 3: DW_OP_lit2, 4")]:
            for depth,pos,values,complete in [(1,3,[g(128)],False),(2,4,[g(128),g(2)],False),
                                               (3,4,[g(128),g(2)],True)]:
                result=self.input(text,mode,depth=depth)
                self.assertEqual((result["position"],result["stack"]),(pos,values))
                self.assertEqual(result["status"],"completed" if complete else "incomplete")
        for depth,complete in [(1,False),(2,True)]:
            result=self.input("10 80 01 9f","hex",depth=depth)
            self.assertEqual(result["position"],4 if complete else 3)
            self.assertEqual(result["result"],{"kind":"value",**g(128)} if complete else None)
        for raw,pos,values in [("9f",0,[]),("31 9f 32",1,[g(1)]),
                               ("31 9f 9f",1,[g(1)]),("31 13",2,[])]:
            result=self.input(raw,"hex")
            self.assertEqual((result["status"],result["position"],result["stack"]),("incomplete",pos,values))
        for mode,source in [("hex",""),("text","0x0")]:
            result=self.success(source,[g(-1)],mode,snapshot(initial_stack=[g(-1)]),end=0)
            self.assertEqual(result["result"],{"kind":"unavailable"})
            pending=self.input(source,mode,snapshot(initial_stack=[g(-1)]),depth=0)
            self.assertEqual((pending["status"],pending["result"],pending["stack"]),("incomplete",None,[g(-1)]))

    def test_format_cli_and_input_errors(self):
        path=Path(self.temp.name)/"cli-input"
        context=Path(self.temp.name)/"context.json"
        context.write_text(json.dumps(snapshot()))
        for mode,source,code in [("hex","11 7f 9f",0),("text","0: DW_OP_lit1, 1",0),
                                  ("hex","10 80",1),("hex","117f",2),
                                  ("text","1: DW_OP_lit1, 1",2),("text","DW_OP_lit1",2)]:
            path.write_text(source)
            process=subprocess.run([sys.executable,str(ROOT/"run.py"),str(path),"--context",str(context),
                                    "--definition",str(self.definition),"--format",mode],capture_output=True,text=True)
            self.assertEqual(process.returncode,code,process.stderr)
            if code==2:
                self.assertTrue(process.stderr)
            else:
                self.assertEqual(json.loads(process.stdout)["status"],"completed" if code==0 else "incomplete")
        with self.assertRaises(ValueError):
            self.input("31","binary")

    def test_wide_signed_decoding_and_leb128(self):
        # A wider destination exposes sign extension that 64-bit modulo would hide.
        raw="09 ff 0b 00 80 0d 00 00 00 80 0f 00 00 00 00 00 00 00 80"
        self.success(raw,[g(((1<<128)+n)%(1<<128)) for n in (-1,-32768,-(1<<31),-(1<<63))],
                     "hex",snapshot(address_width=128),end=19)
        # Explicit 29-byte LEB operands with both high and low nonzero bits.
        raw="10 85 "+"80 "*27+"01 11 85 "+"80 "*27+"7f"
        self.success(raw,[g((1<<196)+5),g((5-(1<<196))%(1<<256))],
                     "hex",snapshot(address_width=256),end=60)
        # Register numbers are identifiers, so an over-64-bit ULEB cannot truncate.
        raw="92 "+"80 "*28+"01 00"
        self.success(raw,[g(42)],"hex",snapshot(registers={str(1<<196):42}),end=31)

    def test_truncated_operands_with_available_context(self):
        # A missing fixture must not hide a decoder that invents an operand.
        # In particular, 0x81 has partial ULEB value 1, which resolves in TS;
        # it must still fail because the required continuation byte is absent.
        ctx=snapshot(registers={"0":4,"1":4},framebase=0,
                     types={"1":ty()},memory={"7":23,"8":0})
        for suffix in ("70","91","92 01","a6 02 81"):
            with self.subTest(suffix=suffix):
                source="37 "+suffix
                stopped=self.input(source,"hex",ctx)
                before=self.input(source,"hex",ctx,depth=1)
                self.assertEqual((stopped["status"],stopped["position"],stopped["stack"]),
                                 ("incomplete",1,[g(7)]))
                self.assert_preserved(before, stopped)
                self.assertIsNone(stopped["result"])
