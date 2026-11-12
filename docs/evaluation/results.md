# Final experiment results

LLDB 22.1.8 and GDB 17.1; standard DWARF expressions. Only K is run during offline reproduction. The native contexts were previously collected and frozen.

| Source | Expressions | Entered K | Fully checked | Pass | Differences | Uncheckable | Not run | Tool errors | Pass / expressions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LLDB | 55 | 55 | 55 | 43 | 12 | 0 | 0 | 0 | 78.18% |
| GDB | 269 | 269 | 269 | 267 | 2 | 0 | 0 | 0 | 99.26% |

Each original expression/context task is counted once; all in-scope predicates must hold. Two LLDB API/diagnostic tasks are auxiliary. Attribute calls do not enlarge the denominator.

## What the LLDB assertions check

| Original requirement | Expressions | Pass | Differences |
| --- | ---: | ---: | ---: |
| Scalar value | 25 | 22 | 3 |
| Expected evaluation failure | 6 | 6 | 0 |
| Load address | 16 | 12 | 4 |
| Object buffer | 7 | 2 | 5 |
| Register identity | 1 | 1 | 0 |

Scalar equality follows the original matcher's value interpretation and integer promotions; a Scalar constructor width is not automatically an exact actual-type requirement. Load addresses compare category/address. Register locations compare category/DWARF number. Host buffers compare content/extent; stopped predicates require the exact scene and verified natural-stop stability.

## Input OP and observed location coverage

| Source | Root expressions | Standard OP names / 164 | Numbered families / 71 | Location categories / 7 |
| --- | ---: | ---: | ---: | ---: |
| lldb | 55 | 28 | 24 | 5 |
| gdb | 269 | 52 | 39 | 7 |
| combined | 324 | 62 | 46 | 7 |

The primary OP metric assumes operations present in each root input are covered: **62 names, 46 numbered families**. Only lit0–31, reg0–31 and breg0–31 are merged. This is input presence at K-certified boundaries, not a dynamic execution trace. Dependency-only operations are supplementary; referenced call bodies retain an inventory evidence gap.

| Final root result | LLDB | GDB | Combined |
| --- | ---: | ---: | ---: |
| memory | 28 | 145 | 173 |
| register | 1 | 12 | 13 |
| value | 9 | 42 | 51 |
| bytes | 1 | 6 | 7 |
| composite | 3 | 26 | 29 |
| implicit_pointer | 0 | 2 | 2 |
| unavailable | 0 | 24 | 24 |
| scalar | 0 | 8 | 8 |
| no_public_result | 13 | 4 | 17 |

Scalar is a value-purpose result; no_public_result is an execution state. Neither is a location category. Internal composite piece categories are separate and may overlap within one expression.

## Types and floating point

The semantics implements DW_ATE_float binary32, binary64, x87 binary80 and binary128: encoding plus numerical representation defines a format. Distinct DIE identities or storage padding do not create additional numerical formats. Six arithmetic operations (abs, neg, plus, minus, mul, div), six comparisons, convert and reinterpret have format/type preconditions. Integer-only operations are not floating-point implementation gaps. Boolean conversion is limited to the documented canonical representation.

| Upstream evidence | LLDB | GDB |
| --- | ---: | ---: |
| Float metadata in context | 0 | 6 |
| Final typed float stack/result | 0 | 0 |

No floating arithmetic execution is confirmed in this upstream set. Metadata presence and register bit transport are not floating computation. Final type, context type metadata and original object static type are counted separately in CSV/JSON. Project floating probes are separate evidence, never added to upstream totals.

[Per-expression OP, type and floating evidence](../../output/coverage/evidence.json) · [All implemented OP names](../reference/support/ops.csv) · [Per-OP floating support](../reference/support/floating-ops.json) · [Regression and proof evidence](../../output/validation/README.md)

This experiment supports the selected expressions and checked properties; it does not establish complete DWARF correctness, all combinations, or all base types. One selected GDB type query has no independent root expression and is not fabricated as an empty expression.
