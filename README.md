# Executable DWARF expression semantics

K rules for DWARF expressions, a frozen upstream corpus, and offline verification tools. K decodes and executes OPs. Python supplies archived context, schedules attribute expressions and checks independently sourced requirements.

## Start here

| Task | Entry |
| --- | --- |
| Develop the rules | [semantics/](semantics/README.md) |
| Run or inspect frozen tests | [test-corpus/](test-corpus/README.md), verify.py |
| Work on the checker | [verification/](verification/README.md) |
| Run project tests or properties | [tests/](tests/README.md) |
| Read paper results and manual notes | [docs/evaluation/](docs/evaluation/README.md) |
| Read selection/support evidence | [docs/reference/](docs/reference/README.md) |
| Learn or try one expression | [examples/](examples/README.md), run.py |
| Set up and reproduce | [docs/reproduction.md](docs/reproduction.md) |

Requirements: Linux, Python 3.10+, K Framework with its LLVM backend, Java and K's compiler prerequisites. Put K tools on PATH. The recorded experiment uses K v7.1.337. Offline replay needs neither debugger installations nor upstream source checkouts or a live inferior.

```bash
make llvm
python3 verify.py --check-corpus
python3 verify.py --output build/verification
# Optional: one source, or a single expression
python3 verify.py --source lldb --output build/verification-lldb
python3 verify.py --source gdb --output build/verification-gdb
python3 run.py examples/expressions/read.hex --format hex --context examples/expressions/context.json
```

The verifier defaults to build/llvm-kompiled, 120 seconds and 10,000 rewrites per K call, with four concurrent tasks. It never builds automatically, starts debuggers, reuses old evaluations or overwrites a result directory. Options include --corpus, --definition, --timeout, --depth and --jobs. Exit 0 means all checked core requirements pass; 1 means a difference or tool fault (distinguished by the report); 2 means input/argument error; 130 means interruption. --require-complete also rejects uncheckable/not-run core requirements.

The recorded core results are LLDB 22.1.8: 55 expressions, 43 passes and 12 differences; GDB 17.1: 269, 267 passes and 2 differences. Two LLDB diagnostic/API checks are auxiliary. Core uncheckable and tool-error counts are zero. Root-input coverage is 62 standard OP names / 46 numbered families; final results include all seven implemented location categories. These metrics do not establish complete DWARF correctness or dynamic per-OP execution coverage.

## Development checks

```bash
make verification-test  # Python checker tests; no K/debugger invocation
make test               # LLVM semantic regression suite
make test-haskell       # Haskell semantic regression suite
make prove              # Symbolic/concrete specifications in tests/proofs/
```

Semantics supports 164 standard DWARF OP names with documented premises, including four DW_ATE_float formats. Vendor OPs are unsupported. An unmet premise naturally stops; incomplete alone proves neither malformed DWARF nor an expected failure. See the interfaces and limits before interpreting a result.

## Source control and complete evidence

Commit rules, tools, tests, examples, test-corpus/ and docs/. build/ and output/ are ignored: build/ is regenerable; output/ is the locally retained, complete recorded result package. The submission artifact includes output/ explicitly. Frozen bytes, contexts, original expectations and selection evidence are versioned independently of saved K results.

A clone without output/ can build, validate the corpus and run fresh evaluations. Recorded-result integration tests explicitly skip only when the entire optional package is absent; a present but damaged package fails validation. To inspect full recorded configurations or regenerate paper tables, restore the complete output/ package and run:

```bash
python3 -m verification.paper_results --output build/paper-reference
```

The exporter preserves canonical methodology and manual notes from docs/evaluation/; --notes can import another notes table. Existing destinations are refused. This layout migration does not create a new experiment: execution identities and raw receipts retain their original provenance. Selection and semantic mapping involved human/AI review; frozen replay requires no AI.
