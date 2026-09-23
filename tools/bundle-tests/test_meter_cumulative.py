"""Portable physical-accounting regressions; requires Python ziglang."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
out = Path(tempfile.mkdtemp(prefix='aiedge-cumulative-'))
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out/'cache'), ZIG_LOCAL_CACHE_DIR=str(out/'local'))
exe = out/'test.exe'
subprocess.run([sys.executable, '-m', 'ziglang', 'c++', '-std=c++11', '-O2', '-UNDEBUG',
    '-I'+str(root/'code/components/jomjol_tfliteclass'),
    '-I'+str(root/'code/components/jomjol_controlcamera'),
    str(Path(__file__).with_name('meter_cumulative_test.cpp')), '-o', str(exe)], check=True, env=env)
subprocess.run([str(exe)], check=True, stdout=subprocess.DEVNULL)
print('PASS: tracked turns, ambiguous gaps, checkpoint bounds, jitter, rollover and restart; synthetic evidence only')
