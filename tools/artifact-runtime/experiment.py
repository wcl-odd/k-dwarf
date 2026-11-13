"""Evaluate expression cases in K and report consistency with their requirements."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import copy
import csv
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from cases import load_corpus, prepare, replace_case, write_json
import dependencies
import k
from processes import ROOT, ToolFailure, stop_children
from requirements import check_requirements


def positive(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def rewrite_steps(payload):
    match = re.search(
        r"([0-9]+)\s+(?:steps|rewrites)",
        payload.get("rewrite_statistics", {}).get("raw", ""),
        re.I,
    )
    return int(match[1]) if match else None


def invocation_faults(directory):
    """Classify process failures separately from semantic requirements."""
    faults = []
    for file in sorted(directory.rglob("exit.json")):
        if file.parent.name != "k":
            continue
        call = file.parent.relative_to(directory).as_posix()
        try:
            receipt = json.loads(file.read_text())
            if receipt.get("timeout"):
                kind = "timeout"
            elif receipt.get("interrupted"):
                kind = "interrupted"
            elif receipt.get("launch_error") or receipt.get("returncode") not in (0, 1):
                kind = "tool_error"
            elif receipt["returncode"] == 0:
                continue
            else:
                command = json.loads((file.parent / "command.json").read_text())["argv"]
                budget = int(command[command.index("--depth") + 1])
                count = re.search(
                    r"([0-9]+)\s+(?:steps|rewrites)",
                    (file.parent / "stderr.txt").read_text(),
                    re.I,
                )
                kind = (
                    "tool_error"
                    if count is None
                    else "budget_exhausted" if int(count[1]) >= budget else None
                )
            if kind:
                faults.append({"call": call, "kind": kind})
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            faults.append(
                {"call": call, "kind": "tool_error", "diagnostic": str(error)}
            )
    return faults


def evaluate_case(case, output, options):
    """Run a case and any stability probe, then check its requirements."""
    directory = output / case.id
    prepare(case, directory)
    payload = {}
    state = "not_run"
    diagnostic = ""
    try:
        if case.dependencies or any(
            case.observation_inputs.get(name)
            for name in (
                "pointer_root_size",
                "count_root",
                "resolve_implicit",
                "member_address_observation",
                "missing_bound_observation",
            )
        ):
            outcome, interface, results, evidence, reason = dependencies.execute(
                case, directory, options
            )
            if outcome is None:
                state = "not_run"
                diagnostic = str(reason)
                payload = {"dependency_evidence": evidence}
            else:
                state, diagnostic = outcome.state, outcome.diagnostic
                payload = dependencies.observation(
                    case, outcome.outcome, results, reason
                )
                payload["dependency_evidence"] = evidence
                case = replace_case(case, context=interface)
        else:
            outcome = k.run(case, directory, options)
            state, diagnostic, payload = (
                outcome.state,
                outcome.diagnostic,
                outcome.outcome,
            )
        if state == "incomplete" and any(
            predicate["target"] == "stopped" and predicate["expected"].get("stable")
            for predicate in case.predicates
        ):
            probe_options = copy(options)
            probe_options.depth = options.depth + max(10000, options.depth)
            probe_directory = directory / "stability-probe"
            prepare(case, probe_directory)
            probe = k.run(case, probe_directory, probe_options)
            payload["stability_evidence"] = {
                "base_budget": options.depth,
                "probe_budget": probe_options.depth,
                "base_rewrite_steps": rewrite_steps(payload),
                "probe_rewrite_steps": rewrite_steps(probe.outcome),
                "probe_status": probe.outcome.get("status"),
                "same_configuration": payload.get("configuration") is not None
                and payload.get("configuration") == probe.outcome.get("configuration"),
            }
            write_json(directory / "stability.json", payload["stability_evidence"])
    except (ToolFailure, OSError, ValueError, KeyError, TypeError) as error:
        state = "tool_error"
        diagnostic = str(error)
    requirement_checks = check_requirements(case, payload, state, diagnostic)
    faults = invocation_faults(directory)
    if state in {"tool_error", "not_run"}:
        faults.append({"call": "root", "kind": state, "diagnostic": diagnostic})
    execution = {
        "success": "normal_completion",
        "incomplete": "abnormal_termination",
    }.get(state, state)
    if faults:
        requirement_checks["verdict"] = "undetermined"
        requirement_checks["fully_checked"] = False
    record = {
        "id": case.id,
        "tool": case.tool,
        "group": case.group,
        "execution": execution,
        **requirement_checks,
        "execution_faults": faults,
        "diagnostic": diagnostic,
        "position": payload.get("position"),
        "end": payload.get("end"),
        "location": payload.get("result"),
        "dependency_evidence": payload.get("dependency_evidence", []),
    }
    write_json(directory / "outcome.json", record)
    return record


def summarize(records):
    """Count verdicts separately for each source and core or auxiliary group."""
    summary = {}
    for tool in sorted({record["tool"] for record in records}):
        groups = {}
        for group in ("core", "auxiliary"):
            selected = [
                record
                for record in records
                if record["tool"] == tool and record["group"] == group
            ]
            counts = Counter(record["verdict"] for record in selected)
            groups[group] = {
                "cases": len(selected),
                "consistent": counts["consistent"],
                "inconsistent": counts["inconsistent"],
                "uncheckable": counts["uncheckable"],
                "undetermined": counts["undetermined"],
                "consistency_rate": (
                    counts["consistent"] / len(selected) if selected else None
                ),
            }
        summary[tool] = groups
    return summary


def markdown_cell(value):
    """Keep diagnostic text inside one Markdown table cell."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", "<br>")
    )


