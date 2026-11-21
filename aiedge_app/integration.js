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
 const nominal = daily?.nominal_estimate;
 if (nominal?.method === 'range_midpoint_v1') {
  const stale = daily.status === 'stale';
  $('usage-estimate').textContent = displayedVolume(nominal.value_ft3, 2) + ' ft³';
  setOptional('usage-assumption', stale ? 'Stale · Last supported full-day estimate' : 'Midpoint of the unresolved daily bounds.');
  setOptional('usage-bounds', 'Unresolved bounds · ' + daily.label);
  setOptional('usage-time', measuredLine(daily.through, daily.timezone));
  $('daily-details').hidden = false;
  $('daily-method').textContent = nominal.assumption +
    (stale ? ' Conflicting meter event ' + daily.conflict_event_id + '.' : '');
  return {source:sourceOf(daily.through), day:daily.day, zone:daily.timezone, value:nominal.value_ft3,
    lower:daily.lower, upper:daily.upper, status:daily.status, method:nominal.method};
 }
 const estimate = daily?.low_use_estimate;
 const hasEstimate = estimate?.method === 'lower_bound_assumption_v1';
 $('usage-estimate').textContent = hasEstimate ? estimate.label : daily?.label || 'Daily usage unavailable';
 setOptional('usage-assumption', hasEstimate ? 'Low-use estimate assuming no extra gas in the gaps.' : daily ? 'Unresolved bounds' : '');
 setOptional('usage-bounds', hasEstimate ? 'Unresolved bounds · ' + daily.label : '');
 setOptional('usage-time', daily ? 'Measured ' + sourceLine(daily.through, daily.timezone) : '');
 $('daily-details').hidden = !daily;
 $('daily-method').textContent = daily ? [daily.day + ' · ' + daily.timezone + ' · Event ' + daily.through.event_id,
   hasEstimate ? estimate.assumption : daily.explanation].filter(Boolean).join('. ') : '';
 return daily && {source:sourceOf(daily.through), day:daily.day, zone:daily.timezone,
   value:hasEstimate ? estimate.value_ft3 : null, lower:daily.lower, upper:daily.upper, status:daily.status, method:estimate?.method};
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

function compactInterval(start, end, zone, reference) {
 const first = new Date(start.captured_at), last = new Date(end.captured_at);
 const sameDay = calendarDay(first, zone) === calendarDay(last, zone);
 const config = {timeZone:zone, hour:'numeric', minute:'2-digit'};
 if (!sameDay || !reference || calendarDay(first, zone) !== calendarDay(new Date(reference), zone)) {
   Object.assign(config, {month:'short', day:'numeric'});
 }
 const offset = new Intl.DateTimeFormat('en', {timeZone:zone, timeZoneName:'shortOffset'});
 const zoneOf = date => offset.formatToParts(date).find(part => part.type === 'timeZoneName').value;
 if (zoneOf(first) !== zoneOf(last)) return interval(start, end, zone);
 if (!reference) config.timeZoneName = 'short';
 return new Intl.DateTimeFormat(undefined, config).formatRange(first, last);
}

function completeHour(recent) {
 const quarters = recent?.quarters;
 // Only put four adjacent, source-bound intervals on a common time axis.
 return Array.isArray(quarters) && quarters.length === 4 && quarters.every((q, i) => {
   const start = sourceOf(q?.start), end = sourceOf(q?.through);
   return start && end && boundPair(q.lower, q.upper) && start.event_id < end.event_id &&
     Date.parse(start.captured_at) < Date.parse(end.captured_at) &&
     sameEvent(start, sourceOf(i ? quarters[i-1].through : recent.hour?.start));
 }) && sameEvent(sourceOf(quarters[3].through), sourceOf(recent.through));
}

function renderRecent(recent) {
 const zone = recent?.timezone;
 $('usage-hour').textContent = recent?.label || 'Hourly usage unavailable';
 setOptional('hour-time', sourceOf(recent?.hour?.start) && sourceOf(recent?.through) ? compactInterval(recent.hour.start, recent.through, zone) : '');
 const list = $('usage-quarters');
 list.replaceChildren();
 const sources = $('quarter-sources');
 sources.replaceChildren();
 const quarters = Array.isArray(recent?.quarters) ? recent.quarters : [];
 const complete = completeHour(recent);
 $('quarter-plot').hidden = !complete;
 window.AIEdgeCharts?.hour(complete ? recent : null);
 for (const quarter of quarters) {
   const row = document.createElement('li');
   const times = document.createElement('span');
   const timed = sourceOf(quarter?.start) && sourceOf(quarter?.through);
   times.textContent = timed ? compactInterval(quarter.start, quarter.through, zone, recent.through?.captured_at) : 'Measurement time unavailable';
   const source = document.createElement('li');
   source.textContent = timed ? interval(quarter.start, quarter.through, zone) + ' · Meter events ' + quarter.start.event_id + '–' + quarter.through.event_id : 'Source unavailable';
   sources.append(source);
   const amount = document.createElement('strong');
   amount.textContent = boundPair(quarter?.lower, quarter?.upper) ? quarter.lower + '–' + quarter.upper + ' ft³' : 'Range unavailable';
   row.append(times, amount);
   list.append(row);
 }
 $('recent-details').hidden = !recent?.quarters?.length;
}

