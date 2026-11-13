"""Export concise paper tables from the one final result package, without K."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote

from .common import ROOT, workspace_lock
from .corpus_integrity import canonical_hash, digest, validate_archive
from .metrics import count

FILES={'README.md','results.md','methodology.md','limitations.md','results.csv','summary.json'}

class Archive:
    """Resolve final evidence relative to its package, tracking read identities."""
    def __init__(self, base):
        self.base=Path(base).absolute();self.hashes={}
    def path(self,path):
        p=Path(path)
        return p if p.is_absolute() else self.base/p
    def relative(self,path):
        return os.path.relpath(self.path(path).absolute(),self.base)
    def read(self,path):
        p=self.path(path);data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
        if p in self.hashes and self.hashes[p]!=sha:raise ValueError('evidence changed: '+str(p))
        self.hashes[p]=sha;return data
    def json(self,path):return json.loads(self.read(path))
    def unchanged(self):
        for p,sha in self.hashes.items():
            if digest(p)!=sha:raise ValueError('evidence changed: '+str(p))


def reference_path(manifest_path, manifest, name):
    """Authenticate explicit documentation inputs without allowing arbitrary escapes."""
    row=manifest['references'][name]
    relative=PurePosixPath(row['path'])
    if (not isinstance(row['path'],str) or relative.as_posix()!=row['path'] or
            len(relative.parts)<3 or relative.parts[:2]!=('..','docs') or
            '..' in relative.parts[2:] or '\\' in row['path']):
        raise ValueError('invalid documentation reference: '+str(row['path']))
    root=manifest_path.parent.parent/'docs'
    path=Path(os.path.abspath(manifest_path.parent/row['path']))
    for parent in (path,*path.parents):
        if parent.is_symlink():raise ValueError('symlink in documentation reference')
        if parent==root:break
    resolved=path.resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file() or digest(resolved)!=row['sha256']:
        raise ValueError('documentation reference missing or changed: '+row['path'])
    return resolved


def load_bundle(manifest_path=ROOT/'output/manifest.json'):
    path=Path(manifest_path).absolute()
    if not path.parent.exists():
        raise FileNotFoundError('saved result package is absent: '+str(path.parent)+'; restore the complete output/ package to export recorded results')
    if not path.is_file():
        raise ValueError('saved result package is incomplete: missing manifest.json')
    a=Archive(path.parent);manifest=a.json(path)
    if manifest.get('profile')!='final-offline-v1':raise ValueError('unknown final-result profile')
    if canonical_hash({k:v for k,v in manifest.items() if k!='identity'})!=manifest['identity']:
        raise ValueError('final-result manifest changed')
    for row in manifest['files']:
        p=(path.parent/row['path']).resolve()
        if not p.is_relative_to(path.parent.resolve()) or p.is_symlink() or digest(p)!=row['sha256']:
            raise ValueError('final result missing or changed: '+row['path'])
    references={key:reference_path(path,manifest,key) for key in ('methodology','support','floating_support','selection','excluded','notes','analyses')}
    corpus_path=(path.parent/manifest['corpus']).absolute()
    corpus,_=validate_archive(corpus_path)
    summary=a.json('summary.json');policy=a.json('expressions.json')
    metrics={}
    source_requirements={}
    for project,dataset in corpus['datasets'].items():
        report_path=path.parent/'evidence'/project/'report.json';report=a.json(report_path)
        rs=[r for r in policy if r['project']==project]
        metrics[project]={'current_semantic':count([r for r in rs if r['scope']=='semantic'])}
        if metrics[project]['current_semantic']!=summary['sources'][project]['core']:
            raise ValueError('stale expression summary: '+project)
        if len(report['cases'])!=len(rs):raise ValueError('expression ledger differs')
        prepared=corpus_path/dataset['directory']/'cases.json'
        proof=a.json(corpus_path/dataset['directory']/'preparation.json')['frozen_selection']
        freeze=a.json(corpus_path/dataset['directory']/proof['path'])
        source_requirements[project]={'preparation':str(prepared),'evidence_report':str(report_path),
            'selection_sha256':freeze['selection_sha256'],
            'dependency_invocations':report['summary']['attribute_invocations']}
    support=list(csv.DictReader(io.StringIO(a.read(references['support']).decode())))
    summary={**summary,'source_requirements':source_requirements,'new_execution':True}
    return {'archive':a,'summary':summary,'policy':policy,'source':policy,
        'metrics':metrics,'support':support,'notes':a.json(references['notes']),
        'analyses':a.json(references['analyses']),'excluded':a.json(references['excluded']),
        'selection':a.json(references['selection']),
        'latest':{'current_rule_version':manifest['rule_version'],'current_observation_version':manifest['result_id']},
        'paths':{**references,'coverage_evidence':path.parent/'coverage/evidence.json',
                 'project_witnesses':path.parent/'validation/project-float-witnesses.json'},
        'manifest':manifest,'manifest_path':path,'corpus':corpus}


def assertion_groups(bundle):
    groups=Counter();statuses={}
    for r in bundle['policy']:
        if r['project']!='lldb' or r['scope']!='semantic':continue
        categories=set()
        for c in r['source_checks']:
            t,e=c['target'],c['expected']
            if t=='stack_top':category='Scalar value'
            elif t=='stopped':category='Expected evaluation failure'
            elif t=='result' and e.get('kind')=='memory':category='Load address'
            elif t=='object' and e.get('kind')=='register':category='Register identity'
            elif t=='object' and 'object_bytes' in e:category='Object buffer'
            else:raise ValueError('unreviewed LLDB assertion category')
            categories.add(category)
        if len(categories)!=1:raise ValueError('mixed LLDB assertion categories')
        category=categories.pop();groups[category]+=1;statuses.setdefault(category,Counter())[r['status']]+=1
    return [{'category':c,'expressions':n,'pass':statuses[c]['pass'],'fail':statuses[c]['fail']} for c,n in groups.items()]


def render(bundle,destination,notes=None):
    from .paper_coverage import public_coverage, coverage_totals, coverage_summary_rows
    dest=Path(destination).absolute();a=bundle['archive'];coverage=a.json(bundle['paths']['coverage_evidence'])
    totals=coverage_totals(coverage)
    canonical_notes=ROOT/'docs/evaluation/limitations.md'
    notes={**bundle['notes'],**(read_notes(canonical_notes) if canonical_notes.is_file() else {}),**(notes or {})}
    targets={'support/ops.csv':bundle['paths']['support'],
             'support/floating-ops.json':bundle['paths']['floating_support'],
             'selection/review.json':bundle['paths']['selection'],
             'selection/excluded.json':bundle['paths']['excluded']}
    def link(path,label):return '['+label+']('+os.path.relpath(a.path(targets.get(path,path)),dest)+')'
    name_count=totals['primary_op_coverage']['name_count'];family_count=totals['primary_op_coverage']['family_count']
    lines=['# Final experiment results','',
        'LLDB 22.1.8 and GDB 17.1; standard DWARF expressions. Only K is run during offline reproduction. The native contexts were previously collected and frozen.','',
        '| Source | Expressions | Entered K | Fully checked | Pass | Differences | Uncheckable | Not run | Tool errors | Pass / expressions |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for p,m in bundle['metrics'].items():
        n=m['current_semantic'];s=n['status'];lines.append(f"| {p.upper()} | {n['total']} | {n['entered_k']} | {n['fully_checked']} | {s['pass']} | {s['fail']} | {s['uncheckable']} | {s['not_run']} | {s['tool_error']} | {n['pass_rate']:.2%} |")
    lines+=['','Each original expression/context task is counted once; all in-scope predicates must hold. Two LLDB API/diagnostic tasks are auxiliary. Attribute calls do not enlarge the denominator.','',
        '## What the LLDB assertions check','',
        '| Original requirement | Expressions | Pass | Differences |','| --- | ---: | ---: | ---: |']
    groups=assertion_groups(bundle)
    for g in groups:lines.append(f"| {g['category']} | {g['expressions']} | {g['pass']} | {g['fail']} |")
    lines+=['','Scalar equality follows the original matcher\'s value interpretation and integer promotions; a Scalar constructor width is not automatically an exact actual-type requirement. Load addresses compare category/address. Register locations compare category/DWARF number. Host buffers compare content/extent; stopped predicates require the exact scene and verified natural-stop stability.','',
        '## Input OP and observed location coverage','',
        '| Source | Root expressions | Standard OP names / 164 | Numbered families / 71 | Location categories / 7 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for p,n in totals['sources'].items():lines.append(f"| {p} | {n['roots']} | {n['root_op_name_count']} | {n['root_op_family_count']} | {n['location_kind_count']} |")
    lines+=['',f'The primary OP metric assumes operations present in each root input are covered: **{name_count} names, {family_count} numbered families**. Only lit0–31, reg0–31 and breg0–31 are merged. This is input presence at K-certified boundaries, not a dynamic execution trace. Dependency-only operations are supplementary; referenced call bodies retain an inventory evidence gap.','',
        '| Final root result | LLDB | GDB | Combined |','| --- | ---: | ---: | ---: |']
    for kind in ['memory','register','value','bytes','composite','implicit_pointer','unavailable','scalar','no_public_result']:
        values=[totals['sources'][p]['location_counts'].get(kind,0) for p in ['lldb','gdb','combined']]
        lines.append('| '+kind+' | '+' | '.join(map(str,values))+' |')
    lines+=['','Scalar is a value-purpose result; no_public_result is an execution state. Neither is a location category. Internal composite piece categories are separate and may overlap within one expression.','',
        '## Types and floating point','',
        'The semantics implements DW_ATE_float binary32, binary64, x87 binary80 and binary128: encoding plus numerical representation defines a format. Distinct DIE identities or storage padding do not create additional numerical formats. Six arithmetic operations (abs, neg, plus, minus, mul, div), six comparisons, convert and reinterpret have format/type preconditions. Integer-only operations are not floating-point implementation gaps. Boolean conversion is limited to the documented canonical representation.','',
        '| Upstream evidence | LLDB | GDB |','| --- | ---: | ---: |']
    for label,key in [('Float metadata in context','float_metadata_roots'),('Final typed float stack/result','observed_float_value_roots')]:
        lines.append(f"| {label} | {coverage['summary']['lldb'][key]} | {coverage['summary']['gdb'][key]} |")
    lines+=['','No floating arithmetic execution is confirmed in this upstream set. Metadata presence and register bit transport are not floating computation. Final type, context type metadata and original object static type are counted separately in CSV/JSON. Project floating probes are separate evidence, never added to upstream totals.','',
        link('coverage/evidence.json','Per-expression OP, type and floating evidence')+' · '+link('support/ops.csv','All implemented OP names')+' · '+link('support/floating-ops.json','Per-OP floating support')+' · '+link('validation/README.md','Regression and proof evidence'),'',
        'This experiment supports the selected expressions and checked properties; it does not establish complete DWARF correctness, all combinations, or all base types. One selected GDB type query has no independent root expression and is not fabricated as an empty expression.']
    limitations=['# Differences, exclusions and limits','',
        'The following rows are expression-level differences, not additional assertions. Manual notes are preserved verbatim. A debugger difference is not automatically a semantic-rule defect.','',
        '| Expression | Analysis | Evidence | 人工备注 |','| --- | --- | --- | --- |']
    for r in bundle['policy']:
        if r['scope']=='semantic' and r['status']=='pass':continue
        why=bundle['analyses'].get(r['id'],r.get('diagnostic') or r['status'])
        limitations.append('| `'+r['id']+'` | '+why.replace('|','\\|')+' | '+link(r['acceptance'],'check')+' / '+link(r['final_configuration'],'configuration')+' | '+notes.get(r['id'],'').replace('|','\\|')+' |')
    limitations+=['','Two LLDB API/diagnostic checks are auxiliary and are not counted as semantic passes. Core selection excludes extension operations (including required dependencies), non-expression C evaluation, robustness-only checks, unmodelled debugger interface failures and attribute-form extensions. Missing K rules or differing outcomes alone are not grounds for exclusion.','',
        '| Excluded expression | Recorded reason | 人工备注 |','| --- | --- | --- |']
    excluded=list(bundle['excluded'])+[r for r in bundle['selection'].get('inherited_exclusions',[]) if r.get('expression_id')]
    for r in excluded:
        ident=r.get('id',r.get('expression_id'));reason=r.get('reason',r.get('criterion','See reviewed selection'))
        limitations.append('| `'+ident+'` | '+reason.replace('|','\\|').replace('\n',' ')+' | '+notes.get(ident,r.get('人工备注','')).replace('|','\\|')+' |')
    limitations+=['',link('selection/review.json','Final selection decisions')+' · '+link('selection/excluded.json','Excluded assertions and source evidence'),'',
        'Selection and oracle mapping involved human/AI review. Frozen replay is deterministic code; no AI produces expected answers during execution. Entry snapshots, sparse memory, supported layouts and source-selected observations bound the conclusions.']
    readme="""# Paper reference files

