requires "../../semantics/execution/core.k"

module RUNTIME-SPEC
  imports DWARF-CORE

  // 调用前后使用同一个栈。空过程正常返回；任意前缀不是新建的局部栈。
  claim [empty-call-preserves-shared-stack]:
    <expr> evaluate(decoded(0, 2, codeAt(0, callUnitOp(32), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little,
        ("runtime" |-> ("dies" |-> (32 |-> preparedDIE(preparedDIE(dieBody(.Bytes, 64, 0, 4, .Map, .Map, noInt, 0, 0), decoded(0, 0, .Instructions, .Bytes)), decoded(0, 0, .Instructions, .Bytes))))),
        .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, callUnitOp(32), 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
           value(V), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, V:Value) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>

  // TLS 偏移不是宿主地址运算；仅查询供应的线程/模块映射，保留原栈前缀。
  claim [tls-preserves-prefix]:
    <expr> evaluate(decoded(0, 2, codeAt(0, formTlsAddressOp, 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes),
      (ctx(64, little, ("runtime" |-> ("tls" |-> (42 |-> 4096))),
        .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 2, locationPurpose)
      => finished(decoded(0, 2, codeAt(0, formTlsAddressOp, 1, codeAt(1, stackValueOp, 2, .Instructions)), .Bytes), C, 2,
           value(val(4096, g)), locationPurpose) </expr>
    <pc> 0 => 2 </pc>
    <stack> push(S:Stack, val(42, g)) => push(S, val(4096, g)) </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), false) </fragments>

  // implicit_pointer 描述引用身份及字节位移，不读取引用对象，不制造地址。
  claim [implicit-pointer-keeps-stack]:
    <expr> evaluate(decoded(0, 1, codeAt(0, implicitPointerOp(32, -1), 1, .Instructions), .Bytes),
      (ctx(64, little,
        ("runtime" |-> ("dies" |-> (32 |-> preparedDIE(preparedDIE(dieBody(.Bytes, 64, 0, 4, .Map, .Map, noInt, 0, 0), decoded(0, 0, .Instructions, .Bytes)), decoded(0, 0, .Instructions, .Bytes))))),
        .Map, .Map, noInt, noInt, unspecified, .Map, 0, noInt) #as C), 1, locationPurpose)
      => finished(decoded(0, 1, codeAt(0, implicitPointerOp(32, -1), 1, .Instructions), .Bytes), C, 1,
           implicitPointer(32, -1), locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> S:Stack </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
endmodule
