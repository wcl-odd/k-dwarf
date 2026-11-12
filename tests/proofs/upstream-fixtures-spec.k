requires "../../semantics/execution/core.k"

module UPSTREAM-FIXTURES-SPEC
  imports DWARF-CORE

  // §2.5.1.1 中带显式基础类型的块保留其 64 位类型，不按 32 位地址宽截断。
  // 任意初始栈前缀保持；常量块的高位在结果中仍可见。
  claim [typed-block-preserves-own-width]:
    <expr> evaluate(decoded(0, 2, codeAt(0, constTypeOp(1, byteCons(1, byteCons(0, byteCons(0, byteCons(0, byteCons(1, byteCons(0, byteCons(0, byteCons(0, .Bytes))))))))), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(32, little, 1 |-> base("u64", "DW_ATE_unsigned", 64, 8), .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, constTypeOp(1, byteCons(1, byteCons(0, byteCons(0, byteCons(0, byteCons(1, byteCons(0, byteCons(0, byteCons(0, .Bytes))))))))), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
        value(val(4294967297, base("u64", "DW_ATE_unsigned", 64, 8))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> S:Stack => push(S, val(4294967297, base("u64", "DW_ATE_unsigned", 64, 8))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>

  // 精确请求表没有 (4096,1) 时，derefOp 不适用；不能拼接其他请求或补零。
  // 此可达性性质证明 nopOp 前缀执行后到达该现场；不可转移另由双后端预算复核。
  claim [missing-request-prefix-reaches-stuck-scene]:
    <expr> evaluate(decoded(0, 2, codeAt(0, nopOp, 1, codeAt(1, derefOp(1), 2, .Instructions)), .Bytes),
      (ctx(64, little, .Map, .Map, requestMemoryMode |-> 1, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> push(S:Stack, val(4096, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
endmodule
