"""Final-table exports authenticate data and preserve manually supplied notes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from verification.common import ROOT
from verification.paper_results import load_bundle, render, export, read_notes
from verification.paper_coverage import coverage_totals

class FinalResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/'output').exists():
            raise unittest.SkipTest('optional saved output/ package is not present')
        cls.bundle=load_bundle(ROOT/'output/manifest.json')
    def test_counts_from_rows_and_coverage_denominators(self):
        b=self.bundle;cov=b['archive'].json(b['paths']['coverage_evidence']);t=coverage_totals(cov)
        self.assertEqual(t['sources']['combined']['roots'],sum(x['current_semantic']['total'] for x in b['metrics'].values()))
        self.assertEqual(sum(t['sources']['combined']['location_counts'].values()),t['sources']['combined']['roots'])
        self.assertEqual(t['primary_op_coverage']['name_count'],len(set().union(*(set(n['root_op_names']) for n in cov['summary'].values()))))
        for p,m in b['metrics'].items():
            rows=[r for r in b['policy'] if r['project']==p and r['scope']=='semantic']
            self.assertEqual(m['current_semantic']['status']['pass'],sum(r['status']=='pass' for r in rows))
    def test_export_notes_and_english_six_file_contract(self):
        task=next(r for r in self.bundle['policy'] if r['scope']=='semantic' and r['status']=='fail')
        docs=render(self.bundle,ROOT/'docs/evaluation',{task['id']:'Retain this manual note'})
        self.assertEqual(len(docs),6);self.assertIn('Retain this manual note',docs['limitations.md'])
        self.assertLessEqual(sum(len(v.splitlines()) for k,v in docs.items() if k.endswith('.md')),300)
        self.assertNotIn('latest.json',docs['README.md'])
    def test_export_refuses_existing_directory(self):
        with self.assertRaises(FileExistsError):export(ROOT/'docs/evaluation')
    def test_result_drift_rejected(self):
        from verification.corpus_integrity import digest
        original=digest
        with patch('verification.paper_results.digest',side_effect=lambda p:'changed' if Path(p).name=='expressions.json' else original(p)):
            with self.assertRaisesRegex(ValueError,'missing or changed'):load_bundle(ROOT/'output/manifest.json')
