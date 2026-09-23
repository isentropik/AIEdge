import assert from 'node:assert/strict';
import {discoverWithRecovery} from './discovery.mjs';
async function scenario(outcomes,resetError){
 const calls=[];let n=0;
 try{const value=await discoverWithRecovery({connect:async timeout=>{calls.push(['connect',timeout]);const result=outcomes[n++];if(result instanceof Error)throw result;return result;},reset:async()=>{calls.push(['reset']);if(resetError)throw resetError;},pause:async ms=>calls.push(['pause',ms]),status:s=>calls.push(['status',s]),isPortBusy:e=>e.message==='busy'});return {value,calls};}catch(error){return {error,calls};}
}
const ok=await scenario(['ready']);assert.equal(ok.value,'ready');assert.deepEqual(ok.calls,[['connect',1500]]);
const recovered=await scenario([new Error('not detected'),'ready']);assert.equal(recovered.value,'ready');assert.deepEqual(recovered.calls.filter(x=>x[0]!=='status'),[['connect',1500],['reset'],['pause',2500],['connect',30000]]);
const failed=await scenario([new Error('not detected'),new Error('still absent')]);assert.equal(failed.error.message,'still absent');assert.equal(failed.calls.filter(x=>x[0]==='reset').length,1);assert.equal(failed.calls.filter(x=>x[0]==='connect').length,2);
const busy=await scenario([new Error('busy')]);assert.equal(busy.error.message,'busy');assert.equal(busy.calls.length,1);
const resetFailed=await scenario([new Error('not detected')],new Error('reset unsupported'));assert.equal(resetFailed.error.message,'reset unsupported');assert.equal(resetFailed.calls.filter(x=>x[0]==='connect').length,1);
console.log('PASS: healthy connection untouched; automatic reset/retry; bounded failure; busy port untouched; reset errors surfaced.');
