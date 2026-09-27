#!/bin/sh
# Профиль VDAC2+ на копии сборки: $1 — первый кадр профиля, $2 — последний кадр, $3 — имя (Build/profile_<имя>.json,
# .log). Остальное — ключи rtype_check (например --object-profile).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON:-C:/Users/andre/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe}"
DEPS="E:/zx/R-Type VDAC2/Build/PythonDeps"
export PYTHONPATH="$DEPS;$ROOT/Source/Tools;$ROOT/Source/Python"
export PYTHONUTF8=1
cd "$ROOT"
FIRST="$1"; LAST="$2"; NAME="$3"
shift 3
COPY="$ROOT/Build/Prof_$NAME"
rm -rf "$COPY"
cp -r "$ROOT/Build/V30Z80" "$COPY"
"$PY" Source/Tools/rtype_check.py --frames "$LAST" --build "$COPY" --sd "$COPY/rtype_sd.img" --invincible \
  --autofire 400 --keys "330:331:space" --render "" --profile 101 --profile-from "$FIRST" \
  --ticks "$ROOT/Build/profile_$NAME.json" "$@"
