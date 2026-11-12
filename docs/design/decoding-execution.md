# Decode frontend and independent execution core

The execution entry follows the paper's fixed decoded expression E and read-only interface I. The split is structural: arithmetic, natural stopping, pieces and public results retain their existing definitions.

| Module | Responsibility |
| --- | --- |
| semantics/frontend/ | Parse text or hex; decode fixed/LEB operands; normalize and prepare valid prefixes and nested code |
| semantics/execution/expression.k | Decoded instructions, expression boundaries and pure code queries |
| semantics/execution/core.k | Fixed decoded expression/context, stack, location results and rewriting |
| semantics/dwarf.k | Integrated preparation and execution entry |

A decoded expression stores start/end positions, ordered `codeAt(position, operation, next, rest)` records and original-byte evidence. Execution does not decode that evidence again. The frontend accepts only encoding parameters (address width, endianness, reference width); register, memory and type contents are queried by execution. Referenced DIE bodies are prepared with their owning CU's parameters. References remain references, allowing recursive calls within the rewrite budget.

Unknown or truncated encoding preserves the valid prefix, failing position and original END. No executable decode-error operation is invented. `run.py` reports the finish reason together with the complete stopped configuration. An incomplete result alone does not prove invalid DWARF or satisfy an expected failure. Text structural errors remain input errors.

Use `make llvm` / `make haskell` for integrated definitions and `make core-llvm` / `make core-haskell` for independent definitions. `evaluate_decoded` in run.py transports K algebra or structured KAST plus a prepared context; it does not execute DWARF in Python. Source spelling and stable KAST symbols are distinguished in [the naming audit](../../semantics/paper-naming-audit.md).

Regression and property evidence are in [output/validation](../../output/validation/README.md). Core/integrated configurations are compared after preparation; an unexpanded zero-budget frontend is not mistaken for a mutated core input. No mechanical frontend refinement theorem is claimed.
