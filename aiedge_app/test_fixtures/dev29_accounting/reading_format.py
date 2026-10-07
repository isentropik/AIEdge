"""Explicit physical interpretation of one image; never infers consumption."""
import hashlib, json, math, re
from decimal import Decimal, localcontext, ROUND_HALF_UP

def finite_number(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value)
    except OverflowError:return False

def validate(document):
    if not isinstance(document,dict) or set(document) not in ({'version','pipeline_id','unit','dials'},{'version','pipeline_id','unit','dials','maximum_rate_per_second'}):
        raise ValueError('invalid_reading_format')
    if type(document['version']) is not int or document['version']!=1:raise ValueError('invalid_reading_format_version')
    if not isinstance(document['pipeline_id'],str) or not re.fullmatch('[a-f0-9]{64}',document['pipeline_id']):
        raise ValueError('invalid_reading_pipeline')
    if document['unit'] not in ('ft3','m3','L','gal_us','kWh'):raise ValueError('invalid_reading_unit')
    rate=document.get('maximum_rate_per_second')
    if rate is not None and (not finite_number(rate) or rate<0):raise ValueError('invalid_maximum_rate')
    dials=document['dials']
    if not isinstance(dials,list) or not 1<=len(dials)<=16:raise ValueError('invalid_reading_dials')
    seen=set();previous=None
    for dial in dials:
        if not isinstance(dial,dict) or set(dial)!={'index','value_per_revolution','position_error'}:
            raise ValueError('invalid_reading_dial')
        index=dial['index']
        if type(index) is not int or index<0 or index>=32 or index in seen:raise ValueError('invalid_reading_dial_index')
        seen.add(index)
        scale,error=dial['value_per_revolution'],dial['position_error']
        if any(not finite_number(x) for x in (scale,error)) or scale<=0 or not 0<=error<.5:
            raise ValueError('invalid_reading_scale_or_error')
        if scale/360<1e-12:raise ValueError('reading_scale_too_small')
        if previous is not None:
            ratio=previous/scale
            if not math.isfinite(ratio) or not 2<=ratio<=1000000 or abs(ratio-round(ratio))>1e-9:
                raise ValueError('reading_scales_must_be_nested')
        previous=scale
    document=dict(document)
    if rate is None:document.pop('maximum_rate_per_second',None)
    blob=json.dumps(document,sort_keys=True,separators=(',',':'),allow_nan=False)
    return json.loads(blob),hashlib.sha256(blob.encode()).hexdigest()

def display_quantity(value,document,register=False,resolution_factor=1):
    """Presentation only. Precision comes from the smallest dial's bound/bin size."""
    lowest=document['dials'][-1];period=document['dials'][0]['value_per_revolution']
    # Decoder has 360 angular bins. Neither this resolution nor the supplied
    # tolerance establishes accuracy; the result remains an unverified estimate.
    resolution=max(lowest['value_per_revolution']/360,
                   lowest['value_per_revolution']*lowest['position_error']/10)*resolution_factor
    if not math.isfinite(resolution) or resolution<=0:raise ValueError('reading_resolution_unrepresentable')
    exponent=max(-12,math.floor(math.log10(resolution)))
    decimals=max(0,-exponent)
    width=max(1,math.ceil(math.log10(period)))
    with localcontext() as context:
        context.prec=340
        rounded=Decimal(str(value)).quantize(Decimal(1).scaleb(exponent),rounding=ROUND_HALF_UP)
        if register:rounded%=Decimal(str(period))
        text=format(rounded,f'.{decimals}f')
    integer,separator,fraction=text.partition('.')
    return (integer.zfill(width) if register else integer)+(separator+fraction if separator else '')

def display_reading(value,document):return display_quantity(value,document,register=True)


def reconcile_reading(reading,consumption):
    """Expose a current temporal refinement only for the same image and format.

    No fallback to an older total when consumption is pending, rejected or
    recovering. Native single-image estimates keep their original provenance.
    """
    if reading.get('state')!='ambiguous' or not isinstance(consumption,dict):return reading
    if consumption.get('state') not in ('anchored','estimated','within_noise','bounded','ambiguous'):return reading
    for key in ('format_id','source_sha256'):
        value=reading.get(key)
        if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value) or value!=consumption.get(key):return reading
    absolute=consumption.get('absolute')
    if not isinstance(absolute,dict) or absolute.get('accuracy_verified') is not False or absolute.get('training_allowed') is not False:return reading
    if absolute.get('unit')!=reading.get('unit') or absolute.get('provenance')!='temporal_consumption_bounds':return reading
    bounds=absolute.get('bounds')
    if not isinstance(bounds,dict) or bounds.get('state')!='bounded':return reading
    result={**reading,'bounds':bounds,'provenance':absolute['provenance'],
            'anchor_captured_at':consumption.get('anchor_captured_at'),'accuracy_verified':False,'training_allowed':False}
    value=absolute.get('value');ranges=bounds.get('ranges')
    if absolute.get('state')=='estimated' and finite_number(value) and value>=0 and isinstance(absolute.get('text'),str):
        if isinstance(ranges,list) and len(ranges)==1 and isinstance(ranges[0],dict) and all(finite_number(ranges[0].get(k)) for k in ('lower','upper')) and ranges[0]['lower']<=value<=ranges[0]['upper']:
            result.update(state='estimated',value=value,text=absolute['text'])
    return result

