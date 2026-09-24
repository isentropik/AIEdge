"""Prepare an unlabelled review manifest; never assign data to training."""
import argparse
from collections import defaultdict
from bisect import bisect_left
import json
from pathlib import Path
import re
from audit_image_archive import audit, read_bounded, unique_keys
from image_archive_store import canonical, digest

GROUP_FIELDS=('device_id','firmware_sha256','model_sha256','calibration_sha256','settings_sha256')

def prepare(root, protected_file, protect_window_seconds=300):
    if type(protect_window_seconds) is not int or not 0 <= protect_window_seconds <= 86400:
        raise ValueError('Protection window must be an integer from 0 to 86400 seconds')
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
    anchors=defaultdict(list)
    for row in records:
        m=row['metadata']
        if m['image_sha256'] in protected:
            anchors[(m['device_id'],m['boot_id'])].append((m['capture_us'],row['capture_id']))
    for values in anchors.values():values.sort()
    window_us=protect_window_seconds*1000000
    def neighbor(rows):
        nearest=None
        if not window_us:return None
        for row in rows:
            m=row['metadata'];values=anchors.get((m['device_id'],m['boot_id']),[])
            index=bisect_left(values,(m['capture_us'],''))
            for at in (index-1,index):
                if not 0<=at<len(values):continue
                timestamp,anchor_id=values[at]
                distance=abs(m['capture_us']-timestamp)
                candidate=(distance,anchor_id,row['capture_id'])
                if distance<=window_us and (nearest is None or candidate<nearest):nearest=candidate
        return None if nearest is None else dict(distance_us=nearest[0],protected_capture_id=nearest[1],neighbor_capture_id=nearest[2])
    groups={};excluded=[]
    for image_hash,rows in sorted(by_image.items()):
        identities={tuple(r['metadata'][k] for k in GROUP_FIELDS) for r in rows}
        nearby=neighbor(rows)
        if image_hash in protected or nearby is not None or len(identities)!=1:
            reason='protected' if image_hash in protected else 'protected_time_neighbor' if nearby is not None else 'conflicting_capture_settings'
            entry=dict(image_sha256=image_hash,capture_ids=sorted(r['capture_id'] for r in rows),reason=reason)
            if reason=='protected_time_neighbor':entry['temporal_match']=nearby
            excluded.append(entry)
            continue
        identity=dict(zip(GROUP_FIELDS,next(iter(identities))))
        group_id=digest(canonical(identity))
        group=groups.setdefault(group_id,dict(group_id=group_id,identity=identity,images=[]))
        group['images'].append(dict(image_sha256=image_hash,
            captures=[dict(capture_id=r['capture_id'],boot_id=r['metadata']['boot_id'],capture_us=r['metadata']['capture_us'],capture_utc=r['metadata']['capture_utc']) for r in sorted(rows,key=lambda r:r['capture_id'])],
            label=None,review_status='unreviewed',split='unassigned',training_eligible=False))
    return dict(version=1,protected_manifest_sha256=digest(raw),protect_window_seconds=protect_window_seconds,protected_hashes_without_capture_records=sorted(protected-set(by_image)),archive_audit=report,
        groups=[groups[k] for k in sorted(groups)],excluded=excluded,training_eligible=False,
        limits=['Time-window exclusion uses original protected captures in the same device boot; it is not visual near-duplicate detection or a split assignment.',
                'No decoding, needle labels, dial crops or training split assignment.',
                'Preserve source records; this manifest is a review starting point, not a training dataset.',
                'Missing UTC stays unknown; capture_us is comparable only within a device boot.',
                'Recheck source hashes before using images; this is a point-in-time inventory.'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path)
    p.add_argument('--protected-hashes',type=Path,required=True,help='Existing held-out and related protected image hashes; explicit empty list only for a new dataset.')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--protect-window-seconds',type=int,default=300,help='Exclude same-boot captures within this interval of held-out captures (default: 300; 0 disables temporal exclusion).')
    a=p.parse_args()
    try:
        result=prepare(a.archive,a.protected_hashes,a.protect_window_seconds)
        # Never overwrite review work or write inside the immutable archive.
        if a.output.resolve().is_relative_to(a.archive.resolve()):
            raise ValueError('Review output must be outside the archive')
        with a.output.open('x',encoding='utf-8') as f:
            json.dump(result,f,indent=2)
    except (ValueError,OSError) as exc:
        p.exit(2,str(exc)+'\n')
    print('Review manifest created; images remain unlabelled and excluded from training.')

if __name__=='__main__':main()
