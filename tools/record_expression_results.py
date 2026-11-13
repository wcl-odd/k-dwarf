"""Package completed expression-case outputs without invoking K.

This development tool recomputes results from case records, not Markdown or a
saved summary. Run settings must be supplied explicitly; invocation receipts
check timeout and rewrite budgets where they were recorded.
"""

import argparse
from collections import Counter
import csv
import gzip
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.compact_cases import export as export_cases
from tools.compact_results import export as export_original_results
from verification.paper_coverage import instructions, numbered_op_family
import run as dwarf

LOCATIONS = {
    "memory",
    "register",
    "value",
    "bytes",
    "composite",
    "implicit_pointer",
    "unavailable",
}
VERDICTS = ("consistent", "inconsistent", "uncheckable", "undetermined")
RESULT_FILES = {"report.md", "expressions.csv", "differences.csv", "evidence.jsonl.gz"}


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def csv_data(columns, rows):
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode()


def positive(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def summarize_records(records, cases, settings, *, interrupted=False, diagnostic=""):
    """Recompute all verdict counts and keep core and auxiliary scopes separate."""
    if set(settings) != {"jobs", "timeout", "depth"}:
        raise ValueError("jobs, timeout and depth are required")
    if (
        any(type(value) is not int or value <= 0 for value in settings.values())
        or settings["jobs"] > 16
    ):
        raise ValueError("invalid run settings")
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)) or set(ids) != set(cases):
        raise ValueError("incomplete or duplicate expression-case experiment")
    for record in records:
        case = cases[record["id"]]
        if record["tool"] != case["tool"] or record["group"] != case["group"]:
            raise ValueError("case source or group differs: " + record["id"])
        if record["verdict"] not in VERDICTS:
            raise ValueError("unknown case verdict: " + record["id"])

    def counts(selected):
        verdicts = Counter(record["verdict"] for record in selected)
        return {
            "cases": len(selected),
            **{name: verdicts[name] for name in VERDICTS},
            "consistency_rate": (
                verdicts["consistent"] / len(selected) if selected else None
            ),
        }

    sources = {}
    for tool in sorted({case["tool"] for case in cases.values()}):
        sources[tool] = {
            group: counts(
                [
                    record
                    for record in records
                    if record["tool"] == tool and record["group"] == group
                ]
            )
            for group in ("core", "auxiliary")
        }
    faults = [
        {"id": record["id"], **fault}
        for record in records
        for fault in record["execution_faults"]
    ]
    if diagnostic:
        faults.append(
            {
                "id": "run",
                "call": "root",
                "kind": "tool_error",
                "diagnostic": diagnostic,
            }
        )
    return {
        "unit": "expression case",
        "sources": sources,
        "total": counts([record for record in records if record["group"] == "core"]),
        "tasks_completed": len(records),
        "tasks_expected": len(cases),
        "missing_cases": [],
        "settings": dict(settings),
        "execution_faults": faults,
        "interrupted": interrupted,
        "diagnostic": diagnostic,
        "exit_code": 130 if interrupted else int(bool(faults)),
    }


def check_invocation_settings(run, settings, case_ids):
    """Check captured per-invocation settings, including larger stability probes."""
    checked = {"commands": 0, "timeouts": 0, "budgets": 0}
    for file in sorted(Path(run).rglob("command.json")):
        if file.parent.name != "k":
            continue
        relative = file.relative_to(run)
        if relative.parts[0] not in case_ids:
            raise ValueError("invocation without a selected case: " + str(relative))
        receipt = json.loads(file.read_text())
        argv = receipt.get("argv")
        if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("invalid invocation command: " + str(relative))
        if "timeout" in receipt:
            if receipt["timeout"] != settings["timeout"]:
                raise ValueError(
                    "timeout differs from invocation receipt: " + str(relative)
                )
            checked["timeouts"] += 1
        if argv.count("--depth") != 1:
            raise ValueError("missing or ambiguous rewrite budget: " + str(relative))
        try:
            budget = int(argv[argv.index("--depth") + 1])
        except (IndexError, ValueError) as error:
            raise ValueError(
                "invalid invocation rewrite budget: " + str(relative)
            ) from error
        expected = settings["depth"]
        if relative.parts[1:] == ("stability-probe", "k", "command.json"):
            expected += max(10000, expected)
        if budget != expected:
            raise ValueError(
                "rewrite budget differs from invocation receipt: " + str(relative)
            )
        checked["commands"] += 1
        checked["budgets"] += 1
    return checked


