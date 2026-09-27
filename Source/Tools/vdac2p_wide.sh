#!/bin/sh
# Широкая сверка VDAC2+ на копии сборки (можно пересобирать во время прогона): вся память V30, вызовы платформы и
# звук против эталона каждый кадр. $1 — число кадров (по умолчанию 70000: все восемь этапов сценария автоогня),
# $2 — имя прогона (каталог Build/Wide_<имя>), остальное — ключи rtype_check (например --random 31 без автоогня).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON:-C:/Users/andre/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe}"
DEPS="E:/zx/R-Type VDAC2/Build/PythonDeps"
export PYTHONPATH="$DEPS;$ROOT/Source/Tools;$ROOT/Source/Python"
export PYTHONUTF8=1
cd "$ROOT"
FRAMES="${1:-70000}"
NAME="${2:-all}"
[ $# -gt 0 ] && shift
[ $# -gt 0 ] && shift
COPY="$ROOT/Build/Wide_$NAME"
rm -rf "$COPY"
cp -r "$ROOT/Build/V30Z80" "$COPY"
if [ $# -eq 0 ]; then
  set -- --invincible --autofire 400 --keys "330:331:space"
fi
"$PY" Source/Tools/rtype_check.py --frames "$FRAMES" --build "$COPY" --sd "$COPY/rtype_sd.img" --render "" "$@"
echo "ШИРОКАЯ СВЕРКА ЗАВЕРШЕНА"
