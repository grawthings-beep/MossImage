"""On-demand, pinned downloads. No model repository executes code."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request

from huggingface_hub import hf_hub_download
from hf_model_access import access_error, model_token
from prepare_comfy import valid_weights

PINS = json.loads(Path(__file__).with_name('models.json').read_text(encoding='utf-8'))
FONT_REV = 'f8d157532fbfaeda587e826d4cd5b21a49186f7c'
FONT_FILES = {
    'NotoSansCJKjp-Regular.otf': ('Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf', '68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5'),
    'OFL.txt': ('Sans/LICENSE', '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2'),
}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Downloads:
    def __init__(self, runtime):
        self.models = Path(runtime) / 'ComfyUI/models'
        self.fonts = Path(runtime) / 'studio/fonts'

    def ensure(self, name):
        pin = PINS[name]
        destination = self.models / pin['destination']
        marker = destination.with_suffix('.verified.json')
        if valid_weights(destination):
            if destination.stat().st_size != pin['size']:
                raise RuntimeError(f'既存モデルが固定版と異なります。上書きせず停止しました: {destination.name}')
            signature = {'sha256': pin['sha256'], 'size': destination.stat().st_size, 'mtime': destination.stat().st_mtime_ns}
            try:
                if json.loads(marker.read_text()) == signature:
                    return destination
            except (OSError, ValueError):
                pass
            if sha256(destination) == pin['sha256']:
                marker.write_text(json.dumps(signature))
                return destination
            raise RuntimeError(f'既存モデルのチェックサムが一致しません: {destination.name}')
        self.models.mkdir(parents=True, exist_ok=True)
        needed = pin['size']
        cache_dir = self.models / '.studio-downloads' / name
        # Hub stores resumable chunks under its local_dir download cache, keyed by ETag.
        partials = list((cache_dir / '.cache/huggingface/download').rglob(f'*.{pin["sha256"]}.incomplete'))
        partial_size = sum(path.stat().st_size for path in partials)
        if partial_size <= pin['size']:
            needed -= partial_size
        complete_cache = cache_dir / pin['file']
        if complete_cache.is_file() and complete_cache.stat().st_size == pin['size']:
            needed = 0
        if shutil.disk_usage(self.models).free < needed + 2 * 2**30:
            raise RuntimeError(f'{name}の取得には、残りの取得容量に加えて2GiBの空きが必要です。')
        if complete_cache.is_file() and complete_cache.stat().st_size == pin['size']:
            cached = complete_cache
        else:
            token = model_token(pin)
            try:
                cached = Path(hf_hub_download(pin['repo'], pin['file'], revision=pin['revision'],
                                             token=token, local_dir=cache_dir))
            except Exception as error:
                status = getattr(getattr(error, 'response', None), 'status_code', None)
                if status is not None:
                    raise RuntimeError(access_error(pin, status)) from None
                raise RuntimeError(f'{name}のHugging Faceダウンロードに失敗しました（{type(error).__name__}）。準備を再試行してください。') from None
        if not valid_weights(cached) or cached.stat().st_size != pin['size'] or sha256(cached) != pin['sha256']:
            cached.unlink(missing_ok=True)
            raise RuntimeError(f'{name}のダウンロード検証に失敗しました。')
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(cached, destination)
        marker.write_text(json.dumps({'sha256': pin['sha256'], 'size': destination.stat().st_size, 'mtime': destination.stat().st_mtime_ns}))
        return destination

    def ensure_fonts(self):
        self.fonts.mkdir(parents=True, exist_ok=True)
        for name, (source, digest) in FONT_FILES.items():
            destination = self.fonts / name
            if destination.exists() and sha256(destination) == digest:
                continue
            url = f'https://raw.githubusercontent.com/notofonts/noto-cjk/{FONT_REV}/{source}'
            temporary = destination.with_suffix('.partial')
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as out:
                shutil.copyfileobj(response, out)
            if sha256(temporary) != digest:
                raise RuntimeError('日本語フォントのダウンロード検証に失敗しました。')
            os.replace(temporary, destination)
        return self.fonts / 'NotoSansCJKjp-Regular.otf'


def required_models(page, kind):
    if kind == 'edit':
        return ['sft', 'edit'] + (['full_vae'] if page['vae'] == 'full' else [])
    names = []
    if page['route'] == 'sft':
        names.append('sft')
    if page['route'] == 'reference':
        names.append('charref')
    if page['hires'] and kind == 'page':
        names.append('hires')
    if page['vae'] == 'full':
        names.append('full_vae')
    return names
