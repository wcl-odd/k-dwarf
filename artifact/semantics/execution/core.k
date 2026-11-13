requires "runtime.k"

// The shared configuration accepts decoded input. The integrated frontend extends Input with pure initialization equations.
module DWARF-STATE
  imports DWARF-RUNTIME
  imports K-EQUAL
  syntax Input ::= DecodedExpression
  syntax KItem ::= evaluate(DecodedExpression, Context, Int, Purpose) [symbol(evaluation)]
                 | finished(DecodedExpression, Context, Int, EvaluationResult, Purpose) [symbol(finishedEvaluation)]
  syntax KItem ::= initialControl(Input, Context, Purpose) [function]
  rule initialControl(E:DecodedExpression, C, PURPOSE) => evaluate(E, C, inputEnd(E), PURPOSE)
  syntax Int ::= initialPosition(Input) [function]
  rule initialPosition(E:DecodedExpression) => inputStart(E)
  configuration
    <dwarf>
      <expr maincell=""> initialControl($PGM:Input, $CONTEXT:Context, $PURPOSE:Purpose) </expr>
      <pc> initialPosition($PGM:Input) </pc>
      <stack> $STACK:Stack </stack>
      <fragments> fragments(initialPosition($PGM:Input), noLocation, .Pieces,
                            objectBits(0, 0, 0), $STACK:Stack ==K .Stack) </fragments>
    </dwarf>
endmodule

