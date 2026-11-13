"""Compact evidence preserves complete outputs and independently recomputable counts."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from verification import baseline


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='kframework-evidence-test-',dir='/tmp/scratch')
        self.addCleanup(self.tmp.cleanup);self.file=Path(self.tmp.name)/'evidence.gz'
        self.task={'kind':'task','project':'gdb','record':{'id':'example'}}
        self.call={'kind':'invocation','project':'gdb','task':'example','path':'k/stdout.txt','payload':{'configuration':{'term':{'token':'full'}}}}

    def read(self,records):
        self.file.write_bytes(baseline.pack(records));return baseline.read_evidence(self.file)

    def test_lossless_and_deterministic_gzip(self):
        records=[self.task,self.call];self.assertEqual(baseline.pack(records),baseline.pack(records))
        tasks,calls,coverage=self.read(records)
        self.assertEqual(tasks['gdb','example'],self.task['record'])
        self.assertEqual(calls['gdb','example','k/stdout.txt'],self.call);self.assertEqual(coverage,[])

    def test_duplicate_missing_and_unowned_calls_rejected(self):
        for records in ([self.task,self.task,self.call],[self.task,self.call,self.call],[self.task],[self.call]):
            with self.subTest(records=records),self.assertRaises(ValueError):self.read(records)

    def test_invocation_paths_cannot_escape(self):
        for path in ('../outside','/outside','k/../outside','k//stdout.txt','k\\stdout.txt'):
            call={**self.call,'path':path}
            with self.subTest(path=path),self.assertRaises(ValueError):self.read([self.task,call])

    def test_family_merges_only_numbered_standard_families(self):
        self.assertEqual(baseline.family('DW_OP_lit31'),'DW_OP_litN')
        self.assertEqual(baseline.family('DW_OP_reg0'),'DW_OP_regN')
        self.assertEqual(baseline.family('DW_OP_breg31'),'DW_OP_bregN')
        self.assertEqual(baseline.family('DW_OP_const1u'),'DW_OP_const1u')
        self.assertEqual(baseline.family('DW_OP_reg32'),'DW_OP_reg32')


class SavedExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[2]
        if not (cls.root/'output').exists():raise unittest.SkipTest('optional recorded result package absent')
        from tools.compact_results import export
        from verification.corpus_integrity import validate_archive
        cls.files,cls.inputs=export(cls.root)
        cls.tmp=tempfile.TemporaryDirectory(prefix='kframework-compact-test-',dir='/tmp/scratch')
        cls.addClassCleanup(cls.tmp.cleanup);cls.copy=Path(cls.tmp.name);folder=cls.copy/'results';folder.mkdir()
        for name,data in cls.files.items():(folder/name).write_bytes(data)
        cls.corpus,cls.scope=validate_archive(cls.root/'test-corpus')

    def load(self):return baseline.load(self.copy,self.corpus,self.scope)

    def test_all_tasks_calls_coverage_and_manual_remarks_survive(self):
        summary,tasks,calls,coverage=self.load()
        self.assertEqual(len(tasks),326);self.assertEqual(len(calls),584)
        self.assertEqual(len(coverage),572)
        combined=summary['statistics']['coverage']['sources']['combined']
        self.assertEqual((combined['op_name_count'],combined['op_family_count'],combined['location_category_count']),(62,46,7))
        rows=list(csv.DictReader(io.StringIO(self.files['expressions.csv'].decode())))
        notes=json.loads(self.files['notes.json'])
        self.assertEqual({(r['source'],r['id']) for r in rows},set(tasks))
        for row in rows:
            self.assertEqual(row['status'],tasks[row['source'],row['id']]['corpus_evaluation']['status'])
            self.assertEqual(row['人工备注'],notes.get(row['id'],''))
        differences=list(csv.DictReader(io.StringIO(self.files['differences.csv'].decode())))
        self.assertEqual(len(differences),16)
        from tools.compact_results import export
        second,_=export(self.root);self.assertEqual(self.files,second)

    def test_provenance_is_inert_but_scope_and_statistics_still_checked(self):
        saved=self.copy/'results/summary.json';original=saved.read_bytes()
        try:
            doc=json.loads(original);doc.update(corpus_sha256='historical',evidence_sha256='historical')
            saved.write_text(json.dumps(doc));self.load()
            scope=deepcopy(self.scope);next(iter(scope.values()))['input_identity']='historical'
            baseline.load(self.copy,self.corpus,scope)
            doc['statistics']['tasks']=0;saved.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'statistics'):self.load()
            saved.write_bytes(original)
            next(iter(scope.values()))['scope']='unknown'
            with self.assertRaisesRegex(ValueError,'task identity'):baseline.load(self.copy,self.corpus,scope)
        finally:saved.write_bytes(original)
