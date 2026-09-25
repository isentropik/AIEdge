"""Archive worker admission and failure checks; no device or network access."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mbedtls', type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--cxx', default='c++')
    parser.add_argument('--zig-python')
    args = parser.parse_args()
    tls = args.mbedtls.resolve()
    if not (tls/'library/sha256.c').is_file():
        parser.error('Expected an mbedTLS source tree')
    tests = Path(__file__).resolve().parent
    flow = tests.parents[2]/'code/components/jomjol_flowcontroll'
    cc = [args.zig_python, '-m', 'ziglang', 'cc'] if args.zig_python else [args.cc]
    cxx = [args.zig_python, '-m', 'ziglang', 'c++'] if args.zig_python else [args.cxx]
    with tempfile.TemporaryDirectory(prefix='aiedge-worker-') as folder:
        out = Path(folder)
        (out/'config.h').write_text('#define MBEDTLS_SHA256_C\n#define MBEDTLS_PLATFORM_C\n', encoding='ascii')
        flags = ['-O2', '-UNDEBUG', '-I'+str(out), '-I'+str(tests/'worker-fixtures'),
                 '-I'+str(tls/'include'), '-I'+str(flow), '-DMBEDTLS_CONFIG_FILE="config.h"']
        env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'), ZIG_LOCAL_CACHE_DIR=str(out/'zig-local'))
        objects = []
        for name in ['sha256', 'platform_util', 'platform']:
            obj = out/(name+'.o'); objects.append(str(obj))
            subprocess.run(cc+flags+['-c', str(tls/'library'/(name+'.c')), '-o', str(obj)], check=True, env=env)
        exe = out/('worker.exe' if os.name == 'nt' else 'worker')
        threads = [] if os.name == 'nt' else ['-pthread']
        subprocess.run(cxx+['-std=c++11']+threads+flags+[str(tests/'worker.cpp'),
            str(flow/'ImageArchiveWorker.cpp')]+objects+['-o', str(exe)], check=True, env=env)
        for mode in range(11):
            spool = out/('scenario-'+str(mode)); spool.mkdir()
            subprocess.run([str(exe), str(spool), str(mode)], check=True, timeout=15)
        print('All 11 archive worker scenarios passed (host tests only).')


if __name__ == '__main__':
    main()
