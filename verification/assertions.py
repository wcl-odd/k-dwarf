"""Check source predicates against K evidence. Never execute DWARF operations.

Object materialization only follows a location already returned by K, using the
saved sparse snapshot. Unknown bits are data, never wildcard expectations.
"""
from copy import deepcopy
import re
from pathlib import PurePosixPath

TARGETS = {"stack_top", "result", "object", "stopped", "no_crash", "uncheckable", "properties"}


def validate_assertions(items):
    if not isinstance(items, list):
        raise ValueError("upstream_assertions must be a list")
    ids = set()
    for item in items:
        if (not isinstance(item, dict) or not {"id", "source", "target", "expected", "mapping"} <= item.keys()
                or item["target"] not in TARGETS or not isinstance(item["expected"], dict)
                or not isinstance(item["mapping"], str) or not item["mapping"]):
            raise ValueError("invalid upstream assertion")
        source = item["source"]
        if (not isinstance(source, dict) or not {"project", "version", "file", "line", "text", "parameter"} <= source.keys()
                or type(source["line"]) is not int or source["line"] <= 0
                or source["project"] not in {"gdb","lldb"}
                or not isinstance(source["file"],str) or PurePosixPath(source["file"]).is_absolute()
                or ".." in PurePosixPath(source["file"]).parts):
            raise ValueError("upstream assertion requires verified source evidence")
        if not isinstance(item["id"], str) or not item["id"] or item["id"] in ids:
            raise ValueError("duplicate or invalid upstream assertion id")
        ids.add(item["id"])
        expected = item["expected"]
        allowed = {
            "stack_top": {"integer", "bits", "width", "signed", "type", "scalar"},
            "result": {"integer", "bits", "width", "signed", "kind", "register", "type", "uninitialized", "scalar"},
            "object": {"kind", "object_bytes", "object_slices", "fields", "availability"},
            "properties": {"lower_bound", "upper_bound", "count", "shape", "allocated", "bounds_available"},
            "stopped": {"position", "stack", "stop_reason", "stable"}, "no_crash": set(), "uncheckable": set(),
        }
        if set(expected) - allowed[item["target"]]:
            raise ValueError("predicate is not implemented for this observation target")
        if item["target"] in {"stack_top","result","object"} and not expected:
            raise ValueError("successful semantic checks require an explicit predicate")
        for name in ("integer","bits","register"):
            if name in expected and (type(expected[name]) not in (int,str) or not re.fullmatch(r"-?[0-9]+",str(expected[name]))):
                raise ValueError("invalid expected integer")
        if "scalar" in expected:
            scalar = expected["scalar"]
            if (not isinstance(scalar, dict) or set(scalar) != {"bits", "width", "signed"}
                    or type(scalar["width"]) is not int or scalar["width"] <= 0
                    or type(scalar["signed"]) is not bool
                    or type(scalar["bits"]) not in (int, str)
                    or not re.fullmatch(r"-?[0-9]+", str(scalar["bits"]))):
                raise ValueError("invalid source Scalar equality predicate")
        if "shape" in expected and (not isinstance(expected["shape"],list) or any(type(n) is not int or n<0 for n in expected["shape"])):
            raise ValueError("invalid expected array shape")
        for name in ('allocated', 'bounds_available'):
            if name in expected and type(expected[name]) is not bool:
                raise ValueError(name + ' must be Boolean')
        if "signed" in expected and type(expected["signed"]) is not bool:
            raise ValueError("signed must be Boolean")
        if "uninitialized" in expected and type(expected["uninitialized"]) is not bool:
            raise ValueError("uninitialized must be Boolean")
        if "stop_reason" in expected and (not isinstance(expected["stop_reason"],dict) or
                set(expected["stop_reason"])!={"kind"} or not isinstance(expected["stop_reason"]["kind"],str) or not expected["stop_reason"]["kind"]):
            raise ValueError("stop_reason requires an explicit K failure category")
        if "stable" in expected and (expected["stable"] is not True
                or item["target"] != "stopped" or not {"position", "stack"} <= expected.keys()):
            raise ValueError("stable stopped checks require true, position and complete stack")
        for name in ("width",):
            if name in expected and (type(expected[name]) is not int or expected[name] <= 0):
                raise ValueError("invalid assertion width")
        if "fields" in expected and (not isinstance(expected["fields"], list) or not expected["fields"]):
            raise ValueError("fields must be a nonempty list")
        for field in expected.get("fields", []):
            if (not isinstance(field, dict) or not {"offset", "size"} <= field.keys()
                    or type(field["offset"]) is not int or field["offset"] < 0
                    or type(field["size"]) is not int or field["size"] <= 0
                    or len({"integer", "bits", "available"} & field.keys()) != 1
                    or set(field)-{"offset","size","integer","bits","available","signed"}
                    or ("available" in field and type(field["available"]) is not bool)
                    or ("signed" in field and type(field["signed"]) is not bool)
                    or any(type(field[n]) not in (int,str) or not re.fullmatch(r"-?[0-9]+",str(field[n]))
                           for n in ("integer","bits") if n in field)):
                raise ValueError("invalid object field predicate")
        if "availability" in expected and (not isinstance(expected["availability"],str)
                                            or not re.fullmatch(r"[01]*",expected["availability"])):
            raise ValueError("availability must be an exact known-bit mask")
        if "object_slices" in expected:
            if not isinstance(expected["object_slices"],list) or not expected["object_slices"]:
                raise ValueError("object_slices must be a nonempty list")
            for part in expected["object_slices"]:
                if (not isinstance(part,dict) or set(part)!={"offset","bytes"}
                        or type(part["offset"]) is not int or part["offset"]<0
                        or not isinstance(part["bytes"],list)
                        or any(type(b) is not int or not 0<=b<=255 for b in part["bytes"])):
                    raise ValueError("invalid object slice")
        for data in [expected["object_bytes"]] if "object_bytes" in expected else []:
            if not isinstance(data,list) or any(type(b) is not int or not 0<=b<=255 for b in data):
                raise ValueError("object_bytes must contain bytes")


