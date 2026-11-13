"""Development clones and recorded-result packages have distinct requirements."""
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from verification.corpus_integrity import digest
from verification.paper_results import load_bundle, main, reference_path

class ResultBoundaryTests(unittest.TestCase):
    def setUp(self):
        base=Path('/tmp/scratch')/('kframework-layout-unit-'+str(os.getpid()))
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_absent_package_has_actionable_message(self):
        with self.assertRaisesRegex(FileNotFoundError,'saved result package is absent'):
            load_bundle(self.root/'output/manifest.json')

    def test_present_incomplete_package_is_not_an_optional_absence(self):
        (self.root/'output').mkdir()
        with self.assertRaisesRegex(ValueError,'incomplete: missing manifest'):
            load_bundle(self.root/'output/manifest.json')

    def test_export_cli_missing_package_returns_two_without_output(self):
        target=self.root/'exported';stderr=io.StringIO()
        with redirect_stderr(stderr),self.assertRaises(SystemExit) as error:
            main(['--results',str(self.root/'missing'),'--output',str(target)])
        self.assertEqual(error.exception.code,2)
        self.assertIn('restore the complete output/',stderr.getvalue())
        self.assertFalse(target.exists())

    def test_corrupt_existing_manifest_is_rejected(self):
        folder=self.root/'output';folder.mkdir()
        (folder/'manifest.json').write_text(json.dumps({'profile':'final-offline-v1','identity':'wrong'}))
        with self.assertRaisesRegex(ValueError,'manifest changed'):load_bundle(folder/'manifest.json')

    def test_reference_hash_and_docs_boundary(self):
        file=self.root/'docs/reference/review.json';file.parent.mkdir(parents=True);file.write_text('{}')
        manifest={'references':{'selection':{'path':'../docs/reference/review.json','sha256':digest(file)}}}
        origin=self.root/'output/manifest.json'
        self.assertEqual(reference_path(origin,manifest,'selection'),file)
        file.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'missing or changed'):reference_path(origin,manifest,'selection')
        for path in ['../../outside','../docs/../outside','/tmp/outside','../docs/./reference/review.json']:
            manifest['references']['selection']['path']=path
            with self.subTest(path=path),self.assertRaises(ValueError):reference_path(origin,manifest,'selection')

    def test_reference_cannot_be_a_symlink(self):
        real=self.root/'docs/reference/real.json';real.parent.mkdir(parents=True);real.write_text('{}')
        link=real.parent/'link.json';link.symlink_to(real)
        manifest={'references':{'selection':{'path':'../docs/reference/link.json','sha256':digest(real)}}}
        with self.assertRaisesRegex(ValueError,'symlink'):reference_path(self.root/'output/manifest.json',manifest,'selection')
