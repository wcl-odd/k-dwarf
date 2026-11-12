"""Inventory archived K inputs/results. Never decode operands or run evaluators.

OP identity is a display lookup at boundaries already supplied by K. It is not
an expression parser: operand bytes, block lengths and LEB128 are never read.
"""
import argparse
import csv
import io
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

import run as dwarf


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "output/coverage/evidence.json"
ARITH = {"abs", "neg", "plus", "minus", "mul", "div"}
COMPARE = {"eq", "ne", "lt", "le", "gt", "ge"}
FORMATS = {32: "binary32", 64: "binary64", 80: "x87 binary80", 128: "binary128"}
# DWARF 5 Table 7.9. Only a name lookup for K-certified instruction starts.
OPCODES = {3: "addr", 6: "deref"}
OPCODES.update(enumerate("const1u const1s const2u const2s const4u const4s const8u const8s constu consts dup drop over pick swap rot xderef abs and div minus mod mul neg not or plus plus_uconst shl shr shra xor bra eq ge gt le lt ne skip".split(), 8))
for start, prefix in ((0x30, "lit"), (0x50, "reg"), (0x70, "breg")):
    OPCODES.update({start + n: prefix + str(n) for n in range(32)})
OPCODES.update(enumerate("regx fbreg bregx piece deref_size xderef_size nop push_object_address call2 call4 call_ref form_tls_address call_frame_cfa bit_piece implicit_value stack_value implicit_pointer addrx constx entry_value const_type regval_type deref_type xderef_type convert reinterpret".split(), 0x90))
OPCODES = {number: "DW_OP_" + name for number, name in OPCODES.items()}
ENCODINGS = {1: "address", 2: "boolean", 3: "complex_float", 4: "float", 5: "signed",
             6: "signed_char", 7: "unsigned", 8: "unsigned_char", 9: "imaginary_float",
             10: "packed_decimal", 11: "numeric_string", 12: "edited", 13: "signed_fixed",
             14: "unsigned_fixed", 15: "decimal_float", 16: "UTF", 17: "UCS", 18: "ASCII"}
RESULT_KINDS = ("memory", "register", "value", "bytes", "composite", "implicit_pointer", "scalar", "unavailable")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def instructions(program):
    """Read K's prepared code, including entry blocks, without parsing bytes."""
    require(dwarf.label(program) == "decodedExpression", "missing K decoded input")
    start, end, code, raw = program["args"]
    data = dwarf.decode_bytes(raw)
    begin, stop = int(start["token"]), int(end["token"])
    require(begin == 0 and stop == len(data), "decoded input boundary/byte identity differs")
    result, gaps, position = [], [], begin
    while dwarf.label(code) == "decodedInstruction":
        first, operation, following, rest = code["args"]
        pos, nxt = int(first["token"]), int(following["token"])
        require(pos == position and pos < nxt <= stop, "noncontiguous K instruction boundaries")
        name = OPCODES.get(data[pos])
        require(name is not None, "K instruction start has no reviewed standard name")
        record = {"offset": pos, "next": nxt, "op": name,
                  "normalized_label": dwarf.label(operation), "block": "root"}
        result.append(record)
        # Only K-prepared entry expressions are traversed. A payload containing
        # opcode-looking bytes is not scanned for additional instructions.
        for arg in operation.get("args", []):
            if dwarf.label(arg) == "decodedExpression":
                nested, missing = instructions(arg)
                nested_bytes = dwarf.decode_bytes(arg["args"][3])
                require(not nested_bytes or (len(nested_bytes) <= nxt-pos-1 and
                        list(data[nxt-len(nested_bytes):nxt]) == list(nested_bytes)),
                        "nested block differs from original bytes")
                for item in nested:
                    item["block"] = f"entry@{pos}/" + item["block"]
                result.extend(nested)
                gaps.extend({**g, "block": f"entry@{pos}/" + g["block"]} for g in missing)
        position, code = nxt, rest
    require(dwarf.label(code) == "emptyInstructions", "unknown K instruction-list tail")
    if position < stop:
        gaps.append({"block": "root", "offset": position, "end": stop,
                     "reason": "K prepared only a decodable prefix; remaining bytes are not inventoried"})
    return result, gaps