def write_report(output, records, options, *, interrupted=False, diagnostic=""):
    """Write checks and counts, including required cases that have not finished."""
    sources = summarize(records)
    faults = [
        {"id": record["id"], **fault}
        for record in records
        for fault in record["execution_faults"]
    ]
    missing = sorted(
        set(getattr(options, "case_ids", [])) - {record["id"] for record in records}
    )
    faults.extend({"id": name, "call": "root", "kind": "not_run"} for name in missing)
    if diagnostic:
        faults.append(
            {
                "id": "run",
                "call": "root",
                "kind": "tool_error",
                "diagnostic": diagnostic,
            }
        )
    core = [record for record in records if record["group"] == "core"]
    summary = {
        "unit": "expression case",
        "sources": sources,
        "total": {
            "cases": len(core),
            "consistent": sum(record["verdict"] == "consistent" for record in core),
            "inconsistent": sum(record["verdict"] == "inconsistent" for record in core),
            "uncheckable": sum(record["verdict"] == "uncheckable" for record in core),
            "undetermined": sum(record["verdict"] == "undetermined" for record in core),
        },
        "tasks_completed": len(records),
        "tasks_expected": len(getattr(options, "case_ids", records)),
        "missing_cases": missing,
        "settings": {
            "timeout": options.timeout,
            "depth": options.depth,
            "jobs": options.jobs,
        },
        "execution_faults": faults,
        "interrupted": interrupted,
        "exit_code": 130 if interrupted else int(bool(faults)),
    }
    for file, columns, rows in [
        (
            "expressions.csv",
            [
                "id",
                "tool",
                "group",
                "execution",
                "verdict",
                "fully_checked",
                "diagnostic",
            ],
            records,
        ),
        (
            "checks.csv",
            ["expression", "target", "status", "complete", "details"],
            [
                {
                    "expression": record["id"],
                    "target": c["target"],
                    "status": {"pass": "consistent", "fail": "inconsistent"}.get(
                        c["status"], c["status"]
                    ),
                    "complete": c.get("semantic_check_complete", False),
                    "details": json.dumps(c.get("details", [])),
                }
                for record in records
                for c in record["checks"]
            ],
        ),
    ]:
        with (output / file).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def table_row(label, counts):
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
        "# Expression-case validation",
        "",
        "Each core expression case contributes one verdict. All its requirements must hold.",
        "",
        "## Core results",
        "",
        columns,
        separator,
    ]
    for tool, groups in sources.items():
        lines.append(table_row(tool.upper(), groups["core"]))
    lines.append(table_row("Total", summary["total"]))
    lines += [
        "",
        "## Auxiliary checks",
        "",
        "Auxiliary checks are excluded from the core denominator.",
        "",
    ]
    auxiliary = {
        tool: groups["auxiliary"]
        for tool, groups in sources.items()
        if groups["auxiliary"]["cases"]
    }
    if auxiliary:
        lines += [columns, separator]
        for tool, counts in auxiliary.items():
            lines.append(table_row(tool.upper(), counts))
    else:
        lines.append("None.")
    lines += [
        "",
        "## Run settings and completion",
        "",
        f"- Completed tasks: {summary['tasks_completed']} / {summary['tasks_expected']}.",
        f"- Timeout: {options.timeout} seconds per K invocation.",
        f"- Rewrite budget: {options.depth} per K invocation.",
        f"- Concurrency: {options.jobs} cases.",
        f"- Interrupted: {'yes' if interrupted else 'no'}.",
        f"- Execution faults: {len(faults)}.",
        f"- Exit code: {summary['exit_code']}.",
        "",
        "## Unexecuted tasks",
        "",
    ]
    lines.extend(f"- `{name}`" for name in missing)
    if not missing:
        lines.append("None.")
    lines += ["", "## Execution faults", ""]
    if diagnostic:
        lines += ["Run diagnostic: " + markdown_cell(diagnostic), ""]
    if faults:
        lines += [
            "| Case | Call | Kind | Diagnostic |",
            "| --- | --- | --- | --- |",
        ]
        for fault in faults:
            cells = [
                markdown_cell(fault.get(name, ""))
                for name in ("id", "call", "kind", "diagnostic")
            ]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("None.")
    lines += [
        "",
        "## Interpretation and evidence",
        "",
        "Normal completion is not a consistency verdict. Expected abnormal termination "
        "requires the reviewed stopped state and a separate stability check. Timeout "
        "and rewrite-budget exhaustion are execution limitations, not expected semantic "
        "failures. Source information is documentation only; no upstream source, "
        "debugger or saved result is read.",
        "",
        "See expressions.csv, checks.csv and each case directory for requirements, "
        "dependency evidence and full K outcomes. This report is the run summary; "
        "no separate summary file is written.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return summary


class ResourceGate:
    """Bound concurrent cases and stop owned processes before exhausting memory."""

    def __init__(self, jobs):
        self.limit = jobs
        self.active = 0
        self.failed = None
        self.condition = threading.Condition()
        self.done = threading.Event()

    def monitor(self):
        """Watch process memory and cancel owned workers at the safety limits."""
        while not self.done.wait(1):
            try:
                pending = [os.getpid()]
                resident_bytes = 0
                while pending:
                    pid = pending.pop()
                    try:
                        resident_bytes += int(
                            Path(f"/proc/{pid}/statm").read_text().split()[1]
                        ) * os.sysconf("SC_PAGE_SIZE")
                        pending.extend(
                            int(p)
                            for p in Path(f"/proc/{pid}/task/{pid}/children")
                            .read_text()
                            .split()
                        )
                        # K calls are launched from worker threads.
                        for thread in Path(f"/proc/{pid}/task").iterdir():
                            if thread.name != str(pid):
                                pending.extend(
                                    int(p)
                                    for p in (thread / "children").read_text().split()
                                )
                    except (OSError, ValueError):
                        pass
                available_bytes = (
                    int(
                        re.search(
                            r"MemAvailable:\s+(\d+)", Path("/proc/meminfo").read_text()
                        )[1]
                    )
                    * 1024
                )
                with self.condition:
                    if resident_bytes >= 32 * 1024**3 or available_bytes < 16 * 1024**3:
                        self.failed = "memory safety limit reached"
                        stop_children()
                        self.condition.notify_all()
                    elif resident_bytes >= 24 * 1024**3:
                        self.limit = max(1, self.limit // 2)
            except (OSError, ValueError, TypeError):
                pass

    @contextmanager
    def slot(self):
        with self.condition:
            self.condition.wait_for(lambda: self.failed or self.active < self.limit)
            if self.failed:
                raise ToolFailure(self.failed)
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


def preflight(definition):
    if sys.version_info < (3, 10):
        raise ValueError("Python 3.10 or newer is required")
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("Linux x86-64 is required")
    if not (definition / "compiled.bin").is_file():
        raise ValueError(
            "compiled definition missing; run make or specify --definition"
        )
    for program in ("krun", "kparse", "java"):
        if shutil.which(program) is None:
            raise ValueError("missing dependency: " + program)
    version = subprocess.run(
        ["krun", "--version"], capture_output=True, text=True, timeout=30
    )
    if version.returncode or "v7.1.337" not in version.stdout + version.stderr:
        raise ValueError("K v7.1.337 is required")


def main(argv=None):
    """Validate inputs, schedule bounded workers and preserve partial reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--definition", type=Path, default=ROOT / "build/llvm-kompiled")
    parser.add_argument("--source", choices=["all", "lldb", "gdb"], default="all")
    parser.add_argument("--timeout", type=positive, default=120)
    parser.add_argument("--depth", type=positive, default=10000)
    parser.add_argument("--jobs", type=positive, choices=range(1, 17), default=4)
    options = parser.parse_args(argv)
    options.definition = options.definition.absolute()
    options.statistics = True
    output = Path(os.path.abspath(options.output))
    records = []
    scratch = None
    gate = None
    created = False
    try:
        if output.exists() or output.is_symlink():
            raise ValueError("output must not exist")
        if any(parent.is_symlink() for parent in output.parents):
            raise ValueError("output cannot follow a symlink")
        if any(
            output.is_relative_to(ROOT / name)
            for name in ("semantics", "scripts", "test-corpus", "results")
        ):
            raise ValueError("output overlaps project inputs")
        if output.is_relative_to(
            options.definition
        ) or options.definition.is_relative_to(output):
            raise ValueError("output overlaps compiled definition")
        cases = load_corpus(ROOT / "test-corpus", options.source)
        if not cases:
            raise ValueError("no expression cases selected")
        options.case_ids = [case.id for case in cases]
        preflight(options.definition)
        (ROOT / "build/tmp").mkdir(parents=True, exist_ok=True)
        scratch = tempfile.mkdtemp(prefix="experiment-", dir=ROOT / "build/tmp")
        os.environ.update(
            TMPDIR=scratch,
            DWARF_INPUT_TMPDIR=scratch,
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            GHCRTS="-N1",
            K_OPTS="-Xmx512m -Xss8m",
            PYTHONDONTWRITEBYTECODE="1",
        )
        if hasattr(os, "sched_getaffinity"):
            os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:16])
        output.mkdir(parents=True)
        created = True
        with (ROOT / "build/experiment.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            gate = ResourceGate(options.jobs)
            thread = threading.Thread(target=gate.monitor, daemon=True)
            thread.start()

            def work(case):
                with gate.slot():
                    return evaluate_case(case, output, options)

            with ThreadPoolExecutor(max_workers=options.jobs) as pool:
                futures = {pool.submit(work, case): case for case in cases}
                try:
                    for future in as_completed(futures):
                        record = future.result()
                        records.append(record)
                        records.sort(key=lambda record: record["id"])
                        print(
                            record["id"],
                            record["execution"],
                            record["verdict"],
                            flush=True,
                        )
                        write_report(output, records, options)
                except BaseException:
                    gate.failed = "execution cancelled"
                    with gate.condition:
                        gate.condition.notify_all()
                    for future in futures:
                        future.cancel()
                    stop_children()
                    raise
            summary = write_report(output, records, options)
            return summary["exit_code"]
    except KeyboardInterrupt:
        stop_children()
        if created:
            write_report(output, records, options, interrupted=True)
        return 130
    except Exception as error:
        stop_children()
        print("validate: " + str(error), file=sys.stderr)
        if created:
            write_report(output, records, options, diagnostic=str(error))
        return 1 if created or isinstance(error, ToolFailure) else 2
    finally:
        if gate:
            gate.done.set()
        if scratch:
            shutil.rmtree(scratch)