function boundPair(lo, hi) {
 return [lo, hi].every(n => (typeof n === 'string' && n.trim() || typeof n === 'number') && Number.isFinite(Number(n))) &&
   Number(lo) >= 0 && Number(lo) <= Number(hi);
}

function sourceOf(value) {
 if (!value || !Number.isInteger(value.event_id) || value.event_id <= 0 || !/^[0-9a-f]{64}$/.test(value.source_sha256)) return null;
 const time = value.measured_at || value.captured_at;
 return Number.isFinite(Date.parse(time)) ? {event_id:value.event_id, source_sha256:value.source_sha256, captured_at:time} : null;
}

function sameEvent(a, b) {
 return a && b && a.event_id === b.event_id && a.source_sha256 === b.source_sha256 && a.captured_at === b.captured_at;
}

function sourceLine(endpoint, zone) {
 return measurementTime(endpoint, zone) + ' · Meter event ' + endpoint.event_id;
}

function calendarDay(date, zone) {
 return new Intl.DateTimeFormat('sv-SE', {timeZone:zone, year:'numeric', month:'2-digit', day:'2-digit'}).format(date);
}

function renderOverviewDaily(nominal, daily) {
 setOptional('daily-event', '');
 const measured = sourceOf(nominal);
 const end = sourceOf(daily?.through);
 const day = nominal?.day;
 const zone = nominal?.timezone;
 const numeric = boundPair(nominal?.value_ft3, nominal?.value_ft3);
 const supported = measured && numeric && day === calendarDay(new Date(measured.captured_at), zone);
 const ranged = end && daily.day === calendarDay(new Date(), daily.timezone) &&
   daily.day === calendarDay(new Date(end.captured_at), daily.timezone) && boundPair(daily.lower, daily.upper);
 const midpoint = ranged && daily.nominal_estimate?.method === 'range_midpoint_v1';
 if (midpoint && (!supported || day !== daily.day || end.event_id > measured.event_id ||
     (sameEvent(end, measured) && (daily.status === 'stale' || nominal.method !== 'range_midpoint_v1')))) {
   setOptional('daily-event', 'Meter event ' + end.event_id);
   return renderDaily(daily);
 }
 if (!supported) {
   if (numeric && nominal.status === 'opening_balance' && day === calendarDay(new Date(), zone)) {
     renderDaily(null);
     $('usage-estimate').textContent = displayedVolume(nominal.value_ft3, 2) + ' ft³';
     setOptional('usage-assumption', 'Opening balance · Partial coverage');
     setOptional('usage-time', 'Awaiting the first measurement for ' + day + '.');
   } else {
     if (ranged) setOptional('daily-event', 'Meter event ' + end.event_id);
     return renderDaily(ranged ? daily : null);
   }
   return;
 }
 const previous = day !== calendarDay(new Date(), zone);
 const partial = nominal.status === 'partial_coverage' || nominal.method === 'observed_increments';
 const stale = nominal.status === 'stale';
 const held = nominal.status === 'held_at_last_reading';
 $('usage-estimate').textContent = displayedVolume(nominal.value_ft3, 2) + ' ft³';
 setOptional('usage-assumption', [previous ? 'Previous day’s estimate' : '', stale ? 'Stale · Last supported full-day estimate' :
   partial ? 'Partial coverage · Observed usage only' : 'Estimated from the daily range', held ? 'Last supported reading' : ''].filter(Boolean).join(' · '));
 setOptional('usage-time', measuredLine(measured, zone));
 setOptional('daily-event', 'Meter event ' + measured.event_id);
 const native = boundPair(nominal.lower_ft3, nominal.upper_ft3);
 let bounds = native ? 'Unresolved bounds · ' + Number(nominal.lower_ft3).toFixed(2) + '–' + Number(nominal.upper_ft3).toFixed(2) + ' ft³' : '';
 if (ranged && daily.day === day && (sameEvent(end, measured) || (!native && end.event_id !== measured.event_id))) {
   bounds = 'Unresolved bounds · ' + daily.label + (sameEvent(end, measured) ? '' : ' · ' + sourceLine(end, zone));
 }
 setOptional('usage-bounds', bounds || (partial ? 'Full-day bounds pending' : ''));
 $('daily-details').hidden = false;
 $('daily-method').textContent = [nominal.assumption, stale && nominal.conflict_event_id ? 'Conflicting meter event ' + nominal.conflict_event_id + '.' : ''].filter(Boolean).join(' ');
 // Only bounds measured at the selected meter event belong to this plotted point.
 const matching = ranged && daily.day === day && daily.timezone === zone && sameEvent(end,measured);
 return {source:measured, day, zone, value:nominal.value_ft3,
   lower:matching ? daily.lower : native ? nominal.lower_ft3 : null,
   upper:matching ? daily.upper : native ? nominal.upper_ft3 : null,
   status:nominal.status, method:nominal.method};
}

