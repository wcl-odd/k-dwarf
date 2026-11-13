# Expression exclusions in the LLDB and GDB corpus

Snapshot: 2026-11-12. Sources: LLDB 22.1.8 and GDB 17.1. This document records the current selection; it changes no rules, inputs, expectations, scope, or experiment results. It belongs to the development project and is not included in the artifact.

## Counting unit and totals

An expression case is one archived root bytecode/context task. Different original contexts are separate cases; multiple predicates on one case do not multiply it. Identical bytes are not merged across contexts or original tasks. Attribute dependencies are not additional root cases.

**Expression cases, source assertion positions, and expanded debugger queries are different units.** An exclusion recorded only as a query cannot automatically be counted as one independent DWARF expression.

| Tool | Retained core expressions | Retained auxiliary evaluation tasks | Fully removed expression cases that can be identified | Total excluded from the core |
| --- | ---: | ---: | --- | --- |
| LLDB 22.1.8 | 55 | 2 | 2, because of an extension OP | 4: 2 removed and 2 retained as auxiliary |
| GDB 17.1 | 269 | 0 | 8 after extraction; initial source-only exclusions are not fully mapped to expression cases | Not fully determined; 8 identified removals plus an unquantified initial expression-level component |

For LLDB, the reviewed evaluator tasks reconcile as **59 = 55 core + 2 auxiliary + 2 extension exclusions**. Fixture and internal-API source checks below are not extra evaluator tasks.

For GDB, the identified post-extraction set reconciles as **277 = 269 retained + 8 removed**. This is not the size of the entire upstream candidate expression population. It does not include the 79 source-reviewed extension queries as 79 additional expressions.

## LLDB: reasons and expression counts

