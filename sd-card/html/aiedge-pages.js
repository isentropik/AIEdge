/* Page layout only; never writes device settings or triggers captures. */
(()=>{'use strict';function init(){
 const body=document.body;body.dataset.page=location.pathname.split('/').pop();if(body.classList.contains('ae-app'))return;
 if(!body.classList.contains('ae-page'))body.classList.add('ae-tool');
 if(window.top===window.self){const header=document.createElement('header');header.className='ae-tool-header';const home=document.createElement('a');home.href='/';home.textContent='AIEdge';header.append(home);const picker=document.querySelector('.aiedge-theme-picker');if(picker)header.append(picker);body.prepend(header);}
 const digital=document.getElementById('Category_Digits_enabled');if(digital){digital.checked=false;digital.disabled=true;document.querySelectorAll('[id^="Digits_"],[id^="Category_Digits"]').forEach(el=>{const row=el.closest('tr');if(row)row.classList.add('ae-digital-disabled');});}
 if(document.getElementById('Category_Analog_enabled')&&location.pathname.includes('edit_config')){
  body.classList.add('ae-settings');const source=document.querySelector('table.table');
  if(source){let section=null,table=null;const sections=document.createElement('div');sections.className='ae-settings-sections';source.before(sections);
   for(const row of [...source.rows]){const heading=[...row.cells].map(cell=>cell.querySelector(':scope > h4')).find(Boolean);if(heading){section=document.createElement('details');section.className='ae-settings-section';section.open=sections.children.length===0;const summary=document.createElement('summary');summary.append(heading);section.append(summary);table=document.createElement('table');section.append(table);sections.append(section);if(heading.querySelector('[id^="Category_Digits"]'))section.classList.add('ae-digital-disabled');}
    else if(table)table.append(row);
   }source.remove();
  }
 }
}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();})();
