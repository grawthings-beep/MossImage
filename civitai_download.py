"""Resumable Civitai downloads. Credentials and signed URLs never enter logs."""
import os
import http.client
import argparse
import json
from pathlib import Path
import re
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request


def api_request(pin, offset=0, check=False):
    parsed = urllib.parse.urlsplit(pin['url'])
    if parsed.scheme != 'https' or parsed.hostname not in ('civitai.red', 'civitai.com'):
        raise ValueError('Civitai download URL must use the official HTTPS API.')
    token = os.environ.get('CIVITAI_TOKEN', '').strip()
    if not token:
        raise RuntimeError('CIVITAI_TOKENが生成プロセスに渡っていません。RunPodのPod／Templateの環境変数でシークレットを割り当ててください。')
    if '{{' in token or '}}' in token:
        raise RuntimeError('CIVITAI_TOKENにシークレット参照式が未展開で入っています。RunPodの環境変数の鍵アイコンからシークレットを割り当て直してください。')
    if any(c.isspace() for c in token) or not token.isascii():
        raise RuntimeError('CIVITAI_TOKENに空白・改行または使用できない文字が含まれています。CivitaiのAPIキーを確認してください。')
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if key not in ('token', 'refresh')]
    query.append(('refresh', f'{time.time_ns()}-{secrets.token_hex(4)}'))
    url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    # A Mozilla UA selects the site's browser-login redirect instead of JSON API errors.
    headers = {'User-Agent': 'MossImage/1.1', 'Accept': 'application/octet-stream, application/json',
               'Accept-Encoding': 'identity'}
    if check or offset:
        headers['Range'] = 'bytes=0-7' if check else f'bytes={offset}-'
    request = urllib.request.Request(url, headers=headers)
    # urllib omits unredirected headers on the signed CDN redirect.
    request.add_unredirected_header('Authorization', f'Bearer {token}')
    return request


def http_error_message(error):
    """Classify provider errors without returning raw bodies, URLs or credentials."""
    with error:
        try:
            body = error.read(8192).decode('utf-8', errors='replace').lower()
        except (OSError, http.client.HTTPException):
            body = ''
    if error.headers and error.headers.get('cf-mitigated') == 'challenge':
        return 'Civitaiの配信側でアクセス確認が要求されました（HTTP 403）。APIキーの誤りとは断定できません。'
    if 'disabled downloads' in body or error.code == 410:
        return 'このモデルはCivitai側でダウンロードが停止・無効化されています。'
    if error.code == 401:
        return 'CIVITAI_TOKENは設定されていますが、Civitaiの認証が通りません（HTTP 401）。APIキーの有効性を確認してください。'
    if error.code == 403:
        if 'early access' in body:
            return 'CivitaiがEarly Accessの利用権限を要求しています（HTTP 403）。'
        if 'do not have access' in body:
            return 'Civitaiがこのアカウントのモデル取得権限を拒否しました（HTTP 403）。'
        return 'Civitaiまたは配信先が取得を拒否しました（HTTP 403）。APIキー・取得権限・配信側の制限を確認してください。'
    if error.code == 404:
        return '指定モデルファイルをCivitaiが見つけられませんでした（HTTP 404）。'
    if error.code == 429:
        return 'Civitaiのダウンロード回数制限です（HTTP 429）。時間を置いて準備を再試行してください。'
    return f'Civitaiの配信エラーです（HTTP {error.code}）。準備を再試行してください。'


def reject_html(response):
    if (urllib.parse.urlsplit(response.geturl()).path.startswith('/login')
            or 'text/html' in response.headers.get('Content-Type', '').lower()):
        raise RuntimeError('Civitaiからモデルの代わりにログイン／確認画面が返りました。CIVITAI_TOKENとCivitaiのアカウント状態を確認してください。')


def preflight(pin, runtime):
    """Check access before installing dependencies or downloading multi-GB weights."""
    models = Path(runtime) / 'ComfyUI/models'
    destination = models / pin['destination']
    partial = models / '.studio-downloads/cottonmoss' / (destination.name + '.partial')
    if any(p.is_file() and p.stat().st_size == pin['size'] for p in (destination, partial)):
        print('CottonMoss: local file found; full checksum verification follows during setup.', flush=True)
        return
    request = api_request(pin, check=True)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            reject_html(response)
            if response.status not in (200, 206):
                raise RuntimeError(f'Civitai事前確認でHTTP {response.status}が返りました。')
            if response.status == 206:
                content_range = response.headers.get('Content-Range', '')
                if not re.fullmatch(rf'bytes 0-\d+/{pin["size"]}', content_range):
                    raise RuntimeError('Civitai事前確認で指定モデルと異なる容量が返りました。')
            first = response.read(8)
            if len(first) != 8 or not 2 <= struct.unpack('<Q', first)[0] <= 100_000_000:
                raise RuntimeError('Civitaiからモデルのヘッダーを受信できませんでした。')
    except urllib.error.HTTPError as error:
        raise RuntimeError(http_error_message(error)) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
        raise RuntimeError('Civitaiへの事前接続に失敗しました。DNS・通信または配信側の障害です。準備を再試行してください。') from None
    print('CottonMoss: API authentication and model-byte access OK.', flush=True)


def download(pin, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error = '通信が中断しました。'
    for attempt in range(3):
        offset = target.stat().st_size if target.exists() else 0
        if offset == pin['size']:
            return target
        if offset > pin['size']:
            target.unlink()
            offset = 0
        try:
            request = api_request(pin, offset)
            with urllib.request.urlopen(request, timeout=120) as response:
                reject_html(response)
                if response.status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not match or int(match[1]) != offset or int(match[3]) != pin['size']:
                        raise RuntimeError('Civitaiの再開位置またはモデル容量が固定版と一致しません。')
                elif response.status == 200:
                    offset = 0  # Server ignored Range: restart, never append a full file.
                else:
                    raise RuntimeError(f'Civitai returned unexpected HTTP {response.status}.')
                with target.open('ab' if offset else 'wb') as output:
                    last_report = time.monotonic()
                    print(f'CottonMoss: {offset / pin["size"]:.0%} downloaded', flush=True)
                    while chunk := response.read(1024 * 1024):
                        offset += len(chunk)
                        if offset > pin['size']:
                            raise RuntimeError('Civitaiから固定版の容量を超えるデータを受信しました。')
                        output.write(chunk)
                        if time.monotonic() - last_report >= 10:
                            print(f'CottonMoss: {offset / pin["size"]:.0%} downloaded', flush=True)
                            last_report = time.monotonic()
            if offset == pin['size']:
                return target
        except urllib.error.HTTPError as error:
            last_error = http_error_message(error)
            cdn_denied = error.code == 403 and urllib.parse.urlsplit(error.url).hostname not in ('civitai.red', 'civitai.com')
            challenged = error.headers and error.headers.get('cf-mitigated') == 'challenge'
            if error.code not in (408, 500, 502, 503, 504) and not (cdn_denied and not challenged):
                raise RuntimeError(last_error) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            last_error = '通信が中断しました。'
        if attempt < 2:
            print('CottonMoss: connection interrupted; resuming download.', flush=True)
            time.sleep(2)
    raise RuntimeError(f'CottonMossの取得が中断しました。{last_error}「準備を再試行」で途中から再開できます。') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    pins = json.loads(Path(__file__).with_name('studio').joinpath('models.json').read_text(encoding='utf-8'))
    try:
        preflight(pins['cottonmoss'], args.runtime)
    except RuntimeError as error:
        print(f'MOSS_ERROR={error}', flush=True)
        raise SystemExit(1) from None
