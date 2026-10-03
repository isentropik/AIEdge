/* Contextual feedback; a shared outage is shown once on the visible page. */
(() => {
'use strict';
const $=id=>document.getElementById(id);
function connection(error){
 return error?.name==='TimeoutError'||[502,503,504].includes(error?.status)||
  error?.name==='TypeError'&&/fetch|network|load failed/i.test(error.message);
}
function message(error,fallback='The request could not be completed.'){
 if(error?.name==='TimeoutError')return 'AIEdge did not respond in time. Try again when the app is available.';
 if(error?.name==='TypeError'&&connection(error))return 'Could not reach AIEdge. Check its connection and try again.';
 if(error?.status===403)return 'Access could not be verified. Reopen AIEdge from Home Assistant.';
 return error?.message||fallback;
}
function sync(){
 const global=$('error');
 const route=typeof location==='undefined'?'':location.hash;
 const inScope=element=>!element.dataset.noticeScope||
  (element.dataset.noticeScope==='editor'?['#calibration','#setup/image','#setup/alignment','#setup/dials'].includes(route):route===element.dataset.noticeScope);
 for(const element of document.querySelectorAll('[data-notice-scope]'))element.hidden=!element.textContent||!inScope(element);
 const elements=[...document.querySelectorAll('[data-notice-kind="connection"]')];
 const wanted=element=>!!element.textContent&&element.dataset.noticeRequested!=='false'&&inScope(element)&&!element.parentElement?.closest('[hidden]');
 const locals=elements.filter(element=>element!==global&&wanted(element));
 const specific=locals.some(element=>element.id!=='setup-status');
 for(const element of elements){
  if(element===global)element.hidden=!element.textContent||locals.length>0;
  else element.hidden=!wanted(element)||(specific&&element.id==='setup-status');
 }
}
function show(id,text,error=false,isConnection=false,scope=null){
 const element=$(id);if(!element)return;
 element.textContent=text;element.hidden=!text;element.dataset.error=String(error);
 element.dataset.noticeRequested=String(!!text);
 if(scope)element.dataset.noticeScope=scope;else delete element.dataset.noticeScope;
 element.dataset.noticeKind=isConnection?'connection':'action';sync();
}
window.AIEdgeNotices={show,sync,connection,message};
})();
