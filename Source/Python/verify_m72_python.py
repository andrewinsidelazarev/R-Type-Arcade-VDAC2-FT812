"""Сопоставить живые состояния Python-V30 с покадровым эталоном MAME."""
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

from rtype_m72.machine import RTypeM72Machine


ROOT = Path(__file__).resolve().parents[2]


def state_hash(parts: list[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def normalized_palette(data: bytes) -> bytes:
    """Оставить подключённые D0-D4 и отбросить зеркальные окна A9."""
    words = struct.unpack("<1536H", data)
    selected = words[0x000:0x100] + words[0x200:0x300] + words[0x400:0x500]
    return bytes(value & 0x1F for value in selected)


def compact(matches: list[tuple[int, list[int]]]) -> list[tuple[int, list[int]]]:
    return [(python_frame, mame_frames[:8]) for python_frame, mame_frames in matches[:8]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path,
                        default=ROOT / "Build" / "Arcade" / "MAME" / "title_all_native")
    parser.add_argument("--frames", type=int, default=1000)
    args = parser.parse_args()

    names = ("vram0", "vram1", "palette0", "palette1", "spriteram")
    references: dict[str, list[int]] = {}
    component_references: dict[str, dict[str, list[int]]] = {name: {} for name in names}
    for vram0 in sorted(args.capture.glob("frame_*_vram0.bin")):
        frame = int(vram0.name.split("_")[1])
        prefix = args.capture / f"frame_{frame:06d}"
        paths = [Path(f"{prefix}_{name}.bin") for name in names]
        if all(path.is_file() for path in paths):
            parts = [path.read_bytes() for path in paths]
            parts[2] = normalized_palette(parts[2])
            parts[3] = normalized_palette(parts[3])
            references.setdefault(
                state_hash(parts), []).append(frame)
            for name, part in zip(names, parts, strict=True):
                component_references[name].setdefault(state_hash([part]), []).append(frame)

    machine = RTypeM72Machine()
    machine.boot()
    matches: list[tuple[int, list[int]]] = []
    component_matches: dict[str, list[tuple[int, list[int]]]] = {name: [] for name in names}
    for python_frame in range(args.frames):
        frame = machine.step_frame()
        parts = [frame.vram0, frame.vram1, normalized_palette(frame.palette0),
                 normalized_palette(frame.palette1), frame.spriteram]
        digest = state_hash(parts)
        if digest in references:
            matches.append((python_frame, references[digest]))
        for name, part in zip(names, parts, strict=True):
            part_digest = state_hash([part])
            if part_digest in component_references[name]:
                component_matches[name].append(
                    (python_frame, component_references[name][part_digest]))
    print(f"Эталонных состояний: {len(references)}")
    print(f"Совпадений: {len(matches)}")
    print("Первые совпадения:", compact(matches))
    for name in names:
        print(f"{name}: {len(component_matches[name])}, "
              f"первые {compact(component_matches[name])}")
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
