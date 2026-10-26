"""Authenticated Manga Studio routes, mounted before the ComfyUI proxy."""
import asyncio
import copy
import hmac
import io
import json
from pathlib import Path
import secrets
import zipfile
import uuid
from characters import CHARACTERS, image_prompt

from aiohttp import web
from .jobs import Engine, ACTIVE
from .render import png_page, svg_page
from .schema import default_project, validate_project, compile_prompt, ident, text
from .store import Store, Conflict

STATIC = Path(__file__).with_name('web')


def job_summary(job):
    return {k: v for k, v in job.items() if k not in ('snapshot', 'page', 'reference', 'units')} | {
        'units': [{k: v for k, v in unit.items() if k not in ('graph', 'prompt')} for unit in job['units']]}


def mount(app, runtime, upstream):
    store = Store(Path(runtime) / 'studio')
    engine = Engine(runtime, store, upstream)
    key = web.AppKey('studio_engine', Engine)
    app[key] = engine
    csrf_token = secrets.token_urlsafe(32)

    @web.middleware
    async def guard(request, handler):
        if not request.path.startswith('/studio'):
            return await handler(request)
        if request.method not in ('GET', 'HEAD'):
            # Reverse proxies can rewrite Host and scheme. A token read from our
            # authenticated bootstrap is independent of that rewriting; another
            # origin cannot read it because Studio does not enable CORS.
            provided = request.headers.get('X-Moss-CSRF', '')
            if not hmac.compare_digest(provided.encode(), csrf_token.encode()):
                return web.json_response({'error': '接続情報を更新して、もう一度操作してください。',
                                          'code': 'csrf_expired'}, status=403)
        try:
            response = await handler(request)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        except Conflict as error:
            return web.json_response({'error': str(error)}, status=409)
        except (ValueError, TypeError) as error:
            return web.json_response({'error': str(error)}, status=400)
        except KeyError:
            return web.json_response({'error': '対象が見つかりません。'}, status=404)
    app.middlewares.append(guard)

    async def context(app):
        await engine.start()
        try:
            yield
        finally:
            await engine.close()
            store.close()
    app.cleanup_ctx.append(context)

    async def read_limited(request, limit):
        chunks, size = [], 0
        async for chunk in request.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError('送信データが大きすぎます。')
            chunks.append(chunk)
        return b''.join(chunks)

    async def body(request):
        if request.content_type != 'application/json':
            raise ValueError('JSON形式で送信してください。')
        raw = await read_limited(request, 1_000_000)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('JSONオブジェクトが必要です。')
        return data

    def page_of(project, key):
        found = next((p for p in project['pages'] if p['id'] == key), None)
        if found is None:
            raise KeyError(key)
        return found

    def check_assets(project):
        ids = [project.get('reference')]
        for page in project['pages']:
            ids += [page.get('reference'), page.get('background'), *page['panel_images'].values()]
        for value in filter(None, ids):
            store.asset_path(value)

    async def index(request):
        return web.FileResponse(STATIC / 'index.html')

    async def image_index(request):
        return web.FileResponse(STATIC / 'image.html')

    async def static(request):
        name = request.match_info['name']
        if name not in ('app.js', 'style.css', 'image.js'):
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name)

    async def bootstrap(request):
        projects = [p for p in store.list('project') if p.get('mode') != 'image']
        if not projects:
            projects = [store.project(validate_project(default_project()))]
        return web.json_response({'csrf_token': csrf_token,
                                  'characters': CHARACTERS,
                                  'projects': [{'id': p['id'], 'title': p['title'], 'pages': len(p['pages'])} for p in projects],
                                  'jobs': [job_summary(j) for j in store.list('job')[:60]]})

    async def new_project(request):
        p = validate_project(default_project())
        data = await body(request) if request.can_read_body else {}
        character_id = data.get('character', 'marian')
        if character_id not in CHARACTERS:
            raise ValueError('キャラクターを選んでください。')
        if character_id != 'marian':
            c = CHARACTERS[character_id]
            p.update(title=c['name'], character=c['description'], trigger=c['trigger'])
            pg = p['pages'][0]
            pg.update(route=character_id, scene='A ruined shrine after rain. Red lanterns glow through the mist. The woman senses someone approaching.')
            for panel in pg['panels']:
                panel['caption'] = panel['caption'].replace('Marian', 'The woman').replace('crown and collar jewel', 'hair ornament and red scarf').replace('hip frills', 'scarf')
        return web.json_response(store.project(p))

    async def generate_image(request):
        data = await body(request)
        jid = str(uuid.UUID(str(data['id'])))
        try:
            return web.json_response(job_summary(store.get('job', jid)))
        except KeyError:
            pass
        cid = data.get('character', 'scarlet')
        if cid not in CHARACTERS:
            raise ValueError('キャラクターを選んでください。')
        prompt_text = text(data.get('prompt', ''), 16000).strip()
        if not prompt_text:
            raise ValueError('プロンプトを入力してください。')
        p = default_project()
        p.update(id='image_' + uuid.UUID(jid).hex, title=CHARACTERS[cid]['name'], mode='image')
        pg = p['pages'][0]
        pg.update(title=CHARACTERS[cid]['name'], route=cid, scene=image_prompt(cid, prompt_text),
                  width=data.get('width', 1152), height=data.get('height', 1536),
                  sampling=data.get('sampling', 'comfy'), seed=data.get('seed', 42),
                  lora_strength=data.get('lora_strength', 1.0))
        p = validate_project(p)
        # Immutable per-submission snapshot; repeated request IDs reuse the job above.
        store.put('project', p)
        return web.json_response(job_summary(engine.create({
            'id': jid, 'project_id': p['id'], 'page_id': pg['id'], 'kind': 'image'})))

    async def project(request):
        key = ident(request.match_info['id'])
        if request.method == 'GET':
            return web.json_response(store.get('project', key))
        data = validate_project(await body(request))
        if data['id'] != key:
            raise ValueError('作品IDが一致しません。')
        check_assets(data)
        return web.json_response(store.project(data))

    async def upload(request):
        raw = await read_limited(request, 25*1024**2)
        return web.json_response(engine.asset(raw))

    async def asset(request):
        return web.FileResponse(store.asset_path(ident(request.match_info['id'])))

    async def font(request):
        path = await engine.fonts()
        return web.FileResponse(path, headers={'Content-Type': 'font/otf'})

    async def prompt(request):
        p = store.get('project', ident(request.match_info['id']))
        page = page_of(p, request.match_info['page'])
        return web.json_response({'prompt': compile_prompt(p, page), 'width': page['width'], 'height': page['height']})

    async def export(request):
        p = store.get('project', ident(request.match_info['id']))
        page = page_of(p, request.match_info['page'])
        kind = request.match_info['kind']
        if kind not in ('png', 'svg', 'preview', 'zip'):
            raise web.HTTPNotFound()
        font_path = await engine.fonts()
        # Snapshot asset bytes on the event loop; rendering runs independently of HTTP/DB writes.
        class Assets:
            def asset_path(self, key):
                return store.root / 'assets' / (ident(key) + '.png')
        assets = Assets()
        def render():
            if kind == 'svg':
                return svg_page(p, page, assets, font_path, embed=True)
            if kind in ('png', 'preview'):
                return png_page(p, page, assets, font_path)
            result = io.BytesIO()
            with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('page.png', png_page(p, page, assets, font_path))
                z.writestr('page.svg', svg_page(p, page, assets, font_path, embed=True))
                z.writestr('project.json', json.dumps(p, ensure_ascii=False, indent=2))
                z.writestr('prompt.json', compile_prompt(p, page))
                z.write(font_path.parent / 'OFL.txt', 'OFL.txt')
                all_ids = {p.get('reference')}
                for pg in p['pages']:
                    all_ids.update([pg.get('reference'), pg.get('background'), *pg['panel_images'].values()])
                for aid in filter(None, all_ids):
                    z.write(assets.asset_path(aid), 'assets/'+aid+'.png')
            return result.getvalue()
        data = await asyncio.to_thread(render)
        content_type = {'png': 'image/png', 'svg': 'image/svg+xml', 'preview': 'image/png', 'zip': 'application/zip'}[kind]
        headers = {} if kind == 'preview' else {'Content-Disposition': f'attachment; filename="moss-{page["id"]}.{kind}"'}
        return web.Response(body=data, content_type=content_type, headers=headers)

    async def jobs(request):
        if request.method == 'POST':
            return web.json_response(job_summary(engine.create(await body(request))), status=202)
        project_id = request.query.get('project')
        result = [j for j in store.list('job') if not project_id or j['project_id'] == project_id]
        return web.json_response([job_summary(j) for j in result[:100]])

    async def job_action(request):
        jid = request.match_info['id']
        action = request.match_info['action']
        job = store.get('job', jid)
        if action == 'cancel':
            if job['state'] in ACTIVE:
                job['cancel_requested'] = True
                store.put('job', job)
            return web.json_response(job_summary(job))
        if action == 'resume':
            return web.json_response(job_summary(await engine.resume(jid)))
        if action == 'apply':
            data = await body(request)
            p = store.get('project', job['project_id'])
            if p['revision'] != data.get('revision'):
                raise Conflict('ページが更新されています。再読込してください。')
            page = page_of(p, job['page_id'])
            chosen = data.get('unit')
            completed = [u for u in job['units'] if u['state'] == 'completed' and (not chosen or chosen == u['id'])]
            if not completed:
                raise ValueError('完成した画像がありません。')
            for unit in completed:
                target = data.get('panel_id')
                if job['kind'] == 'panels':
                    target = unit['id']
                if target:
                    if target not in {panel['id'] for panel in page['panels']}:
                        raise ValueError('採用先のコマがありません。')
                    page['panel_images'][target] = unit['asset']
                else:
                    page['background'] = unit['asset']
                    page['panel_images'] = {}
            if job['kind'] == 'panels' and all(part['id'] in page['panel_images'] for part in page['panels']):
                # A fully assembled page has clean gutters, not fragments of an earlier full-page image.
                page['background'] = ''
            return web.json_response(store.project(p))
        if action == 'snapshot' and request.method == 'GET':
            return web.json_response(job, headers={'Content-Disposition': 'attachment; filename="generation.json"'})
        raise web.HTTPNotFound()

    async def redirect(request):
        raise web.HTTPFound('/studio/')

    app.router.add_get('/studio', redirect)
    app.router.add_get('/studio/', index)
    app.router.add_get('/studio/image', image_index)
    app.router.add_get('/studio/{name:app.js|style.css|image.js}', static)
    app.router.add_get('/studio/font.otf', font)
    app.router.add_get('/studio/api/bootstrap', bootstrap)
    app.router.add_post('/studio/api/projects', new_project)
    app.router.add_get('/studio/api/projects/{id}', project)
    app.router.add_put('/studio/api/projects/{id}', project)
    app.router.add_post('/studio/api/assets', upload)
    app.router.add_get('/studio/api/assets/{id}', asset)
    app.router.add_get('/studio/api/projects/{id}/pages/{page}/prompt', prompt)
    app.router.add_get('/studio/api/projects/{id}/pages/{page}/{kind}', export)
    app.router.add_get('/studio/api/jobs', jobs)
    app.router.add_post('/studio/api/jobs', jobs)
    app.router.add_post('/studio/api/images', generate_image)
    app.router.add_post('/studio/api/jobs/{id}/{action}', job_action)
    app.router.add_get('/studio/api/jobs/{id}/{action:snapshot}', job_action)
    return engine
