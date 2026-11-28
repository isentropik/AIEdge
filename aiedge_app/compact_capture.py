"""Quality-25 compact exposures and deferred, content-verified full originals."""
import hashlib
import http.client
import json
import os
import re
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image

from camera_status import unique_object
from capture import camera_header, now
from capture_recovery import BodyTimeout
from durable_file import sync_directory

FRAME_SIZE = (640, 480)
LIGHT_SETTLE_SECONDS = 2.5
CHUNK = 1024
PACKET_LIMIT = 32768
ORIGINAL_LIMIT = 262144
REPLAY_CHUNK = 2048
REPLAY_IDLE_SECONDS = 2
COMPACT_CYCLE_SECONDS = 30
EMPTY_QUEUE_RECHECK_SECONDS = 60
# Leave room for the camera to commit its queue cursor before replying.
# Both the idle and light-settling workers can offer this within their existing limits.
ACK_MIN_SECONDS = 1.25


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def calibrated_regions(document, fine_index):
    """Pad the saved dial crop and alignment boxes within the native image."""
    width, height = document['image_size']

    def padded(box, margin):
        x, y, w, h = box
        return [max(0, x-margin), max(0, y-margin),
                min(width, x+w+margin), min(height, y+h+margin)]

    fine = padded(document['dials'][fine_index]['crop'], 8)
    return [fine, *(padded(marker['box'], 16) for marker in document['markers'])]


def decode(packet, expected, *, reader=None, fine_index=None):
    if not 4 < len(packet) <= PACKET_LIMIT or digest(packet) != expected:
        raise ValueError('compact_packet_integrity')
    length, = struct.unpack('>I',packet[:4])
    if not 0 < length <= min(4092,len(packet)-4):
        raise ValueError('compact_header_length')
    m = json.loads(packet[4:4+length],object_pairs_hook=unique_object)
    tick = m['monotonic_us']
    if (type(m['version']) is not int or m['version'] != 1 or m['mode'] != 'fine' or
            type(m['source_bytes']) is not int or not 4 <= m['source_bytes'] <= ORIGINAL_LIMIT or
            not sha(m['profile']) or type(tick) is not int or not 0 < tick < 2**63 or
            type(m['sequence']) is not int or m['sequence'] != tick or
            not re.fullmatch('[0-9a-f]{32}',m['clock']) or
            m['frame_id'] != f"{m['clock']}-{tick:x}" or not sha(m['source_sha256'])):
        raise ValueError('compact_exposure_identity')
    stamp = datetime.fromisoformat(m['captured_at'])
    if stamp.utcoffset() is None or stamp.year < 2020 or stamp.timestamp() > time.time()+60:
        raise ValueError('invalid_capture_time')
    parts = m['parts']
    if not isinstance(parts, list) or len(parts) != 4:
        raise ValueError('compact_geometry')
    boxes = [p.get('box') if isinstance(p, dict) else None for p in parts]
    for box in boxes:
        if (not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box)
                or not 0 <= box[0] < box[2] <= FRAME_SIZE[0]
                or not 0 <= box[1] < box[3] <= FRAME_SIZE[1]):
            raise ValueError('compact_geometry')
    # Historical previews and orphan-original receipts have no active reader.
    # Only a packet matching the current local calibration can enter recognition.
    if reader is not None:
        if reader.profile != m['profile'] or reader.runtime is None:
            raise ValueError('compact_calibration_changed')
        if boxes != calibrated_regions(reader.runtime.document, fine_index):
            raise ValueError('compact_geometry')
    pos = 4+length
    canvas = Image.new('RGB',(640,480))
    for part,(x,y,r,b) in zip(parts,boxes):
        size = part['size']
        if type(size) is not int or not 0 < size <= len(packet)-pos:
            raise ValueError('compact_part_length')
        data = packet[pos:pos+size]
        pos += size
        if digest(data) != part['sha256']:
            raise ValueError('compact_part_integrity')
        with Image.open(BytesIO(data)) as tile:
            if tile.format != 'JPEG' or tile.size != (r-x,b-y):
                raise ValueError('compact_part_geometry')
            canvas.paste(tile.convert('RGB'),(x,y))
    if pos != len(packet):
        raise ValueError('compact_trailing_bytes')
    return m,canvas


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS compact_exposures('
               'event_id INTEGER PRIMARY KEY,packet_sha TEXT NOT NULL,packet BLOB NOT NULL,'
               'original_sha TEXT NOT NULL,anchor INTEGER NOT NULL,pipeline TEXT NOT NULL,'
               'fine_index INTEGER NOT NULL,result TEXT NOT NULL,result_sha TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS original_download('
               'camera TEXT PRIMARY KEY,sequence INTEGER NOT NULL,sha TEXT NOT NULL,'
               'size INTEGER NOT NULL,body BLOB NOT NULL,frame TEXT NOT NULL,proof_sha TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS original_proofs(camera TEXT,seq INTEGER,packet BLOB NOT NULL,'
               'PRIMARY KEY(camera,seq))')
    db.execute('CREATE TABLE IF NOT EXISTS original_receipts(camera TEXT,seq INTEGER,frame TEXT,sha TEXT,'
               'size INTEGER,proof_sha TEXT,event_id INTEGER,PRIMARY KEY(camera,seq))')
    db.execute('CREATE INDEX IF NOT EXISTS original_receipts_event ON original_receipts(camera,event_id)')


