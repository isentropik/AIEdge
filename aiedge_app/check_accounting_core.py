"""Compile and execute independent generic accounting regressions, without models."""
import argparse,ctypes,os,shutil,subprocess,tempfile
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--zig-python',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parent
    if args.zig_python:compiler=[str(args.zig_python.resolve()),'-m','ziglang','c++']
    else:
        executable=shutil.which('c++') or shutil.which('g++')
        if not executable:raise SystemExit('A C++17 compiler is required. Use --zig-python only with an existing Zig Python environment.')
        compiler=[executable]
    if os.name=='nt':ctypes.windll.kernel32.SetErrorMode(2)
    with tempfile.TemporaryDirectory(prefix='aiedge-accounting-check-') as directory:
        executable=Path(directory)/('accounting-check.exe' if os.name=='nt' else 'accounting-check')
        subprocess.run([*compiler,'-std=c++17','-O2','-UNDEBUG','-ffp-contract=off','-I'+str(root/'assets/include'),str(root/'test_accounting_core.cpp'),'-o',str(executable)],check=True)
        subprocess.run([str(executable)],check=True,timeout=30)
if __name__=='__main__':main()
