"""Report consistency of explicitly selected 10:1 main dials; never relabel."""
import argparse,json,math,re
from pathlib import Path
from record_review_labels import load
from image_archive_store import digest

def audit(document, sequence, error):
 if type(error) not in (int,float) or not math.isfinite(error) or not 0<=error<.5:
  raise ValueError('Supply an explicit per-dial error assumption from 0 to below 0.5')
 if not isinstance(sequence,list) or not 2<=len(sequence)<=16 or any(not isinstance(x,str) for x in sequence) or len(set(sequence))!=len(sequence):
  raise ValueError('Select at least two distinct main dials in highest-to-lowest order')
 if not isinstance(document,dict) or type(document.get('version')) is not int or document['version']!=1 or document.get('training_eligible') is not False or document.get('position_scale')!='0_to_10_in_each_dials_numbering':
  raise ValueError('Expected an excluded version 1 human-label record on the 0-10 scale')
 if document.get('method') not in ('independent_reading','confirmation_of_shown_estimate'):raise ValueError('Human review method required')
 declared=document.get('dials')
 if not isinstance(declared,list) or any(x not in declared for x in sequence):raise ValueError('Sequence contains an undeclared dial')
 images=document.get('images')
 if not isinstance(images,list) or not images:raise ValueError('No image labels')
 rows=[];seen=set();bound=error*1.1
 for item in images:
  if not isinstance(item,dict):raise ValueError('Invalid image label')
  key=item.get('image_sha256');readings=item.get('readings')
  if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key) or key in seen:raise ValueError('Invalid or duplicate image hash')
  seen.add(key)
  if item.get('training_eligible') is not False or not isinstance(readings,dict) or any(x not in readings for x in sequence):raise ValueError('Invalid or missing readings')
  for name in sequence:
   value=readings[name]
   if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<10):raise ValueError('Invalid dial value')
  pairs=[]
  for high,low in zip(sequence,sequence[1:]):
   h,l=readings[high],readings[low];pair={'higher_dial':high,'following_dial':low,'higher_label':h,'following_label':l,'status':'unknown'}
   if h is not None and l is not None:
    # Nearest integer-turn branch; wrap around the 0/10 boundary.
    residual=(h-l/10+.5)%1-.5
    pair.update(status='review' if abs(residual)>bound+1e-12 else 'consistent_with_assumption',linked_position=(h-residual)%10,signed_residual=residual,allowed_residual=bound)
   pairs.append(pair)
  rows.append({'image_sha256':key,'pairs':pairs})
 return {'version':1,'sequence':sequence,'review_method':document['method'],'per_dial_error_assumption':error,'rows':rows,'training_eligible':False,'limits':['Only explicitly selected adjacent 10:1 main dials are compared; exclude secondary wheels with other gearing.','Labels must come from the same full image and already use each dial numbering direction.','Consistency is not proof of correct readings, calibration or mechanical registration.','Error is a supplied assumption, not measured uncertainty. Unknown stays unknown.','No labels, splits, raw images, firmware or training eligibility are changed.']}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('labels',type=Path);p.add_argument('--sequence',nargs='+',required=True);p.add_argument('--error',type=float,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 try:
  raw,doc=load(a.labels);result=audit(doc,a.sequence,a.error);result['label_record_sha256']=digest(raw)
  with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
 except (OSError,ValueError,TypeError) as e:p.exit(2,str(e)+'\n')
 print('Audit saved; consistency does not admit images to training.')
if __name__=='__main__':main()
