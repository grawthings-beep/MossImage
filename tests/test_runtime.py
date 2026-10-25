import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from aiohttp import BasicAuth, WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import credentials
from launch_comfy import proxy_app
from prepare_comfy import install_workflow, valid_weights


class FileTests(unittest.TestCase):
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

    def test_existing_login_and_workflow_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            login = credentials(root / "login.json")
            self.assertEqual(credentials(root / "login.json"), login)
            pins = {"workflow_file": "moss_marian_queen2.json"}
            install_workflow(root, pins)
            path = root / "user/default/workflows/moss_marian_queen2.json"
            self.assertGreater(len(json.loads(path.read_text(encoding="utf-8"))["nodes"]), 0)
            path.write_text('{"user_edit": true}')
            install_workflow(root, pins)
            self.assertEqual(json.loads(path.read_text()), {"user_edit": True})


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

