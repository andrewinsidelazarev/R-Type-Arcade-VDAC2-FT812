"""Focused proof tests for the Render_Frame C-fragment insertion budget."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pyz80_compiler.frame_fragment_budget import (  # noqa: E402
    BATCH_PREFIX_WORDS,
    BATCH_SUFFIX_WORDS,
    CONTRACT_FORMAT,
    FrameFragmentBudgetError,
    MANDATORY_TAIL_CALLS,
    REPLACED_CALLS,
    TITLE_CALLS,
    audit_distance_cmd_text,
    compute_frame_render_plan_binding,
    compute_source_bindings,
    contract_requirements,
    current_budget_status,
    inspect_render_frame,
    prove_frame_fragment_budget,
)


RENDER = ROOT / "Source" / "ASM" / "render.asm"
BUILD_CMD = ROOT / "build.cmd"
HEIGHT = 768


def zero_raster() -> dict[str, list[list[int]]]:
    return {"rle": [[0, HEIGHT, 0]]}


def section(words: int = 1, raster: int = 0) -> dict[str, object]:
    return {
        "dl_words_kind": "expanded_ram_dl",
        "max_dl_words": words,
        "raster_cycles_by_line": {"rle": [[0, HEIGHT, raster]]},
        "proof": {
            "complete": True,
            "method": "focused-test exhaustive envelope",
            "bound": "conservative",
        },
    }


def complete_contract(*, section_words: int = 1, records: int = 2,
                      appended: int = 8, fragment_raster: int = 0,
                      chunk_capacity: int = 32) -> dict[str, object]:
    names = TITLE_CALLS + ("Render_WorldBackground",) + MANDATORY_TAIL_CALLS
    chunks = 0 if records == 0 else (
        records + chunk_capacity - 1) // chunk_capacity
    expanded = (chunks * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS) +
                2 * records + appended)
    physical = (chunks * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS) +
                5 * records)
    sections = {name: section(section_words) for name in names}
    distance = audit_distance_cmd_text(ROOT)
    sections["RTypePyRenderBeamMeter"] = {
        "dl_words_kind": "expanded_ram_dl",
        "max_dl_words": max(
            section_words, distance["section_expanded_dl_words"]),
        "raster_cycles_by_line": distance["raster_cycles_by_line"],
        "proof": {
            "complete": True,
            "method": "focused-test exact DIST plus conservative BEAM",
            "bound": "conservative",
        },
    }
    return {
        "format": CONTRACT_FORMAT,
        "source_program": {
            "launcher": "run_python.cmd",
            "module": "rtype_port.app",
            "canonical": False,
        },
        "frame_render_plan": compute_frame_render_plan_binding(ROOT),
        "bindings": compute_source_bindings(ROOT),
        "target": {
            "width": 1024,
            "height": HEIGHT,
            "ram_dl_word_limit": 2048,
            "safe_line_cycles": 1209,
        },
        "assembly_defines": [],
        "insertion": {
            "after": "Render_WorldBackground",
            "replaces_calls": list(REPLACED_CALLS),
            "mandatory_tail_calls": list(MANDATORY_TAIL_CALLS),
            "display_words_reserved": 1,
        },
        "statically_audited_sublayers": {
            "RTypePyRenderDistance": distance,
        },
        "sections": sections,
        "fragment": {
            "replaces_calls": list(REPLACED_CALLS),
            "dl_words_kind": "expanded_ram_dl",
            "max_records": records,
            "chunk_capacity": chunk_capacity,
            "max_chunks": chunks,
            "max_appended_words": appended,
            "max_expanded_dl_words": expanded,
            "max_physical_command_words": physical,
            "record_counter": {
                "symbol": "RTypePySpriteBatchRecordCount",
                "maximum": records,
                "origin": "active_python_render_order",
                "overflow_policy": "fail_before_frame_publication",
            },
            "append_bound": {
                "maximum": appended,
                "cmd_append_expanded": True,
                "all_reachable_templates": True,
            },
            "prepublication": {
                "complete_record_count_preflight": True,
                "complete_template_lookup_preflight": True,
                "complete_append_budget_preflight": True,
                "no_queue_fragment_ready_before_preflight": True,
                "atomic_complete_frame_commit": True,
            },
            "raster_cycles_by_line": {
                "rle": [[0, HEIGHT, fragment_raster]]},
            "proof": {
                "complete": True,
                "method": "focused-test active Python frames",
                "bound": "conservative",
            },
        },
    }


class RenderFrameShapeTests(unittest.TestCase):
    def test_budget_requirements_bind_exact_active_python_frame_plan(self) -> None:
        requirements = contract_requirements(ROOT, RENDER)
        binding = requirements["frame_render_plan"]
        self.assertEqual(binding["format"], "pyz80.frame-render-plan.v1")
        for name in (
                "source_sha256", "launcher_sha256", "method_ast_sha256",
                "sink_order_sha256", "semantic_sha256"):
            self.assertEqual(len(binding[name]), 64)
        major = binding["major_z_order"]
        self.assertEqual(
            [(item["call_path"], item["ordinal"])
             for item in major["sinks"]],
            [
                ("target.fill", 0),
                ("self.stage.draw_back", 1),
                ("self.enemy_world.draw", 2),
                ("self.force.draw", 3),
                ("self.bits.draw", 4),
                ("self.stage.draw_front", 13),
                ("target.blit", 14),
                ("self._draw_debug_distance", 18),
            ],
        )
        self.assertTrue(major["background_is_lowest_visible_layer"])
        self.assertTrue(major["enemy_force_bits_are_ordered"])
        self.assertTrue(major["foreground_before_hud"])
        self.assertTrue(major["distance_is_last"])

    def test_blocked_status_contains_plan_without_promoting_live_proof(self) -> None:
        missing = ROOT / "Build" / "__missing_frame_budget_test__.json"
        self.assertFalse(missing.exists())
        status = current_budget_status(ROOT, RENDER, missing)
        self.assertEqual(
            status["status"], "BLOCKED_MISSING_TRANSLATOR_CERTIFICATE")
        self.assertFalse(status["full_frame_proved"])
        self.assertFalse(status["live_target_lowering_present"])
        self.assertEqual(
            status["frame_render_plan"]["semantic_sha256"],
            compute_frame_render_plan_binding(ROOT)["semantic_sha256"],
        )
        self.assertTrue(status["blockers"]["missing_section_envelopes"])
        self.assertTrue(status["blockers"]["missing_fragment_contracts"])

    def test_actual_renderer_has_the_only_supported_insertion_boundary(self) -> None:
        shape = inspect_render_frame(RENDER)
        self.assertEqual(shape.insert_after, "Render_WorldBackground")
        self.assertEqual(shape.replaced_calls, REPLACED_CALLS)
        self.assertEqual(shape.tail_calls, MANDATORY_TAIL_CALLS)
        self.assertEqual(shape.title_calls, TITLE_CALLS)
        self.assertEqual(shape.direct_setup_words, 3)
        self.assertEqual(shape.display_words, 1)

    def test_release_build_is_gated_before_assembler_and_spg(self) -> None:
        text = BUILD_CMD.read_text(encoding="utf-8")
        status = text.index(
            "check_frame_fragment_budget.py --status --output")
        proof = text.index(
            '"%PYTHON%" Source\\Tools\\check_frame_fragment_budget.py\n',
            status)
        assembler = text.index('echo === sjasmplus ===')
        spg = text.index('echo === spgbld ===')
        deploy = text.index('echo === deploy current SPG to patched Unreal ===')
        self.assertLess(status, proof)
        self.assertLess(proof, assembler)
        self.assertLess(assembler, spg)
        self.assertLess(spg, deploy)
        self.assertIn("if errorlevel 1 goto :err", text[proof:assembler])

    def test_real_ft812_parser_expands_both_distance_text_commands(self) -> None:
        audit = audit_distance_cmd_text(ROOT)
        self.assertEqual(audit["text_commands"], 2)
        self.assertEqual(audit["expanded_words_with_display"], 61)
        self.assertEqual(audit["section_expanded_dl_words"], 60)
        self.assertEqual(audit["worst_line_with_display"], 711)
        self.assertEqual(audit["worst_cycles_with_display"], 95)


class FrameFragmentProofTests(unittest.TestCase):
    def test_append_expansion_display_and_both_scenes_are_counted(self) -> None:
        contract = complete_contract(section_words=1, records=2, appended=8)
        report = prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(
            report.frame_render_plan_semantic_sha256,
            contract["frame_render_plan"]["semantic_sha256"],
        )
        self.assertEqual(
            report.frame_render_plan_sink_order_sha256,
            contract["frame_render_plan"]["sink_order_sha256"],
        )
        # pre = VF3/CLEAR_COLOR/CLEAR + world background section.
        self.assertEqual(report.prefix_before_fragment_words, 4)
        # Nine one-word tails + exact 60-word BEAM/DIST tail + DISPLAY.
        self.assertEqual(report.mandatory_tail_words, 70)
        self.assertEqual(report.fragment_max_expanded_dl_words, 25)
        self.assertEqual(report.fragment_max_physical_command_words, 23)
        self.assertEqual(report.fragment_chunk_capacity, 32)
        self.assertEqual(report.fragment_max_chunks, 1)
        self.assertEqual(report.remaining_dl_words, 2047 - 4 - 70)
        self.assertEqual(report.game.word_count, 4 + 25 + 70)
        self.assertEqual(report.title.word_count, 3 + 1 + 1)
        # CLEAR is 1024/16=64 clocks on every scanline; DL walk is additive.
        self.assertEqual(
            report.game.worst_cycles,
            64 + report.game.word_count + 34)

    def test_missing_tail_envelope_fails_closed(self) -> None:
        contract = complete_contract()
        del contract["sections"]["RTypePyRenderLives"]  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB030")

    def test_stale_source_digest_fails_closed(self) -> None:
        contract = complete_contract()
        contract["bindings"]["assembly_tree_sha256"] = "00" * 32  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB056")

    def test_stale_frame_plan_hash_fails_before_envelope_proof(self) -> None:
        contract = complete_contract()
        contract["frame_render_plan"]["semantic_sha256"] = "00" * 32  # type: ignore[index]
        del contract["sections"]["RTypePyRenderLives"]  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB067")

    def test_missing_frame_plan_fails_before_envelope_proof(self) -> None:
        contract = complete_contract()
        del contract["frame_render_plan"]
        del contract["sections"]["RTypePyRenderLives"]  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB052")

    def test_reordered_background_binding_fails_before_envelope_proof(self) -> None:
        contract = complete_contract()
        major = contract["frame_render_plan"]["major_z_order"]  # type: ignore[index]
        background = next(  # type: ignore[arg-type]
            item for item in major["sinks"] if item["role"] == "background")
        background["ordinal"] = 2
        del contract["sections"]["RTypePyRenderLives"]  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB068")

    def test_wrong_cmd_append_expansion_is_rejected(self) -> None:
        contract = complete_contract(records=2, appended=8)
        contract["fragment"]["max_expanded_dl_words"] = 24  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB042")

    def test_multiple_chunks_repeat_prefix_and_suffix_without_frame_truncation(
            self) -> None:
        contract = complete_contract(
            records=70, appended=280, chunk_capacity=32)
        report = prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(report.fragment_max_chunks, 3)
        self.assertEqual(report.fragment_chunk_capacity, 32)
        self.assertEqual(
            report.fragment_max_expanded_dl_words,
            3 * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS) + 2 * 70 + 280)
        self.assertEqual(
            report.fragment_max_physical_command_words,
            3 * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS) + 5 * 70)

    def test_wrong_chunk_count_and_oversized_chunk_fail_closed(self) -> None:
        contract = complete_contract(records=70, chunk_capacity=32)
        contract["fragment"]["max_chunks"] = 2  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB064")

        contract = complete_contract(records=129, chunk_capacity=129)
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB063")

    def test_unbounded_runtime_record_counter_is_rejected(self) -> None:
        contract = complete_contract()
        del contract["fragment"]["record_counter"]  # type: ignore[index]
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB036")

    def test_missing_prepublication_proof_is_rejected(self) -> None:
        contract = complete_contract()
        del contract["fragment"]["prepublication"]  # type: ignore[index]
        with self.assertRaisesRegex(
                FrameFragmentBudgetError, "PZFB070"):
            prove_frame_fragment_budget(ROOT, RENDER, contract)

    def test_partial_frame_publication_is_rejected(self) -> None:
        contract = complete_contract()
        contract["fragment"]["prepublication"][  # type: ignore[index]
            "atomic_complete_frame_commit"] = False
        with self.assertRaisesRegex(
                FrameFragmentBudgetError, "PZFB071"):
            prove_frame_fragment_budget(ROOT, RENDER, contract)

    def test_insertion_boundary_is_part_of_v4_contract(self) -> None:
        contract = complete_contract()
        contract["insertion"]["after"] = "RTypeObjects_Draw"  # type: ignore[index]
        with self.assertRaisesRegex(
                FrameFragmentBudgetError, "PZFB072"):
            prove_frame_fragment_budget(ROOT, RENDER, contract)

    def test_exact_distance_sublayer_audit_is_part_of_v4_contract(self) -> None:
        contract = complete_contract()
        contract["statically_audited_sublayers"][  # type: ignore[index]
            "RTypePyRenderDistance"]["input_ram_cmd_words"] = 0
        with self.assertRaisesRegex(
                FrameFragmentBudgetError, "PZFB073"):
            prove_frame_fragment_budget(ROOT, RENDER, contract)

    def test_beam_envelope_must_dominate_its_distance_tail(self) -> None:
        contract = complete_contract()
        contract["sections"]["RTypePyRenderBeamMeter"][  # type: ignore[index]
            "max_dl_words"] = 59
        with self.assertRaisesRegex(
                FrameFragmentBudgetError, "PZFB074"):
            prove_frame_fragment_budget(ROOT, RENDER, contract)

    def test_ram_dl_overflow_is_rejected_before_live_hook(self) -> None:
        contract = complete_contract(section_words=180, records=128,
                                     appended=1500)
        # Keep the claimed arithmetic internally exact; total frame is unsafe.
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertIn(caught.exception.code, ("PZFB058", "PZFB059", "PZFB050"))

    def test_practical_1209_cycle_limit_is_enforced(self) -> None:
        contract = complete_contract(fragment_raster=1200)
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB051")

    def test_raster_envelope_must_cover_every_physical_line(self) -> None:
        contract = complete_contract()
        contract["fragment"]["raster_cycles_by_line"] = {  # type: ignore[index]
            "rle": [[0, HEIGHT - 1, 0]]}
        with self.assertRaises(FrameFragmentBudgetError) as caught:
            prove_frame_fragment_budget(ROOT, RENDER, contract)
        self.assertEqual(caught.exception.code, "PZFB026")


if __name__ == "__main__":
    unittest.main()
