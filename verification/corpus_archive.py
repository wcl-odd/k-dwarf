"""Read relocatable upstream inputs without consulting a native source checkout.

Only the final portable profile is accepted; historical absolute paths are provenance.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path, PurePosixPath

from .corpus import load_cases

PATH_FORMAT = 'corpus-relative-v1'
OBSERVATIONS = {'source-semantic-requirements', 'standalone-location-identity',
                'queried-object-location-and-declared-properties'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def input_identity(case):
    """Match the existing runner's identity; evidence relocation is not new input."""
    return hashlib.sha256(json.dumps({
        'bytes': case.bytes, 'address_width': case.address_width,
        'endianness': case.endianness, 'architecture': case.architecture,
        'context': case.context, 'purpose': case.purpose,
        'dependencies': case.dependencies}, sort_keys=True).encode()).hexdigest()


def local_path(root, name):
    """Reject escapes and symlinks rather than following a packaged witness out."""
    if (not isinstance(name, str) or not name or '\\' in name or
            PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or
            PurePosixPath(name).as_posix() != name or name == '.'):
        raise ValueError('invalid corpus-relative path: '+str(name))
    root = Path(root).absolute()
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ValueError('symlink in corpus path: '+str(path))
    result = root/name
    for path in (result, *result.parents):
        if path == root:
            break
        if path.is_symlink():
            raise ValueError('symlink in corpus path: '+str(path))
    return result


def validate_archive(root):
    """Check the complete packaged inventory, scopes and original input identity."""
    root = Path(root).absolute()
    manifest_path = local_path(root, 'manifest.json')
    document = json.loads(manifest_path.read_text())
    if document.get('schema') != 1 or document.get('path_format') != PATH_FORMAT:
        raise ValueError('unknown corpus archive format')
    if canonical_hash({k:v for k,v in document.items() if k != 'archive_sha256'}) != document.get('archive_sha256'):
        raise ValueError('corpus manifest identity changed')
    files = {}
    for entry in document['files']:
        name = entry['path']
        path = local_path(root, name)
        if name in files or not path.is_file():
            raise ValueError('missing or duplicate corpus file: '+name)
        if path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise ValueError('corpus file changed: '+name)
        files[name] = entry
    actual = set()
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        local_path(root, name)
        if path.is_file() and name != 'manifest.json':
            actual.add(name)
    if actual != set(files):
        raise ValueError('corpus inventory changed')
    scope_doc = json.loads(local_path(root, 'scope.json').read_text())
    if scope_doc.get('schema') != 1:
        raise ValueError('unknown corpus scope format')
    scope = {}
    for row in scope_doc['cases']:
        if (row['id'] in scope or row['scope'] not in {'semantic', 'auxiliary'} or
                row['observation'] not in OBSERVATIONS or
                not isinstance(row.get('auxiliary_requirements', []), list) or
                any(not isinstance(x, str) for x in row.get('auxiliary_requirements', []))):
            raise ValueError('invalid or duplicate corpus scope')
        scope[row['id']] = row
    identities = set()
    for project, dataset in document['datasets'].items():
        if project not in {'gdb', 'lldb'}:
            raise ValueError('unknown corpus source')
        base = local_path(root, dataset['directory'])
        preparation = json.loads(local_path(base, 'preparation.json').read_text())
        if preparation.get('path_format') != PATH_FORMAT or preparation['source'] != project:
            raise ValueError('corpus preparation profile differs')
        for name in preparation['source_roots'].values():
            local_path(base, name)
        for entry in preparation['source_files'] + preparation.get('artifacts', []):
            path = local_path(base, entry['path'])
            if digest(path) != entry['sha256']:
                raise ValueError('corpus source or evidence changed: '+entry['path'])
        if preparation.get('frozen_selection'):
            from .selection import validate_selection
            proof = preparation['frozen_selection']
            proof_path = local_path(base, proof['path'])
            if digest(proof_path) != proof['sha256']:
                raise ValueError('packaged frozen selection identity changed')
            validate_selection(json.loads(proof_path.read_text()), base)
        if digest(local_path(base, preparation['corpus']['path'])) != preparation['corpus']['sha256']:
            raise ValueError('prepared corpus changed')
        for case in load_cases(base/'cases.json'):
            if case.id in identities or case.id not in scope:
                raise ValueError('missing or duplicate task scope: '+case.id)
            identities.add(case.id)
            row = scope[case.id]
            if (row['project'] != project or case.origin['project'] != project or
                    case.origin['version'] != dataset['version'] or
                    input_identity(case) != row['input_identity'] or
                    canonical_hash(case.upstream_assertions) != row['assertions_sha256']):
                raise ValueError('case input or assertion identity changed: '+case.id)
            resolve_case(base, case)
        counts = Counter(scope[c.id]['scope'] for c in load_cases(base/'cases.json'))
        if dict(counts) != dataset['tasks']:
            raise ValueError('corpus task denominator changed')
    if identities != scope.keys():
        raise ValueError('scope has tasks without input')
    return document, scope


