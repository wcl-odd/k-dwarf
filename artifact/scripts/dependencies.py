"""Schedule attribute expressions; only K evaluates DWARF operations."""

from cases import replace_case as replace, prepare, write_json
import k


class ObservationGap(Exception):
    """Interface data is insufficient to observe a location returned by K."""


def read_object_integer(case, payload, context, byte_size):
    """Observe an object at a K location, without evaluating any DWARF OP."""
    from requirements import materialize

    projected = replace(
        case, context=context, object_byte_size=byte_size, object_bit_size=byte_size * 8
    )
    bits, reads, gap = materialize(projected, payload)
    if gap or bits is None or len(bits) < byte_size * 8 or "?" in bits[: byte_size * 8]:
        raise ObservationGap(
            gap or "pointer/count object has unavailable bits in the archived snapshot"
        )
    return int(bits[: byte_size * 8][::-1], 2), reads


def root_observation(case, payload, context, evidence):
    if case.observation_inputs.get("pointer_root_size"):
        number, reads = read_object_integer(
            case, payload, context, case.observation_inputs["pointer_root_size"]
        )
        payload["observed_value"] = number
        payload["object_location"] = {"kind": "memory", "address": number}
        evidence.append(
            {"id": "root-pointer-object", "object_reads": reads, "value": str(number)}
        )
    if case.observation_inputs.get("count_root"):
        result = payload.get("result") or {}
        if result.get("kind") in {"memory", "register"}:
            number, reads = read_object_integer(case, payload, context, 4)
            payload["observed_value"] = number
            evidence.append(
                {"id": "root-count-object", "object_reads": reads, "value": str(number)}
            )


def implicit_observation(case, payload, context, directory, options, evidence):
    """Resolve a referenced DIE by invoking K on its supplied location expression.

    A DW_AT_const_value is metadata, so observing it needs no expression.
    Cycles and missing interface data are observation gaps, never guessed values.
    The original implicit-pointer result and every additional K outcome are retained.
    """
    result = payload.get("result") or {}
    offset = case.observation_inputs.get("projection_byte_offset", 0)
    seen = set()
    chain = []
    while result.get("kind") == "implicit_pointer":
        reference = str(result["reference"])
        offset += result["offset"]
        if reference in seen or len(seen) >= 32:
            raise ObservationGap("cyclic or excessive implicit-reference dependency")
        seen.add(reference)
        body = context.get("die_locations", {}).get(reference)
        if body is None:
            raise ObservationGap("referenced DIE metadata was not captured")
        constants = case.observation_inputs.get("referent_constants", {})
        if reference in constants:
            result = {"kind": "bytes", "bytes": constants[reference]}
            evidence.append(
                {"id": "referent-" + reference, "constant_bytes": constants[reference]}
            )
        elif "const_value" in body:
            width = body.get("byte_size", 0)
            if width <= 0:
                raise ObservationGap("referenced constant has no object size")
            number = body["const_value"] % (1 << (width * 8))
            result = {
                "kind": "bytes",
                "bytes": list(number.to_bytes(width, case.endianness)),
            }
            evidence.append(
                {
                    "id": "referent-" + reference,
                    "constant_integer": str(body["const_value"]),
                    "byte_size": width,
                }
            )
        else:
            interface = {
                **context,
                "compilation_unit_offset": body.get("unit_offset", 0),
                "dwarf_offset_size": body.get("offset_size", 4),
                "raw_types": body.get("raw_types", {}),
                "types": body.get("types", {}),
                "debug_addr": body.get("debug_addr", {}),
            }
            dependency_case = replace(
                case,
                id=case.id + "--referent-" + reference,
                bytes=body["bytes"],
                purpose="location",
                context=interface,
                address_width=body.get("address_width", case.address_width),
                dependencies=[],
                predicates=[],
            )
            dependency_directory = (
                directory / "dependencies" / ("referent-" + reference)
            )
            prepare(dependency_case, dependency_directory)
            observation = k.run(dependency_case, dependency_directory, options)
            evidence.append(
                {
                    "id": "referent-" + reference,
                    "status": observation.outcome.get("status"),
                    "result": observation.outcome.get("result"),
                    "directory": str(dependency_directory),
                }
            )
            if observation.state == "tool_error":
                raise ValueError(observation.diagnostic)
            if observation.state != "success":
                raise ObservationGap("referenced location expression did not complete")
            result = observation.outcome["result"]
            chain.append(observation.outcome)
    payload["implicit_dependencies"] = [
        {
            "status": dependency_outcome.get("status"),
            "result": dependency_outcome.get("result"),
        }
        for dependency_outcome in chain
    ]
    if result.get("kind") == "memory":
        payload["object_location"] = {**result, "address": result["address"] + offset}
    elif offset < 0:
        raise ObservationGap(
            "implicit pointer projects before the captured value object"
        )
    else:
        payload["object_location"] = result
        payload["object_bit_offset"] = offset * 8
    if case.observation_inputs.get("observe_referent_address"):
        if result.get("kind") != "memory":
            raise ObservationGap("referent has no observable memory address")
        payload["observed_result"] = payload["object_location"]


