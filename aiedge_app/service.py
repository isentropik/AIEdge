import argparse,json,sqlite3,threading,urllib.parse,secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from capture import Store,Camera,Collector

def handler(store,ingress,collector,recognition=None,setup=None,reading_format=None,mqtt_output=None):
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
        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-AIEdge-Setup',''),token):self.send_error(403);return
            if setup is None:self.reply({'error':'Calibration runtime is not configured.'},503);return
            route=urllib.parse.urlsplit(self.path).path
            if route not in ('/api/setup/reference','/api/setup/save','/api/reading-format'):self.send_error(404);return
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
                if route=='/api/reading-format':
                    if reading_format is None:self.reply({'error':'Reading format is not configured.'},503);return
                    result=reading_format.save(data['format'],data['revision'])
                else:result=setup.save(data['reference_sha256'],data['design'],data['revision'])
                self.reply(result)
            except (ValueError,KeyError,TypeError) as exc:self.reply({'error':str(exc)},400)
            except OSError:self.reply({'error':'Could not complete setup storage. Reload before retrying.'},503)
        def do_GET(self):
            try:self.read_request()
            except (BrokenPipeError,ConnectionResetError):pass
            except (OSError,sqlite3.Error):self.reply({'error':'Local storage is unavailable. Saved readings have not been replaced.'},503)
        def read_request(self):
            if not self.allowed():self.send_error(403);return
            route=urllib.parse.urlsplit(self.path).path
            if route=='/api/status':
                state=store.status();state.update(capture_enabled=collector is not None,missed_slots=collector.missed_slots if collector else 0)
                state['last_failure']=state['last_error']
                state['last_error']=collector.last_error if collector else None
                state['interval_seconds']=collector.interval if collector else None
                state['recognition']=recognition.latest() if recognition else {'state':'not_configured'}
                state['reading']=reading_format.evaluate(state['recognition']) if reading_format else {'state':'not_configured','value':None}
                state['setup_recovery']=setup.status().get('recovery') if setup else None
                state['format_recovery']=reading_format.status().get('recovery') if reading_format else None
                state['recognition_error']=recognition.last_error if recognition else None
                state['mqtt']=mqtt_output.status() if mqtt_output else {'state':'disabled','error':None}
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
            elif route=='/favicon.svg':
                body=(Path(__file__).parent/'favicon.svg').read_bytes();kind='image/svg+xml'
            elif route in ('/setup.js','/reading-format.js','/dashboard.js','/editor-geometry.js'):
                body=(Path(__file__).parent/route[1:]).read_bytes();kind='text/javascript; charset=utf-8'
            elif route.startswith('/reference/') and setup:
                try:body=setup.reference(route.removeprefix('/reference/'));kind='image/png' if body.startswith(b'\x89PNG') else 'image/jpeg'
                except (ValueError,FileNotFoundError):self.send_error(404);return
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

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',default='./data');parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--port',type=int,default=8099);parser.add_argument('--ingress',action='store_true');parser.add_argument('--native-library');parser.add_argument('--models');group=parser.add_mutually_exclusive_group();group.add_argument('--calibration-profile');group.add_argument('--calibration-file');args=parser.parse_args()
    path=Path(args.data)/'options.json';options=json.loads(path.read_text()) if path.exists() else {}
    interval=options.get('interval_seconds',30);enabled=options.get('capture_enabled',False)
    if type(interval) is not int or not 10<=interval<=3600:raise ValueError('invalid_capture_interval')
    if type(enabled) is not bool:raise ValueError('invalid_capture_enabled')
    store=Store(args.data);collector=None;recognition=None;setup=None;reading_format=None;mqtt_output=None
    if any((args.native_library,args.models,(args.calibration_profile or args.calibration_file))):
        if not all((args.native_library,args.models)):raise ValueError('recognition_requires_library_and_models')
        from reader import Reader
        from recognition import Recognition
        initial=create_reader(args.native_library,args.models,args.calibration_profile,args.calibration_file) if (args.calibration_profile or args.calibration_file) else None
        recognition=Recognition(store,initial)
        from setup_store import Setup
        if initial and (Path(args.data)/'calibration.json').exists():raise ValueError('explicit_profile_conflicts_with_saved_setup')
        setup=Setup(args.data,lambda document:Reader(args.native_library,args.models,document),recognition)
        from reading_format import FormatStore
        reading_format=FormatStore(args.data,recognition)
    mqtt_enabled=options.get('mqtt_enabled',False)
    if type(mqtt_enabled) is not bool:raise ValueError('invalid_mqtt_enabled')
    if mqtt_enabled:
        if recognition is None or reading_format is None:raise ValueError('mqtt_requires_recognition_runtime')
        from mqtt_output import MqttOutput
        def publication_snapshot():
            inference=recognition.latest();reading=reading_format.evaluate(inference);saved=reading_format.status()
            if reading.get('format_id')!=saved['revision']:reading={'state':'unavailable','value':None}
            return {'latest':store.status()['latest'],'reading':reading,'format':saved['format']}
        mqtt_output=MqttOutput(args.data,publication_snapshot,interval)
    if enabled:
        collector=Collector(store,Camera(options.get('camera_url',''),options.get('camera_token',''),options.get('camera_username',''),options.get('camera_password','')),interval)
    server=ThreadingHTTPServer((args.bind,args.port),handler(store,args.ingress,collector,recognition,setup,reading_format,mqtt_output))
    for worker in (collector,recognition,mqtt_output):
        if worker:threading.Thread(target=worker.run,daemon=True).start()
    try:server.serve_forever()
    finally:
        if collector:collector.stop.set()
        if recognition:recognition.stop.set()
        if mqtt_output:mqtt_output.stop.set()
        server.server_close()
if __name__=='__main__':main()
