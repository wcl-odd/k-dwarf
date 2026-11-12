<a id="正式语义栈求值与位置描述"></a>
# Executable Semantics: Stack Evaluation and Location Descriptions

This directory implements **164 standard DWARF 2–5 operation names** in K. The count expands the `lit0..31`, `reg0..31`, and `breg0..31` families. Vendor-extension operations are not supported. Name coverage does not imply support for every type, operand, ABI, or context combination.

Start with [core.k](execution/core.k) for execution rules and [expression.k](execution/expression.k) for decoded inputs. The [paper naming audit](paper-naming-audit.md) relates the implementation to the current paper, including differences that are not merely names. [README-CN.md](README-CN.md) is a byte-for-byte copy of the Chinese README before this English documentation revision; its historical statements are not an updated specification.

The reference is the [official DWARF 5 specification](https://dwarfstd.org/doc/DWARF5.pdf). The rules distinguish specification requirements from explicit modeling choices. The default compiled definitions are under `build/`; existing builds, frozen inputs, and experimental results remain historical artifacts with their original identities. This documentation revision does not rebuild or rerun them.

<a id="编译和运行"></a>
## Build and Run

Run commands from the project root:

```bash
make llvm
python3 run.py examples/expressions/read.dwarf --context examples/expressions/context.json
python3 run.py examples/expressions/read.hex --format hex --context examples/expressions/context.json
make haskell
python3 run.py examples/expressions/read.dwarf --context examples/expressions/context.json --definition build/haskell-kompiled
```

With the supplied snapshot, `0: DW_OP_bregx 1 -8, 3: DW_OP_deref_size 4, 5: DW_OP_dup, 6` produces stack `[42:g, 42:g]` and location `memory(42)`. Append a final `DW_OP_stack_value` to describe the value 42 rather than storage at address 42.

The CLI outputs JSON with `status`, `position`, `end`, `stack` (bottom to top), `result`, `stop_reason`, and the complete final KAST `configuration`. A completed evaluation has an explicit result for the selected purpose; incomplete evaluations have `result: null`. Examples of public results are:

```json
{"kind":"register","register":0}
{"kind":"memory","address":42}
{"kind":"value","value":42,"type":"g"}
{"kind":"value","value":-2,"type":{"id":"cu0:s16"}}
{"kind":"scalar","value":42,"type":"g"}
{"kind":"unavailable"}
```

`stack` entries expose values and type identities, not expanded type attributes. Generic uses `"g"`; a base type uses `{"id":...}`, so a base type named `g` remains distinct. Width, encoding, and storage size remain in the supplied context and full configuration.

Exit codes are **0** for completion, **1** for incomplete evaluation, and **2** for input-representation or tool-invocation errors. `incomplete` alone does not establish invalid DWARF: missing data, insufficient stack, unmet numeric/type preconditions, and insufficient budget can all cause it. Current rules stop naturally when no rewrite applies; there is no error-state transition. `stop_reason` is retained as a compatibility field and is null for current definitions.

For incomplete byte inputs, an optional `decode_error` object reports when the active position is exactly the end of K's saved decoded prefix, before the original END. It includes `position`, the original `opcode_byte`, `remaining_byte_count`, and reason `no_complete_instruction`. Python observes K's decoded records and retained bytes; it does not implement another DWARF decoder. The current evidence does not distinguish a truncated operand from an unknown/unsupported opcode or unsupported decoding parameters. A valid current instruction, an unreached bad suffix, normal completion, or missing byte evidence does not produce this field. Nested calls/entry blocks use the active child's expression and position. This diagnostic changes no K configuration, result, rewrite budget, or exit code, and does not declare an expression invalid or an expected-error assertion satisfied.

`--depth N` bounds K rewrites, not the number of encoded DWARF operations. Ordinary successful stack operations update the position and stack in one rewrite; pure decoding, validation, and code lookup are not execution steps. A separate `Memory` or `Scalar` rewrite interprets a final stack, whereas a final `StackValue`, standalone `Register`, or `Empty` completes in its own rewrite. Calls and returns also consume rewrites. Two constant operations followed by ordinary memory completion therefore need three rewrites. A two-operation `lit1; stack_value` needs two.

At zero budget, Haskell may retain `initGeneratedTopCell`; the runner reports the initial stack and placeholder `position=end=0` because K has not expanded initialization. LLVM may already expand the initial cells. The runner neither adds budget nor computes expression length in Python. To distinguish natural stopping from budget exhaustion, compare full configurations under a larger budget; record timeouts and tool failures separately. The runner does not compile automatically.

<a id="输入与解码"></a>
## Input and Decoding

The default `--format text` uses complete operation names, declared offsets, commas, and a final standalone END offset:

```text
0x0: DW_OP_consts -0x1,
0x2: DW_OP_stack_value,
0x3
```

The final number has no operation or `end:` label. Numeric literals accept decimal, `0x`/`0X` hexadecimal, and a leading minus sign. These are mathematical integers, not implicit two's-complement encodings: `-0x1` is -1, whereas `0xff` is 255 and does not fit a `const1s` source operand.

Declared offsets must strictly increase; `0x10` and `16` denote the same position. Text does not validate actual encoding lengths, require nonnegative offsets, or require a zero start for nonempty inputs. An empty text expression consists only of zero (`0` or `0x0`); a whitespace-only text file is invalid. This generality is an input-interface feature, not the paper's bytecode syntax.

`--format hex` accepts whitespace-separated two-digit bytes such as `11 7f 9f` or `0X11 0x7F 0x9f`. Each token must have exactly two hexadecimal digits; `117f` is not split. Negative numbers and commas are invalid. An empty hex file denotes an empty expression, with start and END both zero. Nonempty byte inputs start at zero and end at their byte count.

Python calls K's parsing modules and passes their KORE output to evaluation. It does not decode operation bytes, LEB128 operands, or numeric text literals. The Python `evaluate(..., input_format="text"|"hex")` interface follows the same path. JSON context numbers follow JSON syntax separately.

Fixed-size operands use the context's byte order. `DW_OP_addr` requires an address width divisible by eight and consumes `A/8` bytes. ULEB128/SLEB128 group order is independent of byte order. Complete nonminimal encodings and arbitrary-length operands are accepted as mathematical integers. Truncated operands, missing LEB termination, and unknown or unsupported opcodes leave evaluation at the operation start after any executable prefix; no suffix bytes are guessed as operations.

Lexical/syntax errors, duplicate or decreasing offsets, nonzero empty text END, and invalid hex token widths are input errors (exit 2). A Haskell zero-budget run may not yet evaluate those structural checks. Unmet operation preconditions remain incomplete evaluations (exit 1). Source operand ranges are checked separately from target-width truncation.

<a id="组织与复用"></a>
## Modules and Reuse

The source tree separates shared domains, pure input preparation, and execution:

```text
semantics/
├── dwarf.k                    # Integrated text/hex entry
├── domains/
│   └── dwarf-domains.k         # Contexts, types, values, stacks, locations
├── frontend/
│   ├── syntax.k               # External text and hex grammars
│   ├── normalization.k        # Shared operation forms and source checks
│   ├── decoding.k             # Byte and operand decoding
│   └── frontend.k             # Pure expression/context preparation
└── execution/
    ├── expression.k           # Decoded input and code queries
    ├── computations.k         # Type-directed numeric functions
    ├── floating.k             # Floating-point formats and calculations
    ├── composition.k          # Fragment queries and consumer assembly
    ├── runtime.k              # Read-only nested-context queries
    └── core.k                 # Configuration and direct execution rules
```

`dwarf.k` remains the integrated build entry; `execution/core.k` is the independent core entry. Directory organization does not alter module names or serialized constructors. `make` tracks root and nested K sources, and result generators collect them recursively.

The unused `failures.k` compatibility module has been removed: no active module or test imported it, and it contained no execution rules. Failed preconditions still stop naturally in the core. Its original source and the old-to-new path map are retained in the layout revision archive (final evidence: ../output/validation/README.md). Historical source identities and the exact Chinese README backup retain their original paths; use the table below for current locations.

| File | Responsibility |
| --- | --- |
| [syntax.k](frontend/syntax.k) | Separate annotated-text and hex grammars; 164 standard names |
| [decoding.k](frontend/decoding.k) | Fixed-size and LEB operands, opcode dispatch, and complete-operation boundaries |
| [normalization.k](frontend/normalization.k) | Numeric text conversion, source-range checks, and shared internal operations |
| [frontend.k](frontend/frontend.k) | Structural validation and pure preparation of root, entry, and supplied DIE expressions |
| [expression.k](execution/expression.k) | Decoded operations and context-independent code queries |
| [dwarf-domains.k](domains/dwarf-domains.k) | Types, values, stacks, locations, contexts, and basic read queries |
| [computations.k](execution/computations.k) | Finite-width integer calculations, type-directed dispatch, and conversions |
| [floating.k](execution/floating.k) | Exact floating-point decoding, arithmetic, rounding, and comparison |
| [runtime.k](execution/runtime.k) | Read-only DIE, CU, and nested-evaluation metadata queries |
| [composition.k](execution/composition.k) | Fragment boundaries, source-bit extraction, and data/known-mask assembly |
| [core.k](execution/core.k) | Configuration and direct execution/result rewrites over decoded inputs |
| [dwarf.k](dwarf.k) | Integrated text/hex entry into the same execution core |

`decoded(START,END,CODE,EVIDENCE)` is fixed input, not a mutable code-table cell. `instructionAt(E,P)` returns `instruction(OP,NEXT)` or `noInstruction`; `opAt(E,P)`, `next(E,P)`, and `isBoundary(E,P)` do not take a context. There is no default NEXT on a failed lookup. Original bytes are inert provenance; execution queries decoded records rather than decoding bytes again. Text operands outside their source range become `unavailableOperation`, not a structural input error.

The context pattern `ctx(...) #as C` exposes selected fields while retaining the complete read-only context as C. Optional queries use `someInt/noInt`, `someType/noType`, or `someValue/noValue`; successful extraction must be established before using `getInt`, `getType`, or `getValue`. Unknown data do not acquire default zeros. `Pick` and `DerefType` share typed-value query helpers; ordinary reads and register lookup share integer query helpers.

The stack is `.Stack` or `push(S,val(N,T))`; the outermost value is the top. For example, `push(push(.Stack,val(1,g)),val(2,g))` denotes `[1:g,2:g]`. Algebraic prefixes support symbolic preservation properties; this is the expression operand stack, not the target program's stack.

The control term is in `<expr>`, with independent `<pc>`, `<stack>`, and `<fragments>` cells. Completed evaluation replaces `evaluate(E,C,END,PURPOSE)` with `finished(E,C,END,R,PURPOSE)` and sets `pc=END`, retaining the stack in its cell. Nested evaluation uses additional K sequence items to save return information. See the [layering design](../docs/design/decoding-execution.md) and [naming audit](paper-naming-audit.md).

<a id="论文规则对应与支持范围"></a>
## Rule Families and Supported Operations

This table inventories implementation families; it does not imply the paper displays all of them or uses identical labels. The audit provides the actual paper-to-code correspondence.

| Implementation family | Internal operation | Standard names | Count |
| --- | --- | --- | ---: |
| Const | `constOp(n)` | `lit0..31`, `const{1,2,4,8}{u,s}`, `constu`, `consts`, `addr` | 43 |
| AddrIndex / ConstIndex | `addrxOp(i)` / `constxOp(i)` | `addrx`, `constx` | 2 |
| ObjectAddress | `pushObjectAddressOp` | `push_object_address` | 1 |
| Breg | `bregxOp(r,d)` | `breg0..31`, `bregx` | 33 |
| Fbreg | `fbregOp(d)` | `fbreg` | 1 |
| Deref / DerefType | `derefOp(s)` / `derefTypeOp(s,t)` | `deref`, `deref_size`, `deref_type` | 3 |
| Pick | `pickOp(k)` | `dup`, `over`, `pick` | 3 |
| Drop / Swap / Rot | `dropOp`, `swapOp`, `rotOp` | `drop`, `swap`, `rot` | 3 |
| Unary | `unaryOp(u)` | `abs`, `neg`, `not`, `plus_uconst` | 4 |
| Binary | `binaryOp(b)` | `and`, `div`, `minus`, `mod`, `mul`, `or`, `plus`, `shl`, `shr`, `shra`, `xor` | 11 |
| Compare | `compareOp(c)` | `eq`, `ge`, `gt`, `le`, `lt`, `ne` | 6 |
| Convert / Reinterpret | `convertOp(t)` / `reinterpretOp(t)` | `convert`, `reinterpret` | 2 |
| CallFrameCFA | `callFrameCfaOp` | `call_frame_cfa` | 1 |
| Nop | `nopOp` | `nop` | 1 |
| Skip / BraTrue / BraFalse | `skipOp(d)` / `braOp(d)` | `skip`, `bra` | 2 |
| Register | `regxOp(r)` | `reg0..31`, `regx` | 33 |
| StackValue | `stackValueOp` | `stack_value` | 1 |
| ImplicitValue | `implicitValueOp(B)` | `implicit_value` | 1 |
| Piece rules | `pieceOp(n)` / `bitPieceOp(n,k)` | `piece`, `bit_piece` | 2 |
| TypedConstant / TypedRegister | `constTypeOp(t,B)` / `regvalTypeOp(r,t)` | `const_type`, `regval_type` | 2 |
| Call | `callUnitOp(r)` / `callRefOp(r)` | `call2`, `call4`, `call_ref` | 3 |
| Entry | `entryValueOp(B)` | `entry_value` | 1 |
| TLS | `formTlsAddressOp` | `form_tls_address` | 1 |
| XDeref / XDerefType | `xderefOp(s)` / `xderefTypeOp(s,t)` | `xderef`, `xderef_size`, `xderef_type` | 3 |
| ImplicitPointer | `implicitPointerOp(r,d)` | `implicit_pointer` | 1 |

All external names have the `DW_OP_` prefix. `Empty`, `Memory`, and `Scalar` interpret outcomes and add no opcode names. The total is 164.

<a id="整数类型转换"></a>
## Integer Type Conversion

`DW_OP_convert t` (`0xa8`) and `DW_OP_reinterpret t` (`0xa9`) take nonnegative ULEB128 CU-relative references. Reference 0 resolves to generic without looking up a table entry. Other references retain the complete resolved type identity.

`convert` interprets signed/signed_char sources as signed; other supported non-Boolean integral sources are unsigned. Generic sources use their unsigned low A bits, even if the stored representative is negative. This source view applies to both integer and floating-point targets. Integer conversion retains target-width low bits and selects the target encoding's representative; the earlier project restriction against integer overflow is no longer used. Generic targets use nonnegative representatives. For example:

- signed8 -1 converts to signed16 -1 or unsigned16 65535;
- generic 255 converts to signed8 -1, and 256 to unsigned8 0;
- at A=8, both 255:g and -1:g convert to signed16/unsigned16 255;
- at A=32, `const1s -1` followed by conversion to signed64 yields 4294967295; conversion to floating point also uses that positive source value.

DWARF specifies conversion's stack effect and target selection without fully specifying its numerical behavior. The unsigned generic source interpretation is a documented consumer choice, not grounds for rejecting every other consumer's choice as invalid DWARF.

`reinterpret` requires equal effective bit widths, not equal storage sizes. It preserves the bit pattern and target identity. Base-type targets select representatives by encoding; generic targets keep the original integer representative, including negatives. Thus signed8 -1 reinterpreted as unsigned8 becomes 255, whereas signed64 -1 reinterpreted as generic retains -1. It reads no memory and adds no bits.

Boolean conversion is undefined for either a Boolean source or target. It has no applicable transition, rather than silently normalizing or truncating Boolean values. Boolean reads, integral bit-pattern operations, and same-width reinterpretation remain supported. Missing types, empty stacks, unequal reinterpretation widths, and failed conversion preconditions preserve the complete pre-operation state.

Examples: [conversion.dwarf](../examples/expressions/conversion.dwarf), [conversion.hex](../examples/expressions/conversion.hex), and [conversion-context.json](../examples/expressions/conversion-context.json), which produce direct value 127 with type identity `s16`.

<a id="有限位宽计算"></a>
## Finite-Width Computation

`width(T,A)` is A for generic and the declared effective width W for a base type, regardless of storage size. `bits(N,W)` retains the low W bits in `[0,2^W)`; `signedBits` interprets the same bits in `[-2^(W-1),2^(W-1))`. Base-type results follow their encoding, without Boolean normalization. Binary computations require identical complete operand types, including identity; equal attributes do not merge distinct identities. N1 is the top, so subtraction, division, and comparisons compute `N2 OP N1`.

`Const`, `Breg`, and `Fbreg` produce nonnegative A-bit generic patterns. Constant source-range checks precede this truncation: at A=64, `const1s -1` produces `2^64-1:g`; at A=8, `const2u 256` produces `0:g`, but `const1u 256` is outside its source range. `constu` permits any nonnegative mathematical integer; `consts` and register/frame-base offsets permit arbitrary mathematical integers. `addr` itself requires an unsigned A-bit source address.

`abs`, `neg`, and `div` use a signed input view even for unsigned base types. Their generic results use signed representatives; base-type results still follow their encoding. `abs`/`neg` of the minimum signed value have no normal result. `div` requires a nonzero divisor and excludes signed MIN/-1 quotient overflow. `/Int` truncates toward zero. Signed `mod` uses `%Int`, not nonnegative `modInt`; unsigned/generic `mod` uses an unsigned view. Both require a nonzero divisor, but signed MIN % -1 remains defined as zero.

Shift counts follow base-type encoding or generic unsigned interpretation and require `0 <= count < W`. `shl` discards high bits, `shr` shifts unsigned data, and `shra` shifts signed data. Bitwise results retain W bits. `plus_uconst` requires a nonnegative source immediate fitting W bits, interprets that bit pattern as the operand type, and adds with wrapping; for a signed three-bit type, 3 plus immediate 7 yields 2 because `111` denotes -1.

Comparisons use signed views for generic/signed and unsigned views for unsigned base types, returning `0:g` or `1:g`. At A=8, `255:g < 1:g` is true and `-1:g == 255:g` is true. `uop`, `bop`, and `cmp` return `OptionalInt`; core rules update cells only when a result exists.

Generic negative representatives are not globally normalized into positive addresses. At A=8, negating 7 yields -7:g, whose nonzero memory read has no result. Adding generic zero wraps it to 249:g, which can address byte 249. Zero-size reads do not restrict the address. This is separate from the paper's memory-result normalization; see the audit.

<a id="控制流"></a>
## Control Flow

`DW_OP_skip` (`0x2f`) and `DW_OP_bra` (`0x28`) take signed two-byte displacements in target byte order. Text requires `-32768 <= D <= 32767`: `0xffff` is 65535, not -1. `DW_OP_nop` (`0x96`) advances without changing even an empty stack.

`skip` sets P to `NEXT+D` without changing the stack. `bra` consumes the condition and jumps for nonzero N, or falls through to NEXT for zero. The current rule matches the numeric carrier without an explicit type predicate; do not infer an integer-only guard from the README. It does not validate the untaken branch target. Displacements and code positions are mathematical integers, not address-width values or the target register PC.

Taken targets must be confirmed operation starts or END within the current fragment. An operand byte, text-offset gap, or position outside the fragment is not a valid target. Unmet preconditions preserve the condition, stack prefix, and position. Decoding establishes boundaries only in its complete prefix; it never scans a raw suffix for opcode-shaped bytes. END remains a permitted boundary even when a suffix is undecodable, a documented partial-decoding convention rather than a claim of invalidity.

Only reached operations execute. A jump may bypass an unsupported operation or nonfinal `stack_value`, but reaching that marker still requires the current simple description to end there. Jumping to END requires a subsequent result rewrite and a suitable final stack. Backward jumps may diverge; budget exhaustion preserves the active state without inventing a loop error. The [countdown text](../examples/expressions/countdown.dwarf) and [bytes](../examples/expressions/countdown.hex) examples decrement 3 to 0; archived checks use budgets 13/14 to stop at the marker/complete with value zero.

<a id="简单位置结果"></a>
## Simple Location Results

Location results are distinct from operand-stack values. `Empty` returns `unavailable` for an originally empty location expression, preserving any supplied initial stack. This initial-stack interface is more general than the paper's empty-stack location judgment. A nonempty expression ending with an empty stack is incomplete, not unavailable.

`Memory` requires a nonempty expression at END and a nonempty final stack. It records the raw top integer as `memory(N)` without popping, reading the object, checking existence/range, or normalizing a negative representative. The current rule has no top-type restriction. This differs from the current paper's integral/generic restriction and A-bit address normalization; the audit records it without modifying the rule.

`Register` completes in one rewrite when the input consists solely of a nonnegative `regxOp(R)`, at the input start, with NEXT=END. It does not query register contents or change the stack, even with missing data or a nonempty initial stack. Computation prefixes/suffixes and jumps to a register description do not qualify. The raw encodings are `0x50..0x6f` for reg0..31 and `0x90` plus arbitrary-precision ULEB128 for regx. [register.dwarf](../examples/expressions/register.dwarf) and [register.hex](../examples/expressions/register.hex) illustrate `register(3)`; `breg3 0` instead reads and pushes contents.

`StackValue` completes directly from a nonempty stack only as the final operation of the simple description, retaining the entire stack and advancing to END. A later operation, repeated marker, or empty stack leaves evaluation at the marker. This final-marker condition also appears in the current paper's Section 3.4. `constu 42` denotes `memory(42)`, whereas `constu 42; stack_value` denotes direct `value(42:g)`; both retain `[42:g]`.

A standalone `implicit_value` returns bytes of arbitrary length without stack modification or address-width truncation. The paper represents those bytes as `value(n,b)` instead; the implementation preserves a separate public bytes category. Composite fragments have local simple-description ends as described below.

<a id="json-上下文"></a>
## JSON Context

See [context.json](../examples/expressions/context.json). Python validates input representation and builds the configuration; it does not interpret operations or recover values by DWARF computation.

| Field | Representation and default |
| --- | --- |
| `address_width` | Required positive integer A; divisibility by eight is checked where needed, not globally |
| `endianness` | Required `little` or `big` |
| `types` | Positive decimal CU-reference keys to strict base-type records; default `{}` |
| `registers` | Nonnegative decimal DWARF-number keys to register values; default `{}` |
| `memory` | Unsigned A-bit decimal address keys to bytes 0..255; default `{}` |
| `framebase` | Optional unsigned A-bit resolved frame base; omitted means unknown, zero is known |
| `cfa` | Optional independent unsigned A-bit CFA; no default from SP or frame base |
| `architecture` | Optional `i386`, `x86_64`, or `aarch64`; defaults to unspecified |
| `debug_addr` | Current-CU nonnegative indices to arbitrary-precision nonnegative entries; default `{}` |
| `debug_addr_load_bias` | Mathematical-integer load bias for addrx only; default 0 |
| `object_address` | Optional unsigned A-bit object address; zero is valid, omission means unknown |
| `initial_stack` | Bottom-to-top value list; default `[]` |
| `register_widths` | Optional DWARF-number to physical-bit-width map; width without contents remains unavailable |
| `raw_types` | Original type records retaining missing attributes, unsupported encodings, and negative fixtures |
| `memory_requests` | Exact `{address,size,bytes}` mock requests; do not merge conflicting overlaps or mix with nonempty byte memory |

Strict types have `id`, `encoding`, `bit_width`, and `byte_size`, with `0 < bit_width <= 8*byte_size` and positive byte size. Base widths may exceed A. An identity cannot have conflicting attributes; distinct identities remain distinct even with equal attributes. Accepted encodings are `DW_ATE_signed`, `unsigned`, `signed_char`, `unsigned_char`, `boolean`, `UTF`, `UCS`, `ASCII`, `address`, and `float` (each with the `DW_ATE_` prefix). Signed and signed_char use signed interpretation; other supported integral encodings use unsigned interpretation. Float uses its numeric format separately.

Generic is address-width; base types need not be. Section 2.5.1.1's ordinary literal operations truncate generic results to A bits, but `const_type` is the explicit typed exception. This is not a global stack-width bound: at A=32, `deref_type` can produce a 128-bit integer used by subsequent calculations and pieces. Generic read capacity, memory address bounds, and physical register widths remain separate checks.

Initial entries look like `{"value":-1,"type":12}` or `{"value":42,"type":"g"}` and must fit their types. Generic initial values accept `-2^(A-1) <= n < 2^A` and retain their supplied representative. Legacy address-width register entries use the same numeric convention; supplied physical widths are handled separately. Newly produced Const/Breg/Fbreg values are nonnegative patterns. Signed typed reads may retain negatives. Unused external values may remain absent.

`framebase` and `cfa` are independent fixed inputs, not reconstructed by K or inferred from SP. Invalid supplied addresses are rejected rather than truncated. `fbreg D` computes `(FB+D) mod 2^A`; at A=8, FB=255 with D=1 yields zero and FB=0 with D=-1 yields 255. `call_frame_cfa` pushes a known CFA directly and otherwise preserves the complete state.

Legacy `debugaddr`/`debugconst` spellings are rejected as unknown fields; index operations share `debug_addr`. The internal context is `ctx(A,endianness,types,registers,memory,framebase,cfa,architecture,debug_addr,debug_addr_load_bias,object_address)`. Additional runtime metadata are stored under a separate string key in its type Map, not new cells.

<a id="实现选择与结论边界"></a>
## Modeling Choices and Claim Boundaries

- **Decoded positions:** byte inputs retain real encoded boundaries; text uses declared increasing offsets without checking byte lengths. Paired tests do not constitute a proof of total frontend equivalence. Nonminimal and unbounded LEB encodings are accepted deliberately.
- **Concrete storage:** the paper's abstract interface I is realized by snapshot queries. Reads assemble consecutive bytes in target order, taking effective low bits and interpreting the encoding. Boolean reads are not normalized. This storage convention is separate from expression decoding.
- **Finite widths and addresses:** Const/Breg/Fbreg wrap to A bits; base values preserve their own width. Reads do not wrap across the address-space end. Raw memory-location result handling differs from the paper, as explicitly audited.
- **Execution and results:** fixed inputs are separate from mutable state. Successful rules update their required cells atomically. Structural validation is pure initialization and can produce `inputError`; it is not an operation-by-operation execution phase. No distinguished evaluation error result is introduced.
- **Evidence:** tests and claims establish only their tested behavior under their recorded premises. They do not establish full DWARF correctness, every operation/type combination, or a refinement theorem relating all implementation rules to the paper.

See [test and proof documentation](../tests/README.md) and the [paper naming and scope audit](paper-naming-audit.md).

<a id="隐式字节值与复合组装"></a>
## Implicit Bytes and Composite Assembly

| External operation | Byte encoding | Internal operation and rules |
| --- | --- | --- |
| `DW_OP_implicit_value [bytes]` | `0x9e`, ULEB128 length, bytes | `implicitValueOp(B)`; ImplicitValue / PieceImplicitValue |
| `DW_OP_piece n` | `0x93`, ULEB128 | `pieceOp(n)`; ComposePiece, size in bytes |
| `DW_OP_bit_piece n k` | `0x9d`, two ULEB128 operands | `bitPieceOp(n,k)`; ComposePiece, size/offset in bits |

Text byte blocks accept decimal/hex integers 0..255 and an empty `[]`, without a redundant length. Raw block decoding accepts nonminimal lengths but requires complete payloads; payload bytes create no operation boundaries.

`fragments(START,L,PS,BITS,EMPTY)` stores the current fragment start, pending location, committed pieces, accumulated object bits, and whether the initial stack was empty. `noLocation` means computation is still in progress; `located(L)` records a reg/implicit/stack_value result. Ordinary computation requires the former. A computed stack top may describe memory at a delimiter; only an actually empty fragment denotes unavailable. Executing operations and then dropping every entry does not make a fragment empty.

Composite inputs require an empty initial stack. Each successful `ComposePiece` records the original size/unit and location, appends assembled bits, clears the whole stack, and advances in one rewrite. The last delimiter completes directly. After any piece has been committed, an undelimited trailing fragment cannot complete through ordinary Memory/StackValue rules. Piece-specific explicit results first create a pending description; the delimiter then commits it. A standalone register or implicit byte value still preserves an arbitrary initial stack.

Branches stay between the current fragment start and its delimiter on known operation boundaries. The pure boundary scan stops at an unknown/truncated operation and does not search bytes for `0x93`/`0x9d`. If no delimiter is found, it retains the existing global END convention without claiming to identify hidden suffix pieces.

Assembly is little-endian. Memory/direct-value pieces need no explicit architecture; register pieces require an explicit supplied physical width or a supported architecture mapping. The default mappings are address-width GPRs: i386 DWARF 0..8 (32 bits), x86_64 0..16 (64 bits), and AArch64 0..32 (64 bits; X0..X30, SP=31, PC=32). Other registers may form standalone descriptions, but their assembly needs width evidence. There is no general SIMD/SVE or object-type-based register-layout model. Explicit architecture/width combinations are checked by the JSON interface.

DWARF orders pieces by object memory-address order and specifies least-significant-end register bit_piece offsets; placement of subregister byte pieces depends on the ABI. This implementation places earlier pieces in lower object bits, takes low register bits for byte pieces, numbers memory from low addresses and low bits within bytes, and interprets direct/implicit values as little-endian bits. These are explicit target conventions, not a complete ABI-independent assembly specification. Register references: [AMD64 psABI](https://gitlab.com/x86-psABIs/x86-64-ABI), [i386 psABI](https://gitlab.com/x86-psABIs/i386-ABI), [AADWARF64](https://github.com/ARM-software/abi-aa/blob/main/aadwarf64/aadwarf64.rst#dwarf-register-names), and [AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst).

`objectBits(N,V,MASK)` stores length, data, and known-bit mask. Missing bytes make their covered bits unknown; a missing register with known width makes the requested bits unknown. A register, typed value, or block shorter than the requested interval gives no transition, without extension or zero-filling. Zero-size pieces read no data. Memory addresses do not wrap. Expression-internal dereferences still require successful reads of all requested bytes.

```json
{"kind":"bytes","bytes":[17,34]}
{"kind":"composite","pieces":[{"kind":"piece","byte_size":1,"location":{"kind":"unavailable"}}],"bit_size":8,"bits":"????????"}
```

`bits` has exactly `bit_size` characters with the highest object bit on the left; `?` is unknown, never zero or a wildcard. K performs extraction and assembly. Python only renders K's data/mask and observes original assertion fields. Incomplete results remain null, with partial pieces and the actual stop state in the full configuration. Examples: [composite.dwarf](../examples/expressions/composite.dwarf), [composite.hex](../examples/expressions/composite.hex), [composite-context.json](../examples/expressions/composite-context.json).

<a id="地址表和普通值求值"></a>
## Address Tables and Value Purpose

`addrx` (`0xa1`) and `constx` (`0xa2`) take ULEB128 indices; `push_object_address` (`0x97`) has no operand. Nonminimal encodings and arbitrary-precision operands retain the common decoding conventions.

```json
{"address_width":64,"endianness":"little",
 "debug_addr":{"0":4096,"1":42},"debug_addr_load_bias":8192,
 "object_address":1234}
```

AddrIndex adds the verified load bias to the current-CU entry; ConstIndex uses the entry unchanged. Both produce generic results modulo `2^A`. Missing indices have no transition; there is no separate constant table. Byte-order interpretation of table data, CU selection, relocation, and load-map evidence belong to extraction, while K decodes indices and performs lookups. ObjectAddress pushes a known object address without reading it; omission means unknown and zero is valid.

CLI `--purpose location|value` defaults to location; Python `evaluate` has trailing argument `purpose="location"`. Purpose is a fixed control-term argument, not another cell or execution phase. Value purpose uses `Scalar` at END with a nonempty stack, returning the full top and preserving the whole stack. An empty expression can return an initial top. It does not interpret reg, implicit_value, stack_value, piece, or bit_piece as values; evaluation stops before those descriptions. A scalar JSON result retains type identity rather than adding a width field.

<a id="显式基础类型和上游-fixture"></a>
## Explicit Base Types and Upstream Fixtures

`const_type t [bytes]` checks the block against the base type's storage size and interprets target byte order. `regval_type r t` reads physical contents with sufficient source width. In these operations, reference 0 does not denote generic, and explicit base values are not truncated to the address width.

| Encoding | Effective bits | Numeric format | Precision bits | Minimum storage bytes |
| --- | ---: | --- | ---: | ---: |
| `DW_ATE_float` | 32 | binary32 | 24 | 4 |
| `DW_ATE_float` | 64 | binary64 | 53 | 8 |
| `DW_ATE_float` | 80 | x87 binary80, explicit integer bit | 64 | 10 |
| `DW_ATE_float` | 128 | binary128 | 113 | 16 |

These are four formats of one encoding, not four type identities. Different DIE identities remain different types, and storage padding adds no format. Strict float types accept these widths with sufficient byte size; raw metadata preserve unsupported formats for K to reject at lookup rather than misinterpret as integers.

Floating-point Ints carry nonnegative raw bits. `abs`, `neg`, `plus`, `minus`, `mul`, `div`, and six comparisons are implemented. Pure K functions use exact binary rationals and roundTiesToEven, including subnormals, infinities, NaNs, and signed zeros. Arithmetic produces a fixed quiet NaN where needed; abs/neg only change sign bits, and same-width convert/reinterpret preserve payloads. Runtime rounding modes, exception flags, and signaling-NaN traps are not modeled; noncanonical x87 encodings are not validated. Low-bit storage placement does not model every ABI's padded long-double layout.

Integer conversion wraps to target width. Integer-to-float rounds as above; float-to-integer truncates toward zero and requires a finite, representable result. NaN, infinity, and out-of-range integer targets have no transition. Four-format conversion is supported, but Boolean convert remains undefined. Reinterpret requires equal effective bit widths, retains target identity, and need not preserve storage size.

DWARF restricts `and/or/xor/not/mod/shl/shr/shra/plus_uconst` to integral operands. Their lack of floating-point transitions is not a floating-point implementation omission. Bit transport through descriptions/pieces is separate from numerical floating-point computation. See the [per-operation support evidence](../docs/reference/implementation.md#floating); metadata containing float types do not by themselves establish that tests executed floating-point operations.

`raw_types` preserve original tags, encodings, and size attributes, including unsupported or incomplete records. JSON structural errors remain input errors. With only a valid bit_size, K derives the minimum containing byte size as a fixture choice. `memory_requests` preserves address-and-length LLDB mock reads exactly, even when overlaps conflict; it neither merges nor invents bytes. Arbitrary precision is not an unlimited-resource guarantee.

Vendor text names are rejected as input errors; raw vendor opcodes remain undecodable and stop at their start. A legacy `wasm_locations` context field and data constructor exist only for archive compatibility; they restore no Wasm operation or slot evaluation.

<a id="引用调用和外部运行时数据"></a>
## Calls and External Runtime Data

| Family | Internal operation | Supplied data |
| --- | --- | --- |
| call2 / call4 | `callUnitOp(R)` | Two-/four-byte CU-relative DIE reference |
| call_ref | `callRefOp(R)` | Absolute .debug_info reference using the supplied reference width |
| entry_value | `entryValueOp(B)` | ULEB128-length block prepared as a decoded subexpression plus an independent entry snapshot |
| TLS | `formTlsAddressOp` | Thread/module offset-to-address map |
| xderef / xderef_size | `xderefOp(SIZE)` | Top address, next-to-top address-space identifier, and that space's bytes |
| xderef_type | `xderefTypeOp(SIZE,REF)` | The same reads plus complete base-type identity |
| implicit_pointer | `implicitPointerOp(REF,OFF)` | Absolute DIE reference and signed byte offset |

Optional JSON fields do not invent missing registers, memory, entry values, or TLS addresses:

```json
{
  "address_width":64,"endianness":"little",
  "compilation_unit_offset":0,"dwarf_offset_size":4,
  "die_locations":{"32":{"bytes":[50,34],"unit_offset":0,"offset_size":4,"address_width":64}},
  "entry_context":{"registers":{"0":11}},
  "tls_addresses":{"42":4096},
  "address_spaces":{"1":{"16":17,"17":34}}
}
```

`die_locations` keys are absolute DIE offsets. Records can supply bytes, CU offset/reference size/address width, types/raw types, address tables, const_value, byte_size, and type_ref. The referenced DIE's CU supplies metadata. Known DIEs with no location use empty bytes for a no-op procedure; unknown DIEs must not be fabricated as empty procedures. `dwarf_offset_size` is 4 by default or 8; suppliers must account for DWARF version, including DWARF 2 ref_addr address-size rules. Preserved metadata do not restore GNU variable_value evaluation.

Calls use decoded bodies prepared by the frontend. `call2/call4` add the current CU offset; `call_ref` is absolute. K saves caller inputs, return position, and fragment state in `returnCall`, shares the operand stack, and does not require a single return value. Each entry/return consumes one rewrite; recursion is budget-limited. While inside a call, public position/end describe the active expression, and the full configuration retains the caller chain. Input-preservation checks recover root inputs from that chain rather than confusing a changed active expression with mutated root input.

Entry blocks use a separate empty stack and entry context, inheriting only immutable CU/type/DIE metadata. Missing entry registers or memory never fall back to current state. They must leave one stack value or use a standalone register description, whose entry contents are read into the caller stack. Failure preserves the nested stack, position, pieces, and `returnEntry`; it does not roll back or discard the saved caller. Omitted entry context and an explicitly empty one are distinct, but neither derives data from the current snapshot.

TLS consumes an offset and pushes the supplied machine address, without querying host threads. Address-space reads consume both address and space and use only `address_spaces`, without ordinary-memory or host fallback. Size/capacity checks follow existing read conventions; missing bytes are not zero-filled.

A standalone implicit pointer returns `{"kind":"implicit_pointer","reference":32,"offset":-1}`, preserving identity rather than fabricating a physical address. Pointer arithmetic and composite implicit pointers remain limited. Observation may submit the referenced location to K as a separate dependency or inspect original const_value metadata, retaining dependency and offset evidence.

The runtime Map is stored under string key `"runtime"` in the read-only type table, keeping integer type-reference keys separate. Map brackets support K 7.1 serialization; they are not an execution step. These mechanisms add no new configuration cells beyond the existing fragment cell.

<a id="自然-stuckstuck-v1"></a>
## Natural Stuckness and Validation

Unmet operation preconditions leave the exact active configuration unchanged. This includes minimum-signed abs/neg, zero divisors, missing types/data, unknown/truncated operations, and failed nested calls. Structural input errors still use exit 2, incomplete evaluation exit 1; arbitrary incomplete or budget exhaustion is not a successful expected-error check.

The [validation receipts](../output/README.md#validation) and [test documentation](../tests/README.md) state the actual execution and proof scope. The full artifact replay is separate from formal regressions and proofs. Selected-expression statistics are maintained in [paper results](../docs/evaluation/README.md).

<a id="厂商扩展移除standard-only-v1"></a>
## Standard-Only Scope

Vendor operations are unsupported. Current selections exclude extension operations in root expressions, nested entry blocks, calls, and required dependencies without rewriting their bytes. See the [support catalog](../docs/reference/implementation.md#support).

<a id="解码与执行分离core-split-v1"></a>
## Decoding and Execution Separation

Pure preparation handles text/hex roots and supplied DIE code; the core queries only decoded E. It can be compiled independently for LLVM or Haskell. Entry and call bodies follow the same separation. Frontend/core tests and symbolic claims are recorded in the [validation report](../output/README.md#validation); no frontend refinement theorem is claimed.

<a id="与论文相近的内部命名paper-names-v1"></a>
## Paper-Oriented Internal Names

The current source uses `opAt`/`next` for code queries, `uop`/`bop`/`cmp` for calculations, `width`/`bits`/`signedBits` for bit interpretation, and `constOp`/`regxOp`-style normalized constructors. Public location constructors include `memory`, `register`, and `value`. Explicit `[symbol(...)]` attributes preserve earlier serialized KAST names, so source spelling and archival constructor identity must not be conflated. See the [complete correspondence and remaining differences](paper-naming-audit.md).
