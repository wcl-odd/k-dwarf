"""Observe returned-object members from K locations and saved layouts."""
from dataclasses import replace

def materialize_returned_members(case, payload, memory_supplier=None):
    """Observe fields from K's base location and the captured containing object.

    This is a test observation, never a fabricated K composite result. Each
    source read and placement is retained; missing bytes remain collection gaps.
    """
    from .assertions import materialize
    layout = case.origin['returned_member_layout']
    result = payload.get('result') or {}
    if result.get('kind') != 'memory':
        return None, [], 'base-class expression did not return a memory location'
    origin = dict(case.origin)
    del origin['returned_member_layout']
    output = ['?'] * (case.object_bit_size or case.object_size * 8)
    reads = []
    for field in layout['fields']:
        source = result['address'] if field['source'] == 'K-base' else layout['object_address']
        address = source + field['byte_offset']
        projected = replace(case, origin=origin, object_size=field['byte_size'],
                            object_bit_size=field['byte_size'] * 8)
        bits, evidence, gap = materialize(projected, {'result': {'kind': 'memory', 'address': address}}, memory_supplier=memory_supplier)
        reads.append({'member': field['name'], 'source': field['source'],
                      'address': str(address), 'output_bit_offset': field['output_bit_offset'],
                      'reads': evidence})
        if gap:
            return None, reads, gap
        start = field['output_bit_offset']
        if bits is None or len(bits) != field['byte_size'] * 8 or start < 0 or start + len(bits) > len(output):
            raise ValueError('invalid returned member observation extent')
        if any(b != '?' for b in output[start:start + len(bits)]):
            raise ValueError('overlapping returned member observation')
        output[start:start + len(bits)] = bits
    return ''.join(output), reads, None

