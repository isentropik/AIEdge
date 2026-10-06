(() => {
'use strict';
window.renderEventSelection=(selection,configuration)=>{
 const node=document.getElementById('event-selection-status');if(!node)return;
 const s=selection||{effective_mode:'FULL'};
 const mode={FULL:'Full recognition',EVENT_LAST_TWO:'Event recognition: final two dials',EVENT_FULL_FALLBACK:'Event recognition: full fallback'}[s.effective_mode]||'Recognition mode unavailable';
 const parts=[mode,'Capture cadence stays fixed. Alignment checks stay required.'];
 if(s.fixed_interval_seconds)parts.push('Configured interval: '+s.fixed_interval_seconds+' seconds.');
 if(s.last_decision)parts.push('Latest request: '+s.last_decision.mode+'. Reasons: '+(s.last_decision.reasons.join(', ')||'steady observation')+'. Cadence recommendation is advisory.');
 if(s.effective_mode!=='FULL')parts.push('To edit calibration, references or number format, choose FULL in Home Assistant app configuration and restart first. This creates a separate consumption segment; gaps stay unresolved. Unobserved dials are not fresh measurements.');
 if(s.failure||configuration?.state==='invalid')parts.push('Configuration or recognition is blocked. Correct configuration and restart; readings may be withheld.');
 node.textContent=parts.join(' ');
};
})();
