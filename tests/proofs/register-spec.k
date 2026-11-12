requires "../../semantics/execution/core.k"

module REGISTER-SPEC
  imports DWARF-CORE

  // 单独的 regx 只产生寄存器身份，不查 C 中的寄存器，不使用或修改任意栈 S。
  // 已解码位置查询在性质中；解码／归一化前端另行验证；任意非负编号 R 不受地址宽度限制。
  claim [register-preserves-arbitrary-stack]:
    <expr> evaluate(decoded(0, 1, codeAt(0, regxOp(R:Int), 1, .Instructions), .Bytes), C:Context, 1, locationPurpose)
        => finished(decoded(0, 1, codeAt(0, regxOp(R), 1, .Instructions), .Bytes), C, 1, register(R), locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    <stack> S:Stack => S </stack>
    requires R >=Int 0
endmodule
