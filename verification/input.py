"""Transport serialization only: never decode an opcode or its operands."""
import json
from pathlib import Path


def write_json(path, value):
    # Reports can nest a complete K configuration inside backend observations.
    # Indenting a linear builtin Map tree would produce quadratic output size.
    pending=[value];deep=False
    while pending:
        item=pending.pop()
        if isinstance(item,dict):
            if 'configuration' in item:deep=True;break
            pending.extend(item.values())
        elif isinstance(item,list):pending.extend(item)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=None if deep else 2) + "\n")


def prepare(case, directory):
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "case.json", case.document())
    (directory / "expression.hex").write_text(" ".join(f"{b:02x}" for b in case.bytes) + "\n")
    write_json(directory / "context.json", {"address_width": case.address_width,
          "endianness": case.endianness, **({"architecture": case.architecture} if case.architecture else {}),
          **(case.context or {})})
