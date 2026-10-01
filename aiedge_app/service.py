import argparse,json,sqlite3,threading,urllib.parse,secrets
from http.server import BaseHTTPRequestHandler
from http_server import AppHTTPServer
from pathlib import Path
from capture import Store,Camera,Collector
from options import load as load_options

def handler(store,ingress,collector,recognition=None,setup=None,reading_format=None,mqtt_output=None,configuration=None,consumption=None,consumption_error=None,reviews=None,camera_setup=None,archive=None):
    from review_store import ReviewConflict
    from archive import ArchiveConflict
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed(self):
            if ingress:return self.client_address[0]=='172.30.32.2'
            try:host=urllib.parse.urlsplit('//'+self.headers.get('Host','')).hostname
            except ValueError:return False
            return self.client_address[0]=='127.0.0.1' and host in ('127.0.0.1','localhost')
        def reply(self,payload,status=200):
            body=json.dumps(payload,allow_nan=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def reject_post(self):
            # A small POST body can still be arriving when access is rejected.
            # Drain it briefly so TCP close does not turn a 403 into a reset.
            try:
                length=int(self.headers.get('Content-Length','0'))
                if 0<length<=4096 and not self.headers.get('Transfer-Encoding'):
                    self.connection.settimeout(.025);self.rfile.read(length)
            except (OSError,ValueError):pass
            self.send_error(403)
        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-AIEdge-Setup',''),token):self.reject_post();return
            if setup is None:self.reply({'error':'Calibration runtime is not configured.'},503);return
            route=urllib.parse.urlsplit(self.path).path
            if route not in ('/api/setup/reference','/api/setup/save','/api/setup/suggest-markers','/api/reading-format','/api/reviews','/api/camera-setup','/api/archive'):self.send_error(404);return
            try:
                self.connection.settimeout(10)
                length=int(self.headers.get('Content-Length','0'))
                limit=4*1024*1024 if route.endswith('/reference') else 262144
                if not 0<length<=limit or self.headers.get('Transfer-Encoding'):raise ValueError('Invalid request size.')
                body=self.rfile.read(length)
                if len(body)!=length:raise ValueError('Incomplete request.')
                if route.endswith('/reference'):
                    digest=setup.add_reference(body);self.reply({'reference_sha256':digest});return
                if self.headers.get_content_type()!='application/json':raise ValueError('JSON request required.')
                data=json.loads(body)
                if route=='/api/archive':
                    if archive is None:self.reply({'error':'archive_unavailable'},503);return
                    if not isinstance(data,dict):raise ValueError('archive_action_invalid')
                    if set(data)=={'action','config','revision'} and data['action']=='save':result=archive.save(data['config'],data['revision'])
                    elif set(data)=={'action','revision'} and data['action']=='retry':result=archive.retry(data['revision'])
                    else:raise ValueError('archive_action_invalid')
                elif route=='/api/camera-setup':
                    if camera_setup is None:self.reply({'error':'camera_not_configured'},503);return
                    expected={'action','revision','lighting'} if isinstance(data,dict) and data.get('action')=='lighting-apply' else {'action','revision','controls'} if isinstance(data,dict) and data.get('action')=='image-apply' else {'action'}
                    if not isinstance(data,dict) or set(data) != expected:raise ValueError('invalid_camera_setup_action')
                    result=camera_setup.start(data['action'],data.get('revision'),data.get('lighting'),data.get('controls'))
                elif route=='/api/setup/suggest-markers':
                    from marker_suggestions import propose
                    result=propose(setup.reference(data['reference_sha256']),data['crops'])
                elif route=='/api/reviews':
                    if reviews is None:self.reply({'error':'Image review storage is unavailable.'},503);return
                    result=reviews.save(data)
                elif route=='/api/reading-format':
                    if reading_format is None:self.reply({'error':'Reading format is not configured.'},503);return
                    result=reading_format.save(data['format'],data['revision'])
                else:
                    result=setup.save(data['reference_sha256'],data['design'],data['revision'])
                    image=getattr(camera_setup,'image_controls',None)
                    if image:image.calibration_saved(result['calibration']['reference_sha256'])
                self.reply(result)
            except ReviewConflict as exc:self.reply({'error':str(exc),'code':'review_conflict'},409)
            except ArchiveConflict as exc:self.reply({'error':str(exc),'code':'archive_conflict'},409)
            except FileNotFoundError:self.reply({'error':'Capture not found.'},404)
            except sqlite3.Error:self.reply({'error':'Review storage is unavailable. Reload before retrying.'},503)
            except RecursionError:self.reply({'error':'Setup document is too deeply nested.'},400)
            except (ValueError,KeyError,TypeError) as exc:self.reply({'error':str(exc)},400)
            except OSError:self.reply({'error':'Could not complete setup storage. Reload before retrying.'},503)
        def do_GET(self):
            try:self.read_request()
            except (BrokenPipeError,ConnectionResetError):pass
            except (OSError,sqlite3.Error):self.reply({'error':'Local storage is unavailable. Saved readings have not been replaced.','code':'storage_unavailable'},503)
        def read_request(self):
            if not self.allowed():self.send_error(403);return
            route=urllib.parse.urlsplit(self.path).path
            if route=='/api/diagnostics':
                from diagnostics import build
                body=json.dumps(build(store,collector,recognition,setup,reading_format,mqtt_output,configuration,consumption,archive),indent=2,allow_nan=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Disposition','attachment; filename="aiedge-diagnostics.json"');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            if store is None and (route.startswith('/api/') or route.startswith('/image/') or route.startswith('/reference/')):
                self.reply({'error':'App storage could not be opened. Capture and MQTT are stopped. Check the data volume or restore a backup, then restart AIEdge.','code':'storage_startup_failed'},503);return
            if route=='/api/status':
                state=store.status();state.update(capture_enabled=collector is not None,missed_slots=collector.missed_slots if collector else 0)
                state['configuration']=configuration or {'state':'ready'}
                state['camera']=dict(collector.camera_state) if collector else {'state':'not_checked'}
                state['last_failure']=state['last_error']
                state['last_error']=collector.last_error if collector else None
                state['interval_seconds']=collector.interval if collector else None
                state['recognition']=recognition.latest() if recognition else {'state':'not_configured'}
                state['reading']=reading_format.evaluate(state['recognition']) if reading_format else {'state':'not_configured','value':None}
                state['setup_recovery']=setup.status().get('recovery') if setup else None
                state['format_recovery']=reading_format.status().get('recovery') if reading_format else None
                state['recognition_error']=recognition.last_error if recognition else None
                state['mqtt']=mqtt_output.status() if mqtt_output else {'state':'disabled','error':None}
                state['consumption']=consumption.status() if consumption else {'state':'unavailable' if consumption_error else 'not_configured','reason':consumption_error,'value':None,'accuracy_verified':False,'training_allowed':False}
                from reading_format import reconcile_reading
                state['reading']=reconcile_reading(state['reading'],state['consumption'])
                body=json.dumps(state).encode();kind='application/json'
            elif route=='/api/archive':
                state=archive.status() if archive else {'state':'unavailable','error':'archive_unavailable'}
                body=json.dumps(state).encode();kind='application/json'
            elif route=='/api/camera-setup':
                state=camera_setup.status() if camera_setup else {'configured':False,'state':'idle','camera_settings_supported':False}
                body=json.dumps(state).encode();kind='application/json'
            elif route=='/api/reading-format':
                state=reading_format.status() if reading_format else {'revision':None,'format':None}
                if recognition:
                    with recognition.lock:
                        reader=recognition.reader
                        state.update(pipeline_id=reader.pipeline_id if reader else None,dials=[{'index':i,'name':d['name'],'direction':d['direction']} for i,d in enumerate(reader.dials)] if reader else [])
                body=json.dumps(state).encode();kind='application/json'
            elif route=='/api/setup':
                state=setup.status() if setup else {'revision':None,'calibration':None}
                state.update(available=setup is not None,token=token);body=json.dumps(state).encode();kind='application/json'
            elif route in ('/app.css','/parity.css'):
                body=(Path(__file__).parent/route[1:]).read_bytes();kind='text/css; charset=utf-8'
            elif route=='/favicon.svg':
                body=(Path(__file__).parent/'favicon.svg').read_bytes();kind='image/svg+xml'
            elif route in ('/setup.js','/reading-format.js','/dashboard.js','/editor-geometry.js','/reference-image.js','/capture-review.js','/setup-flow.js','/camera-lighting.js','/camera-image.js','/archive.js'):
                body=(Path(__file__).parent/route[1:]).read_bytes();kind='text/javascript; charset=utf-8'
            elif route.startswith('/reference/') and setup:
                try:body=setup.reference(route.removeprefix('/reference/'));kind='image/png' if body.startswith(b'\x89PNG') else 'image/jpeg'
                except (ValueError,FileNotFoundError):self.send_error(404);return
            elif route.startswith('/api/reviews/'):
                if reviews is None:self.reply({'error':'Image review storage is unavailable.'},503);return
                try:result=reviews.get(int(route.removeprefix('/api/reviews/')))
                except FileNotFoundError:self.reply({'error':'Capture not found.'},404);return
                except (ValueError,TypeError) as exc:self.reply({'error':str(exc)},400);return
                body=json.dumps(result,allow_nan=False).encode();kind='application/json'
            elif route=='/api/capture-history':
                try:
                    query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,keep_blank_values=True,max_num_fields=2)
                    if set(query)-{'before','limit'} or any(len(values)!=1 for values in query.values()):raise ValueError()
                    before=int(query['before'][0]) if 'before' in query else None
                    limit=int(query['limit'][0]) if 'limit' in query else 50
                    page=store.history(before,limit)
                    if reviews:reviews.summaries(page['items'])
                except ValueError:self.reply({'error':'Invalid capture history page.'},400);return
                body=json.dumps(page).encode();kind='application/json'
            elif route=='/api/captures':body=json.dumps(store.recent()).encode();kind='application/json'
            elif route.startswith('/image/'):
                try:body=store.image(route.removeprefix('/image/'));kind='image/jpeg'
                except (ValueError,FileNotFoundError):self.send_error(404);return
            elif route=='/':body=(Path(__file__).parent/'index.html').read_bytes();kind='text/html; charset=utf-8'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    return Handler

def create_reader(library,models,profile=None,calibration_file=None):
    from reader import Reader
    if calibration_file:
        from calibration import load
        profile,_=load(calibration_file)
    return Reader(library,models,profile)

def run_service(stop_signals):
    parser=argparse.ArgumentParser();parser.add_argument('--data',default='./data');parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--port',type=int,default=8099);parser.add_argument('--ingress',action='store_true');parser.add_argument('--native-library');parser.add_argument('--accounting-library');parser.add_argument('--models');group=parser.add_mutually_exclusive_group();group.add_argument('--calibration-profile');group.add_argument('--calibration-file');args=parser.parse_args()
    options,configuration=load_options(args.data)
    stop_signals.checkpoint()
    interval=options['interval_seconds'];enabled=options['capture_enabled']
    storage_error=False
    try:store=Store(args.data)
    except (OSError,sqlite3.Error):
        store=None;storage_error=True;enabled=False
    stop_signals.checkpoint()
    collector=None;recognition=None;setup=None;reading_format=None;mqtt_output=None
    if not storage_error and any((args.native_library,args.models,(args.calibration_profile or args.calibration_file))):
        if not all((args.native_library,args.models)):raise ValueError('recognition_requires_library_and_models')
        from reader import Reader
        from recognition import Recognition
        initial=create_reader(args.native_library,args.models,args.calibration_profile,args.calibration_file) if (args.calibration_profile or args.calibration_file) else None
        stop_signals.checkpoint()
        try:
            recognition=Recognition(store,initial)
            from setup_store import Setup
            if initial and (Path(args.data)/'calibration.json').exists():raise ValueError('explicit_profile_conflicts_with_saved_setup')
            setup=Setup(args.data,lambda document:Reader(args.native_library,args.models,document),recognition)
            stop_signals.checkpoint()
            from reading_format import FormatStore
            reading_format=FormatStore(args.data,recognition)
        except (OSError,sqlite3.Error):
            recognition=None;setup=None;reading_format=None;enabled=False
            configuration={'state':'invalid','code':'setup_storage_unavailable'}
    mqtt_enabled=options.get('mqtt_enabled',False) and not storage_error and configuration.get('state')=='ready'
    if mqtt_enabled and (recognition is None or reading_format is None):
        configuration={'state':'invalid','code':'options_mqtt_runtime_required'}
        mqtt_enabled=False;enabled=False
    if mqtt_enabled:
        from mqtt_output import MqttOutput
        def publication_snapshot():
            inference=recognition.latest();reading=reading_format.evaluate(inference);saved=reading_format.status()
            if reading.get('format_id')!=saved['revision']:reading={'state':'unavailable','value':None}
            from reading_format import reconcile_reading
            reading=reconcile_reading(reading,consumption.status() if consumption else None)
            return {'latest':store.status()['latest'],'reading':reading,'format':saved['format']}
        try:mqtt_output=MqttOutput(args.data,publication_snapshot,interval)
        except (OSError,ValueError,UnicodeError):
            configuration={'state':'invalid','code':'mqtt_identity_unavailable'};enabled=False
    camera=None
    if store and configuration.get('state')=='ready' and options.get('camera_url'):
        camera=Camera(options['camera_url'],options.get('camera_token',''),options.get('camera_username',''),options.get('camera_password',''))
    if enabled:
        collector=Collector(store,camera,interval)
    consumption=None;consumption_error=None
    if args.accounting_library and recognition and reading_format:
        try:
            from consumption import Consumption
            consumption=Consumption(store,recognition,reading_format,args.accounting_library)
        except (OSError,sqlite3.Error,ValueError):consumption_error='consumption_runtime_unavailable'
    reviews=None
    if store:
        from review_store import Reviews
        try:reviews=Reviews(store,recognition)
        except (OSError,sqlite3.Error):pass
    archive=None
    if store:
        from archive import Archive
        try:archive=Archive(store)
        except (OSError,sqlite3.Error,ValueError):pass
    from camera_setup import CameraSetup
    from camera_lighting import CameraLighting
    from camera_image import CameraImage
    lighting=CameraLighting(camera,args.data) if camera else None
    image_controls=CameraImage(camera,args.data) if camera else None
    if camera:camera.lighting=lighting;camera.image_controls=image_controls
    if image_controls and setup:
        saved=setup.status().get('calibration')
        if saved:image_controls.calibration_saved(saved.get('reference_sha256'))
    preview=CameraSetup(camera,setup,interval,enabled,lighting,image_controls) if store and configuration.get('state')=='ready' else None
    stop_signals.checkpoint()
    server=AppHTTPServer((args.bind,args.port),handler(store,args.ingress,collector,recognition,setup,reading_format,mqtt_output,configuration,consumption,consumption_error,reviews,preview,archive))
    from lifecycle import ServiceRuntime
    if not ServiceRuntime(server,(collector,recognition,mqtt_output,consumption,preview,archive),signals=stop_signals).run():
        raise SystemExit('App request or worker shutdown timed out.')
def main():
    from lifecycle import StartupSignals,StartupStopped,lifecycle_event
    with StartupSignals() as stop_signals:
        try:run_service(stop_signals)
        except StartupStopped:lifecycle_event('aiedge_stopped',phase='startup',workers=0)
if __name__=='__main__':main()
