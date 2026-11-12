"""Schedule archived attribute expressions; all OP execution is delegated to K."""
from dataclasses import replace
from .input import prepare, write_json
from .backends import k


class ObservationGap(Exception):
    """Saved input is insufficient to observe a K-produced location."""


def read_object_integer(case, payload, context, byte_size, memory_supplier=None):
    """Observe an object at a K location, without evaluating any DWARF OP."""
    from .assertions import materialize
    projected=replace(case,context=context,object_size=byte_size,object_bit_size=byte_size*8)
    bits,reads,gap=materialize(projected,payload,memory_supplier=memory_supplier)
    if gap or bits is None or len(bits)<byte_size*8 or '?' in bits[:byte_size*8]:
        raise ObservationGap(gap or 'pointer/count object has unavailable bits in the archived snapshot')
    return int(bits[:byte_size*8][::-1],2),reads


def root_observation(case,payload,context,evidence,memory_supplier=None):
    if case.origin.get('pointer_root_size'):
        number,reads=read_object_integer(case,payload,context,case.origin['pointer_root_size'],memory_supplier=memory_supplier)
        payload['observed_value']=number
        payload['object_location']={'kind':'memory','address':number}
        evidence.append({'id':'root-pointer-object','object_reads':reads,'value':str(number)})
    if case.origin.get('count_root'):
        result=payload.get('result') or {}
        if result.get('kind') in {'memory','register'}:
            number,reads=read_object_integer(case,payload,context,4,memory_supplier=memory_supplier)
            payload['observed_value']=number
            evidence.append({'id':'root-count-object','object_reads':reads,'value':str(number)})


def implicit_observation(case,payload,context,directory,options,evidence):
    """Resolve a referenced DIE by invoking K on its saved location expression.

    A DW_AT_const_value is metadata, so observing it needs no expression.
    Cycles and missing captured data are observation gaps, never guessed values.
    The original implicit-pointer result and every additional K result survive.
    """
    result=payload.get('result') or {};offset=case.origin.get('projection_byte_offset',0)
    seen=set();chain=[]
    while result.get('kind')=='implicit_pointer':
        ref=str(result['reference']);offset+=result['offset']
        if ref in seen or len(seen)>=32:raise ObservationGap('cyclic or excessive implicit-reference dependency')
        seen.add(ref)
        body=context.get('die_locations',{}).get(ref)
        if body is None:raise ObservationGap('referenced DIE metadata was not captured')
        constants=case.origin.get('referent_constants',{})
        if ref in constants:
            result={'kind':'bytes','bytes':constants[ref]}
            evidence.append({'id':'referent-'+ref,'constant_bytes':constants[ref]})
        elif 'const_value' in body:
            width=body.get('byte_size',0)
            if width<=0:raise ObservationGap('referenced constant has no object size')
            number=body['const_value'] % (1 << (width*8))
            result={'kind':'bytes','bytes':list(number.to_bytes(width,case.endianness))}
            evidence.append({'id':'referent-'+ref,'constant_integer':str(body['const_value']),'byte_size':width})
        else:
            local={**context,'compilation_unit_offset':body.get('unit_offset',0),
                   'dwarf_offset_size':body.get('offset_size',4),'raw_types':body.get('raw_types',{}),
                   'types':body.get('types',{}),'debug_addr':body.get('debug_addr',{})}
            dep=replace(case,id=case.id+'--referent-'+ref,bytes=body['bytes'],purpose='location',context=local,
                        address_width=body.get('address_width',case.address_width),dependencies=[],upstream_assertions=[])
            dest=directory/'dependencies'/('referent-'+ref);prepare(dep,dest)
            observation=k.run(dep,dest,options)
            evidence.append({'id':'referent-'+ref,'status':observation.native.get('status'),
                             'result':observation.native.get('result'),'directory':str(dest)})
            if observation.state=='tool_error':raise ValueError(observation.diagnostic)
            if observation.state!='success':raise ObservationGap('referenced location expression did not complete')
            result=observation.native['result'];chain.append(observation.native)
    payload['implicit_dependencies']=[{'status':p.get('status'),'result':p.get('result')} for p in chain]
    if result.get('kind')=='memory':
        payload['object_location']={**result,'address':result['address']+offset}
    elif offset<0:
        raise ObservationGap('implicit pointer projects before the captured value object')
    else:
        payload['object_location']=result;payload['object_bit_offset']=offset*8
    if case.origin.get('observe_referent_address'):
        if result.get('kind')!='memory':raise ObservationGap('referent has no observable memory address')
        payload['observed_result']=payload['object_location']


