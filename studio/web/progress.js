'use strict';
window.MossProgress = (() => {
  const active = ['queued','preparing','running'];
  function duration(seconds) {
    const s=Math.max(0,Math.floor(seconds || 0)), m=Math.floor(s/60);
    return m>=60 ? `${Math.floor(m/60)}時間${m%60}分` : m ? `${m}分${s%60}秒` : `${s}秒`;
  }
  function structure(job) {
    const {updated,elapsed_seconds,...base}=job;
    return {...base,units:job.units.map(({progress,...unit})=>unit)};
  }
  function update(root,jobs) {
    const byId=new Map(jobs.map(job=>[job.id,job]));
    for (const slot of root.querySelectorAll('[data-progress-job]')) {
      const job=byId.get(slot.dataset.progressJob); if (!job) continue;
      if (!slot.firstElementChild) slot.innerHTML='<div class="progress-heading"><strong class="progress-stage"></strong><span class="progress-time"></span></div><div class="progress-count"></div><progress class="generation-progress" max="100" aria-label="描画ステップ"></progress><p class="progress-note hint"></p><p class="progress-reconnect hint" hidden>進捗情報を再接続中…</p><figure class="progress-preview-wrap" hidden><figcaption class="hint">途中プレビュー · 完成画像ではありません</figcaption><img class="progress-preview" alt="生成途中のプレビュー"></figure>';
      const unit=job.units[job.current_unit || 0] || {}, p=unit.progress || {};
      const done=job.units.filter(u=>u.state==='completed').length;
      const running=active.includes(job.state), sampling=Number.isFinite(p.step)&&Number.isFinite(p.total)&&p.total>0;
      slot.querySelector('.progress-stage').textContent=job.state==='running' ? p.stage || '生成処理の開始を待っています' : job.state==='completed' ? '完成' : job.message;
      slot.querySelector('.progress-time').textContent=`経過 ${duration(job.elapsed_seconds)}`;
      const bar=slot.querySelector('progress'), count=slot.querySelector('.progress-count');
      if (job.state==='completed') {bar.max=100;bar.value=100;count.textContent='完了 · 100%';}
      else if (sampling) {bar.max=p.total;bar.value=p.step;count.textContent=`描画 ${p.step} / ${p.total} ステップ · ${Math.floor(p.step/p.total*100)}%`;}
      else {bar.max=100;bar.removeAttribute('value');count.textContent=job.state==='queued'?'順番待ち':running?'ステップ開始待ち':'';}
      bar.hidden=!running && job.state!=='completed' && !sampling;
      slot.querySelector('.progress-note').textContent=job.units.length>1 ? `${done} / ${job.units.length}枚完成 · 現在 ${(job.current_unit || 0)+1}枚目` : running && sampling ? '割合は描画ステップの進み具合です。描画後に画像の仕上げと保存を行います。' : '';
      slot.querySelector('.progress-reconnect').hidden=!(running && ['submitting','running'].includes(unit.state) && p.live===false);
      const preview=slot.querySelector('.progress-preview-wrap'), img=preview.querySelector('img');
      preview.hidden=!(running && p.preview_version);
      if (!preview.hidden) {
        const url=`/studio/api/jobs/${encodeURIComponent(job.id)}/preview/${encodeURIComponent(unit.id)}?v=${p.preview_version}`;
        if (img.getAttribute('src')!==url) img.src=url;
      }
    }
  }
  return {structure,update};
})();
