requires "../../semantics/execution/core.k"

module COMPOSITION-SPEC
  imports DWARF-CORE

  // 字节值独立完成，任意初始栈不变；字节不会被截断到地址位宽。
  claim [implicit-preserves-stack]:
    <expr> evaluate(decoded(0, 1, codeAt(0, implicitValueOp(byteCons(B:Int, .Bytes)), 1, .Instructions), .Bytes),
                    (ctx(64, little, .Map, .Map, .Map, noInt, noInt, unspecified, _:Map, _:Int, _:OptionalInt) #as C), 1, locationPurpose)
      => finished(decoded(0, 1, codeAt(0, implicitValueOp(byteCons(B, .Bytes)), 1, .Instructions), .Bytes), C, 1,
                  bytesValue(byteCons(B, .Bytes)), locationPurpose) </expr>
    <pc> 0 => 1 </pc>
    <stack> S:Stack => S </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), _:Bool) </fragments>
    requires 0 <=Int B andBool B <Int 256

  // 两个独立片段按地址序连接；第一个字节位于低位。
  claim [pieces-connect-in-address-order]:
    <expr> evaluate(decoded(0, 4, codeAt(0, implicitValueOp(byteCons(17, .Bytes)), 1, codeAt(1, pieceOp(1), 2, codeAt(2, implicitValueOp(byteCons(34, .Bytes)), 3, codeAt(3, pieceOp(1), 4, .Instructions)))), .Bytes),
                    (ctx(64, little, .Map, .Map, .Map, noInt, noInt, aarch64, _:Map, _:Int, _:OptionalInt) #as C), 4, locationPurpose)
      => finished(decoded(0, 4, codeAt(0, implicitValueOp(byteCons(17, .Bytes)), 1, codeAt(1, pieceOp(1), 2, codeAt(2, implicitValueOp(byteCons(34, .Bytes)), 3, codeAt(3, pieceOp(1), 4, .Instructions)))), .Bytes), C, 4,
           composite(appendPiece(appendPiece(.Pieces,
              bytePiece(1, bytesValue(byteCons(17, .Bytes)))),
              bytePiece(1, bytesValue(byteCons(34, .Bytes)))), objectBits(16, 8721, 65535)), locationPurpose) </expr>
    <pc> 0 => 4 </pc>
    <stack> .Stack </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), true)
      => fragments(4, noLocation, appendPiece(appendPiece(.Pieces,
              bytePiece(1, bytesValue(byteCons(17, .Bytes)))),
              bytePiece(1, bytesValue(byteCons(34, .Bytes)))), objectBits(16, 8721, 65535), true) </fragments>

  // 空片段的低八位保持未知，不因后续已知字节而变成零值证据。
  claim [unknown-bits-propagate]:
    <expr> evaluate(decoded(0, 3, codeAt(0, pieceOp(1), 1, codeAt(1, implicitValueOp(byteCons(B:Int, .Bytes)), 2, codeAt(2, pieceOp(1), 3, .Instructions))), .Bytes),
                    (ctx(64, little, .Map, .Map, .Map, noInt, noInt, x86_64, _:Map, _:Int, _:OptionalInt) #as C), 3, locationPurpose)
      => finished(decoded(0, 3, codeAt(0, pieceOp(1), 1, codeAt(1, implicitValueOp(byteCons(B, .Bytes)), 2, codeAt(2, pieceOp(1), 3, .Instructions))), .Bytes), C, 3,
           composite(appendPiece(appendPiece(.Pieces, bytePiece(1, unavailable)),
              bytePiece(1, bytesValue(byteCons(B, .Bytes)))), objectBits(16, 256 *Int B, 65280)), locationPurpose) </expr>
    <pc> 0 => 3 </pc>
    <stack> .Stack </stack>
    <fragments> fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), true)
      => fragments(3, noLocation, appendPiece(appendPiece(.Pieces, bytePiece(1, unavailable)),
              bytePiece(1, bytesValue(byteCons(B, .Bytes)))), objectBits(16, 256 *Int B, 65280), true) </fragments>
    requires 0 <=Int B andBool B <Int 256
endmodule
