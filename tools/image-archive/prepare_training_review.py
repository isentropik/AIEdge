"""Prepare an unlabelled review manifest; never assign data to training."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from audit_image_archive import audit, read_bounded, unique_keys
from image_archive_store import canonical, digest

GROUP_FIELDS=('device_id','firmware_sha256','model_sha256','calibration_sha256','settings_sha256')

def prepare(root, protected_file):
    raw=read_bounded(Path(protected_file),1024*1024)
    protection=json.loads(raw,object_pairs_hook=unique_keys)
    if not isinstance(protection,dict) or set(protection)!={'version','image_sha256s'} or type(protection['version']) is not int or protection['version']!=1:
        raise ValueError('Expected version 1 protected image-hash manifest')
    hashes=protection['image_sha256s']
    if not isinstance(hashes,list) or any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) for h in hashes):
        raise ValueError('Invalid protected image hashes')
    protected=set(hashes)
    report=audit(root,include_records=True)
    if report['invalid_records']:
        raise ValueError('Archive integrity check failed; no review manifest prepared')
    records=report.pop('verified_records')
    by_image=defaultdict(list)
    for record in records:
        by_image[record['metadata']['image_sha256']].append(record)
    groups={};excluded=[]
    for image_hash,rows in sorted(by_image.items()):
        identities={tuple(r['metadata'][k] for k in GROUP_FIELDS) for r in rows}
        if image_hash in protected or len(identities)!=1:
            excluded.append(dict(image_sha256=image_hash,capture_ids=sorted(r['capture_id'] for r in rows),
                                 reason='protected' if image_hash in protected else 'conflicting_capture_settings'))
            continue
        identity=dict(zip(GROUP_FIELDS,next(iter(identities))))
        group_id=digest(canonical(identity))
        group=groups.setdefault(group_id,dict(group_id=group_id,identity=identity,images=[]))
        group['images'].append(dict(image_sha256=image_hash,
            captures=[dict(capture_id=r['capture_id'],boot_id=r['metadata']['boot_id'],capture_us=r['metadata']['capture_us'],capture_utc=r['metadata']['capture_utc']) for r in sorted(rows,key=lambda r:r['capture_id'])],
            label=None,review_status='unreviewed',split='unassigned',training_eligible=False))
    return dict(version=1,protected_manifest_sha256=digest(raw),archive_audit=report,
        groups=[groups[k] for k in sorted(groups)],excluded=excluded,training_eligible=False,
        limits=['Exact hash protection only; near-duplicate and time-adjacent split leakage still needs review.',
                'No decoding, needle labels, dial crops or training split assignment.',
                'Preserve source records; this manifest is a review starting point, not a training dataset.',
                'Missing UTC stays unknown; capture_us is comparable only within a device boot.',
                'Recheck source hashes before using images; this is a point-in-time inventory.'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path)
    p.add_argument('--protected-hashes',type=Path,required=True,help='Existing held-out and related protected image hashes; explicit empty list only for a new dataset.')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:
        result=prepare(a.archive,a.protected_hashes)
        # Never overwrite review work or write inside the immutable archive.
        if a.output.resolve().is_relative_to(a.archive.resolve()):
            raise ValueError('Review output must be outside the archive')
        with a.output.open('x',encoding='utf-8') as f:
            json.dump(result,f,indent=2)
    except (ValueError,OSError) as exc:
        p.exit(2,str(exc)+'\n')
    print('Review manifest created; images remain unlabelled and excluded from training.')

if __name__=='__main__':main()
