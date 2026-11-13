// Shared data structures and pure calculations. Failed queries return noInt/noType/noValue;
// the caller decides whether a normal transition exists. These markers are not DWARF error categories.
module DWARF-DOMAINS
  imports INT
  imports BOOL
  imports STRING
  imports MAP

  // External input interfaces allow Maps inside Maps. Explicit brackets prevent the K 7.1 data unparser
  // from repeatedly attempting KItem brackets for nested Map concatenation. This is not an execution rule.
  syntax Map ::= "(" Map ")" [bracket]

  // g is the address-width generic type; its signed interpretation depends on the operation.
  // base(id, encoding, bit_width, byte_size) preserves type identity and attributes.
  // Distinct base-type IDs remain distinct even when width and encoding agree.
  // [symbol(...)] assigns stable KAST constructor names used by Python to observe K outcomes.
  syntax Ty ::= "g" [symbol(genericType)]
              | base(String, String, Int, Int) [symbol(baseType)]
  // The Int in val is a numeric carrier, not a built-in K machine integer.
  // Generic values produced by Const/Breg/Fbreg use nonnegative integers for A-bit patterns;
  // initial-stack inputs and signed base-type reads may still retain negative representatives.
  syntax Value ::= val(Int, Ty) [symbol(typedValue)]
  // Location results differ from operand-stack Values: addresses, registers, direct values, bytes, composites, or unavailable descriptions.
  // register stores only a DWARF register number; it neither stores nor reads register contents.
  // memory records only an address without reading the object; value retains the complete type.
  // unavailable denotes an empty expression or genuinely empty fragment, not a failed query or abnormal evaluation.
  syntax Purpose ::= "locationPurpose" | "valuePurpose" | "procedurePurpose" | "entryPurpose"
  syntax EvaluationResult ::= LocationResult | scalarResult(Value) [symbol(scalarResult)]
  syntax LocationResult ::= memory(Int) [symbol(memoryLocation)]
                          | register(Int) [symbol(registerLocation)]
                          | value(Value) [symbol(valueLocation)]
                          | "unavailable" [symbol(unavailableLocation)]
                          | bytesValue(ByteBlock) [symbol(bytesLocation)]
                          | composite(Pieces, ObjectBits) [symbol(compositeLocation)]
                          | implicitPointer(Int, Int) [symbol(implicitPointerLocation)]
  // Byte blocks and pieces are not operand-stack entries; separate constructors support arbitrary lengths.
  syntax ByteBlock ::= ".Bytes" [symbol(emptyBytes)]
                     | byteCons(Int, ByteBlock) [symbol(byteCons)]
  // Typed byte-block interpretation follows target byte order; typed constants are not truncated to the address width.
  syntax Int ::= blockLength(ByteBlock) [function]
               | blockUnsigned(ByteBlock, ByteOrder) [function]
  rule blockLength(.Bytes) => 0
  rule blockLength(byteCons(_, B)) => 1 +Int blockLength(B)
  rule blockUnsigned(.Bytes, _) => 0
  rule blockUnsigned(byteCons(N, B), little) => N +Int 256 *Int blockUnsigned(B, little)
  rule blockUnsigned(byteCons(N, B), big) =>
    N *Int (256 ^Int blockLength(B)) +Int blockUnsigned(B, big)
  syntax Piece ::= bytePiece(Int, LocationResult) [symbol(bytePiece)]
                 | bitPiece(Int, Int, LocationResult) [symbol(bitPiece)]
  syntax Pieces ::= ".Pieces" [symbol(emptyPieces)]
                  | appendPiece(Pieces, Piece) [symbol(appendPiece)]
  // objectBits(length, value, known-bit mask): all three fields are mathematical Ints.
  syntax ObjectBits ::= objectBits(Int, Int, Int) [symbol(objectBits)]
  syntax OptionalBits ::= someBits(ObjectBits) | "noBits"
  syntax PendingLocation ::= "noLocation" | located(LocationResult)
  syntax FragmentState ::= fragments(Int, PendingLocation, Pieces, ObjectBits, Bool) [symbol(fragments)]
  // .Stack is empty; push(S,V) appends V to prefix S, so the outermost V is the top.
  // For example, push(push(.Stack,val(1,g)),val(2,g)) denotes [1:g,2:g] from bottom to top.
  // This constructor lets symbolic proofs represent an arbitrary-length prefix directly by S.
  syntax Stack ::= ".Stack" [symbol(emptyStack)]
                 | push(Stack, Value) [symbol(stackPush)]
  syntax ByteOrder ::= "little" | "big"
  // Optional values: some... carries a result, no... means absent; someInt(0) differs from noInt.
  syntax OptionalInt ::= "noInt" | someInt(Int)
  // Optional physical register widths belong only to external register entries, not to operand Value types.
  // Legacy Int entries still denote address-width registers; high bits of wide registers must not be globally truncated.
  syntax RegisterContent ::= registerBits(Int, Int) [symbol(registerBits)]
                           | unavailableRegister(Int) [symbol(unavailableRegister)]
  // Retain the Wasm data constructor for input compatibility; no Wasm operation or slot-read rule exists.
  syntax WasmSlot ::= wasmSlot(Int, Int) [symbol(wasmSlot)]
  syntax MemoryRequest ::= memoryRequest(Int, Int) [symbol(memoryRequest)]
                         | "requestMemoryMode" [symbol(requestMemoryMode)]
  syntax OptionalType ::= "noType" | someType(Ty)
  // A source DIE may have the wrong tag, unknown encoding, or missing size. Preserve its record for audit;
  // K decides whether lookup yields a base type. Python must not filter these tests out in advance.
  syntax RawType ::= rawType(String, String, String, OptionalInt, OptionalInt, String) [symbol(rawType)]
  syntax OptionalValue ::= "noValue" | someValue(Value)
  // ctx(A, E, TS, RS, M, FB, CFA, ARCH, DEBUGADDR, BIAS, OBJECT): address width in bits, byte order, type and register tables,
  // byte-addressed memory, optional frame base/CFA, architecture, address table, load bias, and optional object address. JSON validates well-formedness.
  // A known frame base is someInt(FB), with 0 <= FB < 2^A; an unknown one is noInt.
  // Evaluation only reads the interface; Maps are indexed by type references, register numbers, and numeric addresses as appropriate.
  syntax Architecture ::= "unspecified" | "i386" | "x86_64" | "aarch64"
  // DEBUGADDR is the current CU's address table; BIAS applies only to addrx, not to constx.
  // OBJECT is the optional current-object address, independent of frame base and CFA.
  syntax Context ::= ctx(Int, ByteOrder, Map, Map, Map, OptionalInt, OptionalInt, Architecture, Map, Int, OptionalInt)


  // Optional runtime metadata use the separate string key runtime in the type table; integer DIE references keep their namespace.
  // The ctx argument list stays unchanged; if the interface omits this key, the additional lookups return unknown.
  // dieBody contains supplied DIE metadata; preparedDIE wraps read-only decoded code. The core never executes raw bytes.
  syntax DecodedExpression
  syntax DIEBody ::= dieBody(ByteBlock, Int, Int, Int, Map, Map, OptionalInt, Int, Int) [symbol(dieBody)]
                   | preparedDIE(DIEBody, DecodedExpression) [symbol(preparedDIE)]
  syntax OptionalDIE ::= someDIE(DIEBody) | "noDIE"
  syntax Map ::= runtimeData(Context) [function]
               | runtimeTable(Context, String) [function]
  rule runtimeData(ctx(_, _, ("runtime" |-> M:Map) _:Map, _, _, _, _, _, _, _, _)) => M
  rule runtimeData(_) => .Map [owise]
  rule runtimeTable(C, NAME) => runtimeMap(runtimeData(C), NAME)
  syntax Map ::= runtimeMap(Map, String) [function]
  rule runtimeMap((NAME |-> M:Map) _:Map, NAME) => M
  rule runtimeMap(_, _) => .Map [owise]
  syntax Int ::= runtimeNumber(Context, String, Int) [function]
               | runtimeNumberFrom(Map, String, Int) [function]
  rule runtimeNumber(C, NAME, DEFAULT) => runtimeNumberFrom(runtimeData(C), NAME, DEFAULT)
  rule runtimeNumberFrom((NAME |-> N:Int) _:Map, NAME, _) => N
  rule runtimeNumberFrom(_, _, DEFAULT) => DEFAULT [owise]
  syntax OptionalDIE ::= lookupDIE(Map, Int) [function]
  rule lookupDIE((REF |-> D:DIEBody) _:Map, REF) => someDIE(D)
  rule lookupDIE(_, _) => noDIE [owise]
  syntax Bool ::= hasType(OptionalType) [function]
  rule hasType(someType(_)) => true
  rule hasType(noType) => false
  syntax Bool ::= hasDIE(OptionalDIE) [function]
  rule hasDIE(someDIE(_)) => true
  rule hasDIE(noDIE) => false
  syntax DIEBody ::= getDIE(OptionalDIE) [function]
  rule getDIE(someDIE(D)) => D
  syntax OptionalContext ::= someContext(Context) [symbol(someContext)] | "noContext" [symbol(noContext)]
  syntax OptionalContext ::= entryContext(Context) [function]
  rule entryContext(ctx(_, _, ("runtime" |-> (("entry" |-> C:Context) _:Map)) _:Map, _, _, _, _, _, _, _, _)) => someContext(C)
  rule entryContext(_) => noContext [owise]
  syntax Bool ::= hasContext(OptionalContext) [function]
  rule hasContext(someContext(_)) => true
  rule hasContext(noContext) => false
  syntax Context ::= getContext(OptionalContext) [function]
  rule getContext(someContext(C)) => C
  syntax OptionalInt ::= readAddressSpace(Context, Int, Int, Int) [function]
  rule readAddressSpace(ctx(A, E, _, _, _, _, _, _, _, _, _) #as C, SPACE, SIZE, ADDR) =>
    readSpaceMap(runtimeTable(C, "spaces"), SPACE, SIZE, ADDR, A, E)
  syntax OptionalInt ::= readSpaceMap(Map, Int, Int, Int, Int, ByteOrder) [function]
  rule readSpaceMap((SPACE |-> M:Map) _:Map, SPACE, SIZE, ADDR, A, E) => readUnsigned(M, ADDR, SIZE, E)
    requires 0 <=Int SIZE andBool (SIZE ==Int 0 orBool (0 <=Int ADDR andBool ADDR +Int SIZE <=Int 2 ^Int A))
  rule readSpaceMap(_, _, _, _, _, _) => noInt [owise]

  // [function] declares a reducible pure function, not execution of a DWARF instruction.
  // These predicates check whether source constants fit unsigned/signed W-bit encodings; W is measured in bits.
  // They do not truncate results: fitsUnsigned(256,8) is false although the low eight bits are zero.
  syntax Bool ::= fitsUnsigned(Int, Int) [function]
                | fitsSigned(Int, Int) [function]
  rule fitsUnsigned(N, W) => 0 <=Int N andBool N <Int (2 ^Int W)
  rule fitsSigned(N, W) => (0 -Int (2 ^Int (W -Int 1))) <=Int N
                    andBool N <Int (2 ^Int (W -Int 1))

  // K |-> N is one Map entry; adjacent _REST:Map matches the remainder.
  // Both occurrences of K in lookupInt are the same variable, so lookup selects that key rather than an arbitrary entry.
  // K in_keys(M) tests key presence; explicit absence handling avoids undefined Map access.
  syntax OptionalInt ::= lookupInt(Map, Int) [function]
  rule lookupInt((K |-> N:Int) _REST:Map, K) => someInt(N)
  rule lookupInt((K |-> registerBits(N, _)) _REST:Map, K) => someInt(N)
  rule lookupInt((K |-> unavailableRegister(_)) _REST:Map, K) => noInt
  rule lookupInt(M, K) => noInt requires notBool (K in_keys(M))
  syntax Int ::= physicalRegisterWidth(Map, Int, Int) [function]
  rule physicalRegisterWidth((R |-> registerBits(_, W)) _REST:Map, R, _) => W
  rule physicalRegisterWidth((R |-> unavailableRegister(W)) _REST:Map, R, _) => W
  rule physicalRegisterWidth(_, _, DEFAULT) => DEFAULT [owise]
  // Confirm integer-query success before extraction as well; unknown registers have no default integer.
  syntax Bool ::= hasInt(OptionalInt) [function]
  rule hasInt(someInt(_)) => true
  rule hasInt(noInt) => false
  syntax Int ::= getInt(OptionalInt) [function]
  rule getInt(someInt(N)) => N
  // As with integer lookup, but a successful result must be a Ty and preserve complete type identity.
  syntax OptionalType ::= lookupType(Map, Int) [function]
  rule lookupType((K |-> T:Ty) _REST:Map, K) => someType(T) requires supportedType(T)
  rule lookupType((K |-> T:Ty) _REST:Map, K) => noType requires notBool supportedType(T)
  rule lookupType((K |-> T:RawType) _REST:Map, K) => resolveRawType(T)
  rule lookupType(M, K) => noType requires notBool (K in_keys(M))
  syntax Bool ::= numericEncoding(String) [function]
  rule numericEncoding(E) => E ==String "DW_ATE_address" orBool E ==String "DW_ATE_boolean"
    orBool E ==String "DW_ATE_signed" orBool E ==String "DW_ATE_signed_char"
    orBool E ==String "DW_ATE_unsigned" orBool E ==String "DW_ATE_unsigned_char"
    orBool E ==String "DW_ATE_UTF" orBool E ==String "DW_ATE_UCS" orBool E ==String "DW_ATE_ASCII"
    orBool E ==String "DW_ATE_float"
  // Unknown encodings and unmodeled floating-point formats do not fall through to integer handling.
  syntax Bool ::= integerType(Ty) [function]
                | supportedType(Ty) [function]
  rule integerType(g) => true
  rule integerType(base(_, E, _, _)) => numericEncoding(E) andBool E =/=String "DW_ATE_float"
  rule supportedType((base(_, E, W, _) #as T)) => integerType(T) orBool
    (E ==String "DW_ATE_float" andBool
      (W ==Int 32 orBool W ==Int 64 orBool W ==Int 80 orBool W ==Int 128))
  rule supportedType(g) => true
  syntax OptionalType ::= resolveRawType(RawType) [function]
  rule resolveRawType(rawType(ID, "DW_TAG_base_type", E, someInt(W), someInt(B), _)) => someType(base(ID, E, W, B))
    requires supportedType(base(ID, E, W, B)) andBool 0 <Int W andBool 0 <Int B andBool W <=Int 8 *Int B
  rule resolveRawType(rawType(ID, "DW_TAG_base_type", E, noInt, someInt(B), _)) => someType(base(ID, E, 8 *Int B, B))
    requires supportedType(base(ID, E, 8 *Int B, B)) andBool 0 <Int B
  // If only bit_size is present, use the minimum containing byte count for this model's storage record; retain original attributes.
  rule resolveRawType(rawType(ID, "DW_TAG_base_type", E, someInt(W), noInt, _)) => someType(base(ID, E, W, (W +Int 7) /Int 8))
    requires supportedType(base(ID, E, W, (W +Int 7) /Int 8)) andBool 0 <Int W
  rule resolveRawType(_) => noType [owise]

  // stackAt(S,K) counts from the top: zero selects the outermost Value, and each positive step removes one push from the query.
  // This is pure lookup; recursion never modifies the original stack. Empty stacks and negative indices return noValue.
  // Do not impose K <= 255 here; normalization and the operation rule enforce the DW_OP_pick encoding limit.
  syntax OptionalValue ::= stackAt(Stack, Int) [function]
  rule stackAt(push(_, V), 0) => someValue(V)
  rule stackAt(push(S, _), K) => stackAt(S, K -Int 1) requires K >Int 0
  rule stackAt(.Stack, _) => noValue
  rule stackAt(push(_, _), K) => noValue requires K <Int 0

  // Typed-value success tests and extraction are shared by DerefType and Pick; neither helper changes the configuration.
  // getValue is defined only for someValue; core rules must first establish success with hasValue.
  // noValue has no default Value, so unknown memory and out-of-range stack indices cannot become zero.
  syntax Bool ::= hasValue(OptionalValue) [function]
  rule hasValue(someValue(_)) => true
  rule hasValue(noValue) => false
  syntax Value ::= getValue(OptionalValue) [function]
  rule getValue(someValue(V)) => V

  // readUnsigned(M,A,S,E) reads S consecutive bytes from address A in byte order E.
  // Here A is the starting address, not the address width used in other rules.
  // This helper assembles only an unsigned storage value; callers check address ranges, types, and sizes.
  syntax OptionalInt ::= readUnsigned(Map, Int, Int, ByteOrder) [function]
                       | combineByte(OptionalInt, OptionalInt, Int, ByteOrder) [function]
  // Base case: reading zero bytes yields zero without accessing memory; a negative size has no read result.
  rule readUnsigned(_, _, 0, _) => someInt(0)
  // Look up the current byte, recursively read the remaining S-1 bytes, then combine them in the selected byte order.
  rule readUnsigned(M, A, S, E) =>
    combineByte(lookupInt(M, A), readUnsigned(M, A +Int 1, S -Int 1, E), S, E)
    requires S >Int 0
  rule readUnsigned(_, _, S, _) => noInt requires S <Int 0
  // B is the byte at the lowest address; N is the assembled value of the remaining bytes.
  // little places B in the low eight bits; big places it in the highest byte of the S-byte value.
  // For bytes [0x12,0x34] in increasing address order, little yields 0x3412 and big yields 0x1234.
  rule combineByte(someInt(B), someInt(N), _, little) => someInt(B +Int (256 *Int N))
  rule combineByte(someInt(B), someInt(N), S, big) => someInt((B *Int (256 ^Int (S -Int 1))) +Int N)
  // Any missing current or remaining byte propagates noInt rather than a zero substitute.
  rule combineByte(noInt, _, _, _) => noInt
  rule combineByte(someInt(_), noInt, _, _) => noInt

  // Of the current integral encodings, only signed and signed_char use a signed interpretation;
  // other supported integral encodings use unsigned interpretation, including Boolean without normalization to 0/1 on read.
  syntax Bool ::= signedEncoding(String) [function]
  rule signedEncoding(E) => E ==String "DW_ATE_signed" orBool E ==String "DW_ATE_signed_char"
  syntax Int ::= bits(Int, Int) [function, symbol(unsignedLow(_,_)_DWARF-DOMAINS_Int_Int_Int)]
               | signedBits(Int, Int) [function, symbol(signedLow(_,_)_DWARF-DOMAINS_Int_Int_Int)]
               | interpret(Int, Ty) [function]
  // These functions require W > 0, ensured by valid address and base-type widths.
  // bits retains the low W bits in [0,2^W), for extended values or truncation.
  // signedBits interprets the same pattern as W-bit two's complement in [-2^(W-1),2^(W-1)).
  // For W=3 and N=7, the unsigned interpretation is 7 and the signed interpretation is -1.
  rule bits(N, W) => N modInt (2 ^Int W)
  rule signedBits(N, W) => ((N +Int (2 ^Int (W -Int 1))) modInt (2 ^Int W))
                          -Int (2 ^Int (W -Int 1))
  // Generic reads use the assembled nonnegative integer; the caller ensures the read fits A bits.
  // Base types retain the low W effective bits and interpret signedness by encoding, ignoring other storage bits.
  // Placing effective bits in the low storage bits is this model's storage convention, not expression decoding.
  rule interpret(N, g) => N
  rule interpret(N, base(_, E, W, _)) => signedBits(N, W) requires signedEncoding(E)
  rule interpret(N, base(_, E, W, _)) => bits(N, W) requires numericEncoding(E) andBool notBool signedEncoding(E)

  // S is a byte count and A an address width: generic permits zero bytes but no more than A bits.
  // Typed reads require exactly the type's byte_size, not the rounded-up bit_width.
  // Interface well-formedness ensures byte_size > 0; the operation's 0..255 size-field limit is checked separately.
  syntax Bool ::= validReadSize(Int, Ty, Int) [function]
  rule validReadSize(S, g, A) => 0 <=Int S andBool (8 *Int S) <=Int A
  rule validReadSize(S, (base(_, _, _, B) #as T), _) => supportedType(T) andBool S ==Int B

  // readMemory(C,SIZE,ADDR) reads only an integer, without type lookup or construction of val.
  // As with register queries, success returns someInt(N); missing data or unmet address conditions return noInt.
  // Callers separately check generic capacity and typed storage size; the shared reader does not impose SIZE <= A/8.
  // A nonzero read requires [ADDR,ADDR+SIZE) inside the A-bit address space; the read does not wrap across its boundary.
  // A zero-size read accesses no memory, so ADDR need not be restricted; it returns integer zero, with type selected by the operation rule.
  syntax OptionalInt ::= readMemory(Context, Int, Int) [function]
  rule readMemory(ctx(A, E, _, _, M, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt), SIZE, ADDR) =>
    readUnsigned(M, ADDR, SIZE, E)
    requires 0 <=Int SIZE
      andBool (SIZE ==Int 0 orBool (0 <=Int ADDR andBool ADDR +Int SIZE <=Int (2 ^Int A)))
      andBool notBool (requestMemoryMode in_keys(M))
  rule readMemory(ctx(A, E, _, _, M, _, _, _, _, _, _), SIZE, ADDR) => readRequest(M, ADDR, SIZE, E)
    requires (requestMemoryMode in_keys(M)) andBool 0 <=Int SIZE
      andBool (SIZE ==Int 0 orBool (0 <=Int ADDR andBool ADDR +Int SIZE <=Int (2 ^Int A)))
  rule readMemory(_, _, _) => noInt [owise]
  // The original LLDB mock returns data by (address, read length); overlapping reads can disagree.
  // This memory-input mode preserves the fixture's behavior: it neither merges nor zero-fills data, and different lengths do not share default bytes.
  syntax OptionalInt ::= readRequest(Map, Int, Int, ByteOrder) [function]
  rule readRequest(_, _, 0, _) => someInt(0)
  rule readRequest((memoryRequest(ADDR, SIZE) |-> B:ByteBlock) _REST:Map, ADDR, SIZE, E) => someInt(blockUnsigned(B, E))
    requires SIZE >Int 0 andBool blockLength(B) ==Int SIZE
  rule readRequest(_, _, _, _) => noInt [owise]

  // Only DerefType uses this helper: the second argument is a byte count and the third a type-lookup result.
  // After checking the size, read the same memory integer and interpret effective bits and sign while retaining type identity.
  // #as C binds the whole ctx pattern, allowing access to width A while passing the original interface to readMemory.
  syntax OptionalValue ::= readTypedValue(Context, Int, OptionalType, Int) [function]
                         | interpretRead(OptionalInt, Ty) [function]
  rule readTypedValue(ctx(A, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C, SIZE, someType(T), ADDR) =>
    interpretRead(readMemory(C, SIZE, ADDR), T)
    requires validReadSize(SIZE, T, A)
  // An unknown type or mismatched storage size has no typed value; do not construct a default.
  rule readTypedValue(_, _, _, _) => noValue [owise]

  // Interpret a value only after all required bytes exist; interpret keeps effective low bits and follows the type encoding.
  // The result preserves actual type T; any missing byte propagates noValue without zero-filling.
  rule interpretRead(someInt(N), T) => someValue(val(interpret(N, T), T)) requires supportedType(T)
  rule interpretRead(_, _) => noValue [owise]
endmodule
