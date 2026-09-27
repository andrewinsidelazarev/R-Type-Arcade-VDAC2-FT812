#!/usr/bin/env python3
"""Отрисовка кадра порта в PNG без эмулятора.

Прогоняет сборку в Z80+FT812-симуляторе (модель TS-Config из соседнего HMM2),
забирает список команд, отправленных копроцессору, и выполняет их поверх
изображения 1024×768: очистка, точки, прямоугольники, ARGB4444/RGB565 и
PALETTED4444 из RAM_G, включая расширенные BITMAP_LAYOUT_H/SIZE_H,
матрицу A/C/E/F и кольцевой режим REPEAT.

Это не замена железу и не замена bt8xxemu — но отвечает на вопрос «пустой ли
кадр» ДО запуска эмулятора. Результат: Build/frame_sim.png
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

SCREEN_W, SCREEN_H = 1024, 768
OUT_PNG = ROOT / "Build" / "frame_sim.png"

BEGIN_BITMAPS = 1
BEGIN_POINTS = 2
BEGIN_RECTS = 9


class DLRenderer:
    """Минимальный интерпретатор списка отображения под примитивы порта."""

    def __init__(self, ram_g: bytes) -> None:
        self.img = Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0))
        self.px = self.img.load()
        self.ram_g = ram_g
        self.color = (255, 255, 255)
        self.clear_color = (0, 0, 0)
        self.point_size = 16
        self.primitive = None
        self.vertices: list[tuple[int, int]] = []
        self.bmp_source = 0
        self.bmp_format = 6
        self.bmp_stride = 0
        self.bmp_height = 0
        self.bmp_w = 0
        self.bmp_h = 0
        self.layout_h_stride = 0
        self.layout_h_height = 0
        self.size_h_width = 0
        self.size_h_height = 0
        self.transform_a = 256
        self.transform_c = 0
        self.transform_e = 256
        self.transform_f = 0
        self.wrap_x = False
        self.wrap_y = False
        self.palette_source = 0
        self.vertex_format = 4
        self.scissor_x = 0
        self.scissor_y = 0
        self.scissor_w = SCREEN_W
        self.scissor_h = SCREEN_H
        self.counts = {"points": 0, "rects": 0, "bitmaps": 0}

    def run(self, data: bytes) -> None:
        for i in range(0, len(data), 4):
            self.command(int.from_bytes(data[i:i + 4], "little"))

    def command(self, word: int) -> None:
        if word & 0xFFFFFF00 == 0xFFFFFF00:      # команды копроцессора
            return
        op = word >> 24
        if op & 0xC0 == 0x40:                     # VERTEX2F
            x = (word >> 15) & 0x7FFF
            y = word & 0x7FFF
            if x & 0x4000:
                x -= 0x8000
            if y & 0x4000:
                y -= 0x8000
            self.vertex(x, y)
        elif op == 0x02:
            self.clear_color = ((word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF)
        elif op == 0x26:
            if word & 0x04:
                self.px = self.img.load()
                self.img.paste(self.clear_color, (0, 0, SCREEN_W, SCREEN_H))
                self.px = self.img.load()
        elif op == 0x04:
            self.color = ((word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF)
        elif op == 0x0D:
            self.point_size = word & 0x1FFF
        elif op == 0x01:
            self.bmp_source = word & 0x3FFFFF
        elif op == 0x28:
            self.layout_h_stride = (word >> 2) & 0x03
            self.layout_h_height = word & 0x03
        elif op == 0x07:
            self.bmp_format = (word >> 19) & 0x1F
            self.bmp_stride = ((word >> 9) & 0x3FF) | (self.layout_h_stride << 10)
            self.bmp_height = (word & 0x1FF) | (self.layout_h_height << 9)
        elif op == 0x29:
            self.size_h_width = (word >> 2) & 0x03
            self.size_h_height = word & 0x03
        elif op == 0x08:
            self.bmp_w = ((word >> 9) & 0x1FF) | (self.size_h_width << 9)
            self.bmp_h = (word & 0x1FF) | (self.size_h_height << 9)
            self.wrap_x = bool(word & (1 << 19))
            self.wrap_y = bool(word & (1 << 18))
        elif op == 0x15:
            # A/E — знаковые 17-битные 8.8 коэффициенты. Отрицательные
            # значения используются ROM-descriptor renderer для flip X/Y.
            self.transform_a = self.signed(word & 0x1FFFF, 17)
        elif op == 0x17:
            self.transform_c = self.signed(word & 0xFFFFFF, 24)
        elif op == 0x19:
            self.transform_e = self.signed(word & 0x1FFFF, 17)
        elif op == 0x1A:
            self.transform_f = self.signed(word & 0xFFFFFF, 24)
        elif op == 0x2A:
            self.palette_source = word & 0x3FFFFF
        elif op == 0x1B:
            self.scissor_x = (word >> 11) & 0x03FF
            self.scissor_y = word & 0x03FF
        elif op == 0x1C:
            self.scissor_w = (word >> 12) & 0x07FF
            self.scissor_h = word & 0x07FF
        elif op == 0x27:
            self.vertex_format = word & 0x07
        elif op == 0x1F:
            self.primitive = word & 0x0F
            self.vertices.clear()
        elif op == 0x21:
            self.primitive = None
            self.vertices.clear()

    @staticmethod
    def signed(value: int, bits: int) -> int:
        sign = 1 << (bits - 1)
        return value - (1 << bits) if value & sign else value

    def vertex(self, x16: int, y16: int) -> None:
        if self.primitive == BEGIN_POINTS:
            self.draw_point(x16, y16)
        elif self.primitive == BEGIN_RECTS:
            self.vertices.append((x16, y16))
            if len(self.vertices) == 2:
                self.draw_rect(*self.vertices)
                self.vertices.clear()
        elif self.primitive == BEGIN_BITMAPS:
            self.draw_bitmap(x16, y16)

    def draw_point(self, x16: int, y16: int) -> None:
        units = 1 << self.vertex_format
        cx, cy = x16 / units, y16 / units
        r = max(0.5, self.point_size / 32.0)
        for y in range(int(cy - r), int(cy + r) + 1):
            for x in range(int(cx - r), int(cx + r) + 1):
                if self.inside_scissor(x, y):
                    if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + 0.25:
                        self.px[x, y] = self.color
        self.counts["points"] += 1

    def draw_rect(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        units = 1 << self.vertex_format
        x0, y0 = int(a[0] / units), int(a[1] / units)
        x1, y1 = int(b[0] / units), int(b[1] / units)
        clip_x1 = min(SCREEN_W, self.scissor_x + self.scissor_w)
        clip_y1 = min(SCREEN_H, self.scissor_y + self.scissor_h)
        x0, x1 = sorted((max(self.scissor_x, x0), min(clip_x1, x1)))
        y0, y1 = sorted((max(self.scissor_y, y0), min(clip_y1, y1)))
        self.img.paste(self.color, (x0, y0, x1, y1))
        self.px = self.img.load()
        self.counts["rects"] += 1

    def draw_bitmap(self, x16: int, y16: int) -> None:
        units = 1 << self.vertex_format
        ox, oy = int(x16 / units), int(y16 / units)
        step_x = self.transform_a / 256.0
        step_y = self.transform_e / 256.0
        bytes_per_pixel = 1 if self.bmp_format == 15 else 2
        src_w = self.bmp_stride // bytes_per_pixel
        origin_x = self.transform_c / 256.0
        origin_y = self.transform_f / 256.0
        for dy in range(self.bmp_h):
            sy = int(dy * step_y + origin_y)
            if self.wrap_y:
                sy %= self.bmp_height
            elif not 0 <= sy < self.bmp_height:
                continue
            for dx in range(self.bmp_w):
                sx = int(dx * step_x + origin_x)
                if self.wrap_x:
                    sx %= src_w
                elif not 0 <= sx < src_w:
                    continue
                if self.bmp_format == 15:        # FT_PALETTED4444, index8
                    index = self.ram_g[
                        self.bmp_source + sy * self.bmp_stride + sx]
                    palette = self.palette_source + index * 2
                    value = (self.ram_g[palette] |
                             (self.ram_g[palette + 1] << 8))
                    alpha = (value >> 12) & 0xF
                    if not alpha:
                        continue
                    r = ((value >> 8) & 0xF) * 17
                    g = ((value >> 4) & 0xF) * 17
                    b = (value & 0xF) * 17
                elif self.bmp_format == 7:       # FT_RGB565
                    off = self.bmp_source + sy * self.bmp_stride + sx * 2
                    value = self.ram_g[off] | (self.ram_g[off + 1] << 8)
                    alpha = 15
                    r = ((value >> 11) & 0x1F) * 255 // 31
                    g = ((value >> 5) & 0x3F) * 255 // 63
                    b = (value & 0x1F) * 255 // 31
                elif self.bmp_format == 6:       # FT_ARGB4
                    off = self.bmp_source + sy * self.bmp_stride + sx * 2
                    value = self.ram_g[off] | (self.ram_g[off + 1] << 8)
                    alpha = (value >> 12) & 0xF
                    if not alpha:
                        continue
                    r = ((value >> 8) & 0xF) * 17
                    g = ((value >> 4) & 0xF) * 17
                    b = (value & 0xF) * 17
                else:
                    raise RuntimeError(f"неподдержанный bitmap format {self.bmp_format}")
                x, y = ox + dx, oy + dy
                if self.inside_scissor(x, y):
                    if alpha == 15:
                        self.px[x, y] = (r, g, b)
                    else:
                        base = self.px[x, y]
                        k = alpha / 15.0
                        self.px[x, y] = (
                            int(base[0] * (1 - k) + r * k),
                            int(base[1] * (1 - k) + g * k),
                            int(base[2] * (1 - k) + b * k),
                        )
        self.counts["bitmaps"] += 1

    def inside_scissor(self, x: int, y: int) -> bool:
        return (
            0 <= x < SCREEN_W and 0 <= y < SCREEN_H and
            self.scissor_x <= x < self.scissor_x + self.scissor_w and
            self.scissor_y <= y < self.scissor_y + self.scissor_h
        )


def main() -> int:
    frames = 1
    input_mask = 0
    out_png = OUT_PNG
    snapshot_frames: set[int] = set()
    direct_game = False
    skip_intro = False
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--frames" and i + 1 < len(args):
            frames = int(args[i + 1])
        elif arg == "--input" and i + 1 < len(args):
            input_mask = int(args[i + 1], 0)
        elif arg == "--out" and i + 1 < len(args):
            out_png = Path(args[i + 1])
        elif arg == "--snapshots" and i + 1 < len(args):
            snapshot_frames = {int(value) for value in args[i + 1].split(",")}
            frames = max(frames, max(snapshot_frames))
        elif arg == "--direct-game":
            direct_game = True
        elif arg == "--skip-intro":
            skip_intro = True

    # The display-list reference renderer above is project-local and can be
    # imported by compiler tests without requiring the optional neighbouring
    # Z80 simulator.  Resolve that backend only for an explicit CLI run.
    simulator_tools = (
        ROOT.parent / "HMM2" / "Pre-releases" /
        "v020-2026-07-16-adventure-ui-battle-ai-reference" /
        "Source" / "Tools"
    )
    if not (simulator_tools / "tsconf_ft812_sim.py").is_file():
        raise RuntimeError(
            "TS-Config simulator backend not found at "
            f"{simulator_tools}; DLRenderer itself remains available")
    sys.path.insert(0, str(simulator_tools))
    simulator = importlib.import_module("tsconf_ft812_sim")
    sym = simulator.parse_sym(ROOT / "Build" / "rtype.sym")
    machine = simulator.TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )

    if direct_game:
        machine.run_until_pc(sym["MainLoop"], max_steps=50_000_000)
        machine.call(sym["Application_StartGame"], max_steps=80_000_000)
        if skip_intro:
            machine.set_word(sym["ArcadeIntroFrame"], 226)

    # Ввод подменяется прямо в резидентной переменной: клавиатуру и мышь
    # симулятор не эмулирует, а логике нужен только собранный InputState.
    input_state = 0x4202
    for frame_number in range(1, frames + 1):
        if direct_game:
            machine.call(sym["RTypeSpriteCache_BeginFrame"],
                         max_steps=2_000_000)
            machine.set_byte(input_state, input_mask)
            machine.call(sym["Application_Update"], max_steps=40_000_000)
            machine.call(sym["Render_Frame"], max_steps=40_000_000)
        else:
            # Останавливаться на верхнем dispatcher, а не угадывать сцену по
            # GameMode: значение 2 является attract-demo и имеет собственную
            # обработку Any Key/табличного ввода перед ArcadeGame_Update.
            machine.run_until_pc(sym["Application_Update"], max_steps=40_000_000)
            machine.set_byte(input_state, input_mask)
            # Возврат к MainLoop означает, что FT_CMD_Write уже передал текущий
            # display list в модель FT812; прежняя внутренняя метка waitSwap была
            # до отправки и давала предыдущий кадр.
            machine.run_until_pc(sym["MainLoop"], max_steps=40_000_000)
        if frame_number in snapshot_frames:
            snapshot_data = latest_display_list(machine)
            snapshot_renderer = DLRenderer(bytes(machine.ft.ram_g))
            snapshot_renderer.run(snapshot_data)
            snapshot_path = out_png.with_name(
                f"{out_png.stem}_{frame_number:03d}{out_png.suffix}")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_renderer.img.save(snapshot_path)
            print(f"контрольный кадр {frame_number}: {snapshot_path}")

    data = latest_display_list(machine)
    renderer = DLRenderer(bytes(machine.ft.ram_g))
    renderer.run(data)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    renderer.img.save(out_png)

    pixels = renderer.img.load()
    non_black = sum(1 for y in range(0, SCREEN_H, 4) for x in range(0, SCREEN_W, 4)
                    if pixels[x, y] != (0, 0, 0))
    total = (SCREEN_W // 4) * (SCREEN_H // 4)
    # ArcadePlayerX/Y are logical Q16.8; integer word starts at +1.
    px = machine.get_word(0x4204)
    py = machine.get_word(0x4207)
    force_detached = machine.get_byte(0x420F)
    wave_charge = machine.get_byte(0x4211)
    wave_pending = machine.get_byte(0x4213)
    print(f"кадров: {frames}, игрок: X={px} Y={py} logical px")
    print(f"Force detached={force_detached}, Wave charge={wave_charge}, "
          f"shot pending={wave_pending}")
    print(f"команд в кадре: {len(data) // 4}")
    print(f"нарисовано: точек {renderer.counts['points']}, "
          f"прямоугольников {renderer.counts['rects']}, "
          f"битмапов {renderer.counts['bitmaps']}")
    print(f"не чёрных пикселей: {non_black} из {total} проб "
          f"({100 * non_black / total:.1f}%)")
    print(f"кадр: {out_png}")
    return 0


def latest_display_list(machine) -> bytes:
    data = bytes(machine.ft.ram_cmd[: machine.ft.cmd_write_ptr])
    last_start = 0
    for i in range(0, len(data) - 3, 4):
        if int.from_bytes(data[i:i + 4], "little") == 0xFFFFFF00:
            last_start = i
    return data[last_start:]


if __name__ == "__main__":
    raise SystemExit(main())
