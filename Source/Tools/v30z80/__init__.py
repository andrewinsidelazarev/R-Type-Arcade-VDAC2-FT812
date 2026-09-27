"""Трансляция машинного кода World ROM R-Type (NEC V30, x86-16) в Z80 для TS-Config.

Эталон поведения — машина M72 полного runtime (`rtype_m72.machine`, unicorn) с патчем
баланса `rtype_port.full_runtime`. Модули:
  snapshot — состояние машины после загрузки ROM (память 1 МБ, регистры, PIC, видео);
  decode   — разбор инструкций V30 в операции транслятора;
  discover — поиск всего исполнимого кода и графа переходов;
  flags    — живость флагов;
  codegen  — ассемблер Z80 (sjasmplus) по операциям.
"""

import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[3]
for _extra in (_ROOT / 'Build' / 'PythonDeps', _ROOT / 'Source' / 'Tools', _ROOT / 'Source' / 'Python'):
    if str(_extra) not in _sys.path:
        _sys.path.insert(0, str(_extra))