def value(payload):
    if "observed_value" in payload:
        return payload["observed_value"]
    result = payload.get("result") or {}
    if result.get("kind") == "memory":
        return result["address"]
    if result.get("kind") in {"scalar", "value"}:
        return result["value"]
    raise ValueError("dependency did not return an integer/address")


def execute(case, directory, options):
    """Evaluate prerequisites, the root expression and guarded attributes in order."""
    context = dict(case.context or {})
    results = {}
    evidence = []

    def run_node(node):
        nonlocal context
        guard = node.get("when")
        if guard is not None:
            ref = guard["dependency"]
            if ref not in results or results[ref].get("status") != "completed":
                raise ObservationGap(
                    "attribute guard has no completed K result: " + ref
                )
            number = value(results[ref])
            if (number != 0) != guard["nonzero"]:
                evidence.append(
                    {
                        "id": node["id"],
                        "role": node.get("role"),
                        "bytes": node["bytes"],
                        "status": "skipped",
                        "guard": guard,
                        "guard_value": str(number),
                        "reason": "K-computed attribute guard excludes this dependency",
                    }
                )
                return True
        interface = dict(context)
        for name, ref in node.get("bind", {}).items():
            if ref not in results:
                raise ValueError("missing or cyclic attribute dependency: " + ref)
            interface[name] = value(results[ref])
        dependency_case = replace(
            case,
            id=case.id + "--" + node["id"],
            bytes=node["bytes"],
            purpose=node["purpose"],
            context=interface,
            dependencies=[],
            predicates=[],
        )
        dependency_directory = directory / "dependencies" / node["id"]
        prepare(dependency_case, dependency_directory)
        observation = k.run(dependency_case, dependency_directory, options)
        payload = observation.outcome
        results[node["id"]] = payload
        evidence.append(
            {
                "id": node["id"],
                "role": node.get("role"),
                "purpose": dependency_case.purpose,
                "bytes": dependency_case.bytes,
                "bind": node.get("bind", {}),
                "status": payload.get("status"),
                "result": payload.get("result"),
                "directory": str(dependency_directory),
            }
        )
        if observation.state != "success":
            return False
        if (
            node.get("role") == "framebase"
            and (payload.get("result") or {}).get("kind") == "register"
        ):
            number = str(payload["result"]["register"])
            if number not in context.get("registers", {}):
                raise ObservationGap("frame base register was not captured")
            payload["observed_value"] = context["registers"][number]
            evidence[-1]["register_read"] = {
                "register": number,
                "value": str(payload["observed_value"]),
            }
        if node.get("read_result"):
            layout = node["read_result"]
            result = payload["result"]
            width = layout.get("bit_width", layout["byte_size"] * 8)
            if result["kind"] == "register":
                number = str(result["register"])
                if number not in context.get("registers", {}):
                    raise ObservationGap("referenced bound register was not captured")
                integer = context["registers"][number] % (1 << width)
                evidence[-1]["register_read"] = {
                    "register": number,
                    "value": str(integer),
                    "layout": layout,
                }
            else:
                address = value(payload)
                data = [
                    context.get("memory", {}).get(str(address + index))
                    for index in range(layout["byte_size"])
                ]
                evidence[-1]["object_reads"] = {
                    "address": str(address),
                    "bytes": data,
                    "layout": layout,
                }
                if any(byte is None for byte in data):
                    raise ObservationGap("referenced bound memory was not captured")
                integer = int.from_bytes(
                    bytes(data), layout.get("endianness", case.endianness)
                ) % (1 << width)
            if layout.get("signed") and integer >= (1 << (width - 1)):
                integer -= 1 << width
            payload["observed_value"] = integer + node.get("add", 0)
        elif node.get("add"):
            payload["observed_value"] = value(payload) + node["add"]
        if node.get("assign"):
            context[node["assign"]] = value(payload)
        return True

    directory.joinpath("dependencies").mkdir(exist_ok=True)

    def checked_node(node):
        try:
            return run_node(node), None
        except ObservationGap as error:
            return False, {
                "kind": "observation_gap",
                "diagnostic": str(error),
                "dependency": node["id"],
            }

    for node in case.dependencies:
        if node.get("phase") != "before":
            continue
        success, gap = checked_node(node)
        if not success:
            write_json(directory / "dependency-evidence.json", evidence)
            return (
                None,
                context,
                results,
                evidence,
                gap or "prerequisite attribute expression did not complete",
            )
    actual = replace(case, context=context)
    write_json(
        directory / "interface.json",
        {
            "address_width": case.address_width,
            "endianness": case.endianness,
            **({"architecture": case.architecture} if case.architecture else {}),
            **context,
        },
    )
    root_outcome = k.run(actual, directory, options)
    results["root"] = root_outcome.outcome
    reason = None
    if root_outcome.state == "success":
        try:
            root_observation(case, root_outcome.outcome, context, evidence)
            if case.observation_inputs.get("resolve_implicit"):
                implicit_observation(
                    case, root_outcome.outcome, context, directory, options, evidence
                )
        except ObservationGap as error:
            reason = {
                "kind": "observation_gap",
                "diagnostic": str(error),
                "dependency": "root",
            }
        for node in case.dependencies:
            if reason:
                break
            if node.get("phase") == "before":
                continue
            success, gap = checked_node(node)
            if not success:
                reason = gap or "attribute expression did not complete: " + node["id"]
                break
    write_json(directory / "dependency-evidence.json", evidence)
    return root_outcome, context, results, evidence, reason


