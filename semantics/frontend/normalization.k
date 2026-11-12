requires "syntax.k"
requires "../execution/expression.k"

module DWARF-NORMALIZATION
  imports DWARF-SYNTAX
  imports DWARF-EXPRESSION
  syntax Operation ::= sourceEntry(ByteBlock)

  // Purely map concrete OP names to shared internal operations; do not execute operations or modify the stack.
  // constOp(N), bregxOp(R,D), derefOp(S), and derefTypeOp(S,T) are internal constructors, not external input syntax.
  // unavailableOperation retains an operation whose operand conditions fail; no execution rule applies when it is reached.
  // K converts hexadecimal tokens to mathematical integers; existing Ints retain their values.
  // Decoded operands are also Ints, so both input formats share normalize equations.
  syntax String ::= hexIntegerString(HexInteger) [function, total, hook(STRING.token2string)]
  syntax Int ::= number(Literal) [function]
               | hexadecimal(String) [function]
  rule number(N:Int) => N
  rule number(H:HexInteger) => hexadecimal(hexIntegerString(H))
  rule hexadecimal(S) => 0 -Int String2Base(substrString(S, 3, lengthString(S)), 16)
    requires substrString(S, 0, 1) ==String "-"
  rule hexadecimal(S) => String2Base(substrString(S, 2, lengthString(S)), 16)
    requires substrString(S, 0, 1) =/=String "-"

  // The second normalize(OP,A) argument is the target address width in bits.
  // _ means that a variant does not use A; only equations needing it bind a named A.
  // For example, const2u checks its 16-bit source range; Const performs the actual truncation to A bits.
  syntax Operation ::= normalize(Op, Int) [function]
  // nopOp takes no stack operand; skipOp/braOp source displacements are signed 16-bit values, not address-width-truncated values.
  // Text and bytes share this check; out-of-range text becomes unavailableOperation, not an input syntax error.
  rule normalize(DW_OP_addrx I, _) => addrxOp(number(I)) requires number(I) >=Int 0
  rule normalize(DW_OP_constx I, _) => constxOp(number(I)) requires number(I) >=Int 0
  rule normalize(DW_OP_push_object_address, _) => pushObjectAddressOp
  // A typed constant's block length is a source byte count, not truncated to address width; execution checks the type's storage size.
  rule normalize(DW_OP_const_type T [ B ], _) => constTypeOp(number(T), literalBytes(B))
    requires number(T) >Int 0 andBool validBytes(B)
  rule normalize(DW_OP_regval_type R T, _) => regvalTypeOp(number(R), number(T))
    requires number(R) >=Int 0 andBool number(T) >Int 0
  // call2/4 use CU-relative references; call_ref uses absolute .debug_info references.
  rule normalize(DW_OP_call2 R, _) => callUnitOp(number(R)) requires fitsUnsigned(number(R), 16)
  rule normalize(DW_OP_call4 R, _) => callUnitOp(number(R)) requires fitsUnsigned(number(R), 32)
  rule normalize(DW_OP_call_ref R, _) => callRefOp(number(R)) requires number(R) >=Int 0
  rule normalize(DW_OP_entry_value [ B ], _) => sourceEntry(literalBytes(B)) requires validBytes(B)
  rule normalize(DW_OP_form_tls_address, _) => formTlsAddressOp
  rule normalize(DW_OP_xderef, A) => xderefOp(A /Int 8) requires A modInt 8 ==Int 0
  rule normalize(DW_OP_xderef_size S, _) => xderefOp(number(S)) requires fitsUnsigned(number(S), 8)
  rule normalize(DW_OP_xderef_type S T, _) => xderefTypeOp(number(S), number(T))
    requires fitsUnsigned(number(S), 8) andBool number(T) >Int 0
  rule normalize(DW_OP_implicit_pointer R D, _) => implicitPointerOp(number(R), number(D)) requires number(R) >=Int 0
  rule normalize(DW_OP_call_frame_cfa, _) => callFrameCfaOp
  rule normalize(DW_OP_nop, _) => nopOp
  rule normalize(DW_OP_skip D, _) => skipOp(number(D)) requires fitsSigned(number(D), 16)
  rule normalize(DW_OP_bra D, _) => braOp(number(D)) requires fitsSigned(number(D), 16)
  // lit0..31 encode the constant in the name and have no extra operand; all use Const.
  rule normalize(DW_OP_lit0, _) => constOp(0)
  rule normalize(DW_OP_lit1, _) => constOp(1)
  rule normalize(DW_OP_lit2, _) => constOp(2)
  rule normalize(DW_OP_lit3, _) => constOp(3)
  rule normalize(DW_OP_lit4, _) => constOp(4)
  rule normalize(DW_OP_lit5, _) => constOp(5)
  rule normalize(DW_OP_lit6, _) => constOp(6)
  rule normalize(DW_OP_lit7, _) => constOp(7)
  rule normalize(DW_OP_lit8, _) => constOp(8)
  rule normalize(DW_OP_lit9, _) => constOp(9)
  rule normalize(DW_OP_lit10, _) => constOp(10)
  rule normalize(DW_OP_lit11, _) => constOp(11)
  rule normalize(DW_OP_lit12, _) => constOp(12)
  rule normalize(DW_OP_lit13, _) => constOp(13)
  rule normalize(DW_OP_lit14, _) => constOp(14)
  rule normalize(DW_OP_lit15, _) => constOp(15)
  rule normalize(DW_OP_lit16, _) => constOp(16)
  rule normalize(DW_OP_lit17, _) => constOp(17)
  rule normalize(DW_OP_lit18, _) => constOp(18)
  rule normalize(DW_OP_lit19, _) => constOp(19)
  rule normalize(DW_OP_lit20, _) => constOp(20)
  rule normalize(DW_OP_lit21, _) => constOp(21)
  rule normalize(DW_OP_lit22, _) => constOp(22)
  rule normalize(DW_OP_lit23, _) => constOp(23)
  rule normalize(DW_OP_lit24, _) => constOp(24)
  rule normalize(DW_OP_lit25, _) => constOp(25)
  rule normalize(DW_OP_lit26, _) => constOp(26)
  rule normalize(DW_OP_lit27, _) => constOp(27)
  rule normalize(DW_OP_lit28, _) => constOp(28)
  rule normalize(DW_OP_lit29, _) => constOp(29)
  rule normalize(DW_OP_lit30, _) => constOp(30)
  rule normalize(DW_OP_lit31, _) => constOp(31)
  // Fixed-width constants: 1/2/4/8 in the name is the source byte count; u/s selects the allowed numeric range.
  // number converts text literals to mathematical integers: use -1 for const1s, not 255 to denote 0xff.
  // These conditions check source inputs, not lossless fit in the target; narrower targets may truncate.
  rule normalize(DW_OP_const1u N, _) => constOp(number(N))
    requires fitsUnsigned(number(N), 8)
  rule normalize(DW_OP_const1s N, _) => constOp(number(N))
    requires fitsSigned(number(N), 8)
  rule normalize(DW_OP_const2u N, _) => constOp(number(N))
    requires fitsUnsigned(number(N), 16)
  rule normalize(DW_OP_const2s N, _) => constOp(number(N))
    requires fitsSigned(number(N), 16)
  rule normalize(DW_OP_const4u N, _) => constOp(number(N))
    requires fitsUnsigned(number(N), 32)
  rule normalize(DW_OP_const4s N, _) => constOp(number(N))
    requires fitsSigned(number(N), 32)
  rule normalize(DW_OP_const8u N, _) => constOp(number(N))
    requires fitsUnsigned(number(N), 64)
  rule normalize(DW_OP_const8s N, _) => constOp(number(N))
    requires fitsSigned(number(N), 64)
  // Variable-length constants are decoded in decoding.k; A does not bound their mathematical operands here.
  // constu requires nonnegative operands, while consts permits any integer. Const pushes both modulo 2^A.
  rule normalize(DW_OP_constu N, _) => constOp(number(N)) requires number(N) >=Int 0
  rule normalize(DW_OP_consts N, _) => constOp(number(N))
  // addr's source operand already has target address size, so require an unsigned A-bit value here.
  rule normalize(DW_OP_addr N, A) => constOp(number(N)) requires fitsUnsigned(number(N), A)
  // breg0..31 encode the register number in the name; D is any decoded signed offset.
  // Normalization to bregxOp(R,D) lets one Breg rule perform register lookup, addition, and modular reduction.
  rule normalize(DW_OP_breg0 D, _) => bregxOp(0, number(D))
  rule normalize(DW_OP_breg1 D, _) => bregxOp(1, number(D))
  rule normalize(DW_OP_breg2 D, _) => bregxOp(2, number(D))
  rule normalize(DW_OP_breg3 D, _) => bregxOp(3, number(D))
  rule normalize(DW_OP_breg4 D, _) => bregxOp(4, number(D))
  rule normalize(DW_OP_breg5 D, _) => bregxOp(5, number(D))
  rule normalize(DW_OP_breg6 D, _) => bregxOp(6, number(D))
  rule normalize(DW_OP_breg7 D, _) => bregxOp(7, number(D))
  rule normalize(DW_OP_breg8 D, _) => bregxOp(8, number(D))
  rule normalize(DW_OP_breg9 D, _) => bregxOp(9, number(D))
  rule normalize(DW_OP_breg10 D, _) => bregxOp(10, number(D))
  rule normalize(DW_OP_breg11 D, _) => bregxOp(11, number(D))
  rule normalize(DW_OP_breg12 D, _) => bregxOp(12, number(D))
  rule normalize(DW_OP_breg13 D, _) => bregxOp(13, number(D))
  rule normalize(DW_OP_breg14 D, _) => bregxOp(14, number(D))
  rule normalize(DW_OP_breg15 D, _) => bregxOp(15, number(D))
  rule normalize(DW_OP_breg16 D, _) => bregxOp(16, number(D))
  rule normalize(DW_OP_breg17 D, _) => bregxOp(17, number(D))
  rule normalize(DW_OP_breg18 D, _) => bregxOp(18, number(D))
  rule normalize(DW_OP_breg19 D, _) => bregxOp(19, number(D))
  rule normalize(DW_OP_breg20 D, _) => bregxOp(20, number(D))
  rule normalize(DW_OP_breg21 D, _) => bregxOp(21, number(D))
  rule normalize(DW_OP_breg22 D, _) => bregxOp(22, number(D))
  rule normalize(DW_OP_breg23 D, _) => bregxOp(23, number(D))
  rule normalize(DW_OP_breg24 D, _) => bregxOp(24, number(D))
  rule normalize(DW_OP_breg25 D, _) => bregxOp(25, number(D))
  rule normalize(DW_OP_breg26 D, _) => bregxOp(26, number(D))
  rule normalize(DW_OP_breg27 D, _) => bregxOp(27, number(D))
  rule normalize(DW_OP_breg28 D, _) => bregxOp(28, number(D))
  rule normalize(DW_OP_breg29 D, _) => bregxOp(29, number(D))
  rule normalize(DW_OP_breg30 D, _) => bregxOp(30, number(D))
  rule normalize(DW_OP_breg31 D, _) => bregxOp(31, number(D))
  // bregx explicitly supplies nonnegative register number R; its offset D has the same meaning as in the variants above.
  rule normalize(DW_OP_bregx R D, _) => bregxOp(number(R), number(D)) requires number(R) >=Int 0
  // fbregOp uses the externally resolved frame base; D likewise has no A-bit source-range restriction.
  rule normalize(DW_OP_fbreg D, _) => fbregOp(number(D))
  // Default dereference reads A/8 bytes into generic, requiring A to be divisible by eight.
  // The sized form does not impose divisibility here; validReadSize checks its effective capacity.
  rule normalize(DW_OP_deref, A) => derefOp(A /Int 8)
    requires A modInt 8 ==Int 0
  // The source field for size S is one unsigned byte, hence 0..255.
  // Check only the source field here; execution combines S with A to check generic capacity.
  rule normalize(DW_OP_deref_size S, _) => derefOp(number(S))
    requires 0 <=Int number(S) andBool number(S) <=Int 255
  // Typed reads: S is a byte count, T a positive base-type reference; no type-table query occurs yet.
  // A separate derefTypeOp lets DerefType look up the type and interpret memory, without using ordinary Deref.
  rule normalize(DW_OP_deref_type S T, _) => derefTypeOp(number(S), number(T))
    requires 0 <=Int number(S) andBool number(S) <=Int 255 andBool number(T) >Int 0
  // References are CU-relative offsets; resolveType handles generic reference 0, without lookup here.
  rule normalize(DW_OP_convert T, _) => convertOp(number(T)) requires number(T) >=Int 0
  rule normalize(DW_OP_reinterpret T, _) => reinterpretOp(number(T)) requires number(T) >=Int 0
  // dup copies the top and over the next entry; normalization reuses Pick instead of separate duplication rules.
  rule normalize(DW_OP_dup, _) => pickOp(0)
  rule normalize(DW_OP_over, _) => pickOp(1)
  // pickOp also has an unsigned-byte operand; execution uses stackAt to check stack depth.
  rule normalize(DW_OP_pick K, _) => pickOp(number(K)) requires 0 <=Int number(K) andBool number(K) <=Int 255
  // These three stack operations have no literal operands and map directly to their internal constructors.
  rule normalize(DW_OP_drop, _) => dropOp
  rule normalize(DW_OP_swap, _) => swapOp
  rule normalize(DW_OP_rot, _) => rotOp
  // Computational normalization selects calculations without changing the stack; core rules determine operand order and type conditions.
  rule normalize(DW_OP_abs, _) => unaryOp(absOp)
  rule normalize(DW_OP_neg, _) => unaryOp(negOp)
  rule normalize(DW_OP_not, _) => unaryOp(notOp)
  // X's upper bound depends on the actual operand type and is checked by uop.
  rule normalize(DW_OP_plus_uconst X, _) => unaryOp(plusUconstOp(number(X))) requires number(X) >=Int 0
  rule normalize(DW_OP_and, _) => binaryOp(andOp)
  rule normalize(DW_OP_div, _) => binaryOp(divOp)
  rule normalize(DW_OP_minus, _) => binaryOp(minusOp)
  rule normalize(DW_OP_mod, _) => binaryOp(modOp)
  rule normalize(DW_OP_mul, _) => binaryOp(mulOp)
  rule normalize(DW_OP_or, _) => binaryOp(orOp)
  rule normalize(DW_OP_plus, _) => binaryOp(plusOp)
  rule normalize(DW_OP_shl, _) => binaryOp(shlOp)
  rule normalize(DW_OP_shr, _) => binaryOp(shrOp)
  rule normalize(DW_OP_shra, _) => binaryOp(shraOp)
  rule normalize(DW_OP_xor, _) => binaryOp(xorOp)
  rule normalize(DW_OP_eq, _) => compareOp(eqOp)
  rule normalize(DW_OP_ge, _) => compareOp(geOp)
  rule normalize(DW_OP_gt, _) => compareOp(gtOp)
  rule normalize(DW_OP_le, _) => compareOp(leOp)
  rule normalize(DW_OP_lt, _) => compareOp(ltOp)
  rule normalize(DW_OP_ne, _) => compareOp(neOp)
  // reg stores only a DWARF number; it neither queries the register table nor creates a stack value.
  rule normalize(DW_OP_reg0, _) => regxOp(0)
  rule normalize(DW_OP_reg1, _) => regxOp(1)
  rule normalize(DW_OP_reg2, _) => regxOp(2)
  rule normalize(DW_OP_reg3, _) => regxOp(3)
  rule normalize(DW_OP_reg4, _) => regxOp(4)
  rule normalize(DW_OP_reg5, _) => regxOp(5)
  rule normalize(DW_OP_reg6, _) => regxOp(6)
  rule normalize(DW_OP_reg7, _) => regxOp(7)
  rule normalize(DW_OP_reg8, _) => regxOp(8)
  rule normalize(DW_OP_reg9, _) => regxOp(9)
  rule normalize(DW_OP_reg10, _) => regxOp(10)
  rule normalize(DW_OP_reg11, _) => regxOp(11)
  rule normalize(DW_OP_reg12, _) => regxOp(12)
  rule normalize(DW_OP_reg13, _) => regxOp(13)
  rule normalize(DW_OP_reg14, _) => regxOp(14)
  rule normalize(DW_OP_reg15, _) => regxOp(15)
  rule normalize(DW_OP_reg16, _) => regxOp(16)
  rule normalize(DW_OP_reg17, _) => regxOp(17)
  rule normalize(DW_OP_reg18, _) => regxOp(18)
  rule normalize(DW_OP_reg19, _) => regxOp(19)
  rule normalize(DW_OP_reg20, _) => regxOp(20)
  rule normalize(DW_OP_reg21, _) => regxOp(21)
  rule normalize(DW_OP_reg22, _) => regxOp(22)
  rule normalize(DW_OP_reg23, _) => regxOp(23)
  rule normalize(DW_OP_reg24, _) => regxOp(24)
  rule normalize(DW_OP_reg25, _) => regxOp(25)
  rule normalize(DW_OP_reg26, _) => regxOp(26)
  rule normalize(DW_OP_reg27, _) => regxOp(27)
  rule normalize(DW_OP_reg28, _) => regxOp(28)
  rule normalize(DW_OP_reg29, _) => regxOp(29)
  rule normalize(DW_OP_reg30, _) => regxOp(30)
  rule normalize(DW_OP_reg31, _) => regxOp(31)
  rule normalize(DW_OP_regx R, _) => regxOp(number(R)) requires number(R) >=Int 0
  // Recognize only the result marker here; separate location-result rules check final position and a nonempty stack.
  rule normalize(DW_OP_stack_value, _) => stackValueOp
  rule normalize(DW_OP_piece N, _) => pieceOp(number(N)) requires number(N) >=Int 0
  rule normalize(DW_OP_bit_piece N K, _) => bitPieceOp(number(N), number(K))
    requires number(N) >=Int 0 andBool number(K) >=Int 0
  rule normalize(DW_OP_implicit_value [ B ], _) => implicitValueOp(literalBytes(B))
    requires validBytes(B)
  syntax Bool ::= validBytes(ByteLiterals) [function]
  rule validBytes(.ByteLiterals) => true
  rule validBytes((N:Literal REST:ByteLiterals)) =>
    0 <=Int number(N) andBool number(N) <Int 256 andBool validBytes(REST)
  syntax ByteBlock ::= literalBytes(ByteLiterals) [function]
  rule literalBytes(.ByteLiterals) => .Bytes
  rule literalBytes((N:Literal REST:ByteLiterals)) => byteCons(number(N), literalBytes(REST))
  // Every declared OP has a normalization result; unmet conditions retain unavailableOperation.
  // [owise] applies only when other equations do not; unknown OP names are rejected earlier during syntax parsing.
  // Thus invalid source operands, like missing context, cannot be misreported as normal completion.
  rule normalize(O, _) => unavailableOperation [owise]
endmodule
