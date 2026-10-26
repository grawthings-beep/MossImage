'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const states = {queued:'待機中',preparing:'準備中',running:'生成中',completed:'完成',failed:'要確認',cancelled:'中止'};
let csrf = '', characters = {}, signature = '', submitting = false;
function notice(message) { $('notice').textContent=message; $('notice').hidden=!message; }
function readLocal(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
function writeLocal(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key,value); } catch (_) {} }
async function api(path, body, retry = true) {
  const response = await fetch('/studio/api'+path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json','X-Moss-CSRF':csrf}, body:JSON.stringify(body)});
  const data = await response.json();
  if (response.status===403 && data.code==='csrf_expired' && retry) {
    csrf=(await api('/bootstrap')).csrf_token;
    return api(path,body,false);
  }
  if (!response.ok) { const error=new Error(data.error || `HTTP ${response.status}`); error.status=response.status; throw error; }
  return data;
}
function form() { return {character:$('character').value,prompt:$('prompt').value,width:Number($('width').value),height:Number($('height').value),sampling:$('sampling').value,seed:Number($('seed').value),lora_strength:Number($('strength').value)}; }
function saveDraft() { writeLocal('moss-image-draft',JSON.stringify(form())); }
function preset() { $('prompt').value=characters[$('character').value].prompt; saveDraft(); }
function render(jobs) {
  const images=jobs.filter(j=>j.kind==='image');
  const next=JSON.stringify(images); if (signature===next) return; signature=next;
  $('results').innerHTML=images.length ? images.map(j=>`<article class="job-card"><div class="card-heading"><strong>${esc(j.title)}</strong><span class="job-state ${esc(j.state)}">${states[j.state] || esc(j.state)}</span></div><p class="job-message">${esc(j.message)}</p>${j.units.filter(u=>u.asset).map(u=>`<img style="width:100%;height:auto;border-radius:8px" src="/studio/api/assets/${encodeURIComponent(u.asset)}" alt="生成画像" loading="lazy"><div class="job-actions"><a class="button primary" href="/studio/api/assets/${encodeURIComponent(u.asset)}" download="moss-${esc(j.id)}.png">PNGを保存</a></div>`).join('')}<div class="job-actions"><a href="/studio/api/jobs/${encodeURIComponent(j.id)}/snapshot" download>設定・プロンプト</a>${['queued','preparing','running'].includes(j.state)?`<button data-job="${esc(j.id)}" data-action="cancel">生成を中止</button>`:''}${['failed','cancelled'].includes(j.state)?`<button data-job="${esc(j.id)}" data-action="resume">再開</button>`:''}</div></article>`).join('') : '<p class="empty">ここに完成画像が並びます。</p>';
}
async function poll() { const data=await api('/jobs'); render(data.jobs || data); }
async function submit(payload) {
  if (submitting) return;
  submitting=true; $('generate').disabled=true;
  writeLocal('moss-image-pending',JSON.stringify(payload));
  try {
    await api('/images',payload);
    writeLocal('moss-image-pending',null); notice(''); await poll().catch(()=>{});
    $('generate').textContent='画像を生成';
  } catch (error) {
    if (error.status >= 400 && error.status < 500) { writeLocal('moss-image-pending',null); notice(error.message); $('generate').textContent='画像を生成'; }
    else { notice(error.message+' 「送信を確認」で同じ生成を確認できます。'); $('generate').textContent='送信を確認'; }
  } finally { submitting=false; $('generate').disabled=false; }
}
$('generate').onclick=()=>{
  const pending=readLocal('moss-image-pending');
  submit(pending ? JSON.parse(pending) : {id:crypto.randomUUID(),...form()});
};
$('preset').onclick=preset;
$('character').onchange=preset;
$('random').onclick=()=>{ $('seed').value=crypto.getRandomValues(new Uint32Array(1))[0]; saveDraft(); };
for (const id of ['prompt','width','height','sampling','strength','seed']) $(id).oninput=saveDraft;
$('results').onclick=async event=>{
  const button=event.target.closest('[data-job]'); if (!button) return;
  button.disabled=true;
  try { await api('/jobs/'+button.dataset.job+'/'+button.dataset.action,{}); await poll(); }
  catch (error) { notice(error.message); button.disabled=false; }
};
(async()=>{
  try {
    const data=await api('/bootstrap'); csrf=data.csrf_token; characters=data.characters;
    $('character').innerHTML=Object.entries(characters).map(([id,c])=>`<option value="${esc(id)}">${esc(c.name)}</option>`).join('');
    $('character').value='scarlet'; $('prompt').value=characters.scarlet.prompt;
    const saved=JSON.parse(readLocal('moss-image-draft') || 'null');
    if (saved && characters[saved.character]) {
      for (const key of ['character','prompt','width','height','sampling','seed']) $(key).value=saved[key];
      $('strength').value=saved.lora_strength;
    }
    $('generate').disabled=false; render(data.jobs);
    const pending=readLocal('moss-image-pending'); if (pending) await submit(JSON.parse(pending));
  } catch (error) { notice(error.message); }
})();
setInterval(()=>{ if (!document.hidden) poll().catch(()=>notice('再接続待ちです。生成はPod側で続きます。')); },3500);
document.addEventListener('visibilitychange',()=>{ if (!document.hidden) poll().catch(()=>{}); });
