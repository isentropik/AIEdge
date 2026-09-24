"""Save human dial labels as a separate review record; never enable training."""
import argparse,json,math,re
from datetime import datetime,timezone
from pathlib import Path
from audit_image_archive import read_bounded,unique_keys
from image_archive_store import digest
from prepare_training_review import prepare

def load(path):
 raw=read_bounded(Path(path),1024*1024)
 return raw,json.loads(raw,object_pairs_hook=unique_keys)

def record(archive,review_file,answers_file,protected_file,output):
 archive=Path(archive);output=Path(output);review_file=Path(review_file)
 if output.resolve().is_relative_to(archive.resolve()) or output.resolve().is_relative_to(review_file.parent.resolve()):
  raise ValueError('Label output must be outside the archive and original gallery')
 if output.exists():raise ValueError('Label output already exists')
 raw,review=load(review_file);answer_raw,answers=load(answers_file)
 required={'version','review_sha256','reviewer','method','dials','images'}
 if not isinstance(answers,dict) or set(answers)!=required or type(answers['version']) is not int or answers['version']!=1:
  raise ValueError('Expected version 1 human-label submission')
 if answers['review_sha256']!=digest(raw):raise ValueError('Submission does not match this review')
 if not isinstance(answers['reviewer'],str) or not 1<=len(answers['reviewer'].strip())<=100:raise ValueError('Reviewer required, maximum 100 characters')
 if answers['method'] not in ('independent_reading','confirmation_of_shown_estimate'):raise ValueError('Declare how readings were reviewed')
 dials=answers['dials']
 if not isinstance(dials,list) or not 1<=len(dials)<=16 or any(not isinstance(d,str) or not re.fullmatch('[a-zA-Z0-9_]{1,64}',d) for d in dials) or len(set(dials))!=len(dials):raise ValueError('Declare distinct dial names')
 if not isinstance(review,dict) or type(review.get('version')) is not int or review.get('version')!=1 or review.get('training_eligible') is not False:raise ValueError('Expected an unassigned gallery review')
 window=review.get('protect_window_seconds')
 current=prepare(archive,protected_file,window)
 groups=[g for g in current['groups'] if g['group_id']==review.get('group_id') and g['identity']==review.get('identity')]
 if len(groups)!=1:raise ValueError('Review group no longer available')
 eligible={r['image_sha256']:r for r in groups[0]['images']}
 originals=review.get('images')
 if not isinstance(originals,list) or not originals:raise ValueError('Review has no images')
 gallery={}
 for item in originals:
  if not isinstance(item,dict) or not isinstance(item.get('image_sha256'),str) or item.get('image_sha256') in gallery or eligible.get(item.get('image_sha256'))!=item:raise ValueError('Review changed, protected, or stale; export a new gallery')
  gallery[item['image_sha256']]=item
 images=answers['images']
 if not isinstance(images,list) or not images or len(images)>len(gallery):raise ValueError('Supply a nonempty subset of gallery images')
 seen=set();rows=[]
 for item in images:
  if not isinstance(item,dict) or set(item)!={'image_sha256','readings'}:raise ValueError('Invalid image submission')
  key=item['image_sha256']
  if not isinstance(key,str) or key not in gallery or key in seen:raise ValueError('Unknown or repeated image hash')
  seen.add(key);values=item['readings']
  if not isinstance(values,dict) or set(values)!=set(dials):raise ValueError('Each image must name every declared dial; use null for unknown')
  for v in values.values():
   if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<10):raise ValueError('Use finite 0–10 positions, below 10, or null')
  rows.append(dict(image_sha256=key,captures=gallery[key]['captures'],readings=values,split='unassigned',training_eligible=False))
 result=dict(version=1,recorded_at_utc=datetime.now(timezone.utc).isoformat(),review_sha256=digest(raw),submission_sha256=digest(answer_raw),protected_manifest_sha256=current['protected_manifest_sha256'],protect_window_seconds=window,identity=review['identity'],reviewer=answers['reviewer'],method=answers['method'],position_scale='0_to_10_in_each_dials_numbering',dials=dials,images=rows,training_eligible=False,limits=['Human statements are recorded, not automatically verified.','Unknown stays null. No split assignment or training admission.','Dial names and directions must be checked against calibration before any later use.','Recheck held-out and near-duplicate protections before training.'])
 with output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2,allow_nan=False)
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path)
 for name in ('review','answers','protected-hashes','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args()
 try:record(a.archive,a.review,a.answers,a.protected_hashes,a.output)
 except (ValueError,OSError,TypeError) as exc:p.exit(2,str(exc)+'\n')
 print('Human review saved; images remain excluded from training.')
if __name__=='__main__':main()
