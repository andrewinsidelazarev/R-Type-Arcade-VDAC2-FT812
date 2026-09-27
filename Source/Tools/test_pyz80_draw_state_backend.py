#!/usr/bin/env python3
"""Persistent draw-state sidecar and compact-VM differential proofs."""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pyz80_compiler.draw_c_backend import (
    LiteralDrawRecord,
    NormalizedObjectView,
    NormalizedTransientView,
    interpret_draw_plan,
)
from pyz80_compiler.draw_plan import compile_active_enemy_draw_plan
from pyz80_compiler.draw_state_backend import (
    DRAW_STATE_BACKEND_FORMAT,
    DrawStateBackendError,
    build_draw_state_model,
    emit_draw_state_backend,
)
from pyz80_compiler.draw_vm_backend import emit_draw_vm_backend
from pyz80_compiler.render_order_backend import emit_render_order_backend


ROOT = Path(__file__).resolve().parents[2]
HOST_CC = next((item for item in (
    Path(os.environ["PYZ80_HOST_CC"])
    if os.environ.get("PYZ80_HOST_CC") else None,
    Path(shutil.which("tcc")) if shutil.which("tcc") else None,
    ROOT.parent / "tcc-0.9.27" / "tcc" / "tcc.exe",
) if item is not None and item.is_file()), None)


def _resource_type(palette: int) -> int:
    return (palette * 7 + 0x20) & 0xFF


def _bank_key(palette: int, resource_type: int) -> int:
    return ((palette & 0xFF) << 8) | (resource_type & 0xFF)


class DrawStateBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = compile_active_enemy_draw_plan(ROOT)
        cls.model = build_draw_state_model(ROOT, plan=cls.plan)
        cls.artifacts = emit_draw_state_backend(ROOT, plan=cls.plan)
        cls.vm_artifacts = emit_draw_vm_backend(cls.plan)
        cls.order_artifacts = emit_render_order_backend(ROOT)

    def test_inventory_is_source_derived_and_explicitly_live_blocked(self) -> None:
        model = self.model
        self.assertEqual(
            [item.name for item in model.fields],
            ["active_palette", "body_kind", "descriptor", "effect",
             "overlay_descriptor", "overlay_x", "overlay_y", "palette",
             "render_ready", "state", "visible", "x", "y"])
        self.assertEqual(model.slot_count, 96)
        self.assertEqual(model.object_root_class, "Enemy")
        self.assertEqual(model.value_bytes, 24)
        self.assertEqual(model.slot_state_bytes, 26)
        self.assertEqual(model.state_bytes, 2496)
        self.assertEqual(len(model.concrete_classes), 73)
        self.assertEqual(len(model.mutation_sites), 368)
        self.assertEqual(len(model.derived_field_sites), 17)
        self.assertEqual(
            {item.field_name for item in model.derived_field_sites},
            {"active_palette"})
        self.assertEqual(len(model.dynamic_write_sites), 5)
        self.assertEqual(len(model.identity_sites), 14)
        self.assertEqual(
            {item.kind for item in model.identity_sites},
            {"pool-bind", "pool-release", "pool-bind-assignment",
             "pool-release-assignment", "checkpoint-bind-assignment",
             "same-slot-object-replacement",
             "same-slot-old-owner-detach"})
        self.assertEqual(
            len({item.hash32 for item in model.mutation_sites}),
            len(model.mutation_sites))

        manifest = json.loads(self.artifacts.manifest)
        self.assertEqual(manifest["format"], DRAW_STATE_BACKEND_FORMAT)
        self.assertFalse(manifest["live"])
        self.assertFalse(
            manifest["mutation_inventory"]["coverage"]
                    ["reachable_write_sync_certified"])
        self.assertFalse(
            manifest["concrete_classes"]["manual_type_switch"])
        self.assertEqual(
            manifest["concrete_classes"]["object_root_class"], "Enemy")
        self.assertFalse(
            manifest["provider_abi"]["full_pool_copy_per_frame"])
        self.assertTrue(
            manifest["provider_abi"]
                    ["failure_leaves_object_out_unchanged"])
        self.assertGreaterEqual(
            len(manifest["verification_contract"]["live_blockers"]), 5)

    def test_artifacts_are_deterministic_and_plan_mismatch_fails_closed(self) -> None:
        again = emit_draw_state_backend(ROOT, plan=self.plan)
        self.assertEqual(again, self.artifacts)
        stale = replace(self.plan, semantic_sha256="0" * 64)
        with self.assertRaisesRegex(DrawStateBackendError, "PZDS006"):
            emit_draw_state_backend(ROOT, plan=stale)
        with self.assertRaisesRegex(DrawStateBackendError, "PZDS014"):
            emit_draw_state_backend(ROOT, prefix="bad-prefix")

    @staticmethod
    def _random_fixture(model: object) -> tuple[
            list[int], dict[int, tuple[object, NormalizedObjectView]],
            list[NormalizedTransientView]]:
        rng = random.Random(0x812D5A7E)
        slots = list(range(2, 2 + len(model.concrete_classes)))
        rows: dict[int, tuple[object, NormalizedObjectView]] = {}
        for slot, concrete in zip(slots, model.concrete_classes):
            fields: dict[str, int | bool | str] = {
                "active_palette": rng.randrange(0, 16),
                "body_kind": rng.choice(("other", "middle", "upper")),
                "descriptor": rng.randrange(0x100, 0xF000),
                "effect": rng.choice(("other", "e817")),
                "overlay_descriptor": rng.randrange(0x100, 0xF000),
                "overlay_x": rng.randrange(-2000, 2001),
                "overlay_y": rng.randrange(-2000, 2001),
                "palette": rng.randrange(0, 16),
                "render_ready": rng.random() > 0.08,
                "state": rng.choice(("other", "first")),
                "visible": rng.random() > 0.12,
                "x": rng.randrange(-3000, 3001),
                "y": rng.randrange(-3000, 3001),
            }
            tags = frozenset(concrete.membership_tags)
            # Exercise every class-specific branch rather than relying on
            # chance while all scalar values/order remain randomized.
            if tags:
                fields["palette"] = rng.randrange(0, 16)
                fields["render_ready"] = True
                fields["visible"] = True
            if "ExplosionEffect" in tags:
                fields["effect"] = "e817"
            if "Formation78F8Child" in tags:
                fields["state"] = "first"
            if "MultipartA71DBody" in tags:
                fields["body_kind"] = "upper"
            rows[slot] = (
                concrete,
                NormalizedObjectView(tags, fields),
            )
        rng.shuffle(slots)
        transients = [
            NormalizedTransientView(0x7100, 2, 0x56, -77, 88),
            NormalizedTransientView(0x7200, 3, 0x57, 99, -111),
        ]
        return slots, rows, transients

    def _values_initializer(self, item: NormalizedObjectView) -> str:
        lines = ["    {"]
        for field in self.model.fields:
            value = item.fields[field.name]
            if field.kind == "string_state":
                try:
                    encoded = field.string_values.index(str(value)) + 1
                except ValueError:
                    encoded = 0
            elif isinstance(value, bool):
                encoded = int(value)
            else:
                encoded = int(value)
            suffix = "u" if encoded >= 0 else ""
            lines.append(
                f"        .field_{field.name} = {encoded}{suffix},")
        lines.append("    }")
        return "\n".join(lines)

    @staticmethod
    def _record_initializer(item: LiteralDrawRecord) -> str:
        return "    { %du, %du, %d, %d }" % (
            item.bank_key, item.descriptor, item.anchor_x, item.anchor_y)

    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_host_randomized_persistent_order_vm_oracle_and_atomic_failures(
            self) -> None:
        assert HOST_CC is not None
        slots, rows, transients = self._random_fixture(self.model)
        objects = [rows[slot][1] for slot in slots]
        expected = interpret_draw_plan(
            self.plan, objects=objects, transients=transients,
            resource_type_resolver=_resource_type,
            bank_key_resolver=_bank_key)
        values_rows = ",\n".join(
            self._values_initializer(rows[slot][1])
            for slot in sorted(rows))
        class_rows = ", ".join(
            f"{rows[slot][0].class_id}u" for slot in sorted(rows))
        slot_rows = ", ".join(f"{slot}u" for slot in sorted(rows))
        order_rows = ", ".join(f"{slot}u" for slot in slots)
        transient_rows = ",\n".join(
            "    { %du, %du, %du, %d, %d }" % (
                item.descriptor, item.palette, item.resource_type,
                item.x, item.y)
            for item in transients)
        expected_rows = ",\n".join(
            self._record_initializer(item) for item in expected)
        first_site = self.model.mutation_sites[0]
        x_site = next(
            item for item in self.model.mutation_sites
            if item.field_name == "x" and item.kind != "class-field-initializer")
        replacement = rows[slots[0]][0]
        prefix = "rtype_python_draw_state"
        macro = "RTYPE_PYTHON_DRAW_STATE"
        vm = "rtype_python_draw_vm"
        vmacro = "RTYPE_PYTHON_DRAW_VM"
        order = "rtype_python_render_order"
        omacro = "RTYPE_PYTHON_RENDER_ORDER"
        harness = f'''#include <stdint.h>
#include <string.h>
#include "{self.artifacts.header_name}"

static const {prefix}_values values[] = {{
{values_rows}
}};
static const uint8_t classes[] = {{ {class_rows} }};
static const uint8_t physical_slots[] = {{ {slot_rows} }};
static const uint8_t python_order[] = {{ {order_rows} }};
static const {vm}_transient_view transients[] = {{
{transient_rows}
}};
static const {vm}_record expected[] = {{
{expected_rows}
}};
static uint16_t resolver_calls;
static uint16_t bank_calls;

static uint16_t resolve_resource(void *context, uint16_t palette)
{{
    (void)context;
    ++resolver_calls;
    return (uint16_t)((palette * 7u + 0x20u) & 0xFFu);
}}

static uint16_t resolve_bank(void *context, uint16_t palette, uint16_t type)
{{
    (void)context;
    ++bank_calls;
    return (uint16_t)(((palette & 0xFFu) << 8) | (type & 0xFFu));
}}

static uint8_t same_record(const {vm}_record *a, const {vm}_record *b)
{{
    return (uint8_t)(a->bank_key == b->bank_key &&
        a->descriptor == b->descriptor && a->anchor_x == b->anchor_x &&
        a->anchor_y == b->anchor_y);
}}

int main(void)
{{
    {prefix}_state state;
    {prefix}_state before;
    {prefix}_provider_context provider;
    {order}_state render_order;
    {vm}_input input;
    {vm}_record output[512];
    {vm}_record untouched[512];
    {vm}_object_view view;
    {vm}_object_view view_before;
    uint16_t output_count = 0xBEEFu;
    uint16_t index;
    uint8_t old_position;
    {prefix}_status side_status;
    {vm}_status vm_status;

    {prefix}_reset(&state);
    {order}_reset(&render_order);
    for (index = 0u; index < (uint16_t)(sizeof(values) / sizeof(values[0]));
            ++index) {{
        side_status = {prefix}_bind(&state, physical_slots[index],
            classes[index], &values[index]);
        if (side_status != {macro}_OK) return 10;
    }}
    if ({order}_seed(&render_order, python_order,
            (uint8_t)(sizeof(python_order) / sizeof(python_order[0]))) !=
            {omacro}_OK) return 11;
    provider.state = &state;
    provider.order = &render_order;
    input.objects = 0;
    input.object_count = render_order.count;
    input.load_object = {prefix}_load_object;
    input.object_context = &provider;
    input.transients = transients;
    input.transient_count =
        (uint16_t)(sizeof(transients) / sizeof(transients[0]));
    input.resolve_resource_type = resolve_resource;
    input.resource_context = 0;
    input.resolve_bank_key = resolve_bank;
    input.bank_context = 0;
    resolver_calls = bank_calls = 0u;
    vm_status = {vm}_produce(&input, output, 512u, &output_count);
    if (vm_status != {vmacro}_OK || output_count !=
            (uint16_t)(sizeof(expected) / sizeof(expected[0]))) return 12;
    for (index = 0u; index < output_count; ++index)
        if (!same_record(&output[index], &expected[index])) return 13;

    /* Loader refusal never changes its one working view. */
    memset(&view, 0xA5, sizeof(view));
    view_before = view;
    if ({prefix}_load_object(&provider, render_order.count, &view) != 0u ||
            memcmp(&view, &view_before, sizeof(view)) != 0) return 20;

    /* Every rejected sidecar operation is state-atomic. */
    before = state;
    if ({prefix}_bind(&state, 0u, classes[0], &values[0]) !=
            {macro}_INVALID_SLOT || memcmp(&state, &before, sizeof(state)) != 0)
        return 21;
    if ({prefix}_bind(&state, physical_slots[0], classes[0], &values[0]) !=
            {macro}_ALREADY_BOUND || memcmp(&state, &before, sizeof(state)) != 0)
        return 22;
    if ({prefix}_replace_same_slot(&state, 95u, classes[0], &values[0]) !=
            {macro}_UNBOUND_SLOT || memcmp(&state, &before, sizeof(state)) != 0)
        return 23;
    if ({prefix}_set_field(&state, physical_slots[0],
            {macro}_FIELD_VISIBLE, 2L) != {macro}_VALUE_RANGE ||
            memcmp(&state, &before, sizeof(state)) != 0) return 24;
    if ({prefix}_set_at_site(&state, physical_slots[0],
            {macro}_MUTATION_SITE_COUNT, 0L) != {macro}_INVALID_SITE ||
            memcmp(&state, &before, sizeof(state)) != 0) return 25;
    if ({prefix}_patch(&state, physical_slots[0], 0x8000u, &values[0]) !=
            {macro}_INVALID_PATCH_MASK ||
            memcmp(&state, &before, sizeof(state)) != 0) return 26;

    if ({prefix}_mutation_site_hash32({first_site.ordinal}u) !=
            0x{first_site.hash32:08X}UL) return 27;
    if ({prefix}_set_at_site(&state, physical_slots[0], {x_site.ordinal}u,
            1234L) != {macro}_OK ||
            state.slots[physical_slots[0]].values.field_x != 1234) return 28;

    /* Same-slot replacement changes state identity, never list position. */
    old_position = {order}_position_of(&render_order, physical_slots[0]);
    if ({prefix}_replace_same_slot(&state, physical_slots[0],
            {replacement.class_id}u, &values[0]) != {macro}_OK ||
            {order}_position_of(&render_order, physical_slots[0]) != old_position)
        return 29;

    /* An unbound referenced slot is found in VM preflight: no output/calls. */
    if ({prefix}_clear(&state, python_order[5]) != {macro}_OK) return 30;
    memset(output, 0x5A, sizeof(output));
    memset(untouched, 0x5A, sizeof(untouched));
    resolver_calls = bank_calls = 0u;
    output_count = 0xCAFEu;
    vm_status = {vm}_produce(&input, output, 512u, &output_count);
    if (vm_status != {vmacro}_OBJECT_LOADER || output_count != 0xCAFEu ||
            resolver_calls != 0u || bank_calls != 0u ||
            memcmp(output, untouched, sizeof(output)) != 0) return 31;

    if (sizeof({prefix}_values) != {macro}_VALUE_BYTES ||
            sizeof({prefix}_slot_state) != {macro}_SLOT_STATE_BYTES ||
            sizeof({prefix}_state) != {macro}_STATE_BYTES) return 32;
    return 0;
}}
'''
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-state-host-") as temp:
            directory = Path(temp)
            for artifacts in (
                    self.artifacts, self.vm_artifacts, self.order_artifacts):
                (directory / artifacts.header_name).write_text(
                    artifacts.header, encoding="utf-8", newline="\n")
                (directory / artifacts.source_name).write_text(
                    artifacts.source, encoding="utf-8", newline="\n")
            harness_name = "draw_state_host_check.c"
            (directory / harness_name).write_text(
                harness, encoding="utf-8", newline="\n")
            executable = directory / "draw_state_host_check.exe"
            command = [
                str(HOST_CC), "-std=c11",
                self.order_artifacts.source_name,
                self.vm_artifacts.source_name,
                self.artifacts.source_name,
                harness_name, "-o", executable.name,
            ]
            compiled = subprocess.run(
                command, cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(executable)], cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(executed.returncode, 0, executed.stdout)


if __name__ == "__main__":
    unittest.main()
