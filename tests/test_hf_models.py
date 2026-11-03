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

from hf_model_access import preflight
from studio.assets import Downloads


class HuggingFaceModelTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'HF_TOKEN': 'hf_test_secret', 'CIVITAI_TOKEN': ''}))
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        header = json.dumps({'x': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
        self.data = struct.pack('<Q', len(header)) + header + b'\0' * 4
        self.pin = {'repo': 'uwgm/Moss', 'revision': 'main', 'file': 'test.safetensors', 'token_env': 'HF_TOKEN',
                    'size': len(self.data), 'sha256': hashlib.sha256(self.data).hexdigest(),
                    'destination': 'diffusion_models/test.safetensors'}
        self.metadata = {'siblings': [{'rfilename': self.pin['file'], 'size': len(self.data),
                                      'lfs': {'sha256': self.pin['sha256'], 'size': len(self.data)}}]}

    def cached_file(self, **kwargs):
        path = Path(kwargs['local_dir']) / self.pin['file']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.data)
        return str(path)

    def test_private_download_uses_hf_token_and_reuses_verified_file(self):
        downloads = Downloads(self.root)
        def fetch(repo, filename, **kwargs):
            self.assertEqual((repo, filename), (self.pin['repo'], self.pin['file']))
            self.assertEqual(kwargs['token'], 'hf_test_secret')
            self.assertEqual(kwargs['revision'], 'main')
            return self.cached_file(**kwargs)
        with patch('studio.assets.PINS', {'cottonmoss': self.pin}), patch('studio.assets.hf_hub_download', side_effect=fetch) as api:
            result = downloads.ensure('cottonmoss')
            self.assertEqual(result.read_bytes(), self.data)
            with patch.dict(os.environ, {'HF_TOKEN': ''}):
                self.assertEqual(downloads.ensure('cottonmoss'), result)
                # A completed Hub download can also be installed after an interrupted rename.
                cached = downloads.models / '.studio-downloads/cottonmoss' / self.pin['file']
                result.rename(cached)
                self.assertEqual(downloads.ensure('cottonmoss').read_bytes(), self.data)
            self.assertEqual(api.call_count, 1)

    def test_public_model_does_not_receive_private_token(self):
        public_pin = {k: v for k, v in self.pin.items() if k != 'token_env'}
        with patch('studio.assets.PINS', {'sft': public_pin}), \
             patch('studio.assets.hf_hub_download', side_effect=lambda *a, **k: self.cached_file(**k)) as api:
            Downloads(self.root).ensure('sft')
        self.assertIs(api.call_args.kwargs['token'], False)

    def test_wrong_bytes_are_rejected_before_install_and_cache_is_cleared(self):
        def fetch(*args, **kwargs):
            path = Path(self.cached_file(**kwargs))
            path.write_bytes(self.data[:-1] + b'\1')
            return str(path)
        downloads = Downloads(self.root)
        with patch('studio.assets.PINS', {'cottonmoss': self.pin}), \
             patch('studio.assets.hf_hub_download', side_effect=fetch), self.assertRaises(RuntimeError):
            downloads.ensure('cottonmoss')
        self.assertFalse((downloads.models / self.pin['destination']).exists())
        self.assertFalse((downloads.models / '.studio-downloads/cottonmoss' / self.pin['file']).exists())

    def test_resume_space_accounts_for_the_matching_hub_partial(self):
        downloads = Downloads(self.root)
        partial = downloads.models / '.studio-downloads/cottonmoss/.cache/huggingface/download' / (f'test.{self.pin["sha256"]}.incomplete')
        partial.parent.mkdir(parents=True)
        partial.write_bytes(self.data[:20])
        with patch('studio.assets.PINS', {'cottonmoss': self.pin}), \
             patch('studio.assets.shutil.disk_usage', return_value=SimpleNamespace(free=2*2**30+len(self.data)-20)), \
             patch('studio.assets.hf_hub_download', side_effect=lambda *a, **k: self.cached_file(**k)):
            result = downloads.ensure('cottonmoss')
        self.assertEqual(result.read_bytes(), self.data)

    def test_preflight_checks_private_file_metadata_and_hash(self):
        response = io.BytesIO(json.dumps(self.metadata).encode())
        with patch('hf_model_access.urllib.request.urlopen', return_value=response) as api:
            preflight(self.pin, self.root)
        request = api.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer hf_test_secret')
        self.assertIn('huggingface.co/api/models/uwgm/Moss/revision/main', request.full_url)
        self.assertNotIn('hf_test_secret', request.full_url)
        self.metadata['siblings'][0]['lfs']['sha256'] = '0'*64
        with patch('hf_model_access.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(self.metadata).encode())), \
             self.assertRaisesRegex(RuntimeError, 'SHA256'):
            preflight(self.pin, self.root)

    def test_preflight_reports_missing_token_missing_file_and_auth_failure(self):
        for token, expected in [('', '渡っていません'), ('{{ RUNPOD_SECRET_HF_TOKEN }}', '未展開')]:
            with patch.dict(os.environ, {'HF_TOKEN': token}), \
                 patch('hf_model_access.urllib.request.urlopen') as api, self.assertRaisesRegex(RuntimeError, expected):
                preflight(self.pin, self.root)
            api.assert_not_called()
        with patch('hf_model_access.urllib.request.urlopen', return_value=io.BytesIO(b'{"siblings":[]}')), \
             self.assertRaisesRegex(RuntimeError, '見つかりません'):
            preflight(self.pin, self.root)
        error = urllib.error.HTTPError('https://huggingface.co/?secret=hf_test_secret', 401, 'Unauthorized', {}, io.BytesIO())
        with patch('hf_model_access.urllib.request.urlopen', side_effect=error), self.assertRaises(RuntimeError) as raised:
            preflight(self.pin, self.root)
        self.assertIn('HTTP 401', str(raised.exception))
        self.assertNotIn('hf_test_secret', str(raised.exception))

    def test_download_error_does_not_expose_token_or_signed_url(self):
        error = RuntimeError('https://cdn.example/?token=hf_test_secret')
        error.response = SimpleNamespace(status_code=403)
        with patch('studio.assets.PINS', {'cottonmoss': self.pin}), \
             patch('studio.assets.hf_hub_download', side_effect=error), self.assertRaises(RuntimeError) as raised:
            Downloads(self.root).ensure('cottonmoss')
        self.assertIn('HTTP 403', str(raised.exception))
        self.assertNotIn('hf_test_secret', str(raised.exception))

    def test_preflight_skips_network_for_complete_local_file(self):
        destination = self.root / 'ComfyUI/models' / self.pin['destination']
        destination.parent.mkdir(parents=True)
        destination.write_bytes(self.data)
        with patch.dict(os.environ, {'HF_TOKEN': ''}), patch('hf_model_access.urllib.request.urlopen') as api:
            preflight(self.pin, self.root)
        api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
