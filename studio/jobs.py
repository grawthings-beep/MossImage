"""Persistent FIFO generation queue. HTTP clients never own a generation task."""
import asyncio
import copy
import io
import json
import logging
import math
import os
from pathlib import Path
import time
import uuid

from aiohttp import ClientSession, ClientTimeout
from PIL import Image, ImageOps

from .assets import Downloads, required_models
from .schema import compile_prompt, ident, panel_dimensions, pixel_box, box, text
from .workflow import build_graph
from .progress import Progress

LOG = logging.getLogger(__name__)
ACTIVE = ('queued', 'preparing', 'running')


def image_bytes(data):
    # HTTP uploads have a separate 25MB limit; generated PNGs may be larger.
    if len(data) > 128 * 1024**2:
        raise ValueError('画像ファイルが大きすぎます。')
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 24_000_000:
            raise ValueError('参照画像は24MP以内でアップロードしてください。')
        im = ImageOps.exif_transpose(source).convert('RGBA')
        out = Image.new('RGB', im.size, 'white')
        out.paste(im, mask=im.getchannel('A'))
        result = io.BytesIO()
        out.save(result, format='PNG')
        return result.getvalue(), out.width, out.height


class Engine:
    def __init__(self, runtime, store, upstream, poll_interval=1.5):
        self.runtime, self.store, self.upstream = Path(runtime), store, upstream
        self.downloads = Downloads(runtime)
        self.poll_interval = poll_interval
        self.task = None
        self.session = None
        self.wake = asyncio.Event()
        self.font_lock = asyncio.Lock()
        self.font_path = None
        self.resume_lock = asyncio.Lock()

    async def fonts(self):
        async with self.font_lock:
            if self.font_path is None:
                self.font_path = await asyncio.to_thread(self.downloads.ensure_fonts)
            return self.font_path

    async def start(self):
        self.session = ClientSession(timeout=ClientTimeout(total=45))
        self.task = asyncio.create_task(self.worker(), name='moss-studio-worker')

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.session:
            await self.session.close()

    def asset(self, data, key=None, provenance=None):
        data, width, height = image_bytes(data)
        key = key or uuid.uuid4().hex
        path = self.store.root / 'assets' / (ident(key) + '.png')
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(data)
        os.replace(temporary, path)
        info = {'id': key, 'width': width, 'height': height, 'bytes': len(data), 'provenance': provenance or {}}
        self.store.put('asset', info)
        return info

    def create(self, data):
        job_id = str(uuid.UUID(str(data['id'])))
        try:
            return self.store.get('job', job_id)  # stable client request ID, including lost HTTP replies
        except KeyError:
            pass
        if sum(j['state'] in ACTIVE for j in self.store.list('job')) >= 32:
            raise ValueError('待機中のジョブが32件あります。完了後に追加してください。')
        project = self.store.get('project', ident(data['project_id']))
        page = next((p for p in project['pages'] if p['id'] == data['page_id']), None)
        if page is None:
            raise ValueError('ページが見つかりません。')
        kind = data['kind']
        if kind not in ('page', 'panels', 'edit', 'image'):
            raise ValueError('生成種別が不正です。')
        units = []
        apply_target = data.get('apply_target', '')
        if apply_target and apply_target not in {p['id'] for p in page['panels']}:
            raise ValueError('採用先のコマがありません。')
        if kind == 'edit':
            source = ident(data['source'])
            self.store.asset_path(source)
            instruction = text(data.get('instruction', ''), 6000).strip()
            if not instruction:
                raise ValueError('修正内容を入力してください。')
            crop = box(data['crop']) if data.get('crop') else None
            asset = self.store.get('asset', source)
            w, h = asset['width'], asset['height']
            if crop:
                b = pixel_box(crop, w, h)
                w, h = b[2]-b[0], b[3]-b[1]
            scale = min(1.0, math.sqrt(1024**2 / (w*h)))
            w, h = max(256, round(w*scale/16)*16), max(256, round(h*scale/16)*16)
            units.append({'id': 'edit', 'source': source, 'crop': crop, 'width': w, 'height': h,
                          'prompt': instruction + '\nPreserve the character identity, costume details, art style and all elements not explicitly requested to change.'})
        elif kind == 'image':
            # A single illustration keeps the exact selected dimensions and prompt.
            # It must not inherit manga layout wording or panel-size rescaling.
            units.append({'id': 'image', 'width': page['width'], 'height': page['height'], 'prompt': page['scene']})
        elif kind == 'page':
            units.append({'id': 'page', 'width': page['width'], 'height': page['height'], 'prompt': compile_prompt(project, page)})
        else:
            selected = data.get('panel_id')
            panels = [p for p in page['panels'] if not selected or selected == p['id']]
            if not panels:
                raise ValueError('対象のコマがありません。')
            for panel in panels:
                w, h = panel_dimensions(panel, page)
                units.append({'id': panel['id'], 'width': w, 'height': h, 'prompt': compile_prompt(project, page, panel)})
        reference = page.get('reference') or project.get('reference')
        if page['route'] == 'reference' and kind != 'edit':
            if not reference:
                raise ValueError('キャラの参照画像をアップロードしてください。')
            self.store.asset_path(reference)
        for index, unit in enumerate(units):
            if len(unit['prompt'].encode('utf-8')) > 24000:
                raise ValueError('プロンプトが長すぎます。コマ数や説明を減らしてください。')
            unit.update(state='queued', seed=(page['seed']+index) % (2**53),
                        prompt_id=str(uuid.uuid5(uuid.UUID(job_id), str(index))), attempt=0)
        job = {'id': job_id, 'created': time.time(), 'updated': time.time(), 'project_id': project['id'],
               'page_id': page['id'], 'title': page['title'], 'kind': kind, 'state': 'queued', 'message': '待機中',
               'snapshot': project, 'page': page, 'reference': reference, 'units': units, 'cancel_requested': False,
               'apply_target': apply_target}
        self.store.put('job', job)
        self.wake.set()
        return job

    def save(self, job, state=None, message=None):
        # A cancel request may arrive while a model is downloading in a thread.
        try:
            job['cancel_requested'] = job.get('cancel_requested', False) or self.store.get('job', job['id']).get('cancel_requested', False)
        except KeyError:
            pass
        if state is not None:
            job['state'] = state
            if state == 'preparing':
                job.setdefault('started_at', time.time())
            if state not in ACTIVE:
                job['finished_at'] = time.time()
        if message is not None:
            job['message'] = message
        job['updated'] = time.time()
        self.store.put('job', job)

    async def api(self, method, path, **kwargs):
        async with self.session.request(method, self.upstream+path, **kwargs) as response:
            body = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError('ComfyUI: ' + json.dumps(body, ensure_ascii=False)[:1800])
            return body

    async def cancel_prompt(self, prompt_id):
        for path, body in [('/queue', {'delete': [prompt_id]}), ('/interrupt', {'prompt_id': prompt_id})]:
            async with self.session.post(self.upstream+path, json=body) as response:
                await response.read()
                response.raise_for_status()

    async def location(self, unit):
        history = await self.api('GET', '/history/'+unit['prompt_id'])
        if unit['prompt_id'] in history:
            return 'history', history[unit['prompt_id']]
        queue = await self.api('GET', '/queue')
        if any(row[1] == unit['prompt_id'] for key in ('queue_running', 'queue_pending') for row in queue.get(key, [])):
            return 'queue', None
        return 'missing', None

    def saved_output(self, job, unit):
        directory = self.runtime / 'ComfyUI/output/MOSS/Studio' / job['id']
        matches = sorted(directory.glob(unit['id'] + f'_a{unit["attempt"]}_*.png')) if directory.is_dir() else []
        if len(matches) > 1:
            raise RuntimeError('同じ生成IDの出力が複数あります。履歴を確認してください。')
        return matches[0] if matches else None

    def reference_file(self, job, unit):
        source = unit.get('source') if job['kind'] == 'edit' else job.get('reference') if job['page']['route'] == 'reference' else None
        if not source:
            return None
        with Image.open(self.store.asset_path(source)) as im:
            im = im.convert('RGB')
            if unit.get('crop'):
                im = im.crop(pixel_box(unit['crop'], im.width, im.height))
            scale = min(1.0, math.sqrt(1024**2 / (im.width*im.height)))
            w, h = max(16, round(im.width*scale/16)*16), max(16, round(im.height*scale/16)*16)
            im = im.resize((w, h), Image.Resampling.LANCZOS)
            relative = f'studio/{job["id"]}_{unit["id"]}.png'
            path = self.runtime / 'ComfyUI/input' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            im.save(path)
        return relative

    def finish_unit(self, job, unit, path):
        with Image.open(path) as image:
            image.load()
            if image.size != (unit['width'], unit['height']):
                raise RuntimeError('出力画像サイズが生成設定と一致しません。')
            result = image.convert('RGB')
            if job['kind'] == 'edit' and unit.get('crop'):
                with Image.open(self.store.asset_path(unit['source'])) as original:
                    full = original.convert('RGB')
                b = pixel_box(unit['crop'], full.width, full.height)
                full.paste(result.resize((b[2]-b[0], b[3]-b[1]), Image.Resampling.LANCZOS), b[:2])
                result = full  # pixels outside the chosen rectangle remain unchanged
            out = io.BytesIO()
            result.save(out, format='PNG')
        key = uuid.uuid5(uuid.UUID(job['id']), unit['id'] + f':asset:{unit["attempt"]}').hex
        asset = self.asset(out.getvalue(), key, {'job': job['id'], 'unit': unit['id'], 'seed': unit['seed']})
        unit.update(state='completed', asset=asset['id'])
        self.save(job)

    async def run_unit(self, job, unit):
        if unit['state'] == 'queued':
            unit['client_id'] = 'moss-studio-'+unit['prompt_id']
            unit.pop('progress', None)
        monitor = Progress(self, job, unit)
        try:
            await monitor.start()
            await self._run_unit(job, unit)
        finally:
            await monitor.close()

    async def _run_unit(self, job, unit):
        # First reconcile a persisted submission; never blindly re-submit after reconnect/restart.
        if unit['state'] != 'queued':
            found = self.saved_output(job, unit)
            if found:
                self.finish_unit(job, unit, found)
                return
            # History and queue are separate requests. Completion between them can
            # briefly look missing; use the bounded reconciliation loop below.
            # A persisted submission is never submitted again here.
        else:
            reference = self.reference_file(job, unit)
            graph, output = build_graph(job['page'], unit['prompt'], unit['width'], unit['height'], unit['seed'],
                                        f'MOSS/Studio/{job["id"]}/{unit["id"]}_a{unit["attempt"]}', reference, job['kind'] == 'edit')
            unit.update(graph=graph, output_node=output, state='submitting')
            self.save(job)
            try:
                await self.api('POST', '/prompt', json={'prompt_id': unit['prompt_id'], 'prompt': graph,
                    'client_id': unit.get('client_id', 'moss-studio'), 'extra_data': {'preview_method': 'latent2rgb', 'extra_pnginfo': {'moss_studio': {
                        'job_id': job['id'], 'unit': unit['id'], 'project': job['snapshot'], 'graph': graph}}}})
            except Exception:
                # The server may have accepted it even if the HTTP response was lost.
                await asyncio.sleep(self.poll_interval)
                where, _ = await self.location(unit)
                if where == 'missing':
                    raise
            unit['state'] = 'running'
            self.save(job)
        missing_since = None
        while True:
            latest = self.store.get('job', job['id'])
            if latest.get('cancel_requested'):
                job['cancel_requested'] = True
                await self.cancel_prompt(unit['prompt_id'])
                self.save(job, 'cancelled', '中止しました。完了済み画像は残っています。')
                return
            where, entry = await self.location(unit)
            if where == 'history':
                status = entry.get('status', {})
                if status.get('status_str') == 'error':
                    messages = [m[1].get('exception_message', m[0]) for m in status.get('messages', []) if m[0] in ('execution_error', 'execution_interrupted')]
                    raise RuntimeError('生成に失敗しました: ' + '; '.join(messages)[:1500])
                if status.get('completed'):
                    found = self.saved_output(job, unit)
                    if found is None:
                        raise RuntimeError('ComfyUIは完了しましたが、保存画像が見つかりません。')
                    self.finish_unit(job, unit, found)
                    return
            elif where == 'missing':
                found = self.saved_output(job, unit)
                if found:
                    self.finish_unit(job, unit, found)
                    return
                missing_since = missing_since or time.monotonic()
                if time.monotonic() - missing_since > 12:
                    raise RuntimeError('生成がキューからなくなりました。「再開」で未完了分を再実行できます。')
            else:
                missing_since = None
            await asyncio.sleep(self.poll_interval)

    async def worker(self):
        while True:
            candidates = sorted((j for j in self.store.list('job') if j['state'] in ACTIVE), key=lambda j: j['created'])
            if not candidates:
                self.wake.clear()
                await self.wake.wait()
                continue
            job = candidates[0]
            try:
                if job.get('cancel_requested'):
                    self.save(job, 'cancelled', '中止しました。')
                    continue
                self.save(job, 'preparing', '必要なモデルを確認しています。初回はダウンロードします。')
                for name in required_models(job['page'], job['kind']):
                    if self.store.get('job', job['id']).get('cancel_requested'):
                        break
                    self.save(job, message=f'{name} を準備しています。初回の取得中も画面を閉じられます。')
                    await asyncio.to_thread(self.downloads.ensure, name)
                if job['kind'] != 'image':
                    self.save(job, message='日本語フォントを準備しています。')
                    await self.fonts()
                for index, unit in enumerate(job['units']):
                    if self.store.get('job', job['id']).get('cancel_requested'):
                        job['cancel_requested'] = True
                        self.save(job, 'cancelled', '中止しました。')
                        break
                    if unit['state'] == 'completed':
                        continue
                    job['current_unit'] = index
                    self.save(job, 'running', f'{index+1} / {len(job["units"])} を生成中')
                    await self.run_unit(job, unit)
                    if job['state'] == 'cancelled':
                        break
                if job['state'] != 'cancelled':
                    self.save(job, 'completed', '完成しました。PNGを保存できます。' if job['kind'] == 'image' else '完成しました。「ページに採用」で編集に反映できます。')
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOG.exception('Studio job failed: %s', job['id'])
                self.save(job, 'failed', str(error)[:2400])

    async def resume(self, key):
        # Two tabs retrying one interrupted job must not reset an already requeued unit.
        async with self.resume_lock:
            return await self._resume(key)

    async def _resume(self, key):
        job = self.store.get('job', key)
        if job['state'] in ACTIVE or job['state'] == 'completed':
            return job
        for unit in job['units']:
            if unit['state'] == 'completed':
                continue
            found = self.saved_output(job, unit)
            if found:
                self.finish_unit(job, unit, found)
                continue
            where, _ = await self.location(unit)
            if where == 'queue':
                unit['state'] = 'running'
            else:
                unit['attempt'] += 1
                unit['prompt_id'] = str(uuid.uuid5(uuid.UUID(job['id']), unit['id'] + ':' + str(unit['attempt'])))
                unit['state'] = 'queued'
                unit.pop('progress', None)
                unit.pop('started_at', None)
        job['cancel_requested'] = False
        job.pop('finished_at', None)
        self.store.put('job', job)
        self.save(job, 'queued', '未完了分から再開します。')
        self.wake.set()
        return job
