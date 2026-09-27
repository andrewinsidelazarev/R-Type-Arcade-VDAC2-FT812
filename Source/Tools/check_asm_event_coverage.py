#!/usr/bin/env python3
"""Проверка покрытия всех stage-event handlers целевым Z80 runtime."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = (
    ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" / "Terrain"
    / "all_stage_terrain.json"
)
OBJECT_ASM = ROOT / "Source" / "ASM" / "object_runtime.asm"
WORLD_ASM = ROOT / "Source" / "ASM" / "world_runtime.asm"


def routine_text(source: str, start: str, end: str | None) -> str:
    """Вернуть текст одной процедуры между двумя глобальными метками."""
    begin = source.index(start + ":")
    if end is None:
        return source[begin:]
    finish = source.index(end + ":", begin)
    return source[begin:finish]


def compared_words(source: str) -> set[int]:
    """Снять непосредственные words из цепочки сравнений диспетчера."""
    return {
        int(value, 16)
        for value in re.findall(r"\bLD\s+DE,\s*#([0-9A-Fa-f]{4})\b", source)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="показать пробелы, но не завершать проверку ошибкой",
    )
    args = parser.parse_args()

    document = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    events = [event for stage in document["stages"] for event in stage["events"]]
    counts = Counter(int(event["handler"]) for event in events)
    meanings = {
        int(event["handler"]): str(event["meaning"])
        for event in events
    }
    required = set(counts)

    object_source = OBJECT_ASM.read_text(encoding="utf-8")
    object_dispatch = routine_text(
        object_source,
        "RTypeObjects_DispatchEvent",
        "RTypeObjects_InitTimedControlF366",
    )
    object_handlers = compared_words(object_dispatch) & required

    world_source = WORLD_ASM.read_text(encoding="utf-8")
    world_dispatch = routine_text(world_source, "RTypeWorld_DispatchGlobal", None)
    world_handlers = compared_words(world_dispatch) & required

    covered = object_handlers | world_handlers
    missing = sorted(required - covered)
    duplicate = sorted(object_handlers & world_handlers)

    print(
        "ASM event coverage: "
        f"{len(covered)}/{len(required)} handlers, "
        f"{sum(counts[item] for item in covered)}/{len(events)} event records"
    )
    if duplicate:
        values = ", ".join(f"${item:04X}" for item in duplicate)
        print(f"совместно object/global: {values}")
    if missing:
        print("не покрыты:")
        for handler in missing:
            print(
                f"  ${handler:04X}: {counts[handler]:3d} событий — "
                f"{meanings[handler]}"
            )
        return 0 if args.allow_missing else 1

    print("все stage-event handlers имеют явный Z80 dispatch — OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
