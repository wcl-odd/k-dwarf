"""Development-only conversion of reviewed archives to self-contained expression cases."""
from copy import deepcopy
import json
from pathlib import Path
from verification.corpus_archive import validate_archive, resolve_case
from verification.corpus import load_cases
from verification.locations import verify_binding, native_location

OBSERVATION_INPUTS = {'pointer_root_size','count_root','resolve_implicit','referent_constants',
    'projection_byte_offset','observe_referent_address','member_address_observation',
    'missing_bound_observation','constant_object_bytes','constant_properties','array_index',
    'element_size','returned_member_layout','object_endianness'}

def export(root):
    root=Path(root)
    manifest,scope=validate_archive(root/'test-corpus')
    rows=[];mapping={};inputs={}
    from verification.corpus_integrity import digest
    for tool,dataset in manifest['datasets'].items():
        base=root/'test-corpus'/dataset['directory']
        for i,case in enumerate(load_cases(base/'cases.json'),1):
            name=tool+'-'+str(i).zfill(3);mapping[case.id]=name
            classification=scope[case.id]
            requirements={'predicates':[{k:deepcopy(v) for k,v in a.items()
                if k not in {'id','source'}} for a in case.upstream_assertions],
                'observation':classification['observation'],
                'layout':{'byte_size':case.object_size},
                'observation_inputs':{k:deepcopy(v) for k,v in case.origin.items() if k in OBSERVATION_INPUTS}}
            if case.object_bit_size is not None:requirements['layout']['bit_size']=case.object_bit_size
            if classification.get('auxiliary_requirements'):requirements['auxiliary_facets']=classification['auxiliary_requirements']
            if case.origin.get('snapshot'):requirements['observation_inputs']['captured_memory']=True
            if not requirements['observation_inputs']:requirements.pop('observation_inputs')
            expression={'bytecode':bytes(case.bytes).hex(' '),'purpose':case.purpose}
            if case.dependencies:expression['dependencies']=deepcopy(case.dependencies)
            interface={'address_width':case.address_width,'endianness':case.endianness,'state':deepcopy(case.context)}
            if case.architecture:interface['architecture']=case.architecture
            sources=[]
            for a in case.upstream_assertions:
                source=a['source']
                sources.append({k:source[k] for k in ['file','line','parameter','original_assertion'] if k in source})
            provenance={'file':case.origin['file'],'test':case.origin['test'],'assertions':sources}
            if case.origin.get('location_oracle'):
                resolved=resolve_case(base,case);target=resolved.origin['location_oracle']['target']
                witness=Path(resolved.origin['location_oracle']['path']);snapshot=Path(resolved.origin['snapshot'])
                evidence=json.loads(witness.read_text());scene=json.loads(snapshot.read_text())
                verify_binding(evidence,snapshot,scene,target)
                if case.bytes!=target['original_root_bytes']:raise ValueError('native location bytecode differs')
                observations=[r for r in evidence['observations'] if r['id']==case.id]
                if len(observations)!=1 or observations[0]['role']!=target['role']:raise ValueError('independent location missing')
                expected=native_location(observations[0])
                if expected['kind'] not in {'memory','register'}:raise ValueError('independent location not observable')
                requirements['location']={'role':target['role'],'expected':{k:v for k,v in expected.items() if k in {'kind','address','register'}}}
                # Human-readable independent observation is provenance, never opened by the runtime.
                provenance['independent_location']={'variable':observations[0].get('variable'),
                    'queries':observations[0].get('queries',[]),'role':target['role']}
            rows.append({'id':name,'tool':tool,'group':'core' if classification['scope']=='semantic' else 'auxiliary',
                'source':provenance,'expression':expression,'interface':interface,'requirements':requirements})
    for p in (root/'test-corpus').rglob('*'):
        if p.is_file():inputs[p.relative_to(root).as_posix()]=digest(p)
    return {'cases':rows},mapping,inputs
