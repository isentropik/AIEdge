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
