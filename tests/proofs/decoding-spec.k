requires "../../semantics/dwarf.k"

// 具体纯查询检查：通过空描述保留查询结果，不新增任何 DWARF 操作。
module DECODING-SPEC
  imports DWARF

  claim [raw-boundaries-and-lengths]:
    <expr> evaluate(decoded(0, 0, .Instructions, .Bytes), (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, _:Map, _:Int, _:OptionalInt) #as C), 0, locationPurpose)
        => finished(decoded(0, 0, .Instructions, .Bytes), C, 0, unavailable, locationPurpose) </expr>
    <pc> 0 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(push(push(push(push(push(push(push(push(.Stack, val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), -1, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 0, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 1, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 2, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 3, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 4, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 5, C) #then 1 #else 0 #fi), g)), val(next((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 0, C), g)), val(next((#token("10", "HexByte") #token("80", "HexByte") #token("01", "HexByte") #token("31", "HexByte") .HexProgram), 3, C), g))
         => push(push(push(push(push(push(push(push(push(.Stack, val(0, g)), val(1, g)), val(0, g)), val(0, g)), val(1, g)), val(1, g)), val(0, g)), val(3, g)), val(4, g)) </stack>

  claim [declared-text-boundaries]:
    <expr> evaluate(decoded(0, 0, .Instructions, .Bytes), (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, _:Map, _:Int, _:OptionalInt) #as C), 0, locationPurpose)
        => finished(decoded(0, 0, .Instructions, .Bytes), C, 0, unavailable, locationPurpose) </expr>
    <pc> 0 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(push(push(push(push(push(.Stack, val((#if isBoundary((-3 : DW_OP_lit1, -1 : DW_OP_stack_value, 0), -4, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((-3 : DW_OP_lit1, -1 : DW_OP_stack_value, 0), -3, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((-3 : DW_OP_lit1, -1 : DW_OP_stack_value, 0), -2, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((-3 : DW_OP_lit1, -1 : DW_OP_stack_value, 0), -1, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((-3 : DW_OP_lit1, -1 : DW_OP_stack_value, 0), 0, C) #then 1 #else 0 #fi), g)), val((#if isBoundary((-3 : DW_OP_lit1, -1 : DW_OP_stack_value, 0), 1, C) #then 1 #else 0 #fi), g))
         => push(push(push(push(push(push(.Stack, val(0, g)), val(1, g)), val(0, g)), val(1, g)), val(1, g)), val(0, g)) </stack>
  // 前端字节解码后接独立执行核心；代码准备仍是纯函数。
  claim [raw-dup-drop-preserves-nonempty-stack]:
    <expr> evaluate(prepareProgram((#token("12", "HexByte") #token("13", "HexByte") .HexProgram), encoding(64, little, 4)), C:Context, 2, locationPurpose)
        => finished(prepareProgram((#token("12", "HexByte") #token("13", "HexByte") .HexProgram), encoding(64, little, 4)), C, 2, memory(N), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> push(S:Stack, val(N:Int, T:Ty)) => push(S, val(N, T)) </stack>
endmodule
