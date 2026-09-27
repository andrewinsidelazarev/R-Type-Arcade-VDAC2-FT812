#!/usr/bin/env python3
"""Сгенерировать готовые FT812 vertex-координаты вместо арифметики Z80."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "Source" / "ASM" / "generated_ft812_coordinate_tables.inc"
X_FIRST = -512
X_COUNT = 1280
Y_FIRST = -256
Y_COUNT = 768


def x_vertex(value: int) -> int:
    """Повторить round(X*64/3) текущего ASM без Python banker's rounding."""
    magnitude = (abs(value) * 64 + 1) // 3
    return (-magnitude if value < 0 else magnitude) & 0xFFFF


def y_vertex(value: int) -> int:
    return (value * 24) & 0xFFFF


def emit_table(lines: list[str], label: str, values: list[int]) -> None:
    lines.append(f"{label}:")
    for start in range(0, len(values), 8):
        row = ", ".join(f"#{value:04X}" for value in values[start:start + 8])
        lines.append(f"                DEFW {row}")
    lines.append("")


def main() -> int:
    lines = [
        "; Сгенерировано m72_ft812_coordinate_tables.py; не редактировать.",
        "; Page #00, #1000…#1FFF: готовые VERTEX_FORMAT-3 координаты.",
        f"RTYPE_VERTEX_X_FIRST EQU {X_FIRST}",
        f"RTYPE_VERTEX_X_COUNT EQU {X_COUNT}",
        f"RTYPE_VERTEX_Y_FIRST EQU {Y_FIRST}",
        f"RTYPE_VERTEX_Y_COUNT EQU {Y_COUNT}",
        "",
    ]
    emit_table(lines, "RTypeVertexXTable", [
        x_vertex(value) for value in range(X_FIRST, X_FIRST + X_COUNT)
    ])
    emit_table(lines, "RTypeVertexYTable", [
        y_vertex(value) for value in range(Y_FIRST, Y_FIRST + Y_COUNT)
    ])
    OUTPUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