def observation(case, payload, results, reason):
    # Keep the original K outcome intact. This is an explicitly derived test observation.
    observed = dict(payload)
    observed["dependency_results"] = {
        key: {
            "status": dependency_outcome.get("status"),
            "result": dependency_outcome.get("result"),
        }
        for key, dependency_outcome in results.items()
    }
    if reason:
        if isinstance(reason, dict):
            observed["observation_gap"] = reason
            return observed
        observed["status"] = "incomplete"
        observed["dependency_diagnostic"] = reason
        return observed
    if "data_location" in results:
        observed["object_location"] = results["data_location"]["result"]
    properties = {}
    if "allocated" in results:
        properties["allocated"] = value(results["allocated"]) != 0
    projection = case.observation_inputs.get("member_address_observation")
    if projection:
        root = payload.get("result") or {}
        if root.get("kind") != "memory":
            observed["observation_gap"] = {
                "kind": "observation_gap",
                "diagnostic": "member address requires a completed memory location",
            }
            return observed
        observed["observed_result"] = {
            "kind": "memory",
            "address": root["address"] + projection["byte_offset"],
        }
        observed["member_address_evidence"] = {
            "root_result": root,
            "member": projection,
            "result": observed["observed_result"],
            "memory_reads": [],
        }
    missing_bounds = case.observation_inputs.get("missing_bound_observation")
    if missing_bounds:
        properties["bounds_available"] = False
        observed["bound_availability_evidence"] = missing_bounds
    if case.observation_inputs.get("count_root"):
        properties["count"] = value(results["root"])
    if case.observation_inputs.get("constant_object_bytes") is not None:
        observed["object_location"] = {
            "kind": "bytes",
            "bytes": case.observation_inputs["constant_object_bytes"],
        }
    for name in ("lower_bound", "upper_bound", "count"):
        if name in results:
            properties[name] = value(results[name])
        elif name in case.observation_inputs.get("constant_properties", {}):
            properties[name] = case.observation_inputs["constant_properties"][name]
    if "lower_bound" in properties and "upper_bound" in properties:
        properties["count"] = max(
            0, properties["upper_bound"] - properties["lower_bound"] + 1
        )
    dimensions = {
        **{
            name: result
            for name, result in case.observation_inputs.get(
                "constant_properties", {}
            ).items()
            if name.startswith("dimension_")
        },
        **{
            name: value(result)
            for name, result in results.items()
            if name.startswith("dimension_")
        },
    }
    if dimensions:
        properties["shape"] = [dimensions[name] for name in sorted(dimensions)]
        if len(dimensions) == 1:
            properties["count"] = properties["shape"][0]
    observed["properties"] = properties
    if "array_index" in case.observation_inputs:
        index = case.observation_inputs["array_index"]
        lower_bound = properties.get("lower_bound", 0)
        if index < lower_bound or (
            "upper_bound" in properties and index > properties["upper_bound"]
        ):
            observed["status"] = "incomplete"
            observed["dependency_diagnostic"] = (
                "array index outside the K-computed bounds"
            )
        observed["object_bit_offset"] = (
            (index - lower_bound) * case.observation_inputs["element_size"] * 8
        )
    return observed
