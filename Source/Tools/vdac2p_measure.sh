#!/bin/sh
# Замер скорости VDAC2+ в модели реального времени (пропуск вывода, как на железе) по двум отрезкам: этап 1 (кадры
# 1200…3000) и этап 2 (9600…11400), параллельно. $1 — имя (Build/realtime_<имя>_s1.log, _s2.log). $2 = profile —
# ещё и профили Build/rtprof_<имя>_s1.json, _s2.json (для vdac2p_top.py). Прогон с профилем даёт другие шаги/с, чем
# без него (модель чувствительна к нарезке cpu.run): скорость сравнивать только прогонами без профиля.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="${1:-now}"
cd "$ROOT"
if [ "$2" = "profile" ]; then
  RT_PROFILE="$ROOT/Build/rtprof_${NAME}_s1.json" sh Source/Tools/vdac2p_realtime.sh 3000 1200 3000 "${NAME}_s1" &
  RT_PROFILE="$ROOT/Build/rtprof_${NAME}_s2.json" sh Source/Tools/vdac2p_realtime.sh 11400 9600 11400 "${NAME}_s2" &
else
  sh Source/Tools/vdac2p_realtime.sh 3000 1200 3000 "${NAME}_s1" &
  sh Source/Tools/vdac2p_realtime.sh 11400 9600 11400 "${NAME}_s2" &
fi
wait
echo "этап 1: $(tail -n 1 "$ROOT/Build/realtime_${NAME}_s1.log")"
echo "этап 2: $(tail -n 1 "$ROOT/Build/realtime_${NAME}_s2.log")"