def resolve_case(base, case):
    """Resolve only two runtime-read origin fields; all other paths are provenance."""
    origin = deepcopy(case.origin)
    if origin.get('snapshot'):
        path = local_path(base, origin['snapshot'])
        if not path.is_file():
            raise ValueError('missing packaged snapshot')
        origin['snapshot'] = str(path)
    if origin.get('location_oracle'):
        path = local_path(base, origin['location_oracle']['path'])
        if not path.is_file():
            raise ValueError('missing packaged location witness')
        origin['location_oracle']['path'] = str(path)
    return replace(case, origin=origin)


def read_prepared(inputs):
    """Return cases, preparation and optional portable semantic scope."""
    inputs = Path(inputs).absolute()
    manifest = json.loads((inputs/'preparation.json').read_text())
    profile = manifest.get('path_format')
    if profile != PATH_FORMAT:
        raise ValueError('unknown preparation path format')
    archive, scope = validate_archive(inputs.parent)
    dataset = archive['datasets'][manifest['source']]
    if local_path(inputs.parent, dataset['directory']) != inputs:
        raise ValueError('input directory differs from corpus manifest')
    cases = [resolve_case(inputs, c) for c in load_cases(inputs/'cases.json')]
    manifest = deepcopy(manifest)
    manifest['source_roots'] = {k:str(local_path(inputs, v)) for k,v in manifest['source_roots'].items()}
    if manifest.get('frozen_selection'):
        manifest['frozen_selection']['path'] = str(local_path(inputs, manifest['frozen_selection']['path']))
    return cases, manifest, {c.id:scope[c.id] for c in cases}


def evaluate_scope(record, scope):
    """Reuse the reviewed expression-only projection; preserve source checks."""
    from .metrics import outcome
    from .scope import semantic_checks, location_checks
    checks = semantic_checks(record['checks'], scope.get('auxiliary_requirements', []))
    observation = scope['observation']
    if 'location_check' in record:
        checks = location_checks(checks, record['location_check'], observation)
    elif observation != 'source-semantic-requirements':
        checks = [{'target':'location_identity', 'status':'uncheckable',
                   'semantic_check_complete':False, 'reason':'independent location evidence missing'}]
    status, complete = outcome([record], checks, missing=not checks)
    return {'scope':scope['scope'], 'observation':observation,
            'status':status, 'fully_checked':complete,
            'entered_k':record['execution'] in {'success', 'incomplete'}, 'checks':checks}


def scope_summary(records, require_complete=False):
    """Keep auxiliary diagnostics outside the core expression denominator."""
    from .metrics import count
    selected = [r['corpus_evaluation'] for r in records]
    core = count([r for r in selected if r['scope'] == 'semantic'])
    auxiliary = count([r for r in selected if r['scope'] == 'auxiliary'])
    statuses = core['status']
    failed = statuses['fail'] or statuses['tool_error'] or any(r['execution'] == 'tool_error' for r in records)
    if require_complete:
        failed = failed or statuses['uncheckable'] or statuses['not_run']
    return {'core':core, 'auxiliary':auxiliary, 'exit_code':int(bool(failed))}
