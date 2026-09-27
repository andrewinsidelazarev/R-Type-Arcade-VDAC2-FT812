#!/usr/bin/env python3
"""Compact C VM proofs for the active-Python sprite draw plan."""

from __future__ import annotations

import json
import os
import re
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
    emit_draw_c_backend,
    interpret_draw_plan,
)
from pyz80_compiler.draw_plan import compile_active_enemy_draw_plan
from pyz80_compiler.draw_vm_backend import (
    VM_BACKEND_FORMAT,
    DrawVMBackendError,
    build_draw_vm_program,
    emit_draw_vm_backend,
)
from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc


ROOT = Path(__file__).resolve().parents[2]
COMPILER_MANIFEST = CompilerManifest.load(
    ROOT / "Source" / "Tools" / "rtype_python_compiler.json")
try:
    SDCC: Path | None = locate_sdcc(COMPILER_MANIFEST.target)
except Exception:
    SDCC = None
HOST_CC = next((item for item in (
    Path(os.environ["PYZ80_HOST_CC"])
    if os.environ.get("PYZ80_HOST_CC") else None,
    Path(shutil.which("tcc")) if shutil.which("tcc") else None,
    ROOT.parent / "tcc-0.9.27" / "tcc" / "tcc.exe",
) if item is not None and item.is_file()), None)


def _object(
        *classes: str, **changes: int | bool | str,
        ) -> NormalizedObjectView:
    fields: dict[str, int | bool | str] = {
        "active_palette": 9,
        "body_kind": "other",
        "descriptor": 0x4100,
        "effect": "other",
        "overlay_descriptor": 0x6200,
        "overlay_x": -123,
        "overlay_y": 234,
        "palette": 5,
        "render_ready": True,
        "state": "other",
        "visible": True,
        "x": 111,
        "y": -222,
    }
    fields.update(changes)
    return NormalizedObjectView(frozenset(classes), fields)


def _resource_type(palette: int) -> int:
    return (palette * 7 + 0x20) & 0xFF


def _bank_key(palette: int, resource_type: int) -> int:
    return ((palette & 0xFF) << 8) | (resource_type & 0xFF)


class DrawVMBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = compile_active_enemy_draw_plan(ROOT)
        cls.program = build_draw_vm_program(cls.plan)
        cls.artifacts = emit_draw_vm_backend(cls.plan)

    def _all_action_fixture(self) -> tuple[
            list[NormalizedObjectView], list[NormalizedTransientView]]:
        return ([
            _object("PlayerTargeting80E3", descriptor=0x1000, x=1, y=-1),
            _object("Targeting80E3Projectile", descriptor=0x1100, x=2, y=-2),
            _object("ExplosionEffect", descriptor=0x1200, effect="e817"),
            _object("Handler5CEAShot", descriptor=0x1300),
            _object("Enemy8561", descriptor=0x1400),
            _object("Enemy6F89", descriptor=0x1500),
            _object("Enemy5EED", descriptor=0x1600),
            _object("Handler60BA", descriptor=0x1700),
            _object("Formation78F8Child", descriptor=0x1800, state="first"),
            _object("Enemy7D68", descriptor=0x1900),
            _object("MultipartA71DBody", descriptor=0x1A00,
                    body_kind="upper"),
            _object("MultipartA71DBody", descriptor=0x1B00,
                    body_kind="middle"),
            _object("MultipartA71DBody", descriptor=0x1C00,
                    body_kind="lower"),
            _object("BossB7FBSegment", descriptor=0x1D00),
            _object("FixedLarge6E9B", descriptor=0x1E00),
            _object("Handler60BAChild", descriptor=0x1F00,
                    overlay_descriptor=0x6ABC, overlay_x=-300,
                    overlay_y=301),
            _object("Targeting80E3AttackFlash", descriptor=0x2000,
                    visible=False),
            _object(descriptor=0x2100, palette=0xFF),
        ], [
            NormalizedTransientView(0x7000, 2, 0x56, -17, 18),
            NormalizedTransientView(0x7006, 3, 0x57, 19, -20),
        ])

    def _records(
            self, objects: list[NormalizedObjectView],
            transients: list[NormalizedTransientView],
            trace: list[int] | None = None,
            ) -> tuple[LiteralDrawRecord, ...]:
        return interpret_draw_plan(
            self.plan, objects=objects, transients=transients,
            resource_type_resolver=_resource_type,
            bank_key_resolver=_bank_key, action_trace=trace)

    def _object_initializer(self, item: NormalizedObjectView) -> str:
        model = self.program.model
        class_index = {
            name: index for index, name in enumerate(model.class_tags)
        }
        bits = [0] * model.class_bit_bytes
        for name in item.classes:
            index = class_index[name]
            bits[index >> 3] |= 1 << (index & 7)
        lines = ["    {", "        .class_bits = {" + ", ".join(
            f"0x{value:02X}u" for value in bits) + "},"]
        for field in model.fields:
            value = item.fields[field.name]
            if field.kind == "string_state":
                try:
                    encoded = str(field.string_values.index(str(value)) + 1) + "u"
                except ValueError:
                    encoded = "0u"
            elif isinstance(value, bool):
                encoded = "1u" if value else "0u"
            else:
                encoded = str(int(value))
            lines.append(f"        .field_{field.name} = {encoded},")
        lines.append("    }")
        return "\n".join(lines)

    def _harness(
            self, objects: list[NormalizedObjectView],
            transients: list[NormalizedTransientView],
            expected: tuple[LiteralDrawRecord, ...],
            ) -> str:
        object_rows = ",\n".join(
            self._object_initializer(item) for item in objects)
        transient_rows = ",\n".join(
            "    { %du, %du, %du, %d, %d }" % (
                item.descriptor, item.palette, item.resource_type,
                item.x, item.y)
            for item in transients)
        expected_rows = ",\n".join(
            "    { %du, %du, %d, %d }" % (
                item.bank_key, item.descriptor, item.anchor_x, item.anchor_y)
            for item in expected)
        expected_resource_calls = len(expected) - len(transients)
        prefix, macro = "rtype_python_draw_vm", "RTYPE_PYTHON_DRAW_VM"
        return f'''#include <stdint.h>
#include <string.h>
#include "{self.artifacts.header_name}"

static uint32_t resource_calls;
static uint32_t bank_calls;
static uint16_t stream_accepted;
static uint16_t stream_fail_after;

static uint16_t resolve_resource(void *context, uint16_t palette)
{{
    (void)context;
    ++resource_calls;
    return (uint16_t)((palette * 7u + 0x20u) & 0xFFu);
}}

static uint16_t resolve_bank(void *context, uint16_t palette, uint16_t type)
{{
    (void)context;
    ++bank_calls;
    return (uint16_t)(((palette & 0xFFu) << 8) | (type & 0xFFu));
}}

static const {prefix}_object_view objects[] = {{
{object_rows}
}};
static const {prefix}_transient_view transients[] = {{
{transient_rows}
}};
static const {prefix}_record expected[] = {{
{expected_rows}
}};
static {prefix}_record streamed[128];

static uint8_t emit_stream(void *context, const {prefix}_record *record)
{{
    (void)context;
    if (stream_accepted == stream_fail_after) return 0u;
    streamed[stream_accepted++] = *record;
    return 1u;
}}

static int same_record(const {prefix}_record *a, const {prefix}_record *b)
{{
    return a->bank_key == b->bank_key &&
           a->descriptor == b->descriptor &&
           a->anchor_x == b->anchor_x && a->anchor_y == b->anchor_y;
}}

int main(void)
{{
    {prefix}_record output[128];
    {prefix}_input input;
    uint16_t count = 0xBEEFu;
    uint16_t index;
    {prefix}_status status;
    memset(output, 0xA5, sizeof(output));
    input.objects = objects;
    input.object_count = (uint16_t)(sizeof(objects) / sizeof(objects[0]));
    input.load_object = 0;
    input.object_context = 0;
    input.transients = transients;
    input.transient_count = (uint16_t)(sizeof(transients) / sizeof(transients[0]));
    input.resolve_resource_type = resolve_resource;
    input.resource_context = 0;
    input.resolve_bank_key = resolve_bank;
    input.bank_context = 0;

    resource_calls = 0u;
    bank_calls = 0u;
    status = {prefix}_produce(&input, output, 128u, &count);
    if (status != {macro}_OK || count !=
            (uint16_t)(sizeof(expected) / sizeof(expected[0]))) return 10;
    if (resource_calls != {expected_resource_calls}u || bank_calls != count)
        return 11;
    for (index = 0; index < count; ++index) {{
        if (!same_record(&output[index], &expected[index])) return 20 + index;
    }}

    memset(streamed, 0x5A, sizeof(streamed));
    stream_accepted = 0u;
    stream_fail_after = 0xFFFFu;
    resource_calls = 0u;
    bank_calls = 0u;
    count = 0xBEEFu;
    status = {prefix}_stream(&input, emit_stream, 0, &count);
    if (status != {macro}_OK || count !=
            (uint16_t)(sizeof(expected) / sizeof(expected[0])) ||
            stream_accepted != count) return 60;
    if (resource_calls != {expected_resource_calls}u || bank_calls != count)
        return 61;
    for (index = 0; index < count; ++index) {{
        if (!same_record(&streamed[index], &expected[index])) return 62 + index;
    }}

    stream_accepted = 0u;
    stream_fail_after = 7u;
    count = 0xBEEFu;
    status = {prefix}_stream(&input, emit_stream, 0, &count);
    if (status != {macro}_EMITTER || count != 7u ||
            stream_accepted != 7u) return 75;

    resource_calls = 0u;
    bank_calls = 0u;
    count = 0xCAFEu;
    status = {prefix}_produce(&input, output,
        (uint16_t)((sizeof(expected) / sizeof(expected[0])) - 1u), &count);
    if (status != {macro}_CAPACITY || count != 0xCAFEu) return 80;
    if (resource_calls != 0u || bank_calls != 0u) return 81;
    for (index = 0; index < (uint16_t)(sizeof(expected) / sizeof(expected[0]));
            ++index) {{
        if (!same_record(&output[index], &expected[index])) return 82;
    }}
    return 0;
}}
'''

    def _provider_harness(
            self, objects: list[NormalizedObjectView],
            transients: list[NormalizedTransientView],
            expected: tuple[LiteralDrawRecord, ...],
            ) -> str:
        object_rows = ",\n".join(
            self._object_initializer(item) for item in objects)
        transient_rows = ",\n".join(
            "    { %du, %du, %du, %d, %d }" % (
                item.descriptor, item.palette, item.resource_type,
                item.x, item.y)
            for item in transients)
        expected_rows = ",\n".join(
            "    { %du, %du, %d, %d }" % (
                item.bank_key, item.descriptor, item.anchor_x, item.anchor_y)
            for item in expected)

        object_records = [
            self._records([item], []) for item in objects
        ]
        transient_records = self._records([], transients)
        self.assertEqual(
            tuple(record for rows in object_records for record in rows) +
            transient_records,
            expected,
        )
        # Event kinds: 1=loader, 2=resource resolver, 3=bank resolver,
        # 4=emitter.  Values make the order check sensitive to parameters too.
        events: list[tuple[int, int, int]] = [
            (1, index, 0) for index in range(len(objects))
        ]
        for index, records in enumerate(object_records):
            events.append((1, index, 0))
            for record in records:
                palette = record.bank_key >> 8
                resource_type = record.bank_key & 0xFF
                events.extend((
                    (2, palette, resource_type),
                    (3, palette, resource_type),
                    (4, record.bank_key, record.descriptor),
                ))
        for record in transient_records:
            events.extend((
                (3, record.bank_key >> 8, record.bank_key & 0xFF),
                (4, record.bank_key, record.descriptor),
            ))
        event_rows = ",\n".join(
            f"    {{ {kind}u, {left}u, {right}u }}"
            for kind, left, right in events)
        prefix, macro = "rtype_python_draw_vm", "RTYPE_PYTHON_DRAW_VM"
        object_count = len(objects)
        expected_resource_calls = len(expected) - len(transients)
        return f'''#include <stdint.h>
#include <string.h>
#include "{self.artifacts.header_name}"

typedef struct trace_event {{
    uint8_t kind;
    uint16_t left;
    uint16_t right;
}} trace_event;

static const {prefix}_object_view source_objects[] = {{
{object_rows}
}};
static const {prefix}_transient_view transients[] = {{
{transient_rows}
}};
static const {prefix}_record expected[] = {{
{expected_rows}
}};
static const trace_event expected_events[] = {{
{event_rows}
}};

static trace_event events[256];
static {prefix}_record streamed[128];
static uint16_t event_count;
static uint16_t loader_calls;
static uint16_t resource_calls;
static uint16_t bank_calls;
static uint16_t emitted;
static uint16_t loader_fail_index;

static void trace(uint8_t kind, uint16_t left, uint16_t right)
{{
    if (event_count < 256u) {{
        events[event_count].kind = kind;
        events[event_count].left = left;
        events[event_count].right = right;
    }}
    ++event_count;
}}

static uint8_t load_object(void *context, uint16_t index,
        {prefix}_object_view *object_out)
{{
    (void)context;
    trace(1u, index, 0u);
    ++loader_calls;
    if (index == loader_fail_index) return 0u;
    if (index >= {object_count}u || object_out == 0) return 0u;
    *object_out = source_objects[index];
    return 1u;
}}

static uint16_t resolve_resource(void *context, uint16_t palette)
{{
    uint16_t result;
    (void)context;
    result = (uint16_t)((palette * 7u + 0x20u) & 0xFFu);
    trace(2u, palette, result);
    ++resource_calls;
    return result;
}}

static uint16_t resolve_bank(void *context, uint16_t palette, uint16_t type)
{{
    (void)context;
    trace(3u, palette, type);
    ++bank_calls;
    return (uint16_t)(((palette & 0xFFu) << 8) | (type & 0xFFu));
}}

static uint8_t emit_record(void *context, const {prefix}_record *record)
{{
    (void)context;
    trace(4u, record->bank_key, record->descriptor);
    streamed[emitted++] = *record;
    return 1u;
}}

static int same_record(const {prefix}_record *a, const {prefix}_record *b)
{{
    return a->bank_key == b->bank_key &&
           a->descriptor == b->descriptor &&
           a->anchor_x == b->anchor_x && a->anchor_y == b->anchor_y;
}}

static void reset_trace(void)
{{
    event_count = 0u;
    loader_calls = 0u;
    resource_calls = 0u;
    bank_calls = 0u;
    emitted = 0u;
}}

int main(void)
{{
    {prefix}_input input;
    {prefix}_record untouched[128];
    uint16_t count = 0xBEEFu;
    uint16_t index;
    {prefix}_status status;
    input.objects = 0;
    input.object_count = {object_count}u;
    input.load_object = load_object;
    input.object_context = 0;
    input.transients = transients;
    input.transient_count =
        (uint16_t)(sizeof(transients) / sizeof(transients[0]));
    input.resolve_resource_type = resolve_resource;
    input.resource_context = 0;
    input.resolve_bank_key = resolve_bank;
    input.bank_context = 0;

    loader_fail_index = 0xFFFFu;
    reset_trace();
    status = {prefix}_stream(&input, emit_record, 0, &count);
    if (status != {macro}_OK || count !=
            (uint16_t)(sizeof(expected) / sizeof(expected[0])) ||
            emitted != count) return 10;
    if ({macro}_OBJECT_VIEW_BYTES != 28u) return 11;
    if (loader_calls != (uint16_t)(2u * input.object_count)) return 12;
    if (resource_calls != {expected_resource_calls}u || bank_calls != count)
        return 13;
    if (event_count !=
            (uint16_t)(sizeof(expected_events) / sizeof(expected_events[0])))
        return 14;
    for (index = 0u; index < count; ++index) {{
        if (!same_record(&streamed[index], &expected[index])) return 20;
    }}
    for (index = 0u; index < event_count; ++index) {{
        if (events[index].kind != expected_events[index].kind ||
                events[index].left != expected_events[index].left ||
                events[index].right != expected_events[index].right) return 21;
    }}

    /* A loader refusal is found in preflight, before resolver/emitter/output. */
    memset(streamed, 0xA5, sizeof(streamed));
    memset(untouched, 0xA5, sizeof(untouched));
    loader_fail_index = 5u;
    reset_trace();
    count = 0xCAFEu;
    status = {prefix}_stream(&input, emit_record, 0, &count);
    if (status != {macro}_OBJECT_LOADER || count != 0xCAFEu) return 30;
    if (loader_calls != 6u || resource_calls != 0u || bank_calls != 0u ||
            emitted != 0u || event_count != 6u) return 31;
    if (memcmp(streamed, untouched, sizeof(streamed)) != 0) return 32;

    /* The same preflight guarantee keeps produce's output buffer untouched. */
    reset_trace();
    count = 0xD00Du;
    status = {prefix}_produce(&input, streamed, 128u, &count);
    if (status != {macro}_OBJECT_LOADER || count != 0xD00Du) return 40;
    if (loader_calls != 6u || resource_calls != 0u || bank_calls != 0u ||
            emitted != 0u || event_count != 6u) return 41;
    if (memcmp(streamed, untouched, sizeof(streamed)) != 0) return 42;
    return 0;
}}
'''

    def test_exact_compact_inventory_is_derived_from_active_ir(self) -> None:
        program = self.program
        self.assertEqual(len(program.constants), 24)
        self.assertEqual(len(program.class_masks), 17)
        self.assertEqual(len(program.nodes), 79)
        self.assertEqual(len(program.condition_ids), 89)
        self.assertEqual(len(program.condition_packs), 18)
        self.assertEqual(len(program.actions), 34)
        self.assertEqual(len(program.loops), 2)
        self.assertEqual(program.table_payload_bytes, 815)
        self.assertEqual(program.max_eval_depth, 4)
        self.assertEqual(len(program.callback_node_ids), 1)
        self.assertEqual(
            [(item.kind, item.first_action, item.action_count)
             for item in program.loops],
            [("objects", 0, 33), ("transients", 33, 1)])

    def test_artifacts_are_deterministic_and_materially_smaller(self) -> None:
        again = emit_draw_vm_backend(self.plan)
        self.assertEqual(self.artifacts, again)
        manifest = json.loads(self.artifacts.manifest)
        self.assertEqual(manifest["format"], VM_BACKEND_FORMAT)
        self.assertEqual(manifest["plan"]["semantic_sha256"],
                         self.plan.semantic_sha256)
        self.assertEqual(manifest["vm"]["logical_table_bytes"]["total"],
                         self.program.table_payload_bytes)
        self.assertFalse(manifest["verification_contract"]
                         ["live_target_performance_and_size_certified"])
        self.assertTrue(manifest["normalized_abi"]["failure_atomicity"]
                        ["capacity_failure_atomic"])
        object_abi = manifest["normalized_abi"]["object_view"]
        self.assertEqual(object_abi["exact_target_size_bytes"], 28)
        self.assertEqual(object_abi["working_view_count"], 1)
        self.assertFalse(object_abi["full_pool_materialization_required"])
        self.assertEqual(
            object_abi["provider"]["successful_calls_per_produce_or_stream"],
            "2 * object_count")
        self.assertEqual(
            manifest["lowering"]["loop_order"][0]["action_ordinals"],
            list(range(33)))
        unrolled = emit_draw_c_backend(self.plan)
        self.assertLess(
            len(self.artifacts.source.encode("utf-8")),
            len(unrolled.source.encode("utf-8")) // 3)
        self.assertIn("static const rtype_python_draw_vm_node",
                      self.artifacts.source)
        self.assertNotIn("source sink", self.artifacts.source)

    def test_resolver_reachable_from_preflight_fails_closed(self) -> None:
        action = self.plan.actions[0]
        changed = replace(action, descriptor=action.resource_type)
        plan = replace(self.plan, actions=(changed, *self.plan.actions[1:]))
        with self.assertRaisesRegex(DrawVMBackendError, "PZDVM013"):
            build_draw_vm_program(plan)

    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_host_vm_matches_ir_oracle_and_executes_all_34_actions(self) -> None:
        assert HOST_CC is not None
        objects, transients = self._all_action_fixture()
        trace: list[int] = []
        expected = self._records(objects, transients, trace)
        self.assertEqual(set(trace), set(range(34)))
        self.assertEqual(len(expected), 50)
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-vm-host-") as temp:
            directory = Path(temp)
            (directory / self.artifacts.header_name).write_text(
                self.artifacts.header, encoding="utf-8", newline="\n")
            (directory / self.artifacts.source_name).write_text(
                self.artifacts.source, encoding="utf-8", newline="\n")
            harness = "draw_vm_host_check.c"
            (directory / harness).write_text(
                self._harness(objects, transients, expected),
                encoding="utf-8", newline="\n")
            executable = directory / "draw_vm_host_check.exe"
            compiled = subprocess.run(
                [str(HOST_CC), "-std=c11", self.artifacts.source_name,
                 harness, "-o", executable.name],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(executable)], cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stdout)

    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_single_view_provider_matches_oracle_and_is_fail_atomic(self) -> None:
        assert HOST_CC is not None
        objects, transients = self._all_action_fixture()
        expected = self._records(objects, transients)
        with tempfile.TemporaryDirectory(
                prefix="pyz80-draw-vm-provider-host-") as temp:
            directory = Path(temp)
            (directory / self.artifacts.header_name).write_text(
                self.artifacts.header, encoding="utf-8", newline="\n")
            (directory / self.artifacts.source_name).write_text(
                self.artifacts.source, encoding="utf-8", newline="\n")
            harness = "draw_vm_provider_host_check.c"
            (directory / harness).write_text(
                self._provider_harness(objects, transients, expected),
                encoding="utf-8", newline="\n")
            executable = directory / "draw_vm_provider_host_check.exe"
            compiled = subprocess.run(
                [str(HOST_CC), "-std=c11", self.artifacts.source_name,
                 harness, "-o", executable.name],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(executable)], cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stdout)

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC unavailable")
    def test_full_generated_vm_has_measured_sub_page_sdcc_code(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-vm-sdcc-") as temp:
            directory = Path(temp)
            (directory / self.artifacts.header_name).write_text(
                self.artifacts.header, encoding="utf-8", newline="\n")
            (directory / self.artifacts.source_name).write_text(
                self.artifacts.source, encoding="utf-8", newline="\n")
            environment = os.environ.copy()
            environment["PATH"] = (
                str(SDCC.parent) + os.pathsep + environment.get("PATH", ""))
            completed = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--fno-omit-frame-pointer", "--stack-auto",
                 "--opt-code-speed", "--no-c-code-in-asm",
                 "-c", self.artifacts.source_name],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=180,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            rel = directory / self.artifacts.source_name.replace(".c", ".rel")
            text = rel.read_text(encoding="latin1")
            areas = {
                match.group(1): int(match.group(2), 16)
                for match in re.finditer(
                    r"^A\s+(\S+)\s+size\s+([0-9A-Fa-f]+)\s+",
                    text, re.MULTILINE)
            }
            self.assertEqual(areas.get("_CODE"), 0x1195)
            self.assertEqual(areas.get("_DATA"), 0)
            self.assertLess(areas["_CODE"], 0x4000)
            # Locked baseline of the unrolled backend is 0x551C bytes.
            self.assertLess(areas["_CODE"], 0x551C // 4)


if __name__ == "__main__":
    unittest.main()
