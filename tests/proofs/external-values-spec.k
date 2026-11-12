requires "../../semantics/execution/core.k"
module EXTERNAL-VALUES-SPEC
  imports DWARF-CORE

  // 同一地址表的 addrx 采用加载偏移；栈前缀与所有输入保持不变。
  claim [address-index-preserves-prefix]:
    <expr> evaluate(decoded(0, 1, codeAt(0, addrxOp(1), 1, .Instructions), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, (1 |-> N:Int), B:Int, noInt) #as C), 1, valuePurpose)
      => finished(decoded(0, 1, codeAt(0, addrxOp(1), 1, .Instructions), .Bytes), C, 1, scalarResult(val(bits(N +Int B, 64), g)), valuePurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> S:Stack => push(S, val(bits(N +Int B, 64), g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0,0,0), _:Bool) </fragments>
    requires N >=Int 0

  // 对象地址和 CFA/frame base 独立；不读取内存，也不丢失栈前缀。
  claim [object-address-preserves-prefix]:
    <expr> evaluate(decoded(0, 1, codeAt(0, pushObjectAddressOp, 1, .Instructions), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, _:OptionalInt, _:OptionalInt, unspecified, .Map, 0, someInt(N:Int)) #as C), 1, valuePurpose)
      => finished(decoded(0, 1, codeAt(0, pushObjectAddressOp, 1, .Instructions), .Bytes), C, 1, scalarResult(val(N,g)), valuePurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> S:Stack => push(S,val(N,g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0,0,0), _:Bool) </fragments>
    requires fitsUnsigned(N,64)

  // value 完成不移动任何栈条目，完整类型和整数代表值均保留。
  claim [scalar-preserves-complete-stack]:
    <expr> evaluate(decoded(0, 0, .Instructions, .Bytes), C:Context, 0, valuePurpose)
      => finished(decoded(0, 0, .Instructions, .Bytes),C,0,scalarResult(V),valuePurpose) </expr>
    <pc> 0 </pc>
    <stack> push(S:Stack,V:Value) </stack>
    <fragments> fragments(0,noLocation,.Pieces,objectBits(0,0,0),_:Bool) </fragments>
endmodule
