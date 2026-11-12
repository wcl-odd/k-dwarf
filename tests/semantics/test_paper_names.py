"""Exercise source naming and stable current KAST at the actual K boundary."""
import json
from pathlib import Path
import test_core_separation as core_tests
from test_basic import DwarfTestCase, ROOT, dwarf, snapshot, g

class PaperNamesTests(DwarfTestCase):
    raw = core_tests.CoreSeparationTests.raw
    core_run = core_tests.CoreSeparationTests.core_run
    assert_same = core_tests.CoreSeparationTests.assert_same

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        backend = "haskell" if "haskell" in str(cls.definition) else "llvm"
        cls.core = cls.definition.parent / ("core-" + backend + "-kompiled")

    def test_prepared_kast_runs_in_core(self):
        source=Path(self.temp.name)/"old.hex"; source.write_text("11 7f 9f")
        context=snapshot(initial_stack=[g(7)])
        old=dwarf.evaluate(source,context,self.definition,input_format="hex")
        new=self.raw("11 7f 9f",context)
        self.assert_same(old,new)
        self.assert_same(new,self.core_run(old,context))

    def test_all_public_result_kinds_agree_with_core(self):
        for source,kind in (("31","memory"),("31 9f","value"),("50","register"),
                            ("9e 01 aa","bytes"),("","unavailable"),("30 9f 93 01","composite")):
            with self.subTest(kind=kind):
                context=snapshot(architecture="x86_64")
                p=Path(self.temp.name)/"old.hex"; p.write_text(source)
                old=dwarf.evaluate(p,context,self.definition,input_format="hex")
                new=self.raw(source,context)
                self.assertEqual(new["status"],"completed")
                self.assertEqual(new["result"]["kind"],kind)
                self.assert_same(new,self.core_run(new,context))
