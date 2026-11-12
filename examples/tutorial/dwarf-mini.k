// Lesson 1: a straight-line fragment, not the full paper semantics.
module DWARF-MINI-SYNTAX
  imports INT-SYNTAX

  syntax Instr ::= "DW_OP_constu" Int
                 | "DW_OP_consts" Int
                 | "DW_OP_minus"
                 | "DW_OP_dup"
                 | "DW_OP_drop"
  syntax Program ::= List{Instr, ","}
endmodule

module DWARF-MINI
  imports DWARF-MINI-SYNTAX
  imports INT
  imports BOOL
  imports LIST

  syntax Ty ::= "g"
  syntax Val ::= "val" "(" Int "," Ty ")"

  configuration
    <dwarf>
      <k> $PGM:Program </k>
      <stack> .List </stack>
      <width> 64 </width>
    </dwarf>

  // Move the next instruction into the K computation sequence.
  rule <k> I:Instr , REST:Program => I ~> REST ... </k>
  rule <k> .Program => .K ... </k>

  // Like the paper, the stack top is on the right.
  rule [constu]:
    <k> DW_OP_constu N => .K ... </k>
    <stack> S => S ListItem(val(N, g)) </stack>
    <width> A </width>
    requires 0 <=Int N
      andBool N <Int (2 ^Int A)

  rule [consts]:
    <k> DW_OP_consts N => .K ... </k>
    <stack> S => S ListItem(val(N, g)) </stack>
    <width> A </width>
    requires (0 -Int (2 ^Int (A -Int 1))) <=Int N
      andBool N <Int (2 ^Int (A -Int 1))

  rule [sub]:
    <k> DW_OP_minus => .K ... </k>
    <stack> S ListItem(val(N2, g)) ListItem(val(N1, g))
         => S ListItem(val((N2 -Int N1) modInt (2 ^Int A), g))
    </stack>
    <width> A </width>

  rule [dup]:
    <k> DW_OP_dup => .K ... </k>
    <stack> S ListItem(V:Val) => S ListItem(V) ListItem(V) </stack>

  rule [drop]:
    <k> DW_OP_drop => .K ... </k>
    <stack> S ListItem(_:Val) => S </stack>
endmodule
