# Reproduction and development

## Build and evaluate

Use Linux, Python 3.10+, Java and the K Framework with LLVM/compiler prerequisites on PATH. The recorded experiment uses K v7.1.337. From the repository root:

```bash
make llvm
python3 verify.py --check-corpus
python3 verify.py --output build/verification
make verification-test
```

Options --source lldb|gdb, --corpus, --definition, --timeout, --depth and --jobs select the replay. Defaults are build/llvm-kompiled, 120 seconds and 10,000 rewrites per invocation, four concurrent tasks. A new output directory is required. Known core differences return exit 1; reports distinguish them from tool failures. Compilation is explicit and no debugger runs during replay.

`make test` / `make test-haskell` run project regressions; `make prove` uses tests/proofs/. The independent definitions are build/core-llvm-kompiled and build/core-haskell-kompiled. Build LLVM and Haskell sequentially. Shared generation uses /tmp/locks/kframework.lock; do not nest that lock around commands that already hold it. Temporary data belong under private /tmp/scratch/kframework-* directories. Keep the job limit at or below eight and use bounded library threads.

## Fresh Git clone versus complete result package

The development repository contains rules, checker code, tests, examples, reviewed metadata and frozen inputs. Its root build/ and output/ directories are ignored. The minimal standalone artifact versions its results/ tables and compressed complete K evidence; new builds and caches are ignored. Nothing in a fresh replay reads a prior K result. Frozen evidence is corpus-relative and independent of installed GDB/LLDB sources. Recorded-result tests skip explicitly when output/ is absent; ordinary tests and corpus authentication still run. A partial or corrupt output/ package is an error.

The development-only [output package](../output/README.md) retains original run receipts and supports paper-table export. The submission artifact instead stores complete K configurations and checks in results/evidence.jsonl.gz; it does not ship the developer exporter. To export tables in the development checkout:

```bash
python3 -m verification.paper_results --output build/paper-reference
```

[docs/evaluation](evaluation/README.md) holds six compact reference files, canonical method prose and editable manual notes. The exporter copies/relinks the method and preserves notes; it refuses existing destinations. [docs/reference](reference/README.md) holds final support and selection evidence. Absolute old paths inside immutable original sources/receipts are provenance, never fallback dependencies.

Original extraction required human/AI review and native collection. The shipped workflow replays existing contexts; it is not an automated method for extracting arbitrary new upstream releases. Moving files or resealing packaging metadata is not a new K experiment and does not alter original execution identities.