// Display rounding never feeds the ledger or the Home Assistant sensors.
function displayedVolume(value, places, roundingMode = 'halfExpand') {
 return new Intl.NumberFormat(undefined, {maximumFractionDigits:places, minimumFractionDigits:places, roundingMode}).format(value);
}

function measuredLine(endpoint, zone) {
 return 'Measured ' + measurementTime(endpoint, zone);
}

function renderAbsolute(absolute, zone) {
 const end = sourceOf(absolute);
 const match = /^(\d+)(\.\d+)?$/.exec(String(absolute?.value_ft3));
 const valid = end && match;
 $('absolute-value').textContent = valid ? displayedVolume(absolute.value_ft3, 1) + ' ft³' : 'Awaiting a meter reading';
 setOptional('absolute-raw', valid ? 'Full sensor value · ' + absolute.value_ft3 + ' ft³' : '');
 setOptional('absolute-event', valid ? 'Meter event ' + end.event_id : '');
 setOptional('absolute-status', valid ? {partial_coverage:'Partial coverage',held_at_last_reading:'Held at last measurement'}[absolute.status] || 'Nominal reading' : '');
 setOptional('absolute-time', valid ? measuredLine(end, zone) : '');
 const list = $('absolute-bands');
 list.replaceChildren();
 for (const band of valid ? absolute.bands_ft3 || [] : []) {
   if (!Array.isArray(band) || !boundPair(...band)) continue;
   const li = document.createElement('li');
   li.textContent = displayedVolume(band[0], 2, 'floor') + '–' + displayedVolume(band[1], 2, 'ceil') + ' ft³';
   list.append(li);
 }
 setOptional('absolute-method', valid && absolute.assumption);
 $('absolute-details').hidden = !valid;
}

function renderHistory(segment, daily, zone, policy) {
 const end = sourceOf(segment);
 const verified = end && Number.isFinite(segment.value) && segment.value > 0;
 $('segment-value').textContent = verified ? displayedVolume(segment.value, 2) + ' ft³' : 'Awaiting a verified segment estimate';
 setOptional('segment-time', verified ? measuredLine(end, zone) : '');
 $('segment-details').hidden = !verified;
 setOptional('segment-raw', verified ? String(segment.value) + ' ft³ · Meter event ' + end.event_id : '');
 setOptional('segment-start', verified ? 'Gas used since ' + measurementTime({captured_at:segment.segment_started_at}, zone) : '');
 const elapsed = daily?.elapsed_range;
 const through = sourceOf(elapsed?.through);
 const qualified = sameEvent(through, sourceOf(daily?.through)) && sourceOf(elapsed?.start) &&
   daily.day === calendarDay(new Date(), daily.timezone) && boundPair(elapsed?.lower, elapsed?.upper);
 $('elapsed-value').textContent = qualified ? elapsed.lower + '–' + elapsed.upper + ' ft³' : 'No supported range for this recovery period';
 setOptional('elapsed-time', qualified ? interval(elapsed.start, through, zone) + ' · Meter event ' + through.event_id : '');
 const conditions = [];
 if (qualified && policy?.capacity_cfh > 0) conditions.push('Household ceiling ' + policy.capacity_cfh + ' ft³/hour.');
 if (qualified && elapsed.method === 'saved_prefix_constraints_v1' && policy?.slow_allowance_ft3 > 0) conditions.push('Slow-dial allowance ±' + policy.slow_allowance_ft3 + ' ft³.');
 setOptional('elapsed-method', qualified ? conditions.concat('Usage during gaps is unknown.').join(' ') : '');
}

function render(state) {
 const mqtt = state?.mqtt;
 const usage = mqtt?.usage || {};
 const other = mqtt?.overview_meter === 'other' || mqtt?.state === 'disabled';
 $('gas-overview').hidden = other;
 if (other && !$('capture-operations').dataset.initialized) $('capture-operations').open = true;
 if (mqtt?.overview_meter || mqtt?.state === 'disabled') $('capture-operations').dataset.initialized = 'true';
 const zone = usage.daily_nominal?.timezone || usage.daily?.timezone || usage.resumed?.timezone || usage.recent?.timezone || mqtt?.overview_timezone;
 const headline = renderOverviewDaily(usage.daily_nominal, usage.daily);
 if (['','#overview'].includes(location.hash)) window.AIEdgeCharts?.day(other ? null : usage.daily,other ? null : headline);
 renderAbsolute(usage.absolute_nominal, zone);
 if (mqtt?.overview_connected === false || mqtt?.nominal_error) {
   if (sourceOf(usage.daily_nominal)) $('usage-assumption').append(' · Last published measurement');
 }
 if (mqtt?.overview_connected === false || mqtt?.range_error) {
   if (sourceOf(usage.absolute_nominal)) $('absolute-status').append(' · Last published measurement');
 }
 renderRecent(usage.recent);
 renderResumed(usage.resumed);
 renderHistory(usage.historical, usage.daily, zone, mqtt?.overview_policy);
}
window.AIEdgeIntegration={render};
if(location.hash==='#settings')load();
})();
