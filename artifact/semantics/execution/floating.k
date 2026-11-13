requires "../domains/dwarf-domains.k"

// For floating-point stack values, Int carries raw bits, independent of host floating point or Python calculations.
// Pure functions decode exact binary rationals, compute, and round to the target format with roundTiesToEven.
// Support binary32/binary64/x87 binary80/binary128; the 80-bit format stores its integer bit explicitly.
module DWARF-FLOATING
  imports DWARF-DOMAINS

  syntax UnaryOperator ::= "absOp" | "negOp" | "notOp" | plusUconstOp(Int) [symbol(addUnsigned(_)_DWARF-FLOATING_UnaryOperator_Int)]
  syntax BinaryOperator ::= "andOp" | "divOp" | "minusOp" [symbol(subOp_DWARF-FLOATING_BinaryOperator)] | "modOp" | "mulOp"
                          | "orOp" | "plusOp" [symbol(addOp_DWARF-FLOATING_BinaryOperator)] | "shlOp" | "shrOp" | "shraOp" | "xorOp"
  syntax CompareOperator ::= "eqOp" | "geOp" | "gtOp" | "leOp" | "ltOp" | "neOp"

  syntax Bool ::= floatType(Ty) [function]
                | floatWidth(Int) [function]
  rule floatType(g) => false
  rule floatType(base(_, ENC, _, _)) => ENC ==String "DW_ATE_float"
  rule floatWidth(W) => W ==Int 32 orBool W ==Int 64 orBool W ==Int 80 orBool W ==Int 128
  syntax Int ::= fpPrecision(Int) [function]
               | fpExponentWidth(Int) [function]
               | fpFractionWidth(Int) [function]
               | fpBias(Int) [function]
  rule fpPrecision(32) => 24
  rule fpPrecision(64) => 53
  rule fpPrecision(80) => 64
  rule fpPrecision(128) => 113
  rule fpExponentWidth(32) => 8
  rule fpExponentWidth(64) => 11
  rule fpExponentWidth(80) => 15
  rule fpExponentWidth(128) => 15
  rule fpFractionWidth(W) => W -Int 1 -Int fpExponentWidth(W)
  rule fpBias(W) => (2 ^Int (fpExponentWidth(W) -Int 1)) -Int 1

  // fpFinite(S,M,E) denotes (-1)^S * M * 2^E, with S in {0,1} and M >= 0; zero retains its sign.
  // Operations produce a fixed quiet NaN; reinterpret and same-width convert preserve its payload.
  syntax FloatParts ::= fpFinite(Int, Int, Int) | fpInfinity(Int) | "fpNaN"
  syntax FloatParts ::= fpDecode(Int, Int) [function]
                      | fpDecodeFields(Int, Int, Int, Int) [function]
  rule fpDecode(N, W) => fpDecodeFields(bits(N, W) >>Int (W -Int 1),
    (N >>Int fpFractionWidth(W)) modInt (2 ^Int fpExponentWidth(W)), bits(N, fpFractionWidth(W)), W)
    requires floatWidth(W)
  rule fpDecodeFields(S, 0, F, W) => fpFinite(S, F, 1 -Int fpBias(W) -Int (fpPrecision(W) -Int 1))
  rule fpDecodeFields(S, E, F, W) => fpFinite(S, fpSignificand(F, W), E -Int fpBias(W) -Int (fpPrecision(W) -Int 1))
    requires 0 <Int E andBool E <Int (2 ^Int fpExponentWidth(W)) -Int 1
  rule fpDecodeFields(S, E, F, W) => fpInfinity(S)
    requires E ==Int (2 ^Int fpExponentWidth(W)) -Int 1 andBool F ==Int fpInfinityFraction(W)
  rule fpDecodeFields(_, E, F, W) => fpNaN
    requires E ==Int (2 ^Int fpExponentWidth(W)) -Int 1 andBool F =/=Int fpInfinityFraction(W)
  syntax Int ::= fpSignificand(Int, Int) [function]
               | fpInfinityFraction(Int) [function]
  rule fpSignificand(F, 80) => F
  rule fpSignificand(F, W) => (2 ^Int (fpPrecision(W) -Int 1)) +Int F requires W =/=Int 80
  rule fpInfinityFraction(80) => 2 ^Int 63
  rule fpInfinityFraction(W) => 0 requires W =/=Int 80

  // The denominator is positive. Integer-domain shifts, quotients, and remainders identify exact halfway cases and even low bits.
  syntax Int ::= fpRoundQuotient(Int, Int) [function]
               | fpRoundScaled(Int, Int, Int) [function]
               | fpRatioLog(Int, Int) [function]
               | fpRatioLogAt(Int, Int, Int) [function]
  rule fpRoundQuotient(N, D) => N /Int D
    requires 2 *Int (N modInt D) <Int D orBool
      (2 *Int (N modInt D) ==Int D andBool (N /Int D) modInt 2 ==Int 0)
  rule fpRoundQuotient(N, D) => (N /Int D) +Int 1 [owise]
  rule fpRoundScaled(N, D, S) => fpRoundQuotient(N <<Int S, D) requires S >=Int 0
  rule fpRoundScaled(N, D, S) => fpRoundQuotient(N, D <<Int (0 -Int S)) requires S <Int 0
  rule fpRatioLog(N, D) => fpRatioLogAt(N, D, log2Int(N) -Int log2Int(D))
  rule fpRatioLogAt(N, D, L) => L -Int 1
    requires (L >=Int 0 andBool N <Int (D <<Int L)) orBool
      (L <Int 0 andBool (N <<Int (0 -Int L)) <Int D)
  rule fpRatioLogAt(_, _, L) => L [owise]

  syntax Int ::= fpRound(Int, Int, Int, Int, Int) [function]
               | fpQuantize(Int, Int, Int, Int, Int, Int) [function]
               | fpRounded(Int, Int, Int, Int) [function]
               | fpPack(Int, Int, Int, Int) [function]
               | fpInfinityBits(Int, Int) [function]
               | fpNaNBits(Int) [function]
  rule fpInfinityBits(S, W) => (S <<Int (W -Int 1)) +Int
    (((2 ^Int fpExponentWidth(W)) -Int 1) <<Int fpFractionWidth(W)) +Int fpInfinityFraction(W)
  rule fpNaNBits(W) => fpInfinityBits(0, W) +Int (2 ^Int (fpPrecision(W) -Int 2))
  rule fpRound(S, 0, _, _, W) => S <<Int (W -Int 1)
  rule fpRound(S, N, D, E, W) => fpInfinityBits(S, W)
    requires N >Int 0 andBool fpRatioLog(N, D) +Int E >Int fpBias(W)
  rule fpRound(S, N, D, E, W) => fpQuantize(S, N, D, E, W,
    maxInt(1 -Int fpBias(W), fpRatioLog(N, D) +Int E) -Int (fpPrecision(W) -Int 1))
    requires N >Int 0 andBool fpRatioLog(N, D) +Int E <=Int fpBias(W)
  rule fpQuantize(S, N, D, E, W, Q) => fpRounded(S, fpRoundScaled(N, D, E -Int Q), Q, W)
  rule fpRounded(S, M, Q, W) => fpPack(S, M /Int 2, Q +Int 1, W)
    requires M >=Int (2 ^Int fpPrecision(W))
  rule fpRounded(S, M, Q, W) => fpPack(S, M, Q, W) requires M <Int (2 ^Int fpPrecision(W))
  rule fpPack(S, _, Q, W) => fpInfinityBits(S, W) requires Q +Int fpPrecision(W) -Int 1 >Int fpBias(W)
  rule fpPack(S, M, Q, W) => (S <<Int (W -Int 1)) +Int M
    requires M <Int (2 ^Int (fpPrecision(W) -Int 1)) andBool Q +Int fpPrecision(W) -Int 1 <=Int fpBias(W)
  rule fpPack(S, M, Q, W) => (S <<Int (W -Int 1)) +Int
    ((Q +Int fpPrecision(W) -Int 1 +Int fpBias(W)) <<Int fpFractionWidth(W)) +Int fpStoredSignificand(M, W)
    requires M >=Int (2 ^Int (fpPrecision(W) -Int 1))
      andBool Q +Int fpPrecision(W) -Int 1 <=Int fpBias(W)
  syntax Int ::= fpStoredSignificand(Int, Int) [function]
  rule fpStoredSignificand(M, 80) => M
  rule fpStoredSignificand(M, W) => M -Int (2 ^Int (fpPrecision(W) -Int 1)) requires W =/=Int 80

  syntax Int ::= fpEncode(FloatParts, Int) [function]
               | fpFromInteger(Int, Int) [function]
               | fpSign(Int) [function]
               | fpSigned(Int, Int) [function]
  rule fpEncode(fpFinite(S, M, E), W) => fpRound(S, M, 1, E, W)
  rule fpEncode(fpInfinity(S), W) => fpInfinityBits(S, W)
  rule fpEncode(fpNaN, W) => fpNaNBits(W)
  rule fpSign(N) => 1 requires N <Int 0
  rule fpSign(N) => 0 requires N >=Int 0
  rule fpSigned(0, M) => M
  rule fpSigned(1, M) => 0 -Int M
  rule fpFromInteger(N, W) => fpRound(fpSign(N), absInt(N), 1, 0, W)
  syntax OptionalInt ::= fpToInteger(FloatParts) [function]
  rule fpToInteger(fpFinite(S, M, E)) => someInt(fpSigned(S, M <<Int E)) requires E >=Int 0
  rule fpToInteger(fpFinite(S, M, E)) => someInt(fpSigned(S, M >>Int (0 -Int E))) requires E <Int 0
  rule fpToInteger(fpInfinity(_)) => noInt
  rule fpToInteger(fpNaN) => noInt

  syntax FloatParts ::= fpNegate(FloatParts) [function]
                      | fpAdd(FloatParts, FloatParts) [function]
                      | fpSum(Int, Int, Int) [function]
  rule fpNegate(fpFinite(S, M, E)) => fpFinite(1 -Int S, M, E)
  rule fpNegate(fpInfinity(S)) => fpInfinity(1 -Int S)
  rule fpNegate(fpNaN) => fpNaN
  rule fpAdd(fpNaN, _) => fpNaN
  rule fpAdd(_, fpNaN) => fpNaN
  rule fpAdd(fpInfinity(S), fpInfinity(S)) => fpInfinity(S)
  rule fpAdd(fpInfinity(S1), fpInfinity(S2)) => fpNaN requires S1 =/=Int S2
  rule fpAdd(fpInfinity(S), fpFinite(_, _, _)) => fpInfinity(S)
  rule fpAdd(fpFinite(_, _, _), fpInfinity(S)) => fpInfinity(S)
  rule fpAdd(fpFinite(S1, M1, E1), fpFinite(S2, M2, E2)) =>
    fpSum(fpSigned(S1, M1 <<Int (E1 -Int minInt(E1, E2))) +Int
          fpSigned(S2, M2 <<Int (E2 -Int minInt(E1, E2))), minInt(E1, E2), S1 &Int S2)
  rule fpSum(0, E, S) => fpFinite(S, 0, E)
  rule fpSum(N, E, _) => fpFinite(fpSign(N), absInt(N), E) requires N =/=Int 0

  syntax Int ::= fpMultiply(FloatParts, FloatParts, Int) [function]
               | fpDivide(FloatParts, FloatParts, Int) [function]
  rule fpMultiply(fpNaN, _, W) => fpNaNBits(W)
  rule fpMultiply(_, fpNaN, W) => fpNaNBits(W)
  rule fpMultiply(fpInfinity(_), fpFinite(_, 0, _), W) => fpNaNBits(W)
  rule fpMultiply(fpFinite(_, 0, _), fpInfinity(_), W) => fpNaNBits(W)
  rule fpMultiply(fpInfinity(S1), fpInfinity(S2), W) => fpInfinityBits(S1 xorInt S2, W)
  rule fpMultiply(fpInfinity(S1), fpFinite(S2, M, _), W) => fpInfinityBits(S1 xorInt S2, W) requires M >Int 0
  rule fpMultiply(fpFinite(S1, M, _), fpInfinity(S2), W) => fpInfinityBits(S1 xorInt S2, W) requires M >Int 0
  rule fpMultiply(fpFinite(S1, M1, E1), fpFinite(S2, M2, E2), W) => fpRound(S1 xorInt S2, M1 *Int M2, 1, E1 +Int E2, W)
  rule fpDivide(fpNaN, _, W) => fpNaNBits(W)
  rule fpDivide(_, fpNaN, W) => fpNaNBits(W)
  rule fpDivide(fpInfinity(_), fpInfinity(_), W) => fpNaNBits(W)
  rule fpDivide(fpFinite(_, 0, _), fpFinite(_, 0, _), W) => fpNaNBits(W)
  rule fpDivide(fpInfinity(S1), fpFinite(S2, _, _), W) => fpInfinityBits(S1 xorInt S2, W)
  rule fpDivide(fpFinite(S1, _, _), fpInfinity(S2), W) => (S1 xorInt S2) <<Int (W -Int 1)
  rule fpDivide(fpFinite(S1, M, _), fpFinite(S2, 0, _), W) => fpInfinityBits(S1 xorInt S2, W) requires M >Int 0
  rule fpDivide(fpFinite(S1, M1, E1), fpFinite(S2, M2, E2), W) => fpRound(S1 xorInt S2, M1, M2, E1 -Int E2, W) requires M2 >Int 0

  syntax OptionalInt ::= floatUop(UnaryOperator, Int, Int) [function, symbol(calcFloatUnary(_,_,_)_DWARF-FLOATING_OptionalInt_UnaryOperator_Int_Int)]
                       | floatBop(BinaryOperator, Int, Int, Int) [function, symbol(calcFloatBinary(_,_,_,_)_DWARF-FLOATING_OptionalInt_BinaryOperator_Int_Int_Int)]
  rule floatUop(absOp, N, W) => someInt(bits(N, W -Int 1))
  rule floatUop(negOp, N, W) => someInt(bits(N, W) xorInt (2 ^Int (W -Int 1)))
  rule floatUop(_, _, _) => noInt [owise]
  rule floatBop(plusOp, N1, N2, W) => someInt(fpEncode(fpAdd(fpDecode(N2, W), fpDecode(N1, W)), W))
  rule floatBop(minusOp, N1, N2, W) => someInt(fpEncode(fpAdd(fpDecode(N2, W), fpNegate(fpDecode(N1, W))), W))
  rule floatBop(mulOp, N1, N2, W) => someInt(fpMultiply(fpDecode(N2, W), fpDecode(N1, W), W))
  rule floatBop(divOp, N1, N2, W) => someInt(fpDivide(fpDecode(N2, W), fpDecode(N1, W), W))
  rule floatBop(_, _, _, _) => noInt [owise]

  // Comparison returns -1/0/1 or 2 for unordered; with NaN, ne is true and every other relation is false.
  syntax Int ::= fpOrder(FloatParts, FloatParts) [function]
               | fpIntegerOrder(Int, Int) [function]
  rule fpOrder(fpNaN, _) => 2
  rule fpOrder(_, fpNaN) => 2
  rule fpOrder(fpInfinity(S), fpInfinity(S)) => 0
  rule fpOrder(fpInfinity(S1), fpInfinity(S2)) => S2 -Int S1 requires S1 =/=Int S2
  rule fpOrder(fpInfinity(S), fpFinite(_, _, _)) => 1 -Int 2 *Int S
  rule fpOrder(fpFinite(_, _, _), fpInfinity(S)) => 2 *Int S -Int 1
  rule fpOrder(fpFinite(S1, M1, E1), fpFinite(S2, M2, E2)) => fpIntegerOrder(
    fpSigned(S1, M1 <<Int (E1 -Int minInt(E1, E2))), fpSigned(S2, M2 <<Int (E2 -Int minInt(E1, E2))))
  rule fpIntegerOrder(L, R) => -1 requires L <Int R
  rule fpIntegerOrder(L, R) => 0 requires L ==Int R
  rule fpIntegerOrder(L, R) => 1 requires L >Int R
  syntax Bool ::= fpRelation(CompareOperator, Int) [function]
  rule fpRelation(eqOp, O) => O ==Int 0
  rule fpRelation(neOp, O) => O =/=Int 0
  rule fpRelation(geOp, O) => O ==Int 0 orBool O ==Int 1
  rule fpRelation(gtOp, O) => O ==Int 1
  rule fpRelation(leOp, O) => O ==Int 0 orBool O ==Int -1
  rule fpRelation(ltOp, O) => O ==Int -1
endmodule
