"""Calls, independent entry state and supplied address-space semantics stay in K."""
from pathlib import Path
from test_basic import DwarfTestCase, snapshot, g, ty
import run as dwarf


class RuntimeTests(DwarfTestCase):
    def raw(self, source, ctx=None, **options):
        path=Path(self.temp.name)/"runtime.hex"
        path.write_text(source)
        return dwarf.evaluate(path,ctx or snapshot(),self.definition,input_format="hex",**options)

    def test_calls_share_stack_and_preserve_root_input(self):
        ctx=snapshot(die_locations={"32":{"bytes":[0x32,0x22]}})
        for code in ("31 98 20 00 9f","31 99 20 00 00 00 9f","31 9a 20 00 00 00 9f"):
            r=self.raw(code,ctx)
            self.assertEqual((r["status"],r["stack"]),("completed",[g(3)]))
            root=dwarf.root_inputs(r["configuration"]["term"])
            suspended=self.raw(code,ctx,depth=2)
            self.assertEqual(dwarf.root_inputs(suspended["configuration"]["term"]),root)
            self.assertIsNone(suspended["result"])
        self.complete("DW_OP_lit1, DW_OP_call2 32, DW_OP_stack_value",[g(3)],ctx)

    def test_nested_calls_switch_cu_and_ref_width(self):
        ctx=snapshot(compilation_unit_offset=100,dwarf_offset_size=8,die_locations={
            "132":{"bytes":[0x99,0x10,0,0,0],"unit_offset":200},
            "216":{"bytes":[0x32,0x22],"unit_offset":200}})
        self.assertEqual(self.raw("31 98 20 00 9f",ctx)["stack"],[g(3)])
        ctx["die_locations"]["132"]["bytes"]=[0x9a,0xd8,0,0,0,0,0,0,0]
        ctx["die_locations"]["132"]["offset_size"]=8
        self.assertEqual(self.raw("31 98 20 00 9f",ctx)["stack"],[g(3)])
        for code in ("98 20", "99 20 00 00", "9a 20 00 00 00"):
            r=self.raw(code,ctx)
            self.assertEqual((r["position"],r["stack"]),(0,[]))

    def test_empty_missing_and_recursive_calls(self):
        ctx=snapshot(die_locations={"32":{"bytes":[]}})
        self.assertEqual(self.raw("31 98 20 00 9f",ctx)["stack"],[g(1)])
        r=self.raw("31 98 21 00 9f",ctx)
        self.assertEqual((r["position"],r["stack"],r["stop_reason"]),(1,[g(1)],None))
        ctx["die_locations"]["32"]["bytes"]=[0x98,0x20,0]
        r=self.raw("98 20 00",ctx,depth=10)
        self.assertEqual(r["status"],"incomplete")
        self.assertIsNone(r["stop_reason"])

    def test_entry_register_and_expression_use_independent_snapshot(self):
        ctx=snapshot(registers={"0":99},entry_context={"registers":{"0":11}})
        for code, expected in (("a3 01 50 9f",11),("a3 02 70 03 9f",14)):
            r=self.raw(code,ctx)
            self.assertEqual(r["result"],{"kind":"value",**g(expected)})
        self.complete("DW_OP_entry_value [0x50], DW_OP_stack_value",[g(11)],ctx)

    def test_entry_failure_keeps_callee_and_suspended_caller(self):
        for entry in ({}, {"registers":{"0":11}}):
            ctx=snapshot(registers={"1":99},entry_context=entry)
            r=self.raw("31 a3 01 51 9f",ctx)
            self.assertEqual((r["status"],r["position"],r["end"],r["stack"]),("incomplete",0,1,[]))
            control=dwarf.find_cell(r["configuration"]["term"],"expr")
            continuation=control["items"][1]
            self.assertEqual(dwarf.label(continuation),"returnEntry")
            self.assertEqual(continuation["args"][3]["token"],"1")
            self.assertEqual(dwarf.decode_stack(continuation["args"][7]),[g(1)])
            limited=self.raw("31 a3 01 51 9f",ctx,depth=2)
            self.assertEqual(r["configuration"],limited["configuration"])
            self.assertEqual(self.fixed_inputs(r),self.fixed_inputs(limited))
            self.assertIsNone(r["stop_reason"])
        for code,position,stack in (("31 a3 00 9f",0,[]),("31 a3 02 31 32 9f",2,[g(1),g(2)])):
            r=self.raw(code,snapshot(entry_context={}))
            self.assertEqual((r["position"],r["stack"],r["stop_reason"]),(position,stack,None))
            self.assertEqual(r["status"],"incomplete")
            control=dwarf.find_cell(r["configuration"]["term"],"expr")
            self.assertEqual(dwarf.label(control["items"][1]),"returnEntry")

    def test_failed_nested_calls_keep_shared_stack_and_return_chain(self):
        ctx=snapshot(die_locations={"32":{"bytes":[0x32,0x98,0x21,0]},
                                    "33":{"bytes":[0x33,0x06]}})
        source="31 98 20 00 9f"
        before=self.raw(source,ctx,depth=5)
        after=self.raw(source,ctx,depth=30)
        self.assertEqual((after["status"],after["position"],after["end"],after["stack"]),
                         ("incomplete",1,2,[g(1),g(2),g(3)]))
        self.assertEqual(before["configuration"],after["configuration"])
        control=dwarf.find_cell(after["configuration"]["term"],"expr")
        self.assertEqual([dwarf.label(i) for i in control["items"]],["evaluation","returnCall","returnCall"])
        self.assertEqual(self.fixed_inputs(before),self.fixed_inputs(after))
        self.assertIsNone(after["stop_reason"])

    def test_tls_lookup_is_explicit_and_failure_keeps_stack(self):
        ctx=snapshot(tls_addresses={"42":4096})
        self.complete("DW_OP_lit1, DW_OP_constu 42, DW_OP_form_tls_address, DW_OP_stack_value",[g(1),g(4096)],ctx)
        self.assertEqual(self.raw("08 2a 9b 9f",ctx)["result"],{"kind":"value",**g(4096)})
        r=self.raw("08 29 9b",ctx)
        self.assertEqual((r["position"],r["stack"],r["stop_reason"]),(2,[g(41)],None))

    def test_address_space_order_width_endianness_and_missing_data(self):
        ctx=snapshot(address_width=32,address_spaces={"1":{"16":0x11,"17":0x22},"2":{"16":0xaa}})
        self.assertEqual(self.raw("31 08 10 95 02 9f",ctx)["result"],{"kind":"value",**g(0x2211)})
        ctx["endianness"]="big"
        self.assertEqual(self.raw("31 08 10 95 02 9f",ctx)["stack"],[g(0x1122)])
        r=self.raw("32 08 10 95 02",ctx)
        self.assertEqual((r["position"],r["stack"]),(3,[g(2),g(16)]))

    def test_typed_address_space_read_can_exceed_address_width(self):
        ctx=snapshot(address_width=32,types={"1":ty("u64","DW_ATE_unsigned",64,8)},
            address_spaces={"1":{str(i):i+1 for i in range(8)}})
        r=self.raw("31 30 a7 08 01 9f",ctx)
        self.assertEqual(r["result"],{"kind":"value","value":0x0807060504030201,"type":{"id":"u64"}})

    def test_implicit_pointer_preserves_reference_identity_and_offset(self):
        ctx=snapshot(die_locations={"32":{"const_value":53,"byte_size":1}})
        r=self.raw("a0 20 00 00 00 7f",ctx)
        self.assertEqual(r["result"],{"kind":"implicit_pointer","reference":32,"offset":-1})
        self.assertEqual(r["stack"],[])
        r=self.raw("a0 21 00 00 00 00",ctx)
        self.assertEqual((r["position"],r["stop_reason"]),(0,None))