def type_descriptor(t, *, generic_width=None):
    if t == "g":
        return {"encoding": "generic", "signedness": "unspecified", "bit_width": generic_width,
                "byte_size": generic_width // 8 if generic_width and generic_width % 8 == 0 else None,
                "tag": "generic", "width_basis": "address_width"}
    require(isinstance(t, dict), "type metadata must be an object")
    encoding = t.get("encoding", t.get("DW_AT_encoding"))
    if encoding is not None:
        match = re.fullmatch(r"DW_ATE_unknown_(\d+)", str(encoding))
        number = int(match[1]) if match else int(encoding) if str(encoding).isdigit() else None
        if number is not None:
            encoding = "DW_ATE_" + ENCODINGS.get(number, "unknown_" + str(number))
    size = t.get("byte_size", t.get("DW_AT_byte_size"))
    size = int(size) if size is not None else None
    width = t.get("bit_width", t.get("bit_size", t.get("DW_AT_bit_size")))
    basis = "explicit_bit_width" if width is not None else "byte_size_default" if size is not None else "unknown"
    width = int(width) if width is not None else 8 * size if size is not None else None
    sign = ("signed" if encoding in {"DW_ATE_signed", "DW_ATE_signed_char", "DW_ATE_signed_fixed"}
            else "unsigned" if encoding in {"DW_ATE_unsigned", "DW_ATE_unsigned_char", "DW_ATE_unsigned_fixed"}
            else "not_applicable")
    result = {"encoding": encoding or "not_a_base_type", "signedness": sign,
              "bit_width": width, "byte_size": size, "width_basis": basis,
              "tag": t.get("tag", "DW_TAG_base_type")}
    if encoding == "DW_ATE_float":
        result["format"] = FORMATS.get(width, "unmodeled_or_unknown")
    return result


def type_inventory(context, width):
    result, lookup = [], {}
    for field in ("types", "raw_types"):
        for ref, typ in (context or {}).get(field, {}).items():
            desc = {**type_descriptor(typ), "reference": str(ref), "identity": typ.get("id"), "source": field}
            result.append(desc)
            lookup[str(ref)] = desc
            if typ.get("id"):
                lookup[typ["id"]] = desc
    lookup["g"] = type_descriptor("g", generic_width=width)
    return result, lookup


def observed_types(payload, lookup):
    result, pending = [], [("stack", payload.get("stack", [])), ("result", payload.get("result"))]
    while pending:
        where, value = pending.pop()
        if isinstance(value, list):
            pending.extend((where, item) for item in value)
        elif isinstance(value, dict):
            if "type" in value and "value" in value:
                ref = value["type"]
                ref = ref.get("id") if isinstance(ref, dict) else str(ref)
                desc = lookup.get(ref, {"encoding": "unresolved", "signedness": "unknown",
                                        "bit_width": None, "byte_size": None, "tag": "unresolved"})
                result.append({**desc, "observation": where, "identity": ref})
            pending.extend((where, child) for key, child in value.items() if key in {"pieces", "location"})
    return result


def static_object(case, lookup):
    """Use the archived variable's type reference, never a Scalar's type."""
    origin = case.get("origin", {})
    ref = str(origin.get("selection", {}).get("type_die", ""))
    nodes = {str(n["die_offset"]): n for n in origin.get("type_layout", []) if "die_offset" in n}
    seen = set()
    while ref and ref not in seen:
        seen.add(ref)
        if ref in lookup:
            return {**lookup[ref], "reference": ref, "basis": "original variable type_die"}
        node = nodes.get(ref)
        if not node:
            break
        if node.get("tag") in {"DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"}:
            ref = str(node.get("type_die", ""))
            continue
        return {**type_descriptor(node), "reference": ref, "basis": "original variable type layout"}
    return {"encoding": "not_available", "signedness": "unknown", "bit_width": None,
            "byte_size": None, "tag": "not_available", "basis": "no independently archived root static-type layout"}