// Independent execution rules do not import source syntax, decoding, or normalization.
module DWARF-EXECUTION
  imports DWARF-STATE
  // Reading these rules: opAt(E,P) queries a decoded operation; next(E,P) queries its fixed next boundary.
  // E is the fixed decoded expression; execution rules import neither byte nor text decoders.
  // ctx(...) #as C extracts the required fields while binding the whole read-only interface to C.
  // old => new in <pc>/<stack> updates both cells in the same rewrite; omitted contents remain unchanged.
  // :=K matches operation shapes; #let binds operands within its own #in without introducing an execution phase.
  // requires checks all preconditions; failure gives no transition (natural stuckness) and preserves every actual cell.
  // No error constructor or diagnostic rewrite is produced; stuckness alone does not establish that DWARF is invalid.
  // Nested evaluation also stops in the current expression; return items and their saved caller state are preserved.

  // K sequence items store return information; the tail is neither an evaluator wrapper nor a predecoded table.
  // Entering and returning are explicit rewrites included in the budget. An ordinary successful operation still takes one rewrite.
  syntax KItem ::= returnCall(DecodedExpression, Context, Int, Int, Int, Purpose, FragmentState) [symbol(returnCall)]
                 | returnEntry(DecodedExpression, Context, Int, Int, Int, Purpose, FragmentState, Stack) [symbol(returnEntry)]

  // Call saves the next position, original inputs, and piece state; the called expression shares the operand stack.
  // An empty attribute, including a known DIE with no location attribute, is a no-op call; an unknown DIE has no transition.
  rule [Call]:
       <expr> evaluate(E, C, END, PURPOSE) =>
         evaluate(dieCode(operationDIE(E, P, C)), dieContext(C, operationDIE(E, P, C)),
                  inputEnd(dieCode(operationDIE(E, P, C))), procedurePurpose)
         ~> returnCall(E, C, END, P, next(E, P), PURPOSE, F) ... </expr>
       <pc> P => 0 </pc>
       <fragments> F => fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), true) </fragments>
       requires P <Int END andBool isCall(opAt(E, P))
         andBool hasDIE(lookupDIE(runtimeTable(C, "dies"), referencedDIE(opAt(E, P), C)))

  // ReturnCall restores the caller's NEXT after the procedure reaches its own END; the shared stack is neither copied nor cleared.
  rule [ReturnCall]:
       <expr> evaluate(_, _, END, procedurePurpose) ~> returnCall(E, C, ROOTEND, _, NEXT, PURPOSE, F)
           => evaluate(E, C, ROOTEND, PURPOSE) ... </expr>
       <pc> END => NEXT </pc>
       <fragments> _ => F </fragments>

  // Entry uses independently supplied function-entry state and an empty stack. Current-state data never fill missing entry registers.
  rule [Entry]:
       <expr> evaluate(E, C, END, PURPOSE) =>
         (#let entryValueOp(B) = opAt(E, P)
          #in evaluate(B, getContext(entryContext(C)), inputEnd(B), entryPurpose))
         ~> returnEntry(E, C, END, P, next(E, P), PURPOSE, F, S) ... </expr>
       <pc> P => 0 </pc>
       <stack> S => .Stack </stack>
       <fragments> F => fragments(0, noLocation, .Pieces, objectBits(0, 0, 0), true) </fragments>
       requires P <Int END andBool (entryValueOp(_) :=K opAt(E, P)) andBool hasContext(entryContext(C))

  // An ordinary entry expression must leave exactly one value; a standalone register description separately reads the entry register.
  rule [ReturnEntry]:
       <expr> evaluate(_, _, END, entryPurpose) ~> returnEntry(E, C, ROOTEND, _, NEXT, PURPOSE, F, S)
           => evaluate(E, C, ROOTEND, PURPOSE) ... </expr>
       <pc> END => NEXT </pc>
       <stack> push(.Stack, V) => push(S, V) </stack>
       <fragments> _ => F </fragments>

  rule [EntryRegister]:
       <expr> evaluate(E0, (ctx(A, _, _, RS, _, _, _, _, _, _, _) #as C0), END, entryPurpose)
          ~> returnEntry(E, C, ROOTEND, _, NEXT, PURPOSE, F, S) => evaluate(E, C, ROOTEND, PURPOSE) ... </expr>
       <pc> 0 => NEXT </pc>
       <stack> .Stack => (#let regxOp(R) = opAt(E0, 0) #in push(S, val(bits(getInt(lookupInt(RS, R)), A), g))) </stack>
       <fragments> _ => F </fragments>
       requires (regxOp(_) :=K opAt(E0, 0)) andBool next(E0, 0) ==Int END
         andBool (#let regxOp(R) = opAt(E0, 0) #in hasInt(lookupInt(RS, R)))

  // TLS tables supply only the current module/thread translation; K performs the stack pop and push.
  rule [TLS]:
       <expr> evaluate(E, C, END, _:Purpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(OFFSET, T)) => push(S, val(getInt(lookupInt(runtimeTable(C, "tls"), OFFSET)), g)) </stack>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       requires P <Int END andBool opAt(E, P) ==K formTlsAddressOp
         andBool integerType(T) andBool hasInt(lookupInt(runtimeTable(C, "tls"), OFFSET))

  // Address-space reads take the address from the top and the space identifier from below; both must be integral. Failure pops neither.
  rule [XDeref]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _, _, _, _, _) #as C), END, _:Purpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> push(push(S, val(SPACE, TS)), val(ADDR, TA)) =>
         (#let xderefOp(SIZE) = opAt(E, P) #in push(S, val(getInt(readAddressSpace(C, SPACE, SIZE, ADDR)), g))) </stack>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       requires P <Int END andBool (xderefOp(_) :=K opAt(E, P))
         andBool integerType(TS) andBool integerType(TA)
         andBool (#let xderefOp(SIZE) = opAt(E, P) #in validReadSize(SIZE, g, A) andBool hasInt(readAddressSpace(C, SPACE, SIZE, ADDR)))

  // XDerefType: [S,SPACE,ADDR] -> [S,V:TYPE], replacing entries only after type, size, and address-space reads succeed.
  // TYPE may be wider than the address; ordinary generic read-capacity restrictions must not truncate it.
  rule [XDerefType]:
       <expr> evaluate(E, (ctx(A, _, TYPES, _, _, _, _, _, _, _, _) #as C), END, _:Purpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> push(push(S, val(SPACE, TS)), val(ADDR, TA)) =>
         (#let xderefTypeOp(SIZE, REF) = opAt(E, P)
          #in push(S, getValue(interpretRead(readAddressSpace(C, SPACE, SIZE, ADDR), getType(lookupType(TYPES, REF)))))) </stack>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       requires P <Int END andBool (xderefTypeOp(_, _) :=K opAt(E, P))
         andBool integerType(TS) andBool integerType(TA)
         andBool (#let xderefTypeOp(SIZE, REF) = opAt(E, P) #in hasType(lookupType(TYPES, REF))
           andBool validReadSize(SIZE, getType(lookupType(TYPES, REF)), A) andBool hasInt(readAddressSpace(C, SPACE, SIZE, ADDR)))

  // Implicit pointers preserve the .debug_info reference identity and signed byte offset rather than inventing an address.
  rule [ImplicitPointer]:
       <expr> evaluate(E, C, END, locationPurpose) =>
         (#let implicitPointerOp(REF, OFF) = opAt(E, P)
          #in finished(E, C, END, implicitPointer(REF, OFF), locationPurpose)) ... </expr>
       <pc> P => END </pc>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>
       requires P ==Int inputStart(E) andBool P <Int END
         andBool (implicitPointerOp(_, _) :=K opAt(E, P)) andBool next(E, P) ==Int END
         andBool (#let implicitPointerOp(REF, _) = opAt(E, P) #in hasDIE(lookupDIE(runtimeTable(C, "dies"), REF)))

  // Const shares one rule across constant forms; normalize checks source operand ranges.
  // Keep the low A bits and attach generic type g; for A=8, 256 becomes 0 and -1 becomes 255.
  rule [Const]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let constOp(N) = opAt(E, P)
                         #in push(S, val(bits(N, A), g))) </stack>
       requires P <Int END andBool (constOp(_) :=K opAt(E, P))

  // Both index operations use the same .debug_addr table; normalize checks nonnegative operands.
  // TypedConstant: [S] -> [S,N:T]. T must be a base type in the current CU;
  // the block length equals T's byte_size, and all bytes follow target byte order. T may exceed the address width.
  rule [TypedConstant]:
       <expr> evaluate(E, (ctx(_, ORDER, TS, _, _, _, _, _, _, _, _) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let constTypeOp(REF, B) = opAt(E, P)
         #in push(S, getValue(constantValue(B, ORDER, lookupType(TS, REF))))) </stack>
       requires P <Int END andBool (constTypeOp(_, _) :=K opAt(E, P))
         andBool (#let constTypeOp(REF, B) = opAt(E, P)
           #in hasValue(constantValue(B, ORDER, lookupType(TS, REF))))

  // TypedRegister reads register contents rather than creating a register location. It changes their type interpretation;
  // the contents need not already be a signed mathematical representative; the encoding interprets the low effective bits.
  rule [TypedRegister]:
       <expr> evaluate(E, (ctx(A, _, TS, RS, _, _, _, _, _, _, _) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let regvalTypeOp(R, REF) = opAt(E, P)
         #in push(S, getValue(registerTypedValue(lookupInt(RS, R), lookupType(TS, REF), physicalRegisterWidth(RS, R, A))))) </stack>
       requires P <Int END andBool (regvalTypeOp(_, _) :=K opAt(E, P))
         andBool (#let regvalTypeOp(R, REF) = opAt(E, P)
           #in hasValue(registerTypedValue(lookupInt(RS, R), lookupType(TS, REF), physicalRegisterWidth(RS, R, A))))

  // addrx applies an externally verified module load bias; constx keeps the link-time constant. Missing entries give no transition.
  rule [AddrIndex]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _, _, DA, BIAS, _) #as C), END, _:Purpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let addrxOp(I) = opAt(E, P)
          #in push(S, val(bits(getInt(lookupInt(DA, I)) +Int BIAS, A), g))) </stack>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       requires P <Int END andBool (addrxOp(_) :=K opAt(E, P))
         andBool (#let addrxOp(I) = opAt(E, P) #in hasInt(lookupInt(DA, I)))

  rule [ConstIndex]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _, _, DA, _, _) #as C), END, _:Purpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let constxOp(I) = opAt(E, P)
          #in push(S, val(bits(getInt(lookupInt(DA, I)), A), g))) </stack>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       requires P <Int END andBool (constxOp(_) :=K opAt(E, P))
         andBool (#let constxOp(I) = opAt(E, P) #in hasInt(lookupInt(DA, I)))

  // The external object whose attribute is evaluated supplies the object address; zero is known, never guessed from SP or the stack.
  rule [ObjectAddress]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, _, _, _, _, someInt(ADDR)) #as C), END, _:Purpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> S => push(S, val(ADDR, g)) </stack>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       requires P <Int END andBool opAt(E, P) ==K pushObjectAddressOp

  // Breg: RS is the register table; execution requires a successful integer lookup for register R.
  // Add any offset D and push the result modulo 2^A: [S] -> [S,(RS[R]+D):g].
  rule [Breg]:
       <expr> evaluate(E, (ctx(A, _, _, RS, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let bregxOp(R, D) = opAt(E, P)
                         #in push(S, val(bits(getInt(lookupInt(RS, R)) +Int D, A), g))) </stack>
       requires P <Int END andBool (bregxOp(_, _) :=K opAt(E, P))
         andBool (#let bregxOp(R, _) = opAt(E, P) #in hasInt(lookupInt(RS, R)))

  // Fbreg: the external frame base is an A-bit machine value; the JSON frontend checks 0 <= FB < 2^A.
  // someInt(FB) requires a known input; noInt does not match. D may be positive or negative; the result wraps to A bits.
  rule [Fbreg]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, someInt(FB), _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let fbregOp(D) = opAt(E, P)
                         #in push(S, val(bits(FB +Int D, A), g))) </stack>
       requires P <Int END andBool (fbregOp(_) :=K opAt(E, P))

  // CallFrameCFA: CFA and frame base are independent external inputs; neither SP nor FB supplies an implicit default.
  // Push a known address-width machine value as generic: [S] -> [S,CFA:g]; an unknown CFA has no applicable rule.
  rule [CallFrameCFA]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, someInt(CFA), _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => push(S, val(CFA, g)) </stack>
       requires P <Int END andBool opAt(E, P) ==K callFrameCfaOp

  // Deref: Section 2.5.1.3 requires an integral address operand; floating-point bits cannot serve as an address.
  // The top entry ADDR supplies the address; S is the unchanged stack prefix.
  // Replace [S,ADDR] with [S,N:g] only if the size fits generic capacity and all required bytes are present.
  // C retains all inputs, including byte order and memory; failure preserves the full address entry and P.
  rule [Deref]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(ADDR, ADDRTYPE)) =>
                   (#let derefOp(SIZE) = opAt(E, P)
                      #in push(S, val(getInt(readMemory(C, SIZE, ADDR)), g))) </stack>
       requires P <Int END andBool integerType(ADDRTYPE) andBool (derefOp(_) :=K opAt(E, P))
         andBool (#let derefOp(SIZE) = opAt(E, P)
                     #in validReadSize(SIZE, g, A) andBool hasInt(readMemory(C, SIZE, ADDR)))

  // DerefType looks up REF in TS and requires SIZE to equal the type's storage size in bytes.
  // Interpret the same memory integer's low effective bits and sign, retaining type identity: [S,ADDR] -> [S,N:T].
  // If type, size, or byte preconditions fail, preserve the original stack and position.
  rule [DerefType]:
       <expr> evaluate(E, (ctx(_, _, TS, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(ADDR, ADDRTYPE)) =>
                   (#let derefTypeOp(SIZE, REF) = opAt(E, P)
                      #in push(S, getValue(readTypedValue(C, SIZE, lookupType(TS, REF), ADDR)))) </stack>
       requires P <Int END andBool integerType(ADDRTYPE) andBool (derefTypeOp(_, _) :=K opAt(E, P))
         andBool (#let derefTypeOp(SIZE, REF) = opAt(E, P)
                     #in hasValue(readTypedValue(C, SIZE, lookupType(TS, REF), ADDR)))

  // Pick queries a complete Value by zero-based depth K from the top and appends its copy to S without changing the type.
  // dup/over normalize to pickOp(0)/pickOp(1); an out-of-range index or shallow stack gives no transition.
  rule [Pick]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> S => (#let pickOp(K) = opAt(E, P)
                         #in push(S, getValue(stackAt(S, K)))) </stack>
       requires P <Int END andBool (pickOp(_) :=K opAt(E, P))
         andBool (#let pickOp(K) = opAt(E, P)
                     #in 0 <=Int K andBool K <=Int 255 andBool hasValue(stackAt(S, K)))

  // Drop: push(S,_) requires a nonempty stack; remove its top and retain prefix S.
  rule [Drop]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, _) => S </stack>
       requires P <Int END andBool opAt(E, P) ==K dropOp

  // Swap: V1 is the top; in bottom-to-top order, [V2,V1] -> [V1,V2]. Types may differ.
  rule [Swap]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(push(S, V2), V1) => push(push(S, V1), V2) </stack>
       requires P <Int END andBool opAt(E, P) ==K swapOp

  // Rot requires at least three entries: [V3,V2,V1] -> [V1,V3,V2], or [a,b,c] -> [c,a,b].
  // Preserve prefix S and every complete Value while advancing the execution position.
  rule [Rot]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(push(push(S, V3), V2), V1) => push(push(push(S, V1), V3), V2) </stack>
       requires P <Int END andBool opAt(E, P) ==K rotOp

  // Unary: [S,N:T] -> [S,N':T]. uop handles width, signed interpretation, and applicability.
  // Replace the top and advance only on a successful numeric query; failure preserves the entry and all inputs.
  rule [Unary]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(N, T)) =>
         (#let unaryOp(U) = opAt(E, P)
            #in push(S, val(getInt(uop(U, N, T, A)), T))) </stack>
       requires P <Int END andBool (unaryOp(_) :=K opAt(E, P))
         andBool (#let unaryOp(U) = opAt(E, P) #in hasInt(uop(U, N, T, A)))

  // Binary: N1 is the top; repeated variable T requires identical complete types, including identity.
  // [S,N2:T,N1:T] -> [S,N':T], computing N2 OP N1 and preserving the type.
  rule [Binary]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(push(S, val(N2, T)), val(N1, T)) =>
         (#let binaryOp(B) = opAt(E, P)
            #in push(S, val(getInt(bop(B, N1, N2, T, A)), T))) </stack>
       requires P <Int END andBool (binaryOp(_) :=K opAt(E, P))
         andBool (#let binaryOp(B) = opAt(E, P) #in hasInt(bop(B, N1, N2, T, A)))

  // Compare also requires identical operand types; compare N2 CMP N1 and return 0:g or 1:g.
  // Generic comparisons use a signed view; different integer representatives of the same bits still compare equal.
  rule [Compare]:
       <expr> evaluate(E, (ctx(A, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(push(S, val(N2, T)), val(N1, T)) =>
         (#let compareOp(CMP) = opAt(E, P)
            #in push(S, val(getInt(cmp(CMP, N1, N2, T, A)), g))) </stack>
       requires P <Int END andBool (compareOp(_) :=K opAt(E, P))
         andBool (#let compareOp(CMP) = opAt(E, P) #in hasInt(cmp(CMP, N1, N2, T, A)))

  // Convert: [S,N:SOURCE] -> [S,N':TARGET], leaving prefix S unchanged.
  // SOURCE determines integer interpretation; integer results truncate to the target width, replacing the earlier no-overflow restriction.
  // Missing types, Boolean conversion, or unmet floating-point conversion preconditions preserve the stack and position.
  rule [Convert]:
       <expr> evaluate(E, (ctx(A, _, TS, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(N, SOURCE)) =>
         (#let convertOp(REF) = opAt(E, P)
            #in push(S, val(getInt(convert(N, SOURCE, resolveType(TS, REF), A)),
                            getType(resolveType(TS, REF))))) </stack>
       requires P <Int END andBool (convertOp(_) :=K opAt(E, P))
         andBool (#let convertOp(REF) = opAt(E, P)
                     #in hasInt(convert(N, SOURCE, resolveType(TS, REF), A)))

  // Reinterpret replaces only the top type and its integer representative, preserving the low effective bits.
  // Equal widths may have distinct identities; unequal widths or missing types preserve the stack and position.
  rule [Reinterpret]:
       <expr> evaluate(E, (ctx(A, _, TS, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(N, SOURCE)) =>
         (#let reinterpretOp(REF) = opAt(E, P)
            #in push(S, val(getInt(reinterpret(N, SOURCE, resolveType(TS, REF), A)),
                            getType(resolveType(TS, REF))))) </stack>
       requires P <Int END andBool (reinterpretOp(_) :=K opAt(E, P))
         andBool (#let reinterpretOp(REF) = opAt(E, P)
                     #in hasInt(reinterpret(N, SOURCE, resolveType(TS, REF), A)))

  // Nop preserves the whole stack, including an empty one, and advances to the next position.
  rule [Nop]:
       <expr> evaluate(E, C, END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       requires P <Int END andBool opAt(E, P) ==K nopOp

  // Skip: D is a signed 16-bit mathematical integer; the target is NEXT+D, not P+D, with no A-bit wrapping.
  // Boundary queries inspect decoded records without executing skipped operations; Memory still interprets a jump to END.
  // Backward jumps and self-loops are allowed; budget exhaustion preserves the actual state and does not make a loop complete.
  rule [Skip]:
       <expr> evaluate(E, C, END, _:Purpose) ... </expr>
       <fragments> fragments(START, noLocation, _, _, _) </fragments>
       <pc> P => (#let skipOp(D) = opAt(E, P)
                      #in next(E, P) +Int D) </pc>
       requires P <Int END andBool (skipOp(_) :=K opAt(E, P))
         andBool (#let skipOp(D) = opAt(E, P)
                      #in localBoundary(E, START, next(E, P) +Int D))

  // BraTrue: [S,N:T] -> [S] for nonzero N; T need not be Boolean or generic.
  // The target must be an operation start or END; pop the condition and update the position only after all preconditions succeed.
  // An unavailable target does not consume the condition; the fixed expression and interface remain unchanged.
  rule [BraTrue]:
       <expr> evaluate(E, C, END, _:Purpose) ... </expr>
       <fragments> fragments(START, noLocation, _, _, _) </fragments>
       <pc> P => (#let braOp(D) = opAt(E, P)
                      #in next(E, P) +Int D) </pc>
       <stack> push(S, val(N, _)) => S </stack>
       requires P <Int END andBool N =/=Int 0 andBool (braOp(_) :=K opAt(E, P))
         andBool (#let braOp(D) = opAt(E, P)
                      #in localBoundary(E, START, next(E, P) +Int D))

  // BraFalse: [S,0:T] -> [S], falling through to NEXT.
  // The untaken NEXT+D need not be a valid boundary, but the displacement must still fit its signed 16-bit source field.
  rule [BraFalse]:
       <expr> evaluate(E, C, END, _:Purpose) ... </expr>
       <fragments> fragments(_, noLocation, _, _, _) </fragments>
       <pc> P => next(E, P) </pc>
       <stack> push(S, val(0, _)) => S </stack>
       requires P <Int END andBool (braOp(_) :=K opAt(E, P))

  // The value purpose returns the complete computed top value rather than interpreting it as an object address.
  // An empty input may return an externally supplied initial top; an empty stack has no result. Preserve fixed inputs and the whole stack.
  rule [Scalar]:
       <expr> evaluate(E, C, END, valuePurpose) => finished(E, C, END, scalarResult(V), valuePurpose) ... </expr>
       <pc> END </pc>
       <stack> push(_, V) </stack>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>

  // Empty: an empty description under location purpose returns unavailable and preserves the complete initial stack.
  // It does not replace failed queries or an empty final stack from a nonempty expression.
  rule [Empty]:
       <expr> evaluate(E, C, END, locationPurpose) => finished(E, C, END, unavailable, locationPurpose) ... </expr>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>
       <pc> END </pc>
       requires emptyInput(E)

  // Memory: a nonempty expression has reached END with at least one stack entry.
  // Any supported top type T may supply address N; lower entries are ignored but retained, and the object is not read.
  // Preserve N as supplied: do not check memory existence or implicitly convert a negative representative to nonnegative.
  // A budget ending exactly at END still needs this completion rewrite; no result rule applies to an empty final stack.
  rule [Memory]:
       <expr> evaluate(E, C, END, locationPurpose) => finished(E, C, END, memory(N), locationPurpose) ... </expr>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>
       <pc> END </pc>
       <stack> push(_, val(N, _)) </stack>
       requires notBool emptyInput(E)

  // Register: DWARF 5 Section 2.6.1.1.3 requires a register operation to form the entire simple description.
  // P must be the input start and the sole operation's NEXT must equal END; computation prefixes, suffixes,
  // and registers reached after a jump therefore do not qualify. normalize ensures a nonnegative R.
  // NEXT=END is explicit integer equality; variables in :=K are locally bound and cannot test the outer END by name alone.
  // Return only register identity: do not query its contents or read or modify any stack entry.
  // Even absent register contents or a nonempty initial stack allow direct completion in one rewrite.
  rule [Register]:
       <expr> evaluate(E, C, END, locationPurpose)
           => (#let regxOp(R) = opAt(E, P)
                    #in finished(E, C, END, register(R), locationPurpose)) ... </expr>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>
       <pc> P => END </pc>
       requires P <Int END andBool P ==Int inputStart(E)
         andBool (regxOp(_) :=K opAt(E, P))
         andBool next(E, P) ==Int END

  // StackValue is a location-result marker, not a stack transformation.
  // Complete only when the query returns instruction(stackValueOp,END) and the stack is nonempty.
  // Match the operation and its next position together; a failed decode must not call next without a result.
  // Preserve the prefix and top; do not pass through Memory or take an additional completion step.
  // A following ordinary operation or empty stack preserves the state; PieceStackValue handles an immediately following piece delimiter.
  // The NEXT=END condition matches the final-marker form in the current paper, Section 3.4.
  rule [StackValue]:
       <expr> evaluate(E, (ctx(_, _, _, _, _, _, _:OptionalInt, _:Architecture, _:Map, _:Int, _:OptionalInt) #as C), END, locationPurpose)
           => finished(E, C, END, value(V), locationPurpose) ... </expr>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>
       <pc> P => END </pc>
       <stack> push(_, V) </stack>
       requires P <Int END andBool instructionAt(E, P) ==K instruction(stackValueOp, END)

  // ImplicitValue completes with standalone bytes, without interpreting a machine integer or modifying the initial stack.
  rule [ImplicitValue]:
       <expr> evaluate(E, C, END, locationPurpose)
         => (#let implicitValueOp(B) = opAt(E, P)
                   #in finished(E, C, END, bytesValue(B), locationPurpose)) ... </expr>
       <pc> P => END </pc>
       <fragments> fragments(_, noLocation, .Pieces, _, _) </fragments>
       requires P ==Int inputStart(E) andBool P <Int END
         andBool (implicitValueOp(_) :=K opAt(E, P))
         andBool next(E, P) ==Int END

  // Piece-specific results: reg/implicit must be the sole description of the fragment, immediately before its delimiter.
  // Save a pending description without changing the stack; the delimiter reads the object, commits the piece, and clears the stack.
  rule [PieceRegister]:
       <expr> evaluate(E, C, END, locationPurpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <fragments> fragments(P, noLocation, PS, BITS, true)
         => (#let regxOp(R) = opAt(E, P)
              #in fragments(P, located(register(R)), PS, BITS, true)) </fragments>
       requires P <Int END andBool (regxOp(_) :=K opAt(E, P))
         andBool followsComposition(E, next(E, P))

  // An implicit block likewise creates only a pending description; its bytes do not become an address-width integer.
  rule [PieceImplicitValue]:
       <expr> evaluate(E, C, END, locationPurpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <fragments> fragments(P, noLocation, PS, BITS, true)
         => (#let implicitValueOp(B) = opAt(E, P)
              #in fragments(P, located(bytesValue(B)), PS, BITS, true)) </fragments>
       requires P <Int END andBool (implicitValueOp(_) :=K opAt(E, P))
         andBool followsComposition(E, next(E, P))

  // stack_value may follow computations but must immediately precede the current piece delimiter; preserve the complete Value.
  rule [PieceStackValue]:
       <expr> evaluate(E, C, END, locationPurpose) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> push(_, V) </stack>
       <fragments> fragments(START, noLocation, PS, BITS, true)
          => fragments(START, located(value(V)), PS, BITS, true) </fragments>
       requires P <Int END andBool opAt(E, P) ==K stackValueOp
         andBool followsComposition(E, next(E, P))

  // ComposePiece commits the piece, advances pc, and clears the whole stack in one rewrite only after all preconditions succeed.
  // An out-of-range source has no result; missing external data instead allow assembly with unknown bits in the mask.
  // The last delimiter completes directly; otherwise start the next piece. Ordinary completion rejects an undelimited trailing fragment.
  syntax KItem ::= afterPiece(DecodedExpression, Context, Int, Int, Pieces, ObjectBits) [function]
  rule afterPiece(E, C, END, END, PS, BITS) => finished(E, C, END, assembledLocation(PS, BITS), locationPurpose)
  rule afterPiece(E, C, END, NEXT, _, _) => evaluate(E, C, END, locationPurpose) requires NEXT =/=Int END
  rule [ComposePiece]:
       <expr> evaluate(E, C, END, locationPurpose)
          => afterPiece(E, C, END, next(E, P),
               appendPiece(PS, pieceDesc(opAt(E, P), getLocation(fragmentLocation(P, START, L, S)))),
               appendBits(BITS, getBits(extractObject(getLocation(fragmentLocation(P, START, L, S)),
                    pieceSize(opAt(E, P)), pieceOffset(opAt(E, P)), C)))) ... </expr>
       <pc> P => next(E, P) </pc>
       <stack> S => .Stack </stack>
       <fragments> fragments(START, L, PS, BITS, true)
          => fragments(next(E, P), noLocation,
               appendPiece(PS, pieceDesc(opAt(E, P), getLocation(fragmentLocation(P, START, L, S)))),
               appendBits(BITS, getBits(extractObject(getLocation(fragmentLocation(P, START, L, S)),
                    pieceSize(opAt(E, P)), pieceOffset(opAt(E, P)), C))), true) </fragments>
       requires canCompose(P <Int END andBool isComposition(opAt(E, P)),
         opAt(E, P), P, START, L, S, C)
endmodule


module DWARF-CORE
  imports DWARF-EXECUTION
endmodule
