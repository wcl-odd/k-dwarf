requires "execution/core.k"
requires "frontend/frontend.k"

// Compatible runtime entry: pure frontend preparation enters the independent core without consuming operation-execution rewrites.
module DWARF
  imports DWARF-CORE
  imports DWARF-FRONTEND
  syntax KItem ::= inputError(Program, Context, String) [symbol(inputError)]
  rule initialPosition(E:Program) => inputStart(E)
  rule initialControl(E:Program, C, PURPOSE) =>
    evaluate(prepareProgram(E, encodingOf(C)), prepareContext(C), inputEnd(E), PURPOSE)
    requires validInput(E)
  rule initialControl(E:Program, C, _:Purpose) => inputError(E, C,
    "invalid input: offsets must strictly increase; empty text must end at zero; hex bytes need exactly two digits")
    requires notBool validInput(E)
endmodule
