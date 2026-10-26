"""Observe native ComfyUI events without making the browser own generation."""
import asyncio
import io
import json
import math
import os
import struct
import time

from aiohttp import WSMsgType
from PIL import Image

STAGES = {
    'UNETLoader': '画像モデルを準備中', 'CLIPLoader': 'テキストモデルを準備中',
    'VAELoader': '画像デコーダーを準備中', 'LoraLoaderModelOnly': 'キャラLoRAを適用中',
    'CLIPTextEncode': 'プロンプトを解析中（初回はモデル読み込み）',
    'TextEncodeMOSSImageEdit': '参照画像とプロンプトを解析中',
    'LoadImage': '参照画像を読み込み中', 'EmptyFlux2LatentImage': '描画領域を準備中',
    'SkipLayerGuidanceDiTSimple': '描画設定を準備中',
    'KSampler': '描画の準備中（モデル転送・初回計算）',
    'VAEDecode': '画像を仕上げ中', 'SaveImage': '画像を保存中',
}


class Progress:
    def __init__(self, engine, job, unit):
        self.engine, self.job, self.unit = engine, job, unit
        self.task = None
        self.connected = asyncio.Event()
        self.last_write = 0
        self.last_preview = 0
        self.dirty = False
        self.flush_handle = None
        self.value = unit.setdefault('progress', {'stage': '生成キューの順番待ち', 'step': None, 'total': None})
        self.value['live'] = False

    def persist(self, force=False):
        now = time.monotonic()
        if self.dirty and (force or now - self.last_write >= .4):
            if self.flush_handle:
                self.flush_handle.cancel()
                self.flush_handle = None
            self.value['updated_at'] = time.time()
            self.engine.save(self.job)
            self.last_write, self.dirty = now, False
        elif self.dirty and self.flush_handle is None:
            # Flush even when no further events arrive (slow steps/reconnection).
            self.flush_handle = asyncio.get_running_loop().call_later(
                max(0, .4-(now-self.last_write)), self.flush,
            )

    def flush(self):
        self.flush_handle = None
        self.persist(force=True)

    def update(self, **values):
        if any(self.value.get(k) != v for k, v in values.items()):
            urgent = any(k in values and self.value.get(k) != values[k] for k in ('stage', 'live', 'preview_version'))
            self.value.update(values)
            self.dirty = True
            self.persist(force=urgent)

    async def start(self):
        self.task = asyncio.create_task(self.listen(), name='moss-progress')
        # Try to subscribe before submission; a progress outage must not block work.
        try:
            await asyncio.wait_for(self.connected.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.value['live'] = False
        self.dirty = True
        self.persist(force=True)

    async def listen(self):
        while True:
            try:
                async with self.engine.session.ws_connect(
                    self.engine.upstream+'/ws', params={'clientId': self.unit.get('client_id', 'moss-studio')},
                    heartbeat=20, max_msg_size=12*1024**2,
                ) as socket:
                    await socket.send_json({'type': 'feature_flags', 'data': {'supports_preview_metadata': True}})
                    self.connected.set()
                    self.update(live=True)
                    async for message in socket:
                        try:
                            if message.type == WSMsgType.TEXT:
                                self.event(json.loads(message.data))
                            elif message.type == WSMsgType.BINARY:
                                self.preview(message.data)
                            elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSED):
                                break
                        except (ValueError, TypeError, KeyError, OSError, struct.error):
                            # Invalid telemetry never invalidates a generation job.
                            continue
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            self.update(live=False)
            self.persist(force=True)
            await asyncio.sleep(1)

    def event(self, event):
        if not isinstance(event, dict):
            return
        data = event.get('data', {})
        if not isinstance(data, dict) or data.get('prompt_id') != self.unit['prompt_id']:
            return  # Ignore broadcasts, old jobs, and unscoped reconnect snapshots.
        kind = event.get('type')
        if kind == 'execution_start':
            self.unit.setdefault('started_at', time.time())
            self.update(stage='モデルとプロンプトを準備中')
        elif kind == 'executing':
            node = data.get('node')
            if node is None:
                self.update(stage='保存結果を確認中')
                return
            node = str(node)
            info = self.unit.get('graph', {}).get(node)
            if info:
                values = {'node': node, 'stage': STAGES.get(info['class_type'], '生成処理中')}
                if info['class_type'] == 'KSampler' and self.value.get('step') is None:
                    values.update(step=0, total=info['inputs']['steps'])
                self.update(**values)
        elif kind == 'progress':
            self.sampling(data.get('node'), data.get('value'), data.get('max'))
        elif kind == 'progress_state':
            for node, state in data.get('nodes', {}).items():
                if state.get('state') == 'running' and state.get('max', 0) > 1:
                    self.sampling(node, state.get('value'), state.get('max'))
        elif kind == 'execution_success':
            self.update(stage='保存結果を確認中')
        self.persist()

    def sampling(self, node, value, total):
        node = str(node)
        if self.unit.get('graph', {}).get(node, {}).get('class_type') != 'KSampler':
            return
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (value, total)):
            return
        if total <= 0 or value < 0 or value > total:
            return
        previous = self.value.get('step')
        if self.value.get('node') == node and previous is not None and value < previous:
            return
        self.update(node=node, stage='描画中', step=int(value), total=int(total))

    def preview(self, data):
        # Only metadata-bearing frames are safely attributable across queued jobs.
        if len(data) < 8 or len(data) > 10*1024**2 or struct.unpack('>I', data[:4])[0] != 4:
            return
        size = struct.unpack('>I', data[4:8])[0]
        if size > 65536 or 8+size >= len(data):
            return
        metadata = json.loads(data[8:8+size])
        if metadata.get('prompt_id') != self.unit['prompt_id'] or time.monotonic()-self.last_preview < 1:
            return
        with Image.open(io.BytesIO(data[8+size:])) as image:
            if image.width*image.height > 2_000_000:
                return
            image.thumbnail((512, 512))
            output = io.BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=80)
        directory = self.engine.store.root/'previews'
        directory.mkdir(exist_ok=True)
        target = directory/(self.unit['prompt_id']+'.jpg')
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(output.getvalue())
        os.replace(temporary, target)
        self.last_preview = time.monotonic()
        self.update(preview_version=str(time.time_ns()))


def elapsed(job):
    start = job.get('started_at')
    if not start:
        return 0
    # Older stored jobs have no finish timestamp; their last update is the fallback.
    end = job.get('finished_at', job.get('updated', start)) if job['state'] not in ('queued', 'preparing', 'running') else time.time()
    return max(0, int(end-start))
