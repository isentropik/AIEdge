"""Compile the firmware matcher duplicate-peak regression fixture."""
import os,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[2]
if os.name=='nt':
 import ctypes
 ctypes.windll.kernel32.SetErrorMode(3)
with tempfile.TemporaryDirectory(prefix='aiedge-ambiguity-') as folder:
 out=Path(folder);env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'global'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 exe=out/('test.exe' if os.name=='nt' else 'test')
 subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG','-I'+str(root/'code/components/jomjol_tfliteclass'),str(Path(__file__).with_name('alignment_ambiguity_test.cpp')),'-o',str(exe)],env=env,check=True)
 subprocess.run([str(exe)],check=True)
