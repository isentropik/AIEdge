import assert from 'node:assert/strict';
import {flashWithSpeedFallback} from './flash-speed.mjs';
const fail = (code, name='Error') => ({state:'error',message:code,details:{error:code,details:{name}}});
async function scenario(attempts, eraseFirst=false) {
  const calls=[], events=[]; let pending=false;
  await flashWithSpeedFallback(async (emit, baud, erase) => {
    assert.equal(pending,false,'prior transport must finish cleanup before retry');
    pending=true; calls.push({baud,erase});
    for (const event of attempts[calls.length-1]) {
      if (event instanceof Error) throw event;
      emit(event);
    }
    await Promise.resolve(); pending=false;
  }, event => {
    if (event.state==='error') assert.equal(pending,false,'dialog must not reopen a port during cleanup');
    events.push(event);
  }, eraseFirst);
  return {calls,events};
}
const done={state:'finished',message:'done'};
const fast=await scenario([[done]]);
assert.deepEqual(fast.calls,[{baud:460800,erase:false}]);
const init=await scenario([[fail('failed_initialize')],[done]],true);
assert.deepEqual(init.calls,[{baud:460800,erase:true},{baud:115200,erase:true}]);
assert.equal(init.events.filter(e=>e.state==='error').length,0);
assert(init.events.some(e=>e.details?.slowFallback));
const write=await scenario([[{state:'erasing',details:{done:true}},fail('write_failed')],[{state:'initializing'},done]],true);
assert.deepEqual(write.calls,[{baud:460800,erase:true},{baud:115200,erase:false}]);
assert(write.events.some(e=>e.message==='Retrying USB installation at 115,200 baud…'));
const noErase=await scenario([[fail('write_failed')],[done]]);
assert(noErase.calls.every(c=>!c.erase));
const failed=await scenario([[fail('write_failed')],[fail('write_failed')]]);
assert.equal(failed.calls.length,2);
assert.equal(failed.events.filter(e=>e.state==='error').length,1);
assert(!failed.events.some(e=>e.state==='finished'));
for (const code of ['not_supported','failed_firmware_download']) {
  const r=await scenario([[fail(code)]]);assert.equal(r.calls.length,1);assert.equal(r.events.at(-1).state,'error');
}
for (const name of ['NotAllowedError','NotFoundError','InvalidStateError','SecurityError']) {
  const r=await scenario([[fail('failed_initialize',name)]]);assert.equal(r.calls.length,1);
}
let runs=0;const cleanupEvents=[];
await flashWithSpeedFallback(async emit=>{runs++;emit(fail('write_failed'));throw Error('cleanup failed');},e=>cleanupEvents.push(e),false);
assert.equal(runs,1);assert.equal(cleanupEvents.at(-1).details.error,'usb_recovery_failed');
console.log('PASS: fast success; one slow fallback after clean init/write failure; no extra erase; final error; no unsupported/permission/cleanup retries.');
