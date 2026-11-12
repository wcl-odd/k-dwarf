# Offline verification tools

The project verifier is `python3 verify.py --output build/verification`. It reads the frozen test-corpus/ and a compiled K definition; it does not launch GDB/LLDB or use a historical collection directory.

| Modules | Responsibility |
| --- | --- |
| cli, acceptance, backends/k | CLI, task orchestration and K subprocess protocol |
| dependencies | Attribute/reference scheduling; every expression executes in K |
| assertions, objects, locations | Original predicates, object observations and independent location identities |
| corpus, corpus_archive, selection | Input, inventory, source and reviewed-selection authentication |
| scope, metrics | Core/auxiliary classification and expression counts |
| common, model, context, input, process | Shared identities, transport, context validation and process cleanup |
| paper_coverage, paper_results | Saved-result coverage and paper-table export without evaluation |

Tests are in [tests/verification/](../tests/verification/). Run `make verification-test`; final-result integration checks require the optional local output/ package, while ordinary checker tests do not. Frozen input construction involved human/AI review, recorded in [the method](../docs/evaluation/methodology.md) and [selection evidence](../docs/reference/README.md). This package is not a retained native recollection or three-backend comparison pipeline.
