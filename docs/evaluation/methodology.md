# Test selection, extraction and checkability

## Sources and selection

| Source | Frozen release | Candidate scope | Final roots |
| --- | --- | --- | ---: |
| LLDB | llvmorg-22.1.8; ca7933e47d3a3451d81e72ac174dcb5aa28b59d1 | Entire DWARFExpressionTest.cpp, 19 test functions | 55 core + 2 auxiliary |
| GDB | gdb-17.1-release; 631a49c452a4a456dd9889d172541ea789f8bcae | gdb.dwarf2: 280 .exp drivers, 3 embedded C assertion sources; 6 shared Tcl files / 15 anchor sites additionally reviewed | 269 core from 37 drivers |

LLDB's evaluator unit tests expose original byte arrays, helper conditions, mock state and matchers. Original loops are expanded into fixture instances, retaining reader address size, endianness, type references and absent-context conditions. This is reviewed source-fixture reconstruction, not a claim that the native LLDB unit binary was rerun. LLDB Shell/API suites are outside this frozen corpus.

GDB's gdb.dwarf2 is selected because its stated test purposes directly concern DWARF expressions, location descriptions, layouts and dynamic attributes. Many tests deliberately construct debug metadata with Dwarf::assemble; some use compiler-generated or supplied assembly inputs. The directory is not claimed to be entirely handwritten DWARF. Other GDB directories primarily test language evaluation, execution control, architecture, remote protocols, symbols or interfaces; DWARF locations there are often background infrastructure.

Selection is purpose-based, not random and not representative of the entire debugger suite. Fix the native Linux x86-64, LP64, little-endian configuration. Include standard expression evaluation, location identity, object fragments/availability and dynamic attributes. Retain genuine empty expressions and expected semantic failures. Exclude vendor OPs in roots, nested blocks and required dependencies; exclude architecture-inapplicable inputs, C-language arithmetic/casts, format/backtrace-only requirements, robustness-only tests, nonstandard attribute forms and debugger-interface conditions that this framework cannot faithfully observe. Missing K rules or differing answers are not exclusion criteria.

Each candidate source and assertion has a reviewed disposition with source evidence in the packaged frozen selections. The final eligible expression scope is in scope.json, separate from earlier source-assertion units. Subsequent scope decisions are disclosed in the final review and exclusion list; changed proportions must not be described as rule improvements. One selected GDB type query has no independent root expression; no fake empty task is inserted. Source assertions, expanded instances, root expressions and attribute calls are distinct quantities.

[Final reviewed decisions](../reference/selection/review.json) · [Excluded assertions and reasons](../reference/selection/excluded.json) · [No-independent-expression query](../reference/selection/unextracted-query.json) · [Frozen corpus and original sources](../../test-corpus/README.md)

## Three inputs for one case

| Input | Archived representation | How it was obtained |
| --- | --- | --- |
| Expression | cases.json: bytes | LLDB reviewed source literals/mock fixtures; GDB original ELF/DWO DWARF byte blocks selected by CU, DIE, PC and location-list range |
| Configuration | address_width, endianness, architecture, purpose, context, dependencies | Original LLDB fixture; GDB stopped-frame registers, entry snapshots, sparse memory, type/CU/reference metadata and module mappings |
| Expected | upstream_assertions; independent location evidence; scope.json | Original source matcher plus reviewed semantic mapping; separate native address/register witnesses for position identity |

Human/AI review identified semantics, finite loop parameters, helper assumptions and mappings. Scripts authenticated source hashes and anchors, ran reviewed collection recipes, extracted metadata, preserved contexts, invoked K and checked predicates. This was not pure automatic C++/Tcl interpretation. The final artifact intentionally ships the extracted inputs and review evidence, not the historical collection toolchain. Re-extracting a new upstream version requires review and native collection again.

GDB contexts were captured read-only at the original query stops. The inferior remained paused while K requested necessary memory; only needed ranges were stored, normally capped at 1 MiB per snapshot. Independent location observations were bound to the same query, selected frame and unchanged register state. Original missing data remain missing. Entry state is separately captured, not inferred from current registers or from a printed variable value. Current offline replay starts no debugger and follows no absolute historical collection paths.

## What makes a task checkable?

A task is checkable when (1) its requirements are in the research scope; (2) original bytes and the active CU/location/stop are identifiable; (3) required external conditions, including deliberate unknowns, can be represented faithfully; (4) the oracle is independently sourced; and (5) all in-scope semantic requirements can be decided from K's result or stopped configuration.

Checkability does not require K to implement every needed rule or to agree with the expected answer. With complete inputs/oracle, missing support or a different result remains a difference. Interface/observation limitations are disclosed, not declarations that an expression is invalid. Tool errors, timeouts and rewrite-budget exhaustion are distinct from semantic failures.

| K observation | Comparison |
| --- | --- |
| Memory location | Category and address, without an additional object-value requirement |
| Register location | Category and DWARF register number, without an additional register-content requirement |
| Direct value | Required mathematical value / effective bit string and independently required type properties |
| Composite / byte value | Piece by piece where required; contents, extent and exact availability mask; unknown bits are not wildcards |
| Dynamic attribute | Each expression runs in K; Python schedules dependencies and observes layouts; calls do not enlarge root denominator |
| Expected semantic failure | Required position and complete stack, plus independent natural-stop stability evidence; arbitrary incomplete never counts as pass |
| Unavailable | Correct when the source requirement expects unavailability; not automatically an execution failure |

Scalar constructor width/signedness in LLDB's expected value participate in the original matcher promotion rules; they are not automatically strict actual-type equality. Diagnostic wording, Module object existence, formatting and unrelated backtrace assertions are not invented as DWARF semantic predicates. Two LLDB API/diagnostic tasks remain auxiliary.

## Coverage and statistics

An expression is one original bytecode/context root task. Multiple source predicates are conjoined and counted once. Core and auxiliary outcomes are separate. Execution coverage, complete-check coverage and pass / all core expressions have distinct numerators; completion alone is not a pass.

OP coverage is input presence at K-certified decoded boundaries, including nested entry blocks, assuming the expression's OPs are exercised; it is not measured dynamic execution. Main coverage uses roots only. lit0–31, reg0–31 and breg0–31 merge only in the numbered-family metric. Referenced call bodies without separate decoded evidence remain gaps; unused CU metadata do not add OPs. Location coverage uses actual final public result categories. Scalar value-purpose results and no-result states are separate. Context type metadata, final typed values and static object types are separate inventories. Float metadata or register bit transport is not floating computation.

No observed proportion proves complete DWARF correctness or support for every base type. The final artifact retains all original predicates, scope decisions and manual notes needed to interpret the selected experiment.
