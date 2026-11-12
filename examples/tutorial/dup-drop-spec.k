requires "dwarf-mini.k"

module DUP-DROP-SPEC
  imports DWARF-MINI

  // A singleton generic stack is preserved for every integer N.
  claim [dup-drop]:
    <k> DW_OP_dup ~> DW_OP_drop => .K </k>
    <stack> ListItem(val(N:Int, g))
         => ListItem(val(N, g)) </stack>
endmodule
