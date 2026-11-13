"""Development-only export of primary paper results, without run directories."""
import csv
import io
import json
from pathlib import Path

from verification.baseline import pack, recompute
from hashlib import sha256
from verification.corpus_integrity import digest
from verification.paper_results import load_bundle, read_notes
from verification.paper_coverage import OPCODES, coverage_totals


def sha(data):
    return sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()


def csv_bytes(columns,rows):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore')
    writer.writeheader();writer.writerows(rows);return stream.getvalue().encode()


def export(root):
    root=Path(root);bundle=load_bundle(root/'output/manifest.json');archive=bundle['archive']
    records=[];tasks={};calls={}
    for project in ('lldb','gdb'):
        report=archive.json('evidence/'+project+'/report.json')
        for record in report['cases']:
            name=record['id'];tasks[project,name]=record
            records.append({'kind':'task','project':project,'record':record})
            base=root/'output/evidence'/project/name
            for path in sorted(base.rglob('stdout.txt')):
                if path.parent.name!='k':continue
                raw=archive.read(path);relative=path.relative_to(base).as_posix()
                call={'kind':'invocation','project':project,'task':name,'path':relative,
                      'original_stdout_sha256':sha(raw),'payload':json.loads(raw)}
                for field,file in [('input_evidence','input-evidence.json'),('context_evidence','context-evidence.json')]:
                    p=path.parent/file
                    if p.is_file():call[field]=archive.json(p)
                records.append(call);calls[project,name,relative]=call
    coverage=archive.json('coverage/evidence.json')
    items=[]
    for original in coverage['records']:
        item=dict(original)
        file=Path(item.pop('final_configuration'))
        if file.parts[:3]!=('evidence',item['project'],item['root_id']):raise ValueError('coverage path differs')
        item['invocation']=Path(*file.parts[3:]).as_posix()
        item['provenance']={'manifest':item.pop('manifest'),'final_configuration':str(file)}
        key=(item['project'],item['root_id'],item['invocation'])
        if key not in calls:raise ValueError('coverage invocation missing')
        records.append({'kind':'coverage','record':item});items.append(item)
    stats=recompute(tasks,items,sorted(OPCODES.values()));stats['invocations']=len(calls)
    if stats['sources']!=bundle['summary']['sources']:raise ValueError('compact/source statistics differ')
    totals=coverage_totals(coverage);combined=stats['coverage']['sources']['combined']
    if (combined['op_name_count']!=totals['primary_op_coverage']['name_count'] or
        combined['op_family_count']!=totals['primary_op_coverage']['family_count'] or
        combined['location_category_count']!=totals['sources']['combined']['location_kind_count']):raise ValueError('compact coverage differs')
    data=pack(records)
    notes={**bundle['notes'],**read_notes(root/'docs/evaluation/limitations.md')}
    summary={'schema':1,'profile':'paper-results-v1','corpus_sha256':bundle['corpus']['archive_sha256'],
        'versions':bundle['corpus']['datasets'],'evidence_sha256':sha(data),
        'implemented_op_names':sorted(OPCODES.values()),'statistics':stats,
        'original_execution':archive.json('summary.json'),
        'original_result_identity':bundle['manifest']['identity'],
        'original_result_manifest_sha256':digest(root/'output/manifest.json'),
        'selection_sha256':{p:v['selection_sha256'] for p,v in bundle['summary']['source_requirements'].items()},
        'evidence_format':'JSON Lines gzip: task, invocation, coverage; paths inside record bodies are provenance only'}
    rows=[];differences=[]
    for (project,name),record in sorted(tasks.items()):
        evaluation=record['corpus_evaluation']
        row={'id':name,'source':project,'execution':record['execution'],'input_identity':record['input_identity'],
             'budget_exhausted':record['budget_exhausted'],**evaluation,'人工备注':notes.get(name,'')}
        rows.append(row)
        if evaluation['scope']=='auxiliary' or evaluation['status']!='pass':
            differences.append({**row,'analysis':bundle['analyses'].get(name,record.get('diagnostic') or evaluation['status']),
                                'evidence_key':f'task:{project}:{name}'})
    lines=['# Recorded paper results','','Expression/context tasks are counted once. All in-scope predicates must hold.','',
           '| Source | Core | Pass | Differences | Uncheckable | Tool errors | Confirmed/core |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for project,s in stats['sources'].items():
        c=s['core'];v=c['status'];lines.append(f"| {project.upper()} | {c['total']} | {v['pass']} | {v['fail']} | {v['uncheckable']} | {v['tool_error']} | {100*c['pass_rate']:.2f}% |")
    lines+=['',f"Auxiliary checks: {sum(s['auxiliary']['total'] for s in stats['sources'].values())}; outside the core denominator. {stats['tasks']} archived tasks and {stats['invocations']} K invocations, including dependencies and stability probes.",'',
       f"Root-input presence covers {combined['op_name_count']} standard OP names ({combined['op_family_count']} OP families after merging numbered variants). Final results cover {combined['location_category_count']} location categories. This is not a dynamic OP execution trace.",'',
       '| File | Contents |','| --- | --- |',
       '| summary.json | Recomputed counts, source/selection identities and original execution provenance |',
       '| expressions.csv | Every task, execution state and original-requirement outcome |',
       '| differences.csv | Core differences and auxiliary checks, analysis and manual remarks |',
       '| evidence.jsonl.gz | Complete task checks, K outputs and per-expression coverage evidence |','',
       'The compressed evidence is standard gzip JSON Lines: use `python3 -m gzip -d -c results/evidence.jsonl.gz` to inspect it. Task keys are project/ID; invocation keys additionally include the relative invocation path. Each complete K configuration retains the supplied expression and context. The frozen corpus supplies original bytes, snapshots and expected answers; original and documentation-only packaging identities link both packages. Historical paths embedded in record bodies are provenance, never runtime dependencies.','',
       'Known differences are retained. A successful reproduction means the same semantic conclusions and K configurations; it does not mean every upstream assertion passes. Memory locations compare category/address; register locations compare category/DWARF number. Direct values and composite pieces retain their original value, bit and availability predicates.','',
       'Only the selected upstream experiment is packaged. Developer regressions, symbolic proofs, teaching examples and cross-version probes are not included. No floating arithmetic execution is confirmed in the upstream set; float metadata or register-bit transport alone is not floating computation. Conclusions do not establish complete DWARF correctness.']
    location_counts=combined['location_counts']
    lines.insert(12,'Observed root location counts: '+', '.join(f"{k}={v}" for k,v in location_counts.items() if k not in {'scalar','no_public_result'})+'. '
        +f"Scalar attribute values ({location_counts.get('scalar',0)}) and tasks without a public result ({location_counts.get('no_public_result',0)}) are separate; neither is a location category.")
    # Keep the full review-note inventory available to development exporters.
    # Publication omits this duplicate file; published CSVs retain the remarks.
    output={'README.md':('\n'.join(lines)+'\n').encode(),'summary.json':json_bytes(summary),
            'expressions.csv':csv_bytes(['id','source','scope','execution','entered_k','fully_checked','status','budget_exhausted','input_identity','人工备注'],rows),
            'differences.csv':csv_bytes(['id','source','scope','status','analysis','evidence_key','人工备注'],differences),
            'notes.json':json_bytes(notes),'evidence.jsonl.gz':data}
    archive.unchanged()
    # Publication rechecks all source dependencies after staging.
    inputs={p.resolve().relative_to(root.resolve()).as_posix():h for p,h in archive.hashes.items()}
    for p in [root/'docs/evaluation/limitations.md',root/'test-corpus/manifest.json']:
        inputs[p.relative_to(root).as_posix()]=digest(p)
    return output,inputs
