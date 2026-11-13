"""Publication copying protects source identity and independent local edits."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_artifact as package


class PublicationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path("/tmp/scratch")
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="kframework-package-test-", dir=scratch
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "development"
        self.root.mkdir()
        self.dest = Path(self.temp.name) / "publication"
        for name in package.COPY:
            p = self.root / name
            if p.suffix:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("source\n")
            else:
                p.mkdir(parents=True, exist_ok=True)
                (p / "fixture.txt").write_text("fixture\n")
        (self.root / "semantics/main.k").write_text("module TEST endmodule\n")
        for name in package.TEMPLATES:
            p = self.root / "tools/artifact-template" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("template\n")
        for name in package.RUNTIME:
            p = self.root / "tools/artifact-runtime" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# runtime\n")
        (self.root / "tools/artifact-runtime/README.md").write_text(
            "# Internal scripts\n\nRuntime module responsibilities.\n"
        )
        (self.root / "tools/artifact-template/validate.py").write_text(
            "import experiment\n"
        )
        modules = [name[:-3] for name in package.RUNTIME if name != "experiment.py"]
        (self.root / "tools/artifact-runtime/experiment.py").write_text(
            "".join("import " + name + "\n" for name in modules)
        )
        (self.root / "test-corpus/manifest.json").write_text("{}")
        corpus = {
            "cases": [
                {
                    "id": tool + "-001",
                    "tool": tool,
                    "group": "core",
                    "expression": {"bytecode": "31"},
                    "interface": {},
                    "requirements": {},
                }
                for tool in ("lldb", "gdb")
            ]
        }
        mock = patch("tools.compact_cases.export", return_value=(corpus, {}, {}))
        mock.start()
        self.addCleanup(mock.stop)
        (self.root / "output/manifest.json").write_text("{}")
        (self.root / "tools/artifact-template/Makefile").write_text("all:\n\ttrue\n")
        final = self.root / "docs/reference/artifact-results"
        final.mkdir(parents=True)
        for name in (
            "report.md",
            "expressions.csv",
            "differences.csv",
            "evidence.jsonl.gz",
        ):
            (final / name).write_bytes(b"saved\n")

    def publish(self):
        return package.publish(self.root, self.dest)

    def test_first_and_repeat_are_real_deterministic_copies(self):
        a = self.publish()
        b = self.publish()
        self.assertEqual(a, b)
        self.assertEqual(a, package.publish(self.root, self.dest, check=True))
        src = self.root / "semantics/main.k"
        dst = self.dest / "semantics/main.k"
        self.assertEqual(src.read_bytes(), dst.read_bytes())
        self.assertNotEqual(src.stat().st_ino, dst.stat().st_ino)
        self.assertFalse(dst.is_symlink())
        self.assertEqual(
            (self.dest / "scripts/README.md").read_bytes(),
            (self.root / "tools/artifact-runtime/README.md").read_bytes(),
        )
        self.assertNotIn("private:", (self.dest / "Makefile").read_text())
        self.assertNotIn("check:", (self.dest / "Makefile").read_text())
        self.assertFalse((self.dest / package.MANIFEST).exists())
        self.assertTrue(package.sync_path(self.root, self.dest).is_file())

    def test_validate_entry_retires_only_the_unchanged_managed_old_entries(self):
        self.publish()
        state = package.sync_path(self.root, self.dest)
        doc = json.loads(state.read_text())
        for name in ("run.py", "reproduce.py"):
            old = self.dest / name
            old.write_text("import experiment\n")
            old.chmod(0o644)
            doc["files"].append(
                {
                    "path": name,
                    "sha256": package.sha(old.read_bytes()),
                    "bytes": old.stat().st_size,
                    "mode": 0o644,
                }
            )
        doc.pop("identity")
        doc["identity"] = package.sha(package.encoded(doc))
        state.write_bytes(package.encoded(doc))
        self.publish()
        self.assertFalse((self.dest / "run.py").exists())
        self.assertFalse((self.dest / "reproduce.py").exists())
        self.assertTrue((self.dest / "validate.py").is_file())
        package.publish(self.root, self.dest, check=True)

    def test_standalone_validate_help_needs_no_parent_inputs_or_tools(self):
        import shutil
        import subprocess
        import sys

        maintained = Path(__file__).resolve().parents[2] / "tools"
        standalone = Path(self.temp.name) / "standalone"
        standalone.mkdir()
        shutil.copyfile(
            maintained / "artifact-template/validate.py", standalone / "validate.py"
        )
        shutil.copytree(
            maintained / "artifact-runtime",
            standalone / "scripts",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        result = subprocess.run(
            [sys.executable, str(standalone / "validate.py"), "--help"],
            cwd=standalone,
            env=dict(os.environ, PYTHONPATH="", PATH="", PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: validate.py", result.stdout)
        for option in (
            "--source",
            "--definition",
            "--output",
            "--jobs",
            "--timeout",
            "--depth",
        ):
            self.assertIn(option, result.stdout)
        self.assertFalse((standalone / "build").exists())

    def test_duplicate_notes_are_retired_and_csv_remarks_survive(self):
        self.publish()
        state = package.sync_path(self.root, self.dest)
        doc = json.loads(state.read_text())
        notes = {"lldb-001": "Reviewed manual remark."}
        old = self.dest / "results/notes.json"
        old.write_text(json.dumps(notes))
        old.chmod(0o644)
        doc["files"].append(
            {
                "path": "results/notes.json",
                "sha256": package.sha(old.read_bytes()),
                "bytes": old.stat().st_size,
                "mode": 0o644,
            }
        )
        doc.pop("identity")
        doc["identity"] = package.sha(package.encoded(doc))
        state.write_bytes(package.encoded(doc))
        files = {p.name: p.read_bytes() for p in (self.dest / "results").iterdir()}
        remarks = b"id,manual_remarks\nlldb-001,Reviewed manual remark.\n"
        files["expressions.csv"] = remarks
        files["differences.csv"] = remarks
        files.pop("notes.json")
        final = self.root / "docs/reference/artifact-results"
        for name, data in files.items():
            (final / name).write_bytes(data)
        self.publish()
        package.publish(self.root, self.dest, check=True)
        self.assertFalse(old.exists())
        self.assertEqual(len(list((self.dest / "results").iterdir())), 4)
        for name in ("expressions.csv", "differences.csv"):
            self.assertEqual((self.dest / "results" / name).read_bytes(), remarks)

    def test_old_report_and_summary_are_retired_after_managed_migration(self):
        self.publish()
        state = package.sync_path(self.root, self.dest)
        doc = json.loads(state.read_text())
        for name in ("README.md", "summary.json"):
            old = self.dest / "results" / name
            old.write_text("old recorded data\n")
            old.chmod(0o644)
            doc["files"].append(
                {
                    "path": "results/" + name,
                    "sha256": package.sha(old.read_bytes()),
                    "bytes": old.stat().st_size,
                    "mode": 0o644,
                }
            )
        doc.pop("identity")
        doc["identity"] = package.sha(package.encoded(doc))
        state.write_bytes(package.encoded(doc))
        self.publish()
        self.assertEqual(
            {p.name for p in (self.dest / "results").iterdir()},
            {"report.md", "expressions.csv", "differences.csv", "evidence.jsonl.gz"},
        )
        package.publish(self.root, self.dest, check=True)

    def test_damaged_final_package_does_not_fall_back_to_history(self):
        final = self.root / "docs/reference/artifact-results"
        (final / "report.md").unlink()
        with self.assertRaisesRegex(ValueError, "file set differs"):
            self.publish()
        self.assertFalse(self.dest.exists())
        for path in list(final.iterdir()):
            path.unlink()
        final.rmdir()
        with self.assertRaisesRegex(ValueError, "result package missing"):
            self.publish()

    def test_add_update_remove_k_files(self):
        self.publish()
        (self.root / "semantics/new.k").write_text("new\n")
        with self.assertRaisesRegex(ValueError, "K sources differ"):
            package.rules_check(self.root, self.dest)
        with self.assertRaisesRegex(ValueError, "out of date"):
            package.publish(self.root, self.dest, check=True)
        self.publish()
        (self.root / "semantics/main.k").unlink()
        self.publish()
        self.assertFalse((self.dest / "semantics/main.k").exists())
        (self.root / "semantics/new.k").write_text("updated\n")
        self.publish()
        self.assertEqual((self.dest / "semantics/new.k").read_text(), "updated\n")

    def test_destination_edits_are_never_overwritten_or_retired(self):
        (self.root / "semantics/keep.k").write_text("keep")
        self.publish()
        p = self.dest / "semantics/main.k"
        p.write_text("my edit\n")
        (self.root / "semantics/main.k").unlink()
        with self.assertRaisesRegex(ValueError, "local edits"):
            self.publish()
        self.assertEqual(p.read_text(), "my edit\n")

    def test_unmanaged_files_and_builds_survive(self):
        self.publish()
        p = self.dest / "build/runtime.log"
        p.parent.mkdir()
        p.write_text("keep")
        q = self.dest / "notes.txt"
        q.write_text("notes")
        with self.assertRaisesRegex(ValueError, "unmanaged file"):
            self.publish()
        self.assertEqual(p.read_text(), "keep")
        self.assertEqual(q.read_text(), "notes")
        q.unlink()
        self.publish()
        package.publish(self.root, self.dest, check=True)
        self.assertEqual(p.read_text(), "keep")

    def test_unmanaged_collision_and_unknown_destination_rejected(self):
        self.dest.mkdir()
        unknown = self.dest / "unknown"
        unknown.write_text("mine")
        with self.assertRaisesRegex(ValueError, "no local sync state"):
            self.publish()
        unknown.unlink()
        self.dest.rmdir()
        self.publish()
        (self.root / "semantics/new.k").write_text("upstream")
        p = self.dest / "semantics/new.k"
        p.write_text("my file")
        with self.assertRaisesRegex(ValueError, "unmanaged file"):
            self.publish()
        self.assertEqual(p.read_text(), "my file")

    def test_source_drift_before_publication_rejected(self):
        original = package.manifest_for

        def drift(items):
            (self.root / "semantics/main.k").write_text("changed while staging")
            return original(items)

        with patch.object(package, "manifest_for", side_effect=drift):
            with self.assertRaisesRegex(ValueError, "source drift"):
                self.publish()
        self.assertFalse(self.dest.exists())

    def test_symlinks_and_path_escape_rejected(self):
        for name in ("../escape", "/absolute", "x/../y", "x//y"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.safe(self.dest, name)
        (self.root / "semantics/link.k").symlink_to(self.root / "semantics/main.k")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.publish()
        (self.root / "semantics/link.k").unlink()
        self.publish()
        (self.dest / "semantics/extra.k").symlink_to(self.root / "semantics/main.k")
        with self.assertRaisesRegex(ValueError, "symlink"):
            package.rules_check(self.root, self.dest)

    def test_source_overlap_and_absent_rule_check(self):
        package.rules_check(self.root, self.dest, if_present=True)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            package.publish(self.root, self.root / "output/subdir")
        with self.assertRaisesRegex(ValueError, "overlaps"):
            package.publish(self.root, self.root / "other/../output/subdir")
        with self.assertRaisesRegex(ValueError, "contain"):
            package.publish(self.root, self.root.parent)

    def test_cache_files_are_not_published(self):
        p = self.root / "tools/artifact-runtime/__pycache__/x.pyc"
        p.parent.mkdir()
        p.write_bytes(b"cache")
        doc = self.publish()
        self.assertNotIn(
            "verification/__pycache__/x.pyc", [r["path"] for r in doc["files"]]
        )

    def test_empty_source_rules_refused_before_retiring_anything(self):
        self.publish()
        before = package.sync_path(self.root, self.dest).read_bytes()
        (self.root / "semantics/main.k").unlink()
        with self.assertRaisesRegex(ValueError, "no K sources"):
            self.publish()
        self.assertEqual(before, package.sync_path(self.root, self.dest).read_bytes())
        self.assertTrue((self.dest / "semantics/main.k").exists())

    def test_legacy_migration_retires_only_authenticated_files_and_bytecode(self):
        self.publish()
        state = package.sync_path(self.root, self.dest)
        doc = json.loads(state.read_text())
        state.unlink()
        old = self.dest / "tests/old.py"
        old.parent.mkdir()
        old.write_text("# retired\n")
        old.chmod(0o644)
        doc["files"].append(
            {
                "path": "tests/old.py",
                "sha256": package.sha(old.read_bytes()),
                "bytes": old.stat().st_size,
                "mode": 0o644,
            }
        )
        doc.update(schema=1, profile="standalone-publication-v1")
        doc.pop("identity")
        doc["identity"] = package.sha(package.encoded(doc))
        (self.dest / package.MANIFEST).write_bytes(package.encoded(doc))
        cache = old.parent / "__pycache__/old.cpython-310.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"old cache")
        doc = self.publish()
        self.assertFalse(old.exists())
        self.assertFalse(cache.exists())
        self.assertFalse(old.parent.exists())
        self.assertFalse((self.dest / package.MANIFEST).exists())
        self.assertTrue(state.is_file())
        self.assertEqual(doc["profile"], "paper-minimal-v1")
        receipts = list((self.root / "build/artifact-cleanup").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(
            json.loads(receipts[0].read_text())["deleted_bytes"],
            len(b"# retired\nold cache"),
        )

    def test_publication_whitelist_excludes_development_material(self):
        doc = self.publish()
        names = {r["path"] for r in doc["files"]}
        self.assertIn("scripts/runner.py", names)
        self.assertIn("scripts/experiment.py", names)
        self.assertNotIn("scripts/verify.py", names)
        self.assertNotIn("scripts/verification/baseline.py", names)
        self.assertIn("results/evidence.jsonl.gz", names)
        self.assertFalse(
            any(
                n.startswith(("tests/", "docs/", "output/", "verification/"))
                for n in names
            )
        )
        self.assertNotIn("semantics/fixture.txt", names)

    def test_only_source_case_files_and_guide_are_published(self):
        doc = self.publish()
        names = {
            r["path"] for r in doc["files"] if r["path"].startswith("test-corpus/")
        }
        self.assertEqual(
            names,
            {"test-corpus/lldb.json", "test-corpus/gdb.json", "test-corpus/README.md"},
        )
        for tool in ("lldb", "gdb"):
            cases = json.loads(
                (self.dest / "test-corpus" / (tool + ".json")).read_text()
            )["cases"]
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["tool"], tool)
            self.assertEqual(cases[0]["expression"]["bytecode"], "31")
        self.assertFalse((self.dest / "test-corpus/cases.json").exists())
        self.assertFalse((self.dest / "test-corpus/manifest.json").exists())
        self.assertIn(
            "documentation only", (self.dest / "test-corpus/README.md").read_text()
        )

    def test_non_english_source_comment_stops_before_any_publication_write(self):
        (self.root / "semantics/main.k").write_text(
            "module TEST // 中文注释\nendmodule\n"
        )
        with self.assertRaisesRegex(ValueError, "non-English"):
            self.publish()
        self.assertFalse(self.dest.exists())

    def test_sync_state_loss_adopts_only_exact_copy(self):
        self.publish()
        state = package.sync_path(self.root, self.dest)
        state.unlink()
        self.publish()
        self.assertTrue(state.is_file())
        state.unlink()
        (self.dest / "README.md").write_text("independent edit")
        with self.assertRaisesRegex(ValueError, "no local sync state"):
            self.publish()

    def test_local_sync_state_drift_is_rejected(self):
        self.publish()
        state = package.sync_path(self.root, self.dest)
        state.write_text("{}")
        with self.assertRaisesRegex(ValueError, "sync state changed"):
            self.publish()

    def test_unchanged_copies_keep_mtime(self):
        self.publish()
        p = self.dest / "semantics/main.k"
        stamp = p.stat().st_mtime_ns
        self.publish()
        self.assertEqual(p.stat().st_mtime_ns, stamp)
