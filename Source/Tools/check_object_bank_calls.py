#!/usr/bin/env python3
"""Запретить межбанковые CALL/JP в переключаемое окно TS-Config.

Во время выполнения ``object_bank1…4`` CPU slot2 (``#8000…#BFFF``) содержит
сам bank, а не вторую страницу Core. Поэтому внешний адрес в этом диапазоне
указывает на случайные байты текущего bank. Проверка запускается после
sjasmplus, когда известны окончательные адреса символов, и ловит сдвиг
раскладки до упаковки SPG.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SYM_PATH = ROOT / "Build" / "rtype.sym"
BANK_NAMES = ("collision_bank.asm", "fixed_player_bank.asm")
SYMBOL_RE = re.compile(r"^([^:]+): EQU 0x([0-9A-Fa-f]+)$")
LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
BRANCH_RE = re.compile(
    r"\b(?:CALL|JP)\s+(?:[A-Z]{1,2},\s*)?([A-Za-z_][A-Za-z0-9_]*)"
)


def load_symbols(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = SYMBOL_RE.match(line)
        if match:
            symbols[match.group(1)] = int(match.group(2), 16)
    return symbols


def main() -> int:
    symbols = load_symbols(SYM_PATH)
    errors: list[str] = []
    asm_dir = ROOT / "Source" / "ASM"
    banks = sorted(asm_dir.glob("object_bank*.asm"))
    banks.extend(asm_dir / name for name in BANK_NAMES)
    for bank in banks:
        lines = bank.read_text(encoding="utf-8").splitlines()
        local = {
            match.group(1)
            for line in lines
            if (match := LABEL_RE.match(line)) is not None
        }
        targets = {
            match.group(1)
            for line in lines
            if (match := BRANCH_RE.search(line)) is not None
        }
        for target in sorted(targets):
            address = symbols.get(target)
            if address is None or target in local or address < 0x8000:
                continue
            errors.append(
                f"{bank.name}: {target} = #{address:04X} попадает в slot2 bank"
            )
    if errors:
        print("OBJECT BANK CALL AUDIT FAILED", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        f"switchable-bank audit OK: {len(banks)} banks, "
        "all external CALL/JP targets below #8000"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
