#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
KIT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export MOSS_HOME="${MOSS_HOME:-/workspace/moss-image-runtime}"
export HF_HOME="$MOSS_HOME/hf-cache"
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUTF8=1
mkdir -p "$MOSS_HOME/logs"
exec 9>"$MOSS_HOME/runtime.lock"
flock -n 9 || { echo 'MOSS-Image is already starting or running in this MOSS_HOME.' >&2; exit 1; }
bash "$KIT/setup.sh"
exec "$MOSS_HOME/comfy-venv/bin/python" -u "$KIT/launch_comfy.py" --runtime "$MOSS_HOME" "$@" > >(tee -a "$MOSS_HOME/logs/comfy-ui.log") 2>&1
