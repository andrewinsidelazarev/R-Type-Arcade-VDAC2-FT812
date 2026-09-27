"""Сборка машины с автоматической заменой JR вне диапазона на JP в vdac2p_native.asm (по сообщениям sjasmplus
«[JR] Target out of range»), пока ошибки такого рода есть. Запускает vdac2p_rebuild.sh."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8")
NATIVE = ROOT / 'Source' / 'ASM' / 'vdac2p_native.asm'
for attempt in range(6):
    result = subprocess.run(['sh', str(ROOT / 'Source' / 'Tools' / 'vdac2p_rebuild.sh')], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', cwd=ROOT)
    output = result.stdout + result.stderr
    (ROOT / 'Build' / 'rebuild.log').write_text(output, encoding='utf-8')
    lines = sorted({int(m[1]) for m in re.finditer(r'vdac2p_native\.asm\((\d+)\): error: \[JR\] Target out of range', output)})
    if not lines:
        errors = [line for line in output.splitlines() if 'error' in line.lower()]
        print('\n'.join(errors[:10]) if errors else 'сборка: ' + next((l for l in output.splitlines() if l.startswith('сборка:')), '?'))
        sys.exit(1 if errors else 0)
    text = NATIVE.read_text(encoding='utf-8').split('\n')
    for number in lines:
        text[number - 1] = re.sub(r'\bjr\b', 'jp', text[number - 1], count=1)
    NATIVE.write_text('\n'.join(text), encoding='utf-8', newline='\n')
    print(f'JR → JP: строки {lines}')