class ReadingFormat:
    def __init__(self,native,document):
        self.native=native;self.document,self.identity=validate(document)
    def evaluate(self,inference):
        result={'state':'unavailable','value':None,'unit':self.document['unit'],
                'format_id':self.identity,'source_sha256':inference.get('source_sha256'),'accuracy_verified':False,'training_allowed':False}
        if inference.get('state')!='estimated':
            result['reason']='image_unavailable';return result
        if inference.get('pipeline_id')!=self.document['pipeline_id']:
            result['reason']='reading_pipeline_changed';return result
        rows=inference.get('dial_positions')
        # Every calibrated dial is represented once. No hidden role or include switch.
        indices=[d['index'] for d in self.document['dials']]
        if not isinstance(rows,list) or sorted(indices)!=list(range(len(rows))):
            result['reason']='reading_dial_mapping_mismatch';return result
        positions=[]
        for i in indices:
            row=rows[i];position=row.get('position') if isinstance(row,dict) else None
            if not isinstance(row,dict) or row.get('state')!='estimated' or not finite_number(position) or not 0<=position<10:
                result['reason']='dial_unavailable';return result
            positions.append(position)
        result.update(self.native.reading([d['value_per_revolution'] for d in self.document['dials']],positions,
                                         [d['position_error'] for d in self.document['dials']]))
        if result['state']=='estimated':result['text']=display_reading(result['value'],self.document)
        elif result['state']=='ambiguous':
            from reading_bounds import display_bounds
            result['bounds']=display_bounds(self.document,positions)
            if result['bounds']['state']=='inconsistent':
                result.update(state='inconsistent',reason='dial_bounds_disagree')
        if result['state']=='inconsistent':
            from reading_bounds import diagnose_inconsistency
            result['consistency']=diagnose_inconsistency(self.document,positions)
        return result


class FormatStore:
    """Saved interpretation, bound to the complete reader pipeline identity."""
    def __init__(self,directory,recognition,meter=None):
        from pathlib import Path
        import threading
        self.path=Path(directory)/'reading-format.json'
        self.recognition=recognition;self.lock=threading.Lock();self.active=None
        self.meter=meter
        from saved_file import SavedFile
        self.saved=SavedFile(self.path)
        try:
            raw=self.saved.read()
            if raw is not None:self.active=validate(json.loads(raw))
        except (ValueError,KeyError,TypeError,UnicodeError,RecursionError):
            self.saved.failed('saved_reading_format_invalid')
        except OSError:
            self.saved.failed('reading_format_file_unavailable')
    def status(self):
        with self.lock:
            if self.active is None:return {'revision':self.saved.revision,'format':None,**self.saved.recovery()}
            return {'revision':self.active[1],'format':json.loads(json.dumps(self.active[0]))}
    def save(self,document,revision):
        from setup_store import Setup
        candidate,identity=validate(document)
        # Same lock as calibration activation: no save can bind to half an update.
        from contextlib import nullcontext
        with (self.meter.lock if self.meter else nullcontext()),self.recognition.lock,self.lock:
            if self.meter:self.meter.require_unit(candidate['unit'])
            reader=self.recognition.reader
            if reader is None or candidate['pipeline_id']!=reader.pipeline_id:raise ValueError('reading_pipeline_changed')
            if sorted(d['index'] for d in candidate['dials'])!=list(range(len(reader.dials))):
                raise ValueError('reading_dial_mapping_mismatch')
            if revision!=(self.active[1] if self.active else self.saved.revision):raise ValueError('reading_format_changed_reload')
            self.saved.replace(json.dumps(candidate,indent=2,allow_nan=False).encode('utf-8'),Setup._atomic,'reading_format_changed_reload')
            self.active=(candidate,identity)
        return self.status()
    def evaluate(self,inference):
        with self.recognition.lock:
            reader=self.recognition.reader
            with self.lock:active=self.active
            if active is None:return {'state':'unavailable','reason':self.saved.error,'value':None} if self.saved.error else {'state':'not_configured','value':None}
            if reader is None:return {'state':'unavailable','reason':'reader_unavailable','value':None}
            if active[0]['pipeline_id']!=reader.pipeline_id:
                return {'state':'unavailable','reason':'reading_pipeline_changed','value':None}
            return ReadingFormat(reader.native,active[0]).evaluate(inference)
