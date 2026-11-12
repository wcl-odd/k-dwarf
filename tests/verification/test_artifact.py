"""Offline CLI, dependency and process boundaries without running K or debuggers."""
from dataclasses import replace
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from verification import cli, dependencies, process
from verification.model import Case, Observation

SCRATCH=Path('/tmp/scratch/kframework-final-unit-'+str(os.getpid()))

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.definition=self.root/'definition';self.definition.mkdir()
        (self.definition/'compiled.bin').write_bytes(b'test definition')
        self.options=SimpleNamespace(corpus=self.root/'corpus',output=self.root/'results',definition=self.definition,source='all',timeout=120,depth=10000,jobs=4,require_complete=False)
        self.manifest={'archive_sha256':'test','datasets':{'lldb':{'directory':'lldb'},'gdb':{'directory':'gdb'}}}
        self.case=Case('root',[49],64,'little',5,True,4,{},[])

    def fake_acceptance(self,options):
        options.output.mkdir(parents=True)
        project=options.output.name
        rows=[]
        for i,scope in enumerate(['semantic','auxiliary'] if project=='lldb' else ['semantic']):
            evaluated={'scope':scope,'status':'uncheckable' if scope=='auxiliary' else 'pass','fully_checked':scope=='semantic','entered_k':True,'checks':[]}
            rows.append({'id':str(i),'execution':'success','corpus_evaluation':evaluated,'budget_exhausted':False,'input_identity':str(i)})
        report={'cases':rows,'summary':{'attribute_invocations':0,'exit_code':0}}
        (options.output/'report.json').write_text(json.dumps(report))

    def test_source_selection_and_auxiliary_denominator(self):
        for source in ['all','lldb','gdb']:
            self.options.source=source;self.options.output=self.root/source
            with patch('verification.cli.validate_archive',return_value=(self.manifest,None)),patch('verification.cli.acceptance.test',side_effect=self.fake_acceptance):
                self.assertEqual(cli.run(self.options),0)
            d=json.loads((self.options.output/'summary.json').read_text())
            self.assertEqual(set(d['sources']),{'lldb','gdb'} if source=='all' else {source})
            for project,row in d['sources'].items():
                self.assertEqual(row['core']['total'],1)
                self.assertEqual(row['auxiliary']['total'],int(project=='lldb'))
            self.assertTrue((self.options.output/'checks.csv').is_file())

    def test_refuse_overwrite_or_missing_definition(self):
        with patch('verification.cli.validate_archive',return_value=(self.manifest,None)):
            self.options.output.mkdir()
            with self.assertRaisesRegex(ValueError,'must not exist'):cli.run(self.options)
            self.options.output=self.root/'new';self.options.definition=self.root/'absent'
            with self.assertRaisesRegex(ValueError,'definition missing'):cli.run(self.options)
            self.assertFalse(self.options.output.exists())

    def test_invalid_parameters_and_input_return_two(self):
        for args in [[],['--timeout','0'],['--jobs','9'],['--depth','-1']]:
            with self.subTest(args=args),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as e:cli.main(args)
            self.assertEqual(e.exception.code,2)
        with patch('verification.cli.validate_archive',side_effect=ValueError('corrupt corpus')),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--check-corpus']),2)

    def test_interruption_cleanup_returns_130(self):
        with patch('verification.cli.run',side_effect=KeyboardInterrupt),patch('verification.process.stop_children') as cleanup:
            self.assertEqual(cli.main(['--output',str(self.root/'unused')]),130)
        cleanup.assert_called_once()

    def test_dependency_bind_and_assignment_are_k_results(self):
        case=replace(self.case,dependencies=[{'id':'base','bytes':[49],'purpose':'value','phase':'before','assign':'object_address'},{'id':'bound','bytes':[50],'purpose':'value','bind':{'object_address':'base'}}])
        requests=[]
        def evaluate(case,directory,options):
            requests.append(case)
            return Observation('k','success',native={'status':'completed','result':{'kind':'scalar','value':8,'type':'g'}})
        dest=self.root/'deps';dest.mkdir()
        with patch('verification.dependencies.k.run',side_effect=evaluate):
            obs,ctx,results,evidence,reason=dependencies.execute(case,dest,self.options)
        self.assertIsNone(reason);self.assertEqual(ctx['object_address'],8)
        self.assertEqual(requests[1].context['object_address'],8)
        self.assertEqual(requests[2].context['object_address'],8)
        self.assertEqual(len(evidence),2)

    def test_dependency_missing_cycle_and_guard(self):
        dest=self.root/'deps';dest.mkdir()
        case=replace(self.case,dependencies=[{'id':'x','bytes':[49],'purpose':'value','phase':'before','bind':{'object_address':'x'}}])
        with self.assertRaisesRegex(ValueError,'missing or cyclic'):dependencies.execute(case,dest,self.options)
        case=replace(case,dependencies=[{'id':'x','bytes':[49],'purpose':'value','phase':'before','when':{'dependency':'missing','nonzero':True}}])
        result=dependencies.execute(case,dest,self.options)
        self.assertEqual(result[-1]['kind'],'observation_gap')
        self.assertIsNone(result[0])

    def test_implicit_reference_missing_and_cycle(self):
        payload={'result':{'kind':'implicit_pointer','reference':1,'offset':0}}
        with self.assertRaisesRegex(dependencies.ObservationGap,'not captured'):
            dependencies.implicit_observation(self.case,payload,{},self.root,self.options,[])
        ctx={'die_locations':{'1':{'bytes':[49]}}}
        native={'status':'completed','result':{'kind':'implicit_pointer','reference':1,'offset':0}}
        with patch('verification.dependencies.k.run',return_value=Observation('k','success',native=native)):
            with self.assertRaisesRegex(dependencies.ObservationGap,'cyclic'):
                dependencies.implicit_observation(self.case,payload,ctx,self.root,self.options,[])

    def test_process_timeout_preserves_receipts_and_kills_group(self):
        command=[sys.executable,'-c','import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); print(p.pid,flush=True); time.sleep(60)']
        target=self.root/'timeout'
        with self.assertRaises(process.ToolFailure):process.execute(command,target,0.15)
        self.assertTrue(json.loads((target/'exit.json').read_text())['timeout'])
        pid=int((target/'stdout.txt').read_text().strip())
        stat=Path('/proc')/str(pid)/'stat'
        self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z')
        self.assertFalse(process._children)

    def test_process_keyboard_interrupt_kills_child(self):
        command=[sys.executable,'-c','import time; time.sleep(60)'];original=subprocess.Popen.communicate;calls=[]
        def interrupt(child,*a,**kw):
            if not calls:calls.append(child.pid);raise KeyboardInterrupt
            return original(child,*a,**kw)
        with patch.object(subprocess.Popen,'communicate',interrupt):
            with self.assertRaises(KeyboardInterrupt):process.execute(command,self.root/'interrupt',5)
        self.assertTrue(json.loads((self.root/'interrupt/exit.json').read_text())['interrupted'])
        self.assertFalse(process._children)

if __name__=='__main__':unittest.main()
