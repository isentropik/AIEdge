"""Prepare matching meter/server archive configuration offline; never deploy."""
import argparse
import json
import ipaddress
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import ssl

HERE = Path(__file__).resolve().parent

def absolute_destination(value):
    if not value or any(ord(c)<32 for c in value):
        raise ValueError('Use an absolute server-local path without control characters')
    if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
        raise ValueError('Folder and TLS file paths must be absolute on the storage server')
    return value

def prepare(output, host, folder, ca_file, certificate, private_key, device='gas-meter', port=8766, bind='0.0.0.0'):
    if len(host)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',host):
        raise ValueError('Use a server IPv4 address or DNS name, without scheme, port or path')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',device):
        raise ValueError('Invalid device identifier')
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError('Port must be 1 through 65535')
    ipaddress.IPv4Address(bind)
    for value in (folder,certificate,private_key):absolute_destination(value)
    ca=Path(ca_file).read_bytes()
    if not 0<len(ca)<=8192:raise ValueError('CA PEM must be 1 through 8192 bytes')
    ssl.create_default_context(cadata=ca.decode('ascii'))
    # Validate every input before creating output. Never replace an existing setup.
    output=Path(output);output.mkdir(mode=0o700,parents=False,exist_ok=False)
    meter=output/'meter-config';server=output/'server'
    meter.mkdir(mode=0o700);server.mkdir(mode=0o700)
    token=secrets.token_urlsafe(32)+'\n'
    for target in (meter/'image-archive-token.txt',server/'archive-token.txt'):
        with target.open('x',encoding='ascii') as f:f.write(token)
        os.chmod(target,0o600)
    (meter/'image-archive-ca.pem').write_bytes(ca)
    config={'enabled':True,'host':host,'device_id':device,'port':port,'timeout_ms':15000}
    (meter/'image-archive.json').write_text(json.dumps(config,indent=2)+'\n',encoding='ascii')
    # One authoritative revision for the web editor; legacy files remain available
    # for older development builds and for copying values into the form.
    settings=meter/'image-archive-settings.json'
    with settings.open('x',encoding='ascii') as f:
        json.dump({'version':1,'config':config,'token':token.rstrip('\n'),'ca_pem':ca.decode('ascii')},f,indent=2)
        f.write('\n')
    os.chmod(settings,0o600)
    args=['--bind',bind,'--port',str(port),'--folder',folder,'--certificate',certificate,'--private-key',private_key]
    (server/'receiver-arguments.json').write_text(json.dumps(args,indent=2)+'\n',encoding='utf-8')
    for name in ('image_archive_receiver.py','image_archive_store.py'):
        (server/name).write_bytes((HERE/name).read_bytes())
    (server/'start_receiver.py').write_text('''"""Run on the storage server after reviewing receiver-arguments.json."""
import json
from pathlib import Path
import runpy
import sys
base=Path(__file__).resolve().parent
args=json.loads((base/'receiver-arguments.json').read_text(encoding='utf-8'))
sys.argv=[str(base/'image_archive_receiver.py'),'--token-file',str(base/'archive-token.txt'),*args]
runpy.run_path(sys.argv[0],run_name='__main__')
''',encoding='utf-8')
    (output/'README.md').write_text('''# Offline image archive setup

Nothing was deployed or contacted. These files contain an upload token; keep
this directory private and out of Git, shared reports and firmware ZIPs. On
Windows, verify NTFS permissions; chmod is not an ACL privacy guarantee.

1. Review server/receiver-arguments.json. The folder and certificate/key paths
   refer to the storage server, not the meter. The destination filesystem must
   support hard links on Linux or same-folder no-replace rename on Windows.
   Test the actual share with the storage probe. The TLS certificate must match the configured IP
   or hostname and chain to the supplied CA. CA parsing alone does not prove it.
2. Copy server/ to the intended storage server. Install Python 3.10 or newer,
   provision the certificate/key and destination permissions, then run
   `python start_receiver.py`. It listens on IPv4 interfaces at the chosen port.
   No firewall changes or background service installation are performed here.
3. On a compatible build, open Settings > Image archive. Enter the host, port
   and device name from meter-config/image-archive.json, then the token and CA
   certificate from the matching text files. Save and restart when ready. This
   enables archival; saving alone does not change the running uploader.
   For offline SD setup, preserve any existing settings, power off the meter,
   and copy image-archive-settings.json into its config folder. That one file is
   authoritative on current builds. The three legacy files are for older builds;
   editing them has no effect while the unified settings file exists.
4. Verify receipts and /image_archive_status with the intended device. An upload
   failure must remain visible; this setup does not prove connectivity, timing,
   available space, SD recovery, certificate hostname validity or model accuracy.

The destination is HTTPS receiver storage, not an SMB/NFS path on the ESP32.
Saved images stay unreviewed and are never automatically added to training.
''',encoding='utf-8')
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','host','folder','ca-file','certificate','private-key'):p.add_argument('--'+name,required=True)
    p.add_argument('--bind',default='0.0.0.0');p.add_argument('--device',default='gas-meter');p.add_argument('--port',type=int,default=8766)
    a=p.parse_args()
    try:result=prepare(a.output,a.host,a.folder,a.ca_file,a.certificate,a.private_key,a.device,a.port,a.bind)
    except (ValueError,OSError,UnicodeError) as e:p.error(str(e))
    print('Prepared private local setup at '+str(result)+'; nothing deployed.')
if __name__=='__main__':main()
