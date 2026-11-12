"""Independent location observations; never interpret DWARF operations here.

The root K result remains unchanged. A queried array element may instead use
the data-location/bounds already computed by K and the reviewed type layout.
"""
import hashlib
import json
import re
from pathlib import Path


def register_numbers():
    from .context import registers
    result = {name: number for number, (name, _) in registers(64, 'x86_64').items()}
    result.update({f'xmm{i}': 17 + i for i in range(16)})
    result.update({f'st{i}': 33 + i for i in range(8)})
    return result


def native_location(record):
    """Accept native pointer or explicit storage diagnostics, not disassembly."""
    if record.get('address') is not None:
        return {'kind': 'memory', 'address': int(record['address'])}
    mapping = register_numbers()
    for query in record.get('queries', []):
        text = query.get('output', '')
        if not query.get('error') and query.get('command', '').startswith('output/x &('):
            address = re.fullmatch(r'\s*(0x[0-9a-fA-F]+)\s*', text)
            if address:
                return {'kind': 'memory', 'address': int(address[1], 16)}
        match = re.search(r'\bin register\s+(\$?[A-Za-z][A-Za-z0-9]*)', text)
        if not match and not query.get('error'):
            match = re.fullmatch(r'Symbol "' + re.escape(record['variable']) +
                                r'" is a variable in \$(\w+)\.\s*', text)
        if match:
            name = match[1].lstrip('$').rstrip('.')
            if name in mapping:
                return {'kind': 'register', 'register': mapping[name], 'name': name,
                        'evidence': query['command'], 'value_availability_proven': False}
    return {'kind': 'unknown', 'reason': record.get('diagnostic') or
            '; '.join(q.get('output', '') for q in record.get('queries', [])) or
            'native debugger did not expose an address or register identity'}


def queried_location(case, payload, role):
    """Project an existing K observation, preserving its root and provenance."""
    if payload.get('observation_gap') or payload.get('dependency_diagnostic'):
        raise ValueError('K object-location dependency is incomplete')
    root = payload.get('result') or {}
    if role in ('root', 'base_subobject'):
        return dict(root)
    if role not in ('resolved_object', 'element'):
        raise ValueError('unreviewed location target role')
    result = dict(payload.get('object_location') or {})
    if result.get('kind') != 'memory':
        raise ValueError('K did not establish the queried object memory location')
    offset = payload.get('object_bit_offset', 0)
    if offset % 8:
        raise ValueError('queried object is not byte aligned')
    result['address'] += offset // 8
    return result


def verify_binding(evidence, snapshot_path, snapshot, target):
    """Reject evidence from a different archive, frame, query or stop."""
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != evidence['snapshot_sha256']:
        raise ValueError('location evidence snapshot identity differs')
    if not evidence.get('same_stop') or not evidence.get('registers_unchanged'):
        raise ValueError('location collection changed the stop or registers')
    if not evidence.get('settings_restored', False):
        raise ValueError('location collection did not restore debugger settings')
    if evidence['suite'] != target['suite'] or snapshot['command'] != target['command']:
        raise ValueError('location evidence query identity differs')
    expected = snapshot.get('frame')
    actual = evidence['before']
    if actual['pid'] != snapshot['pid'] or actual['level'] != target['frame_level']:
        raise ValueError('location evidence frame identity differs')
    if expected and actual['pc'] != expected['pc']:
        raise ValueError('location evidence program counter differs')


def compare_location(actual, expected):
    if expected.get('kind') == 'unknown':
        return 'uncheckable', expected.get('reason', 'native location unavailable')
    if actual.get('kind') not in ('memory', 'register'):
        return 'uncheckable', 'K did not return the reviewed standalone location'
    if actual['kind'] != expected['kind']:
        return 'difference', 'K and native location categories differ'
    key = 'address' if actual['kind'] == 'memory' else 'register'
    return ('match', key + ' agrees') if actual[key] == expected[key] else ('difference', key + ' differs')


def check_archived(case, payload):
    """Replay an optional auxiliary location check without a live debugger.

    Source predicates remain separate. Missing or corrupt evidence cannot be
    converted to a semantic pass, and a root descriptor is retained verbatim.
    """
    oracle = case.origin.get('location_oracle')
    if oracle is None:
        return None
    record = {'id': case.id, 'target': 'location_identity', 'role': oracle['target']['role'],
              'k_root_result': payload.get('result'), 'native_evidence': oracle['path']}
    try:
        path = Path(oracle['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != oracle['sha256']:
            raise ValueError('native location evidence identity differs')
        evidence = json.loads(path.read_text())
        snapshot_path = Path(case.origin['snapshot'])
        snapshot = json.loads(snapshot_path.read_text())
        target = oracle['target']
        if case.bytes != target['original_root_bytes']:
            raise ValueError('root expression differs from the reviewed native query')
        verify_binding(evidence, snapshot_path, snapshot, target)
        matches = [r for r in evidence['observations'] if r['id'] == case.id]
        if len(matches) != 1 or matches[0]['role'] != target['role']:
            raise ValueError('native observation target is absent or ambiguous')
        expected = native_location(matches[0])
        record['native_location'] = expected
        try:
            actual = queried_location(case, payload, target['role'])
        except ValueError as error:
            record.update(status='uncheckable', reason=str(error), semantic_check_complete=False)
            return record
        state, reason = compare_location(actual, expected)
        record.update(k_queried_location=actual, reason=reason,
                      status={'match':'pass', 'difference':'fail'}.get(state, state),
                      semantic_check_complete=state in ('match', 'difference'),
                      dependency_results=payload.get('dependency_results', {}),
                      properties=payload.get('properties', {}))
    except (OSError, ValueError, KeyError, TypeError) as error:
        record.update(status='tool_error', semantic_check_complete=False, reason=str(error))
    return record
