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
# File locking prevents a second setup/launch on the same runtime directory.
exec 9>"$MOSS_HOME/runtime.lock"
flock -n 9 || { echo 'MOSS-Image is already starting or running in this MOSS_HOME.' >&2; exit 1; }
bash "$KIT/setup.sh"
exec "$MOSS_HOME/.venv/bin/python" -u "$KIT/launch.py" --runtime "$MOSS_HOME" "$@" > >(tee -a "$MOSS_HOME/logs/ui.log") 2>&1
