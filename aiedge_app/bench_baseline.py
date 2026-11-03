"""Bind the saved camera settings from preflight to the settings seen at startup."""
from pathlib import Path
import hashlib
import json
import time
from camera_image import Config, capabilities
from bench_store import BurstStore

def baseline(raw, caps):
    model=capabilities(caps)['model']
    controls=Config(raw,model).controls()
    orientation=int(controls['mirror'])+2*int(controls['flip'])
    return dict(model=model,revision=hashlib.sha256(raw).hexdigest(),orientation=orientation)

def provision(directory,raw,caps):
    from bench_owner import service_owner
    with service_owner(directory):
        return _create(directory,raw,caps)

def _create(directory,raw,caps):
    directory=Path(directory)
    record=baseline(raw,caps)
    db=directory/'burst-bench.sqlite3'
    manifest=directory/'burst-baseline.json'
    # Call only in the owned, dedicated bench data directory.
    if manifest.exists():raise FileExistsError(manifest)
    with db.open('xb'):pass
    store=BurstStore(db,None)
    store.close()
    with manifest.open('x',encoding='utf-8') as out:json.dump(record,out)

def settings_binding(context,image_controls,directory):
    expected=json.loads((Path(directory)/'burst-baseline.json').read_text(encoding='utf-8'))
    image_controls.require_capture()
    # The immutable saved config can be read while a pending worker owns the sensor.
    raw=image_controls.request('/fileserver/config/config.ini',time.monotonic()+15,json_response=False)
    revision=hashlib.sha256(raw).hexdigest()
    if revision!=expected['revision']:raise ValueError('camera configuration drift')
    controls=Config(raw,expected['model']).controls()
    orientation=int(controls['mirror'])+2*int(controls['flip'])
    if type(expected['orientation']) is not int or expected['orientation']!=orientation:
        raise ValueError('saved orientation mismatch')
    modules=('service.py','bench_owner.py','bench_baseline.py','bench_store.py',
             'bench_transport.py','bench_collector.py','bench_startup.py','buffered_ingest.py')
    source={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in modules}
    return {'collector':context,'camera':expected,'bench_source':source},orientation
EXPECTED_BUNDLE = 'db755b0c797578136886894773ede6aa04ab28ccd151e14eb592d259e5c846e0'

def prepare_trial(activation,collector,image_controls,directory):
    if not activation:
        raise ValueError('unfinished buffered trial needs its reviewed option')
    ticket,revision=activation.split('@')
    if collector.stop.is_set() or collector.shutdown.is_set() or collector.transfer_attempt is not None:
        raise ValueError('collector already held or recovering')
    image_controls.require_capture()
    deadline=time.monotonic()+15
    live=image_controls.request('/bundle_status',deadline)
    if (not isinstance(live,dict) or live.get('running_bundle_verified') is not True
            or live.get('running_bundle_id')!=EXPECTED_BUNDLE or live.get('active') is not False):
        raise ValueError('camera firmware does not match buffered trial')
    directory=Path(directory)
    if not (directory/'burst-bench.sqlite3').exists():
        caps=image_controls.request('/image-controls-capabilities',deadline)
        raw=image_controls.request('/fileserver/config/config.ini',deadline,json_response=False)
        if hashlib.sha256(raw).hexdigest()!=revision:
            raise ValueError('reviewed camera configuration changed')
        _create(directory,raw,caps)
    context,orientation=settings_binding(collector.continuation_context(),image_controls,directory)
    if context['camera']['revision']!=revision:
        raise ValueError('reviewed camera configuration changed')
    return context,orientation,ticket