| Reason | Expressions outside the core | Disposition | Evidence |
| --- | ---: | --- | --- |
| Extension OP: DW_OP_WASM_location | 2 | Removed before extraction; helper called with main and split symbols | [Reviewed source selection](test-corpus/lldb-22.1.8/evidence/selections/cb76d31649682c6766e0a4b32248b51e70fd13ab3e9a5298fc0464c38f4ef5df.json) |
| Missing Module object required by the native API | 1 | Retained as auxiliary; not a core semantic pass | [Source assertion](test-corpus/lldb-22.1.8/sources/lldb/lldb/unittests/Expression/DWARFExpressionTest.cpp#L563), case lldb-22.1.8-L563-single |
| Exact diagnostic for unknown opcode 0xff | 1 | Retained as auxiliary; safe stopping does not validate LLDB's diagnostic text | [Source assertion](test-corpus/lldb-22.1.8/sources/lldb/lldb/unittests/Expression/DWARFExpressionTest.cpp#L629), case lldb-22.1.8-L629-single |
| **Total outside core** | **4** | **2 removed; 2 auxiliary retained** | |

The unknown byte 0xff is a diagnostic fixture, not another named extension OP. It is not included in the DW_OP_WASM_location count.

The source review also classifies **17 fixture assertions and 2 internal-API assertion positions** as auxiliary. These check fixture construction or methods such as Update_DW_OP_addr / ContainsThreadLocalStorage, rather than independent expression evaluation. Their 19 source positions must not be added to the expression exclusion total or confused with the two archived auxiliary evaluation tasks.

## GDB: identified removals after extraction

Each row has a distinct stable expression-case identity. Reasons in this table are mutually exclusive; the total is additive.

| Primary reason | Removed expression cases | Stable identity | Explanation |
| --- | ---: | --- | --- |
| C-language field arithmetic | 1 | `gdb-expanded-var-access-e35-t2` | The query computes t2.x + t2.y + t2.z, rather than checking an independent DWARF result. |
| C-language array cast and warning | 1 | `gdb-native-shortpiece-e6-s3` | The query p (int []) s3 requires C cast behavior and a cast warning; the direct p s3 check remains selected. |
| Unobservable debugger bounds diagnostic | 1 | `gdb-native-shortpiece-e2-s2` | The upstream synthetic-pointer bounds diagnostic cannot be faithfully checked by the archived K observation; a different K stopping condition is not equivalent. |
| Unmodelled recursive frame-base interface | 1 | `gdb-fixed-dw2-ref-missing-frame-e15-func_loopfb_var` | The original requires detection of a self-referential frame-base attribute; the fixed framebase interface cannot represent that recursive dependency faithfully. |
| Robustness-only check | 1 | `gdb-fixed-dw2-regno-invalid-e10-bregx` | The query has no explicit result matcher and checks that an oversized register number does not crash GDB. |
| Nonstandard DWARF attribute form | 1 | `gdb-fixed-dynamic-bit-offset-e2-value` | An expression-valued DW_AT_data_bit_offset is an attribute-form extension, not an extension OP. |
| Debugger selected-frame interface | 1 | `gdb-fixed-symbol_needs_eval_fail-e2-a` | No frame selected tests debugger interface state before execution, not a DWARF expression result. |
| No comparable independent location oracle | 1 | `gdb-fixed-dw2-entry-value-2-e12-argc` | The post-step argc fixture cannot be matched to a comparable location oracle. The expression is not declared structurally invalid; the entry-point argc case remains selected. |
| **Total identified removals** | **8** | | |

The complete list is the union of `excluded` and `inherited_exclusions` in [the final review](docs/reference/selection/review.json), deduplicated by id/expression_id. The [seven-row exclusion file](docs/reference/selection/excluded.json) alone omits the inherited C-field arithmetic removal, so counting that file alone would give the wrong total of seven.

## GDB: initial filters and the remaining counting gap

| Initial review reason | Source assertion positions | Expanded excluded query instances | Independent expression cases removed |
| --- | ---: | ---: | --- |
| Extension OP in the root or a required dependency | 66 | 79 | Not determined from the retained review records |
| Outside expression-result research scope | 676 | Not fully enumerated | Not determined; many checks have no independent expression task |
| Native control / auxiliary requirements | 140 | Not expanded as root expression cases | Not an expression-removal count |

The first two rows account for the **742 excluded source assertion positions** in the [GDB source selection](test-corpus/gdb-17.1/evidence/selections/9736904789bed94792c1b05a52e1756b99f8356bd46515251bfd1c0ae5ce993d.json). They are not 742 removed expressions. Formatting, symbols, execution control and unrelated language/interface checks may have no independent DWARF expression; other queries may require several expressions or dependencies. There is no complete expression-level expansion for these excluded candidates.

One additional [selected type query](docs/reference/selection/unextracted-query.json) has no independent root expression. It does not count as one removed expression or as an empty expression.

The retained review explicitly records `unextracted_expression_total_unknown: true`. Therefore, the complete GDB expression exclusion total and a complete expression-level breakdown by initial filtering reason cannot currently be reported as exact numbers. **Do not write 79 or 87 (= 79 + 8) as that total.**

### Extension OP details

The LLDB count below is confirmed as two evaluator expression cases. GDB entries count reviewed expanded queries, not fully extracted root expressions. A query with several extension OPs appears under each relevant OP, so rows must not be summed.

| Tool | Extension OP | Excluded instances | Unit |
| --- | --- | ---: | --- |
| LLDB | `DW_OP_WASM_location` | 2 | Expression cases |
| GDB | `DW_OP_GNU_addr_index` | 3 | Expanded query instances |
| GDB | `DW_OP_GNU_const_type` | 7 | Expanded query instances |
| GDB | `DW_OP_GNU_convert` | 22 | Expanded query instances |
| GDB | `DW_OP_GNU_entry_value` | 1 | Expanded query instances |
| GDB | `DW_OP_GNU_implicit_pointer` | 33 | Expanded query instances |
| GDB | `DW_OP_GNU_regval_type` | 21 | Expanded query instances |
| GDB | `DW_OP_GNU_reinterpret` | 2 | Expanded query instances |
| GDB | `DW_OP_GNU_uninit` | 2 | Expanded query instances |
| GDB | `DW_OP_GNU_variable_value` | 13 | Expanded query instances |

After deduplication within each tool: **LLDB: 2 expression cases, 1 extension OP name; GDB: 79 reviewed queries, 9 extension OP names.** Their sum of 81 is a mixed-unit review-instance count, not a combined expression-exclusion count.

## Interpretation for reporting

- LLDB has an exact expression-level account: two removed for an extension OP and two retained as auxiliary for native API/diagnostic requirements.
- GDB has an exact account of eight identified post-extraction removals, with one case for each reason above. Its full initial-filter expression count remains unknown.
- Attribute-form extensions are separate from extension OPs. Retained semantic differences and missing K support alone are not exclusion reasons.
- This document does not reconstruct missing bytecode/context mappings or silently substitute assertion counts for expression counts. Completing the GDB total requires a separate review and mapping of excluded candidates, preserving original query parameters and contexts.

Sources: [current task scope](test-corpus/scope.json), [final selection decisions](docs/reference/selection/review.json), [excluded cases](docs/reference/selection/excluded.json), [methodology](docs/evaluation/methodology.md), and the two source selections linked above. No K run, debugger run, corpus change, or artifact update was performed to create this document.
