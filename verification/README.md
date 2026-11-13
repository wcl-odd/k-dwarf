# Offline verification tools

The project verifier is `python3 verify.py --output build/verification`. It reads the frozen test-corpus/ and a compiled K definition; it does not launch GDB/LLDB or use a historical collection directory.

| Modules | Responsibility |
| --- | --- |
| cli, acceptance, backends/k | CLI, task orchestration and K subprocess protocol |
| dependencies | Attribute/reference scheduling; every expression executes in K |
| assertions, objects, locations | Original predicates, object observations and independent location identities |
| corpus, corpus_archive | Input structure, task membership, source anchors and local evidence paths |
| corpus_integrity, selection | Development-only inventory and reviewed-selection integrity checks |
| reproduction | Run a fresh artifact experiment and report completion separately from assertion outcomes |
| baseline | Development-only saved-evidence reading and compact-result statistics |
| scope, metrics | Core/auxiliary classification and expression counts |
| common, model, context, input, process | Project paths, local locks, transport, context validation and process cleanup |
| paper_coverage, paper_results | Saved-result coverage and paper-table export without evaluation |

Tests are in [tests/verification/](../tests/verification/). Run `make verification-test`; final-result integration checks require the optional local output/ package, while ordinary checker tests do not. Frozen input construction involved human/AI review, recorded in [the method](../docs/evaluation/methodology.md) and [selection evidence](../docs/reference/README.md). This package is not a retained native recollection or three-backend comparison pipeline.

Replay treats archived hash fields as provenance; it checks actual source anchors, expression/context values and semantic evidence. Development exporters use the separate strict inventory checks. In the standalone paper project, `make` compiles and `reproduce.py` runs fresh checks against original expectations without reading saved results; neither invokes the other.
