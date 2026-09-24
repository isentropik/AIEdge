"""Read-only custom-firmware telemetry trial. Never triggers captures or settings.

Only GET /cycle_timing is requested. No redirects or environment proxies.
Credentials, if needed: METER_TRIAL_USER and METER_TRIAL_PASSWORD environment vars.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from analyze_cycle_trial import analyze, distribution

MAX_BODY = 65536
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def endpoint(base):
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTP(S) device origin without embedded credentials')
    if parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('Use only the device origin; path is fixed to /cycle_timing')
    if any(ord(c)<33 for c in base):
        raise ValueError('Invalid origin')
    return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'/cycle_timing','',''))

def get(url, timeout, authorization=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request = urllib.request.Request(url, headers={'Accept':'application/json','Cache-Control':'no-cache'})
    if authorization:request.add_header('Authorization',authorization)
    try:
        with opener.open(request,timeout=timeout) as response:
            return response.status,response.read(MAX_BODY+1)
    except urllib.error.HTTPError as error:
        with error:
            return error.code,error.read(MAX_BODY+1)

def collect(base, output, samples=60, interval=10, timeout=3, *, fetch=get,
            monotonic=time.monotonic, sleep=time.sleep, authorization=None):
    url=endpoint(base)
    if type(samples) is not int or not 1<=samples<=720:
        raise ValueError('Samples must be 1..720')
    if not math.isfinite(interval) or not 5<=interval<=60 or not math.isfinite(timeout) or not 0<timeout<=10:
        raise ValueError('Interval must be 5..60 seconds; socket timeout >0 and <=10')
    output=Path(output);output.mkdir(parents=False,exist_ok=False)
    records=[];boots={};failure_streak=0;skipped_poll_slots=0
    due=monotonic()
    for index in range(samples):
        sleep(max(0,due-monotonic()))
        started=monotonic()
        record={'sample':index,'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
                'capture_time':False,'success':False}
        try:
            status,body=fetch(url,timeout,authorization)
            path=output/f'{index:04d}.response'
            path.write_bytes(body)
            record.update(http_status=status,response_file=path.name,
                          sha256=hashlib.sha256(body).hexdigest(),bytes=len(body))
            if status!=200:raise ValueError('http_status_'+str(status))
            if len(body)>MAX_BODY:raise ValueError('body_limit_exceeded')
            snapshot=json.loads(body)
            # Validate each sample before including it in any aggregate.
            single=analyze({'snapshots':[snapshot]})
            if single['boot_continuity_evidence']!='firmware_boot_id':
                raise ValueError('firmware_boot_identity_required')
            boots.setdefault(snapshot['boot_id'],[]).append(snapshot)
            record.update(success=True,boot_id=snapshot['boot_id'])
            failure_streak=0
        except Exception as error:
            # Exception class only: network errors may include credential details.
            record['error_type']=type(error).__name__
            failure_streak+=1
        record['request_seconds']=max(0,monotonic()-started)
        records.append(record)
        with (output/'requests.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps(record)+'\n');log.flush();os.fsync(log.fileno())
        if failure_streak>=3:break
        due+=interval
        now=monotonic()
        if due<now:
            skipped=math.ceil((now-due)/interval)
            skipped_poll_slots+=skipped;due+=skipped*interval
    reports={}
    for boot,snapshots in boots.items():
        (output/f'{boot}.snapshots.json').write_text(json.dumps({'snapshots':snapshots},indent=2))
        try:reports[boot]=analyze({'snapshots':snapshots})
        except (ValueError,KeyError,TypeError) as error:
            reports[boot]={'invalid':True,'reason':str(error)}
    result={'requests':len(records),'successful_responses':sum(r['success'] for r in records),
        'failures':sum(not r['success'] for r in records),'consecutive_failure_stop':failure_streak>=3,
        'skipped_collector_poll_slots':skipped_poll_slots,
        'request_latency':distribution([r['request_seconds']*1e6 for r in records]),
        'boots':reports,'target_achieved':None,
        'limits':['Retrieval timestamps are not capture times','Socket timeout is an inactivity bound, not a hard total request deadline',
                  'Only telemetry is sampled; MQTT delivery and image accuracy are not verified']}
    (output/'summary.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=60)
    parser.add_argument('--interval',type=float,default=10)
    parser.add_argument('--timeout',type=float,default=3)
    args=parser.parse_args()
    user,password=os.getenv('METER_TRIAL_USER'),os.getenv('METER_TRIAL_PASSWORD')
    if (user is None)!=(password is None):parser.error('Set both credential environment variables, or neither')
    authorization=None if user is None else 'Basic '+base64.b64encode((user+':'+password).encode()).decode()
    print(json.dumps(collect(args.origin,args.output,args.samples,args.interval,args.timeout,authorization=authorization),indent=2))
