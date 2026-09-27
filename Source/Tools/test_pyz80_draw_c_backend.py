#!/usr/bin/env python3
"""Portable C producer proofs for the active Python enemy draw IR."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pyz80_compiler.draw_c_backend import (
    BACKEND_FORMAT,
    DrawCBackendError,
    LiteralDrawRecord,
    NormalizedObjectView,
    NormalizedTransientView,
    ProducerStatus,
    build_draw_c_model,
    emit_draw_c_backend,
    interpret_draw_plan,
    produce_draw_records_oracle,
    validate_resolver_domains,
)
from pyz80_compiler.draw_plan import DrawExpr, compile_active_enemy_draw_plan
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


class DrawCBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = compile_active_enemy_draw_plan(ROOT)
        cls.model = build_draw_c_model(cls.plan)
        cls.artifacts = emit_draw_c_backend(cls.plan)

    def records(
            self, objects: list[NormalizedObjectView],
            transients: list[NormalizedTransientView] | None = None,
            action_trace: list[int] | None = None,
            ) -> tuple[LiteralDrawRecord, ...]:
        return interpret_draw_plan(
            self.plan, objects=objects, transients=transients or [],
            resource_type_resolver=_resource_type,
            bank_key_resolver=_bank_key, action_trace=action_trace)

    def _all_action_fixture(self) -> tuple[
            list[NormalizedObjectView], list[NormalizedTransientView]]:
        objects = [
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
        ]
        transients = [
            NormalizedTransientView(0x7000, 2, 0x56, -17, 18),
            NormalizedTransientView(0x7006, 3, 0x57, 19, -20),
        ]
        return objects, transients

    def _c_object_initializer(self, item: NormalizedObjectView) -> str:
        class_index = {name: index for index, name in enumerate(
            self.model.class_tags)}
        bits = [0] * self.model.class_bit_bytes
        for name in item.classes:
            index = class_index[name]
            bits[index >> 3] |= 1 << (index & 7)
        lines = ["    {", "        .class_bits = {" + ", ".join(
            f"0x{value:02X}u" for value in bits) + "},"]
        for field in self.model.fields:
            value = item.fields[field.name]
            if field.kind == "string_state":
                try:
                    tag = field.string_values.index(str(value)) + 1
                except ValueError:
                    tag = 0
                encoded = f"{tag}u"
            elif isinstance(value, bool):
                encoded = "1u" if value else "0u"
            else:
                encoded = str(int(value))
            lines.append(f"        .field_{field.name} = {encoded},")
        lines.append("    }")
        return "\n".join(lines)

    def _host_harness(
            self, objects: list[NormalizedObjectView],
            transients: list[NormalizedTransientView],
            expected: tuple[LiteralDrawRecord, ...],
            ) -> str:
        object_rows = ",\n".join(
            self._c_object_initializer(item) for item in objects)
        transient_rows = ",\n".join(
            "    { %du, %du, %du, %d, %d }" % (
                item.descriptor, item.palette, item.resource_type,
                item.x, item.y)
            for item in transients)
        expected_rows = ",\n".join(
            "    { %du, %du, %d, %d }" % (
                item.bank_key, item.descriptor, item.anchor_x, item.anchor_y)
            for item in expected)
        prefix = "rtype_python_draw_plan"
        macro = prefix.upper()
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
    {prefix}_object_view bad_object;
    uint16_t count = 0xBEEFu;
    uint16_t index;
    {prefix}_status status;
    memset(output, 0xA5, sizeof(output));
    input.objects = objects;
    input.object_count = (uint16_t)(sizeof(objects) / sizeof(objects[0]));
    input.transients = transients;
    input.transient_count = (uint16_t)(sizeof(transients) / sizeof(transients[0]));
    input.resolve_resource_type = resolve_resource;
    input.resource_context = 0;
    input.resolve_bank_key = resolve_bank;
    input.bank_context = 0;

    status = {prefix}_produce(&input, output, 128u, &count);
    if (status != {macro}_OK || count !=
            (uint16_t)(sizeof(expected) / sizeof(expected[0]))) return 10;
    for (index = 0; index < count; ++index) {{
        if (!same_record(&output[index], &expected[index])) return 20 + index;
    }}

    memset(streamed, 0x5A, sizeof(streamed));
    stream_accepted = 0u;
    stream_fail_after = 0xFFFFu;
    count = 0xBEEFu;
    status = {prefix}_stream(&input, emit_stream, 0, &count);
    if (status != {macro}_OK || count !=
            (uint16_t)(sizeof(expected) / sizeof(expected[0])) ||
            stream_accepted != count) return 60;
    for (index = 0; index < count; ++index) {{
        if (!same_record(&streamed[index], &expected[index])) return 61 + index;
    }}

    bad_object = objects[0];
    bad_object.field_descriptor = 0xFFFFu;
    input.objects = &bad_object;
    input.object_count = 1u;
    input.transients = 0;
    input.transient_count = 0u;
    resource_calls = 0u;
    bank_calls = 0u;
    stream_accepted = 0u;
    stream_fail_after = 0xFFFFu;
    count = 0xBEEFu;
    status = {prefix}_stream(&input, emit_stream, 0, &count);
    if (status != {macro}_RANGE || count != 0xBEEFu ||
            stream_accepted != 0u || resource_calls != 0u ||
            bank_calls != 0u) return 70;
    input.objects = objects;
    input.object_count = (uint16_t)(sizeof(objects) / sizeof(objects[0]));
    input.transients = transients;
    input.transient_count = (uint16_t)(sizeof(transients) / sizeof(transients[0]));

    stream_accepted = 0u;
    stream_fail_after = 7u;
    count = 0xBEEFu;
    status = {prefix}_stream(&input, emit_stream, 0, &count);
    if (status != {macro}_EMITTER || count != 7u ||
            stream_accepted != 7u) return 75;
    for (index = 0; index < count; ++index) {{
        if (!same_record(&streamed[index], &expected[index])) return 76;
    }}

    resource_calls = 0;
    bank_calls = 0;
    count = 0xCAFEu;
    status = {prefix}_produce(
        &input, output,
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

    def test_schema_is_derived_from_ir_and_ast_class_graph(self) -> None:
        model = self.model
        self.assertEqual(len(model.class_tags), 26)
        self.assertEqual(model.class_bit_bytes, 4)
        self.assertEqual(set(model.class_tags), {
            str(node.value)
            for action in self.plan.actions
            for expression in (*action.conditions, action.descriptor,
                               action.palette, action.resource_type,
                               action.anchor_x, action.anchor_y)
            for node in self._walk(expression)
            if node.op == "type"
        })
        self.assertEqual(
            [item.name for item in model.fields],
            ["active_palette", "body_kind", "descriptor", "effect",
             "overlay_descriptor", "overlay_x", "overlay_y", "palette",
             "render_ready", "state", "visible", "x", "y"])
        by_name = {item.name: item for item in model.fields}
        self.assertEqual(by_name["body_kind"].string_values,
                         ("middle", "upper"))
        self.assertEqual(by_name["effect"].string_values, ("e817",))
        self.assertEqual(by_name["state"].string_values, ("first",))
        self.assertEqual(by_name["render_ready"].getattr_default, True)
        memberships = dict(model.class_memberships)
        self.assertIn("Enemy", memberships)
        self.assertEqual(memberships["PlayerTargeting80E3"],
                         ("PlayerTargeting80E3",))
        self.assertEqual(len(model.class_graph_sha256), 64)

    @staticmethod
    def _walk(value: DrawExpr):
        yield value
        for argument in value.arguments:
            yield from DrawCBackendTests._walk(argument)

    def test_primary_plus_six_and_active_palette_are_literal(self) -> None:
        item = _object("PlayerTargeting80E3")
        records = self.records([item])
        resource = _resource_type(9)
        self.assertEqual(records, (
            LiteralDrawRecord(_bank_key(9, resource), 0x4100, 111, -222),
            LiteralDrawRecord(_bank_key(9, resource), 0x4106, 111, -222),
        ))

    def test_state_and_body_kind_follow_ir_branch_and_tuple_order(self) -> None:
        first = self.records([
            _object("Formation78F8Child", state="first", descriptor=0x2200),
        ])
        other = self.records([
            _object("Formation78F8Child", state="other", descriptor=0x2200),
        ])
        self.assertEqual([item.descriptor for item in first], [0x2200, 0x2206])
        self.assertEqual([item.descriptor for item in other], [0x2200])

        upper = self.records([_object("MultipartA71DBody", body_kind="upper")])
        middle = self.records([_object("MultipartA71DBody", body_kind="middle")])
        lower = self.records([_object("MultipartA71DBody", body_kind="lower")])
        self.assertEqual([item.descriptor for item in upper[1:]],
                         [0x5A08, 0x5A0E, 0x5A14, 0x5A1A, 0x5A20])
        self.assertEqual([item.descriptor for item in middle[1:]],
                         [0x5A4C, 0x5A52, 0x5A58, 0x5A5E, 0x5A64])
        self.assertEqual([item.descriptor for item in lower[1:]],
                         [0x5A88, 0x5A8E, 0x5A94])

    def test_overlay_fixed_tuple_and_transient_tuple_keep_python_order(self) -> None:
        records = self.records([
            _object("Handler60BAChild"),
            _object("FixedLarge6E9B", descriptor=0x5000, x=12, y=34),
        ], [NormalizedTransientView(0x7777, 3, 0x44, -8, 19)])
        self.assertEqual(records[0].descriptor, 0x4100)
        self.assertEqual(records[1], LiteralDrawRecord(
            _bank_key(5, _resource_type(5)), 0x6200, -123, 234))
        self.assertEqual(
            [item.descriptor for item in records[2:10]],
            [0x5000, 0x3048, 0x304E, 0x3054,
             0x305A, 0x3060, 0x3066, 0x306C])
        self.assertEqual(records[-1], LiteralDrawRecord(
            _bank_key(3, 0x44), 0x7777, -8, 19))

    def test_every_python_skip_predicate_suppresses_the_record(self) -> None:
        skipped = [
            _object(palette=0xFF),
            _object(render_ready=False),
            _object("BackgroundParticleE5CD", render_ready=False),
            _object("Targeting80E3AttackFlash", visible=False),
        ]
        self.assertEqual(self.records(skipped), ())
        visible = self.records([
            _object("Targeting80E3AttackFlash", visible=True),
        ])
        self.assertEqual(len(visible), 1)

    def test_capacity_failure_is_atomic_and_invokes_no_callback(self) -> None:
        calls = {"resource": 0, "bank": 0}

        def resource(palette: int) -> int:
            calls["resource"] += 1
            return _resource_type(palette)

        def bank(palette: int, resource_type: int) -> int:
            calls["bank"] += 1
            return _bank_key(palette, resource_type)

        sentinel = LiteralDrawRecord(1, 2, 3, 4)
        output = [sentinel]
        status = produce_draw_records_oracle(
            self.plan,
            objects=[_object("PlayerTargeting80E3")], transients=[],
            resource_type_resolver=resource, bank_key_resolver=bank,
            output=output, capacity=1)
        self.assertEqual(status, ProducerStatus.CAPACITY)
        self.assertEqual(output, [sentinel])
        self.assertEqual(calls, {"resource": 0, "bank": 0})

    def test_generated_artifacts_are_deterministic_and_not_action_tables(self) -> None:
        again = emit_draw_c_backend(self.plan)
        self.assertEqual(self.artifacts, again)
        manifest = json.loads(self.artifacts.manifest)
        self.assertEqual(manifest["format"], BACKEND_FORMAT)
        self.assertEqual(manifest["plan"]["action_count"],
                         len(self.plan.actions))
        self.assertEqual(
            manifest["lowering"]["action_ordinals"],
            list(range(len(self.plan.actions))))
        self.assertTrue(manifest["normalized_abi"]["failure_atomicity"]
                        ["capacity_failure_atomic"])
        self.assertFalse(manifest["normalized_abi"]["streaming"]
                         ["record_array_required"])
        self.assertEqual(manifest["normalized_abi"]["streaming"]["order"],
                         "strict-active-Python-loop-order")
        self.assertTrue(manifest["normalized_abi"]["bank_identity"]
                        ["host_validation"]["required_before_target_build"])
        self.assertIn("rtype_python_draw_plan_stream(", self.artifacts.header)
        self.assertIn("RTYPE_PYTHON_DRAW_PLAN_EMITTER = 4",
                      self.artifacts.header)
        self.assertIn("(sizeof(rtype_python_draw_plan_record) == 8) ? 1 : -1",
                      self.artifacts.source)
        self.assertNotIn("static const", self.artifacts.source)
        self.assertEqual(
            self.artifacts.source.count("source sink"), len(self.plan.actions))
        self.assertEqual(
            self.artifacts.source.count("strict Python order"),
            len(self.plan.actions))

    def test_unsupported_expression_fails_closed(self) -> None:
        action = self.plan.actions[0]
        changed = replace(
            action,
            descriptor=DrawExpr("multiply", (
                action.descriptor, DrawExpr("constant", value=2))))
        plan = replace(
            self.plan, actions=(changed, *self.plan.actions[1:]))
        with self.assertRaisesRegex(DrawCBackendError, "PZDPC001"):
            emit_draw_c_backend(plan)

    def test_host_resolver_proof_exhausts_declared_byte_domains(self) -> None:
        proof = validate_resolver_domains(
            palette_domain=range(256), resource_type_domain=range(256),
            resource_type_resolver=_resource_type,
            bank_key_resolver=_bank_key)
        self.assertEqual(proof["palette_count"], 256)
        self.assertEqual(proof["resource_type_count"], 256)
        self.assertEqual(proof["palette_resource_pair_count"], 65536)
        self.assertTrue(proof["total"])
        self.assertTrue(proof["deterministic"])

    @unittest.skipUnless(HOST_CC is not None, "portable host C compiler unavailable")
    def test_host_c_output_matches_python_ir_oracle_for_every_action(self) -> None:
        assert HOST_CC is not None
        objects, transients = self._all_action_fixture()
        action_trace: list[int] = []
        expected = self.records(objects, transients, action_trace)
        # All 34 IR action templates execute at least once; primary actions
        # execute once per visible object, so the resulting record array is
        # intentionally larger than the action inventory.
        self.assertGreater(len(expected), len(self.plan.actions))
        self.assertEqual(set(action_trace), set(range(len(self.plan.actions))))
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-host-") as temporary:
            directory = Path(temporary)
            (directory / self.artifacts.header_name).write_text(
                self.artifacts.header, encoding="utf-8", newline="\n")
            (directory / self.artifacts.source_name).write_text(
                self.artifacts.source, encoding="utf-8", newline="\n")
            harness_name = "draw_plan_host_check.c"
            (directory / harness_name).write_text(
                self._host_harness(objects, transients, expected),
                encoding="utf-8", newline="\n")
            executable = directory / "draw_plan_host_check.exe"
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

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC is unavailable")
    def test_generated_abi_compiles_with_pinned_sdcc(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-c-") as temporary:
            directory = Path(temporary)
            (directory / self.artifacts.header_name).write_text(
                self.artifacts.header, encoding="utf-8", newline="\n")
            smoke_name = "draw_plan_abi_smoke.c"
            (directory / smoke_name).write_text(
                '#include "' + self.artifacts.header_name + '"\n'
                "uint16_t draw_plan_abi_smoke(\n"
                "    const rtype_python_draw_plan_object_view *object,\n"
                "    rtype_python_draw_plan_record *record)\n"
                "{\n"
                "    return (uint16_t)(sizeof(*object) + sizeof(*record));\n"
                "}\n", encoding="utf-8", newline="\n")
            environment = os.environ.copy()
            environment["PATH"] = (
                str(SDCC.parent) + os.pathsep + environment.get("PATH", ""))
            completed = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--nolospre", "--nolabelopt", "--noinvariant",
                 "--noinduction", "--noloopreverse", "--no-peep",
                 "-c", smoke_name],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=180,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue((directory / smoke_name.replace(
                ".c", ".rel")).is_file())


if __name__ == "__main__":
    unittest.main()
