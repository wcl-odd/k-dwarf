"""Read self-contained expression cases; never open a source file or saved result."""

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class ExpressionCase:
    id: str
    tool: str
    group: str
    expression: dict
    interface: dict
    requirements: dict

    @property
    def bytes(self):
        return list(bytes.fromhex(self.expression["bytecode"]))

    @property
    def purpose(self):
        return self.expression.get("purpose", "location")

    @property
    def dependencies(self):
        return self.expression.get("dependencies", [])

    @property
    def address_width(self):
        return self.interface["address_width"]

    @property
    def endianness(self):
        return self.interface["endianness"]

    @property
    def architecture(self):
        return self.interface.get("architecture")

    @property
    def context(self):
        return self.interface.get("state")

    @property
    def observation_inputs(self):
        return self.requirements.get("observation_inputs", {})

    @property
    def object_byte_size(self):
        return self.requirements.get("layout", {}).get("byte_size", 1)

    @property
    def object_bit_size(self):
        return self.requirements.get("layout", {}).get("bit_size")

    @property
    def predicates(self):
        return [
            dict(predicate, id=self.id + ":" + str(index))
            for index, predicate in enumerate(self.requirements["predicates"])
        ]


def replace_case(case, **changes):
    """Copy a case with runtime overrides without modifying the original case."""
    expression = dict(case.expression)
    interface = dict(case.interface)
    requirements = dict(case.requirements)
    for name, value in changes.items():
        if name == "bytes":
            expression["bytecode"] = bytes(value).hex(" ")
        elif name in {"purpose", "dependencies"}:
            expression[name] = value
        elif name == "context":
            interface["state"] = value
        elif name in {"address_width", "endianness", "architecture"}:
            interface[name] = value
        elif name == "predicates":
            requirements["predicates"] = value
        elif name == "observation_inputs":
            requirements["observation_inputs"] = value
        elif name in {"object_byte_size", "object_bit_size"}:
            requirements.setdefault(
                "layout", dict(case.requirements.get("layout", {}))
            )["byte_size" if name == "object_byte_size" else "bit_size"] = value
        elif name != "id":
            raise ValueError("unknown expression-case replacement: " + name)
    return replace(
        case,
        id=changes.get("id", case.id),
        expression=expression,
        interface=interface,
        requirements=requirements,
    )


def load_cases(file):
    """Load and validate self-contained cases without following source anchors."""
    import runner
    from requirements import validate_requirements

    document = json.loads(
        Path(file).read_text(), object_pairs_hook=runner.unique_object
    )
    if set(document) != {"cases"} or not isinstance(document["cases"], list):
        raise ValueError("invalid expression-case file")
    cases = []
    ids = set()
    for row in document["cases"]:
        if set(row) - {
            "id",
            "tool",
            "group",
            "source",
            "expression",
            "interface",
            "requirements",
        }:
            raise ValueError("unknown case field")
        case = ExpressionCase(**{k: v for k, v in row.items() if k != "source"})
        if not re.fullmatch(r"(lldb|gdb)-[0-9]{3}", case.id) or case.id in ids:
            raise ValueError("duplicate or unsafe case ID")
        if case.tool not in {"lldb", "gdb"} or case.group not in {"core", "auxiliary"}:
            raise ValueError("invalid case group")
        ids.add(case.id)
        if not isinstance(case.expression["bytecode"], str) or not re.fullmatch(
            r"(?:[0-9a-fA-F]{2}(?: [0-9a-fA-F]{2})*)?", case.expression["bytecode"]
        ):
            raise ValueError("invalid hexadecimal bytecode")
        if case.purpose not in {"location", "value"}:
            raise ValueError("invalid evaluation purpose")
        runner.validate_interface(
            {
                "address_width": case.address_width,
                "endianness": case.endianness,
                **({"architecture": case.architecture} if case.architecture else {}),
                **(case.context or {}),
            }
        )
        validate_requirements(case.predicates)
        seen = set()
        has_result_dependencies = False
        for node in case.dependencies:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", node["id"]) or node["id"] in seen:
                raise ValueError("invalid dependency ID")
            before = node.get("phase") == "before"
            if before and has_result_dependencies:
                raise ValueError("prerequisite follows result dependency")
            has_result_dependencies |= not before
            allowed = seen | ({"root"} if not before else set())
            if any(ref not in allowed for ref in node.get("bind", {}).values()):
                raise ValueError("missing or cyclic dependency")
            if node.get("when", {}).get("dependency") not in seen and node.get("when"):
                raise ValueError("invalid dependency guard")
            if not isinstance(node["bytes"], list) or any(
                type(byte) is not int or not 0 <= byte <= 255 for byte in node["bytes"]
            ):
                raise ValueError("invalid dependency bytecode")
            seen.add(node["id"])
        location = case.requirements.get("location")
        if location is not None and (
            location["role"]
            not in {"root", "base_subobject", "resolved_object", "element"}
            or location["expected"].get("kind") not in {"memory", "register"}
        ):
            raise ValueError("invalid independent location requirement")
        cases.append(case)
    if not cases:
        raise ValueError("empty expression-case file")
    return cases


def load_corpus(directory, source="all"):
    """Read only the requested source files and retain core/auxiliary groups."""
    if source not in {"all", "lldb", "gdb"}:
        raise ValueError("invalid case source")
    cases = []
    for tool in ("lldb", "gdb") if source == "all" else (source,):
        file = Path(directory) / (tool + ".json")
        selected = load_cases(file)
        if any(
            case.tool != tool or not case.id.startswith(tool + "-") for case in selected
        ):
            raise ValueError("case source differs from file: " + file.name)
        cases.extend(selected)
    return cases


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    )


def prepare(case, directory):
    """Write the bytecode and fixed interface for one K invocation."""
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "expression.hex").write_text(case.expression["bytecode"] + "\n")
    write_json(
        directory / "interface.json",
        {
            "address_width": case.address_width,
            "endianness": case.endianness,
            **({"architecture": case.architecture} if case.architecture else {}),
            **(case.context or {}),
        },
    )
