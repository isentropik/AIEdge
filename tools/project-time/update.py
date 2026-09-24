"""Approximate project activity from explicitly selected local Codex transcripts.
No conversation text or local paths are written to the public report.
"""
import argparse,datetime as dt,json,math
from pathlib import Path

def merge(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if end<=start:continue
        if merged and start<=merged[-1][1]:merged[-1][1]=max(end,merged[-1][1])
        else:merged.append([start,end])
    return merged

def active_intervals(points,max_gap=300):
    points=sorted(set(points))
    return [(a,b) for a,b in zip(points,points[1:]) if 0<b-a<=max_gap]

def timestamp(value):return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--session',action='append',type=Path,required=True);ap.add_argument('--after',required=True);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--max-gap',type=int,default=300);args=ap.parse_args()
    cutoff=timestamp(args.after);intervals=[];last=cutoff;sources=0
    for path in args.session:
        points=[]
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:r=json.loads(line)
                except json.JSONDecodeError:continue # In-progress final record may be incomplete.
                if r.get('type') not in ('response_item','event_msg','turn_context'):continue
                if r.get('type')=='event_msg' and r.get('payload',{}).get('type') not in ('task_started','task_complete'):continue
                try:t=timestamp(r['timestamp'])
                except (KeyError,ValueError):continue
                if t>=cutoff:points.append(t)
        if points:sources+=1;last=max(last,max(points))
        intervals.extend(active_intervals(points,args.max_gap))
    merged=merge(intervals);seconds=sum(b-a for a,b in merged)
    result={'approximate_hours':math.floor(seconds/3600+.5),'as_of_utc':dt.datetime.fromtimestamp(last,dt.timezone.utc).isoformat(),'included_since_utc':args.after,'source_chat_count':sources,'method':'Union of within-chat gaps between recorded activity events of at most '+str(args.max_gap)+' seconds. Longer gaps excluded; overlapping chats counted once. Rounded to nearest hour.','limitations':['Approximate shared project activity, not human labor hours or model compute time.','Long builds or thinking gaps can be undercounted; short waits can be counted.','Only explicitly selected project chats included; earlier unrelated Home Assistant work excluded.','No claim that all historical work is recoverable.']}
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
