"""Run each unchanged LLVM regression in an isolated process with four workers."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json,os,sys,time,unittest
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--definition',type=Path,required=True)
    parser.add_argument('--core-definition',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.root.absolute();output=args.output.absolute()
    if output.exists():parser.error('output must not exist')
    if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    os.environ.update(DWARF_DEFINITION=str(args.definition.absolute()),DWARF_CORE_DEFINITION=str(args.core_definition.absolute()),
                      PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',GHCRTS='-N1',K_OPTS='-Xmx512m -Xss8m')
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests/semantics'))
    from verification.process import execute,stop_children,ToolFailure
    suite=unittest.TestLoader().discover(str(root/'tests/semantics'),pattern='test_*.py')
    def flatten(s):
        for item in s:
            if isinstance(item,unittest.TestSuite):yield from flatten(item)
            else:yield item.id()
    ids=sorted(flatten(suite));assert len(ids)==len(set(ids))
    output.mkdir(parents=True)
    (output/'tasks.json').write_text(json.dumps(ids,indent=2)+'\n')
    print('LLVM regressions:',len(ids),'unique tests, four workers',flush=True)
    def run(name):
        start=time.monotonic()
        try:
            proc=execute([sys.executable,'-B','-m','unittest','-v',name],output/name,1800,cwd=root/'tests/semantics',env={'PYTHONPATH':str(root)+os.pathsep+str(root/'tests/semantics')})
            return {'id':name,'returncode':proc.returncode,'seconds':time.monotonic()-start}
        except ToolFailure as error:return {'id':name,'returncode':1,'error':str(error),'seconds':time.monotonic()-start}
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(run,name) for name in ids]
        try:
            for future in as_completed(futures):
                row=future.result();rows.append(row)
                (output/'results.json').write_text(json.dumps(sorted(rows,key=lambda r:r['id']),indent=2)+'\n')
                print(len(rows),'/',len(ids),row['id'],row['returncode'],flush=True)
        except BaseException:
            for future in futures:future.cancel()
            stop_children();raise
    result={'tasks':len(ids),'completed':len(rows),'pass':sum(r['returncode']==0 for r in rows),'fail':sum(r['returncode']!=0 for r in rows),'jobs':4,'ids_unique':True,'all_expected_ids_executed':set(ids)=={r['id'] for r in rows}}
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return int(bool(result['fail']))

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(130)
