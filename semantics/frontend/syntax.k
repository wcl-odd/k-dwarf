// Two formal input formats: offset-annotated OP text and hexadecimal raw bytes.
// External hexadecimal numbers are literals, not signed two's-complement encodings; convert to mathematical Int before checking source ranges.
// Separate parsing modules prevent treating hex-file token 11 as decimal integer 11.
module DWARF-TEXT-SYNTAX
  imports INT-SYNTAX
  syntax HexInteger ::= r"-?0[xX][0-9a-fA-F]+" [token]
  syntax Literal ::= Int | HexInteger
  // lit0..31 encode their value in the name and take no additional Literal operand.
  syntax ByteLiterals ::= List{Literal, ""}
  syntax Op ::= "DW_OP_lit0"
              | "DW_OP_lit1"
              | "DW_OP_lit2"
              | "DW_OP_lit3"
              | "DW_OP_lit4"
              | "DW_OP_lit5"
              | "DW_OP_lit6"
              | "DW_OP_lit7"
              | "DW_OP_lit8"
              | "DW_OP_lit9"
              | "DW_OP_lit10"
              | "DW_OP_lit11"
              | "DW_OP_lit12"
              | "DW_OP_lit13"
              | "DW_OP_lit14"
              | "DW_OP_lit15"
              | "DW_OP_lit16"
              | "DW_OP_lit17"
              | "DW_OP_lit18"
              | "DW_OP_lit19"
              | "DW_OP_lit20"
              | "DW_OP_lit21"
              | "DW_OP_lit22"
              | "DW_OP_lit23"
              | "DW_OP_lit24"
              | "DW_OP_lit25"
              | "DW_OP_lit26"
              | "DW_OP_lit27"
              | "DW_OP_lit28"
              | "DW_OP_lit29"
              | "DW_OP_lit30"
              | "DW_OP_lit31"
              // Fixed-width constants: 1/2/4/8 is the encoded byte count; Literal is the decoded value.
              | "DW_OP_const1u" Literal
              | "DW_OP_const1s" Literal
              | "DW_OP_const2u" Literal
              | "DW_OP_const2s" Literal
              | "DW_OP_const4u" Literal
              | "DW_OP_const4s" Literal
              | "DW_OP_const8u" Literal
              | "DW_OP_const8s" Literal
              // Variable-length constants and direct addresses still use mathematical integers as text operands.
              | "DW_OP_constu" Literal
              | "DW_OP_consts" Literal
              | "DW_OP_addr" Literal
              | "DW_OP_addrx" Literal
              | "DW_OP_constx" Literal
              | "DW_OP_const_type" Literal "[" ByteLiterals "]"
              | "DW_OP_regval_type" Literal Literal
              | "DW_OP_push_object_address"
              // breg0..31 take only an offset; the register number is already in the OP name.
              | "DW_OP_breg0" Literal
              | "DW_OP_breg1" Literal
              | "DW_OP_breg2" Literal
              | "DW_OP_breg3" Literal
              | "DW_OP_breg4" Literal
              | "DW_OP_breg5" Literal
              | "DW_OP_breg6" Literal
              | "DW_OP_breg7" Literal
              | "DW_OP_breg8" Literal
              | "DW_OP_breg9" Literal
              | "DW_OP_breg10" Literal
              | "DW_OP_breg11" Literal
              | "DW_OP_breg12" Literal
              | "DW_OP_breg13" Literal
              | "DW_OP_breg14" Literal
              | "DW_OP_breg15" Literal
              | "DW_OP_breg16" Literal
              | "DW_OP_breg17" Literal
              | "DW_OP_breg18" Literal
              | "DW_OP_breg19" Literal
              | "DW_OP_breg20" Literal
              | "DW_OP_breg21" Literal
              | "DW_OP_breg22" Literal
              | "DW_OP_breg23" Literal
              | "DW_OP_breg24" Literal
              | "DW_OP_breg25" Literal
              | "DW_OP_breg26" Literal
              | "DW_OP_breg27" Literal
              | "DW_OP_breg28" Literal
              | "DW_OP_breg29" Literal
              | "DW_OP_breg30" Literal
              | "DW_OP_breg31" Literal
              // bregx operands are register number then offset, separated by whitespace.
              | "DW_OP_bregx" Literal Literal
              | "DW_OP_fbreg" Literal
              | "DW_OP_call_frame_cfa"
              // K evaluates call references and uses function-entry state and external address spaces.
              | "DW_OP_call2" Literal | "DW_OP_call4" Literal | "DW_OP_call_ref" Literal
              | "DW_OP_entry_value" "[" ByteLiterals "]"
              | "DW_OP_xderef" | "DW_OP_xderef_size" Literal | "DW_OP_xderef_type" Literal Literal
              | "DW_OP_form_tls_address"
              | "DW_OP_implicit_pointer" Literal Literal
              // Dereference: default size, explicit byte count, or byte count plus base-type reference.
              | "DW_OP_deref"
              | "DW_OP_deref_size" Literal
              | "DW_OP_deref_type" Literal Literal
              // Type reference 0 means generic; evaluation resolves other references through the interface.
              | "DW_OP_convert" Literal
              | "DW_OP_reinterpret" Literal
              // Only pick among these stack operations takes an operand, a zero-based depth from the top.
              | "DW_OP_dup"
              | "DW_OP_over"
              | "DW_OP_pick" Literal
              | "DW_OP_drop"
              | "DW_OP_swap"
              | "DW_OP_rot"
              // Computations take stack operands and no literal operands except plus_uconst's immediate.
              | "DW_OP_abs" | "DW_OP_neg" | "DW_OP_not"
              | "DW_OP_plus_uconst" Literal
              | "DW_OP_and" | "DW_OP_div" | "DW_OP_minus" | "DW_OP_mod"
              | "DW_OP_mul" | "DW_OP_or" | "DW_OP_plus"
              | "DW_OP_shl" | "DW_OP_shr" | "DW_OP_shra" | "DW_OP_xor"
              | "DW_OP_eq" | "DW_OP_ge" | "DW_OP_gt"
              | "DW_OP_le" | "DW_OP_lt" | "DW_OP_ne"
              // Control-flow offsets are decoded signed two-byte integers relative to the next position.
              | "DW_OP_nop"
              | "DW_OP_skip" Literal
              | "DW_OP_bra" Literal
              // reg alone forms the whole simple description or current fragment; a standalone result does not read register contents.
              | "DW_OP_reg0"
              | "DW_OP_reg1"
              | "DW_OP_reg2"
              | "DW_OP_reg3"
              | "DW_OP_reg4"
              | "DW_OP_reg5"
              | "DW_OP_reg6"
              | "DW_OP_reg7"
              | "DW_OP_reg8"
              | "DW_OP_reg9"
              | "DW_OP_reg10"
              | "DW_OP_reg11"
              | "DW_OP_reg12"
              | "DW_OP_reg13"
              | "DW_OP_reg14"
              | "DW_OP_reg15"
              | "DW_OP_reg16"
              | "DW_OP_reg17"
              | "DW_OP_reg18"
              | "DW_OP_reg19"
              | "DW_OP_reg20"
              | "DW_OP_reg21"
              | "DW_OP_reg22"
              | "DW_OP_reg23"
              | "DW_OP_reg24"
              | "DW_OP_reg25"
              | "DW_OP_reg26"
              | "DW_OP_reg27"
              | "DW_OP_reg28"
              | "DW_OP_reg29"
              | "DW_OP_reg30"
              | "DW_OP_reg31"
              | "DW_OP_regx" Literal
              // A location-description result marker, not a stack operation; it must end the input or immediately precede a piece delimiter.
              | "DW_OP_stack_value"
              // Implicit byte blocks omit a redundant length; piece sizes are bytes and bit_piece sizes are bits.
              | "DW_OP_implicit_value" "[" ByteLiterals "]"
              | "DW_OP_piece" Literal
              | "DW_OP_bit_piece" Literal Literal
  // A nonempty input must end with a separate END; the old unannotated operation list is not accepted here.
  // For example: 0x0: DW_OP_consts -0x1, 0x2: DW_OP_stack_value, 0x3.
  syntax TextProgram ::= Literal
                       | Literal ":" Op "," TextProgram [symbol(textInstruction)]
  syntax Program ::= TextProgram
  syntax Input ::= Program
endmodule

module DWARF-HEX-SYNTAX
  // Capture the entire longest numeric token first, then let K require exactly two digits; never split 117f into 11 7f.
  syntax HexByte ::= r"(0[xX])?[0-9a-fA-F]+" [token]
  syntax HexProgram ::= List{HexByte, ""}
  syntax Program ::= HexProgram
  syntax Input ::= Program
endmodule

module DWARF-SYNTAX
  imports DWARF-TEXT-SYNTAX
  imports DWARF-HEX-SYNTAX
endmodule
