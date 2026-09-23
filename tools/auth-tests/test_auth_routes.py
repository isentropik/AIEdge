"""Source-route audit; complements HTTP tests, not a runtime penetration test."""
from pathlib import Path
import re
root=Path(__file__).resolve().parents[2]
checked=[]
for p in (root/'code').rglob('*.cpp'):
 if '.pio' in p.parts:continue
 for m in re.finditer(r'\.handler\s*=\s*([^;,\n]+)',p.read_text(encoding='utf-8-sig',errors='replace')):
  value=m.group(1).strip()
  if value.startswith('APPLY_BASIC_AUTH_FILTER('):checked.append(str(p.relative_to(root)))
  elif p.name=='basic_auth.cpp' and value=='setup':checked.append(str(p.relative_to(root)))
  else:raise AssertionError(f'Unreviewed HTTP handler: {p}: {value}')
loader=(root/'bootstrap/src/main.cpp').read_text()
for m in re.finditer(r'\.handler\s*=\s*([^;,\n]+)',loader):
 value=m.group(1).strip()
 assert value.startswith('WEBSITE_AUTH(') or value=='website_setup',value
 checked.append('bootstrap/src/main.cpp')
assert len(checked)>60
main=(root/'code/main/server_main.cpp').read_text()
assert main.index('register_website_auth(server)')<main.index('return server;',main.index('httpd_handle_t start_webserver'))
for file in ['code/main/StorageRecovery.cpp','code/main/softAP.cpp']:
 source=(root/file).read_text();assert 'init_basic_auth();' in source and 'register_website_auth(server)' in source
assert 'websiteHttp.initialize();' in loader and 'http.max_uri_handlers=12' in loader
assert 'nvs_flash_erase' not in loader
print(f'PASS: {len(checked)} handler assignments reviewed for shared authentication; startup setup registration present')
