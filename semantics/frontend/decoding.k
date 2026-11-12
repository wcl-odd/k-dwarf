requires "normalization.k"

// DWARF 5 Section 7.6, Table 7.9, Appendix C: decode only; do not execute operations.
// Instruction records a normalized operation and next position; Operand records an integer and operand end position.
// noInstruction/noOperand mean the current query has no result, not that DWARF is invalid.
module DWARF-DECODING
  imports DWARF-NORMALIZATION

  syntax ByteCode ::= HexProgram | ByteBlock
  syntax Program ::= rawBytes(ByteBlock) [symbol(rawBytes)]
  syntax Operand ::= operand(Int, Int) | "noOperand"
  syntax String ::= byteString(HexByte) [function, total, hook(STRING.token2string)]
                  | byteDigits(HexByte) [function]
  rule byteDigits(B) => substrString(byteString(B), 2, lengthString(byteString(B)))
    requires lengthString(byteString(B)) >=Int 2
      andBool (substrString(byteString(B), 0, 2) ==String "0x"
        orBool substrString(byteString(B), 0, 2) ==String "0X")
  rule byteDigits(B) => byteString(B) [owise]
  syntax Int ::= byteNumber(HexByte) [function]
  rule byteNumber(B) => String2Base(byteDigits(B), 16)

  // A complete text sequence compares mathematical offsets only; its final number is END.
  // Recursive suffixes may have a nonzero END; only a wholly empty expression requires that number to be zero.
  syntax Bool ::= validInput(Program) [function]
                | orderedText(TextProgram) [function]
  rule validInput(N:Literal) => number(N) ==Int 0
  rule validInput((P:Literal : O:Op, REST:TextProgram)) => orderedText((P : O, REST))
  rule validInput(.HexProgram) => true
  rule validInput((B:HexByte REST:HexProgram)) =>
    lengthString(byteDigits(B)) ==Int 2 andBool validInput(REST)
  rule orderedText(_:Literal) => true
  rule orderedText((P:Literal : _:Op, REST:TextProgram)) =>
    number(P) <Int inputStart(REST) andBool orderedText(REST)

  rule validInput(rawBytes(_)) => true
  rule inputStart(rawBytes(_)) => 0
  rule inputEnd(rawBytes(B)) => blockLength(B)
  rule emptyInput(rawBytes(B)) => blockLength(B) ==Int 0
  syntax Int ::= inputStart(Program) [function]
               | inputEnd(Program) [function]
               | byteLength(ByteCode) [function]
  rule inputStart(N:Literal) => number(N)
  rule inputStart((P:Literal : _:Op, _:TextProgram)) => number(P)
  rule inputStart(_:HexProgram) => 0
  rule inputEnd(N:Literal) => number(N)
  rule inputEnd((_:Literal : _:Op, REST:TextProgram)) => inputEnd(REST)
  rule inputEnd(B:HexProgram) => byteLength(B)
  rule byteLength(B:ByteBlock) => blockLength(B)
  rule byteLength(.HexProgram) => 0
  rule byteLength((_:HexByte REST:HexProgram)) => 1 +Int byteLength(REST)
  syntax Bool ::= emptyInput(Program) [function]
  rule emptyInput(_:Literal) => true
  rule emptyInput((_:Literal : _:Op, _:TextProgram)) => false
  rule emptyInput(B:HexProgram) => byteLength(B) ==Int 0

  // byteAt queries code bytes independently of target memory; missing bytes are never filled with zero.
  syntax OptionalInt ::= byteAt(ByteCode, Int) [function]
  rule byteAt(byteCons(B, _), 0) => someInt(B)
  rule byteAt(byteCons(_, REST), P) => byteAt(REST, P -Int 1) requires P >Int 0
  rule byteAt((B:HexByte _:HexProgram), 0) => someInt(byteNumber(B))
  rule byteAt((_:HexByte REST:HexProgram), P) => byteAt(REST, P -Int 1) requires P >Int 0
  rule byteAt(_, _) => noInt [owise]

  // For fixed operands, check the whole range, assemble an unsigned integer, then interpret signedness at the source width.
  syntax Operand ::= readFixed(ByteCode, Int, Int, ByteOrder, Bool) [function]
  rule readFixed(B, P, SIZE, E, SIGNED) =>
    operand(fixedInterpret(codeUnsigned(B, P, SIZE, E), SIZE, SIGNED), P +Int SIZE)
    requires P >=Int 0 andBool SIZE >Int 0 andBool P +Int SIZE <=Int byteLength(B)
  rule readFixed(_, _, _, _, _) => noOperand [owise]
  syntax Int ::= codeUnsigned(ByteCode, Int, Int, ByteOrder) [function]
               | fixedInterpret(Int, Int, Bool) [function]
  rule codeUnsigned(_, _, 0, _) => 0
  rule codeUnsigned(B, P, SIZE, little) =>
    getInt(byteAt(B, P)) +Int 256 *Int codeUnsigned(B, P +Int 1, SIZE -Int 1, little)
    requires SIZE >Int 0
  rule codeUnsigned(B, P, SIZE, big) =>
    getInt(byteAt(B, P)) *Int (256 ^Int (SIZE -Int 1))
      +Int codeUnsigned(B, P +Int 1, SIZE -Int 1, big)
    requires SIZE >Int 0
  rule fixedInterpret(N, SIZE, true) => signedBits(N, 8 *Int SIZE)
  rule fixedInterpret(N, _, false) => N

  // LEB128 group order is independent of target byte order. Each recursion consumes one actual byte;
  // missing termination returns noOperand. Length is unbounded, and nonminimal encodings are accepted.
  syntax Operand ::= readLEB(ByteCode, Int, Bool) [function]
                   | lebFrom(ByteCode, Int, Bool, Int, Int) [function]
                   | lebByte(ByteCode, Int, Bool, Int, Int, Int) [function]
  rule readLEB(B, P, SIGNED) => lebFrom(B, P, SIGNED, 0, 0)
  rule lebFrom(B, P, SIGNED, SHIFT, ACC) =>
    lebByte(B, P, SIGNED, SHIFT, ACC, getInt(byteAt(B, P)))
    requires hasInt(byteAt(B, P))
  rule lebFrom(_, _, _, _, _) => noOperand [owise]
  rule lebByte(_, P, SIGNED, SHIFT, ACC, BYTE) =>
    operand(lebFinish(ACC +Int BYTE *Int (2 ^Int SHIFT), SHIFT +Int 7, BYTE, SIGNED), P +Int 1)
    requires BYTE <Int 128
  rule lebByte(B, P, SIGNED, SHIFT, ACC, BYTE) =>
    lebFrom(B, P +Int 1, SIGNED, SHIFT +Int 7,
            ACC +Int (BYTE modInt 128) *Int (2 ^Int SHIFT))
    requires BYTE >=Int 128
  syntax Int ::= lebFinish(Int, Int, Int, Bool) [function]
  rule lebFinish(N, SHIFT, BYTE, true) => N -Int (2 ^Int SHIFT) requires BYTE >=Int 64
  rule lebFinish(N, _, BYTE, true) => N requires BYTE <Int 64
  rule lebFinish(N, _, _, false) => N

  // Both inputs return instruction(OP,NEXT), retaining the original E.
  // A text END has no operation; do not infer or validate the user's declared encoding lengths here.
  syntax Encoding ::= encoding(Int, ByteOrder, Int)
  syntax Encoding ::= encodingOf(Context) [function]
  rule encodingOf(ctx(A, ORDER, _, _, _, _, _, _, _, _, _) #as C) =>
    encoding(A, ORDER, runtimeNumber(C, "offset_size", 4))
  syntax Instruction ::= sourceInstructionAt(Program, Int, Encoding) [function]
                       | textInstructionAt(TextProgram, Int, Int) [function]
  rule sourceInstructionAt(E:TextProgram, P, encoding(A, _, _)) => textInstructionAt(E, P, A)
  rule textInstructionAt((L:Literal : O:Op, REST:TextProgram), P, A) =>
    instruction(normalize(O, A), inputStart(REST)) requires number(L) ==Int P
  rule textInstructionAt((_:Literal : _:Op, REST:TextProgram), P, A) =>
    textInstructionAt(REST, P, A) [owise]
  rule textInstructionAt(_:Literal, _, _) => noInstruction
  rule sourceInstructionAt(B:HexProgram, P, encoding(A, E, OS)) =>
    decodeEncoded(B, getInt(byteAt(B, P)), P +Int 1, encoding(A, E, OS))
    requires hasInt(byteAt(B, P))
  rule sourceInstructionAt(_:HexProgram, _, _) => noInstruction [owise]
  rule sourceInstructionAt(rawBytes(B), P, C) => decodeEncoded(B, getInt(byteAt(B, P)), P +Int 1, C)
    requires hasInt(byteAt(B, P))
  rule sourceInstructionAt(rawBytes(_), _, _) => noInstruction [owise]

  // call_ref and implicit-pointer reference widths come from the DWARF format, not the processor address width.
  // DWARF 2 ref_addr uses address size; the input supplier must preserve this independent metadata.
  syntax Instruction ::= decodeEncoded(ByteCode, Int, Int, Encoding) [function]
                       | implicitReference(ByteCode, Operand) [function]
                       | implicitDisplacement(Int, Operand) [function]
                       | entryBlock(ByteCode, Operand) [function]
                       | xderefFirst(ByteCode, Operand) [function]
                       | xderefSecond(Int, Operand) [function]
  rule decodeEncoded(B, 154, P, encoding(_, E, OS)) => withOperand(154, readFixed(B, P, OS, E, false), 0)
  rule decodeEncoded(B, 160, P, encoding(_, E, OS)) => implicitReference(B, readFixed(B, P, OS, E, false))
  rule decodeEncoded(B, O, P, encoding(A, E, _)) => decodeOpcode(B, O, P, A, E) [owise]
  syntax ByteOrder ::= contextOrder(Context) [function]
  rule contextOrder(ctx(_, E, _, _, _, _, _, _, _, _, _)) => E
  rule decodeOpcode(B, 152, P, A, E) => withOperand(152, readFixed(B, P, 2, E, false), A)
  rule decodeOpcode(B, 153, P, A, E) => withOperand(153, readFixed(B, P, 4, E, false), A)
  rule withOperand(152, operand(R, NEXT), _) => instruction(callUnitOp(R), NEXT)
  rule withOperand(153, operand(R, NEXT), _) => instruction(callUnitOp(R), NEXT)
  rule withOperand(154, operand(R, NEXT), _) => instruction(callRefOp(R), NEXT)
  rule decodeOpcode(B, 163, P, _, _) => entryBlock(B, readLEB(B, P, false))
  rule entryBlock(B, operand(N, P)) => instruction(sourceEntry(codeBlock(B, P, N)), P +Int N)
    requires P +Int N <=Int byteLength(B)
  rule entryBlock(_, _) => noInstruction [owise]
  rule implicitReference(B, operand(R, P)) => implicitDisplacement(R, readLEB(B, P, true))
  rule implicitReference(_, noOperand) => noInstruction
  rule implicitDisplacement(R, operand(D, NEXT)) => instruction(implicitPointerOp(R, D), NEXT)
  rule implicitDisplacement(_, noOperand) => noInstruction
  rule decodeOpcode(_, 155, P, _, _) => instruction(formTlsAddressOp, P)
  rule decodeOpcode(_, 24, P, A, _) => instruction(xderefOp(A /Int 8), P) requires A modInt 8 ==Int 0
  rule decodeOpcode(B, 149, P, _, E) => withOperand(149, readFixed(B, P, 1, E, false), 0)
  rule withOperand(149, operand(SIZE, NEXT), _) => instruction(xderefOp(SIZE), NEXT)
  rule decodeOpcode(B, 167, P, _, E) => xderefFirst(B, readFixed(B, P, 1, E, false))
  rule xderefFirst(B, operand(SIZE, P)) => xderefSecond(SIZE, readLEB(B, P, false))
  rule xderefFirst(_, noOperand) => noInstruction
  rule xderefSecond(SIZE, operand(T, NEXT)) => instruction(xderefTypeOp(SIZE, T), NEXT)
  rule xderefSecond(_, noOperand) => noInstruction
  syntax Instruction ::= instructionAt(Program, Int, Context) [function]
  rule instructionAt(E, P, C) => sourceInstructionAt(E, P, encodingOf(C))
  syntax Operation ::= opAt(Program, Int, Context) [function, symbol(operationAt(_,_,_)_DWARF-DECODING_Operation_Program_Int_Context)]
  rule opAt(E, P, C) => instructionOperation(instructionAt(E, P, C))
  syntax Int ::= next(Program, Int, Context) [function, symbol(nextPosition(_,_,_)_DWARF-DECODING_Int_Program_Int_Context)]
  rule next(E, P, C) => instructionNext(instructionAt(E, P, C))

  // Raw block lengths use ULEB128; check the complete block and never treat its bytes as operations.
  syntax ByteBlock ::= codeBlock(ByteCode, Int, Int) [function]
  rule codeBlock(_, _, 0) => .Bytes
  rule codeBlock(B, P, N) => byteCons(getInt(byteAt(B, P)), codeBlock(B, P +Int 1, N -Int 1))
    requires N >Int 0
  syntax Instruction ::= decodeBlock(ByteCode, Operand) [function]
                       | decodeBitPiece(ByteCode, Operand) [function]
                       | finishBitPiece(Int, Operand) [function]
  rule decodeBlock(B, operand(N, P)) => instruction(implicitValueOp(codeBlock(B, P, N)), P +Int N)
    requires P +Int N <=Int byteLength(B)
  rule decodeBlock(_, _) => noInstruction [owise]
  rule decodeBitPiece(B, operand(N, P)) => finishBitPiece(N, readLEB(B, P, false))
  rule decodeBitPiece(_, noOperand) => noInstruction
  rule finishBitPiece(N, operand(K, P)) => instruction(bitPieceOp(N, K), P)
  rule finishBitPiece(_, noOperand) => noInstruction
  // Opcode dispatch from Table 7.9.
  // Corresponds to normalize(DW_OP_implicit_value [ B ], A), normalize(DW_OP_piece N, A),
  // and normalize(DW_OP_bit_piece N K, A); raw blocks need no reconstructed text literals. P follows the opcode at the first operand byte.
  rule decodeOpcode(B, 158, P, _, _) => decodeBlock(B, readLEB(B, P, false))
  rule decodeOpcode(B, 147, P, A, _) => withOperand(147, readLEB(B, P, false), A)
  rule withOperand(147, operand(N, NEXT), A) => instruction(normalize(DW_OP_piece N, A), NEXT)
  rule decodeOpcode(B, 157, P, _, _) => decodeBitPiece(B, readLEB(B, P, false))
  syntax Instruction ::= decodeOpcode(ByteCode, Int, Int, Int, ByteOrder) [function]
                       | withOperand(Int, Operand, Int) [function]
  rule decodeOpcode(B, 3, P, A, E) => withOperand(3, readFixed(B, P, A /Int 8, E, false), A) requires A >Int 0 andBool A modInt 8 ==Int 0
  rule withOperand(3, operand(N, NEXT), A) => instruction(normalize(DW_OP_addr N, A), NEXT)
  rule decodeOpcode(_, 6, P, A, _) => instruction(normalize(DW_OP_deref, A), P)
  rule decodeOpcode(B, 8, P, A, E) => withOperand(8, readFixed(B, P, 1, E, false), A)
  rule withOperand(8, operand(N, NEXT), A) => instruction(normalize(DW_OP_const1u N, A), NEXT)
  rule decodeOpcode(B, 9, P, A, E) => withOperand(9, readFixed(B, P, 1, E, true), A)
  rule withOperand(9, operand(N, NEXT), A) => instruction(normalize(DW_OP_const1s N, A), NEXT)
  rule decodeOpcode(B, 10, P, A, E) => withOperand(10, readFixed(B, P, 2, E, false), A)
  rule withOperand(10, operand(N, NEXT), A) => instruction(normalize(DW_OP_const2u N, A), NEXT)
  rule decodeOpcode(B, 11, P, A, E) => withOperand(11, readFixed(B, P, 2, E, true), A)
  rule withOperand(11, operand(N, NEXT), A) => instruction(normalize(DW_OP_const2s N, A), NEXT)
  rule decodeOpcode(B, 12, P, A, E) => withOperand(12, readFixed(B, P, 4, E, false), A)
  rule withOperand(12, operand(N, NEXT), A) => instruction(normalize(DW_OP_const4u N, A), NEXT)
  rule decodeOpcode(B, 13, P, A, E) => withOperand(13, readFixed(B, P, 4, E, true), A)
  rule withOperand(13, operand(N, NEXT), A) => instruction(normalize(DW_OP_const4s N, A), NEXT)
  rule decodeOpcode(B, 14, P, A, E) => withOperand(14, readFixed(B, P, 8, E, false), A)
  rule withOperand(14, operand(N, NEXT), A) => instruction(normalize(DW_OP_const8u N, A), NEXT)
  rule decodeOpcode(B, 15, P, A, E) => withOperand(15, readFixed(B, P, 8, E, true), A)
  rule withOperand(15, operand(N, NEXT), A) => instruction(normalize(DW_OP_const8s N, A), NEXT)
  rule decodeOpcode(B, 16, P, A, _) => withOperand(16, readLEB(B, P, false), A)
  rule withOperand(16, operand(N, NEXT), A) => instruction(normalize(DW_OP_constu N, A), NEXT)
  rule decodeOpcode(B, 17, P, A, _) => withOperand(17, readLEB(B, P, true), A)
  rule withOperand(17, operand(N, NEXT), A) => instruction(normalize(DW_OP_consts N, A), NEXT)
  rule decodeOpcode(_, 18, P, A, _) => instruction(normalize(DW_OP_dup, A), P)
  rule decodeOpcode(_, 19, P, A, _) => instruction(normalize(DW_OP_drop, A), P)
  rule decodeOpcode(_, 20, P, A, _) => instruction(normalize(DW_OP_over, A), P)
  rule decodeOpcode(B, 21, P, A, E) => withOperand(21, readFixed(B, P, 1, E, false), A)
  rule withOperand(21, operand(N, NEXT), A) => instruction(normalize(DW_OP_pick N, A), NEXT)
  rule decodeOpcode(_, 22, P, A, _) => instruction(normalize(DW_OP_swap, A), P)
  rule decodeOpcode(_, 23, P, A, _) => instruction(normalize(DW_OP_rot, A), P)
  rule decodeOpcode(_, 151, P, A, _) => instruction(normalize(DW_OP_push_object_address, A), P)
  rule decodeOpcode(B, 161, P, A, _) => withOperand(161, readLEB(B, P, false), A)
  rule withOperand(161, operand(N, NEXT), A) => instruction(normalize(DW_OP_addrx N, A), NEXT)
  rule decodeOpcode(B, 162, P, A, _) => withOperand(162, readLEB(B, P, false), A)
  rule withOperand(162, operand(N, NEXT), A) => instruction(normalize(DW_OP_constx N, A), NEXT)
  rule decodeOpcode(_, 25, P, A, _) => instruction(normalize(DW_OP_abs, A), P)
  rule decodeOpcode(_, 26, P, A, _) => instruction(normalize(DW_OP_and, A), P)
  rule decodeOpcode(_, 27, P, A, _) => instruction(normalize(DW_OP_div, A), P)
  rule decodeOpcode(_, 28, P, A, _) => instruction(normalize(DW_OP_minus, A), P)
  rule decodeOpcode(_, 29, P, A, _) => instruction(normalize(DW_OP_mod, A), P)
  rule decodeOpcode(_, 30, P, A, _) => instruction(normalize(DW_OP_mul, A), P)
  rule decodeOpcode(_, 31, P, A, _) => instruction(normalize(DW_OP_neg, A), P)
  rule decodeOpcode(_, 32, P, A, _) => instruction(normalize(DW_OP_not, A), P)
  rule decodeOpcode(_, 33, P, A, _) => instruction(normalize(DW_OP_or, A), P)
  rule decodeOpcode(_, 34, P, A, _) => instruction(normalize(DW_OP_plus, A), P)
  rule decodeOpcode(B, 35, P, A, _) => withOperand(35, readLEB(B, P, false), A)
  rule withOperand(35, operand(N, NEXT), A) => instruction(normalize(DW_OP_plus_uconst N, A), NEXT)
  rule decodeOpcode(_, 36, P, A, _) => instruction(normalize(DW_OP_shl, A), P)
  rule decodeOpcode(_, 37, P, A, _) => instruction(normalize(DW_OP_shr, A), P)
  rule decodeOpcode(_, 38, P, A, _) => instruction(normalize(DW_OP_shra, A), P)
  rule decodeOpcode(_, 39, P, A, _) => instruction(normalize(DW_OP_xor, A), P)
  // braOp (0x28)/skipOp (0x2f) displacements are signed 16-bit integers in target byte order; P follows the opcode.
  rule decodeOpcode(B, 40, P, A, E) => withOperand(40, readFixed(B, P, 2, E, true), A)
  rule withOperand(40, operand(N, NEXT), A) => instruction(normalize(DW_OP_bra N, A), NEXT)
  rule decodeOpcode(_, 41, P, A, _) => instruction(normalize(DW_OP_eq, A), P)
  rule decodeOpcode(_, 42, P, A, _) => instruction(normalize(DW_OP_ge, A), P)
  rule decodeOpcode(_, 43, P, A, _) => instruction(normalize(DW_OP_gt, A), P)
  rule decodeOpcode(_, 44, P, A, _) => instruction(normalize(DW_OP_le, A), P)
  rule decodeOpcode(_, 45, P, A, _) => instruction(normalize(DW_OP_lt, A), P)
  rule decodeOpcode(_, 46, P, A, _) => instruction(normalize(DW_OP_ne, A), P)
  rule decodeOpcode(B, 47, P, A, E) => withOperand(47, readFixed(B, P, 2, E, true), A)
  rule withOperand(47, operand(N, NEXT), A) => instruction(normalize(DW_OP_skip N, A), NEXT)
  rule decodeOpcode(_, 48, P, A, _) => instruction(normalize(DW_OP_lit0, A), P)
  rule decodeOpcode(_, 49, P, A, _) => instruction(normalize(DW_OP_lit1, A), P)
  rule decodeOpcode(_, 50, P, A, _) => instruction(normalize(DW_OP_lit2, A), P)
  rule decodeOpcode(_, 51, P, A, _) => instruction(normalize(DW_OP_lit3, A), P)
  rule decodeOpcode(_, 52, P, A, _) => instruction(normalize(DW_OP_lit4, A), P)
  rule decodeOpcode(_, 53, P, A, _) => instruction(normalize(DW_OP_lit5, A), P)
  rule decodeOpcode(_, 54, P, A, _) => instruction(normalize(DW_OP_lit6, A), P)
  rule decodeOpcode(_, 55, P, A, _) => instruction(normalize(DW_OP_lit7, A), P)
  rule decodeOpcode(_, 56, P, A, _) => instruction(normalize(DW_OP_lit8, A), P)
  rule decodeOpcode(_, 57, P, A, _) => instruction(normalize(DW_OP_lit9, A), P)
  rule decodeOpcode(_, 58, P, A, _) => instruction(normalize(DW_OP_lit10, A), P)
  rule decodeOpcode(_, 59, P, A, _) => instruction(normalize(DW_OP_lit11, A), P)
  rule decodeOpcode(_, 60, P, A, _) => instruction(normalize(DW_OP_lit12, A), P)
  rule decodeOpcode(_, 61, P, A, _) => instruction(normalize(DW_OP_lit13, A), P)
  rule decodeOpcode(_, 62, P, A, _) => instruction(normalize(DW_OP_lit14, A), P)
  rule decodeOpcode(_, 63, P, A, _) => instruction(normalize(DW_OP_lit15, A), P)
  rule decodeOpcode(_, 64, P, A, _) => instruction(normalize(DW_OP_lit16, A), P)
  rule decodeOpcode(_, 65, P, A, _) => instruction(normalize(DW_OP_lit17, A), P)
  rule decodeOpcode(_, 66, P, A, _) => instruction(normalize(DW_OP_lit18, A), P)
  rule decodeOpcode(_, 67, P, A, _) => instruction(normalize(DW_OP_lit19, A), P)
  rule decodeOpcode(_, 68, P, A, _) => instruction(normalize(DW_OP_lit20, A), P)
  rule decodeOpcode(_, 69, P, A, _) => instruction(normalize(DW_OP_lit21, A), P)
  rule decodeOpcode(_, 70, P, A, _) => instruction(normalize(DW_OP_lit22, A), P)
  rule decodeOpcode(_, 71, P, A, _) => instruction(normalize(DW_OP_lit23, A), P)
  rule decodeOpcode(_, 72, P, A, _) => instruction(normalize(DW_OP_lit24, A), P)
  rule decodeOpcode(_, 73, P, A, _) => instruction(normalize(DW_OP_lit25, A), P)
  rule decodeOpcode(_, 74, P, A, _) => instruction(normalize(DW_OP_lit26, A), P)
  rule decodeOpcode(_, 75, P, A, _) => instruction(normalize(DW_OP_lit27, A), P)
  rule decodeOpcode(_, 76, P, A, _) => instruction(normalize(DW_OP_lit28, A), P)
  rule decodeOpcode(_, 77, P, A, _) => instruction(normalize(DW_OP_lit29, A), P)
  rule decodeOpcode(_, 78, P, A, _) => instruction(normalize(DW_OP_lit30, A), P)
  rule decodeOpcode(_, 79, P, A, _) => instruction(normalize(DW_OP_lit31, A), P)
  // reg0..31 (0x50..0x6f) have no operands; regx (0x90) uses an arbitrary-precision ULEB128 register number.
  rule decodeOpcode(_, 80, P, A, _) => instruction(normalize(DW_OP_reg0, A), P)
  rule decodeOpcode(_, 81, P, A, _) => instruction(normalize(DW_OP_reg1, A), P)
  rule decodeOpcode(_, 82, P, A, _) => instruction(normalize(DW_OP_reg2, A), P)
  rule decodeOpcode(_, 83, P, A, _) => instruction(normalize(DW_OP_reg3, A), P)
  rule decodeOpcode(_, 84, P, A, _) => instruction(normalize(DW_OP_reg4, A), P)
  rule decodeOpcode(_, 85, P, A, _) => instruction(normalize(DW_OP_reg5, A), P)
  rule decodeOpcode(_, 86, P, A, _) => instruction(normalize(DW_OP_reg6, A), P)
  rule decodeOpcode(_, 87, P, A, _) => instruction(normalize(DW_OP_reg7, A), P)
  rule decodeOpcode(_, 88, P, A, _) => instruction(normalize(DW_OP_reg8, A), P)
  rule decodeOpcode(_, 89, P, A, _) => instruction(normalize(DW_OP_reg9, A), P)
  rule decodeOpcode(_, 90, P, A, _) => instruction(normalize(DW_OP_reg10, A), P)
  rule decodeOpcode(_, 91, P, A, _) => instruction(normalize(DW_OP_reg11, A), P)
  rule decodeOpcode(_, 92, P, A, _) => instruction(normalize(DW_OP_reg12, A), P)
  rule decodeOpcode(_, 93, P, A, _) => instruction(normalize(DW_OP_reg13, A), P)
  rule decodeOpcode(_, 94, P, A, _) => instruction(normalize(DW_OP_reg14, A), P)
  rule decodeOpcode(_, 95, P, A, _) => instruction(normalize(DW_OP_reg15, A), P)
  rule decodeOpcode(_, 96, P, A, _) => instruction(normalize(DW_OP_reg16, A), P)
  rule decodeOpcode(_, 97, P, A, _) => instruction(normalize(DW_OP_reg17, A), P)
  rule decodeOpcode(_, 98, P, A, _) => instruction(normalize(DW_OP_reg18, A), P)
  rule decodeOpcode(_, 99, P, A, _) => instruction(normalize(DW_OP_reg19, A), P)
  rule decodeOpcode(_, 100, P, A, _) => instruction(normalize(DW_OP_reg20, A), P)
  rule decodeOpcode(_, 101, P, A, _) => instruction(normalize(DW_OP_reg21, A), P)
  rule decodeOpcode(_, 102, P, A, _) => instruction(normalize(DW_OP_reg22, A), P)
  rule decodeOpcode(_, 103, P, A, _) => instruction(normalize(DW_OP_reg23, A), P)
  rule decodeOpcode(_, 104, P, A, _) => instruction(normalize(DW_OP_reg24, A), P)
  rule decodeOpcode(_, 105, P, A, _) => instruction(normalize(DW_OP_reg25, A), P)
  rule decodeOpcode(_, 106, P, A, _) => instruction(normalize(DW_OP_reg26, A), P)
  rule decodeOpcode(_, 107, P, A, _) => instruction(normalize(DW_OP_reg27, A), P)
  rule decodeOpcode(_, 108, P, A, _) => instruction(normalize(DW_OP_reg28, A), P)
  rule decodeOpcode(_, 109, P, A, _) => instruction(normalize(DW_OP_reg29, A), P)
  rule decodeOpcode(_, 110, P, A, _) => instruction(normalize(DW_OP_reg30, A), P)
  rule decodeOpcode(_, 111, P, A, _) => instruction(normalize(DW_OP_reg31, A), P)
  rule decodeOpcode(B, 144, P, A, _) => withOperand(144, readLEB(B, P, false), A)
  rule withOperand(144, operand(N, NEXT), A) => instruction(normalize(DW_OP_regx N, A), NEXT)
  rule decodeOpcode(B, 112, P, A, _) => withOperand(112, readLEB(B, P, true), A)
  rule withOperand(112, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg0 N, A), NEXT)
  rule decodeOpcode(B, 113, P, A, _) => withOperand(113, readLEB(B, P, true), A)
  rule withOperand(113, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg1 N, A), NEXT)
  rule decodeOpcode(B, 114, P, A, _) => withOperand(114, readLEB(B, P, true), A)
  rule withOperand(114, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg2 N, A), NEXT)
  rule decodeOpcode(B, 115, P, A, _) => withOperand(115, readLEB(B, P, true), A)
  rule withOperand(115, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg3 N, A), NEXT)
  rule decodeOpcode(B, 116, P, A, _) => withOperand(116, readLEB(B, P, true), A)
  rule withOperand(116, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg4 N, A), NEXT)
  rule decodeOpcode(B, 117, P, A, _) => withOperand(117, readLEB(B, P, true), A)
  rule withOperand(117, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg5 N, A), NEXT)
  rule decodeOpcode(B, 118, P, A, _) => withOperand(118, readLEB(B, P, true), A)
  rule withOperand(118, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg6 N, A), NEXT)
  rule decodeOpcode(B, 119, P, A, _) => withOperand(119, readLEB(B, P, true), A)
  rule withOperand(119, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg7 N, A), NEXT)
  rule decodeOpcode(B, 120, P, A, _) => withOperand(120, readLEB(B, P, true), A)
  rule withOperand(120, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg8 N, A), NEXT)
  rule decodeOpcode(B, 121, P, A, _) => withOperand(121, readLEB(B, P, true), A)
  rule withOperand(121, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg9 N, A), NEXT)
  rule decodeOpcode(B, 122, P, A, _) => withOperand(122, readLEB(B, P, true), A)
  rule withOperand(122, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg10 N, A), NEXT)
  rule decodeOpcode(B, 123, P, A, _) => withOperand(123, readLEB(B, P, true), A)
  rule withOperand(123, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg11 N, A), NEXT)
  rule decodeOpcode(B, 124, P, A, _) => withOperand(124, readLEB(B, P, true), A)
  rule withOperand(124, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg12 N, A), NEXT)
  rule decodeOpcode(B, 125, P, A, _) => withOperand(125, readLEB(B, P, true), A)
  rule withOperand(125, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg13 N, A), NEXT)
  rule decodeOpcode(B, 126, P, A, _) => withOperand(126, readLEB(B, P, true), A)
  rule withOperand(126, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg14 N, A), NEXT)
  rule decodeOpcode(B, 127, P, A, _) => withOperand(127, readLEB(B, P, true), A)
  rule withOperand(127, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg15 N, A), NEXT)
  rule decodeOpcode(B, 128, P, A, _) => withOperand(128, readLEB(B, P, true), A)
  rule withOperand(128, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg16 N, A), NEXT)
  rule decodeOpcode(B, 129, P, A, _) => withOperand(129, readLEB(B, P, true), A)
  rule withOperand(129, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg17 N, A), NEXT)
  rule decodeOpcode(B, 130, P, A, _) => withOperand(130, readLEB(B, P, true), A)
  rule withOperand(130, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg18 N, A), NEXT)
  rule decodeOpcode(B, 131, P, A, _) => withOperand(131, readLEB(B, P, true), A)
  rule withOperand(131, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg19 N, A), NEXT)
  rule decodeOpcode(B, 132, P, A, _) => withOperand(132, readLEB(B, P, true), A)
  rule withOperand(132, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg20 N, A), NEXT)
  rule decodeOpcode(B, 133, P, A, _) => withOperand(133, readLEB(B, P, true), A)
  rule withOperand(133, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg21 N, A), NEXT)
  rule decodeOpcode(B, 134, P, A, _) => withOperand(134, readLEB(B, P, true), A)
  rule withOperand(134, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg22 N, A), NEXT)
  rule decodeOpcode(B, 135, P, A, _) => withOperand(135, readLEB(B, P, true), A)
  rule withOperand(135, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg23 N, A), NEXT)
  rule decodeOpcode(B, 136, P, A, _) => withOperand(136, readLEB(B, P, true), A)
  rule withOperand(136, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg24 N, A), NEXT)
  rule decodeOpcode(B, 137, P, A, _) => withOperand(137, readLEB(B, P, true), A)
  rule withOperand(137, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg25 N, A), NEXT)
  rule decodeOpcode(B, 138, P, A, _) => withOperand(138, readLEB(B, P, true), A)
  rule withOperand(138, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg26 N, A), NEXT)
  rule decodeOpcode(B, 139, P, A, _) => withOperand(139, readLEB(B, P, true), A)
  rule withOperand(139, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg27 N, A), NEXT)
  rule decodeOpcode(B, 140, P, A, _) => withOperand(140, readLEB(B, P, true), A)
  rule withOperand(140, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg28 N, A), NEXT)
  rule decodeOpcode(B, 141, P, A, _) => withOperand(141, readLEB(B, P, true), A)
  rule withOperand(141, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg29 N, A), NEXT)
  rule decodeOpcode(B, 142, P, A, _) => withOperand(142, readLEB(B, P, true), A)
  rule withOperand(142, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg30 N, A), NEXT)
  rule decodeOpcode(B, 143, P, A, _) => withOperand(143, readLEB(B, P, true), A)
  rule withOperand(143, operand(N, NEXT), A) => instruction(normalize(DW_OP_breg31 N, A), NEXT)
  rule decodeOpcode(B, 145, P, A, _) => withOperand(145, readLEB(B, P, true), A)
  rule withOperand(145, operand(N, NEXT), A) => instruction(normalize(DW_OP_fbreg N, A), NEXT)
  rule decodeOpcode(B, 148, P, A, E) => withOperand(148, readFixed(B, P, 1, E, false), A)
  rule withOperand(148, operand(N, NEXT), A) => instruction(normalize(DW_OP_deref_size N, A), NEXT)
  rule decodeOpcode(_, 150, P, A, _) => instruction(normalize(DW_OP_nop, A), P)
  rule decodeOpcode(_, 156, P, A, _) => instruction(normalize(DW_OP_call_frame_cfa, A), P)
  rule decodeOpcode(_, 159, P, A, _) => instruction(normalize(DW_OP_stack_value, A), P)
  rule decodeOpcode(B, 146, P, A, _) => bregxFirst(B, readLEB(B, P, false), A)
  rule decodeOpcode(B, 166, P, A, E) => typedFirst(B, readFixed(B, P, 1, E, false), A)
  // DWARF 5 Table 7.9: conversion type references use ULEB128, including the defined reference 0.
  rule decodeOpcode(B, 168, P, A, _) => withOperand(168, readLEB(B, P, false), A)
  rule withOperand(168, operand(T, NEXT), A) => instruction(normalize(DW_OP_convert T, A), NEXT)
  rule decodeOpcode(B, 169, P, A, _) => withOperand(169, readLEB(B, P, false), A)
  rule withOperand(169, operand(T, NEXT), A) => instruction(normalize(DW_OP_reinterpret T, A), NEXT)
  // Section 2.5.1.1: const_type has a ULEB128 type reference and a one-byte block length, not ULEB128.
  // Return an instruction only after reading the entire block; opcode-like block bytes create no instruction boundaries.
  rule decodeOpcode(B, 164, P, _, E) => constTypeReference(B, readLEB(B, P, false), E)
  rule decodeOpcode(B, 165, P, _, _) => regTypeReference(B, readLEB(B, P, false))
  // Do not decode vendor opcodes; stop at their start as for unknown operations, without executing a speculative suffix.
  rule decodeOpcode(_, _, _, _, _) => noInstruction [owise]
  rule withOperand(_, noOperand, _) => noInstruction

  // For multiple operands, query the next only after the previous succeeds; still return a single Instruction.
  syntax Instruction ::= bregxFirst(ByteCode, Operand, Int) [function]
                       | bregxSecond(Int, Operand, Int) [function]
                       | typedFirst(ByteCode, Operand, Int) [function]
                       | typedSecond(Int, Operand, Int) [function]
  rule bregxFirst(B, operand(R, P), A) => bregxSecond(R, readLEB(B, P, true), A)
  rule bregxFirst(_, noOperand, _) => noInstruction
  rule bregxSecond(R, operand(D, NEXT), A) => instruction(normalize(DW_OP_bregx R D, A), NEXT)
  rule bregxSecond(_, noOperand, _) => noInstruction
  rule typedFirst(B, operand(SIZE, P), A) => typedSecond(SIZE, readLEB(B, P, false), A)
  rule typedFirst(_, noOperand, _) => noInstruction
  rule typedSecond(SIZE, operand(T, NEXT), A) => instruction(normalize(DW_OP_deref_type SIZE T, A), NEXT)
  rule typedSecond(_, noOperand, _) => noInstruction

  syntax Instruction ::= constTypeReference(ByteCode, Operand, ByteOrder) [function]
                       | constTypeSize(ByteCode, Int, Operand) [function]
                       | regTypeReference(ByteCode, Operand) [function]
                       | regTypeFinish(Int, Operand) [function]
  rule constTypeReference(B, operand(T, P), E) => constTypeSize(B, T, readFixed(B, P, 1, E, false))
  rule constTypeReference(_, noOperand, _) => noInstruction
  rule constTypeSize(B, T, operand(SIZE, P)) =>
    instruction(constTypeOp(T, codeBlock(B, P, SIZE)), P +Int SIZE)
    requires P +Int SIZE <=Int byteLength(B)
  rule constTypeSize(_, _, _) => noInstruction [owise]
  rule regTypeReference(B, operand(R, P)) => regTypeFinish(R, readLEB(B, P, false))
  rule regTypeReference(_, noOperand) => noInstruction
  rule regTypeFinish(R, operand(T, NEXT)) => instruction(regvalTypeOp(R, T), NEXT)
  rule regTypeFinish(_, noOperand) => noInstruction
endmodule
