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

from civitai_download import api_request, download, preflight
from studio.assets import Downloads


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None, url='https://cdn.example/model'):
        super().__init__(body)
        self.status, self.headers, self.url = status, headers or {}, url
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def geturl(self):
        return self.url


class CivitaiTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'CIVITAI_TOKEN': 'test-secret'}))
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
        with patch.dict(os.environ, {'CIVITAI_TOKEN': 'test-secret&+'}), \
             patch('civitai_download.urllib.request.urlopen', side_effect=responses) as fetch, \
             patch('civitai_download.time.sleep'), contextlib.redirect_stdout(output):
            download(self.pin, self.target)
        self.assertEqual(self.target.read_bytes(), self.data)
        second = fetch.call_args_list[1].args[0]
        self.assertEqual(second.get_header('Range'), 'bytes=20-')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(second.full_url).query)
        self.assertNotIn('token', query)
        self.assertEqual(second.get_header('Authorization'), 'Bearer test-secret&+')
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

    def test_api_auth_header_is_not_forwarded_to_signed_cdn(self):
        request = api_request(self.pin, 20)
        self.assertNotIn('Mozilla', request.get_header('User-agent'))
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, 302, 'Found', {}, 'https://cdn.example/file?signed=value')
        self.assertIsNone(redirected.get_header('Authorization'))
        self.assertEqual(redirected.get_header('Range'), 'bytes=20-')
        self.assertNotIn('test-secret', request.full_url)

    def test_preflight_only_reads_header_and_rejects_missing_or_unexpanded_secret(self):
        for token, expected in [('', '渡っていません'), ('{{ RUNPOD_SECRET_CIVITAI_TOKEN }}', '未展開')]:
            with patch.dict(os.environ, {'CIVITAI_TOKEN': token}), \
                 patch('civitai_download.urllib.request.urlopen') as fetch, \
                 self.assertRaisesRegex(RuntimeError, expected):
                preflight(self.pin, self.root)
            fetch.assert_not_called()
        response = Response(self.data, 206, {'Content-Range': f'bytes 0-7/{len(self.data)}'})
        with patch('civitai_download.urllib.request.urlopen', return_value=response) as fetch:
            preflight(self.pin, self.root)
        self.assertEqual(response.read_sizes, [8])
        self.assertEqual(fetch.call_args.args[0].get_header('Range'), 'bytes=0-7')

    def test_preflight_retains_existing_local_file_without_requiring_token(self):
        destination = self.root / 'ComfyUI/models' / self.pin['destination']
        destination.parent.mkdir(parents=True)
        destination.write_bytes(self.data)
        with patch.dict(os.environ, {'CIVITAI_TOKEN': ''}), \
             patch('civitai_download.urllib.request.urlopen') as fetch:
            preflight(self.pin, self.root)
        fetch.assert_not_called()

    def test_json_auth_failure_and_cloudflare_are_distinguished(self):
        for code, body, headers, expected in [
            (401, b'{"error":"Unauthorized"}', {}, 'HTTP 401'),
            (403, b'<html>blocked</html>', {'cf-mitigated': 'challenge'}, 'APIキーの誤りとは断定できません'),
            (403, b'{"error":"You do not have access to download this file"}', {}, '取得権限'),
            (429, b'{"error":"rate limit"}', {}, '回数制限'),
        ]:
            error = urllib.error.HTTPError(self.pin['url'], code, 'error', headers, io.BytesIO(body))
            with patch('civitai_download.urllib.request.urlopen', side_effect=error), \
                 self.assertRaisesRegex(RuntimeError, expected):
                preflight(self.pin, self.root)

    def test_expired_cdn_link_refreshes_from_api_but_403_at_api_stops(self):
        error = urllib.error.HTTPError('https://cdn.example/weights?signature=secret', 403, 'expired', {}, io.BytesIO(b'expired'))
        with patch('civitai_download.urllib.request.urlopen', side_effect=[error, Response(self.data)]) as fetch, \
             patch('civitai_download.time.sleep'):
            download(self.pin, self.target)
        self.assertEqual(self.target.read_bytes(), self.data)
        urls = [c.args[0].full_url for c in fetch.call_args_list]
        self.assertNotEqual(urls[0], urls[1])
        self.target.unlink()
        error = urllib.error.HTTPError(self.pin['url'], 403, 'Forbidden', {}, io.BytesIO(b'Forbidden'))
        with patch('civitai_download.urllib.request.urlopen', side_effect=error) as fetch, self.assertRaises(RuntimeError):
            download(self.pin, self.target)
        self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
