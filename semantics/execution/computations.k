requires "floating.k"

// Integer/floating-point calculations and conversions only compute values; they do not read configuration cells or change the PC or stack.
// An unmet precondition returns noInt: no normal calculation result, not an error classification.
module DWARF-COMPUTATIONS
  imports DWARF-FLOATING

  // The effective width of g is A; a base type uses its own W, not its storage size in bytes.
  // Type identity does not affect numeric interpretation but is preserved by core rules; well-formed inputs ensure positive widths.
  syntax Int ::= width(Ty, Int) [function, symbol(typeWidth(_,_)_DWARF-COMPUTATIONS_Int_Ty_Int)]
  rule width(g, A) => A
  rule width(base(_, _, W, _), _) => W
  syntax Bool ::= signedType(Ty) [function]
  rule signedType(g) => false
  rule signedType(base(_, E, _, _)) => signedEncoding(E)

  // Ordinary operands follow their base-type encoding; generic operands use unsigned bit patterns.
  // Shift counts and plus_uconst immediates use this interpretation; abs/neg/div select a signed view separately.
  syntax Int ::= operandValue(Int, Ty, Int) [function]
  rule operandValue(N, g, A) => bits(N, A)
  rule operandValue(N, base(ID, E, W, B), _) => interpret(N, base(ID, E, W, B))

  // In conversions, reference 0 denotes the address-width generic type, not a type-table entry.
  syntax OptionalType ::= resolveType(Map, Int) [function]
  rule resolveType(_, 0) => someType(g)
  rule resolveType(TS, REF) => lookupType(TS, REF) requires REF >Int 0
  rule resolveType(_, REF) => noType requires REF <Int 0
  syntax Ty ::= getType(OptionalType) [function]
  rule getType(someType(T)) => T

  // Sections 2.5.1.1/2: explicit base types preserve identity; reference 0 does not denote generic in these two operations.
  syntax OptionalValue ::= constantValue(ByteBlock, ByteOrder, OptionalType) [function]
                         | registerTypedValue(OptionalInt, OptionalType, Int) [function]
  rule constantValue(B, ORDER, someType(base(ID, ENC, W, SIZE))) =>
    someValue(val(interpret(blockUnsigned(B, ORDER), base(ID, ENC, W, SIZE)), base(ID, ENC, W, SIZE)))
    requires supportedType(base(ID, ENC, W, SIZE)) andBool blockLength(B) ==Int SIZE
  rule constantValue(_, _, _) => noValue [owise]
  rule registerTypedValue(someInt(N), someType(base(ID, ENC, W, SIZE)), RW) =>
    someValue(val(interpret(N, base(ID, ENC, W, SIZE)), base(ID, ENC, W, SIZE)))
    requires supportedType(base(ID, ENC, W, SIZE)) andBool W <=Int RW
  rule registerTypedValue(_, _, _) => noValue [owise]

  // Section 2.5.1.6 specifies target-type conversion, not the earlier project restriction against out-of-range results.
  // Integer narrowing keeps the target low bits and interprets them as two's complement where appropriate. Section 2.5.1 leaves generic signedness unspecified;
  // this model chooses an unsigned source view for conversion and a nonnegative bit-pattern representative for a generic target.
  // This is an explicit consumer choice; a different consumer choice alone does not make DWARF invalid.
  // Boolean conversion remains undefined pending a separate decision; do not silently normalize or truncate it.
  syntax Bool ::= booleanType(Ty) [function]
                | represents(Int, Ty, Int) [function]
  rule booleanType(g) => false
  rule booleanType(base(_, E, _, _)) => E ==String "DW_ATE_boolean"
  rule represents(N, T, A) => fitsSigned(N, width(T, A)) requires signedType(T) andBool width(T, A) <=Int 4096
  rule represents(N, T, A) => fitsUnsigned(N, width(T, A)) requires notBool signedType(T) andBool width(T, A) <=Int 4096
  // For very large DIE widths, compare the bits actually required by the value rather than allocating 2^W to validate zero.
  // 4096 selects the checking algorithm, not a type-width limit; both checks define the same mathematical range.
  rule represents(N, T, A) => fitsByBits(N, width(T, A)) requires notBool signedType(T) andBool width(T, A) >Int 4096
  rule represents(N, T, A) => fitsByBits(N, width(T, A) -Int 1) requires signedType(T) andBool N >=Int 0 andBool width(T, A) >Int 4096
  rule represents(N, T, A) => fitsByBits(0 -Int N -Int 1, width(T, A) -Int 1) requires signedType(T) andBool N <Int 0 andBool width(T, A) >Int 4096
  syntax Bool ::= fitsByBits(Int, Int) [function]
  rule fitsByBits(0, W) => W >=Int 0
  rule fitsByBits(N, W) => log2Int(N) <Int W requires N >Int 0
  rule fitsByBits(N, _) => false requires N <Int 0
  syntax OptionalInt ::= convert(Int, Ty, OptionalType, Int) [function, symbol(convertInteger(_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_Int_Ty_OptionalType_Int)]
                       | reinterpret(Int, Ty, OptionalType, Int) [function, symbol(reinterpretInteger(_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_Int_Ty_OptionalType_Int)]
  rule convert(N, SOURCE, someType(TARGET), A) => integerConversion(conversionOperand(N, SOURCE, A), TARGET, A)
    requires integerType(SOURCE) andBool integerType(TARGET)
      andBool notBool booleanType(SOURCE) andBool notBool booleanType(TARGET)
  syntax Int ::= conversionOperand(Int, Ty, Int) [function]
  rule conversionOperand(N, g, A) => bits(N, A)
  rule conversionOperand(N, base(ID, E, W, B), A) => operandValue(N, base(ID, E, W, B), A)
  syntax OptionalInt ::= integerConversion(Int, Ty, Int) [function]
  // Keep an already representable mathematical integer directly, also avoiding construction of 2^W for very large DIE widths.
  rule integerConversion(N, T, A) => someInt(N) requires represents(N, T, A)
  rule integerConversion(N, T, A) => someInt(resultValue(N, T, A, false)) requires notBool represents(N, T, A)
  // For floating-point types, Int carries bits; conversions use exact rationals, and conversion to an integer truncates toward zero.
  rule convert(N, SOURCE, someType(base(_, "DW_ATE_float", W, _)), A) =>
    someInt(fpFromInteger(conversionOperand(N, SOURCE, A), W))
    requires integerType(SOURCE) andBool notBool booleanType(SOURCE) andBool floatWidth(W)
  rule convert(N, base(_, "DW_ATE_float", W1, _), someType(base(_, "DW_ATE_float", W2, _)), _) =>
    someInt(fpEncode(fpDecode(N, W1), W2))
    requires floatWidth(W1) andBool floatWidth(W2) andBool W1 =/=Int W2
  rule convert(N, base(_, "DW_ATE_float", W, _), someType(base(_, "DW_ATE_float", W, _)), _) => someInt(N)
    requires floatWidth(W)
  rule convert(N, base(_, "DW_ATE_float", W, _), someType(TARGET), A) =>
    checkedFloatInteger(fpToInteger(fpDecode(N, W)), TARGET, A)
    requires floatWidth(W) andBool integerType(TARGET) andBool notBool booleanType(TARGET)
  syntax OptionalInt ::= checkedFloatInteger(OptionalInt, Ty, Int) [function]
  rule checkedFloatInteger(someInt(N), T, A) => someInt(N) requires represents(N, T, A)
  rule checkedFloatInteger(_, _, _) => noInt [owise]
  rule convert(_, _, _, _) => noInt [owise]
  // Reinterpret requires equal effective bit widths, not equal storage sizes in bytes.
  // A base-type target selects its representative by encoding; a generic target preserves N, including negative representatives.
  rule reinterpret(N, SOURCE, someType(g), A) => someInt(N)
    requires supportedType(SOURCE) andBool width(SOURCE, A) ==Int A
  rule reinterpret(N, SOURCE, someType(base(ID, E, W, B)), A) => someInt(interpret(N, base(ID, E, W, B)))
    requires supportedType(SOURCE) andBool supportedType(base(ID, E, W, B)) andBool width(SOURCE, A) ==Int W
  rule reinterpret(_, _, _, _) => noInt [owise]

  // The final Bool selects only the generic result representative: true for signed, false for unsigned.
  // Base-type results always follow their encoding; Boolean results are not automatically normalized to 0/1.
  syntax Int ::= resultValue(Int, Ty, Int, Bool) [function]
  rule resultValue(N, g, A, true) => signedBits(N, A)
  rule resultValue(N, g, A, false) => bits(N, A)
  rule resultValue(N, base(ID, E, W, B), _, _) => interpret(N, base(ID, E, W, B))

  // Unary calculations preserve the attached type. abs/neg interpret the input bits as signed even for unsigned base types.
  // abs/neg of the minimum signed value have no result; truncating an unrepresentable mathematical result must not imply success.
  syntax OptionalInt ::= integerUop(UnaryOperator, Int, Ty, Int) [function, symbol(integerUnary(_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_UnaryOperator_Int_Ty_Int)]
  rule integerUop(absOp, N, T, A) =>
    someInt(resultValue(absInt(signedBits(N, width(T, A))), T, A, true))
    requires signedBits(N, width(T, A)) =/=Int (0 -Int (2 ^Int (width(T, A) -Int 1)))
  rule integerUop(negOp, N, T, A) =>
    someInt(resultValue(0 -Int signedBits(N, width(T, A)), T, A, true))
    requires signedBits(N, width(T, A)) =/=Int (0 -Int (2 ^Int (width(T, A) -Int 1)))
  // Truncate the two's-complement bitwise complement to W bits; K's unbounded integers are not finite bit strings.
  rule integerUop(notOp, N, T, A) =>
    someInt(resultValue(~Int bits(N, width(T, A)), T, A, false))
  // X must fit an unsigned W-bit source field of the operand type; interpret it, add it to N, and wrap the result.
  rule integerUop(plusUconstOp(X), N, T, A) =>
    someInt(resultValue(operandValue(N, T, A) +Int operandValue(X, T, A), T, A, false))
    requires fitsUnsigned(X, width(T, A))
  rule integerUop(_, _, _, _) => noInt [owise]

  // Arguments follow pop order: N1 is the top, N2 is below it; subtraction/division compute N2 OP N1.
  // The low W bits of addition/subtraction/multiplication do not depend on representative choice; source views still follow the type explicitly.
  syntax OptionalInt ::= integerBop(BinaryOperator, Int, Int, Ty, Int) [function, symbol(integerBinary(_,_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_BinaryOperator_Int_Int_Ty_Int)]
  rule integerBop(plusOp, N1, N2, T, A) =>
    someInt(resultValue(operandValue(N2, T, A) +Int operandValue(N1, T, A), T, A, false))
  rule integerBop(minusOp, N1, N2, T, A) =>
    someInt(resultValue(operandValue(N2, T, A) -Int operandValue(N1, T, A), T, A, false))
  rule integerBop(mulOp, N1, N2, T, A) =>
    someInt(resultValue(operandValue(N2, T, A) *Int operandValue(N1, T, A), T, A, false))

  // div always uses signed division; /Int truncates toward zero. The only signed W-bit quotient overflow is MIN/-1.
  // Check only total comparisons in the precondition; perform division afterwards, avoiding premature evaluation of /Int 0.
  rule integerBop(divOp, N1, N2, T, A) =>
    someInt(resultValue(signedBits(N2, width(T, A)) /Int signedBits(N1, width(T, A)), T, A, true))
    requires signedBits(N1, width(T, A)) =/=Int 0
      andBool notBool (signedBits(N2, width(T, A)) ==Int (0 -Int (2 ^Int (width(T, A) -Int 1)))
                       andBool signedBits(N1, width(T, A)) ==Int -1)

  // mod follows the source type: signed uses the truncated remainder %Int; unsigned/generic uses an unsigned view.
  // Only a nonzero divisor is required; MIN % -1 = 0 remains defined and does not inherit div's quotient-overflow restriction.
  rule integerBop(modOp, N1, N2, T, A) =>
    someInt(resultValue(signedBits(N2, width(T, A)) %Int signedBits(N1, width(T, A)), T, A, false))
    requires signedType(T) andBool signedBits(N1, width(T, A)) =/=Int 0
  rule integerBop(modOp, N1, N2, T, A) =>
    someInt(resultValue(bits(N2, width(T, A)) %Int bits(N1, width(T, A)), T, A, false))
    requires notBool signedType(T) andBool bits(N1, width(T, A)) =/=Int 0

  // Bitwise operations act on two W-bit patterns and preserve the low W bits and the original type.
  rule integerBop(andOp, N1, N2, T, A) =>
    someInt(resultValue(bits(N2, width(T, A)) &Int bits(N1, width(T, A)), T, A, false))
  rule integerBop(orOp, N1, N2, T, A) =>
    someInt(resultValue(bits(N2, width(T, A)) |Int bits(N1, width(T, A)), T, A, false))
  rule integerBop(xorOp, N1, N2, T, A) =>
    someInt(resultValue(bits(N2, width(T, A)) xorInt bits(N1, width(T, A)), T, A, false))

  // Counts follow the original type, with unsigned counts for generic; all three shifts require 0 <= count < W.
  // shr interprets data as unsigned, shra as signed; >>Int itself is an arithmetic right shift.
  rule integerBop(shlOp, N1, N2, T, A) =>
    someInt(resultValue(bits(N2, width(T, A)) <<Int operandValue(N1, T, A), T, A, false))
    requires 0 <=Int operandValue(N1, T, A) andBool operandValue(N1, T, A) <Int width(T, A)
  rule integerBop(shrOp, N1, N2, T, A) =>
    someInt(resultValue(bits(N2, width(T, A)) >>Int operandValue(N1, T, A), T, A, false))
    requires 0 <=Int operandValue(N1, T, A) andBool operandValue(N1, T, A) <Int width(T, A)
  rule integerBop(shraOp, N1, N2, T, A) =>
    someInt(resultValue(signedBits(N2, width(T, A)) >>Int operandValue(N1, T, A), T, A, true))
    requires 0 <=Int operandValue(N1, T, A) andBool operandValue(N1, T, A) <Int width(T, A)
  rule integerBop(_, _, _, _, _) => noInt [owise]

  // Comparisons use a different generic view: g and signed base types are compared as signed integers.
  // Interpret the bits before comparing; for example, -1:g and 255:g are equal when A=8.
  syntax Int ::= comparisonValue(Int, Ty, Int) [function]
  rule comparisonValue(N, g, A) => signedBits(N, A)
  rule comparisonValue(N, base(ID, E, W, B), _) => interpret(N, base(ID, E, W, B))
  syntax Bool ::= relation(CompareOperator, Int, Int) [function]
  rule relation(eqOp, L, R) => L ==Int R
  rule relation(neOp, L, R) => L =/=Int R
  rule relation(geOp, L, R) => L >=Int R
  rule relation(gtOp, L, R) => L >Int R
  rule relation(leOp, L, R) => L <=Int R
  rule relation(ltOp, L, R) => L <Int R
  syntax Int ::= indicator(Bool) [function, symbol(truthValue(_)_DWARF-COMPUTATIONS_Int_Bool)]
  rule indicator(true) => 1
  rule indicator(false) => 0
  // The core first matches equal operand types; this helper computes only 0/1 and does not retain the operand type in the result.
  syntax OptionalInt ::= integerCmp(CompareOperator, Int, Int, Ty, Int) [function, symbol(integerCompare(_,_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_CompareOperator_Int_Int_Ty_Int)]
  rule integerCmp(CMP, N1, N2, T, A) =>
    someInt(indicator(relation(CMP, comparisonValue(N2, T, A), comparisonValue(N1, T, A))))
  // Dispatch each operation family to integer or floating-point pure functions by type, without adding an execution phase.
  syntax OptionalInt ::= uop(UnaryOperator, Int, Ty, Int) [function, symbol(calcUnary(_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_UnaryOperator_Int_Ty_Int)]
                       | bop(BinaryOperator, Int, Int, Ty, Int) [function, symbol(calcBinary(_,_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_BinaryOperator_Int_Int_Ty_Int)]
                       | cmp(CompareOperator, Int, Int, Ty, Int) [function, symbol(calcCompare(_,_,_,_,_)_DWARF-COMPUTATIONS_OptionalInt_CompareOperator_Int_Int_Ty_Int)]
  rule uop(U, N, T, A) => integerUop(U, N, T, A) requires integerType(T)
  rule uop(U, N, base(_, "DW_ATE_float", W, _), _) => floatUop(U, N, W) requires floatWidth(W)
  rule uop(_, _, _, _) => noInt [owise]
  rule bop(B, N1, N2, T, A) => integerBop(B, N1, N2, T, A) requires integerType(T)
  rule bop(B, N1, N2, base(_, "DW_ATE_float", W, _), _) => floatBop(B, N1, N2, W) requires floatWidth(W)
  rule bop(_, _, _, _, _) => noInt [owise]
  rule cmp(CMP, N1, N2, T, A) => integerCmp(CMP, N1, N2, T, A) requires integerType(T)
  rule cmp(CMP, N1, N2, base(_, "DW_ATE_float", W, _), _) =>
    someInt(indicator(fpRelation(CMP, fpOrder(fpDecode(N2, W), fpDecode(N1, W))))) requires floatWidth(W)
  rule cmp(_, _, _, _, _) => noInt [owise]

endmodule
