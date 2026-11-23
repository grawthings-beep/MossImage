import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import BasicAuth, WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import credentials
from launch_comfy import proxy_app
from prepare_comfy import RETIRED_WORKFLOWS, install_workflows, valid_weights, prepare_generation_model


class FileTests(unittest.TestCase):
    def test_only_marciana_models_are_prepared(self):
        with tempfile.TemporaryDirectory() as directory, patch('studio.assets.Downloads.ensure') as ensure:
            prepare_generation_model(Path(directory))
            self.assertEqual([call.args[0] for call in ensure.call_args_list],
                             ['cottonmoss', 'marciana_marine_study', 'upscale_2x'])

    def test_truncated_download_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.safetensors"
            header = json.dumps({"x": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
            data = struct.pack("<Q", len(header)) + header + b"\0" * 4
            path.write_bytes(data)
            self.assertTrue(valid_weights(path))
            path.write_bytes(data[:-1])
            self.assertFalse(valid_weights(path))
            path.write_text("<html>authentication required</html>")
            self.assertFalse(valid_weights(path))

    def test_existing_login_and_saved_workflows_survive_migration_and_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            login = credentials(root / 'login.json')
            self.assertEqual(credentials(root / 'login.json'), login)
            profile = root / 'user/default'
            folder = profile / 'workflows'
            folder.mkdir(parents=True)
            custom = folder / 'my_workflow.json'
            custom.write_text('personal')
            archive = profile / 'moss-workflow-archive'
            archive.mkdir()
            previous = RETIRED_WORKFLOWS[0]
            (archive / previous).write_text('older')
            for filename in RETIRED_WORKFLOWS:
                (folder / filename).write_text('previous edit')
            install_workflows(root)
            kept = sorted(folder.glob('MOSS_*.json'))
            self.assertEqual(len(kept), 2)
            self.assertTrue(all('marciana_marine_study' in p.name for p in kept))
            kept[0].write_text('current edit')
            install_workflows(root)
            self.assertEqual(kept[0].read_text(), 'current edit')
            self.assertEqual(custom.read_text(), 'personal')
            self.assertEqual((archive / previous).read_text(), 'older')
            self.assertEqual((archive / f'{Path(previous).stem}-1.json').read_text(), 'previous edit')
            self.assertEqual(len(list(archive.iterdir())), len(RETIRED_WORKFLOWS) + 1)
            self.assertEqual(len(list(folder.iterdir())), 3)


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def echo(request):
            return web.json_response({
                "path": request.raw_path,
                "body": (await request.read()).decode(),
                "auth": request.headers.get("Authorization"),
                "host": request.headers["Host"],
            })

        async def websocket(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            async for message in socket:
                if isinstance(message.data, bytes):
                    await socket.send_bytes(message.data)
                else:
                    await socket.send_str(message.data)
            return socket

        upstream = web.Application()
        upstream.router.add_get('/', echo)
        upstream.router.add_route("*", "/echo", echo)
        upstream.router.add_get("/ws", websocket)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        self.client = TestClient(TestServer(proxy_app(
            str(self.upstream.make_url("")).rstrip("/"),
            {"username": "moss", "password": "test-password"},
        )))
        await self.client.start_server()
        self.auth = BasicAuth("moss", "test-password")

    async def test_native_comfy_home_is_forwarded_even_with_legacy_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(TestServer(proxy_app(str(self.upstream.make_url('')).rstrip('/'),
                {'username':'moss','password':'test-password'}, directory)))
            await client.start_server()
            try:
                response = await client.get('/', auth=self.auth, allow_redirects=False)
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())['path'], '/')
                self.assertNotIn('Location', response.headers)
            finally:
                await client.close()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()

    async def test_http_and_websocket_require_login(self):
        response = await self.client.get("/echo")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/echo", auth=BasicAuth("moss", "wrong"))
        self.assertEqual(response.status, 401)
        with self.assertRaises(WSServerHandshakeError) as raised:
            await self.client.ws_connect("/ws")
        self.assertEqual(raised.exception.status, 401)

    async def test_authenticated_api_keeps_body_query_host_but_not_credentials(self):
        response = await self.client.post(
            "/echo?name=%E3%83%9E%E3%83%AA%E3%82%A2%E3%83%B3&x=1&x=2",
            data="workflow payload", auth=self.auth, headers={"Host": "pod.proxy.runpod.net"},
        )
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertIn("&x=1&x=2", result["path"])
        self.assertEqual(result["body"], "workflow payload")
        self.assertEqual(result["host"], "pod.proxy.runpod.net")
        self.assertIsNone(result["auth"])

    async def test_progress_and_binary_previews_pass_through(self):
        async with self.client.ws_connect("/ws", auth=self.auth) as socket:
            await socket.send_str('{"type":"progress","value":1}')
            self.assertEqual(await socket.receive_str(), '{"type":"progress","value":1}')
            await socket.send_bytes(b"\x00\x01preview")
            self.assertEqual(await socket.receive_bytes(), b"\x00\x01preview")


if __name__ == "__main__":
    unittest.main()

