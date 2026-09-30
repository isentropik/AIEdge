"""Durable relative consumption. Replays capture events; never fabricates turns."""
import hashlib,json,sqlite3,threading,uuid
from pathlib import Path
import capture_clock
from datetime import datetime
from accounting_native import AccountingNative
from recognition import decode_result,MAX_RESULT_BYTES
from reading_format import validate,display_quantity,finite_number

MAX_RECORD_BYTES=65536
class SegmentChanged(Exception):pass

class Consumption:
    def __init__(self,store,recognition,formats,library):
        self.store,self.recognition,self.formats=store,recognition,formats
        self.native=AccountingNative(library)
        dependencies=('consumption.py','accounting_native.py','reading_format.py','capture_clock.py','recognition.py')
        contract={'native':self.native.identity,'sources':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in dependencies},'schema':1}
        self.engine=hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()
        self.stop=threading.Event();self.lock=threading.Lock();self.last_error=None;self.blocked=False
        self.tracker=None;self.segment=None;self.cursor=0;self.previous=None;self.anchor=None
        self.state={'state':'not_configured','value':None,'accuracy_verified':False,'training_allowed':False}
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS consumption_segments(segment_id TEXT PRIMARY KEY,format_id TEXT NOT NULL,engine_id TEXT NOT NULL,first_event INTEGER NOT NULL,gap_reason TEXT NOT NULL,document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS consumption_active(singleton INTEGER PRIMARY KEY CHECK(singleton=1),segment_id TEXT NOT NULL,FOREIGN KEY(segment_id) REFERENCES consumption_segments(segment_id))')
            db.execute('CREATE TABLE IF NOT EXISTS consumption_records(segment_id TEXT NOT NULL,event_id INTEGER NOT NULL,result TEXT NOT NULL,PRIMARY KEY(segment_id,event_id),FOREIGN KEY(segment_id) REFERENCES consumption_segments(segment_id),FOREIGN KEY(event_id) REFERENCES capture_events(event_id))')
            db.execute('SELECT segment_id,format_id,engine_id,first_event,gap_reason,document FROM consumption_segments LIMIT 0')
            db.execute('SELECT singleton,segment_id FROM consumption_active LIMIT 0')
            db.execute('SELECT segment_id,event_id,result FROM consumption_records LIMIT 0')
    def _drop(self):
        if self.tracker:self.tracker.close()
        self.tracker=None;self.segment=None;self.previous=None;self.anchor=None
    def _activate(self,segment,document):
        tracker=self.native.tracker(document)
        self._drop();self.tracker=tracker;self.segment=segment;self.document=document
        self.cursor=segment['first_event']-1
        self.state={'state':'recovering','value':None,'segment_id':segment['segment_id'],
                    'accuracy_verified':False,'training_allowed':False}
    def _create(self,identity,document,first,gap,expected):
        segment={'segment_id':uuid.uuid4().hex,'format_id':identity,'engine_id':self.engine,'first_event':first,'gap_reason':gap}
        tracker=self.native.tracker(document)
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                active=db.execute('SELECT segment_id FROM consumption_active WHERE singleton=1').fetchone()
                if (active[0] if active else None)!=expected:raise SegmentChanged()
                db.execute('INSERT INTO consumption_segments VALUES(?,?,?,?,?,?)',(*segment.values(),json.dumps(document,sort_keys=True,allow_nan=False)))
                db.execute('INSERT INTO consumption_active VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET segment_id=excluded.segment_id',(segment['segment_id'],))
        except Exception:tracker.close();raise
        self._drop();self.tracker=tracker;self.segment=segment;self.document=document;self.cursor=first-1
        self.state={'state':'recovering','value':None,'segment_id':segment['segment_id'],'accuracy_verified':False,'training_allowed':False}
    def _prepare(self,identity,document):
        with self.store.connect() as db:
            row=db.execute('SELECT s.segment_id,s.format_id,s.engine_id,s.first_event,s.gap_reason,CASE WHEN length(CAST(s.document AS BLOB))<=? THEN s.document ELSE NULL END FROM consumption_active a JOIN consumption_segments s ON s.segment_id=a.segment_id WHERE a.singleton=1',(MAX_RECORD_BYTES,)).fetchone()
            if not row and db.execute('SELECT 1 FROM consumption_active LIMIT 1').fetchone():raise ValueError('consumption_saved_state_invalid')
            latest=db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]
        if row and self.segment and row[0]==self.segment['segment_id'] and row[1]==identity and row[2]==self.engine:return
        if row and row[1]==identity and row[2]==self.engine:
            saved,actual=validate(json.loads(row[5]))
            if actual!=identity or saved!=document or type(row[3]) is not int or row[3]<1 or row[3]>max(1,latest) or row[4] not in ('first_capture','interpretation_changed','capture_clock_changed','capture_clock_missing','capture_clock_invalid','capture_clock_not_increasing','capture_clock_utc_discontinuity','capture_camera_changed'):
                raise ValueError('consumption_saved_state_invalid')
            segment=dict(zip(('segment_id','format_id','engine_id','first_event','gap_reason'),row[:5]))
            self._activate(segment,document)
        else:self._create(identity,document,max(1,latest),'interpretation_changed' if row else 'first_capture',row[0] if row else None)
    @staticmethod
    def _clock_valid(current):
        try:
            tick=current['monotonic_us']
            if type(tick) is not int or not 0<=tick<=capture_clock.MAX_TICK:return False
            capture_clock.parse({capture_clock.CLOCK_HEADER:current['clock_id'],capture_clock.TICK_HEADER:str(tick)})
            stamp=datetime.fromisoformat(current['captured_at'].replace('Z','+00:00'))
            return stamp.tzinfo is not None and stamp.year>=2020
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):return False
    def _base(self,event,digest):
        return {'event_id':event,'source_sha256':digest,'format_id':self.segment['format_id'],
                'segment_id':self.segment['segment_id'],'unit':self.document['unit'],'value':None,
                'average_rate_per_second':None,'accuracy_verified':False,'training_allowed':False,
                'gap_reason':self.segment['gap_reason']}
    def once(self):
        # Calibration, physical interpretation, replay and persistence cannot mix.
        with self.recognition.lock,self.formats.lock,self.lock:
            reader=self.recognition.reader;active=self.formats.active
            if not reader or not active:
                self.state={'state':'not_configured','value':None,'accuracy_verified':False,'training_allowed':False};return False
            document,identity=active
            if document['pipeline_id']!=reader.pipeline_id:
                self.state={'state':'unavailable','reason':'reading_pipeline_changed','value':None,'accuracy_verified':False,'training_allowed':False};return False
            self._prepare(identity,document)
            with self.store.connect() as db:
                row=db.execute("""SELECT e.event_id,e.camera,f.captured_at,f.sha256,c.clock_id,c.monotonic_us,
                    CASE WHEN length(CAST(i.result AS BLOB))<=? THEN i.result ELSE NULL END,i.sha256
                    FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id
                    LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id
                    LEFT JOIN inference i ON i.sha256=f.sha256 AND i.pipeline=?
                    WHERE e.event_id>? ORDER BY e.event_id LIMIT 1""",(MAX_RESULT_BYTES,reader.pipeline_id,self.cursor)).fetchone()
                cached=db.execute('SELECT CASE WHEN length(CAST(result AS BLOB))<=? THEN result ELSE NULL END FROM consumption_records WHERE segment_id=? AND event_id=?',(MAX_RECORD_BYTES,self.segment['segment_id'],row[0])).fetchone() if row else None
            if not row:
                if self.state.get('state')=='recovering':self.state={**self.state,'state':'waiting_for_image'}
                return False
            event,camera,stamp,digest,clock,tick,encoded,inferred=row
            if inferred is None:
                self.state={**self._base(event,digest),'state':'pending','reason':'consumption_waiting_for_recognition'};return False
            current={'camera':camera,'captured_at':stamp,'clock_id':clock,'monotonic_us':tick}
            timing=capture_clock.interval(self.previous,current)
            # A gap starts a separate relative segment; never stitch two clocks.
            if self.anchor and timing['state']!='continuous':
                self._create(identity,document,event,timing['reason'],self.segment['segment_id']);cached=None
            output=self._base(event,digest)
            try:inference=decode_result(encoded,digest,reader.pipeline_id)
            except (ValueError,TypeError,RecursionError):inference={'state':'unavailable'}
            if inference.get('state')!='estimated':
                self.tracker.stale();output.update(state='unavailable',reason='consumption_image_rejected')
            elif clock is None or tick is None:
                self.tracker.stale();output.update(state='unavailable',reason='capture_clock_missing')
            elif not self._clock_valid(current):
                self.tracker.stale();output.update(state='unavailable',reason='capture_clock_invalid')
            else:
                rows=inference.get('dial_positions');indices=[d['index'] for d in document['dials']]
                if not isinstance(rows,list) or sorted(indices)!=list(range(len(rows))):
                    self.tracker.stale();output.update(state='unavailable',reason='reading_dial_mapping_mismatch')
                else:
                    positions=[rows[index].get('position') for index in indices]
                    if any(rows[index].get('state')!='estimated' or not finite_number(value) or not 0<=value<10 for index,value in zip(indices,positions)):
                        self.tracker.stale();output.update(state='unavailable',reason='dial_unavailable')
                    else:
                        native=self.tracker.observe(positions,tick,clock)
                        if not native['accepted']:output.update(state='unavailable',reason='consumption_positions_contradict_bounds')
                        else:
                            if self.anchor is None:self.anchor={'captured_at':stamp,'monotonic_us':tick,'camera':camera}
                            output.update({key:native[key] for key in ('state','minimum','maximum','value','upper_unbounded')})
                            output.update(anchor_captured_at=self.anchor['captured_at'],through_captured_at=stamp,
                                          elapsed_seconds=(native['through_us']-native['anchor_us'])/1e6)
                            if native['through_us']==native['anchor_us']:output.update(state='anchored',value=0)
                            if output['value'] is not None:
                                output['text']=display_quantity(output['value'],document,resolution_factor=2)
                                if output['elapsed_seconds']>0:
                                    rate=output['value']/output['elapsed_seconds']
                                    if finite_number(rate):output['average_rate_per_second']=rate
                                    ratio=60/output['elapsed_seconds'];lowest=document['dials'][-1]
                                    scaled=lowest['value_per_revolution']*ratio
                                    if finite_number(rate*60) and finite_number(scaled) and scaled>0:
                                        rate_document={'dials':[{**lowest,'value_per_revolution':scaled}]}
                                        output['average_rate_per_minute_text']=display_quantity(rate*60,rate_document,resolution_factor=2)
            encoded_output=json.dumps(output,sort_keys=True,separators=(',',':'),allow_nan=False)
            if len(encoded_output.encode())>MAX_RECORD_BYTES:raise ValueError('consumption_result_too_large')
            if cached and (cached[0] is None or json.loads(cached[0])!=output):raise ValueError('consumption_saved_result_invalid')
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                active_segment=db.execute('SELECT segment_id FROM consumption_active WHERE singleton=1').fetchone()
                if not active_segment or active_segment[0]!=self.segment['segment_id']:raise SegmentChanged()
                if not cached:
                    # A second worker may have written this event while native
                    # calculation ran. Accept only the identical durable decision.
                    prior=db.execute('SELECT CASE WHEN length(CAST(result AS BLOB))<=? THEN result ELSE NULL END FROM consumption_records WHERE segment_id=? AND event_id=?',(MAX_RECORD_BYTES,self.segment['segment_id'],event)).fetchone()
                    if prior:
                        if prior[0] is None or json.loads(prior[0])!=output:raise ValueError('consumption_saved_result_invalid')
                    else:db.execute('INSERT INTO consumption_records VALUES(?,?,?)',(self.segment['segment_id'],event,encoded_output))
            # State becomes public only after the durable decision is saved.
            self.previous=current;self.cursor=event;self.state=output;self.last_error=None
            return True
    def status(self):
        with self.recognition.lock,self.formats.lock,self.lock:
            reader=self.recognition.reader;configured=self.formats.active
            state=dict(self.state);cursor=self.cursor;error=self.last_error
            segment=self.segment['segment_id'] if self.segment else None
            if not reader or not configured:return {'state':'not_configured','value':None,'accuracy_verified':False,'training_allowed':False}
            if configured[0]['pipeline_id']!=reader.pipeline_id:return {'state':'unavailable','reason':'reading_pipeline_changed','value':None,'accuracy_verified':False,'training_allowed':False}
            if segment and self.segment['format_id']!=configured[1]:return {'state':'recovering','reason':'consumption_interpretation_changed','value':None,'accuracy_verified':False,'training_allowed':False}
        if error:return {'state':'unavailable','reason':error,'value':None,'accuracy_verified':False,'training_allowed':False}
        # Even identical JPEGs are different timing observations. Do not expose
        # a previous event's result as the latest capture's consumption.
        with self.store.connect() as db:
            latest=db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]
            active=db.execute('SELECT segment_id FROM consumption_active WHERE singleton=1').fetchone()
        if segment and (not active or active[0]!=segment):return {'state':'recovering','value':None,'accuracy_verified':False,'training_allowed':False}
        if latest>cursor and state.get('state') not in ('not_configured','unavailable','pending','recovering'):
            return {**state,'state':'pending','value':None,'text':None,'average_rate_per_second':None,'average_rate_per_minute_text':None,'reason':'consumption_waiting_for_latest_capture'}
        return state
    def run(self):
        try:
            while not self.stop.is_set():
                if self.blocked:self.stop.wait(5);continue
                try:
                    worked=self.once();self.last_error=None
                    if not worked:self.stop.wait(.5)
                except SegmentChanged:
                    with self.lock:self._drop()
                    self.stop.wait(.05)
                except (OSError,sqlite3.Error):
                    with self.lock:self._drop();self.last_error='consumption_storage_unavailable'
                    self.stop.wait(5)
                except (ValueError,TypeError,KeyError,RecursionError):
                    with self.lock:self._drop();self.last_error='consumption_saved_state_invalid';self.blocked=True
        finally:
            with self.lock:self._drop()
