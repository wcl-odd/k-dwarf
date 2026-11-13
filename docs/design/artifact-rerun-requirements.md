# Fresh experiment runner without saved-result comparison

Status: implemented on 2026-11-12. Validation is limited to Python unit tests, simulated execution and static packaging checks; no K invocation, compilation, debugger run or new experiment is included.

The public entry now runs the shared offline executor directly, checks original upstream expectations and generates fresh results. Saved project results remain reference material only.

## Goal

Run K afresh on the frozen corpus and generate a new set of experiment results. Continue checking the original GDB/LLDB expectations, but do not read, compare against, or depend on the project's saved experiment results.

The user explicitly confirmed that original upstream assertion checks must remain. Removing historical-result comparison does not mean removing the test oracle.

## Required behavior

- Make the public reproduction entry directly reuse the existing execution and assertion-checking workflow. Remove historical-result loading, historical per-case/final-configuration comparison, and the extra verifier subprocess used by that wrapper.
- Keep `--output`, `--source`, `--definition`, `--timeout`, `--depth`, and `--jobs`. Require a new output directory and refuse to overwrite an existing one.
- Keep the defaults: LLVM, `build/llvm-kompiled`, 120 seconds per K call, 10,000 rewrites, and four concurrent tasks. Python must use an existing definition and must not compile automatically.
- Write summary JSON, per-expression and per-check CSV, a readable results table, source reports, complete K final configurations, and dependency-call evidence directly below the requested output directory.
- Do not generate `comparison.json` or `comparison.csv`, historical agreement counts, or a verdict that the saved experiment was reproduced.
- Compute all new counts and rates from this run's individual checks. Do not hardcode the recorded pass/difference counts.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The experiment ran to completion without execution faults; semantic assertion differences do not change this code. |
| 1 | An execution fault, tool failure, timeout, or rewrite-budget exhaustion occurred. |
| 2 | Invalid arguments, inputs, or environment. |
| 130 | Interrupted execution. |

Original assertion passes, failures, uncheckable requirements, and execution states must remain explicit in the reports. The public entry must not use the number of semantic differences to determine whether the experiment completed successfully.

## Packaging and documentation

- Remove artifact runtime modules and forwarding scripts that are needed only for historical-result comparison. Keep development-side saved-result export code where it is still used.
- Retain the saved `results/` package as reference material. Rerunning must work when that directory is absent or corrupted, because the runtime must not read it.
- Continue reading original expectations and independent native location evidence from the frozen corpus; these are legitimate test inputs, not the project's saved K results.
- Update the development-side publisher, English README files, and command help so regenerated artifacts have the same behavior.

## Unchanged boundaries

- Plain `make` only compiles the semantics. Python only executes the experiment, checks original requirements, and writes new results.
- Preserve K rules, frozen expressions and contexts, original expectations, selection and comparison criteria, manual remarks, and all previously saved results.
- Keep the artifact independent of the development checkout and upstream debugger installations.
- Keep project temporary files and locks under the artifact's own `build/` directory, with runtime scratch files under `build/tmp/`. No existing material in `/tmp` is a reproduction dependency.

## Planned validation

- In a relocated copy, verify that the entry works with saved results removed and with deliberately corrupted saved results, without accessing either.
- Verify that original-assertion mutations still produce failing checks, while ordinary semantic failures do not make an otherwise completed experiment exit nonzero.
- Check argument forwarding, fresh output generation, source selection, output collision rejection, missing definitions, environment errors, tool faults, timeouts, budget exhaustion, and interruption cleanup.
- Run affected Python verification and packaging tests with simulated execution, and static dependency/copy checks. Do not invoke K for either upstream source in this change.
- Do not recompile K or rerun the complete frozen corpus solely to implement this interface change.

## Execution status

The user resumed implementation with an explicit no-experiment boundary. Runtime, packaging and English documentation changes are included; K rules, frozen inputs, original expectations, selected scope, saved results and manual notes remain unchanged. Actual experiment execution is deferred.
