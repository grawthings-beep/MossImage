import asyncio
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock
import uuid
import zipfile

from aiohttp import BasicAuth, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch_comfy import proxy_app
from studio.jobs import Engine
from studio.render import png_page, svg_page
from studio.schema import default_project, validate_project, compile_prompt, pixel_box
from studio.store import Store, Conflict
from studio.workflow import build_graph

FONT = Path(os.environ.get('MOSS_TEST_FONT', '__font_not_configured__'))


def image_data(size=(512, 512), color='#427563'):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, 'PNG')
    return stream.getvalue()


class SchemaTests(unittest.TestCase):
    def test_layout_uses_official_centered_yxyx_and_keeps_dialogue_separate(self):
        p = validate_project(default_project())
        pg = p['pages'][0]
        pg['bubbles'] = [{'text': 'DO NOT DIFFUSE THIS'}]
        layout = json.loads(compile_prompt(p, pg))
        b = pixel_box(pg['panels'][0]['box'], pg['width'], pg['height'])
        self.assertEqual(layout['bbox_format'], 'yxyx')
        self.assertEqual(layout['items'][0]['bbox'], [b[1]-864, b[0]-576, b[3]-864, b[2]-576])
        self.assertEqual(len(layout['items']), 4)
        self.assertNotIn('DO NOT DIFFUSE THIS', json.dumps(layout))
        self.assertIn(p['trigger'], layout['summary']['caption'])
        pg['route'] = 'reference'
        self.assertIn('Same character and art style as Picture 1.', compile_prompt(p, pg))
        self.assertNotIn(p['trigger'], compile_prompt(p, pg))

    def test_invalid_size_bounds_and_hires_are_rejected(self):
        for change in ({'width': 1153}, {'width':4096,'height':4096}, {'hires':True}, {'seed':float('nan')}):
            p = default_project(); p['pages'][0].update(change)
            with self.assertRaises(ValueError): validate_project(p)
        p = default_project(); p['pages'][0]['panels'][0]['box'] = [990,0,40,40]
        with self.assertRaises(ValueError): validate_project(p)

    def test_routes_keep_the_correct_backbone_adapters_and_sampling(self):
        pg = default_project()['pages'][0]
        graph, _ = build_graph(pg, 'prompt', 1152, 1728, 42, 'test')
        self.assertEqual([n['inputs']['lora_name'] for n in graph.values() if n['class_type']=='LoraLoaderModelOnly'], ['mossimage_lora_marian_queen2.safetensors'])
        pg.update(route='reference', sampling='comfy')
        graph, _ = build_graph(pg, 'prompt', 1152,1728,42,'test','reference.png')
        encoders = [n['inputs'] for n in graph.values() if n['class_type']=='TextEncodeMOSSImageEdit']
        self.assertEqual(len(encoders), 2)
        self.assertEqual(encoders[0]['images.image_0'], encoders[1]['images.image_0'])
        self.assertEqual([n['inputs']['steps'] for n in graph.values() if n['class_type']=='KSampler'], [50])
        graph, _ = build_graph(pg, 'edit', 512,512,42,'test','reference.png',edit=True)
        self.assertEqual(graph['1']['inputs']['unet_name'], 'moss_image_sft_bf16.safetensors')
        self.assertEqual([n['inputs']['lora_name'] for n in graph.values() if n['class_type']=='LoraLoaderModelOnly'], ['moss_edit_armV6.safetensors'])

    def test_project_revision_prevents_overwriting_another_tab(self):
        with tempfile.TemporaryDirectory() as root:
            s = Store(root)
            try:
                p = s.project(default_project()); stale = copy.deepcopy(p)
                p['title'] = 'new'; s.project(p)
                with self.assertRaises(Conflict): s.project(stale)
                self.assertEqual(s.get('project', p['id'])['title'], 'new')
            finally: s.close()


