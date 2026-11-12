import sys
import json
import hashlib
from pathlib import Path

from ..model import Observation
from ..process import ToolFailure, execute, read_payload
from ..input import write_json
import run as dwarf

ROOT = Path(__file__).resolve().parents[2]


def run(case, directory, options):
    supplier = getattr(options, "memory_supplier", None)
    if supplier is not None:
        supplier.before_expression(case)
        write_json(directory / "context.json", {"address_width":case.address_width,
            "endianness":case.endianness, **({"architecture":case.architecture} if case.architecture else {}),
            **(case.context or {})})
    command = [sys.executable, ROOT / "run.py", directory / "expression.hex",
        "--format", "hex", "--context", directory / "context.json",
        "--definition", options.definition, "--purpose", case.purpose]
    if getattr(options, "depth", None) is not None:
        command += ["--depth", str(options.depth)]
    if getattr(options, "statistics", False):
        command.append("--statistics")
    process = execute(command, directory / "k", options.timeout)
    if process.returncode not in (0, 1):
        raise ToolFailure(f"K invocation: exit {process.returncode}: {process.stderr[-2000:]}")
    value = read_payload(process.stdout)
    if getattr(options, "statistics", False):
        value["rewrite_statistics"] = {"raw": process.stderr}
    expected_status = "completed" if process.returncode == 0 else "incomplete"
    if value.get("status") != expected_status or "configuration" not in value:
        raise ToolFailure("K status/exit code or configuration protocol mismatch")
    term = value["configuration"]["term"]
    if dwarf.label(term) == "initGeneratedTopCell":
        program = dwarf.initializer_argument(term, "$PGM")
        final_context = dwarf.initializer_argument(term, "$CONTEXT")
        final_purpose = dwarf.initializer_argument(term, "$PURPOSE")
    else:
        program, final_context, final_purpose = dwarf.root_inputs(term)
    # Prepared E retains original bytes as inert audit data. No OP or operand
    # is decoded in Python; legacy/unexpanded configurations retain byte tokens.
    decoded_program = program if dwarf.label(program) == "decodedExpression" else None
    if decoded_program is not None:
        supplied = dwarf.decode_bytes(decoded_program["args"][3])
        tokens = [f"{byte:02x}" for byte in supplied]
        program = {"args": []}
    else:
        tokens = []
    while len(program.get("args", [])) == 2 and program["args"][0].get("sort", {}).get("name") == "HexByte":
        token, program = program["args"]
        tokens.append(token["token"].lower().removeprefix("0x"))
    unchanged = (tokens == [f"{byte:02x}" for byte in case.bytes] and not program.get("args")
                 and dwarf.label(final_purpose).startswith(case.purpose+'Purpose_'))
    write_json(directory / "k/input-evidence.json", {"unchanged": unchanged, "observed_hex": tokens,
        'observed_purpose':dwarf.label(final_purpose),
        'decoded_input_sha256': hashlib.sha256(repr(dwarf.canonical_term(decoded_program)).encode()).hexdigest() if decoded_program else None,
        'byte_evidence_role': 'inert provenance; execution queries decoded operations' if decoded_program else 'legacy source input'})
    if not unchanged:
        raise ToolFailure("K final expression differs from supplied raw bytes")
    if case.context is not None:
        context = final_context["args"]
        def decode_base(node):
            if dwarf.label(node) != "baseType":
                raise ToolFailure("unexpected K base type")
            identity, encoding, width, size = node["args"]
            return {"id": identity["token"], "encoding": encoding["token"],
                    "bit_width": int(width["token"]), "byte_size": int(size["token"])}
        def context_map(node, decode=lambda item: int(item["token"]), decode_key=lambda item:str(int(item["token"]))):
            result={};pending=[node]
            while pending:
                item=pending.pop();tag=dwarf.label(item)
                if tag==".Map":continue
                if tag=="_Map_":pending.extend(item["args"])
                elif tag=="_|->_":
                    key,value=item["args"];result[decode_key(key)]=decode(value)
                else:raise ToolFailure("unexpected K context map")
            return result
        register_entries = context_map(context[3], lambda node: node,
            lambda node:tuple(int(a["token"]) for a in node["args"]) if dwarf.label(node)=="wasmSlot" else str(int(node["token"])))
        memory_entries=context_map(context[4],lambda node:node,lambda node:tuple(int(a["token"]) for a in node["args"]) if dwarf.label(node)=="memoryRequest" else
            "request-mode" if dwarf.label(node)=="requestMemoryMode" else str(int(node["token"])))
        actual = {"registers": {}, "memory":{key:int(node["token"]) for key,node in memory_entries.items() if key!="request-mode" and not isinstance(key,tuple)}}
        observed_widths = {}
        for key, node in register_entries.items():
            if isinstance(key,tuple):
                actual.setdefault("wasm_locations",{})[f"{key[0]}:{key[1]}"]={"value":int(node["args"][0]["token"]),"bit_width":int(node["args"][1]["token"])}
                continue
            if dwarf.label(node) == "registerBits":
                actual["registers"][key] = int(node["args"][0]["token"])
                observed_widths[key] = int(node["args"][1]["token"])
            elif dwarf.label(node) == "unavailableRegister":
                observed_widths[key] = int(node["args"][0]["token"])
            else:
                actual["registers"][key] = int(node["token"])
        expected = {key: case.context.get(key, {}) for key in ("registers", "memory")}
        if "wasm_locations" in case.context or "wasm_locations" in actual:
            expected["wasm_locations"]=case.context.get("wasm_locations",{})
            actual.setdefault("wasm_locations",{})
        if "request-mode" in memory_entries:
            actual["memory_requests"]=[{"address":key[0],"size":key[1],"bytes":dwarf.decode_bytes(node)} for key,node in memory_entries.items() if isinstance(key,tuple)]
            actual["memory_requests"].sort(key=lambda r:(r["address"],r["size"]))
            expected["memory_requests"]=sorted(case.context.get("memory_requests",[]),key=lambda r:(r["address"],r["size"]))
        if observed_widths or "register_widths" in case.context:
            actual["register_widths"] = observed_widths
            expected["register_widths"] = case.context.get("register_widths", {})
        type_entries = context_map(context[2], lambda node:node,
            lambda node:node["token"] if node.get("sort",{}).get("name")=="String" else str(int(node["token"])))
        runtime=type_entries.pop('"runtime"',None)
        # K String token JSON carries its textual value without quotes in the
        # output. Accept either spelling only as a key, never a value default.
        runtime=type_entries.pop("runtime",runtime)
        if runtime is not None:
            doc={"address_width":case.address_width,"endianness":case.endianness,
                 **({"architecture":case.architecture} if case.architecture else {}),**case.context}
            expected_context=dwarf.configuration_ast(doc)[0]
            if dwarf.canonical_term(dwarf.source_context(final_context))!=dwarf.canonical_term(expected_context,serialized=True):
                raise ToolFailure("K fixed runtime metadata differs from original input")
        raw_types = {key:json.loads(node["args"][-1]["token"]) for key,node in type_entries.items() if dwarf.label(node)=="rawType"}
        actual["types"] = {key:decode_base(node) for key,node in type_entries.items() if dwarf.label(node)!="rawType"}
        expected["types"] = case.context.get("types", {})
        if raw_types or "raw_types" in case.context:
            actual["raw_types"] = raw_types
            expected["raw_types"] = case.context.get("raw_types", {})
        for index, field in ((5, "framebase"), (6, "cfa"), (10, "object_address")):
            node = context[index]
            actual[field] = (int(node["args"][0]["token"])
                             if dwarf.label(node).startswith("someInt") else None)
            expected[field] = case.context.get(field)
        actual["debug_addr"] = context_map(context[8])
        expected["debug_addr"] = case.context.get("debug_addr", {})
        actual["debug_addr_load_bias"] = int(context[9]["token"])
        expected["debug_addr_load_bias"] = case.context.get("debug_addr_load_bias", 0)
        unchanged = (actual == expected and int(context[0]["token"]) == case.address_width
                     and dwarf.label(context[1]).startswith(case.endianness + "_")
                     and dwarf.label(context[7]).startswith((case.architecture or 'unspecified')+'_'))
        write_json(directory / "k/context-evidence.json", {"unchanged": unchanged, "observed": actual})
        if not unchanged:
            raise ToolFailure("K final context differs from shared input")
    observation = Observation("k", "success" if process.returncode == 0 else "incomplete", native=value)
    result = value.get("result")
    if observation.state == "success":
        if not isinstance(result, dict) or result.get("kind") not in ("memory", "value", "unavailable", "register", "bytes", "composite", "scalar", "implicit_pointer"):
            raise ToolFailure("missing K location result")
        observation.kind = result["kind"]
        if result["kind"] in ("bytes", "composite"):
            if result["kind"] == "bytes":
                data = result["bytes"]
                observation.object_bits = "".join(f"{b:08b}" for b in reversed(data))
                observation.availability = "1" * len(observation.object_bits)
            else:
                display = result["bits"]
                observation.object_bits = display.replace("?", "0")
                observation.availability = "".join("0" if bit == "?" else "1" for bit in display)
                observation.pieces = result["pieces"]
        elif result["kind"] == "register":
            number = result.get("register")
            if type(number) is not int or number < 0:
                raise ToolFailure("invalid K register identity")
            observation.register = str(number)
        elif result["kind"] == "implicit_pointer":
            pass  # identity and offset are preserved in native result, not a numeric address
        elif result["kind"] != "unavailable":
            number = result["address"] if result["kind"] == "memory" else result["value"]
            observation.integer = str(number)
            observation.width = case.address_width
            if result["kind"] in ("value", "scalar") and result.get("type") == "g":
                observation.type_identity = "generic"
            elif result["kind"] in ("value", "scalar"):
                identity = result["type"]["id"]
                records = {**(case.context or {}).get("types", {}), **(case.context or {}).get("raw_types", {})}.values()
                record = next((record for record in records if record["id"] == identity), None)
                if record is None:
                    raise ToolFailure("K result type has no shared metadata")
                observation.type_identity = identity
                observation.width = record.get("bit_width", 8 * record.get("byte_size", 0))
            # A raw upstream DIE can declare an enormous width. For an already
            # nonnegative representable carrier there is no reason to allocate
            # 2**width simply to preserve that same integer in the observation.
            observation.bits = str(number if number >= 0 and number.bit_length() <= observation.width
                                   else number % (1 << observation.width))
    return observation
