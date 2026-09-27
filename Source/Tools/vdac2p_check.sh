#!/bin/sh
# Покадровая сверка VDAC2+: вся память V30 и буфер спрайтов против эталона (ROM на Unicorn) каждый кадр,
# вызовы платформы и звук — тоже; вывод — хеши display list, RAM_G вне кольца фона и видимой части кольца
# (--ring-visible: кольцо пишется с отложенными столбцами) против опорных (Baselines, записаны тем же ключом).
# $1 — число кадров (по умолчанию 11400: этапы 1 и 2 сценария автоогня), $2 — опорные хеши вывода
# («-» — не сверять вывод), остальное — ключи rtype_check.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON:-C:/Users/andre/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe}"
DEPS="E:/zx/R-Type VDAC2/Build/PythonDeps"
export PYTHONPATH="$DEPS;$ROOT/Source/Tools;$ROOT/Source/Python"
export PYTHONUTF8=1
cd "$ROOT"
FRAMES="${1:-11400}"
BASE="${2:-$ROOT/Baselines/vdac2p_ringvis_11400.json}"
[ $# -gt 0 ] && shift
[ $# -gt 0 ] && shift
if [ "$BASE" = "-" ]; then
  "$PY" Source/Tools/rtype_check.py --frames "$FRAMES" --invincible --autofire 400 --keys "330:331:space" \
    --render "" --ticks "$ROOT/Build/ticks.json" "$@"
else
  "$PY" Source/Tools/rtype_check.py --frames "$FRAMES" --invincible --autofire 400 --keys "330:331:space" \
    --render "" --ring-visible --dl-compare "$BASE" --ticks "$ROOT/Build/ticks.json" "$@"
fi
"$PY" Source/Tools/vdac2p_speed.py "$ROOT/Build/ticks.json"
