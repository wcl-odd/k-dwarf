requires "../../semantics/execution/core.k"

module FLOATING-SPEC
  imports DWARF-CORE

  // NaN payload 不因同宽转换而被改变，任意栈前缀保持。
  claim [float-convert-same-width-keeps-payload]:
    <expr> evaluate(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, (1 |-> base("f32", "DW_ATE_float", 32, 4)), .Map, .Map,
           noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
           value(val(N, base("f32", "DW_ATE_float", 32, 4))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(N:Int, base("f32", "DW_ATE_float", 32, 4))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires 0 <=Int N andBool N <Int 4294967296

  // 固定位串的浮点加法与比较，证明不依赖宿主 Float hook。
  claim [float-add-preserves-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, binaryOp(plusOp), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, binaryOp(plusOp), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
           value(val(1077936128, base("f32", "DW_ATE_float", 32, 4))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(push(S:Stack, val(1065353216, base("f32", "DW_ATE_float", 32, 4))),
           val(1073741824, base("f32", "DW_ATE_float", 32, 4)))
           => push(S, val(1077936128, base("f32", "DW_ATE_float", 32, 4))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>

  claim [float-nan-is-unordered]:
    <expr> evaluate(decoded(0, 2, codeAt(0, compareOp(neOp), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, compareOp(neOp), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2, value(val(1, g)), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(push(S:Stack, val(2143289344, base("f32", "DW_ATE_float", 32, 4))),
           val(1065353216, base("f32", "DW_ATE_float", 32, 4))) => push(S, val(1, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
  // 浮点位串不能充当 derefOp 地址。nopOp 可执行，随后读取前提不成立。
  // 这里只证明到达停止现场，不用 Q => Q 冒充 irreducibility 证明。
  claim [float-address-prefix-reaches-stuck-scene]:
    <expr> evaluate(decoded(0, 2, codeAt(0, nopOp, 1, codeAt(1, derefOp(1), 2, .Instructions)), .Bytes),
      (ctx(64, little, .Map, .Map, M:Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> push(S:Stack, val(N:Int, base("f32", "DW_ATE_float", 32, 4))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires 0 <=Int N andBool N <Int 4294967296
endmodule
