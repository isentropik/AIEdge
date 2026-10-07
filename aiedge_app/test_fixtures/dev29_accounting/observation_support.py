"""Versioned support assertions on one immutable image, never retained rows."""
from reading_format import finite_number

SUPPORT_VERSION=1
def observed_rows(result):
    rows=result.get('dial_positions')
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
        raise ValueError('invalid_dial_results')
    # Legacy unchanged full reader results preserve their existing admission path.
    if 'observation_support' not in result:return [True]*len(rows)
    support=result['observation_support']
    if not isinstance(support,dict) or set(support)!= {'schema_version','source_sha256','pipeline_id','observed'}:
        raise ValueError('invalid_observation_support')
    if type(support['schema_version']) is not int or support['schema_version']!=SUPPORT_VERSION:
        raise ValueError('unsupported_observation_support_version')
    if support['source_sha256']!=result.get('source_sha256') or support['pipeline_id']!=result.get('pipeline_id'):
        raise ValueError('observation_support_identity_mismatch')
    mask=support['observed']
    if not isinstance(mask,list) or len(mask)!=len(rows) or any(type(x) is not bool for x in mask) or not any(mask):
        raise ValueError('invalid_observation_mask')
    for row,flag in zip(rows,mask):
        if 'source_sha256' in row and row['source_sha256']!=result['source_sha256']:
            raise ValueError('dial_row_source_mismatch')
        if flag:
            p=row.get('position')
            if row.get('state')!='estimated' or not finite_number(p) or not 0<=p<10:
                raise ValueError('observed_dial_unavailable')
        elif row.get('state')!='unavailable' or row.get('position') is not None:
            raise ValueError('unobserved_dial_stale_injection')
    return list(mask)

def document_observation(result,indices):
    rows=result.get('dial_positions');mask=observed_rows(result)
    if sorted(indices)!=list(range(len(rows))):raise ValueError('reading_dial_mapping_mismatch')
    return [rows[i].get('position') for i in indices],[mask[i] for i in indices]
