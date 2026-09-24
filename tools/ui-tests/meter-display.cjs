const assert=require('node:assert/strict');
const {accounting}=require('../../sd-card/html/meter_diagnostics.js');
assert.match(accounting({}),/compatible meter details/);
const s={state:'interval',display:{unit:'m3',interval:{minimum:.1,maximum:.2,estimate:null,average_per_second:null},cumulative_since_anchor:{current:false,minimum:.3,maximum:.4,estimate:.35}}};
const text=accounting(s);assert.match(text,/0.1 m\u00b3/);assert.match(text,/Interval estimate: Unknown/);assert.match(text,/Average flow: Unknown/);assert.match(text,/not current/);assert.match(text,/Cumulative estimate: Unknown/);
s.display.unit='ft3';s.display.cumulative_since_anchor.current=true;assert.match(accounting(s),/0.35 ft\u00b3/);
s.display.interval.minimum=NaN;assert.match(accounting(s),/Interval bounds: Unknown/);
console.log('Consumption UI preserves unknown estimates, stale segments and explicit units');

const {history}=require('../../sd-card/html/meter_diagnostics.js');
const h={scanned_at_uptime_us:123,valid:true,segments:2,covered_minimum_ft3:1000,covered_maximum_ft3:2000,display:{unit:'m3',minimum:28.316846592,maximum:56.633693184}};
assert.match(history(h),/28.316847–56.633693 m³/);
assert.match(history(h),/not a lifetime total/);
assert.match(history(h),/unresolved gaps/);
for(const [lo,hi] of [[null,56],[NaN,56],[30,20],[-1,20],[0,Infinity]]){
 h.display.minimum=lo;h.display.maximum=hi;assert.match(history(h),/Covered consumption: Unknown/);
 assert.doesNotMatch(history(h),/1000/);
}
h.display={unit:'ft3',minimum:0,maximum:0};assert.match(history(h),/0–0 ft³/);
h.display=null;assert.match(history(h),/1000–2000 ft³ \(stored units\)/);
h.valid=false;assert.match(history(h),/History is not available/);
h.valid=true;h.active=true;assert.match(history(h),/scan is running/);
console.log('History display conversion, unknown bounds, canonical fallback and scan state passed');

// Real retained-frame discrepancy: explain the rejection without changing readings.
const {accountingReason}=require('../../sd-card/html/meter_diagnostics.js');
const rejected={reason:'main_dials_inconsistent',state:'rejected',assumptions:{main_dial_error:0.1},raw_observation:{main_dial_positions:[0.289215684,2.50806093,5.60520554,5.34,4.78]}};
const before=JSON.stringify(rejected);
assert.match(accountingReason(rejected),/Main dial 4 reads 5.340; dial 5 implies 5.478/);
assert.match(accountingReason(rejected),/Difference 0.138 exceeds 0.110/);
assert.equal(JSON.stringify(rejected),before);
assert.match(accounting(rejected),/Main dials disagree/); // Also visible without display preference.
for(const bad of [null,[],[0,1,null,3,4],[0,1,2,3,10],[0,1,NaN,3,4]]) {
 const r={...rejected,raw_observation:{main_dial_positions:bad}};
 assert.doesNotMatch(accountingReason(r),/Main dial 4|implies|NaN/);
 assert.match(accountingReason(r),/unavailable/);
}
const wrap={...rejected,raw_observation:{main_dial_positions:[9.999998,9.99998,9.9998,9.998,9.98]}};
assert.doesNotMatch(accountingReason(wrap),/exceeds/);
assert.equal(accountingReason({}), '');
assert.equal(accountingReason({reason:'whole_turn_count_unresolved'}),'Reason: whole turn count unresolved');

// Exercise the actual page IDs and refresh path, including accounting failures.
(async()=>{
 const fs=require('node:fs'),path=require('node:path');
 const html=fs.readFileSync(path.join(__dirname,'../../sd-card/html/meter_diagnostics.html'),'utf8');
 const nodes={};
 for(const match of html.matchAll(/id="([^"]+)"/g))nodes[match[1]]={textContent:'Not loaded.',disabled:false,addEventListener(){},set innerHTML(v){throw Error('Use textContent for device data');}};
 const {mount}=require('../../sd-card/html/meter_diagnostics.js');
 const data={...rejected,display:{unit:'ft3',interval:{minimum:null,maximum:null,estimate:null,average_per_second:null},cumulative_since_anchor:{current:false,minimum:1,maximum:2,estimate:null}}};
 const calls=[];let fail=false;
 const ui=mount({getElementById:id=>nodes[id]},async(url,options)=>{
  calls.push({url,method:options.method});
  if(url==='/meter_accounting'&&fail)throw Error('offline');
  return {ok:true,json:async()=>url==='/meter_accounting'?data:{}};
 });
 assert.equal(calls.length,0);
 await ui.refresh();
 assert.deepEqual(calls.map(x=>x.url),['/cycle_timing','/image_archive_status','/meter_history','/meter_accounting']);
 assert(calls.every(x=>x.method==='GET'));
 assert.match(nodes.accounting.textContent,/Main dial 4 reads 5.340/);
 assert.match(nodes.accounting.textContent,/Interval estimate: Unknown/);
 assert.match(nodes.accounting.textContent,/Average flow: Unknown/);
 assert.match(nodes.accounting.textContent,/Cumulative estimate: Unknown/);
 assert.match(nodes.status.textContent,/^Status refreshed/);
 fail=true;await ui.refresh();
 assert.equal(nodes.accounting.textContent,'Could not read current status: offline');
 assert.doesNotMatch(nodes.accounting.textContent,/5.340/); // No stale rejected observation.
 assert.match(nodes.status.textContent,/Some sections could not refresh/);
 assert.equal(nodes.refresh.disabled,false);assert.equal(nodes.scan.disabled,false);
 fail=false;data.reason='<img src=x onerror=bad>';await ui.refresh();
 assert.match(nodes.accounting.textContent,/<img/); // Literal text only.
 console.log('Actual page IDs, all four GETs, rejection details, unknown estimates and failed-refresh stale-data removal passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
