'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uuid = () => crypto.randomUUID();
const clone = value => JSON.parse(JSON.stringify(value));
const assetURL = id => `/studio/api/assets/${encodeURIComponent(id)}`;
const active = ['queued', 'preparing', 'running'];
const states = {queued:'待機中', preparing:'準備中', running:'生成中', completed:'完成', failed:'要確認', cancelled:'中止'};
let project, pageId, projects = [], jobs = [], selected = null, currentTab = 'page';
let version = 0, savedVersion = 0, saving = null, saveTimer, previewURL, previewRequest = 0, busy = false;
let jobsSignature = '', pendingRequest = null;
let csrfToken = '';

function notice(message, good = false) {
  $('notice').hidden = !message;
  $('notice').textContent = message || '';
  $('notice').className = good ? 'success' : '';
}
async function api(path, options = {}, retryCsrf = true) {
  const headers = {'X-Moss-Studio':'1', 'X-Moss-CSRF':csrfToken, ...options.headers};
  let body = options.body;
  if (body && !(body instanceof Blob)) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }
  const response = await fetch('/studio/api' + path, {...options, headers, body});
  const data = await response.json().catch(() => ({error:`通信に失敗しました（${response.status}）。`}));
  if (response.status === 403 && data.code === 'csrf_expired' && retryCsrf) {
    // The server rejected this before executing it, so one token-refresh retry
    // is safe even for uploads and generation submissions.
    await api('/bootstrap', {}, false);
    return api(path, options, false);
  }
  if (!response.ok) {
    const error = new Error(data.error || `通信エラー ${response.status}`);
    error.status = response.status;
    throw error;
  }
  if (path === '/bootstrap' && data.csrf_token) csrfToken = data.csrf_token;
  return data;
}
const page = () => project.pages.find(p => p.id === pageId);
const pagePath = () => `/projects/${project.id}/pages/${pageId}`;
const safely = fn => async (...args) => { try { await fn(...args); } catch (error) { notice(error.message); } };
const draftKey = id => 'moss-studio-draft:' + id;
function localSet(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (_) {} }
function localGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
function changed() {
  version++;
  $('save-state').textContent = '保存待ち…';
  localSet(draftKey(project.id), JSON.stringify(project));
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => flush().catch(error => notice(error.message)), 650);
}
async function flush() {
  clearTimeout(saveTimer);
  if (saving) { await saving; if (savedVersion < version) return flush(); return; }
  if (!project || savedVersion === version) return;
  saving = (async () => {
    try {
      while (savedVersion < version) {
        const sentVersion = version;
        $('save-state').textContent = 'RunPodに保存中…';
        const updated = await api('/projects/' + project.id, {method:'PUT', body:clone(project)});
        project.revision = updated.revision;
        savedVersion = sentVersion;
        localSet(draftKey(project.id), savedVersion === version ? null : JSON.stringify(project));
      }
      $('save-state').textContent = 'RunPodに保存済み';
      const entry = projects.find(p => p.id === project.id);
      if (entry) { entry.title = project.title; entry.pages = project.pages.length; }
      projectList();
      refreshPreview();
    } catch (error) {
      $('save-state').textContent = '未保存 · この画面の下書きを保持';
      if (error.status === 409) error.message += ' 未保存の編集はこのブラウザーの下書きに残しています。';
      throw error;
    }
  })();
  try { await saving; } finally { saving = null; }
}
async function exclusive(fn) {
  if (busy) return;
  busy = true;
  document.querySelector('.workspace').inert = true;
  document.querySelector('.project-bar').inert = true;
  document.querySelector('.page-bar').inert = true;
  try { await fn(); } finally {
    busy = false;
    document.querySelector('.workspace').inert = false;
    document.querySelector('.project-bar').inert = false;
    document.querySelector('.page-bar').inert = false;
  }
}
function projectList() {
  $('projects').innerHTML = projects.map(p => `<option value="${esc(p.id)}">${esc(p.title || '無題の作品')}</option>`).join('');
  if (project) $('projects').value = project.id;
}
async function loadProject(id) {
  project = await api('/projects/' + id);
  version = savedVersion = 0;
  const raw = localGet(draftKey(id));
  if (raw) {
    try {
      const draft = JSON.parse(raw);
      if (draft.revision === project.revision) {
        project = draft;
        changed();
        notice('前回の未保存の編集を復元しました。', true);
      } else {
        notice('サーバーに新しい版があります。前回の下書きはブラウザーに保持しています。必要なら「下書きを保存」で取り出せます。');
        const button = document.createElement('button');
        button.textContent = '下書きを保存';
        button.onclick = () => downloadBlob(new Blob([raw], {type:'application/json'}), 'moss-draft.json');
        $('notice').append(' ', button);
      }
    } catch (_) {}
  }
  pageId = project.pages[0].id;
  selected = null;
  $('save-state').textContent = version ? '下書きを復元' : 'RunPodに保存済み';
  localSet('moss-studio-last-project', id);
  jobsSignature = '';
  renderProject();
  await pollJobs();
}
function renderProject() {
  projectList();
  const p = page();
  $('page-tabs').innerHTML = project.pages.map((pg, i) => `<button data-page="${esc(pg.id)}" class="${pg.id === pageId ? 'active' : ''}">${i+1} · ${esc(pg.title || 'ページ')}</button>`).join('');
  for (const [id, object, key] of fields) $(id).value = (object === 'project' ? project : p)[key];
  $('hires').checked = p.hires;
  $('resolution').value = p.width === 1152 && p.height === 1728 ? '2' : p.width === 1664 && p.height === 2496 ? '4' : 'custom';
  $('compiled').value = '';
  referencePreview();
  renderPanels(); renderBubbles(); renderEditSources();
  refreshPreview();
}
function referencePreview() {
  $('reference-section').hidden = page().route !== 'reference';
  const ref = page().reference || project.reference;
  $('reference-preview').hidden = !ref;
  if (ref) $('reference-preview').src = assetURL(ref);
}
async function refreshPreview() {
  const p = page(), requestId = ++previewRequest;
  $('preview-label').textContent = `PAGE ${String(project.pages.indexOf(p)+1).padStart(2,'0')}`;
  $('size-label').textContent = `${p.width} × ${p.height}`;
  $('canvas-wrap').style.aspectRatio = `${p.width} / ${p.height}`;
  $('hit-layer').setAttribute('viewBox', '0 0 1000 1000');
  $('hit-layer').setAttribute('preserveAspectRatio', 'none');
  hitLayer();
  for (const kind of ['png', 'svg', 'zip']) $(kind+'-export').href = '/studio/api' + pagePath() + '/' + kind;
  try {
    const result = await fetch('/studio/api' + pagePath() + '/preview?v=' + project.revision);
    if (!result.ok) {
      const info = await result.json().catch(() => ({}));
      throw new Error(info.error || 'プレビューを作れませんでした。');
    }
    const blob = await result.blob();
    if (requestId !== previewRequest) return;
    const old = previewURL;
    previewURL = URL.createObjectURL(blob);
    $('page-preview').src = previewURL;
    if (old) URL.revokeObjectURL(old);
  } catch (error) { if (requestId === previewRequest) notice(error.message); }
}
function coords(item, kind) {
  return `<div class="coordinates">${['X %','Y %','幅 %','高さ %'].map((label,i) => `<label>${label}<input type="number" min="0" max="100" step="0.1" data-kind="${kind}" data-id="${esc(item.id)}" data-coordinate="${i}" value="${+(item.box[i]/10).toFixed(1)}"></label>`).join('')}</div>`;
}
function renderPanels() {
  $('panels').innerHTML = page().panels.map((p,i) => `<article class="panel-card ${selected?.id === p.id ? 'selected' : ''}" data-card="${esc(p.id)}">
    <div class="card-heading"><strong>コマ ${i+1}</strong><div class="small-actions"><button data-action="select" data-id="${esc(p.id)}" aria-label="コマ${i+1}の位置を選択">位置</button><button data-action="up" data-id="${esc(p.id)}" ${i === 0 ? 'disabled' : ''} aria-label="コマ${i+1}を前へ">↑</button><button data-action="remove" data-id="${esc(p.id)}" class="danger" ${page().panels.length === 1 ? 'disabled' : ''}>削除</button></div></div>
    <textarea rows="3" aria-label="コマ${i+1}の演出" data-kind="panel" data-id="${esc(p.id)}" data-field="caption" maxlength="6000">${esc(p.caption)}</textarea>
    ${coords(p,'panel')}<button data-action="generate" data-id="${esc(p.id)}" class="secondary">このコマだけ生成</button>
    ${page().panel_images[p.id] ? `<button data-action="clear" data-id="${esc(p.id)}" class="secondary">採用を外す</button>` : ''}</article>`).join('');
  hitLayer();
}
function renderBubbles() {
  $('bubbles').innerHTML = page().bubbles.map((b,i) => `<article class="bubble-card ${selected?.id === b.id ? 'selected' : ''}">
    <div class="card-heading"><strong>セリフ ${i+1}</strong><div class="small-actions"><button data-action="select" data-id="${esc(b.id)}">位置</button><button data-action="remove" data-id="${esc(b.id)}" class="danger">削除</button></div></div>
    <textarea rows="3" aria-label="セリフ${i+1}" data-kind="bubble" data-id="${esc(b.id)}" data-field="text" maxlength="1000">${esc(b.text)}</textarea>
    <div class="two"><label>向き<select data-kind="bubble" data-id="${esc(b.id)}" data-field="direction"><option value="vertical" ${b.direction === 'vertical' ? 'selected' : ''}>縦書き</option><option value="horizontal" ${b.direction === 'horizontal' ? 'selected' : ''}>横書き</option></select></label><label>吹き出し<select data-kind="bubble" data-id="${esc(b.id)}" data-field="shape">${[['ellipse','楕円'],['rect','四角'],['none','文字のみ']].map(([v,t]) => `<option value="${v}" ${v === b.shape ? 'selected' : ''}>${t}</option>`).join('')}</select></label></div>
    <label>文字サイズ<input type="number" min="12" max="120" data-kind="bubble" data-id="${esc(b.id)}" data-field="size" value="${b.size}"></label>${coords(b,'bubble')}</article>`).join('') || '<p class="empty">セリフを追加すると、ここで編集できます。</p>';
  hitLayer();
}
function itemBy(kind, id) { return (kind === 'panel' ? page().panels : page().bubbles).find(p => p.id === id); }
function hitLayer() {
  if (!project) return;
  const item = selected && itemBy(selected.kind, selected.id);
  $('hit-layer').classList.toggle('editing', !!item);
  $('hit-layer').innerHTML = item ? `<rect x="${item.box[0]}" y="${item.box[1]}" width="${item.box[2]}" height="${item.box[3]}"/>` : '';
}
function setTab(tab) {
  currentTab = tab;
  for (const button of document.querySelectorAll('[data-tab]')) button.classList.toggle('active', button.dataset.tab === tab);
  for (const name of ['page','text','results']) $('tab-'+name).hidden = name !== tab;
  selected = null;
  hitLayer();
}
function keepSelect(id, options) {
  const old = $(id).value;
  const html = options.map(([v,t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('');
  if ($(id).innerHTML !== html) $(id).innerHTML = html;
  if (options.some(([v]) => v === old)) $(id).value = old;
}
function renderEditSources() {
  if (!project) return;
  const sources = new Map();
  if (page().background) sources.set(page().background, '現在のページ画像');
  for (const [i,p] of page().panels.entries()) if (page().panel_images[p.id]) sources.set(page().panel_images[p.id], `採用済み コマ${i+1}`);
  for (const j of jobs.filter(j => j.page_id === pageId)) for (const u of j.units) if (u.asset && !sources.has(u.asset)) sources.set(u.asset, `${j.title} · ${j.kind === 'panels' ? u.id : j.kind === 'edit' ? '修正' : 'ページ'} · ${new Date(j.created*1000).toLocaleTimeString()}`);
  keepSelect('edit-source', [...sources]);
  keepSelect('edit-target', [['','ページ全体'], ...page().panels.map((p,i) => [p.id,`コマ ${i+1}`])]);
  $('generate-edit').disabled = !sources.size;
}
async function pollJobs() {
  if (!project) return;
  const id = project.id;
  const result = await api('/jobs?project=' + id);
  if (id !== project.id) return;
  jobs = result;
  const signature = JSON.stringify(result) + pageId;
  if (signature !== jobsSignature) { jobsSignature = signature; renderJobs(); renderEditSources(); }
}
function renderJobs() {
  const targets = new Map([...document.querySelectorAll('[data-apply-target]')].map(el => [el.dataset.applyTarget, el.value]));
  $('active-count').textContent = jobs.filter(j => active.includes(j.state)).length || '';
  $('jobs').innerHTML = jobs.filter(j => j.page_id === pageId).map(j => {
    const completed = j.units.filter(u => u.asset);
    return `<article class="job-card" data-job="${j.id}"><div class="card-heading"><strong>${esc(j.title)} · ${{page:'全体生成',panels:'コマ生成',edit:'画像修正'}[j.kind]}</strong><span class="job-state ${j.state}">${states[j.state]}</span></div>
      <div class="hint">${new Date(j.created*1000).toLocaleString()} · seed ${j.units[0].seed}</div><p class="job-message">${esc(j.message)}</p>
      <div class="job-images">${completed.map(u => `<figure><a href="${assetURL(u.asset)}" target="_blank" rel="noopener"><img src="${assetURL(u.asset)}" loading="lazy" alt="${esc(u.id)}の生成結果"></a><button data-action="apply" data-job="${j.id}" data-unit="${esc(u.id)}">${j.kind === 'panels' ? 'このコマを採用' : 'ページに採用'}</button><a href="${assetURL(u.asset)}" download="moss-${j.id}-${u.id}.png">元画像を保存 ↗</a></figure>`).join('')}</div>
      ${j.kind === 'edit' && completed.length ? `<label>修正画像の採用先<select data-apply-target="${j.id}"><option value="">ページ全体</option>${page().panels.map((p,i) => `<option value="${p.id}" ${p.id === j.apply_target ? 'selected' : ''}>コマ ${i+1}</option>`).join('')}</select></label>` : ''}
      <div class="job-actions">${j.kind === 'panels' && completed.length > 1 ? `<button data-action="apply" data-job="${j.id}">完成したコマをすべて採用</button>` : ''}${active.includes(j.state) ? `<button class="danger" data-action="cancel" data-job="${j.id}" ${j.cancel_requested ? 'disabled' : ''}>${j.cancel_requested ? '中止を待っています' : '中止'}</button>` : ''}${['failed','cancelled'].includes(j.state) ? `<button data-action="resume" data-job="${j.id}">未完了分を再開</button>` : ''}<a href="/studio/api/jobs/${j.id}/snapshot" class="button secondary">生成設定を保存</a></div></article>`;
  }).join('') || '<p class="empty">このページの生成履歴はまだありません。</p>';
  for (const el of document.querySelectorAll('[data-apply-target]')) if (targets.has(el.dataset.applyTarget)) el.value = targets.get(el.dataset.applyTarget);
}
async function generate(kind, extra = {}) {
  await exclusive(async () => {
    await flush();
    // Preserve the request ID until a reply is received, including a Safari/network interruption.
    const body = {id:uuid(), project_id:project.id, page_id:pageId, kind, ...extra};
    const saved = localGet('moss-studio-pending-job');
    pendingRequest = saved ? JSON.parse(saved) : body;
    localSet('moss-studio-pending-job', JSON.stringify(pendingRequest));
    let job;
    try { job = await api('/jobs', {method:'POST', body:pendingRequest}); }
    catch (error) {
      if (error.status >= 400 && error.status < 500) {
        localSet('moss-studio-pending-job', null); pendingRequest = null;
      }
      throw error;
    }
    const recovered = pendingRequest.id !== body.id;
    localSet('moss-studio-pending-job', null); pendingRequest = null;
    setTab('results');
    await pollJobs();
    notice(recovered ? '前回の送信を確認しました。生成履歴を確認してから、必要なら次の生成を追加してください。' : 'RunPodに受け付けました。画面を閉じても生成が続きます。', true);
    $('tab-results').scrollIntoView({behavior:'smooth', block:'start'});
    return job;
  });
}
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
const fields = [
  ['project-title','project','title'], ['character','project','character'], ['trigger','project','trigger'],
  ['page-title','page','title'], ['scene','page','scene'], ['style','page','style'], ['route','page','route'],
  ['width','page','width'], ['height','page','height'], ['lora-strength','page','lora_strength'],
  ['hires-strength','page','hires_strength'], ['sampling','page','sampling'], ['vae','page','vae'], ['seed','page','seed']
];
for (const [id, object, key] of fields) $(id).addEventListener('input', () => {
  (object === 'project' ? project : page())[key] = $(id).type === 'number' ? Number($(id).value) : $(id).value;
  if (id === 'route') referencePreview();
  if (id === 'width' || id === 'height') $('resolution').value = 'custom';
  changed();
});
$('hires').onchange = () => { page().hires = $('hires').checked; changed(); };
$('resolution').onchange = () => {
  if ($('resolution').value === 'custom') return;
  const high = $('resolution').value === '4';
  Object.assign(page(), {width:high ? 1664 : 1152, height:high ? 2496 : 1728, hires:high});
  $('width').value = page().width; $('height').value = page().height; $('hires').checked = high;
  changed();
};
$('random-seed').onclick = () => { page().seed = crypto.getRandomValues(new Uint32Array(1))[0]; $('seed').value = page().seed; changed(); };
for (const kind of ['panel','bubble']) {
  const container = $(kind === 'panel' ? 'panels' : 'bubbles');
  container.addEventListener('input', event => {
    const input = event.target, id = input.dataset.id;
    if (!id) return;
    const item = itemBy(kind, id);
    if (input.dataset.coordinate !== undefined) item.box[Number(input.dataset.coordinate)] = Number(input.value)*10;
    else if (input.dataset.field) item[input.dataset.field] = input.type === 'number' ? Number(input.value) : input.value;
    changed(); hitLayer();
  });
  container.addEventListener('click', safely(async event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const {action, id} = button.dataset, list = kind === 'panel' ? page().panels : page().bubbles;
    const index = list.findIndex(p => p.id === id);
    if (action === 'generate') return generate('panels', {panel_id:id});
    if (action === 'select') { selected = selected?.id === id ? null : {kind, id}; }
    else if (action === 'remove') { list.splice(index, 1); if (kind === 'panel') delete page().panel_images[id]; changed(); }
    else if (action === 'up' && index > 0) { [list[index-1],list[index]] = [list[index],list[index-1]]; changed(); }
    else if (action === 'clear') { delete page().panel_images[id]; changed(); }
    kind === 'panel' ? renderPanels() : renderBubbles();
  }));
}
$('add-panel').onclick = () => {
  if (page().panels.length >= 12) return notice('コマは12個以内です。');
  page().panels.push({id:uuid(), box:[50,50,900,250], caption:''}); changed(); renderPanels();
};
$('add-bubble').onclick = () => {
  if (page().bubbles.length >= 40) return notice('セリフは40個以内です。');
  const id = uuid(); page().bubbles.push({id, box:[720,80,200,260], text:'ここにセリフ', size:32, direction:'vertical', shape:'ellipse'});
  selected = {kind:'bubble',id}; changed(); renderBubbles();
};
$('use-template').onclick = () => {
  const count = Number($('layout-template').value);
  const boxes = count === 4 ? [[35,30,930,330],[520,380,445,230],[35,380,465,230],[35,630,930,340]] :
    Array.from({length:count}, (_,i) => [35,30+i*(940/count+10),930,940/count-10]);
  const old = page().panels;
  page().panels = boxes.map((box,i) => ({id:old[i]?.id || uuid(),caption:old[i]?.caption || '',box}));
  page().panel_images = Object.fromEntries(Object.entries(page().panel_images).filter(([id]) => page().panels.some(p => p.id === id)));
  selected = null; changed(); renderPanels();
};
let drag = null;
$('hit-layer').onpointerdown = event => {
  if (!selected || event.target.tagName !== 'rect') return;
  const item = itemBy(selected.kind, selected.id), bounds = $('hit-layer').getBoundingClientRect();
  drag = {x:event.clientX,y:event.clientY,box:[...item.box],bounds,item};
  $('hit-layer').setPointerCapture(event.pointerId); event.preventDefault();
};
$('hit-layer').onpointermove = event => {
  if (!drag) return;
  const {box,bounds,item} = drag;
  item.box[0] = Math.round(Math.max(0,Math.min(1000-box[2],box[0]+(event.clientX-drag.x)*1000/bounds.width)));
  item.box[1] = Math.round(Math.max(0,Math.min(1000-box[3],box[1]+(event.clientY-drag.y)*1000/bounds.height)));
  hitLayer();
};
function endDrag() { if (!drag) return; drag = null; changed(); renderPanels(); renderBubbles(); }
$('hit-layer').onpointerup = endDrag; $('hit-layer').onpointercancel = endDrag;
for (const button of document.querySelectorAll('[data-tab]')) button.onclick = () => setTab(button.dataset.tab);
$('projects').onchange = safely(() => exclusive(async () => { const id = $('projects').value; await flush(); await loadProject(id); }));
$('new-project').onclick = safely(() => exclusive(async () => { await flush(); const p = await api('/projects',{method:'POST'}); projects.unshift({id:p.id,title:p.title,pages:1}); await loadProject(p.id); }));
$('page-tabs').onclick = safely(async event => {
  const button = event.target.closest('[data-page]'); if (!button) return;
  await exclusive(async () => { await flush(); pageId = button.dataset.page; selected = null; jobsSignature=''; renderProject(); renderJobs(); });
});
$('new-page').onclick = safely(() => exclusive(async () => {
  await flush(); if (project.pages.length >= 32) throw new Error('1作品32ページ以内です。');
  const p = clone(page()); Object.assign(p,{id:uuid(),title:`第${project.pages.length+1}ページ`,background:'',panel_images:{},bubbles:[]});
  project.pages.push(p); pageId = p.id; selected = null; changed(); await flush(); renderProject(); renderJobs();
}));
$('reference-upload').onchange = safely(async () => {
  const file = $('reference-upload').files[0]; if (!file) return;
  if (file.size > 25*1024**2) throw new Error('参照画像は25MB以内です。');
  await exclusive(async () => { const info = await api('/assets',{method:'POST',body:file}); project.reference=info.id; page().reference=''; changed(); referencePreview(); await flush(); });
});
async function showPrompt() { await flush(); const data = await api(pagePath()+'/prompt'); $('compiled').value=JSON.stringify(JSON.parse(data.prompt),null,2); }
$('show-prompt').onclick = safely(showPrompt);
$('copy-prompt').onclick = safely(async () => { await showPrompt(); await navigator.clipboard.writeText($('compiled').value); notice('JSONをコピーしました。',true); });
$('generate-page').onclick = safely(() => generate('page'));
$('generate-panels').onclick = safely(() => generate('panels'));
$('edit-region').onchange = () => { $('edit-crop').hidden = $('edit-region').value === 'all'; };
$('edit-region').onchange();
$('generate-edit').onclick = safely(() => generate('edit', {source:$('edit-source').value, instruction:$('edit-instruction').value, apply_target:$('edit-target').value,
  crop:$('edit-region').value === 'custom' ? ['x','y','w','h'].map(k => Number($('crop-'+k).value)*10) : null}));
$('jobs').onclick = safely(async event => {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const {action,job:id,unit} = button.dataset;
  await exclusive(async () => {
    if (action === 'apply') {
      await flush();
      const target = document.querySelector(`[data-apply-target="${id}"]`)?.value || '';
      project = await api(`/jobs/${id}/apply`,{method:'POST',body:{revision:project.revision,unit,panel_id:target}});
      localSet(draftKey(project.id),null); renderProject(); notice('ページに採用しました。',true);
    } else { await api(`/jobs/${id}/${action}`,{method:'POST'}); }
    await pollJobs();
  });
});
for (const kind of ['png','svg','zip']) $(kind+'-export').onclick = safely(async event => {
  event.preventDefault();
  await flush();
  // Use a regular authenticated navigation/download, so large ZIPs do not fill mobile JS memory.
  const link = document.createElement('a'); link.href='/studio/api'+pagePath()+'/'+kind; link.download=`moss-${pageId}.${kind}`; link.click();
});
document.addEventListener('visibilitychange', () => {
  if (!project) return;
  if (document.hidden) flush().catch(() => {});
  else { pollJobs().catch(error => notice(error.message)); if (version > savedVersion) flush().catch(error => notice(error.message)); }
});
window.addEventListener('beforeunload', event => { if (savedVersion < version) { event.preventDefault(); event.returnValue=''; } });
setInterval(() => { if (!document.hidden) pollJobs().catch(() => { $('save-state').textContent='再接続待ち · RunPod側で生成を継続'; }); }, 3500);
(async () => {
  try {
    const data = await api('/bootstrap'); projects=data.projects; jobs=data.jobs;
    const pending = localGet('moss-studio-pending-job');
    if (pending && jobs.some(j => j.id === JSON.parse(pending).id)) localSet('moss-studio-pending-job', null);
    const last = localGet('moss-studio-last-project');
    await loadProject(projects.some(p=>p.id===last) ? last : projects[0].id);
  } catch (error) { notice(error.message); $('save-state').textContent='接続できませんでした。再読込してください。'; }
})();
