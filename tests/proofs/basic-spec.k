requires "../../semantics/execution/core.k"

module BASIC-SPEC
  imports DWARF-CORE

  // claim 是 kprove 检查的可达性性质，不是执行规则。
  // 空表达式正常产生 unavailable，任意初始栈 S 和上下文 C 均保留。
  claim [empty-preserves-stack]:
    <expr> evaluate(decoded(0, 0, .Instructions, .Bytes), C:Context, 0, locationPurpose) => finished(decoded(0, 0, .Instructions, .Bytes), C, 0, unavailable, locationPurpose) </expr>
    <pc> 0 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> S:Stack => S </stack>

  // 直接从已解码 E 开始；dup 的归一化结果为 pickOp(0)。
  // 任意前缀 S、完整带类型栈顶，经 dup/dropOp 后均不改变，最后解释为普通地址。
  claim [dup-drop-preserves-nonempty-stack]:
    <expr> evaluate(decoded(0, 2, codeAt(0, pickOp(0), 1, codeAt(1, dropOp, 2, .Instructions)), .Bytes),
                    C:Context, 2, locationPurpose)
        => finished(decoded(0, 2, codeAt(0, pickOp(0), 1, codeAt(1, dropOp, 2, .Instructions)), .Bytes), C, 2, memory(N), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(S:Stack, val(N:Int, T:Ty)) => push(S, val(N, T)) </stack>

  // 在 64 位地址宽度及任意可表示的 N 下，相同 generic 位串比较相等。
  // 允许 signed/unsigned 代表值的并集，覆盖 JSON 输入和计算产生的负数代表值。
  // 固定位宽避免把符号指数 2^A 交给 SMT；其他位宽由具体执行测试覆盖。
  // 任意栈前缀及全部输入保持不变，两个操作数被替换为 1:g；包含正常完成步。
  claim [equal-generic-values]:
    <expr> evaluate(decoded(0, 1, codeAt(0, compareOp(eqOp), 1, .Instructions), .Bytes),
                    (ctx(64, _:ByteOrder, _:Map, _:Map, _:Map, _:OptionalInt, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), 1, locationPurpose)
        => finished(decoded(0, 1, codeAt(0, compareOp(eqOp), 1, .Instructions), .Bytes), C, 1, memory(1), locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(push(S:Stack, val(N:Int, g)), val(N, g)) => push(S, val(1, g)) </stack>
    requires fitsSigned(N, 64) orBool fitsUnsigned(N, 64)

  // 标记为唯一且末尾的 OP；任意非空栈均返回完整栈顶，整个栈不变。
  // 包含已解码位置查询，不要求具体位宽或具体基础类型。
  claim [stack-value-preserves-stack]:
    <expr> evaluate(decoded(0, 1, codeAt(0, stackValueOp, 1, .Instructions), .Bytes),
                    C:Context, 1, locationPurpose)
        => finished(decoded(0, 1, codeAt(0, stackValueOp, 1, .Instructions), .Bytes), C, 1, value(V), locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(S:Stack, V:Value) => push(S, V) </stack>
endmodule
