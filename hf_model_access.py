"""Check the private model before installing dependencies; standard library only."""
import argparse
import http.client
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def model_token(pin):
    name = pin.get('token_env')
    if not name:
        return False  # Public models never receive the private repository token.
    token = os.environ.get(name, '').strip()
    if not token:
        raise RuntimeError(f'{name}が生成プロセスに渡っていません。RunPodの環境変数へシークレットを割り当ててください。')
    if '{{' in token or '}}' in token:
        raise RuntimeError(f'{name}にシークレット参照式が未展開で入っています。RunPodの鍵アイコンから割り当て直してください。')
    if any(c.isspace() for c in token) or not token.isascii():
        raise RuntimeError(f'{name}の値の形式が正しくありません。Hugging Faceの読み取りトークンを確認してください。')
    return token


def access_error(pin, status):
    if status in (401, 403, 404):
        return (f'Hugging Faceの{pin["repo"]}または指定ファイルにアクセスできません（HTTP {status}）。'
                f'{pin.get("token_env", "HF_TOKEN")}の読み取り権限とアップロード済みのファイル名を確認してください。')
    return f'Hugging Faceの取得に失敗しました（HTTP {status}）。準備を再試行してください。'


def preflight(pin, runtime):
    models = Path(runtime) / 'ComfyUI/models'
    destination = models / pin['destination']
    cached = models / '.studio-downloads/cottonmoss' / pin['file']
    if any(p.is_file() and p.stat().st_size == pin['size'] for p in (destination, cached)):
        print('CottonMoss: local file found; full checksum verification follows during setup.', flush=True)
        return
    token = model_token(pin)
    repo = urllib.parse.quote(pin['repo'], safe='/')
    revision = urllib.parse.quote(pin['revision'], safe='')
    request = urllib.request.Request(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true',
                                     headers={'User-Agent': 'MossImage/1.2', 'Accept': 'application/json'})
    if token:
        request.add_unredirected_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            metadata = json.load(response)
    except urllib.error.HTTPError as error:
        error.close()
        raise RuntimeError(access_error(pin, error.code)) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
        raise RuntimeError('Hugging Faceへの事前接続に失敗しました。準備を再試行してください。') from None
    except ValueError:
        raise RuntimeError('Hugging Faceからモデル情報を取得できませんでした。準備を再試行してください。') from None
    match = next((file for file in metadata.get('siblings', []) if file['rfilename'] == pin['file']), None)
    if not match:
        raise RuntimeError(f'{pin["repo"]}に{pin["file"]}が見つかりません。アップロードの完了を確認してください。')
    lfs = match.get('lfs') or {}
    if match.get('size', lfs.get('size')) != pin['size'] or lfs.get('sha256', '').lower() != pin['sha256']:
        raise RuntimeError('Hugging FaceのCottonMossが指定版のサイズ・SHA256と一致しません。別ファイルを取得せず停止しました。')
    print('CottonMoss: Hugging Face access, filename, size and SHA256 metadata OK.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    pins = json.loads((Path(__file__).parent / 'studio/models.json').read_text(encoding='utf-8'))
    try:
        preflight(pins['cottonmoss'], args.runtime)
    except RuntimeError as error:
        print(f'MOSS_ERROR={error}', flush=True)
        raise SystemExit(1) from None
