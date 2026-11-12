# Examples

- [expressions/](expressions/): text/hex expressions and matching JSON contexts for run.py.
- [tutorial/](tutorial/README.md): separate introductory K rules, programs and a simple proof.

From the workspace root:

```bash
make llvm
python3 run.py examples/expressions/read.dwarf --context examples/expressions/context.json
python3 run.py examples/expressions/read.hex --format hex --context examples/expressions/context.json
```

Examples and tutorial programs are project material, not additional frozen upstream coverage.
