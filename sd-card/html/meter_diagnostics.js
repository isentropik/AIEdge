"use strict";
(function(root){
  const number = v => typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
  const count = v => number(v) === null ? "Unknown" : String(v);
  const seconds = v => number(v) === null ? "Unknown" : (v/1e6).toFixed(2)+" s";
  function timing(s) {
    const r=s.last||{}, start=number(r.start_us), end=number(r.end_us), capture=number(r.capture_us);
    const duration=start!==null && end!==null && end>0 && end>=start ? end-start : null;
    return [s.active===true?"A cycle is running.":s.active===false?"No cycle is currently running.":"Activity unknown.",
      "Completed: "+count(s.pipeline_completed)+" · Failed: "+count(s.failed),
      "Reader accepted: "+count(s.accepted_reader_cycles)+" (software result, not verified accuracy)",
      "Last cycle duration: "+seconds(duration),
      "Last capture interval: "+seconds(number(r.capture_interval_us)>0?r.capture_interval_us:null),
      "Capture to pipeline finish: "+seconds(capture>0&&end>=capture?end-capture:null),
      "Over 30 seconds: "+count(s.over_target)+" · Missed schedule slots: "+count(s.missed_schedule_slots),
      "Rejected overlapping attempts: "+count(s.overlaps_rejected)].join("\n");
  }
  function archive(s) {
    return [s.capture_enabled===true?"New captures are eligible for archival.":s.capture_enabled===false?"New capture archival is disabled.":"Capture archival status unknown.",
      "Pending: "+count(s.pending)+" · Blocked: "+count(s.blocked),
      "Upload acknowledgments: "+count(s.upload_acknowledgments),
      "Upload failures: "+count(s.upload_failures)+" · Cleanup failures: "+count(s.cleanup_failures),
      "Rejected captures: binding "+count(s.binding_rejected)+", handoff "+count(s.handoff_rejected)+", queue "+count(s.enqueue_rejected),
      "Archived images remain unreviewed and excluded from training."].join("\n");
  }
  function history(s) {
    if(s.active===true)return "A saved-history scan is running. Refresh to check its result.";
    if(!number(s.scanned_at_uptime_us))return "No saved-history scan result yet.";
    if(s.valid!==true)return "History is not available: "+String(s.reason||"Unknown reason");
    return "Completed segments: "+count(s.segments)+"\nCovered consumption: "+count(s.covered_minimum_ft3)+"–"+count(s.covered_maximum_ft3)+" ft³\nThis excludes the active segment and unresolved gaps. It is not a lifetime total.";
  }
  function accounting(s) {
    const d=s.display;if(!d||!['ft3','m3'].includes(d.unit))return "Choose compatible meter details to enable converted consumption display.";
    const unit=d.unit==='ft3'?'ft³':'m³',i=d.interval||{},c=d.cumulative_since_anchor||{};
    const quantity=v=>number(v)===null?'Unknown':Number(v.toPrecision(8))+' '+unit;
    return ['State: '+String(s.state||'unknown'),
      'Interval bounds: '+quantity(i.minimum)+' – '+quantity(i.maximum),
      'Interval estimate: '+quantity(i.estimate),
      'Average flow: '+(number(i.average_per_second)===null?'Unknown':quantity(i.average_per_second)+'/s'),
      'Since anchor'+(c.current===true?'':' (not current)')+': '+quantity(c.minimum)+' – '+quantity(c.maximum),
      'Cumulative estimate: '+quantity(c.current===true?c.estimate:null),
      'Unresolved whole turns remain unknown; these are not lifetime totals.'].join('\n');
  }
  async function request(fetcher,path,method="GET") {
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),5000);
    try {
      const response=await fetcher(path,{method,cache:"no-store",credentials:"same-origin",redirect:"error",signal:controller.signal});
      if(!response.ok)throw new Error("HTTP "+response.status);
      const data=await response.json();
      if(!data || typeof data!=="object" || Array.isArray(data))throw new Error("Invalid response");
      return data;
    } finally {clearTimeout(timer);}
  }
  function mount(doc,fetcher) {
    const refresh=doc.getElementById("refresh"),scan=doc.getElementById("scan"),status=doc.getElementById("status");let busy=false;
    async function run(scanFirst) {
      if(busy)return;busy=true;refresh.disabled=scan.disabled=true;
      status.textContent="Reading meter status…";
      let errors=0;
      try {
        if(scanFirst){
          await request(fetcher,"/meter_history","POST");
          status.textContent="Scan requested. Reading current status…";
        }
        for(const [id,path,render] of [["timing","/cycle_timing",timing],["archive","/image_archive_status",archive],["history","/meter_history",history],["accounting","/meter_accounting",accounting]]){
          const el=doc.getElementById(id);el.textContent="Refreshing…";
          try{el.textContent=render(await request(fetcher,path));}
          catch(error){errors++;el.textContent="Could not read current status: "+error.message;}
        }
        status.textContent=(errors?"Some sections could not refresh. ":"Status refreshed. ")+"No automatic polling. "+new Date().toLocaleTimeString();
      }catch(error){status.textContent="Scan request failed or its outcome is unknown: "+error.message+". Refresh status before trying again.";}
      finally{busy=false;refresh.disabled=scan.disabled=false;}
    }
    refresh.addEventListener("click",()=>run(false));scan.addEventListener("click",()=>run(true));
    return {refresh:()=>run(false),scan:()=>run(true)};
  }
  const api={timing,archive,history,accounting,request,mount};
  if(typeof module!=="undefined" && module.exports)module.exports=api;
  else mount(root.document,root.fetch.bind(root));
})(typeof window!=="undefined"?window:globalThis);