class PartialCompact(BodyTimeout):
    """The camera advertised a retained packet before the capture response broke."""
    def __init__(self, evidence, headers, prefix, *, reset):
        super().__init__(evidence, reset=reset)
        self.headers = headers
        self.prefix = prefix


class OriginalWindowEnded(TimeoutError):
    """The next queue request did not start before capture reclaimed its time."""


def request(camera,path,*,headers=None,body=None,deadline,limit,timing=None):
    values = dict(headers or {})
    if camera.token:
        values['Authorization']='Bearer '+camera.token
    elif camera.basic:
        values['Authorization']='Basic '+camera.basic
    req = urllib.request.Request(camera.origin+path,headers=values,data=body)
    req.aiedge_deadline = deadline
    req.aiedge_timing = timing
    remaining = deadline-time.monotonic()
    if path=='/api/v1/original/ack' and remaining<ACK_MIN_SECONDS:
        raise OriginalWindowEnded()
    if remaining <= 0:
        if path in ('/api/v1/original','/api/v1/original/ack'):
            raise OriginalWindowEnded()
        raise TimeoutError('compact_deadline')
    with camera.opener.open(req,timeout=remaining) as reply:
        if timing is not None:
            timing['headers_at']=time.monotonic()
            timing['headers_utc']=now()
            if path=='/api/v1/original' and reply.status==200:
                seq=reply.headers.get('X-AIEdge-Sequence','')
                frame=reply.headers.get('X-AIEdge-Frame-Id','')
                if re.fullmatch('[0-9]{1,20}',seq):
                    timing['response_sequence']=int(seq)
                if re.fullmatch('[a-f0-9]{32}-[a-f0-9]{1,16}',frame):
                    timing['response_frame_id']=frame
        if reply.status == 204:
            return None,None
        n = camera_header(reply.headers,'Content-Length')
        if reply.status != 200 or not re.fullmatch('[1-9][0-9]{0,5}',n) or int(n)>limit:
            raise ValueError('compact_response_length')
        expected=int(n)
        if path=='/api/v1/compact':
            packet_sha=camera_header(reply.headers,'X-AIEdge-SHA256')
            if camera_header(reply.headers,'Content-Type')!='application/x-aiedge-q25' or not sha(packet_sha):
                raise ValueError('compact_response_metadata')
            replay = camera_header(reply.headers, 'X-AIEdge-Compact-Replay') == '1'
            set_deadline = getattr(reply, 'set_body_deadline', None) if replay else None
            data=bytearray()
            try:
                while len(data)<expected:
                    if set_deadline:
                        set_deadline(min(deadline, time.monotonic()+REPLAY_IDLE_SECONDS))
                    block=reply.read1(expected-len(data))
                    if not block:raise ConnectionResetError('compact body ended early')
                    data.extend(block)
            except (TimeoutError,ConnectionError,http.client.IncompleteRead) as exc:
                evidence = dict(stage='compact_body', expected_bytes=expected, received_bytes=len(data),
                                expected_sha256=packet_sha)
                reset = isinstance(exc, ConnectionError)
                if replay:
                    raise PartialCompact(evidence, reply.headers, bytes(data), reset=reset) from exc
                failure = BodyTimeout(evidence, reset=reset)
                failure.replay = ('not_advertised',len(data),0)
                raise failure from exc
            return reply.headers,bytes(data)
        data=reply.read(expected)
        if len(data)!=expected:
            raise http.client.IncompleteRead(data,expected-len(data))
        return reply.headers,data


