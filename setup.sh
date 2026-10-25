#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
KIT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export MOSS_HOME="${MOSS_HOME:-/workspace/moss-image-runtime}"
export HF_HOME="$MOSS_HOME/hf-cache"
export PIP_CACHE_DIR="$MOSS_HOME/pip-cache"
export GRADIO_TEMP_DIR="$MOSS_HOME/gradio-temp"
export GRADIO_ANALYTICS_ENABLED=False
export TOKENIZERS_PARALLELISM=false
export PYTHONUTF8=1
mkdir -p "$MOSS_HOME/logs"
exec > >(tee -a "$MOSS_HOME/logs/setup.log") 2>&1
trap 'printf "Setup failed at line %s. See %s/logs/setup.log\n" "$LINENO" "$MOSS_HOME" >&2' ERR
command -v git >/dev/null
command -v python3 >/dev/null
python3 "$KIT/check_runtime.py" --constraints "$MOSS_HOME/cuda-constraints.txt"
if [[ ! -x "$MOSS_HOME/.venv/bin/python" ]]; then
    python3 -m venv --system-site-packages "$MOSS_HOME/.venv"
fi
PY="$MOSS_HOME/.venv/bin/python"
"$PY" -m pip install --constraint "$MOSS_HOME/cuda-constraints.txt" -r "$KIT/requirements.txt"
"$PY" "$KIT/check_runtime.py" --imports
UPSTREAM_URL="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream_url"])' "$KIT/revisions.json")"
UPSTREAM_REV="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream_revision"])' "$KIT/revisions.json")"
if [[ ! -d "$MOSS_HOME/upstream/.git" ]]; then
    git clone --no-checkout --filter=blob:none "$UPSTREAM_URL" "$MOSS_HOME/upstream"
fi
if [[ -n "$(git -C "$MOSS_HOME/upstream" status --porcelain --untracked-files=no)" ]] && git -C "$MOSS_HOME/upstream" rev-parse --verify HEAD >/dev/null 2>&1; then
    # A --no-checkout clone reports deleted files before its first checkout.
    if [[ -e "$MOSS_HOME/upstream/gradio_app.py" ]]; then
        echo 'Upstream has local edits. Keep them and use a fresh MOSS_HOME.' >&2
        exit 1
    fi
fi
git -C "$MOSS_HOME/upstream" cat-file -e "$UPSTREAM_REV^{commit}" 2>/dev/null || git -C "$MOSS_HOME/upstream" fetch origin "$UPSTREAM_REV"
git -C "$MOSS_HOME/upstream" checkout --detach "$UPSTREAM_REV"
"$PY" "$KIT/launch.py" --runtime "$MOSS_HOME" --check-ui
"$PY" "$KIT/download_model.py" --runtime "$MOSS_HOME"
"$PY" -m pip freeze > "$MOSS_HOME/installed-packages.txt"
echo 'Setup finished. Starting the UI is handled by start.sh.'
