requires "computations.k"

// Fixed execution input E: operations and operands are decoded; code queries do not depend on runtime context.
// The final ByteBlock preserves raw-byte identity only; text or direct inputs use .Bytes.
// It is audit data and takes no part in operation, boundary, or computation queries.
module DWARF-EXPRESSION
  imports DWARF-COMPUTATIONS

  syntax Operation ::= addrxOp(Int) [symbol(addressIndex(_)_DWARF-EXPRESSION_Operation_Int)]
                     | constxOp(Int) [symbol(constantIndex(_)_DWARF-EXPRESSION_Operation_Int)]
                     | "pushObjectAddressOp" [symbol(objectAddress_DWARF-EXPRESSION_Operation)]
                     | constOp(Int) [symbol(constant(_)_DWARF-EXPRESSION_Operation_Int)]
                     | bregxOp(Int, Int) [symbol(breg(_,_)_DWARF-EXPRESSION_Operation_Int_Int)]
                     | fbregOp(Int) [symbol(fbreg(_)_DWARF-EXPRESSION_Operation_Int)]
                    
                     | derefOp(Int) [symbol(deref(_)_DWARF-EXPRESSION_Operation_Int)]
                     | derefTypeOp(Int, Int) [symbol(derefType(_,_)_DWARF-EXPRESSION_Operation_Int_Int)]
                    
                     | pickOp(Int) [symbol(pick(_)_DWARF-EXPRESSION_Operation_Int)]
                     | "dropOp" [symbol(drop_DWARF-EXPRESSION_Operation)]
                     | "swapOp" [symbol(swap_DWARF-EXPRESSION_Operation)]
                     | "rotOp" [symbol(rot_DWARF-EXPRESSION_Operation)]
                     | "unavailableOperation"
                    
                     | "noOperation"
                    
                     | unaryOp(UnaryOperator) [symbol(unary(_)_DWARF-EXPRESSION_Operation_UnaryOperator)]
                     | binaryOp(BinaryOperator) [symbol(binary(_)_DWARF-EXPRESSION_Operation_BinaryOperator)]
                     | compareOp(CompareOperator) [symbol(compare(_)_DWARF-EXPRESSION_Operation_CompareOperator)]
                    
                     | "stackValueOp" [symbol(stackValue_DWARF-EXPRESSION_Operation)]
                     | regxOp(Int) [symbol(register(_)_DWARF-EXPRESSION_Operation_Int)]
                    
                     | "nopOp" [symbol(nop_DWARF-EXPRESSION_Operation)]
                     | skipOp(Int) [symbol(skip(_)_DWARF-EXPRESSION_Operation_Int)]
                     | braOp(Int) [symbol(bra(_)_DWARF-EXPRESSION_Operation_Int)]
                    
                     | implicitValueOp(ByteBlock) [symbol(implicitBytes(_)_DWARF-EXPRESSION_Operation_ByteBlock)]
                     | pieceOp(Int) [symbol(piece(_)_DWARF-EXPRESSION_Operation_Int)]
                     | bitPieceOp(Int, Int)
                    
                     | convertOp(Int) [symbol(convertTo(_)_DWARF-EXPRESSION_Operation_Int)]
                     | reinterpretOp(Int) [symbol(reinterpretAs(_)_DWARF-EXPRESSION_Operation_Int)]
                     | "callFrameCfaOp" [symbol(callFrameCFA_DWARF-EXPRESSION_Operation)]
                    
                     | constTypeOp(Int, ByteBlock) [symbol(typedConstant(_,_)_DWARF-EXPRESSION_Operation_Int_ByteBlock)]
                     | regvalTypeOp(Int, Int) [symbol(typedRegister(_,_)_DWARF-EXPRESSION_Operation_Int_Int)]
                    
                     | callUnitOp(Int) [symbol(callUnit(_)_DWARF-EXPRESSION_Operation_Int)]
                     | callRefOp(Int) [symbol(callSection(_)_DWARF-EXPRESSION_Operation_Int)]
                     | entryValueOp(DecodedExpression) [symbol(entryValue(_)_DWARF-EXPRESSION_Operation_DecodedExpression)]
                    
                     | "formTlsAddressOp" [symbol(tlsAddress_DWARF-EXPRESSION_Operation)]
                     | xderefOp(Int) [symbol(xderef(_)_DWARF-EXPRESSION_Operation_Int)]
                     | xderefTypeOp(Int, Int) [symbol(xderefType(_,_)_DWARF-EXPRESSION_Operation_Int_Int)]
                    
                     | implicitPointerOp(Int, Int) [symbol(implicitPointer(_,_)_DWARF-EXPRESSION_Operation_Int_Int)]


  syntax DecodedExpression ::= decoded(Int, Int, Instructions, ByteBlock) [symbol(decodedExpression)]
  syntax Instructions ::= ".Instructions" [symbol(emptyInstructions)]
                        | codeAt(Int, Operation, Int, Instructions) [symbol(decodedInstruction)]
  syntax Instruction ::= instruction(Operation, Int) | "noInstruction"
  syntax Int ::= inputStart(DecodedExpression) [function]
               | inputEnd(DecodedExpression) [function]
  rule inputStart(decoded(START, _, _, _)) => START
  rule inputEnd(decoded(_, END, _, _)) => END
  syntax Bool ::= emptyInput(DecodedExpression) [function]
  rule emptyInput(decoded(START, END, _, _)) => START ==Int END

  syntax Instruction ::= instructionAt(DecodedExpression, Int) [function]
                       | lookupInstruction(Instructions, Int) [function]
  rule instructionAt(decoded(_, _, CODE, _), P) => lookupInstruction(CODE, P)
  rule lookupInstruction(codeAt(P, OP, NEXT, _), P) => instruction(OP, NEXT)
  rule lookupInstruction(codeAt(_, _, _, REST), P) => lookupInstruction(REST, P) [owise]
  rule lookupInstruction(.Instructions, _) => noInstruction
  syntax Operation ::= opAt(DecodedExpression, Int) [function, symbol(operationAt(_,_)_DWARF-EXPRESSION_Operation_DecodedExpression_Int)]
                     | instructionOperation(Instruction) [function]
  rule opAt(E, P) => instructionOperation(instructionAt(E, P))
  rule instructionOperation(instruction(OP, _)) => OP
  rule instructionOperation(noInstruction) => noOperation
  syntax Int ::= next(DecodedExpression, Int) [function, symbol(nextPosition(_,_)_DWARF-EXPRESSION_Int_DecodedExpression_Int)]
               | instructionNext(Instruction) [function]
  rule next(E, P) => instructionNext(instructionAt(E, P))
  rule instructionNext(instruction(_, NEXT)) => NEXT

  // The start, known next boundaries, and original END are valid; an undecodable suffix creates no guessed boundaries.
  syntax Bool ::= isBoundary(DecodedExpression, Int) [function]
                | instructionBoundary(Instructions, Int) [function]
  rule isBoundary(decoded(START, END, CODE, _), P) =>
    P ==Int START orBool P ==Int END orBool instructionBoundary(CODE, P)
  rule instructionBoundary(codeAt(P, _, _, _), P) => true
  rule instructionBoundary(codeAt(_, _, P, _), P) => true
  rule instructionBoundary(codeAt(_, _, _, REST), P) => instructionBoundary(REST, P) [owise]
  rule instructionBoundary(.Instructions, _) => false
endmodule
