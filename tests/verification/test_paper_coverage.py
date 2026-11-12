"""Coverage accounting consumes K-certified boundaries, never DWARF operands."""
import copy
import csv
import io
from unittest import TestCase

from verification.paper_coverage import (
    instructions, type_inventory, observed_types, type_descriptor, static_object,
    float_evidence, aggregate, coverage_csv, invocation_csv, coverage_totals, coverage_summary_rows, numbered_op_family, OPCODES,
)


def app(label, *args):
    return {"node": "KApply", "label": {"name": label}, "args": list(args)}


def integer(n):
    return {"node": "KToken", "sort": {"name": "Int"}, "token": str(n)}


def program(raw, entries):
    block = app("emptyBytes")
    for n in reversed(raw):
        block = app("byteCons", integer(n), block)
    code = app("emptyInstructions")
    for first, operation, following in reversed(entries):
        code = app("decodedInstruction", integer(first), operation, integer(following), code)
    return app("decodedExpression", integer(0), integer(len(raw)), code, block)


def record(ident="x", scope="root", status="pass", result=None, ops=()):
    return {"id": ident, "root_id": "x", "project": "gdb", "scope": scope, "status": status,
            "result": result, "instructions": list(ops), "metadata_types": [], "observed_types": [],
            "static_object": type_descriptor("g",generic_width=64),
            "floating": float_evidence({"context":{},"address_width":64}, [], [], [], [])}


class InstructionEvidenceTests(TestCase):
    def test_operands_and_implicit_bytes_are_not_instructions(self):
        # constu operand and implicit payload intentionally look like valid OPs.
        p = program([0x10,0x30,0x9e,2,0x22,0x06], [
            (0,app("constant",integer(48)),2),
            (2,app("implicitBytes",app("payload")),6)])
        ops, gaps = instructions(p)
        self.assertEqual([r["op"] for r in ops],["DW_OP_constu","DW_OP_implicit_value"])
        self.assertFalse(gaps)

    def test_normalization_does_not_merge_original_const_names(self):
        ops,_=instructions(program([0x08,1,0x09,1],[(0,app("constant",integer(1)),2),(2,app("constant",integer(1)),4)]))
        self.assertEqual([r["op"] for r in ops],["DW_OP_const1u","DW_OP_const1s"])
        self.assertEqual(ops[0]["normalized_label"],ops[1]["normalized_label"])

    def test_nested_only_when_prepared_by_k_and_payload_identity_checked(self):
        nested=program([0x50],[(0,app("registerLocation",integer(0)),1)])
        root=program([0xa3,1,0x50],[(0,app("entryValue",nested),3)])
        ops,gaps=instructions(root)
        self.assertEqual([r["op"] for r in ops],["DW_OP_entry_value","DW_OP_reg0"])
        self.assertEqual(ops[1]["block"],"entry@0/root")
        self.assertFalse(gaps)
        root["args"][2]["args"][1]["args"][0]=program([0x51],[(0,app("registerLocation",integer(1)),1)])
        with self.assertRaisesRegex(ValueError,"nested block differs"):
            instructions(root)

    def test_unknown_or_truncated_suffix_is_a_gap_not_byte_scanned(self):
        ops,gaps=instructions(program([0x30,0xff,0x22],[(0,app("constant",integer(0)),1)]))
        self.assertEqual(len(ops),1)
        self.assertEqual(gaps[0]["offset"],1)
        self.assertEqual(gaps[0]["end"],3)
        _,gaps=instructions(program([0x10,0x80],[]))
        self.assertEqual(gaps[0]["offset"],0)

    def test_boundary_and_name_drift_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"boundaries"):
            instructions(program([0x30],[(1,app("constant"),1)]))
        with self.assertRaisesRegex(ValueError,"standard name"):
            instructions(program([0xe0],[(0,app("extension"),1)]))
        self.assertEqual(len(OPCODES),164)

    def test_branch_input_presence_does_not_claim_execution(self):
        p=program([0x2f,1,0,0x30,0x31],[(0,app("skip",integer(1)),3),(3,app("constant",integer(0)),4),(4,app("constant",integer(1)),5)])
        ops,_=instructions(p)
        rows=aggregate([record(ops=ops)],{name:{"family":"test"} for name in OPCODES.values()})
        self.assertEqual({r["item"] for r in rows if r["view"]=="op_root"},{"DW_OP_skip","DW_OP_lit0","DW_OP_lit1"})
        self.assertTrue(all(r["evidence_level"]=="input_presence" for r in rows if r["view"].startswith("op_")))