def float_evidence(case, ops, metadata, observed, gaps):
    names = {r["op"] for r in ops}
    table = type_inventory(case.get("context", {}), case["address_width"])[1]
    initial_float_or_unknown = False
    for item in (case.get("context") or {}).get("initial_stack", []):
        ref = item.get("type", "g")
        ref = ref.get("id") if isinstance(ref, dict) else str(ref)
        initial_float_or_unknown |= table.get(ref, {}).get("encoding") not in {
            "generic", "DW_ATE_signed", "DW_ATE_signed_char", "DW_ATE_unsigned",
            "DW_ATE_unsigned_char", "DW_ATE_boolean", "DW_ATE_address"}
    producers = {"DW_OP_" + n for n in ("const_type", "regval_type", "deref_type", "xderef_type",
                                       "convert", "reinterpret", "entry_value", "call2", "call4", "call_ref")}
    # This is a conservative absence proof, not stack evaluation. With no
    # floating initial value and no producer, no OP can receive a float value.
    absent = not initial_float_or_unknown and not (names & producers) and not gaps
    found = any(t["encoding"] == "DW_ATE_float" for t in observed)
    has_meta = any(t["encoding"] in {"DW_ATE_float", "DW_ATE_decimal_float", "DW_ATE_complex_float", "DW_ATE_imaginary_float"} for t in metadata)
    categories = {}
    for category, shortnames in (("typed_transport", {"const_type", "regval_type", "deref_type", "xderef_type"}),
                                 ("arithmetic", ARITH), ("comparison", COMPARE),
                                 ("convert", {"convert"}), ("reinterpret", {"reinterpret"})):
        present = bool(names & {"DW_OP_" + n for n in shortnames})
        categories[category] = {"confirmed_execution": 0,
            "assessment": "absent_by_input_structure" if absent else
                          "no_relevant_op_in_decoded_root" if not present and not gaps else "unconfirmed"}
    return {"metadata_present": has_meta, "observed_float_value": found,
            "no_float_operand_possible": absent,
            "basis": "generic/empty initial stack and no typed/nested/call producer in complete K-decoded input"
                     if absent else "final configurations do not provide a per-OP execution trace",
            "categories": categories}


