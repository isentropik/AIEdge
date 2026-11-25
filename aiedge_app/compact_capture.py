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
from durable_file import sync_directory

FRAME_SIZE = (640, 480)
LIGHT_SETTLE_SECONDS = 2.5
CHUNK = 1024
PACKET_LIMIT = 32768
ORIGINAL_LIMIT = 262144


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


def request(camera,path,*,headers=None,body=None,deadline,limit):
    values = dict(headers or {})
    if camera.token:
        values['Authorization']='Bearer '+camera.token
    elif camera.basic:
        values['Authorization']='Basic '+camera.basic
    req = urllib.request.Request(camera.origin+path,headers=values,data=body)
    req.aiedge_deadline = deadline
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError('compact_deadline')
    with camera.opener.open(req,timeout=remaining) as reply:
        if reply.status == 204:
            return None,None
        n = camera_header(reply.headers,'Content-Length')
        if reply.status != 200 or not re.fullmatch('[1-9][0-9]{0,5}',n) or int(n)>limit:
            raise ValueError('compact_response_length')
        expected=int(n)
        if path=='/api/v1/compact':
            from capture_recovery import BodyTimeout
            packet_sha=camera_header(reply.headers,'X-AIEdge-SHA256')
            if camera_header(reply.headers,'Content-Type')!='application/x-aiedge-q25' or not sha(packet_sha):
                raise ValueError('compact_response_metadata')
            data=bytearray()
            try:
                while len(data)<expected:
                    block=reply.read1(expected-len(data))
                    if not block:raise ConnectionResetError('compact body ended early')
                    data.extend(block)
            except (TimeoutError,ConnectionError,http.client.IncompleteRead) as exc:
                raise BodyTimeout(dict(stage='compact_body',expected_bytes=expected,received_bytes=len(data),
                                       expected_sha256=packet_sha),reset=isinstance(exc,ConnectionError)) from exc
            return reply.headers,bytes(data)
        data=reply.read(expected)
        if len(data)!=expected:
            raise http.client.IncompleteRead(data,expected-len(data))
        return reply.headers,data


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
        self.download_error=None
        self.nominal_slot=None
        self.timing=None
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
                if not self.download(end):
                    self.original_pending=False
                    return
            except (OSError,ValueError,sqlite3.Error,http.client.HTTPException) as error:
                self.download_error=type(error).__name__
                return

    def collect(self,started):
        from capture_recovery import RequestTimeout,FreshnessRejected,TransientHTTPResponse,TRANSIENT_HTTP
        self.camera.require_capture()
        posted=time.monotonic()
        cancel=threading.Event()
        drain=None
        if self.original_pending:
            drain=threading.Thread(target=self._while_settling,args=(cancel,posted),name='aiedge-original-chunk')
            drain.start()
        try:
            headers,data=request(self.camera,'/api/v1/compact',body=b'{}',
                headers={'Content-Type':'application/json','X-AIEdge-Anchor':str(int(self.force_anchor))},
                deadline=time.monotonic()+20,limit=PACKET_LIMIT)
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
            cancel.set()
            if drain is not None:drain.join()
        if headers is None or camera_header(headers,'Content-Type')!='application/x-aiedge-q25':
            raise ValueError('compact_response_type')
        anchor=camera_header(headers,'X-AIEdge-Anchor')
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
        self.timing={'request_to_observation_seconds':round(verified-posted,3),
                     'scheduled_slot_to_observation_seconds':round(verified-self.nominal_slot,3) if self.nominal_slot is not None else None,
                     'observed':result['state']=='estimated','original_retained':anchor=='1'}
        self.original_pending=self.original_pending or anchor=='1'
        self.force_anchor=anchor=='deferred' or result['state']!='estimated'
        return True

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
        headers,data=request(self.camera,'/api/v1/original',headers=hdr,deadline=deadline,limit=CHUNK)
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

    def download(self,deadline):
        camera=self.camera.origin
        with self.store.connect() as db:
            row=db.execute('SELECT sequence,sha,size,body,frame,proof_sha FROM original_download WHERE camera=?',
                           (camera,)).fetchone()
        offset=len(row[3]) if row else 0
        if row and offset==row[2]:
            if not self._receipt(row,deadline):
                return True
            # The file and identity-bound receipt survive a lost acknowledgement.
            headers,_=request(self.camera,'/api/v1/original',headers={'X-AIEdge-Offset':'0'},
                              deadline=deadline,limit=CHUNK)
            if headers is not None and camera_header(headers,'X-AIEdge-Sequence')==str(row[0]):
                if tuple(camera_header(headers,'X-AIEdge-'+k) for k in ('Original','Frame-Id','Proof'))!=(row[1],row[4],row[5]):
                    raise ValueError('original_head_identity_changed')
                _,reply=request(self.camera,'/api/v1/original/ack',body=f'{row[0]} {row[1]} 0'.encode(),
                                deadline=deadline,limit=2)
                if reply!=b'OK':raise ValueError('original_receipt_unconfirmed')
            with self.store.connect() as db:
                db.execute('DELETE FROM original_download WHERE camera=? AND sequence=? AND sha=?',(camera,*row[:2]))
            return True
        hdr={'X-AIEdge-Offset':str(offset)}
        if row:hdr['X-AIEdge-Original']=row[1]
        headers,part=request(self.camera,'/api/v1/original',headers=hdr,deadline=deadline,limit=CHUNK)
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
        while not stop.is_set() and due-time.monotonic()>1.25:
            try:
                with self.camera.operation():
                    if not self.download(min(due-.25,time.monotonic()+1.5)):
                        self.original_pending=False
                        break
                    self.original_pending=True
                self.download_error=None
            except (OSError,ValueError,sqlite3.Error,http.client.HTTPException) as error:
                self.download_error=type(error).__name__
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
