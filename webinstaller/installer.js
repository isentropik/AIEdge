// Original AIEdge page code. Flashing component: ESP Web Tools (Apache-2.0).
const status = document.querySelector('#status');
const button = document.querySelector('#install');
const urls = [];
const timeout = 30000;
async function fetchChecked(url) {
  const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(timeout)});
  if (!response.ok) throw new Error(`Download failed (${response.status}).`);
  return response;
}
async function prepare() {
  if (!window.isSecureContext) throw new Error('Open the HTTPS version of this installer to use USB.');
  if (!('serial' in navigator)) throw new Error('Use desktop Chrome or Edge for USB installation. You can use your phone for Wi-Fi setup afterward.');
  const manifest = await (await fetchChecked('manifest.json')).json();
  const integrity = await (await fetchChecked('integrity.json')).json();
  if (manifest.name !== 'AIEdge Wi-Fi loader' || manifest.version !== integrity.version ||
      manifest.builds.length !== 1 || manifest.builds[0].chipFamily !== 'ESP32' ||
      manifest.builds[0].parts.length !== 1 || manifest.builds[0].parts[0].offset !== 0)
    throw new Error('Unexpected installer manifest. Installation is disabled.');
  const part = manifest.builds[0].parts[0];
  const expected = integrity.files[part.path];
  if (!expected || !/^[a-f0-9]{64}$/.test(expected.sha256)) throw new Error('Missing file fingerprint. Installation is disabled.');
  const fileURL = new URL(part.path, location.href);
  if (fileURL.origin !== location.origin) throw new Error('Installer file must be hosted on this site.');
  const bytes = await (await fetchChecked(fileURL)).arrayBuffer();
  if (bytes.byteLength !== expected.bytes) throw new Error('Installer file is incomplete. Reload to try again.');
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)), n=>n.toString(16).padStart(2,'0')).join('');
  if (digest !== expected.sha256) throw new Error('Installer fingerprint does not match. Installation is disabled.');
  // Hand the component the exact verified bytes, not a second network download.
  const binaryURL = URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
  urls.push(binaryURL);
  part.path = binaryURL;
  const manifestURL = URL.createObjectURL(new Blob([JSON.stringify(manifest)],{type:'application/json'}));
  urls.push(manifestURL);
  button.setAttribute('manifest',manifestURL);
  await import('./vendor/esp-web-tools-aiedge.js?v=usb-recovery-1');
  await customElements.whenDefined('esp-web-install-button');
  button.hidden=false;
  status.textContent='Installer files checked. Ready to connect.';
}
prepare().catch(error=>{
  button.hidden=true;
  status.dataset.error='true';
  status.textContent=`${error.message} If this continues, use the manual installation guide.`;
  for (const url of urls) URL.revokeObjectURL(url);
});