| File | Purpose |
| --- | --- |
| README.md | Directory guide and maintenance |
| results.md | Expression results, LLDB assertions and OP/location/type coverage |
| methodology.md | Canonical selection, extraction and checkability method |
| limitations.md | Differences, exclusions, limits and editable manual notes |
| results.csv | Machine-generated result and coverage rows |
| summary.json | Metrics, identities and evidence references |

Read results, methodology and limitations together. Methodology and manual notes are maintained here; exports preserve them. Full configurations are in {output}, and frozen inputs in {corpus}. Full evidence is local and is included in the artifact, not required in a development Git clone. Links to output/ require that package to be restored.

Re-export with `python3 -m verification.paper_results --output NEW-DIRECTORY`. Existing destinations are refused. The exporter reads the recorded result package and does not run K or debuggers. Notes default to this directory; use --notes to import another limitations.md.
""".format(output=os.path.relpath(a.base,dest),corpus=os.path.relpath(a.base/bundle['manifest']['corpus'],dest))
    method_path=bundle['paths']['methodology']
    methodology=a.read(method_path).decode()
    # Preserve canonical prose while resolving its links for the export destination.
    methodology=re.sub(r'\]\(([^)#]+)(#[^)]*)?\)',lambda m:']('+os.path.relpath((method_path.parent/m[1]).resolve(),dest)+(m[2] or '')+')',methodology)
    summary={'schema':1,'unit':'original expression case','versions':bundle['corpus']['datasets'],
        'results':{p:v['current_semantic'] for p,v in bundle['metrics'].items()},
        'auxiliary':{p:d['auxiliary'] for p,d in bundle['summary']['sources'].items()},
        'coverage':public_coverage(coverage),'lldb_assertion_scope':groups,
        'corpus_sha256':bundle['corpus']['archive_sha256'],'result_identity':bundle['manifest']['identity'],
        'rule_source_sha256':bundle['summary']['rule_source_sha256'],
        'sources':{os.path.relpath(p,dest):h for p,h in a.hashes.items()},'manual_notes':notes}
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['view','source','unit','item','expressions','entered_k','fully_checked','pass','fail','uncheckable','not_run','tool_error','fraction','evidence_level']);writer.writeheader()
    for p,v in bundle['metrics'].items():
        n=v['current_semantic'];writer.writerow({'view':'core','source':p,'unit':'expression','expressions':n['total'],'entered_k':n['entered_k'],'fully_checked':n['fully_checked'],**n['status'],'fraction':n['pass_rate']})
    for row in coverage['rows']+coverage_summary_rows(coverage):
        writer.writerow({'view':row['view'],'source':row['source'],'unit':row['unit'],'item':row['item'],'expressions':row['cases'],**(row['status'] if row['unit']=='expression' else {}),'fraction':row.get('coverage_fraction',''),'evidence_level':row.get('evidence_level','')})
    docs={'README.md':readme,'results.md':'\n'.join(lines)+'\n','methodology.md':methodology,'limitations.md':'\n'.join(limitations)+'\n','results.csv':stream.getvalue(),'summary.json':json.dumps(summary,ensure_ascii=False,indent=2)+'\n'}
    if sum(len(t.splitlines()) for n,t in docs.items() if n.endswith('.md'))>300:raise ValueError('paper Markdown exceeds 300 lines')
    for name,text in docs.items():
        if not name.endswith('.md'):continue
        for url in re.findall(r'\]\(([^)]+)\)',text):
            p=unquote(url.split('#')[0])
            if p and p not in FILES and not (dest/p).resolve().is_file():raise ValueError('broken evidence link: '+url)
    return docs


def read_notes(path):
    notes={}
    for line in Path(path).read_text().splitlines():
        if not line.startswith('| `'):continue
        cells=line.split('|');ident=cells[1].strip().strip('`').split('`')[0]
        note=cells[-2].strip()
        if note:notes[ident]=note
    return notes


def export(destination,manifest_path=ROOT/'output/manifest.json',notes_path=None):
    dest=Path(destination).absolute()
    if os.path.lexists(dest):raise FileExistsError('export destination already exists')
    with workspace_lock():
        bundle=load_bundle(manifest_path);docs=render(bundle,dest,read_notes(notes_path) if notes_path else None)
        bundle['archive'].unchanged();dest.mkdir(parents=True)
        for name,text in docs.items():(dest/name).write_text(text)
    return {'files':sorted(docs),'results':{p:v['current_semantic'] for p,v in bundle['metrics'].items()}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=ROOT/'output');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--notes',type=Path,help='preserve manual notes from an existing limitations.md')
    args=parser.parse_args(argv)
    try:print(json.dumps(export(args.output,args.results/'manifest.json',args.notes),ensure_ascii=False))
    except (ValueError,OSError,KeyError,TypeError) as error:parser.exit(2,'paper-results: '+str(error)+'\n')

if __name__=='__main__':main()