class FakeComfy:
    """Synthetic pixels only. Test queue ownership; never claim this tests diffusion."""
    def __init__(self, runtime):
        self.runtime = Path(runtime)
        self.submitted, self.pending, self.history, self.interrupted = [], {}, {}, []
        self.app = web.Application()
        self.app.router.add_post('/prompt', self.prompt)
        self.app.router.add_get('/queue', self.queue)
        self.app.router.add_post('/queue', self.delete)
        self.app.router.add_get('/history/{id}', self.get_history)
        self.app.router.add_post('/interrupt', self.interrupt)

    async def prompt(self, request):
        body = await request.json(); key = body['prompt_id']
        self.submitted.append(key); self.pending[key] = body
        return web.json_response({'prompt_id':key})

    async def queue(self, request):
        return web.json_response({'queue_running':[], 'queue_pending':[[i,k] for i,k in enumerate(self.pending)]})

    async def delete(self, request):
        for key in (await request.json()).get('delete',[]): self.pending.pop(key,None)
        return web.json_response({})

    async def interrupt(self, request):
        self.interrupted.append((await request.json()).get('prompt_id'))
        return web.json_response({})

    async def get_history(self, request):
        key = request.match_info['id']
        return web.json_response({key:self.history[key]} if key in self.history else {})

    def complete(self, key, color='#9278b5'):
        body = self.pending.pop(key)
        graph = body['prompt']
        latent = next(n['inputs'] for n in graph.values() if n['class_type']=='EmptyFlux2LatentImage')
        output = next(n['inputs'] for n in graph.values() if n['class_type']=='SaveImage')
        path = self.runtime / 'ComfyUI/output' / (output['filename_prefix'] + '_00001_.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_data((latent['width'],latent['height']),color))
        self.history[key] = {'status': {'completed':True, 'status_str':'success'}}
        return path


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.store = Store(self.root/'studio')
        self.project = self.store.project(validate_project(default_project()))
        self.fake = FakeComfy(self.root)
        self.server = TestServer(self.fake.app); await self.server.start_server()
        self.engine = self.make_engine(); await self.engine.start()

    def make_engine(self):
        e = Engine(self.root,self.store,str(self.server.make_url('')).rstrip('/'),poll_interval=.02)
        e.fonts = AsyncMock(return_value=FONT)
        e.downloads.ensure = Mock()
        return e

    async def asyncTearDown(self):
        await self.engine.close(); await self.server.close(); self.store.close(); self.tmp.cleanup()

    async def until(self, predicate):
        for _ in range(200):
            if predicate(): return
            await asyncio.sleep(.02)
        self.fail('Timed out waiting for test queue')

    def create(self, kind='page', **extra):
        data = dict(id=str(uuid.uuid4()), project_id=self.project['id'], page_id=self.project['pages'][0]['id'],kind=kind, **extra)
        return self.engine.create(data), data

    async def test_idempotent_submission_finishes_without_any_http_client(self):
        job, data = self.create()
        self.assertEqual(self.engine.create(data)['id'],job['id'])
        await self.until(lambda: len(self.fake.pending)==1)
        self.fake.complete(next(iter(self.fake.pending)))
        await self.until(lambda: self.store.get('job',job['id'])['state']=='completed')
        result = self.store.get('job',job['id'])
        self.assertEqual(len(self.fake.submitted),1)
        self.assertTrue(self.store.asset_path(result['units'][0]['asset']).is_file())
        self.assertFalse(self.store.get('project',self.project['id'])['pages'][0]['background'])

    async def test_restart_rejoins_existing_prompt_without_resubmitting(self):
        job,_ = self.create()
        await self.until(lambda: len(self.fake.pending)==1)
        await self.engine.close()
        # Reopen SQLite as a fresh server process would.
        self.store.close(); self.store = Store(self.root/'studio')
        self.engine = self.make_engine(); await self.engine.start()
        await asyncio.sleep(.08)
        self.assertEqual(len(self.fake.submitted),1)
        self.fake.complete(next(iter(self.fake.pending)))
        await self.until(lambda: self.store.get('job',job['id'])['state']=='completed')
        self.assertEqual(len(self.fake.submitted),1)

    async def test_disk_output_recovers_even_after_comfy_history_is_lost(self):
        job,_=self.create(); await self.until(lambda:len(self.fake.pending)==1)
        await self.engine.close()
        self.fake.complete(next(iter(self.fake.pending))); self.fake.history.clear()
        self.engine=self.make_engine(); await self.engine.start()
        await self.until(lambda:self.store.get('job',job['id'])['state']=='completed')
        self.assertEqual(len(self.fake.submitted),1)

    async def test_cancel_is_scoped_and_resume_keeps_completed_panels(self):
        self.project['pages'][0]['panels']=self.project['pages'][0]['panels'][:2]
        self.store.project(self.project)
        job,_=self.create('panels'); await self.until(lambda:len(self.fake.pending)==1)
        first=next(iter(self.fake.pending)); self.fake.complete(first)
        await self.until(lambda:len(self.fake.submitted)==2)
        second=next(iter(self.fake.pending))
        latest=self.store.get('job',job['id']); latest['cancel_requested']=True; self.store.put('job',latest)
        await self.until(lambda:self.store.get('job',job['id'])['state']=='cancelled')
        before=self.store.get('job',job['id'])['units'][0]['asset']
        self.assertEqual(self.fake.interrupted,[second])
        await asyncio.gather(self.engine.resume(job['id']),self.engine.resume(job['id']))
        await self.until(lambda:len(self.fake.submitted)==3)
        self.assertNotEqual(next(iter(self.fake.pending)),second)
        self.fake.complete(next(iter(self.fake.pending)))
        await self.until(lambda:self.store.get('job',job['id'])['state']=='completed')
        self.assertEqual(self.store.get('job',job['id'])['units'][0]['asset'],before)
        self.assertEqual(self.fake.submitted.count(first),1)

    async def test_crop_edit_preserves_every_pixel_outside_rectangle(self):
        source=self.engine.asset(image_data((512,512),'#246892'))
        job,_=self.create('edit',source=source['id'],instruction='Change the sky',crop=[250,250,500,500])
        await self.until(lambda:len(self.fake.pending)==1)
        self.fake.complete(next(iter(self.fake.pending)),color='#ffffff')
        await self.until(lambda:self.store.get('job',job['id'])['state']=='completed')
        result=self.store.get('job',job['id'])['units'][0]['asset']
        with Image.open(self.store.asset_path(result)) as im:
            self.assertEqual(im.size,(512,512))
            self.assertEqual(im.getpixel((0,0)),(36,104,146))
            self.assertEqual(im.getpixel((127,200)),(36,104,146))
            self.assertEqual(im.getpixel((384,200)),(36,104,146))
            self.assertEqual(im.getpixel((250,250)),(255,255,255))
            for rectangle in ((0,0,512,128),(0,384,512,512),(0,128,128,384),(384,128,512,384)):
                self.assertEqual(im.crop(rectangle).getcolors(),[(Image.new('RGB',(rectangle[2]-rectangle[0],rectangle[3]-rectangle[1])).width*(rectangle[3]-rectangle[1]),(36,104,146))])

    async def test_cancel_flag_survives_save_after_download(self):
        job,_=self.create()
        latest=copy.deepcopy(job); latest['cancel_requested']=True; self.store.put('job',latest)
        self.engine.save(job,'preparing','download completed')
        self.assertTrue(self.store.get('job',job['id'])['cancel_requested'])
        await self.until(lambda:self.store.get('job',job['id'])['state']=='cancelled')
        self.assertEqual(self.fake.submitted,[])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        app=proxy_app('http://127.0.0.1:1', {'username':'moss','password':'test'},self.root)
        self.engine=next(v for v in app.values() if isinstance(v,Engine))
        self.engine.fonts=AsyncMock(return_value=FONT)
        self.client=TestClient(TestServer(app)); await self.client.start_server()
        self.auth=BasicAuth('moss','test')
        self.headers={'X-Moss-Studio':'1'}

    async def asyncTearDown(self):
        await self.client.close(); self.tmp.cleanup()

    async def test_studio_assets_and_state_require_login_and_same_origin_mutations(self):
        for route in ('/studio/','/studio/api/bootstrap','/studio/app.js','/studio/api/assets/anything'):
            self.assertEqual((await self.client.get(route)).status,401)
        self.assertEqual((await self.client.post('/studio/api/projects',auth=self.auth)).status,403)
        self.assertEqual((await self.client.post('/studio/api/projects',auth=self.auth,headers=self.headers|{'Origin':'https://another.example'})).status,403)
        response=await self.client.get('/studio/api/bootstrap',auth=self.auth)
        self.assertEqual(response.status,200)
        self.assertEqual(len((await response.json())['projects']),1)

    async def test_chunked_upload_and_revision_conflict(self):
        async def chunks(raw):
            for offset in range(0,len(raw),27):
                yield raw[offset:offset+27]; await asyncio.sleep(0)
        response=await self.client.post('/studio/api/assets',auth=self.auth,headers=self.headers,data=chunks(image_data()))
        self.assertEqual(response.status,200,await response.text())
        asset=await response.json()
        p=await (await self.client.post('/studio/api/projects',auth=self.auth,headers=self.headers)).json()
        p['reference']=asset['id']; p['title']='保存確認'
        route='/studio/api/projects/'+p['id']
        response=await self.client.put(route,auth=self.auth,headers=self.headers|{'Content-Type':'application/json'},data=chunks(json.dumps(p).encode()))
        self.assertEqual(response.status,200,await response.text())
        response=await self.client.put(route,auth=self.auth,headers=self.headers,json=p)
        self.assertEqual(response.status,409)
        response=await self.client.get(route+'/pages/missing/preview',auth=self.auth)
        self.assertEqual(response.status,404)

    @unittest.skipUnless(FONT.is_file(),'Set MOSS_TEST_FONT to the verified Noto Japanese OTF for render integration')
    async def test_japanese_preview_png_and_portable_svg_zip(self):
        p=validate_project(default_project()); pg=p['pages'][0]
        asset=self.engine.asset(image_data((1152,1728),'#4d7564'))
        pg['background']=asset['id']
        pg['bubbles']=[dict(id='b1',box=[700,100,230,400],text='「ここにいるよ」\nマリアン',size=40,direction='vertical',shape='ellipse'),
                       dict(id='b2',box=[100,700,600,100],text='<script>&安全な文字',size=32,direction='horizontal',shape='rect')]
        self.engine.store.project(p)
        route=f'/studio/api/projects/{p["id"]}/pages/{pg["id"]}'
        response=await self.client.get(route+'/preview',auth=self.auth)
        self.assertEqual(response.content_type,'image/png')
        preview=await response.read()
        with Image.open(io.BytesIO(preview)) as im:
            self.assertEqual(im.size,(1152,1728))
            self.assertEqual(im.getpixel((0,0)),(77,117,100))
            self.assertGreater(len(im.crop((806,173,1071,864)).getcolors(1_000_000)),10)
        svg=svg_page(p,pg,self.engine.store,FONT,embed=True).decode()
        self.assertIn('data:image/png;base64,',svg); self.assertIn('data:font/otf;base64,',svg)
        self.assertNotIn('<script>',svg); self.assertIn('&lt;script&gt;&amp;',svg)
        response=await self.client.get(route+'/zip',auth=self.auth)
        self.assertEqual(response.status,200)
        with zipfile.ZipFile(io.BytesIO(await response.read())) as z:
            self.assertEqual(json.loads(z.read('project.json'))['id'],p['id'])
            self.assertEqual(z.read('page.png'),preview)
            self.assertIn('assets/'+asset['id']+'.png',z.namelist())


if __name__=='__main__': unittest.main()