def aggregate(records, catalog):
    groups = defaultdict(dict)
    def add(view, source, item, record, **extra):
        key = (view, source, item)
        groups[key][record["id"]] = (record, extra)
    for r in records:
        scope, project = r["scope"], r["project"]
        for name in {i["op"] for i in r["instructions"]}:
            add("op_" + scope, project, name, r, family=catalog[name]["family"], evidence_level="input_presence")
        for block_scope in ("root", "nested"):
            for name in {i["op"] for i in r["instructions"] if (i["block"] == "root") == (block_scope == "root")}:
                add("op_" + scope + "_" + block_scope + "_block", project, name, r,
                    family=catalog[name]["family"], evidence_level="input_presence")
        kind = (r["result"] or {}).get("kind")
        if kind:
            require(kind in RESULT_KINDS, "unreviewed location kind: " + kind)
        if scope == "root":
            add("location" if kind else "no_result", project, kind or "no_public_result", r,
                evidence_level="final_result" if kind else "execution_state")
            for kind in {(p.get("location") or {}).get("kind", "unknown") for p in (r["result"] or {}).get("pieces", [])}:
                add("piece_location", project, kind, r, evidence_level="final_piece_result")
        for view, types in (("type_metadata_" + scope, r["metadata_types"]),
                            ("type_observed_" + scope, r["observed_types"]),
                            ("type_object_static", [r["static_object"]] if scope == "root" else [])):
            for t in types:
                signature = "{}:{}:{}:{}".format(t["encoding"], t.get("bit_width"), t.get("byte_size"), t.get("tag"))
                add(view, project, signature, r, encoding=t["encoding"], signedness=t["signedness"],
                    bit_width=t.get("bit_width"), byte_size=t.get("byte_size"), tag=t.get("tag"),
                    evidence_level="type_metadata" if "metadata" in view or "static" in view else "final_typed_value")
    result = []
    for (view, project, item), members in sorted(groups.items()):
        cases = [r for r, _ in members.values()]
        result.append({"view": view, "source": project, "item": item, "cases": len(cases),
                       "unit": "dependency_invocation" if cases[0]["scope"] == "dependency" else "expression",
                       "status": dict(Counter(r["status"] for r in cases)) if cases[0]["scope"] == "root" else {},
                       "evidence_ids": sorted(members), **next(iter(members.values()))[1]})
    for project in ("lldb", "gdb"):
        for scope in ("root", "dependency"):
            members = [r for r in records if r["project"] == project and r["scope"] == scope]
            for item in ("typed_transport", "arithmetic", "comparison", "convert", "reinterpret"):
                for assessment in sorted({r["floating"]["categories"][item]["assessment"] for r in members}):
                    selected = [r for r in members if r["floating"]["categories"][item]["assessment"] == assessment]
                    result.append({"view": "floating_" + scope, "source": project, "item": item,
                        "assessment": assessment, "cases": len(selected),
                        "unit": "expression" if scope == "root" else "dependency_invocation",
                        "status": dict(Counter(r["status"] for r in selected)) if scope == "root" else {},
                        "evidence_level": "structural_absence" if assessment == "absent_by_input_structure" else "not_confirmed",
                        "confirmed_execution_witnesses": 0,
                        "evidence_ids": sorted(r["id"] for r in selected)})
    return result


