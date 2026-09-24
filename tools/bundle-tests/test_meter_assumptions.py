"""Validate optional physical flow bounds without firmware or device access."""
from pathlib import Path
import argparse, os, subprocess, sys, tempfile
parser=argparse.ArgumentParser()
parser.add_argument('--idf',type=Path,required=True)
a=parser.parse_args()
root=Path(__file__).resolve().parents[2]
sdk=a.idf/'components/json/cJSON'
with tempfile.TemporaryDirectory(prefix='aiedge-assumptions-') as folder:
 out=Path(folder)
 env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'cache'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 obj=out/'cjson.o';exe=out/'test.exe'
 subprocess.run([sys.executable,'-m','ziglang','cc','-c',str(sdk/'cJSON.c'),'-o',str(obj)],env=env,check=True)
 for test in ('meter_assumptions_test.cpp','meter_assumptions_store_test.cpp','meter_assumptions_runtime_test.cpp'):
  subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG',
   '-I'+str(sdk),'-I'+str(root/'code/components/jomjol_tfliteclass'),
   '-I'+str(root/'code/components/jomjol_controlcamera'),
   str(Path(__file__).with_name(test)),str(obj),'-o',str(exe)],env=env,check=True)
  subprocess.run([str(exe)],check=True)
print('PASS: flow parsing, bounds, namespaces, stale saves, interrupted writes, recovery conflicts, cleanup retries and isolated runtime transitions')
