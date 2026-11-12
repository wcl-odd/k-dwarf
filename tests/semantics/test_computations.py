"""Section 3.5 integer calculations; expected values follow the paper's tables."""

from test_basic import DwarfTestCase, dwarf, g, snapshot, ty


COMPARISONS = {"eq", "ge", "gt", "le", "lt", "ne"}


class ComputationTests(DwarfTestCase):
    def cases(self, cases, width=8, types=None):
        """Batch independent successful cases; typed operands come from byte memory.

        A case is (opcode suffix, operands in stack order, expected value, type ref).
        Expectations are explicit below, not computed by a second interpreter.
        """
        types = {} if types is None else types
        source, expected, memory = [], [], {}
        address = 0
        for op, operands, value, ref in cases:
            for number in operands:
                if ref is None:
                    source.append(f"DW_OP_consts {number}")
                else:
                    size = types[str(ref)]["byte_size"]
                    for index in range(size):
                        memory[str(address + index)] = (number >> (8 * index)) & 255
                    source.extend([f"DW_OP_addr {address}", f"DW_OP_deref_type {size} {ref}"])
                    address += size
            source.append(f"DW_OP_{op}")
            if ref is None or op.split()[0] in COMPARISONS:
                expected.append(g(value))
            else:
                expected.append({"value": value, "type": {"id": types[str(ref)]["id"]}})
        return self.complete(", ".join(source), expected,
                             snapshot(address_width=width, types=types, memory=memory))

    def stopped_case(self, op, numbers, ref=None, record=None, sentinel=True):
        """Stop after two successful prefix steps and retain the whole input stack."""
        stack = ([g(42)] if sentinel else []) + [
            {"value": n, "type": "g" if ref is None else ref} for n in numbers
        ]
        types = {} if ref is None else {str(ref): record}
        ctx = snapshot(address_width=8, initial_stack=stack, types=types,
                       registers={"1": 3}, framebase=255, memory={"0": 7})
        source = f"DW_OP_lit1, DW_OP_drop, DW_OP_{op}"
        result = self.incomplete(source, ctx, position=2)
        expected = ([g(42)] if sentinel else []) + [
            g(n) if ref is None else {"value": n, "type": {"id": record["id"]}}
            for n in numbers
        ]
        self.assertEqual(result["stack"], expected)
        self.assertEqual(result["end"], 3)
        return result, source, ctx

    def test_generic_machine_arithmetic(self):
        self.cases([
            ("abs", [-7], 7, None), ("abs", [129], 127, None),
            ("neg", [7], -7, None), ("neg", [255], 1, None),
            ("not", [0], 255, None), ("not", [128], 127, None),
            ("plus", [255, 1], 0, None), ("minus", [0, 1], 255, None),
            ("mul", [255, 2], 254, None), ("plus_uconst 255", [1], 0, None),
            ("and", [170, 204], 136, None), ("or", [170, 204], 238, None),
            ("xor", [170, 204], 102, None),
            ("div", [-7, 2], -3, None), ("div", [7, -2], -3, None),
            ("div", [-7, -2], 3, None),
            ("mod", [-7, 2], 1, None), ("mod", [128, 255], 128, None),
            ("shl", [129, 1], 2, None), ("shr", [129, 1], 64, None),
            ("shra", [129, 1], -64, None), ("shra", [255, 0], -1, None),
            ("shl", [1, 7], 128, None), ("shr", [128, 7], 1, None),
            ("shra", [128, 7], -1, None),
        ])

    def test_small_and_wide_generic_widths(self):
        for width in (1, 3, 64, 128):
            with self.subTest(width=width):
                maximum = (1 << width) - 1
                self.cases([
                    ("plus", [maximum, 1], 0, None),
                    ("not", [0], maximum, None),
                    ("plus", [-1, 0], maximum, None),
                    ("shra", [maximum, 0], -1, None),
                    ("plus_uconst 1", [maximum], 0, None),
                ], width=width)

    def test_typed_machine_arithmetic(self):
        records = {
            "1": ty("s3", "DW_ATE_signed", 3, 1),
            "2": ty("u3", "DW_ATE_unsigned", 3, 1),
            "3": ty("bool8", "DW_ATE_boolean", 8, 1),
            "4": ty("sc3", "DW_ATE_signed_char", 3, 1),
            "5": ty("uc3", "DW_ATE_unsigned_char", 3, 1),
            "6": ty("address3", "DW_ATE_address", 3, 1),
            "7": ty("utf3", "DW_ATE_UTF", 3, 1),
            "8": ty("ucs3", "DW_ATE_UCS", 3, 1),
            "9": ty("ascii3", "DW_ATE_ASCII", 3, 1),
        }
        signed = [
            ("plus", [3, 1], -4), ("minus", [-4, 1], 3), ("mul", [3, 3], 1),
            ("abs", [-3], 3), ("neg", [1], -1), ("not", [0], -1),
            ("and", [-1, 2], 2), ("or", [1, 2], 3), ("xor", [-1, 3], -4),
            ("div", [-3, 2], -1), ("div", [3, -2], -1),
            ("mod", [-3, 2], -1), ("mod", [-4, -1], 0),
            ("shl", [3, 1], -2), ("shr", [-4, 1], 2), ("shra", [-4, 1], -2),
            ("plus_uconst 7", [3], 2),
        ]
        unsigned = [
            ("plus", [7, 1], 0), ("minus", [0, 1], 7), ("mul", [7, 2], 6),
            ("neg", [1], 7), ("abs", [7], 1), ("not", [0], 7),
            ("div", [5, 2], 7), ("mod", [5, 2], 1),
            ("shra", [4, 1], 6), ("shr", [4, 1], 2),
            ("plus_uconst 7", [3], 2),
        ]
        cases = [(op, ns, value, ref) for ref in (1, 4) for op, ns, value in signed]
        cases += [(op, ns, value, ref) for ref in (2, 5) for op, ns, value in unsigned]
        cases += [("not", [0], 255, 3), ("plus", [127, 2], 129, 3),
                  ("div", [249, 2], 253, 3), ("mod", [249, 2], 1, 3)]
        cases += [("not", [0], 7, ref) for ref in (6, 7, 8, 9)]
        self.cases(cases, width=16, types=records)

    def test_comparison_views_and_identity(self):
        cases = [(op, [255, 1], value, None) for op, value in
                 [("eq", 0), ("ne", 1), ("lt", 1), ("le", 1), ("gt", 0), ("ge", 0)]]
        cases += [(op, [3, 3], value, None) for op, value in
                  [("eq", 1), ("ne", 0), ("lt", 0), ("le", 1), ("gt", 0), ("ge", 1)]]
        self.cases(cases)
        records = {"1": ty("s3", "DW_ATE_signed", 3, 1),
                   "2": ty("u3", "DW_ATE_unsigned", 3, 1)}
        cases = [(op, [-1, 1], value, 1) for op, value in
                 [("eq", 0), ("ne", 1), ("lt", 1), ("le", 1), ("gt", 0), ("ge", 0)]]
        cases += [(op, [7, 1], value, 2) for op, value in
                  [("eq", 0), ("ne", 1), ("lt", 0), ("le", 0), ("gt", 1), ("ge", 1)]]
        self.cases(cases, types=records)
        # Different Int representatives of the same bit pattern compare equal.
        self.complete("DW_OP_eq", [g(1)],
                      snapshot(address_width=8, initial_stack=[g(-1), g(255)]))
        # References may alias a type identity without creating distinct types.
        self.complete("DW_OP_plus", [{"value": 6, "type": {"id": "shared"}}],
                      snapshot(types={"1": ty("shared"), "2": ty("shared")},
                               initial_stack=[{"value": 3, "type": 1}, {"value": 3, "type": 2}]))

    def test_undefined_arithmetic_preserves_state(self):
        for op, values in [
            ("abs", [128]), ("neg", [128]), ("plus_uconst 256", [1]),
            ("plus_uconst -1", [1]), (f"plus_uconst {1 << 200}", [1]),
            ("div", [7, 0]), ("mod", [7, 0]), ("div", [128, 255]),
            ("shl", [1, 8]), ("shr", [128, 8]), ("shra", [128, 8]),
            ("shra", [128, -1]),
        ]:
            with self.subTest(op=op, values=values):
                self.stopped_case(op, values)
        for op, values, record in [
            ("abs", [4], ty("u3", "DW_ATE_unsigned", 3, 1)),
            ("neg", [-4], ty("s3", "DW_ATE_signed", 3, 1)),
            ("div", [4, 7], ty("u3", "DW_ATE_unsigned", 3, 1)),
            ("mod", [-3, 0], ty("s3", "DW_ATE_signed", 3, 1)),
            ("shl", [1, -1], ty("s3", "DW_ATE_signed", 3, 1)),
            ("plus_uconst 8", [1], ty("u3", "DW_ATE_unsigned", 3, 1)),
        ]:
            with self.subTest(op=op, values=values, record=record):
                self.stopped_case(op, values, ref=1, record=record)
        stopped, source, ctx = self.stopped_case("div", [7, 0])
        before = self.execute(source, ctx, depth=2)
        self.assert_preserved(before, stopped)
        for cell in ("pc", "stack"):
            self.assertEqual(dwarf.find_cell(before["configuration"]["term"], cell),
                             dwarf.find_cell(stopped["configuration"]["term"], cell))

    def test_type_mismatch_and_underflow(self):
        for op, values in [("abs", []), ("plus", [2]), ("eq", [2])]:
            with self.subTest(op=op):
                self.stopped_case(op, values, sentinel=False)
        records = {"1": ty("A", "DW_ATE_unsigned", 8, 1),
                   "2": ty("B", "DW_ATE_unsigned", 8, 1),
                   "3": ty("g", "DW_ATE_unsigned", 8, 1)}
        for op, stack in [
            ("plus", [{"value": 2, "type": 1}, {"value": 3, "type": 2}]),
            ("eq", [{"value": 2, "type": 1}, {"value": 2, "type": 2}]),
            ("eq", [g(2), {"value": 2, "type": 3}]),
        ]:
            with self.subTest(op=op, stack=stack):
                result = self.incomplete(f"DW_OP_{op}", snapshot(types=records, initial_stack=stack))
                expected = [g(item["value"]) if item["type"] == "g" else
                            {"value": item["value"], "type": {"id": records[str(item["type"])]["id"]}}
                            for item in stack]
                self.assertEqual(result["stack"], expected)

    def test_computation_result_addresses(self):
        ctx = snapshot(address_width=8, memory={"249": 42})
        stopped = self.incomplete("DW_OP_lit7, DW_OP_neg, DW_OP_deref_size 1", ctx, position=2)
        self.assertEqual(stopped["stack"], [g(-7)])
        self.complete("DW_OP_lit7, DW_OP_neg, DW_OP_lit0, DW_OP_plus, DW_OP_deref_size 1", [g(42)], ctx)
        self.complete("DW_OP_lit7, DW_OP_neg, DW_OP_deref_size 0", [g(0)], ctx)
