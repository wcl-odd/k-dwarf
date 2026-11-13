"""Development-only integrity checks for the maintained frozen archive."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from .corpus import load_cases
from .corpus_archive import PATH_FORMAT, OBSERVATIONS, local_path, resolve_case


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