def resume_compact(camera, partial, deadline):
    expected = partial.evidence['expected_bytes']
    packet_sha = partial.evidence['expected_sha256']
    data = bytearray(partial.prefix)
    requests = 0
    failures = 0
    reason = 'deadline'
    while len(data) < expected:
        start = time.monotonic()
        if start >= deadline:
            partial.replay = (reason,len(data),requests)
            raise partial
        offset = str(len(data))
        length = min(REPLAY_CHUNK, expected - len(data))
        requests += 1
        # One slow GET must leave time for another read of the identical offset.
        part_deadline = min(deadline, start + min(4 + 2*failures, 8))
        try:
            headers, chunk = request(camera, '/api/v1/compact/part', deadline=part_deadline, limit=length,
                                     headers={'X-AIEdge-SHA256': packet_sha, 'X-AIEdge-Offset': offset})
            if (headers is None or len(chunk) != length or
                    camera_header(headers, 'Content-Type') != 'application/octet-stream' or
                    camera_header(headers, 'X-AIEdge-SHA256') != packet_sha or
                    camera_header(headers, 'X-AIEdge-Size') != str(expected) or
                    camera_header(headers, 'X-AIEdge-Offset') != offset):
                raise ValueError('compact_replay_metadata')
        except (OSError,http.client.HTTPException,ValueError) as exc:
            cause = exc.reason if isinstance(exc,urllib.error.URLError) else exc
            if isinstance(exc,urllib.error.HTTPError):
                reason = f'http_{exc.code}'
                exc.close()
                retry = exc.code in (408,502,503,504)
            elif isinstance(cause,(TimeoutError,ConnectionError,http.client.IncompleteRead)):
                reason = ('timeout' if isinstance(cause,TimeoutError) else
                          'short_body' if isinstance(cause,http.client.IncompleteRead) else 'connection_error')
                retry = True
            else:
                reason = 'invalid_response' if isinstance(exc,ValueError) else 'transport_error'
                retry = False
            if not retry:
                partial.replay = (reason,len(data),requests)
                raise partial from exc
            time.sleep(min(.25*2**min(failures,4),max(0,deadline-time.monotonic())))
            failures += 1
            continue
        data.extend(chunk)
        failures = 0
        reason = 'deadline'
    if digest(data) != packet_sha:
        partial.replay = ('digest_mismatch',len(data),requests)
        raise partial
    return bytes(data)


def fine_read(reader,canvas,index,source,packet_sha):
    mask=[i==index for i in range(len(reader.dials))]
    result=reader.read_rgb(canvas.tobytes(),observed=mask)
    result.pop('_observed_mask',None)
    result.update(source_sha256=source,pipeline_id=reader.pipeline_id,compact_packet_sha256=packet_sha,
                  accuracy_verified=False,training_allowed=False)
    proof=dict(schema_version=1,source_sha256=source,pipeline_id=reader.pipeline_id)
    if result['state']=='estimated':
        result['observation_support']={**proof,'observed':mask}
    else:
        result['observation_attempt']={**proof,'requested_observed':mask}
    return result


