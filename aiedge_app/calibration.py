"""Versioned runtime geometry, independent fixed pivots and explicit model routing."""
import base64,copy,hashlib,json,math,re
from pathlib import Path

def finite_number(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value)
    except OverflowError:return False

def load(path):
    with Path(path).open('rb') as stream:raw=stream.read(262145)
    if len(raw)>262144:raise ValueError('calibration_too_large')
    return validate(json.loads(raw))

def validate(document):
    d=copy.deepcopy(document)
    if not isinstance(d,dict) or d.get('version')!=1 or d.get('image_size')!=[640,480]:raise ValueError('unsupported_calibration_schema')
    if not re.fullmatch('[a-f0-9]{64}',str(d.get('reference_sha256',''))):raise ValueError('reference_hash_required')
    if not isinstance(d.get('markers'),list) or len(d['markers'])!=3:raise ValueError('three_markers_required')
    def ints(value,count):
        if not isinstance(value,list) or len(value)!=count or any(type(x) is not int or abs(x)>10000 for x in value):raise ValueError('invalid_integer_geometry')
    def nums(value,count):
        if not isinstance(value,list) or len(value)!=count or any(not finite_number(x) for x in value):raise ValueError('invalid_numeric_geometry')
    for m in d['markers']:
        if not isinstance(m,dict):raise ValueError('invalid_marker')
        ints(m['box'],4);nums(m['target'],2);x,y,w,h=m['box']
        if not (8<=w<=128 and 8<=h<=128 and 0<=x<=640-w and 0<=y<=480-h):raise ValueError('marker_outside_frame')
        pixels=base64.b64decode(m['pixels'],validate=True)
        if len(pixels)!=w*h or hashlib.sha256(pixels).hexdigest()!=m['sha256']:raise ValueError('marker_hash_or_size_mismatch')
    if not isinstance(d.get('dials'),list) or not 1<=len(d['dials'])<=32:raise ValueError('invalid_dial_count')
    names=set()
    for dial in d['dials']:
        if not isinstance(dial,dict):raise ValueError('invalid_dial')
        name=dial.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>80 or name in names:raise ValueError('invalid_or_duplicate_dial_name')
        names.add(name)
        if dial.get('model') not in ('main','secondary') or dial.get('direction') not in ('cw','ccw'):raise ValueError('invalid_dial_model_or_direction')
        ints(dial['crop'],4);ints(dial['sampling_anchor'],2);nums(dial['inverse'],9);nums(dial['pivot'],2)
    encoded=json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return d,hashlib.sha256(encoded).hexdigest()
