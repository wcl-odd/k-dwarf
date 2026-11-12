#!/usr/bin/env python3
"""Load a JSON snapshot and invoke K; all DWARF evaluation stays in K."""

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import subprocess
import sys
import shutil
import fcntl
import time
import hashlib
from contextlib import contextmanager
from functools import wraps


# K serializes large builtin Maps as deep associative KAST trees. Allow their
# JSON representation; subsequent cell/map traversal is iterative. Compact CLI
# output avoids quadratic indentation for those complete configurations.
sys.setrecursionlimit(max(sys.getrecursionlimit(),100000))
ROOT = Path(__file__).resolve().parent
DEFAULT_DEFINITION = ROOT / "build/llvm-kompiled"
ENCODINGS = {
    "DW_ATE_address", "DW_ATE_boolean", "DW_ATE_signed", "DW_ATE_signed_char",
    "DW_ATE_unsigned", "DW_ATE_unsigned_char", "DW_ATE_UTF", "DW_ATE_UCS", "DW_ATE_ASCII", "DW_ATE_float",
}
SIGNED = {"DW_ATE_signed", "DW_ATE_signed_char"}
FIELDS = {
    "address_width", "endianness", "types", "registers", "memory",
    "framebase", "cfa", "initial_stack", "architecture", "debug_addr", "debug_addr_load_bias", "object_address",
    "register_widths",
    "raw_types",
    "memory_requests",
    "wasm_locations",
    "dwarf_offset_size", "compilation_unit_offset", "die_locations",
    "entry_context", "tls_addresses", "address_spaces",
}


@contextmanager
def frontend_slot():
    """Bound parser JVMs across independent replay/test processes.

    Each krun may launch several Java frontends, including a Java-version
    probe. Per-runner job limits alone do not bound the workspace's total
    thread count when LLVM, Haskell and corpus checks run concurrently.
    OS locks are released on cancellation, so there is no stale quota state.
    """
    slots=ROOT/'build/frontend-slots';slots.mkdir(parents=True,exist_ok=True)
    acquired=None
    try:
        while acquired is None:
            for index in range(4):
                handle=(slots/str(index)).open('a')
                try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:handle.close()
                else:acquired=handle;break
            if acquired is None:time.sleep(0.05)
        yield
    finally:
        if acquired is not None:
            fcntl.flock(acquired,fcntl.LOCK_UN);acquired.close()


def bounded_frontends(function):
    @wraps(function)
    def run_bounded(*args,**kwargs):
        # The adapter can reserve the quota before starting a child timeout.
        if os.environ.get("DWARF_FRONTEND_SLOT_HELD") == "1":
            return function(*args, **kwargs)
        with frontend_slot():return function(*args,**kwargs)
    return run_bounded


