"""Load manually audited cases, without interpreting C++, Tcl or DWARF."""
import hashlib
import json
import re
from pathlib import Path

from .model import Case
from .context import validate


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_cases(location):
    path = Path(location)
    files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"no case files at {path}")
    cases, ids = [], set()
    required = {"id", "bytes", "address_width", "endianness", "dwarf_version",
                "delegate", "object_size", "origin", "compare"}
    allowed = required | {"expected", "requirements", "backends", "context", "architecture", "object_bit_size", "object_format", "lldb_type_source", "upstream_assertions", "purpose", "dependencies"}
    for file in files:
        doc = json.loads(file.read_text(), object_pairs_hook=unique_object)
        if not isinstance(doc, dict) or set(doc) != {"schema", "cases"} or type(doc["schema"]) is not int or doc["schema"] != 1 or not isinstance(doc["cases"], list):
            raise ValueError(f"{file}: expected schema=1 and cases list")
        for entry in doc["cases"]:
            if not isinstance(entry, dict) or not required <= set(entry) or set(entry) - allowed:
                raise ValueError(f"{file}: invalid case fields")
            name = entry["id"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in ids:
                raise ValueError(f"{file}: invalid or duplicate case id: {name!r}")
            if entry.get("purpose", "location") not in ("location", "value"):
                raise ValueError("purpose must be location or value")
            if not isinstance(entry.get("dependencies", []), list):
                raise ValueError("dependencies must be a list")
            dependency_ids=set()
            prior=set()
            after_seen=False
            for dep in entry.get("dependencies", []):
                if (not isinstance(dep,dict) or not {"id","bytes","purpose"}<=dep.keys()
                    or not isinstance(dep["id"],str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*",dep["id"])
                    or dep["id"] in dependency_ids or dep["id"]=="root"
                    or dep["purpose"] not in {"location","value"}
                    or not isinstance(dep["bytes"],list) or any(type(b) is not int or not 0<=b<=255 for b in dep["bytes"])
                    or dep.get("phase","after") not in {"before","after"}
                    or dep.get("assign") not in {None,"framebase","cfa","object_address"}):
                    raise ValueError("invalid attribute dependency")
                dependency_ids.add(dep["id"])
                if dep.get('phase','after')=='before':
                    if after_seen:raise ValueError('prerequisite dependencies must precede result dependencies')
                else:after_seen=True
                layout=dep.get('read_result')
                if layout is not None and (not isinstance(layout,dict)
                    or set(layout)-{'byte_size','bit_width','signed','endianness'}
                    or type(layout.get('byte_size')) is not int or layout['byte_size']<=0
                    or type(layout.get('bit_width',layout['byte_size']*8)) is not int
                    or not 0<layout.get('bit_width',layout['byte_size']*8)<=layout['byte_size']*8
                    or type(layout.get('signed',False)) is not bool
                    or layout.get('endianness','little') not in {'little','big'}):
                    raise ValueError('invalid referenced attribute object layout')
                if not isinstance(dep.get("bind",{}),dict) or any(k not in {"framebase","cfa","object_address"} or v not in prior | ({"root"} if dep.get("phase")!="before" else set()) for k,v in dep.get("bind",{}).items()):
                    raise ValueError("missing or cyclic attribute dependency")
                guard = dep.get('when')
                if guard is not None and (not isinstance(guard, dict)
                        or set(guard) != {'dependency', 'nonzero'}
                        or not isinstance(guard['dependency'], str)
                        or guard['dependency'] not in prior
                        or type(guard['nonzero']) is not bool):
                    raise ValueError('invalid or forward attribute guard')
                prior.add(dep["id"])
            raw = entry["bytes"]
            if not isinstance(raw, list) or any(type(x) is not int or not 0 <= x <= 255 for x in raw):
                raise ValueError(f"{name}: bytes must be integers in 0..255")
            if type(entry["address_width"]) is not int or entry["address_width"] <= 0:
                raise ValueError(f"{name}: address_width must be positive")
            target = entry.get("architecture")
            if target is not None and (target not in ("i386", "x86_64", "aarch64") or
                    entry["address_width"] != (32 if target == "i386" else 64) or entry["endianness"] != "little"):
                raise ValueError(f"{name}: architecture/width/endianness mismatch")
            if "context" in entry:
                validate(entry["context"], entry["address_width"])
            type_source = entry.get("lldb_type_source", "module")
            if type_source not in ("module", "delegate") or (type_source == "delegate" and
                    (entry.get("delegate") is not True or "types" not in entry.get("context", {}))):
                raise ValueError(f"{name}: delegate type source requires delegate=true and context.types")
            if entry["endianness"] not in ("little", "big") or type(entry["delegate"]) is not bool:
                raise ValueError(f"{name}: invalid endian/delegate")
            if type(entry["dwarf_version"]) is not int or not 2 <= entry["dwarf_version"] <= 5:
                raise ValueError(f"{name}: DWARF version must be 2..5")
            if type(entry["object_size"]) is not int or entry["object_size"] <= 0 or (entry.get("object_format", "integer") == "integer" and entry["object_size"] not in (1, 2, 4, 8)):
                raise ValueError(f"{name}: unsupported integer object size")
            if entry.get("object_format", "integer") not in ("integer", "bytes"):
                raise ValueError(f"{name}: object_format must be integer or bytes")
            bits = entry.get("object_bit_size", entry["object_size"] * 8)
            if type(bits) is not int or bits <= 0 or bits > entry["object_size"] * 8:
                raise ValueError(f"{name}: invalid object_bit_size")
            origin = entry["origin"]
            if not isinstance(origin, dict) or not {"project", "version", "file", "test", "assertion", "migration"} <= set(origin):
                raise ValueError(f"{name}: missing provenance")
            if any(not isinstance(origin[key], str) or not origin[key] for key in ("project", "version", "file", "test", "assertion", "migration")):
                raise ValueError(f"{name}: provenance fields must be nonempty strings")
            if origin["project"] not in ("lldb", "gdb", "project"):
                raise ValueError(f"{name}: unknown source project")
            source_file = Path(origin["file"])
            if source_file.is_absolute() or ".." in source_file.parts:
                raise ValueError(f"{name}: origin file must be source-relative")
            for field, values in [("compare", {"numeric", "kind", "type", "register", "object", "availability", "pieces"}),
                                  ("backends", {"k", "lldb", "gdb"})]:
                items = entry.get(field, ["k", "lldb", "gdb"])
                if not isinstance(items, list) or not items or any(not isinstance(x, str) or x not in values for x in items) or len(set(items)) != len(items):
                    raise ValueError(f"{name}: invalid {field}")
            if not isinstance(entry.get("requirements", []), list) or any(not isinstance(x, str) for x in entry.get("requirements", [])):
                raise ValueError(f"{name}: invalid requirements")
            expected = entry.get("expected", {})
            if not isinstance(expected, dict) or set(expected) - {"k", "lldb", "gdb"}:
                raise ValueError(f"{name}: invalid expected backends")
            for expectation in expected.values():
                if not isinstance(expectation, dict) or expectation.get("state") not in ("success", "error", "no_crash", "incomplete"):
                    raise ValueError(f"{name}: invalid expected assertion")
                properties = {"integer", "bits", "width", "native_kind", "native_context", "signed", "kind", "register", "object_bytes", "object_slices"}
                if set(expectation) - properties - {"state", "diagnostic_contains"}:
                    raise ValueError(f"{name}: unknown expected assertion property")
                if expectation["state"] != "success" and properties & expectation.keys():
                    raise ValueError(f"{name}: result assertions require state=success")
                for field in ("native_kind", "native_context", "kind"):
                    if field in expectation and not isinstance(expectation[field], str):
                        raise ValueError(f"{name}: expected {field} must be a string")
                if "signed" in expectation and type(expectation["signed"]) is not bool:
                    raise ValueError(f"{name}: expected signed must be Boolean")
                for field in ("integer", "bits"):
                    if field in expectation and not re.fullmatch(r"-?[0-9]+", str(expectation[field])):
                        raise ValueError(f"{name}: invalid expected integer")
                if "register" in expectation and (not isinstance(expectation["register"], str)
                        or not re.fullmatch(r"0|[1-9][0-9]*", expectation["register"])):
                    raise ValueError(f"{name}: invalid expected register identity")
                if "width" in expectation and (type(expectation["width"]) is not int or expectation["width"] <= 0):
                    raise ValueError(f"{name}: invalid expected width")
                if "diagnostic_contains" in expectation and (not isinstance(expectation["diagnostic_contains"], str) or not expectation["diagnostic_contains"]):
                    raise ValueError(f"{name}: invalid expected diagnostic substring")
                if "object_bytes" in expectation and (not isinstance(expectation["object_bytes"], list) or
                        any(type(b) is not int or not 0 <= b <= 255 for b in expectation["object_bytes"])):
                    raise ValueError(f"{name}: invalid expected object bytes")
                if "object_slices" in expectation:
                    slices = expectation["object_slices"]
                    if not isinstance(slices, list) or not slices or any(
                            not isinstance(s, dict) or set(s) != {"offset", "bytes"} or
                            type(s["offset"]) is not int or s["offset"] < 0 or not isinstance(s["bytes"], list) or
                            any(type(b) is not int or not 0 <= b <= 255 for b in s["bytes"]) for s in slices):
                        raise ValueError(f"{name}: invalid expected object byte slices")
            ids.add(name)
            from .assertions import validate_assertions
            validate_assertions(entry.get("upstream_assertions", []))
            cases.append(Case(**entry))
    if not cases:
        raise ValueError("empty corpus")
    return cases


def source_evidence(case, roots):
    origin = case.origin
    root = roots.get(origin["project"])
    if root is None:
        return {"status": "source_not_supplied"}
    file = Path(root) / origin["file"]
    if not file.is_file():
        return {"status": "source_file_missing", "path": str(file)}
    actual = hashlib.sha256(file.read_bytes()).hexdigest()
    recorded = origin.get("sha256")
    return {"status": "match" if recorded == actual else "changed" if recorded else "unverified",
            "path": str(file), "recorded_sha256": recorded, "actual_sha256": actual}
