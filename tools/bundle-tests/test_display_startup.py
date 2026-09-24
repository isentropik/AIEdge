"""Compile real display-profile restoration against in-memory storage failures."""
import argparse,os,subprocess,sys,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--idf',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[2];c=root/'code/components';sdk=a.idf/'components/json/cJSON'
assert (sdk/'cJSON.c').is_file()
with tempfile.TemporaryDirectory(prefix='aiedge-display-startup-') as folder:
 out=Path(folder);env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'global'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 obj=out/'cjson.o';exe=out/('test.exe' if os.name=='nt' else 'test')
 subprocess.run([sys.executable,'-m','ziglang','cc','-c',str(sdk/'cJSON.c'),'-o',str(obj)],env=env,check=True)
 args=[sys.executable,'-m','ziglang','c++','-std=c++17','-O2','-UNDEBUG','-I'+str(sdk)]
 for name in ('jomjol_flowcontroll','jomjol_tfliteclass','jomjol_controlcamera'):args+=['-I'+str(c/name)]
 subprocess.run(args+[str(Path(__file__).with_name('meter_display_startup_test.cpp')),str(obj),'-o',str(exe)],env=env,check=True)
 subprocess.run([str(exe)],check=True)
s=(root/'code/main/main.cpp').read_text(encoding='utf-8')
assert s.index('initializeBootBundle')<s.index('meter::restoreDisplayProfile')<s.index('server = start_webserver()')<s.index('InitializeFlowTask()')
print('Startup wiring restores profile after bundle checks and before HTTP/flow tasks')