class CompactCapture:
    def __init__(self,store,camera,recognition):
        self.store,self.camera,self.recognition=store,camera,recognition
        self.force_anchor=True
        self.download_issue=None
        self.confirmed_ack_head=None
        self.nominal_slot=None
        self.timing=None
        self.previous_exchange_seconds=0
        self.queue_recheck_at=0
        self.anchor_deferred=False
        self.original_pending=False
        with store.connect() as db:
            initialize(db)
            self.original_pending=bool(db.execute('SELECT 1 FROM original_download WHERE camera=?',(camera.origin,)).fetchone())

    def available(self,status):
        reader=self.recognition.reader
        return bool(status.get('q25') and getattr(reader,'runtime',None) is not None and
                    sha(reader.profile) and status.get('q25_profile') == reader.profile and
                    hasattr(self.recognition,'observation_context') and
                    self.recognition.document['dials'][-1]['index']==len(reader.dials)-1)

    def _while_settling(self,cancel,posted):
        # The camera handles acquisition in an async worker. Its HTTP server can
        # send a retained chunk during lighting, before the compact response is due.
        end=posted+LIGHT_SETTLE_SECONDS-.30
        if cancel.wait(.18):return
        while not cancel.is_set() and end-time.monotonic()>.80:
            try:
                if not self._advance_original(end):
                    return
            except OriginalWindowEnded:
                return
            except (OSError,ValueError,sqlite3.Error,http.client.HTTPException) as error:
                self._download_failed(error,'settling')
                return

    def collect(self,started,*,reserve_link=False,interval=None,phases=None):
        from capture_recovery import RequestTimeout,FreshnessRejected,TransientHTTPResponse,TRANSIENT_HTTP
        self.camera.require_capture()
        posted=time.monotonic()
        cancel=threading.Event()
        drain=None
        resumed_bytes=0
        reserve_link = reserve_link or (interval is not None and self.previous_exchange_seconds>=interval/2)
        if self.original_pending and (not reserve_link or self.anchor_deferred):
            drain=threading.Thread(target=self._while_settling,args=(cancel,posted),name='aiedge-original-chunk')
            drain.start()
        transport={}
        if phases is not None:
            phases['concurrent_original_worker']=drain is not None
        try:
            headers,data=request(self.camera,'/api/v1/compact',body=b'{}',
                headers={'Content-Type':'application/json','X-AIEdge-Anchor':str(int(self.force_anchor))},
                deadline=time.monotonic()+20,limit=PACKET_LIMIT,timing=transport)
        except PartialCompact as partial:
            data = resume_compact(self.camera, partial, posted + COMPACT_CYCLE_SECONDS)
            headers = partial.headers
            resumed_bytes = len(data) - len(partial.prefix)
        except urllib.error.HTTPError as e:
            with e:
                reason=e.read(257)
                if e.code==503 and reason==b'Frame is stale or clock changed during capture':
                    raise FreshnessRejected() from None
                if e.code in TRANSIENT_HTTP:
                    raise TransientHTTPResponse(e.code) from None
            raise
        except urllib.error.URLError as e:
            if isinstance(e.reason,(TimeoutError,ConnectionResetError)):
                raise RequestTimeout(reset=isinstance(e.reason,ConnectionResetError)) from e
            raise ValueError('camera_connection_failed') from e
        except (TimeoutError,ConnectionError,http.client.IncompleteRead) as e:
            raise RequestTimeout(reset=isinstance(e,ConnectionError)) from e
        finally:
            packet_end=time.monotonic()
            self.previous_exchange_seconds=packet_end-posted
            cancel.set()
            if drain is not None:drain.join()
            joined=time.monotonic()
            if phases is not None:
                phases['compact_exchange_s']=round(packet_end-posted,3)
                phases['original_join_s']=round(joined-packet_end,3)
                if 'connected_at' in transport:
                    phases['compact_tcp_ready_s']=round(transport['connected_at']-posted,3)
                if 'headers_at' in transport:
                    phases['compact_headers_s']=round(transport['headers_at']-posted,3)
                    phases['compact_body_including_replay_s']=round(packet_end-transport['headers_at'],3)
        if headers is None or camera_header(headers,'Content-Type')!='application/x-aiedge-q25':
            raise ValueError('compact_response_type')
        anchor=camera_header(headers,'X-AIEdge-Anchor')
        replay_available = camera_header(headers, 'X-AIEdge-Compact-Replay') == '1'
        if anchor not in ('0','1','deferred') or (self.force_anchor and anchor=='0'):
            raise ValueError('compact_anchor_unconfirmed')
        packet_sha=camera_header(headers,'X-AIEdge-SHA256')
        with self.recognition.lock:
            reader=self.recognition.reader
            index=self.recognition.document['dials'][-1]['index']
            if reader is None or index!=len(reader.dials)-1:
                raise ValueError('compact_calibration_changed')
            m,canvas=decode(data,packet_sha,reader=reader,fine_index=index)
            source=m['source_sha256']
            result=fine_read(reader,canvas,index,source,packet_sha)
        recognized=time.monotonic()
        encoded=json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)
        stamp=datetime.fromisoformat(m['captured_at']).astimezone(timezone.utc).isoformat()
        key=(self.camera.origin,m['frame_id'])
        with self.store.lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM frames WHERE camera=? AND frame_id=?',key).fetchone():
                return False
            self.store.require_space(len(data)+len(encoded))
            db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?,0)',(*key,stamp,now(),source,m['source_bytes']))
            eid=db.execute('INSERT INTO capture_events(camera,frame_id) VALUES(?,?)',key).lastrowid
            db.execute('INSERT INTO capture_clocks VALUES(?,?,?,?)',(*key,m['clock'],m['monotonic_us']))
            db.execute('INSERT INTO compact_exposures VALUES(?,?,?,?,?,?,?,?,?)',(eid,packet_sha,data,source,
                       int(anchor=='1'),reader.pipeline_id,index,encoded,digest(encoded.encode())))
        self.store.performance.admit(eid,source,started)
        verified=time.monotonic()
        if phases is not None:
            phases.update(packet_bytes=len(data),replayed_bytes=resumed_bytes,
                          join_end_to_recognition_s=round(recognized-joined,3),
                          recognition_end_to_store_s=round(verified-recognized,3))
            phases.update(event_id=eid,exposure_utc=stamp,original_retained=anchor=='1')
            if 'headers_utc' in transport:
                phases['compact_headers_utc']=transport['headers_utc']
        self.timing={'request_to_observation_seconds':round(verified-posted,3),
                     'scheduled_slot_to_observation_seconds':round(verified-self.nominal_slot,3) if self.nominal_slot is not None else None,
                     'observed':result['state']=='estimated','original_retained':anchor=='1',
                     'compact_replay_available': replay_available}
        if resumed_bytes:
            self.timing['compact_bytes_recovered'] = resumed_bytes
        self.anchor_deferred=anchor=='deferred'
        self.original_pending=self.original_pending or anchor!='0'
        self.force_anchor=anchor=='deferred' or result['state']!='estimated'
        return True

    @property
    def download_error(self):
        issue=self.download_issue
        return issue['error'] if issue else None

    def _original_request(self,operation,deadline,row=None,*,offset=None,headers=None,body=None):
        path='/api/v1/original/ack' if operation=='ack' else '/api/v1/original'
        timing={}
        start=time.monotonic()
        try:
            return request(self.camera,path,deadline=deadline,headers=headers,body=body,
                           limit=2 if body is not None else CHUNK,timing=timing)
        except OriginalWindowEnded:
            raise
        except (OSError,ValueError,http.client.HTTPException) as error:
            phase='connect'
            if isinstance(error,urllib.error.HTTPError):
                phase='http_response'
            elif 'headers_at' in timing:
                phase='response_body'
            elif 'request_sent_at' in timing:
                phase='waiting_for_headers'
            elif 'connected_at' in timing:
                phase='before_request_sent'
            error.original_request=dict(operation=operation,method='POST' if body is not None else 'GET',path=path,
                phase=phase,sequence=row[0] if row else None,frame_id=row[4] if row else None,offset=offset,
                budget_ms=round(max(0,deadline-start)*1000),elapsed_ms=round((time.monotonic()-start)*1000))
            for field in ('connected_at','request_sent_at','headers_at'):
                if field in timing:error.original_request[field.removesuffix('_at')+'_ms']=round((timing[field]-start)*1000)
            for field in ('response_sequence','response_frame_id'):
                if field in timing:error.original_request[field]=timing[field]
            if isinstance(error,urllib.error.HTTPError):error.original_request['http_status']=error.code
            raise

    def _download_failed(self,error,worker):
        cause=error.reason if isinstance(error,urllib.error.URLError) and isinstance(error.reason,Exception) else error
        issue=dict(at=now(),worker=worker,error=type(error).__name__,cause=type(cause).__name__,
                   **getattr(error,'original_request',{'operation':'local'}))
        self.download_issue=issue
        self._log_original('original_download_failure',**issue)

    @staticmethod
    def _log_original(event,**fields):
        from lifecycle import lifecycle_event
        try:
            lifecycle_event(event,**fields)
        except OSError:
            pass  # A closed journal must not affect capture or retry.

    def _advance_original(self,deadline):
        progressed=self.download(deadline)
        self.original_pending=progressed
        if not progressed:
            self.queue_recheck_at=time.monotonic()+EMPTY_QUEUE_RECHECK_SECONDS
        self.download_issue=None
        return progressed

    def _proof(self,row,deadline):
        """Recover proof for an orphan original without adding an observation across the gap."""
        seq,source,total,_,frame,packet_sha=row
        camera=self.camera.origin
        with self.store.connect() as db:
            previous=db.execute('SELECT packet FROM original_proofs WHERE camera=? AND seq=?',(camera,seq)).fetchone()
        packet=previous[0] if previous else b''
        if packet and digest(packet)==packet_sha:
            meta,_=decode(packet,packet_sha)
            if (meta['frame_id'],meta['source_sha256'],meta['source_bytes'])!=(frame,source,total):
                raise ValueError('original_proof_conflict')
            return True
        offset=len(packet)
        hdr={'X-AIEdge-Offset':str(offset),'X-AIEdge-Original':source,'X-AIEdge-Part':'proof'}
        headers,data=self._original_request('proof',deadline,row,offset=offset,headers=hdr)
        if headers is None:raise ValueError('original_proof_missing')
        length=int(camera_header(headers,'X-AIEdge-Size'))
        if (not 4<length<=PACKET_LIMIT or not 0<=offset<length or len(data)!=min(CHUNK,length-offset) or
                (frame,packet_sha,source,str(seq),str(offset),digest(data))!=tuple(
                    camera_header(headers,'X-AIEdge-'+key) for key in ('Frame-Id','Proof','Original','Sequence','Offset','SHA256'))):
            raise ValueError('original_proof_chunk_invalid')
        packet+=data
        if len(packet)==length:
            meta,_=decode(packet,packet_sha)
            if (meta['frame_id'],meta['source_sha256'],meta['source_bytes'])!=(frame,source,total):
                raise ValueError('original_proof_conflict')
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO original_proofs VALUES(?,?,?)',(camera,seq,packet))
        return len(packet)==length

    def _receipt(self,row,deadline):
        camera=self.camera.origin
        seq,source,total,buf,frame,packet_sha=row
        with self.store.connect() as db:
            done=db.execute('SELECT frame,sha,size,proof_sha FROM original_receipts WHERE camera=? AND seq=?',
                            (camera,seq)).fetchone()
            match=db.execute('SELECT e.event_id,f.sha256,f.bytes,c.packet_sha FROM capture_events e '
                             'JOIN frames f USING(camera,frame_id) JOIN compact_exposures c ON c.event_id=e.event_id '
                             'WHERE e.camera=? AND e.frame_id=?',(camera,frame)).fetchone()
        if done and done!=(frame,source,total,packet_sha):
            raise ValueError('original_receipt_identity_changed')
        if done:return True
        if match and match[1:]!=(source,total,packet_sha):
            raise ValueError('original_exposure_conflict')
        if not match and not self._proof(row,deadline):
            return False
        if digest(buf)!=source:
            raise ValueError('original_image_integrity')
        with Image.open(BytesIO(buf)) as im:
            if im.format!='JPEG' or im.size!=(640,480):
                raise ValueError('original_image_geometry')
            im.load()
        with self.store.lock:
            folder=self.store.root/('images' if match else 'original-recovery')
            folder.mkdir(exist_ok=True);sync_directory(folder.parent)
            temp=folder/(uuid.uuid4().hex+'.tmp')
            try:
                with temp.open('xb') as f:
                    f.write(buf);f.flush();os.fsync(f.fileno())
                os.replace(temp,folder/(source+'.jpg'))
                sync_directory(folder)
            finally:
                temp.unlink(missing_ok=True)
            with self.store.connect() as db:
                if match:
                    db.execute('DELETE FROM retired_images WHERE sha256=?',(source,))
                db.execute('INSERT INTO original_receipts VALUES(?,?,?,?,?,?,?)',
                           (camera,seq,frame,source,total,packet_sha,match[0] if match else None))
        return True

    def _acknowledge_saved(self,row,deadline):
        seq,source,size,_,frame,proof=row
        identity=(seq,source,size,frame,proof)
        observed_seq=None
        if self.confirmed_ack_head!=identity:
            self.confirmed_ack_head=None
            headers,_=self._original_request('receipt_head',deadline,row,offset=0,headers={'X-AIEdge-Offset':'0'})
            if headers is None:
                outcome='queue_empty_before_post'
            else:
                number=camera_header(headers,'X-AIEdge-Sequence')
                if not re.fullmatch('[1-9][0-9]{0,18}',number) or int(number)>=2**63:
                    raise ValueError('original_head_sequence_invalid')
                observed_seq=int(number)
                if observed_seq==seq:
                    if tuple(camera_header(headers,'X-AIEdge-'+k) for k in ('Original','Frame-Id','Proof'))!=(source,frame,proof):
                        raise ValueError('original_head_identity_changed')
                    self.confirmed_ack_head=identity
                else:
                    outcome='queue_head_changed_before_post'
        if self.confirmed_ack_head==identity:
            # The camera also compares seq and digest atomically before removal.
            # Cache the head only across a pre-dispatch yield. Every attempted POST
            # consumes this check, including timeouts, conflicts and malformed replies.
            self.confirmed_ack_head=None
            try:
                _,reply=self._original_request('ack',deadline,row,body=f'{seq} {source} 0'.encode())
            except OriginalWindowEnded:
                self.confirmed_ack_head=identity
                raise
            if reply!=b'OK':raise ValueError('original_receipt_unconfirmed')
            outcome='camera_replied_ok'
            observed_seq=seq
        with self.store.connect() as db:
            db.execute('DELETE FROM original_download WHERE camera=? AND sequence=? AND sha=?',(self.camera.origin,seq,source))
        self._log_original('original_ack_resolution',at=now(),sequence=seq,frame_id=frame,
                           outcome=outcome,observed_sequence=observed_seq)

    def download(self,deadline):
        camera=self.camera.origin
        with self.store.connect() as db:
            row=db.execute('SELECT sequence,sha,size,body,frame,proof_sha FROM original_download WHERE camera=?',
                           (camera,)).fetchone()
        offset=len(row[3]) if row else 0
        if row and offset==row[2]:
            if self._receipt(row,deadline):
                self._acknowledge_saved(row,deadline)
            return True
        hdr={'X-AIEdge-Offset':str(offset)}
        if row:hdr['X-AIEdge-Original']=row[1]
        headers,part=self._original_request('jpeg' if row else 'queue_head',deadline,row,offset=offset,headers=hdr)
        if headers is None:
            if row:raise ValueError('original_disappeared')
            return False
        source=camera_header(headers,'X-AIEdge-Original')
        frame=camera_header(headers,'X-AIEdge-Frame-Id')
        packet_sha=camera_header(headers,'X-AIEdge-Proof')
        seq=int(camera_header(headers,'X-AIEdge-Sequence'))
        total=int(camera_header(headers,'X-AIEdge-Size'))
        if (not sha(source) or not sha(packet_sha) or not re.fullmatch('[a-f0-9]{32}-[a-f0-9]{1,16}',frame) or
                not 0<seq<2**63 or not 0<total<=ORIGINAL_LIMIT or
                camera_header(headers,'X-AIEdge-Offset')!=str(offset) or
                len(part)!=min(CHUNK,total-offset) or digest(part)!=camera_header(headers,'X-AIEdge-SHA256') or
                (row and (row[:3]!=(seq,source,total) or row[4:]!=(frame,packet_sha)))):
            raise ValueError('original_chunk_integrity')
        buf=(row[3] if row else b'')+part
        self.store.require_space(total+PACKET_LIMIT)
        if len(buf)==total and digest(buf)!=source:
            with self.store.connect() as db:
                db.execute('DELETE FROM original_download WHERE camera=?',(camera,))
            raise ValueError('original_image_integrity')
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO original_download VALUES(?,?,?,?,?,?,?)',
                       (camera,seq,source,total,buf,frame,packet_sha))
        return True

    def idle(self,stop,due):
        # Acquisition and repair share one collector. Never start a chunk in the next exposure slot.
        if not self.original_pending and time.monotonic()<self.queue_recheck_at:
            return
        while not stop.is_set() and due-time.monotonic()>1.25:
            try:
                with self.camera.operation():
                    if not self._advance_original(min(due-.25,time.monotonic()+1.5)):
                        break
            except OriginalWindowEnded:
                # The per-step allowance can expire well before lighting is due.
                # Start a fresh step if the already-checked ACK still fits.
                if self.confirmed_ack_head is None or due-.25-time.monotonic()<ACK_MIN_SECONDS:
                    break
            except (OSError,ValueError,sqlite3.Error,http.client.HTTPException) as error:
                self._download_failed(error,'idle')
                break


