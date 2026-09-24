"""Optional local human-label form; no receiver or training writes."""
import html,json,re

STYLE="""
fieldset{border:1px solid var(--line);border-radius:8px;margin:12px 0;padding:12px}
.reading-field{display:block;margin:12px 0}input,button{font:inherit;max-width:100%;padding:10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--text)}
.reading-field input{display:block;width:100%;margin-top:5px}input[type=checkbox]{width:20px;height:20px;vertical-align:middle}button{cursor:pointer;margin:10px 0}#review-message{overflow-wrap:anywhere}
"""

def validate_dials(dials):
    if not isinstance(dials,list) or not 1<=len(dials)<=16 or any(not isinstance(d,str) or not re.fullmatch(r'[a-zA-Z0-9_]{1,64}',d) for d in dials) or len(set(dials))!=len(dials):
        raise ValueError('Supply 1 to 16 distinct dial names using letters, numbers or underscores')

def fields(image_hash,dials):
    esc=html.escape
    inputs=''.join(f'<label class="reading-field">{esc(d)}<input data-dial="{esc(d)}" inputmode="decimal" autocomplete="off" placeholder="Number or unknown" aria-label="{esc(d)} reading"></label><label><input type="checkbox" data-unknown="{esc(d)}"> {esc(d)} unknown</label>' for d in dials)
    return f'<fieldset data-image="{image_hash}"><legend>Readings on the 0–10 scale</legend><label><input type="checkbox" data-include> Include this image in my answers</label>{inputs}<p class="muted">Use each dial’s numbering direction. Check unknown if you cannot read it; that takes priority over the number field. Blank fields are not saved as zero.</p></fieldset>'

def panel(config):
    data=json.dumps(config).replace('<',r'\u003c')
    return '<section><h2>Save your answers</h2><p>This downloads an answers file to your phone or computer. It does not upload images or add them to training. Entries are not saved until you download the file; keep it before closing this page.</p><label class="reading-field">Reviewer nickname<input id="reviewer" maxlength="100" autocomplete="off"></label><label>How did you review these?<select id="review-method"><option value="">Choose a method</option><option value="independent_reading">I read the dials myself</option><option value="confirmation_of_shown_estimate">I checked estimates shown to me</option></select></label><p>Check the dial names against your calibration before recording these answers.</p><button id="download-answers" type="button">Download my answers</button><p id="review-message" role="status" aria-live="polite"></p><noscript>JavaScript is needed to download answers. You can still view the original images.</noscript></section><script type="application/json" id="review-config">'+data+'</script><script>'+SCRIPT+'</script>'

SCRIPT=r"""
(function(){
'use strict';
function reading(text){
 const value=text.trim();
 if(value.toLowerCase()==='unknown')return null;
 if(!/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/.test(value))throw Error('Enter a number from 0 to below 10, or unknown.');
 const number=Number(value);if(!Number.isFinite(number)||number<0||number>=10)throw Error('Readings must be from 0 to below 10.');return number;
}
function answers(config,reviewer,method,rows){
 reviewer=reviewer.trim();if(!reviewer||reviewer.length>100)throw Error('Enter a reviewer nickname (up to 100 characters).');
 if(!['independent_reading','confirmation_of_shown_estimate'].includes(method))throw Error('Choose how you reviewed the readings.');
 const images=[],seen=new Set();
 for(const row of rows){
  if(!row.include)continue;
  if(!config.images.includes(row.hash)||seen.has(row.hash))throw Error('Unknown or repeated image.');
  seen.add(row.hash);const readings=Object.create(null);
  for(const dial of config.dials){if(typeof row.values[dial]!=='string')throw Error('Missing dial reading.');readings[dial]=reading(row.values[dial]);}
  images.push({image_sha256:row.hash,readings});
 }
 if(!images.length)throw Error('Select at least one image to include.');
 return {version:1,review_sha256:config.review_sha256,reviewer,method,dials:config.dials,images};
}
if(typeof module!=='undefined'&&module.exports)module.exports={reading,answers};
if(typeof document==='undefined')return;
const config=JSON.parse(document.getElementById('review-config').textContent);
document.getElementById('download-answers').addEventListener('click',()=>{
 const message=document.getElementById('review-message');
 try{
  const rows=Array.from(document.querySelectorAll('fieldset[data-image]'),field=>{
   const values=Object.create(null);for(const input of field.querySelectorAll('[data-dial]'))values[input.dataset.dial]=field.querySelector('[data-unknown="'+input.dataset.dial+'"]').checked?'unknown':input.value;
   return {hash:field.dataset.image,include:field.querySelector('[data-include]').checked,values};
  });
  const result=answers(config,document.getElementById('reviewer').value,document.getElementById('review-method').value,rows);
  const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='aiedge-answers-'+config.review_sha256.slice(0,12)+'.json';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
  message.textContent='Download requested. Check your downloads before closing. Images remain excluded from training.';
 }catch(error){message.textContent=error.message;}
});
})();
"""
