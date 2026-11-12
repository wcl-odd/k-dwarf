requires "../../semantics/execution/core.k"

module STUCK-SPEC
  imports DWARF-CORE

  // 证明可执行前缀到达失败 OP，且其数值辅助函数没有结果。
  // 不是自反的 Q => Q；无后续重写另外用双后端增加预算检查。
  claim [generic-abs-minimum-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, nopOp, 1, codeAt(1, unaryOp(absOp), 2, .Instructions)), .Bytes),
      ctx(8, little, .Map, .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt),
      2, locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> push(S:Stack, val(128, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    ensures notBool hasInt(uop(absOp, 128, g, 8))

  claim [typed-abs-minimum-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, nopOp, 1, codeAt(1, unaryOp(absOp), 2, .Instructions)), .Bytes),
      ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt),
      2, locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> push(S:Stack, val(-32768, base("s16", "DW_ATE_signed", 16, 2))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    ensures notBool hasInt(uop(absOp, -32768, base("s16", "DW_ATE_signed", 16, 2), 64))
endmodule
