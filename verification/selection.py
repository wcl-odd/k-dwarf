"""Authenticate the final reviewed selection, without rerunning discovery.

The corpus inventory pins the complete reviewed artifact. This validates its
selection hash, archived source/dependency identities, and quoted anchors;
it does not reimplement source selection or infer new review decisions.
"""
import json
from .corpus_integrity import canonical_hash, digest
from .corpus_archive import local_path

def validate_selection(frozen, base):
    selection = frozen['selection']
    if canonical_hash(selection) != frozen['selection_sha256']:
        raise ValueError('packaged frozen selection content changed')
    for row in selection['files'] + selection['dependencies']:
        path = local_path(base, 'sources/' + row['project'] + '/' + row['file'])
        if not path.is_file() or digest(path) != row['sha256']:
            raise ValueError('frozen source or dependency changed: ' + str(path))
    for row in selection['files']:
        source = local_path(base, 'sources/' + row['project'] + '/' + row['file'])
        lines = source.read_text().splitlines()
        for site in row.get('sites', []):
            review = site.get('review', {})
            if review.get('disposition') not in {'semantic','auxiliary','excluded'} or not review.get('reason'):
                raise ValueError('unresolved source review')
            for quote in review.get('evidence', []):
                if not 0 < quote['line'] <= len(lines) or quote['text'] != lines[quote['line']-1]:
                    raise ValueError('review source anchor changed')
            if review['disposition'] == 'semantic' and not site.get('instances'):
                raise ValueError('unexpanded semantic assertion')
    return selection
