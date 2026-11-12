requires "decoding.k"

// Pure frontend: structural checks, normalization of complete operations, decodable-prefix preparation, and read-only metadata preparation.
// It does not evaluate operations, query live processes, introduce an execution phase, or consume execution rewrites.
module DWARF-FRONTEND
  imports DWARF-DECODING

  syntax Bool ::= isBoundary(Program, Int, Context) [function]
  rule isBoundary(E, P, C) => isBoundary(prepareProgram(E, encodingOf(C)), P)

  syntax DecodedExpression ::= prepareProgram(Program, Encoding) [function]
  rule prepareProgram(E:TextProgram, ENC) =>
    decoded(inputStart(E), inputEnd(E), prepareText(E, ENC), .Bytes)
  rule prepareProgram(E:HexProgram, ENC) =>
    decoded(0, inputEnd(E), preparePrefix(E, 0, ENC), sourceBytes(E))
  rule prepareProgram(rawBytes(B), ENC) =>
    decoded(0, blockLength(B), preparePrefix(rawBytes(B), 0, ENC), B)
  syntax ByteBlock ::= sourceBytes(HexProgram) [function]
  rule sourceBytes(.HexProgram) => .Bytes
  rule sourceBytes((B:HexByte REST:HexProgram)) => byteCons(byteNumber(B), sourceBytes(REST))
  syntax Instructions ::= prepareText(TextProgram, Encoding) [function]
                        | preparePrefix(Program, Int, Encoding) [function]
                        | prepareInstruction(Program, Int, Encoding, Instruction) [function]
  rule prepareText(_:Literal, _) => .Instructions
  rule prepareText((P:Literal : OP:Op, REST:TextProgram), encoding(A, E, OS)) =>
    codeAt(number(P), prepareOperation(normalize(OP, A), encoding(A, E, OS)),
           inputStart(REST), prepareText(REST, encoding(A, E, OS)))
  rule preparePrefix(E, P, ENC) => prepareInstruction(E, P, ENC, sourceInstructionAt(E, P, ENC))
    requires P <Int inputEnd(E)
  rule preparePrefix(E, P, _) => .Instructions requires P >=Int inputEnd(E)
  rule prepareInstruction(E, P, ENC, instruction(OP, NEXT)) =>
    codeAt(P, prepareOperation(OP, ENC), NEXT, preparePrefix(E, NEXT, ENC))
  rule prepareInstruction(_, _, _, noInstruction) => .Instructions
  syntax Operation ::= prepareOperation(Operation, Encoding) [function]
  rule prepareOperation(sourceEntry(B), ENC) => entryValueOp(prepareProgram(rawBytes(B), ENC))
  rule prepareOperation(OP, _) => OP [owise]

  // Prepare each supplied DIE once; references remain references, and the actual execution budget bounds recursive calls.
  syntax Context ::= prepareContext(Context) [function]
  rule prepareContext(ctx(A, E, TS, RS, M, FB, CFA, ARCH, DA, BIAS, OBJ)) =>
    ctx(A, E, prepareTypes(TS, E), RS, M, FB, CFA, ARCH, DA, BIAS, OBJ)
  syntax Map ::= prepareTypes(Map, ByteOrder) [function]
               | prepareRuntime(Map, ByteOrder) [function]
               | prepareRuntimeDIEs(Map, ByteOrder) [function]
               | prepareRuntimeEntry(Map) [function]
               | prepareDIEs(Map, ByteOrder) [function]
  rule prepareTypes(("runtime" |-> RT:Map) REST:Map, E) =>
    ("runtime" |-> prepareRuntime(RT, E)) REST
  rule prepareTypes(TS, _) => TS [owise]
  rule prepareRuntime(RT, E) => prepareRuntimeEntry(prepareRuntimeDIEs(RT, E))
  rule prepareRuntimeDIEs(("dies" |-> DS:Map) REST:Map, E) =>
    ("dies" |-> prepareDIEs(DS, E)) REST
  rule prepareRuntimeDIEs(RT, _) => RT [owise]
  rule prepareRuntimeEntry(("entry" |-> C:Context) REST:Map) =>
    ("entry" |-> prepareContext(C)) REST
  rule prepareRuntimeEntry(RT) => RT [owise]
  rule prepareDIEs(.Map, _) => .Map
  rule prepareDIEs((R:Int |-> (dieBody(B, A, UNIT, OS, TS, DA, CONST, SIZE, TREF) #as D)) REST:Map, E) =>
    (R |-> preparedDIE(D, prepareProgram(rawBytes(B), encoding(A, E, OS)))) prepareDIEs(REST, E)
endmodule
