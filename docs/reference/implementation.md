# Final scope and supporting evidence

<a id="support"></a>
## Supported standard operations

The current semantics supports 164 DWARF 2–5 standard OP names, with documented preconditions. Vendor extensions are unsupported and excluded from the core corpus, including required dependencies. The full list and rule locations are in support/ops.csv. Generic constants in DWARF 5 2.5.1.1 are truncated to address width; explicitly typed stack values may be wider. Failed preconditions stop naturally; incomplete does not by itself establish invalid DWARF.

<a id="floating"></a>
## Floating-point operations

DW_ATE_float binary32, binary64, x87 binary80 and binary128 are implemented. Encoding plus numerical representation defines a format; padding and DIE identity do not multiply formats. Supported arithmetic: abs, neg, plus, minus, mul, div. Supported comparisons: eq, ne, lt, le, gt, ge. Convert and reinterpret have the documented supported-encoding, width and representability conditions. Full per-name supported, unsupported and nonapplicable classifications are in support/floating-ops.json. Integer-only operators are nonapplicable to floating inputs, rather than missing floating features. No complex/imaginary/decimal-floating arithmetic is claimed. See ../../semantics/README.md for types, rounding and conversion bounds.

Generic-to-integer and generic-to-float conversion interprets the generic source as unsigned at address width. Boolean conversion uses the existing canonical-representation policy; it does not implement arbitrary noncanonical Boolean normalization. Stack and result type identities remain distinct from original object type and LLDB Scalar storage bookkeeping.

## Context and observation boundaries

Registers, sparse memory, types, frame base, CFA, object address, indexed addresses, calls, entry snapshots, TLS and address-space maps are supplied as fixed external inputs. Python schedules attribute expressions and reads already located objects; K decodes and executes every OP. No general CFI/unwinding or target-language evaluator is supplied. Register positions compare identity, memory positions compare address. Composite values retain unavailable bits. One GDB type query has no independent expression; two LLDB API/diagnostic checks are auxiliary. Final differences and manual notes are in ../evaluation/limitations.md.