class TypeAndFloatEvidenceTests(TestCase):
    def test_metadata_final_identity_and_static_type_are_independent(self):
        context={"types":{"1":{"id":"f","encoding":"DW_ATE_float","bit_width":32,"byte_size":8},
                          "2":{"id":"u","encoding":"DW_ATE_unsigned","bit_width":32,"byte_size":4},
                          "3":{"id":"other-f","encoding":"DW_ATE_float","bit_width":32,"byte_size":4}}}
        meta,lookup=type_inventory(context,64)
        out={"stack":[{"value":123,"type":{"id":"u"}}],"result":{"kind":"register","register":19}}
        observed=observed_types(out,lookup)
        self.assertTrue(any(t["encoding"]=="DW_ATE_float" for t in meta))
        self.assertFalse(any(t["encoding"]=="DW_ATE_float" for t in observed))
        audit=float_evidence({"context":context,"address_width":64},[{"op":"DW_OP_reg19"}],meta,observed,[])
        self.assertTrue(audit["metadata_present"])
        self.assertTrue(audit["no_float_operand_possible"])
        self.assertFalse(audit["observed_float_value"])
        obj=static_object({"origin":{"selection":{"type_die":"2"}}},lookup)
        self.assertEqual(obj["encoding"],"DW_ATE_unsigned")
        self.assertEqual(lookup["f"]["format"],lookup["other-f"]["format"])
        self.assertNotEqual(lookup["f"]["byte_size"],lookup["other-f"]["byte_size"])

    def test_genuinely_typed_final_float_is_observed_but_arithmetic_not_inferred(self):
        context={"raw_types":{"7":{"id":"f","encoding":4,"byte_size":8}}}
        meta,lookup=type_inventory(context,64)
        observed=observed_types({"result":{"kind":"value","type":{"id":"f"},"value":0}},lookup)
        self.assertEqual(observed[0]["encoding"],"DW_ATE_float")
        audit=float_evidence({"context":context,"address_width":64},[{"op":"DW_OP_const_type"}],meta,observed,[])
        self.assertTrue(audit["observed_float_value"])
        self.assertFalse(audit["no_float_operand_possible"])
        self.assertEqual(audit["categories"]["typed_transport"]["assessment"],"unconfirmed")
        self.assertEqual(audit["categories"]["typed_transport"]["confirmed_execution"],0)

    def test_unknown_initial_type_and_decode_gaps_prevent_false_absence_proof(self):
        for context,gaps in (({"initial_stack":[{"type":99,"value":1}]},[]),({},[{"offset":0}])):
            audit=float_evidence({"context":context,"address_width":64},[],[],[],gaps)
            self.assertFalse(audit["no_float_operand_possible"])
        context={"types":{"1":{"id":"f","encoding":"DW_ATE_float","bit_width":32,"byte_size":4}},
                 "initial_stack":[{"type":1,"value":1}]}
        audit=float_evidence({"context":context,"address_width":64},[{"op":"DW_OP_plus"}],[],[],[])
        self.assertEqual(audit["categories"]["arithmetic"]["assessment"],"unconfirmed")

    def test_width_sign_encoding_and_storage_basis_are_recorded(self):
        t=type_descriptor({"encoding":"DW_ATE_signed","bit_width":13,"byte_size":2})
        self.assertEqual((t["signedness"],t["bit_width"],t["byte_size"]),("signed",13,2))
        self.assertEqual(t["width_basis"],"explicit_bit_width")
        t=type_descriptor({"encoding":"DW_ATE_unknown_15","byte_size":8})
        self.assertEqual(t["encoding"],"DW_ATE_decimal_float")
        self.assertEqual(t["width_basis"],"byte_size_default")
        self.assertEqual(type_descriptor("g",generic_width=64)["signedness"],"unspecified")


class CoverageAccountingTests(TestCase):
    def test_root_results_pieces_and_dependencies_have_different_denominators(self):
        ops=[{"op":"DW_OP_reg0","block":"root"},{"op":"DW_OP_reg0","block":"entry@0/root"}]
        roots=[record("x",result={"kind":"composite","pieces":[{"location":{"kind":"register"}},{"location":{"kind":"register"}},{"location":{"kind":"memory"}}]},ops=ops),
               record("y",status="fail")]
        dep=record("x/attr",scope="dependency",status=None,result={"kind":"scalar"},ops=ops)
        rows=aggregate(roots+[dep],{"DW_OP_reg0":{"family":"register"}})
        self.assertEqual(sum(r["cases"] for r in rows if r["view"] in {"location","no_result"}),2)
        self.assertEqual(sum(r["cases"] for r in rows if r["view"]=="piece_location"),2)
        op=next(r for r in rows if r["view"]=="op_root")
        self.assertEqual(op["cases"],1)
        dep_row=next(r for r in rows if r["view"]=="op_dependency")
        self.assertEqual(dep_row["unit"],"dependency_invocation")
        self.assertEqual(dep_row["status"],{})
        text=coverage_csv({"rows":rows})
        exported=list(csv.DictReader(io.StringIO(text)))
        self.assertTrue(all(r["pass"]==r["fail"]=="" for r in exported if r["unit"]=="dependency_invocation"))
        self.assertEqual(op["evidence_ids"],["x"])

    def test_no_public_result_never_becomes_a_location_kind(self):
        rows=aggregate([record(status="pass")],{})
        self.assertFalse(any(r["view"]=="location" for r in rows))
        self.assertEqual(next(r for r in rows if r["view"]=="no_result")["status"],{"pass":1})


