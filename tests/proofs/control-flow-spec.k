requires "../../semantics/execution/core.k"

module CONTROL-FLOW-SPEC
  imports DWARF-CORE

  // nopOp 保持任意非空带类型栈，完成步返回原栈顶地址。
  claim [nop-preserves-stack]:
    <expr> evaluate(decoded(0, 1, codeAt(0, nopOp, 1, .Instructions), .Bytes), C:Context, 1, locationPurpose)
        => finished(decoded(0, 1, codeAt(0, nopOp, 1, .Instructions), .Bytes), C, 1, memory(N), locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(S:Stack, val(N:Int, T:Ty)) => push(S, val(N, T)) </stack>

  // 前跳绕过会弹栈的 dropOp；原始输入与完整栈均保留。
  claim [skip-preserves-stack]:
    <expr> evaluate(decoded(0, 4, codeAt(0, skipOp(1), 3, codeAt(3, dropOp, 4, .Instructions)), .Bytes), C:Context, 4, locationPurpose)
        => finished(decoded(0, 4, codeAt(0, skipOp(1), 3, codeAt(3, dropOp, 4, .Instructions)), .Bytes), C, 4, memory(N), locationPurpose) </expr>
    <pc> 0 => 4 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(S:Stack, val(N:Int, T:Ty)) => push(S, val(N, T)) </stack>

  // 任意非零整数类型的条件被消费，不限制为 Boolean 或 generic。
  claim [bra-nonzero-consumes-condition]:
    <expr> evaluate(decoded(0, 4, codeAt(0, braOp(1), 3, codeAt(3, dropOp, 4, .Instructions)), .Bytes), C:Context, 4, locationPurpose)
        => finished(decoded(0, 4, codeAt(0, braOp(1), 3, codeAt(3, dropOp, 4, .Instructions)), .Bytes), C, 4, memory(N), locationPurpose) </expr>
    <pc> 0 => 4 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(push(S:Stack, val(N:Int, T:Ty)), val(B:Int, _:Ty))
          => push(S, val(N, T)) </stack>
    requires B =/=Int 0

  // 零条件走 NEXT=END；未采用的目标 102 不在表达式内也不影响正常落下。
  claim [bra-zero-ignores-unused-target]:
    <expr> evaluate(decoded(0, 3, codeAt(0, braOp(99), 3, .Instructions), .Bytes), C:Context, 3, locationPurpose)
        => finished(decoded(0, 3, codeAt(0, braOp(99), 3, .Instructions), .Bytes), C, 3, memory(N), locationPurpose) </expr>
    <pc> 0 => 3 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(push(S:Stack, val(N:Int, T:Ty)), val(0, _:Ty))
          => push(S, val(N, T)) </stack>
endmodule
