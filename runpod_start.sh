#!/usr/bin/env bash
# Container startup: optional file browser plus generation, with no terminal session.
set -Eeuo pipefail
umask 077
KIT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p /workspace
if command -v jupyter >/dev/null && ! python3 -c 'import socket; s=socket.create_connection(("127.0.0.1",8888),timeout=1); s.close()' 2>/dev/null; then
    if [[ -n "${MOSS_PASSWORD:-}" ]]; then
        export JUPYTER_TOKEN="$MOSS_PASSWORD"
    fi
    nohup jupyter lab --ip=0.0.0.0 --port=8888 --ServerApp.port_retries=0 \
        --ServerApp.allow_remote_access=True --ServerApp.root_dir=/workspace \
        --no-browser --allow-root > /workspace/jupyter-lab.log 2>&1 < /dev/null &
fi
# Keep PID 1 separate so --stop can stop generation while leaving the Pod available
# for a later LoRA training job. Never restart an intentionally stopped server.
bash "$KIT/start.sh" &
generation_pid=$!
trap 'kill -TERM "$generation_pid" 2>/dev/null || true; exit 0' TERM INT
wait "$generation_pid" || true
echo 'Generation process ended. Pod remains available for training or restart.'
sleep infinity &
wait $!
