#!/usr/bin/env python3
"""Copy the maintained project into a standalone paper project with development-only sync bookkeeping."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MANIFEST = "artifact-manifest.json"
COPY = (
    "semantics",
    "test-corpus",
    "tools/artifact-runtime",
    "output",
    "docs",
    "tools/artifact-template",
)
RUNTIME = (
    "cases.py",
    "requirements.py",
    "dependencies.py",
    "k.py",
    "runner.py",
    "processes.py",
    "experiment.py",
)
TEMPLATES = ("README.md", "Makefile", "validate.py", ".gitignore")
SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()


def safe(root, name):
    q = PurePosixPath(name)
    if (
        not name
        or q.is_absolute()
        or q.as_posix() != name
        or ".." in q.parts
        or "\\" in name
    ):
        raise ValueError("unsafe publication path: " + str(name))
    p = root / q
    for parent in (p, *p.parents):
        if parent.is_symlink():
            raise ValueError("symlink in publication path: " + str(parent))
        if parent == root:
            break
    return p


def payloads(root):
    result = {}

    def add(path, target=None, data=None, method="copy", inputs=None):
        if path.is_symlink() or not path.is_file():
            raise ValueError("source must be a regular file: " + str(path))
        name = target or path.relative_to(root).as_posix()
        original = path.read_bytes()
        result[name] = {
            "data": original if data is None else data,
            "source": path.relative_to(root).as_posix(),
            "source_sha256": sha(original),
            "method": method,
            "mode": 0o755 if path.stat().st_mode & 0o111 else 0o644,
            "inputs": inputs or {},
        }

    base = safe(root, "semantics")
    if not base.is_dir():
        raise ValueError("required publication source missing: semantics")
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise ValueError("source symlink: " + str(path))
        if path.is_file() and path.suffix == ".k":
            add(path)
    from tools.compact_cases import export as export_cases

    corpus, mapping, corpus_inputs = export_cases(root)
    guide = (
        "# Expression cases\n\n"
        "lldb.json and gdb.json contain the complete, self-contained inputs for their respective sources. Each expression case consists of expression bytecode, a fixed external input interface, and a requirement on the K outcome. "
        "Source file names, test names, and original assertion quotations are documentation only; the runner never opens them.\n\n"
        "The group field separates core expression cases from auxiliary checks; it is used only for reporting and is not supplied to K. Dependencies belong to their root case and do not enlarge the denominator. "
        "Requirements come from upstream tests or independently observed native addresses or registers; expected results are never inferred from K. "
        "An absent interface entry remains unknown; an empty bytecode string is a genuine empty expression.\n\n"
        "See the project README for selection, installation, parallel execution, and result files. "
        "Detailed selection and input-collection records are maintained separately from this project.\n"
    ).encode()
    origin = safe(root, "test-corpus/manifest.json")
    for tool in ("lldb", "gdb"):
        selected = {"cases": [case for case in corpus["cases"] if case["tool"] == tool]}
        add(
            origin,
            "test-corpus/" + tool + ".json",
            encoded(selected),
            "self-contained expression/interface/requirements",
            corpus_inputs,
        )
    add(origin, "test-corpus/README.md", guide, "corpus guide")
    for name in RUNTIME:
        add(safe(root, "tools/artifact-runtime/" + name), "scripts/" + name)
    add(safe(root, "tools/artifact-runtime/README.md"), "scripts/README.md")
    for name in TEMPLATES:
        add(safe(root, "tools/artifact-template/" + name), name, method="template")
    from tools.artifact_audit import RESULT_FILES

    final = safe(root, "docs/reference/artifact-results")
    if not final.is_dir():
        raise ValueError("recorded result package missing: " + str(final))
    files = list(final.iterdir())
    if {p.name for p in files} != RESULT_FILES or any(
        not p.is_file() or p.is_symlink() for p in files
    ):
        raise ValueError("recorded result package file set differs")
    compact = {p.name: p.read_bytes() for p in files}
    inputs = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in files}
    for name, data in compact.items():
        add(
            safe(root, "output/manifest.json"),
            "results/" + name,
            data,
            "compact primary experiment; no semantic changes",
            inputs,
        )
    return result


def sync_path(root, dest):
    """Sync state is local maintenance data, never part of the standalone tree."""
    return safe(
        root, "build/artifact-sync/" + sha(str(dest.absolute()).encode()) + ".json"
    )


def read_state(file):
    if not file.exists():
        return None
    if not file.is_file():
        raise ValueError("sync state must be a regular file")
    doc = json.loads(file.read_text())
    identity = doc.get("identity")
    if (doc.get("schema"), doc.get("profile")) not in {
        (1, "standalone-publication-v1"),
        (2, "paper-minimal-v1"),
    } or sha(encoded({k: v for k, v in doc.items() if k != "identity"})) != identity:
        raise ValueError("sync state changed")
    names = [row["path"] for row in doc["files"]]
    if len(names) != len(set(names)) or MANIFEST in names:
        raise ValueError("duplicate/reserved sync entry")
    return doc


def verify_dest(dest, doc):
    for row in doc["files"]:
        p = safe(dest, row["path"])
        if (
            not p.is_file()
            or sha(p.read_bytes()) != row["sha256"]
            or p.stat().st_size != row["bytes"]
            or (p.stat().st_mode & 0o777) != row["mode"]
        ):
            raise ValueError("artifact has local edits or missing file: " + row["path"])


def manifest_for(items):
    doc = {
        "schema": 2,
        "profile": "paper-minimal-v1",
        "generator": {
            "path": "tools/package_artifact.py",
            "sha256": sha(Path(__file__).read_bytes()),
        },
        "policy": {
            "path": "tools/artifact_audit.py",
            "sha256": sha(Path(__file__).with_name("artifact_audit.py").read_bytes()),
        },
        "maintenance": "Development tree is canonical; copied files are not independent edits.",
        "generation_inputs": {
            n: h for item in items.values() for n, h in item.get("inputs", {}).items()
        },
        "files": [
            {
                "path": name,
                "sha256": sha(item["data"]),
                "bytes": len(item["data"]),
                **{k: item[k] for k in ("source", "source_sha256", "method", "mode")},
            }
            for name, item in sorted(items.items())
        ],
    }
    doc["identity"] = sha(encoded(doc))
    return doc


def rules_check(root, dest, if_present=False):
    if not dest.exists() and if_present:
        return
    for base in (root / "semantics", dest / "semantics"):
        safe(base.parent, base.name)
        for p in base.rglob("*"):
            if p.is_symlink():
                raise ValueError("symlink in rule source: " + str(p))
    a = {
        p.relative_to(root / "semantics").as_posix(): sha(p.read_bytes())
        for p in (root / "semantics").rglob("*.k")
    }
    b = {
        p.relative_to(dest / "semantics").as_posix(): sha(p.read_bytes())
        for p in (dest / "semantics").rglob("*.k")
    }
    if not a or a != b:
        raise ValueError(
            "K sources differ; run make artifact to copy the maintained rules"
        )


def unmanaged_files(dest, previous):
    """Only known Python bytecode caches are regenerable migration debris."""
    caches = []
    if not dest.exists():
        return caches
    for path in dest.rglob("*"):
        name = path.relative_to(dest).as_posix()
        if Path(name).parts[0] in {"build", ".git"}:
            continue
        if path.is_symlink():
            raise ValueError("unmanaged symlink: " + name)
        if path.is_dir() or name in previous or name == MANIFEST:
            continue
        if path.parent.name == "__pycache__" and path.suffix == ".pyc":
            source = path.parent.parent / (path.name.split(".")[0] + ".py")
            if source.relative_to(dest).as_posix() in previous:
                caches.append(
                    {
                        "path": name,
                        "sha256": sha(path.read_bytes()),
                        "bytes": path.stat().st_size,
                        "reason": "regenerable bytecode for a formerly managed source",
                    }
                )
                continue
        raise ValueError(
            "unmanaged file; publication stopped without deleting it: " + name
        )
    return caches


def publish(root, dest, check=False):
    root, dest = root.absolute(), Path(os.path.abspath(dest))
    safe(dest.parent, dest.name)
    if dest == root or root.is_relative_to(dest):
        raise ValueError("artifact destination cannot contain the source tree")
    items = payloads(root)
    if not any(n.startswith("semantics/") and n.endswith(".k") for n in items):
        raise ValueError("no K sources to publish")
    if any(
        (root / name).is_relative_to(dest) or dest.is_relative_to(root / name)
        for name in COPY
    ):
        raise ValueError("artifact destination overlaps a publication source")
    from tools.artifact_audit import audit

    audit(items)
    state = sync_path(root, dest)
    doc = read_state(state)
    state_before = state.read_bytes() if doc else None
    legacy = safe(dest, MANIFEST)
    legacy_before = legacy.read_bytes() if legacy.is_file() else None
    if doc is None and legacy_before is not None:
        doc = read_state(legacy)
    previous = {r["path"]: r for r in doc["files"]} if doc else {}
    if doc:
        verify_dest(dest, doc)
    elif dest.exists() and any(dest.iterdir()):
        # State may be removed locally; adopt only an exact, unmodified copy.
        candidate = manifest_for(items)
        try:
            verify_dest(dest, candidate)
            unmanaged_files(dest, {r["path"]: r for r in candidate["files"]})
        except (ValueError, OSError) as error:
            raise ValueError(
                "existing directory has no local sync state and is not an exact copy"
            ) from error
        doc = candidate
        previous = {r["path"]: r for r in doc["files"]}
    caches = unmanaged_files(dest, previous)
    new_doc = manifest_for(items)
    if check:
        if not doc or doc != new_doc or legacy_before is not None:
            raise ValueError("artifact is out of date; run make artifact")
        rules_check(root, dest)
        return new_doc
    for name in items.keys() - previous.keys():
        if os.path.lexists(safe(dest, name)):
            raise ValueError("unmanaged destination collision: " + name)
    scratch = Path("/tmp/scratch")
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="kframework-publication-", dir=scratch
    ) as folder:
        stage = Path(folder)
        for name, item in items.items():
            file = stage / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(item["data"])
            file.chmod(item["mode"])
        # Abort before publishing if any source or destination changed while staging.
        sources = {item["source"]: item["source_sha256"] for item in items.values()}
        sources.update(
            {n: h for item in items.values() for n, h in item.get("inputs", {}).items()}
        )
        for name, identity in sources.items():
            if sha(safe(root, name).read_bytes()) != identity:
                raise ValueError("publication source drift: " + name)
        if doc:
            verify_dest(dest, doc)
        if (state.read_bytes() if state.exists() else None) != state_before:
            raise ValueError("local sync state drift")
        if (legacy.read_bytes() if legacy.exists() else None) != legacy_before:
            raise ValueError("legacy manifest drift")
        dest.mkdir(parents=True, exist_ok=True)
        for name, item in items.items():
            file = safe(dest, name)
            if name in previous and sha(file.read_bytes()) != previous[name]["sha256"]:
                raise ValueError("destination drift: " + name)
            if name not in previous and os.path.lexists(file):
                raise ValueError("unmanaged destination collision: " + name)
            if (
                name in previous
                and previous[name]["sha256"] == sha(item["data"])
                and previous[name]["mode"] == item["mode"]
            ):
                continue
            file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stage / name, file)
            file.chmod(item["mode"])
        retired = []
        for name in previous.keys() - items.keys():
            file = safe(dest, name)
            if sha(file.read_bytes()) != previous[name]["sha256"]:
                raise ValueError("retired destination drift: " + name)
            retired.append(
                {
                    "path": name,
                    "sha256": previous[name]["sha256"],
                    "bytes": file.stat().st_size,
                    "reason": "not in minimal paper publication",
                }
            )
            file.unlink()
        for row in caches:
            file = safe(dest, row["path"])
            if sha(file.read_bytes()) != row["sha256"]:
                raise ValueError("cache drift: " + row["path"])
            file.unlink()
        parents = {
            parent
            for row in retired + caches
            for parent in (dest / row["path"]).parents
            if parent.is_relative_to(dest) and parent != dest
        }
        for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        if retired or caches:
            receipt = {
                "from": doc["identity"],
                "to": new_doc["identity"],
                "files": sorted(retired + caches, key=lambda r: r["path"]),
                "deleted_bytes": sum(r["bytes"] for r in retired + caches),
            }
            audit = root / "build/artifact-cleanup"
            audit.mkdir(parents=True, exist_ok=True)
            file = audit / (sha(encoded(receipt)) + ".json")
            if file.exists() and file.read_bytes() != encoded(receipt):
                raise ValueError("cleanup receipt drift")
            file.write_bytes(encoded(receipt))
        if legacy_before is not None:
            if legacy.read_bytes() != legacy_before:
                raise ValueError("legacy manifest drift")
            legacy.unlink()
        if (state.read_bytes() if state.exists() else None) != state_before:
            raise ValueError("local sync state drift")
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_bytes(encoded(new_doc))
    verify_dest(dest, new_doc)
    rules_check(root, dest)
    return new_doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifact")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--if-present", action="store_true")
    args = parser.parse_args(argv)
    try:
        Path("/tmp/locks").mkdir(exist_ok=True)
        with open("/tmp/locks/kframework.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.rules_only:
                rules_check(ROOT, args.output.absolute(), args.if_present)
                return 0
            doc = publish(ROOT, args.output, args.check)
        print(
            ("Verified" if args.check else "Copied")
            + f" {len(doc['files'])} files; local sync {doc['identity']}"
        )
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("artifact: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
