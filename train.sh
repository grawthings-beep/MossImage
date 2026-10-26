#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
KIT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUTF8=1
exec python3 -u "$KIT/training/launch.py" "$@"
