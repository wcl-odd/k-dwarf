"""Count original expression test cases without counting their predicates twice.

An archived root expression case is the primary unit. Identical K inputs are
also grouped separately, with all their original observations conjoined. Missing
expression placeholders remain collection gaps, never fabricated empty inputs.
"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


STATUSES = ("pass", "fail", "uncheckable", "not_run", "tool_error")
EXECUTED = {"success", "incomplete"}


def assertion_key(source):
    return source["file"], source["line"], source["parameter"]


def outcome(records, checks, missing=False):
    """Every original requirement must be checked; a partial pass is not a pass."""
    states = {item["status"] for item in checks}
    states.update(r["execution"] for r in records if r["execution"] in {"tool_error", "not_run"})
    if missing:
        states.add("not_run")
    complete = bool(checks) and not missing and all(
        c["status"] in {"pass", "fail"}
        and c.get("semantic_check_complete", c["target"] not in {"no_crash", "uncheckable"})
        for c in checks
    ) and all(r["execution"] in EXECUTED for r in records)
    status = next((s for s in ("tool_error", "fail", "not_run", "uncheckable") if s in states), "pass")
    if status == "pass" and not complete:
        status = "uncheckable"
    return status, complete


def count(rows):
    total = len(rows)
    checked = sum(r["fully_checked"] for r in rows)
    passed = sum(r["status"] == "pass" for r in rows)
    return {
        "total": total,
        "entered_k": sum(r["entered_k"] for r in rows),
        "fully_checked": checked,
        "status": {s: sum(r["status"] == s for r in rows) for s in STATUSES},
        "pass_rate": passed / total if total else None,
        "pass_rate_checked": passed / checked if checked else None,
    }

