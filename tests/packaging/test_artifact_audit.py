"""Release policy is enforced before publishing; data and notation stay intact."""

from copy import deepcopy
import unittest

from tools.artifact_audit import audit, english_prose, k_comments, RESULT_FILES


class ReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        self.items = {
            n: {"data": b"English prose\n"}
            for n in ("README.md", "Makefile", ".gitignore", "test-corpus/README.md", "scripts/README.md")
        }
        self.items.update(
            {
                n: {"data": text.encode()}
                for n, text in {
                    "validate.py": "import sample\n",
                    "scripts/runner.py": "import sample.checker\n",
                    "scripts/sample/__init__.py": "from . import checker\n",
                    "scripts/sample/checker.py": "import json\ndef observe():\n    import pathlib\n",
                    "semantics/test.k": "module TEST // English comment with mathematical Γ notation.\nendmodule\n",
                }.items()
            }
        )
        self.items.update(
            {"results/" + n: {"data": b"English result\n"} for n in RESULT_FILES}
        )

    def test_minimal_profile_and_complete_relative_import_closure(self):
        report = audit(self.items)
        self.assertEqual(report["readme_files"], 3)
        self.assertEqual(report["k_files"], 1)
        self.assertEqual(report["runtime_modules"], 4)
        self.assertIn(
            "scripts/sample/checker.py",
            report["python_dependencies"]["scripts/sample/__init__.py"],
        )

    def test_development_and_unreferenced_runtime_files_rejected(self):
        for name in (
            "docs/design.md",
            "tests/test_private.py",
            "semantics/notes.md",
            "output/old.json",
            "requirements.txt",
            "reproduce.py",
            "run.py",
            "results/notes.json",
            "results/summary.json",
            "results/README.md",
        ):
            items = deepcopy(self.items)
            items[name] = {"data": b"not released"}
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "file set differs|outside minimal"),
            ):
                audit(items)
        self.items["scripts/unused.py"] = {"data": b"import json\n"}
        with self.assertRaisesRegex(ValueError, "unreferenced runtime module"):
            audit(self.items)

    def test_external_and_parent_imports_rejected_even_inside_functions(self):
        for source in (
            "def hidden():\n    from tools.collect import collect\n",
            "from ..parent import value\n",
            "import third_party_package\n",
        ):
            items = deepcopy(self.items)
            items["scripts/sample/checker.py"] = {"data": source.encode()}
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(ValueError, "outside artifact"),
            ):
                audit(items)

    def test_missing_entrypoint_or_result_cannot_publish(self):
        for name in ("scripts/runner.py", "results/report.md"):
            items = deepcopy(self.items)
            del items[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit(items)

    def test_non_english_readme_and_both_k_comment_forms_rejected(self):
        for name, text in [
            ("README.md", "中文说明"),
            ("results/report.md", "中文说明"),
            ("semantics/test.k", "module T // 中文注释\nendmodule"),
            ("semantics/test.k", "/* 中文注释 */ module T endmodule"),
        ]:
            with (
                self.subTest(name=name, text=text),
                self.assertRaisesRegex(ValueError, "non-English"),
            ):
                english_prose(name, text.encode())

    def test_literals_escaped_quotes_and_notation_are_preserved(self):
        source = 'syntax X ::= "中文 // literal /* literal */"\n// English with Γ and ≤.\n/* Another English comment. */'
        comments = k_comments(source)
        self.assertNotIn("中文", comments)
        self.assertIn("English with Γ", comments)
        english_prose("semantics/test.k", source.encode())
        self.assertEqual(
            k_comments(r'"escaped \" // literal" // English'), "// English"
        )
        with self.assertRaisesRegex(ValueError, "unterminated"):
            k_comments("/* unfinished")

    def test_other_documents_and_manual_remarks_are_outside_language_scope(self):
        english_prose("results/differences.csv", '{"case":"人工备注"}'.encode())
        english_prose("docs/methodology.md", "其他文档等待下一轮".encode())
