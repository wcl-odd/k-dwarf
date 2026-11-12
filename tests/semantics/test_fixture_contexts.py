"""Lossless upstream fixtures and natural stuck states, independently of agreement."""
from pathlib import Path
from test_basic import DwarfTestCase, snapshot, g
import run as dwarf


class FixtureContextTests(DwarfTestCase):
    def raw(self,source,ctx,**kwargs):
        path=Path(self.temp.name)/"fixture.hex";path.write_text(source)
        return dwarf.evaluate(path,ctx,self.definition,input_format="hex",**kwargs)

    def test_conflicting_request_memory_and_composition(self):
        ctx=snapshot(address_width=32,architecture="i386",registers={"0":0x504},memory_requests=[
            {"address":0x504,"size":4,"bytes":[10,11,12,13]},
            {"address":0x505,"size":4,"bytes":[5,6,7,8]}])
        self.complete("DW_OP_breg0 0, DW_OP_deref, DW_OP_breg0 1, DW_OP_deref",[g(0x0d0c0b0a),g(0x08070605)],ctx)
        result=self.execute("DW_OP_breg0 0, DW_OP_piece 4, DW_OP_breg0 1, DW_OP_piece 4",ctx)
        self.assertEqual(result["result"]["bits"],f"{0x080706050d0c0b0a:064b}")
        result=self.incomplete("DW_OP_breg0 0, DW_OP_deref_size 1",ctx,position=1)
        self.assertEqual(result["stop_reason"], None)
        self.assertEqual(result["stack"],[g(0x504)])

    def test_raw_types_are_resolved_in_k(self):
        ctx=snapshot(raw_types={"1":{"id":"raw-u16","tag":"DW_TAG_base_type","encoding":"DW_ATE_unsigned","byte_size":2},
            "2":{"id":"enum","tag":"DW_TAG_enumeration_type","encoding":"DW_ATE_unsigned","byte_size":4},
            "3":{"id":"string","tag":"DW_TAG_base_type","encoding":"DW_ATE_numeric_string","byte_size":1},
            "4":{"id":"huge","tag":"DW_TAG_base_type","encoding":"DW_ATE_unsigned","bit_width":4294967295}})
        self.complete("DW_OP_lit1, DW_OP_convert 1",[{"value":1,"type":{"id":"raw-u16"}}],ctx)
        self.complete("DW_OP_lit0, DW_OP_convert 4",[{"value":0,"type":{"id":"huge"}}],ctx)
        for ref in (2,3):
            result=self.incomplete(f"DW_OP_lit1, DW_OP_convert {ref}",ctx,position=1)
            self.assertEqual(result["stop_reason"], None)

    def test_standard_pieces_with_wide_mock_registers(self):
        ctx=snapshot(address_width=32,architecture="i386",registers={"32":0x8877665544332211,"33":0x8877665544332211},register_widths={"32":64,"33":64})
        text=self.execute("DW_OP_regx 32, DW_OP_piece 4, DW_OP_regx 33, DW_OP_piece 4",ctx)
        raw=self.raw("90 20 93 04 90 21 93 04",ctx)
        self.assertEqual(raw["result"],text["result"])
        self.assertEqual(raw["result"]["bits"],f"{0x4433221144332211:064b}")
    def test_stuck_consumes_no_failure_rewrite_and_budget_can_resume(self):
        ctx=snapshot()
        source="DW_OP_lit1, DW_OP_drop, DW_OP_drop"
        prefix=self.execute(source,ctx,depth=1)
        before=self.execute(source,ctx,depth=2)
        stopped=self.execute(source,ctx,depth=20)
        self.assertEqual((prefix["position"],prefix["stack"]),(1,[g(1)]))
        self.assertEqual((stopped["position"],stopped["stack"]),(2,[]))
        self.assert_preserved(before,stopped)
        self.assertEqual(before["configuration"],stopped["configuration"])
        self.assertIsNone(stopped["stop_reason"])
        # A budget-limited executable configuration can still change.
        resumable="DW_OP_lit1, DW_OP_drop, DW_OP_lit2"
        limited=self.execute(resumable,ctx,depth=2)
        finished=self.execute(resumable,ctx,depth=20)
        self.assertEqual(limited["status"],"incomplete")
        self.assertEqual((finished["status"],finished["stack"]),("completed",[g(2)]))

