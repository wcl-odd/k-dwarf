requires "../../semantics/execution/core.k"

module CONVERSION-SPEC
  imports DWARF-CORE

  // 源 signed8 的可表示数学整数，转换到 signed16 后保持数值和任意栈前缀。
  claim [convert-preserves-value-and-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, (1 |-> base("s16", "DW_ATE_signed", 16, 2)), .Map, .Map, noInt, noInt, unspecified, _:Map, _:Int, _:OptionalInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
                  value(val(N, base("s16", "DW_ATE_signed", 16, 2))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(N:Int, base("s8", "DW_ATE_signed", 8, 1)))
         => push(S, val(N, base("s16", "DW_ATE_signed", 16, 2))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires -128 <=Int N andBool N <Int 128

  // 同宽 reinterpret 保持低八位，目标 unsigned 代表值就是该位串的非负值。
  claim [reinterpret-preserves-bits-and-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, reinterpretOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, (1 |-> base("u8", "DW_ATE_unsigned", 8, 2)), .Map, .Map, noInt, noInt, unspecified, _:Map, _:Int, _:OptionalInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, reinterpretOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
                  value(val(bits(N, 8), base("u8", "DW_ATE_unsigned", 8, 2))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(N:Int, base("s8", "DW_ATE_signed", 8, 1)))
         => push(S, val(bits(N, 8), base("u8", "DW_ATE_unsigned", 8, 2))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires -128 <=Int N andBool N <Int 128

  // generic 目标的 reinterpret 保留原整数代表，不能把负数默默改为无符号代表。
  claim [reinterpret-generic-keeps-representative]:
    <expr> evaluate(decoded(0, 2, codeAt(0, reinterpretOp(0), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, _:Map, _:Int, _:OptionalInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, reinterpretOp(0), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
                  value(val(N, g)), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(N:Int, base("s64", "DW_ATE_signed", 64, 8))) => push(S, val(N, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires fitsSigned(N, 64)

  // generic 的两个整数代表都按低八位无符号数扩展，不依赖原数学 Int 的正负。
  claim [convert-generic-unsigned-widens-preserving-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(8, little, (1 |-> base("s16", "DW_ATE_signed", 16, 2)), .Map, .Map,
           noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
          value(val(bits(N, 8), base("s16", "DW_ATE_signed", 16, 2))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(N:Int, g))
         => push(S, val(bits(N, 8), base("s16", "DW_ATE_signed", 16, 2))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires -128 <=Int N andBool N <Int 256

  claim [convert-generic-unsigned-target-preserves-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(8, little, (1 |-> base("u16", "DW_ATE_unsigned", 16, 2)), .Map, .Map,
           noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, convertOp(1), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
          value(val(bits(N, 8), base("u16", "DW_ATE_unsigned", 16, 2))), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(N:Int, g))
         => push(S, val(bits(N, 8), base("u16", "DW_ATE_unsigned", 16, 2))) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>
    requires -128 <=Int N andBool N <Int 256
endmodule
