"""Resumable Civitai downloads. Credentials and signed URLs never enter logs."""
import os
import http.client
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


def download(pin, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlsplit(pin['url'])
    if parsed.scheme != 'https' or parsed.hostname not in ('civitai.red', 'civitai.com'):
        raise ValueError('Civitai download URL must use the official HTTPS API.')
    token = os.environ.get('CIVITAI_TOKEN', '').strip()
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if token:
        query.append(('token', token))
    for attempt in range(3):
        # Each retry obtains a new signed CDN URL rather than reusing an expired one.
        fresh_query = query + [('refresh', str(time.time_ns()))]
        url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(fresh_query)))
        offset = target.stat().st_size if target.exists() else 0
        if offset == pin['size']:
            return target
        if offset > pin['size']:
            target.unlink()
            offset = 0
        headers = {'User-Agent': 'Mozilla/5.0 (MossImage RunPod downloader)', 'Accept-Encoding': 'identity'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                final_path = urllib.parse.urlsplit(response.geturl()).path
                if final_path.startswith('/login') or 'text/html' in response.headers.get('Content-Type', '').lower():
                    raise RuntimeError('Civitai認証が必要です。PodのCIVITAI_TOKENを確認してください。HF_TOKENとは別です。')
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
            if error.code in (401, 403):
                raise RuntimeError('Civitaiへのアクセスが拒否されました。PodのCIVITAI_TOKENとモデルのダウンロード権限を確認してください。') from None
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f'Civitai download failed (HTTP {error.code}).') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            pass
        if attempt < 2:
            print('CottonMoss: connection interrupted; resuming download.', flush=True)
            time.sleep(2)
    raise RuntimeError('CottonMossの取得が中断しました。「準備を再試行」で途中から再開できます。') from None
