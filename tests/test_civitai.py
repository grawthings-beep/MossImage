import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

from civitai_download import download
from studio.assets import Downloads


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None, url='https://cdn.example/model'):
        super().__init__(body)
        self.status, self.headers, self.url = status, headers or {}, url

    def geturl(self):
        return self.url


class CivitaiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        header = json.dumps({'x': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
        self.data = struct.pack('<Q', len(header)) + header + b'\0' * 4
        self.pin = {'url': 'https://civitai.red/api/download/models/3437076?fileId=3334385',
                    'size': len(self.data), 'sha256': hashlib.sha256(self.data).hexdigest(),
                    'destination': 'diffusion_models/test.safetensors'}
        self.target = self.root / 'model.partial'

    def test_interrupted_download_resumes_without_logging_token(self):
        responses = [Response(self.data[:20]), Response(self.data[20:], 206,
                     {'Content-Range': f'bytes 20-{len(self.data)-1}/{len(self.data)}'})]
        output = io.StringIO()
        with patch.dict(os.environ, {'CIVITAI_TOKEN': 'test-secret &+'}), \
             patch('civitai_download.urllib.request.urlopen', side_effect=responses) as fetch, \
             patch('civitai_download.time.sleep'), contextlib.redirect_stdout(output):
            download(self.pin, self.target)
        self.assertEqual(self.target.read_bytes(), self.data)
        second = fetch.call_args_list[1].args[0]
        self.assertEqual(second.get_header('Range'), 'bytes=20-')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(second.full_url).query)
        self.assertEqual(query['token'], ['test-secret &+'])
        self.assertNotIn('test-secret', output.getvalue())

    def test_server_ignores_range_restarts_instead_of_appending(self):
        self.target.write_bytes(self.data[:20])
        with patch('civitai_download.urllib.request.urlopen', return_value=Response(self.data)):
            download(self.pin, self.target)
        self.assertEqual(self.target.read_bytes(), self.data)

    def test_bad_range_is_rejected_without_corrupting_partial(self):
        self.target.write_bytes(self.data[:20])
        response = Response(self.data, 206, {'Content-Range': f'bytes 0-{len(self.data)-1}/{len(self.data)}'})
        with patch('civitai_download.urllib.request.urlopen', return_value=response), self.assertRaises(RuntimeError):
            download(self.pin, self.target)
        self.assertEqual(self.target.read_bytes(), self.data[:20])

    def test_login_page_and_auth_errors_never_save_html_or_expose_token(self):
        with patch.dict(os.environ, {'CIVITAI_TOKEN': 'test-secret'}):
            for result in [Response(b'<html>login</html>', headers={'Content-Type': 'text/html'}),
                           urllib.error.HTTPError('https://civitai.red/?token=test-secret', 403, 'Forbidden', {}, None)]:
                kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with patch('civitai_download.urllib.request.urlopen', **kwargs), self.assertRaises(RuntimeError) as raised:
                    download(self.pin, self.target)
                self.assertNotIn('test-secret', str(raised.exception))
                self.assertFalse(self.target.exists())

    def test_checksum_checked_before_install_and_valid_file_reused(self):
        downloads = Downloads(self.root)
        destination = downloads.models / self.pin['destination']
        with patch('studio.assets.PINS', {'cottonmoss': self.pin}):
            with patch('civitai_download.urllib.request.urlopen', return_value=Response(self.data)):
                self.assertEqual(downloads.ensure('cottonmoss'), destination)
            self.assertEqual(destination.read_bytes(), self.data)
            with patch('civitai_download.urllib.request.urlopen') as fetch:
                downloads.ensure('cottonmoss')
                fetch.assert_not_called()
            destination.unlink()
            bad = self.data[:-1] + b'\1'
            with patch('civitai_download.urllib.request.urlopen', return_value=Response(bad)), self.assertRaises(RuntimeError):
                downloads.ensure('cottonmoss')
            self.assertFalse(destination.exists())
            self.assertFalse(list(downloads.models.rglob('*.partial')))

    def test_resume_only_requires_space_for_remaining_bytes(self):
        downloads = Downloads(self.root)
        cached = downloads.models / '.studio-downloads/cottonmoss/test.safetensors.partial'
        cached.parent.mkdir(parents=True)
        cached.write_bytes(self.data[:20])
        response = Response(self.data[20:], 206, {'Content-Range': f'bytes 20-{len(self.data)-1}/{len(self.data)}'})
        with patch('studio.assets.PINS', {'cottonmoss': self.pin}), \
             patch('studio.assets.shutil.disk_usage', return_value=SimpleNamespace(free=2*2**30+len(self.data)-20)), \
             patch('civitai_download.urllib.request.urlopen', return_value=response):
            destination = downloads.ensure('cottonmoss')
        self.assertEqual(destination.read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
