# Earlier full-copy artifact validation

This is the retained receipt for the earlier full-copy profile, not the current minimal package. Its test counts and developer targets describe that earlier validation. For current standalone commands and contents, use [artifact/README.md](../../../artifact/README.md).

These receipts describe validation of a relocated publication on 2026-11-12. The development workspace (including old builds) and upstream source directories were hidden by mount-namespace tmpfs mounts. System K, Java and native build tools remained available. Nothing launched a debugger or recollected native inputs.

| Check | Measured result |
| --- | --- |
| Fresh LLVM replay | 326/326 task outcomes match |
| Complete K configurations, including dependencies/stability | 584 invocations match |
| Original verifier / reproduction exit code | 1 / 0 |
| LLVM semantic regressions | 157/157 pass |
| Isolated verification-tool tests | 108 pass |
| Development generator tests | 10 pass |

The raw verifier retains the existing upstream differences. Reproduction success means the same independently checked outcomes and K configurations, not universal upstream agreement. Auxiliary checks remain separate. Counts come from individual records; no expected answer or corpus scope was changed.

- [report.json](report.json): source identities, measured counts, tool versions, isolation, manual-note hashes and actual scope. The packaging identity is separate from original execution identities.
- [comparison.json](comparison.json): every root task and matched K-call count.
- [llvm-regressions.json](llvm-regressions.json), [llvm-test-logs.json](llvm-test-logs.json): every discovered regression, its return code and complete process receipts.
- [commands.json](commands.json) and LLVM build logs: the fresh build and replay invocation.
- Verification/generator logs record defensive tests for drift, missing evidence, local-edit protection, dependencies, locations, expected failures, timeout, interruption and output collisions.

The regression driver is the byte-identical script now maintained as `tests/run_semantics.py`. It runs the unchanged discovered suite in four independent processes; earlier partial sequential diagnostics are not counted. Integrated/core definitions were both freshly built and used identical rule hashes to the final replay. Haskell regressions and symbolic proofs were **not** rerun; proof `requires` targets were checked, and original proof receipts retain their original provenance.

The final publication adds these receipts, documentation and the regression driver. The tested replay code, rule files, original data and manual notes remain unchanged. Absolute paths inside receipts are provenance only; the active commands use files in the standalone repository.

The earlier validation used `python3 reproduce.py --check-only` and development test targets. Those are historical commands, not interfaces of the current minimal package. Current standalone use is `make`, followed by `python3 validate.py --output build/reproduction`; see [artifact/README.md](../../../artifact/README.md). Development regression commands remain in [tests/README.md](../../../tests/README.md). No receipt path is a runtime dependency of the verifier.
