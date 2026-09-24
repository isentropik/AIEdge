const assert=require('node:assert/strict');
const api=require('../../sd-card/html/meter-profile.js');
const gas={version:1,kind:'gas',source_unit:'ft3',display_unit:'m3',units_per_count:1,has_secondary:true,secondary_units_per_revolution:5,confirmed:true};
const initial={revision:'a'.repeat(64),profile:null,model_compatible:false,activation:'not_integrated'};
function doc(){const nodes={};for(const id of ['profile-message','profile-load','profile-save','profile-fields','profile-form','meter-kind','meter-source','meter-display','meter-multiplier','meter-secondary','meter-revolution','meter-confirm','secondary-fields','scale-lock'])nodes[id]={value:'',checked:false,disabled:false,children:[],events:{},addEventListener(k,v){this.events[k]=v;},replaceChildren(){this.children=[];this.value='';},append(v){this.children.push(v);}};return {nodes,getElementById:id=>nodes[id],createElement:()=>({})};}
(async()=>{
 for(const kind of Object.keys(api.choices))for(const unit of api.choices[kind])assert.equal(api.validateProfile({...gas,kind,source_unit:unit,display_unit:unit}).kind,kind);
 for(const patch of [{kind:'other'},{source_unit:'L'},{display_unit:'kWh'},{units_per_count:0},{units_per_count:Infinity},{secondary_units_per_revolution:0},{has_secondary:false},{confirmed:false}])assert.throws(()=>api.validateProfile({...gas,...patch}));
 for(const value of [null,{}, {...initial,revision:'bad'},{...initial,activation:'unsupported'}, {...initial,profile:{}}])assert.throws(()=>api.validateSaved(value));
 const d=doc(),calls=[];let status=200,result=initial;
 const ui=api.mount(d,async(url,options)=>{calls.push([url,options]);return {ok:status===200,status,json:async()=>result};});
 assert(d.nodes['profile-save'].disabled);await ui.load();assert(!d.nodes['profile-save'].disabled);assert.equal(d.nodes['meter-kind'].value,'');
 await ui.save();assert.equal(calls.length,1,'Missing fields must not write');
 d.nodes['meter-kind'].value='gas';d.nodes['meter-kind'].events.change();assert.deepEqual(d.nodes['meter-source'].children.map(x=>x.value),['','ft3','m3']);
 for(const [id,value] of Object.entries({'meter-source':'ft3','meter-display':'m3','meter-multiplier':'1','meter-revolution':'5'}))d.nodes[id].value=value;
 d.nodes['meter-secondary'].checked=true;d.nodes['meter-secondary'].events.change();assert(!d.nodes['secondary-fields'].hidden);
 d.nodes['meter-confirm'].checked=true;result={status:'saved_not_active',active_changed:false};await ui.save();
 assert.deepEqual(JSON.parse(calls.at(-1)[1].body),gas);assert.equal(calls.at(-1)[1].headers['X-AIEdge-Revision'],initial.revision);assert.equal(calls.at(-1)[1].redirect,'error');assert.match(d.nodes['profile-message'].textContent,/not active/);assert(d.nodes['profile-save'].disabled);
 const count=calls.length;await ui.save();assert.equal(calls.length,count,'No retry after uncertain or successful write without reloading');
 result={...initial,profile:gas,model_compatible:true};await ui.load();assert(d.nodes['meter-kind'].disabled);assert(!d.nodes['meter-display'].disabled);assert(!d.nodes['meter-confirm'].checked);
 d.nodes['meter-confirm'].checked=true;status=409;result={error:'conflict'};await ui.save();assert.match(d.nodes['profile-message'].textContent,/Reload/);assert(d.nodes['profile-save'].disabled);
 status=200;result=initial;await ui.load();assert(!d.nodes['meter-kind'].disabled);
 d.nodes['meter-confirm'].checked=true;d.nodes['profile-form'].events.input();assert(!d.nodes['meter-confirm'].checked);
 result={...initial,profile:gas,model_compatible:true,activation:'display_only'};await ui.load();assert.match(d.nodes['profile-message'].textContent,/Display units are active/);
 d.nodes['meter-confirm'].checked=true;result={status:'saved_display_only',active_changed:true};await ui.save();assert.match(d.nodes['profile-message'].textContent,/apply now/);
 console.log('Meter form checks passed: units, scale validation, explicit confirmation, saved/active distinction, conflict, locking and no implicit retries');
})().catch(e=>{console.error(e);process.exitCode=1;});
