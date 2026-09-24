"""Create a bounded, read-only image gallery outside the immutable archive."""
import argparse
import html
import io
import json
from pathlib import Path
from PIL import Image
from audit_image_archive import read_bounded
from image_archive_store import digest,MAX_IMAGE_BYTES
from prepare_training_review import prepare

STYLE="""
:root{color-scheme:light dark;--bg:#f3f6f7;--card:#fff;--text:#16272b;--muted:#526469;--line:#cbd7da;--accent:#087565}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#101b1f;--card:#1a2a30;--text:#edf3f5;--muted:#bdcbd0;--line:#3b525c;--accent:#82dac6}}
:root[data-theme=light]{color-scheme:light}:root[data-theme=dark]{color-scheme:dark;--bg:#101b1f;--card:#1a2a30;--text:#edf3f5;--muted:#bdcbd0;--line:#3b525c;--accent:#82dac6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}main{max-width:1000px;margin:auto;padding:20px}header{display:flex;align-items:center;justify-content:space-between;gap:16px}h1{font-size:1.5rem;margin:0}h2{font-size:1.15rem}p{margin:12px 0}.muted{color:var(--muted)}select{padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--text)}article{margin:22px 0;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}article img{display:block;width:100%;height:auto}section{padding:16px}summary{cursor:pointer}code{overflow-wrap:anywhere;font-size:.8rem}a{color:var(--accent)}dl{margin:12px 0}dt{color:var(--muted)}dd{margin:0 0 10px;overflow-wrap:anywhere}header label{white-space:nowrap}details{margin:14px 0}@media(max-width:420px){main{padding:12px}header{align-items:flex-start}header label{font-size:.85rem}h1{font-size:1.25rem}}
"""
SCRIPT="""
const theme=document.querySelector('select');
function apply(value){document.documentElement.dataset.theme=value;theme.value=value;}
try{const saved=localStorage.getItem('aiedge-review-theme');if(['system','light','dark'].includes(saved))apply(saved);}catch(e){}
theme.addEventListener('change',()=>{apply(theme.value);try{localStorage.setItem('aiedge-review-theme',theme.value);}catch(e){}});
"""

def build(archive,protection,group_id,output,offset=0,limit=6,protect_window_seconds=300):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=12:
        raise ValueError('Use a nonnegative offset and a limit from 1 to 12')
    archive=Path(archive);output=Path(output)
    if output.resolve().is_relative_to(archive.resolve()):raise ValueError('Gallery must be outside archive')
    if output.exists():raise ValueError('Gallery output already exists')
    review=prepare(archive,protection,protect_window_seconds)
    groups=[g for g in review['groups'] if g['group_id']==group_id]
    if len(groups)!=1:raise ValueError('Select an existing review group ID')
    group=groups[0];selected=group['images'][offset:offset+limit]
    if not selected:raise ValueError('No images at requested offset')
    blobs=[]
    for row in selected:
        data=read_bounded(archive/'blobs'/(row['image_sha256']+'.image'),MAX_IMAGE_BYTES)
        if digest(data)!=row['image_sha256']:raise ValueError('Image changed after audit')
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('JPEG','PNG') or image.width*image.height>2000000 or getattr(image,'n_frames',1)!=1:
                raise ValueError('Review supports single JPEG/PNG images up to two million pixels')
            extension='jpg' if image.format=='JPEG' else 'png'
            image.load()
        blobs.append((row['image_sha256']+'.'+extension,data))
    cards=[]
    esc=lambda v:html.escape(str(v),quote=True)
    for number,(row,(name,data)) in enumerate(zip(selected,blobs),offset+1):
        captures=''.join('<li>'+esc(c['capture_utc'] or 'UTC unknown')+' â€” boot '+esc(c['boot_id'])+', capture '+esc(c['capture_us'])+' Âµs</li>' for c in row['captures'])
        cards.append(f'<article><section><h2>Image {number}</h2><p class="muted">Unreviewed Â· excluded from training</p></section><a href="{name}" target="_blank" rel="noopener"><img src="{name}" alt="Archived meter capture {number}" loading="lazy"></a><section><p>Tap the image to open its original size.</p><details><summary>Capture details ({len(row["captures"])})</summary><ul>{captures}</ul><p>SHA-256 <code>{row["image_sha256"]}</code></p></details></section></article>')
    identity=''.join('<dt>'+esc(k.replace('_',' '))+'</dt><dd><code>'+esc(v)+'</code></dd>' for k,v in group['identity'].items())
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIEdge archive review</title><style>'+STYLE+'</style><main><header><h1>AIEdge archive review</h1><label>Theme <select aria-label="Theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label></header><p>Original archived images from one capture-settings group. No readings have been assigned.</p><p class="muted">Exact duplicates are combined. Similar images may still be present. This page does not change labels or training splits.</p><details><summary>Capture-settings group</summary><dl>'+identity+'</dl></details><p>'+f'Showing {offset+1}â€“{offset+len(selected)} of {len(group["images"])} unique images, ordered by image hash.'+'</p>'+''.join(cards)+'</main><script>'+SCRIPT+'</script></html>'
    notice=f'<p class="muted">Held-out protection window: {protect_window_seconds} seconds within the same device boot. This is not visual near-duplicate detection.</p>'
    missing=len(review['protected_hashes_without_capture_records'])
    if missing:notice+=f'<p>{missing} protected image hashes have no capture records here. Their neighboring captures cannot be excluded by time.</p>'
    page=page.replace('</header>','</header>'+notice,1)
    output.mkdir(parents=True,exist_ok=False)
    for name,data in blobs:
        with (output/name).open('xb') as f:f.write(data)
    manifest=dict(version=1,group_id=group_id,identity=group['identity'],images=selected,protected_manifest_sha256=review['protected_manifest_sha256'],protect_window_seconds=review['protect_window_seconds'],protected_hashes_without_capture_records=review['protected_hashes_without_capture_records'],training_eligible=False,limits=review['limits'])
    (output/'review.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'index.html').write_text(page,encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path)
    p.add_argument('--protected-hashes',type=Path,required=True);p.add_argument('--group',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=6)
    p.add_argument('--protect-window-seconds',type=int,default=300)
    a=p.parse_args()
    try:build(a.archive,a.protected_hashes,a.group,a.output,a.offset,a.limit,a.protect_window_seconds)
    except (ValueError,OSError) as exc:p.exit(2,str(exc)+'\n')
    print(str(a.output/'index.html'))
if __name__=='__main__':main()
