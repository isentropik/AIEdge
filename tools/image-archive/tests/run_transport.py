"""Run archive upload deadline and transport checks against production headers."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mbedtls',type=Path,required=True,help='mbedTLS source directory containing include/ and library/')
    parser.add_argument('--cjson',type=Path,required=True,help='cJSON source directory containing cJSON.c and cJSON.h')
    parser.add_argument('--cc',default='cc')
    parser.add_argument('--cxx',default='c++')
    parser.add_argument('--zig-python',help='Optional Python executable with the ziglang module installed')
    args=parser.parse_args()
    tls=args.mbedtls.resolve()
    if not (tls/'library/sha256.c').is_file():parser.error('Expected an mbedTLS source tree')
    repo=Path(__file__).resolve().parents[3]
    source=Path(__file__).with_name('transport.cpp')
    fixture=Path(__file__).with_name('transport-fixtures')
    cjson=args.cjson.resolve()
    cc=[args.zig_python,'-m','ziglang','cc'] if args.zig_python else [args.cc]
    cxx=[args.zig_python,'-m','ziglang','c++'] if args.zig_python else [args.cxx]
    with tempfile.TemporaryDirectory(prefix='aiedge-transport-') as folder:
        out=Path(folder)
        (out/'archive_sha_config.h').write_text('#define MBEDTLS_SHA256_C\n#define MBEDTLS_PLATFORM_C\n#define MBEDTLS_BASE64_C\n',encoding='ascii')
        flags=['-O2','-UNDEBUG','-I'+str(tls/'include'),'-I'+str(out),'-I'+str(fixture),'-I'+str(cjson),'-DMBEDTLS_CONFIG_FILE="archive_sha_config.h"']
        env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),ZIG_LOCAL_CACHE_DIR=str(out/'zig-local'))
        objects=[]
        for name in ['sha256','platform_util','platform','base64','constant_time']:
            obj=out/(name+'.o');objects.append(str(obj))
            subprocess.run(cc+flags+['-c',str(tls/'library'/(name+'.c')),'-o',str(obj)],check=True,env=env)
        obj=out/'cjson.o';objects.append(str(obj))
        subprocess.run(cc+flags+['-c',str(cjson/'cJSON.c'),'-o',str(obj)],check=True,env=env)
        exe=out/('destination-queues.exe' if os.name=='nt' else 'destination-queues')
        subprocess.run(cxx+['-std=c++11']+flags+['-I'+str(repo/'code/components/jomjol_flowcontroll'),str(source),str(repo/'code/components/jomjol_flowcontroll/ImageArchiveTransport.cpp')]+objects+['-o',str(exe)],check=True,env=env)
        evidence=out/'spool';evidence.mkdir()
        subprocess.run([str(exe),str(evidence)],check=True)

if __name__=='__main__':main()