def value(payload):
    if 'observed_value' in payload: return payload['observed_value']
    result=payload.get('result') or {}
    if result.get('kind')=='memory': return result['address']
    if result.get('kind') in {'scalar','value'}: return result['value']
    raise ValueError('dependency did not return an integer/address')


def execute(case, directory, options):
    context=dict(case.context or {})
    results={}; evidence=[]
    def run_node(node):
        nonlocal context
        guard = node.get('when')
        if guard is not None:
            ref = guard['dependency']
            if ref not in results or results[ref].get('status') != 'completed':
                raise ObservationGap('attribute guard has no completed K result: ' + ref)
            number = value(results[ref])
            if (number != 0) != guard['nonzero']:
                evidence.append({'id': node['id'], 'role': node.get('role'),
                    'bytes': node['bytes'], 'status': 'skipped',
                    'guard': guard, 'guard_value': str(number),
                    'reason': 'K-computed attribute guard excludes this dependency'})
                return True
        local=dict(context)
        for name,ref in node.get('bind',{}).items():
            if ref not in results: raise ValueError('missing or cyclic attribute dependency: '+ref)
            local[name]=value(results[ref])
        dep=replace(case,id=case.id+'--'+node['id'],bytes=node['bytes'],purpose=node['purpose'],context=local,
                    dependencies=[],upstream_assertions=[])
        dest=directory/'dependencies'/node['id']
        prepare(dep,dest)
        observation=k.run(dep,dest,options)
        payload=observation.native
        results[node['id']]=payload
        evidence.append({'id':node['id'],'role':node.get('role'), 'purpose':dep.purpose,
            'bytes':dep.bytes,'bind':node.get('bind',{}),'status':payload.get('status'),
            'result':payload.get('result'),'directory':str(dest)})
        if observation.state!='success': return False
        if node.get('role')=='framebase' and (payload.get('result') or {}).get('kind')=='register':
            number=str(payload['result']['register'])
            if number not in context.get('registers',{}): raise ObservationGap('frame base register was not captured')
            payload['observed_value']=context['registers'][number]
            evidence[-1]['register_read']={'register':number,'value':str(payload['observed_value'])}
        if node.get('read_result'):
            layout=node['read_result'];result=payload['result']
            width=layout.get('bit_width',layout['byte_size']*8)
            if result['kind']=='register':
                number=str(result['register'])
                if number not in context.get('registers',{}): raise ObservationGap('referenced bound register was not captured')
                integer=context['registers'][number] % (1<<width)
                evidence[-1]['register_read']={'register':number,'value':str(integer),'layout':layout}
            else:
                address=value(payload)
                supplier=getattr(options,'memory_supplier',None)
                if supplier is not None:
                    supplier.ensure(context,address,layout['byte_size'],reason='referenced bound object')
                data=[context.get('memory',{}).get(str(address+i)) for i in range(layout['byte_size'])]
                evidence[-1]['object_reads']={'address':str(address),'bytes':data,'layout':layout}
                if any(b is None for b in data): raise ObservationGap('referenced bound memory was not captured')
                integer=int.from_bytes(bytes(data),layout.get('endianness',case.endianness)) % (1<<width)
            if layout.get('signed') and integer >= (1<<(width-1)):integer-=1<<width
            payload['observed_value']=integer+node.get('add',0)
        elif node.get('add'): payload['observed_value']=value(payload)+node['add']
        if node.get('assign'): context[node['assign']]=value(payload)
        return True
    directory.joinpath('dependencies').mkdir(exist_ok=True)
    def checked_node(node):
        try:return run_node(node),None
        except ObservationGap as error:
            return False,{'kind':'observation_gap','diagnostic':str(error),'dependency':node['id']}
    for node in case.dependencies:
        if node.get('phase')!='before':continue
        success,gap=checked_node(node)
        if not success:
            write_json(directory/'dependency-evidence.json',evidence)
            return None,context,results,evidence,gap or 'prerequisite attribute expression did not complete'
    actual=replace(case,context=context)
    write_json(directory/'context.json',{'address_width':case.address_width,'endianness':case.endianness,
        **({'architecture':case.architecture} if case.architecture else {}),**context})
    obs=k.run(actual,directory,options); results['root']=obs.native
    reason=None
    if obs.state=='success':
        try:
            root_observation(case,obs.native,context,evidence,getattr(options,'memory_supplier',None))
            if case.origin.get('resolve_implicit'):
                implicit_observation(case,obs.native,context,directory,options,evidence)
        except ObservationGap as error:
            reason={'kind':'observation_gap','diagnostic':str(error),'dependency':'root'}
        for node in case.dependencies:
            if reason:break
            if node.get('phase')=='before':continue
            success,gap=checked_node(node)
            if not success:
                reason=gap or 'attribute expression did not complete: '+node['id'];break
    write_json(directory/'dependency-evidence.json',evidence)
    return obs,context,results,evidence,reason


