"""Reject vendor names and leave raw vendor bytes at their original operation start."""
from pathlib import Path
import json, subprocess, sys
from test_basic import DwarfTestCase, ROOT, snapshot, g
import run as dwarf

EXTENSIONS = [
    ("DW_OP_GNU_const_type 1 [1]", "f4 01 01 01"),
    ("DW_OP_GNU_regval_type 0 1", "f5 00 01"),
    ("DW_OP_GNU_deref_type 1 1", "f6 01 01"),
    ("DW_OP_GNU_convert 1", "f7 01"),
    ("DW_OP_GNU_reinterpret 1", "f9 01"),
    ("DW_OP_GNU_addr_index 0", "fb 00"),
    ("DW_OP_GNU_const_index 0", "fc 00"),
    ("DW_OP_GNU_entry_value [0x50]", "f3 01 50"),
    ("DW_OP_GNU_push_tls_address", "e0"),
    ("DW_OP_GNU_implicit_pointer 32 0", "f2 20 00 00 00 00"),
    ("DW_OP_GNU_variable_value 32", "fd 20 00 00 00"),
    ("DW_OP_GNU_uninit", "f0"),
    ("DW_OP_LLVM_nop", "e9 01"),
    ("DW_OP_LLVM_piece_end", "e9 0a"),
    ("DW_OP_WASM_location 0 0", "ed 00 00"),
]

class StandardOnlyTests(DwarfTestCase):
    def raw(self,source,ctx=None,**options):
        path=Path(self.temp.name)/"standard-only.hex"
        path.write_text(source)
        return dwarf.evaluate(path,snapshot() if ctx is None else ctx,self.definition,input_format="hex",**options)

    def test_all_removed_text_names_are_input_errors(self):
        for text,_ in EXTENSIONS:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                self.execute(text)

    def test_all_removed_raw_ops_preserve_prefix_and_fixed_inputs(self):
        ctx=snapshot(initial_stack=[g(7)],registers={"0":42},memory={"0":99},
            tls_addresses={"1":4096},die_locations={"32":{"bytes":[0x31],"byte_size":1}},
            debug_addr={"0":42},types={"1":{"id":"u8","encoding":"DW_ATE_unsigned","bit_width":8,"byte_size":1}})
        for _,raw in EXTENSIONS:
            with self.subTest(raw=raw):
                before=self.raw("31 "+raw+" 9f",ctx,depth=1)
                after=self.raw("31 "+raw+" 9f",ctx,depth=20)
                self.assertEqual((after["status"],after["position"],after["stack"],after["result"]),
                                 ("incomplete",1,[g(7),g(1)],None))
                self.assert_preserved(before,after)
                self.assertEqual(before["configuration"],after["configuration"])
                self.assertIsNone(after["stop_reason"])

    def test_extensions_inside_entry_and_called_code_keep_actual_scene(self):
        ctx=snapshot(entry_context={},die_locations={"32":{"bytes":[0x31,0xf7,0x01]}})
        for raw,position,stack,continuation in [
            ("a3 02 e9 01 9f",0,[],"returnEntry"),
            ("98 20 00 9f",1,[g(1)],"returnCall")]:
            result=self.raw(raw,ctx,depth=20)
            self.assertEqual((result["status"],result["position"],result["stack"]),("incomplete",position,stack))
            control=dwarf.find_cell(result["configuration"]["term"],"expr")
            self.assertEqual(dwarf.label(control["items"][1]),continuation)

    def test_raw_extension_at_start_and_incomplete_operands_do_not_advance(self):
        for raw in ("e0","e9","ed","f0","f2","f3","f4","f5","f6","f7","f9","fb","fc","fd"):
            result=self.raw(raw,snapshot(initial_stack=[g(17)]),depth=20)
            self.assertEqual((result["status"],result["position"],result["stack"]),("incomplete",0,[g(17)]))

    def test_cli_distinguishes_text_input_error_and_raw_unsupported_opcode(self):
        context=Path(self.temp.name)/"cli-context.json";context.write_text(json.dumps(snapshot()))
        for mode,source,code in [("text","0: DW_OP_GNU_uninit, 1",2),("hex","31 f0",1)]:
            path=Path(self.temp.name)/("cli."+mode);path.write_text(source)
            result=subprocess.run([sys.executable,str(ROOT/"run.py"),str(path),"--format",mode,
                "--definition",str(self.definition),"--context",str(context)],capture_output=True,text=True)
            self.assertEqual(result.returncode,code,result.stderr)
            if mode=="hex":
                observed=json.loads(result.stdout)
                self.assertEqual((observed["status"],observed["position"],observed["stack"],observed["result"]),
                                 ("incomplete",1,[g(1)],None))
            else:
                self.assertFalse(result.stdout)
                self.assertNotIn("the following arguments are required",result.stderr)
