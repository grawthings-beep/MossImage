"""Serve native ComfyUI behind the kit's existing per-Pod login."""
import argparse
import asyncio
import contextlib
import hmac
import os
from pathlib import Path
import socket
import sys

from aiohttp import BasicAuth, ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, web
from multidict import CIMultiDict
from yarl import URL

from launch import credentials

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}


def forwarded_headers(headers):
    blocked = HOP_HEADERS | {
        h.strip().lower() for h in headers.get("Connection", "").split(",")
    }
    return CIMultiDict(
        (key, value) for key, value in headers.items()
        if key.lower() not in blocked
        and key.lower() != "authorization"
        and not key.lower().startswith("sec-websocket-")
    )


def proxy_app(upstream, login):
    expected = BasicAuth(login["username"], login["password"]).encode()

    @web.middleware
    async def authenticate(request, handler):
        provided = request.headers.get("Authorization", "")
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="MOSS-Image"'})
        return await handler(request)

    app = web.Application(middlewares=[authenticate], client_max_size=1024**3)
    session_key = web.AppKey("session", ClientSession)

    async def session_context(app):
        async with ClientSession(
            auto_decompress=False, timeout=ClientTimeout(total=None),
            cookie_jar=DummyCookieJar(),
        ) as session:
            app[session_key] = session
            yield

    app.cleanup_ctx.append(session_context)

    async def proxy(request):
        target = URL(upstream + request.raw_path, encoded=True)
        headers = forwarded_headers(request.headers)
        session = request.app[session_key]
        if request.headers.get("Upgrade", "").lower() == "websocket":
            async with session.ws_connect(target, headers=headers, max_msg_size=0) as remote:
                local = web.WebSocketResponse(max_msg_size=0)
                await local.prepare(request)

                async def relay(source, destination):
                    async for message in source:
                        if message.type == WSMsgType.TEXT:
                            await destination.send_str(message.data)
                        elif message.type == WSMsgType.BINARY:
                            await destination.send_bytes(message.data)
                        elif message.type == WSMsgType.ERROR:
                            break
                    await destination.close()

                tasks = [asyncio.create_task(relay(local, remote)),
                         asyncio.create_task(relay(remote, local))]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                return local
        async with session.request(
            request.method, target, headers=headers, data=request.content,
            allow_redirects=False,
        ) as response:
            result = web.StreamResponse(
                status=response.status, reason=response.reason,
                headers=forwarded_headers(response.headers),
            )
            await result.prepare(request)
            async for chunk in response.content.iter_chunked(256 * 1024):
                await result.write(chunk)
            await result.write_eof()
            return result

    app.router.add_route("*", "/{path:.*}", proxy)
    return app


async def serve(args):
    runtime = args.runtime.resolve()
    comfy = runtime / "ComfyUI"
    login = credentials(runtime / "login.json")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        internal_port = listener.getsockname()[1]
    command = [
        sys.executable, "-u", str(comfy / "main.py"),
        "--listen", "127.0.0.1", "--port", str(internal_port),
        "--disable-auto-launch", "--disable-all-custom-nodes",
    ]
    if args.cpu:
        command.append("--cpu")
    process = await asyncio.create_subprocess_exec(*command, cwd=comfy)
    upstream = f"http://127.0.0.1:{internal_port}"
    runner = None
    try:
        async with ClientSession(timeout=ClientTimeout(total=2)) as session:
            for _ in range(180):
                if process.returncode is not None:
                    raise RuntimeError(f"ComfyUI exited with code {process.returncode}. See the UI log.")
                try:
                    async with session.get(upstream + "/system_stats") as response:
                        if response.status == 200:
                            break
                except (OSError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(1)
            else:
                raise RuntimeError("ComfyUI startup timed out. See the UI log.")
        runner = web.AppRunner(proxy_app(upstream, login), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, args.host, args.port).start()
        print(f"Login user: {login['username']}\nLogin password: {login['password']}", flush=True)
        pod_id = os.environ.get("RUNPOD_POD_ID")
        address = (f"https://{pod_id}-{args.port}.proxy.runpod.net"
                   if pod_id else f"http://127.0.0.1:{args.port}")
        print(f"Open: {address}", flush=True)
        print("Workflows -> moss_marian_queen2 -> Run", flush=True)
        print(f"Images: {comfy / 'output' / 'MOSS'}", flush=True)
        code = await process.wait()
        if code:
            raise RuntimeError(f"ComfyUI exited with code {code}.")
    finally:
        if runner:
            await runner.cleanup()
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--cpu", action="store_true", help="Local startup verification only")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

