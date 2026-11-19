(() => {
'use strict';
const $=id=>document.getElementById(id);
const stamp=(value,zone)=>value?new Date(value).toLocaleString(undefined,zone?{timeZone:zone}:undefined):'Unknown time';
let revision=null;
const form=$('retention-form'),message=$('retention-message');
async function request(path, options={}) {
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(8000),...options});
 const value=await response.json();
 if(!response.ok)throw Error(value.error||'Request failed');
 return value;
}
async function load() {
 form.querySelector('button').disabled=true;
 try {
  const saved=await request('api/retention');revision=saved.revision;
  for(const [name,value] of Object.entries(saved.config))form.elements.namedItem(name).value=value;
  const e=saved.evidence;
  $('retention-coverage').textContent=e?
   `${e.protected_gap_images} protected gap photos (${(e.protected_gap_bytes/1048576).toFixed(1)} MiB). ${e.complete_pairs} complete gap pairs; ${e.missing_endpoint_pairs} pairs already missing photos; ${e.awaiting_right_endpoint} awaiting a right endpoint. Checked ${stamp(e.checked_at)}.`:
   'Photo coverage has not been checked yet.';
  message.textContent=saved.error?'Cleanup needs attention; eligible photos have not all been removed.':'Saved settings loaded.';
  form.querySelector('button').disabled=false;
 } catch(error) {revision=null;message.textContent='Could not load retention settings. Reload before editing.';}
}
form.addEventListener('submit',async event=>{
 event.preventDefault();if(revision===null||!form.reportValidity())return;
 form.querySelector('button').disabled=true;
 const config=Object.fromEntries(['recent_events','older_images','older_megabytes'].map(name=>[name,Number(form.elements.namedItem(name).value)]));
 try {
  const setup=await request('api/setup');
  const saved=await request('api/retention',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':setup.token},body:JSON.stringify({config,revision})});
  revision=saved.revision;message.textContent='Saved. Limits apply at the next cleanup; protected evidence is kept.';
  form.querySelector('button').disabled=false;
 } catch(error) {
  revision=null;message.textContent='Save was not confirmed. Reload saved settings before retrying.';
 }
});
$('retention-reload').onclick=load;
window.addEventListener('hashchange',()=>{if(location.hash==='#settings'&&revision===null)load();});
function setOptional(id, text) {
 const node = $(id);
 node.textContent = text || '';
 node.hidden = !text;
}

function measurementTime(endpoint, timezone) {
 if (!endpoint?.captured_at) return 'Measurement time unavailable';
 const options = {year:'numeric', month:'short', day:'numeric', hour:'numeric', minute:'2-digit',
                  second:'2-digit', timeZoneName:'short'};
 if (timezone) options.timeZone = timezone;
 return new Date(endpoint.captured_at).toLocaleString(undefined, options);
}

function interval(start, end, timezone, onDay) {
 if (!start?.captured_at || !end?.captured_at) return 'Measurement time unavailable';
 const first = new Date(start.captured_at), last = new Date(end.captured_at);
 const day = new Intl.DateTimeFormat(undefined, {timeZone:timezone, year:'numeric', month:'short', day:'numeric'});
 const offset = new Intl.DateTimeFormat('en', {timeZone:timezone, timeZoneName:'shortOffset'});
 const zoneOf = date => offset.formatToParts(date).find(part => part.type === 'timeZoneName').value;
 if (day.format(first) !== day.format(last) || zoneOf(first) !== zoneOf(last)) {
   return measurementTime(start, timezone) + ' → ' + measurementTime(end, timezone);
 }
 const clock = new Intl.DateTimeFormat(undefined, {timeZone:timezone, hour:'numeric', minute:'2-digit', second:'2-digit'});
 if (onDay && day.format(new Date(onDay)) === day.format(first) && zoneOf(new Date(onDay)) === zoneOf(first)) {
   return clock.formatRange(first, last);
 }
 const zone = new Intl.DateTimeFormat(undefined, {timeZone:timezone,timeZoneName:'short'})
   .formatToParts(last).find(part => part.type === 'timeZoneName').value;
 return day.format(last) + ' · ' + clock.formatRange(first, last) + ' ' + zone;
}

function renderDaily(daily) {
 const estimate = daily?.low_use_estimate;
 const hasEstimate = estimate?.method === 'lower_bound_assumption_v1';
 $('usage-estimate').textContent = hasEstimate ? estimate.label : daily?.label || 'Daily usage unavailable';
 setOptional('usage-assumption', hasEstimate ? 'Low-use estimate assuming no extra gas in the gaps.' : daily ? 'Unresolved bounds' : '');
 setOptional('usage-bounds', hasEstimate ? 'Unresolved bounds · ' + daily.label : '');
 setOptional('usage-time', daily ? 'Measured ' + measurementTime(daily.through, daily.timezone) : '');
 $('daily-details').hidden = !daily;
 $('daily-method').textContent = daily ? [daily.day + ' · ' + daily.timezone + ' · Event ' + daily.through.event_id,
   hasEstimate ? estimate.assumption : daily.explanation].filter(Boolean).join('. ') : '';
}

function renderResumed(resumed) {
 const photo = resumed?.photo_supported;
 const estimate = resumed?.estimate;
 const zone = resumed?.timezone;
 const historical = photo && photo.through.event_id !== resumed.through.event_id;
 setOptional('usage-reviewed', photo ? photo.lower + '–' + photo.upper + ' ft³' :
             estimate ? 'About ' + estimate.value + ' ft³' : '');
 setOptional('photo-assumption', photo ? 'Photo-supported range. ' + photo.assumption.split(' Carried forward from reviewed event ')[0] :
             estimate ? 'Photo-supported estimate. ' + estimate.assumption : '');
 setOptional('photo-time', historical ? 'Photo result through ' + measurementTime(photo.through, zone) : '');
 $('usage-resumed').textContent = resumed ? 'Unresolved bounds · ' + resumed.label : 'Resumed usage unavailable';
 setOptional('usage-resumed-time', resumed ? 'Measured ' + measurementTime(resumed.through, zone) : '');
 const details = [];
 if (resumed) {
   details.push('From ' + measurementTime(resumed.start, zone) + ' through event ' + resumed.through.event_id + '.');
   if (photo) details.push('Photo result through event ' + photo.through.event_id + '. ' + photo.assumption);
   if (historical) details.push('Unresolved bounds at that earlier event · ' + photo.unresolved_lower + '–' + photo.unresolved_upper + ' ft³.');
   if (estimate) details.push('Photo-supported estimate of about ' + estimate.value + ' ft³ (' + estimate.lower + '–' + estimate.upper + ' ft³). ' + estimate.assumption);
   if (resumed.explanation) details.push(resumed.explanation);
 }
 $('usage-resumed-note').textContent = details.join(' ');
 $('resumed-details').hidden = !resumed;
}

function renderRecent(recent) {
 const zone = recent?.timezone;
 $('usage-hour').textContent = recent?.label || 'Hourly usage unavailable';
 setOptional('hour-time', recent ? interval(recent.hour.start, recent.through, zone) : '');
 const list = $('usage-quarters');
 list.replaceChildren();
 for (const quarter of recent?.quarters || []) {
   const row = document.createElement('li');
   const times = document.createElement('span');
   times.textContent = interval(quarter.start, quarter.through, zone, recent.through.captured_at);
   const amount = document.createElement('strong');
   amount.textContent = quarter.lower + '–' + quarter.upper + ' ft³';
   row.append(times, amount);
   list.append(row);
 }
 $('recent-details').hidden = !recent?.quarters?.length;
}

function render(state) {
 const usage = state?.mqtt?.usage;
 renderDaily(usage?.daily);
 renderResumed(usage?.resumed);
 renderRecent(usage?.recent);
}
window.AIEdgeIntegration={render};
if(location.hash==='#settings')load();
})();
