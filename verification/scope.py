"""Reviewed expression-only projections; source checks remain intact."""
from copy import deepcopy

def semantic_checks(checks, auxiliary_facets):
    """Project only already-reviewed non-expression facets out of a matcher."""
    result=[]
    for original in checks:
        check=deepcopy(original)
        facets=check.get('uncheckable') or check.get('details', [])
        if facets and set(facets)<=set(auxiliary_facets):
            # A native diagnostic facet is not evidence of numeric correctness.
            # Both semantic flags must have been established by the checker.
            if check.get('predicates_passed') and check.get('semantic_predicates_checked'):
                check.update(status='pass',semantic_check_complete=True)
        result.append(check)
    return result


def location_checks(checks, observed, observation):
    """Apply the approved position scope, not the archived object-value scope."""
    if observation=='standalone-location-identity':
        return [observed]
    return [c for c in checks if c['target']!='object']+[observed]