def _type(case, value):
    if value.get("kind") == "memory":
        return case.address_width, None
    ty = value.get("type")
    if ty == "g":
        return case.address_width, None
    identity = ty.get("id") if isinstance(ty, dict) else None
    for record in {**(case.context or {}).get("types", {}), **(case.context or {}).get("raw_types", {})}.values():
        if record["id"] == identity:
            return record.get("bit_width",8*record.get("byte_size",0)), record.get("encoding") in {"DW_ATE_signed", "DW_ATE_signed_char"}
    return None, None


def scalar_equal(number, width, signed, expected):
    """Observe integer Scalar equality after source-preserving promotion.

    ExpectScalar constructs the expected Scalar; its width/sign are operands
    of equality, not independent requirements on the actual DWARF type.
    A generic K value has no native Scalar signedness. Only classify its
    equality when both signedness interpretations give the same answer.
    """
    if number is None or width is None:
        return None, {"limitation": "actual integer value/width is not observable"}
    common = max(width, expected["width"])
    mask = (1 << common) - 1
    def extend(n, bits, sign):
        n %= 1 << bits
        if sign and n & (1 << (bits - 1)):
            n -= 1 << bits
        return n & mask
    wanted = extend(int(expected["bits"]), expected["width"], expected["signed"])
    options = [False, True] if signed is None else [signed]
    comparisons = [{"actual_signed": sign,
                    "promoted_actual_bits": str(extend(number, width, sign)),
                    "equal": extend(number, width, sign) == wanted}
                   for sign in options]
    answers = {r["equal"] for r in comparisons}
    return (answers.pop() if len(answers) == 1 else None), {
        "actual_width": width, "actual_signed": signed, "expected": expected,
        "common_width": common, "promoted_expected_bits": str(wanted),
        "comparisons": comparisons}


