requires "../../semantics/execution/core.k"

module FRAME-SPEC
  imports DWARF-CORE

  // 任意栈前缀 S 不变；已知 CFA 原样以 generic 入栈。FB 可为任意可选值。
  claim [cfa-preserves-stack-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, callFrameCfaOp, 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, _FB:OptionalInt, someInt(CFA:Int), unspecified, _:Map, _:Int, _:OptionalInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, callFrameCfaOp, 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
                  value(val(CFA, g)), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> S:Stack => push(S, val(CFA, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    requires fitsUnsigned(CFA, 64)

  // 两种帧输入独立读取：Fbreg 0 取 FB，CFA 操作取 CFA，不以其中一个代替另一个。
  claim [frame-inputs-independent]:
    <expr> evaluate(decoded(0, 3, codeAt(0, fbregOp(0), 1, codeAt(1, callFrameCfaOp, 2, codeAt(2, stackValueOp, 3, .Instructions))), .Bytes),
      (ctx(64, little, .Map, .Map, .Map, someInt(FB:Int), someInt(CFA:Int), unspecified, _:Map, _:Int, _:OptionalInt) #as C), 3, locationPurpose)
      => finished(decoded(0, 3, codeAt(0, fbregOp(0), 1, codeAt(1, callFrameCfaOp, 2, codeAt(2, stackValueOp, 3, .Instructions))), .Bytes), C, 3,
                  value(val(CFA, g)), locationPurpose) </expr>
    <pc> 0 => 3 </pc>
    <stack> S:Stack => push(push(S, val(FB, g)), val(CFA, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    requires fitsUnsigned(FB, 64) andBool fitsUnsigned(CFA, 64)
endmodule
