# Tests and proof specifications

| Directory | Contents | Command |
| --- | --- | --- |
| semantics/ | Project regression tests for actual K execution | make test / make test-haskell |
| verification/ | Offline Python checker, dependency, integrity and report tests | make verification-test |
| proofs/ | K symbolic/concrete reachability specifications | make prove |

Project tests and proof claims are distinct from the 324 frozen upstream expression tasks. Semantic regression covers decoding, arithmetic boundaries, type identity, conversion, floating representations, control flow, locations, pieces and nested runtime mechanisms. Claim premises and configurations remain in the .k files. Examples are in [examples/expressions/](../examples/expressions/).

The semantic targets compile integrated and independent-core definitions if needed. LLVM/Haskell builds are serialized with the workspace lock. Run test modules directly with `python3 -m unittest discover -s tests/semantics -v` or `python3 -m unittest discover -s tests/verification -v` after arranging the required definition/environment.

Checker tests need no K evaluator or debugger. Recorded-result integration tests skip only if the complete optional output/ directory is absent. If output/ exists but its manifest or required evidence is missing/changed, they fail. Retained full regression and proof receipts are included in the local/submission output/ package; directory reorganization does not rerun or change those proofs.

For a four-worker LLVM regression run on definitions already built, use `python3 tests/run_semantics.py --definition build/llvm-kompiled --core-definition build/core-llvm-kompiled --output build/llvm-regressions`. This runs each unchanged test in a separate process, bounds CPU affinity and frontend threads, saves per-test logs, and refuses an existing destination. The integrated and core definitions must be siblings for tests that compare both interfaces. `make test` remains the sequential entry.
