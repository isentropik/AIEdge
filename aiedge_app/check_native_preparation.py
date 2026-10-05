"""Compile synthetic masked/full native parity checks without images or models."""
import argparse,ctypes,os,shutil,subprocess,tempfile
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--zig-python',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parent
    if args.zig_python:compiler=[str(args.zig_python.resolve()),'-m','ziglang','c++']
    else:
        executable=shutil.which('c++') or shutil.which('g++')
        if not executable:raise SystemExit('A C++17 compiler is required. --zig-python uses an existing Zig environment.')
        compiler=[executable]
    if os.name=='nt':ctypes.windll.kernel32.SetErrorMode(2)
    with tempfile.TemporaryDirectory(prefix='aiedge-native-preparation-check-') as directory:
        folder=Path(directory);executable=folder/('native-check.exe' if os.name=='nt' else 'native-check')
        env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(folder/'zig-local'),ZIG_GLOBAL_CACHE_DIR=str(folder/'zig-global'))
        subprocess.run([*compiler,'-std=c++17','-O2','-UNDEBUG','-ffp-contract=off','-I'+str(root/'assets/include'),str(root/'test_native_masked.cpp'),'-o',str(executable)],check=True,env=env,timeout=120)
        subprocess.run([str(executable)],check=True,timeout=30)
if __name__=='__main__':main()
