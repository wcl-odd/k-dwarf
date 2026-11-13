"""Read compact, lossless paper evidence without development-report dependencies."""
from collections import Counter
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.setrecursionlimit(max(sys.getrecursionlimit(),100000))

from .metrics import count

LOCATIONS = {'memory','register','value','bytes','composite','implicit_pointer','unavailable'}


def encoded(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()


def pack(records):
    """Deterministic gzip; no machine filename or wall-clock timestamp."""
    return gzip.compress(b''.join(encoded(row) for row in records),mtime=0)


def read_evidence(file):
    tasks={};calls={};coverage=[]
    with gzip.open(file,'rt',encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);kind=row['kind']
            if kind=='task':
                key=(row['project'],row['record']['id'])
                if key in tasks:raise ValueError('duplicate evidence task')
                tasks[key]=row['record']
            elif kind=='invocation':
                name=row['path'];p=PurePosixPath(name)
                if not isinstance(name,str) or p.is_absolute() or '..' in p.parts or p.as_posix()!=name or '\\' in name:
                    raise ValueError('unsafe invocation identity')
                key=(row['project'],row['task'],name)
                if key in calls:raise ValueError('duplicate evidence invocation')
                calls[key]=row
            elif kind=='coverage':coverage.append(row['record'])
            else:raise ValueError('unknown compact evidence record')
    if not tasks:raise ValueError('empty evidence task set')
    if any(k[:2] not in tasks for k in calls):raise ValueError('invocation without root task')
    for key in tasks:
        if (*key,'k/stdout.txt') not in calls:raise ValueError('root K configuration missing')
    return tasks,calls,coverage


def family(name):
    match=re.fullmatch(r'DW_OP_(lit|reg|breg)([0-9]+)',name)
    return 'DW_OP_'+match[1]+'N' if match and int(match[2])<=31 else name


def recompute(tasks, coverage, implemented):
    sources={}
    for project in sorted({p for p,_ in tasks}):
        records=[v for (p,_),v in tasks.items() if p==project]
        rows=[r['corpus_evaluation'] for r in records]
        core=count([r for r in rows if r['scope']=='semantic'])
        sources[project]={'core':core,'auxiliary':count([r for r in rows if r['scope']=='auxiliary']),
            'execution':dict(Counter(r['execution'] for r in records)),
            'attribute_invocations':sum('directory' in e for r in records for e in r.get('dependency_evidence',[])),
            'exit_code':int(bool(core['status']['fail'] or core['status']['tool_error']))}
    roots=[r for r in coverage if r['scope']=='root']
    expected={k for k,v in tasks.items() if v['corpus_evaluation']['scope']=='semantic'}
    if len(roots)!=len(expected) or {(r['project'],r['root_id']) for r in roots}!=expected:
        raise ValueError('coverage root denominator differs')
    inventory=set(implemented)
    if len(inventory)!=len(implemented):raise ValueError('duplicate implemented OP name')
    def coverage_for(records):
        names={o['op'] for r in records for o in r['instructions']}
        if not names<=inventory:raise ValueError('unknown standard OP name')
        kinds=Counter((r.get('result') or {}).get('kind','no_public_result') for r in records)
        return {'expressions':len(records),'op_names':sorted(names),'op_name_count':len(names),
            'op_families':sorted({family(n) for n in names}),'op_family_count':len({family(n) for n in names}),
            'location_counts':dict(sorted(kinds.items())),'location_categories':sorted(set(kinds)&LOCATIONS),
            'location_category_count':len(set(kinds)&LOCATIONS)}
    stats={p:coverage_for([r for r in roots if r['project']==p]) for p in sources}
    stats['combined']=coverage_for(roots)
    return {'tasks':len(tasks),'invocations':None,'sources':sources,
            'coverage':{'metric':'root input presence, not dynamic OP execution; observed final locations',
                        'implemented_op_names':len(inventory),'sources':stats}}


def load(root, corpus, scope):
    """Read stable task/call identities and recompute every displayed count."""
    folder=Path(root)/'results';summary=json.loads((folder/'summary.json').read_text())
    if summary.get('schema')!=1 or summary.get('profile')!='paper-results-v1':raise ValueError('unknown result profile')
    tasks,calls,coverage=read_evidence(folder/'evidence.jsonl.gz')
    if {name for _,name in tasks}!=set(scope):raise ValueError('saved task denominator differs')
    for (project,name),record in tasks.items():
        expected=scope[name]
        if (expected['project']!=project or expected['scope']!=record['corpus_evaluation']['scope']):raise ValueError('saved task identity differs: '+name)
    for item in coverage:
        invocation=item['invocation']
        key=(item['project'],item['root_id'],invocation)
        if key not in calls:raise ValueError('coverage without K invocation')
        if item.get('result')!=calls[key]['payload'].get('result'):raise ValueError('coverage result differs from K output')
    actual=recompute(tasks,coverage,summary['implemented_op_names']);actual['invocations']=len(calls)
    if actual!=summary['statistics']:raise ValueError('saved statistics differ from individual evidence')
    return summary,tasks,calls,coverage