class CombinedCoverageTests(TestCase):
    def fixture(self):
        return {"summary": {
            "lldb": dict(roots=2, dependency_invocations=0,
                         root_op_names=["DW_OP_reg0", "DW_OP_lit0"], root_op_name_count=2,
                         dependency_op_names=[], dependency_op_name_count=0,
                         location_counts={"register": 1, "no_public_result": 1}),
            "gdb": dict(roots=3, dependency_invocations=2,
                        root_op_names=["DW_OP_reg0", "DW_OP_plus"], root_op_name_count=2,
                        dependency_op_names=["DW_OP_plus", "DW_OP_push_object_address"],
                        dependency_op_name_count=2,
                        location_counts={"composite": 1, "unavailable": 1, "scalar": 1})},
                "rows": [dict(view="no_result" if k=="no_public_result" else "location", source=p,
                              item=k, cases=1, status={"pass": 1})
                         for p, kinds in (("lldb",("register","no_public_result")),
                                          ("gdb",("composite","unavailable","scalar"))) for k in kinds]}

    def test_union_is_not_sum_and_dependencies_only_add_new_names(self):
        totals=coverage_totals(self.fixture())
        combined=totals["sources"]["combined"]
        self.assertEqual(combined["root_op_name_count"],3)
        self.assertEqual(combined["root_or_dependency_op_name_count"],4)
        self.assertEqual(combined["added_by_dependencies"],["DW_OP_push_object_address"])
        self.assertEqual(combined["root_op_fraction"],3/164)
        self.assertEqual(combined["roots"],5)
        self.assertEqual(combined["dependency_invocations"],2)

    def test_scalar_and_stopped_states_do_not_expand_location_kinds(self):
        totals=coverage_totals(self.fixture())
        combined=totals["sources"]["combined"]
        self.assertEqual(set(combined["location_kinds"]),{"register","composite","unavailable"})
        self.assertEqual(combined["location_kind_count"],3)
        self.assertEqual(len(totals["implemented_location_kinds"]),7)
        rows=coverage_summary_rows(self.fixture())
        combined_results=[r for r in rows if r["source"]=="combined" and r["unit"]=="expression"]
        self.assertEqual(sum(r["cases"] for r in combined_results),5)
        self.assertEqual(sum(r["status"]["pass"] for r in combined_results),5)
        self.assertEqual(next(r for r in rows if r["source"]=="combined" and r["view"]=="location_kind_coverage")["cases"],3)

    def test_inconsistent_name_counts_or_result_denominators_are_rejected(self):
        for field, value in (("root_op_name_count",3),("roots",4)):
            report=self.fixture()
            report["summary"]["lldb"][field]=value
            with self.assertRaises(ValueError):coverage_totals(report)
        report=self.fixture()
        report["rows"][0]["cases"]=9
        with self.assertRaisesRegex(ValueError,"combined root result rows differ"):
            coverage_summary_rows(report)


    def test_numbered_family_ranges_do_not_merge_x_or_const_variants(self):
        for prefix in ("lit","reg","breg"):
            self.assertEqual({numbered_op_family(f"DW_OP_{prefix}{i}") for i in range(32)},
                             {f"DW_OP_{prefix}N"})
            self.assertEqual(numbered_op_family(f"DW_OP_{prefix}32"),f"DW_OP_{prefix}32")
        for name in ("DW_OP_regx","DW_OP_bregx","DW_OP_const1u","DW_OP_const2u","DW_OP_consts"):
            self.assertEqual(numbered_op_family(name),name)

    def test_numbered_family_union_and_denominator_are_recomputed_together(self):
        report=self.fixture()
        report["summary"]["lldb"].update(root_op_names=["DW_OP_lit0","DW_OP_lit31",
            "DW_OP_reg0","DW_OP_reg31","DW_OP_breg0","DW_OP_breg31"],root_op_name_count=6)
        totals=coverage_totals(report)
        combined=totals["sources"]["combined"]
        self.assertEqual(totals["implemented_op_family_count"],71)
        self.assertEqual(combined["root_op_name_count"],7)
        self.assertEqual(combined["root_op_family_count"],4)
        self.assertAlmostEqual(combined["root_op_family_fraction"],4/71)
        self.assertEqual(totals["primary_op_coverage"],dict(scope="root_expression",name_count=7,
                         name_denominator=164,family_count=4,family_denominator=71))
        row=next(r for r in coverage_summary_rows(report)
                 if r["source"]=="combined" and r["view"]=="op_family_coverage_summary")
        self.assertEqual((row["cases"],row["coverage_denominator"]),(4,71))
