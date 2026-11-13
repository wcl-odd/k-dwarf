# Executable DWARF expression semantics

This companion project contains the paper's K semantics, expression cases, an offline validation runner and recorded results. Copy it anywhere: no parent checkout, debugger, upstream installation or AI service is needed.

| Path | Contents |
| --- | --- |
| `semantics/` | K domains, bytecode decoding and expression evaluation |
| `test-corpus/lldb.json`, `test-corpus/gdb.json` | Expressions, interfaces and requirements; source anchors are documentation only |
| [`scripts/`](scripts/README.md) | Seven internal modules for input, K invocation, dependencies, observations and reporting |
| `results/` | Recorded results and complete compressed K outcomes; never read by the runner |
| `Makefile` | Compilation only |
| `validate.py` | Validate expression cases using an existing compiled definition |

## Installation

Use Linux x86-64, Python 3.10+ and **K v7.1.337** with its LLVM backend. Python uses only its standard library. Put `kompile`, `kparse` and `krun` on `PATH`. The validated toolchain uses Java 21 and LLVM/Clang 15.0.7; use the compiler and libraries required by your K distribution, independently of any debugger installation.

Follow the [K release](https://github.com/runtimeverification/k/releases/tag/v7.1.337) and [installation guide](https://kframework.org/docs/getting-started/). Typical Ubuntu build prerequisites are:

```bash
sudo apt-get install build-essential make cmake pkg-config util-linux \
  clang-15 llvm-15-dev lld-15 libgmp-dev libmpfr-dev libboost-dev \
  libffi-dev libfmt-dev libjemalloc-dev libunwind-dev libz3-dev zlib1g-dev
```

Install Java 21 and K separately following their distribution instructions. No local dependency wrappers are included.

## Run the experiment

```bash
make
python3 validate.py --output build/experiment
python3 validate.py --source lldb --jobs 4 --output build/lldb
python3 validate.py --definition /path/to/llvm-kompiled --jobs 16 --output build/parallel
```

`make` only compiles. Python never compiles, starts a debugger or compares against saved results. It checks the requirements in the selected source file(s) and refuses an existing output directory. Removing `results/` does not affect execution.

Defaults: 120 seconds and 10,000 rewrites per K invocation, four concurrent cases, and `build/llvm-kompiled`. `--jobs` accepts 1 through 16. Dependency calls within each case are sequential. Parser/library threads are bounded; memory monitoring reduces concurrency or stops owned processes before its safety limits are exceeded. The resource guard reduces concurrency at 24 GiB aggregate process RSS and stops owned processes at 32 GiB or when host available memory falls below 16 GiB. Temporary inputs and locks stay under this project's `build/` directory.

Exit **0** means completed without execution faults; **1** means a tool failure, timeout, exhausted rewrite budget or required task not run; **2** means invalid input/environment; **130** means interruption. Semantic inconsistency is reported independently. A stuck evaluation can be consistent with a requirement for abnormal termination; a timeout or exhausted budget cannot establish that expectation.

## Expression cases

An expression case follows Section 4 of the paper:

- **expression**: original hexadecimal bytecode, evaluation purpose and separately evaluated attribute dependencies;
- **interface**: the fixed external inputs read during evaluation, including address width, byte order, optional architecture, registers, sparse memory, type metadata, frame base and function-entry state;
- **requirement** (`requirements`): predicates on the K outcome, plus object layout or observation inputs when necessary.

`id` and `tool` identify cases. `group` distinguishes the 324 core expression cases from the two LLDB auxiliary checks, which are excluded from the core denominator; it is reporting metadata, never an input to K. `--source lldb` reads only `lldb.json`, `--source gdb` reads only `gdb.json`, and the default reads both. `source` records the upstream file, test name and original assertion; the runner discards it and never opens source paths. The simplified corpus has no version records, file inventory or SHA-256 fields. The optional parser cache stores only K-generated KORE inputs under `build/llvm-kompiled/input-parse-cache`; every invocation still evaluates the expression and checks its requirements. It does not cache evaluation results or authenticate the corpus. Set `DWARF_K_PARSE_CACHE=off` to repeat parsing, or remove the cache directory to regenerate it.

```json
{
  "id": "lldb-001", "tool": "lldb", "group": "core",
  "source": {"file": "DWARFExpressionTest.cpp", "test": "DW_OP_pick"},
  "expression": {"bytecode": "31 30 15 00", "purpose": "location"},
  "interface": {"address_width": 32, "endianness": "little", "state": null},
  "requirements": {"layout": {"byte_size": 4},
    "observation": "source-semantic-requirements",
    "predicates": [{"target": "stack_top", "expected": {"bits": "0"},
      "mapping": "Original stack-top requirement."}]}
}
```

The paper's interface `I` is represented by the K `Context`/`ctx` domain; the evaluation state uses `<pc>` and `<stack>`. These implementation names retain their existing syntax and KAST representation.

K alone decodes and evaluates DWARF operations. Python validates the interface, serializes it as KAST, schedules dependency expressions, observes K outcomes and checks requirements. Memory observations read only the fixed interface; they do not collect additional data. Expected results are never inferred from K or the expression. Mapping explanations document the reviewed requirement; they do not execute source assertions. Missing interface entries stay unknown; empty bytecode denotes a genuine empty expression.

## Sources, selection and comparison

LLDB 22.1.8 cases come from `lldb/unittests/Expression/DWARFExpressionTest.cpp`: expressions and mock interfaces were reconstructed from reviewed fixtures. GDB 17.1 cases come from `gdb/testsuite/gdb.dwarf2`: regression scripts construct DWARF and exercise its interpretation. The external inputs read at native Linux x86-64 breakpoints were recorded as each case's fixed interface. Validation needs neither debugger.

Selection keeps standard expression evaluation, locations, object pieces and dynamic attributes. Vendor operations, including required dependencies containing them, are excluded. Formatting, unrelated C computations, debugger API/robustness checks and requirements that the interface cannot faithfully express are outside the core scope. Missing K rules or an inconsistent result alone are not exclusion reasons.

A case is **consistent** only when all in-scope requirements hold; otherwise it is **inconsistent** when the outcome can be decided. Memory locations compare category/address; register locations compare category/DWARF number. The stack top must match the expected bit pattern and type. A standalone value location result is compared on its common bits with the expected value; this rule does not apply to value pieces in a composite. Composites are checked piece by piece, including the exact set of available bits: unknown bits are not wildcards. A requirement for abnormal termination checks the reviewed position, complete stack and a stable invocation with a larger step limit whose rewrite count is below that limit. This establishes a stuck state rather than exhaustion of the limit.

There are 324 core cases and two LLDB auxiliary checks. Auxiliary cases concern API/diagnostic requirements outside the K interface and are reported separately. Attribute calls do not increase the core denominator. Inputs cover 62 standard operation names, or 46 families after merging numbered forms; final outcomes exhibit seven location-description categories. This is input-presence and result-observation coverage, not a dynamic operation trace. No floating arithmetic execution is confirmed here; float metadata and raw register transport do not demonstrate floating computation.

## Result files

A fresh run creates the directory passed to `--output` and refuses an existing destination:

```text
<output>/
├── report.md          Result tables, settings, completion and fault details
├── expressions.csv    One verdict per case
├── checks.csv         One row per requirement
└── <case-id>/         Inputs, checks, commands and complete K outcomes
```

Each case directory also retains any attribute dependencies and stopped-state stability probe. This working output differs from the compact recorded `results/` package: the runner does not generate `differences.csv`, compress evidence into `evidence.jsonl.gz`, or copy reviewed manual remarks. Those annotations and the recorded coverage statistics belong to the published reference results. The report contains completed/expected task counts, missing tasks, interruption status, exit code and execution-fault details. Statistics remain in memory; no separate summary file is written.

The four files under [`results/`](results/report.md) record the completed experiment; both CSV tables retain the English manual remarks. Fresh runs never read them. Counts are calculated from individual cases. Conclusions are limited to these tests, not complete DWARF correctness.

## Human and AI participation

Selection, fixture reconstruction and mapping assertions to requirements involved human/AI review. Development scripts validated and converted those decisions into the case file. For this experiment, AI simplified the representation and runner, reviewed observation dependencies, restored omitted interface-identity helpers, enabled rewrite counters for stopped-state evidence and reviewed terminology. Scripts invoked K, evaluated dependencies, checked predicates and counted verdicts. Original expected answers were retained; AI did not generate expected results during validation. Repeating the experiment requires no AI service.

All prose, comments and public terminology in this project are English. Upstream notices are retained; no project-wide license is assigned. Development-side tooling maintains real copies of K and runtime files but is not required here.
