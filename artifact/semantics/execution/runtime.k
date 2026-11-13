requires "composition.k"

// Metadata queries are read-only; procedure and entry-block evaluation use direct configuration rules in core.k.
module DWARF-RUNTIME
  imports DWARF-COMPOSITION

  syntax Int ::= referencedDIE(Operation, Context) [function]
  rule referencedDIE(callUnitOp(R), C) => runtimeNumber(C, "unit_offset", 0) +Int R
  rule referencedDIE(callRefOp(R), _) => R
  syntax DIEBody ::= operationDIE(DecodedExpression, Int, Context) [function]
  rule operationDIE(E, P, C) => getDIE(lookupDIE(runtimeTable(C, "dies"), referencedDIE(opAt(E, P), C)))
  syntax Bool ::= isCall(Operation) [function]
  rule isCall(callUnitOp(_)) => true
  rule isCall(callRefOp(_)) => true
  rule isCall(_) => false [owise]
  syntax DecodedExpression ::= dieCode(DIEBody) [function]
  rule dieCode(preparedDIE(_, E)) => E
  syntax Context ::= dieContext(Context, DIEBody) [function]
  // Registers, memory, frame data, and load bias come from the caller's interface; CU/types/address tables come from the called DIE.
  // runtime retains all referenced objects; switching CUs preserves repeated-call and cross-CU reference lookup.
  rule dieContext(C, preparedDIE(D, _)) => dieContext(C, D)
  rule dieContext(ctx(_, ORDER, _, RS, M, FB, CFA, ARCH, _, BIAS, OBJ) #as C,
                  dieBody(_, A, UNIT, OS, TYPES, DA, _, _, _)) =>
    ctx(A, ORDER, TYPES ("runtime" |-> (runtimeData(C)["unit_offset" <- UNIT]["offset_size" <- OS])),
        RS, M, FB, CFA, ARCH, DA, BIAS, OBJ)

endmodule
