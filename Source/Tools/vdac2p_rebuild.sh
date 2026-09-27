#!/bin/sh
# Пересборка VDAC2+: оболочка p2c → машина (нативные процедуры + подстраховка переводом) → заставка → SPG и код игры
# RTYPECOD.PAC → образ SD.
# Python-зависимости берутся из папки VDAC2 только на чтение (см. CLAUDE.md).
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON:-C:/Users/andre/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe}"
DEPS="E:/zx/R-Type VDAC2/Build/PythonDeps"
export PYTHONPATH="$DEPS;$ROOT/Source/Tools;$ROOT/Source/Python"
export PYTHONUTF8=1
cd "$ROOT"
echo "== оболочка =="
"$PY" Source/Tools/p2c_runtime_z80.py
echo "== машина =="
"$PY" Source/Tools/v30z80_build.py
echo "== заставка =="
"$PY" Source/Tools/vdac2p_splash.py
echo "== SPG =="
"$PY" Source/Tools/rtype_spg.py --skip-parts
cp "Build/V30Z80/rtype_vdac2.spg" "Build/_SD/R-Type VDAC2/rtype_vdac2.spg"
cp "Build/V30Z80/RTYPECOD.PAC" "Build/_SD/R-Type VDAC2/RTYPECOD.PAC"
cp "Build/V30Z80/RTYPELVL.PAC" "Build/_SD/R-Type VDAC2/RTYPELVL.PAC"
echo "== образ SD =="
"$PY" Source/Tools/rtype_sd_image.py
