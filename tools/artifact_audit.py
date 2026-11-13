"""Release policy: minimal files, local Python dependencies and English prose.

Reviewed upstream sources are inert evidence, not additional Python modules.
Mathematical notation and original K string literals are not natural-language
comments. Other documents, CSV labels and original manual remarks are outside
this language check.
"""

import ast
from importlib.util import resolve_name
from pathlib import PurePosixPath
import re
import sys

ROOT_FILES = {"README.md", "Makefile", "validate.py", ".gitignore"}
RESULT_FILES = {"report.md", "expressions.csv", "differences.csv", "evidence.jsonl.gz"}
NON_ENGLISH_SCRIPT = re.compile(
    r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\U00020000-\U0003134f]"
)


def k_comments(text):
    """Extract K comments while ignoring double-quoted/escaped literals."""
    fragments = []
    i = 0
    while i < len(text):
        if text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
            fragments.append(text[i:end])
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated K block comment")
            fragments.append(text[i : end + 2])
            i = end + 2
        else:
            i += 1
    return "\n".join(fragments)


def english_prose(name, data):
    """Reject non-English scripts; actual prose is also reviewed in English."""
    path = PurePosixPath(name)
    if path.name.upper().startswith("README") or path.name == "report.md":
        text = data.decode("utf-8")
    elif path.parts[0] == "semantics" and path.suffix == ".k":
        text = k_comments(data.decode("utf-8"))
    else:
        return
    if NON_ENGLISH_SCRIPT.search(text):
        raise ValueError("non-English README or K comment: " + name)


def python_closure(items):
    """Resolve all static imports, including imports inside functions.

    runner is a subprocess entrypoint, so its imports must also be a root.
    No collection tools, parent package or third-party Python module may enter
    the runtime closure. Every shipped runtime module must be reachable.
    """
    modules = {}
    paths = {}
    for name, item in items.items():
        path = PurePosixPath(name)
        if name == "validate.py":
            module = "validate"
        elif path.parts[0] == "scripts" and path.suffix == ".py":
            bits = list(path.with_suffix("").parts[1:])
            if bits[-1] == "__init__":
                bits.pop()
            module = ".".join(bits)
        else:
            continue
        try:
            modules[module] = ast.parse(item["data"].decode("utf-8"), filename=name)
        except SyntaxError as error:
            raise ValueError("invalid runtime Python: " + name) from error
        paths[module] = name
    edges = {m: set() for m in modules}
    for module, tree in modules.items():
        package = (
            module
            if paths[module].endswith("/__init__.py")
            else module.rpartition(".")[0]
        )

        def dependency(target):
            if target in modules:
                edges[module].add(target)
                parts = target.split(".")
                edges[module].update(
                    ".".join(parts[:i])
                    for i in range(1, len(parts))
                    if ".".join(parts[:i]) in modules
                )
            elif target.split(".")[0] not in sys.stdlib_module_names:
                raise ValueError(
                    "Python dependency outside artifact: "
                    + paths[module]
                    + " -> "
                    + target
                )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependency(alias.name)
            elif isinstance(node, ast.ImportFrom):
                try:
                    target = (
                        resolve_name("." * node.level + (node.module or ""), package)
                        if node.level
                        else node.module
                    )
                except ImportError as error:
                    raise ValueError(
                        "relative import outside artifact: " + paths[module]
                    ) from error
                dependency(target)
                for alias in node.names:
                    child = target + "." + alias.name
                    if child in modules:
                        dependency(child)
    reachable = set()
    pending = ["validate", "runner"]
    while pending:
        module = pending.pop()
        if module not in modules:
            raise ValueError("internal entrypoint missing: " + module)
        if module not in reachable:
            reachable.add(module)
            pending.extend(edges[module] - reachable)
    if reachable != modules.keys():
        raise ValueError(
            "unreferenced runtime module: "
            + ", ".join(paths[m] for m in sorted(modules.keys() - reachable))
        )
    return {paths[m]: sorted(paths[n] for n in edges[m]) for m in sorted(modules)}


def audit(items):
    names = set(items)
    if {n for n in names if "/" not in n} != ROOT_FILES:
        raise ValueError("minimal artifact root file set differs")
    if {
        PurePosixPath(n).name for n in names if n.startswith("results/")
    } != RESULT_FILES:
        raise ValueError("minimal artifact result file set differs")
    for name, item in items.items():
        p = PurePosixPath(name)
        allowed = (
            name in ROOT_FILES
            or p.parts[0] == "test-corpus"
            or (p.parts[0] == "semantics" and p.suffix == ".k")
            or name == "scripts/README.md"
            or (p.parts[0] == "scripts" and p.suffix == ".py")
            or (
                len(p.parts) == 2 and p.parts[0] == "results" and p.name in RESULT_FILES
            )
        )
        if not allowed:
            raise ValueError("file outside minimal artifact profile: " + name)
        english_prose(name, item["data"])
    graph = python_closure(items)
    return {
        "readme_files": sum(
            PurePosixPath(n).name.upper().startswith("README") for n in names
        ),
        "k_files": sum(n.startswith("semantics/") and n.endswith(".k") for n in names),
        "runtime_modules": len(graph),
        "python_dependencies": graph,
    }
