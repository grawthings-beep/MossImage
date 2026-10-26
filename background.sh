#!/usr/bin/env bash
# Start independently of the terminal (including iPhone Safari web terminals).
set -Eeuo pipefail
umask 077
KIT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export MOSS_HOME="${MOSS_HOME:-/workspace/moss-image-runtime}"
if [[ "${1:-}" == '--restart' ]]; then
  shift
  exec python3 "$KIT/restart.py" "$@"
fi
mkdir -p "$MOSS_HOME/logs"
if ! flock -n "$MOSS_HOME/runtime.lock" true; then
  echo 'MOSS is already starting or running. Use the existing HTTP Service 7860.'
  exit 0
fi
LOG="$MOSS_HOME/logs/background.log"
nohup bash "$KIT/start.sh" "$@" </dev/null >>"$LOG" 2>&1 &
echo "Started in background (PID $!). Setup and model downloads may take several minutes."
echo "Log: tail -n 80 -f '$LOG'"
echo 'After the log shows Manga Studio, open HTTP Service 7860 and append /studio/ to its URL.'
echo 'HF_TOKEN must already be set, or the Marian LoRA must already be installed.'
