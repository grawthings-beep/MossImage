"""Show authenticated startup progress, then hand the same port to generation."""
import argparse
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading

from launch import credentials

KIT = Path(__file__).resolve().parent
PAGE = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MOSS 起動中</title><style>body{background:#10191e;color:#edf4ee;font:16px/1.8 system-ui;margin:0;display:grid;min-height:100vh;place-items:center}main{max-width:560px;padding:32px}h1{font-size:28px}button{background:#b6e8b2;border:0;border-radius:8px;padding:14px 24px;font:inherit}small{color:#a6b8b9}</style>
<main><h1>MOSSを準備しています</h1><p id="stage">起動確認中…</p><p>初回はモデルをダウンロードします。準備ができると画像生成画面へ移動します。</p><small>この画面を閉じても準備はPod側で続きます。</small><p><button id="retry" hidden>準備を再試行</button></p></main>
<script>const button=document.getElementById('retry');async function poll(){try{const r=await fetch('/startup/status',{cache:'no-store'});if(!r.ok)return;const s=await r.json();if(s.ready){location.replace(s.url);return;}document.getElementById('stage').textContent=s.message;button.hidden=!s.failed;button.onclick=async()=>{button.disabled=true;try{await fetch('/startup/retry',{method:'POST',headers:{'X-Moss-Boot':s.csrf}});}finally{button.disabled=false;}};}catch(e){}}poll();setInterval(poll,2500);</script></html>'''


def progress_server(host, port, login, status, retry):
    expected = ('Basic ' + base64.b64encode((login['username']+':'+login['password']).encode()).decode()).encode()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, content_type):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def authenticated(self):
            if hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected):
                return True
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="MOSS-Image", charset="UTF-8"')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False

        def do_GET(self):
            if not self.authenticated():
                return
            if self.path.split('?')[0] == '/startup/status':
                self.reply(200, json.dumps(status, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            else:
                self.reply(200, PAGE.encode(), 'text/html; charset=utf-8')

        do_HEAD = do_GET

        def do_POST(self):
            if not self.authenticated():
                return
            if self.path != '/startup/retry' or not hmac.compare_digest(self.headers.get('X-Moss-Boot', '').encode(), status['csrf'].encode()):
                self.reply(403, b'Forbidden', 'text/plain')
                return
            retry.set()
            self.reply(202, b'{}', 'application/json')
    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def run_setup(status):
    process = subprocess.Popen(['bash', str(KIT / 'setup.sh')], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        for line in process.stdout:
            print(line, end='', flush=True)
            if line.startswith('MOSS_STAGE='):
                status['message'] = line.partition('=')[2].strip()
        return process.wait()
    finally:
        process.stdout.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '7860')))
    args, extra = parser.parse_known_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    login = credentials(runtime / 'login.json')
    if not os.getenv('MOSS_PASSWORD'):
        print(f"Login user: {login['username']}\nLogin password: {login['password']}", flush=True)
    status = {'ready': False, 'failed': False, 'message': '起動確認中', 'csrf': secrets.token_urlsafe(32)}
    retry = threading.Event()
    server = progress_server(args.host, args.port, login, status, retry)
    def stopped(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stopped)
    gpu_lock = None
    try:
        import fcntl
        train_home = Path(os.getenv('MOSS_TRAIN_HOME', '/workspace/moss-training'))
        train_home.mkdir(parents=True, exist_ok=True)
        gpu_lock = (train_home / 'gpu.lock').open('a+')
        os.set_inheritable(gpu_lock.fileno(), True)
        while True:
            try:
                fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                status['message'] = 'LoRA学習の終了を待っています。終了後に生成の準備を始めます。'
                retry.wait(2)
                retry.clear()
        while True:
            status.update(failed=False, message='生成環境を準備しています')
            retry.clear()
            code = run_setup(status)
            if code == 0:
                break
            status.update(failed=True, message=f'準備が停止しました（終了コード {code}）。RunPodのLogsで原因を確認できます。')
            retry.wait()
        status['message'] = 'モデルの準備完了。生成サーバーを起動しています…'
    except BaseException:
        if gpu_lock:
            gpu_lock.close()
        raise
    finally:
        server.shutdown()
        server.server_close()
    python = str(runtime / 'comfy-venv/bin/python')
    os.execv(python, [python, '-u', str(KIT / 'launch_comfy.py'), '--runtime', str(runtime),
                     '--host', args.host, '--port', str(args.port), *extra])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
