# Extracted upstream test corpus

This directory contains test data, not collection or evaluator scripts. It can be copied to another location and replayed offline with the project runner and a compiled K definition. The original debugger installations, source checkouts and collection directory are not needed. No saved K results or debugger binaries are included.

| Source | Core expressions | Auxiliary checks | Archived tasks |
|---|---:|---:|---:|
| LLDB 22.1.8 | 55 | 2 | 57 |
| GDB 17.1 | 269 | 0 | 269 |

The 324 core expressions retain the current frozen selection, original predicates and comparison policy. Attribute dependencies are included within their root cases; they do not enlarge the denominator. The two LLDB diagnostic/API checks remain auxiliary. Export is repackaging, not a new experiment.

## Data layout and the three validation inputs

- `cases.json`: `bytes` is the original expression bytecode. `context` contains the fixed configuration (including registers, sparse memory, type metadata and runtime metadata); address width, endianness and `purpose` are separate case fields. An omitted context preserves the original missing-context fixture.
- `upstream_assertions` in each case: original source requirements, source anchors, expected predicates and reviewed mappings. The legacy `expected` field is retained; it is not necessarily the active upstream oracle.
- `scope.json`: stable task IDs, core/auxiliary membership, observation policy and reviewed auxiliary facets. Memory locations compare address/category; register locations compare DWARF register identity/category. Value and composite cases retain the reviewed semantic predicates.
- `sources/`: archived upstream assertion sources and fixture/harness dependencies. `evidence/`: original snapshots, independent native location observations, frozen selection and original preparation records. These files retain their original bytes.
- `preparation.json`: each dataset's hashes and explicit `corpus-relative-v1` path profile. `manifest.json`: the complete portable inventory, source identities and old-to-new evidence mappings.

Paths used by the checker resolve relative to the corresponding dataset directory. Absolute paths remaining inside original snapshots or provenance describe the historical collection and are not followed during offline checking. The original collection method and reviewed decisions are documented in [the methodology](../docs/evaluation/methodology.md); the final `verification/` contains only offline code.

## Offline replay

Run from the project root:

```bash
make llvm
python3 verify.py --output build/verification
python3 verify.py --source lldb --output build/verification-lldb
python3 verify.py --source gdb --output build/verification-gdb
python3 verify.py --check-corpus
```

Use `--corpus PATH` for a relocated corpus and `--definition PATH` for a compatible compiled K definition. Each run requires a new output directory and starts no debugger. The default is 120 seconds, 10,000 rewrites per K invocation and four concurrent tasks. A semantic difference produces exit 1, distinct in the reports from tool errors. Auxiliary checks do not enter the core denominator.

The final package retains original bytes, contexts, expectations, source evidence and selection identities. Only this guide and its enclosing inventory were updated during artifact packaging; the old inventory identity is recorded as provenance in the manifest. Absolute paths in provenance are never offline dependencies. Native recollection automation and historical exporters are intentionally not shipped.