def evidence(db,event):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='compact_exposures'").fetchone():
        return None
    return db.execute('SELECT packet_sha,original_sha,anchor,pipeline,fine_index,result,result_sha '
                      'FROM compact_exposures WHERE event_id=?',(event,)).fetchone()


def fine_mask(record,source,pipeline,count):
    if record[1]!=source or record[3]!=pipeline or not 0<=record[4]<count:
        raise ValueError('compact_observation_binding')
    return [i==record[4] for i in range(count)]


def saved_result(record):
    if digest(record[5].encode())!=record[6]:
        raise ValueError('compact_observation_integrity')
    result=json.loads(record[5])
    if result['source_sha256']!=record[1] or result['compact_packet_sha256']!=record[0] or result['pipeline_id']!=record[3]:
        raise ValueError('compact_observation_binding')
    return result


def preview(store,event):
    if not re.fullmatch('[1-9][0-9]{0,17}',event):
        raise ValueError('invalid_compact_exposure')
    with store.connect() as db:
        if not evidence(db,int(event)):
            raise FileNotFoundError(event)
        row=db.execute('SELECT c.packet,c.packet_sha,f.sha256,e.frame_id FROM compact_exposures c '
                       'JOIN capture_events e USING(event_id) JOIN frames f USING(camera,frame_id) '
                       'WHERE c.event_id=?',(int(event),)).fetchone()
    meta,canvas=decode(row[0],row[1])
    if (meta['source_sha256'],meta['frame_id'])!=row[2:]:
        raise ValueError('compact_preview_binding')
    output=BytesIO()
    canvas.crop(meta['parts'][0]['box']).save(output,format='PNG')
    return output.getvalue()