def analyze(bundle):
    archive = bundle["archive"]
    catalog = {r["op"]: r for r in bundle["support"]}
    require(set(OPCODES.values()) == set(catalog), "name lookup differs from 164-name implementation catalog")
    # Generator identities are provenance, separate from the historical rules.
    archive.read(Path(__file__))
    archive.read(ROOT / "verification/paper_results.py")
    floating_support = archive.json(bundle["paths"]["floating_support"])
    records = []
    for project in ("lldb", "gdb"):
        saved = bundle["summary"]["source_requirements"][project]
        manifest = Path(saved["preparation"])
        cases = {c["id"]: c for c in archive.json(manifest)["cases"]}
        report = archive.json(Path(saved["evidence_report"]))
        executions = {c["id"]: c for c in report["cases"]}
        require(len(executions) == len(report["cases"]), "duplicate archived execution IDs")
        for row in bundle["policy"]:
            if row["project"] != project or row["scope"] != "semantic":
                continue
            case = cases[row["id"]]
            payload = archive.json(row["final_configuration"])
            require((payload.get("result"), payload["position"], payload["end"], payload.get("stack")) ==
                    (row.get("result"), row["position"], row["end"], row.get("stack")), "saved final observation differs: " + row["id"])
            invocations = [(row["id"], "root", case, payload, row["final_configuration"])]
            for dep in executions[row["id"]].get("dependency_evidence", []):
                if "directory" not in dep:
                    continue
                folder = Path(dep["directory"])
                dep_case = archive.json(folder / "case.json")
                dep_payload = archive.json(folder / "k/stdout.txt")
                invocations.append((row["id"] + "/" + dep["id"], "dependency", dep_case, dep_payload, str(folder / "k/stdout.txt")))
            for ident, scope, inp, out, path in invocations:
                expression, context, purpose = dwarf.root_inputs(out["configuration"]["term"])
                raw = dwarf.decode_bytes(expression["args"][3])
                require(raw == inp["bytes"], "K prepared bytes differ from manifest: " + ident)
                ops, gaps = instructions(expression)
                meta, lookup = type_inventory(inp.get("context", {}), inp["address_width"])
                observed = observed_types(out, lookup)
                calls = sorted({i["op"] for i in ops} & {"DW_OP_call2", "DW_OP_call4", "DW_OP_call_ref"})
                coverage_gaps = list(gaps)
                if calls:
                    coverage_gaps.append({"reason": "referenced call bodies have no separately archived decoded execution trace; CU metadata is not inventoried", "ops": calls})
                if scope == "root" and static_object(inp, lookup)["encoding"] == "not_available":
                    coverage_gaps.append({"reason": "no independently archived root static-type layout in reviewed manifest",
                        "classification": "not_applicable_evaluator_unit_fixture" if project == "lldb" else "metadata_gap"})
                if any(t["encoding"] == "unresolved" for t in observed):
                    coverage_gaps.append({"reason": "final type identity cannot be resolved to archived type metadata"})
                record = {"id": ident, "root_id": row["id"], "project": project, "scope": scope,
                          "status": row["status"] if scope == "root" else None, "root_input_identity": row["input_identity"],
                          "input_sha256": hashlib.sha256(json.dumps(inp, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                          "original_bytes_sha256": hashlib.sha256(bytes(raw)).hexdigest(),
                          "execution_status": out.get("status"), "position": out["position"], "end": out["end"],
                          "purpose": inp.get("purpose", "location"), "coverage_gaps": coverage_gaps,
                          "final_configuration": archive.relative(path), "manifest": archive.relative(manifest),
                          "instructions": ops, "decode_gaps": gaps, "result": out.get("result"),
                          "metadata_types": meta, "observed_types": observed,
                          "static_object": static_object(inp, lookup) if scope == "root" else None,
                          "floating": float_evidence(inp, ops, meta, observed, gaps)}
                records.append(record)
    rows = aggregate(records, catalog)
    summary = {}
    for project in ("lldb", "gdb"):
        roots = [r for r in records if r["project"] == project and r["scope"] == "root"]
        deps = [r for r in records if r["project"] == project and r["scope"] == "dependency"]
        present = {op["op"] for r in roots for op in r["instructions"]}
        dep_names = {op["op"] for r in deps for op in r["instructions"]}
        summary[project] = {"roots": len(roots), "dependency_invocations": len(deps),
            "root_op_names": sorted(present), "root_op_name_count": len(present),
            "dependency_op_names": sorted(dep_names), "dependency_op_name_count": len(dep_names),
            "not_present_in_root_inputs": sorted(set(catalog) - present),
            "not_present_in_root_or_dependencies": sorted(set(catalog) - present - dep_names),
            "decode_gap_invocations": sum(bool(r["decode_gaps"]) for r in roots + deps),
            "location_counts": dict(Counter((r["result"] or {}).get("kind", "no_public_result") for r in roots)),
            "float_metadata_roots": sum(r["floating"]["metadata_present"] for r in roots),
            "observed_float_value_roots": sum(r["floating"]["observed_float_value"] for r in roots),
            "no_public_result_statuses": dict(Counter(r["execution_status"] for r in roots if r["result"] is None)),
            "nested_blocks": len({(r["id"], i["block"]) for r in roots for i in r["instructions"] if i["block"] != "root"}),
            "call_body_inventory_gap_roots": sum(any(i["op"] in {"DW_OP_call2", "DW_OP_call4", "DW_OP_call_ref"} for i in r["instructions"]) for r in roots),
            "static_object_described_roots": sum(r["static_object"]["encoding"] != "not_available" for r in roots),
            "float_metadata_audit": [{"id": r["id"], "ops": sorted({i["op"] for i in r["instructions"]}),
                                      "static_object": r["static_object"], "floating": r["floating"]} for r in roots if r["floating"]["metadata_present"]],
            "float_operation_execution": "not traced; no confirmed floating execution witnesses; see per-input absence analysis",
            "float_category_assessments": {category: dict(Counter(r["floating"]["categories"][category]["assessment"] for r in roots + deps))
                                           for category in ("typed_transport", "arithmetic", "comparison", "convert", "reinterpret")},
            "float_assessments_by_scope": {scope: {category: dict(Counter(r["floating"]["categories"][category]["assessment"] for r in entries))
                for category in ("typed_transport", "arithmetic", "comparison", "convert", "reinterpret")}
                for scope, entries in (("root", roots), ("dependency", deps))}}
        require(len(roots) == bundle["metrics"][project]["current_semantic"]["total"], "coverage root denominator differs")
        require(len(deps) == bundle["summary"]["source_requirements"][project]["dependency_invocations"], "dependency invocation count differs")
    for project, stats in summary.items():
        for name in stats["not_present_in_root_inputs"]:
            rows.append({"view": "op_not_present_root", "source": project, "item": name,
                         "unit": "expression", "cases": 0, "status": {}, "evidence_ids": [],
                         "family": catalog[name]["family"], "evidence_level": "input_absence"})
        for category, key in (("metadata_present", "metadata_present"), ("final_float_value", "observed_float_value")):
            members = [r for r in records if r["project"] == project and r["scope"] == "root" and r["floating"][key]]
            rows.append({"view": "floating_root_observation", "source": project, "item": category,
                         "unit": "expression", "cases": len(members), "status": dict(Counter(r["status"] for r in members)),
                         "evidence_ids": sorted(r["id"] for r in members),
                         "evidence_level": "type_metadata" if key == "metadata_present" else "final_typed_value"})
    witnesses = archive.json(bundle["paths"]["project_witnesses"])
    return {"schema": 1, "rule_version": bundle["latest"]["current_rule_version"],
            "result_version": bundle["latest"]["current_observation_version"],
            "selection_sha256": {p: bundle["summary"]["source_requirements"][p]["selection_sha256"] for p in summary},
            "execution_performed": False, "OP_metric": "input presence at K-certified boundaries; not dynamic coverage",
            "dependency_outcomes": "not independently counted as upstream assertion pass/fail",
            "summary": summary, "rows": rows, "records": records,
            "project_float_witnesses": witnesses,
            "floating_implementation": floating_support,
            "implemented_formats": [{"encoding": "DW_ATE_float", "bit_width": w, "format": name,
                "minimum_byte_size": (w+7)//8} for w, name in FORMATS.items()],
            "evidence_levels": {"implemented": "historical per-name rule catalog, not an upstream execution claim",
                "input_presence": "original opcode at a K-archived decoded boundary, including nested blocks",
                "final_result": "actual archived public result, not inferred from input",
                "final_typed_value": "actual final stack/result identity resolved through metadata",
                "confirmed_execution": "no upstream per-OP trace; isolated historical project probes are separate"},
            "sources": {archive.relative(p): h for p, h in sorted(archive.hashes.items())
                        if p not in {bundle["paths"]["coverage_evidence"], bundle["manifest_path"]}}}


LOCATION_KINDS = tuple(kind for kind in RESULT_KINDS if kind != "scalar")


def numbered_op_family(name):
    """Merge only the standard 0..31 lit/reg/breg encodings, not x variants."""
    match = re.fullmatch(r"DW_OP_(lit|reg|breg)([0-9]+)", name)
    if match and 0 <= int(match[2]) <= 31:
        return "DW_OP_" + match[1] + "N"
    return name


def coverage_totals(report):
    """Union archived name inventories; scalar and stopped states are not locations."""
    sources = {}
    implemented = set(OPCODES.values())
    implemented_families = {numbered_op_family(name) for name in implemented}
    combined_root, combined_dep, combined_results = set(), set(), Counter()
    for project, stats in report["summary"].items():
        root, dep = set(stats["root_op_names"]), set(stats["dependency_op_names"])
        require(len(root) == stats["root_op_name_count"] and
                len(dep) == stats["dependency_op_name_count"], "OP inventory count differs")
        require(root | dep <= implemented, "unknown standard OP in inventory")
        counts = Counter(stats["location_counts"])
        require(set(counts) <= set(RESULT_KINDS) | {"no_public_result"} and
                all(n >= 0 for n in counts.values()) and sum(counts.values()) == stats["roots"],
                "root result denominator differs")
        sources[project] = dict(roots=stats["roots"], dependency_invocations=stats["dependency_invocations"],
                                root_op_names=sorted(root), dependency_op_names=sorted(dep),
                                location_counts=dict(counts))
        combined_root.update(root)
        combined_dep.update(dep)
        combined_results.update(counts)
    sources["combined"] = dict(roots=sum(v["roots"] for v in sources.values()),
                               dependency_invocations=sum(v["dependency_invocations"] for v in sources.values()),
                               root_op_names=sorted(combined_root), dependency_op_names=sorted(combined_dep),
                               location_counts=dict(combined_results))
    for stats in sources.values():
        root, dep = set(stats["root_op_names"]), set(stats["dependency_op_names"])
        families = sorted({numbered_op_family(name) for name in root})
        kinds = [k for k in LOCATION_KINDS if stats["location_counts"].get(k, 0)]
        stats.update(root_op_name_count=len(root), root_op_fraction=len(root)/len(implemented),
                     root_or_dependency_op_names=sorted(root | dep),
                     root_or_dependency_op_name_count=len(root | dep),
                     root_or_dependency_op_fraction=len(root | dep)/len(implemented),
                     added_by_dependencies=sorted(dep-root),
                     not_present_in_root_inputs=sorted(implemented-root),
                     root_op_families=families, root_op_family_count=len(families),
                     root_op_family_fraction=len(families)/len(implemented_families),
                     root_numbered_family_members={family: sorted(n for n in root if numbered_op_family(n) == family)
                         for family in ("DW_OP_litN", "DW_OP_regN", "DW_OP_bregN") if family in families},
                     location_kinds=kinds, location_kind_count=len(kinds))
    return {"implemented_op_name_count": len(implemented),
            "implemented_op_family_count": len(implemented_families),
            "implemented_op_families": sorted(implemented_families),
            "family_merge_policy": "only lit0..31, reg0..31 and breg0..31; regx/bregx and other names remain distinct",
            "primary_op_coverage": {"scope": "root_expression", "name_count": len(combined_root),
                "name_denominator": len(implemented),
                "family_count": sources["combined"]["root_op_family_count"],
                "family_denominator": len(implemented_families)},
            "implemented_location_kinds": list(LOCATION_KINDS),
            "sources": sources, "OP_metric": "input presence, not confirmed per-OP execution",
            "location_metric": "observed public root location kinds; scalar and no_public_result excluded"}


def coverage_summary_rows(report):
    """Derived paper rows do not change the immutable archived coverage tables."""
    totals = coverage_totals(report)
    rows = []
    for source, stats in totals["sources"].items():
        for item, key in (("root", "root_op"), ("root_or_dependencies", "root_or_dependency_op")):
            rows.append(dict(view="op_coverage_summary", source=source, item=item, unit="op_name",
                             cases=stats[key+"_name_count"], status={}, evidence_level="input_presence",
                             coverage_denominator=totals["implemented_op_name_count"],
                             coverage_fraction=stats[key+"_fraction"]))
        rows.append(dict(view="op_family_coverage_summary", source=source, item="root", unit="op_family",
                         cases=stats["root_op_family_count"], status={}, evidence_level="input_presence",
                         coverage_denominator=totals["implemented_op_family_count"],
                         coverage_fraction=stats["root_op_family_fraction"]))
        denominator = len(totals["implemented_location_kinds"])
        rows.append(dict(view="location_kind_coverage", source=source, item="observed_root_location_kinds",
                         unit="location_kind", cases=stats["location_kind_count"], status={},
                         evidence_level="final_result", coverage_denominator=denominator,
                         coverage_fraction=stats["location_kind_count"]/denominator))
    for kind, count in sorted(totals["sources"]["combined"]["location_counts"].items()):
        members = [r for r in report["rows"] if r["view"] in {"location", "no_result"} and r["item"] == kind]
        require(sum(r["cases"] for r in members) == count, "combined root result rows differ")
        status = Counter()
        for row in members:status.update(row["status"])
        rows.append(dict(view="no_result" if kind == "no_public_result" else "location", source="combined",
                         item=kind, unit="expression", cases=count, status=dict(status),
                         evidence_level="execution_state" if kind == "no_public_result" else "final_result"))
    return rows


def public_coverage(report):
    return {"totals": coverage_totals(report),
            "summary": {p: {k: v for k, v in stats.items() if k != "float_metadata_audit"}
                         for p, stats in report["summary"].items()},
            "rows": [{k: v for k, v in row.items() if k != "evidence_ids"} for row in report["rows"]],
            "evidence_levels": report["evidence_levels"],
            "formats": report["implemented_formats"],
            "floating_implementation_groups": {category: sorted(r["op"] for r in report["floating_implementation"] if r["floating_status"] == category)
                for category in sorted({r["floating_status"] for r in report["floating_implementation"]})},
            "project_float_witnesses": {"unit": "isolated archived project probe; not upstream expression",
                "total": len(report["project_float_witnesses"]),
                "by_format_and_op": [{"format": fmt, "op": op, "probes": n}
                    for (fmt, op), n in sorted(Counter((r["format"], r["op"]) for r in report["project_float_witnesses"]).items())]}}


COVERAGE_COLUMNS = ["item", "cases", "family", "evidence_level", "encoding", "signedness", "bit_width",
                    "byte_size", "tag", "assessment", "confirmed_execution_witnesses"]


def coverage_csv(report):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["view", "source", "unit", *COVERAGE_COLUMNS,
                                               "pass", "fail", "evidence_ids"])
    writer.writeheader()
    for row in report["rows"]:
        writer.writerow({**{key: row.get(key, "") for key in writer.fieldnames if key not in {"pass", "fail", "evidence_ids"}},
                         **{status: row["status"].get(status, 0) if row["unit"] == "expression" else "" for status in ("pass", "fail")},
                         "evidence_ids": json.dumps(row["evidence_ids"], ensure_ascii=False)})
    return stream.getvalue()


def invocation_csv(report):
    stream = io.StringIO(newline="")
    fields = ["id", "root_id", "project", "scope", "status", "execution_status", "position", "end", "location",
              "op_names", "metadata_types", "observed_types", "static_object", "floating", "coverage_gaps",
              "original_bytes_sha256", "input_sha256", "final_configuration"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in report["records"]:
        data = {key: row.get(key) for key in fields}
        data["location"] = (row["result"] or {}).get("kind", "no_public_result")
        data["op_names"] = sorted({i["op"] for i in row["instructions"]})
        if row["scope"] == "dependency":
            data["status"] = ""  # No independent upstream oracle for a dependency.
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                         for key, value in data.items()})
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT/'output')
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    from .paper_results import load_bundle
    bundle=load_bundle(args.results/'manifest.json')
    report=analyze(bundle)
    if args.output.exists():parser.error('output must not exist')
    args.output.mkdir(parents=True)
    (args.output/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (args.output/'coverage.csv').write_text(coverage_csv(report))
    (args.output/'invocations.csv').write_text(invocation_csv(report))

if __name__ == '__main__':
    main()
