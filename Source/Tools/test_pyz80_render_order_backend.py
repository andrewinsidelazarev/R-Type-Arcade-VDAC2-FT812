#!/usr/bin/env python3
"""Proofs for the source-derived compact Python render-order backend."""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pyz80_compiler.render_order_backend import (
    RENDER_ORDER_BACKEND_FORMAT,
    RenderOrderBackendError,
    build_render_order_model,
    emit_render_order_backend,
)


ROOT = Path(__file__).resolve().parents[2]
HOST_CC = next((item for item in (
    Path(os.environ["PYZ80_HOST_CC"])
    if os.environ.get("PYZ80_HOST_CC") else None,
    Path(shutil.which("tcc")) if shutil.which("tcc") else None,
    ROOT.parent / "tcc-0.9.27" / "tcc" / "tcc.exe",
) if item is not None and item.is_file()), None)


def _mask(slots: list[int], byte_count: int) -> list[int]:
    value = [0] * byte_count
    for slot in slots:
        value[slot >> 3] |= 1 << (slot & 7)
    return value


class RenderOrderBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = build_render_order_model(ROOT)
        cls.artifacts = emit_render_order_backend(ROOT)

    def test_active_pool_checkpoint_and_six_mutations_are_source_derived(
            self) -> None:
        model = self.model
        self.assertEqual(model.slot_count, 96)
        self.assertEqual(model.reserved_sentinel_count, 2)
        self.assertEqual(model.capacity, 94)
        self.assertEqual((model.slot_first, model.slot_stop_exclusive,
                          model.slot_stride), (0x0540, 0x1D40, 0x40))
        self.assertEqual(len(model.checkpoint_slot_indices), 27)
        self.assertEqual(model.checkpoint_slot_indices[0], 53)
        self.assertEqual(model.checkpoint_slot_indices[-1], 24)
        self.assertEqual(len(set(model.checkpoint_slot_indices)), 27)
        self.assertEqual(
            [kind for _line, kind, _source in model.enemy_mutations],
            [
                "initialize-empty",
                "checkpoint-seed",
                "append-after-bind",
                "extend-allocating-pending",
                "filtered-survivors",
                "extend-pending-slice",
            ])
        self.assertEqual(model.state_bytes, 191)

    def test_artifacts_are_deterministic_and_live_is_explicitly_blocked(
            self) -> None:
        self.assertEqual(self.artifacts, emit_render_order_backend(ROOT))
        manifest = json.loads(self.artifacts.manifest)
        self.assertEqual(manifest["format"], RENDER_ORDER_BACKEND_FORMAT)
        self.assertFalse(manifest["live"])
        self.assertEqual(manifest["semantic_sha256"],
                         self.model.semantic_sha256)
        self.assertEqual(
            manifest["audited_mutation_inventory"]["count"], 6)
        self.assertEqual(
            manifest["normalized_abi"]["state"]["target_bytes"], 191)
        self.assertEqual(
            manifest["normalized_abi"]["operations"]["slot_at"],
            "O(1) direct VM-loader lookup")
        self.assertFalse(
            manifest["normalized_abi"]["state"]
            ["full_object_copy_required"])
        self.assertFalse(
            manifest["verification_contract"]["live_target_hooks_present"])
        self.assertTrue(manifest["draw_order"]["direct_python_list_order"])
        self.assertIn(
            "return state->order[order_position];", self.artifacts.source)

    def test_unexpected_enemy_list_mutation_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        source = path.read_text(encoding="utf-8")
        needle = "            self.enemies.append(visual)"
        self.assertEqual(source.count(needle), 1)
        stale = source.replace(needle, needle + "\n" + needle, 1)
        with self.assertRaisesRegex(
                RenderOrderBackendError,
                r"PZRO001: .*PZFRB009: enemy-list mutation inventory changed"):
            build_render_order_model(ROOT, enemy_source_override=stale)

    def test_changed_draw_iteration_order_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        source = path.read_text(encoding="utf-8")
        needle = "        for enemy in self.enemies:\n"
        # There are other gameplay scans; mutate only the direct loop inside
        # M72EnemyWorld.draw, located after that method definition.
        draw_start = source.index("    def draw(self, target: pygame.Surface) -> None:")
        loop_at = source.index(needle, draw_start)
        stale = (source[:loop_at] +
                 "        for enemy in reversed(self.enemies):\n" +
                 source[loop_at + len(needle):])
        with self.assertRaisesRegex(RenderOrderBackendError, "PZRO010"):
            build_render_order_model(ROOT, enemy_source_override=stale)

    def test_invalid_prefix_fails_closed(self) -> None:
        with self.assertRaisesRegex(RenderOrderBackendError, "PZRO009"):
            emit_render_order_backend(ROOT, prefix="not-a-c-prefix")

    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_host_c_randomized_sequence_matches_python_list_oracle(self) -> None:
        assert HOST_CC is not None
        model = self.model
        prefix = "rtype_python_render_order"
        macro = prefix.upper()
        rng = random.Random(0x8120A6)
        oracle = list(model.checkpoint_slot_indices)
        operations: list[str] = []
        snapshots: list[tuple[int, ...]] = [tuple(oracle)]

        for _ in range(420):
            free = [slot for slot in range(
                model.reserved_sentinel_count, model.slot_count)
                    if slot not in oracle]
            if not oracle:
                choice = "append"
            elif len(oracle) > 80:
                choice = "filter"
            else:
                choice = rng.choices(
                    ["append", "extend", "remove", "filter", "replace"],
                    weights=[24, 20, 18, 20, 18], k=1)[0]
            if choice == "append" and free:
                slot = rng.choice(free)
                oracle.append(slot)
                operation = f"{prefix}_append(&state, {slot}u)"
            elif choice == "extend" and free:
                count = min(len(free), rng.randint(1, 4))
                values = rng.sample(free, count)
                oracle.extend(values)
                literal = ", ".join(f"{value}u" for value in values)
                operation = (
                    f"{prefix}_extend(&state, "
                    f"(const uint8_t[]){{ {literal} }}, {count}u)")
            elif choice == "remove" and oracle:
                slot = rng.choice(oracle)
                oracle.remove(slot)
                operation = f"{prefix}_remove(&state, {slot}u)"
            elif choice == "filter" and oracle:
                kept = [slot for slot in oracle if rng.random() < 0.67]
                mask = _mask(kept, model.keep_mask_bytes)
                oracle = kept
                literal = ", ".join(f"0x{value:02X}u" for value in mask)
                operation = (
                    f"{prefix}_filter(&state, "
                    f"(const uint8_t[]){{ {literal} }})")
            elif oracle:
                slot = rng.choice(oracle)
                operation = (
                    f"{prefix}_replace_same_slot(&state, {slot}u)")
            else:
                continue
            index = len(snapshots)
            operations.append(
                f"    status = {operation};\n"
                f"    if (status != {macro}_OK || !verify(&state, {index}u)) "
                f"return {20 + index % 200};")
            snapshots.append(tuple(oracle))

        offsets: list[int] = []
        flattened: list[int] = []
        for snapshot in snapshots:
            offsets.append(len(flattened))
            flattened.extend(snapshot)
        flat_text = ", ".join(f"{value}u" for value in flattened) or "0u"
        offset_text = ", ".join(f"{value}u" for value in offsets)
        count_text = ", ".join(f"{len(value)}u" for value in snapshots)
        operation_text = "\n".join(operations)
        checkpoint_free = next(
            slot for slot in range(model.reserved_sentinel_count,
                                   model.slot_count)
            if slot not in model.checkpoint_slot_indices)
        full_text = ", ".join(
            f"{slot}u" for slot in range(
                model.reserved_sentinel_count, model.slot_count))
        harness = f'''#include <stdint.h>
#include <string.h>
#include "{self.artifacts.header_name}"

static const uint8_t expected_flat[] = {{ {flat_text} }};
static const uint16_t expected_offset[] = {{ {offset_text} }};
static const uint8_t expected_count[] = {{ {count_text} }};

static uint8_t verify(const {prefix}_state *state, uint16_t snapshot)
{{
    uint8_t expected_position[{macro}_SLOT_COUNT];
    uint8_t index;
    uint8_t slot;
    uint16_t offset = expected_offset[snapshot];
    if (state->count != expected_count[snapshot]) return 0u;
    for (slot = 0u; slot < {macro}_SLOT_COUNT; ++slot)
        expected_position[slot] = {macro}_NONE;
    for (index = 0u; index < state->count; ++index) {{
        slot = expected_flat[offset + index];
        expected_position[slot] = index;
        if ({prefix}_slot_at(state, index) != slot) return 0u;
    }}
    if ({prefix}_slot_at(state, state->count) != {macro}_NONE) return 0u;
    for (slot = 0u; slot < {macro}_SLOT_COUNT; ++slot) {{
        if ({prefix}_position_of(state, slot) != expected_position[slot])
            return 0u;
        if ({prefix}_contains(state, slot) !=
                (uint8_t)(expected_position[slot] != {macro}_NONE)) return 0u;
    }}
    return 1u;
}}

int main(void)
{{
    {prefix}_state state;
    {prefix}_state before;
    {prefix}_status status;
    static const uint8_t duplicate[] = {{ {checkpoint_free}u, {checkpoint_free}u }};
    static const uint8_t full[] = {{ {full_text} }};
    uint8_t invalid_mask[{macro}_KEEP_MASK_BYTES] = {{ 0u }};
    uint8_t missing_mask[{macro}_KEEP_MASK_BYTES] = {{ 0u }};

    {prefix}_reset(&state);
    status = {prefix}_seed_checkpoint(&state);
    if (status != {macro}_OK || !verify(&state, 0u)) return 10;
{operation_text}

    /* Every rejected operation is atomic. */
    status = {prefix}_seed_checkpoint(&state);
    if (status != {macro}_OK) return 230;
    before = state;
    if ({prefix}_append(&state, 0u) != {macro}_INVALID_SLOT ||
            memcmp(&state, &before, sizeof(state)) != 0) return 231;
    if ({prefix}_append(&state, state.order[0]) != {macro}_DUPLICATE_SLOT ||
            memcmp(&state, &before, sizeof(state)) != 0) return 232;
    if ({prefix}_extend(&state, duplicate, 2u) != {macro}_DUPLICATE_SLOT ||
            memcmp(&state, &before, sizeof(state)) != 0) return 233;
    if ({prefix}_seed(&state, duplicate, 2u) != {macro}_DUPLICATE_SLOT ||
            memcmp(&state, &before, sizeof(state)) != 0) return 234;
    if ({prefix}_remove(&state, {checkpoint_free}u) != {macro}_NOT_MEMBER ||
            memcmp(&state, &before, sizeof(state)) != 0) return 235;
    if ({prefix}_replace_same_slot(&state, {checkpoint_free}u) !=
            {macro}_NOT_MEMBER || memcmp(&state, &before, sizeof(state)) != 0)
        return 236;
    invalid_mask[0] = 1u;
    if ({prefix}_filter(&state, invalid_mask) != {macro}_INVALID_SLOT ||
            memcmp(&state, &before, sizeof(state)) != 0) return 237;
    missing_mask[{checkpoint_free}u >> 3] =
        (uint8_t)(1u << ({checkpoint_free}u & 7u));
    if ({prefix}_filter(&state, missing_mask) != {macro}_NOT_MEMBER ||
            memcmp(&state, &before, sizeof(state)) != 0) return 238;
    status = {prefix}_seed(&state, full, {macro}_CAPACITY);
    if (status != {macro}_OK) return 239;
    before = state;
    if ({prefix}_append(&state, 2u) != {macro}_CAPACITY_EXCEEDED ||
            memcmp(&state, &before, sizeof(state)) != 0) return 240;
    if (sizeof(state) != {macro}_STATE_BYTES) return 241;
    return 0;
}}
'''
        with tempfile.TemporaryDirectory(prefix="pyz80-render-order-host-") as temp:
            directory = Path(temp)
            (directory / self.artifacts.header_name).write_text(
                self.artifacts.header, encoding="utf-8", newline="\n")
            (directory / self.artifacts.source_name).write_text(
                self.artifacts.source, encoding="utf-8", newline="\n")
            harness_name = "render_order_host_check.c"
            (directory / harness_name).write_text(
                harness, encoding="utf-8", newline="\n")
            executable = directory / "render_order_host_check.exe"
            compiled = subprocess.run(
                [str(HOST_CC), "-std=c11", self.artifacts.source_name,
                 harness_name, "-o", executable.name],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(executable)], cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stdout)


if __name__ == "__main__":
    unittest.main()
