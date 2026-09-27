#!/bin/sh
# Модель реального времени VDAC2+ с режимом: $1 кадров, $2 первый, $3 последний, $4 имя, $5 режимы (например skip99).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON:-C:/Users/andre/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe}"
export PYTHONUTF8=1
cd "$ROOT"
COPY="$ROOT/Build/RT_$4"
rm -rf "$COPY"
cp -r "$ROOT/Build/V30Z80" "$COPY"
RT_MACHINE="$COPY" "$PY" Source/Tools/vdac2p_realtime.py "$1" "$2" "$3" "$5" 400 > "$ROOT/Build/realtime_$4.log" 2>&1
tail -n 1 "$ROOT/Build/realtime_$4.log"
