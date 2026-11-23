import base64
import json
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import credentials
from pod_boot import progress_server, run_setup
from studio.assets import PINS


class BootTests(unittest.TestCase):
    def test_preparation_failure_reaches_status_without_secret_or_signed_url(self):
        process = Mock()
        process.stdout = io.StringIO('MOSS_STAGE=Checking download\nMOSS_ERROR=HTTP 401 token=test-secret https://example.invalid/?signed=private\n')
        process.wait.return_value = 1
        process.poll.return_value = 1
        status = {'error': 'old failure'}
        with patch('pod_boot.subprocess.Popen', return_value=process), \
             patch.dict('os.environ', {'CIVITAI_TOKEN': 'test-secret'}):
            self.assertEqual(run_setup(status), 1)
        self.assertIn('HTTP 401', status['error'])
        self.assertNotIn('test-secret', status['error'])
        self.assertNotIn('signed=private', status['error'])
        self.assertEqual(status['message'], 'Checking download')

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

    def test_marciana_workflows_generate_once_and_save_both_resolutions(self):
        root = Path(__file__).resolve().parents[1]
        sizes = {'MOSS_08_Quality2x_marciana_marine_study.json': [1152, 1536, 1],
                 'MOSS_10_Fast2x_marciana_marine_study.json': [864, 1152, 1]}
        self.assertEqual({p.name for p in (root/'workflows').glob('*.json')}, set(sizes))
        for filename, size in sizes.items():
            with self.subTest(filename=filename):
                data = json.loads((root/'workflows'/filename).read_text(encoding='utf-8'))
                nodes = {n['id']: n for n in data['nodes']}
                self.assertEqual(nodes[1]['widgets_values'][0], PINS['cottonmoss']['file'])
                self.assertEqual(nodes[10]['widgets_values'], [PINS['marciana_marine_study']['file'], 1.0])
                self.assertEqual(nodes[20]['widgets_values'], [PINS['upscale_2x']['file']])
                self.assertIn('m4rc14n4m4r1ne', nodes[4]['widgets_values'][0])
                self.assertEqual(nodes[6]['widgets_values'], size)
                self.assertEqual(nodes[7]['widgets_values'][2:6], [12, 3.0, 'er_sde', 'simple'])
                self.assertEqual(sum(n['type'] == 'KSampler' for n in nodes.values()), 1)
                self.assertEqual(nodes[19]['widgets_values'], [1, 0.7])
                self.assertEqual(nodes[22]['widgets_values'], [0.25, 'normal'])
                self.assertTrue(nodes[9]['widgets_values'][0].endswith('/base'))
                self.assertTrue(nodes[23]['widgets_values'][0].endswith('/final'))
                expected = {(8,0,9,0), (8,0,19,0), (20,0,21,0), (19,0,21,1),
                            (21,0,22,0), (8,0,22,1), (22,0,23,0)}
                self.assertEqual({tuple(link[1:5]) for link in data['links']
                                  if link[3] in (9, 19, 21, 22, 23)}, expected)