def observation(case, payload, results, reason):
    # Keep native K output intact. This is an explicitly derived test observation.
    observed=dict(payload)
    observed['dependency_results']={key:{'status':p.get('status'),'result':p.get('result')} for key,p in results.items()}
    if reason:
        if isinstance(reason,dict):
            observed['observation_gap']=reason;return observed
        observed['status']='incomplete';observed['dependency_diagnostic']=reason;return observed
    if 'data_location' in results: observed['object_location']=results['data_location']['result']
    properties={}
    if 'allocated' in results:
        properties['allocated'] = value(results['allocated']) != 0
    projection = case.origin.get('member_address_observation')
    if projection:
        root = payload.get('result') or {}
        if root.get('kind') != 'memory':
            observed['observation_gap'] = {'kind': 'observation_gap',
                'diagnostic': 'member address requires a completed memory location'}
            return observed
        observed['observed_result'] = {'kind': 'memory',
            'address': root['address'] + projection['byte_offset']}
        observed['member_address_evidence'] = {'root_result': root,
            'member': projection, 'result': observed['observed_result'], 'memory_reads': []}
    missing_bounds = case.origin.get('missing_bound_observation')
    if missing_bounds:
        properties['bounds_available'] = False
        observed['bound_availability_evidence'] = missing_bounds
    if case.origin.get('count_root'):properties['count']=value(results['root'])
    if case.origin.get('constant_object_bytes') is not None:
        observed['object_location']={'kind':'bytes','bytes':case.origin['constant_object_bytes']}
    for name in ('lower_bound','upper_bound','count'):
        if name in results: properties[name]=value(results[name])
        elif name in case.origin.get('constant_properties',{}): properties[name]=case.origin['constant_properties'][name]
    if 'lower_bound' in properties and 'upper_bound' in properties:
        properties['count']=max(0,properties['upper_bound']-properties['lower_bound']+1)
    dimensions={**{k:v for k,v in case.origin.get('constant_properties',{}).items() if k.startswith('dimension_')},
                **{k:value(v) for k,v in results.items() if k.startswith('dimension_')}}
    if dimensions:
        properties['shape']=[dimensions[k] for k in sorted(dimensions)]
        if len(dimensions)==1:properties['count']=properties['shape'][0]
    observed['properties']=properties
    if 'array_index' in case.origin:
        index=case.origin['array_index']; lower=properties.get('lower_bound',0)
        if index<lower or ('upper_bound' in properties and index>properties['upper_bound']):
            observed['status']='incomplete';observed['dependency_diagnostic']='array index outside the K-computed bounds'
        observed['object_bit_offset']=(index-lower)*case.origin['element_size']*8
    return observed
