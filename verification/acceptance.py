"""Replay archived upstream inputs using K alone."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from copy import copy
import json
import re
import shutil
from pathlib import Path

from . import assertions
from .backends import k
from .corpus import load_cases, source_evidence
from .input import prepare as prepare_case, write_json
from .process import ToolFailure



def verify_stopped_configuration(case, directory, options, payload):
    """Ask K again with more budget; do not decode OPs or classify failures."""
    probe_options = copy(options)
    probe_options.depth = options.depth + max(10000, options.depth)
    probe_directory = directory / "stability-probe"
    prepare_case(case, probe_directory)
    probe = k.run(case, probe_directory, probe_options)
    def steps(document):
        raw = document.get("rewrite_statistics", {}).get("raw", "")
        match = re.search(r"([0-9]+)\s+(?:steps|rewrites)", raw, re.I)
        return int(match[1]) if match else None
    original_configuration = payload.get("configuration")
    probe_configuration = probe.native.get("configuration")
    evidence = {
        "base_budget": options.depth, "probe_budget": probe_options.depth,
        "base_rewrite_steps": steps(payload), "probe_rewrite_steps": steps(probe.native),
        "probe_status": probe.native.get("status"),
        "same_configuration": original_configuration is not None and original_configuration == probe_configuration,
        "probe_output": str(probe_directory / "k/stdout.txt"),
        "probe_input_evidence": str(probe_directory / "k/input-evidence.json"),
    }
    write_json(directory / "stability-evidence.json", evidence)
    return evidence


def test(options):
    inputs, output = options.inputs.resolve(), options.output.resolve()
    if output.exists():
        raise ValueError(f"test output must not exist: {output}")
    from .corpus_archive import read_prepared
    cases, manifest, corpus_scope = read_prepared(inputs)
    output.mkdir(parents=True)
    records = []
    counts = Counter()
    roots = {key: Path(value) for key, value in manifest["source_roots"].items()}
    for case in cases:
        for assertion in case.upstream_assertions:
            source = assertion["source"]
            from .corpus_archive import local_path
            file = local_path(roots[source["project"]], source["file"])
            lines = file.read_text().splitlines() if file.is_file() else []
            if (not file.is_file() or not 0 < source["line"] <= len(lines) or lines[source["line"]-1] != source["text"]):
                raise ValueError("source assertion anchor changed: " + str(file))
    options.statistics = True
    options.definition_evidence={'path':str(options.definition)}
    def execute_case(case):
        original_case=case
        directory = output / case.id
        prepare_case(case, directory)
        evidence = source_evidence(case, roots)
        state, diagnostic, payload = "not_run", "", {}
        if evidence["status"] != "match":
            diagnostic = "upstream source missing or changed; prepared assertion cannot be verified"
        elif case.origin.get("capture_error"):
            diagnostic = case.origin["capture_error"]
        else:
            try:
                if case.dependencies or any(case.origin.get(name) for name in ('pointer_root_size','count_root','resolve_implicit',
                        'member_address_observation','missing_bound_observation')):
                    from .dependencies import execute as run_dependencies, observation
                    obs,context,results,dependency_evidence,reason=run_dependencies(case,directory,options)
                    if obs is None:
                        state,diagnostic,payload='incomplete',reason,{'status':'incomplete','dependency_results':results}
                        payload['dependency_evidence']=dependency_evidence
                        if isinstance(reason,dict):
                            state='not_run';diagnostic=reason['diagnostic'];payload['observation_gap']=reason
                    else:
                        state,diagnostic,payload=obs.state,obs.diagnostic,obs.native
                        payload=observation(case,payload,results,reason)
                        payload['dependency_evidence']=dependency_evidence
                        case=replace(case,context=context)
                else:
                    obs = k.run(case, directory, options)
                    state, diagnostic, payload = obs.state, obs.diagnostic, obs.native
                if state == "incomplete" and any(a["target"] == "stopped" and a["expected"].get("stable")
                                                  for a in case.upstream_assertions):
                    payload["stability_evidence"] = verify_stopped_configuration(case, directory, options, payload)
            except (ToolFailure, OSError, ValueError, KeyError, TypeError) as error:
                state, diagnostic = "tool_error", str(error)
        checks = assertions.check(case, payload, state, diagnostic)
        if not checks:
            raise ValueError(f"upstream case has no assertion mapping: {case.id}")
        raw_stats = payload.get("rewrite_statistics", {}).get("raw", "")
        count = re.search(r"([0-9]+)\s+(?:steps|rewrites)", raw_stats, re.I)
        steps = int(count[1]) if count else None
        record = {"id": case.id, "origin": case.origin, "execution": state,
                  # Retained historical identity is a provenance label, not a digest check.
                  "input_identity":corpus_scope[case.id].get('input_identity') if corpus_scope else None,
                  "input":{'bytes':original_case.bytes, 'address_width':original_case.address_width,
                      'endianness':original_case.endianness, 'architecture':original_case.architecture,
                      'context':original_case.context, 'purpose':original_case.purpose,
                      'dependencies':original_case.dependencies},
                  "diagnostic": diagnostic, "position": payload.get("position"),
                  "budget": options.depth, "rewrite_steps": steps,
                  "budget_exhausted": (steps >= options.depth) if steps is not None and state == "incomplete" else False if state == "success" else None,
                  "rewrite_statistics": raw_stats,
                  "stability_evidence": payload.get("stability_evidence"),
                  "checks": checks, "source_evidence": evidence, "dependency_evidence":payload.get("dependency_evidence",[])}
        if case.origin.get('location_oracle'):
            from .locations import check_archived
            record['location_check'] = check_archived(case, payload)
        if corpus_scope is not None:
            from .corpus_archive import evaluate_scope
            record['corpus_evaluation'] = evaluate_scope(record, corpus_scope[case.id])
        write_json(directory / "acceptance.json", record)
        print(case.id, state, dict(Counter(c["status"] for c in checks)), flush=True)
        return record
    with ThreadPoolExecutor(max_workers=getattr(options, "jobs", 4)) as executor:
        futures = {executor.submit(execute_case, case): i for i, case in enumerate(cases)}
        completed = {}
        try:
            for future in as_completed(futures):
                record = future.result()
                completed[futures[future]] = record
                records = [completed[i] for i in sorted(completed)]
                counts.update(item["status"] for item in record["checks"])
                _report(output, records, counts, inputs, options)
        except BaseException:
            from .process import stop_children
            for future in futures: future.cancel()
            stop_children()
            raise
    return _report(output, records, counts, inputs, options)


def _report(output, records, counts, inputs, options):
    def has_expression(record):
        origin=record["origin"]
        # Older capture archives recorded absent DIE expressions as an explicit
        # null selection before adding missing_expression. An actual empty unit
        # expression has no selection key and remains a legitimate input.
        return not origin.get("missing_expression",False) and not (
            "selection" in origin and origin["selection"] is None)
    anchors = {(c["source"]["project"], c["source"]["file"], c["source"]["line"]) for r in records for c in r["checks"]}
    instances = {(c["source"]["project"], c["source"]["file"], c["source"]["line"], c["source"]["parameter"]) for r in records for c in r["checks"]}
    grouped = {}
    for r in records:
        for c in r["checks"]:
            s=c["source"]
            grouped.setdefault((s["project"],s["file"],s["line"],s["parameter"]),[]).append(c["status"])
    priority = {"pass":0,"uncheckable":1,"not_run":2,"fail":3,"tool_error":4}
    whole = Counter(max(values,key=priority.get) for values in grouped.values())
    preparation = json.loads((inputs / "preparation.json").read_text())
    capture_errors = (preparation.get("capture") or {}).get("tool_errors",0)
    summary = {"inputs":len(records), "expressions":sum(has_expression(r) for r in records), "source_assertion_sites": len(anchors),
        "distinct_expression_inputs":len({json.dumps(r["input"],sort_keys=True) for r in records if has_expression(r)}),
        "expanded_assertion_instances": len(instances), "checks": dict(counts),
        "whole_assertion_instances":dict(whole), "capture_tool_errors":capture_errors,
        "execution": dict(Counter(r["execution"] for r in records)),
        "attribute_invocations":sum('directory' in e for r in records for e in r.get('dependency_evidence',[])),
        "attribute_execution":dict(Counter(e['status'] for r in records for e in r.get('dependency_evidence',[]) if 'directory' in e)),
        "no_crash_only": sum(c.get("category") == "no_crash_only" for r in records for c in r["checks"]),
        "semantic_predicates_passed":sum(bool(c.get("semantic_predicates_checked") and c.get("predicates_passed")) for r in records for c in r["checks"]),
        "exit_code": int(bool(counts["fail"] or counts["tool_error"] or capture_errors or
            (options.require_complete and (counts["uncheckable"] or counts["not_run"]))))}
    if preparation.get('path_format'):
        from .corpus_archive import scope_summary
        summary['source_requirements_exit_code'] = summary['exit_code']
        summary['corpus_scope'] = scope_summary(records, options.require_complete)
        summary['exit_code'] = summary['corpus_scope']['exit_code']
    summary["by_project"] = {}
    for project in ("lldb", "gdb"):
        selected = [r for r in records if r["origin"]["project"] == project]
        sites = {(c["source"]["file"], c["source"]["line"]) for r in selected for c in r["checks"]}
        summary["by_project"][project] = {
            "inputs":len(selected), "source_assertion_sites":len(sites),
            "checks":dict(Counter(c["status"] for r in selected for c in r["checks"])),
            "whole_assertion_instances":dict(Counter(max(values,key=priority.get)
                for key,values in grouped.items() if key[0] == project)),
            "execution":dict(Counter(r["execution"] for r in selected)),
        }
    write_json(output / "report.json", {"schema": 1, "inputs": str(inputs), "summary": summary, "cases": records,
        **({'definition':options.definition_evidence} if getattr(options,'definition_evidence',None) else {})})
    lines = ["# K upstream assertion validation", "", "Expectations come from archived upstream assertions; only K is executed.", "",
        f"Summary: `{summary}`", "", "A partially checked assertion is not a complete pass.", "",
        "| Expression | K execution | Source checks |", "| --- | --- | --- |"]
    for record in records:
        lines.append(f"| [{record['id']}]({record['id']}/acceptance.json) | {record['execution']} | " +
            ", ".join(f"{c['source']['line']}: {c['status']}" for c in record["checks"]) + " |")
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return summary
