#!/usr/bin/env python3
"""Проверки строгого AST-переноса активного Python-runtime."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import sys
import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtype_python_translator as translator
from pyz80_compiler.frontend import lower_function
from pyz80_compiler.interpreter import execute
from pyz80_compiler.manifest import CompilerManifest


class PythonTranslatorTests(unittest.TestCase):
    def test_active_import_graph(self) -> None:
        paths = translator.module_paths()
        trees, _ = translator.reachable_graph(paths)
        self.assertIn("rtype_port.app", trees)
        self.assertIn("rtype_port.game", trees)
        self.assertIn("rtype_port.stage", trees)
        self.assertIn("rtype_port.enemies", trees)
        self.assertIn("rtype_port.force", trees)
        self.assertIn("rtype_port.bits", trees)
        self.assertNotIn("rtype_port.full_runtime", trees)
        self.assertNotIn("rtype_m72.machine", trees)

    def test_tables_and_compiled_functions_are_computed_from_ast(self) -> None:
        paths = translator.module_paths()
        trees, _ = translator.reachable_graph(paths)
        records = {}
        for spec in translator.TABLE_SPECS:
            blob, record = translator.compile_table(spec, trees)
            records[spec.asm_name] = (blob, record)
        for spec in translator.CONSTANT_TABLE_SPECS:
            blob, record = translator.compile_constant_table(spec, trees)
            records[spec.asm_name] = (blob, record)

        label, _ = records["RTypePyP1LabelVisible"]
        self.assertEqual((label[0], label[15], label[16], label[31]),
                         (1, 1, 0, 0))

        self.assertNotIn("RTypePyAdvancePitch", records)
        manifest = CompilerManifest.load(translator.PYZ80_MANIFEST)
        pitch_spec = next(
            item for item in manifest.functions
            if item.symbol == "rtype_port.game.advance_pitch")
        pitch, _ = lower_function(translator.PYTHON_ROOT, pitch_spec)
        self.assertEqual(execute(pitch, (20, 1, 0)), 19)
        self.assertEqual(execute(pitch, (20, 0, 1)), 21)
        self.assertEqual(execute(pitch, (20, 1, 1)), 20)

        beam, _ = records["RTypePyBeamNativeWidth"]
        self.assertEqual((beam[0], beam[4], beam[128]), (0, 0, 124))
        power, _ = records["RTypePyWavePower"]
        self.assertEqual((power[0x17], power[0x18], power[0x30], power[0x68]),
                         (0, 4, 8, 20))
        tier, _ = records["RTypePyWavePowerTier"]
        self.assertEqual((tier[0], tier[1], tier[20]), (0, 4, 20))
        charge, _ = records["RTypePyAdvanceWaveCharge"]
        self.assertEqual((charge[0], charge[127], charge[128]), (2, 128, 128))
        phase, _ = records["RTypePyBeamAnimationPhase"]
        self.assertEqual((phase[0], phase[4], phase[28], phase[32]), (0, 1, 7, 0))

        logo, _ = records["RTypePyTitleLogoState"]
        last_r = (315 * 7) * 5
        self.assertEqual(struct.unpack_from("<Bhh", logo, last_r), (1, 16, 128))
        trademark = (125 * 7 + 6) * 5
        self.assertEqual(struct.unpack_from("<Bhh", logo, trademark)[0], 0)

        prompt, _ = records["RTypePyTitlePromptVisible"]
        self.assertEqual((prompt[0], prompt[31], prompt[32], prompt[63]),
                         (1, 1, 0, 0))


    def test_unsupported_ast_fails_instead_of_guessing(self) -> None:
        tree = translator.ast.parse("def f(x):\n    return str(x)\n")
        function = translator.find_function(tree, "f")
        with self.assertRaises(translator.TranslationError):
            translator.execute_function(function, {}, {"x": 1})

    def test_hq_asset_contract_uses_exact_python_cell_geometry(self) -> None:
        paths = translator.module_paths()
        trees, _ = translator.reachable_graph(paths)
        terrain_cell, sprite_cell, fingerprint = (
            translator.hq_asset_geometry_contract(trees))
        requests = translator.python_sprite_bootstrap_requests()

        self.assertEqual(terrain_cell, (14, 15))
        self.assertEqual(sprite_cell, (27, 30))
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(len(requests), 206)
        self.assertEqual({request[1] for request in requests}, {0x09, 0x20, 0x55})
        self.assertTrue(all(0 <= request[2] < 4096 for request in requests))

    def test_ft812_fragment_queue_contract_is_explicit_and_byte_compatible(
            self) -> None:
        protocol = translator.ft812_queue_protocol_contract()
        self.assertEqual(
            (protocol["format"], protocol["header_size"],
             protocol["kind_offset"]),
            (3, 16, 14))
        self.assertEqual(protocol["full"], {
            "kind": 0,
            "acquire_prefix": ["CMD_DLSTART"],
            "commit_suffix": ["DISPLAY", "CMD_SWAP"],
        })
        self.assertEqual(protocol["fragment"]["kind"], 1)
        self.assertEqual(protocol["fragment"]["acquire_prefix"], [])
        self.assertEqual(protocol["fragment"]["commit_suffix"], [])
        batch = protocol["fragment"]["sprite_batch"]
        self.assertEqual(
            (batch["record_size"], batch["record_vma"],
             batch["record_bytes"], batch["max_records"]),
            (8, 0xCA44, 0x35BC, 128))
        self.assertEqual(
            batch["remaining_dl_budget"], "caller full-frame <=2048")
        self.assertEqual(
            batch["pre_resolved"]["record_size"], 6)
        self.assertEqual(
            batch["pre_resolved"]["old_literal_abi"],
            "retained as differential oracle")
        self.assertEqual(protocol["mixed_kind"], "fail-closed")

        legacy_full = struct.pack(
            "<HBBHHHHBBH", 0x4651, 3, 0xED,
            0x1234, 7, 28, 5, 2, 0, 0)
        explicit_full = struct.pack(
            "<HBBHHHHBBBB", 0x4651, 3, 0xED,
            0x1234, 7, 28, 5, 2, 0, 0, 0)
        fragment = struct.pack(
            "<HBBHHHHBBBB", 0x4651, 3, 0xED,
            0x1234, 5, 20, 6, 2, 0, 1, 0)
        self.assertEqual(explicit_full, legacy_full)
        self.assertEqual(fragment[14], 1)

        exports = {name for name, _abi in translator.FT812_SUPPORT_EXPORTS}
        self.assertIn("PyZ80FT_QueueAcquireFragment", exports)
        self.assertIn("PyZ80FT_QueueCommitFragment", exports)
        self.assertIn("PyZ80FT_LogicalVertex", exports)
        self.assertIn("PyZ80FT_BuildSpriteBatch", exports)
        self.assertIn("PyZ80FT_BuildSpriteBatchFast", exports)
        self.assertTrue(all(len(name) <= 32 for name in exports))

    def test_enemy_draw_plan_is_compiled_from_active_python_in_source_order(
            self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        self.assertEqual(plan.symbol,
                         "rtype_port.enemies.M72EnemyWorld.draw")
        self.assertEqual(len(plan.loops), 2)
        self.assertEqual(len(plan.sink_occurrences), 16)
        self.assertEqual(len(plan.actions), 34)
        self.assertEqual(
            [item.ordinal for item in plan.actions],
            list(range(34)))
        self.assertEqual(len(plan.semantic_sha256), 64)

        bound = translator.analyze_active_frame_record_bound(translator.ROOT)
        bound_value = bound.as_dict()
        self.assertEqual(
            bound_value["status"],
            "READY_CONSERVATIVE_REACHABLE_STATE_BOUND")
        self.assertTrue(bound_value["proof_complete"])
        self.assertIsNone(bound_value["exact_max_records"])
        self.assertEqual(bound_value["certified_frame_max_records"], 228)
        self.assertEqual(
            bound_value["bound_kind"], "conservative_upper_bound")
        self.assertTrue(bound_value["can_certify_frame_budget"])
        self.assertEqual(bound_value["blockers"], [])
        self.assertEqual(len(bound_value["optional_tightening_gaps"]), 2)
        self.assertEqual(
            bound_value["draw_plan"]["semantic_sha256"],
            plan.semantic_sha256)

    def test_portable_draw_c_stage_is_hash_bound_and_not_linked_live(
            self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = translator.emit_draw_c_backend_stage(plan, output)
            repeated = translator.emit_draw_c_backend_stage(plan, output)

            self.assertEqual(report, repeated)
            self.assertEqual(report["format"],
                             translator.DRAW_C_BACKEND_FORMAT)
            self.assertEqual(report["plan"]["semantic_sha256"],
                             plan.semantic_sha256)
            self.assertEqual(
                report["artifacts"]["manifest"][
                    "plan_semantic_sha256"],
                plan.semantic_sha256)
            for kind in ("header", "source", "manifest"):
                artifact = report["artifacts"][kind]
                path = Path(artifact["path"])
                self.assertEqual(path.stat().st_size, artifact["size"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    artifact["sha256"])

            integration = report["compile_manifest_integration"]
            self.assertFalse(integration["support_files_included"])
            self.assertFalse(
                integration["live_target_performance_and_size_certified"])
            self.assertIn("object-layout adapter", integration["reason"])
            streaming = report["streaming"]
            self.assertFalse(streaming["record_array_required"])
            self.assertTrue(streaming["preflight_before_first_emission"])
            self.assertEqual(
                streaming["function"], "rtype_python_draw_plan_stream")
            chunker = streaming["bounded_chunk_adapter"]
            self.assertEqual(chunker["status"], "portable-not-live")
            for artifact in chunker["artifacts"].values():
                path = translator.ROOT / artifact["path"]
                self.assertEqual(path.stat().st_size, artifact["size"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    artifact["sha256"])
            size_probe = report["target_size_probe"]
            self.assertEqual(
                size_probe["status"], "BLOCKED_CODE_PAGE_OVERFLOW")
            self.assertEqual(size_probe["code_bytes"], 21788)
            self.assertEqual(size_probe["single_page_bytes"], 16384)
            self.assertEqual(
                size_probe["overflow_bytes_before_other_runtime_code"], 5404)
            support_names = {
                name for name, _contents in translator.compiler_support_files()
            }
            self.assertNotIn(translator.OUT_DRAW_C_HEADER.name, support_names)
            self.assertNotIn(translator.OUT_DRAW_C_SOURCE.name, support_names)
            self.assertNotIn(translator.DRAW_CHUNKER_HEADER.name, support_names)
            self.assertNotIn(translator.DRAW_CHUNKER_SOURCE.name, support_names)

    def test_portable_draw_c_stage_rejects_semantic_hash_before_write(
            self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        artifacts = translator.emit_draw_c_backend(plan)
        manifest = json.loads(artifacts.manifest)
        manifest["plan"]["semantic_sha256"] = "0" * 64
        corrupted = replace(
            artifacts,
            manifest=json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        with tempfile.TemporaryDirectory() as temporary:
            with (mock.patch.object(
                    translator, "emit_draw_c_backend",
                    return_value=corrupted),
                  mock.patch.object(
                    translator, "write_draw_c_backend") as writer):
                with self.assertRaisesRegex(
                        translator.TranslationError,
                        "manifest is not bound"):
                    translator.emit_draw_c_backend_stage(
                        plan, Path(temporary))
                writer.assert_not_called()

    def test_compact_draw_vm_stage_is_selected_zero_copy_and_hash_bound(
            self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = translator.emit_draw_vm_backend_stage(plan, output)
            repeated = translator.emit_draw_vm_backend_stage(plan, output)

            self.assertEqual(report, repeated)
            self.assertEqual(report["format"],
                             translator.DRAW_VM_BACKEND_FORMAT)
            self.assertEqual(
                report["status"],
                "selected-compact-target-neutral-live-blocked")
            self.assertEqual(report["plan"]["semantic_sha256"],
                             plan.semantic_sha256)
            self.assertEqual(
                report["artifacts"]["manifest"][
                    "plan_semantic_sha256"],
                plan.semantic_sha256)
            for kind in ("header", "source", "manifest"):
                artifact = report["artifacts"][kind]
                path = Path(artifact["path"])
                self.assertEqual(path.stat().st_size, artifact["size"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    artifact["sha256"])

            compact = report["compact_program"]
            self.assertEqual(compact["node_count"], 79)
            self.assertEqual(compact["condition_pack_count"], 18)
            self.assertEqual(compact["action_count"], 34)
            self.assertEqual(compact["logical_table_payload_bytes"], 815)
            provider = report["zero_copy_object_provider"]
            self.assertFalse(provider["full_pool_materialization_required"])
            self.assertEqual(provider["working_view_count"], 1)
            self.assertEqual(provider["working_view_bytes"], 28)
            self.assertTrue(provider["failure_before_first_output"])
            self.assertEqual(
                provider[
                    "resolver_or_emitter_calls_before_preflight_failure"],
                0)
            size_probe = report["target_size_probe"]
            self.assertEqual(
                size_probe["status"],
                "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED")
            self.assertEqual(size_probe["code_bytes"], 4501)
            self.assertEqual(size_probe["data_bytes"], 0)
            self.assertEqual(size_probe["single_page_bytes"], 16384)
            self.assertEqual(
                size_probe["page_headroom_bytes_before_adapter_and_runtime"],
                11883)
            stack = report["target_stack_certificate"]
            self.assertEqual(
                stack["status"],
                "INTERNAL_STACK_BOUND_PASS_EXTERNAL_CALLBACKS_BLOCKED")
            self.assertEqual(
                stack[
                    "maximum_internal_stack_bytes_including_public_arguments"],
                241)
            self.assertEqual(stack["produce_internal_stack_bytes"], 241)
            self.assertEqual(stack["stream_internal_stack_bytes"], 239)
            self.assertEqual(stack["eval_stack_bytes_from_function_entry"], 92)
            self.assertEqual(stack["walk_stack_bytes_from_function_entry"], 214)
            self.assertEqual(
                stack["maximum_simultaneous_eval_invocations"], 4)
            self.assertIsNone(
                stack["complete_vm_plus_callbacks_stack_bytes"])
            self.assertFalse(stack["live_target_use_certified"])
            integration = report["compile_manifest_integration"]
            self.assertFalse(integration["support_files_included"])
            self.assertFalse(
                integration["live_target_performance_and_size_certified"])
            support_names = {
                name for name, _contents in translator.compiler_support_files()
            }
            self.assertNotIn(translator.OUT_DRAW_VM_HEADER.name, support_names)
            self.assertNotIn(translator.OUT_DRAW_VM_SOURCE.name, support_names)

    def test_compact_draw_vm_stage_rejects_semantic_hash_before_write(
            self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        artifacts = translator.emit_draw_vm_backend(plan)
        manifest = json.loads(artifacts.manifest)
        manifest["plan"]["semantic_sha256"] = "0" * 64
        corrupted = replace(
            artifacts,
            manifest=json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        with tempfile.TemporaryDirectory() as temporary:
            with (mock.patch.object(
                    translator, "emit_draw_vm_backend",
                    return_value=corrupted),
                  mock.patch.object(
                    translator, "write_draw_vm_backend") as writer):
                with self.assertRaisesRegex(
                        translator.TranslationError,
                        "manifest is not bound"):
                    translator.emit_draw_vm_backend_stage(
                        plan, Path(temporary))
                writer.assert_not_called()

    def test_render_order_stage_preserves_python_list_not_physical_slots(
            self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = translator.emit_render_order_backend_stage(
                translator.ROOT, output)
            repeated = translator.emit_render_order_backend_stage(
                translator.ROOT, output)

            self.assertEqual(report, repeated)
            self.assertEqual(report["format"],
                             translator.RENDER_ORDER_BACKEND_FORMAT)
            self.assertEqual(
                report["status"],
                "source-derived-target-neutral-live-blocked")
            self.assertTrue(
                report["draw_order"]["direct_python_list_order"])
            pool = report["source_derived_pool"]
            self.assertEqual(pool["slot_count"], 96)
            self.assertEqual(pool["reserved_sentinel_count"], 2)
            self.assertEqual(pool["capacity"], 94)
            self.assertEqual(pool["checkpoint_count"], 27)
            self.assertEqual(pool["audited_mutation_kinds"], 6)
            state = report["normalized_state"]
            self.assertEqual(state["target_bytes"], 191)
            self.assertFalse(state["full_object_copy_required"])
            self.assertEqual(
                state["slot_at"], "O(1) direct VM-loader lookup")
            self.assertTrue(state["failure_atomic"])
            size_probe = report["target_size_probe"]
            self.assertEqual(
                size_probe["status"],
                "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED")
            self.assertEqual(size_probe["code_bytes"], 1489)
            self.assertEqual(size_probe["data_bytes"], 0)
            self.assertEqual(size_probe["state_bytes"], 191)
            self.assertEqual(
                size_probe["page_headroom_bytes_before_adapter_and_runtime"],
                14895)
            for kind in ("header", "source", "manifest"):
                artifact = report["artifacts"][kind]
                path = Path(artifact["path"])
                self.assertEqual(path.stat().st_size, artifact["size"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    artifact["sha256"])
            integration = report["compile_manifest_integration"]
            self.assertFalse(integration["support_files_included"])
            self.assertFalse(integration["live_target_hooks_present"])
            support_names = {
                name for name, _contents in translator.compiler_support_files()
            }
            self.assertNotIn(
                translator.OUT_RENDER_ORDER_HEADER.name, support_names)
            self.assertNotIn(
                translator.OUT_RENDER_ORDER_SOURCE.name, support_names)

    def test_render_order_stage_rejects_stale_semantic_before_write(
            self) -> None:
        artifacts = translator.emit_render_order_backend(translator.ROOT)
        manifest = json.loads(artifacts.manifest)
        manifest["semantic_sha256"] = "0" * 64
        corrupted = replace(
            artifacts,
            manifest=json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        with tempfile.TemporaryDirectory() as temporary:
            with (mock.patch.object(
                    translator, "emit_render_order_backend",
                    return_value=corrupted),
                  mock.patch.object(
                    translator, "write_render_order_backend") as writer):
                with self.assertRaisesRegex(
                        translator.TranslationError,
                        "format/status/source semantic binding changed"):
                    translator.emit_render_order_backend_stage(
                        translator.ROOT, Path(temporary))
                writer.assert_not_called()

    def test_draw_state_stage_is_persistent_source_derived_and_not_live(
            self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = translator.emit_draw_state_backend_stage(
                plan, translator.ROOT, output)
            repeated = translator.emit_draw_state_backend_stage(
                plan, translator.ROOT, output)

            self.assertEqual(report, repeated)
            self.assertEqual(report["format"],
                             translator.DRAW_STATE_BACKEND_FORMAT)
            self.assertEqual(
                report["status"],
                "source-derived-persistent-sidecar-live-blocked")
            state = report["persistent_state"]
            self.assertEqual(state["slot_count"], 96)
            self.assertEqual(state["slot_state_bytes"], 26)
            self.assertEqual(state["state_bytes"], 2496)
            self.assertEqual(state["normalized_field_count"], 13)
            self.assertEqual(state["concrete_enemy_class_count"], 73)
            self.assertFalse(state["frame_materialization"])
            writes = report["source_write_inventory"]
            self.assertEqual(writes["mutation_site_count"], 368)
            self.assertEqual(writes["derived_field_site_count"], 17)
            self.assertEqual(writes["dynamic_write_blocker_count"], 5)
            self.assertEqual(writes["identity_site_count"], 14)
            self.assertEqual(report["provider"]["output_bytes"], 28)
            size = report["target_size_probe"]
            self.assertEqual(size["code_bytes"], 4957)
            self.assertEqual(size["data_bytes"], 0)
            self.assertEqual(size["persistent_state_bytes"], 2496)
            self.assertEqual(
                size["page_headroom_bytes_before_linked_runtime"], 11427)
            for artifact in report["artifacts"].values():
                path = Path(artifact["path"])
                self.assertEqual(path.stat().st_size, artifact["size"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    artifact["sha256"])
            integration = report["compile_manifest_integration"]
            self.assertFalse(integration["support_files_included"])
            self.assertFalse(integration["live_target_hooks_present"])
            support_names = {
                name for name, _contents in translator.compiler_support_files()
            }
            self.assertNotIn(
                translator.OUT_DRAW_STATE_HEADER.name, support_names)
            self.assertNotIn(
                translator.OUT_DRAW_STATE_SOURCE.name, support_names)

    def test_draw_state_stage_rejects_stale_semantic_before_write(self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        artifacts = translator.emit_draw_state_backend(
            translator.ROOT, plan=plan)
        manifest = json.loads(artifacts.manifest)
        manifest["semantic_sha256"] = "0" * 64
        corrupted = replace(
            artifacts,
            manifest=json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        with tempfile.TemporaryDirectory() as temporary:
            with (mock.patch.object(
                    translator, "emit_draw_state_backend",
                    return_value=corrupted),
                  mock.patch.object(
                    translator, "write_draw_state_backend") as writer):
                with self.assertRaisesRegex(
                        translator.TranslationError,
                        "format/status/source binding changed"):
                    translator.emit_draw_state_backend_stage(
                        plan, translator.ROOT, Path(temporary))
                writer.assert_not_called()

    def test_fast_draw_pipeline_is_hash_bound_and_not_linked_live(self) -> None:
        plan = translator.compile_active_enemy_draw_plan(translator.ROOT)
        report = translator.draw_fast_pipeline_contract(
            {
                "plan": {"semantic_sha256": plan.semantic_sha256},
                "target_size_probe": {"code_bytes": 4501},
            },
            {"sprite_templates": {"record_count": 40}},
        )
        self.assertEqual(
            report["status"],
            "target-neutral-fast-pipeline-live-blocked")
        self.assertFalse(
            report["bridge_contract"]["full_frame_record_array_required"])
        size = report["target_size_probe"]
        self.assertEqual(size["code_bytes"], 1828)
        self.assertEqual(
            size["vm_plus_bridge_additive_code_upper_bound"], 6329)
        timing = report["pinned_z80_timing"]
        self.assertEqual(timing["steady_nonflush_record_tstates"], 2674)
        self.assertEqual(timing["chunk32_before_fast_batch_tstates"], 88007)
        self.assertFalse(timing["fast_batch_body_included"])
        integration = report["compile_manifest_integration"]
        self.assertFalse(integration["support_files_included"])
        self.assertFalse(
            integration["live_target_performance_size_stack_certified"])
        support_names = {
            name for name, _contents in translator.compiler_support_files()
        }
        self.assertNotIn(
            translator.DRAW_FAST_CHUNKER_HEADER.name, support_names)
        self.assertNotIn(
            translator.DRAW_FAST_CHUNKER_SOURCE.name, support_names)

    def test_late_translation_failure_restores_all_owned_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files, directories = translator.translator_generation_surfaces(root)
            report = root / "Build" / "rtype_python_translation.json"
            generated = root / "Source" / "C" / "generated"
            call_site_status = (
                root / "Build" /
                "rtype_python_active_call_site_lowering_status.json")
            call_abi_status = (
                root / "Build" /
                "rtype_python_whole_program_vm_call_abi_status.json")
            generated.mkdir(parents=True)
            existing_c = generated / "existing.c"
            unowned = root / "Source" / "Python" / "game.py"
            report.parent.mkdir(parents=True, exist_ok=True)
            unowned.parent.mkdir(parents=True, exist_ok=True)
            report.write_bytes(b"report-before")
            existing_c.write_bytes(b"c-before")
            unowned.write_bytes(b"python-before")
            self.assertIn(report.resolve(), files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_translation_checkpoint.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" / "rtype_python_frame_budget.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_frame_record_bound_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_frame_record_reachability_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_frame_sprite_fragment_envelope_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_draw_target_bundle_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_draw_bank_placement_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_mutation_hook_ir_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_object_store_ir_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_function_cfg_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_active_call_graph_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_active_call_site_lowering_status.json")
                .resolve(), files)
            self.assertIn(call_abi_status.resolve(), files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_active_target_adapters_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_frame_timing_provider_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_frame_timing_contract.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_draw_ramdl_shadow_v4_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_whole_program_vm.bin").resolve(), files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_whole_program_vm_proof.bin").resolve(), files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_whole_program_vm_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_whole_program_vm_stack_bound_status.json")
                .resolve(), files)
            self.assertIn(
                (root / "Source" / "ASM" /
                 "generated_python_frame_timing.inc").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_full_hqt3_inventory_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_hqt3_ramg_schedule_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_hqt3_partition_solver_status.json").resolve(),
                files)
            self.assertIn(
                (root / "Build" /
                 "rtype_python_hqt3_frame_page_solver_status.json").resolve(),
                files)
            self.assertIn(generated.resolve(), directories)

            def fail_late(_require_complete: bool) -> dict[str, object]:
                report.write_bytes(b"report-partial")
                call_site_status.write_bytes(b"call-site-partial")
                call_abi_status.write_bytes(b"call-abi-partial")
                existing_c.write_bytes(b"c-partial")
                (generated / "new.c").write_bytes(b"new-partial")
                unowned.write_bytes(b"python-user-change")
                raise translator.TranslationError("deliberate late failure")

            with (mock.patch.object(translator, "ROOT", root),
                  mock.patch.object(
                      translator, "_translate_untransactional",
                      side_effect=fail_late)):
                with self.assertRaisesRegex(
                        translator.TranslationError,
                        "deliberate late failure"):
                    translator.translate(False)

            self.assertEqual(report.read_bytes(), b"report-before")
            self.assertFalse(call_site_status.exists())
            self.assertFalse(call_abi_status.exists())
            self.assertEqual(existing_c.read_bytes(), b"c-before")
            self.assertFalse((generated / "new.c").exists())
            self.assertEqual(unowned.read_bytes(), b"python-user-change")

    def test_legacy_backend_is_bound_but_not_claimed_as_compiled(self) -> None:
        paths = translator.module_paths()
        trees, _ = translator.reachable_graph(paths)
        contract = translator.gameplay_backend_contract(trees)
        self.assertEqual(contract["terrain_foreground_clear_code"], 0x0DFC)
        self.assertEqual(contract["terrain_background_clear_code"], 0x07D0)
        self.assertEqual((contract["initial_lives"], contract["max_lives"]),
                         (8, 8))
        self.assertEqual(contract["z_order"][0], "self.stage.draw_back")
        self.assertEqual(contract["z_order"][-1], "self._draw_debug_distance")
        self.assertEqual(contract["frame_counter_seed"], 0x0292)
        self.assertEqual(contract["frame_counter_step"], 1)
        self.assertEqual(contract["frame_counter_mask"], 0xFFFF)
        self.assertEqual(contract["source_frame_rate"], 55.0)
        counts = contract["object_draw_policy"]["descriptor_counts"]
        self.assertEqual((counts[11], counts[21], counts[65], counts[70]),
                         (2, 2, 2, 2))
        self.assertEqual(counts[41], 1)
        self.assertEqual(len(contract["beam_meter"]["states"]), 65)
        self.assertTrue(all(len(state) == 17
                            for state in contract["beam_meter"]["states"]))
        self.assertEqual(len(contract["charge_assets"]), 8)

        translator.emit_gameplay_backend(contract)
        generated = translator.OUT_GAMEPLAY_BACKEND.read_text(encoding="utf-8")
        collision = translator.OUT_COLLISION_BACKEND.read_text(encoding="utf-8")
        self.assertIn("RTypePyPlayerTerrainCollision:", collision)
        self.assertIn("RTypePyRenderLives:", generated)
        self.assertIn("RTypePyBackgroundParticleFastUpdate:", generated)
        self.assertIn("RTypePyObjectDrawCount:", generated)
        self.assertIn("RTypePyRenderChargeOrb:", generated)
        self.assertIn("RTypePyRenderBeamMeter:", generated)
        self.assertIn("RTypePyGameplay_AdvanceFrameCounter:", generated)
        compiled_symbols = {
            item.symbol for item in
            CompilerManifest.load(translator.PYZ80_MANIFEST).functions
        }
        self.assertNotIn("rtype_port.game.Game.update", compiled_symbols)
        tables = translator.OUT_GAMEPLAY_TABLES.read_text(encoding="utf-8")
        self.assertNotIn("FT.Coprocessor.Write", tables)
        self.assertNotIn("RTypePyCoprocessorWriteDMA:", tables)

    def test_translation_closure_cannot_hide_live_target_blockers(self) -> None:
        blocked = translator.translation_closure_contract(
            pending=[{"symbol": "rtype_port.game.Game.update"}],
            sprite_working_sets={
                "ready": False,
                "status": "BLOCKED",
                "missing_invariants": [{"code": "PZSW101"}],
            },
            frame_record_bound={
                "proof_complete": False,
                "can_certify_frame_budget": False,
                "status": "BLOCKED",
                "blockers": [{"code": "PZFRB101"}],
            },
            frame_sprite_fragment_envelope={
                "status": "BLOCKED",
                "proof_complete": False,
                "live_eligible": False,
                "blockers": [{"code": "PZFSFE101"}],
            },
            frame_render_plan={
                "live_target_lowering_present": False,
                "status": "BLOCKED",
                "live_blockers": ["not lowered"],
            },
            frame_budget={
                "status": "BLOCKED_MISSING_TRANSLATOR_CERTIFICATE",
                "full_frame_proved": False,
                "live_target_lowering_present": False,
                "blockers": {"missing_fragment_contracts": ["counter"]},
            },
            frame_budget_live_hook={
                "status": "BLOCKED",
                "present": False,
                "blockers": ["not connected"],
            },
            render_order_backend={
                "status": "BLOCKED",
                "compile_manifest_integration": {
                    "live_target_hooks_present": False,
                    "reason": "not hooked",
                },
            },
            draw_vm_backend={
                "status": "BLOCKED",
                "compile_manifest_integration": {
                    "live_target_performance_and_size_certified": False,
                    "reason": "not certified",
                },
            },
            draw_state_backend={
                "status": "BLOCKED",
                "compile_manifest_integration": {
                    "live_target_hooks_present": False,
                    "reason": "not hooked",
                },
            },
            draw_fast_pipeline={
                "status": "BLOCKED",
                "compile_manifest_integration": {
                    "live_target_performance_size_stack_certified": False,
                    "reason": "not linked",
                },
            },
            draw_target_bundle={
                "status": "BLOCKED",
                "live": False,
                "live_blockers": [{"code": "PZTB001"}],
            },
            draw_bank_placement={
                "status": "BLOCKED",
                "live": False,
                "live_blockers": [{"code": "PZBP001"}],
            },
            mutation_hook_ir={
                "status": "BLOCKED",
                "live": False,
                "live_blockers": ["frontend not connected"],
            },
            object_store_ir={
                "status": "BLOCKED",
                "live": False,
                "live_blockers": ["backend not connected"],
            },
            function_cfg_ir={
                "status": "ACTIVE_FUNCTION_CFG_COMPLETE_LIVE_BLOCKED",
                "live": False,
                "live_blockers": ["backend not connected"],
            },
            active_call_graph={
                "status": "ACTIVE_CALL_GRAPH_INVENTORIED_LIVE_BLOCKED",
                "live": False,
                "live_blockers": [{"code": "PZACG201"}],
            },
            active_call_site_lowering={
                "status": "ACTIVE_CALL_SITE_LOWERING_PLANNED_LIVE_BLOCKED",
                "live": False,
                "proof": {"backend_consumer_bound": False},
                "live_blockers": [{"code": "PZCSL210"}],
            },
            whole_program_vm_call_abi={
                "status": "WHOLE_PROGRAM_VM_CALL_ABI_PLANNED_LIVE_BLOCKED",
                "live": False,
                "proof": {"current_vm_backend_consumes_call_abi": False},
                "live_blockers": [{"code": "PZCABI213"}],
            },
            active_target_adapters={
                "status": "ACTIVE_TARGET_ADAPTERS_INVENTORIED_LIVE_BACKEND_BLOCKED",
                "live": False,
                "live_blockers": [{"code": "PZATA201"}],
            },
            frame_timing_provider={
                "status": "FRAME_TIMING_CONTRACT_GENERATED_ASSEMBLE_MEASURE_BLOCKED",
                "live": False,
                "live_blockers": [{"code": "PZFTP201"}],
            },
            draw_ramdl_shadow_v4={
                "status": "DIRECT_RAMDL_DEDUP_LAYOUT_PROVED_LIVE_INTEGRATION_BLOCKED",
                "live": False,
                "blockers": [{"code": "PZRAMDL401"}],
            },
            whole_program_vm={
                "format": "pyz80.whole-program-vm-status.v1",
                "live": False,
                "live_blockers": [{"code": "PZWVLIVE001"}],
            },
            whole_program_vm_stack_bound={
                "format": "pyz80.whole-program-vm-stack-bound.v1",
                "complete_bound_proved": False,
                "live": False,
                "live_blockers": [{"code": "PZVSBLIVE002"}],
            },
            full_hqt3_inventory={
                "status": "COMPLETE_TEMPLATE_CATALOG_LOAD_TRANSITIONS_BLOCKED",
                "live": False,
                "blockers": [{"code": "PZHQT203"}],
            },
            hqt3_ramg_schedule={
                "status": "EXACT_SCOPE_PACKS_TRANSITIONS_AND_LIFETIMES_BLOCKED",
                "live": False,
                "blockers": [{"code": "PZRG301"}],
            },
            hqt3_partition_solver={
                "status": "STRUCTURAL_HQT_SHARD_PROVED_RAMG_PAGING_LIFETIMES_BLOCKED",
                "live": False,
                "blockers": [{"code": "PZPART401"}],
            },
            hqt3_frame_page_solver={
                "status": "EXACT_PAGE_ATOMS_AND_COLD_MISS_FLOOR_LIFETIME_UPPER_BOUND_BLOCKED",
                "live": False,
                "blockers": [{"code": "PZPAGE501"}],
            },
            gameplay_backend={"status": "legacy_template_not_translation"},
            sprite_backend={"status": "legacy_template_not_translation"},
        )
        self.assertFalse(blocked["complete"])
        self.assertEqual(blocked["blocker_count"], 30)
        self.assertEqual(
            [item["code"] for item in blocked["blockers"]],
            [f"PZCLOSURE{index:03d}" for index in range(1, 31)],
        )

    def test_translation_closure_requires_every_contract_to_pass(self) -> None:
        complete = translator.translation_closure_contract(
            pending=[],
            sprite_working_sets={"ready": True, "status": "READY"},
            frame_record_bound={
                "proof_complete": True,
                "can_certify_frame_budget": True,
                "status": "CERTIFIED",
                "certified_frame_max_records": 228,
                "bound_kind": "conservative_upper_bound",
                "exact_max_records": None,
            },
            frame_sprite_fragment_envelope={
                "status": "LIVE",
                "proof_complete": True,
                "live_eligible": True,
                "blockers": [],
            },
            frame_render_plan={
                "live_target_lowering_present": True,
                "status": "LIVE",
            },
            frame_budget={
                "status": "PASS",
                "full_frame_proved": True,
                "live_target_lowering_present": False,
            },
            frame_budget_live_hook={
                "status": "LIVE",
                "present": True,
            },
            render_order_backend={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_hooks_present": True,
                },
            },
            draw_vm_backend={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_performance_and_size_certified": True,
                },
            },
            draw_state_backend={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_hooks_present": True,
                },
            },
            draw_fast_pipeline={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_performance_size_stack_certified": True,
                },
            },
            draw_target_bundle={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            draw_bank_placement={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            mutation_hook_ir={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            object_store_ir={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            function_cfg_ir={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            active_call_graph={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            active_call_site_lowering={
                "status": "ACTIVE_CALL_SITE_LOWERING_PLANNED_LIVE_BLOCKED",
                "live": False,
                "semantic_sha256": "lowering-semantic",
                "proof": {"backend_consumer_bound": False},
                "live_blockers": [{"code": "PZCSL210"}],
            },
            whole_program_vm_call_abi={
                "status": "WHOLE_PROGRAM_VM_CALL_ABI_PLANNED_LIVE_BLOCKED",
                "live": False,
                "semantic_sha256": "call-abi-semantic",
                "proof": {"current_vm_backend_consumes_call_abi": False},
                "live_blockers": [{"code": "PZCABI213"}],
            },
            active_target_adapters={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            frame_timing_provider={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            draw_ramdl_shadow_v4={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            whole_program_vm={
                "format": "LIVE",
                "live": True,
                "live_blockers": [],
                "execution_contract": {
                    "call_abi_consumer_enabled": True,
                    "call_abi_occurrences_bound_by_exact_cfg_path": True,
                    "call_abi_only_replaces_invocation": True,
                    "python_call_adapters_are_call_site_specific": True,
                },
                "call_abi_binding": {
                    "enabled": True,
                    "occurrences_bound_by_exact_cfg_path": True,
                    "active_call_site_lowering_semantic_sha256":
                        "lowering-semantic",
                    "whole_program_vm_call_abi_semantic_sha256":
                        "call-abi-semantic",
                },
            },
            whole_program_vm_stack_bound={
                "format": "LIVE",
                "complete_bound_proved": True,
                "live": True,
                "live_blockers": [],
            },
            full_hqt3_inventory={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            hqt3_ramg_schedule={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            hqt3_partition_solver={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            hqt3_frame_page_solver={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            gameplay_backend={"status": "translated-live-certified"},
            sprite_backend={"status": "translated-live-certified"},
        )
        self.assertTrue(complete["complete"])
        self.assertEqual(complete["blocker_count"], 0)
        self.assertEqual(complete["blockers"], [])

    def test_vm_call_consumer_rejects_resigned_input_mismatch(self) -> None:
        lowering = {"semantic_sha256": "lowering-semantic"}
        call_abi = {"semantic_sha256": "call-abi-semantic"}
        vm = {
            "execution_contract": {
                "call_abi_consumer_enabled": True,
                "call_abi_occurrences_bound_by_exact_cfg_path": True,
                "call_abi_only_replaces_invocation": True,
                "python_call_adapters_are_call_site_specific": True,
            },
            "call_abi_binding": {
                "enabled": True,
                "occurrences_bound_by_exact_cfg_path": True,
                "active_call_site_lowering_semantic_sha256":
                    "lowering-semantic",
                "whole_program_vm_call_abi_semantic_sha256":
                    "call-abi-semantic",
            },
        }
        self.assertTrue(translator.whole_program_vm_consumes_call_abi(
            vm, lowering, call_abi))

        vm["call_abi_binding"][
            "active_call_site_lowering_semantic_sha256"] = "resigned-forgery"
        self.assertFalse(
            translator.whole_program_vm_consumes_call_site_lowering(
                vm, lowering))
        vm["call_abi_binding"][
            "active_call_site_lowering_semantic_sha256"] = "lowering-semantic"
        vm["call_abi_binding"][
            "whole_program_vm_call_abi_semantic_sha256"] = "resigned-forgery"
        self.assertFalse(translator.whole_program_vm_consumes_call_abi(
            vm, lowering, call_abi))

    def test_budget_pass_without_live_prepublication_hook_is_incomplete(
            self) -> None:
        closure = translator.translation_closure_contract(
            pending=[],
            sprite_working_sets={"ready": True, "status": "READY"},
            frame_record_bound={
                "proof_complete": True,
                "can_certify_frame_budget": True,
                "status": "CERTIFIED",
                "certified_frame_max_records": 228,
                "bound_kind": "conservative_upper_bound",
                "exact_max_records": None,
            },
            frame_sprite_fragment_envelope={
                "status": "LIVE",
                "proof_complete": True,
                "live_eligible": True,
                "blockers": [],
            },
            frame_render_plan={
                "live_target_lowering_present": True,
                "status": "LIVE",
            },
            frame_budget={
                "status": "PASS",
                "full_frame_proved": True,
                "live_target_lowering_present": False,
            },
            frame_budget_live_hook={
                "status": "BLOCKED",
                "present": False,
                "blockers": ["prepublication not proved"],
            },
            render_order_backend={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_hooks_present": True,
                },
            },
            draw_vm_backend={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_performance_and_size_certified": True,
                },
            },
            draw_state_backend={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_hooks_present": True,
                },
            },
            draw_fast_pipeline={
                "status": "LIVE",
                "compile_manifest_integration": {
                    "live_target_performance_size_stack_certified": True,
                },
            },
            draw_target_bundle={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            draw_bank_placement={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            mutation_hook_ir={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            object_store_ir={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            function_cfg_ir={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            active_call_graph={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            active_call_site_lowering={
                "status": "LIVE",
                "live": True,
                "semantic_sha256": "lowering-test-sha",
                "proof": {"backend_consumer_bound": True},
                "live_blockers": [],
            },
            whole_program_vm_call_abi={
                "status": "LIVE",
                "live": True,
                "semantic_sha256": "call-abi-test-sha",
                "proof": {"current_vm_backend_consumes_call_abi": True},
                "live_blockers": [],
            },
            active_target_adapters={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            frame_timing_provider={
                "status": "LIVE",
                "live": True,
                "live_blockers": [],
            },
            draw_ramdl_shadow_v4={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            whole_program_vm={
                "format": "LIVE",
                "live": True,
                "live_blockers": [],
                "execution_contract": {
                    "call_abi_consumer_enabled": True,
                    "call_abi_occurrences_bound_by_exact_cfg_path": True,
                    "python_call_adapters_are_call_site_specific": True,
                    "call_abi_only_replaces_invocation": True,
                },
                "call_abi_binding": {
                    "enabled": True,
                    "occurrences_bound_by_exact_cfg_path": True,
                    "active_call_site_lowering_semantic_sha256":
                        "lowering-test-sha",
                    "whole_program_vm_call_abi_semantic_sha256":
                        "call-abi-test-sha",
                },
            },
            whole_program_vm_stack_bound={
                "format": "LIVE",
                "complete_bound_proved": True,
                "live": True,
                "live_blockers": [],
            },
            full_hqt3_inventory={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            hqt3_ramg_schedule={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            hqt3_partition_solver={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            hqt3_frame_page_solver={
                "status": "LIVE",
                "live": True,
                "blockers": [],
            },
            gameplay_backend={"status": "translated-live-certified"},
            sprite_backend={"status": "translated-live-certified"},
        )
        self.assertFalse(closure["complete"])
        self.assertEqual(
            [item["code"] for item in closure["blockers"]],
            ["PZCLOSURE011"])

    @staticmethod
    def _draw_target_bundle_fixture() -> dict[str, object]:
        proved = {
            name: True for name in (
                "active_launcher_is_rtype_port_app",
                "active_python_backends_regenerated_byte_exact",
                "active_source_and_semantic_hashes_cross_bound",
                "actual_link_completed",
                "all_bundle_objects_compiled_together_with_pinned_sdcc",
                "direct_symbol_references_resolved",
                "duplicate_global_symbols_absent",
                "frame_budget_v4_status_hash_bound",
                "ft812_dependency_slice_exact_source_spans",
                "headers_and_cross_object_abis_compile_together",
                "hqt3_asset_manifest_binding_exact",
                "hqt3_dependency_slice_only_reachable_tables",
                "known_stack_paths_assembly_proved",
                "linked_code_and_data_measured_from_map",
            )
        }
        proved.update({
            "single_16k_code_bank_fit": False,
            "code_data_ranges_do_not_overlap": False,
            "cross_bank_link_adapter_proved": False,
            "complete_external_callback_stack_bound": False,
        })
        return {
            "format": translator.DRAW_TARGET_BUNDLE_FORMAT,
            "status": translator.DRAW_TARGET_BUNDLE_STATUS,
            "checks": proved,
            "link": {
                "code": {
                    "bytes": 17137,
                    "bank_bytes": 16384,
                    "banks_required": 2,
                    "fits_one_bank": False,
                    "single_bank_overflow_bytes": 753,
                },
                "data": {
                    "bytes": 1280,
                    "expected_private_fast_cache_bytes": 1280,
                },
                "placement": {
                    "code_data_overlap": True,
                    "cross_bank_link_adapter_proved": False,
                },
            },
            "stack": {
                "maximum_known_candidate_bytes": 245,
                "target_stack_budget_bytes": 992,
                "known_candidate_headroom_bytes": 747,
                "complete_bound_certified": False,
            },
            "frame_publication_contract": {
                "required_contract_format":
                    translator.FRAME_BUDGET_CONTRACT_FORMAT,
                "required": {
                    "complete_record_count_preflight": True,
                    "complete_template_lookup_preflight": True,
                    "complete_append_budget_preflight": True,
                    "no_queue_fragment_ready_before_preflight": True,
                    "atomic_complete_frame_commit": True,
                },
            },
            "live": False,
            "live_blockers": [{"code": "PZTB001", "detail": "blocked"}],
        }

    def test_draw_target_bundle_contract_validates_one_link_report(self) -> None:
        fixture = self._draw_target_bundle_fixture()
        with mock.patch.object(
                translator, "probe_draw_target_bundle",
                return_value=fixture) as probe:
            result = translator.draw_target_bundle_contract(translator.ROOT)
        probe.assert_called_once_with(translator.ROOT)
        self.assertIs(result, fixture)

    def test_draw_target_bundle_rejects_inconsistent_bank_count(self) -> None:
        fixture = self._draw_target_bundle_fixture()
        fixture["link"]["code"]["banks_required"] = 1
        with self.assertRaisesRegex(
                translator.TranslationError, "bank arithmetic"):
            translator.validate_draw_target_bundle_certificate(fixture)

    @staticmethod
    def _draw_bank_placement_fixtures() -> tuple[
            dict[str, object], dict[str, object]]:
        placement = json.loads(
            translator.OUT_DRAW_BANK_PLACEMENT_STATUS.read_text(
                encoding="utf-8"))
        bundle = json.loads(
            translator.OUT_DRAW_TARGET_BUNDLE_STATUS.read_text(
                encoding="utf-8"))
        return placement, bundle

    def test_draw_bank_placement_validates_two_real_links(self) -> None:
        placement, bundle = self._draw_bank_placement_fixtures()
        with mock.patch.object(
                translator, "probe_draw_bank_placement",
                return_value=placement) as probe:
            result = translator.draw_bank_placement_contract(
                bundle, translator.ROOT)
        probe.assert_called_once_with(translator.ROOT)
        self.assertIs(result, placement)
        self.assertEqual(
            result["memory"]["draw_code_banks"][0]["page_hex"], "0xF1")
        self.assertEqual(
            result["memory"]["draw_code_banks"][1]["page_hex"], "0xF2")

    def test_draw_bank_placement_rejects_link_overflow(self) -> None:
        placement, bundle = self._draw_bank_placement_fixtures()
        placement["links"]["page_f2"]["code"]["bytes"] = 0x4001
        with self.assertRaisesRegex(
                translator.TranslationError, "does not fit"):
            translator.validate_draw_bank_placement_certificate(
                placement, bundle)

    def test_mutation_hook_ir_is_bound_to_draw_state_sidecar(self) -> None:
        report = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(
                encoding="utf-8"))
        source = report["source"]
        state = {
            "semantic_sha256":
                report["pinned_draw_state_semantic_sha256"],
            "active_source": {
                "launcher": source["launcher"],
                "entrypoint": source["entrypoint"],
                "launcher_sha256": source["launcher_sha256"],
                "module": source["path"],
                "module_sha256": source["sha256"],
            },
            "persistent_state": {
                "slot_count": report["slot_normalization"]["slot_count"],
            },
        }
        self.assertIs(
            translator.validate_mutation_hook_ir(report, state), report)

    def test_mutation_hook_ir_rejects_missing_lowered_write(self) -> None:
        report = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(
                encoding="utf-8"))
        source = report["source"]
        state = {
            "semantic_sha256":
                report["pinned_draw_state_semantic_sha256"],
            "active_source": {
                "launcher": source["launcher"],
                "entrypoint": source["entrypoint"],
                "launcher_sha256": source["launcher_sha256"],
                "module": source["path"],
                "module_sha256": source["sha256"],
            },
            "persistent_state": {
                "slot_count": report["slot_normalization"]["slot_count"],
            },
        }
        report["coverage"]["counts"]["direct_and_implicit_lowered"] -= 1
        with self.assertRaisesRegex(
                translator.TranslationError, "coverage counts"):
            translator.validate_mutation_hook_ir(report, state)

    def test_object_store_ir_covers_each_runtime_mutation(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(
                encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(
                encoding="utf-8"))
        self.assertIs(
            translator.validate_object_store_ir(stores, hooks), stores)
        self.assertEqual(
            stores["coverage"]["runtime_hook_fragments"], 364)

    def test_object_store_ir_rejects_missing_fragment(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(
                encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(
                encoding="utf-8"))
        stores["fragments"].pop()
        with self.assertRaisesRegex(
                translator.TranslationError,
                "cover each mutation hook exactly once"):
            translator.validate_object_store_ir(stores, hooks)

    def test_object_store_ir_rejects_opaque_expression_fallback(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(
                encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(
                encoding="utf-8"))
        execute = next(
            item for item in stores["fragments"][0]["instructions"]
            if item["op"] == "execute-expression-cfg")
        execute["op"] = "eval-expression"
        with self.assertRaisesRegex(
                translator.TranslationError, "exactly one non-opaque"):
            translator.validate_object_store_ir(stores, hooks)

    def test_object_store_ir_rejects_corrupt_expression_hash(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(
                encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(
                encoding="utf-8"))
        expression = stores["fragments"][0]["expression"]
        expression["semantic_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError, "semantic hash"):
            translator.validate_object_store_ir(stores, hooks)

    def test_active_function_cfg_is_complete_and_bound_to_store_ir(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(encoding="utf-8"))
        functions = json.loads(
            translator.OUT_FUNCTION_CFG_STATUS.read_text(encoding="utf-8"))
        self.assertIs(
            translator.validate_function_cfg_ir(
                functions, hooks, stores, translator.ROOT), functions)
        self.assertTrue(
            functions["coverage"]["full_function_cfg_lowered"])
        self.assertEqual(functions["coverage"]["unsupported_count"], 0)
        self.assertEqual(
            functions["coverage"]["spliced_store_fragment_count"], 364)

    def test_active_function_cfg_rejects_corrupt_function_semantic(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(encoding="utf-8"))
        functions = json.loads(
            translator.OUT_FUNCTION_CFG_STATUS.read_text(encoding="utf-8"))
        functions["functions"][0]["semantic_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError, "function semantic hash"):
            translator.validate_function_cfg_ir(
                functions, hooks, stores, translator.ROOT)

    def test_active_call_graph_defines_reachable_pending_closure(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(encoding="utf-8"))
        graph = json.loads(
            translator.OUT_ACTIVE_CALL_GRAPH_STATUS.read_text(encoding="utf-8"))
        self.assertIs(
            translator.validate_active_call_graph(
                graph, hooks, stores, translator.ROOT), graph)
        callable_count = graph["callable_inventory"]["callable_count"]
        reachable_ids = graph["call_graph"][
            "proven_reachable_callable_ids"]
        self.assertEqual(
            callable_count,
            len(graph["callable_inventory"]["callables"]))
        self.assertEqual(
            graph["callable_inventory"]["cfg_lowered_callable_count"],
            callable_count)
        self.assertEqual(
            graph["call_graph"]["proven_reachable_callable_count"],
            len(reachable_ids))
        self.assertEqual(
            graph["call_graph"]["not_proven_reachable_callable_count"],
            callable_count - len(reachable_ids))
        self.assertEqual(
            graph["module_initialization"]["call_site_count"],
            len(graph["module_initialization"]["call_sites"]))
        translated = {
            spec.symbol: "translated_lut" for spec in translator.TABLE_SPECS}
        translated.update({
            spec.symbol: "translated_lut"
            for spec in translator.CONSTANT_TABLE_SPECS})
        translated.update({
            spec.symbol: "compiled_z80"
            for spec in CompilerManifest.load(
                translator.PYZ80_MANIFEST).functions})
        pending = translator.active_reachable_pending_symbols(graph, translated)
        self.assertLessEqual(len(pending), len(reachable_ids))
        self.assertTrue(all(item["callable_id"] in
                            graph["call_graph"]
                            ["proven_reachable_callable_ids"]
                            for item in pending))

    def test_active_call_graph_rejects_corrupt_semantic_hash(self) -> None:
        hooks = json.loads(
            translator.OUT_MUTATION_HOOK_IR_STATUS.read_text(encoding="utf-8"))
        stores = json.loads(
            translator.OUT_OBJECT_STORE_IR_STATUS.read_text(encoding="utf-8"))
        graph = json.loads(
            translator.OUT_ACTIVE_CALL_GRAPH_STATUS.read_text(encoding="utf-8"))
        graph["semantic_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError, "active call graph failed"):
            translator.validate_active_call_graph(
                graph, hooks, stores, translator.ROOT)

    def test_active_call_site_lowering_is_atomic_bound_and_tamper_aware(
            self) -> None:
        graph = translator.analyze_active_call_graph(translator.ROOT)
        report = translator.active_call_site_lowering_contract(
            graph, translator.ROOT)
        mapping = report["mapping"]
        self.assertEqual(
            report["active_call_graph_semantic_sha256"],
            graph["semantic_sha256"])
        self.assertEqual(
            mapping["reachable_callable_count"],
            len(graph["call_graph"]["proven_reachable_callable_ids"]))
        self.assertEqual(
            mapping["represented_graph_call_site_count"] +
            mapping["unrepresented_graph_call_site_count"],
            mapping["reachable_graph_call_site_count"])
        self.assertEqual(mapping["missing_cfg_to_graph_match_count"], 0)
        self.assertEqual(mapping["ambiguous_cfg_to_graph_match_count"], 0)
        self.assertFalse(report["proof"]["backend_consumer_bound"])
        self.assertFalse(report["live"])
        self.assertIn(
            "PZCSL210",
            [row["code"] for row in report["live_blockers"]])
        self.assertEqual(
            json.loads(
                translator.OUT_ACTIVE_CALL_SITE_LOWERING_STATUS.read_text(
                    encoding="utf-8")), report)

        tampered = json.loads(json.dumps(report))
        tampered["semantic_sha256"] = "0" * 64
        with self.assertRaises(translator.ActiveCallSiteLoweringError):
            translator.validate_active_call_site_lowering_report(
                translator.ROOT, tampered, active_graph=graph)

    def test_whole_program_vm_call_abi_reuses_lowering_and_rejects_tamper(
            self) -> None:
        graph = translator.analyze_active_call_graph(translator.ROOT)
        lowering = json.loads(
            translator.OUT_ACTIVE_CALL_SITE_LOWERING_STATUS.read_text(
                encoding="utf-8"))
        self.assertEqual(
            lowering["active_call_graph_semantic_sha256"],
            graph["semantic_sha256"])
        report = translator.whole_program_vm_call_abi_contract(
            graph, lowering, translator.ROOT)
        census = report["census"]
        self.assertEqual(
            report["call_site_lowering_semantic_sha256"],
            lowering["semantic_sha256"])
        self.assertEqual(
            census["represented_call_site_count"],
            lowering["mapping"]["represented_graph_call_site_count"])
        self.assertEqual(
            census["call_occurrence_descriptor_count"],
            lowering["mapping"]["cfg_python_call_occurrence_count"])
        self.assertEqual(
            census["exact_callable_ssa_provenance_count"] +
            census["ambiguous_callable_ssa_provenance_count"],
            census["call_occurrence_descriptor_count"])
        self.assertFalse(
            report["proof"]["current_vm_backend_consumes_call_abi"])
        self.assertFalse(report["live"])
        self.assertIn(
            "PZCABI213",
            [row["code"] for row in report["live_blockers"]])
        self.assertEqual(
            json.loads(
                translator.OUT_WHOLE_PROGRAM_VM_CALL_ABI_STATUS.read_text(
                    encoding="utf-8")), report)

        tampered = json.loads(json.dumps(report))
        tampered["semantic_sha256"] = "0" * 64
        with self.assertRaises(translator.WholeProgramVMCallABIError):
            translator.validate_whole_program_vm_call_abi_report(
                translator.ROOT, tampered, active_graph=graph,
                call_site_lowering=lowering)

    def test_active_target_adapters_bind_exact_active_graph(self) -> None:
        graph = json.loads(
            translator.OUT_ACTIVE_CALL_GRAPH_STATUS.read_text(encoding="utf-8"))
        adapters = json.loads(
            translator.OUT_ACTIVE_TARGET_ADAPTERS_STATUS.read_text(
                encoding="utf-8"))
        self.assertIs(
            translator.validate_active_target_adapters(
                adapters, graph, translator.ROOT), adapters)
        self.assertEqual(
            adapters["inventory"]["runtime"]["input_host_boundary_count"],
            graph["call_graph"]["reachable_host_boundary_call_site_count"])
        self.assertEqual(
            adapters["inventory"]["runtime"]["input_unresolved_count"],
            graph["call_graph"]["reachable_unresolved_call_site_count"])
        self.assertFalse(adapters["live"])

    def test_active_target_adapters_reject_tampered_semantic_hash(self) -> None:
        graph = json.loads(
            translator.OUT_ACTIVE_CALL_GRAPH_STATUS.read_text(encoding="utf-8"))
        adapters = json.loads(
            translator.OUT_ACTIVE_TARGET_ADAPTERS_STATUS.read_text(
                encoding="utf-8"))
        adapters["semantic_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError, "active target adapters failed"):
            translator.validate_active_target_adapters(
                adapters, graph, translator.ROOT)

    def test_frame_timing_provider_binds_active_python_and_adapters(self) -> None:
        timing = json.loads(
            translator.OUT_FRAME_TIMING_PROVIDER_STATUS.read_text(
                encoding="utf-8"))
        translator.validate_frame_timing_provider_report(
            translator.ROOT, timing, validate_artifacts=True)
        contract = timing["contract"]
        self.assertEqual(
            contract["source_rates"]["python_application_hz"]["numerator"],
            55)
        self.assertEqual(
            contract["selected_profile"]["registers"]["FT_REG_VCYCLE"],
            866)
        self.assertEqual(
            contract["scanline_budget"]["practical_cycle_limit_floor"],
            1209)
        self.assertFalse(timing["live"])

    def test_frame_timing_provider_rejects_tampered_semantic_hash(self) -> None:
        timing = json.loads(
            translator.OUT_FRAME_TIMING_PROVIDER_STATUS.read_text(
                encoding="utf-8"))
        timing["semantic_sha256"] = "0" * 64
        with self.assertRaises(translator.FrameTimingProviderError):
            translator.validate_frame_timing_provider_report(
                translator.ROOT, timing, validate_artifacts=True)

    def test_draw_ramdl_shadow_v4_report_is_bound_and_fail_closed(self) -> None:
        report = json.loads(
            translator.OUT_DRAW_RAMDL_SHADOW_V4_STATUS.read_text(
                encoding="utf-8"))
        validated = translator.validate_draw_ramdl_shadow_v4_report(
            translator.ROOT, report)
        self.assertEqual(validated["status"], "valid")
        self.assertEqual(
            report["layout"]["active_catalog_cyclic_words"], 1934)
        self.assertTrue(report["layout"]["boundary_2047"]["passes"])
        self.assertFalse(report["layout"]["boundary_2048"]["passes"])
        self.assertEqual(
            report["allocation"]["target_struct_sizes_bytes"]
            ["dedup_scratch"], 1830)
        self.assertFalse(report["live"])

    def test_draw_ramdl_shadow_v4_rejects_tampered_analysis_seal(self) -> None:
        report = json.loads(
            translator.OUT_DRAW_RAMDL_SHADOW_V4_STATUS.read_text(
                encoding="utf-8"))
        report["analysis_sha256"] = "0" * 64
        with self.assertRaises(translator.V4CheckError):
            translator.validate_draw_ramdl_shadow_v4_report(
                translator.ROOT, report)

    def test_whole_program_vm_encodes_every_proven_reachable_callable(
            self) -> None:
        graph = json.loads(
            translator.OUT_ACTIVE_CALL_GRAPH_STATUS.read_text(
                encoding="utf-8"))
        lowering = json.loads(
            translator.OUT_ACTIVE_CALL_SITE_LOWERING_STATUS.read_text(
                encoding="utf-8"))
        call_abi = json.loads(
            translator.OUT_WHOLE_PROGRAM_VM_CALL_ABI_STATUS.read_text(
                encoding="utf-8"))
        # Exercise the main-flow in-memory form: analyzer reports may retain
        # tuple containers although the signed form is JSON.
        graph["call_graph"]["proven_reachable_callable_ids"] = tuple(
            graph["call_graph"]["proven_reachable_callable_ids"])
        temporary = tempfile.TemporaryDirectory(
            prefix="rtype-translator-vm-abi-")
        self.addCleanup(temporary.cleanup)
        output_root = Path(temporary.name)
        for relative in (
                "Source/C/python_vm/pyz80_whole_program_vm.h",
                "Source/C/python_vm/pyz80_whole_program_vm.c"):
            source = translator.ROOT / relative
            target = output_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        (output_root / "Build").mkdir(parents=True, exist_ok=True)

        artifact, status, stack_bound = translator.whole_program_vm_contract(
            graph, lowering, call_abi, output_root)
        reachable = list(
            graph["call_graph"]["proven_reachable_callable_ids"])
        guarded = list(artifact.document.get("guarded_callable_ids", []))
        serialized = [*reachable, *guarded]
        self.assertEqual(
            status["proof_coverage"]["function_count"], len(serialized))
        self.assertEqual(
            status["target_coverage"]["function_count"], len(serialized))
        self.assertEqual(
            status["target_coverage"]["proven_reachable_function_count"],
            len(reachable))
        self.assertEqual(
            status["target_coverage"]["guarded_callable_function_count"],
            len(guarded))
        self.assertEqual(
            status["active_call_graph_semantic_sha256"],
            graph["semantic_sha256"])
        self.assertEqual(
            hashlib.sha256((
                output_root / "Build/rtype_python_whole_program_vm.bin")
                .read_bytes())
            .hexdigest(), status["target_bytecode"]["sha256"])
        self.assertEqual(
            hashlib.sha256(
                (output_root /
                 "Build/rtype_python_whole_program_vm_proof.bin")
                .read_bytes())
            .hexdigest(), status["host_proof"]["sha256"])
        self.assertEqual(
            (output_root / "Build/rtype_python_whole_program_vm.bin")
            .read_bytes()[:4], b"PZVT")
        self.assertEqual(
            (output_root / "Build/rtype_python_whole_program_vm_proof.bin")
            .read_bytes()[:4],
            b"PZVM")
        decoded = translator.decode_whole_program_vm(
            artifact.proof_bytecode)
        self.assertEqual(
            [item["callable_id"] for item in decoded["functions"]],
            serialized)
        compact = translator.decode_compact_target_vm(
            artifact.target_bytecode,
            expected_proof_semantic_sha256=artifact.semantic_sha256)
        self.assertEqual(len(compact["functions"]), len(serialized))
        self.assertEqual(
            [item["code"] for item in status["live_blockers"]],
            [f"PZWVLIVE{index:03d}" for index in range(1, 6)])
        self.assertIn(
            "PZWVLIVE005",
            [item["code"] for item in status["live_blockers"]])
        binding = status["call_abi_binding"]
        coverage = status["target_coverage"]
        execution = status["execution_contract"]
        self.assertTrue(binding["enabled"])
        self.assertTrue(binding["occurrences_bound_by_exact_cfg_path"])
        self.assertEqual(
            binding["active_call_site_lowering_semantic_sha256"],
            lowering["semantic_sha256"])
        self.assertEqual(
            binding["whole_program_vm_call_abi_semantic_sha256"],
            call_abi["semantic_sha256"])
        self.assertEqual(
            artifact.document[
                "active_call_site_lowering_semantic_sha256"],
            lowering["semantic_sha256"])
        self.assertEqual(
            artifact.document["whole_program_vm_call_abi_semantic_sha256"],
            call_abi["semantic_sha256"])
        self.assertTrue(execution[
            "call_abi_occurrences_bound_by_exact_cfg_path"])
        self.assertTrue(execution["call_abi_only_replaces_invocation"])
        self.assertEqual(
            coverage["abi_eligible_call_instruction_count"],
            coverage["abi_lowered_call_instruction_count"])
        self.assertGreater(
            coverage["abi_lowered_call_instruction_count"],
            binding["legacy_direct_call_instruction_count"])
        self.assertGreater(
            coverage["abi_lowered_call_site_count"],
            binding["legacy_direct_call_site_count"])
        self.assertGreater(
            coverage["abi_unlowered_call_instruction_count"], 0)
        self.assertGreater(coverage["abi_unlowered_call_site_count"], 0)
        self.assertFalse(
            coverage["active_interprocedural_execution_closed"])
        self.assertEqual(
            translator.validate_whole_program_vm_stack_bound_report(
                artifact, json.loads(json.dumps(graph)), stack_bound,
                project_root=output_root),
            stack_bound)
        self.assertEqual(
            json.loads(
                (output_root / "Build" /
                 "rtype_python_whole_program_vm_stack_bound_status.json")
                .read_text(encoding="utf-8")), stack_bound)
        self.assertEqual(
            json.loads((output_root / "Build" /
                        "rtype_python_whole_program_vm_status.json")
                       .read_text(encoding="utf-8")), status)
        self.assertFalse(stack_bound["complete_bound_proved"])
        self.assertFalse(stack_bound["live"])
        self.assertTrue(stack_bound["live_blockers"])
        self.assertFalse(status["live"])

        damaged = bytearray(artifact.target_bytecode)
        damaged[-1] ^= 0x80
        with self.assertRaises(translator.WholeProgramVMError):
            translator.decode_compact_target_vm(bytes(damaged))

        owned = tuple(output_root / "Build" / name for name in (
            "rtype_python_whole_program_vm.bin",
            "rtype_python_whole_program_vm_proof.bin",
            "rtype_python_whole_program_vm_status.json",
            "rtype_python_whole_program_vm_stack_bound_status.json",
        ))
        before = {path: path.read_bytes() for path in owned}
        semantic_tamper = json.loads(json.dumps(call_abi))
        semantic_tamper["semantic_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError,
                "whole-program VM lowering failed"):
            translator.whole_program_vm_contract(
                graph, lowering, semantic_tamper, output_root)
        self.assertEqual(before, {path: path.read_bytes() for path in owned})

        path_tamper = json.loads(json.dumps(lowering))
        path_tamper["cfg_occurrences_in_cfg_order"][0]["cfg_path"][-1] = (
            1 << 30)
        path_tamper["semantic_sha256"] = hashlib.sha256(json.dumps(
            {key: value for key, value in path_tamper.items()
             if key != "semantic_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        path_abi = json.loads(json.dumps(call_abi))
        path_abi["call_site_lowering_semantic_sha256"] = path_tamper[
            "semantic_sha256"]
        path_abi["semantic_sha256"] = hashlib.sha256(json.dumps(
            {key: value for key, value in path_abi.items()
             if key != "semantic_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(
                translator.TranslationError, "PZWV264"):
            translator.whole_program_vm_contract(
                graph, path_tamper, path_abi, output_root)
        self.assertEqual(before, {path: path.read_bytes() for path in owned})

    def test_whole_program_vm_rejects_tampered_graph_semantic_hash(self) -> None:
        graph = json.loads(
            translator.OUT_ACTIVE_CALL_GRAPH_STATUS.read_text(encoding="utf-8"))
        graph["semantic_sha256"] = "0" * 64
        with self.assertRaises(translator.WholeProgramVMError):
            translator.build_whole_program_vm(graph)

    def test_translation_report_uses_proven_reachable_pending_only(self) -> None:
        report = json.loads(
            translator.OUT_REPORT.read_text(encoding="utf-8"))
        graph = report["active_call_graph"]
        self.assertEqual(
            report["coverage"]["pending"],
            graph["reachable_pending_count"])
        self.assertGreaterEqual(
            report["coverage"]["imported_pending_diagnostic"],
            report["coverage"]["pending"])
        self.assertEqual(
            report["coverage"]["pending_definition"],
            "source-proven reachable active Python callables only")
        self.assertIsInstance(graph["reachable_pending_count"], int)
        self.assertEqual(
            graph["call_graph"]["proven_reachable_callable_count"] +
            graph["call_graph"]["not_proven_reachable_callable_count"],
            graph["callable_inventory"]["callable_count"])
        self.assertIn(
            "PZCLOSURE022",
            [item["code"] for item in
             report["translation_closure"]["blockers"]])

    def test_full_hqt3_inventory_binds_current_envelope_without_residency_claim(
            self) -> None:
        inventory = json.loads(
            translator.OUT_FULL_HQT3_INVENTORY_STATUS.read_text(
                encoding="utf-8"))
        envelope = json.loads(
            translator.OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS.read_text(
                encoding="utf-8"))
        source = inventory["source_binding"]
        coverage = SimpleNamespace(
            root_module=source["root_module"],
            rom_sha256=source["rom_sha256"],
            source_hashes=tuple(sorted(
                source["coverage_source_hashes"].items())),
        )
        self.assertIs(
            translator.validate_full_hqt3_inventory(
                inventory, coverage, envelope, translator.ROOT), inventory)
        self.assertEqual(
            inventory["load_plan"]["resident_combinations"], [])
        self.assertTrue(
            inventory["frame_sprite_fragment_envelope_crosscheck"]
            ["missing_current_identities_present_in_full_catalog"])

    def test_hqt3_ramg_schedule_binds_full_inventory_without_residency_claim(
            self) -> None:
        inventory = json.loads(
            translator.OUT_FULL_HQT3_INVENTORY_STATUS.read_text(
                encoding="utf-8"))
        schedule = json.loads(
            translator.OUT_HQT3_RAMG_SCHEDULE_STATUS.read_text(
                encoding="utf-8"))
        self.assertIs(
            translator.validate_hqt3_ramg_schedule(
                schedule, inventory, translator.ROOT), schedule)
        census = schedule["scope_pack_census"]
        self.assertEqual(census["scope_count"], 174)
        self.assertEqual(census["ram_g_isolated_fit_count"], 171)
        self.assertEqual(census["ram_g_isolated_nonfit_count"], 3)
        self.assertEqual(schedule["resident_combinations"], [])
        self.assertFalse(schedule["whole_inventory_resident"])

    def test_hqt3_ramg_schedule_rejects_stale_inventory_binding(self) -> None:
        inventory = json.loads(
            translator.OUT_FULL_HQT3_INVENTORY_STATUS.read_text(
                encoding="utf-8"))
        schedule = json.loads(
            translator.OUT_HQT3_RAMG_SCHEDULE_STATUS.read_text(
                encoding="utf-8"))
        schedule["inventory_binding"]["analysis_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError,
                "HQT3/RAM_G schedule failed|stale against"):
            translator.validate_hqt3_ramg_schedule(
                schedule, inventory, translator.ROOT)

    def test_hqt3_partition_solver_binds_both_physical_inputs(self) -> None:
        inventory = json.loads(
            translator.OUT_FULL_HQT3_INVENTORY_STATUS.read_text(
                encoding="utf-8"))
        schedule = json.loads(
            translator.OUT_HQT3_RAMG_SCHEDULE_STATUS.read_text(
                encoding="utf-8"))
        partitions = json.loads(
            translator.OUT_HQT3_PARTITION_SOLVER_STATUS.read_text(
                encoding="utf-8"))
        self.assertIs(
            translator.validate_hqt3_partition_solver(
                partitions, inventory, schedule, translator.ROOT), partitions)
        self.assertTrue(partitions["structural_partition_proof_complete"])
        self.assertFalse(partitions["ram_g_runtime_paging_complete"])
        self.assertEqual(partitions["event_cost_census"]["exact_event_count"], 125)
        self.assertEqual(
            partitions["event_cost_census"]["ambiguous_event_count"], 663)
        self.assertEqual(partitions["resident_combinations"], [])
        self.assertEqual(partitions["eviction_inferences"], [])

    def test_hqt3_partition_solver_rejects_stale_schedule_binding(self) -> None:
        inventory = json.loads(
            translator.OUT_FULL_HQT3_INVENTORY_STATUS.read_text(
                encoding="utf-8"))
        schedule = json.loads(
            translator.OUT_HQT3_RAMG_SCHEDULE_STATUS.read_text(
                encoding="utf-8"))
        partitions = json.loads(
            translator.OUT_HQT3_PARTITION_SOLVER_STATUS.read_text(
                encoding="utf-8"))
        partitions["input_binding"]["schedule_analysis_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                translator.TranslationError,
                "HQT3 partition solver failed|stale against"):
            translator.validate_hqt3_partition_solver(
                partitions, inventory, schedule, translator.ROOT)

    def test_hqt3_frame_page_solver_binds_frame_and_physical_inputs(
            self) -> None:
        load = lambda path: json.loads(path.read_text(encoding="utf-8"))
        inventory = load(translator.OUT_FULL_HQT3_INVENTORY_STATUS)
        schedule = load(translator.OUT_HQT3_RAMG_SCHEDULE_STATUS)
        partitions = load(translator.OUT_HQT3_PARTITION_SOLVER_STATUS)
        bound = load(translator.OUT_FRAME_RECORD_BOUND_STATUS)
        envelope = load(translator.OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS)
        graph = load(translator.OUT_ACTIVE_CALL_GRAPH_STATUS)
        pages = load(translator.OUT_HQT3_FRAME_PAGE_SOLVER_STATUS)
        self.assertIs(
            translator.validate_hqt3_frame_page_solver(
                pages, inventory, schedule, partitions, bound, envelope,
                graph, translator.ROOT), pages)
        self.assertEqual(
            pages["exact_bcab_page_catalog"]["union_ram_g_bytes"],
            1_263_796)
        self.assertEqual(
            pages["exact_bcab_page_catalog"]["union_ram_g_overflow_bytes"],
            215_220)
        self.assertFalse(
            pages["double_buffer_capacity"]["strict_fit_proved"])
        self.assertEqual(pages["resident_combinations"], [])
        self.assertEqual(pages["eviction_inferences"], [])

    def test_hqt3_frame_page_solver_rejects_stale_graph_binding(self) -> None:
        load = lambda path: json.loads(path.read_text(encoding="utf-8"))
        inventory = load(translator.OUT_FULL_HQT3_INVENTORY_STATUS)
        schedule = load(translator.OUT_HQT3_RAMG_SCHEDULE_STATUS)
        partitions = load(translator.OUT_HQT3_PARTITION_SOLVER_STATUS)
        bound = load(translator.OUT_FRAME_RECORD_BOUND_STATUS)
        envelope = load(translator.OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS)
        graph = load(translator.OUT_ACTIVE_CALL_GRAPH_STATUS)
        pages = load(translator.OUT_HQT3_FRAME_PAGE_SOLVER_STATUS)
        pages["input_binding"]["active_call_graph"]["semantic_sha256"] = (
            "0" * 64)
        with self.assertRaisesRegex(
                translator.TranslationError,
                "HQT3 frame-page solver failed|stale against"):
            translator.validate_hqt3_frame_page_solver(
                pages, inventory, schedule, partitions, bound, envelope,
                graph, translator.ROOT)

    def test_whole_frame_budget_is_bound_to_active_render_plan(self) -> None:
        plan = translator.compile_active_frame_render_plan(
            translator.ROOT).as_dict()
        with tempfile.TemporaryDirectory() as temporary:
            budget = translator.frame_budget_contract(
                plan, translator.ROOT,
                Path(temporary) / "missing-frame-budget.json")
        self.assertEqual(
            budget["status"],
            "BLOCKED_MISSING_TRANSLATOR_CERTIFICATE")
        self.assertFalse(budget["full_frame_proved"])
        self.assertFalse(budget["live_target_lowering_present"])
        self.assertEqual(
            budget["frame_render_plan"]["semantic_sha256"],
            plan["semantic_sha256"])
        self.assertTrue(
            budget["frame_render_plan"]["major_z_order"]
            ["background_is_lowest_visible_layer"])

    def test_sprite_fragment_envelope_keeps_missing_hqt3_fail_closed(
            self) -> None:
        envelope = json.loads(
            translator.OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS.read_text(
                encoding="utf-8"))
        bound = json.loads(
            translator.OUT_FRAME_RECORD_BOUND_STATUS.read_text(
                encoding="utf-8"))
        assets = json.loads(
            translator.HQ_ASSET_MANIFEST.read_text(encoding="utf-8"))
        draw_plan = translator.compile_active_enemy_draw_plan(
            translator.ROOT).as_dict()
        self.assertIs(
            translator.validate_frame_sprite_fragment_envelope(
                envelope, bound, draw_plan, assets), envelope)
        self.assertFalse(envelope["proof_complete"])
        self.assertIsNone(
            envelope["weighted_display_list"]
            ["max_cmd_append_expanded_words"])

    def test_sprite_fragment_envelope_rejects_optimistic_blocked_maximum(
            self) -> None:
        envelope = json.loads(
            translator.OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS.read_text(
                encoding="utf-8"))
        bound = json.loads(
            translator.OUT_FRAME_RECORD_BOUND_STATUS.read_text(
                encoding="utf-8"))
        assets = json.loads(
            translator.HQ_ASSET_MANIFEST.read_text(encoding="utf-8"))
        draw_plan = translator.compile_active_enemy_draw_plan(
            translator.ROOT).as_dict()
        envelope["weighted_display_list"][
            "max_cmd_append_expanded_words"] = 0
        semantic = dict(envelope)
        semantic.pop("semantic_sha256")
        envelope["semantic_sha256"] = hashlib.sha256(json.dumps(
            semantic, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(
                translator.TranslationError, "leaked optimistic"):
            translator.validate_frame_sprite_fragment_envelope(
                envelope, bound, draw_plan, assets)


if __name__ == "__main__":
    unittest.main()
