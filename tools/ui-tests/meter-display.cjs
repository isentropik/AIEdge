const assert=require('node:assert/strict');
const {accounting}=require('../../sd-card/html/meter_diagnostics.js');
assert.match(accounting({}),/compatible meter details/);
const s={state:'interval',display:{unit:'m3',interval:{minimum:.1,maximum:.2,estimate:null,average_per_second:null},cumulative_since_anchor:{current:false,minimum:.3,maximum:.4,estimate:.35}}};
const text=accounting(s);assert.match(text,/0.1 m\u00b3/);assert.match(text,/Interval estimate: Unknown/);assert.match(text,/Average flow: Unknown/);assert.match(text,/not current/);assert.match(text,/Cumulative estimate: Unknown/);
s.display.unit='ft3';s.display.cumulative_since_anchor.current=true;assert.match(accounting(s),/0.35 ft\u00b3/);
s.display.interval.minimum=NaN;assert.match(accounting(s),/Interval bounds: Unknown/);
console.log('Consumption UI preserves unknown estimates, stale segments and explicit units');