def parse_input(command, definition, environment):
    """Cache only K's pure parser output, never an evaluation or a result.

    The exact input bytes, complete definition fingerprint, parser options and
    Java options identify an entry. In particular the hex parser only produces
    byte tokens: opcode and LEB128 decoding still happens on every K execution.
    Set DWARF_K_PARSE_CACHE=off to independently repeat parsing without reuse.
    """
    if environment.get("DWARF_K_PARSE_CACHE") == "off":
        return subprocess.run(command, capture_output=True, text=True, env=environment)
    definition = Path(definition)
    parser = Path(shutil.which(command[0]) or command[0]).resolve()
    metadata = {"schema": 1, "definition": {
                    name: hashlib.sha256((definition / name).read_bytes()).hexdigest()
                    for name in ("compiled.bin", "cache.bin", "scanner") if (definition / name).is_file()},
                "parser": str(parser), "parser_sha256": hashlib.sha256(parser.read_bytes()).hexdigest() if parser.is_file() else None,
                "arguments": command[2:],
                "input_sha256": hashlib.sha256(Path(command[1]).read_bytes()).hexdigest(),
                "java_options": {key: environment.get(key) for key in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS")}}
    key = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    cache = definition / "input-parse-cache"
    cache.mkdir(exist_ok=True)
    target = cache / (key + ".json")
    with (cache / (key + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            entry = json.loads(target.read_text())
            if (entry.get("metadata") != metadata or
                    hashlib.sha256(entry["stdout"].encode()).hexdigest() != entry.get("stdout_sha256")):
                raise RuntimeError("K parser cache integrity failure: " + str(target))
            return subprocess.CompletedProcess(command, 0, entry["stdout"], entry["stderr"])
        result = subprocess.run(command, capture_output=True, text=True, env=environment)
        if result.returncode == 0:
            entry = {"metadata": metadata, "original_command": command, "stdout": result.stdout,
                     "stderr": result.stderr, "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()}
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(entry) + "\n")
            temporary.replace(target)
        return result


def integer(value, where):
    if type(value) is not int:
        raise ValueError(f"{where}: expected an integer")
    return value


def object_value(value, where):
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected an object")
    return value


def index_key(value, where, positive=False):
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ValueError(f"{where}: keys must be canonical nonnegative decimal strings")
    number = int(value)
    if positive and number == 0:
        raise ValueError(f"{where}: base-type references must be positive")
    return number


def generic_value(value, width, where):
    value = integer(value, where)
    if not -(1 << (width - 1)) <= value < (1 << width):
        raise ValueError(f"{where}: outside the generic {width}-bit representation range")
    return value


def kstring(value):
    return json.dumps(value, ensure_ascii=False)


def kmap(entries):
    return " ".join(f"{key} |-> {value}" for key, value in entries) or ".Map"



def entry_document(document):
    # Entry state is supplied independently. Only immutable decoding/type data
    # is inherited; missing entry registers, memory and frame data stay missing.
    return {**{key:document[key] for key in ("address_width","endianness","architecture","types","raw_types",
            "debug_addr","debug_addr_load_bias","dwarf_offset_size","compilation_unit_offset","die_locations") if key in document},
            **document["entry_context"]}


def validate_runtime(doc, width, endian):
    if doc.get("dwarf_offset_size",4) not in (4,8) or type(doc.get("dwarf_offset_size",4)) is not int:
        raise ValueError("dwarf_offset_size must be 4 or 8 bytes")
    if integer(doc.get("compilation_unit_offset",0),"compilation_unit_offset") < 0:
        raise ValueError("compilation_unit_offset must be nonnegative")
    for key, rec in object_value(doc.get("die_locations",{}),"die_locations").items():
        index_key(key,"die_locations")
        rec=object_value(rec,"die_locations."+key)
        allowed={"bytes","unit_offset","address_width","offset_size","types","raw_types","debug_addr","const_value","byte_size","type_ref"}
        if set(rec)-allowed:
            raise ValueError("unknown DIE fixture fields")
        data=rec.get("bytes",[])
        if not isinstance(data,list) or any(type(b) is not int or not 0<=b<=255 for b in data):
            raise ValueError("DIE location must contain raw bytes")
        for name in ("unit_offset","byte_size","type_ref"):
            if integer(rec.get(name,0),"DIE "+name)<0:raise ValueError("DIE metadata must be nonnegative")
        if "const_value" in rec:integer(rec["const_value"],"DIE const_value")
        prepare_context({"address_width":rec.get("address_width",width),"endianness":endian,
            "types":rec.get("types",{}),"raw_types":rec.get("raw_types",{}),
            "debug_addr":rec.get("debug_addr",{}),"dwarf_offset_size":rec.get("offset_size",doc.get("dwarf_offset_size",4))})
    for key,value in object_value(doc.get("tls_addresses",{}),"tls_addresses").items():
        index_key(key,"tls_addresses")
        if not 0<=integer(value,"TLS address")<1<<width:raise ValueError("TLS address must have address width")
    for key,memory in object_value(doc.get("address_spaces",{}),"address_spaces").items():
        index_key(key,"address_spaces")
        prepare_context({"address_width":width,"endianness":endian,"memory":memory})
    if "entry_context" in doc:
        entry=object_value(doc["entry_context"],"entry_context")
        if set(entry)-{"registers","register_widths","memory","memory_requests","framebase","cfa"}:
            raise ValueError("entry_context accepts only independent register, memory and frame snapshot data")
        prepare_context(entry_document(doc))


def runtime_surface(doc):
    """Serialize metadata only; no opcode/operand is interpreted here."""
    entries=[]
    for field,key in (("dwarf_offset_size","offset_size"),("compilation_unit_offset","unit_offset")):
        if field in doc:entries.append((kstring(key),str(doc[field])))
    if "entry_context" in doc:entries.append((kstring("entry"),prepare_context(entry_document(doc))[0]))
    for field,key in (("tls_addresses","tls"),("address_spaces","spaces")):
        if field in doc:
            entries.append((kstring(key),kmap([(int(k),kmap([(int(a),b) for a,b in v.items()]) if field=="address_spaces" else v) for k,v in doc[field].items()])))
    if "die_locations" in doc:
        dies=[]
        for key,rec in doc["die_locations"].items():
            block=".Bytes"
            for b in reversed(rec.get("bytes",[])):block=f"byteCons({b}, {block})"
            local={"address_width":rec.get("address_width",doc["address_width"]),"endianness":doc["endianness"],
                   "types":rec.get("types",{}),"raw_types":rec.get("raw_types",{})}
            ts=surface_types(local)
            const=f"someInt({rec['const_value']})" if "const_value" in rec else "noInt"
            dies.append((int(key),f"dieBody({block}, {local['address_width']}, {rec.get('unit_offset',0)}, {rec.get('offset_size',doc.get('dwarf_offset_size',4))}, {ts}, {kmap([(int(k),v) for k,v in rec.get('debug_addr',{}).items()])}, {const}, {rec.get('byte_size',0)}, {rec.get('type_ref',0)})"))
        entries.append((kstring("dies"),kmap(dies)))
    return kmap(entries)


def surface_types(doc):
    entries=[]
    for key,rec in doc.get("types",{}).items():
        entries.append((int(key),f"base({kstring(rec['id'])}, {kstring(rec['encoding'])}, {rec['bit_width']}, {rec['byte_size']})"))
    for key,rec in doc.get("raw_types",{}).items():
        attr=lambda n:f"someInt({rec[n]})" if n in rec else "noInt"
        entries.append((int(key),f"rawType({kstring(rec['id'])}, {kstring(rec['tag'])}, {kstring(rec.get('encoding',''))}, {attr('bit_width')}, {attr('byte_size')}, {kstring(json.dumps(rec,sort_keys=True))})"))
    return kmap(entries)

def configuration_ast(document):
    """Serialize validated context data, not expression operands, as KAST.

    K's JSON reader avoids the ambiguous surface Map concatenation grammar.
    Balanced Map trees also keep serialization depth logarithmic for snapshots.
    The constructors are those of dwarf-domains.k; K still checks their sorts.
    """
    def app(name, *args):
        return {"node": "KApply", "label": {"node": "KLabel", "name": name, "params": []},
                "arity": len(args), "args": list(args)}

    def token(value, sort="Int"):
        return {"node": "KToken", "sort": {"node": "KSort", "name": sort, "params": []},
                "token": kstring(value) if sort == "String" else str(value)}

    def base(record):
        return app("baseType", token(record["id"], "String"), token(record["encoding"], "String"),
                   token(record["bit_width"]), token(record["byte_size"]))

    def type_entry(pair):
        raw, record = pair
        if not raw:
            return base(record)
        def attribute(name):
            return (app("someInt(_)_DWARF-DOMAINS_OptionalInt_Int", token(record[name]))
                    if name in record else app("noInt_DWARF-DOMAINS_OptionalInt"))
        return app("rawType",token(record["id"],"String"),token(record["tag"],"String"),
                   token(record.get("encoding",""),"String"),attribute("bit_width"),attribute("byte_size"),
                   token(json.dumps(record,sort_keys=True),"String"))

    def mapping(records, encode=token, encode_key=token):
        items = [app("_|->_", encode_key(key), encode(value)) for key, value in records.items()]
        def tree(low, high):
            if high == low:
                return app(".Map")
            if high - low == 1:
                return items[low]
            mid = (low + high) // 2
            return app("_Map_", tree(low, mid), tree(mid, high))
        return tree(0, len(items))

    def optional(name):
        return (app("someInt(_)_DWARF-DOMAINS_OptionalInt_Int", token(document[name]))
                if name in document else app("noInt_DWARF-DOMAINS_OptionalInt"))

    memory_records=dict(document.get("memory",{}))
    if "memory_requests" in document:
        memory_records["request-mode"]=1
        memory_records.update({(rec["address"],rec["size"]):rec["bytes"] for rec in document["memory_requests"]})
    def memory_value(value):
        if not isinstance(value,list):return token(value)
        term=app("emptyBytes")
        for byte in reversed(value):term=app("byteCons",token(byte),term)
        return term
    def memory_key(key):
        if isinstance(key,tuple):return app("memoryRequest",token(key[0]),token(key[1]))
        if key=="request-mode":return app("requestMemoryMode")
        return token(key)

    register_records={key:(document.get("registers",{}).get(key),document.get("register_widths",{}).get(key))
                      for key in document.get("registers",{}).keys() | document.get("register_widths",{}).keys()}
    register_records.update({tuple(map(int,key.split(":"))):(rec["value"],rec["bit_width"])
                             for key,rec in document.get("wasm_locations",{}).items()})
    def register_key(key):
        return app("wasmSlot",token(key[0]),token(key[1])) if isinstance(key,tuple) else token(key)

    type_records={**{key:(False,rec) for key,rec in document.get("types",{}).items()},
                  **{key:(True,rec) for key,rec in document.get("raw_types",{}).items()}}
    encoded_types=mapping(type_records,type_entry)
    metadata={}
    for field,key in (("dwarf_offset_size","offset_size"),("compilation_unit_offset","unit_offset")):
        if field in document:metadata[key]=token(document[field])
    if "entry_context" in document:metadata["entry"]=configuration_ast(entry_document(document))[0]
    if "tls_addresses" in document:metadata["tls"]=mapping(document["tls_addresses"])
    if "address_spaces" in document:metadata["spaces"]=mapping(document["address_spaces"],lambda m:mapping(m))
    if "die_locations" in document:
        def die(rec):
            local={"address_width":rec.get("address_width",document["address_width"]),"endianness":document["endianness"],
                   "types":rec.get("types",{}),"raw_types":rec.get("raw_types",{})}
            types=configuration_ast(local)[0]["args"][2]
            return app("dieBody",memory_value(rec.get("bytes",[])),token(local["address_width"]),
                token(rec.get("unit_offset",0)),token(rec.get("offset_size",document.get("dwarf_offset_size",4))),
                types,mapping(rec.get("debug_addr",{})),
                app("someInt(_)_DWARF-DOMAINS_OptionalInt_Int",token(rec["const_value"])) if "const_value" in rec else app("noInt_DWARF-DOMAINS_OptionalInt"),
                token(rec.get("byte_size",0)),token(rec.get("type_ref",0)))
        metadata["dies"]=mapping(document["die_locations"],die)
    if metadata:
        encoded_types=app("_Map_",encoded_types,app("_|->_",token("runtime","String"),mapping(metadata,lambda x:x,lambda k:token(k,"String"))))

    context = app("ctx(_,_,_,_,_,_,_,_,_,_,_)_DWARF-DOMAINS_Context_Int_ByteOrder_Map_Map_Map_OptionalInt_OptionalInt_Architecture_Map_Int_OptionalInt",
                  token(document["address_width"]), app(document["endianness"] + "_DWARF-DOMAINS_ByteOrder"),
                  encoded_types, mapping(register_records,
                      lambda pair: app("unavailableRegister", token(pair[1])) if pair[0] is None else
                      token(pair[0]) if pair[1] is None else app("registerBits", token(pair[0]), token(pair[1])),register_key),
                  mapping(memory_records,memory_value,memory_key), optional("framebase"), optional("cfa"),
                  app(document.get("architecture", "unspecified") + "_DWARF-DOMAINS_Architecture"),
                  mapping(document.get("debug_addr", {})), token(document.get("debug_addr_load_bias", 0)),
                  optional("object_address"))
    stack = app("emptyStack")
    for item in document.get("initial_stack", []):
        ty = app("genericType") if item["type"] == "g" else base(document["types"][str(item["type"])])
        stack = app("stackPush", stack, app("typedValue", token(item["value"]), ty))
    return context, stack


def prepare_context(document):
    """Validate the external representation and serialize K configuration values."""
    doc = object_value(document, "context")
    unknown = set(doc) - FIELDS
    if unknown:
        raise ValueError(f"unknown context fields: {', '.join(sorted(unknown))}")
    if "address_width" not in doc or "endianness" not in doc:
        raise ValueError("address_width and endianness are required")
    width = integer(doc["address_width"], "address_width")
    if width <= 0:
        raise ValueError("address_width must be positive")
    endian = doc["endianness"]
    if endian not in ("little", "big"):
        raise ValueError("endianness must be little or big")

    architecture = doc.get("architecture", "unspecified")
    if architecture not in ("unspecified", "i386", "x86_64", "aarch64") or ("architecture" in doc and architecture == "unspecified"):
        raise ValueError("architecture must be i386, x86_64 or aarch64")
    if architecture != "unspecified" and (endian != "little" or width != (32 if architecture == "i386" else 64)):
        raise ValueError("architecture requires its matching address width and little endianness")

    types = {}
    identities = {}
    type_entries = []
    for key, record in object_value(doc.get("types", {}), "types").items():
        ref = index_key(key, "types", positive=True)
        record = object_value(record, f"types.{key}")
        if set(record) != {"id", "encoding", "bit_width", "byte_size"}:
            raise ValueError(f"types.{key}: expected id, encoding, bit_width, byte_size")
        identity, encoding = record["id"], record["encoding"]
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"types.{key}.id: expected a nonempty string")
        if not isinstance(encoding, str) or encoding not in ENCODINGS:
            raise ValueError(f"types.{key}.encoding: unsupported encoding {encoding!r}")
        bits = integer(record["bit_width"], f"types.{key}.bit_width")
        size = integer(record["byte_size"], f"types.{key}.byte_size")
        # DWARF 5 §2.5.1 permits any supported base type on the stack.
        # Only generic has address width; typed values may be wider.
        if bits <= 0 or size <= 0 or bits > 8 * size:
            raise ValueError(f"types.{key}: require 0 < bit_width <= 8*byte_size and byte_size > 0")
        if encoding == "DW_ATE_float" and bits not in (32, 64, 80, 128):
            raise ValueError(f"types.{key}: unsupported floating format {bits}")
        if identity in identities and identities[identity] != record:
            raise ValueError(f"types.{key}: conflicting metadata for type identity {identity!r}")
        identities[identity] = record
        term = f"base({kstring(identity)}, {kstring(encoding)}, {bits}, {size})"
        types[ref] = (record, term)
        type_entries.append((ref, term))

    widths = {}
    for key, record in object_value(doc.get("raw_types", {}), "raw_types").items():
        ref = index_key(key,"raw_types",positive=True)
        record = object_value(record,f"raw_types.{key}")
        if (set(record)-{"id","tag","encoding","bit_width","byte_size"} or
                any(not isinstance(record.get(name),str) or not record[name] for name in ("id","tag")) or
                ("encoding" in record and not isinstance(record["encoding"],str))):
            raise ValueError(f"raw_types.{key}: expected id, tag and optional encoding, bit_width, byte_size")
        if key in doc.get("types",{}):
            raise ValueError("types and raw_types references must not overlap")
        for name in ("bit_width","byte_size"):
            if name in record:integer(record[name],f"raw_types.{key}.{name}")
        attr=lambda name:f"someInt({record[name]})" if name in record else "noInt"
        type_entries.append((ref,f"rawType({kstring(record['id'])}, {kstring(record['tag'])}, {kstring(record.get('encoding',''))}, {attr('bit_width')}, {attr('byte_size')}, {kstring(json.dumps(record,sort_keys=True))})"))
    for key, bits in object_value(doc.get("register_widths", {}), "register_widths").items():
        index_key(key, "register_widths")
        if integer(bits, f"register_widths.{key}") <= 0:
            raise ValueError("register_widths entries must be positive bit counts")
        widths[key] = bits
    encoded_maps = {}
    for field in ("registers", "memory"):
        entries = []
        for key, value in object_value(doc.get(field, {}), field).items():
            index = index_key(key, field)
            if field == "memory":
                value = integer(value, f"memory.{key}")
                if not 0 <= index < (1 << width) or not 0 <= value <= 255:
                    raise ValueError(f"memory.{key}: require an address-width unsigned address and a byte in 0..255")
            else:
                value = generic_value(value, widths.get(key, width), f"{field}.{key}")
            entries.append((index, f"registerBits({value}, {widths[key]})" if field == "registers" and key in widths else value))
        encoded_maps[field] = kmap(entries)
    if set(widths) - doc.get("registers", {}).keys():
        encoded_maps["registers"] = kmap(
            [(int(key), f"registerBits({value}, {widths[key]})" if key in widths else value)
             for key, value in doc.get("registers", {}).items()] +
            [(int(key), f"unavailableRegister({widths[key]})") for key in widths if key not in doc.get("registers", {})])

    frame_values = {}
    wasm_entries=[]
    for key,rec in object_value(doc.get("wasm_locations",{}),"wasm_locations").items():
        if not isinstance(key,str) or not re.fullmatch(r"[0-3]:(0|[1-9][0-9]*)",key):
            raise ValueError("wasm_locations keys require kind:index with canonical nonnegative decimal index")
        rec=object_value(rec,f"wasm_locations.{key}")
        if set(rec)!={"value","bit_width"} or integer(rec["bit_width"],"wasm bit_width")<=0:
            raise ValueError("wasm_locations entries require value and positive bit_width")
        generic_value(rec["value"],rec["bit_width"],"wasm value")
        kind,index=map(int,key.split(":"))
        wasm_entries.append((f"wasmSlot({kind}, {index})",f"registerBits({rec['value']}, {rec['bit_width']})"))
    if wasm_entries:
        encoded_maps["registers"] = ("" if encoded_maps["registers"]==".Map" else encoded_maps["registers"]+" ")+kmap(wasm_entries)
    if "memory_requests" in doc:
        records=doc["memory_requests"]
        if not isinstance(records,list) or doc.get("memory"):
            raise ValueError("memory_requests requires a list and cannot be combined with sparse memory")
        entries=[("requestMemoryMode",1)];seen=set()
        for i,rec in enumerate(records):
            if not isinstance(rec,dict) or set(rec)!={"address","size","bytes"}:
                raise ValueError("memory_requests entries require address, size, bytes")
            address=integer(rec["address"],f"memory_requests[{i}].address")
            size=integer(rec["size"],f"memory_requests[{i}].size")
            if not 0<=address<1<<width or size<0 or address+size>1<<width or (address,size) in seen:
                raise ValueError("invalid or duplicate memory request address/size")
            seen.add((address,size))
            data=rec["bytes"]
            if not isinstance(data,list) or len(data)!=size or any(type(b) is not int or not 0<=b<=255 for b in data):
                raise ValueError("memory request must contain exactly size bytes")
            term=".Bytes"
            for byte in reversed(data):term=f"byteCons({byte}, {term})"
            entries.append((f"memoryRequest({address}, {size})",term))
        encoded_maps["memory"]=kmap(entries)
    for field in ("framebase", "cfa"):
        frame_values[field] = "noInt"
        if field in doc:
            # Independent unsigned address-width machine numbers; zero is known.
            value = integer(doc[field], field)
            if not 0 <= value < (1 << width):
                raise ValueError(f"{field}: expected an unsigned {width}-bit machine number")
            frame_values[field] = f"someInt({value})"

    for key, value in object_value(doc.get("debug_addr", {}), "debug_addr").items():
        index_key(key, "debug_addr")
        if integer(value, f"debug_addr.{key}") < 0:
            raise ValueError("debug_addr entries must be nonnegative")
    integer(doc.get("debug_addr_load_bias", 0), "debug_addr_load_bias")
    if "object_address" in doc and not 0 <= integer(doc["object_address"], "object_address") < 1 << width:
        raise ValueError("object_address must be an unsigned address-width integer")

    values = doc.get("initial_stack", [])
    if not isinstance(values, list):
        raise ValueError("initial_stack: expected a list in bottom-to-top order")
    stack = ".Stack"
    for index, item in enumerate(values):
        where = f"initial_stack[{index}]"
        item = object_value(item, where)
        if set(item) != {"value", "type"}:
            raise ValueError(f"{where}: expected value and type")
        if item["type"] == "g":
            number = generic_value(item["value"], width, f"{where}.value")
            ty = "g"
        else:
            ref = integer(item["type"], f"{where}.type")
            if ref not in types:
                raise ValueError(f"{where}.type: missing type reference {ref}")
            record, ty = types[ref]
            number = integer(item["value"], f"{where}.value")
            bits = record["bit_width"]
            lo, hi = (-(1 << (bits - 1)), 1 << (bits - 1)) if record["encoding"] in SIGNED else (0, 1 << bits)
            if not lo <= number < hi:
                raise ValueError(f"{where}.value: not representable by its type")
        stack = f"push({stack}, val({number}, {ty}))"

    validate_runtime(doc, width, endian)
    runtime=runtime_surface(doc)
    if runtime!=".Map":type_entries.append((kstring("runtime"),runtime))
    context = (
        f"ctx({width}, {endian}, {kmap(type_entries)}, "
        f"{encoded_maps['registers']}, {encoded_maps['memory']}, {frame_values['framebase']}, {frame_values['cfa']}, {architecture}, {kmap([(int(k),v) for k,v in doc.get('debug_addr', {}).items()])}, {doc.get('debug_addr_load_bias', 0)}, {'someInt(' + str(doc['object_address']) + ')' if 'object_address' in doc else 'noInt'})"
    )
    return context, stack


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_context(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def label(node):
    return node.get("label", {}).get("name", "")


def find_cell(node, name):
    pending=[node]
    while pending:
        current=pending.pop()
        if current.get("node")=="KApply" and label(current)==f"<{name}>":
            return current["args"][0]
        pending.extend(current.get("args",[]))
        pending.extend(current.get("items",[]))
    return None


def initializer_argument(term, name):
    """Read an input binding before K has expanded its configuration initializer."""
    pending = list(term["args"])
    while pending:
        node = pending.pop()
        if label(node) == "_Map_":
            pending.extend(node["args"])
        elif label(node) == "_|->_":
            key, value = node["args"]
            if key.get("sort", {}).get("name") == "KConfigVar" and key.get("token") == name:
                return value
    raise ValueError(f"missing initializer argument: {name}")


def evaluation_term(term):
    """Extract the single evaluation item from K's main computation cell."""
    state = find_cell(term, "expr")
    if state is None:
        raise ValueError("missing K evaluation cell: expr")
    if state.get("node") == "KSequence" and state["items"]:
        state = state["items"][0]
    return state



def root_inputs(term):
    """Find immutable root input even while a K continuation is suspended."""
    cell=find_cell(term,"expr")
    items=cell.get("items",[]) if cell.get("node")=="KSequence" else [cell]
    for item in reversed(items):
        if label(item) in {"returnCall","returnEntry","returnVariable"}:
            args=item["args"]
            return args[0],args[1],args[5]
    state=evaluation_term(term)
    return state["args"][0],state["args"][1],state["args"][-1]


def serialize_output_term(term):
    """Translate K output String tokens back to KAST input notation."""
    if term.get("node") == "KToken":
        return {**term, "token": json.dumps(term["token"], ensure_ascii=False)} if term["sort"]["name"] == "String" else term
    return {**term, "args": [serialize_output_term(a) for a in term.get("args", [])]}


def source_context(term):
    """Discard only frontend preparation wrappers, retaining supplied metadata.

    This is structural provenance recovery, never DWARF decoding. Execution and
    full-configuration checks continue to retain the prepared code itself.
    """
    if label(term) == "preparedDIE":
        return source_context(term["args"][0])
    if term.get("node") == "KToken":
        return term
    return {**term, "args": [source_context(a) for a in term.get("args", [])]}


def canonical_term(term, serialized=False):
    """Canonicalize builtin Map association/order for input identity checks."""
    if term.get("node")=="KToken":
        sort=term["sort"]["name"]
        return (sort,json.loads(term["token"]) if serialized and sort=="String" else term["token"])
    if term.get("node") == "KSequence":
        return ("KSequence", tuple(canonical_term(a, serialized) for a in term.get("items", [])))
    tag=label(term)
    if tag in {"_Map_",".Map","_|->_"}:
        entries=[];pending=[term]
        while pending:
            item=pending.pop()
            if label(item)=="_Map_":pending.extend(item["args"])
            elif label(item)=="_|->_":entries.append(tuple(canonical_term(a,serialized) for a in item["args"]))
            elif label(item)!=".Map":raise ValueError("malformed K map")
        return ("Map",tuple(sorted(entries,key=repr)))
    return (tag,tuple(canonical_term(a,serialized) for a in term.get("args",[])))

def decode_type(node):
    """Display only type identity; execution metadata stays in the configuration."""
    if label(node) == "genericType":
        return "g"
    if label(node) == "baseType":
        # Keep base identities distinct from the generic tag, even for id="g".
        return {"id": node["args"][0]["token"]}
    raise ValueError(f"unexpected K type constructor: {label(node)}")


def decode_value(node):
    if label(node) != "typedValue":
        raise ValueError("unexpected K value representation")
    number, ty = node["args"]
    return {"value": int(number["token"]), "type": decode_type(ty)}


def decode_result(node):
    """Decode the location result produced by K, without interpreting the program."""
    if label(node) == "implicitPointerLocation":
        return {"kind":"implicit_pointer","reference":int(node["args"][0]["token"]),"offset":int(node["args"][1]["token"])}
    if label(node) == "uninitializedLocation":
        return {**decode_result(node["args"][0]),"uninitialized":True}
    if label(node) == "bytesLocation":
        return {"kind": "bytes", "bytes": decode_bytes(node["args"][0])}
    if label(node) == "compositeLocation":
        pieces, bits = node["args"]
        size, value, mask = [int(arg["token"]) for arg in bits["args"]]
        entries = []
        while label(pieces) == "appendPiece":
            pieces, item = pieces["args"]
            args = item["args"]
            if label(item) == "bytePiece":
                entries.append({"kind": "piece", "byte_size": int(args[0]["token"]), "location": decode_result(args[1])})
            elif label(item) == "bitPiece":
                entries.append({"kind": "bit_piece", "bit_size": int(args[0]["token"]),
                                "bit_offset": int(args[1]["token"]), "location": decode_result(args[2])})
            else:
                raise ValueError("unexpected K piece")
        if label(pieces) != "emptyPieces":
            raise ValueError("unexpected K pieces")
        return {"kind": "composite", "pieces": list(reversed(entries)), "bit_size": size,
                "bits": "".join(str((value >> i) & 1) if (mask >> i) & 1 else "?" for i in reversed(range(size)))}
    if label(node) == "registerLocation":
        return {"kind": "register", "register": int(node["args"][0]["token"])}
    if label(node) == "memoryLocation":
        return {"kind": "memory", "address": int(node["args"][0]["token"])}
    if label(node) == "scalarResult":
        return {"kind": "scalar", **decode_value(node["args"][0])}
    if label(node) == "valueLocation":
        return {"kind": "value", **decode_value(node["args"][0])}
    if label(node) == "unavailableLocation":
        return {"kind": "unavailable"}
    raise ValueError(f"unexpected K location result: {label(node)}")


def decode_bytes(node):
    result = []
    while label(node) == "byteCons":
        byte, node = node["args"]
        result.append(int(byte["token"]))
    if label(node) != "emptyBytes":
        raise ValueError("unexpected K byte block")
    return result


def decode_diagnostic(state, position):
    """Report a missing instruction using K's saved prefix and byte evidence.

    This only observes constructors already produced by K. It does not decode
    opcodes or operands, classify DWARF validity, or infer a semantic failure.
    In particular, a bad suffix is irrelevant until the active PC reaches it.
    """
    if label(state) != "evaluation":
        return None
    expression = state["args"][0]
    if label(expression) != "decodedExpression":
        return None
    start, end, instructions, evidence = expression["args"]
    start, end = int(start["token"]), int(end["token"])
    if start != 0 or not 0 <= position < end:
        return None

    # Byte decoding produces a contiguous prefix. Do not classify arbitrary
    # gaps or operand positions in a caller-supplied algebraic expression.
    prefix_end = start
    while label(instructions) == "decodedInstruction":
        offset, _, following, instructions = instructions["args"]
        offset, following = int(offset["token"]), int(following["token"])
        if offset != prefix_end or not offset < following <= end:
            return None
        if position < following:
            return None
        prefix_end = following
    if label(instructions) != "emptyInstructions" or position != prefix_end:
        return None

    # Text inputs have no byte evidence. A core input may also deliberately
    # omit evidence; neither is grounds for a byte-decoding diagnosis.
    raw = decode_bytes(evidence)
    if len(raw) != end or any(not 0 <= byte <= 255 for byte in raw):
        return None
    return {
        "position": position,
        "opcode_byte": raw[position],
        "remaining_byte_count": end - position,
        "reason": "no_complete_instruction",
        "message": (
            "K's saved decoded prefix has no complete instruction at this byte position. "
            "The encoding may be truncated, the opcode unknown/unsupported, or the "
            "decoding parameters unsupported."
        ),
    }


def decode_stack(node):
    values = []
    while label(node) == "stackPush":
        node, value = node["args"]
        values.append(decode_value(value))
    if label(node) != "emptyStack":
        raise ValueError("unexpected K stack representation")
    return list(reversed(values))


def evaluate(expression, context, definition=DEFAULT_DEFINITION, depth=None, input_format="text", statistics=False, purpose="location"):
    if input_format not in ("text", "hex"):
        raise ValueError("input_format must be text or hex")
    return _evaluate(expression, context, definition, depth, input_format, statistics, purpose)


def evaluate_decoded(expression, context, definition, depth=None, statistics=False, purpose="location", prepared_context=None):
    """Run a K algebraic DecodedExpression with an independently compiled core.

    This development/proof entry does not add a corpus format. Contexts requiring
    DIE code must already supply prepared code through the K core interface;
    JSON byte-code contexts belong to the integrated text/hex frontend.
    prepared_context, when supplied, uses output KAST token notation as retained
    by root_inputs; its source code has already been prepared by K.
    """
    if prepared_context is None and (context.get("die_locations") or context.get("entry_context", {}).get("die_locations")):
        raise ValueError("decoded core entry requires prepared DIE metadata; use its K Context interface")
    return _evaluate(expression, context, definition, depth, "decoded", statistics, purpose, prepared_context)


@bounded_frontends
def _evaluate(expression, context, definition, depth, input_format, statistics, purpose, prepared_context=None):
    if purpose not in ("location", "value"):
        raise ValueError("purpose must be location or value")
    prepare_context(context)
    encoded_context, encoded_stack = configuration_ast(context)
    if prepared_context is not None:
        encoded_context = serialize_output_term(prepared_context)
    definition = Path(definition).resolve()
    if not (definition / "compiled.bin").exists():
        raise ValueError(f"compiled definition not found at {definition}; see semantics/README.md")
    # Both source formats are parsed by K. Its KORE output is passed through
    # unchanged; Python does not inspect expression tokens or decoded operands.
    main_module = "DWARF-CORE" if input_format == "decoded" else "DWARF"
    module, sort = (("DWARF-MEMORY-PROBE", "Input") if input_format == "memory-probe" else
                    ("DWARF-CORE", "Input") if input_format == "decoded" else
                    ("DWARF-TEXT-SYNTAX", "Input") if input_format == "text" else
                    ("DWARF-HEX-SYNTAX", "Input"))
    # A parallel corpus run starts several Java frontends. On large hosts the
    # JVM otherwise creates a host-sized GC pool per parser, exhausting thread
    # limits and sometimes writing startup warnings into its KORE stdout.
    # Respect an explicitly supplied processor limit.
    environment = os.environ.copy()
    input_tmp = Path(os.environ.get("DWARF_INPUT_TMPDIR", str(Path(tempfile.gettempdir()) / "scratch" / f"kframework-run-{os.getpid()}")))
    input_tmp.mkdir(parents=True, exist_ok=True)
    environment["TMPDIR"] = str(input_tmp)
    java_options = environment.get("JAVA_TOOL_OPTIONS", "")
    if "ActiveProcessorCount" not in java_options and "ActiveProcessorCount" not in environment.get("JDK_JAVA_OPTIONS", ""):
        java_options = (java_options + " -XX:ActiveProcessorCount=1").strip()
    # Batch replays also run Haskell/GDB checks. Serial GC avoids allocating a
    # separate parallel GC pool in each short-lived parser JVM. Respect a
    # caller-selected collector; JVM startup warnings can otherwise corrupt
    # KORE stdout when the host's thread quota is exhausted.
    if not re.search(r"[+-]Use\w*GC",java_options+' '+environment.get('JDK_JAVA_OPTIONS','')):
        java_options+=' -XX:+UseSerialGC'
    environment["JAVA_TOOL_OPTIONS"]=java_options.strip()
    parser_command = ["kparse", str(Path(expression).resolve()),
                      "--definition", str(definition), "--module", module, "--sort", sort]
    if input_format in ("decoded", "memory-probe") and Path(expression).suffix == ".json":
        parser_command += ["--input", "json"]
    parsed = parse_input(parser_command, definition, environment)
    if parsed.returncode:
        raise RuntimeError(parsed.stderr.strip() or "K input parser failed")
    command = ["krun", "--definition", str(definition), "--parser", "cat",
               "--output", "json", "--color", "off"]
    if depth is not None:
        if type(depth) is not int or depth < 0:
            raise ValueError("depth must be a nonnegative integer")
        command.extend(["--depth", str(depth)])
    if statistics and (definition / "interpreter").is_file():
        command.append("--statistics")
    (ROOT / "build").mkdir(exist_ok=True)
    input_tmp = Path(os.environ.get("DWARF_INPUT_TMPDIR", str(Path(tempfile.gettempdir()) / "scratch" / f"kframework-run-{os.getpid()}")))
    input_tmp.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="input-", dir=input_tmp) as directory:
        program = Path(directory) / "program.kore"
        program.write_text(parsed.stdout)
        # krun's -c argument holds a file name, not the potentially megabytes of
        # snapshot data. Its parser receives a file containing that name.
        reader = Path(directory) / "read-kore"
        reader.write_text(f"#!{sys.executable}\nimport pathlib, sys\n"
                          "sys.stdout.write(pathlib.Path(pathlib.Path(sys.argv[1]).read_text()).read_text())\n")
        reader.chmod(0o755)
        # JSON KAST is a structural serialization of the existing data domains,
        # not a second DWARF parser. Preserve every captured register and byte.
        for name, term, sort in (("CONTEXT", encoded_context, "Context"), ("STACK", encoded_stack, "Stack"),
                                 ("PURPOSE", {"node":"KApply", "label":{"node":"KLabel", "name":purpose + "Purpose_DWARF-DOMAINS_Purpose", "params":[]}, "arity":0, "args":[]}, "Purpose")):
            source = Path(directory) / f"{name}.json"
            source.write_text(json.dumps({"format": "KAST", "version": 4, "term": term}))
            converted = parse_input(["kparse", str(source), "--definition", str(definition),
                                     "--module", main_module, "--input", "json", "--sort", sort], definition, environment)
            if converted.returncode:
                raise RuntimeError(converted.stderr.strip() or "K configuration reader failed")
            serialized = Path(directory) / f"{name}.kore"
            serialized.write_text(converted.stdout)
            command.extend([f"-p{name}={reader}", f"-c{name}={serialized}"])
        process = subprocess.run(command + [str(program)], capture_output=True, text=True, env=environment)
        if process.returncode:
            # Keep the actual serialized parser inputs on tool failure. A
            # frontend warning on KORE stdout otherwise disappears with the
            # temporary directory and becomes impossible to diagnose/replay.
            failed=ROOT/'build/failed-inputs'/Path(directory).name
            failed.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(directory,failed)
            (failed/'stdout.txt').write_text(process.stdout)
            (failed/'stderr.txt').write_text(process.stderr)
            original=[str(x) for x in command+[str(program)]]
            (failed/'command.json').write_text(json.dumps({'original_argv':original,
                'replay_argv':[x.replace(directory,str(failed)) for x in original],
                'definition':str(definition)},indent=2))
            process.stderr+='\nSaved parser inputs: '+str(failed)+'\n'
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or "krun failed")
    if statistics:
        # Preserve the backend's own count. Never infer steps from pc or OPs.
        count = re.match(r"\[[0-9]+ steps\]\s*\n", process.stdout)
        if count:
            print(count[0], end="", file=sys.stderr)
            process.stdout = process.stdout[count.end():]
        print(process.stderr, end="", file=sys.stderr)
    configuration = json.loads(process.stdout)
    native_configuration = None
    if input_format == "decoded":
        # The independent core's syntax module includes STRING-SYNTAX. K emits
        # its String tokens in literal notation; the source-only syntax module
        # used by the integrated driver emits their semantic contents instead.
        # Normalize this serialization difference and retain the native KAST.
        native_configuration = configuration
        def semantic_tokens(node):
            if node.get("node") == "KToken":
                return {**node, "token": json.loads(node["token"])} if node["sort"]["name"] == "String" else node
            return {**node, "args": [semantic_tokens(a) for a in node["args"]]} if "args" in node else {**node, "items": [semantic_tokens(a) for a in node["items"]]} if "items" in node else node
        configuration = {**configuration, "term": semantic_tokens(configuration["term"])}
    term = configuration["term"]
    # At depth 0 Haskell may leave initGeneratedTopCell unsimplified, with no
    # cells yet; retain the actual KAST and display the input stack.
    # Report initial zeros before K has calculated the program length.
    if label(term) == "initGeneratedTopCell":
        return {"status": "incomplete", "position": 0, "end": 0,
                "stack": decode_stack(initializer_argument(term, "$STACK")),
                "result": None,
                "stop_reason": None,
                "configuration": configuration}
    state = evaluation_term(term)
    result = None
    stop_reason = None
    # Separate collection-only definition: this is a request for raw input,
    # never a core result or a classification of a stuck DWARF expression.
    if input_format == "memory-probe" and label(state) == "memoryDemand":
        _, _, end, _, scope, address, size = state["args"]
        return {"status": "input_needed", "position": int(find_cell(term, "pc")["token"]),
                "end": int(end["token"]), "stack": decode_stack(find_cell(term, "stack")),
                "result": None, "stop_reason": None, "configuration": configuration,
                "memory_request": {"scope": scope["token"], "address": str(address["token"]),
                                   "size": int(size["token"])}}
    if label(state) == "inputError":
        raise ValueError(state["args"][2]["token"])
    if label(state) == "evaluation":
        _, _, end, _ = state["args"]
        complete = False
    # Compatibility with archived definitions; current rules stop naturally
    # in evaluation (or a child finished item with pending continuations).
    # Neither incomplete nor a finite budget alone proves an invalid input.
    elif label(state) == "stoppedEvaluation":
        _, _, end, reason, _ = state["args"]
        complete = False
        stop_reason = {"kind": reason["token"]}
    elif label(state) == "finishedEvaluation":
        _, _, end, location, _ = state["args"]
        result = decode_result(location)
        complete = True
    else:
        raise ValueError(f"unexpected K evaluation constructor: {label(state)}")
    position = int(find_cell(term, "pc")["token"])
    end = int(end["token"])
    stack = find_cell(term, "stack")
    control_cell = find_cell(term, "expr")
    nested = control_cell.get("node") == "KSequence" and len(control_cell["items"]) > 1
    complete = complete and position == end and not nested
    diagnostic = decode_diagnostic(state, position) if not complete else None
    return {"status": "completed" if complete else "incomplete", "position": position,
            "end": end, "stack": decode_stack(stack), "result": result if complete else None,
            "stop_reason": stop_reason,
            **({"decode_error": diagnostic} if diagnostic is not None else {}),
            "configuration": configuration,
            **({"native_configuration": native_configuration} if native_configuration is not None else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expression", type=Path)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--format", choices=("text", "hex"), default="text",
                        help="offset-annotated OP text (default) or hexadecimal bytes; parsed by K")
    parser.add_argument("--depth", type=int, help="K rewrite budget, not DWARF instruction count")
    parser.add_argument("--purpose", choices=("location", "value"), default="location")
    parser.add_argument("--statistics", action="store_true", help="preserve native K rewrite statistics on stderr (LLVM)")
    args = parser.parse_args()
    try:
        result = evaluate(args.expression, read_context(args.context), args.definition, args.depth, args.format, args.statistics, args.purpose)
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