def materialize(case, payload, memory_supplier=None):
    """Return low-bit-first object evidence and all snapshot reads performed."""
    if case.origin.get("returned_member_layout"):
        from .objects import materialize_returned_members
        return materialize_returned_members(case, payload, memory_supplier=memory_supplier)
    result = payload.get("object_location", payload.get("result")) or {}
    kind = result.get("kind")
    count = (case.object_bit_size or case.object_size * 8) + payload.get("object_bit_offset",0)
    reads = []
    if kind == "composite":
        bits = result["bits"][::-1]
    elif kind == "bytes":
        bits = "".join(f"{byte:08b}"[::-1] for byte in result["bytes"])
    elif kind == "unavailable":
        bits = "?" * count
    elif kind == "value":
        width, _ = _type(case, result)
        if width is None:
            return None, reads, "result type width is not observable"
        # Oversized objects do not gain invented extension bits.
        number = result["value"] % (1 << width)
        bits = f"{number:0{width}b}"[::-1]
    elif kind == "register":
        key = str(result["register"])
        value = (case.context or {}).get("registers", {}).get(key)
        register_width = (case.context or {}).get("register_widths", {}).get(key, case.address_width)
        reads.append({"kind": "register", "register": key, "value": value, "bit_width": register_width})
        if count > register_width:
            # An original debugger may spread an oversized register object
            # across several physical registers. A single K register location
            # and an address-sized GPR snapshot do not specify that placement.
            # Padding here would fabricate unavailable object bits and turn an
            # observation gap into a semantic failure (or a false pass).
            return None, reads, "register-spanning object layout is not represented by the saved GPR fixture"
        bits = "?" * register_width if value is None else f"{value % (1 << register_width):0{register_width}b}"[::-1]
    elif kind == "memory":
        if memory_supplier is not None:
            memory_supplier.ensure(case.context, result["address"], (count + 7) // 8,
                                   reason="object at K-produced location")
        memory = (case.context or {}).get("memory", {})
        values = [memory.get(str(result["address"] + i)) for i in range((count + 7) // 8)]
        if "memory_requests" in (case.context or {}):
            request=next((r for r in case.context["memory_requests"] if r["address"]==result["address"] and r["size"]==len(values)),None)
            values=list(request["bytes"]) if request else [None]*len(values)
            reads.append({"kind":"memory_request","address":str(result["address"]),"size":len(values),"available":request is not None})
        reads.extend({"kind": "memory", "address": str(result["address"] + i), "value": v}
                     for i, v in enumerate(values))
        if case.origin.get("snapshot") and any(v is None for v in values):
            return None, reads, "object memory is outside the captured/readable original snapshot; collection coverage is insufficient"
        if case.origin.get("object_endianness", case.endianness) == "big":
            values.reverse()
        bits = "".join("?" * 8 if v is None else f"{v:08b}"[::-1] for v in values)
    else:
        return None, reads, "no completed location to materialize"
    bits=bits[:count] + "?" * max(0,count-len(bits))
    return bits[payload.get("object_bit_offset",0):], reads, None


def check(case, payload, execution="success", diagnostic=""):
    outcomes = []
    for assertion in case.upstream_assertions:
        item = {"id": assertion["id"], "source": assertion["source"], "target": assertion["target"],
                "mapping": assertion["mapping"], "expected": assertion["expected"], "details": [], "evidence": {}}
        failures, unknown = [], []
        target, expected = assertion["target"], assertion["expected"]
        if payload.get('observation_gap'):
            item.update(status='uncheckable',details=[payload['observation_gap']['diagnostic']],
                        evidence={'collection_limitation':payload['observation_gap']})
            outcomes.append(item)
            continue
        if execution in {"tool_error", "not_run"}:
            item.update(status=execution, details=[diagnostic])
            outcomes.append(item)
            continue
        if target == "uncheckable":
            unknown.append(assertion["mapping"])
        elif target == "no_crash":
            item["category"] = "no_crash_only"
        elif target == "stopped":
            if payload.get("status") != "incomplete":
                failures.append("expected an operation to remain unexecuted")
            if not {"position", "stack"} <= expected.keys():
                unknown.append("native error alone does not identify a K failure state")
            for name in ("position", "stack", "stop_reason"):
                if name in expected and payload.get(name) != expected[name]:
                    failures.append(f"{name} differs")
            item["evidence"] = {name: payload.get(name) for name in ("position", "stack", "stop_reason")}
            if expected.get("stable"):
                stability = payload.get("stability_evidence", {})
                item["evidence"]["stability"] = stability
                if not stability:
                    unknown.append("stopped assertion requires an independent larger-budget replay")
                else:
                    if stability.get("same_configuration") is not True or stability.get("probe_status") != "incomplete":
                        failures.append("larger-budget replay changed the stopped configuration")
                    steps, budget = stability.get("probe_rewrite_steps"), stability.get("probe_budget")
                    base_budget = stability.get("base_budget")
                    if not (type(steps) is int and type(budget) is int and type(base_budget) is int):
                        unknown.append("native rewrite counts are unavailable; stable configuration alone may be a loop")
                    elif budget <= base_budget or steps >= budget:
                        failures.append("larger-budget replay does not establish a natural stop")
        elif payload.get("status") != "completed":
            failures.append("K did not produce the successful result required by the source assertion")
        elif target == "properties":
            actual=payload.get("properties",{})
            item["evidence"]=actual
            for name,desired in expected.items():
                if name not in actual: unknown.append("attribute result missing: "+name)
                elif actual[name]!=desired: failures.append(f"{name}: {actual[name]} != {desired}")
        elif target in {"stack_top", "result"}:
            value = ((payload.get("stack") or [None])[-1] if target == "stack_top" else payload.get("observed_result",payload.get("result")))
            if not value:
                failures.append("required value is absent")
            else:
                item["evidence"] = deepcopy(value)
                number = value.get("value", value.get("address"))
                width, signed = _type(case, value)
                if "scalar" in expected:
                    equal, evidence = scalar_equal(number, width, signed, expected["scalar"])
                    item["evidence"]["scalar_equality"] = evidence
                    if equal is None:
                        unknown.append("source Scalar equality depends on unobservable native signedness")
                    elif not equal:
                        failures.append("source Scalar values differ after integer promotion")
                for name in ("kind", "type", "uninitialized"):
                    if name in expected and value.get(name) != expected[name]:
                        failures.append(f"{name} differs")
                if "register" in expected and value.get("register") != int(expected["register"]):
                    failures.append("register differs")
                if "integer" in expected and number != int(expected["integer"]):
                    failures.append(f"integer {number} != {expected['integer']}")
                if "bits" in expected:
                    # Source assertion width is authoritative for bit-pattern projection.
                    w = expected.get("width", width)
                    if number is None or w is None:
                        unknown.append("bit-pattern width is not observable")
                    elif number % (1 << w) != int(expected["bits"]) % (1 << w):
                        failures.append("value bit pattern differs")
                if "width" in expected and width != expected["width"]:
                    failures.append(f"effective width {width} != {expected['width']}")
                if "signed" in expected:
                    if signed is None:
                        unknown.append("generic has no Scalar signedness; cannot assert native representation")
                    elif signed != expected["signed"]:
                        failures.append("type signedness differs")
        elif target == "object":
            if "kind" in expected and (payload.get("result") or {}).get("kind") != expected["kind"]:
                failures.append("location kind differs")
            if "object_bytes" in expected:
                result = payload.get("result") or {}
                extent = (len(result["bytes"]) * 8 if result.get("kind") == "bytes" else
                          result.get("bit_size") if result.get("kind") == "composite" else
                          case.object_bit_size or case.object_size * 8)
                if extent != len(expected["object_bytes"]) * 8:
                    failures.append("object extent differs from the exact source buffer assertion")
            bits, reads, reason = materialize(case, payload)
            item["evidence"] = {"low_bit_first": bits, "reads": reads}
            if reason:
                unknown.append(reason)
            else:
                fields = list(expected.get("fields", []))
                for offset, data in [(0, expected["object_bytes"])] if "object_bytes" in expected else []:
                    for i, byte in enumerate(data):
                        fields.append({"offset": 8 * (offset + i), "size": 8, "bits": byte})
                for piece in expected.get("object_slices", []):
                    for i, byte in enumerate(piece["bytes"]):
                        fields.append({"offset": 8 * (piece["offset"] + i), "size": 8, "bits": byte})
                for field in fields:
                    observed = bits[field["offset"]:field["offset"] + field["size"]]
                    if len(observed) != field["size"]:
                        failures.append("field exceeds the captured object extent")
                    elif "available" in field:
                        known = "?" not in observed
                        if known != field["available"]:
                            failures.append(f"field availability differs at bit {field['offset']}")
                    elif "?" in observed:
                        failures.append(f"expected known field contains unavailable bits at {field['offset']}")
                    else:
                        number = int(observed[::-1], 2)
                        if "integer" in field:
                            if field.get("signed") and number >> (field["size"] - 1):
                                number -= 1 << field["size"]
                            desired = int(field["integer"])
                        else:
                            desired = int(field["bits"])
                        if number != desired:
                            failures.append(f"field at bit {field['offset']}: {number} != {desired}")
                if "availability" in expected:
                    mask = "".join("0" if b == "?" else "1" for b in bits[::-1])
                    if mask != expected["availability"]:
                        failures.append("object availability mask differs")
        semantic_checked = bool(expected) and target != "uncheckable" and len(unknown) < len(expected)
        unknown.extend(assertion.get("uncheckable", []))
        item.update(status="fail" if failures else "uncheckable" if unknown else "pass",
                    details=failures + unknown, predicates_passed=not failures and semantic_checked,
                    semantic_predicates_checked=semantic_checked,
                    semantic_check_complete=not unknown and target not in {'no_crash','uncheckable'})
        outcomes.append(item)
    return outcomes
