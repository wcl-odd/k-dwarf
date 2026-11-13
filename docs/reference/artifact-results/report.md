# Recorded expression-case experiment

One core expression case contributes one verdict; all its in-scope requirements must hold. This report packages an existing LLVM run, not a new experiment.

## Core results

| Source | Cases | Consistent | Inconsistent | Uncheckable | Undetermined | Consistent / cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GDB | 269 | 267 | 2 | 0 | 0 | 99.26% |
| LLDB | 55 | 43 | 12 | 0 | 0 | 78.18% |
| Total | 324 | 310 | 14 | 0 | 0 | 95.68% |

## Auxiliary checks

These checks are outside the core denominator. Their API/diagnostic requirements are not fully represented by the K interface.

| Source | Cases | Consistent | Inconsistent | Uncheckable | Undetermined | Consistent / cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LLDB | 2 | 0 | 0 | 2 | 0 | 0.00% |

## Run settings and completion

- Completed tasks: 326 / 326.
- K invocations: 584, including attributes and stability probes.
- Timeout: 120 seconds per K invocation.
- Rewrite budget: 10000 per K invocation; stability probes use a larger budget.
- Concurrency: 16 cases.
- Interrupted: no.
- Execution faults: 0.
- Exit code: 0.

Settings were supplied explicitly at export; 584 timeout receipts and 584 rewrite budgets were checked across 584 captured commands. Concurrency is not independently recorded by individual invocation receipts.

## Unexecuted tasks

None.

## Execution faults

None.

## Input and final-location coverage

OP counts describe root input presence, including nested blocks, not actual OP execution. Attribute calls do not enlarge the root denominator. Separately called bodies and skipped branches limit execution claims. Full OP names and instructions remain in the compressed coverage records.

| Source | Core inputs | OP names | Numbered families | Location categories | Decode-gap cases |
| --- | ---: | ---: | ---: | ---: | ---: |
| GDB | 269 | 52 | 39 | 7 | 0 |
| LLDB | 55 | 28 | 24 | 5 | 0 |
| COMBINED | 324 | 62 | 46 | 7 | 0 |

| Final root result | LLDB | GDB | Combined |
| --- | ---: | ---: | ---: |
| bytes | 1 | 6 | 7 |
| composite | 3 | 26 | 29 |
| implicit_pointer | 0 | 2 | 2 |
| memory | 28 | 145 | 173 |
| no_public_result | 13 | 4 | 17 |
| register | 1 | 12 | 13 |
| scalar | 0 | 8 | 8 |
| unavailable | 0 | 24 | 24 |
| value | 9 | 42 | 51 |

Scalar attribute values and outcomes without a public result are separate; neither is a location-description category. No floating arithmetic execution is confirmed in this upstream set. Metadata or raw register transport alone does not establish floating computation.

## Files and interpretation

| File | Contents |
| --- | --- |
| report.md | Result counts, settings, faults, coverage and interpretation |
| expressions.csv | All core and auxiliary verdicts, with manual remarks |
| differences.csv | Inconsistency and auxiliary analyses, with manual remarks |
| evidence.jsonl.gz | Complete case checks, K outcomes, dependency/stability calls and coverage |

The evidence is ordinary gzip JSON Lines with case, invocation and coverage records. Case ID and relative call path identify each record. Original requirements and source anchors are in ../test-corpus/lldb.json and ../test-corpus/gdb.json. Absolute strings in raw evidence are provenance, not runtime file dependencies.

Memory/register results compare location identity. Direct values retain their required value/type predicates; composites are checked piece by piece with exact availability. Expected abnormal termination is distinct from timeout or exhausted budget. Normal completion does not by itself establish consistency.

Fresh validation checks the frozen requirements and writes new files; it does not compare with these recorded verdicts. Source selection and semantic mapping involved human/AI review. Conclusions are limited to the selected cases and do not establish complete DWARF correctness.
