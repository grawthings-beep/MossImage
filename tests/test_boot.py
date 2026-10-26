import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import credentials
from pod_boot import progress_server
from characters import CHARACTERS


class BootTests(unittest.TestCase):
    def test_configured_password_used_without_overwriting_saved_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'login.json'
            with patch.dict('os.environ', {'MOSS_PASSWORD': ''}):
                original = credentials(path)
            with patch.dict('os.environ', {'MOSS_PASSWORD': 'chosen-test-password'}):
                self.assertEqual(credentials(path), {'username': 'moss', 'password': 'chosen-test-password'})
                self.assertEqual(json.loads(path.read_text()), original)

    def test_startup_progress_requires_login_and_retry_requires_csrf(self):
        status = {'ready': False, 'failed': True, 'message': 'test failed', 'csrf': 'csrf-test'}
        retry = threading.Event()
        server = progress_server('127.0.0.1', 0, {'username': 'moss', 'password': 'test-password'}, status, retry)
        base = f'http://127.0.0.1:{server.server_address[1]}'
        auth = 'Basic '+base64.b64encode(b'moss:test-password').decode()
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base+'/startup/status')
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
            with urllib.request.urlopen(urllib.request.Request(base+'/startup/status', headers={'Authorization': auth})) as r:
                data = json.load(r)
                self.assertTrue(data['failed'])
                self.assertNotIn('test-password', json.dumps(data))
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base+'/startup/retry', data=b'', headers={'Authorization': auth}))
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            self.assertFalse(retry.is_set())
            with urllib.request.urlopen(urllib.request.Request(base+'/startup/retry', data=b'', headers={'Authorization': auth, 'X-Moss-Boot': data['csrf']})) as r:
                self.assertEqual(r.status, 202)
            self.assertTrue(retry.is_set())
        finally:
            server.shutdown()
            server.server_close()

    def test_both_exported_workflows_have_the_requested_lora_size_and_steps(self):
        root = Path(__file__).resolve().parents[1]
        for c in CHARACTERS.values():
            with self.subTest(character=c['name']):
                data = json.loads((root/'workflows'/c['workflow']).read_text(encoding='utf-8'))
                nodes = {n['type']: n for n in data['nodes']}
                self.assertEqual(nodes['LoraLoaderModelOnly']['widgets_values'][0], c['file'])
                self.assertEqual(nodes['EmptyFlux2LatentImage']['widgets_values'], [1152, 1536, 1])
                self.assertEqual(nodes['KSampler']['widgets_values'][2:6], [25, 2.5, 'er_sde', 'simple'])
                positive = next(n for n in data['nodes'] if n['id'] == 4)
                self.assertIn(c['trigger'], positive['widgets_values'][0])