def coverage_counts(items):
    names = {operation["op"] for item in items for operation in item["instructions"]}
    kinds = Counter(item["location"] for item in items)
    families = {numbered_op_family(name) for name in names}
    return {
        "cases": len(items),
        "op_names": sorted(names),
        "op_name_count": len(names),
        "op_families": sorted(families),
        "op_family_count": len(families),
        "location_counts": dict(sorted(kinds.items())),
        "location_categories": sorted(set(kinds) & LOCATIONS),
        "location_category_count": len(set(kinds) & LOCATIONS),
        "decode_gap_cases": sum(bool(item["decode_gaps"]) for item in items),
    }


def markdown_cell(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", "<br>")
    )


def render_report(summary):
    """Render the complete published summary without a companion JSON file."""

    def row(label, counts):
        rate = (
            f"{counts['consistent'] / counts['cases']:.2%}"
            if counts["cases"]
            else "n/a"
        )
        return (
            f"| {label} | {counts['cases']} | {counts['consistent']} | "
            f"{counts['inconsistent']} | {counts['uncheckable']} | "
            f"{counts['undetermined']} | {rate} |"
        )

    columns = "| Source | Cases | Consistent | Inconsistent | Uncheckable | Undetermined | Consistent / cases |"
    separator = "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [
        "# Recorded expression-case experiment",
        "",
        "One core expression case contributes one verdict; all its in-scope requirements must hold. "
        "This report packages an existing LLVM run, not a new experiment.",
        "",
        "## Core results",
        "",
        columns,
        separator,
    ]
    for tool, groups in summary["sources"].items():
        lines.append(row(tool.upper(), groups["core"]))
    lines.append(row("Total", summary["total"]))
    lines += [
        "",
        "## Auxiliary checks",
        "",
        "These checks are outside the core denominator. Their API/diagnostic requirements "
        "are not fully represented by the K interface.",
        "",
        columns,
        separator,
    ]
    for tool, groups in summary["sources"].items():
        if groups["auxiliary"]["cases"]:
            lines.append(row(tool.upper(), groups["auxiliary"]))
    settings = summary["settings"]
    verified = summary["settings_evidence"]
    lines += [
        "",
        "## Run settings and completion",
        "",
        f"- Completed tasks: {summary['tasks_completed']} / {summary['tasks_expected']}.",
        f"- K invocations: {summary['k_invocations']}, including attributes and stability probes.",
        f"- Timeout: {settings['timeout']} seconds per K invocation.",
        f"- Rewrite budget: {settings['depth']} per K invocation; stability probes use a larger budget.",
        f"- Concurrency: {settings['jobs']} cases.",
        f"- Interrupted: {'yes' if summary['interrupted'] else 'no'}.",
        f"- Execution faults: {len(summary['execution_faults'])}.",
        f"- Exit code: {summary['exit_code']}.",
        "",
        f"Settings were supplied explicitly at export; {verified['timeouts']} timeout receipts "
        f"and {verified['budgets']} rewrite budgets were checked across {verified['commands']} "
        "captured commands. Concurrency is not independently recorded by individual invocation receipts.",
        "",
        "## Unexecuted tasks",
        "",
    ]
    lines.extend(f"- `{name}`" for name in summary["missing_cases"])
    if not summary["missing_cases"]:
        lines.append("None.")
    lines += ["", "## Execution faults", ""]
    if summary.get("diagnostic"):
        lines += ["Run diagnostic: " + markdown_cell(summary["diagnostic"]), ""]
    if summary["execution_faults"]:
        lines += ["| Case | Call | Kind | Diagnostic |", "| --- | --- | --- | --- |"]
        for fault in summary["execution_faults"]:
            lines.append(
                "| "
                + " | ".join(
                    markdown_cell(fault.get(key, ""))
                    for key in ("id", "call", "kind", "diagnostic")
                )
                + " |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## Input and final-location coverage",
        "",
        "OP counts describe root input presence, including nested blocks, not actual OP execution. "
        "Attribute calls do not enlarge the root denominator. Separately called bodies and skipped "
        "branches limit execution claims. Full OP names and instructions remain in the compressed coverage records.",
        "",
        "| Source | Core inputs | OP names | Numbered families | Location categories | Decode-gap cases |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tool in (*summary["sources"], "combined"):
        counts = summary["coverage"][tool]
        lines.append(
            f"| {tool.upper()} | {counts['cases']} | {counts['op_name_count']} | "
            f"{counts['op_family_count']} | {counts['location_category_count']} | {counts['decode_gap_cases']} |"
        )
    lines += [
        "",
        "| Final root result | LLDB | GDB | Combined |",
        "| --- | ---: | ---: | ---: |",
    ]
    kinds = sorted(summary["coverage"]["combined"]["location_counts"])
    for kind in kinds:
        values = [
            summary["coverage"].get(tool, {}).get("location_counts", {}).get(kind, 0)
            for tool in ("lldb", "gdb", "combined")
        ]
        lines.append(f"| {kind} | {values[0]} | {values[1]} | {values[2]} |")
    lines += [
        "",
        "Scalar attribute values and outcomes without a public result are separate; "
        "neither is a location-description category. No floating arithmetic execution is confirmed "
        "in this upstream set. Metadata or raw register transport alone does not establish floating computation.",
        "",
        "## Files and interpretation",
        "",
        "| File | Contents |",
        "| --- | --- |",
        "| report.md | Result counts, settings, faults, coverage and interpretation |",
        "| expressions.csv | All core and auxiliary verdicts, with manual remarks |",
        "| differences.csv | Inconsistency and auxiliary analyses, with manual remarks |",
        "| evidence.jsonl.gz | Complete case checks, K outcomes, dependency/stability calls and coverage |",
        "",
        "The evidence is ordinary gzip JSON Lines with case, invocation and coverage records. "
        "Case ID and relative call path identify each record. Original requirements and source "
        "anchors are in ../test-corpus/lldb.json and ../test-corpus/gdb.json. Absolute strings in "
        "raw evidence are provenance, not runtime file dependencies.",
        "",
        "Memory/register results compare location identity. Direct values retain their required "
        "value/type predicates; composites are checked piece by piece with exact availability. "
        "Expected abnormal termination is distinct from timeout or exhausted budget. Normal "
        "completion does not by itself establish consistency.",
        "",
        "Fresh validation checks the frozen requirements and writes new files; it does not compare "
        "with these recorded verdicts. Source selection and semantic mapping involved human/AI review. "
        "Conclusions are limited to the selected cases and do not establish complete DWARF correctness.",
    ]
    return "\n".join(lines) + "\n"


def export(root, run, *, jobs, timeout, depth, interrupted=False, diagnostic=""):
    root, run = Path(root), Path(run)
    corpus, mapping, _ = export_cases(root)
    cases = {case["id"]: case for case in corpus["cases"]}
    try:
        records = [
            json.loads((run / name / "outcome.json").read_text()) for name in cases
        ]
    except FileNotFoundError as error:
        raise ValueError(
            "incomplete expression-case experiment: " + str(error.filename)
        ) from error
    summary = summarize_records(
        records,
        cases,
        {"jobs": jobs, "timeout": timeout, "depth": depth},
        interrupted=interrupted,
        diagnostic=diagnostic,
    )
    summary["settings_evidence"] = check_invocation_settings(
        run, summary["settings"], set(cases)
    )
    # Reviewed annotations are inherited, never used to compute expected answers.
    original, _ = export_original_results(root)
    translations = {
        "\u6269\u5c55\u89c4\u5219\uff0c\u4fdd\u7559": "Debugger rule extension; retain this case.",
        "\u662f\u9884\u671f\u5931\u8d25\uff0c\u4e0d\u505a\u5904\u7406": "Expected failure; no change.",
        "\u9002\u914d\u6d41\u7a0b\u5bfc\u81f4\uff0c\u4e0d\u505a\u5904\u7406": "Caused by interface extraction; no change.",
    }
    notes = {}
    for name, text in json.loads(original["notes.json"]).items():
        if not text:
            continue
        english = translations.get(text, text)
        if any("\u3400" <= char <= "\u9fff" for char in english):
            raise ValueError("untranslated manual remark: " + name)
        notes[mapping.get(name, name)] = english
    analyses = {
        mapping[row["id"]]: row["analysis"]
        for row in csv.DictReader(io.StringIO(original["differences.csv"].decode()))
        if row["id"] in mapping
    }
    rows, differences, evidence, coverage = [], [], [], []
    calls = 0
    for record in records:
        name = record["id"]
        case, base = cases[name], run / name
        row = {
            key: record[key]
            for key in (
                "id",
                "tool",
                "group",
                "execution",
                "verdict",
                "fully_checked",
                "diagnostic",
            )
        }
        row["manual_remarks"] = notes.get(name, "")
        rows.append(row)
        if record["group"] == "auxiliary" or record["verdict"] != "consistent":
            differences.append(
                {
                    **row,
                    "analysis": analyses.get(name, record["diagnostic"]),
                    "evidence_key": "case:" + name,
                }
            )
        evidence.append({"kind": "case", "record": record})
        for file in sorted(base.rglob("stdout.txt")):
            if file.parent.name != "k":
                continue
            outcome = json.loads(file.read_text())
            relative = file.relative_to(base).as_posix()
            invocation = {
                "kind": "invocation",
                "case": name,
                "path": relative,
                "outcome": outcome,
                "exit": json.loads((file.parent / "exit.json").read_text()),
                "rewrite_statistics": (file.parent / "stderr.txt").read_text(),
            }
            for field, filename in (
                ("expression_evidence", "input-evidence.json"),
                ("interface_evidence", "context-evidence.json"),
            ):
                if (file.parent / filename).is_file():
                    invocation[field] = json.loads((file.parent / filename).read_text())
            evidence.append(invocation)
            calls += 1
            if record["group"] == "core" and relative == "k/stdout.txt":
                expression, _, _ = dwarf.root_inputs(outcome["configuration"]["term"])
                operations, gaps = instructions(expression)
                if dwarf.decode_bytes(expression["args"][3]) != list(
                    bytes.fromhex(case["expression"]["bytecode"])
                ):
                    raise ValueError("coverage expression differs")
                coverage.append(
                    {
                        "id": name,
                        "tool": case["tool"],
                        "instructions": operations,
                        "decode_gaps": gaps,
                        "location": (outcome.get("result") or {}).get(
                            "kind", "no_public_result"
                        ),
                    }
                )
    summary["coverage"] = {
        tool: coverage_counts([item for item in coverage if item["tool"] == tool])
        for tool in summary["sources"]
    }
    summary["coverage"]["combined"] = coverage_counts(coverage)
    summary["k_invocations"] = calls
    evidence.extend({"kind": "coverage", "record": item} for item in coverage)
    return {
        "report.md": render_report(summary).encode(),
        "expressions.csv": csv_data(
            [
                "id",
                "tool",
                "group",
                "execution",
                "verdict",
                "fully_checked",
                "diagnostic",
                "manual_remarks",
            ],
            rows,
        ),
        "differences.csv": csv_data(
            [
                "id",
                "tool",
                "group",
                "verdict",
                "analysis",
                "evidence_key",
                "manual_remarks",
            ],
            differences,
        ),
        "evidence.jsonl.gz": gzip.compress(
            b"".join(encoded(item) for item in evidence), mtime=0
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=positive, choices=range(1, 17), required=True)
    parser.add_argument("--timeout", type=positive, required=True)
    parser.add_argument("--depth", type=positive, required=True)
    parser.add_argument(
        "--interrupted",
        action="store_true",
        help="record a known run-level interruption",
    )
    parser.add_argument(
        "--diagnostic", default="", help="preserve a known run-level diagnostic"
    )
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output must not exist")
    import fcntl

    Path("/tmp/locks").mkdir(exist_ok=True)
    try:
        with open("/tmp/locks/kframework.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            files = export(
                ROOT,
                args.run,
                jobs=args.jobs,
                timeout=args.timeout,
                depth=args.depth,
                interrupted=args.interrupted,
                diagnostic=args.diagnostic,
            )
            args.output.mkdir(parents=True)
            for name, data in files.items():
                (args.output / name).write_bytes(data)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print("Recorded " + str(len(files)) + " files in " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
