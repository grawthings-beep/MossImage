#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
KIT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export MOSS_HOME="${MOSS_HOME:-/workspace/moss-image-runtime}"
export HF_HOME="$MOSS_HOME/hf-cache"
export PIP_CACHE_DIR="$MOSS_HOME/pip-cache"
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUTF8=1
mkdir -p "$MOSS_HOME/logs"
exec > >(tee -a "$MOSS_HOME/logs/comfy-setup.log") 2>&1
trap 'printf "Setup failed at line %s. See %s/logs/comfy-setup.log\n" "$LINENO" "$MOSS_HOME" >&2' ERR
command -v git >/dev/null
command -v python3 >/dev/null
python3 "$KIT/check_runtime.py" --constraints "$MOSS_HOME/comfy-cuda-constraints.txt"

COMFY="$MOSS_HOME/ComfyUI"
REV="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["comfy_revision"])' "$KIT/comfy-revisions.json")"
URL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["comfy_url"])' "$KIT/comfy-revisions.json")"
if [[ ! -d "$COMFY/.git" ]]; then
    git clone --no-checkout --filter=blob:none "$URL" "$COMFY"
fi
if [[ -f "$COMFY/main.py" ]] && [[ -n "$(git -C "$COMFY" status --porcelain --untracked-files=no)" ]]; then
    echo 'ComfyUI has local edits. Keep them and use a fresh MOSS_HOME.' >&2
    exit 1
fi
git -C "$COMFY" cat-file -e "$REV^{commit}" 2>/dev/null || git -C "$COMFY" fetch origin "$REV"
git -C "$COMFY" checkout --detach "$REV"
if [[ ! -x "$MOSS_HOME/comfy-venv/bin/python" ]]; then
    python3 -m venv --system-site-packages "$MOSS_HOME/comfy-venv"
fi
PY="$MOSS_HOME/comfy-venv/bin/python"
"$PY" -m pip install --constraint "$MOSS_HOME/comfy-cuda-constraints.txt" -r "$COMFY/requirements.txt" -r "$KIT/comfy-requirements.txt"
"$PY" "$KIT/check_runtime.py"
"$PY" "$KIT/check_comfy.py" --comfy "$COMFY"
"$PY" "$KIT/prepare_comfy.py" --runtime "$MOSS_HOME"
"$PY" -m pip freeze > "$MOSS_HOME/comfy-installed-packages.txt"
echo 'Setup finished. start.sh will launch the ComfyUI login page.'
