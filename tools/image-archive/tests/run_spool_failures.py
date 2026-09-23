"""Run archive write-failure checks against production headers and mbedTLS."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mbedtls',type=Path,required=True,help='mbedTLS source directory containing include/ and library/')
    parser.add_argument('--cc',default='cc')
    parser.add_argument('--cxx',default='c++')
    parser.add_argument('--zig-python',help='Optional Python executable with the ziglang module installed')
    args=parser.parse_args()
    tls=args.mbedtls.resolve()
    if not (tls/'library/sha256.c').is_file():parser.error('Expected an mbedTLS source tree')
    repo=Path(__file__).resolve().parents[3]
    source=Path(__file__).with_name('spool_write_failures.cpp')
    cc=[args.zig_python,'-m','ziglang','cc'] if args.zig_python else [args.cc]
    cxx=[args.zig_python,'-m','ziglang','c++'] if args.zig_python else [args.cxx]
    with tempfile.TemporaryDirectory(prefix='aiedge-spool-faults-') as folder:
        out=Path(folder)
        (out/'archive_sha_config.h').write_text('#define MBEDTLS_SHA256_C\n#define MBEDTLS_PLATFORM_C\n',encoding='ascii')
        flags=['-O2','-UNDEBUG','-I'+str(tls/'include'),'-I'+str(out),'-DMBEDTLS_CONFIG_FILE="archive_sha_config.h"']
        env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),ZIG_LOCAL_CACHE_DIR=str(out/'zig-local'))
        objects=[]
        for name in ['sha256','platform_util','platform']:
            obj=out/(name+'.o');objects.append(str(obj))
            subprocess.run(cc+flags+['-c',str(tls/'library'/(name+'.c')),'-o',str(obj)],check=True,env=env)
        exe=out/('spool-faults.exe' if os.name=='nt' else 'spool-faults')
        subprocess.run(cxx+['-std=c++11']+flags+['-I'+str(repo/'code/components/jomjol_flowcontroll'),str(source)]+objects+['-o',str(exe)],check=True,env=env)
        evidence=out/'spool';evidence.mkdir()
        subprocess.run([str(exe),str(evidence)],check=True)

if __name__=='__main__':main()
