requires "expression.k"

// Piece queries and bit-string assembly are pure computations; execution rules are in core.k.
module DWARF-COMPOSITION
  imports DWARF-EXPRESSION
  imports K-EQUAL

  syntax Bool ::= isComposition(Operation) [function]
  rule isComposition(pieceOp(_)) => true
  rule isComposition(bitPieceOp(_, _)) => true
  rule isComposition(_) => false [owise]
  syntax Int ::= pieceSize(Operation) [function]
               | pieceOffset(Operation) [function]
  rule pieceSize(pieceOp(N)) => 8 *Int N
  rule pieceSize(bitPieceOp(N, _)) => N
  rule pieceOffset(pieceOp(_)) => 0
  rule pieceOffset(bitPieceOp(_, K)) => K
  syntax Piece ::= pieceDesc(Operation, LocationResult) [function, symbol(describePiece(_,_)_DWARF-COMPOSITION_Piece_Operation_LocationResult)]
  rule pieceDesc(pieceOp(N), L) => bytePiece(N, L)
  rule pieceDesc(bitPieceOp(N, K), L) => bitPiece(N, K, L)

  // Find the delimiter of the current simple description; stop at a decoding failure without guessing later bytes.
  // Use the original END if no delimiter is found, preserving the END boundary convention for unknown suffixes.
  syntax Int ::= fragmentEnd(DecodedExpression, Int) [function]
               | scanFragment(DecodedExpression, Int, Instruction) [function]
  rule fragmentEnd(E, P) => scanFragment(E, P, instructionAt(E, P))
    requires P <Int inputEnd(E)
  rule fragmentEnd(E, P) => inputEnd(E) requires P >=Int inputEnd(E)
  rule scanFragment(_, P, instruction(O, _)) => P requires isComposition(O)
  rule scanFragment(E, _, instruction(O, NEXT)) => fragmentEnd(E, NEXT)
    requires notBool isComposition(O)
  rule scanFragment(E, _, noInstruction) => inputEnd(E)
  syntax Bool ::= localBoundary(DecodedExpression, Int, Int) [function]
  rule localBoundary(E, START, TARGET) =>
    START <=Int TARGET andBool TARGET <=Int fragmentEnd(E, START)
      andBool isBoundary(E, TARGET)

  // Only a fragment containing no operations is unavailable; computing and then emptying the stack is not an empty description.
  syntax PendingLocation ::= fragmentLocation(Int, Int, PendingLocation, Stack) [function]
  rule fragmentLocation(_, _, located(L), _) => located(L)
  rule fragmentLocation(P, P, noLocation, .Stack) => located(unavailable)
  rule fragmentLocation(P, START, noLocation, push(_, val(N, _))) => located(memory(N))
    requires P =/=Int START
  rule fragmentLocation(_, _, _, _) => noLocation [owise]

  // Match preconditions in stages; query bits only after the delimiter, target requirements, and fragment result are established.
  // This also avoids guessing pieceSize(noOperation) or getLocation(noLocation) during symbolic evaluation.
  syntax Bool ::= canCompose(Bool, Operation, Int, Int, PendingLocation, Stack, Context) [function]
                | compositionSource(Bool, Operation, PendingLocation, Context) [function]
  rule canCompose(false, _, _, _, _, _, _) => false
  rule canCompose(true, O, P, START, L, S, C) =>
    compositionSource(assemblyTarget(C), O, fragmentLocation(P, START, L, S), C)
  rule compositionSource(false, _, _, _) => false
  rule compositionSource(true, _, noLocation, _) => false
  rule compositionSource(true, O, located(L), C) =>
    hasBits(extractObject(L, pieceSize(O), pieceOffset(O), C))

  syntax Int ::= blockNumber(ByteBlock) [function]
  rule blockNumber(.Bytes) => 0
  rule blockNumber(byteCons(N, B)) => N +Int 256 *Int blockNumber(B)

  // Provide address-width x86 and AArch64 general-purpose registers; do not infer vector or other register sizes.
  syntax OptionalInt ::= registerWidth(Architecture, Int) [function]
  rule registerWidth(i386, R) => someInt(32) requires 0 <=Int R andBool R <=Int 8
  rule registerWidth(x86_64, R) => someInt(64) requires 0 <=Int R andBool R <=Int 16
  rule registerWidth(aarch64, R) => someInt(64) requires 0 <=Int R andBool R <=Int 32
  rule registerWidth(_, _) => noInt [owise]
  syntax OptionalInt ::= suppliedRegisterWidth(Map, Architecture, Int) [function]
  rule suppliedRegisterWidth((R |-> registerBits(_, W)) _REST:Map, _, R) => someInt(W)
  rule suppliedRegisterWidth((R |-> unavailableRegister(W)) _REST:Map, _, R) => someInt(W)
  rule suppliedRegisterWidth(_, ARCH, R) => registerWidth(ARCH, R) [owise]
  syntax Bool ::= assemblyTarget(Context) [function]
  // Memory and explicit-value bit concatenation depends on byte order; it does not require an invented architecture.
  // Register pieces separately check the supplied physical width or declared ABI through suppliedRegisterWidth.
  rule assemblyTarget(ctx(_, little, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt)) => true
  rule assemblyTarget(_) => false [owise]

  // A fixed-width source must contain enough bits; otherwise assembly has no result. Zero-bit pieces do not query the source.
  syntax OptionalBits ::= extractObject(LocationResult, Int, Int, Context) [function]
  rule extractObject(_, 0, _, _) => someBits(objectBits(0, 0, 0))
  rule extractObject(unavailable, N, _, _) => someBits(objectBits(N, 0, 0)) requires N >Int 0
  rule extractObject(value(val(V, T)), N, K, ctx(A, _, _, _, _, _, _:OptionalInt, _, _:Map, _:Int, _:OptionalInt)) =>
    someBits(knownSlice(V, N, K))
    requires N >Int 0 andBool K +Int N <=Int width(T, A)
  rule extractObject(bytesValue(B), N, K, _) => someBits(knownSlice(blockNumber(B), N, K))
    requires N >Int 0 andBool K +Int N <=Int 8 *Int blockLength(B)
  rule extractObject(register(R), N, K, (ctx(_, _, _, RS, _, _, _:OptionalInt, ARCH, _:Map, _:Int, _:OptionalInt) #as C)) =>
    registerSlice(lookupInt(RS, R), N, K)
    requires N >Int 0 andBool hasInt(suppliedRegisterWidth(RS, ARCH, R))
      andBool K +Int N <=Int getInt(suppliedRegisterWidth(RS, ARCH, R)) andBool assemblyTarget(C)
  rule extractObject(memory(ADDR), N, K, ctx(A, _, _, _, M, _, _:OptionalInt, _, _:Map, _:Int, _:OptionalInt)) =>
    someBits(memoryBits(M, ADDR, N, K, A)) requires N >Int 0 andBool notBool (requestMemoryMode in_keys(M))
  rule extractObject(memory(ADDR), N, K, ctx(A, _, _, _, M, _, _, _, _, _, _)) =>
    registerSlice(readRequest(M, ADDR +Int (K /Int 8), (K modInt 8 +Int N +Int 7) /Int 8, little), N, K modInt 8)
    requires N >Int 0 andBool (requestMemoryMode in_keys(M)) andBool fitsUnsigned(ADDR, A)
      andBool ADDR +Int ((K +Int N +Int 7) /Int 8) <=Int (2 ^Int A)
  rule extractObject(_, _, _, _) => noBits [owise]
  syntax ObjectBits ::= knownSlice(Int, Int, Int) [function]
                      | memoryBits(Map, Int, Int, Int, Int) [function]
                      | prependBit(OptionalInt, Int, ObjectBits) [function]
                      | appendBits(ObjectBits, ObjectBits) [function]
  rule knownSlice(V, N, K) => objectBits(N, bits(V >>Int K, N), (2 ^Int N) -Int 1)
  syntax OptionalBits ::= registerSlice(OptionalInt, Int, Int) [function]
  rule registerSlice(someInt(V), N, K) => someBits(knownSlice(V, N, K))
  rule registerSlice(noInt, N, _) => someBits(objectBits(N, 0, 0))
  // Preserve memory availability bit by bit; addresses do not wrap, and missing bytes make only their covered bits unknown.
  syntax OptionalInt ::= objectByte(Map, Int, Int) [function]
  rule objectByte(M, ADDR, A) => lookupInt(M, ADDR) requires fitsUnsigned(ADDR, A)
  rule objectByte(_, _, _) => noInt [owise]
  rule memoryBits(_, _, 0, _, _) => objectBits(0, 0, 0)
  rule memoryBits(M, ADDR, N, K, A) =>
    prependBit(objectByte(M, ADDR +Int (K /Int 8), A), K modInt 8,
      memoryBits(M, ADDR, N -Int 1, K +Int 1, A)) requires N >Int 0
  rule prependBit(someInt(B), K, objectBits(N, V, MASK)) =>
    objectBits(N +Int 1, ((B >>Int K) &Int 1) +Int 2 *Int V, 1 +Int 2 *Int MASK)
  rule prependBit(noInt, _, objectBits(N, V, MASK)) => objectBits(N +Int 1, 2 *Int V, 2 *Int MASK)
  // Earlier pieces occupy lower object bits; concatenate data and known-bit masks in the same order.
  rule appendBits(objectBits(N, V, MASK), objectBits(M, W, KNOWN)) =>
    objectBits(N +Int M, V +Int W *Int (2 ^Int N), MASK +Int KNOWN *Int (2 ^Int N))
  syntax Bool ::= hasBits(OptionalBits) [function]
  rule hasBits(someBits(_)) => true
  rule hasBits(noBits) => false
  syntax ObjectBits ::= getBits(OptionalBits) [function]
  rule getBits(someBits(B)) => B
  // Standard pieces consume no vendor-specific state or termination marker.
  syntax LocationResult ::= assembledLocation(Pieces, ObjectBits) [function]
  rule assembledLocation(PS, BITS) => composite(PS, BITS)
  syntax Bool ::= followsComposition(DecodedExpression, Int) [function]
  rule followsComposition(E, P) => isComposition(opAt(E, P))
  syntax LocationResult ::= getLocation(PendingLocation) [function]
  rule getLocation(located(L)) => L
endmodule
