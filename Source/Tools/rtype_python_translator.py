#!/usr/bin/env python3
"""Строгая трансляция активного Python-runtime в данные цели Z80/FT812.

Это не второй, вручную переписанный вариант игры. Скрипт начинает с
``rtype_port.app``, строит реальный граф локальных импортов и исполняет
строгие LUT для функций из TABLE_SPECS и полный CFG/call graph всех функций
активного импорт-графа. В closure попадают только функции, чья достижимость от
``rtype_port.app.main`` доказана исходным кодом; сам факт импорта модуля её не
подменяет. Неразрешённый dispatch, host boundary, module initialization или
неподдержанная AST-семантика остаются fail-closed. ``--require-complete``
завершает сборку ошибкой, пока любой такой барьер не закрыт.
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import importlib
import itertools
import json
import multiprocessing
import operator
import os
import re
import struct
import sys
import time
from collections import Counter
from types import SimpleNamespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pyz80_compiler import (AssetCompileError, CompileError, CompilerManifest,
                            compile_manifest)
from pyz80_compiler.sprite_coverage import (
    CoverageReport,
    SpriteCoverageError,
    analyze_sprite_coverage,
)
from pyz80_compiler.sprite_working_sets import (
    SpriteWorkingSetError,
    WorkingSetPlan,
    plan_sprite_working_sets,
)
from pyz80_compiler.draw_plan import (
    DrawPlanCompileError,
    SpriteDrawPlanIR,
    compile_active_enemy_draw_plan,
)
from pyz80_compiler.draw_c_backend import (
    BACKEND_FORMAT as DRAW_C_BACKEND_FORMAT,
    DrawCArtifacts,
    DrawCBackendError,
    emit_draw_c_backend,
    write_draw_c_backend,
)
from pyz80_compiler.draw_vm_backend import (
    VM_BACKEND_FORMAT as DRAW_VM_BACKEND_FORMAT,
    DrawVMBackendError,
    emit_draw_vm_backend,
    write_draw_vm_backend,
)
from pyz80_compiler.draw_state_backend import (
    DRAW_STATE_BACKEND_FORMAT,
    DrawStateArtifacts,
    DrawStateBackendError,
    build_draw_state_model,
    emit_draw_state_backend,
    write_draw_state_backend,
)
from pyz80_compiler.mutation_hook_ir import (
    MUTATION_HOOK_IR_FORMAT,
    MutationHookIRError,
    MutationHookPlan,
    build_mutation_hook_ir,
)
from pyz80_compiler.frontend import (
    OBJECT_STORE_IR_FORMAT,
    lower_active_object_store_ir,
    object_store_ir_report,
)
from pyz80_compiler.function_cfg import (
    FUNCTION_CFG_IR_FORMAT,
    FunctionCFGError,
    build_active_function_cfg_ir,
    function_cfg_report,
)
from pyz80_compiler.active_call_graph import (
    ACTIVE_CALL_GRAPH_FORMAT,
    ACTIVE_CALL_GRAPH_STATUS,
    ActiveCallGraphError,
    analyze_active_call_graph,
    validate_active_call_graph_report,
)
from pyz80_compiler.active_call_site_lowering import (
    ACTIVE_CALL_SITE_LOWERING_FORMAT,
    ACTIVE_CALL_SITE_LOWERING_STATUS,
    ActiveCallSiteLoweringError,
    analyze_active_call_site_lowering,
    validate_active_call_site_lowering_report,
)
from pyz80_compiler.active_target_adapters import (
    ACTIVE_TARGET_ADAPTERS_FORMAT,
    ACTIVE_TARGET_ADAPTERS_STATUS,
    ActiveTargetAdaptersError,
    analyze_active_target_adapters,
    validate_active_target_adapters_report,
)
from pyz80_compiler.frame_timing_provider import (
    FRAME_TIMING_PROVIDER_FORMAT,
    FRAME_TIMING_PROVIDER_STATUS,
    FrameTimingProviderError,
    analyze_frame_timing_provider,
    render_frame_timing_include,
    render_frame_timing_manifest,
    validate_frame_timing_provider_report,
)
from pyz80_compiler.whole_program_vm_backend import (
    COMPACT_TARGET_VM_FORMAT,
    WHOLE_PROGRAM_VM_FORMAT,
    WHOLE_PROGRAM_VM_STATUS_FORMAT,
    WholeProgramVMError,
    build_whole_program_vm,
    decode_compact_target_vm,
    decode_whole_program_vm,
    whole_program_vm_status,
)
from pyz80_compiler.whole_program_vm_stack_bound import (
    WHOLE_PROGRAM_VM_STACK_BOUND_FORMAT,
    WholeProgramVMStackBoundError,
    analyze_whole_program_vm_stack_bound,
    validate_whole_program_vm_stack_bound_report,
)
from pyz80_compiler.whole_program_vm_call_abi import (
    WHOLE_PROGRAM_VM_CALL_ABI_FORMAT,
    WHOLE_PROGRAM_VM_CALL_ABI_STATUS,
    WholeProgramVMCallABIError,
    analyze_whole_program_vm_call_abi,
    validate_whole_program_vm_call_abi_report,
)
from pyz80_translation_checkpoint import (
    TranslationCheckpointError,
    write_translation_checkpoint,
)
from pyz80_compiler.full_hqt3_inventory import (
    FULL_HQT3_INVENTORY_FORMAT,
    FULL_HQT3_INVENTORY_STATUS,
    FullHQT3InventoryError,
    analyze_full_hqt3_inventory,
)
from pyz80_compiler.hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    HQT3_RAMG_SCHEDULE_FORMAT,
    HQT3_RAMG_SCHEDULE_STATUS,
    HQT3_RECORD_BYTES,
    HQT3RAMGScheduleError,
    TSCONF_RAM_BYTES,
    analyze_hqt3_ramg_schedule,
)
from pyz80_compiler.hqt3_partition_solver import (
    HQT3_PARTITION_SOLVER_FORMAT,
    HQT3_PARTITION_SOLVER_STATUS,
    HQT3PartitionSolverError,
    analyze_hqt3_partition_solver,
)
from pyz80_compiler.hqt3_frame_page_solver import (
    HQT3_FRAME_PAGE_SOLVER_FORMAT,
    HQT3_FRAME_PAGE_SOLVER_STATUS,
    HQT3FramePageSolverError,
    analyze_hqt3_frame_page_solver,
)
from pyz80_compiler.generation_transaction import (
    GenerationTransaction,
    GenerationTransactionError,
)
from pyz80_compiler.frame_record_bound import (
    FrameRecordBoundError,
    analyze_active_frame_record_bound,
)
from pyz80_compiler.frame_sprite_fragment_envelope import (
    FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT,
    FrameSpriteFragmentEnvelopeError,
    analyze_frame_sprite_fragment_envelope,
)
from pyz80_compiler.frame_render_plan import (
    FrameRenderPlanError,
    compile_active_frame_render_plan,
)
from pyz80_compiler.frame_fragment_budget import (
    CONTRACT_FORMAT as FRAME_BUDGET_CONTRACT_FORMAT,
    FrameFragmentBudgetError,
    contract_requirements,
    current_budget_status,
)
from check_pyz80_draw_target_bundle import (
    FORMAT as DRAW_TARGET_BUNDLE_FORMAT,
    STATUS as DRAW_TARGET_BUNDLE_STATUS,
    DrawTargetBundleError,
    probe as probe_draw_target_bundle,
)
from check_pyz80_draw_bank_placement import (
    FORMAT as DRAW_BANK_PLACEMENT_FORMAT,
    STATUS as DRAW_BANK_PLACEMENT_STATUS,
    DrawBankPlacementError,
    probe as probe_draw_bank_placement,
)
from check_pyz80_draw_ramdl_shadow_v4 import (
    FORMAT as DRAW_RAMDL_SHADOW_V4_FORMAT,
    STATUS as DRAW_RAMDL_SHADOW_V4_STATUS,
    V4CheckError,
    build_report as build_draw_ramdl_shadow_v4_report,
    validate_report as validate_draw_ramdl_shadow_v4_report,
)
from check_pyz80_full_hqt3_inventory import (
    validate_report as validate_full_hqt3_inventory_report,
)
from check_pyz80_hqt3_ramg_schedule import (
    validate_report as validate_hqt3_ramg_schedule_report,
)
from check_pyz80_hqt3_partition_solver import (
    validate_report as validate_hqt3_partition_solver_report,
)
from check_pyz80_hqt3_frame_page_solver import (
    validate_report as validate_hqt3_frame_page_solver_report,
)
from pyz80_compiler.render_order_backend import (
    RENDER_ORDER_BACKEND_FORMAT,
    RenderOrderArtifacts,
    RenderOrderBackendError,
    build_render_order_model,
    emit_render_order_backend,
    write_render_order_backend,
)
from rtype_python_assets import (SpriteTemplateSource,
                                 compile_rtype_hq_asset_plan,
                                 encode_sprite_bank_key)


ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ROOT / "Source" / "Python"

# CPU-bound translator stages run in processes, not threads: CPython's GIL
# would otherwise keep these pure analyses on one core.  The coordinator owns
# every generated file and consumes worker results in a fixed name/key order,
# so scheduling cannot change output bytes or semantic hashes.
_PARALLEL_JOBS = max(1, os.cpu_count() or 1)
_INITIAL_ANALYSIS_STAGES = (
    "sprite_coverage",
    "frame_render_plan",
    "frame_record_bound",
)


def _normalise_parallel_jobs(value: int | None) -> int:
    jobs = max(1, os.cpu_count() or 1) if value is None else value
    if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs < 1:
        raise TranslationError("--jobs должен быть целым числом >= 1")
    return jobs


def _initial_analysis_worker(stage: str, project_root: str) -> Any:
    """Execute one file-system-read-only analysis in a spawned process."""
    root = Path(project_root)
    try:
        if stage == "sprite_coverage":
            return analyze_sprite_coverage(root)
        if stage == "frame_render_plan":
            return compile_active_frame_render_plan(root)
        if stage == "frame_record_bound":
            return analyze_active_frame_record_bound(root)
        raise RuntimeError(f"unknown analysis stage: {stage}")
    except Exception as exc:
        # Several domain exceptions deliberately have multi-argument
        # constructors and are therefore not safely reconstructed by Windows
        # multiprocessing pickle.  Preserve their complete diagnostic in a
        # spawn-safe exception instead of losing the real failure to a broken
        # result pipe.
        raise RuntimeError(
            f"{stage}: {type(exc).__name__}: {exc}") from None


def _run_initial_analyses(
        project_root: Path, jobs: int,
        ) -> tuple[CoverageReport, Any, Any]:
    """Run independent source analyses while preserving deterministic order."""
    if jobs == 1:
        values = {
            stage: _initial_analysis_worker(stage, str(project_root))
            for stage in _INITIAL_ANALYSIS_STAGES
        }
    else:
        worker_count = min(jobs, len(_INITIAL_ANALYSIS_STAGES))
        context = multiprocessing.get_context("spawn")
        try:
            with concurrent.futures.ProcessPoolExecutor(
                    max_workers=worker_count, mp_context=context) as pool:
                futures = {
                    stage: pool.submit(
                        _initial_analysis_worker, stage, str(project_root))
                    for stage in _INITIAL_ANALYSIS_STAGES
                }
                # Result collection order is source-controlled, never the
                # non-deterministic completion order of worker processes.
                values = {
                    stage: futures[stage].result()
                    for stage in _INITIAL_ANALYSIS_STAGES
                }
        except Exception as exc:
            raise TranslationError(
                f"параллельные начальные анализы не завершены: {exc}"
            ) from exc
    coverage = values["sprite_coverage"]
    render_plan = values["frame_render_plan"]
    record_bound = values["frame_record_bound"]
    if not isinstance(coverage, CoverageReport):
        raise TranslationError("worker вернул неверный CoverageReport")
    return coverage, render_plan, record_bound


def _progress(stage: str, started: float) -> float:
    now = time.perf_counter()
    print(f"[translator] {stage}: {now - started:.2f}s", flush=True)
    return now


OUT_BLOB = ROOT / "Build" / "python_translation_tables.bin"
OUT_REPORT = ROOT / "Build" / "rtype_python_translation.json"
OUT_SPRITE_WORKING_SET_STATUS = (
    ROOT / "Build" / "rtype_python_sprite_working_set_status.json"
)
OUT_FRAME_RENDER_PLAN_STATUS = (
    ROOT / "Build" / "rtype_python_frame_render_plan_status.json"
)
OUT_FRAME_RECORD_BOUND_STATUS = (
    ROOT / "Build" / "rtype_python_frame_record_bound_status.json"
)
OUT_FRAME_RECORD_REACHABILITY_STATUS = (
    ROOT / "Build" / "rtype_python_frame_record_reachability_status.json"
)
OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS = (
    ROOT / "Build" /
    "rtype_python_frame_sprite_fragment_envelope_status.json"
)
OUT_FRAME_BUDGET_STATUS = (
    ROOT / "Build" / "rtype_python_frame_budget_status.json"
)
OUT_FRAME_BUDGET_CONTRACT = (
    ROOT / "Build" / "rtype_python_frame_budget.json"
)
OUT_DRAW_TARGET_BUNDLE_STATUS = (
    ROOT / "Build" / "rtype_python_draw_target_bundle_status.json"
)
OUT_DRAW_BANK_PLACEMENT_STATUS = (
    ROOT / "Build" / "rtype_python_draw_bank_placement_status.json"
)
OUT_MUTATION_HOOK_IR_STATUS = (
    ROOT / "Build" / "rtype_python_mutation_hook_ir_status.json"
)
OUT_OBJECT_STORE_IR_STATUS = (
    ROOT / "Build" / "rtype_python_object_store_ir_status.json"
)
OUT_FUNCTION_CFG_STATUS = (
    ROOT / "Build" / "rtype_python_function_cfg_status.json"
)
OUT_ACTIVE_CALL_GRAPH_STATUS = (
    ROOT / "Build" / "rtype_python_active_call_graph_status.json"
)
OUT_ACTIVE_CALL_SITE_LOWERING_STATUS = (
    ROOT / "Build" / "rtype_python_active_call_site_lowering_status.json"
)
OUT_ACTIVE_TARGET_ADAPTERS_STATUS = (
    ROOT / "Build" / "rtype_python_active_target_adapters_status.json"
)
OUT_FRAME_TIMING_PROVIDER_STATUS = (
    ROOT / "Build" / "rtype_python_frame_timing_provider_status.json"
)
OUT_FRAME_TIMING_CONTRACT = (
    ROOT / "Build" / "rtype_python_frame_timing_contract.json"
)
OUT_FRAME_TIMING_INCLUDE = (
    ROOT / "Source" / "ASM" / "generated_python_frame_timing.inc"
)
OUT_DRAW_RAMDL_SHADOW_V4_STATUS = (
    ROOT / "Build" / "rtype_python_draw_ramdl_shadow_v4_status.json"
)
OUT_WHOLE_PROGRAM_VM_BIN = (
    ROOT / "Build" / "rtype_python_whole_program_vm.bin"
)
OUT_WHOLE_PROGRAM_VM_PROOF_BIN = (
    ROOT / "Build" / "rtype_python_whole_program_vm_proof.bin"
)
OUT_WHOLE_PROGRAM_VM_STATUS = (
    ROOT / "Build" / "rtype_python_whole_program_vm_status.json"
)
OUT_WHOLE_PROGRAM_VM_STACK_BOUND_STATUS = (
    ROOT / "Build" / "rtype_python_whole_program_vm_stack_bound_status.json"
)
OUT_WHOLE_PROGRAM_VM_CALL_ABI_STATUS = (
    ROOT / "Build" / "rtype_python_whole_program_vm_call_abi_status.json"
)
OUT_TRANSLATION_CHECKPOINT = (
    ROOT / "Build" / "rtype_python_translation_checkpoint.json"
)
OUT_FULL_HQT3_INVENTORY_STATUS = (
    ROOT / "Build" / "rtype_python_full_hqt3_inventory_status.json"
)
OUT_HQT3_RAMG_SCHEDULE_STATUS = (
    ROOT / "Build" / "rtype_python_hqt3_ramg_schedule_status.json"
)
OUT_HQT3_PARTITION_SOLVER_STATUS = (
    ROOT / "Build" / "rtype_python_hqt3_partition_solver_status.json"
)
OUT_HQT3_FRAME_PAGE_SOLVER_STATUS = (
    ROOT / "Build" / "rtype_python_hqt3_frame_page_solver_status.json"
)
HQ_ASSET_MANIFEST = ROOT / "Build" / "rtype_python_assets.json"
OUT_INC = ROOT / "Source" / "ASM" / "generated_python_translation.inc"
OUT_SPRITE_CACHE = ROOT / "Source" / "ASM" / "generated_python_sprite_cache.asm"
OUT_STACK_CONTROL = ROOT / "Source" / "ASM" / "generated_python_stack.asm"
OUT_GAMEPLAY_BACKEND = ROOT / "Source" / "ASM" / "generated_python_gameplay.asm"
OUT_GAMEPLAY_TABLES = (
    ROOT / "Source" / "ASM" / "generated_python_gameplay_tables.inc"
)
OUT_GAMEPLAY_LAYOUT = (
    ROOT / "Source" / "ASM" / "generated_python_gameplay_layout.inc"
)
OUT_COLLISION_BACKEND = (
    ROOT / "Source" / "ASM" / "generated_python_collision.asm"
)
OBJECT_RUNTIME_ASM = ROOT / "Source" / "ASM" / "object_runtime.asm"
ARCADE_GAME_ASM = ROOT / "Source" / "ASM" / "arcade_game.asm"
WORLD_RUNTIME_ASM = ROOT / "Source" / "ASM" / "world_runtime.asm"
OUT_BEAM_COMMANDS = ROOT / "Build" / "rtype_python_beam_commands.bin"
PYZ80_MANIFEST = ROOT / "Source" / "Tools" / "rtype_python_compiler.json"
LAUNCHER = ROOT / "run_python.cmd"
PLAYER_ASSET_MANIFEST = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Player" / "r9_pitch.json"
)
BEAM_METER_CAPTURE = (
    ROOT / "Build" / "Arcade" / "MAME" / "beam_meter_exact_trace"
)
TARGET_PACK = ROOT / "Build" / "rtype_target_pack.bin"
TARGET_PACK_MANIFEST = ROOT / "Build" / "rtype_target_pack.json"
DRAW_C_OUTPUT_DIRECTORY = ROOT / "Source" / "C" / "generated"
DRAW_C_PREFIX = "rtype_python_draw_plan"
OUT_DRAW_C_HEADER = DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_C_PREFIX}.h"
OUT_DRAW_C_SOURCE = DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_C_PREFIX}.c"
OUT_DRAW_C_MANIFEST = DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_C_PREFIX}.json"
DRAW_CHUNKER_HEADER = (
    ROOT / "Source" / "C" / "ft812" / "pyz80_draw_chunker.h")
DRAW_CHUNKER_SOURCE = (
    ROOT / "Source" / "C" / "ft812" / "pyz80_draw_chunker.c")
DRAW_C_SIZE_STATUS = ROOT / "Build" / "rtype_python_draw_c_size_status.json"
DRAW_VM_PREFIX = "rtype_python_draw_vm"
OUT_DRAW_VM_HEADER = DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_VM_PREFIX}.h"
OUT_DRAW_VM_SOURCE = DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_VM_PREFIX}.c"
OUT_DRAW_VM_MANIFEST = DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_VM_PREFIX}.json"
DRAW_VM_SIZE_STATUS = ROOT / "Build" / "rtype_python_draw_vm_size_status.json"
DRAW_VM_STACK_STATUS = (
    ROOT / "Build" / "rtype_python_draw_vm_stack_status.json")
RENDER_ORDER_PREFIX = "rtype_python_render_order"
OUT_RENDER_ORDER_HEADER = (
    DRAW_C_OUTPUT_DIRECTORY / f"{RENDER_ORDER_PREFIX}.h")
OUT_RENDER_ORDER_SOURCE = (
    DRAW_C_OUTPUT_DIRECTORY / f"{RENDER_ORDER_PREFIX}.c")
OUT_RENDER_ORDER_MANIFEST = (
    DRAW_C_OUTPUT_DIRECTORY / f"{RENDER_ORDER_PREFIX}.json")
RENDER_ORDER_SIZE_STATUS = (
    ROOT / "Build" / "rtype_python_render_order_size_status.json")
DRAW_STATE_PREFIX = "rtype_python_draw_state"
OUT_DRAW_STATE_HEADER = (
    DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_STATE_PREFIX}.h")
OUT_DRAW_STATE_SOURCE = (
    DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_STATE_PREFIX}.c")
OUT_DRAW_STATE_MANIFEST = (
    DRAW_C_OUTPUT_DIRECTORY / f"{DRAW_STATE_PREFIX}.json")
DRAW_STATE_SIZE_STATUS = (
    ROOT / "Build" / "rtype_python_draw_state_size_status.json")
DRAW_FAST_CHUNKER_HEADER = (
    ROOT / "Source" / "C" / "ft812" / "pyz80_draw_fast_chunker.h")
DRAW_FAST_CHUNKER_SOURCE = (
    ROOT / "Source" / "C" / "ft812" / "pyz80_draw_fast_chunker.c")
DRAW_FAST_CHUNKER_STATUS = (
    ROOT / "Build" / "rtype_python_draw_fast_chunker_status.json")
DRAW_FAST_CHUNKER_TIMING = (
    ROOT / "Build" / "rtype_python_draw_fast_chunker_timing.json")
M72_ATLAS_INC = ROOT / "Source" / "ASM" / "generated_m72_atlas.inc"
M72_ATLAS_BIN = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" /
    "TILE_ATLAS_ARGB4444.bin"
)
TARGET_PAGE = 0xE7
PAGE_SIZE = 0x4000
BEAM_COMMAND_PAGE = 0xEB
M72_ATLAS_RAMG = 0x020000
M72_GLYPH_BYTES = 14 * 15 * 2

# Единственный bridge между Python-классами и compact type byte аппаратного
# object pool. Сама кратность descriptor-отрисовки ниже извлекается из AST;
# отсутствующий bridge запрещает сборку вместо невидимого/обрезанного enemy.
OBJECT_TYPE_BY_CLASS = {
    "PlayerTargeting80E3": 11,
    "Targeting80E3Projectile": 13,
    "Handler60BA": 21,
    "Enemy6F89": 35,
    "Enemy7D68": 38,
    "Child8D85": 39,
    "Handler5CEAShot": 47,
    "Enemy8561": 48,
    "Enemy5EED": 50,
    "BossB7FBSegment": 65,
    "BossB7FBMissile": 69,
    "BossB7FBCore": 70,
}
OBJECT_TYPE_COUNT = 80

FT812_SUPPORT_EXPORTS = (
    ("PyZ80FT_QueueInitialize", "sdcccall(0)"),
    ("PyZ80FT_QueueAcquire", "sdcccall(0)"),
    ("PyZ80FT_QueueAcquireFragment", "sdcccall(0)"),
    ("PyZ80FT_QueuePushCommand", "sdcccall(0)"),
    ("PyZ80FT_QueuePushDL", "sdcccall(0)"),
    ("PyZ80FT_ResolveBankKey", "sdcccall(0)"),
    ("PyZ80FT_LogicalVertex", "sdcccall(0)"),
    ("PyZ80FT_LowerNativeX", "sdcccall(0)"),
    ("PyZ80FT_LowerNativeY", "sdcccall(0)"),
    ("PyZ80FT_FindHQTemplate", "sdcccall(0)"),
    ("PyZ80FT_QueuePushTemplate", "sdcccall(0)"),
    ("PyZ80FT_QueuePushDescriptor", "sdcccall(0)"),
    ("PyZ80FT_QueuePushDescAppend", "sdcccall(0)"),
    ("PyZ80FT_BuildSpriteBatch", "sdcccall(0)"),
    ("PyZ80FT_BuildSpriteBatchFast", "sdcccall(0)"),
    ("PyZ80FT_QueueCommit", "sdcccall(0)"),
    ("PyZ80FT_QueueCommitFragment", "sdcccall(0)"),
)


def ft812_queue_protocol_contract() -> dict[str, Any]:
    """Binary queue modes consumed by the resident FT812 bridge."""
    return {
        "format": 3,
        "header_size": 16,
        "kind_offset": 14,
        "full": {
            "kind": 0,
            "acquire_prefix": ["CMD_DLSTART"],
            "commit_suffix": ["DISPLAY", "CMD_SWAP"],
        },
        "fragment": {
            "kind": 1,
            "acquire_prefix": [],
            "commit_suffix": [],
            "embedding": "open FT_CMD_Start/FT_DL_Start",
            "sprite_batch": {
                "record_format": (
                    "packed <bank_key:u16,descriptor:u16,"
                    "anchor_x:i16,anchor_y:i16>"),
                "record_size": 8,
                "record_vma": 0xCA44,
                "record_bytes": 0x35BC,
                "max_records": 128,
                "remaining_dl_budget": "caller full-frame <=2048",
                "output": (
                    "white+transforms+bitmap-size+VF3+BEGIN, ordered "
                    "CMD_APPEND, translate-zero, END, READY"),
                "preflight": "two-pass atomic, queue/record non-overlap",
                "pre_resolved": {
                    "record_format": (
                        "packed <template_index:u16,anchor_x:i16,"
                        "anchor_y:i16>"),
                    "record_size": 6,
                    "template_identity": (
                        "immutable generated HQT3 table index"),
                    "old_literal_abi": "retained as differential oracle",
                    "preflight": (
                        "same two-pass/fail-closed/budget/publication rules"),
                },
            },
        },
        "publication": "READY state byte written last",
        "mixed_kind": "fail-closed",
    }


def compile_initial_checkpoint_snapshot() -> tuple[bytes, dict[str, Any]]:
    """Execute the launched Python initializers and serialize their live pool.

    This is source execution during translation, not a hand-authored Z80
    approximation.  The compact stream contains every live record, every
    non-zero free-slot Q8 residue, allocator/resource/RNG state and the exact
    scheduler links observed before the first ``Game.update`` call.
    """
    python_root = str(PYTHON_ROOT)
    if python_root not in sys.path:
        sys.path.insert(0, python_root)
    enemies = importlib.import_module("rtype_port.enemies")
    stage = importlib.import_module("rtype_port.stage")

    world = enemies.M72EnemyWorld()
    scroll = stage.M72Scroll()
    records: dict[int, bytearray] = {}

    def index_for_slot(slot: int) -> int:
        index, remainder = divmod(slot - 0x0540, 0x40)
        if remainder or not 0 <= index < 96:
            raise TranslationError(f"Python object slot вне pool: {slot:#06x}")
        return index

    def put_word(record: bytearray, offset: int, value: int) -> None:
        struct.pack_into("<H", record, offset, value & 0xFFFF)

    # Allocation does not clear these two Q8 residue bytes.
    for slot, (x_fraction, y_fraction) in world.object_pool.residue.items():
        if x_fraction or y_fraction:
            record = records.setdefault(index_for_slot(slot), bytearray(0x40))
            record[0x10] = x_fraction & 0xFF
            record[0x11] = y_fraction & 0xFF

    ordered: list[object] = []
    for enemy in world.enemies:
        slot = enemy.object_slot
        if slot is None:
            raise TranslationError("checkpoint enemy без object_slot")
        index = index_for_slot(slot)
        record = records.setdefault(index, bytearray(0x40))
        record[0x01] = 0
        put_word(record, 0x02, enemy.x)
        put_word(record, 0x04, enemy.y)
        put_word(record, 0x06, enemy.descriptor)
        record[0x08] = enemy.palette & 0xFF
        record[0x09] = (
            world.resources.types[enemy.palette]
            if 0 <= enemy.palette < len(world.resources.types) else 0xFF)
        put_word(record, 0x0A, enemy.scheduler_priority)
        put_word(record, 0x0C, enemy.scheduler_serial)

        if isinstance(enemy, enemies.BackgroundParticleE5CD):
            record[0] = 4
            record[0x0E] = int(enemy.initialized)
            record[0x0F] = int(enemy.render_ready)
            record[0x10] = enemy.x_fraction & 0xFF
            record[0x11] = enemy.y_fraction & 0xFF
            put_word(record, 0x12, enemy.x_velocity)
            put_word(record, 0x16, enemy.velocity_table)
        elif isinstance(enemy, enemies.PaletteCycleFBED):
            record[0] = 2
            put_word(record, 0x20, enemy.palette_index)
            put_word(record, 0x22, enemy.first_resource)
            put_word(record, 0x24, enemy.second_resource)
            put_word(record, 0x26, enemy.remaining)
            put_word(record, 0x28, enemy.mode)
            put_word(record, 0x2A, enemy.mask)
            put_word(record, 0x2C, enemy.phase)
        else:
            raise TranslationError(
                f"неподдержанный initial checkpoint enemy {type(enemy).__name__}")
        ordered.append(enemy)

    for owner in world.resource_owners:
        if owner.object_slot is None:
            raise TranslationError("checkpoint resource owner без object_slot")
        index = index_for_slot(owner.object_slot)
        record = records.setdefault(index, bytearray(0x40))
        record[0] = 3
        put_word(record, 0x0A, 0x1000)
        put_word(record, 0x20, owner.remaining)
        put_word(record, 0x22, owner.velocity_table)
        put_word(record, 0x24, owner.cadence)
        put_word(record, 0x26, owner.spawn_counter)
        record[0x28:0x2C] = bytes(owner.slots)
        ordered.append(owner)

    # M72EnemyWorld.update executes the same ascending-priority order.
    order_position = {id(owner): position for position, owner in enumerate(ordered)}
    ordered.sort(key=lambda owner: (
        getattr(owner, "scheduler_priority", 0x1000),
        -getattr(owner, "scheduler_serial", 0),
        order_position[id(owner)],
    ))
    chain = [index_for_slot(owner.object_slot) for owner in ordered]
    scheduler_next = bytearray(b"\xFF" * 96)
    scheduler_prev = bytearray(b"\xFF" * 96)
    for position, index in enumerate(chain):
        if position:
            scheduler_prev[index] = chain[position - 1]
        if position + 1 < len(chain):
            scheduler_next[index] = chain[position + 1]

    free_indices = [index_for_slot(slot) for slot in world.object_pool.free]
    free_queue = bytes(free_indices) + bytes([0xFF] * (96 - len(free_indices)))
    payload = bytearray(b"PYI1")
    payload.append(len(records))
    for index in sorted(records):
        payload.append(index)
        payload.extend(records[index])
    payload.extend(free_queue)
    payload.extend(bytes((0, len(free_indices), len(free_indices))))
    payload.extend(struct.pack("<H", world.object_pool.serial & 0xFFFF))
    payload.extend(bytes(world.resources.types))
    payload.extend(bytes(world.resources.refs))
    payload.extend(bytes((world.rng.a, world.rng.b, world.rng.c)))
    payload.extend(scheduler_next)
    payload.extend(scheduler_prev)
    payload.extend(bytes((chain[0], chain[-1])))
    # Keep the contiguous runtime fields contiguous in the generated stream as
    # well.  The loader can then copy them verbatim instead of synthesising
    # Python values with a long sequence of immediate Z80 stores.
    payload.extend(struct.pack("<I", scroll.progression_accumulator & 0xFFFFFF)[:3])
    payload.extend(struct.pack("<H", scroll.foreground_velocity & 0xFFFF))
    payload.extend(struct.pack("<H", scroll.background_velocity & 0xFFFF))
    payload.extend(struct.pack("<I", scroll.foreground_accumulator & 0xFFFFFF)[:3])
    payload.extend(struct.pack("<I", scroll.background_accumulator & 0xFFFFFF)[:3])

    stage_first = enemies.STAGE_EVENT_RANGES[world.stage][0]
    event_skip, remainder = divmod(world.event_pointer - stage_first, 4)
    if remainder:
        raise TranslationError("Python initial event pointer не выровнен")
    return bytes(payload), {
        "symbol": "rtype_port.game.Game.__init__ checkpoint state",
        "asm_name": "RTypePyInitialCheckpoint",
        "element": "bytes",
        "dimensions": [len(payload)],
        "entries": len(payload),
        "ast_sha256": hashlib.sha256(payload).hexdigest(),
        "record_count": len(records),
        "active_count": len(chain),
        "free_count": len(free_indices),
        "event_skip": event_skip,
        "progression_accumulator": scroll.progression_accumulator,
        "foreground_accumulator": scroll.foreground_accumulator,
        "foreground_velocity": scroll.foreground_velocity,
        "background_accumulator": scroll.background_accumulator,
        "background_velocity": scroll.background_velocity,
    }


class TranslationError(RuntimeError):
    """Ошибка строгой трансляции выбранного Python-символа."""


@dataclass(frozen=True)
class ArgDomain:
    name: str
    values: tuple[int | bool, ...]


@dataclass(frozen=True)
class TableSpec:
    module: str
    function: str
    asm_name: str
    domains: tuple[ArgDomain, ...]
    element: str
    class_name: str | None = None
    initial_state: tuple[tuple[str, Any], ...] = ()
    output_attribute: str | None = None

    @property
    def symbol(self) -> str:
        owner = f"{self.class_name}." if self.class_name else ""
        return f"{self.module}.{owner}{self.function}"


@dataclass(frozen=True)
class ConstantMembershipSpec:
    module: str
    constant: str
    asm_name: str
    domain: ArgDomain

    @property
    def symbol(self) -> str:
        return f"{self.module}.{self.constant}"


def integer_domain(name: str, first: int, last: int) -> ArgDomain:
    return ArgDomain(name, tuple(range(first, last + 1)))


TABLE_SPECS = (
    TableSpec("rtype_port.game", "p1_label_visible", "RTypePyP1LabelVisible",
              (integer_domain("frame_counter", 0, 31),), "u8"),
    TableSpec("rtype_port.game", "beam_native_width", "RTypePyBeamNativeWidth",
              (integer_domain("charge", 0, 128),), "u8"),
    TableSpec("rtype_port.game", "wave_power", "RTypePyWavePower",
              (integer_domain("charge", 0, 128),), "u8"),
    TableSpec("rtype_port.game", "wave_power_tier", "RTypePyWavePowerTier",
              (integer_domain("power", 0, 255),), "u8"),
    TableSpec("rtype_port.game", "advance_wave_charge", "RTypePyAdvanceWaveCharge",
              (integer_domain("charge", 0, 128),), "u8"),
    TableSpec("rtype_port.game", "beam_animation_phase", "RTypePyBeamAnimationPhase",
              (integer_domain("m72_frame_counter", 0, 255),), "u8"),
    TableSpec("rtype_port.title", "_native_x", "RTypePyTitleNativeX",
              (integer_domain("value", 0, 384),), "u16"),
    TableSpec("rtype_port.title", "_native_y", "RTypePyTitleNativeY",
              (integer_domain("value", 0, 256),), "u16"),
    TableSpec("rtype_port.title", "prompt_visible", "RTypePyTitlePromptVisible",
              (integer_domain("frame", 276, 339),), "u8"),
    TableSpec("rtype_port.title", "_logo_state", "RTypePyTitleLogoState",
              (integer_domain("frame", 0, 315),
               integer_domain("glyph", 0, 6)), "flag_s16_s16"),
)

CONSTANT_TABLE_SPECS: tuple[ConstantMembershipSpec, ...] = ()

LIFECYCLE_CONSTANT_SPECS = (
    ("INITIAL_LIVES", "RTYPEPY_INITIAL_LIVES", 1, 255),
    ("MAX_LIVES", "RTYPEPY_MAX_LIVES", 1, 255),
    ("PLAYER_CLEAR_AGE", "RTYPEPY_PLAYER_CLEAR_AGE", 0, 0xFFFF),
    ("LIFE_DECREMENT_AGE", "RTYPEPY_LIFE_DECREMENT_AGE", 0, 0xFFFF),
    ("RESPAWN_AGE", "RTYPEPY_RESPAWN_AGE", 0, 0xFFFF),
    ("RESPAWN_INVULNERABILITY", "RTYPEPY_RESPAWN_INVULNERABILITY", 0, 255),
)


BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
}
UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
    ast.Not: operator.not_,
}
CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}
SAFE_CALLS = {
    "abs": abs,
    "bool": bool,
    "frozenset": frozenset,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "tuple": tuple,
}


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(PYTHON_ROOT).with_suffix("").parts)


def module_paths() -> dict[str, Path]:
    return {
        module_name(path): path
        for path in sorted(PYTHON_ROOT.rglob("*.py"))
        if path.name != "__init__.py"
    }


def launcher_entry() -> tuple[str, str]:
    """Получить модуль буквально из run_python.cmd, а не из настройки скрипта."""
    data = LAUNCHER.read_bytes()
    text = data.decode("utf-8", errors="strict")
    matches = re.findall(r"(?:^|\s)-m\s+([A-Za-z_][A-Za-z0-9_.]*)", text,
                         flags=re.MULTILINE)
    if len(matches) != 1:
        raise TranslationError(
            f"run_python.cmd должен содержать ровно один запуск -m, найдено {matches}")
    return matches[0], hashlib.sha256(data).hexdigest()


def resolve_from(current: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = current.split(".")[:-1]
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return ""
    prefix = package[:keep]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def reachable_graph(paths: dict[str, Path], entry_module: str | None = None
                    ) -> tuple[dict[str, ast.Module], dict[str, list[str]]]:
    trees: dict[str, ast.Module] = {}
    edges: dict[str, list[str]] = {}
    if entry_module is None:
        entry_module, _ = launcher_entry()
    queue = [entry_module]
    while queue:
        name = queue.pop(0)
        if name in trees:
            continue
        path = paths.get(name)
        if path is None:
            raise TranslationError(f"не найден входной Python-модуль {name}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[name] = tree
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = resolve_from(name, node)
                if base in paths:
                    imports.add(base)
                for alias in node.names:
                    child = f"{base}.{alias.name}" if base else alias.name
                    if child in paths:
                        imports.add(child)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in paths:
                        imports.add(alias.name)
        edges[name] = sorted(imports)
        queue.extend(child for child in sorted(imports) if child not in trees)
    return trees, edges


def eval_expr(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise TranslationError(f"неизвестное имя {node.id}")
    if isinstance(node, ast.Attribute):
        owner = eval_expr(node.value, env)
        try:
            return getattr(owner, node.attr)
        except AttributeError as exc:
            raise TranslationError(f"нет атрибута {node.attr}") from exc
    if isinstance(node, ast.Tuple):
        return tuple(eval_expr(item, env) for item in node.elts)
    if isinstance(node, ast.List):
        return [eval_expr(item, env) for item in node.elts]
    if isinstance(node, ast.Set):
        return {eval_expr(item, env) for item in node.elts}
    if isinstance(node, ast.Dict):
        return {eval_expr(key, env): eval_expr(value, env)
                for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARYOPS:
        return UNARYOPS[type(node.op)](eval_expr(node.operand, env))
    if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
        return BINOPS[type(node.op)](eval_expr(node.left, env), eval_expr(node.right, env))
    if isinstance(node, ast.BoolOp):
        values = [eval_expr(value, env) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = eval_expr(node.left, env)
        for operation, comparator in zip(node.ops, node.comparators):
            right = eval_expr(comparator, env)
            function = CMPOPS.get(type(operation))
            if function is None:
                raise TranslationError(f"неподдержанное сравнение {type(operation).__name__}")
            if not function(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        branch = node.body if eval_expr(node.test, env) else node.orelse
        return eval_expr(branch, env)
    if isinstance(node, ast.Subscript):
        return eval_expr(node.value, env)[eval_expr(node.slice, env)]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = SAFE_CALLS.get(node.func.id)
        if function is None or node.keywords:
            raise TranslationError(f"неподдержанный вызов {node.func.id}")
        return function(*(eval_expr(argument, env) for argument in node.args))
    raise TranslationError(f"неподдержанная AST-нода выражения {type(node).__name__}")


def module_constants(tree: ast.Module) -> dict[str, Any]:
    constants: dict[str, Any] = {}
    for node in tree.body:
        name: str | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name is None or value is None:
            continue
        try:
            constants[name] = eval_expr(value, constants)
        except TranslationError:
            pass
    return constants


def class_constants(tree: ast.Module, class_name: str) -> dict[str, Any]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            synthetic = ast.Module(body=node.body, type_ignores=[])
            return module_constants(synthetic)
    raise TranslationError(f"класс {class_name} не найден")


def find_function(tree: ast.Module, name: str, class_name: str | None = None) -> ast.FunctionDef:
    body: list[ast.stmt] = tree.body
    if class_name is not None:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                body = node.body
                break
        else:
            raise TranslationError(f"класс {class_name} не найден")
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            if isinstance(node, ast.AsyncFunctionDef):
                raise TranslationError(f"async-функция {name} не поддерживается")
            return node
    raise TranslationError(f"функция {name} не найдена")


def bind_function(function: ast.FunctionDef, values: dict[str, Any], constants: dict[str, Any]) -> dict[str, Any]:
    positional = list(function.args.posonlyargs) + list(function.args.args)
    if function.args.vararg or function.args.kwarg:
        raise TranslationError(f"сложная сигнатура {function.name} не поддерживается")
    defaults_at = len(positional) - len(function.args.defaults)
    env = dict(constants)
    for index, argument in enumerate(positional):
        if argument.arg in values:
            env[argument.arg] = values[argument.arg]
        elif index >= defaults_at:
            env[argument.arg] = eval_expr(function.args.defaults[index - defaults_at], env)
        else:
            raise TranslationError(f"не задан аргумент {argument.arg} функции {function.name}")
    for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
        if argument.arg in values:
            env[argument.arg] = values[argument.arg]
        elif default is not None:
            env[argument.arg] = eval_expr(default, env)
        else:
            raise TranslationError(f"не задан keyword-only аргумент {argument.arg}")
    return env


def assign_target(target: ast.expr, value: Any, env: dict[str, Any]) -> None:
    if isinstance(target, ast.Name):
        env[target.id] = value
        return
    if isinstance(target, ast.Attribute):
        owner = eval_expr(target.value, env)
        setattr(owner, target.attr, value)
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        values = tuple(value)
        if len(values) != len(target.elts):
            raise TranslationError("число значений распаковки не совпало")
        for child, item in zip(target.elts, values):
            assign_target(child, item, env)
        return
    raise TranslationError(f"неподдержанная цель присваивания {type(target).__name__}")


def execute_statements(statements: Iterable[ast.stmt], env: dict[str, Any]) -> tuple[bool, Any]:
    for node in statements:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.If):
            branch = node.body if eval_expr(node.test, env) else node.orelse
            returned, value = execute_statements(branch, env)
            if returned:
                return True, value
            continue
        if isinstance(node, ast.Return):
            return True, None if node.value is None else eval_expr(node.value, env)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            assign_target(node.targets[0], eval_expr(node.value, env), env)
            continue
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            assign_target(node.target, eval_expr(node.value, env), env)
            continue
        if isinstance(node, ast.AugAssign) and type(node.op) in BINOPS:
            current = eval_expr(node.target, env)
            assign_target(node.target, BINOPS[type(node.op)](current, eval_expr(node.value, env)), env)
            continue
        if isinstance(node, ast.For):
            for item in eval_expr(node.iter, env):
                assign_target(node.target, item, env)
                returned, value = execute_statements(node.body, env)
                if returned:
                    return True, value
            if node.orelse:
                returned, value = execute_statements(node.orelse, env)
                if returned:
                    return True, value
            continue
        raise TranslationError(f"неподдержанный оператор {type(node).__name__}")
    return False, None


def execute_function(function: ast.FunctionDef, constants: dict[str, Any], values: dict[str, Any],
                     *, require_return: bool = True) -> Any:
    env = bind_function(function, values, constants)
    returned, result = execute_statements(function.body, env)
    if not returned and require_return:
        raise TranslationError(f"функция {function.name} завершилась без return")
    return result


def encode_value(value: Any, element: str) -> bytes:
    try:
        if element == "u8":
            return struct.pack("<B", int(value))
        if element == "u16":
            return struct.pack("<H", int(value))
        if element == "s16":
            return struct.pack("<h", int(value))
        if element == "flag_s16_s16":
            visible, x, y = value
            return struct.pack("<Bhh", int(bool(visible)), int(x), int(y))
    except struct.error as exc:
        raise TranslationError(f"значение {value!r} не помещается в {element}") from exc
    raise TranslationError(f"неизвестный тип таблицы {element}")


def compile_table(spec: TableSpec, trees: dict[str, ast.Module]) -> tuple[bytes, dict[str, Any]]:
    tree = trees.get(spec.module)
    if tree is None:
        raise TranslationError(f"модуль таблицы не достижим: {spec.module}")
    function = find_function(tree, spec.function, spec.class_name)
    expected_args = [domain.name for domain in spec.domains]
    actual_args = [arg.arg for arg in (list(function.args.posonlyargs) +
                                      list(function.args.args) +
                                      list(function.args.kwonlyargs))]
    if spec.class_name is not None:
        actual_args = [name for name in actual_args if name != "self"]
    if not set(expected_args).issubset(actual_args):
        raise TranslationError(
            f"изменена сигнатура {spec.symbol}: {actual_args}, ожидались {expected_args}"
        )
    constants = module_constants(tree)
    blob = bytearray()
    sample_hash = hashlib.sha256()
    count = 0
    for combination in itertools.product(*(domain.values for domain in spec.domains)):
        arguments = dict(zip(expected_args, combination))
        if spec.class_name is not None:
            state = SimpleNamespace(**dict(spec.initial_state))
            arguments["self"] = state
            execute_function(function, constants, arguments, require_return=False)
            if spec.output_attribute is None:
                raise TranslationError(f"для метода {spec.symbol} не задан выходной атрибут")
            result = getattr(state, spec.output_attribute)
        else:
            result = execute_function(function, constants, arguments)
        encoded = encode_value(result, spec.element)
        blob.extend(encoded)
        sample_hash.update(encoded)
        count += 1
    ast_hash = hashlib.sha256(ast.dump(function, include_attributes=False).encode("utf-8")).hexdigest()
    return bytes(blob), {
        "symbol": spec.symbol,
        "asm_name": spec.asm_name,
        "element": spec.element,
        "dimensions": [len(domain.values) for domain in spec.domains],
        "arguments": [
            {"name": domain.name, "first": domain.values[0], "last": domain.values[-1]}
            for domain in spec.domains
        ],
        "entries": count,
        "ast_sha256": ast_hash,
        "data_sha256": sample_hash.hexdigest(),
    }


def compile_constant_table(spec: ConstantMembershipSpec,
                           trees: dict[str, ast.Module]) -> tuple[bytes, dict[str, Any]]:
    tree = trees.get(spec.module)
    if tree is None:
        raise TranslationError(f"модуль константы не достижим: {spec.module}")
    constants = module_constants(tree)
    if spec.constant not in constants:
        raise TranslationError(f"константа {spec.symbol} не вычисляется строгим AST")
    values = constants[spec.constant]
    if not isinstance(values, (set, frozenset, tuple, list)):
        raise TranslationError(f"{spec.symbol} не является набором кадров")
    assignment: ast.AST | None = None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and
                any(isinstance(target, ast.Name) and target.id == spec.constant
                    for target in node.targets)):
            assignment = node
            break
    if assignment is None:
        raise TranslationError(f"AST-присваивание {spec.symbol} не найдено")
    blob = bytes(int(value in values) for value in spec.domain.values)
    return blob, {
        "symbol": spec.symbol,
        "asm_name": spec.asm_name,
        "element": "u8",
        "dimensions": [len(spec.domain.values)],
        "arguments": [{
            "name": spec.domain.name,
            "first": spec.domain.values[0],
            "last": spec.domain.values[-1],
        }],
        "entries": len(blob),
        "ast_sha256": hashlib.sha256(
            ast.dump(assignment, include_attributes=False).encode("utf-8")).hexdigest(),
        "data_sha256": hashlib.sha256(blob).hexdigest(),
    }


def lifecycle_constant_contract(trees: dict[str, ast.Module]) -> list[dict[str, Any]]:
    """Extract the player lifecycle literally from the launched Python graph."""
    module = "rtype_port.player_lifecycle"
    tree = trees.get(module)
    if tree is None:
        raise TranslationError(f"модуль lifecycle не достижим: {module}")
    constants = module_constants(tree)
    result: list[dict[str, Any]] = []
    for name, asm_name, minimum, maximum in LIFECYCLE_CONSTANT_SPECS:
        value = constants.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TranslationError(
                f"{module}.{name} не является целой AST-константой")
        if not minimum <= value <= maximum:
            raise TranslationError(
                f"{module}.{name}={value} вне диапазона {minimum}…{maximum}")
        assignment = next((
            node for node in tree.body
            if ((isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == name
                         for target in node.targets))
                or (isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == name))
        ), None)
        if assignment is None:
            raise TranslationError(f"AST-присваивание {module}.{name} не найдено")
        result.append({
            "symbol": f"{module}.{name}",
            "asm_name": asm_name,
            "value": value,
            "ast_sha256": hashlib.sha256(
                ast.dump(assignment, include_attributes=False).encode("utf-8")
            ).hexdigest(),
        })
    values = {item["symbol"].rsplit(".", 1)[1]: item["value"]
              for item in result}
    if values["INITIAL_LIVES"] > values["MAX_LIVES"]:
        raise TranslationError("Python INITIAL_LIVES превышает MAX_LIVES")
    if not (values["PLAYER_CLEAR_AGE"] < values["LIFE_DECREMENT_AGE"] <
            values["RESPAWN_AGE"]):
        raise TranslationError("нарушен порядок возрастов Python lifecycle")
    return result


def decorated_with_dataclass(node: ast.ClassDef) -> bool:
    return any(
        (isinstance(item, ast.Name) and item.id == "dataclass")
        or (isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "dataclass")
        for item in node.decorator_list
    )


def annotation_text(node: ast.AST) -> str:
    return ast.unparse(node)


def inventory(trees: dict[str, ast.Module], translated: dict[str, str]
              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    schemas: list[dict[str, Any]] = []
    for module, tree in sorted(trees.items()):
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = f"{module}.{node.name}"
                symbols.append({
                    "symbol": symbol,
                    "line": node.lineno,
                    "status": translated.get(symbol, "pending"),
                })
            elif isinstance(node, ast.ClassDef):
                if decorated_with_dataclass(node):
                    fields = []
                    for field in node.body:
                        if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name):
                            fields.append({
                                "name": field.target.id,
                                "type": annotation_text(field.annotation),
                                "has_default": field.value is not None,
                            })
                    schemas.append({"symbol": f"{module}.{node.name}", "fields": fields})
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbol = f"{module}.{node.name}.{child.name}"
                        symbols.append({
                            "symbol": symbol,
                            "line": child.lineno,
                            "status": translated.get(symbol, "pending"),
                        })
    return symbols, schemas


def source_manifest(paths: dict[str, Path], trees: dict[str, ast.Module]) -> list[dict[str, Any]]:
    result = []
    for module in sorted(trees):
        path = paths[module]
        data = path.read_bytes()
        result.append({
            "module": module,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return result


def _project_path(path: Path) -> str:
    """Return a stable report path without assuming a test output is in ROOT."""
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def frame_budget_contract(
        frame_render_plan: dict[str, Any], project_root: Path = ROOT,
        certificate_path: Path | None = None,
        ) -> dict[str, Any]:
    """Audit the final generated surfaces against the whole-frame FT812 gate."""
    render_path = project_root / "Source" / "ASM" / "render.asm"
    if certificate_path is None:
        certificate_path = (
            project_root / "Build" / "rtype_python_frame_budget.json")
    requirements = contract_requirements(project_root, render_path)
    status = current_budget_status(
        project_root, render_path, certificate_path)
    if not isinstance(status, dict):
        raise TranslationError("frame budget gate did not return an object")

    plan_hash_keys = (
        "format", "source_path", "source_sha256", "launcher_sha256",
        "method_ast_sha256", "sink_order_sha256", "semantic_sha256",
    )
    required_plan = requirements.get("frame_render_plan")
    if (not isinstance(required_plan, dict) or
            any(required_plan.get(key) != frame_render_plan.get(key)
                for key in plan_hash_keys)):
        raise TranslationError(
            "whole-frame FT812 requirements are not bound to the current "
            "source-derived Game.render plan")
    if (status.get("format") !=
            "pyz80-ft812-frame-fragment-budget-status-v2" or
            status.get("contract_format_required") !=
            FRAME_BUDGET_CONTRACT_FORMAT or
            status.get("contract_path") != str(certificate_path.resolve()) or
            status.get("source_program") != requirements.get("source_program") or
            status.get("frame_render_plan") != required_plan or
            status.get("bindings") != requirements.get("bindings") or
            status.get("insertion") != requirements.get("insertion")):
        raise TranslationError(
            "whole-frame FT812 status is stale against final generated "
            "Python/ASM/C surfaces")

    gate_status = status.get("status")
    if gate_status not in {
            "BLOCKED_MISSING_TRANSLATOR_CERTIFICATE",
            "BLOCKED_INVALID_TRANSLATOR_CERTIFICATE", "PASS"}:
        raise TranslationError(
            f"unknown whole-frame FT812 budget status: {gate_status!r}")
    if not isinstance(status.get("live_target_lowering_present"), bool):
        raise TranslationError(
            "whole-frame FT812 budget omitted live-lowering state")
    if gate_status == "PASS":
        if (status.get("full_frame_proved") is not True or
                not isinstance(status.get("remaining_dl_words"), int) or
                not isinstance(status.get("report"), dict)):
            raise TranslationError(
                "whole-frame FT812 PASS omitted its complete proof")
    elif (status.get("full_frame_proved") is not False or
          status.get("remaining_dl_words") is not None or
          ("blockers" not in status and "diagnostic" not in status)):
        raise TranslationError(
            "blocked whole-frame FT812 status omitted its evidence")
    return status


def validate_frame_sprite_fragment_envelope(
        report: dict[str, Any], frame_record_bound: dict[str, Any],
        draw_plan: dict[str, Any], hq_assets: dict[str, Any],
        ) -> dict[str, Any]:
    """Accept only a complete weighted join or an explicit blocked join.

    This gate prevents the whole-frame budget from using ``record_count``
    times a guessed/global template maximum.  Missing reachable HQT3 keys
    must keep every weighted/raster maximum unset.
    """
    if report.get("format") != FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT:
        raise TranslationError("sprite-fragment envelope format changed")
    semantic_sha256 = report.get("semantic_sha256")
    if (not isinstance(semantic_sha256, str) or
            re.fullmatch(r"[0-9a-f]{64}", semantic_sha256) is None):
        raise TranslationError("sprite-fragment envelope hash is malformed")
    semantic_payload = dict(report)
    semantic_payload.pop("semantic_sha256", None)
    actual_semantic = hashlib.sha256(json.dumps(
        semantic_payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    if actual_semantic != semantic_sha256:
        raise TranslationError(
            "sprite-fragment envelope semantic hash is inconsistent")

    proof_complete = report.get("proof_complete")
    can_size = report.get("can_size_sprite_fragment")
    if (not isinstance(proof_complete, bool) or
            can_size is not proof_complete or
            report.get("frame_budget_contract_pass") is not False or
            report.get("prepublication_certified") is not False or
            report.get("atomic_commit_certified") is not False or
            report.get("live_eligible") is not False):
        raise TranslationError(
            "sprite-fragment envelope proof/live state is inconsistent")

    record = report.get("record_envelope")
    certified_records = frame_record_bound.get(
        "certified_frame_max_records")
    object_records = frame_record_bound.get("object_multiplicity", {}).get(
        "source_derived_abstract_upper_bound")
    transient_records = frame_record_bound.get("transients", {}).get(
        "source_derived_finite_upper_bound")
    if not isinstance(record, dict):
        raise TranslationError("sprite-fragment record envelope is missing")
    capacity = record.get("chunk_capacity")
    records = record.get("certified_frame_max_records")
    chunks = record.get("max_chunks")
    if (not isinstance(records, int) or isinstance(records, bool) or
            records != certified_records or records < 0 or records > 0xFFFF or
            record.get("object_records") != object_records or
            record.get("transient_records") != transient_records or
            not isinstance(capacity, int) or isinstance(capacity, bool) or
            not 1 <= capacity <= 128 or
            chunks != ((records + capacity - 1) // capacity if records else 0) or
            record.get("chunk_capacity_target_max") != 128):
        raise TranslationError(
            "sprite-fragment envelope disagrees with the frame-record proof")

    bindings = report.get("input_bindings")
    bound_plan = bindings.get("draw_plan") if isinstance(bindings, dict) else None
    if (not isinstance(bindings, dict) or not isinstance(bound_plan, dict) or
            bound_plan.get("source_sha256") != draw_plan.get("source_sha256") or
            bound_plan.get("semantic_sha256") !=
            draw_plan.get("semantic_sha256")):
        raise TranslationError(
            "sprite-fragment envelope is stale against DrawPlan")

    template_metrics = report.get("template_metrics")
    artifacts = hq_assets.get("artifacts")
    sprite_artifacts = [
        item for item in artifacts
        if isinstance(item, dict) and
        item.get("kind") == "sprite-bootstrap-working-set"
    ] if isinstance(artifacts, list) else []
    template_report = (
        sprite_artifacts[0].get("templates")
        if len(sprite_artifacts) == 1 else None)
    if (not isinstance(template_metrics, dict) or
            not isinstance(template_report, dict) or
            template_metrics.get("template_count") !=
            template_report.get("record_count") or
            not isinstance(template_metrics.get("domain_sha256"), str) or
            not isinstance(
                template_metrics.get("max_append_words_in_generated_set"), int) or
            not isinstance(
                template_metrics.get("max_raster_peak_in_generated_set"), int)):
        raise TranslationError(
            "sprite-fragment envelope is stale against generated HQT3")

    witnesses = report.get("class_action_witnesses")
    transient_witnesses = report.get("transient_composition_witnesses")
    scope = report.get("proof_scope")
    gates = report.get("integration_gates")
    if (not isinstance(witnesses, list) or not witnesses or
            not isinstance(transient_witnesses, list) or
            not transient_witnesses or not isinstance(scope, dict) or
            scope.get("uses_global_template_max_times_frame_records")
            is not False or
            scope.get("transients_accounted_separately") is not True or
            scope.get("whole_frame_record_array_required") is not False or
            not isinstance(gates, list) or len(gates) != 1 or
            not isinstance(gates[0], dict) or
            gates[0].get("code") != "PZFSFE201" or
            gates[0].get("satisfied") is not False):
        raise TranslationError(
            "sprite-fragment weighted proof scope/integration gate changed")

    blockers = report.get("blockers")
    weighted = report.get("weighted_display_list")
    raster = report.get("raster_envelope")
    if (not isinstance(blockers, list) or not isinstance(weighted, dict) or
            not isinstance(raster, dict) or raster.get("height") != 768):
        raise TranslationError(
            "sprite-fragment envelope result sections are malformed")
    blocker_codes = [
        item.get("code") for item in blockers if isinstance(item, dict)
    ]
    if (len(blocker_codes) != len(blockers) or
            len(set(blocker_codes)) != len(blocker_codes) or
            any(not isinstance(code, str) or not code
                for code in blocker_codes)):
        raise TranslationError(
            "sprite-fragment envelope blockers are malformed")

    if proof_complete:
        append_words = weighted.get("max_cmd_append_expanded_words")
        expanded_words = weighted.get("max_fragment_expanded_dl_words")
        raster_lines = raster.get("max_raster_cycles_by_line")
        if (report.get("status") !=
                "READY_CONSERVATIVE_ENVELOPE_PREPUBLICATION_BLOCKED" or
                blockers or
                weighted.get("bound_kind") !=
                "source_derived_conservative_upper_bound" or
                not isinstance(append_words, int) or
                isinstance(append_words, bool) or append_words < 0 or
                not isinstance(expanded_words, int) or
                isinstance(expanded_words, bool) or
                expanded_words != chunks * 13 + records * 2 + append_words or
                not isinstance(raster_lines, list) or len(raster_lines) != 768 or
                any(not isinstance(value, int) or isinstance(value, bool) or
                    value < 0 for value in raster_lines) or
                raster.get("worst_line_raster_cycles") != max(raster_lines) or
                raster.get("max_raster_cycles_by_line_sha256") !=
                hashlib.sha256(json.dumps(
                    raster_lines, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")).encode("utf-8")).hexdigest()):
            raise TranslationError(
                "complete sprite-fragment envelope arithmetic is inconsistent")
    else:
        if (report.get("status") !=
                "BLOCKED_UNMAPPED_REACHABLE_TEMPLATE" or not blockers or
                weighted.get("bound_kind") is not None or
                any(weighted.get(name) is not None for name in (
                    "max_cmd_append_expanded_words",
                    "object_cmd_append_expanded_words",
                    "transient_cmd_append_expanded_words",
                    "max_fragment_expanded_dl_words")) or
                raster.get("max_raster_cycles_by_line") is not None or
                raster.get("max_raster_cycles_by_line_sha256") is not None or
                raster.get("worst_line_raster_cycles") is not None):
            raise TranslationError(
                "blocked sprite-fragment envelope leaked optimistic maxima")
    return report


def frame_sprite_fragment_envelope_contract(
        frame_record_bound: dict[str, Any],
        sprite_coverage: CoverageReport,
        draw_plan: SpriteDrawPlanIR,
        hq_assets: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Build and validate the weighted active-Python sprite-frame envelope."""
    try:
        envelope = analyze_frame_sprite_fragment_envelope(
            project_root,
            record_bound_report=frame_record_bound,
            coverage_report=sprite_coverage,
            assets_manifest=hq_assets,
            draw_plan=draw_plan,
        )
    except (FrameSpriteFragmentEnvelopeError, OSError, ValueError) as exc:
        raise TranslationError(
            f"sprite-fragment envelope failed: {exc}") from exc
    report = envelope.as_dict()
    return validate_frame_sprite_fragment_envelope(
        report, frame_record_bound, draw_plan.as_dict(), hq_assets)


def validate_draw_target_bundle_certificate(
        certificate: dict[str, Any]) -> dict[str, Any]:
    """Validate the one-link C target measurement before trusting it.

    Per-object sizes are not a link certificate.  This gate accepts only the
    report produced from one pinned-SDCC image containing render order,
    persistent state, the compact VM and the FT812 fast path together.
    """
    if (certificate.get("format") != DRAW_TARGET_BUNDLE_FORMAT or
            certificate.get("status") != DRAW_TARGET_BUNDLE_STATUS):
        raise TranslationError(
            "draw target bundle certificate format/status changed")

    checks = certificate.get("checks")
    required_true = (
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
    if (not isinstance(checks, dict) or
            any(checks.get(name) is not True for name in required_true)):
        raise TranslationError(
            "draw target bundle omitted a required linked/static proof")

    link = certificate.get("link")
    code = link.get("code") if isinstance(link, dict) else None
    data = link.get("data") if isinstance(link, dict) else None
    placement = link.get("placement") if isinstance(link, dict) else None
    if not all(isinstance(item, dict) for item in (link, code, data, placement)):
        raise TranslationError("draw target bundle link layout is malformed")
    assert isinstance(code, dict)
    assert isinstance(data, dict)
    assert isinstance(placement, dict)
    code_bytes = code.get("bytes")
    bank_bytes = code.get("bank_bytes")
    banks_required = code.get("banks_required")
    overflow = code.get("single_bank_overflow_bytes")
    data_bytes = data.get("bytes")
    cache_bytes = data.get("expected_private_fast_cache_bytes")
    integers = (
        code_bytes, bank_bytes, banks_required, overflow,
        data_bytes, cache_bytes,
    )
    if any(not isinstance(value, int) or isinstance(value, bool)
           for value in integers):
        raise TranslationError("draw target bundle sizes are not integers")
    assert isinstance(code_bytes, int)
    assert isinstance(bank_bytes, int)
    assert isinstance(banks_required, int)
    assert isinstance(overflow, int)
    assert isinstance(data_bytes, int)
    assert isinstance(cache_bytes, int)
    if (code_bytes <= 0 or bank_bytes != 0x4000 or
            banks_required != (code_bytes + bank_bytes - 1) // bank_bytes or
            code.get("fits_one_bank") is not (banks_required == 1) or
            overflow != max(0, code_bytes - bank_bytes) or
            data_bytes != cache_bytes or data_bytes <= 0):
        raise TranslationError(
            "draw target bundle code/data bank arithmetic is inconsistent")
    if (checks.get("single_16k_code_bank_fit") is not
            (banks_required == 1) or
            checks.get("code_data_ranges_do_not_overlap") is not
            (placement.get("code_data_overlap") is False) or
            checks.get("cross_bank_link_adapter_proved") is not
            (placement.get("cross_bank_link_adapter_proved") is True)):
        raise TranslationError(
            "draw target bundle placement checks disagree with the link map")

    stack = certificate.get("stack")
    if not isinstance(stack, dict):
        raise TranslationError("draw target bundle stack report is missing")
    known_stack = stack.get("maximum_known_candidate_bytes")
    stack_budget = stack.get("target_stack_budget_bytes")
    stack_headroom = stack.get("known_candidate_headroom_bytes")
    if (not isinstance(known_stack, int) or isinstance(known_stack, bool) or
            not isinstance(stack_budget, int) or isinstance(stack_budget, bool) or
            not isinstance(stack_headroom, int) or isinstance(stack_headroom, bool) or
            known_stack < 0 or stack_budget <= 0 or
            stack_headroom != stack_budget - known_stack or
            stack_headroom < 0 or
            checks.get("complete_external_callback_stack_bound") is not
            (stack.get("complete_bound_certified") is True)):
        raise TranslationError(
            "draw target bundle stack arithmetic/certification is inconsistent")

    publication = certificate.get("frame_publication_contract")
    required_publication = (
        publication.get("required")
        if isinstance(publication, dict) else None)
    if (not isinstance(publication, dict) or
            publication.get("required_contract_format") !=
            FRAME_BUDGET_CONTRACT_FORMAT or
            not isinstance(required_publication, dict) or
            any(required_publication.get(name) is not True for name in (
                "complete_record_count_preflight",
                "complete_template_lookup_preflight",
                "complete_append_budget_preflight",
                "no_queue_fragment_ready_before_preflight",
                "atomic_complete_frame_commit",
            ))):
        raise TranslationError(
            "draw target bundle is not bound to the v4 publication contract")

    live = certificate.get("live")
    blockers = certificate.get("live_blockers")
    if not isinstance(live, bool) or not isinstance(blockers, list):
        raise TranslationError("draw target bundle live state is malformed")
    blocker_codes = [
        item.get("code") for item in blockers if isinstance(item, dict)
    ]
    if (len(blocker_codes) != len(blockers) or
            len(set(blocker_codes)) != len(blocker_codes) or
            (live and blockers) or (not live and not blockers)):
        raise TranslationError(
            "draw target bundle live blockers are inconsistent")
    return certificate


def draw_target_bundle_contract(
        project_root: Path = ROOT) -> dict[str, Any]:
    """Regenerate, link and validate the selected draw target as one image."""
    try:
        certificate = probe_draw_target_bundle(project_root)
    except (DrawTargetBundleError, OSError, ValueError) as exc:
        raise TranslationError(
            f"draw target linked-bundle certificate failed: {exc}") from exc
    if not isinstance(certificate, dict):
        raise TranslationError(
            "draw target linked-bundle probe did not return an object")
    return validate_draw_target_bundle_certificate(certificate)


def validate_draw_bank_placement_certificate(
        certificate: dict[str, Any],
        draw_target_bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate the two real slot-2 links and their resident bank gate.

    The preceding unsplit link proves which active-source objects belong to
    the draw target.  This certificate must bind that exact measurement to
    two independently linked 16 KiB images and to non-overlapping resident
    page-00 storage.  Free pages alone are not live integration evidence.
    """
    if (certificate.get("format") != DRAW_BANK_PLACEMENT_FORMAT or
            certificate.get("status") != DRAW_BANK_PLACEMENT_STATUS):
        raise TranslationError(
            "draw bank placement certificate format/status changed")

    semantic_sha256 = certificate.get("semantic_sha256")
    if (not isinstance(semantic_sha256, str) or
            re.fullmatch(r"[0-9a-f]{64}", semantic_sha256) is None):
        raise TranslationError(
            "draw bank placement semantic hash is malformed")

    checks = certificate.get("checks")
    required_true = (
        "unsplit_active_source_bundle_status_bound",
        "unsplit_code_17137_data_1280_measured",
        "two_actual_pinned_sdcc_links_completed",
        "each_code_link_fits_one_16k_slot2_bank",
        "physical_pages_f1_f2_free_in_current_packer",
        "mutable_cache_exactly_page00_0b00_1000",
        "resident_page00_ranges_nonoverlapping",
        "ft812_queues_remain_ed_ee_c000",
        "ft812_record_tail_remains_ca44_ffff",
        "ft812_template_page_ef_reserved",
        "cross_bank_edge_count_exactly_one",
        "sdcccall0_tail_stack_shape_preserved",
        "callee_entry_linked_at_8000",
        "resident_gate_assembled_and_fits",
    )
    required_false = (
        "real_final_link_proved",
        "production_packer_binding_proved",
        "live_callback_binding_proved",
        "isr_preemption_composition_proved",
    )
    if (not isinstance(checks, dict) or
            any(checks.get(name) is not True for name in required_true) or
            any(checks.get(name) is not False for name in required_false)):
        raise TranslationError(
            "draw bank placement omitted a required static/live proof")

    unsplit = certificate.get("unsplit_source_derived_bundle")
    target_link = draw_target_bundle.get("link")
    target_code = target_link.get("code") if isinstance(target_link, dict) else None
    target_data = target_link.get("data") if isinstance(target_link, dict) else None
    if (not isinstance(unsplit, dict) or
            not isinstance(target_code, dict) or
            not isinstance(target_data, dict) or
            unsplit.get("status_path") !=
            "Build/rtype_python_draw_target_bundle_status.json" or
            unsplit.get("code_bytes") != target_code.get("bytes") or
            unsplit.get("data_bytes") != target_data.get("bytes") or
            unsplit.get("live") is not draw_target_bundle.get("live")):
        raise TranslationError(
            "draw bank placement is not bound to the unsplit target bundle")

    memory = certificate.get("memory")
    if not isinstance(memory, dict):
        raise TranslationError("draw bank placement memory report is missing")
    banks = memory.get("draw_code_banks")
    bank_pages = (
        [item.get("page_hex") for item in banks]
        if isinstance(banks, list) and
        all(isinstance(item, dict) for item in banks) else None
    )
    existing = memory.get("existing_compiler_page")
    if (memory.get("physical_page_bytes") != 0x4000 or
            memory.get("physical_page_count") != 256 or
            memory.get("physical_ram_bytes") != 4 * 1024 * 1024 or
            bank_pages != ["0xF1", "0xF2"] or
            not isinstance(existing, dict) or
            existing.get("page_hex") != "0xF0" or
            existing.get("artifact") != "Build/python_compiled_p00.bin" or
            existing.get("bytes") != 0x4000):
        raise TranslationError(
            "draw bank placement physical-page layout changed")

    intervals = memory.get("resident_intervals")
    expected_intervals = {
        "existing_ft812_bridge": (0x0500, 0x07A0),
        "draw_cross_bank_gate": (0x07A0, 0x0B00),
        "ft812_batch_cache": (0x0B00, 0x1000),
        "coordinate_tables": (0x1000, 0x2000),
        "resident_tables": (0x2000, 0x4000),
    }
    if (not isinstance(intervals, list) or
            len(intervals) != len(expected_intervals) or
            {row.get("name") for row in intervals if isinstance(row, dict)} !=
            set(expected_intervals)):
        raise TranslationError(
            "draw bank placement resident interval set changed")
    previous_end = 0
    for row in intervals:
        if not isinstance(row, dict) or row.get("name") not in expected_intervals:
            raise TranslationError(
                "draw bank placement resident interval is malformed")
        limit_start, limit_end = expected_intervals[str(row["name"])]
        try:
            start = int(str(row.get("start_hex")), 16)
            end = int(str(row.get("end_exclusive_hex")), 16)
        except (TypeError, ValueError) as exc:
            raise TranslationError(
                "draw bank placement resident interval address is malformed") from exc
        size = row.get("bytes")
        if (not isinstance(size, int) or isinstance(size, bool) or
                start < limit_start or end > limit_end or end - start != size or
                start < previous_end):
            raise TranslationError(
                "draw bank placement resident intervals overlap or overflow")
        previous_end = end

    storage = certificate.get("ft812_storage")
    cache = storage.get("batch_cache") if isinstance(storage, dict) else None
    queue = storage.get("queue_vma") if isinstance(storage, dict) else None
    tail = storage.get("record_tail") if isinstance(storage, dict) else None
    if (not isinstance(storage, dict) or
            storage.get("queue_pages") != ["0xED", "0xEE"] or
            storage.get("command_template_page_hex") != "0xEF" or
            not isinstance(cache, dict) or
            (cache.get("physical_page_hex"), cache.get("start_hex"),
             cache.get("end_exclusive_hex"), cache.get("bytes"),
             cache.get("always_mapped")) !=
            ("0x00", "0x0B00", "0x1000", 1280, True) or
            not isinstance(queue, dict) or
            (queue.get("start_hex"), queue.get("end_exclusive_hex"),
             queue.get("bytes")) != ("0xC000", "0x10000", 0x4000) or
            not isinstance(tail, dict) or
            (tail.get("start_hex"), tail.get("end_exclusive_hex"),
             tail.get("bytes")) != ("0xCA44", "0x10000", 0x35BC)):
        raise TranslationError("draw bank placement FT812 storage changed")

    links = certificate.get("links")
    if not isinstance(links, dict):
        raise TranslationError("draw bank placement linked images are missing")
    for name in ("page_f1", "page_f2"):
        link = links.get(name)
        code = link.get("code") if isinstance(link, dict) else None
        if not isinstance(code, dict):
            raise TranslationError(
                f"draw bank placement {name} code report is missing")
        size = code.get("bytes")
        headroom = code.get("headroom_bytes")
        try:
            origin = int(str(code.get("origin_hex")), 16)
            end = int(str(code.get("end_exclusive_hex")), 16)
        except (TypeError, ValueError) as exc:
            raise TranslationError(
                f"draw bank placement {name} address is malformed") from exc
        if (not isinstance(size, int) or isinstance(size, bool) or
                not isinstance(headroom, int) or isinstance(headroom, bool) or
                size <= 0 or size > 0x4000 or origin != 0x8000 or
                end != origin + size or headroom != 0x4000 - size or
                code.get("fits_one_bank") is not True):
            raise TranslationError(
                f"draw bank placement {name} does not fit one slot-2 bank")
    page_f1 = links["page_f1"]
    page_f2 = links["page_f2"]
    f1_data = page_f1.get("data")
    f2_data = page_f2.get("data")
    f2_symbols = page_f2.get("public_symbols")
    if (not isinstance(f1_data, dict) or f1_data.get("bytes") != 0 or
            not isinstance(f2_data, dict) or
            (f2_data.get("bytes"), f2_data.get("origin_hex"),
             f2_data.get("end_exclusive_hex")) !=
            (1280, "0x0B00", "0x1000") or
            not isinstance(f2_symbols, dict) or
            f2_symbols.get("_PyZ80DrawBank1_BuildSpriteBatchFast") !=
            "0x8000" or
            f2_symbols.get("_PyZ80FT_BatchResolved") != "0x0B00"):
        raise TranslationError(
            "draw bank placement data/entry symbols are inconsistent")

    partition = certificate.get("source_partition")
    edges = partition.get("cross_bank_edges") if isinstance(partition, dict) else None
    if (not isinstance(partition, dict) or
            partition.get("hot_record_lookup_kept_in_caller_bank") is not True or
            not isinstance(edges, list) or len(edges) != 1 or
            not isinstance(edges[0], dict) or
            (edges[0].get("from_page_hex"), edges[0].get("to_page_hex"),
             edges[0].get("callee_entry_address_hex")) !=
            ("0xF1", "0xF2", "0x8000")):
        raise TranslationError(
            "draw bank placement cross-bank edge is inconsistent")

    gate = certificate.get("resident_gate")
    if not isinstance(gate, dict):
        raise TranslationError("draw bank placement resident gate is missing")
    gate_size = gate.get("bytes")
    gate_headroom = gate.get("headroom_bytes")
    try:
        gate_start = int(str(gate.get("origin_hex")), 16)
        gate_end = int(str(gate.get("end_exclusive_hex")), 16)
    except (TypeError, ValueError) as exc:
        raise TranslationError(
            "draw bank placement resident gate address is malformed") from exc
    if (not isinstance(gate_size, int) or isinstance(gate_size, bool) or
            not isinstance(gate_headroom, int) or
            isinstance(gate_headroom, bool) or gate_start != 0x07A0 or
            gate_end != gate_start + gate_size or gate_end > 0x0B00 or
            gate_headroom != 0x0B00 - gate_end):
        raise TranslationError(
            "draw bank placement resident gate overflows its window")

    final_binding = certificate.get("final_binding_evidence")
    live = certificate.get("live")
    blockers = certificate.get("live_blockers")
    if (not isinstance(final_binding, dict) or
            final_binding.get("proved") is not False or live is not False or
            not isinstance(blockers, list) or not blockers):
        raise TranslationError(
            "draw bank placement final-binding/live state is inconsistent")
    blocker_codes = [
        item.get("code") for item in blockers if isinstance(item, dict)
    ]
    if (len(blocker_codes) != len(blockers) or
            len(set(blocker_codes)) != len(blocker_codes) or
            any(not isinstance(code, str) or not code for code in blocker_codes)):
        raise TranslationError(
            "draw bank placement live blockers are malformed")
    return certificate


def draw_bank_placement_contract(
        draw_target_bundle: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Regenerate and validate the real F1/F2 draw-bank placement."""
    try:
        certificate = probe_draw_bank_placement(project_root)
    except (DrawBankPlacementError, DrawTargetBundleError,
            OSError, ValueError) as exc:
        raise TranslationError(
            f"draw-bank placement certificate failed: {exc}") from exc
    if not isinstance(certificate, dict):
        raise TranslationError(
            "draw-bank placement probe did not return an object")
    return validate_draw_bank_placement_certificate(
        certificate, draw_target_bundle)


def validate_mutation_hook_ir(
        report: dict[str, Any],
        draw_state_backend: dict[str, Any]) -> dict[str, Any]:
    """Bind complete source mutation coverage to the persistent sidecar."""
    if (report.get("format") != MUTATION_HOOK_IR_FORMAT or
            report.get("status") !=
            "TARGET_NEUTRAL_HOOK_IR_COMPLETE_LIVE_BLOCKED" or
            report.get("live") is not False):
        raise TranslationError(
            "mutation hook IR format/status/live state changed")

    source = report.get("source")
    state_source = draw_state_backend.get("active_source")
    if (not isinstance(source, dict) or
            not isinstance(state_source, dict) or
            source.get("launcher") != state_source.get("launcher") or
            source.get("entrypoint") != state_source.get("entrypoint") or
            source.get("launcher_sha256") !=
            state_source.get("launcher_sha256") or
            source.get("path") != state_source.get("module") or
            source.get("sha256") != state_source.get("module_sha256") or
            report.get("pinned_draw_state_semantic_sha256") !=
            draw_state_backend.get("semantic_sha256")):
        raise TranslationError(
            "mutation hook IR is stale against the active sidecar/source")

    hooks = report.get("mutation_hooks")
    derived = report.get("derived_fields")
    dynamic = report.get("dynamic_setattrs")
    lifecycle = report.get("lifecycle_hooks")
    coverage = report.get("coverage")
    counts = coverage.get("counts") if isinstance(coverage, dict) else None
    programs = derived.get("programs") if isinstance(derived, dict) else None
    dispatch = (
        derived.get("class_id_to_program_id")
        if isinstance(derived, dict) else None)
    read_sites = (
        derived.get("read_sites") if isinstance(derived, dict) else None)
    sequences = (hooks, programs, dispatch, read_sites, dynamic, lifecycle)
    if (not all(isinstance(value, list) for value in sequences) or
            not isinstance(coverage, dict) or not isinstance(counts, dict)):
        raise TranslationError("mutation hook IR inventories are malformed")
    assert isinstance(hooks, list)
    assert isinstance(programs, list)
    assert isinstance(dispatch, list)
    assert isinstance(read_sites, list)
    assert isinstance(dynamic, list)
    assert isinstance(lifecycle, list)
    expected_counts = {
        "direct_and_implicit_candidates": len(hooks),
        "direct_and_implicit_lowered": len(hooks),
        "derived_getter_candidates": len(programs),
        "derived_getter_programs": len(programs),
        "derived_read_candidates": len(read_sites),
        "derived_reads_lowered": len(read_sites),
        "dynamic_setattr_candidates": len(dynamic),
        "dynamic_setattrs_lowered": len(dynamic),
        "lifecycle_identity_candidates": len(lifecycle),
        "lifecycle_identities_lowered": len(lifecycle),
    }
    if any(counts.get(name) != value
           for name, value in expected_counts.items()):
        raise TranslationError("mutation hook IR coverage counts disagree")
    runtime_hooks = counts.get("direct_runtime_sync_hooks")
    schema_fields = counts.get("implicit_bind_schema_fields")
    disjoint_setattrs = counts.get("dynamic_setattrs_proved_disjoint")
    if (not isinstance(runtime_hooks, int) or
            not isinstance(schema_fields, int) or
            runtime_hooks + schema_fields != len(hooks) or
            disjoint_setattrs != len(dynamic) or
            coverage.get("complete_ast_coverage") is not True or
            coverage.get("independent_census_matches_draw_state") is not True or
            coverage.get("all_mutation_site_ids_unique") is not True or
            coverage.get("all_derived_program_ids_unique") is not True or
            coverage.get("derived_dispatch_entries") != len(dispatch) or
            coverage.get("manual_object_type_switch") is not False or
            coverage.get(
                "physical_slot_normalization_source_derived") is not True or
            coverage.get("gameplay_source_modified") is not False or
            coverage.get("runtime_hooks_installed") is not False or
            coverage.get("live_claimed") is not False or
            derived.get("manual_object_type_switch") is not False):
        raise TranslationError(
            "mutation hook IR completeness/source-derivation proof changed")

    slot = report.get("slot_normalization")
    slot_count = draw_state_backend.get(
        "persistent_state", {}).get("slot_count")
    if (not isinstance(slot, dict) or
            slot.get("hook_representation") != "compact uint8 slot index" or
            slot.get("slot_count") != slot_count or
            slot.get("source_derived") is not True or
            not isinstance(slot.get("physical_first"), int) or
            not isinstance(slot.get("physical_stop_exclusive"), int) or
            not isinstance(slot.get("physical_stride"), int) or
            slot["physical_stride"] <= 0 or
            (slot["physical_stop_exclusive"] - slot["physical_first"]) %
            slot["physical_stride"] != 0 or
            (slot["physical_stop_exclusive"] - slot["physical_first"]) //
            slot["physical_stride"] != slot_count):
        raise TranslationError(
            "mutation hook IR physical-slot normalization is inconsistent")

    frontend = report.get("frontend_integration_contract")
    blockers = report.get("live_blockers")
    if (not isinstance(frontend, dict) or
            frontend.get(
                "current_frontend_supports_full_object_gameplay_cfg")
            is not False or
            frontend.get("current_frontend_supports_object_store_fragments")
            is not True or
            frontend.get("current_pipeline_consumes_this_ir") is not False or
            not isinstance(blockers, list) or not blockers or
            not all(isinstance(item, str) and item for item in blockers)):
        raise TranslationError(
            "mutation hook IR omitted its live integration blockers")
    return report


def build_mutation_hook_ir_stage(
        draw_state_backend: dict[str, Any],
        project_root: Path = ROOT,
        ) -> tuple[MutationHookPlan, dict[str, Any]]:
    """Regenerate the hook plan once and retain it for downstream lowering."""
    try:
        plan = build_mutation_hook_ir(project_root)
    except MutationHookIRError as exc:
        raise TranslationError(f"mutation hook IR failed: {exc}") from exc
    report = plan.as_dict()
    if not isinstance(report, dict):
        raise TranslationError("mutation hook IR did not return an object")
    return plan, validate_mutation_hook_ir(report, draw_state_backend)


def mutation_hook_ir_contract(
        draw_state_backend: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Compatibility wrapper returning the validated hook report."""
    return build_mutation_hook_ir_stage(
        draw_state_backend, project_root)[1]


def validate_object_store_ir(
        report: dict[str, Any], mutation_hook_ir: dict[str, Any],
        ) -> dict[str, Any]:
    """Require one ordered effect-SSA fragment for every runtime hook."""
    if (report.get("format") != OBJECT_STORE_IR_FORMAT or
            report.get("status") !=
            "OBJECT_STORE_EXPRESSION_CFG_COMPLETE_LIVE_BLOCKED" or
            report.get("live") is not False or
            report.get("mutation_hook_semantic_sha256") !=
            mutation_hook_ir.get("semantic_sha256")):
        raise TranslationError(
            "object-store IR format/status/hook binding changed")
    source = report.get("source")
    hook_source = mutation_hook_ir.get("source")
    if (not isinstance(source, dict) or not isinstance(hook_source, dict) or
            source.get("path") != hook_source.get("path") or
            source.get("sha256") != hook_source.get("sha256")):
        raise TranslationError(
            "object-store IR is stale against active mutation hooks")

    fragments = report.get("fragments")
    schema_ids = report.get("bind_schema_site_ids")
    coverage = report.get("coverage")
    hook_rows = mutation_hook_ir.get("mutation_hooks")
    if (not isinstance(fragments, list) or
            not isinstance(schema_ids, list) or
            not isinstance(coverage, dict) or
            not isinstance(hook_rows, list)):
        raise TranslationError("object-store IR inventories are malformed")
    runtime_rows = [
        row for row in hook_rows
        if isinstance(row, dict) and row.get("runtime_hook_required") is True
    ]
    schema_rows = [
        row for row in hook_rows
        if isinstance(row, dict) and row.get("runtime_hook_required") is False
    ]
    runtime_ids = [row.get("site_id") for row in runtime_rows]
    fragment_ids = [
        row.get("site_id") for row in fragments if isinstance(row, dict)
    ]
    expected_schema_ids = [row.get("site_id") for row in schema_rows]
    if (len(runtime_rows) + len(schema_rows) != len(hook_rows) or
            len(fragment_ids) != len(fragments) or
            fragment_ids != runtime_ids or schema_ids != expected_schema_ids or
            len(set(fragment_ids + schema_ids)) != len(hook_rows)):
        raise TranslationError(
            "object-store IR does not cover each mutation hook exactly once")

    expression_program_ids: set[str] = set()
    expression_op_counts: Counter[str] = Counter()
    expression_block_count = 0
    expression_branch_count = 0
    expression_instruction_count = 0
    for fragment in fragments:
        assert isinstance(fragment, dict)
        instructions = fragment.get("instructions")
        expression = fragment.get("expression")
        if not isinstance(instructions, list) or not isinstance(expression, dict):
            raise TranslationError(
                "object-store IR fragment expression/instructions are missing")
        program_id = expression.get("program_id")
        expression_hash = expression.get("semantic_sha256")
        expression_ast_hash = expression.get("ast_sha256")
        expression_source = expression.get("source")
        blocks = expression.get("blocks")
        if (not isinstance(program_id, str) or not program_id or
                program_id in expression_program_ids or
                not isinstance(expression_hash, str) or
                re.fullmatch(r"[0-9a-f]{64}", expression_hash) is None or
                not isinstance(expression_ast_hash, str) or
                re.fullmatch(r"[0-9a-f]{64}", expression_ast_hash) is None or
                not isinstance(expression_source, str) or not expression_source or
                not isinstance(blocks, list) or not blocks):
            raise TranslationError(
                "object-store expression CFG identity is malformed")
        expression_program_ids.add(program_id)
        try:
            # ``ast.get_source_segment`` can retain a physical newline from a
            # parenthesized source expression.  Re-wrap the isolated segment
            # so Python's own implicit-continuation rule remains in force.
            expression_node = ast.parse(
                "(" + expression_source + "\n)", mode="eval").body
        except SyntaxError as exc:
            raise TranslationError(
                "object-store expression source is not a Python expression") from exc
        actual_ast_hash = hashlib.sha256(ast.dump(
            expression_node, annotate_fields=True,
            include_attributes=False).encode("utf-8")).hexdigest()
        if actual_ast_hash != expression_ast_hash:
            raise TranslationError(
                "object-store expression AST hash is inconsistent")
        expression_payload = {
            name: expression.get(name) for name in (
                "program_id", "entry", "result", "result_kind", "blocks",
                "source", "ast_sha256")
        }
        actual_expression_hash = hashlib.sha256(json.dumps(
            expression_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        if actual_expression_hash != expression_hash:
            raise TranslationError(
                "object-store expression semantic hash is inconsistent")

        block_names = [
            block.get("name") for block in blocks if isinstance(block, dict)
        ]
        if (len(block_names) != len(blocks) or
                any(not isinstance(name, str) or not name
                    for name in block_names) or
                len(set(block_names)) != len(block_names) or
                expression.get("entry") not in block_names):
            raise TranslationError(
                "object-store expression CFG blocks/entry are malformed")
        expression_block_count += len(blocks)
        sequences: list[int] = []
        destinations: set[str] = set()
        return_results: list[object] = []
        for block in blocks:
            assert isinstance(block, dict)
            block_instructions = block.get("instructions")
            terminator = block.get("terminator")
            if (not isinstance(block_instructions, list) or
                    not isinstance(terminator, dict) or
                    not isinstance(terminator.get("targets"), list) or
                    any(target not in block_names
                        for target in terminator["targets"])):
                raise TranslationError(
                    "object-store expression CFG edge is malformed")
            term_op = terminator.get("op")
            if term_op not in ("branch-truth", "jump", "return-expression"):
                raise TranslationError(
                    "object-store expression CFG terminator is unsupported")
            if term_op == "branch-truth":
                expression_branch_count += 1
            if term_op == "return-expression":
                arguments = terminator.get("arguments")
                if not isinstance(arguments, list) or len(arguments) != 1:
                    raise TranslationError(
                        "object-store expression return is malformed")
                return_results.append(arguments[0])
            for item in block_instructions:
                if (not isinstance(item, dict) or
                        not isinstance(item.get("sequence"), int) or
                        isinstance(item.get("sequence"), bool) or
                        not isinstance(item.get("op"), str) or
                        not isinstance(item.get("destination"), str) or
                        item["destination"] in destinations):
                    raise TranslationError(
                        "object-store expression SSA instruction is malformed")
                sequences.append(item["sequence"])
                destinations.add(item["destination"])
                expression_op_counts[item["op"]] += 1
                expression_instruction_count += 1
        if (sorted(sequences) != list(range(len(sequences))) or
                expression.get("result") not in destinations or
                return_results != [expression.get("result")]):
            raise TranslationError(
                "object-store expression SSA/result is inconsistent")

        execute_rows = [
            item for item in instructions
            if isinstance(item, dict) and item.get("op") ==
            "execute-expression-cfg"
        ]
        if (len(execute_rows) != 1 or any(
                isinstance(item, dict) and item.get("op") == "eval-expression"
                for item in instructions)):
            raise TranslationError(
                "object-store IR must execute exactly one non-opaque expression CFG")
        execute = execute_rows[0]
        execute_attributes = execute.get("attributes")
        if (not isinstance(execute.get("arguments"), list) or
                execute["arguments"] != [program_id] or
                not isinstance(execute_attributes, dict) or
                execute_attributes.get("program_id") != program_id or
                execute_attributes.get("program_result") !=
                expression.get("result") or
                execute_attributes.get("program_semantic_sha256") !=
                expression_hash):
            raise TranslationError(
                "object-store expression CFG execution binding changed")
        sync_indices = [
            index for index, item in enumerate(instructions)
            if isinstance(item, dict) and item.get("op") ==
            "draw-sync-if-bound"
        ]
        if len(sync_indices) != 1 or sync_indices[0] == 0:
            raise TranslationError(
                "object-store IR fragment lacks one post-store sync")
        sync_index = sync_indices[0]
        store = instructions[sync_index - 1]
        sync = instructions[sync_index]
        if (not isinstance(store, dict) or not isinstance(sync, dict) or
                store.get("op") != "store-attribute" or
                not isinstance(store.get("arguments"), list) or
                not isinstance(sync.get("arguments"), list) or
                store["arguments"][0] != sync["arguments"][0] or
                store["arguments"][2] != sync["arguments"][2] or
                sync["arguments"][3] != fragment.get("site_id") or
                sync["arguments"][1] != fragment.get("field_id")):
            raise TranslationError(
                "object-store IR store/sync SSA identity changed")

    shapes = coverage.get("assignment_shape_counts")
    expression_census = coverage.get("expression_census")
    if (coverage.get("runtime_hook_candidates") != len(fragments) or
            coverage.get("runtime_hook_fragments") != len(fragments) or
            coverage.get("bind_schema_candidates") != len(schema_ids) or
            coverage.get("unsupported_active_sites") != 0 or
            coverage.get("receiver_evaluated_once") is not True or
            coverage.get(
                "each_source_receiver_occurrence_evaluated_once") is not True or
            coverage.get("rhs_evaluated_once") is not True or
            coverage.get("augassign_old_value_loaded_once") is not True or
            coverage.get("original_store_precedes_adjacent_sync") is not True or
            coverage.get("store_and_sync_reuse_same_ssa_temps") is not True or
            coverage.get("enclosing_control_flow_preserved_by_site_splice")
            is not True or
            coverage.get("full_gameplay_cfg_lowered") is not False or
            coverage.get("opaque_expressions_lowered") is not True or
            coverage.get("expression_cfg_is_target_neutral") is not True or
            coverage.get("expression_cfg_preserves_python_branch_laziness")
            is not True or
            coverage.get("expression_cfg_ssa_validated") is not True or
            coverage.get("current_scalar_pipeline_consumes_object_ir")
            is not False or
            coverage.get("live_claimed") is not False or
            not isinstance(shapes, dict) or
            any(not isinstance(value, int) or isinstance(value, bool)
                for value in shapes.values()) or
            sum(shapes.values()) !=
            len(fragments)):
        raise TranslationError(
            "object-store IR evaluation/coverage contract changed")
    if (not isinstance(expression_census, dict) or
            expression_census.get("expression_roots") != len(fragments) or
            expression_census.get("expression_cfg_programs") !=
            len(fragments) or
            expression_census.get("expression_cfg_blocks") !=
            expression_block_count or
            expression_census.get("expression_cfg_branches") !=
            expression_branch_count or
            expression_census.get("expression_ssa_instructions") !=
            expression_instruction_count or
            expression_census.get("expression_ir_op_counts") !=
            dict(sorted(expression_op_counts.items())) or
            expression_census.get("unsupported_expression_count") != 0 or
            expression_census.get("unsupported_expressions") != []):
        raise TranslationError(
            "object-store expression census disagrees with the CFG inventory")
    blockers = report.get("live_blockers")
    if (not isinstance(blockers, list) or not blockers or
            not all(isinstance(item, str) and item for item in blockers)):
        raise TranslationError("object-store IR omitted live blockers")
    return report


def build_object_store_ir_stage(
        mutation_plan: MutationHookPlan,
        mutation_hook_ir: dict[str, Any],
        project_root: Path = ROOT) -> tuple[Any, dict[str, Any]]:
    """Lower all active object stores using the already-built hook plan."""
    module = lower_active_object_store_ir(
        project_root, hook_plan=mutation_plan)
    report = object_store_ir_report(module)
    if not isinstance(report, dict):
        raise TranslationError("object-store lowering did not return an object")
    return module, validate_object_store_ir(report, mutation_hook_ir)


def object_store_ir_contract(
        mutation_plan: MutationHookPlan,
        mutation_hook_ir: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Compatibility wrapper returning the validated object-store report."""
    return build_object_store_ir_stage(
        mutation_plan, mutation_hook_ir, project_root)[1]


def _canonical_value_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_function_cfg_ir(
        report: dict[str, Any], mutation_hook_ir: dict[str, Any],
        object_store_ir: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Validate the complete, target-neutral CFG without trusting its census."""
    if (report.get("format") != FUNCTION_CFG_IR_FORMAT or
            report.get("status") !=
            "ACTIVE_FUNCTION_CFG_COMPLETE_LIVE_BLOCKED" or
            report.get("live") is not False or
            report.get("mutation_hook_semantic_sha256") !=
            mutation_hook_ir.get("semantic_sha256") or
            report.get("object_store_semantic_sha256") !=
            object_store_ir.get("semantic_sha256")):
        raise TranslationError(
            "active function CFG format/status/input binding changed")
    source = report.get("source")
    object_source = object_store_ir.get("source")
    if (not isinstance(source, dict) or
            not isinstance(object_source, dict) or
            source != object_source or
            not isinstance(source.get("path"), str) or
            not isinstance(source.get("sha256"), str)):
        raise TranslationError(
            "active function CFG is stale against object-store source")
    source_path = project_root / str(source["path"])
    if (not source_path.is_file() or
            hashlib.sha256(source_path.read_bytes()).hexdigest() !=
            source["sha256"]):
        raise TranslationError(
            "active function CFG source hash does not match the workspace")

    functions = report.get("functions")
    coverage = report.get("coverage")
    if not isinstance(functions, list) or not isinstance(coverage, dict):
        raise TranslationError("active function CFG inventories are malformed")
    function_ids: set[str] = set()
    mutation_sites: list[int] = []
    splice_rows: list[tuple[int, str]] = []
    block_count = 0
    exception_edge_count = 0
    instruction_count = 0
    expression_program_count = 0
    expression_block_count = 0
    expression_instruction_count = 0
    for function in functions:
        if not isinstance(function, dict):
            raise TranslationError("active function CFG row is malformed")
        function_id = function.get("function_id")
        function_semantic = function.get("semantic_sha256")
        if (not isinstance(function_id, str) or not function_id or
                function_id in function_ids or
                not isinstance(function_semantic, str) or
                re.fullmatch(r"[0-9a-f]{64}", function_semantic) is None):
            raise TranslationError("active function CFG identity is malformed")
        function_ids.add(function_id)
        semantic_payload = dict(function)
        semantic_payload.pop("semantic_sha256", None)
        if _canonical_value_sha256(semantic_payload) != function_semantic:
            raise TranslationError(
                "active function CFG function semantic hash is inconsistent")
        if function.get("blockers") != []:
            raise TranslationError(
                "active function CFG contains a non-executable blocker")
        blocks = function.get("blocks")
        programs = function.get("expression_programs")
        sites = function.get("mutation_site_ids")
        splices = function.get("spliced_store_fragments")
        if (not isinstance(blocks, list) or not blocks or
                not isinstance(programs, list) or
                not isinstance(sites, list) or
                not isinstance(splices, list)):
            raise TranslationError(
                "active function CFG blocks/programs/sites are malformed")
        block_names = [
            block.get("name") for block in blocks if isinstance(block, dict)
        ]
        if (len(block_names) != len(blocks) or
                len(set(block_names)) != len(block_names) or
                function.get("entry") not in block_names):
            raise TranslationError("active function CFG block graph is malformed")
        sequences: list[int] = []
        executed_programs: list[str] = []
        for block in blocks:
            assert isinstance(block, dict)
            instructions = block.get("instructions")
            terminator = block.get("terminator")
            exception_target = block.get("exception_target")
            if (not isinstance(instructions, list) or
                    not isinstance(terminator, dict) or
                    not isinstance(terminator.get("targets"), list) or
                    any(target not in block_names
                        for target in terminator["targets"]) or
                    (exception_target is not None and
                     exception_target not in block_names)):
                raise TranslationError(
                    "active function CFG edge/terminator is malformed")
            if exception_target is not None:
                exception_edge_count += 1
            for instruction in instructions:
                if not isinstance(instruction, dict):
                    raise TranslationError(
                        "active function CFG instruction is malformed")
                sequence = instruction.get("sequence")
                op = instruction.get("op")
                if (not isinstance(sequence, int) or
                        isinstance(sequence, bool) or
                        not isinstance(op, str) or not op or
                        op.startswith("blocked-")):
                    raise TranslationError(
                        "active function CFG contains invalid/non-executable op")
                sequences.append(sequence)
                if op == "execute-expression-cfg":
                    arguments = instruction.get("arguments")
                    if (not isinstance(arguments, list) or
                            len(arguments) != 1 or
                            not isinstance(arguments[0], str)):
                        raise TranslationError(
                            "active function CFG expression reference malformed")
                    executed_programs.append(arguments[0])
        if sorted(sequences) != list(range(len(sequences))):
            raise TranslationError(
                "active function CFG instruction sequence is not contiguous")
        program_ids = [
            program.get("program_id")
            for program in programs if isinstance(program, dict)
        ]
        if (len(program_ids) != len(programs) or
                any(not isinstance(item, str) or not item
                    for item in program_ids) or
                len(set(program_ids)) != len(program_ids) or
                Counter(executed_programs) != Counter(program_ids)):
            raise TranslationError(
                "active function CFG expression programs are not executed once")
        for program in programs:
            assert isinstance(program, dict)
            program_blocks = program.get("blocks")
            if not isinstance(program_blocks, list) or not program_blocks:
                raise TranslationError(
                    "active function CFG expression subgraph is malformed")
            expression_block_count += len(program_blocks)
            for program_block in program_blocks:
                if (not isinstance(program_block, dict) or
                        not isinstance(program_block.get("instructions"), list)):
                    raise TranslationError(
                        "active function CFG expression block is malformed")
                expression_instruction_count += len(
                    program_block["instructions"])
        if (any(not isinstance(site, int) or isinstance(site, bool)
                for site in sites) or
                any(not isinstance(row, dict) or
                    not isinstance(row.get("site_id"), int) or
                    not isinstance(row.get("semantic_sha256"), str)
                    for row in splices)):
            raise TranslationError(
                "active function CFG mutation splice is malformed")
        mutation_sites.extend(sites)
        splice_rows.extend(
            (int(row["site_id"]), str(row["semantic_sha256"]))
            for row in splices)
        block_count += len(blocks)
        instruction_count += len(sequences)
        expression_program_count += len(programs)

    expected_fragments = {
        int(row["site_id"]): str(row["semantic_sha256"])
        for row in object_store_ir.get("fragments", [])
        if isinstance(row, dict)
    }
    if (len(expected_fragments) != len(object_store_ir.get("fragments", [])) or
            sorted(mutation_sites) != sorted(expected_fragments) or
            len(mutation_sites) != len(set(mutation_sites)) or
            len(splice_rows) != len(expected_fragments) or
            dict(splice_rows) != expected_fragments):
        raise TranslationError(
            "active function CFG does not splice every object store exactly once")
    expected_counts = {
        "function_count": len(functions),
        "runtime_mutation_site_count": len(expected_fragments),
        "spliced_store_fragment_count": len(expected_fragments),
        "cfg_block_count": block_count,
        "cfg_exception_edge_count": exception_edge_count,
        "cfg_instruction_count": instruction_count,
        "function_expression_program_count": expression_program_count,
        "function_expression_block_count": expression_block_count,
        "function_expression_instruction_count": expression_instruction_count,
        "functions_without_blockers": len(functions),
        "functions_with_blockers": 0,
        "unsupported_count": 0,
    }
    if (any(coverage.get(name) != value
            for name, value in expected_counts.items()) or
            coverage.get("unsupported") != [] or
            coverage.get("unsupported_code_counts") != {} or
            coverage.get("unsupported_ast_kind_counts") != {} or
            coverage.get("all_runtime_sites_spliced_once") is not True or
            coverage.get("exact_object_store_fragments_reused") is not True or
            coverage.get("expressions_use_object_expression_ir") is not True or
            coverage.get("full_function_cfg_lowered") is not True or
            coverage.get("current_c_backend_consumes_function_cfg") is not False or
            coverage.get("live_claimed") is not False):
        raise TranslationError("active function CFG coverage census disagrees")
    compiler_hashes = coverage.get("compiler_input_sha256")
    if (not isinstance(compiler_hashes, dict) or not compiler_hashes or
            any(not isinstance(path, str) or
                not (project_root / path).is_file() or
                hashlib.sha256((project_root / path).read_bytes()).hexdigest()
                != digest
                for path, digest in compiler_hashes.items())):
        raise TranslationError(
            "active function CFG compiler inputs are not hash-bound")
    module_payload = {
        "format": report["format"],
        "source_path": source["path"],
        "source_sha256": source["sha256"],
        "mutation_hook_semantic_sha256":
            report["mutation_hook_semantic_sha256"],
        "object_store_semantic_sha256":
            report["object_store_semantic_sha256"],
        "functions": functions,
        "coverage": coverage,
    }
    if _canonical_value_sha256(module_payload) != report.get("semantic_sha256"):
        raise TranslationError(
            "active function CFG module semantic hash is inconsistent")
    blockers = report.get("live_blockers")
    if (not isinstance(blockers, list) or len(blockers) != 2 or
            not all(isinstance(item, str) and item for item in blockers)):
        raise TranslationError("active function CFG omitted live blockers")
    return report


def build_function_cfg_ir_stage(
        mutation_plan: MutationHookPlan, object_store_module: Any,
        mutation_hook_ir: dict[str, Any], object_store_ir: dict[str, Any],
        project_root: Path = ROOT) -> tuple[Any, dict[str, Any]]:
    """Lower every active mutation-owning function into one complete CFG."""
    try:
        module = build_active_function_cfg_ir(
            project_root, hook_plan=mutation_plan,
            object_store_module=object_store_module)
    except FunctionCFGError as exc:
        raise TranslationError(f"active function CFG failed: {exc}") from exc
    report = function_cfg_report(module)
    return module, validate_function_cfg_ir(
        report, mutation_hook_ir, object_store_ir, project_root)


def validate_active_call_graph(
        report: dict[str, Any], mutation_hook_ir: dict[str, Any],
        object_store_ir: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Validate the whole active callable world without import reachability."""
    try:
        validate_active_call_graph_report(project_root, report)
    except ActiveCallGraphError as exc:
        raise TranslationError(f"active call graph failed: {exc}") from exc
    if (report.get("format") != ACTIVE_CALL_GRAPH_FORMAT or
            report.get("status") != ACTIVE_CALL_GRAPH_STATUS):
        raise TranslationError("active call graph identity changed")
    store_binding = report.get("object_store_binding")
    callables = report.get("callable_inventory")
    graph = report.get("call_graph")
    classes = report.get("class_inventory")
    initialization = report.get("module_initialization")
    proof = report.get("proof")
    if not all(isinstance(item, dict) for item in (
            store_binding, callables, graph, classes, initialization, proof)):
        raise TranslationError("active call graph omitted a required section")
    if (store_binding.get("mutation_hook_semantic_sha256") !=
            mutation_hook_ir.get("semantic_sha256") or
            store_binding.get("object_store_semantic_sha256") !=
            object_store_ir.get("semantic_sha256") or
            store_binding.get("fragment_count") !=
            object_store_ir["coverage"]["runtime_hook_fragments"] or
            store_binding.get("attached_fragment_count") !=
            store_binding.get("fragment_count") or
            store_binding.get("all_fragments_attached_exactly_once") is not True):
        raise TranslationError(
            "active call graph is stale against mutation/object-store IR")
    callable_rows = callables.get("callables")
    class_rows = classes.get("classes")
    reachable = graph.get("proven_reachable_callable_ids")
    not_reachable = graph.get("not_proven_reachable_callable_ids")
    exact_edges = graph.get("exact_internal_edges")
    if (not isinstance(callable_rows, list) or not isinstance(class_rows, list) or
            not isinstance(reachable, list) or
            not isinstance(not_reachable, list) or
            not isinstance(exact_edges, list) or
            callables.get("callable_count") != len(callable_rows) or
            callables.get("cfg_lowered_callable_count") != len(callable_rows) or
            callables.get("cfg_lowering_failure_count") != 0 or
            classes.get("class_count") != len(class_rows) or
            graph.get("proven_reachable_callable_count") != len(reachable) or
            graph.get("not_proven_reachable_callable_count") != len(not_reachable) or
            len(reachable) + len(not_reachable) != len(callable_rows) or
            graph.get("exact_internal_edge_count") != len(exact_edges) or
            graph.get("reachability_uses_only_proven_edges") is not True or
            graph.get("module_import_does_not_imply_callable_reachability")
            is not True or
            graph.get("dynamic_candidates_are_not_promoted_to_proven_reachable")
            is not True):
        raise TranslationError("active callable/edge census is inconsistent")
    if (initialization.get("call_site_count") !=
            initialization.get("explicit_call_site_count") +
            initialization.get("decorator_application_count") or
            initialization.get("status") != "INVENTORIED_NOT_CFG_LOWERED" or
            initialization.get("module_initializers_have_no_function_cfg")
            is not True or
            proof.get("all_function_defs_in_active_modules_inventoried")
            is not True or
            proof.get("all_functions_not_claimed_reachable_by_import") is not True or
            proof.get("only_source_evidenced_exact_edges_drive_reachability")
            is not True or
            proof.get("unresolved_dynamic_dispatch_is_fail_closed") is not True or
            proof.get("module_initialization_calls_inventoried") is not True or
            proof.get("module_initialization_cfg_lowered") is not False or
            proof.get("current_backend_consumes_inventory") is not False or
            report.get("live") is not False):
        raise TranslationError("active call graph proof boundary changed")
    blockers = report.get("live_blockers")
    expected_blockers = {
        **({"PZACG201": graph["reachable_finite_dynamic_dispatch_site_count"]}
           if graph["reachable_finite_dynamic_dispatch_site_count"] else {}),
        **({"PZACG202": graph["reachable_unresolved_call_site_count"]}
           if graph["reachable_unresolved_call_site_count"] else {}),
        **({"PZACG203": (graph["reachable_cfg_blocker_count"] +
                          graph["reachable_cfg_lowering_failure_count"])}
           if (graph["reachable_cfg_blocker_count"] or
               graph["reachable_cfg_lowering_failure_count"]) else {}),
        **({"PZACG204": graph["reachable_host_boundary_call_site_count"]}
           if graph["reachable_host_boundary_call_site_count"] else {}),
        "PZACG205": 1,
        "PZACG206": 1,
        "PZACG207": initialization["call_site_count"],
    }
    actual_blockers = ({
        item.get("code"): item.get("count") for item in blockers
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    } if isinstance(blockers, list) else None)
    if (actual_blockers != expected_blockers or
            len(blockers) != len(actual_blockers) or
            any(not isinstance(item.get("detail"), str) or not item["detail"]
                for item in blockers if isinstance(item, dict))):
        raise TranslationError("active call graph live blocker set differs")
    return report


def active_call_graph_contract(
        mutation_plan: MutationHookPlan, object_store_module: Any,
        mutation_hook_ir: dict[str, Any], object_store_ir: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    try:
        report = analyze_active_call_graph(
            project_root, hook_plan=mutation_plan,
            object_store_module=object_store_module)
    except ActiveCallGraphError as exc:
        raise TranslationError(f"active call graph failed: {exc}") from exc
    return validate_active_call_graph(
        report, mutation_hook_ir, object_store_ir, project_root)


def active_call_site_lowering_contract(
        active_call_graph: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Seal reachable CFG python-call occurrences to graph call-site IDs."""
    try:
        report = analyze_active_call_site_lowering(
            project_root, active_graph=active_call_graph)
    except ActiveCallSiteLoweringError as exc:
        raise TranslationError(
            f"active call-site lowering failed: {exc}") from exc

    mapping = report.get("mapping")
    proof = report.get("proof")
    numeric = report.get("numeric_id_contract")
    blockers = report.get("live_blockers")
    if (report.get("format") != ACTIVE_CALL_SITE_LOWERING_FORMAT or
            report.get("status") != ACTIVE_CALL_SITE_LOWERING_STATUS or
            report.get("live") is not False or
            report.get("active_call_graph_semantic_sha256") !=
            active_call_graph.get("semantic_sha256") or
            not isinstance(mapping, dict) or
            mapping.get("reachable_callable_count") !=
            active_call_graph["call_graph"][
                "proven_reachable_callable_count"] or
            mapping.get("represented_graph_call_site_count", 0) +
            mapping.get("unrepresented_graph_call_site_count", 0) !=
            mapping.get("reachable_graph_call_site_count") or
            mapping.get("unique_mapped_call_site_count") !=
            mapping.get("represented_graph_call_site_count") or
            mapping.get("missing_cfg_to_graph_match_count") != 0 or
            mapping.get("ambiguous_cfg_to_graph_match_count") != 0 or
            not isinstance(numeric, dict) or
            numeric.get("width_bits") != 16 or
            numeric.get("zero_is_reserved") is not True or
            numeric.get("highest_assigned_id") !=
            mapping.get("reachable_graph_call_site_count") or
            not isinstance(proof, dict) or
            proof.get("active_call_graph_validated_in_memory") is not True or
            proof.get("every_reachable_cfg_python_call_maps_exactly_once")
            is not True or
            proof.get("finite_candidates_never_become_proven") is not True or
            proof.get("argument_layout_is_copied_from_cfg_without_reordering")
            is not True or
            proof.get("backend_consumer_bound") is not False or
            not isinstance(blockers, list) or not blockers or
            sum(isinstance(row, dict) and row.get("code") == "PZCSL210"
                for row in blockers) != 1):
        raise TranslationError(
            "active call-site lowering invented an unproved backend binding")
    rendered = (json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n").encode("utf-8")
    status_path = project_root / "Build" / \
        "rtype_python_active_call_site_lowering_status.json"
    status_path.write_bytes(rendered)
    if status_path.read_bytes() != rendered:
        raise TranslationError(
            "active call-site lowering output write differs")
    return report


def whole_program_vm_call_abi_contract(
        active_call_graph: dict[str, Any],
        active_call_site_lowering: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Build the numeric per-occurrence call ABI from the existing inventory."""
    try:
        report = analyze_whole_program_vm_call_abi(
            project_root, active_graph=active_call_graph,
            call_site_lowering=active_call_site_lowering)
    except (WholeProgramVMCallABIError, ActiveCallSiteLoweringError,
            ActiveCallGraphError) as exc:
        raise TranslationError(
            f"whole-program VM call ABI failed: {exc}") from exc

    function_contract = report.get("function_id_contract")
    function_table = report.get("function_id_table")
    census = report.get("census")
    site_descriptors = report.get("site_abi_descriptors_in_source_order")
    occurrence_descriptors = report.get(
        "occurrence_abi_descriptors_in_cfg_order")
    proof = report.get("proof")
    blockers = report.get("live_blockers")
    lowering_mapping = active_call_site_lowering.get("mapping", {})
    if (report.get("format") != WHOLE_PROGRAM_VM_CALL_ABI_FORMAT or
            report.get("status") != WHOLE_PROGRAM_VM_CALL_ABI_STATUS or
            report.get("live") is not False or
            report.get("active_call_graph_semantic_sha256") !=
            active_call_graph.get("semantic_sha256") or
            report.get("call_site_lowering_semantic_sha256") !=
            active_call_site_lowering.get("semantic_sha256") or
            not isinstance(function_contract, dict) or
            function_contract.get("width_bits") != 16 or
            function_contract.get(
                "proven_reachable_prefix_matches_current_pzvt_order")
            is not True or
            function_contract.get(
                "candidate_only_functions_are_not_current_pzvt_functions")
            is not True or
            not isinstance(function_table, list) or
            function_contract.get("function_count") != len(function_table) or
            len(function_table) != active_call_graph[
                "callable_inventory"]["callable_count"] or
            not isinstance(census, dict) or
            census.get("represented_call_site_count") !=
            lowering_mapping.get("represented_graph_call_site_count") or
            census.get("call_occurrence_descriptor_count") !=
            lowering_mapping.get("cfg_python_call_occurrence_count") or
            census.get("duplicate_occurrence_descriptor_count") !=
            lowering_mapping.get("duplicate_cfg_occurrence_count") or
            census.get("exact_callable_ssa_provenance_count", 0) +
            census.get("ambiguous_callable_ssa_provenance_count", 0) !=
            census.get("call_occurrence_descriptor_count") or
            not isinstance(site_descriptors, list) or
            len(site_descriptors) != census.get(
                "represented_call_site_count") or
            not isinstance(occurrence_descriptors, list) or
            len(occurrence_descriptors) != census.get(
                "call_occurrence_descriptor_count") or
            not isinstance(proof, dict) or
            proof.get(
                "active_call_graph_and_lowering_validated_in_memory")
            is not True or
            proof.get("one_numeric_descriptor_per_represented_cfg_occurrence")
            is not True or
            proof.get("callable_ssa_chain_is_traced_without_receiver_invention")
            is not True or
            proof.get("finite_dispatch_tables_remain_non_proven") is not True or
            proof.get("argument_evaluation_order_is_not_reordered") is not True or
            proof.get("parameter_destination_map_is_per_occurrence_and_target")
            is not True or
            proof.get("current_vm_backend_consumes_call_abi") is not False or
            not isinstance(blockers, list) or not blockers or
            sum(isinstance(row, dict) and row.get("code") == "PZCABI213"
                for row in blockers) != 1):
        raise TranslationError(
            "whole-program VM call ABI invented an unproved live binding")

    rendered = (json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n").encode("utf-8")
    status_path = project_root / "Build" / \
        "rtype_python_whole_program_vm_call_abi_status.json"
    status_path.write_bytes(rendered)
    if status_path.read_bytes() != rendered:
        raise TranslationError("whole-program VM call ABI output write differs")
    return report


def validate_active_target_adapters(
        report: dict[str, Any], active_call_graph: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Bind every host/hardware adapter obligation to this exact call graph."""
    try:
        validate_active_target_adapters_report(
            project_root, report, active_call_graph)
    except ActiveTargetAdaptersError as exc:
        raise TranslationError(
            f"active target adapters failed: {exc}") from exc
    if (report.get("format") != ACTIVE_TARGET_ADAPTERS_FORMAT or
            report.get("status") != ACTIVE_TARGET_ADAPTERS_STATUS):
        raise TranslationError("active target adapter identity changed")
    binding = report.get("input_binding", {}).get("active_call_graph")
    inventory = report.get("inventory")
    proof = report.get("proof")
    if not all(isinstance(item, dict) for item in (
            binding, inventory, proof)):
        raise TranslationError("active target adapter proof section is missing")
    graph_path = project_root / "Build" / \
        "rtype_python_active_call_graph_status.json"
    if (not graph_path.is_file() or
            binding.get("file_sha256") !=
            hashlib.sha256(graph_path.read_bytes()).hexdigest() or
            binding.get("format") != active_call_graph.get("format") or
            binding.get("status") != active_call_graph.get("status") or
            binding.get("semantic_sha256") !=
            active_call_graph.get("semantic_sha256") or
            binding.get("source_graph_semantic_sha256") !=
            active_call_graph.get("source_graph", {}).get("semantic_sha256")):
        raise TranslationError(
            "active target adapters are stale against this translation run")
    sites = inventory.get("sites")
    groups = inventory.get("semantic_groups")
    if (not isinstance(sites, list) or not isinstance(groups, list) or
            inventory.get("site_count") != len(sites) or
            inventory.get("semantic_group_count") != len(groups) or
            proof.get("all_reachable_host_boundaries_inventoried") is not True or
            proof.get("all_reachable_unresolved_calls_inventoried") is not True or
            proof.get("unmatched_calls_remain_fail_closed") is not True or
            proof.get("target_backend_consumes_inventory") is not False or
            report.get("live") is not False):
        raise TranslationError(
            "active target adapters invented an unproved backend binding")
    blockers = report.get("live_blockers")
    if (not isinstance(blockers, list) or
            [item.get("code") for item in blockers
             if isinstance(item, dict)] !=
            [f"PZATA{index}" for index in range(201, 206)]):
        raise TranslationError("active target adapter blocker set differs")
    return report


def active_target_adapters_contract(
        active_call_graph: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    try:
        report = analyze_active_target_adapters(
            project_root,
            project_root / "Build" /
            "rtype_python_active_call_graph_status.json")
    except ActiveTargetAdaptersError as exc:
        raise TranslationError(
            f"active target adapters failed: {exc}") from exc
    return validate_active_target_adapters(
        report, active_call_graph, project_root)


def frame_timing_provider_contract(
        active_target_adapters: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Generate the 55 Hz FT812 timing artifacts from the active Python source.

    The timing analyser binds itself to the just-written adapter inventory.
    All three outputs are owned by the surrounding generation transaction, so
    a later closure failure restores them byte-for-byte with the other target
    artifacts.
    """
    adapter_status = (
        project_root / "Build" /
        "rtype_python_active_target_adapters_status.json")
    if not adapter_status.is_file():
        raise TranslationError(
            "frame timing provider has no current adapter status")
    try:
        report = analyze_frame_timing_provider(project_root)
    except FrameTimingProviderError as exc:
        raise TranslationError(
            f"frame timing provider failed: {exc}") from exc
    if (report.get("format") != FRAME_TIMING_PROVIDER_FORMAT or
            report.get("status") != FRAME_TIMING_PROVIDER_STATUS or
            report.get("live") is not False):
        raise TranslationError("frame timing provider identity changed")
    binding = report.get("input_binding", {}).get(
        "active_target_adapters", {})
    if (binding.get("file_sha256") !=
            hashlib.sha256(adapter_status.read_bytes()).hexdigest() or
            binding.get("semantic_sha256") !=
            active_target_adapters.get("semantic_sha256")):
        raise TranslationError(
            "frame timing provider is stale against this adapter inventory")

    include_text = render_frame_timing_include(report)
    contract_text = render_frame_timing_manifest(report)
    status_text = json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    include_path = project_root / "Source" / "ASM" / \
        "generated_python_frame_timing.inc"
    contract_path = project_root / "Build" / \
        "rtype_python_frame_timing_contract.json"
    status_path = project_root / "Build" / \
        "rtype_python_frame_timing_provider_status.json"
    include_path.write_text(
        include_text, encoding="utf-8", newline="\n")
    contract_path.write_text(
        contract_text, encoding="utf-8", newline="\n")
    status_path.write_text(
        status_text, encoding="utf-8", newline="\n")
    try:
        validate_frame_timing_provider_report(
            project_root, report, validate_artifacts=True)
    except FrameTimingProviderError as exc:
        raise TranslationError(
            f"generated frame timing provider failed validation: {exc}") from exc
    return report


def whole_program_vm_contract(
        active_call_graph: dict[str, Any],
        active_call_site_lowering: dict[str, Any],
        whole_program_vm_call_abi: dict[str, Any],
        project_root: Path = ROOT,
        *, object_store_ir: dict[str, Any] | None = None,
        output_directory: Path | None = None,
        ) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Emit a compact target VM, a lossless proof and its stack certificate.

    ``rtype_python_whole_program_vm.bin`` remains the deployment-compatible
    path, but now unambiguously contains the numeric PZVT image.  The larger
    PZVM document is a host-only semantic proof and is written separately.
    Both images and the stack/arena report are validated before any of their
    caller-owned transaction outputs are written.
    """
    try:
        artifact = build_whole_program_vm(
            active_call_graph,
            active_call_site_lowering=active_call_site_lowering,
            whole_program_vm_call_abi=whole_program_vm_call_abi,
            object_store_ir=object_store_ir)
        decoded_proof = decode_whole_program_vm(artifact.proof_bytecode)
        decoded_target = decode_compact_target_vm(
            artifact.target_bytecode,
            expected_proof_semantic_sha256=artifact.semantic_sha256)
        status = whole_program_vm_status(
            artifact, project_root=project_root)
        status["call_abi_binding"] = {
            "enabled": artifact.target_coverage.get(
                "call_abi_input_enabled"),
            "active_call_site_lowering_semantic_sha256":
                artifact.target_coverage.get(
                    "active_call_site_lowering_semantic_sha256"),
            "whole_program_vm_call_abi_semantic_sha256":
                artifact.target_coverage.get(
                    "whole_program_vm_call_abi_semantic_sha256"),
            "occurrences_bound_by_exact_cfg_path": status.get(
                "execution_contract", {}).get(
                    "call_abi_occurrences_bound_by_exact_cfg_path"),
            "legacy_direct_call_instruction_count":
                artifact.target_coverage.get(
                    "legacy_direct_call_instruction_count"),
            "legacy_direct_call_site_count":
                artifact.target_coverage.get(
                    "legacy_direct_call_site_count"),
            "additional_direct_call_instruction_count":
                artifact.target_coverage.get(
                    "direct_call_instruction_count", 0) -
                artifact.target_coverage.get(
                    "legacy_direct_call_instruction_count", 0),
            "guarded_finite_dispatch_instruction_count":
                artifact.target_coverage.get(
                    "abi_finite_dispatch_instruction_count", 0),
            "guarded_finite_dispatch_site_count":
                artifact.target_coverage.get(
                    "abi_finite_dispatch_site_count", 0),
            "guarded_finite_bound_dispatch_instruction_count":
                artifact.target_coverage.get(
                    "abi_finite_bound_dispatch_instruction_count", 0),
            "guarded_finite_bound_dispatch_site_count":
                artifact.target_coverage.get(
                    "abi_finite_bound_dispatch_site_count", 0),
            "guarded_finite_lexical_dispatch_instruction_count":
                artifact.target_coverage.get(
                    "abi_finite_lexical_dispatch_instruction_count", 0),
            "guarded_finite_lexical_dispatch_site_count":
                artifact.target_coverage.get(
                    "abi_finite_lexical_dispatch_site_count", 0),
            "guarded_callable_function_count":
                artifact.target_coverage.get(
                    "guarded_callable_function_count", 0),
            "guarded_body_adapter_instruction_count":
                artifact.target_coverage.get(
                    "guarded_body_adapter_instruction_count", 0),
            "additional_fully_lowered_call_site_count":
                artifact.target_coverage.get(
                    "abi_lowered_call_site_count", 0) -
                artifact.target_coverage.get(
                    "legacy_direct_call_site_count", 0),
        }
        rendered_status = (json.dumps(
            status, ensure_ascii=False, sort_keys=True, indent=2,
        ) + "\n").encode("utf-8")
        stack_bound = analyze_whole_program_vm_stack_bound(
            artifact, active_call_graph, project_root=project_root)
        stack_bound = validate_whole_program_vm_stack_bound_report(
            artifact, active_call_graph, stack_bound,
            project_root=project_root)
    except (WholeProgramVMError, WholeProgramVMStackBoundError) as exc:
        raise TranslationError(
            f"whole-program VM lowering failed: {exc}") from exc
    reachable = [str(item) for item in active_call_graph["call_graph"]
                 ["proven_reachable_callable_ids"]]
    guarded = [str(item) for item in artifact.document.get(
        "guarded_callable_ids", [])]
    serialized = [*reachable, *guarded]
    decoded_ids = [str(item["callable_id"])
                   for item in decoded_proof.get("functions", [])]
    blocker_codes = [row.get("code") for row in status.get(
        "live_blockers", []) if isinstance(row, dict)]
    host_proof = status.get("host_proof", {})
    target_bytecode = status.get("target_bytecode", {})
    proof_coverage = status.get("proof_coverage", {})
    target_coverage = status.get("target_coverage", {})
    execution = status.get("execution_contract", {})
    call_abi_binding = status.get("call_abi_binding", {})
    abi_eligible_instructions = target_coverage.get(
        "abi_eligible_call_instruction_count")
    abi_lowered_instructions = target_coverage.get(
        "abi_lowered_call_instruction_count")
    abi_unlowered_instructions = target_coverage.get(
        "abi_unlowered_call_instruction_count")
    abi_eligible_sites = target_coverage.get(
        "abi_eligible_call_site_count")
    abi_lowered_sites = target_coverage.get(
        "abi_lowered_call_site_count")
    abi_unlowered_sites = target_coverage.get(
        "abi_unlowered_call_site_count")
    direct_instructions = target_coverage.get(
        "direct_call_instruction_count")
    guarded_finite_instructions = target_coverage.get(
        "abi_finite_dispatch_instruction_count")
    guarded_finite_sites = target_coverage.get(
        "abi_finite_dispatch_site_count")
    guarded_finite_bound_instructions = target_coverage.get(
        "abi_finite_bound_dispatch_instruction_count")
    guarded_finite_bound_sites = target_coverage.get(
        "abi_finite_bound_dispatch_site_count")
    guarded_finite_lexical_instructions = target_coverage.get(
        "abi_finite_lexical_dispatch_instruction_count")
    guarded_finite_lexical_sites = target_coverage.get(
        "abi_finite_lexical_dispatch_site_count")
    legacy_direct_instructions = call_abi_binding.get(
        "legacy_direct_call_instruction_count")
    legacy_direct_sites = call_abi_binding.get(
        "legacy_direct_call_site_count")
    from pyz80_compiler.whole_program_vm_stack_bound import _unit_labels
    definition_labels, definition_units = _unit_labels(artifact.document)
    target_ids = [definition_labels[index]["owner"] for index in definition_units]
    if (status.get("function_id_table") != target_ids or
            status.get("format") != WHOLE_PROGRAM_VM_STATUS_FORMAT or
            not isinstance(host_proof, dict) or
            host_proof.get("format") != WHOLE_PROGRAM_VM_FORMAT or
            host_proof.get("deployment") is not False or
            host_proof.get("bytes") != len(artifact.proof_bytecode) or
            host_proof.get("sha256") != artifact.proof_bytecode_sha256 or
            not isinstance(target_bytecode, dict) or
            target_bytecode.get("format") !=
            COMPACT_TARGET_VM_FORMAT or
            target_bytecode.get("bytes") != len(artifact.target_bytecode) or
            target_bytecode.get("sha256") !=
            artifact.target_bytecode_sha256 or
            not isinstance(proof_coverage, dict) or
            proof_coverage != artifact.coverage or
            proof_coverage.get("function_count") != len(serialized) or
            proof_coverage.get("proven_reachable_function_count") !=
            len(reachable) or
            proof_coverage.get("guarded_callable_function_count") !=
            len(guarded) or
            not isinstance(target_coverage, dict) or
            target_coverage != artifact.target_coverage or
            target_coverage.get("function_count") != len(target_ids) or
            target_coverage.get("proven_reachable_function_count") !=
            len(reachable) or
            target_coverage.get("guarded_callable_function_count") !=
            len(guarded) or
            decoded_target.get("format") !=
            COMPACT_TARGET_VM_FORMAT or
            decoded_target.get("proof_document_semantic_sha256") !=
            artifact.semantic_sha256 or
            tuple(decoded_target.get("functions", [])) != definition_units or
            status.get("active_call_graph_semantic_sha256") !=
            active_call_graph.get("semantic_sha256") or
            status.get("artifact_semantic_sha256") !=
            artifact.semantic_sha256 or
            artifact.document.get(
                "active_call_site_lowering_semantic_sha256") !=
            active_call_site_lowering.get("semantic_sha256") or
            artifact.document.get(
                "whole_program_vm_call_abi_semantic_sha256") !=
            whole_program_vm_call_abi.get("semantic_sha256") or
            decoded_ids != serialized or
            status.get("live") is not False or
            not isinstance(execution, dict) or
            not isinstance(call_abi_binding, dict) or
            call_abi_binding.get("enabled") is not True or
            call_abi_binding.get(
                "active_call_site_lowering_semantic_sha256") !=
            active_call_site_lowering.get("semantic_sha256") or
            call_abi_binding.get(
                "whole_program_vm_call_abi_semantic_sha256") !=
            whole_program_vm_call_abi.get("semantic_sha256") or
            call_abi_binding.get(
                "occurrences_bound_by_exact_cfg_path") is not True or
            target_coverage.get("call_abi_input_enabled") is not True or
            not all(isinstance(value, int) for value in (
                abi_eligible_instructions, abi_lowered_instructions,
                abi_unlowered_instructions, abi_eligible_sites,
                abi_lowered_sites, abi_unlowered_sites,
                direct_instructions, guarded_finite_instructions,
                guarded_finite_sites, guarded_finite_bound_instructions,
                guarded_finite_bound_sites,
                guarded_finite_lexical_instructions,
                guarded_finite_lexical_sites, legacy_direct_instructions,
                legacy_direct_sites)) or
            abi_eligible_instructions != abi_lowered_instructions or
            abi_lowered_instructions <= legacy_direct_instructions or
            abi_unlowered_instructions <= 0 or
            abi_eligible_sites != abi_lowered_sites or
            abi_lowered_sites <= legacy_direct_sites or
            abi_unlowered_sites <= 0 or
            call_abi_binding.get(
                "additional_direct_call_instruction_count") !=
            direct_instructions - legacy_direct_instructions or
            call_abi_binding.get(
                "guarded_finite_dispatch_instruction_count") !=
            guarded_finite_instructions or
            call_abi_binding.get(
                "guarded_finite_dispatch_site_count") !=
            guarded_finite_sites or
            call_abi_binding.get(
                "guarded_finite_bound_dispatch_instruction_count") !=
            guarded_finite_bound_instructions or
            call_abi_binding.get(
                "guarded_finite_bound_dispatch_site_count") !=
            guarded_finite_bound_sites or
            call_abi_binding.get(
                "guarded_finite_lexical_dispatch_instruction_count") !=
            guarded_finite_lexical_instructions or
            call_abi_binding.get(
                "guarded_finite_lexical_dispatch_site_count") !=
            guarded_finite_lexical_sites or
            not 0 <= guarded_finite_bound_instructions <=
            guarded_finite_instructions or
            not 0 <= guarded_finite_bound_sites <= guarded_finite_sites or
            not 0 <= guarded_finite_lexical_instructions <=
            guarded_finite_instructions or
            not 0 <= guarded_finite_lexical_sites <= guarded_finite_sites or
            guarded_finite_bound_instructions +
            guarded_finite_lexical_instructions >
            guarded_finite_instructions or
            guarded_finite_bound_sites + guarded_finite_lexical_sites >
            guarded_finite_sites or
            abi_lowered_instructions !=
            direct_instructions + guarded_finite_instructions or
            call_abi_binding.get(
                "additional_fully_lowered_call_site_count") !=
            abi_lowered_sites - legacy_direct_sites or
            execution.get("active_suspend_yield_protocol_executable") is
            not False or
            execution.get("call_abi_consumer_enabled") is not True or
            execution.get("call_abi_occurrences_bound_by_exact_cfg_path")
            is not True or
            execution.get("call_abi_only_replaces_invocation") is not True or
            target_coverage.get("active_interprocedural_execution_closed")
            is not False or
            blocker_codes != [f"PZWVLIVE{index:03d}"
                              for index in range(1, 6)]):
        raise TranslationError(
            "whole-program VM report invented an unproved target binding")

    stack_binding = stack_bound.get("binding", {})
    stack_blockers = stack_bound.get("live_blockers", [])
    if (stack_bound.get("format") != WHOLE_PROGRAM_VM_STACK_BOUND_FORMAT or
            not isinstance(stack_binding, dict) or
            stack_binding.get("active_call_graph_semantic_sha256") !=
            active_call_graph.get("semantic_sha256") or
            stack_binding.get("artifact_semantic_sha256") !=
            artifact.semantic_sha256 or
            stack_binding.get("proof_bytecode_sha256") !=
            artifact.proof_bytecode_sha256 or
            stack_binding.get("target_bytecode_sha256") !=
            artifact.target_bytecode_sha256 or
            stack_bound.get("complete_bound_proved") is not False or
            stack_bound.get("live") is not False or
            not isinstance(stack_blockers, list) or not stack_blockers):
        raise TranslationError(
            "whole-program VM stack report invented a complete/live bound")

    rendered_stack_bound = (json.dumps(
        stack_bound, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")
    output_directory = output_directory or project_root / "Build"
    output_directory.mkdir(parents=True, exist_ok=True)
    target_path = output_directory / \
        "rtype_python_whole_program_vm.bin"
    proof_path = output_directory / \
        "rtype_python_whole_program_vm_proof.bin"
    status_path = output_directory / \
        "rtype_python_whole_program_vm_status.json"
    stack_path = output_directory / \
        "rtype_python_whole_program_vm_stack_bound_status.json"
    target_path.write_bytes(artifact.target_bytecode)
    proof_path.write_bytes(artifact.proof_bytecode)
    status_path.write_bytes(rendered_status)
    stack_path.write_bytes(rendered_stack_bound)
    if (hashlib.sha256(target_path.read_bytes()).hexdigest() !=
            artifact.target_bytecode_sha256 or
            hashlib.sha256(proof_path.read_bytes()).hexdigest() !=
            artifact.proof_bytecode_sha256 or
            status_path.read_bytes() != rendered_status or
            stack_path.read_bytes() != rendered_stack_bound):
        raise TranslationError("whole-program VM output write differs")
    return artifact, status, stack_bound


def draw_ramdl_shadow_v4_contract(
        project_root: Path = ROOT) -> dict[str, Any]:
    """Rebuild and validate the fail-closed direct-RAM_DL v4 certificate."""
    try:
        report = build_draw_ramdl_shadow_v4_report(project_root)
        validation = validate_draw_ramdl_shadow_v4_report(project_root, report)
    except V4CheckError as exc:
        raise TranslationError(
            f"direct RAM_DL shadow v4 certificate failed: {exc}") from exc
    if (report.get("format") != DRAW_RAMDL_SHADOW_V4_FORMAT or
            report.get("status") != DRAW_RAMDL_SHADOW_V4_STATUS or
            report.get("live") is not False or
            validation.get("live") is not False or
            validation.get("analysis_sha256") !=
            report.get("analysis_sha256")):
        raise TranslationError(
            "direct RAM_DL shadow v4 certificate identity changed")
    blocker_codes = sorted(
        str(row.get("code")) for row in report.get("blockers", [])
        if isinstance(row, dict))
    if blocker_codes != [f"PZRAMDL{index}" for index in range(401, 408)]:
        raise TranslationError(
            "direct RAM_DL shadow v4 blocker set differs")
    output = (project_root / "Build" /
              "rtype_python_draw_ramdl_shadow_v4_status.json")
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return report


def active_reachable_pending_symbols(
        active_call_graph: dict[str, Any],
        translated: dict[str, str]) -> list[dict[str, Any]]:
    """Return only source-proven reachable functions lacking a lowering."""
    rows = active_call_graph["callable_inventory"]["callables"]
    by_id = {str(row["callable_id"]): row for row in rows}
    reachable = active_call_graph["call_graph"][
        "proven_reachable_callable_ids"]
    if len(by_id) != len(rows) or any(identifier not in by_id
                                     for identifier in reachable):
        raise TranslationError("active call graph reachable ids are inconsistent")
    pending: list[dict[str, Any]] = []
    for identifier in reachable:
        row = by_id[str(identifier)]
        symbol = f"{row['module']}.{row['qualname']}"
        status = translated.get(symbol, "pending")
        if status == "pending":
            pending.append({
                "symbol": symbol,
                "callable_id": identifier,
                "module": row["module"],
                "qualname": row["qualname"],
                "line": row["definition_line"],
                "status": status,
            })
    pending.sort(key=lambda item: str(item["callable_id"]))
    return pending


def validate_full_hqt3_inventory(
        report: dict[str, Any], coverage_report: CoverageReport,
        frame_envelope: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Bind the full catalogue to coverage, current HQT3 and the envelope."""
    try:
        validate_full_hqt3_inventory_report(report)
    except FullHQT3InventoryError as exc:
        raise TranslationError(f"full HQT3 inventory failed: {exc}") from exc
    if (report.get("format") != FULL_HQT3_INVENTORY_FORMAT or
            report.get("status") != FULL_HQT3_INVENTORY_STATUS):
        raise TranslationError("full HQT3 inventory identity changed")
    analysis = report.get("analysis_sha256")
    analysis_payload = dict(report)
    analysis_payload.pop("analysis_sha256", None)
    analysis_payload.pop("status", None)
    if (not isinstance(analysis, str) or
            _canonical_value_sha256(analysis_payload) != analysis):
        raise TranslationError("full HQT3 inventory analysis hash differs")
    source = report.get("source_binding")
    if (not isinstance(source, dict) or
            source.get("root_module") != coverage_report.root_module or
            source.get("rom_sha256") != coverage_report.rom_sha256 or
            source.get("coverage_source_hashes") !=
            dict(coverage_report.source_hashes) or
            report.get("source_binding_sha256") !=
            _canonical_value_sha256(source)):
        raise TranslationError(
            "full HQT3 inventory is stale against sprite coverage")
    bootstrap = report.get("current_bootstrap_hqt3")
    if not isinstance(bootstrap, dict):
        raise TranslationError("full HQT3 bootstrap binding is missing")
    manifest_path = project_root / str(bootstrap.get("manifest_path", ""))
    hqt3_path = project_root / str(bootstrap.get("hqt3_path", ""))
    if (not manifest_path.is_file() or not hqt3_path.is_file() or
            hashlib.sha256(manifest_path.read_bytes()).hexdigest() !=
            bootstrap.get("manifest_sha256") or
            hashlib.sha256(hqt3_path.read_bytes()).hexdigest() !=
            bootstrap.get("hqt3_sha256")):
        raise TranslationError(
            "full HQT3 inventory is stale against generated bootstrap assets")
    crosscheck = report.get("frame_sprite_fragment_envelope_crosscheck")
    envelope_path = (
        project_root / "Build" /
        "rtype_python_frame_sprite_fragment_envelope_status.json")
    if not isinstance(crosscheck, dict) or not envelope_path.is_file():
        raise TranslationError("full HQT3 frame-envelope cross-check is missing")
    envelope_bytes = envelope_path.read_bytes()
    hqt_blockers = [
        item for item in frame_envelope.get("blockers", [])
        if isinstance(item, dict) and item.get("code") == "PZFSFE102"
    ]
    if (crosscheck.get("status") != frame_envelope.get("status") or
            crosscheck.get("status_sha256") !=
            hashlib.sha256(envelope_bytes).hexdigest() or
            len(hqt_blockers) != 1 or
            crosscheck.get("missing_from_current_hqt3_count") !=
            hqt_blockers[0].get("missing_template_count") or
            crosscheck.get("missing_from_current_hqt3_domain_sha256") !=
            hqt_blockers[0].get("missing_template_domain_sha256") or
            crosscheck.get(
                "missing_current_identities_present_in_full_catalog") is not True or
            crosscheck.get("empty_draw_action_domains_resolved") is not True):
        raise TranslationError(
            "full HQT3 catalogue differs from the frame-envelope blocker")
    catalog = report.get("global_catalog")
    load_plan = report.get("load_plan")
    if not isinstance(catalog, dict) or not isinstance(load_plan, dict):
        raise TranslationError("full HQT3 catalogue/load plan is missing")
    scopes = load_plan.get("scopes")
    storage = load_plan.get("scope_storage")
    if (not isinstance(scopes, list) or not isinstance(storage, dict) or
            storage.get("scope_count") != len(scopes) or
            catalog.get("template_count") != len(catalog.get("templates", [])) or
            load_plan.get("resident_combinations") != [] or
            report.get("inventory_complete") is not True or
            report.get("live") is not False):
        raise TranslationError(
            "full HQT3 catalogue/load-scope census is inconsistent")
    return report


def full_hqt3_inventory_contract(
        coverage_report: CoverageReport,
        frame_envelope: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    try:
        report = analyze_full_hqt3_inventory(
            project_root, coverage_report=coverage_report,
            asset_manifest_path=(
                project_root / "Build" / "rtype_python_assets.json"))
    except FullHQT3InventoryError as exc:
        raise TranslationError(f"full HQT3 inventory failed: {exc}") from exc
    return validate_full_hqt3_inventory(
        report, coverage_report, frame_envelope, project_root)


def validate_hqt3_ramg_schedule(
        report: dict[str, Any], full_inventory: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Bind measured RAM_G/4 MiB packs to this transaction's inventory."""
    try:
        validate_hqt3_ramg_schedule_report(report)
    except HQT3RAMGScheduleError as exc:
        raise TranslationError(f"HQT3/RAM_G schedule failed: {exc}") from exc
    if (report.get("format") != HQT3_RAMG_SCHEDULE_FORMAT or
            report.get("status") != HQT3_RAMG_SCHEDULE_STATUS):
        raise TranslationError("HQT3/RAM_G schedule identity changed")
    if HQT3_RECORD_BYTES != 18:
        raise TranslationError("HQT3/RAM_G schedule uses a non-physical record size")

    binding = report.get("inventory_binding")
    catalog = full_inventory.get("global_catalog")
    load_plan = full_inventory.get("load_plan")
    if (not isinstance(binding, dict) or not isinstance(catalog, dict) or
            not isinstance(load_plan, dict)):
        raise TranslationError("HQT3/RAM_G inventory binding is missing")
    inventory_path = (
        project_root / "Build" / "rtype_python_full_hqt3_inventory_status.json")
    if not inventory_path.is_file():
        raise TranslationError("HQT3/RAM_G inventory artifact is missing")
    inventory_bytes = inventory_path.read_bytes()
    scopes = load_plan.get("scopes")
    events = load_plan.get("events")
    if (not isinstance(scopes, list) or not isinstance(events, list) or
            binding.get("path") !=
            inventory_path.resolve().relative_to(project_root.resolve()).as_posix() or
            binding.get("file_sha256") !=
            hashlib.sha256(inventory_bytes).hexdigest() or
            binding.get("analysis_sha256") !=
            full_inventory.get("analysis_sha256") or
            binding.get("source_binding_sha256") !=
            full_inventory.get("source_binding_sha256") or
            binding.get("global_template_rows_sha256") !=
            catalog.get("template_rows_sha256") or
            binding.get("template_count") != catalog.get("template_count") or
            binding.get("scope_count") != len(scopes) or
            binding.get("event_count") != len(events)):
        raise TranslationError(
            "HQT3/RAM_G schedule is stale against the full inventory")

    capacities = report.get("capacities")
    census = report.get("scope_pack_census")
    if (not isinstance(capacities, dict) or not isinstance(census, dict) or
            capacities.get("ft812_ram_g_bytes") != FT812_RAM_G_BYTES or
            capacities.get("tsconf_ram_bytes") != TSCONF_RAM_BYTES or
            capacities.get("storage_domains_are_separate") is not True or
            census.get("scope_count") != len(scopes) or
            report.get("resident_combinations") != [] or
            report.get("whole_inventory_resident") is not False or
            report.get("whole_stage_union_resident") is not False or
            report.get("scope_pack_proof_complete") is not True or
            report.get("load_schedule_complete") is not False or
            report.get("live") is not False):
        raise TranslationError(
            "HQT3/RAM_G schedule invented an unproved residency/load claim")
    return report


def hqt3_ramg_schedule_contract(
        full_inventory: dict[str, Any],
        project_root: Path = ROOT, *,
        max_workers: int = 1) -> dict[str, Any]:
    try:
        report = analyze_hqt3_ramg_schedule(
            project_root, max_workers=max_workers)
    except HQT3RAMGScheduleError as exc:
        raise TranslationError(f"HQT3/RAM_G schedule failed: {exc}") from exc
    return validate_hqt3_ramg_schedule(
        report, full_inventory, project_root)


def validate_hqt3_partition_solver(
        report: dict[str, Any], full_inventory: dict[str, Any],
        ramg_schedule: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Bind source-safe HQT shards/event costs to both physical inputs."""
    try:
        validate_hqt3_partition_solver_report(report)
    except HQT3PartitionSolverError as exc:
        raise TranslationError(f"HQT3 partition solver failed: {exc}") from exc
    if (report.get("format") != HQT3_PARTITION_SOLVER_FORMAT or
            report.get("status") != HQT3_PARTITION_SOLVER_STATUS):
        raise TranslationError("HQT3 partition solver identity changed")
    binding = report.get("input_binding")
    if not isinstance(binding, dict):
        raise TranslationError("HQT3 partition solver input binding is missing")
    inventory_path = (
        project_root / "Build" / "rtype_python_full_hqt3_inventory_status.json")
    schedule_path = (
        project_root / "Build" / "rtype_python_hqt3_ramg_schedule_status.json")
    if not inventory_path.is_file() or not schedule_path.is_file():
        raise TranslationError("HQT3 partition solver input artifact is missing")
    root = project_root.resolve()
    if (binding.get("inventory_path") !=
            inventory_path.resolve().relative_to(root).as_posix() or
            binding.get("inventory_file_sha256") !=
            hashlib.sha256(inventory_path.read_bytes()).hexdigest() or
            binding.get("inventory_analysis_sha256") !=
            full_inventory.get("analysis_sha256") or
            binding.get("schedule_path") !=
            schedule_path.resolve().relative_to(root).as_posix() or
            binding.get("schedule_file_sha256") !=
            hashlib.sha256(schedule_path.read_bytes()).hexdigest() or
            binding.get("schedule_analysis_sha256") !=
            ramg_schedule.get("analysis_sha256")):
        raise TranslationError(
            "HQT3 partition solver is stale against inventory/schedule")

    problem_scopes = report.get("problem_scopes")
    census = report.get("event_cost_census")
    transitions = ramg_schedule.get("event_transitions")
    resolution = report.get("blocker_resolution")
    if (not isinstance(problem_scopes, list) or not isinstance(census, dict) or
            not isinstance(transitions, dict) or not isinstance(resolution, dict) or
            report.get("problem_scope_count") != len(problem_scopes) or
            census.get("event_count") !=
            transitions.get("event_obligation_count") or
            census.get("exact_event_count") !=
            transitions.get("event_correlation_exact_count") or
            census.get("ambiguous_event_count") !=
            transitions.get("event_correlation_ambiguous_count") or
            report.get("structural_partition_proof_complete") is not True or
            report.get("ram_g_runtime_paging_complete") is not False or
            report.get("resident_combinations") != [] or
            report.get("eviction_inferences") != [] or
            report.get("live") is not False):
        raise TranslationError(
            "HQT3 partition solver invented an unproved paging/lifetime claim")
    state_resolution = resolution.get("PZRG307")
    ramg_resolution = resolution.get("PZRG301")
    expected_state_nonfit = sorted(
        ramg_schedule["scope_pack_census"]
        ["hqt3_index_width_nonfit_scope_ids"])
    if (not isinstance(state_resolution, dict) or
            not isinstance(ramg_resolution, dict) or
            state_resolution.get(
                "can_eliminate_by_structural_hqt_sharding_without_python_semantic_change")
            is not True or
            sorted(state_resolution.get("structurally_solved_scope_ids", [])) !=
            expected_state_nonfit or
            state_resolution.get("target_multi_table_resolver_still_required")
            is not True or
            ramg_resolution.get(
                "can_eliminate_by_structural_paging_without_python_semantic_change")
            is not False or
            ramg_resolution.get("structurally_solved_scope_ids") != []):
        raise TranslationError(
            "HQT3 partition solver blocker resolution differs from evidence")
    return report


def hqt3_partition_solver_contract(
        full_inventory: dict[str, Any], ramg_schedule: dict[str, Any],
        project_root: Path = ROOT, *,
        max_workers: int = 1) -> dict[str, Any]:
    try:
        report = analyze_hqt3_partition_solver(
            project_root, max_workers=max_workers)
    except HQT3PartitionSolverError as exc:
        raise TranslationError(f"HQT3 partition solver failed: {exc}") from exc
    return validate_hqt3_partition_solver(
        report, full_inventory, ramg_schedule, project_root)


def validate_hqt3_frame_page_solver(
        report: dict[str, Any], full_inventory: dict[str, Any],
        ramg_schedule: dict[str, Any], partition_solver: dict[str, Any],
        frame_record_bound: dict[str, Any],
        frame_sprite_fragment_envelope: dict[str, Any],
        active_call_graph: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    """Bind frame-local RAM_G paging facts to this exact translation run."""
    try:
        validate_hqt3_frame_page_solver_report(report)
    except HQT3FramePageSolverError as exc:
        raise TranslationError(
            f"HQT3 frame-page solver failed: {exc}") from exc
    if (report.get("format") != HQT3_FRAME_PAGE_SOLVER_FORMAT or
            report.get("status") != HQT3_FRAME_PAGE_SOLVER_STATUS):
        raise TranslationError("HQT3 frame-page solver identity changed")

    binding = report.get("input_binding")
    if not isinstance(binding, dict):
        raise TranslationError("HQT3 frame-page input binding is missing")
    inventory_binding = binding.get("inventory")
    schedule_binding = binding.get("schedule")
    partition_binding = binding.get("partition")
    bound_binding = binding.get("frame_record_bound")
    envelope_binding = binding.get("frame_sprite_fragment_envelope")
    graph_binding = binding.get("active_call_graph")
    if not all(isinstance(item, dict) for item in (
            inventory_binding, schedule_binding, partition_binding,
            bound_binding, envelope_binding, graph_binding)):
        raise TranslationError("HQT3 frame-page binding section is malformed")
    if (inventory_binding.get("analysis_sha256") !=
            full_inventory.get("analysis_sha256") or
            schedule_binding.get("analysis_sha256") !=
            ramg_schedule.get("analysis_sha256") or
            partition_binding.get("analysis_sha256") !=
            partition_solver.get("analysis_sha256") or
            bound_binding.get("status") != frame_record_bound.get("status") or
            envelope_binding.get("semantic_sha256") !=
            frame_sprite_fragment_envelope.get("semantic_sha256") or
            graph_binding.get("semantic_sha256") !=
            active_call_graph.get("semantic_sha256")):
        raise TranslationError(
            "HQT3 frame-page solver is stale against this translation run")

    frame = report.get("frame_record_contract")
    hardware = report.get("hardware_contract")
    double_buffer = report.get("double_buffer_capacity")
    bandwidth = report.get("upload_bandwidth")
    proof = report.get("proof_boundaries")
    bcab = report.get("exact_bcab_page_catalog")
    if not all(isinstance(item, dict) for item in (
            frame, hardware, double_buffer, bandwidth, proof, bcab)):
        raise TranslationError("HQT3 frame-page proof section is missing")
    if (frame.get("certified_frame_max_records") !=
            frame_record_bound.get("certified_frame_max_records") or
            frame.get("record_bound_proof_complete") is not True or
            hardware.get("ft812_ram_g_capacity_bytes") != FT812_RAM_G_BYTES or
            hardware.get("tsconf_ram_capacity_bytes") != TSCONF_RAM_BYTES or
            hardware.get(
                "displayed_page_overwrite_before_retirement_permitted")
            is not False or
            bcab.get("union_ram_g_bytes") != 1_263_796 or
            bcab.get("union_ram_g_overflow_bytes") != 215_220 or
            bcab.get("page_atom_count") != 596 or
            bcab.get("all_atoms_semantic") is not True or
            bcab.get("all_atoms_individually_strict_ram_g_fit") is not True or
            double_buffer.get("strict_fit_proved") is not False or
            double_buffer.get("retirement_fence_required_before_overwrite")
            is not True or
            bandwidth.get("deadline_proved") is not False or
            proof.get("exact_per_frame_page_sets_proved") is not False or
            proof.get("two_generation_ram_g_fit_proved") is not False or
            proof.get("upload_deadline_proved") is not False or
            report.get("resident_combinations") != [] or
            report.get("eviction_inferences") != [] or
            report.get("live") is not False):
        raise TranslationError(
            "HQT3 frame-page solver invented an unproved residency, fence "
            "or upload claim")
    blockers = report.get("blockers")
    if (not isinstance(blockers, list) or
            [item.get("code") for item in blockers
             if isinstance(item, dict)] !=
            [f"PZPAGE{index}" for index in range(501, 509)]):
        raise TranslationError("HQT3 frame-page blocker set differs")
    return report


def hqt3_frame_page_solver_contract(
        full_inventory: dict[str, Any], ramg_schedule: dict[str, Any],
        partition_solver: dict[str, Any],
        frame_record_bound: dict[str, Any],
        frame_sprite_fragment_envelope: dict[str, Any],
        active_call_graph: dict[str, Any],
        project_root: Path = ROOT) -> dict[str, Any]:
    try:
        report = analyze_hqt3_frame_page_solver(project_root)
    except (HQT3FramePageSolverError, ActiveCallGraphError) as exc:
        raise TranslationError(
            f"HQT3 frame-page solver failed: {exc}") from exc
    return validate_hqt3_frame_page_solver(
        report, full_inventory, ramg_schedule, partition_solver,
        frame_record_bound, frame_sprite_fragment_envelope,
        active_call_graph, project_root)


def whole_program_vm_consumes_call_site_lowering(
        whole_program_vm: dict[str, Any],
        active_call_site_lowering: dict[str, Any]) -> bool:
    """Prove that the emitted VM consumes the pre-backend lowering input."""
    execution_contract = whole_program_vm.get("execution_contract", {})
    call_abi_binding = whole_program_vm.get("call_abi_binding", {})
    lowering_sha256 = active_call_site_lowering.get("semantic_sha256")
    return (
        isinstance(execution_contract, dict)
        and isinstance(call_abi_binding, dict)
        and isinstance(lowering_sha256, str)
        and bool(lowering_sha256)
        and execution_contract.get("call_abi_consumer_enabled") is True
        and execution_contract.get(
            "call_abi_occurrences_bound_by_exact_cfg_path") is True
        and execution_contract.get(
            "python_call_adapters_are_call_site_specific") is True
        and call_abi_binding.get("enabled") is True
        and call_abi_binding.get("occurrences_bound_by_exact_cfg_path") is True
        and call_abi_binding.get(
            "active_call_site_lowering_semantic_sha256") == lowering_sha256
    )


def whole_program_vm_consumes_call_abi(
        whole_program_vm: dict[str, Any],
        active_call_site_lowering: dict[str, Any],
        whole_program_vm_call_abi: dict[str, Any]) -> bool:
    """Prove that the emitted VM, rather than its input inventory, uses ABI.

    ``whole_program_vm_call_abi`` is deliberately produced before the VM
    backend.  Its pre-consumer PZCABI213 blocker therefore cannot be used to
    decide whether the subsequently emitted PZVT consumed the contract.  The
    backend is the authoritative consumer and binds both input reports by
    semantic digest.
    """
    execution_contract = whole_program_vm.get("execution_contract", {})
    call_abi_binding = whole_program_vm.get("call_abi_binding", {})
    call_abi_sha256 = whole_program_vm_call_abi.get("semantic_sha256")
    return (
        whole_program_vm_consumes_call_site_lowering(
            whole_program_vm, active_call_site_lowering)
        and isinstance(execution_contract, dict)
        and isinstance(call_abi_binding, dict)
        and isinstance(call_abi_sha256, str)
        and bool(call_abi_sha256)
        and execution_contract.get("call_abi_only_replaces_invocation") is True
        and call_abi_binding.get(
            "whole_program_vm_call_abi_semantic_sha256") == call_abi_sha256
    )


def translation_closure_contract(
        *, pending: list[dict[str, Any]],
        sprite_working_sets: dict[str, Any],
        frame_record_bound: dict[str, Any],
        frame_sprite_fragment_envelope: dict[str, Any],
        frame_render_plan: dict[str, Any],
        frame_budget: dict[str, Any],
        frame_budget_live_hook: dict[str, Any],
        render_order_backend: dict[str, Any],
        draw_vm_backend: dict[str, Any],
        draw_state_backend: dict[str, Any],
        draw_fast_pipeline: dict[str, Any],
        draw_target_bundle: dict[str, Any],
        draw_bank_placement: dict[str, Any],
        mutation_hook_ir: dict[str, Any],
        object_store_ir: dict[str, Any],
        function_cfg_ir: dict[str, Any],
        active_call_graph: dict[str, Any],
        active_call_site_lowering: dict[str, Any],
        whole_program_vm_call_abi: dict[str, Any],
        active_target_adapters: dict[str, Any],
        frame_timing_provider: dict[str, Any],
        draw_ramdl_shadow_v4: dict[str, Any],
        whole_program_vm: dict[str, Any],
        whole_program_vm_stack_bound: dict[str, Any],
        full_hqt3_inventory: dict[str, Any],
        hqt3_ramg_schedule: dict[str, Any],
        hqt3_partition_solver: dict[str, Any],
        hqt3_frame_page_solver: dict[str, Any],
        gameplay_backend: dict[str, Any],
        sprite_backend: dict[str, Any],
        ) -> dict[str, Any]:
    """Return the one fail-closed definition of a complete translation.

    No individual generator is allowed to promote the project to complete.
    Completion means that every reachable symbol and every target boundary
    needed by the active Python frame has a live, certified lowering.
    """
    blockers: list[dict[str, Any]] = []

    if pending:
        blockers.append({
            "code": "PZCLOSURE001",
            "component": "reachable_python_symbols",
            "reason": "reachable active-Python symbols remain untranslated",
            "count": len(pending),
            "symbols": sorted(str(item["symbol"]) for item in pending),
        })

    if sprite_working_sets.get("ready") is not True:
        blockers.append({
            "code": "PZCLOSURE002",
            "component": "sprite_working_sets",
            "reason": "source-derived resident/loadable sprite plan is blocked",
            "status": sprite_working_sets.get("status"),
            "evidence": sprite_working_sets.get("missing_invariants", []),
        })

    certified_records = frame_record_bound.get(
        "certified_frame_max_records")
    bound_kind = frame_record_bound.get("bound_kind")
    exact_records = frame_record_bound.get("exact_max_records")
    record_bound_valid = (
        frame_record_bound.get("proof_complete") is True and
        frame_record_bound.get("can_certify_frame_budget") is True and
        isinstance(certified_records, int) and
        not isinstance(certified_records, bool) and
        0 <= certified_records <= 0xFFFF and
        bound_kind in ("exact", "conservative_upper_bound") and
        (exact_records is None or exact_records == certified_records)
    )
    if not record_bound_valid:
        blockers.append({
            "code": "PZCLOSURE003",
            "component": "frame_record_bound",
            "reason": (
                "the active Python frame has no certified reachable-state "
                "record bound"),
            "status": frame_record_bound.get("status"),
            "evidence": frame_record_bound.get("blockers", []),
        })

    if frame_render_plan.get("live_target_lowering_present") is not True:
        blockers.append({
            "code": "PZCLOSURE004",
            "component": "frame_render_plan",
            "reason": "the complete source-derived frame order is not live",
            "status": frame_render_plan.get("status"),
            "evidence": frame_render_plan.get("live_blockers", []),
        })

    order_integration = render_order_backend.get(
        "compile_manifest_integration", {})
    if (not isinstance(order_integration, dict) or
            order_integration.get("live_target_hooks_present") is not True):
        blockers.append({
            "code": "PZCLOSURE005",
            "component": "render_order_backend",
            "reason": "Python list order is not connected to the live object pool",
            "status": render_order_backend.get("status"),
            "evidence": (
                order_integration.get("reason")
                if isinstance(order_integration, dict) else None),
        })

    vm_integration = draw_vm_backend.get("compile_manifest_integration", {})
    if (not isinstance(vm_integration, dict) or
            vm_integration.get(
                "live_target_performance_and_size_certified") is not True):
        blockers.append({
            "code": "PZCLOSURE006",
            "component": "draw_vm_backend",
            "reason": "the selected compact draw VM is not certified live",
            "status": draw_vm_backend.get("status"),
            "evidence": (
                vm_integration.get("reason")
                if isinstance(vm_integration, dict) else None),
        })

    if gameplay_backend.get("status") != "translated-live-certified":
        blockers.append({
            "code": "PZCLOSURE007",
            "component": "gameplay_backend",
            "reason": "the gameplay backend is still a legacy template",
            "status": gameplay_backend.get("status"),
        })

    if sprite_backend.get("status") != "translated-live-certified":
        blockers.append({
            "code": "PZCLOSURE008",
            "component": "sprite_backend",
            "reason": "the sprite backend is still a legacy template",
            "status": sprite_backend.get("status"),
        })

    if (frame_budget.get("status") != "PASS" or
            frame_budget.get("full_frame_proved") is not True):
        blockers.append({
            "code": "PZCLOSURE009",
            "component": "whole_frame_ft812_budget",
            "reason": (
                "RAM_DL and 1209-cycle scanline budgets are not certified "
                "for the complete frame"),
            "status": frame_budget.get("status"),
            "evidence": frame_budget.get(
                "blockers", frame_budget.get("diagnostic")),
        })

    state_integration = draw_state_backend.get(
        "compile_manifest_integration", {})
    if (not isinstance(state_integration, dict) or
            state_integration.get("live_target_hooks_present") is not True):
        blockers.append({
            "code": "PZCLOSURE010",
            "component": "draw_state_backend",
            "reason": (
                "persistent Python draw fields/classes are not synchronized "
                "by live mutation and lifecycle hooks"),
            "status": draw_state_backend.get("status"),
            "evidence": (
                state_integration.get("reason")
                if isinstance(state_integration, dict) else None),
        })

    if frame_budget_live_hook.get("present") is not True:
        blockers.append({
            "code": "PZCLOSURE011",
            "component": "frame_budget_live_hook",
            "reason": (
                "the certified record counter/budget is not enforced before "
                "atomic frame publication"),
            "status": frame_budget_live_hook.get("status"),
            "evidence": frame_budget_live_hook.get("blockers", []),
        })

    fast_integration = draw_fast_pipeline.get(
        "compile_manifest_integration", {})
    if (not isinstance(fast_integration, dict) or
            fast_integration.get(
                "live_target_performance_size_stack_certified") is not True):
        blockers.append({
            "code": "PZCLOSURE012",
            "component": "draw_fast_pipeline",
            "reason": (
                "compact VM output is not fully linked/certified through the "
                "six-byte FT812 fast batch"),
            "status": draw_fast_pipeline.get("status"),
            "evidence": (
                fast_integration.get("reason")
                if isinstance(fast_integration, dict) else None),
        })

    if draw_target_bundle.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE013",
            "component": "draw_target_bundle",
            "reason": (
                "the selected draw pipeline is not placed, linked and stack-"
                "certified as a complete live target path"),
            "status": draw_target_bundle.get("status"),
            "evidence": draw_target_bundle.get("live_blockers", []),
        })

    if mutation_hook_ir.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE014",
            "component": "mutation_hook_ir",
            "reason": (
                "source-derived object mutation/getter/lifecycle hooks are "
                "not consumed by the live target frontend/provider"),
            "status": mutation_hook_ir.get("status"),
            "evidence": mutation_hook_ir.get("live_blockers", []),
        })

    if object_store_ir.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE015",
            "component": "object_store_ir",
            "reason": (
                "effect-SSA stores and expression CFGs are not embedded in "
                "the complete gameplay CFG/live C sidecar provider"),
            "status": object_store_ir.get("status"),
            "evidence": object_store_ir.get("live_blockers", []),
        })

    if draw_bank_placement.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE016",
            "component": "draw_bank_placement",
            "reason": (
                "the proved F1/F2 links and resident gate are not installed "
                "by the production final link/packer/callback path"),
            "status": draw_bank_placement.get("status"),
            "evidence": draw_bank_placement.get("live_blockers", []),
        })

    if (frame_sprite_fragment_envelope.get("proof_complete") is not True or
            frame_sprite_fragment_envelope.get("live_eligible") is not True):
        blockers.append({
            "code": "PZCLOSURE017",
            "component": "frame_sprite_fragment_envelope",
            "reason": (
                "reachable HQT3/CMD_APPEND identities and the weighted "
                "768-line sprite envelope are not live/prepublication-certified"),
            "status": frame_sprite_fragment_envelope.get("status"),
            "evidence": frame_sprite_fragment_envelope.get(
                "blockers", frame_sprite_fragment_envelope.get(
                    "integration_gates", [])),
        })

    if function_cfg_ir.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE018",
            "component": "active_function_cfg_ir",
            "reason": (
                "the complete active-Python function CFG is not consumed by "
                "the live C/VM provider and final target link"),
            "status": function_cfg_ir.get("status"),
            "evidence": function_cfg_ir.get("live_blockers", []),
        })

    if full_hqt3_inventory.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE019",
            "component": "full_hqt3_inventory",
            "reason": (
                "the complete template catalogue has no proved lifetime, "
                "load-transition and RAM_G resident-pack schedule"),
            "status": full_hqt3_inventory.get("status"),
            "evidence": full_hqt3_inventory.get("blockers", []),
        })

    if hqt3_ramg_schedule.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE020",
            "component": "hqt3_ramg_schedule",
            "reason": (
                "the source-derived HQT3 packs have no complete RAM_G/4 MiB "
                "lifetime, transition, allocation and upload schedule"),
            "status": hqt3_ramg_schedule.get("status"),
            "evidence": hqt3_ramg_schedule.get("blockers", []),
        })

    if hqt3_partition_solver.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE021",
            "component": "hqt3_partition_solver",
            "reason": (
                "source-safe HQT shards are not yet backed by proved RAM_G "
                "page exclusivity, object lifetimes and FT812 eviction fences"),
            "status": hqt3_partition_solver.get("status"),
            "evidence": hqt3_partition_solver.get("blockers", []),
        })

    if active_call_graph.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE022",
            "component": "active_call_graph",
            "reason": (
                "the whole active callable CFG still has unresolved dispatch, "
                "host boundaries, module initialization and no live backend"),
            "status": active_call_graph.get("status"),
            "evidence": active_call_graph.get("live_blockers", []),
        })

    if hqt3_frame_page_solver.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE023",
            "component": "hqt3_frame_page_solver",
            "reason": (
                "the exact current/next-frame page union, FT812 retirement "
                "fence and measured 55 Hz upload deadline remain unproved"),
            "status": hqt3_frame_page_solver.get("status"),
            "evidence": hqt3_frame_page_solver.get("blockers", []),
        })

    if active_target_adapters.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE024",
            "component": "active_target_adapters",
            "reason": (
                "reachable host/hardware calls are inventoried, but their "
                "exact target ABIs, module initialization and 55 Hz timing "
                "provider are not all connected to the live backend"),
            "status": active_target_adapters.get("status"),
            "evidence": active_target_adapters.get("live_blockers", []),
        })

    if frame_timing_provider.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE025",
            "component": "frame_timing_provider",
            "reason": (
                "the source-derived 55 Hz FT812 VCYCLE contract is generated, "
                "but final-link, DLSWAP cadence and measured-device timing "
                "proofs are not complete"),
            "status": frame_timing_provider.get("status"),
            "evidence": frame_timing_provider.get("live_blockers", []),
        })

    if draw_ramdl_shadow_v4.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE026",
            "component": "draw_ramdl_shadow_v4",
            "reason": (
                "the deduplicated atomic direct-RAM_DL frame fits the current "
                "active catalogue, but translator hooks, physical page owner, "
                "hardware WCET, ISR composition and final retirement wrapper "
                "are not proved live"),
            "status": draw_ramdl_shadow_v4.get("status"),
            "evidence": draw_ramdl_shadow_v4.get("blockers", []),
        })

    if whole_program_vm.get("live") is not True:
        blockers.append({
            "code": "PZCLOSURE027",
            "component": "whole_program_vm",
            "reason": (
                "all source-proven reachable CFGs are encoded into bankable "
                "PZVM, but real Python/host adapters, active generator "
                "execution, final link and whole-game stack/WCET proofs remain"),
            "status": whole_program_vm.get("format"),
            "evidence": whole_program_vm.get("live_blockers", []),
        })

    if (whole_program_vm_stack_bound.get("complete_bound_proved") is not True
            or whole_program_vm_stack_bound.get("live") is not True):
        blockers.append({
            "code": "PZCLOSURE028",
            "component": "whole_program_vm_stack_bound",
            "reason": (
                "the iterative PZVT arena and Z80 hardware stack have no "
                "complete whole-program bound including dynamic dispatch, "
                "callbacks, bank reader and ISR pre-emption"),
            "status": whole_program_vm_stack_bound.get("format"),
            "evidence": whole_program_vm_stack_bound.get(
                "live_blockers", []),
        })

    if not whole_program_vm_consumes_call_site_lowering(
            whole_program_vm, active_call_site_lowering):
        blockers.append({
            "code": "PZCLOSURE029",
            "component": "whole_program_vm",
            "reason": (
                "PZVT does not consume the reachable CFG call-site lowering "
                "through exact path-specific and semantic-digest bindings"),
            "status": whole_program_vm.get("format"),
            "evidence": whole_program_vm.get(
                "live_blockers", []),
        })

    if not whole_program_vm_consumes_call_abi(
            whole_program_vm, active_call_site_lowering,
            whole_program_vm_call_abi):
        blockers.append({
            "code": "PZCLOSURE030",
            "component": "whole_program_vm",
            "reason": (
                "the per-occurrence numeric function/receiver/argument ABI "
                "is not consumed by PZVT with exact CFG-path and semantic-"
                "digest bindings to both ABI inputs"),
            "status": whole_program_vm.get("format"),
            "evidence": whole_program_vm.get(
                "live_blockers", []),
        })

    return {
        "format": "rtype-python-translation-closure-v1",
        "complete": not blockers,
        "policy": "all active-Python and live-target proofs must pass",
        "blocker_count": len(blockers),
        "blockers": blockers,
    }


def _render_order_backend_contract(
        artifacts: RenderOrderArtifacts, output_directory: Path,
        project_root: Path = ROOT) -> dict[str, Any]:
    """Bind the compact object order to the active Python list semantics."""
    model = build_render_order_model(project_root)
    try:
        manifest = json.loads(artifacts.manifest)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "render-order backend: generated manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise TranslationError(
            "render-order backend: manifest root must be an object")
    if (manifest.get("format") != RENDER_ORDER_BACKEND_FORMAT or
            manifest.get("prefix") != RENDER_ORDER_PREFIX or
            manifest.get("status") !=
            "TARGET_NEUTRAL_GENERATED_LIVE_BLOCKED" or
            manifest.get("live") is not False or
            manifest.get("semantic_sha256") != model.semantic_sha256):
        raise TranslationError(
            "render-order backend: format/status/source semantic binding "
            "changed")

    active_source = manifest.get("active_source")
    pool = manifest.get("source_derived_pool")
    draw_order = manifest.get("draw_order")
    checkpoint = manifest.get("checkpoint_seed")
    mutations = manifest.get("audited_mutation_inventory")
    expected_mutation_sites = [
        {"line": line, "kind": kind, "source": source}
        for line, kind, source in model.enemy_mutations
    ]
    if (not isinstance(active_source, dict) or
            active_source.get("entrypoint") != "rtype_port.app" or
            active_source.get("launcher") != "run_python.cmd" or
            active_source.get("launcher_sha256") != model.launcher_sha256 or
            active_source.get("module") !=
            "Source/Python/rtype_port/enemies.py" or
            active_source.get("module_sha256") != model.source_sha256 or
            not isinstance(pool, dict) or
            pool.get("slot_count") != model.slot_count or
            pool.get("reserved_sentinel_count") !=
            model.reserved_sentinel_count or
            pool.get("allocatable_capacity") != model.capacity or
            pool.get("physical_first") != model.slot_first or
            pool.get("physical_stop_exclusive") != model.slot_stop_exclusive or
            pool.get("physical_stride") != model.slot_stride or
            pool.get("allocator_ast_sha256") != model.allocator_ast_sha256 or
            pool.get("pending_append_ast_sha256") !=
            model.pending_append_ast_sha256 or
            not isinstance(draw_order, dict) or
            draw_order.get("direct_python_list_order") is not True or
            draw_order.get("outer_loop_ast_sha256") !=
            model.draw_loop_ast_sha256 or
            not isinstance(checkpoint, dict) or
            checkpoint.get("ast_sha256") != model.checkpoint_seed_ast_sha256 or
            checkpoint.get("normalized_slot_indices") !=
            list(model.checkpoint_slot_indices) or
            checkpoint.get("preserves_python_list_order") is not True or
            not isinstance(mutations, dict) or
            mutations.get("count") != len(model.enemy_mutations) or
            mutations.get("sites") != expected_mutation_sites or
            mutations.get("unexpected_mutation_policy") !=
            "generation fails closed"):
        raise TranslationError(
            "render-order backend: active Python pool/list audit is stale")

    expected_names = {
        "header": f"{RENDER_ORDER_PREFIX}.h",
        "source": f"{RENDER_ORDER_PREFIX}.c",
        "manifest": f"{RENDER_ORDER_PREFIX}.json",
    }
    actual_names = {
        "header": artifacts.header_name,
        "source": artifacts.source_name,
        "manifest": artifacts.manifest_name,
    }
    if actual_names != expected_names:
        raise TranslationError(
            "render-order backend: artifact names changed: "
            f"{actual_names!r} != {expected_names!r}")
    header_bytes = artifacts.header.encode("utf-8")
    source_bytes = artifacts.source.encode("utf-8")
    manifest_bytes = artifacts.manifest.encode("utf-8")
    header_sha256 = hashlib.sha256(header_bytes).hexdigest()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest.get("artifacts") != {
            "header": {
                "name": artifacts.header_name,
                "sha256": header_sha256,
                "utf8_bytes": len(header_bytes),
            },
            "source": {
                "name": artifacts.source_name,
                "sha256": source_sha256,
                "utf8_bytes": len(source_bytes),
            }}:
        raise TranslationError(
            "render-order backend: C/H hashes or byte counts changed")

    normalized = manifest.get("normalized_abi")
    verification = manifest.get("verification_contract")
    state = normalized.get("state") if isinstance(normalized, dict) else None
    operations = (
        normalized.get("operations") if isinstance(normalized, dict) else None)
    failure_atomicity = (
        normalized.get("failure_atomicity")
        if isinstance(normalized, dict) else None)
    if (not isinstance(state, dict) or
            state.get("target_bytes") != model.state_bytes or
            state.get("ordered_slot_index_bytes") != model.capacity or
            state.get("membership_position_bytes") != model.slot_count or
            state.get("full_object_copy_required") is not False or
            not isinstance(operations, dict) or
            operations.get("slot_at") != "O(1) direct VM-loader lookup" or
            operations.get("position_of") !=
            "O(1) membership/position lookup" or
            operations.get("filter") !=
            "stable survivor filter by membership mask" or
            not isinstance(failure_atomicity, dict) or
            failure_atomicity.get("append_remove_replace") !=
            "validate before mutation" or
            not isinstance(verification, dict) or
            verification.get("live_target_hooks_present") is not False):
        raise TranslationError(
            "render-order backend: compact/failure-atomic ABI changed")
    live_blockers = verification.get("live_blockers")
    if (not isinstance(live_blockers, list) or not live_blockers or
            not all(isinstance(item, str) and item for item in live_blockers)):
        raise TranslationError(
            "render-order backend: live blockers are missing")

    try:
        size_bytes = RENDER_ORDER_SIZE_STATUS.read_bytes()
        size_probe = json.loads(size_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "render-order backend: target size probe missing/invalid") from exc
    size_input = size_probe.get("input") if isinstance(size_probe, dict) else None
    size_result = (
        size_probe.get("result") if isinstance(size_probe, dict) else None)
    size_model = (
        size_probe.get("source_derived_model")
        if isinstance(size_probe, dict) else None)
    size_header = (
        size_input.get("header") if isinstance(size_input, dict) else None)
    size_source = (
        size_input.get("source") if isinstance(size_input, dict) else None)
    size_manifest = (
        size_input.get("manifest") if isinstance(size_input, dict) else None)
    code_bytes = (
        size_result.get("code_bytes") if isinstance(size_result, dict) else None)
    data_bytes = (
        size_result.get("data_bytes") if isinstance(size_result, dict) else None)
    page_bytes = (
        size_result.get("single_page_bytes")
        if isinstance(size_result, dict) else None)
    headroom = (
        size_result.get("page_headroom_bytes_before_adapter_and_runtime")
        if isinstance(size_result, dict) else None)
    if (not isinstance(size_probe, dict) or
            size_probe.get("format") !=
            "pyz80-render-order-target-size-probe-v1" or
            size_probe.get("status") !=
            "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED" or
            size_probe.get("live") is not False or
            not isinstance(size_input, dict) or
            size_input.get("semantic_sha256") != model.semantic_sha256 or
            size_input.get("active_python_source_sha256") !=
            model.source_sha256 or
            not isinstance(size_header, dict) or
            size_header.get("sha256") != header_sha256 or
            size_header.get("bytes") != len(header_bytes) or
            not isinstance(size_source, dict) or
            size_source.get("sha256") != source_sha256 or
            size_source.get("bytes") != len(source_bytes) or
            not isinstance(size_manifest, dict) or
            size_manifest.get("sha256") != manifest_sha256 or
            size_manifest.get("bytes") != len(manifest_bytes) or
            not isinstance(size_model, dict) or
            size_model.get("slot_count") != model.slot_count or
            size_model.get("capacity") != model.capacity or
            size_model.get("checkpoint_count") !=
            len(model.checkpoint_slot_indices) or
            size_model.get("audited_enemy_mutation_kinds") !=
            len(model.enemy_mutations) or
            not isinstance(code_bytes, int) or code_bytes <= 0 or
            not isinstance(page_bytes, int) or code_bytes > page_bytes or
            data_bytes != 0 or headroom != page_bytes - code_bytes or
            size_result.get("state_bytes") != model.state_bytes):
        raise TranslationError(
            "render-order backend: target size probe is stale/inconsistent")

    return {
        "format": manifest["format"],
        "status": "source-derived-target-neutral-live-blocked",
        "semantic_sha256": model.semantic_sha256,
        "active_source": active_source,
        "draw_order": draw_order,
        "source_derived_pool": {
            "slot_count": model.slot_count,
            "reserved_sentinel_count": model.reserved_sentinel_count,
            "capacity": model.capacity,
            "checkpoint_count": len(model.checkpoint_slot_indices),
            "audited_mutation_kinds": len(model.enemy_mutations),
        },
        "normalized_state": {
            "target_bytes": model.state_bytes,
            "full_object_copy_required": False,
            "slot_at": operations["slot_at"],
            "position_of": operations["position_of"],
            "stable_filter": operations["filter"],
            "failure_atomic": True,
        },
        "target_size_probe": {
            "path": _project_path(RENDER_ORDER_SIZE_STATUS),
            "sha256": hashlib.sha256(size_bytes).hexdigest(),
            "status": size_probe["status"],
            "code_bytes": code_bytes,
            "data_bytes": data_bytes,
            "state_bytes": model.state_bytes,
            "single_page_bytes": page_bytes,
            "page_headroom_bytes_before_adapter_and_runtime": headroom,
        },
        "artifacts": {
            "header": {
                "path": _project_path(
                    output_directory / artifacts.header_name),
                "size": len(header_bytes), "sha256": header_sha256,
            },
            "source": {
                "path": _project_path(
                    output_directory / artifacts.source_name),
                "size": len(source_bytes), "sha256": source_sha256,
            },
            "manifest": {
                "path": _project_path(
                    output_directory / artifacts.manifest_name),
                "size": len(manifest_bytes), "sha256": manifest_sha256,
                "semantic_sha256": model.semantic_sha256,
            },
        },
        "compile_manifest_integration": {
            "support_files_included": False,
            "live_target_hooks_present": False,
            "reason": "; ".join(live_blockers),
        },
    }


def _draw_state_backend_contract(
        plan: SpriteDrawPlanIR, artifacts: DrawStateArtifacts,
        output_directory: Path, project_root: Path = ROOT,
        ) -> dict[str, Any]:
    """Validate the persistent source-derived object state without going live."""
    model = build_draw_state_model(project_root, plan=plan)
    try:
        manifest = json.loads(artifacts.manifest)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw-state backend: generated manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise TranslationError(
            "draw-state backend: manifest root must be an object")
    if (manifest.get("format") != DRAW_STATE_BACKEND_FORMAT or
            manifest.get("status") !=
            "TARGET_NEUTRAL_PERSISTENT_SIDECAR_LIVE_BLOCKED" or
            manifest.get("live") is not False or
            manifest.get("semantic_sha256") != model.semantic_sha256 or
            manifest.get("prefix") != DRAW_STATE_PREFIX):
        raise TranslationError(
            "draw-state backend: format/status/source binding changed")

    active = manifest.get("active_source")
    pinned = manifest.get("pinned_inputs")
    vm_binding = pinned.get("draw_vm") if isinstance(pinned, dict) else None
    order_binding = (
        pinned.get("render_order") if isinstance(pinned, dict) else None)
    if (not isinstance(active, dict) or
            active.get("launcher") != "run_python.cmd" or
            active.get("entrypoint") != "rtype_port.app" or
            active.get("launcher_sha256") != model.launcher_sha256 or
            active.get("module") != plan.source_path or
            active.get("module_sha256") != model.source_sha256 or
            active.get("draw_method_ast_sha256") != plan.method_ast_sha256 or
            not isinstance(pinned, dict) or
            pinned.get("draw_plan_semantic_sha256") != plan.semantic_sha256 or
            not isinstance(vm_binding, dict) or
            vm_binding != {
                "semantic_sha256": model.draw_vm_semantic_sha256,
                "header_sha256": model.draw_vm_header_sha256,
                "source_sha256": model.draw_vm_source_sha256,
                "manifest_sha256": model.draw_vm_manifest_sha256,
            } or not isinstance(order_binding, dict) or
            order_binding != {
                "semantic_sha256": model.render_order_semantic_sha256,
                "header_sha256": model.render_order_header_sha256,
                "source_sha256": model.render_order_source_sha256,
                "manifest_sha256": model.render_order_manifest_sha256,
            }):
        raise TranslationError(
            "draw-state backend: active plan/VM/order hashes are stale")

    state = manifest.get("persistent_state")
    fields = manifest.get("normalized_fields")
    classes = manifest.get("concrete_classes")
    mutations = manifest.get("mutation_inventory")
    identities = manifest.get("concrete_identity_inventory")
    provider = manifest.get("provider_abi")
    verification = manifest.get("verification_contract")
    if (not isinstance(state, dict) or
            state.get("slot_count") != model.slot_count or
            state.get("reserved_sentinels") != model.reserved_sentinels or
            state.get("field_values_bytes_per_slot") != model.value_bytes or
            state.get("slot_state_bytes") != model.slot_state_bytes or
            state.get("state_bytes") != model.state_bytes or
            state.get("frame_materialization") is not False or
            not isinstance(fields, list) or
            len(fields) != len(model.fields) or
            not isinstance(classes, dict) or
            classes.get("object_root_class") != model.object_root_class or
            classes.get("count") != len(model.concrete_classes) or
            classes.get("manual_type_switch") is not False or
            not isinstance(mutations, dict) or
            mutations.get("direct_and_implicit_count") !=
            len(model.mutation_sites) or
            mutations.get("derived_field_count") !=
            len(model.derived_field_sites) or
            mutations.get("dynamic_write_blocker_count") !=
            len(model.dynamic_write_sites) or
            not isinstance(identities, dict) or
            identities.get("count") != len(model.identity_sites) or
            identities.get("runtime_hooks_present") is not False or
            not isinstance(provider, dict) or
            provider.get("function") !=
            f"{DRAW_STATE_PREFIX}_load_object" or
            provider.get("object_index_semantics") !=
            "Python render-order position" or
            provider.get("output_bytes") != 28 or
            provider.get("full_pool_copy_per_frame") is not False or
            provider.get("failure_leaves_object_out_unchanged") is not True or
            not isinstance(verification, dict)):
        raise TranslationError(
            "draw-state backend: persistent/provider ABI changed")
    live_blockers = verification.get("live_blockers")
    if (not isinstance(live_blockers, list) or not live_blockers or
            not all(isinstance(item, str) and item for item in live_blockers)):
        raise TranslationError(
            "draw-state backend: live blockers are missing")

    header_bytes = artifacts.header.encode("utf-8")
    source_bytes = artifacts.source.encode("utf-8")
    manifest_bytes = artifacts.manifest.encode("utf-8")
    artifact_manifest = manifest.get("artifacts")
    if artifact_manifest != {
            "header": {
                "name": artifacts.header_name,
                "sha256": hashlib.sha256(header_bytes).hexdigest(),
                "utf8_bytes": len(header_bytes),
            },
            "source": {
                "name": artifacts.source_name,
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                "utf8_bytes": len(source_bytes),
            }}:
        raise TranslationError(
            "draw-state backend: generated C/H hashes changed")

    try:
        size_bytes = DRAW_STATE_SIZE_STATUS.read_bytes()
        size_probe = json.loads(size_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw-state backend: pinned target size probe missing/invalid") from exc
    size_input = size_probe.get("input") if isinstance(size_probe, dict) else None
    size_sidecar = (
        size_input.get("sidecar") if isinstance(size_input, dict) else None)
    size_model = (
        size_probe.get("source_derived_model")
        if isinstance(size_probe, dict) else None)
    size_result = size_probe.get("result") if isinstance(size_probe, dict) else None
    expected_sidecar = {
        "header": {
            "path": "Source/C/generated/" + artifacts.header_name,
            "bytes": len(header_bytes),
            "sha256": hashlib.sha256(header_bytes).hexdigest(),
        },
        "source": {
            "path": "Source/C/generated/" + artifacts.source_name,
            "bytes": len(source_bytes),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "manifest": {
            "path": "Source/C/generated/" + artifacts.manifest_name,
            "bytes": len(manifest_bytes),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    }
    code_bytes = (
        size_result.get("code_bytes") if isinstance(size_result, dict) else None)
    page_bytes = (
        size_result.get("single_page_bytes")
        if isinstance(size_result, dict) else None)
    headroom = (
        size_result.get("page_headroom_bytes_before_linked_vm_order_runtime")
        if isinstance(size_result, dict) else None)
    if (not isinstance(size_probe, dict) or
            size_probe.get("format") !=
            "pyz80-draw-state-target-size-probe-v1" or
            size_probe.get("status") !=
            "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED" or
            size_probe.get("live") is not False or
            not isinstance(size_input, dict) or
            size_input.get("semantic_sha256") != model.semantic_sha256 or
            size_input.get("active_python_source_sha256") !=
            model.source_sha256 or
            size_input.get("draw_plan_semantic_sha256") !=
            plan.semantic_sha256 or
            size_sidecar != expected_sidecar or
            not isinstance(size_model, dict) or
            size_model.get("slot_count") != model.slot_count or
            size_model.get("normalized_field_count") != len(model.fields) or
            size_model.get("concrete_enemy_class_count") !=
            len(model.concrete_classes) or
            size_model.get("mutation_site_count") !=
            len(model.mutation_sites) or
            size_model.get("derived_field_site_count") !=
            len(model.derived_field_sites) or
            size_model.get("dynamic_write_blocker_count") !=
            len(model.dynamic_write_sites) or
            size_model.get("identity_site_count") != len(model.identity_sites) or
            not isinstance(size_result, dict) or
            not isinstance(code_bytes, int) or code_bytes <= 0 or
            size_result.get("data_bytes") != 0 or
            size_result.get("persistent_state_bytes") != model.state_bytes or
            size_result.get("slot_state_bytes") != model.slot_state_bytes or
            size_result.get("values_bytes") != model.value_bytes or
            not isinstance(page_bytes, int) or code_bytes > page_bytes or
            headroom != page_bytes - code_bytes):
        raise TranslationError(
            "draw-state backend: pinned target size probe is stale")
    size_blockers = size_probe.get("live_blockers")
    if (not isinstance(size_blockers, list) or not size_blockers or
            not all(isinstance(item, str) and item for item in size_blockers)):
        raise TranslationError(
            "draw-state backend: size probe live blockers are missing")

    return {
        "format": manifest["format"],
        "status": "source-derived-persistent-sidecar-live-blocked",
        "semantic_sha256": model.semantic_sha256,
        "active_source": active,
        "persistent_state": {
            "slot_count": model.slot_count,
            "slot_state_bytes": model.slot_state_bytes,
            "state_bytes": model.state_bytes,
            "frame_materialization": False,
            "normalized_field_count": len(model.fields),
            "concrete_enemy_class_count": len(model.concrete_classes),
        },
        "source_write_inventory": {
            "mutation_site_count": len(model.mutation_sites),
            "derived_field_site_count": len(model.derived_field_sites),
            "dynamic_write_blocker_count": len(model.dynamic_write_sites),
            "identity_site_count": len(model.identity_sites),
        },
        "provider": {
            "function": provider["function"],
            "object_index_semantics": provider["object_index_semantics"],
            "output_bytes": provider["output_bytes"],
            "full_pool_copy_per_frame": False,
        },
        "target_size_probe": {
            "path": _project_path(DRAW_STATE_SIZE_STATUS),
            "sha256": hashlib.sha256(size_bytes).hexdigest(),
            "status": size_probe["status"],
            "code_bytes": code_bytes,
            "data_bytes": 0,
            "persistent_state_bytes": model.state_bytes,
            "single_page_bytes": page_bytes,
            "page_headroom_bytes_before_linked_runtime": headroom,
        },
        "artifacts": {
            role: {
                "path": _project_path(output_directory / name),
                "size": len(value.encode("utf-8")),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
            for role, name, value in (
                ("header", artifacts.header_name, artifacts.header),
                ("source", artifacts.source_name, artifacts.source),
                ("manifest", artifacts.manifest_name, artifacts.manifest),
            )
        },
        "compile_manifest_integration": {
            "support_files_included": False,
            "live_target_hooks_present": False,
            "reason": "; ".join(dict.fromkeys(
                [*live_blockers, *size_blockers])),
        },
    }


def draw_fast_pipeline_contract(
        draw_vm_backend: dict[str, Any],
        hq_asset_summary: dict[str, Any],
        ) -> dict[str, Any]:
    """Validate the compact VM -> generated lookup -> six-byte FT812 bridge."""
    try:
        status_bytes = DRAW_FAST_CHUNKER_STATUS.read_bytes()
        timing_bytes = DRAW_FAST_CHUNKER_TIMING.read_bytes()
        status = json.loads(status_bytes.decode("utf-8"))
        timing = json.loads(timing_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "fast draw pipeline: size/oracle/timing certificate missing or "
            "invalid") from exc
    if not isinstance(status, dict) or not isinstance(timing, dict):
        raise TranslationError(
            "fast draw pipeline: certificate roots must be objects")

    paths = {
        "asset_manifest": HQ_ASSET_MANIFEST,
        "bridge_header": DRAW_FAST_CHUNKER_HEADER,
        "bridge_source": DRAW_FAST_CHUNKER_SOURCE,
        "ft812_header": ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.h",
        "ft812_source": ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.c",
        "host_test": ROOT / "Source" / "Tools" /
        "test_pyz80_draw_fast_chunker.py",
        "hq_header": ROOT / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.h",
        "hq_source": ROOT / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.c",
        "timing_report": DRAW_FAST_CHUNKER_TIMING,
        "vm_header": OUT_DRAW_VM_HEADER,
        "vm_manifest": OUT_DRAW_VM_MANIFEST,
    }
    inputs = status.get("input")
    if not isinstance(inputs, dict):
        raise TranslationError("fast draw pipeline: input hashes are missing")
    actual_hashes: dict[str, str] = {}
    for name, path in paths.items():
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise TranslationError(
                f"fast draw pipeline: missing input {path}") from exc
        record = inputs.get(name)
        digest = hashlib.sha256(payload).hexdigest()
        actual_hashes[name] = digest
        if (not isinstance(record, dict) or
                record.get("path") != _project_path(path) or
                record.get("bytes") != len(payload) or
                record.get("sha256") != digest):
            raise TranslationError(
                f"fast draw pipeline: stale input binding {name}")

    source_binding = status.get("source_binding")
    bridge = status.get("bridge_contract")
    result = status.get("result")
    performance = status.get("performance")
    checks = status.get("checks")
    failure = status.get("failure_atomicity")
    vm_plan = draw_vm_backend.get("plan")
    templates = hq_asset_summary.get("sprite_templates")
    if (status.get("format") !=
            "pyz80-draw-fast-chunker-target-size-probe-v1" or
            status.get("status") !=
            "TARGET_NEUTRAL_FAST_BRIDGE_PASS_LIVE_BLOCKED" or
            status.get("live") is not False or
            not isinstance(source_binding, dict) or
            not isinstance(vm_plan, dict) or
            source_binding.get("draw_plan_semantic_sha256") !=
            vm_plan.get("semantic_sha256") or
            source_binding.get("draw_vm_format") != DRAW_VM_BACKEND_FORMAT or
            source_binding.get("manual_mapping_table") is not False or
            source_binding.get("lookup_export") != "PyZ80FT_FindHQTemplate" or
            not isinstance(templates, dict) or
            source_binding.get("hq_template_count") !=
            templates.get("record_count") or
            not isinstance(bridge, dict) or
            bridge.get("full_frame_record_array_required") is not False or
            bridge.get("maximum_chunk_records") != 128 or
            bridge.get("maximum_caller_chunk_bytes") != 768 or
            bridge.get("ordering") !=
            "strict active-Python VM emission order; no sort" or
            bridge.get("fast_batch_export") !=
            "PyZ80FT_BuildSpriteBatchFast" or
            not isinstance(result, dict) or
            result.get("data_bytes") != 0 or
            not isinstance(result.get("code_bytes"), int) or
            result.get("code_bytes") <= 0 or
            result.get("compact_vm_code_bytes") !=
            draw_vm_backend.get("target_size_probe", {}).get("code_bytes") or
            result.get("compact_vm_plus_bridge_additive_code_upper_bound") !=
            result.get("code_bytes") + result.get("compact_vm_code_bytes") or
            result.get("fast_batch_call_sites") != 1 or
            result.get("generated_lookup_call_sites") != 1 or
            not isinstance(checks, dict) or
            checks.get("no_full_frame_record_array_required") is not True or
            checks.get("failure_matrix_covered") is not True or
            not isinstance(failure, dict) or
            not isinstance(performance, dict)):
        raise TranslationError(
            "fast draw pipeline: VM/HQT3/six-byte bridge contract changed")

    timing_hashes = timing.get("source_hashes")
    timing_measurement = timing.get("measurement")
    steady = (
        timing_measurement.get("steady_nonflush_record")
        if isinstance(timing_measurement, dict) else None)
    chunk32 = (
        timing_measurement.get("modeled_32_record_chunk_before_fast_batch")
        if isinstance(timing_measurement, dict) else None)
    expected_timing_sources = {
        _project_path(path): actual_hashes[name]
        for name, path in paths.items()
        if name in {
            "bridge_header", "bridge_source", "ft812_header", "ft812_source",
            "hq_header", "hq_source", "vm_header",
        }
    }
    if (timing.get("format") !=
            "pyz80-draw-fast-chunker-z80-timing-v1" or
            timing.get("status") !=
            "TARGET_NEUTRAL_MICROBENCH_PASS_LIVE_BLOCKED" or
            timing.get("live") is not False or
            timing_hashes != expected_timing_sources or
            not isinstance(steady, dict) or
            steady.get("all_samples_equal") is not True or
            not isinstance(steady.get("net_tstates"), int) or
            steady.get("net_tstates") <= 0 or
            not isinstance(chunk32, dict) or
            not isinstance(chunk32.get("net_tstates"), int) or
            chunk32.get("net_tstates") <= 0 or
            performance.get("steady_nonflush_record_tstates") !=
            steady.get("net_tstates") or
            performance.get(
                "modeled_32_record_chunk_before_fast_batch_tstates") !=
            chunk32.get("net_tstates") or
            performance.get("live_certified") is not False or
            inputs["timing_report"].get("sha256") !=
            hashlib.sha256(timing_bytes).hexdigest()):
        raise TranslationError(
            "fast draw pipeline: pinned Z80 timing certificate is stale")

    live_blockers = status.get("live_blockers")
    timing_blockers = timing.get("live_blockers")
    if (not isinstance(live_blockers, list) or not live_blockers or
            not isinstance(timing_blockers, list) or not timing_blockers):
        raise TranslationError(
            "fast draw pipeline: live blockers are missing")
    return {
        "format": status["format"],
        "status": "target-neutral-fast-pipeline-live-blocked",
        "source_binding": source_binding,
        "bridge_contract": bridge,
        "failure_atomicity": failure,
        "target_size_probe": {
            "path": _project_path(DRAW_FAST_CHUNKER_STATUS),
            "sha256": hashlib.sha256(status_bytes).hexdigest(),
            "code_bytes": result["code_bytes"],
            "data_bytes": result["data_bytes"],
            "vm_plus_bridge_additive_code_upper_bound":
                result["compact_vm_plus_bridge_additive_code_upper_bound"],
            "vm_plus_bridge_additive_headroom_bytes":
                result["compact_vm_plus_bridge_additive_headroom_bytes"],
        },
        "pinned_z80_timing": {
            "path": _project_path(DRAW_FAST_CHUNKER_TIMING),
            "sha256": hashlib.sha256(timing_bytes).hexdigest(),
            "steady_nonflush_record_tstates": steady["net_tstates"],
            "chunk32_before_fast_batch_tstates": chunk32["net_tstates"],
            "fast_batch_body_included": False,
        },
        "compile_manifest_integration": {
            "support_files_included": False,
            "live_target_performance_size_stack_certified": False,
            "reason": "; ".join(dict.fromkeys(
                [*live_blockers, *timing_blockers])),
        },
    }


def _draw_vm_backend_contract(
        plan: SpriteDrawPlanIR, artifacts: DrawCArtifacts,
        output_directory: Path) -> dict[str, Any]:
    """Validate the selected compact lowering before it can be materialized.

    Passing this contract proves that the VM is a deterministic, one-view
    lowering of the current active-Python draw plan and that its pinned SDCC
    object fits one 16-KiB page by itself.  It deliberately does *not* claim a
    live target hook: target field mapping, stack bytes, complete link size and
    frame timing remain separate mandatory certificates.
    """
    try:
        manifest = json.loads(artifacts.manifest)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw VM backend: generated manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise TranslationError(
            "draw VM backend: manifest root must be an object")
    if manifest.get("format") != DRAW_VM_BACKEND_FORMAT:
        raise TranslationError(
            "draw VM backend: unexpected manifest format "
            f"{manifest.get('format')!r}")

    plan_manifest = manifest.get("plan")
    if not isinstance(plan_manifest, dict):
        raise TranslationError("draw VM backend: missing plan manifest")
    expected_plan = {
        "format": plan.format,
        "symbol": plan.symbol,
        "source_path": plan.source_path,
        "source_sha256": plan.source_sha256,
        "method_ast_sha256": plan.method_ast_sha256,
        "semantic_sha256": plan.semantic_sha256,
        "sink_order_sha256": plan.sink_order_sha256,
        "action_count": len(plan.actions),
    }
    actual_plan = {key: plan_manifest.get(key) for key in expected_plan}
    if actual_plan != expected_plan:
        raise TranslationError(
            "draw VM backend: manifest is not bound to the compiled "
            f"SpriteDrawPlanIR: {actual_plan!r} != {expected_plan!r}")

    expected_names = {
        "header": f"{DRAW_VM_PREFIX}.h",
        "source": f"{DRAW_VM_PREFIX}.c",
        "manifest": f"{DRAW_VM_PREFIX}.json",
    }
    actual_names = {
        "header": artifacts.header_name,
        "source": artifacts.source_name,
        "manifest": artifacts.manifest_name,
    }
    if actual_names != expected_names:
        raise TranslationError(
            "draw VM backend: generated artifact names changed: "
            f"{actual_names!r} != {expected_names!r}")

    header_bytes = artifacts.header.encode("utf-8")
    source_bytes = artifacts.source.encode("utf-8")
    manifest_bytes = artifacts.manifest.encode("utf-8")
    header_sha256 = hashlib.sha256(header_bytes).hexdigest()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    expected_artifact_manifest = {
        "header": {
            "name": artifacts.header_name,
            "sha256": header_sha256,
            "utf8_bytes": len(header_bytes),
        },
        "source": {
            "name": artifacts.source_name,
            "sha256": source_sha256,
            "utf8_bytes": len(source_bytes),
        },
    }
    if manifest.get("artifacts") != expected_artifact_manifest:
        raise TranslationError(
            "draw VM backend: C/H hashes or byte counts do not match manifest")

    normalized_abi = manifest.get("normalized_abi")
    verification = manifest.get("verification_contract")
    vm = manifest.get("vm")
    if (not isinstance(normalized_abi, dict) or
            not isinstance(verification, dict) or
            not isinstance(vm, dict)):
        raise TranslationError(
            "draw VM backend: normalized ABI/VM/verification contract missing")
    output_record = normalized_abi.get("output_record")
    failure_atomicity = normalized_abi.get("failure_atomicity")
    streaming = normalized_abi.get("streaming")
    object_view = normalized_abi.get("object_view")
    provider = (
        object_view.get("provider") if isinstance(object_view, dict) else None)
    if (not isinstance(output_record, dict) or
            output_record.get("size") != 8 or
            not isinstance(failure_atomicity, dict) or
            failure_atomicity.get(
                "produce_non_ok_output_buffer_unchanged") is not True or
            failure_atomicity.get(
                "object_loader_failure_during_preflight_atomic") is not True):
        raise TranslationError(
            "draw VM backend: 8-byte failure-atomic record ABI changed")
    if (not isinstance(streaming, dict) or
            streaming.get("function") != f"{DRAW_VM_PREFIX}_stream" or
            streaming.get("record_array_required") is not False or
            streaming.get("preflight_before_first_emission") is not True or
            streaming.get(
                "emitter_failure_reports_accepted_prefix") is not True):
        raise TranslationError(
            "draw VM backend: bounded streaming ABI changed")
    if (not isinstance(object_view, dict) or
            object_view.get("input_shape") !=
            "provider-or-contiguous-normalized-array" or
            object_view.get("exact_target_size_bytes") != 28 or
            object_view.get("field_storage_bytes_without_target_padding") != 28 or
            object_view.get("full_pool_materialization_required") is not False or
            object_view.get("single_working_view_abi_certified") is not True or
            object_view.get("working_view_count") != 1 or
            object_view.get("working_view_bytes") != 28 or
            not isinstance(provider, dict) or
            provider.get("calls_per_item_per_pass") != 1 or
            provider.get("failure_before_first_output") is not True or
            provider.get(
                "resolver_or_emitter_calls_before_preflight_failure") != 0):
        raise TranslationError(
            "draw VM backend: zero-copy one-view provider ABI changed")
    vm_counts = vm.get("counts")
    vm_table_bytes = vm.get("logical_table_bytes")
    if (not isinstance(vm_counts, dict) or
            vm_counts.get("actions") != len(plan.actions) or
            not isinstance(vm_table_bytes, dict) or
            not isinstance(vm_table_bytes.get("total"), int) or
            vm_table_bytes["total"] <= 0 or
            vm.get("limits", {}).get("fail_closed") is not True):
        raise TranslationError(
            "draw VM backend: compact program bounds are missing or stale")
    if verification.get(
            "live_target_performance_and_size_certified") is not False:
        raise TranslationError(
            "draw VM backend: live state must remain false until all target "
            "certificates pass")
    blockers = verification.get("certification_blockers")
    if (not isinstance(blockers, list) or not blockers or
            not all(isinstance(item, str) and item for item in blockers)):
        raise TranslationError(
            "draw VM backend: live certification blockers are missing")

    try:
        size_probe_bytes = DRAW_VM_SIZE_STATUS.read_bytes()
        size_probe = json.loads(size_probe_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw VM backend: target size probe is missing or invalid") from exc
    if not isinstance(size_probe, dict):
        raise TranslationError(
            "draw VM backend: target size probe root must be an object")
    size_input = size_probe.get("input")
    size_result = size_probe.get("result")
    size_normalized = size_probe.get("normalized_input_abi")
    size_source = (
        size_input.get("source") if isinstance(size_input, dict) else None)
    size_header = (
        size_input.get("header") if isinstance(size_input, dict) else None)
    size_manifest = (
        size_input.get("manifest") if isinstance(size_input, dict) else None)
    page_bytes = (
        size_result.get("single_page_bytes")
        if isinstance(size_result, dict) else None)
    code_bytes = (
        size_result.get("code_bytes")
        if isinstance(size_result, dict) else None)
    data_bytes = (
        size_result.get("data_bytes")
        if isinstance(size_result, dict) else None)
    headroom_bytes = (
        size_result.get("page_headroom_bytes_before_adapter_and_runtime")
        if isinstance(size_result, dict) else None)
    pinned_sizes = (
        size_normalized.get("pinned_sdcc_sizeof")
        if isinstance(size_normalized, dict) else None)
    size_provider = (
        size_normalized.get("object_provider")
        if isinstance(size_normalized, dict) else None)
    source_pool = (
        size_normalized.get("source_derived_pool")
        if isinstance(size_normalized, dict) else None)
    if (size_probe.get("format") !=
            "pyz80-draw-vm-target-size-probe-v2" or
            size_probe.get("status") !=
            "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED" or
            size_probe.get(
                "live_target_performance_and_size_certified") is not False or
            not isinstance(size_input, dict) or
            size_input.get("plan_semantic_sha256") != plan.semantic_sha256 or
            not isinstance(size_source, dict) or
            size_source.get("sha256") != source_sha256 or
            size_source.get("bytes") != len(source_bytes) or
            not isinstance(size_header, dict) or
            size_header.get("sha256") != header_sha256 or
            size_header.get("bytes") != len(header_bytes) or
            not isinstance(size_manifest, dict) or
            size_manifest.get("sha256") != manifest_sha256 or
            size_manifest.get("bytes") != len(manifest_bytes) or
            not isinstance(code_bytes, int) or code_bytes <= 0 or
            not isinstance(page_bytes, int) or code_bytes > page_bytes or
            data_bytes != 0 or headroom_bytes != page_bytes - code_bytes or
            not isinstance(size_normalized, dict) or
            size_normalized.get("live_adapter_status") !=
            "PROVIDER_ABI_READY_TARGET_LAYOUT_MAPPING_BLOCKED" or
            not isinstance(size_provider, dict) or
            size_provider.get("abi_present") is not True or
            not isinstance(pinned_sizes, dict) or
            pinned_sizes.get("object_view_bytes") != 28 or
            not isinstance(source_pool, dict) or
            source_pool.get("full_pool_copy_required") is not False or
            source_pool.get("working_object_view_count") != 1 or
            source_pool.get("working_object_view_bytes") != 28):
        raise TranslationError(
            "draw VM backend: target size/zero-copy probe is stale or "
            "inconsistent")
    size_blockers = size_probe.get("live_blockers")
    if (not isinstance(size_blockers, list) or not size_blockers or
            not all(isinstance(item, str) and item for item in size_blockers)):
        raise TranslationError(
            "draw VM backend: target size probe omitted live blockers")

    try:
        stack_bytes = DRAW_VM_STACK_STATUS.read_bytes()
        stack_probe = json.loads(stack_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw VM backend: pinned SDCC stack certificate missing/invalid") from exc
    stack_input = (
        stack_probe.get("input") if isinstance(stack_probe, dict) else None)
    stack_result = (
        stack_probe.get("result") if isinstance(stack_probe, dict) else None)
    stack_dag = (
        stack_probe.get("expression_dag")
        if isinstance(stack_probe, dict) else None)
    stack_functions = (
        stack_probe.get("functions") if isinstance(stack_probe, dict) else None)
    stack_public = (
        stack_probe.get("public_entries")
        if isinstance(stack_probe, dict) else None)
    stack_callbacks = (
        stack_probe.get("callback_contracts")
        if isinstance(stack_probe, dict) else None)
    stack_checks = (
        stack_probe.get("checks") if isinstance(stack_probe, dict) else None)
    stack_source = (
        stack_input.get("source") if isinstance(stack_input, dict) else None)
    stack_header = (
        stack_input.get("header") if isinstance(stack_input, dict) else None)
    stack_manifest = (
        stack_input.get("manifest") if isinstance(stack_input, dict) else None)
    stack_plan = (
        stack_input.get("plan") if isinstance(stack_input, dict) else None)
    stack_size = (
        stack_input.get("size_report")
        if isinstance(stack_input, dict) else None)
    produce_stack = (
        stack_public.get(f"{DRAW_VM_PREFIX}_produce")
        if isinstance(stack_public, dict) else None)
    stream_stack = (
        stack_public.get(f"{DRAW_VM_PREFIX}_stream")
        if isinstance(stack_public, dict) else None)
    eval_stack = (
        stack_functions.get(f"{DRAW_VM_PREFIX}_eval")
        if isinstance(stack_functions, dict) else None)
    walk_stack = (
        stack_functions.get(f"{DRAW_VM_PREFIX}_walk")
        if isinstance(stack_functions, dict) else None)
    expected_callback_boundaries = {
        "resolve_resource_type": 214,
        "load_object": 133,
        "resolve_bank_key": 133,
        "emit_record": 131,
    }
    actual_callback_boundaries = {
        name: (
            row.get(
                "maximum_internal_bytes_to_entry_including_public_arguments")
            if isinstance(row, dict) else None)
        for name, row in (
            stack_callbacks.items()
            if isinstance(stack_callbacks, dict) else ())
    }
    callback_rows_valid = (
        isinstance(stack_callbacks, dict) and
        set(stack_callbacks) == set(expected_callback_boundaries) and
        all(isinstance(row, dict) and
            row.get("status") == "MISSING_EXTERNAL_STACK_BOUND" and
            row.get("maximum_additional_stack_bytes_from_entry_sp") is None
            for row in stack_callbacks.values()))
    stack_actual_plan = (
        {key: stack_plan.get(key) for key in expected_plan}
        if isinstance(stack_plan, dict) else None)
    if (not isinstance(stack_probe, dict) or
            stack_probe.get("format") !=
            "pyz80-draw-vm-pinned-sdcc-stack-certificate-v1" or
            stack_probe.get("status") !=
            "INTERNAL_STACK_BOUND_PASS_EXTERNAL_CALLBACKS_BLOCKED" or
            not isinstance(stack_input, dict) or
            not isinstance(stack_source, dict) or
            stack_source.get("sha256") != source_sha256 or
            stack_source.get("bytes") != len(source_bytes) or
            not isinstance(stack_header, dict) or
            stack_header.get("sha256") != header_sha256 or
            stack_header.get("bytes") != len(header_bytes) or
            not isinstance(stack_manifest, dict) or
            stack_manifest.get("sha256") != manifest_sha256 or
            stack_manifest.get("bytes") != len(manifest_bytes) or
            stack_actual_plan != expected_plan or
            not isinstance(stack_size, dict) or
            stack_size.get("format") != size_probe["format"] or
            stack_size.get("status") != size_probe["status"] or
            stack_size.get("sha256") !=
            hashlib.sha256(size_probe_bytes).hexdigest() or
            stack_size.get("bytes") != len(size_probe_bytes) or
            not isinstance(stack_result, dict) or
            stack_result.get("internal_vm_stack_bound_certified") is not True or
            stack_result.get(
                "maximum_internal_stack_bytes_including_public_arguments") !=
            241 or
            stack_result.get(
                "complete_vm_plus_callbacks_stack_bound_certified") is not False or
            stack_result.get("complete_vm_plus_callbacks_stack_bytes") is not None or
            stack_result.get("live_target_use_certified") is not False or
            stack_result.get("missing_external_callback_bounds") !=
            list(expected_callback_boundaries) or
            not isinstance(stack_dag, dict) or
            stack_dag.get("node_count") != vm_counts["nodes"] or
            stack_dag.get("logical_max_recursive_eval_depth") !=
            vm["max_recursive_eval_depth"] or
            stack_dag.get("maximum_simultaneous_eval_invocations") != 4 or
            stack_dag.get(
                "logical_depth_is_not_used_as_a_byte_count") is not True or
            not isinstance(produce_stack, dict) or
            produce_stack.get("public_stack_argument_bytes") != 4 or
            produce_stack.get(
                "maximum_internal_bytes_including_public_stack_arguments") !=
            241 or
            not isinstance(stream_stack, dict) or
            stream_stack.get("public_stack_argument_bytes") != 4 or
            stream_stack.get(
                "maximum_internal_bytes_including_public_stack_arguments") !=
            239 or
            not isinstance(eval_stack, dict) or
            eval_stack.get("maximum_depth_from_function_entry_sp") != 92 or
            not isinstance(walk_stack, dict) or
            walk_stack.get("maximum_depth_from_function_entry_sp") != 214 or
            not callback_rows_valid or
            actual_callback_boundaries != expected_callback_boundaries or
            not isinstance(stack_checks, dict) or
            stack_checks.get("internal_stack_bound_proved") is not True or
            stack_checks.get("external_callback_stack_bounds_present") is not False or
            stack_checks.get(
                "logical_depth_not_reported_as_stack_bytes") is not True):
        raise TranslationError(
            "draw VM backend: pinned SDCC stack certificate is stale or "
            "inconsistent")
    stack_blockers = stack_probe.get("live_blockers")
    if (not isinstance(stack_blockers, list) or not stack_blockers or
            not all(isinstance(item, str) and item for item in stack_blockers)):
        raise TranslationError(
            "draw VM backend: stack certificate omitted live blockers")

    return {
        "format": manifest["format"],
        "status": "selected-compact-target-neutral-live-blocked",
        "plan": {
            **expected_plan,
            "sink_inventory_sha256": plan.sink_inventory_sha256,
        },
        "normalized_record_size": 8,
        "failure_atomic": True,
        "compact_program": {
            "node_count": vm_counts["nodes"],
            "condition_pack_count": vm_counts["condition_packs"],
            "action_count": vm_counts["actions"],
            "logical_table_payload_bytes": vm_table_bytes["total"],
            "max_recursive_eval_depth": vm["max_recursive_eval_depth"],
        },
        "zero_copy_object_provider": {
            "input_shape": object_view["input_shape"],
            "full_pool_materialization_required": False,
            "working_view_count": 1,
            "working_view_bytes": 28,
            "calls_per_item_per_pass": 1,
            "failure_before_first_output": True,
            "resolver_or_emitter_calls_before_preflight_failure": 0,
            "live_target_layout_mapping_certified": False,
        },
        "streaming": {
            "function": streaming["function"],
            "record_array_required": False,
            "preflight_before_first_emission": True,
            "emitter_failure_reports_accepted_prefix": True,
        },
        "target_size_probe": {
            "path": _project_path(DRAW_VM_SIZE_STATUS),
            "sha256": hashlib.sha256(size_probe_bytes).hexdigest(),
            "status": size_probe["status"],
            "code_bytes": code_bytes,
            "data_bytes": data_bytes,
            "single_page_bytes": page_bytes,
            "page_headroom_bytes_before_adapter_and_runtime": headroom_bytes,
        },
        "target_stack_certificate": {
            "path": _project_path(DRAW_VM_STACK_STATUS),
            "sha256": hashlib.sha256(stack_bytes).hexdigest(),
            "status": stack_probe["status"],
            "maximum_internal_stack_bytes_including_public_arguments": 241,
            "produce_internal_stack_bytes": 241,
            "stream_internal_stack_bytes": 239,
            "eval_stack_bytes_from_function_entry": 92,
            "walk_stack_bytes_from_function_entry": 214,
            "maximum_simultaneous_eval_invocations": 4,
            "callback_entry_internal_stack_bytes":
                expected_callback_boundaries,
            "complete_vm_plus_callbacks_stack_bytes": None,
            "live_target_use_certified": False,
        },
        "artifacts": {
            "header": {
                "path": _project_path(
                    output_directory / artifacts.header_name),
                "size": len(header_bytes),
                "sha256": header_sha256,
            },
            "source": {
                "path": _project_path(
                    output_directory / artifacts.source_name),
                "size": len(source_bytes),
                "sha256": source_sha256,
            },
            "manifest": {
                "path": _project_path(
                    output_directory / artifacts.manifest_name),
                "size": len(manifest_bytes),
                "sha256": manifest_sha256,
                "plan_semantic_sha256": plan_manifest["semantic_sha256"],
            },
        },
        "compile_manifest_integration": {
            "support_files_included": False,
            "live_target_performance_and_size_certified": False,
            "reason": "; ".join(dict.fromkeys(
                [*size_blockers, *stack_blockers])),
        },
    }


def _draw_c_backend_contract(
        plan: SpriteDrawPlanIR, artifacts: DrawCArtifacts,
        output_directory: Path) -> dict[str, Any]:
    """Fail closed unless portable C artifacts remain bound to this IR.

    This is intentionally target-neutral.  In particular, successful C
    emission is not evidence that the producer fits the live Z80 link layout
    or has an adapter for the game's object pool.
    """
    try:
        manifest = json.loads(artifacts.manifest)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw C backend: generated manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise TranslationError("draw C backend: manifest root must be an object")
    if manifest.get("format") != DRAW_C_BACKEND_FORMAT:
        raise TranslationError(
            "draw C backend: unexpected manifest format "
            f"{manifest.get('format')!r}")

    plan_manifest = manifest.get("plan")
    if not isinstance(plan_manifest, dict):
        raise TranslationError("draw C backend: missing plan manifest")
    expected_plan = {
        "format": plan.format,
        "symbol": plan.symbol,
        "source_path": plan.source_path,
        "source_sha256": plan.source_sha256,
        "method_ast_sha256": plan.method_ast_sha256,
        "semantic_sha256": plan.semantic_sha256,
        "sink_order_sha256": plan.sink_order_sha256,
        "action_count": len(plan.actions),
    }
    actual_plan = {
        key: plan_manifest.get(key) for key in expected_plan
    }
    if actual_plan != expected_plan:
        raise TranslationError(
            "draw C backend: manifest is not bound to the compiled "
            f"SpriteDrawPlanIR: {actual_plan!r} != {expected_plan!r}")

    expected_names = {
        "header": f"{DRAW_C_PREFIX}.h",
        "source": f"{DRAW_C_PREFIX}.c",
        "manifest": f"{DRAW_C_PREFIX}.json",
    }
    actual_names = {
        "header": artifacts.header_name,
        "source": artifacts.source_name,
        "manifest": artifacts.manifest_name,
    }
    if actual_names != expected_names:
        raise TranslationError(
            "draw C backend: generated artifact names changed: "
            f"{actual_names!r} != {expected_names!r}")

    artifact_manifest = manifest.get("artifacts")
    if not isinstance(artifact_manifest, dict):
        raise TranslationError("draw C backend: missing artifact hashes")
    header_sha256 = hashlib.sha256(
        artifacts.header.encode("utf-8")).hexdigest()
    source_bytes = artifacts.source.encode("utf-8")
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    expected_artifact_manifest = {
        "header": {
            "name": artifacts.header_name,
            "sha256": header_sha256,
        },
        "source": {
            "name": artifacts.source_name,
            "sha256": source_sha256,
            "utf8_bytes": len(source_bytes),
        },
    }
    if artifact_manifest != expected_artifact_manifest:
        raise TranslationError(
            "draw C backend: C/H hashes do not match manifest")

    normalized_abi = manifest.get("normalized_abi")
    verification = manifest.get("verification_contract")
    if not isinstance(normalized_abi, dict) or not isinstance(verification, dict):
        raise TranslationError(
            "draw C backend: normalized ABI/verification contract is missing")
    output_record = normalized_abi.get("output_record")
    failure_atomicity = normalized_abi.get("failure_atomicity")
    streaming = normalized_abi.get("streaming")
    if (not isinstance(output_record, dict) or
            output_record.get("size") != 8 or
            not isinstance(failure_atomicity, dict) or
            failure_atomicity.get("non_ok_output_unchanged") is not True):
        raise TranslationError(
            "draw C backend: 8-byte atomic literal-record ABI changed")
    if (not isinstance(streaming, dict) or
            streaming.get("function") != f"{DRAW_C_PREFIX}_stream" or
            streaming.get("record_array_required") is not False or
            streaming.get("preflight_before_first_emission") is not True or
            streaming.get("emitter_failure_reports_accepted_prefix") is not True):
        raise TranslationError(
            "draw C backend: bounded streaming ABI changed")
    live_certified = verification.get(
        "live_target_performance_and_size_certified")
    if live_certified is not False:
        raise TranslationError(
            "draw C backend: live certification state must be explicit false "
            "until an object-layout adapter and target budget proof exist")
    blocker = verification.get("certification_blocker")
    if not isinstance(blocker, str) or not blocker:
        raise TranslationError(
            "draw C backend: missing live certification blocker")

    manifest_sha256 = hashlib.sha256(
        artifacts.manifest.encode("utf-8")).hexdigest()
    chunker_artifacts: dict[str, dict[str, Any]] = {}
    for kind, path in (
        ("header", DRAW_CHUNKER_HEADER),
        ("source", DRAW_CHUNKER_SOURCE),
    ):
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise TranslationError(
                f"draw C backend: missing bounded chunk adapter {path}") from exc
        chunker_artifacts[kind] = {
            "path": _project_path(path),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    try:
        size_probe = json.loads(DRAW_C_SIZE_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationError(
            "draw C backend: target size probe is missing or invalid") from exc
    if not isinstance(size_probe, dict):
        raise TranslationError(
            "draw C backend: target size probe root must be an object")
    size_input = size_probe.get("input")
    size_result = size_probe.get("result")
    size_source = (
        size_input.get("source") if isinstance(size_input, dict) else None)
    size_header = (
        size_input.get("header") if isinstance(size_input, dict) else None)
    if (size_probe.get("format") != "pyz80-draw-c-target-size-probe-v1" or
            size_probe.get("status") != "BLOCKED_CODE_PAGE_OVERFLOW" or
            size_probe.get(
                "live_target_performance_and_size_certified") is not False or
            not isinstance(size_input, dict) or
            size_input.get("plan_semantic_sha256") != plan.semantic_sha256 or
            not isinstance(size_source, dict) or
            size_source.get("sha256") != source_sha256 or
            size_source.get("bytes") != len(source_bytes) or
            not isinstance(size_header, dict) or
            size_header.get("sha256") != header_sha256 or
            size_header.get("bytes") !=
            len(artifacts.header.encode("utf-8")) or
            not isinstance(size_result, dict) or
            size_result.get("code_bytes", 0) <=
            size_result.get("single_page_bytes", 0) or
            size_result.get("overflow_bytes_before_other_runtime_code") !=
            size_result.get("code_bytes", 0) -
            size_result.get("single_page_bytes", 0)):
        raise TranslationError(
            "draw C backend: target size probe is stale or inconsistent")
    size_probe_report = {
        "path": _project_path(DRAW_C_SIZE_STATUS),
        "sha256": hashlib.sha256(
            DRAW_C_SIZE_STATUS.read_bytes()).hexdigest(),
        "status": size_probe["status"],
        "code_bytes": size_result["code_bytes"],
        "single_page_bytes": size_result["single_page_bytes"],
        "overflow_bytes_before_other_runtime_code":
            size_result["overflow_bytes_before_other_runtime_code"],
    }
    return {
        "format": manifest["format"],
        "status": "generated-target-neutral-not-live",
        "plan": {
            **expected_plan,
            "sink_inventory_sha256": plan.sink_inventory_sha256,
        },
        "normalized_record_size": 8,
        "failure_atomic": True,
        "target_size_probe": size_probe_report,
        "streaming": {
            "function": streaming["function"],
            "record_array_required": False,
            "preflight_before_first_emission": True,
            "emitter_failure_reports_accepted_prefix": True,
            "bounded_chunk_adapter": {
                "status": "portable-not-live",
                "capacity": "caller-provided, nonzero uint16",
                "record_order": "strict-active-Python-prefix",
                "artifacts": chunker_artifacts,
            },
        },
        "artifacts": {
            "header": {
                "path": _project_path(
                    output_directory / artifacts.header_name),
                "size": len(artifacts.header.encode("utf-8")),
                "sha256": header_sha256,
            },
            "source": {
                "path": _project_path(
                    output_directory / artifacts.source_name),
                "size": len(source_bytes),
                "sha256": source_sha256,
            },
            "manifest": {
                "path": _project_path(
                    output_directory / artifacts.manifest_name),
                "size": len(artifacts.manifest.encode("utf-8")),
                "sha256": manifest_sha256,
                "plan_semantic_sha256": plan_manifest["semantic_sha256"],
            },
        },
        "compile_manifest_integration": {
            "support_files_included": False,
            "live_target_performance_and_size_certified": False,
            "reason": (
                f"{blocker}; generated portable source is "
                f"{len(source_bytes)} UTF-8 bytes and is therefore not linked "
                "before a separate object-layout and target size/timing "
                "certificate; the bounded chunk adapter alone is not a live "
                "FT812 hook"),
        },
    }


def emit_render_order_backend_stage(
        project_root: Path = ROOT,
        output_directory: Path = DRAW_C_OUTPUT_DIRECTORY,
        ) -> dict[str, Any]:
    """Validate, then materialize Python-list render order."""
    artifacts = emit_render_order_backend(
        project_root, prefix=RENDER_ORDER_PREFIX, stem=RENDER_ORDER_PREFIX)
    report = _render_order_backend_contract(
        artifacts, output_directory, project_root)
    written = write_render_order_backend(
        project_root, output_directory,
        prefix=RENDER_ORDER_PREFIX, stem=RENDER_ORDER_PREFIX)
    if written != artifacts:
        raise TranslationError(
            "render-order backend: write pass is not deterministic")
    contents = {
        written.header_name: written.header,
        written.source_name: written.source,
        written.manifest_name: written.manifest,
    }
    for name, expected_text in contents.items():
        path = output_directory / name
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TranslationError(
                f"render-order backend: cannot verify {path}") from exc
        if actual != expected_text:
            raise TranslationError(
                "render-order backend: written artifact differs from emitter: "
                f"{path}")
    return report


def emit_draw_vm_backend_stage(
        plan: SpriteDrawPlanIR,
        output_directory: Path = DRAW_C_OUTPUT_DIRECTORY,
        ) -> dict[str, Any]:
    """Validate, then materialize the selected compact draw producer."""
    artifacts = emit_draw_vm_backend(
        plan, prefix=DRAW_VM_PREFIX, stem=DRAW_VM_PREFIX)
    report = _draw_vm_backend_contract(plan, artifacts, output_directory)

    written = write_draw_vm_backend(
        plan, output_directory,
        prefix=DRAW_VM_PREFIX, stem=DRAW_VM_PREFIX)
    if written != artifacts:
        raise TranslationError(
            "draw VM backend: write pass is not deterministic")
    contents = {
        written.header_name: written.header,
        written.source_name: written.source,
        written.manifest_name: written.manifest,
    }
    for name, expected_text in contents.items():
        path = output_directory / name
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TranslationError(
                f"draw VM backend: cannot verify {path}") from exc
        if actual != expected_text:
            raise TranslationError(
                "draw VM backend: written artifact differs from emitter: "
                f"{path}")
    return report


def emit_draw_state_backend_stage(
        plan: SpriteDrawPlanIR, project_root: Path = ROOT,
        output_directory: Path = DRAW_C_OUTPUT_DIRECTORY,
        ) -> dict[str, Any]:
    """Validate, then materialize the persistent VM/provider sidecar."""
    artifacts = emit_draw_state_backend(
        project_root, prefix=DRAW_STATE_PREFIX, stem=DRAW_STATE_PREFIX,
        plan=plan, vm_prefix=DRAW_VM_PREFIX,
        order_prefix=RENDER_ORDER_PREFIX)
    report = _draw_state_backend_contract(
        plan, artifacts, output_directory, project_root)
    written = write_draw_state_backend(
        project_root, output_directory,
        prefix=DRAW_STATE_PREFIX, stem=DRAW_STATE_PREFIX, plan=plan,
        vm_prefix=DRAW_VM_PREFIX, order_prefix=RENDER_ORDER_PREFIX)
    if written != artifacts:
        raise TranslationError(
            "draw-state backend: write pass is not deterministic")
    for name, expected_text in (
            (written.header_name, written.header),
            (written.source_name, written.source),
            (written.manifest_name, written.manifest)):
        path = output_directory / name
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TranslationError(
                f"draw-state backend: cannot verify {path}") from exc
        if actual != expected_text:
            raise TranslationError(
                "draw-state backend: written artifact differs from emitter: "
                f"{path}")
    return report


def emit_draw_c_backend_stage(
        plan: SpriteDrawPlanIR,
        output_directory: Path = DRAW_C_OUTPUT_DIRECTORY,
        ) -> dict[str, Any]:
    """Materialize the readable unrolled semantic-oracle producer."""
    artifacts = emit_draw_c_backend(
        plan, prefix=DRAW_C_PREFIX, stem=DRAW_C_PREFIX)
    report = _draw_c_backend_contract(plan, artifacts, output_directory)

    written = write_draw_c_backend(
        plan, output_directory,
        prefix=DRAW_C_PREFIX, stem=DRAW_C_PREFIX)
    if written != artifacts:
        raise TranslationError(
            "draw C backend: write pass is not deterministic")
    contents = {
        written.header_name: written.header,
        written.source_name: written.source,
        written.manifest_name: written.manifest,
    }
    for name, expected_text in contents.items():
        path = output_directory / name
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TranslationError(
                f"draw C backend: cannot verify {path}") from exc
        if actual != expected_text:
            raise TranslationError(
                f"draw C backend: written artifact differs from emitter: {path}")
    return report


def compiler_support_files() -> tuple[tuple[str, str], ...]:
    """Return only target-certified C support files for the Z80 compiler.

    Render order, persistent draw state, both draw producers and the fast
    bridge are deliberately absent until the compact pipeline has complete
    live mutation hooks plus stack/link/timing/frame certificates.  Their
    exclusion is explicit in the corresponding translation-report sections.
    """
    paths = (
        ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.h",
        ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.c",
        ROOT / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.h",
        ROOT / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.c",
    )
    return tuple(
        (path.name, path.read_text(encoding="utf-8")) for path in paths)


def asset_literals(trees: dict[str, ast.Module]) -> list[dict[str, Any]]:
    suffixes = (".png", ".bin", ".json", ".npz", ".wav", ".ogg")
    found: set[tuple[str, str]] = set()
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if value.lower().endswith(suffixes):
                    found.add((module, value))
    return [{"module": module, "literal": literal} for module, literal in sorted(found)]


def _atlas_draw_calls(node: ast.AST) -> list[ast.Call]:
    return [
        item for item in ast.walk(node)
        if (isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "draw"
            and ast.unparse(item.func.value) == "self.atlas")
    ]


def _isinstance_classes(test: ast.AST) -> tuple[str, ...] | None:
    """Return classes only for a bare ``isinstance(enemy, ...)`` test."""
    if (not isinstance(test, ast.Call) or
            not isinstance(test.func, ast.Name) or
            test.func.id != "isinstance" or len(test.args) != 2 or
            not isinstance(test.args[0], ast.Name) or
            test.args[0].id != "enemy"):
        return None
    classes = test.args[1]
    if isinstance(classes, ast.Name):
        return (classes.id,)
    if (isinstance(classes, ast.Tuple) and
            all(isinstance(item, ast.Name) for item in classes.elts)):
        return tuple(item.id for item in classes.elts)  # type: ignore[attr-defined]
    return None


def _has_adjacent_descriptor_draw(node: ast.AST) -> bool:
    expected = ast.parse("enemy.descriptor + 6", mode="eval").body
    return any(
        ast.dump(item, include_attributes=False) ==
        ast.dump(expected, include_attributes=False)
        for call in _atlas_draw_calls(node)
        for argument in call.args
        for item in ast.walk(argument)
    )


def object_draw_contract(enemy_draw: ast.FunctionDef) -> dict[str, Any]:
    """Translate every extra draw branch of ``M72EnemyWorld.draw``.

    The old target used a handwritten switch and therefore silently lost the
    second descriptor of several bosses. Here all top-level extra branches are
    inventoried. An unfamiliar condition or a class without a target type is
    a translation error, not a one-descriptor fallback.
    """
    enemy_loop = next((
        node for node in enemy_draw.body
        if isinstance(node, ast.For) and ast.unparse(node.iter) == "self.enemies"
    ), None)
    if enemy_loop is None:
        raise TranslationError("M72EnemyWorld.draw: цикл self.enemies не найден")

    expected_special_tests = {
        "isinstance(enemy, ExplosionEffect) and enemy.effect == 'e817'",
        "isinstance(enemy, Formation78F8Child) and enemy.state == 'first'",
        "isinstance(enemy, MultipartA71DBody)",
        "isinstance(enemy, FixedLarge6E9B)",
        "isinstance(enemy, Handler60BAChild)",
    }
    pair_classes: set[str] = set()
    seen_special: set[str] = set()
    extra_branches = 0
    for statement in enemy_loop.body:
        if not isinstance(statement, ast.If) or not _atlas_draw_calls(statement):
            continue
        extra_branches += 1
        test_text = ast.unparse(statement.test)
        classes = _isinstance_classes(statement.test)
        if classes is not None and _has_adjacent_descriptor_draw(statement):
            pair_classes.update(classes)
            continue
        if test_text in expected_special_tests:
            seen_special.add(test_text)
            continue
        raise TranslationError(
            "M72EnemyWorld.draw: неподдержанная extra draw policy: " + test_text)

    if seen_special != expected_special_tests:
        missing = sorted(expected_special_tests - seen_special)
        raise TranslationError(
            "M72EnemyWorld.draw: исчезла special draw policy: " + ", ".join(missing))
    missing_bridge = sorted(pair_classes - OBJECT_TYPE_BY_CLASS.keys())
    if missing_bridge:
        raise TranslationError(
            "нет target type для Python pair renderer: " + ", ".join(missing_bridge))
    stale_bridge = sorted(OBJECT_TYPE_BY_CLASS.keys() - pair_classes)
    if stale_bridge:
        raise TranslationError(
            "target pair bridge больше не подтверждён Python AST: " +
            ", ".join(stale_bridge))

    counts = [1] * OBJECT_TYPE_COUNT
    for class_name in sorted(pair_classes):
        counts[OBJECT_TYPE_BY_CLASS[class_name]] = 2
    return {
        "pair_classes": sorted(pair_classes),
        "descriptor_counts": counts,
        "extra_branches": extra_branches,
        "special_policies": sorted(seen_special),
    }


def beam_meter_states() -> list[list[int]]:
    """Extract the 65 reachable Beam tile strips from deterministic MAME RAM."""
    frames: dict[int, int] = {}
    for workram_path in sorted(BEAM_METER_CAPTURE.glob("frame_*_workram.bin")):
        match = re.fullmatch(r"frame_(\d{6})_workram\.bin", workram_path.name)
        if match is None:
            continue
        workram = workram_path.read_bytes()
        if len(workram) <= 0x3D:
            raise TranslationError(f"короткий Beam workram capture: {workram_path}")
        charge = workram[0x3D]
        if charge <= 0x80 and not (charge & 1):
            frames.setdefault(charge, int(match.group(1)))
    expected = set(range(0, 0x81, 2))
    if set(frames) != expected:
        raise TranslationError(
            "неполный Beam meter capture: " +
            ",".join(f"${value:02X}" for value in sorted(expected - set(frames))))

    states: list[list[int]] = []
    for charge in sorted(frames):
        vram_path = BEAM_METER_CAPTURE / f"frame_{frames[charge]:06d}_vram0.bin"
        vram = vram_path.read_bytes()
        state: list[int] = []
        for column in range(24, 41):
            offset = column * 4
            if offset + 4 > len(vram):
                raise TranslationError(f"короткий Beam VRAM capture: {vram_path}")
            code, attribute = struct.unpack_from("<HH", vram, offset)
            if attribute != 0x008F:
                raise TranslationError(
                    f"Beam charge ${charge:02X}: attr ${attribute:04X}, ожидался $008F")
            state.append(code & 0x3FFF)
        states.append(state)
    return states


def beam_glyph_slots(codes: set[int]) -> dict[int, int]:
    """Resolve Beam cells from the actual two-layer HQ-atlas bridge.

    ``M72GlyphLookup`` stores separate back/front slots and marks a transparent
    layer with ``#FF``.  Beam cells belong to group 2 and currently occupy the
    front layer; using the legacy ``M72_BEAM_*`` back-slot constants selects
    their fully transparent neighbours.  Derive the slot from the bridge
    record itself and verify that its packed ARGB4444 pixels are visible.
    """
    try:
        text = M72_ATLAS_INC.read_text(encoding="utf-8")
        atlas = M72_ATLAS_BIN.read_bytes()
    except OSError as exc:
        raise TranslationError(f"не читается Beam atlas/bridge: {exc}") from exc
    slots: dict[int, int] = {}
    for match in re.finditer(
            (r"^\s*DEFW\s+(\d+)\s*:\s*DEFB\s+"
             r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$"),
            text, re.MULTILINE):
        code, palette, group, back_slot, front_slot = map(int, match.groups())
        if code not in codes or palette != 0x0F or group != 2:
            continue
        visible_layers = [slot for slot in (back_slot, front_slot)
                          if slot != 0xFF]
        if len(visible_layers) != 1:
            raise TranslationError(
                f"Beam cell ${code:04X}: ожидался один видимый atlas layer, "
                f"получено back={back_slot}, front={front_slot}")
        slot = visible_layers[0]
        start = slot * M72_GLYPH_BYTES
        cell = atlas[start:start + M72_GLYPH_BYTES]
        if len(cell) != M72_GLYPH_BYTES:
            raise TranslationError(
                f"Beam cell ${code:04X}: slot {slot} вне HQ-атласа")
        pixels = struct.unpack("<" + "H" * (len(cell) // 2), cell)
        if not any(pixel & 0xF000 for pixel in pixels):
            raise TranslationError(
                f"Beam cell ${code:04X}: slot {slot} полностью прозрачен")
        if code in slots:
            raise TranslationError(
                f"Beam cell ${code:04X}: повтор в HQ-atlas bridge")
        slots[code] = slot
    if not codes <= set(slots):
        raise TranslationError(
            "HQ Beam atlas bridge не совпал с Python/MAME states: " +
            ",".join(f"${code:04X}" for code in sorted(codes - set(slots))))
    if len(set(slots.values())) != len(slots):
        raise TranslationError("HQ Beam atlas bridge содержит повторяющиеся slots")
    return {code: slots[code] for code in codes}


def background_particle_sprite_contract() -> dict[str, Any]:
    """Validate the ROM descriptors selected by BackgroundParticleE5CD.

    The active Python object chooses one of 32 records at ES:$83AC and renders
    it with ``read_descriptor``.  All reachable records currently resolve to
    six adjacent, unflipped 1x1 cells with one shared anchor offset.  Recording
    that proven shape lets the FT812 backend batch the particles without
    rereading six ROM bytes and rebuilding identical bitmap state per star.
    """
    try:
        manifest = json.loads(TARGET_PACK_MANIFEST.read_text(encoding="utf-8"))
        pack = TARGET_PACK.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationError(f"не читается target pack для particle renderer: {exc}") from exc
    world_info = manifest.get("globals", {}).get("world_rom", {})
    offset = world_info.get("offset")
    size = world_info.get("size")
    if (not isinstance(offset, int) or size != 0x10000 or
            offset < 0 or offset + size > len(pack)):
        raise TranslationError("target pack не содержит 64-КБ World ROM")
    world = pack[offset:offset + size]
    if hashlib.sha256(world).hexdigest() != world_info.get("sha256"):
        raise TranslationError("World ROM target pack не совпал с manifest")

    entries: list[tuple[int, int, int, int, int, int]] = []
    for index in range(32):
        descriptor, resource = struct.unpack_from("<HH", world, 0x83AC + index * 4)
        dx = struct.unpack_from("<b", world, descriptor)[0]
        dy = struct.unpack_from("<b", world, descriptor + 1)[0]
        code, attribute = struct.unpack_from("<HH", world, descriptor + 2)
        width = 1 << ((attribute >> 14) & 3)
        height = 1 << ((attribute >> 12) & 3)
        entries.append((descriptor, resource & 0xFF, dx, dy,
                        code & 0x0FFF, attribute))
        if width != 1 or height != 1 or attribute != 0:
            raise TranslationError(
                f"BackgroundParticleE5CD record {index}: нужен unflipped 1x1 descriptor")

    descriptors = sorted({entry[0] for entry in entries})
    if not descriptors or descriptors != list(range(
            descriptors[0], descriptors[0] + len(descriptors) * 6, 6)):
        raise TranslationError("BackgroundParticleE5CD descriptors больше не adjacent")
    decoded = []
    for descriptor in descriptors:
        dx = struct.unpack_from("<b", world, descriptor)[0]
        dy = struct.unpack_from("<b", world, descriptor + 1)[0]
        code, attribute = struct.unpack_from("<HH", world, descriptor + 2)
        decoded.append((dx, dy, code & 0x0FFF, attribute))
    dx_values = {entry[0] for entry in decoded}
    dy_values = {entry[1] for entry in decoded}
    codes = [entry[2] for entry in decoded]
    if (len(dx_values) != 1 or len(dy_values) != 1 or
            codes != list(range(codes[0], codes[0] + len(codes)))):
        raise TranslationError(
            "BackgroundParticleE5CD больше не имеет общего offset/adjacent cells")
    return {
        "descriptor_base": descriptors[0],
        "descriptor_count": len(descriptors),
        "descriptor_stride": 6,
        "cell_code_base": codes[0],
        "dx": next(iter(dx_values)),
        "dy": next(iter(dy_values)),
        "table_sha256": hashlib.sha256(world[0x83AC:0x842C]).hexdigest(),
    }


def player_charge_assets(game_constants: dict[str, Any]) -> list[dict[str, int]]:
    """Validate offline-translated charge images consumed by the FT812 backend."""
    try:
        manifest = json.loads(PLAYER_ASSET_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationError(f"не читается {PLAYER_ASSET_MANIFEST}: {exc}") from exc
    binary_info = manifest.get("charge_binary")
    if not isinstance(binary_info, dict):
        raise TranslationError(
            "r9_pitch.json не содержит charge_binary; запустите m72_player_assets.py")
    binary_path = PLAYER_ASSET_MANIFEST.parent / str(binary_info.get("file", ""))
    try:
        binary = binary_path.read_bytes()
    except OSError as exc:
        raise TranslationError(f"не читается charge binary: {binary_path}") from exc
    if (len(binary) != binary_info.get("size") or
            hashlib.sha256(binary).hexdigest() != binary_info.get("sha256")):
        raise TranslationError("charge binary не совпал с r9_pitch.json")
    source_offset = binary_info.get("source_offset")
    if not isinstance(source_offset, int):
        raise TranslationError("charge_binary.source_offset отсутствует")

    records = sorted(
        (record for record in manifest.get("records", [])
         if record.get("kind") == "charge"),
        key=lambda record: int(record.get("phase", -1)),
    )
    if [record.get("phase") for record in records] != list(range(8)):
        raise TranslationError("Python charge manifest должен содержать phases 0…7")
    crop_left = tuple(game_constants.get("CHARGE_CROP_LEFT", ()))
    crop_top = tuple(game_constants.get("CHARGE_CROP_TOP", ()))
    if len(crop_left) != 8 or len(crop_top) != 8:
        raise TranslationError("Python CHARGE_CROP_LEFT/TOP должны содержать 8 фаз")

    translated: list[dict[str, int]] = []
    for phase, record in enumerate(records):
        values = {
            key: record.get(key)
            for key in ("offset", "length", "width", "height",
                        "crop_left", "crop_top")
        }
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in values.values()):
            raise TranslationError(f"charge phase {phase}: нецелая геометрия")
        offset = int(values["offset"]) - source_offset
        length = int(values["length"])
        width = int(values["width"])
        height = int(values["height"])
        if (offset < 0 or offset + length > len(binary) or
                length != width * height * 2):
            raise TranslationError(f"charge phase {phase}: неверный binary range")
        if ((values["crop_left"], values["crop_top"]) !=
                (crop_left[phase], crop_top[phase])):
            raise TranslationError(
                f"charge phase {phase}: crop не совпал с активным game.py")
        translated.append({
            "phase": phase, "offset": offset, "width": width, "height": height,
            "crop_left": int(values["crop_left"]),
            "crop_top": int(values["crop_top"]),
        })
    return translated


def gameplay_backend_contract(trees: dict[str, ast.Module]) -> dict[str, Any]:
    """Validate gameplay semantics that the Z80/FT812 backend implements.

    These checks deliberately bind the hardware routines below to the launched
    Python graph.  If collision thresholds, the R-9 lifecycle, particle motion,
    or draw order changes in Python, the build stops instead of silently keeping
    an obsolete handwritten approximation.
    """
    app_tree = trees.get("rtype_port.app")
    game_tree = trees.get("rtype_port.game")
    enemies_tree = trees.get("rtype_port.enemies")
    stage_tree = trees.get("rtype_port.stage")
    lifecycle_tree = trees.get("rtype_port.player_lifecycle")
    if (app_tree is None or game_tree is None or enemies_tree is None or
            stage_tree is None or lifecycle_tree is None):
        raise TranslationError("gameplay backend: обязательный Python-модуль недостижим")

    update = find_function(game_tree, "update", "Game")
    render = find_function(game_tree, "render", "Game")
    game_init = find_function(game_tree, "__init__", "Game")
    begin_player_death = find_function(game_tree, "_begin_player_death", "Game")
    restore_checkpoint = find_function(game_tree, "_restore_checkpoint", "Game")
    update_player_death = find_function(game_tree, "_update_player_death", "Game")
    draw_charge_orb = find_function(game_tree, "_draw_charge_orb", "Game")
    draw_beam_meter = find_function(game_tree, "_draw_beam_meter", "Game")
    draw_debug_distance = find_function(
        game_tree, "_draw_debug_distance", "Game")
    beam_phase = find_function(game_tree, "beam_animation_phase")
    enemy_draw = find_function(enemies_tree, "draw", "M72EnemyWorld")
    enemy_world_update = find_function(enemies_tree, "update", "M72EnemyWorld")
    particle_update = find_function(
        enemies_tree, "update", "BackgroundParticleE5CD")
    particle_init = find_function(
        enemies_tree, "__init__", "BackgroundParticleE5CD")
    pool_bind = find_function(enemies_tree, "bind", "M72ObjectPool")
    pool_release = find_function(enemies_tree, "release", "M72ObjectPool")
    enemy_dispatch = find_function(enemies_tree, "_dispatch", "M72EnemyWorld")
    dispatch_progression = find_function(
        stage_tree, "dispatch_progression", "M72Scroll")
    integrated_delta = find_function(
        stage_tree, "_integrated_delta", "M72Scroll")
    dispatch_foreground_delta = find_function(
        stage_tree, "dispatch_foreground_delta", "M72Scroll")
    dispatch_background_delta = find_function(
        stage_tree, "dispatch_background_delta", "M72Scroll")
    modifier_child_init = find_function(
        enemies_tree, "__init__", "TerrainModifierChild6C37")
    modifier_child_update = find_function(
        enemies_tree, "update", "TerrainModifierChild6C37")
    lifecycle_begin = find_function(
        lifecycle_tree, "begin_death", "PlayerLifecycle")
    lifecycle_advance = find_function(
        lifecycle_tree, "advance", "PlayerLifecycle")
    checkpoint_select = find_function(
        lifecycle_tree, "checkpoint_for_progression")

    def require_order(function: ast.FunctionDef, fragments: tuple[str, ...],
                      label: str) -> str:
        source = ast.unparse(function)
        cursor = -1
        for fragment in fragments:
            position = source.find(fragment, cursor + 1)
            if position < 0:
                raise TranslationError(
                    f"gameplay backend: изменён Python-контракт {label}: "
                    f"нет {fragment!r}")
            cursor = position
        return source

    begin_death_text = require_order(begin_player_death, (
        "self.lifecycle.begin_death(self.enemy_world.stage, self.stage.m72_scroll.dispatch_progression)",
        "self.death_native = self._logical_player_native()",
        "self.force.sync_level(0, self.enemy_world.resources.acquire, self.enemy_world.resources.release)",
        "self.bits.sync_and_update(0, self.death_native, 0, self.m72_frame_counter",
        "self.enemy_world.ram_0033 = 0",
        "self.enemy_world.ram_0035 = 0",
        "self.enemy_world.ram_0036 = 0",
        "self.enemy_world.weapon_pickups = 0",
        "self.enemy_world.weapon_type = 0",
        "self.enemy_world.force_level = 0",
        "self.shots.clear()",
        "self.pending_shot_spawn = False",
        "self.pending_matrix_fire = None",
        "self.wave = None",
        "self.wave_charge = 0",
        "self.fire_held = False",
        "self.force_action_held = False",
        "self.death_palette = self.enemy_world.resources.acquire(9)",
        "self.stage.m72_scroll.foreground_velocity = 0",
        "self.stage.m72_scroll.background_velocity = 0",
        "self.stage.m72_scroll.pending_foreground_velocity = None",
        "self.stage.m72_scroll.pending_background_velocity = None",
        "self.play_sfx(0)",
        "self.play_sfx(53)",
    ), "Game._begin_player_death")
    restore_text = require_order(restore_checkpoint, (
        "checkpoint = self.lifecycle.checkpoint",
        "score_bcd = bytes(old_world.score_bcd)",
        "stage_score_bcd = bytes(old_world.stage_score_bcd)",
        "stage_flags = list(old_world.stage_transition_flags)",
        "transition_sound_index = old_world.transition_sound_index",
        "self.stage.reset_checkpoint(checkpoint.stage, checkpoint.ordinal)",
        "self.enemy_world = M72EnemyWorld(stage=checkpoint.stage, full_event_stream=True",
        "self.enemy_world.event_pointer = pointer",
        "self.enemy_world.event_last = event_last",
        "self.enemy_world.score_bcd[:] = score_bcd",
        "self.enemy_world.stage_score_bcd[:] = stage_score_bcd",
        "self.enemy_world.stage_transition_flags[:] = stage_flags",
        "self.enemy_world.transition_sound_index = transition_sound_index",
        "self.force = Force(self.enemy_world.rom)",
        "self.bits = PlayerBits(self.enemy_world.rom)",
        "self.player_x = round((432 - 336) * 5 / 3) * Q8",
        "self.player_y = round((374 - 256) * 15 / 8) * Q8",
        "self.player_pitch = PITCH_NEUTRAL",
        "self.player_native_history = [(432, 256)] * 16",
        "self.stage_exit_autopilot = None",
        "self.player_hit = False",
        "self.death_palette = 255",
        "self.death_native = (0, 0)",
    ), "Game._restore_checkpoint")
    death_update_text = require_order(update_player_death, (
        "if self.lifecycle.state == 'game_over'",
        "self.stage.m72_scroll.foreground_velocity = 0",
        "self.stage.m72_scroll.background_velocity = 0",
        "self.stage.update()",
        "self.enemy_world.update(",
        "allow_scroll=False",
        "events = self.lifecycle.advance()",
        "if events.player_cleared",
        "self.enemy_world.resources.release(self.death_palette)",
        "if events.checkpoint_rebuild",
        "self.enemy_world.cleanup_active = True",
        "if events.respawned",
        "self._restore_checkpoint()",
    ), "Game._update_player_death")
    lifecycle_begin_text = require_order(lifecycle_begin, (
        "if not self.collision_enabled",
        "self.state = 'death'",
        "self.death_age = 0",
        "self.invulnerability = 0",
        "self.checkpoint = checkpoint_for_progression(stage, progression)",
    ), "PlayerLifecycle.begin_death")
    lifecycle_advance_text = require_order(lifecycle_advance, (
        "if self.active",
        "self.invulnerability -= 1",
        "if self.state == 'game_over'",
        "self.death_age += 1",
        "if self.death_age == PLAYER_CLEAR_AGE",
        "if self.death_age == LIFE_DECREMENT_AGE",
        "self.lives -= 1",
        "checkpoint_rebuild=True",
        "if self.death_age == RESPAWN_AGE",
        "self.state = 'active'",
        "self.invulnerability = RESPAWN_INVULNERABILITY",
        "respawned=True",
    ), "PlayerLifecycle.advance")
    checkpoint_text = require_order(checkpoint_select, (
        "stage_points = tuple((point for point in CHECKPOINTS if point.stage == stage))",
        "progression &= 65535",
        "eligible = tuple((point for point in stage_points if point.progression <= progression))",
        "return eligible[-1] if eligible else stage_points[0]",
    ), "checkpoint_for_progression")
    distance_text = require_order(draw_debug_distance, (
        "self.stage.m72_scroll.progression & 65535",
        "self.debug_distance_font.render(f'DIST {value:04X}', False, (255, 255, 255))",
        "self.debug_distance_font.render(f'DIST {value:04X}', False, (0, 0, 0))",
        "target.get_width() - image.get_width() - 6",
        "target.get_height() - image.get_height() - 4",
        "target.blit(shadow, (x + 1, y + 1))",
        "target.blit(image, (x, y))",
    ), "Game._draw_debug_distance")

    terrain_assignment = next((
        node for node in ast.walk(update)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "terrain_hit"
    ), None)
    expected_terrain = ast.parse(
        "foreground_code < 0x0DFC or background_code < 0x07D0",
        mode="eval",
    ).body
    if (terrain_assignment is None or
            ast.dump(terrain_assignment.value, include_attributes=False) !=
            ast.dump(expected_terrain, include_attributes=False)):
        raise TranslationError(
            "изменена Python-формула столкновения R-9 с foreground/background")

    render_calls: list[str] = []
    for node in ast.walk(render):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = ast.unparse(node.func.value)
        render_calls.append(f"{owner}.{node.func.attr}")
    required_order = (
        "self.stage.draw_back",
        "self.enemy_world.draw",
        "self.force.draw",
        "self.bits.draw",
        "self._draw_charge_orb",
        "self.stage.draw_front",
        "self._draw_player_label",
        "self._draw_score",
        "self._draw_beam_meter",
        "self._draw_debug_distance",
    )
    try:
        order_indices = [render_calls.index(name) for name in required_order]
    except ValueError as exc:
        raise TranslationError(
            "gameplay backend: изменён обязательный Python draw pipeline") from exc
    if order_indices != sorted(order_indices):
        raise TranslationError(
            "gameplay backend: нарушен Python Z-order back/objects/fixed/front")

    draw_policy = object_draw_contract(enemy_draw)

    game_constants = module_constants(game_tree)
    constant_specs = {
        "INTRO_FRAMES": 226,
        "CHARGE_FIRST_VISIBLE": 0x0F,
        "BEAM_METER_X": 220,
        "BEAM_METER_Y": 454,
        "BEAM_METER_W": 213,
        "WAVE_MAX_CHARGE": 0x80,
    }
    for name, expected in constant_specs.items():
        if game_constants.get(name) != expected:
            raise TranslationError(
                f"gameplay backend: {name}={game_constants.get(name)!r}, "
                f"ожидалось {expected}")
    motion_constants = {
        name: game_constants.get(name)
        for name in ("MOVE_X", "MOVE_Y", "SHOT_VX")
    }
    if (any(isinstance(value, bool) or not isinstance(value, int)
            for value in motion_constants.values()) or
            not (0 < int(motion_constants["MOVE_X"]) <
                 int(motion_constants["SHOT_VX"])) or
            not (0 < int(motion_constants["MOVE_Y"]) <
                 int(motion_constants["SHOT_VX"]))):
        raise TranslationError(
            "gameplay backend: неверные Python MOVE_X/MOVE_Y/SHOT_VX")
    movement_text = ast.unparse(update)
    movement_requirements = (
        "self.player_x -= MOVE_X",
        "self.player_x += MOVE_X",
        "self.player_y -= MOVE_Y",
        "self.player_y += MOVE_Y",
    )
    if any(fragment not in movement_text for fragment in movement_requirements):
        raise TranslationError("изменена Python-дискретная физика движения R-9")
    if (tuple(game_constants.get("CHARGE_CROP_LEFT", ())) !=
            (0, 0, 0, 1, 1, 1, 0, 0) or
            tuple(game_constants.get("CHARGE_CROP_TOP", ())) !=
            (0, 1, 3, 5, 7, 11, 12, 14)):
        raise TranslationError("изменена геометрия Python charge orb")

    charge_text = ast.unparse(draw_charge_orb)
    charge_requirements = (
        "self.intro_frame < INTRO_FRAMES",
        "self.fire_held and self.wave_charge >= CHARGE_FIRST_VISIBLE",
        "phase = beam_animation_phase(self.m72_frame_counter)",
        "self.player_x // Q8 + 53 + CHARGE_CROP_LEFT[phase]",
        "self.player_y // Q8 - 8 + CHARGE_CROP_TOP[phase]",
    )
    if any(fragment not in charge_text for fragment in charge_requirements):
        raise TranslationError("изменён Python renderer накопления Beam")
    meter_text = ast.unparse(draw_beam_meter)
    meter_requirements = (
        "self.intro_frame < INTRO_FRAMES",
        "min(WAVE_MAX_CHARGE, max(0, self.wave_charge)) // 2",
        "self.beam_meter_images[index]",
        "(BEAM_METER_X, BEAM_METER_Y)",
    )
    if any(fragment not in meter_text for fragment in meter_requirements):
        raise TranslationError("изменён Python renderer индикатора Beam")
    expected_phase_expr = ast.parse(
        "(m72_frame_counter & 0x001C) >> 2", mode="eval").body
    phase_returns = [
        node for node in beam_phase.body if isinstance(node, ast.Return)]
    if (len(phase_returns) != 1 or phase_returns[0].value is None or
            ast.dump(phase_returns[0].value, include_attributes=False) !=
            ast.dump(expected_phase_expr, include_attributes=False)):
        raise TranslationError("изменена Python phase-функция накопления Beam")

    frame_seed_assignment = next((
        node for node in ast.walk(game_init)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and ast.unparse(node.targets[0]) == "self.m72_frame_counter"
    ), None)
    if (frame_seed_assignment is None or
            not isinstance(frame_seed_assignment.value, ast.Constant) or
            not isinstance(frame_seed_assignment.value.value, int)):
        raise TranslationError("Game.__init__: m72_frame_counter seed не найден")
    frame_counter_seed = int(frame_seed_assignment.value.value)
    if not 0 <= frame_counter_seed <= 0xFFFF:
        raise TranslationError("Game.__init__: m72_frame_counter вне word")

    # Это не таймер backend-а и не измерение скорости хоста. В активном
    # Python Game.update сам задаёт номер логического кадра. Транслятор обязан
    # перенести именно эту операцию, чтобы Python и Z80 можно было сопоставлять
    # по одному и тому же значению независимо от реальной частоты вывода.
    frame_counter_assignments = [
        node for node in update.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and ast.unparse(node.targets[0]) == "self.m72_frame_counter"
    ]
    if len(frame_counter_assignments) != 1:
        raise TranslationError(
            "Game.update: требуется ровно одно присваивание m72_frame_counter")
    frame_counter_assignment = frame_counter_assignments[0]
    expected_frame_counter = ast.parse(
        "(self.m72_frame_counter + 1) & 0xFFFF", mode="eval").body
    if ast.dump(frame_counter_assignment.value, include_attributes=False) != ast.dump(
            expected_frame_counter, include_attributes=False):
        raise TranslationError(
            "Game.update: изменена Python-операция m72_frame_counter")

    app_constants = module_constants(app_tree)
    frame_rate = app_constants.get("FRAME_RATE")
    if (isinstance(frame_rate, bool) or
            not isinstance(frame_rate, (int, float)) or frame_rate <= 0):
        raise TranslationError("rtype_port.app.FRAME_RATE не является положительным числом")

    arcade_source = ARCADE_GAME_ASM.read_text(encoding="utf-8")
    frame_prologue = re.compile(
        r"^ArcadeGame_Update:\r?\n"
        r"[ \t]+LD[ \t]+HL,[ \t]*\(FrameCounter\)\r?\n"
        r"[ \t]+INC[ \t]+HL\r?\n"
        r"[ \t]+LD[ \t]+\(FrameCounter\),[ \t]*HL\r?$",
        re.MULTILINE,
    )
    if frame_prologue.search(arcade_source) is None:
        raise TranslationError(
            "ArcadeGame_Update: невозможно безопасно установить "
            "сгенерированный Python frame-counter prologue")

    meter_states = beam_meter_states()
    supported_beam_codes = {
        0x06AD, 0x06AE, 0x06B0, 0x06B2, 0x06B4, 0x06B6, 0x06B8,
        0x06BA, 0x06BB, 0x06BC, 0x06BD, 0x06BE, 0x06BF,
    }
    observed_codes = {code for state in meter_states for code in state}
    if not observed_codes <= supported_beam_codes:
        raise TranslationError(
            "Beam capture содержит tile без HQ bridge: " +
            ",".join(f"${code:04X}" for code in sorted(
                observed_codes - supported_beam_codes)))
    glyph_slots = beam_glyph_slots(observed_codes)
    charge_assets = player_charge_assets(game_constants)

    modifier_text = (
        ast.unparse(modifier_child_init) + "\n" +
        ast.unparse(modifier_child_update))
    modifier_requirements = (
        "self.local_timer = ordinal * 4",
        "hp=hp",
        "self.local_timer = _u16(self.local_timer - 1)",
        "if self.local_timer == 0",
    )
    if any(fragment not in modifier_text for fragment in modifier_requirements):
        raise TranslationError(
            "изменены независимые поля local_timer/hp TerrainModifierChild6C37")
    # Target record packing: timer is a word; HP must begin after both bytes.
    modifier_layout = {
        "local_timer_offset": 0x2D,
        "local_timer_size": 2,
        "hp_offset": 0x2F,
        "hp_size": 1,
    }

    particle_dump = ast.dump(particle_update, include_attributes=False)
    particle_requirements = (
        "self.initialized", "self.x_velocity", "self.x_fraction",
        "self.render_ready", "self.velocity_table", "self.alive",
    )
    if any(name not in ast.unparse(particle_update) for name in particle_requirements):
        raise TranslationError(
            "изменён автомат BackgroundParticleE5CD; fast-path нельзя применять")
    particle_constants = {
        node.value for node in ast.walk(particle_update)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    if not {0x832C, 0x02C0, 0x0140}.issubset(particle_constants):
        raise TranslationError(
            "изменены границы BackgroundParticleE5CD")
    particle_text = ast.unparse(particle_update)
    if ("self.initialized = True\n        return" not in particle_text or
            particle_text.index("self.render_ready = True") <
            particle_text.index("self.initialized = True")):
        raise TranslationError(
            "BackgroundParticleE5CD должен оставаться невидимым в init-pass")
    particle_sprite = background_particle_sprite_contract()
    particle_init_text = ast.unparse(particle_init)
    pool_bind_text = ast.unparse(pool_bind)
    pool_release_text = ast.unparse(pool_release)
    if "self.inherit_slot_fractions = True" not in particle_init_text:
        raise TranslationError(
            "BackgroundParticleE5CD больше не наследует Q8 residue slot-а")
    for fragment in (
            "x_fraction, y_fraction = self.residue[slot]",
            "enemy.inherit_slot_fractions",
            "enemy.x_fraction = x_fraction",
            "enemy.y_fraction = y_fraction"):
        if fragment not in pool_bind_text:
            raise TranslationError(
                "изменён Python-контракт M72ObjectPool.bind Q8 residue")
    for fragment in (
            "old_x, old_y = self.residue[slot]",
            "x_fraction = getattr(owner, 'x_fraction', old_x) & 255",
            "y_fraction = getattr(owner, 'y_fraction', old_y) & 255",
            "self.residue[slot] = (x_fraction, y_fraction)"):
        if fragment not in pool_release_text:
            raise TranslationError(
                "изменён Python-контракт M72ObjectPool.release Q8 residue")
    dispatch_progression_text = require_order(dispatch_progression, (
        "accumulator = self.progression_accumulator",
        "if self.vblank not in M72_INTEGRATOR_MISSING",
        "accumulator = accumulator + self.foreground_velocity & 16777215",
        "return accumulator >> 8 & 65535",
    ), "M72Scroll.dispatch_progression")
    integrated_delta_text = require_order(integrated_delta, (
        "previous = accumulator >> 8 & 511",
        "current = accumulator + velocity >> 8 & 511",
        "step = current - previous & 511",
        "if step & 256",
        "step -= 512",
        "return -step & 65535",
    ), "M72Scroll._integrated_delta")
    dispatch_fg_delta_text = ast.unparse(dispatch_foreground_delta)
    dispatch_bg_delta_text = ast.unparse(dispatch_background_delta)
    if ("return self._integrated_delta(self.foreground_accumulator, "
            "self.foreground_velocity)" not in dispatch_fg_delta_text or
            "return self._integrated_delta(self.background_accumulator, "
            "self.background_velocity)" not in dispatch_bg_delta_text):
        raise TranslationError(
            "изменён Python-контракт M72Scroll dispatch delta")
    enemy_world_update_text = ast.unparse(enemy_world_update)
    if ("if _u16(frame_counter + 1) & 511 == 0:" not in
            enemy_world_update_text or
            "self.rng.reset()" not in enemy_world_update_text):
        raise TranslationError(
            "изменён Python-контракт M72EnemyWorld.update RNG reset")
    delegated_handlers = class_constants(
        enemies_tree, "M72EnemyWorld").get("DELEGATED_HANDLERS")
    enemy_dispatch_text = ast.unparse(enemy_dispatch)
    if (not isinstance(delegated_handlers, frozenset) or
            0xF0F3 not in delegated_handlers or
            "event.handler in self.DELEGATED_HANDLERS" not in enemy_dispatch_text or
            "self.delegated_events.append(event)" not in enemy_dispatch_text):
        raise TranslationError(
            "изменён Python-контракт delegated event $F0F3")

    lifecycle_constants = module_constants(lifecycle_tree)
    initial_lives = lifecycle_constants.get("INITIAL_LIVES")
    max_lives = lifecycle_constants.get("MAX_LIVES")
    if not isinstance(initial_lives, int) or not isinstance(max_lives, int):
        raise TranslationError("gameplay backend: Python lives не являются целыми")
    if not (1 <= initial_lives <= max_lives <= 8):
        raise TranslationError(
            "FT812 HUD рассчитан на 1…8 жизней активной Python-версии")

    digest = hashlib.sha256(
        (ast.dump(update, include_attributes=False) + "\n" +
         ast.dump(render, include_attributes=False) + "\n" +
         ast.dump(draw_charge_orb, include_attributes=False) + "\n" +
         ast.dump(draw_beam_meter, include_attributes=False) + "\n" +
         ast.dump(draw_debug_distance, include_attributes=False) + "\n" +
         ast.dump(beam_phase, include_attributes=False) + "\n" +
         ast.dump(frame_counter_assignment, include_attributes=False) + "\n" +
         ast.dump(begin_player_death, include_attributes=False) + "\n" +
         ast.dump(restore_checkpoint, include_attributes=False) + "\n" +
         ast.dump(update_player_death, include_attributes=False) + "\n" +
         ast.dump(lifecycle_begin, include_attributes=False) + "\n" +
         ast.dump(lifecycle_advance, include_attributes=False) + "\n" +
         ast.dump(checkpoint_select, include_attributes=False) + "\n" +
         ast.dump(enemy_draw, include_attributes=False) + "\n" +
         ast.dump(modifier_child_init, include_attributes=False) + "\n" +
         ast.dump(modifier_child_update, include_attributes=False) + "\n" +
         particle_dump).encode("utf-8")
    ).hexdigest()
    return {
        "validated_source_symbols": (
            "rtype_port.game.Game.update",
            "rtype_port.game.Game.render",
            "rtype_port.game.Game._draw_charge_orb",
             "rtype_port.game.Game._draw_beam_meter",
             "rtype_port.game.Game._draw_debug_distance",
            "rtype_port.game.Game._begin_player_death",
            "rtype_port.game.Game._restore_checkpoint",
            "rtype_port.game.Game._update_player_death",
            "rtype_port.game.beam_animation_phase",
            "rtype_port.enemies.M72EnemyWorld.draw",
            "rtype_port.enemies.TerrainModifierChild6C37.__init__",
            "rtype_port.enemies.TerrainModifierChild6C37.update",
            "rtype_port.enemies.BackgroundParticleE5CD.update",
            "rtype_port.player_lifecycle.PlayerLifecycle.advance",
            "rtype_port.player_lifecycle.PlayerLifecycle.begin_death",
            "rtype_port.player_lifecycle.checkpoint_for_progression",
        ),
        "kind": "z80_ft812_gameplay",
        "terrain_foreground_clear_code": 0x0DFC,
        "terrain_background_clear_code": 0x07D0,
        "initial_lives": initial_lives,
        "max_lives": max_lives,
        "z_order": list(required_order),
        "frame_counter_seed": frame_counter_seed,
        "frame_counter_step": 1,
        "frame_counter_mask": 0xFFFF,
        "source_frame_rate": float(frame_rate),
        "object_draw_policy": draw_policy,
        "beam_meter": {
            "x": game_constants["BEAM_METER_X"],
            "y": game_constants["BEAM_METER_Y"],
            "width": game_constants["BEAM_METER_W"],
            "states": meter_states,
            "glyph_slots": glyph_slots,
        },
        "distance_contract": hashlib.sha256(distance_text.encode()).hexdigest(),
        "charge_first_visible": game_constants["CHARGE_FIRST_VISIBLE"],
        "intro_frames": game_constants["INTRO_FRAMES"],
        "charge_assets": charge_assets,
        "motion": motion_constants,
        "terrain_modifier_child_layout": modifier_layout,
        "background_particle_fast_path": True,
        "background_particle_prepare_on_init": False,
        "background_particle_sprite": particle_sprite,
        "dispatch_progression_contract": hashlib.sha256(
            dispatch_progression_text.encode()).hexdigest(),
        "delegated_f0f3_contract": hashlib.sha256(
            enemy_dispatch_text.encode()).hexdigest(),
        "rng_reseed_contract": hashlib.sha256(
            enemy_world_update_text.encode()).hexdigest(),
        "dispatch_delta_contract": hashlib.sha256(
            (integrated_delta_text + dispatch_fg_delta_text +
             dispatch_bg_delta_text).encode()).hexdigest(),
        "lifecycle_contract": {
            "begin_death": hashlib.sha256(begin_death_text.encode()).hexdigest(),
            "restore_checkpoint": hashlib.sha256(restore_text.encode()).hexdigest(),
            "update_death": hashlib.sha256(death_update_text.encode()).hexdigest(),
            "state_begin": hashlib.sha256(lifecycle_begin_text.encode()).hexdigest(),
            "state_advance": hashlib.sha256(lifecycle_advance_text.encode()).hexdigest(),
            "checkpoint_select": hashlib.sha256(checkpoint_text.encode()).hexdigest(),
        },
        "ast_sha256": digest,
    }


def emit_gameplay_backend(contract: dict[str, Any]) -> None:
    """Emit gameplay code selected only after validating the Python AST."""
    fg_clear = int(contract["terrain_foreground_clear_code"])
    bg_clear = int(contract["terrain_background_clear_code"])
    max_lives = int(contract["max_lives"])
    frame_seed = int(contract["frame_counter_seed"])
    frame_step = int(contract["frame_counter_step"])
    frame_mask = int(contract["frame_counter_mask"])
    source_frame_rate = float(contract["source_frame_rate"])
    checkpoint = contract.get("initial_checkpoint")
    if checkpoint is None:
        _, checkpoint = compile_initial_checkpoint_snapshot()
    checkpoint_event_skip = int(checkpoint["event_skip"])
    checkpoint_progress = int(checkpoint["progression_accumulator"])
    checkpoint_fg_scroll = int(checkpoint["foreground_accumulator"])
    checkpoint_fg_velocity = int(checkpoint["foreground_velocity"])
    checkpoint_bg_scroll = int(checkpoint["background_accumulator"])
    checkpoint_bg_velocity = int(checkpoint["background_velocity"])
    if frame_step != 1 or frame_mask != 0xFFFF:
        raise TranslationError("Z80 backend поддерживает только Python counter +1 & 0xFFFF")
    intro_frames = int(contract["intro_frames"])
    charge_first_visible = int(contract["charge_first_visible"])
    object_counts = list(contract["object_draw_policy"]["descriptor_counts"])
    beam_states = list(contract["beam_meter"]["states"])
    beam_glyph_map = {
        int(code): int(slot)
        for code, slot in dict(contract["beam_meter"]["glyph_slots"]).items()
    }
    charge_assets = list(contract["charge_assets"])
    motion = dict(contract["motion"])
    particle_sprite = dict(contract["background_particle_sprite"])
    particle_descriptor_base = int(particle_sprite["descriptor_base"])
    particle_descriptor_count = int(particle_sprite["descriptor_count"])
    particle_descriptor_stride = int(particle_sprite["descriptor_stride"])
    particle_cell_code_base = int(particle_sprite["cell_code_base"])
    particle_dx = int(particle_sprite["dx"])
    particle_dy = int(particle_sprite["dy"])
    particle_x_bias = particle_dx - 320
    particle_y_origin = 384 - 16 - particle_dy
    bank4_bridge_pattern = re.compile(
        r"^(?P<wrapper>RTypeObjectBank4_[A-Za-z0-9_]+):\r?\n"
        r"(?:(?P<push>[ \t]+PUSH\s+AF\r?\n))?"
        r"[ \t]+LD\s+A,\s+RTYPE_OBJECT_BANK4_PAGE\r?\n"
        r"[ \t]+SetPage2_A\r?\n"
        r"(?:(?P<pop>[ \t]+POP\s+AF\r?\n))?"
        r"[ \t]+CALL\s+(?P<target>RTypeBank4_[A-Za-z0-9_]+)\r?\n"
        r"[ \t]+LD\s+A,\s+CorePage\s+\+\s+1\r?\n"
        r"[ \t]+SetPage2_A\r?\n"
        r"[ \t]+RET\s*$",
        re.MULTILINE,
    )
    object_runtime_source = OBJECT_RUNTIME_ASM.read_text(encoding="utf-8")
    object_new_prologue = re.compile(
        r"^RTypeObjects_New:\r?\n"
        r"[ \t]+CALL\s+RTypeObjects_Take\r?\n"
        r"[ \t]+RET\s+C\r?\n"
        r"[ \t]+LD\s+\(RTypeObjects_CurrentIndex\),\s*A\r?\n"
        r"[ \t]+PUSH\s+AF\r?\n"
        r"[ \t]+CALL\s+RTypeObjects_ClearScratch\r?$",
        re.MULTILINE,
    )
    if object_new_prologue.search(object_runtime_source) is None:
        raise TranslationError(
            "невозможно установить generated M72ObjectPool Q8 residue")
    rng_update_prologue = re.compile(
        r"^RTypeObjects_Update:\r?\n"
        r"(?:[ \t]*;[^\r\n]*\r?\n)*"
        r"[ \t]+LD\s+A,\s*\(FrameCounter\)\r?\n"
        r"[ \t]+OR\s+A\r?\n"
        r"[ \t]+JR\s+NZ,\s*\.bands\r?\n"
        r"[ \t]+LD\s+A,\s*\(FrameCounter\s*\+\s*1\)\r?\n"
        r"[ \t]+AND\s+1\r?\n"
        r"[ \t]+CALL\s+Z,\s*RTypeRng_Reset\r?\n"
        r"\.bands:",
        re.MULTILINE,
    )
    if rng_update_prologue.search(object_runtime_source) is None:
        raise TranslationError(
            "невозможно установить generated M72EnemyWorld.update RNG reset")
    world_runtime_source = WORLD_RUNTIME_ASM.read_text(encoding="utf-8")
    dispatch_compare = re.compile(
        r"[ \t]+LD\s+DE,\s*\(RTypeWorldProgressQ8\s*\+\s*1\)\r?\n"
        r"[ \t]+LD\s+A,\s*D\r?\n"
        r"[ \t]+CP\s+B\r?\n"
        r"[ \t]+RET\s+C\r?\n"
        r"[ \t]+JR\s+NZ,\s*\.eventReady\r?\n"
        r"[ \t]+LD\s+A,\s*E\r?\n"
        r"[ \t]+CP\s+C\r?\n"
        r"[ \t]+RET\s+C\r?\n"
        r"\.eventReady:",
    )
    if dispatch_compare.search(world_runtime_source) is None:
        raise TranslationError(
            "невозможно установить generated M72Scroll.dispatch_progression")
    object_update_call = re.compile(
        r"[ \t]+CALL\s+RTypeWorld_Stage3Update\r?\n"
        r"[ \t]+CALL\s+RTypeObjects_Update\r?\n"
        r"(?:[ \t]*;[^\r\n]*\r?\n)*"
        r"[ \t]+CALL\s+RTypeCollision_Update\r?\n"
        r"\r?\n\.eventLoop:",
    )
    if object_update_call.search(world_runtime_source) is None:
        raise TranslationError(
            "невозможно установить generated M72Scroll dispatch delta")
    delegated_f0f3_prologue = re.compile(
        r"^RTypeWorld_DispatchGlobal:\r?\n"
        r"[ \t]+LD\s+HL,\s*\(RTypeWorldLastHandler\)\r?\n"
        r"[ \t]+LD\s+DE,\s*#F0F3\b",
        re.MULTILINE,
    )
    if delegated_f0f3_prologue.search(world_runtime_source) is None:
        raise TranslationError(
            "невозможно установить generated delegated event $F0F3")
    bank4_bridges: list[tuple[str, str, bool]] = []
    for match in bank4_bridge_pattern.finditer(object_runtime_source):
        preserves_af = bool(match.group("push"))
        if preserves_af != bool(match.group("pop")):
            raise TranslationError(
                f"несимметричное сохранение AF в {match.group('wrapper')}")
        bank4_bridges.append((
            match.group("wrapper"), match.group("target"), preserves_af))
    if len(bank4_bridges) != 26:
        raise TranslationError(
            "изменён набор bank4-обёрток object runtime: "
            f"найдено {len(bank4_bridges)}, ожидалось 26")
    if not any(
            wrapper == "RTypeObjectBank4_InitPaletteControl"
            for wrapper, _, _ in bank4_bridges):
        raise TranslationError("нет bank4-обёртки palette events $5526/$5596")
    contract["resident_bank4_bridges"] = {
        "count": len(bank4_bridges),
        "wrappers": [wrapper for wrapper, _, _ in bank4_bridges],
    }
    text = f"""; Сгенерировано rtype_python_translator.py из Game.update/render,
; PlayerLifecycle и BackgroundParticleE5CD.update активного Python-графа.
; Ручное редактирование запрещено: следующая сборка перезапишет файл.

RTYPE_PY_TERRAIN_FG_CLEAR EQU #{fg_clear:04X}
RTYPE_PY_TERRAIN_BG_CLEAR EQU #{bg_clear:04X}
RTYPE_PY_HUD_MAX_LIVES    EQU {max_lives}
RTYPE_PY_FRAME_COUNTER_SEED EQU #{frame_seed:04X}
RTYPE_PY_FRAME_COUNTER_STEP EQU {frame_step}
RTYPE_PY_FRAME_COUNTER_MASK EQU #{frame_mask:04X}
RTYPE_PY_SOURCE_FRAME_RATE_X1000 EQU {round(source_frame_rate * 1000)}
RTYPE_PY_INTRO_FRAMES      EQU {intro_frames}
RTYPE_PY_CHARGE_VISIBLE    EQU #{charge_first_visible:02X}
RTYPE_PY_MOVE_X_Q8         EQU {int(motion["MOVE_X"])}
RTYPE_PY_MOVE_Y_Q8         EQU {int(motion["MOVE_Y"])}
RTYPE_PY_SHOT_VX_Q8        EQU {int(motion["SHOT_VX"])}

; Дополнительное translated-состояние lifecycle. Блок #44C0…#44CF не
; пересекает ArcadeStageFrame (#4290), title overlay и fixed-player state.
RTypePyDeathPalette       EQU #44C0
RTypePyDeathNativeX       EQU #44C1
RTypePyDeathNativeY       EQU #44C3
RTypePyFastParticleIndex  EQU #44C5
RTypePyParticleCellCode   EQU #44C6
RTypePyParticleX          EQU #44C8
RTypePyParticleY          EQU #44CA
RTypePyParticlePalette    EQU #44CC
RTypePyParticleVertexX    EQU #44CD
RTypePyParticleWasReady   EQU #44CF

RTYPE_PY_PARTICLE_DESCRIPTOR_BASE EQU #{particle_descriptor_base:04X}
RTYPE_PY_PARTICLE_DESCRIPTOR_COUNT EQU {particle_descriptor_count}
RTYPE_PY_PARTICLE_DESCRIPTOR_STRIDE EQU {particle_descriptor_stride}
RTYPE_PY_PARTICLE_CELL_BASE EQU #{particle_cell_code_base:04X}
RTYPE_PY_PARTICLE_X_BIAS EQU {particle_x_bias}
RTYPE_PY_PARTICLE_Y_ORIGIN EQU {particle_y_origin}

; Буквальный перенос Game._begin_player_death. Checkpoint выбирается из
; активного stage-пакета до очистки объектов и ресурсов.
RTypePyLifecycle_BeginDeathBackend:
                CALL RTypePyLifecycle_SaveCheckpoint
                LD   HL, (RTypePlayerNativeX)
                LD   (RTypePyDeathNativeX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTypePyDeathNativeY), HL
                ; Постоянно отображённый helper безопасно переключает slot2,
                ; тогда как сам сгенерированный backend находится в Core slot2.
                CALL RTypePyLifecycle_ClearFixedPlayer
                ; Enemy fixed bytes, input edges, shots, pending matrix fire,
                ; Wave object and charge are all cleared in the same branch.
                XOR  A
                LD   HL, ArcadeReleasePrev
                LD   DE, ArcadeReleasePrev + 1
                LD   BC, 5
                LD   (HL), A
                LDIR
                LD   HL, ArcadeShotTable
                LD   DE, ArcadeShotTable + 1
                LD   BC, ArcadeShotPending - ArcadeShotTable
                LD   (HL), A
                LDIR
                LD   A, #09
                CALL RTypeResources_Acquire
                LD   (RTypePyDeathPalette), A
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                ; play_sfx($00), затем play_sfx($35): target-latch передаёт
                ; аппаратному звуковому мосту ту же последнюю команду.
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, #35
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                RET

RTypePyLifecycle_ClearBackend:
                LD   A, (RTypePyDeathPalette)
                CALL RTypeResources_Release
                LD   A, #FF
                LD   (RTypePyDeathPalette), A
                RET

; Буквальный _restore_checkpoint: сбросить ring выбранного stage, создать
; новый мир объектов/ресурсов, вернуть постоянное transition-состояние и
; поставить event-reader на первую запись с progression checkpoint.
RTypePyLifecycle_RespawnBackend:
                CALL RTypePyLifecycle_RebuildCheckpoint
                XOR  A
                LD   (ArcadePlayerX), A
                LD   (ArcadePlayerY), A
                LD   HL, 160
                LD   (ArcadePlayerX + 1), HL
                LD   HL, 221
                LD   (ArcadePlayerY + 1), HL
                LD   A, ARCADE_PITCH_NEUTRAL
                LD   (ArcadePlayerPitch), A
                CALL ArcadePlayer_SyncNative
                XOR  A
                LD   (RTypePyDeathNativeX), A
                LD   (RTypePyDeathNativeX + 1), A
                LD   (RTypePyDeathNativeY), A
                LD   (RTypePyDeathNativeY + 1), A
                LD   A, #FF
                LD   (RTypePyDeathPalette), A
                RET

; Неактивные Python-кадры обновляют остановленный мир, затем lifecycle;
; ввод и оружие игрока не исполняются. GAME OVER терминален.
RTypePyLifecycle_DeathFrame:
                LD   A, (ArcadeLifeState)
                CP   ARCADE_LIFE_GAME_OVER
                RET  Z
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                CALL RTypeWorld_Update
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                CALL ArcadeLifecycle_Update
                ; PlayerLifecycle.advance выдаёт checkpoint_rebuild только на
                ; кадре уменьшения жизней и только если осталась ещё жизнь.
                LD   A, (ArcadeLifeState)
                CP   ARCADE_LIFE_DEATH
                RET  NZ
                LD   HL, (ArcadeDeathAge)
                LD   DE, ARCADE_LIFE_DECREMENT_AGE
                OR   A
                SBC  HL, DE
                RET  NZ
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, 1
                LD   (RTYPE_CLEANUP_ACTIVE), A
                RET

RTypePyLifecycle_PrepareExplosion:
                LD   A, (ArcadePlayerVisible)
                OR   A
                RET  Z
                LD   A, (RTypePyDeathPalette)
                CP   #FF
                RET  Z
                LD   HL, (ArcadeDeathDescriptor)
                LD   A, H
                OR   L
                RET  Z
                JP   RTypeSprite_PrepareDescriptor

; Game.render chooses explosion while dying and the five-frame pitch body only
; while active.  This prevents a silent R-9 disappearance at the death edge.
RTypePyRenderPlayerLifecycle:
                LD   A, (ArcadeLifeState)
                CP   ARCADE_LIFE_DEATH
                JP   NZ, Render_M72DynamicPlayer
                LD   A, (ArcadePlayerVisible)
                OR   A
                RET  Z
                LD   A, (RTypePyDeathPalette)
                CP   #FF
                RET  Z
                LD   HL, (ArcadeDeathDescriptor)
                LD   BC, (RTypePyDeathNativeX)
                LD   DE, (RTypePyDeathNativeY)
                JP   RTypeSprite_DrawDescriptor

; HUD_FIXED contains two captured icons.  Clear only their black HUD area on
; screen, then reuse the first icon directly from RAM_G and draw ArcadeLives
; copies.  No runtime scaling/filtering and no modification of Python assets.
RTypePyRenderLives:
                FT_ColorRGB 0, 0, 0
                FT_Begin FT_RECTS
                LD   BC, 16 * 8
                LD   DE, 720 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   BC, 212 * 8
                LD   DE, 750 * 8
                CALL FT.Coprocessor.Vertex2f
                FT_End
                LD   A, (ArcadeLives)
                OR   A
                RET  Z
                CP   RTYPE_PY_HUD_MAX_LIVES + 1
                JR   C, .countReady
                LD   A, RTYPE_PY_HUD_MAX_LIVES
.countReady:    LD   (.remaining), A
                LD   HL, 12
                LD   (.logicalX), HL
                FT_BitmapTransformA 160
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 160
                FT_BitmapTransformF 0
                FT_BitmapSource ARCADE_BG_RAMG + 12 * 2
                FT_BitmapLayout FT_RGB565, ARCADE_BG_STRIDE, 18
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 24, 29
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
.nextLife:     LD   HL, (.logicalX)
                CALL M72_LogicalToVertex
                LD   DE, 720 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   HL, (.logicalX)
                LD   DE, 15
                ADD  HL, DE
                LD   (.logicalX), HL
                LD   HL, .remaining
                DEC  (HL)
                JR   NZ, .nextLife
                FT_End
                RET
.remaining:    DEFB 0
.logicalX:     DEFW 0

; Активной BackgroundParticleE5CD нужны только перенесённый шаг Q8 и проверка
; границы. Прямой путь в page #09 убирает два 64-байтных LDIR на каждую звезду.
; Carry=0 передаёт одноразовый Python-initializer общему пути.
RTypePyBackgroundParticleFastUpdate:
                LD   (RTypePyFastParticleIndex), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypePyFastParticleIndex)
                CALL RTypeObjects_RecordAddress
                PUSH HL
                POP  IX
                ; Python scheduler проверяет cleanup до вызова update любого
                ; Enemy. Быстрый путь обязан удалить частицу в том же кадре.
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   Z, .cleanupPassed
                LD   A, (IX + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTypePyFastParticleIndex)
                CALL RTypeObjects_Release
                SCF
                RET
.cleanupPassed:
                LD   A, (IX + RTYPE_OBJ_STATE)
                OR   A
                RET  Z
                LD   A, (IX + RTYPE_OBJ_SUBSTATE)
                LD   (RTypePyParticleWasReady), A
                LD   L, (IX + RTYPE_OBJ_X_FRACTION)
                LD   H, (IX + RTYPE_OBJ_X)
                LD   E, (IX + RTYPE_OBJ_X_VELOCITY)
                LD   D, (IX + RTYPE_OBJ_X_VELOCITY + 1)
                ADD  HL, DE
                LD   (IX + RTYPE_OBJ_X_FRACTION), L
                LD   (IX + RTYPE_OBJ_X), H
                LD   C, 0
                BIT  7, D
                JR   Z, .velocitySignReady
                DEC  C
.velocitySignReady:
                LD   A, (IX + RTYPE_OBJ_X + 1)
                ADC  A, C
                LD   (IX + RTYPE_OBJ_X + 1), A
                LD   (IX + RTYPE_OBJ_SUBSTATE), 1
                LD   L, (IX + RTYPE_OBJ_SCRIPT)
                LD   H, (IX + RTYPE_OBJ_SCRIPT + 1)
                LD   DE, #832C
                OR   A
                SBC  HL, DE
                JR   NZ, .leftMoving
                LD   L, (IX + RTYPE_OBJ_X)
                LD   H, (IX + RTYPE_OBJ_X + 1)
                LD   DE, #02C0
                OR   A
                SBC  HL, DE
                JR   C, .prepare
                JR   .remove
.leftMoving:   LD   L, (IX + RTYPE_OBJ_X)
                LD   H, (IX + RTYPE_OBJ_X + 1)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                JR   NC, .prepare
.remove:       LD   A, (IX + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTypePyFastParticleIndex)
                CALL RTypeObjects_Release
                SCF
                RET
.prepare:      LD   A, (RTypePyParticleWasReady)
                OR   A
                JR   NZ, .prepared
                LD   L, (IX + RTYPE_OBJ_DESCRIPTOR)
                LD   H, (IX + RTYPE_OBJ_DESCRIPTOR + 1)
                CALL RTypeSprite_PrepareDescriptor
.prepared:
                SCF
                RET

; Python-initializer ставит initialized=True и возвращает render_ready=False.
; Подготовка descriptor здесь опережала семантику на кадр и давала пик кэша
; на 80 объектов. Следующий перенесённый шаг готовит его ровно один раз.
RTypePyBackgroundParticleAfterInit:
                RET

; Звёзды/background particles выводятся раньше остальных объектов. Python-выбор
; 32 вариантов ES:$83AC проверен как шесть соседних неотражённых 1x1 descriptor
; с общим смещением. Поэтому FT812-state общий для всей пачки; меняются только
; palette, источник кэшированной cell и vertex каждой частицы.
RTypePyDrawBackgroundParticles:
                FT_ColorRGB 255, 255, 255
                FT_BitmapTransformA 96
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 85
                FT_BitmapTransformF 0
                FT_BitmapLayout FT_PALETTED4444, 16, 16
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 43, 49
                FT_Begin FT_BITMAPS
                LD   A, 2
                LD   (RTypeObjects_ScanIndex), A
                LD   HL, RTYPE_OBJECT_BASE + 2 * RTYPE_OBJECT_REC_SIZE
                LD   (.recordPtr), HL
.nextParticle: LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (.recordPtr)
                LD   A, (HL)
                CP   RTYPE_OBJ_BG_PARTICLE
                JP   NZ, .advance
                PUSH HL
                POP  IX
                LD   A, (IX + RTYPE_OBJ_SUBSTATE)
                OR   A
                JP   Z, .advance
                LD   L, (IX + RTYPE_OBJ_DESCRIPTOR)
                LD   H, (IX + RTYPE_OBJ_DESCRIPTOR + 1)
                LD   DE, RTYPE_PY_PARTICLE_DESCRIPTOR_BASE
                OR   A
                SBC  HL, DE
                JP   C, .advance
                LD   A, H
                OR   A
                JP   NZ, .advance
                LD   A, L
                LD   B, 0
.descriptorIndex:
                OR   A
                JR   Z, .descriptorReady
                CP   RTYPE_PY_PARTICLE_DESCRIPTOR_STRIDE
                JP   C, .advance
                SUB  RTYPE_PY_PARTICLE_DESCRIPTOR_STRIDE
                INC  B
                JR   .descriptorIndex
.descriptorReady:
                LD   A, B
                CP   RTYPE_PY_PARTICLE_DESCRIPTOR_COUNT
                JP   NC, .advance
                LD   L, A
                LD   H, 0
                LD   DE, RTYPE_PY_PARTICLE_CELL_BASE
                ADD  HL, DE
                LD   (RTypePyParticleCellCode), HL
                LD   L, (IX + RTYPE_OBJ_X)
                LD   H, (IX + RTYPE_OBJ_X + 1)
                LD   (RTypePyParticleX), HL
                LD   L, (IX + RTYPE_OBJ_Y)
                LD   H, (IX + RTYPE_OBJ_Y + 1)
                LD   (RTypePyParticleY), HL
                LD   A, (IX + RTYPE_OBJ_PALETTE)
                LD   (RTypePyParticlePalette), A

                ; PALETTE_SOURCE = translated live resource slot * 32.
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTYPE_WORLD_SPRITE_PALETTE_RAMG & #FFFF
                ADD  HL, DE
                LD   E, L
                LD   D, H
                LD   C, (RTYPE_WORLD_SPRITE_PALETTE_RAMG >> 16) & #FF
                LD   B, #2A
                CALL FT.Coprocessor.Command_BCDE

                ; BITMAP_SOURCE = persistent cache slot * 256.
                LD   HL, (RTypePyParticleCellCode)
                CALL RTypeSpriteCache_LoadCell
                JP   C, .advance
                LD   A, H
                ADD  A, (RTYPE_PY_SPRITE_CACHE_RAMG >> 16) & #FF
                LD   D, L
                LD   E, 0
                LD   C, A
                LD   B, #01
                CALL FT.Coprocessor.Command_BCDE

                ; Same descriptor geometry as read_descriptor()/atlas.draw.
                LD   HL, (RTypePyParticleX)
                LD   DE, RTYPE_PY_PARTICLE_X_BIAS
                ADD  HL, DE
                CALL RTypeSprite_NativeXToVertex
                LD   (RTypePyParticleVertexX), BC
                LD   HL, RTYPE_PY_PARTICLE_Y_ORIGIN
                LD   DE, (RTypePyParticleY)
                OR   A
                SBC  HL, DE
                CALL RTypeSprite_NativeYToVertex
                PUSH BC
                LD   BC, (RTypePyParticleVertexX)
                POP  DE
                CALL FT.Coprocessor.Vertex2f
.advance:      LD   A, (RTypeObjects_ScanIndex)
                INC  A
                LD   (RTypeObjects_ScanIndex), A
                LD   HL, (.recordPtr)
                LD   DE, RTYPE_OBJECT_REC_SIZE
                ADD  HL, DE
                LD   (.recordPtr), HL
                CP   RTYPE_OBJECT_COUNT
                JP   C, .nextParticle
                FT_End
                RET
.recordPtr:    DEFW 0
"""
    count_lines = [
        "; Descriptor count for each compact target object type, extracted",
        "; from every unconditional adjacent draw in M72EnemyWorld.draw.",
        "RTypePyObjectDrawCount:",
    ]
    for offset in range(0, len(object_counts), 16):
        count_lines.append(
            "                DEFB " + ", ".join(
                str(value) for value in object_counts[offset:offset + 16]))

    charge_command_lines = [
        "",
        "; Eight offline-HQ bitmaps selected by beam_animation_phase.",
        "RTypePyChargeCommandTable:",
    ]
    for asset in charge_assets:
        address = 0x02C000 + int(asset["offset"])
        width = int(asset["width"])
        height = int(asset["height"])
        stride = width * 2
        physical_width = (width * 8 + 4) // 5
        physical_height = (height * 8 + 4) // 5
        words = (
            0x01000000 | address,
            0x28000000 | (((stride >> 10) & 3) << 2) | ((height >> 9) & 3),
            0x07000000 | (6 << 19) | ((stride & 0x3FF) << 9) | (height & 0x1FF),
            0x29000000 | (((physical_width >> 9) & 3) << 2)
            | ((physical_height >> 9) & 3),
            0x08000000 | ((physical_width & 0x1FF) << 9)
            | (physical_height & 0x1FF),
        )
        charge_command_lines.append(
            f"                ; phase {asset['phase']}: {width}x{height}")
        charge_command_lines.extend(
            f"                DEFD ${word:08X}" for word in words)
    charge_command_lines.extend([
        "RTypePyChargeCropLeft:",
        "                DEFB " + ", ".join(
            str(int(asset["crop_left"])) for asset in charge_assets),
        "RTypePyChargeCropTop:",
        "                DEFB " + ", ".join(
            str(int(asset["crop_top"])) for asset in charge_assets),
    ])

    beam_blob = bytearray()
    for index, state in enumerate(beam_states):
        for column_offset, code in enumerate(state):
            column = 16 + column_offset
            vertex_x = column * 170 + (column * 2) // 3
            vertex_y = 720 * 8
            vertex = (0x40000000 | ((vertex_x & 0x7FFF) << 15) |
                      (vertex_y & 0x7FFF))
            source = (0x01000000 | M72_ATLAS_RAMG |
                      (beam_glyph_map[int(code)] * M72_GLYPH_BYTES))
            beam_blob.extend(struct.pack("<II", source, vertex))
    expected_beam_bytes = len(beam_states) * 17 * 8
    if len(beam_blob) != expected_beam_bytes or len(beam_blob) > PAGE_SIZE:
        raise TranslationError("FT812 Beam command blob не помещается в одну TS page")
    OUT_BEAM_COMMANDS.write_bytes(beam_blob)
    beam_table_lines = [
        "",
        "; Beam command strips live in a generated non-stage TS page.",
        f"RTYPE_PY_BEAM_COMMAND_PAGE EQU #{BEAM_COMMAND_PAGE:02X}",
        f"RTYPE_PY_BEAM_COMMAND_BYTES EQU {len(beam_blob)}",
    ]

    runtime = f"""

; Game.__init__ literal seed. It drives every translated phase selector,
; including the eight-frame charge animation.
RTypePyGameplay_InitFrameCounter:
                CALL RTypePyInstallBank4Bridges
                ; M72ObjectPool хранит Q8 residue отдельно от owner-а. После
                ; очистки физической записи восстановить оба сохранённых byte.
                LD   HL, RTypePyObjects_ClearScratchWithResidue
                LD   (RTypeObjects_New + 9), HL
                ; Четырёхбайтный LD DE,(progression) заменяется на вызов
                ; свойства M72Scroll.dispatch_progression, сгенерированного
                ; из активного stage.py. Последний byte становится NOP.
                LD   A, #CD
                LD   (RTypeWorld_Update.eventReady - 12), A
                LD   HL, RTypePyGameplay_GetDispatchProgression
                LD   (RTypeWorld_Update.eventReady - 11), HL
                XOR  A
                LD   (RTypeWorld_Update.eventReady - 9), A
                ; В Python $F0F3 остаётся delegated event без изменения
                ; progression. Невозможное значение отключает старую ветку.
                LD   HL, #FFFF
                LD   (RTypeWorld_DispatchGlobal + 4), HL
                ; M72EnemyWorld.update reseed: `(frame_counter + 1) & $1FF`.
                LD   HL, RTypePyGameplay_RngReseedAndUpdate
                LD   (RTypeObjects_Update + 1), HL
                LD   A, #C3
                LD   (RTypeObjects_Update), A
                LD   HL, RTypePyGameplay_ObjectsUpdateWithDispatchDeltas
                LD   (RTypeWorld_Update.eventLoop - 5), HL
                ; Первые семь байтов ArcadeGame_Update раньше вручную
                ; повторяли Python-присваивание. Теперь исполняется только
                ; код, сгенерированный из AST Game.update.
                LD   HL, RTypePyGameplay_AdvanceFrameCounter
                LD   (ArcadeGame_Update + 1), HL
                LD   A, #C3
                LD   (ArcadeGame_Update), A
                LD   A, 1
                LD   (RTypePyInitialSnapshotPending), A
                LD   HL, RTYPE_PY_FRAME_COUNTER_SEED
                LD   (FrameCounter), HL
                RET

RTypePyGameplay_AdvanceFrameCounter:
                LD   A, (RTypePyInitialSnapshotPending)
                OR   A
                CALL NZ, RTypePyGameplay_LoadInitialSnapshot
                LD   HL, (FrameCounter)
                INC  HL
                LD   (FrameCounter), HL
                JP   ArcadeGame_Update + 7

; Serialized by executing Game.__init__/M72EnemyWorld.__init__ from the
; launched Python graph. Source is mapped in slot2; page #09 stays in slot3.
RTypePyInitialSnapshotPending:
                DEFB 0

RTypePyObjects_ClearScratchWithResidue:
                CALL RTypeObjects_ClearScratch
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                RET

RTypePyGameplay_GetDispatchProgression:
                PUSH BC
                PUSH HL
                LD   HL, (RTypeWorldProgressQ8)
                LD   DE, (RTypeWorldFgVelocity)
                LD   C, 0
                BIT  7, D
                JR   Z, .signReady
                DEC  C
.signReady:     ADD  HL, DE
                LD   A, (RTypeWorldProgressQ8 + 2)
                ADC  A, C
                LD   E, H
                LD   D, A
                POP  HL
                POP  BC
                RET

RTypePyGameplay_RngReseedAndUpdate:
                LD   HL, (FrameCounter)
                INC  HL
                LD   A, L
                OR   A
                JR   NZ, .bands
                LD   A, H
                AND  1
                CALL Z, RTypeRng_Reset
.bands:         JP   RTypeObjects_UpdateOrdered

; Upload the eight cropped Python charge bitmaps after title RAM_G is detached.
RTypePyChargeAssetsUpload:
                LD   HL, RTypePyChargePageTable
                LD   (.tblPtr), HL
                LD   A, (RTYPE_PY_CHARGE_RAMG >> 16) & #FF
                LD   (.ramgHi), A
                LD   HL, RTYPE_PY_CHARGE_RAMG & #FFFF
                LD   (.ramgLo), HL
                LD   A, RTYPE_PY_CHARGE_PAGE_COUNT
                LD   (.count), A
.next:         LD   HL, (.tblPtr)
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .next
                RET
.tblPtr:       DEFW 0
.ramgLo:       DEFW 0
.ramgHi:       DEFB 0
.chunkLen:     DEFW 0
.count:        DEFB 0

; Python _draw_charge_orb: after intro, while FIRE is held and charge >= $0F.
RTypePyRenderChargeOrb:
                LD   HL, (ArcadeIntroFrame)
                LD   DE, RTYPE_PY_INTRO_FRAMES
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, (ArcadeFireHeld)
                OR   A
                RET  Z
                LD   A, (ArcadeWaveCharge)
                CP   RTYPE_PY_CHARGE_VISIBLE
                RET  C
                LD   A, (FrameCounter)
                AND  #1C
                RRCA
                RRCA
                AND  7
                LD   (.phase), A
                CALL RTypePyLogicalBitmapState
                LD   A, (.phase)
                CALL RTypePyCharge_CopyAsset
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   A, (.phase)
                LD   E, A
                LD   D, 0
                LD   HL, RTypePyChargeCropLeft
                ADD  HL, DE
                LD   E, (HL)
                LD   D, 0
                LD   HL, (ArcadePlayerX + 1)
                ADD  HL, DE
                LD   DE, 53
                ADD  HL, DE
                CALL M72_LogicalToVertex
                LD   (M72SprX), BC
                LD   A, (.phase)
                LD   E, A
                LD   D, 0
                LD   HL, RTypePyChargeCropTop
                ADD  HL, DE
                LD   E, (HL)
                LD   D, 0
                LD   HL, (ArcadePlayerY + 1)
                ADD  HL, DE
                LD   DE, -8
                ADD  HL, DE
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f
                FT_End
                RET
.phase:        DEFB 0

; A=phase 0..7, append its five FT812 bitmap-state commands.
RTypePyCharge_CopyAsset:
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, RTypePyChargeCommandTable
                ADD  HL, DE
                LD   BC, 20
                JP   FT.Coprocessor.Copy

; Сохраняет буквальный порядок Game.render: Beam, затем DIST.
RTypePyRenderBeamMeter:
                CALL RTypePyRenderBeamMeterBody
                JP   RTypePyRenderDistance

; Python _draw_beam_meter: собирать захваченный crop 213x9 из 17 HQ tiles.
; Транслятор заранее разрешил все источники и vertex в неизменяемую полосу
; FT812-команд. Runtime выбирает одно из 65 точных состояний.
RTypePyRenderBeamMeterBody:
                LD   HL, (ArcadeIntroFrame)
                LD   DE, RTYPE_PY_INTRO_FRAMES
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, (ArcadeWaveCharge)
                CP   #81
                JR   C, .chargeReady
                LD   A, #80
.chargeReady:  SRL  A
                LD   L, A
                LD   H, 0
                PUSH HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                POP  DE
                ADD  HL, DE
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                    ; state * 17 * 8 bytes
                LD   DE, #C000
                ADD  HL, DE
                LD   (.commandPtr), HL
                FT_ScissorXY 352, 726
                FT_ScissorSize 341, 15
                FT_BitmapTransformA 160
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 160
                FT_BitmapTransformF 0
                FT_BitmapLayout FT_ARGB4, M72_GLYPH_W * 2, M72_GLYPH_H
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, M72_GLYPH_PHYS_W, M72_GLYPH_PHYS_H
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   A, RTYPE_PY_BEAM_COMMAND_PAGE
                SetPage3_A
                LD   HL, (.commandPtr)
                LD   BC, 17 * 8
                CALL FT.Coprocessor.Copy
                FT_End
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 768
                RET
.commandPtr:   DEFW 0

; `$F0F3` body is unreachable after the generated delegated-event patch.
; Reuse those bytes for the two M72Scroll dispatch-delta properties without
; growing Core past the configured FT812 command window.
RTypePyGameplay_OverlayResume EQU $
                ORG  RTypeWorld_DispatchGlobal + 11
RTypePyGameplay_ObjectsUpdateWithDispatchDeltas:
                LD   A, (RTypeWorldFgScrollQ8)
                LD   L, A
                LD   H, 0
                LD   DE, (RTypeWorldFgVelocity)
                CALL .integratedDelta
                LD   (RTypeWorldFgDelta), HL
                LD   A, (RTypeWorldBgScrollQ8)
                LD   L, A
                LD   H, 0
                LD   DE, (RTypeWorldBgVelocity)
                CALL .integratedDelta
                LD   (RTypeWorldBgDelta), HL
                JP   RTypeObjects_Update
.integratedDelta:
                ADD  HL, DE
                LD   A, H
                NEG
                LD   L, A
                ADD  A, A
                SBC  A, A
                LD   H, A
                RET
                ASSERT $ <= RTypeWorld_DispatchGlobal.checkStop
                ORG  RTypePyGameplay_OverlayResume
"""
    # The large immutable visual tables live in always-mapped page 0. Keeping
    # them out of Core leaves command-buffer headroom below CMD_ADDRESS_PTR.
    text += "\n".join(count_lines)
    lifecycle_runtime = r"""

; Медленный перенос death/checkpoint лежит в постоянно отображённой page 0
; TS-Conf и генерируется из проверенного выше Python-контракта lifecycle.
RTypePyLifecycle_ClearFixedPlayer:
                XOR  A
                LD   (ArcadeForceRequestedLevel), A
                LD   (ArcadeBitCount), A
                LD   (ArcadeForceDirection), A
                LD   A, RTYPE_FIXED_PLAYER_BANK_PAGE
                SetPage2_A
                CALL RTypeForce_SyncLevel
                CALL RTypeBits_Update
                CALL RTypeFixedPlayerBank_Init
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyLifecycle_SaveCheckpoint:
                LD   A, (RTypeTargetStage)
                LD   (RTypePyCheckpointStage), A
                LD   A, RTYPE_TARGET_PACK_BASE_PAGE
                SetPage3_A
                LD   A, (RTypePyCheckpointStage)
                CALL RTypeTarget_StageRecord
                INC  HL
                LD   A, (HL)
                LD   (RTypePyCheckpointRemaining), A
                LD   A, (RTypeTargetCheckPage)
                SetPage3_A
                LD   HL, (RTypeTargetCheckPtr)
                XOR  A
                LD   (RTypePyCheckpointOrdinal), A
                LD   (RTypePyCheckpointCandidate), A
.checkpoint:    PUSH HL
                INC  HL
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                LD   HL, (RTypeWorldProgressQ8 + 1)
                OR   A
                SBC  HL, BC
                POP  HL
                JR   C, .checkpointDone
                LD   A, (RTypePyCheckpointCandidate)
                LD   (RTypePyCheckpointOrdinal), A
                LD   DE, RTYPE_TARGET_CHECKPOINT_REC
                ADD  HL, DE
                LD   A, (RTypePyCheckpointCandidate)
                INC  A
                LD   (RTypePyCheckpointCandidate), A
                LD   A, (RTypePyCheckpointRemaining)
                DEC  A
                LD   (RTypePyCheckpointRemaining), A
                JR   NZ, .checkpoint
.checkpointDone:
                RET

RTypePyLifecycle_RebuildCheckpoint:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTYPE_TRANSITION_FLAGS)
                LD   (RTypePySavedTransitionFlags), HL
                LD   A, (RTYPE_TRANSITION_SOUND_INDEX)
                LD   (RTypePySavedTransitionSound), A
                LD   A, (RTypePyCheckpointStage)
                CALL RTypeTarget_SelectStage
                CALL RTypePyLifecycle_ApplyCheckpoint
                CALL RTypeObjects_Reset
                CALL RTypeSpriteCache_Reset
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTypePySavedTransitionFlags)
                LD   (RTYPE_TRANSITION_FLAGS), HL
                LD   A, (RTypePySavedTransitionSound)
                LD   (RTYPE_TRANSITION_SOUND_INDEX), A
                CALL RTypePyLifecycle_SelectCheckpointEvent
                CALL ArcadeFixedPlayer_Init
                XOR  A
                LD   (RTypeFinalPlayerExitLatch), A
                RET

RTypePyLifecycle_ApplyCheckpoint:
                LD   A, (RTypeTargetCheckPage)
                SetPage3_A
                LD   HL, (RTypeTargetCheckPtr)
                LD   A, (RTypePyCheckpointOrdinal)
.recordOffset:  OR   A
                JR   Z, .recordReady
                LD   DE, RTYPE_TARGET_CHECKPOINT_REC
                ADD  HL, DE
                DEC  A
                JR   .recordOffset
.recordReady:   INC  HL
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                XOR  A
                LD   (RTypeWorldProgressQ8), A
                LD   (RTypeWorldProgressQ8 + 1), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgSource), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgSource), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgVelocity), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgVelocity), DE
                LD   HL, (RTypeWorldFgSource)
                LD   DE, (RTypeWorldFgSourceBase)
                CALL RTypeWorld_SourceIndex
                LD   (RTypeWorldFgStripIndex), HL
                LD   HL, (RTypeWorldBgSource)
                LD   DE, (RTypeWorldBgSourceBase)
                CALL RTypeWorld_SourceIndex
                LD   (RTypeWorldBgStripIndex), HL
                XOR  A
                LD   (RTypeWorldFgTracker), A
                LD   (RTypeWorldBgTracker), A
                LD   A, #70
                LD   (RTypeWorldFgTarget), A
                LD   (RTypeWorldBgTarget), A
                CALL RTypeWorld_ClearMaps
                LD   B, 7
.preload:       PUSH BC
                CALL RTypeWorld_PumpForeground
                CALL RTypeWorld_PumpBackground
                POP  BC
                DJNZ .preload
                RET

RTypePyLifecycle_SelectCheckpointEvent:
                LD   A, (RTypeTargetEventPage)
                SetPage3_A
                LD   HL, (RTypeTargetEventPtr)
                LD   BC, 0
.event:         PUSH HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, (RTypeWorldProgressQ8 + 1)
                OR   A
                SBC  HL, DE
                POP  HL
                JR   Z, .eventFound
                LD   DE, RTYPE_TARGET_EVENT_REC
                ADD  HL, DE
                INC  BC
                LD   DE, (RTypeTargetEventCount)
                PUSH HL
                LD   H, B
                LD   L, C
                OR   A
                SBC  HL, DE
                POP  HL
                JR   C, .event
                RET
.eventFound:    LD   (RTypeTargetEventPtr), HL
                LD   (RTypeTargetEventIndex), BC
                RET

; Буквальный Game._draw_debug_distance: четыре hex-цифры берутся из того же
; progression, что Python выводит как `DIST {value:04X}`. Строку и тень рисует
; аппаратный ROM-font FT812 в правом нижнем углу без участия Z80 в пикселях.
; Процедура лежит в постоянно отображённой page 0, сохраняя место в Core.
RTypePyRenderDistance:
                LD   HL, (RTypeWorldProgressQ8 + 1)
                LD   DE, RTypePyDistanceBuffer + 5
                LD   A, H
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                CALL .storeHex
                LD   A, H
                AND  #0F
                CALL .storeHex
                LD   A, L
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                CALL .storeHex
                LD   A, L
                AND  #0F
                CALL .storeHex
                FT_LoadIdentity
                FT_Scale #0001999A, #0001999A
                FT_SetMatrix
                FT_ColorRGB 0, 0, 0
                FT_Text 915, 711, 26, 0
                LD   HL, RTypePyDistanceBuffer
                LD   BC, 12
                CALL FT.Coprocessor.Copy
                FT_ColorRGB 255, 255, 255
                FT_Text 914, 710, 26, 0
                LD   HL, RTypePyDistanceBuffer
                LD   BC, 12
                JP   FT.Coprocessor.Copy
.storeHex:     CP   10
                JR   C, .decimal
                ADD  A, 'A' - 10
                JR   .store
.decimal:      ADD  A, '0'
.store:        LD   (DE), A
                INC  DE
                RET

RTypePyDistanceBuffer:
                DEFM "DIST "
                DEFS 4, '0'
                DEFB 0, 0, 0

RTypePyCheckpointStage:          DEFB 1
RTypePyCheckpointOrdinal:        DEFB 0
RTypePyCheckpointCandidate:      DEFB 0
RTypePyCheckpointRemaining:      DEFB 0
RTypePySavedTransitionFlags:     DEFW 0
RTypePySavedTransitionSound:     DEFB 0
"""
    bridge_table_lines = [
        "",
        "; Bank4-обёртки Core пересекли границу $8000. После смены page2",
        "; возврат в такую обёртку зависел от случайного состояния кэша Z80.",
        "; Транслятор ставит JP на постоянно отображённые мосты page 0.",
        "RTypePyInstallBank4Bridges:",
        "                LD   HL, RTypePyBank4BridgePatchTable",
        f"                LD   B, {len(bank4_bridges)}",
        ".next:         LD   E, (HL)",
        "                INC  HL",
        "                LD   D, (HL)",
        "                INC  HL",
        "                LD   C, (HL)",
        "                INC  HL",
        "                LD   A, (HL)",
        "                INC  HL",
        "                PUSH HL",
        "                EX   DE, HL",
        "                LD   (HL), #C3",
        "                INC  HL",
        "                LD   (HL), C",
        "                INC  HL",
        "                LD   (HL), A",
        "                POP  HL",
        "                DJNZ .next",
        "                RET",
        "",
        "RTypePyBank4BridgePatchTable:",
    ]
    for wrapper, _, _ in bank4_bridges:
        bridge = f"RTypePyBridge_{wrapper}"
        bridge_table_lines.append(f"                DEFW {wrapper}, {bridge}")
    bridge_table_lines.extend([
        "",
        "; Game.__init__/M72EnemyWorld.__init__ snapshot emitted by Python.",
        "RTypePyGameplay_LoadInitialSnapshot:",
        "                LD   A, RTYPEPYINITIALCHECKPOINT_PAGE",
        "                SetPage2_A",
        "                LD   A, RTYPE_OBJECT_PAGE",
        "                SetPage3_A",
        "                LD   HL, #8000 + RTYPEPYINITIALCHECKPOINT_OFFSET + 4",
        "                LD   A, (HL)",
        "                INC  HL",
        ".record:       OR   A",
        "                JR   Z, .recordsDone",
        "                DEC  A",
        "                PUSH AF",
        "                LD   E, (HL)",
        "                INC  HL",
        "                PUSH HL",
        "                LD   L, E",
        "                LD   H, 0",
        "                ADD  HL, HL",
        "                ADD  HL, HL",
        "                ADD  HL, HL",
        "                ADD  HL, HL",
        "                ADD  HL, HL",
        "                ADD  HL, HL",
        "                LD   DE, RTYPE_OBJECT_BASE",
        "                ADD  HL, DE",
        "                EX   DE, HL",
        "                POP  HL",
        "                LD   BC, RTYPE_OBJECT_REC_SIZE",
        "                LDIR",
        "                POP  AF",
        "                JR   .record",
        ".recordsDone:  LD   DE, RTYPE_OBJECT_FREE_QUEUE",
        "                LD   BC, 96",
        "                LDIR",
        "                LD   DE, RTYPE_OBJECT_FREE_HEAD",
        "                LD   BC, 5",
        "                LDIR",
        "                LD   DE, RTYPE_RESOURCE_TYPES",
        "                LD   BC, 35",
        "                LDIR",
        "                LD   DE, RTYPE_SCHED_NEXT",
        "                LD   BC, 194",
        "                LDIR",
        "                LD   DE, RTypeWorldProgressQ8",
        "                LD   BC, 7",
        "                LDIR",
        "                LD   DE, RTypeWorldFgScrollQ8",
        "                LD   BC, 6",
        "                LDIR",
        f"                LD   HL, {checkpoint_event_skip}",
        "                LD   (RTypeTargetEventIndex), HL",
        "                LD   HL, (RTypeTargetEventPtr)",
        f"                LD   DE, {checkpoint_event_skip * 6}",
        "                ADD  HL, DE",
        "                LD   (RTypeTargetEventPtr), HL",
        "                LD   HL, 1",
        "                LD   (ArcadeStageFrame), HL",
        "                LD   A, CorePage + 1",
        "                SetPage2_A",
        "                XOR  A",
        "                LD   (RTypePyInitialSnapshotPending), A",
        "                RET",
    ])
    for wrapper, target, preserves_af in bank4_bridges:
        bridge = f"RTypePyBridge_{wrapper}"
        bridge_table_lines.extend(["", f"{bridge}:"])
        if preserves_af:
            bridge_table_lines.append("                PUSH AF")
        bridge_table_lines.extend([
            "                LD   A, RTYPE_OBJECT_BANK4_PAGE",
            "                SetPage2_A",
        ])
        if preserves_af:
            bridge_table_lines.append("                POP  AF")
        bridge_table_lines.extend([
            f"                CALL {target}",
            "                LD   A, CorePage + 1",
            "                SetPage2_A",
            "                RET",
        ])
    text += runtime
    OUT_GAMEPLAY_BACKEND.write_text(text, encoding="utf-8", newline="\n")
    lifecycle_runtime += "\n".join(bridge_table_lines) + "\n"
    table_text = (
        "; Сгенерировано rtype_python_translator.py из Beam renderer/ассетов.\n"
        "; Ручное редактирование запрещено.\n" +
        "\n".join(charge_command_lines + beam_table_lines) + "\n" +
        lifecycle_runtime
    )
    OUT_GAMEPLAY_TABLES.write_text(table_text, encoding="utf-8", newline="\n")
    modifier_layout = contract["terrain_modifier_child_layout"]
    layout_text = f"""; Сгенерировано rtype_python_translator.py из независимых
; Python-полей TerrainModifierChild6C37.local_timer и hp.
RTYPE_PY_MOD_LOCAL_TIMER_OFFSET EQU #{int(modifier_layout['local_timer_offset']):02X}
RTYPE_PY_MOD_HP_OFFSET          EQU #{int(modifier_layout['hp_offset']):02X}
                ASSERT RTYPE_PY_MOD_LOCAL_TIMER_OFFSET + {int(modifier_layout['local_timer_size'])} <= RTYPE_PY_MOD_HP_OFFSET
"""
    OUT_GAMEPLAY_LAYOUT.write_text(layout_text, encoding="utf-8", newline="\n")
    collision_text = f"""; Сгенерировано rtype_python_translator.py из Game.update.
; Эта процедура намеренно размещается ниже $8000: collision bank page #E5
; не видит вторую страницу Core в переключаемом slot2.
RTypePyPlayerTerrainCollision:
                LD   BC, (RTypePlayerNativeX)
                LD   DE, (RTypePlayerNativeY)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #{fg_clear:04X}
                OR   A
                SBC  HL, DE
                JR   C, .hit
                LD   BC, (RTypePlayerNativeX)
                LD   DE, (RTypePlayerNativeY)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #{bg_clear:04X}
                OR   A
                SBC  HL, DE
                RET  NC
.hit:          SCF
                RET

; Collision page #E5 cannot call lifecycle code stored in Core slot2.
; Restore page #06 before tail-entering the Python-translated death branch;
; its RET still reaches the resident wrapper that called the collision bank.
RTypePyCollisionBeginDeath:
                LD   A, CorePage + 1
                SetPage2_A
                ifdef RTYPE_DIAGNOSTIC_INVINCIBLE
                ; Временная покадровая проверка: collision полностью вычислена,
                ; но смерть не запускается. Релиз без define идёт обычным путём.
                RET
                endif
                JP   ArcadeLifecycle_BeginDeath
"""
    OUT_COLLISION_BACKEND.write_text(
        collision_text, encoding="utf-8", newline="\n")


def _tuple_constant(
        tree: ast.Module, names: tuple[str, ...],
        ) -> tuple[int, ...] | None:
    """Извлечь одно буквальное распакованное присваивание целых констант."""
    for node in tree.body:
        if (not isinstance(node, ast.Assign) or len(node.targets) != 1 or
                not isinstance(node.targets[0], (ast.Tuple, ast.List)) or
                not isinstance(node.value, (ast.Tuple, ast.List))):
            continue
        target_names = tuple(
            item.id if isinstance(item, ast.Name) else ""
            for item in node.targets[0].elts)
        if target_names != names or len(node.value.elts) != len(names):
            continue
        if not all(isinstance(item, ast.Constant) and
                   isinstance(item.value, int) and
                   not isinstance(item.value, bool)
                   for item in node.value.elts):
            raise TranslationError(
                f"{names}: геометрия Python должна быть целыми AST-константами")
        return tuple(int(item.value) for item in node.value.elts)  # type: ignore[arg-type]
    return None


def hq_asset_geometry_contract(
        trees: dict[str, ast.Module],
        ) -> tuple[tuple[int, int], tuple[int, int], str]:
    """Проверить геометрию именно тех HQ-банков, которые читает Python."""
    stage_tree = trees.get("rtype_port.stage")
    enemy_tree = trees.get("rtype_port.enemies")
    if stage_tree is None or enemy_tree is None:
        raise TranslationError("HQ asset contract требует stage.py и enemies.py")
    terrain_cell = _tuple_constant(stage_tree, ("GLYPH_W", "GLYPH_H"))
    enemy_constants = module_constants(enemy_tree)
    sprite_cell = (
        enemy_constants.get("SPRITE_CELL_W"),
        enemy_constants.get("SPRITE_CELL_H"),
    )
    if terrain_cell != (14, 15):
        raise TranslationError(
            f"изменена Python HQ terrain cell: {terrain_cell}, ожидалось (14, 15)")
    if sprite_cell != (27, 30):
        raise TranslationError(
            f"изменена Python HQ sprite cell: {sprite_cell}, ожидалось (27, 30)")
    glyph_bytes_assignment = next((
        node for node in stage_tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and
        isinstance(node.targets[0], ast.Name) and
        node.targets[0].id == "GLYPH_BYTES"
    ), None)
    expected_glyph_bytes = ast.parse(
        "GLYPH_W * GLYPH_H * 2", mode="eval").body
    if (glyph_bytes_assignment is None or
            ast.dump(glyph_bytes_assignment.value, include_attributes=False) !=
            ast.dump(expected_glyph_bytes, include_attributes=False)):
        raise TranslationError("Python GLYPH_BYTES не равен GLYPH_W×GLYPH_H×2")
    if enemy_constants.get("SPRITE_CELL_BYTES") != 27 * 30 * 2:
        raise TranslationError("Python SPRITE_CELL_BYTES не равен 27×30×2")

    watched = (
        find_function(enemy_tree, "_asset", "M72SpriteAtlas"),
        find_function(enemy_tree, "cell", "M72SpriteAtlas"),
        find_function(enemy_tree, "draw", "M72SpriteAtlas"),
        find_function(stage_tree, "__init__", "StageSection"),
        find_function(stage_tree, "_draw_layer", "Stage"),
    )
    fingerprint = hashlib.sha256("\n".join(
        ast.dump(node, include_attributes=False) for node in watched
    ).encode("utf-8")).hexdigest()
    return terrain_cell, (int(sprite_cell[0]), int(sprite_cell[1])), fingerprint


def python_sprite_bootstrap_plan() -> tuple[
        tuple[tuple[int, int, int, bool, bool], ...],
        tuple[SpriteTemplateSource, ...],
        tuple[int, ...],
        ]:
    """Execute Python preload and retain both exact cells and draw templates."""
    python_root = str(PYTHON_ROOT)
    if python_root not in sys.path:
        sys.path.insert(0, python_root)
    enemies = importlib.import_module("rtype_port.enemies")
    atlas = enemies.M72SpriteAtlas()
    requested: set[tuple[int, int, int, bool, bool]] = set()
    templates: dict[tuple[int, int], SpriteTemplateSource] = {}
    typed_resources: list[int] = []

    # This is deliberately obtained from the launched Python class itself.
    # The translator does not carry a second hand-maintained resource list.
    for resource_type in range(0x100):
        bank_tuple, path = atlas._asset(0, resource_type)
        if bank_tuple == (1, resource_type):
            if not path.is_file():
                raise TranslationError(
                    f"Python _asset selected missing typed bank {path}")
            typed_resources.append(resource_type)
        elif bank_tuple != (0, 0):
            raise TranslationError(
                f"Python _asset returned unsupported bank key {bank_tuple}")

    def record(palette: int, resource_type: int, code: int,
               flip_x: bool, flip_y: bool) -> None:
        bank_tuple, _path = atlas._asset(palette, resource_type)
        encode_sprite_bank_key(int(bank_tuple[0]), int(bank_tuple[1]))
        requested.add((palette & 0x0F, resource_type & 0xFF,
                       code & 0x0FFF, bool(flip_x), bool(flip_y)))

    original_preload_descriptor = atlas.preload_descriptor

    def record_descriptor(rom: Any, address: int, resource_type: int) -> None:
        descriptor = enemies.read_descriptor(rom, address)
        bank_tuple, _path = atlas._asset(0, resource_type)
        candidate = SpriteTemplateSource(
            descriptor_address=address & 0xFFFF,
            bank_key=encode_sprite_bank_key(
                int(bank_tuple[0]), int(bank_tuple[1])),
            resource_type=resource_type & 0xFF,
            dx=int(descriptor.dx),
            dy=int(descriptor.dy),
            code=int(descriptor.code),
            width=int(descriptor.width),
            height=int(descriptor.height),
            flip_x=bool(descriptor.flip_x),
            flip_y=bool(descriptor.flip_y),
        )
        key = (candidate.bank_key, candidate.descriptor_address)
        previous = templates.setdefault(key, candidate)
        if (previous.dx, previous.dy, previous.code,
                previous.width, previous.height,
                previous.flip_x, previous.flip_y) != (
                candidate.dx, candidate.dy, candidate.code,
                candidate.width, candidate.height,
                candidate.flip_x, candidate.flip_y):
            raise TranslationError(
                f"Python bank/descriptor key {key} has conflicting geometry")
        original_preload_descriptor(rom, address, resource_type)

    atlas.cell = record
    atlas.preload_descriptor = record_descriptor
    atlas.preload_80e3(enemies.M72Rom())
    if not requested:
        raise TranslationError("Python M72SpriteAtlas.preload_80e3 не выбрал ячейки")
    if not templates:
        raise TranslationError("Python M72SpriteAtlas.preload_80e3 не выбрал descriptors")
    return (tuple(sorted(requested)), tuple(sorted(
        templates.values(),
        key=lambda item: (item.bank_key, item.descriptor_address),
    )), tuple(typed_resources))


def python_sprite_bootstrap_requests() -> tuple[
        tuple[int, int, int, bool, bool], ...]:
    """Compatibility view used by focused translator tests."""
    return python_sprite_bootstrap_plan()[0]


def sprite_backend_contract(trees: dict[str, ast.Module]) -> dict[str, Any]:
    """Validate the Python cell renderer before emitting its FT812 backend.

    Python keeps 4096 logical M72 cells and draws a descriptor cell-by-cell.
    The target cannot retain pygame surfaces, so the translator maps that
    exact loop to a persistent index8 RAM_G cell cache.  The streamed Python
    tilemap is mapped to eight immutable 64x512 FT812 bitmap slots per layer;
    a new 64x240 strip is inflated straight into its slot.  Failing these AST
    checks is intentional: a changed Python renderer must never silently keep
    using an obsolete hardware translation.
    """
    tree = trees.get("rtype_port.enemies")
    if tree is None:
        raise TranslationError("модуль rtype_port.enemies недостижим")
    draw = find_function(tree, "draw", "M72SpriteAtlas")
    cell = find_function(tree, "cell", "M72SpriteAtlas")

    code_assignment = next((
        node for node in ast.walk(draw)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "code"
    ), None)
    expected_code = ast.parse(
        "descriptor.code + 8 * source_x + source_y", mode="eval").body
    if (code_assignment is None or
            ast.dump(code_assignment.value, include_attributes=False) !=
            ast.dump(expected_code, include_attributes=False)):
        raise TranslationError(
            "изменена формула M72SpriteAtlas.draw для sprite cell code")

    loop_domains = {
        ast.unparse(node.iter)
        for node in ast.walk(draw)
        if isinstance(node, ast.For)
    }
    if not {"range(descriptor.width)", "range(descriptor.height)"}.issubset(
            loop_domains):
        raise TranslationError(
            "M72SpriteAtlas.draw больше не является width×height cell renderer")

    code_mask = next((
        int(node.value.value)
        for node in ast.walk(cell)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "code"
        and isinstance(node.op, ast.BitAnd)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, int)
    ), None)
    if code_mask != 0x0FFF:
        raise TranslationError(
            "M72SpriteAtlas.cell должен ограничивать code маской 0x0FFF")

    stage_tree = trees.get("rtype_port.stage")
    if stage_tree is None:
        raise TranslationError("модуль rtype_port.stage недостижим")
    draw_strip = find_function(stage_tree, "_draw_strip", "M72Tilemaps")
    draw_layer = find_function(stage_tree, "_draw_layer", "Stage")
    strip_text = ast.unparse(draw_strip)
    layer_text = ast.unparse(draw_layer)
    strip_requirements = (
        "for metatile in range(5)",
        "for row in range(6)",
        "for _ in range(8)",
    )
    layer_requirements = (
        "source_base = (scroll_x >> 3) + 8 & 63",
        "for row in range(32)",
    )
    if (any(fragment not in strip_text for fragment in strip_requirements) or
            any(fragment not in layer_text for fragment in layer_requirements)):
        raise TranslationError(
            "изменена геометрия Python M72 tilemap strip/ring renderer")
    stage_constants = module_constants(stage_tree)
    if stage_constants.get("VISIBLE_ROW_FIRST") != 16:
        raise TranslationError("изменён Python VISIBLE_ROW_FIRST")

    app_tree = trees.get("rtype_port.app")
    if app_tree is None:
        raise TranslationError("модуль rtype_port.app недостижим")
    app_constants = module_constants(app_tree)
    logical_width = app_constants.get("WIDTH")
    logical_height = app_constants.get("HEIGHT")
    if logical_width is None or logical_height is None:
        for node in app_tree.body:
            if (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Tuple)
                    and isinstance(node.value, ast.Tuple)):
                names = [
                    item.id if isinstance(item, ast.Name) else None
                    for item in node.targets[0].elts
                ]
                values = [
                    item.value if isinstance(item, ast.Constant) else None
                    for item in node.value.elts
                ]
                paired = dict(zip(names, values))
                logical_width = paired.get("WIDTH", logical_width)
                logical_height = paired.get("HEIGHT", logical_height)
    physical_width, physical_height, vertex_format = 1024, 768, 3
    geometry = (logical_width, logical_height,
                physical_width, physical_height, vertex_format)
    if geometry != (640, 480, 1024, 768, 3):
        raise TranslationError(
            "изменена геометрия активного Python/FT812 target: "
            f"получено {geometry}, ожидалось (640, 480, 1024, 768, 3)")
    transform_x, rem_x = divmod(256 * logical_width, physical_width)
    transform_y, rem_y = divmod(256 * logical_height, physical_height)
    if rem_x or rem_y or transform_x != transform_y:
        raise TranslationError(
            "Python framebuffer нельзя точно масштабировать одной FT812 матрицей")

    return {
        "validated_source_symbols": (
            "rtype_port.enemies.M72SpriteAtlas.draw",
            "rtype_port.enemies.M72SpriteAtlas.cell",
        ),
        "kind": "ft812_persistent_cell_cache_and_strip_ring",
        "code_count": code_mask + 1,
        "cell_bytes": 16 * 16,
        "buffers": 1,
        "cells_per_buffer": 1024,
        "ram_g_base": 0x0C0000,
        "ram_g_bytes": 0x040000,
        "world_strip_width": 64,
        "world_strip_height": 240,
        "world_slot_height": 512,
        "world_slots_per_layer": 8,
        "logical_width": geometry[0],
        "logical_height": geometry[1],
        "physical_width": geometry[2],
        "physical_height": geometry[3],
        "vertex_format": geometry[4],
        "logical_bitmap_transform": transform_x,
        "ast_sha256": hashlib.sha256(
            (ast.dump(draw, include_attributes=False) + "\n" +
             ast.dump(cell, include_attributes=False) + "\n" +
             ast.dump(draw_strip, include_attributes=False) + "\n" +
             ast.dump(draw_layer, include_attributes=False) + "\n" +
             f"rtype_port.app:{logical_width}x{logical_height}->"
             f"{physical_width}x{physical_height}").encode("utf-8")
        ).hexdigest(),
    }


def emit_sprite_cache_backend(contract: dict[str, Any]) -> None:
    """Emit the FT812 implementation selected from M72SpriteAtlas AST."""
    code_count = int(contract["code_count"])
    cell_bytes = int(contract["cell_bytes"])
    buffers = int(contract["buffers"])
    per_buffer = int(contract["cells_per_buffer"])
    bitmap_transform = int(contract["logical_bitmap_transform"])
    strip_geometry = (
        int(contract["world_strip_width"]),
        int(contract["world_strip_height"]),
        int(contract["world_slot_height"]),
        int(contract["world_slots_per_layer"]),
    )
    if (code_count, cell_bytes, buffers, per_buffer) != (4096, 256, 1, 1024):
        raise TranslationError("неподдержанная геометрия FT812 sprite cache")
    if strip_geometry != (64, 240, 512, 8):
        raise TranslationError("неподдержанная геометрия FT812 world strip ring")
    text = f"""; Сгенерировано rtype_python_translator.py из M72SpriteAtlas.draw/cell.
; Ручное редактирование запрещено: следующая сборка перезапишет файл.
; Python перебирает cells конкретного descriptor. Поэтому target хранит cells,
; а не 8-КБ chunks. Все 1024 slots постоянны до смены world: immutable cell
; после первого TS DMA больше не гоняется заново через Z80 каждый второй кадр.

RTYPE_PY_SPRITE_CODE_COUNT       EQU {code_count}
RTYPE_PY_SPRITE_CELL_BYTES       EQU {cell_bytes}
RTYPE_PY_SPRITE_CACHE_BUFFERS    EQU {buffers}
RTYPE_PY_SPRITE_CELLS_PER_BUFFER EQU {per_buffer}
RTYPE_PY_SPRITE_CACHE_TOTAL      EQU {buffers * per_buffer}
RTYPE_PY_SPRITE_CACHE_RAMG       EQU #0C0000
; Вся bookkeeping живёт в отдельной физической странице TS RAM. Page #09
; уже занята object pool/FIFO/scheduler/palette records: размещение map там
; стирает allocator и даёт пустой level без единого enemy.
RTYPE_PY_SPRITE_META_PAGE        EQU #EC
RTYPE_PY_SPRITE_CELL_MAP         EQU #C000
RTYPE_PY_SPRITE_CELL_MAP_BYTES   EQU {code_count * 2}
RTYPE_PY_LOGICAL_BITMAP_TRANSFORM EQU {bitmap_transform}
RTYPE_PY_WORLD_STRIP_WIDTH       EQU {strip_geometry[0]}
RTYPE_PY_WORLD_STRIP_HEIGHT      EQU {strip_geometry[1]}
RTYPE_PY_WORLD_SLOT_HEIGHT       EQU {strip_geometry[2]}
RTYPE_PY_WORLD_SLOT_BYTES        EQU #8000
RTYPE_PY_WORLD_SLOT_COUNT        EQU {strip_geometry[3]}

; Масштаб вычислен из WIDTH/HEIGHT активного rtype_port.app и физического
; FT812 target. Terrain меняет A/C/E/F, поэтому перед logical Python blit
; translated backend обязан восстановить все шесть коэффициентов.
RTypePyLogicalBitmapState:
                FT_BitmapTransformA RTYPE_PY_LOGICAL_BITMAP_TRANSFORM
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE RTYPE_PY_LOGICAL_BITMAP_TRANSFORM
                FT_BitmapTransformF 0
                RET

; Title Sprite RAM больше не читается в GAME. Resident bytes после
; fixed-player принадлежат сгенерированному backend и видны при любом bank.
RTypePyWorldRenderCount          EQU #4488
RTypeSpriteCacheNextSlot         EQU #4489
RTypePyWorldRenderBaseHigh       EQU #448B
RTypePyWorldRenderSlot           EQU #448C
RTypePyWorldRenderX              EQU #448D
; Scratch lookup принадлежит сгенерированному renderer backend. Python render
; однопоточен, поэтому это не re-entrant ABI и стек Z80 не расходуется под key.
RTypePyHQLookupBankKey           EQU #448E
RTypePyHQLookupFlags             EQU #4490
RTypePyHQLookupCode              EQU #4491
RTypePyHQLookupLow               EQU #4493
RTypePyHQLookupHigh              EQU #4495
RTypePyHQLookupMid               EQU #4497
RTypePyHQLookupSavedPage3        EQU #4499

; Загрузить готовый Python bootstrap 27x30 ARGB4444 в RAM_G. Z80 передаёт
; только выровненный zlib-поток через TS DMA; распаковку выполняет FT812.
; Функция пока является отдельной проверяемой стадией backend: переключение
; draw path выполняется только после готовности resource-aware render queue.
RTypePyHQSprite_Upload:
                CALL FT.Coprocessor.WaitFlush
                RET  C
                FT_WR32_CMD FT_CMD_INFLATE
                LD   DE, RTYPE_PY_HQ_SPRITE_RAMG_BASE & #FFFF
                LD   A, (RTYPE_PY_HQ_SPRITE_RAMG_BASE >> 16) & #FF
                LD   H, 0
                LD   L, A
                CALL FT.Coprocessor.Write32
                RET  C
                LD   A, RTYPE_PY_HQ_SPRITE_ZLIB_FIRST_PAGE
                LD   (.sourcePage), A
                LD   HL, RTYPE_PY_HQ_SPRITE_ZLIB_SIZE
                LD   (.remaining), HL
.page:         LD   BC, #4000
                LD   HL, (.remaining)
                OR   A
                SBC  HL, BC
                JR   NC, .chunkReady
                ADD  HL, BC
                LD   B, H
                LD   C, L
.chunkReady:   LD   (.chunk), BC
                LD   A, (.sourcePage)
                LD   HL, #C000
                CALL RTypeFT_CmdWritePageDMA
                JR   C, .failure
                LD   BC, (.chunk)
                LD   HL, (.remaining)
                OR   A
                SBC  HL, BC
                LD   (.remaining), HL
                LD   A, H
                OR   L
                JR   Z, .complete
                LD   HL, .sourcePage
                INC  (HL)
                JR   .page
.complete:     CALL FT.Coprocessor.WaitFlush
                RET
.failure:      SCF
                RET
.sourcePage:   DEFB 0
.remaining:    DEFW 0
.chunk:        DEFW 0

; Exact HQA2 lookup generated from active Python M72SpriteAtlas._asset keys.
; In:  DE=bank_key ((kind<<8)|value), C=flip flags, HL=Python code.
; Out: CF=0 and A:DE=absolute RAM_G address; CF=1 on an explicit miss.
; Python semantics are applied here: only flip bits 0..1 and code bits 0..11
; participate in the key. The previous slot3 page is always restored.
RTypePyHQSprite_FindCell:
                LD   (RTypePyHQLookupBankKey), DE
                LD   A, C
                AND  #03
                LD   (RTypePyHQLookupFlags), A
                LD   A, H
                AND  #0F
                LD   H, A
                LD   (RTypePyHQLookupCode), HL
                GetPage3
                LD   (RTypePyHQLookupSavedPage3), A
                LD   A, RTYPE_PY_HQ_LOOKUP_PAGE
                SetPage3_A
                LD   HL, 0
                LD   (RTypePyHQLookupLow), HL
                LD   HL, RTYPE_PY_HQ_LOOKUP_COUNT
                LD   (RTypePyHQLookupHigh), HL
.search:        LD   HL, (RTypePyHQLookupLow)
                LD   DE, (RTypePyHQLookupHigh)
                OR   A
                SBC  HL, DE
                JR   NC, .miss
                LD   HL, (RTypePyHQLookupHigh)
                LD   DE, (RTypePyHQLookupLow)
                OR   A
                SBC  HL, DE
                SRL  H
                RR   L
                ADD  HL, DE
                LD   (RTypePyHQLookupMid), HL
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, RTYPE_PY_HQ_LOOKUP_PTR + 16
                ADD  HL, DE
                INC  HL
                LD   A, (RTypePyHQLookupBankKey + 1)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                DEC  HL
                LD   A, (RTypePyHQLookupBankKey)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                INC  HL
                INC  HL
                LD   A, (RTypePyHQLookupFlags)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                INC  HL
                INC  HL
                INC  HL
                LD   A, (RTypePyHQLookupCode + 1)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                DEC  HL
                LD   A, (RTypePyHQLookupCode)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                INC  HL
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   B, (HL)
                INC  HL
                LD   A, (HL)
                OR   A
                JR   NZ, .miss
                LD   A, E
                ADD  A, RTYPE_PY_HQ_SPRITE_RAMG_BASE & #FF
                LD   E, A
                LD   A, D
                ADC  A, (RTYPE_PY_HQ_SPRITE_RAMG_BASE >> 8) & #FF
                LD   D, A
                LD   A, B
                ADC  A, (RTYPE_PY_HQ_SPRITE_RAMG_BASE >> 16) & #FF
                JR   C, .miss
                CP   #40
                JR   NC, .miss
                LD   B, A
                PUSH BC
                PUSH DE
                LD   A, (RTypePyHQLookupSavedPage3)
                SetPage3_A
                POP  DE
                POP  BC
                LD   A, B
                OR   A
                RET
.less:         LD   HL, (RTypePyHQLookupMid)
                LD   (RTypePyHQLookupHigh), HL
                JP   .search
.greater:      LD   HL, (RTypePyHQLookupMid)
                INC  HL
                LD   (RTypePyHQLookupLow), HL
                JP   .search
.miss:         LD   A, (RTypePyHQLookupSavedPage3)
                SetPage3_A
                SCF
                RET

                ASSERT RTYPE_PY_HQ_LOOKUP_REC_SIZE = 10
                ASSERT RTYPE_PY_HQ_LOOKUP_SIZE = 16 + RTYPE_PY_HQ_LOOKUP_COUNT * 10
                ASSERT RTYPE_PY_HQ_LOOKUP_PTR + RTYPE_PY_HQ_LOOKUP_SIZE <= #10000

; Полный сброс нужен только при входе в новый world/level. Python sprite cells
; immutable, поэтому уже загруженный slot остаётся валиден между кадрами.
RTypeSpriteCache_Reset:
                XOR  A
                LD   (RTypeTargetSpriteLoaded), A
                LD   A, RTYPE_PY_SPRITE_META_PAGE
                SetPage3_A
                LD   HL, RTYPE_PY_SPRITE_CELL_MAP
                LD   DE, RTYPE_PY_SPRITE_CELL_MAP + 1
                LD   BC, RTYPE_PY_SPRITE_CELL_MAP_BYTES - 1
                LD   (HL), #FF
                LDIR
                XOR  A
                LD   (RTypeSpriteCacheNextSlot), A
                LD   (RTypeSpriteCacheNextSlot + 1), A
                INC  A
                LD   (RTypeTargetSpriteLoaded), A
                RET

; Межкадровое начало теперь не очищает map и не вызывает повторные DMA.
RTypeSpriteCache_BeginFrame:
                LD   A, (RTypeTargetSpriteLoaded)
                OR   A
                JP   Z, RTypeSpriteCache_Reset
                RET

; HL=Python cell code 0..4095. Вернуть HL=absolute cache slot 0..1023.
; Каждый miss копирует аппаратным TS DMA ровно одну исходную 16x16 index8 cell.
RTypeSpriteCache_LoadCell:
                LD   A, H
                AND  #F0
                JP   NZ, .full
                LD   (.requested), HL
                LD   A, (RTypeTargetSpriteLoaded)
                OR   A
                CALL Z, RTypeSpriteCache_Reset
                LD   A, RTYPE_PY_SPRITE_META_PAGE
                SetPage3_A
                LD   HL, (.requested)
                ADD  HL, HL
                LD   DE, RTYPE_PY_SPRITE_CELL_MAP
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                EX   DE, HL
                LD   A, H
                CP   #FF
                JR   Z, .miss
                OR   A
                RET

.miss:         LD   HL, (RTypeSpriteCacheNextSlot)
                LD   A, H
                CP   4
                JP   NC, .full
                INC  HL
                LD   (RTypeSpriteCacheNextSlot), HL
                DEC  HL
                LD   (.slot), HL

                LD   HL, (.requested)
                ADD  HL, HL
                LD   DE, RTYPE_PY_SPRITE_CELL_MAP
                ADD  HL, DE
                LD   DE, (.slot)
                LD   (HL), E
                INC  HL
                LD   (HL), D

                LD   HL, (.requested)
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   DE, RTypeSpriteRawPageTable
                ADD  HL, DE
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                LD   HL, (.requested)
                LD   A, L
                AND  #3F
                OR   #C0
                LD   H, A
                LD   L, 0
                LD   DE, (.slot)
                LD   A, D
                ADD  A, (RTYPE_PY_SPRITE_CACHE_RAMG >> 16) & #FF
                LD   D, E
                LD   E, 0
                LD   BC, RTYPE_PY_SPRITE_CELL_BYTES
                CALL RTypeFT_WriteMemDMA
                LD   HL, (.slot)
                OR   A
                RET
.full:         SCF
                RET
.requested:    DEFW 0
.slot:         DEFW 0

; A=0 foreground/1 background, HL=strip index, C=ring tracker. Python создаёт
; contiguous 64x240 strip; FT812 распаковывает его прямо в один из восьми
; 64x512 slots. Старые 240 CMD_MEMCPY и 3840-байтная Z80 SPI-команда исчезли.
RTypePyWorldTexturePump:
                LD   (.layer), A
                LD   A, C
                LD   (.tracker), A
                LD   (.stripIndex), HL
                LD   A, (.layer)
                OR   A
                JR   NZ, .background
                LD   A, (RTypeTargetFgTexturePage)
                LD   HL, (RTypeTargetFgTexturePtr)
                LD   D, #08
                JR   .streamReady
.background:   LD   A, (RTypeTargetBgTexturePage)
                LD   HL, (RTypeTargetBgTexturePtr)
                LD   D, #04
.streamReady:  LD   (.streamPage), A
                LD   (.streamPtr), HL
                LD   A, D
                LD   (.textureBaseHigh), A

                ; destination slot = ((tracker >> 4) + 1) & 7. Y=128 leaves
                ; the same vertical guard area as the former 512x512 ring.
                LD   A, (.tracker)
                RRCA
                RRCA
                RRCA
                RRCA
                INC  A
                AND  7
                LD   C, A
                AND  1
                JR   Z, .evenSlot
                LD   DE, #A000
                JR   .destinationLowReady
.evenSlot:     LD   DE, #2000
.destinationLowReady:
                LD   (.destinationLow), DE
                LD   A, C
                SRL  A
                LD   B, A
                LD   A, (.textureBaseHigh)
                ADD  A, B
                LD   (.destinationHigh), A

                LD   A, (.streamPage)
                SetPage3_A
                LD   HL, (.stripIndex)
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                ADD  HL, HL                      ; index * 6
                LD   DE, (.streamPtr)
                ADD  HL, DE
                LD   DE, RTYPE_TARGET_TEXTURE_HEAD
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   C, (HL)
                INC  HL
                INC  HL
                LD   (.relative), DE
                LD   A, C
                LD   (.relative + 2), A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (.compressedSize), DE
                LD   DE, (.relative)
                LD   A, (.relative + 2)
                ADD  A, A
                ADD  A, A
                LD   C, A
                LD   A, D
                AND  #C0
                RLCA
                RLCA
                OR   C
                LD   C, A
                LD   A, (.streamPage)
                ADD  A, C
                LD   (.compressedPage), A
                LD   A, D
                AND  #3F
                LD   H, A
                LD   L, E
                LD   BC, (.compressedSize)
                EXX
                LD   B, 0
                EXX
                LD   A, (.compressedPage)
                EX   AF, AF'
                LD   DE, (.destinationLow)
                LD   A, (.destinationHigh)
                JP   FT.Coprocessor.Inflate
.layer:        DEFB 0
.tracker:      DEFB 0
.stripIndex:   DEFW 0
.streamPage:   DEFB 0
.streamPtr:    DEFW 0
.relative:     DEFS 3
.compressedSize: DEFW 0
.compressedPage: DEFB 0
.textureBaseHigh: DEFB 0
.destinationHigh: DEFB 0
.destinationLow: DEFW 0

; A=physical source page, HL=page-safe strip index, C=tracker, D=map page.
; Source and collision map are simultaneously mapped into slot3/slot2. This
; removes the former 960-byte scratch copy; only the thirty unavoidable
; strided 32-byte map rows remain on Z80, while bitmap pixels go through FT812.
RTypePyWorldMapStripDirect:
                LD   (.inputPage), A
                LD   A, C
                LD   (.tracker), A
                LD   A, D
                LD   (.destinationPage), A
                LD   A, (.inputPage)
                CALL RTypeWorld_StripPointer
                SetPage3_A
                LD   (.source), HL
                LD   A, (.destinationPage)
                SetPage2_A
                LD   A, (.tracker)
                ADD  A, A
                ADD  A, #20
                LD   (.destinationLow), A
                LD   A, #90                      ; slot2 + map offset #1000
                LD   (.destinationHigh), A
                LD   HL, (.source)
                LD   B, 30
.row:
                PUSH BC
                LD   A, (.destinationLow)
                LD   E, A
                LD   A, (.destinationHigh)
                LD   D, A
                LD   BC, 32
                LDIR
                LD   A, (.destinationHigh)
                INC  A
                LD   (.destinationHigh), A
                POP  BC
                DJNZ .row
                LD   A, CorePage + 1
                SetPage2_A
                RET
.inputPage:    DEFB 0
.tracker:      DEFB 0
.destinationPage: DEFB 0
.source:       DEFW 0
.destinationLow: DEFB 0
.destinationHigh: DEFB 0

; Семь отдельных 64x512 bitmap slots покрывают 384 native pixels. FT812 сам
; масштабирует, обрезает первый slot по scroll offset и повторяет Y; Z80 выдаёт
; только семь BITMAP_SOURCE/VERTEX2F вместо копирования 240 строк.
RTypePyRenderWorldBackground:
                LD   A, #04
                LD   (RTypePyWorldRenderBaseHigh), A
                LD   HL, (RTypeWorldBgScrollQ8 + 1)
                LD   DE, 64
                ADD  HL, DE
                CALL RTypePyWorldRenderPrepareX
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 720
                CALL RTypePyWorldRenderTransform
                LD   HL, (RTypeWorldBgYScrollQ8 + 1)
                LD   DE, 128
                ADD  HL, DE
                CALL Render_WorldTransformF
                FT_PaletteSource RTYPE_WORLD_TILE_PALETTE_RAMG
                JP   RTypePyWorldRenderSlots

RTypePyRenderWorldForeground:
                LD   A, #08
                LD   (RTypePyWorldRenderBaseHigh), A
                LD   HL, (RTypeWorldFgScrollQ8 + 1)
                LD   DE, 64
                ADD  HL, DE
                CALL RTypePyWorldRenderPrepareX
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 720
                CALL RTypePyWorldRenderTransform
                LD   HL, (RTypeWorldFgYScrollQ8 + 1)
                LD   DE, 128
                ADD  HL, DE
                CALL Render_WorldTransformF
                FT_PaletteSource RTYPE_WORLD_TILE_PALETTE_RAMG + 512
                JP   RTypePyWorldRenderSlots

RTypePyWorldRenderPrepareX:
                LD   (.scroll), HL
                LD   A, H
                AND  1
                LD   H, A
                LD   A, L
                AND  #3F
                JR   Z, .zeroOffset
                NEG
                LD   L, A
                LD   H, #FF
                JR   .xReady
.zeroOffset:   LD   HL, 0
.xReady:       LD   (RTypePyWorldRenderX), HL
                ; slot = ((scroll & 511) >> 6) & 7
                LD   HL, (.scroll)
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   A, L
                AND  7
                LD   (RTypePyWorldRenderSlot), A
                RET
.scroll:       DEFW 0

RTypePyWorldRenderTransform:
                FT_BitmapTransformA 96
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 85
                RET

RTypePyWorldRenderSlots:
                FT_BitmapLayout FT_PALETTED4444, 64, 512
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_REPEAT, 171, 720
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   A, 7
                LD   (RTypePyWorldRenderCount), A
.next:         LD   A, (RTypePyWorldRenderSlot)
                LD   C, A
                SRL  A
                LD   B, A
                LD   A, (RTypePyWorldRenderBaseHigh)
                ADD  A, B
                LD   C, A
                LD   A, (RTypePyWorldRenderSlot)
                AND  1
                JR   Z, .sourceEven
                LD   D, #80
                JR   .sourceReady
.sourceEven:   LD   D, 0
.sourceReady:  LD   E, 0
                LD   B, #01
                CALL FT.Coprocessor.Command_BCDE
                LD   HL, (RTypePyWorldRenderX)
                CALL RTypeSprite_NativeXToVertex
                LD   H, B
                LD   L, C
                LD   DE, 0
                CALL M72Video_Vertex2f
                LD   HL, (RTypePyWorldRenderX)
                LD   DE, 64
                ADD  HL, DE
                LD   (RTypePyWorldRenderX), HL
                LD   A, (RTypePyWorldRenderSlot)
                INC  A
                AND  7
                LD   (RTypePyWorldRenderSlot), A
                LD   HL, RTypePyWorldRenderCount
                DEC  (HL)
                JR   NZ, .next
                FT_End
                RET
"""
    OUT_SPRITE_CACHE.write_text(text, encoding="utf-8", newline="\n")


def audit_generated_z80_stack(paths: Iterable[Path]) -> dict[str, Any]:
    """Reject unbalanced PUSH/POP paths in translator-owned Z80 routines."""
    routines: dict[str, dict[str, int]] = {}
    current: str | None = None
    depth = 0
    maximum = 0
    returns = 0
    for path in paths:
        for line_number, raw in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            code = raw.split(";", 1)[0].strip()
            if not code:
                continue
            global_label = re.fullmatch(r"(RType[A-Za-z0-9_]+):", code)
            if global_label:
                if current is not None and depth != 0:
                    raise TranslationError(
                        f"{path.name}:{line_number}: {current} оставляет "
                        f"{depth} байт на Z80 stack")
                if current is not None:
                    routines[current] = {
                        "max_local_bytes": maximum,
                        "returns": returns,
                    }
                current = global_label.group(1)
                depth = maximum = returns = 0
                continue
            if current is None:
                continue
            instruction = code.split(None, 1)[0].upper()
            if instruction == "PUSH":
                depth += 2
                maximum = max(maximum, depth)
            elif instruction == "POP":
                depth -= 2
                if depth < 0:
                    raise TranslationError(
                        f"{path.name}:{line_number}: POP без PUSH в {current}")
            elif instruction in {"RET", "RETI", "RETN"}:
                returns += 1
                if depth != 0:
                    raise TranslationError(
                        f"{path.name}:{line_number}: возврат {current} при "
                        f"stack delta {depth}")
                # CALL temporarily places one return word on the hardware
                # stack. It does not change the caller's persistent delta.
            elif instruction == "CALL":
                maximum = max(maximum, depth + 2)
    if current is not None:
        if depth != 0:
            raise TranslationError(f"{current} оставляет {depth} байт на Z80 stack")
        routines[current] = {"max_local_bytes": maximum, "returns": returns}
    if not routines:
        raise TranslationError("не найдены сгенерированные Z80 routines для stack audit")
    return {
        "balanced": True,
        "routines": routines,
        "max_translator_local_bytes": max(
            item["max_local_bytes"] for item in routines.values()),
    }


def emit_z80_stack_control() -> dict[str, Any]:
    """Emit runtime stack bounds/canary and audit all generated Z80 code."""
    layout_path = ROOT / "Source" / "ASM" / "m72_video.asm"
    layout_text = layout_path.read_text(encoding="utf-8")
    scratch = re.search(
        r"(?m)^M72StageEventScratch\s+EQU\s+#([0-9A-Fa-f]+)",
        layout_text)
    scratch_count = re.search(
        r"(?m)^M72StageEventScratchEnd\s+EQU\s+"
        r"M72StageEventScratch\s*\+\s*(\d+)\s*\*\s*(\d+)",
        layout_text)
    resident_contract = re.search(
        r"(?m)^RTYPE_RESIDENT_DATA_END\s+EQU\s+M72StageEventScratchEnd",
        layout_text)
    if not (scratch and scratch_count and resident_contract):
        raise TranslationError(
            "m72_video.asm не публикует RTYPE_RESIDENT_DATA_END для Z80 stack")
    resident_end = (int(scratch.group(1), 16) +
                    int(scratch_count.group(1)) * int(scratch_count.group(2)))
    guard_base = (resident_end + 31) & ~31
    guard_bytes = 32
    stack_bottom = guard_base + guard_bytes
    stack_top = 0x4EFF
    text = f"""; Сгенерировано rtype_python_translator.py.
; Translator owns the Z80 stack contract. RTYPE_RESIDENT_DATA_END=#{resident_end:04X};
; #{guard_base:04X}…#{guard_base + guard_bytes - 1:04X} is a canary and usable stack
; may not descend below #{stack_bottom:04X}.

RTYPE_PY_Z80_STACK_GUARD_BASE  EQU #{guard_base:04X}
RTYPE_PY_Z80_STACK_GUARD_BYTES EQU {guard_bytes}
RTYPE_PY_Z80_STACK_BOTTOM      EQU #{stack_bottom:04X}
RTYPE_PY_Z80_STACK_TOP         EQU #{stack_top:04X}
RTYPE_PY_Z80_STACK_BYTES       EQU RTYPE_PY_Z80_STACK_TOP - RTYPE_PY_Z80_STACK_BOTTOM + 1
RTYPE_PY_Z80_STACK_CANARY      EQU #A5
RTypePyStackFault              EQU #44B0
RTypePyStackPhase              EQU #44B1
RTypePyStackObservedSP         EQU #44B2
; Scheduler watchdog state is translator-owned too: it must never overlap
; sprite/palette scratch assembled by the handwritten FT812 backend.
RTypePySchedulerUpdateRemaining EQU #44B4
RTypePySchedulerInsertRemaining EQU #44B5
RTypePySchedulerRebuildIndex    EQU #44B6
RTypePySchedulerRepairCount     EQU #44B7
; Per-frame number of intermediate FT812 command-buffer flushes.  The
; translator owns this byte so the backend diagnostic cannot overlap a Python
; gameplay field when the generated layout changes.
RTypePyCommandFlushCount         EQU #44B8

                ASSERT StackTop = RTYPE_PY_Z80_STACK_TOP
                ASSERT #{resident_end:04X} <= RTYPE_PY_Z80_STACK_GUARD_BASE

RTypePyStack_Init:
                LD   HL, RTYPE_PY_Z80_STACK_GUARD_BASE
                LD   B, RTYPE_PY_Z80_STACK_GUARD_BYTES
                LD   A, RTYPE_PY_Z80_STACK_CANARY
.fill:         LD   (HL), A
                INC  HL
                DJNZ .fill
                XOR  A
                LD   (RTypePyStackFault), A
                LD   (RTypePyStackPhase), A
                LD   (RTypePySchedulerUpdateRemaining), A
                LD   (RTypePySchedulerInsertRemaining), A
                LD   (RTypePySchedulerRebuildIndex), A
                LD   (RTypePySchedulerRepairCount), A
                LD   (RTypePyCommandFlushCount), A
                LD   HL, RTYPE_PY_Z80_STACK_TOP
                LD   (RTypePyStackObservedSP), HL
                RET

; Проверяется на каждой итерации MainLoop до следующего Python update.
; Carry=1 останавливает игру до того, как повреждение уйдёт в object pool.
RTypePyStack_Check:
                LD   HL, 0
                ADD  HL, SP
                LD   (RTypePyStackObservedSP), HL
                LD   DE, RTYPE_PY_Z80_STACK_TOP - 2
                OR   A
                SBC  HL, DE
                JR   NZ, .spFault
                LD   HL, RTYPE_PY_Z80_STACK_GUARD_BASE
                LD   B, RTYPE_PY_Z80_STACK_GUARD_BYTES
                LD   A, RTYPE_PY_Z80_STACK_CANARY
.check:        CP   (HL)
                JR   NZ, .fault
                INC  HL
                DJNZ .check
                OR   A
                RET
.fault:        LD   A, 1
                LD   (RTypePyStackFault), A
                SCF
                RET
.spFault:      LD   A, 2
                LD   (RTypePyStackFault), A
                SCF
                RET

; Stack уже недостоверен: никаких CALL/PUSH. Красный border делает fault
; видимым и процессор остаётся в локальном цикле вместо дальнейшей порчи RAM.
RTypePyStack_Fatal:
                DI
                LD   A, 2
                OUT  (#FE), A
.halt:         JR   .halt
"""
    OUT_STACK_CONTROL.write_text(text, encoding="utf-8", newline="\n")
    audit = audit_generated_z80_stack((OUT_SPRITE_CACHE, OUT_STACK_CONTROL))
    return {
        "guard_base": guard_base,
        "guard_bytes": guard_bytes,
        "stack_bottom": stack_bottom,
        "stack_top": stack_top,
        "usable_bytes": stack_top - stack_bottom + 1,
        "resident_data_end": resident_end,
        "layout_source": str(layout_path.relative_to(ROOT)).replace("\\", "/"),
        "runtime_canary": True,
        "build_audit": audit,
    }


def emit_include(records: list[dict[str, Any]], scalar_constants: list[dict[str, Any]],
                 blob_size: int, fingerprint: str) -> None:
    lines = [
        "; Сгенерировано rtype_python_translator.py из активного Source/Python.",
        "; Ручное редактирование запрещено: следующая сборка перезапишет файл.",
        f"RTYPE_PY_TRANSLATION_PAGE EQU #{TARGET_PAGE:02X}",
        f"RTYPE_PY_TRANSLATION_SIZE EQU #{blob_size:04X}",
        f"RTYPE_PY_TRANSLATION_PAGE_COUNT EQU {(blob_size + PAGE_SIZE - 1) // PAGE_SIZE}",
        f"RTYPE_PY_TRANSLATION_FINGERPRINT_LO EQU #{fingerprint[:4]}",
        "",
    ]
    for record in scalar_constants:
        lines.extend([
            f"; {record['symbol']} | AST {record['ast_sha256'][:16]}",
            f"{record['asm_name']} EQU {record['value']}",
            "",
        ])
    for record in records:
        prefix = record["asm_name"].upper()
        dimensions = record["dimensions"]
        lines.extend([
            f"; {record['symbol']} | AST {record['ast_sha256'][:16]}",
            f"{prefix}_PAGE EQU #{record['page']:02X}",
            f"{prefix}_OFFSET EQU #{record['page_offset']:04X}",
            f"{prefix}_ADDRESS EQU #{0xC000 + record['page_offset']:04X}",
            f"{prefix}_COUNT EQU {record['entries']}",
            f"{prefix}_DIMENSIONS EQU {len(dimensions)}",
        ])
        for index, size in enumerate(dimensions):
            lines.append(f"{prefix}_DIM{index} EQU {size}")
        lines.append("")
    OUT_INC.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def translator_generation_surfaces(
        project_root: Path = ROOT,
        ) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Return the complete bounded output surface owned by this translator.

    The two directories contain generated artifacts only.  Files in shared
    Build/ASM directories are listed individually so rollback can never touch
    an unrelated user or tool output.
    """
    build = project_root / "Build"
    asm = project_root / "Source" / "ASM"
    files = (
        build / "python_translation_tables.bin",
        build / "rtype_python_translation.json",
        build / "rtype_python_sprite_working_set_status.json",
        build / "rtype_python_frame_render_plan_status.json",
        build / "rtype_python_frame_record_bound_status.json",
        build / "rtype_python_frame_record_reachability_status.json",
        build / "rtype_python_frame_sprite_fragment_envelope_status.json",
        build / "rtype_python_frame_budget_status.json",
        build / "rtype_python_frame_budget.json",
        build / "rtype_python_draw_target_bundle_status.json",
        build / "rtype_python_draw_bank_placement_status.json",
        build / "rtype_python_mutation_hook_ir_status.json",
        build / "rtype_python_object_store_ir_status.json",
        build / "rtype_python_function_cfg_status.json",
        build / "rtype_python_active_call_graph_status.json",
        build / "rtype_python_active_call_site_lowering_status.json",
        build / "rtype_python_whole_program_vm_call_abi_status.json",
        build / "rtype_python_active_target_adapters_status.json",
        build / "rtype_python_frame_timing_provider_status.json",
        build / "rtype_python_frame_timing_contract.json",
        build / "rtype_python_draw_ramdl_shadow_v4_status.json",
        build / "rtype_python_whole_program_vm.bin",
        build / "rtype_python_whole_program_vm_proof.bin",
        build / "rtype_python_whole_program_vm_status.json",
        build / "rtype_python_whole_program_vm_stack_bound_status.json",
        build / "rtype_python_translation_checkpoint.json",
        build / "rtype_python_full_hqt3_inventory_status.json",
        build / "rtype_python_hqt3_ramg_schedule_status.json",
        build / "rtype_python_hqt3_partition_solver_status.json",
        build / "rtype_python_hqt3_frame_page_solver_status.json",
        build / "rtype_python_assets.json",
        build / "rtype_python_beam_commands.bin",
        build / "python_compiled_p00.bin",
        build / "rtype_python_compiled.asm",
        build / "rtype_python_compiled.map",
        build / "rtype_python_ir.json",
        build / "rtype_python_compiler.json",
        asm / "generated_python_translation.inc",
        asm / "generated_python_sprite_cache.asm",
        asm / "generated_python_stack.asm",
        asm / "generated_python_gameplay.asm",
        asm / "generated_python_gameplay_tables.inc",
        asm / "generated_python_gameplay_layout.inc",
        asm / "generated_python_collision.asm",
        asm / "generated_python_compiled_symbols.inc",
        asm / "generated_python_call_adapters.asm",
        asm / "generated_python_frame_timing.inc",
    )
    directories = (
        build / "PythonAssets",
        project_root / "Source" / "C" / "generated",
    )
    return files, directories


def translation_generation_transaction(
        project_root: Path = ROOT) -> GenerationTransaction:
    files, directories = translator_generation_surfaces(project_root)
    return GenerationTransaction(files=files, directories=directories)


def sprite_working_set_report(
        coverage_report: CoverageReport, project_root: Path = ROOT,
        ) -> dict[str, Any]:
    """Build a deterministic, source-bound working-set report in memory.

    ``plan_sprite_working_sets`` owns no output path.  Keeping this adapter
    before the first generator write means a stale source binding or an
    analysis error cannot leave partial translator artifacts.  A valid
    ``BLOCKED_*`` result remains a reportable proof state; only
    ``--require-complete`` turns that honest incompleteness into a build
    failure.
    """
    plan: WorkingSetPlan = plan_sprite_working_sets(
        coverage_report, project_root)
    if (plan.root_module != coverage_report.root_module or
            plan.coverage_source_hashes != coverage_report.source_hashes or
            plan.rom_sha256 != coverage_report.rom_sha256):
        raise TranslationError(
            "sprite working-set analysis is not bound to CoverageReport")
    result = plan.as_dict()
    stable_json = json.dumps(
        result, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    analysis_sha256 = hashlib.sha256(stable_json.encode("utf-8")).hexdigest()
    if stable_json != plan.to_json() or analysis_sha256 != plan.analysis_sha256:
        raise TranslationError(
            "sprite working-set report is not deterministically reproducible")
    result["analysis_sha256"] = analysis_sha256
    return result


def _translate_untransactional(require_complete: bool) -> dict[str, Any]:
    stage_started = time.perf_counter()
    print(
        f"[translator] multiprocessing jobs: {_PARALLEL_JOBS}",
        flush=True,
    )
    paths = module_paths()
    entry_module, launcher_sha256 = launcher_entry()
    trees, edges = reachable_graph(paths, entry_module)
    excluded = sorted(
        module for module in trees
        if module == "rtype_port.full_runtime" or module.startswith("rtype_m72")
    )
    if excluded:
        raise TranslationError(
            "run_python.cmd достиг исключённого старого runtime: "
            + ", ".join(excluded)
        )
    required_modules = {
        "rtype_port.app", "rtype_port.game", "rtype_port.stage",
        "rtype_port.enemies", "rtype_port.force", "rtype_port.bits",
        "rtype_port.title", "rtype_port.audio", "rtype_port.tsfm",
    }
    missing = sorted(required_modules - trees.keys())
    if missing:
        raise TranslationError(f"активный граф не содержит обязательные модули: {missing}")

    # Sprite coverage is part of the translation contract, not a post-build
    # diagnostic.  It follows the same active run_python.cmd import graph and
    # fails before any generated target file is mutated when a draw sink,
    # descriptor selector, event handler, or bank domain is no longer finite.
    (sprite_coverage, frame_render_plan,
     frame_record_bound) = _run_initial_analyses(ROOT, _PARALLEL_JOBS)
    if sprite_coverage.root_module != entry_module:
        raise TranslationError(
            "анализ спрайтов выполнен не от активной Python-точки входа: "
            f"{sprite_coverage.root_module!r} != {entry_module!r}"
        )
    if sprite_coverage.unresolved_domains:
        raise TranslationError(
            "не замкнуты Python-домены спрайтов: "
            + ", ".join(sprite_coverage.unresolved_domains)
        )
    # This remains entirely in memory.  In particular, the structured
    # BLOCKED lifetime result is embedded into the final report but never
    # silently promoted to a resident pack or used to emit target data.
    sprite_working_sets = sprite_working_set_report(sprite_coverage, ROOT)
    enemy_draw_plan = compile_active_enemy_draw_plan(
        ROOT, coverage_report=sprite_coverage)
    frame_render_plan_report = frame_render_plan.as_dict()
    frame_record_bound_report = frame_record_bound.as_dict()
    stage_started = _progress("initial source analyses", stage_started)
    frame_record_reachability_report = frame_record_bound_report.get(
        "abstract_reachability")
    if (not isinstance(frame_record_reachability_report, dict) or
            frame_record_reachability_report.get("format") !=
            "pyz80.frame-record-reachability-subproof.v1" or
            frame_record_reachability_report.get(
                "proof_complete_for_conservative_certification") is not True):
        raise TranslationError(
            "frame record bound omitted its conservative reachability proof")

    compiler_manifest = CompilerManifest.load(PYZ80_MANIFEST)
    translated = {
        spec.symbol: "translated_lut" for spec in TABLE_SPECS
    }
    translated.update({
        spec.symbol: "translated_lut" for spec in CONSTANT_TABLE_SPECS
    })
    translated.update({
        spec.symbol: "compiled_z80" for spec in compiler_manifest.functions
    })
    symbols, schemas = inventory(trees, translated)
    imported_pending = [
        item for item in symbols if item["status"] == "pending"]

    # These are the first generated target artifacts after the active import
    # graph, coverage and draw-plan proofs.  The surrounding generation
    # transaction guarantees byte-exact rollback if the later whole-callable
    # graph or final --require-complete closure remains blocked.  The compact VM is the
    # selected lowering; the readable unrolled C is retained only as a
    # semantic oracle.  Neither enters the live link before the remaining
    # adapter/stack/frame certificates pass.  --require-complete must fail
    # before either write just like it fails before every legacy mutation.
    render_order_backend = emit_render_order_backend_stage(ROOT)
    draw_vm_backend = emit_draw_vm_backend_stage(enemy_draw_plan)
    draw_state_backend = emit_draw_state_backend_stage(enemy_draw_plan, ROOT)
    mutation_hook_plan, mutation_hook_ir = build_mutation_hook_ir_stage(
        draw_state_backend, ROOT)
    OUT_MUTATION_HOOK_IR_STATUS.write_text(
        json.dumps(mutation_hook_ir, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    object_store_module, object_store_ir = build_object_store_ir_stage(
        mutation_hook_plan, mutation_hook_ir, ROOT)
    OUT_OBJECT_STORE_IR_STATUS.write_text(
        json.dumps(object_store_ir, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    function_cfg_module, function_cfg_ir = build_function_cfg_ir_stage(
        mutation_hook_plan, object_store_module,
        mutation_hook_ir, object_store_ir, ROOT)
    OUT_FUNCTION_CFG_STATUS.write_text(
        json.dumps(function_cfg_ir, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    active_call_graph = active_call_graph_contract(
        mutation_hook_plan, object_store_module,
        mutation_hook_ir, object_store_ir, ROOT)
    OUT_ACTIVE_CALL_GRAPH_STATUS.write_text(
        json.dumps(active_call_graph, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    stage_started = _progress("whole callable graph", stage_started)
    active_call_site_lowering = active_call_site_lowering_contract(
        active_call_graph, ROOT)
    stage_started = _progress("call-site lowering", stage_started)
    whole_program_vm_call_abi = whole_program_vm_call_abi_contract(
        active_call_graph, active_call_site_lowering, ROOT)
    stage_started = _progress("whole-program call ABI", stage_started)
    active_target_adapters = active_target_adapters_contract(
        active_call_graph, ROOT)
    OUT_ACTIVE_TARGET_ADAPTERS_STATUS.write_text(
        json.dumps(active_target_adapters, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    frame_timing_provider = frame_timing_provider_contract(
        active_target_adapters, ROOT)
    (whole_program_vm_artifact, whole_program_vm,
     whole_program_vm_stack_bound) = whole_program_vm_contract(
         active_call_graph, active_call_site_lowering,
         whole_program_vm_call_abi, ROOT, object_store_ir=object_store_ir)
    stage_started = _progress("compact whole-program VM", stage_started)
    vm_translated_symbols: dict[str, str] = {}
    for item in whole_program_vm_artifact.document["functions"]:
        row = item["row"]
        symbol = f"{row['module']}.{row['qualname']}"
        if symbol in vm_translated_symbols:
            raise TranslationError(
                f"whole-program VM emitted duplicate symbol {symbol}")
        vm_translated_symbols[symbol] = "encoded_whole_program_vm"
    translated.update(vm_translated_symbols)
    pending = active_reachable_pending_symbols(active_call_graph, translated)
    draw_c_backend = emit_draw_c_backend_stage(enemy_draw_plan)

    gameplay_backend = {
        **gameplay_backend_contract(trees),
        "status": "legacy_template_not_translation",
    }
    sprite_backend = {
        **sprite_backend_contract(trees),
        "status": "legacy_template_not_translation",
    }
    terrain_cell, sprite_cell, hq_asset_ast_sha256 = (
        hq_asset_geometry_contract(trees))
    sprite_bootstrap, sprite_templates, typed_resources = (
        python_sprite_bootstrap_plan())
    hq_assets = compile_rtype_hq_asset_plan(
        ROOT,
        sprite_bootstrap,
        sprite_templates,
        typed_resources,
        terrain_cell=terrain_cell,
        sprite_cell=sprite_cell,
        source_ast_sha256=hq_asset_ast_sha256,
    )
    compiler_result = compile_manifest(
        python_root=PYTHON_ROOT,
        manifest_path=PYZ80_MANIFEST,
        output_directory=ROOT / "Build",
        asm_directory=ROOT / "Source" / "ASM",
        c_directory=ROOT / "Source" / "C" / "generated",
        support_files=compiler_support_files(),
        support_exports=FT812_SUPPORT_EXPORTS,
    )
    hq_asset_manifest_sha256 = hashlib.sha256(
        HQ_ASSET_MANIFEST.read_bytes()).hexdigest()
    sprite_asset_detail = next(
        artifact for artifact in hq_assets["artifacts"]
        if artifact["kind"] == "sprite-bootstrap-working-set")
    sprite_template_detail = sprite_asset_detail["templates"]
    hq_asset_summary = {
        "format": hq_assets["format"],
        "manifest": str(HQ_ASSET_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": hq_asset_manifest_sha256,
        "source_ast_sha256": hq_assets["source_ast_sha256"],
        "pixel_format": hq_assets["pixel_format"],
        "terrain_cell": hq_assets["terrain_cell"],
        "sprite_cell": hq_assets["sprite_cell"],
        "sprite_bootstrap_requests": hq_assets["sprite_bootstrap_requests"],
        "sprite_bank_resolution": sprite_asset_detail["bank_resolution"],
        "sprite_hybrid_pack": {
            key: sprite_asset_detail[key]
            for key in ("format", "pixel_policy", "size",
                        "raw_argb4444_bytes", "saved_bytes",
                        "logical_entries", "unique_cells", "palette_count",
                        "format_counts")
        },
        "descriptor_lowering": {
            "format": "M72SpriteAtlas-fixed-exact-v1",
            "x_formula": "round(native*5/3)",
            "y_formula": "round(native*15/8)",
            "rounding": "Python ties-to-even",
            "native_x_range": [-1535, 1535],
            "native_y_range": [-1365, 1365],
            "outside_range": "fail-closed",
            "append_phase": "positive logical modulo 5 without division",
        },
        "queue_protocol": ft812_queue_protocol_contract(),
        "sprite_templates": {
            key: sprite_template_detail[key]
            for key in ("format", "path", "size", "sha256", "record_count",
                        "record_size", "cell_count", "cell_record_size",
                        "state_count", "state_record_size", "resolver_hash",
                        "append", "c_tables")
        },
        "totals": hq_assets["totals"],
        "target_policy": hq_assets["target_policy"],
        "artifacts": [{
            key: artifact[key]
            for key in ("kind", "path", "size", "sha256",
                        "logical_entries", "unique_cells")
        } for artifact in hq_assets["artifacts"]],
    }
    frame_sprite_fragment_envelope = (
        frame_sprite_fragment_envelope_contract(
            frame_record_bound_report,
            sprite_coverage,
            enemy_draw_plan,
            hq_assets,
            ROOT,
        )
    )
    OUT_FRAME_SPRITE_FRAGMENT_ENVELOPE_STATUS.write_text(
        json.dumps(frame_sprite_fragment_envelope, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    full_hqt3_inventory = full_hqt3_inventory_contract(
        sprite_coverage, frame_sprite_fragment_envelope, ROOT)
    OUT_FULL_HQT3_INVENTORY_STATUS.write_text(
        json.dumps(full_hqt3_inventory, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    stage_started = _progress("full HQT3 inventory", stage_started)
    hqt3_ramg_schedule = hqt3_ramg_schedule_contract(
        full_hqt3_inventory, ROOT, max_workers=_PARALLEL_JOBS)
    OUT_HQT3_RAMG_SCHEDULE_STATUS.write_text(
        json.dumps(hqt3_ramg_schedule, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    stage_started = _progress("parallel HQT3 RAM_G schedule", stage_started)
    hqt3_partition_solver = hqt3_partition_solver_contract(
        full_hqt3_inventory, hqt3_ramg_schedule, ROOT,
        max_workers=_PARALLEL_JOBS)
    OUT_HQT3_PARTITION_SOLVER_STATUS.write_text(
        json.dumps(hqt3_partition_solver, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    stage_started = _progress("parallel HQT3 partition solver", stage_started)
    hqt3_frame_page_solver = hqt3_frame_page_solver_contract(
        full_hqt3_inventory, hqt3_ramg_schedule, hqt3_partition_solver,
        frame_record_bound_report, frame_sprite_fragment_envelope,
        active_call_graph, ROOT)
    OUT_HQT3_FRAME_PAGE_SOLVER_STATUS.write_text(
        json.dumps(hqt3_frame_page_solver, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    draw_ramdl_shadow_v4 = draw_ramdl_shadow_v4_contract(ROOT)
    draw_fast_pipeline = draw_fast_pipeline_contract(
        draw_vm_backend, hq_asset_summary)
    lifecycle_constants = lifecycle_constant_contract(trees)
    checkpoint_data, checkpoint_record = compile_initial_checkpoint_snapshot()
    gameplay_backend["initial_checkpoint"] = checkpoint_record
    emit_sprite_cache_backend(sprite_backend)
    z80_stack = emit_z80_stack_control()
    blob = bytearray()
    records: list[dict[str, Any]] = []
    compiled_tables = [(spec, *compile_table(spec, trees)) for spec in TABLE_SPECS]
    compiled_tables.extend(
        (spec, *compile_constant_table(spec, trees))
        for spec in CONSTANT_TABLE_SPECS
    )
    for spec, data, record in compiled_tables:
        if len(blob) & 1:
            blob.append(0)
        page_offset = len(blob) % PAGE_SIZE
        if page_offset + len(data) > PAGE_SIZE:
            blob.extend(bytes(PAGE_SIZE - page_offset))
        offset = len(blob)
        record["offset"] = offset
        record["page"] = TARGET_PAGE + offset // PAGE_SIZE
        record["page_offset"] = offset % PAGE_SIZE
        record["size"] = len(data)
        records.append(record)
        blob.extend(data)

    if len(blob) & 1:
        blob.append(0)
    checkpoint_page_offset = len(blob) % PAGE_SIZE
    if checkpoint_page_offset + len(checkpoint_data) > PAGE_SIZE:
        blob.extend(bytes(PAGE_SIZE - checkpoint_page_offset))
    checkpoint_offset = len(blob)
    checkpoint_record["offset"] = checkpoint_offset
    checkpoint_record["page"] = TARGET_PAGE + checkpoint_offset // PAGE_SIZE
    checkpoint_record["page_offset"] = checkpoint_offset % PAGE_SIZE
    checkpoint_record["size"] = len(checkpoint_data)
    records.append(checkpoint_record)
    blob.extend(checkpoint_data)
    emit_gameplay_backend(gameplay_backend)
    page_count = (len(blob) + PAGE_SIZE - 1) // PAGE_SIZE
    if TARGET_PAGE + page_count > 0x100:
        raise TranslationError(f"LUT занимают {page_count} страниц и выходят за 4 МБ TS RAM")

    source_files = source_manifest(paths, trees)
    fingerprint_source = "\n".join(f"{item['module']}:{item['sha256']}" for item in source_files)
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    # This is the final translator-owned ASM write.  The whole-frame gate
    # hashes the entire ASM tree, so it must run only after this point.
    emit_include(records, lifecycle_constants, len(blob), fingerprint)
    frame_budget = frame_budget_contract(frame_render_plan_report, ROOT)
    # The linked-bundle probe hash-binds this exact final budget status.  Write
    # it inside the generation transaction before probing; any later failure
    # restores the previous byte-exact file together with all other outputs.
    OUT_FRAME_BUDGET_STATUS.write_text(
        json.dumps(frame_budget, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    draw_target_bundle = draw_target_bundle_contract(ROOT)
    OUT_DRAW_TARGET_BUNDLE_STATUS.write_text(
        json.dumps(draw_target_bundle, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    # The split placement checker hashes the just-written unsplit certificate,
    # performs both pinned links and assembles the resident gate.  It remains
    # inside the same rollback transaction as every other translator output.
    draw_bank_placement = draw_bank_placement_contract(
        draw_target_bundle, ROOT)
    OUT_DRAW_BANK_PLACEMENT_STATUS.write_text(
        json.dumps(draw_bank_placement, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    frame_budget_contract_artifact: dict[str, Any] = {
        "path": _project_path(OUT_FRAME_BUDGET_CONTRACT),
        "present": OUT_FRAME_BUDGET_CONTRACT.is_file(),
    }
    if OUT_FRAME_BUDGET_CONTRACT.is_file():
        contract_bytes = OUT_FRAME_BUDGET_CONTRACT.read_bytes()
        frame_budget_contract_artifact.update({
            "size": len(contract_bytes),
            "sha256": hashlib.sha256(contract_bytes).hexdigest(),
        })
        try:
            contract_value = json.loads(contract_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            contract_value = None
        frame_budget_contract_artifact["format"] = (
            contract_value.get("format")
            if isinstance(contract_value, dict) else None)
        frame_budget_contract_artifact["bindings"] = (
            contract_value.get("bindings")
            if isinstance(contract_value, dict) else None)
    frame_budget_live_hook = {
        "format": "rtype-python-frame-budget-live-hook-v1",
        "status": "BLOCKED_PREPUBLICATION_AND_TARGET_HOOK_UNPROVED",
        "present": False,
        "record_counter_symbol": None,
        "prepublication_record_and_append_bound_proved": False,
        "atomic_complete_frame_publication_proved": False,
        "fast_pipeline_status_sha256":
            draw_fast_pipeline["target_size_probe"]["sha256"],
        "fast_pipeline_timing_sha256":
            draw_fast_pipeline["pinned_z80_timing"]["sha256"],
        "sprite_fragment_envelope_semantic_sha256":
            frame_sprite_fragment_envelope["semantic_sha256"],
        "sprite_fragment_envelope_proof_complete":
            frame_sprite_fragment_envelope["proof_complete"],
        "blockers": [
            "no source-derived max-record counter is exported on target",
            "reachable HQT3/CMD_APPEND weighted join is incomplete",
            "fast chunks may form a published prefix before a later failure",
            "queue rotation is not bound to one atomic complete-frame commit",
            "the final build has external ASM generators after this translator",
        ],
    }
    translation_closure = translation_closure_contract(
        pending=pending,
        sprite_working_sets=sprite_working_sets,
        frame_record_bound=frame_record_bound_report,
        frame_sprite_fragment_envelope=frame_sprite_fragment_envelope,
        frame_render_plan=frame_render_plan_report,
        frame_budget=frame_budget,
        frame_budget_live_hook=frame_budget_live_hook,
        render_order_backend=render_order_backend,
        draw_vm_backend=draw_vm_backend,
        draw_state_backend=draw_state_backend,
        draw_fast_pipeline=draw_fast_pipeline,
        draw_target_bundle=draw_target_bundle,
        draw_bank_placement=draw_bank_placement,
        mutation_hook_ir=mutation_hook_ir,
        object_store_ir=object_store_ir,
        function_cfg_ir=function_cfg_ir,
        active_call_graph=active_call_graph,
        active_call_site_lowering=active_call_site_lowering,
        whole_program_vm_call_abi=whole_program_vm_call_abi,
        active_target_adapters=active_target_adapters,
        frame_timing_provider=frame_timing_provider,
        draw_ramdl_shadow_v4=draw_ramdl_shadow_v4,
        whole_program_vm=whole_program_vm,
        whole_program_vm_stack_bound=whole_program_vm_stack_bound,
        full_hqt3_inventory=full_hqt3_inventory,
        hqt3_ramg_schedule=hqt3_ramg_schedule,
        hqt3_partition_solver=hqt3_partition_solver,
        hqt3_frame_page_solver=hqt3_frame_page_solver,
        gameplay_backend=gameplay_backend,
        sprite_backend=sprite_backend,
    )
    if require_complete and not translation_closure["complete"]:
        raise TranslationError(
            "полная трансляция запрошена, но live closure не завершён: "
            + ", ".join(
                str(item["code"])
                for item in translation_closure["blockers"]
            )
        )
    report = {
        "format": "rtype-python-translation-v2",
        "entry": entry_module,
        "launcher": {
            "path": str(LAUNCHER.relative_to(ROOT)).replace("\\", "/"),
            "sha256": launcher_sha256,
        },
        "source_fingerprint": fingerprint,
        "target": {
            "cpu": "Z80",
            "video": "FT812",
            "table_page": TARGET_PAGE,
            "table_bytes": len(blob),
            "compiled_code_page": compiler_result.report["target"]["code_page"],
        },
        "modules": source_files,
        "imports": edges,
        "tables": records[:-1],
        "generated_state": [checkpoint_record],
        "scalar_constants": lifecycle_constants,
        "compiler": compiler_result.report,
        "hardware_backends": [
            {
                "kind": "exact-hq-argb4444-working-sets",
                "status": "compiled-from-active-python",
                "manifest": "Build/rtype_python_assets.json",
                "ast_sha256": hq_asset_ast_sha256,
            },
            gameplay_backend,
            sprite_backend,
        ],
        "hq_assets": hq_asset_summary,
        "sprite_coverage": sprite_coverage.as_dict(),
        "sprite_working_sets": sprite_working_sets,
        "draw_plans": [enemy_draw_plan.as_dict()],
        "frame_render_plan": frame_render_plan_report,
        "render_order_backend": render_order_backend,
        "draw_backend_selection": {
            "selected": "compact_vm",
            "selected_status": draw_vm_backend["status"],
            "unrolled_role": "diagnostic_semantic_oracle",
            "live_target_performance_and_size_certified": False,
        },
        "draw_vm_backend": draw_vm_backend,
        "draw_state_backend": draw_state_backend,
        "mutation_hook_ir": mutation_hook_ir,
        "object_store_ir": object_store_ir,
        "active_function_cfg_ir": {
            "status": function_cfg_ir["status"],
            "live": function_cfg_ir["live"],
            "status_path": _project_path(OUT_FUNCTION_CFG_STATUS),
            "semantic_sha256": function_cfg_ir["semantic_sha256"],
            "source": function_cfg_ir["source"],
            "coverage": {
                name: function_cfg_ir["coverage"][name]
                for name in (
                    "function_count",
                    "runtime_mutation_site_count",
                    "spliced_store_fragment_count",
                    "cfg_block_count",
                    "cfg_exception_edge_count",
                    "cfg_instruction_count",
                    "function_expression_program_count",
                    "function_expression_block_count",
                    "function_expression_instruction_count",
                    "unsupported_count",
                    "full_function_cfg_lowered",
                    "current_c_backend_consumes_function_cfg",
                )
            },
            "live_blockers": function_cfg_ir["live_blockers"],
        },
        "active_call_graph": {
            "status": active_call_graph["status"],
            "live": active_call_graph["live"],
            "status_path": _project_path(OUT_ACTIVE_CALL_GRAPH_STATUS),
            "semantic_sha256": active_call_graph["semantic_sha256"],
            "entrypoint": active_call_graph["entrypoint"],
            "source_graph": {
                name: active_call_graph["source_graph"][name]
                for name in (
                    "module_count", "module_names",
                    "internal_import_edge_count", "external_import_edge_count",
                    "semantic_sha256",
                )
            },
            "callable_inventory": {
                name: active_call_graph["callable_inventory"][name]
                for name in (
                    "callable_count", "cfg_lowered_callable_count",
                    "cfg_blocker_free_callable_count",
                    "cfg_blocked_callable_count", "cfg_lowering_failure_count",
                    "unsupported_lowering_blocker_count",
                    "cfg_block_count", "cfg_exception_edge_count",
                    "cfg_instruction_count",
                )
            },
            "class_count": active_call_graph["class_inventory"]["class_count"],
            "call_graph": {
                name: active_call_graph["call_graph"][name]
                for name in (
                    "call_site_count", "exact_internal_edge_count",
                    "finite_dynamic_dispatch_site_count",
                    "unresolved_call_site_count",
                    "proven_reachable_callable_count",
                    "not_proven_reachable_callable_count",
                    "reachable_finite_dynamic_dispatch_site_count",
                    "reachable_unresolved_call_site_count",
                    "reachable_host_boundary_call_site_count",
                    "reachable_cfg_blocker_count",
                    "reachable_cfg_lowering_failure_count",
                    "reachability_uses_only_proven_edges",
                    "module_import_does_not_imply_callable_reachability",
                    "dynamic_candidates_are_not_promoted_to_proven_reachable",
                    "semantic_sha256",
                )
            },
            "module_initialization": {
                name: active_call_graph["module_initialization"][name]
                for name in (
                    "status", "call_site_count", "explicit_call_site_count",
                    "decorator_application_count", "host_boundary_call_site_count",
                    "unresolved_call_site_count",
                    "module_initializers_have_no_function_cfg", "semantic_sha256",
                )
            },
            "boundaries": [{
                name: row.get(name) for name in (
                    "boundary", "status", "total_inventoried_call_site_count",
                    "reachable_call_site_count",
                    "module_initialization_call_site_count",
                )
            } for row in active_call_graph["boundaries"]],
            "proof": active_call_graph["proof"],
            "compiler_input_sha256":
                active_call_graph["compiler_input_sha256"],
            "reachable_pending_count": len(pending),
            "imported_pending_diagnostic_count": len(imported_pending),
            "live_blockers": active_call_graph["live_blockers"],
        },
        "active_call_site_lowering": {
            **active_call_site_lowering,
            "status_path": _project_path(
                OUT_ACTIVE_CALL_SITE_LOWERING_STATUS),
        },
        "whole_program_vm_call_abi": {
            **whole_program_vm_call_abi,
            "status_path": _project_path(
                OUT_WHOLE_PROGRAM_VM_CALL_ABI_STATUS),
        },
        "active_target_adapters": {
            "status": active_target_adapters["status"],
            "live": active_target_adapters["live"],
            "status_path": _project_path(OUT_ACTIVE_TARGET_ADAPTERS_STATUS),
            "semantic_sha256": active_target_adapters["semantic_sha256"],
            "input_binding": active_target_adapters["input_binding"],
            "provider_catalog": active_target_adapters["provider_catalog"],
            "inventory": {
                name: active_target_adapters["inventory"][name]
                for name in (
                    "site_count", "unique_call_site_count",
                    "exact_callable_semantics_count",
                    "resolved_call_site_ids",
                    "unresolved_callable_semantics_count",
                    "unresolved_call_site_ids", "source_resolved_call_site_ids",
                    "source_resolved_internal_call_count",
                    "source_resolved_internal_no_adapter_count",
                    "source_resolved_internal_target_substitution_count",
                    "provider_family_mapped_site_count",
                    "provider_capability_match_site_count",
                    "adapter_pending_site_count", "semantic_group_count",
                    "runtime", "module_initialization",
                    "input_resolution_kind_counts", "semantic_kind_counts",
                    "provider_family_counts", "multi_provider_routing_site_count",
                    "adapter_binding_status_counts", "interprocedural_fact_proof",
                    "semantic_groups",
                )
            },
            "adapter_abi_obligation_count":
                active_target_adapters["adapter_abi_obligation_count"],
            "proof": active_target_adapters["proof"],
            "live_blockers": active_target_adapters["live_blockers"],
        },
        "frame_timing_provider": {
            "status": frame_timing_provider["status"],
            "live": frame_timing_provider["live"],
            "status_path": _project_path(OUT_FRAME_TIMING_PROVIDER_STATUS),
            "contract_path": _project_path(OUT_FRAME_TIMING_CONTRACT),
            "include_path": _project_path(OUT_FRAME_TIMING_INCLUDE),
            "semantic_sha256": frame_timing_provider["semantic_sha256"],
            "input_binding": frame_timing_provider["input_binding"],
            "contract": frame_timing_provider["contract"],
            "generated_artifacts":
                frame_timing_provider["generated_artifacts"],
            "integration": frame_timing_provider["integration"],
            "live_blockers": frame_timing_provider["live_blockers"],
        },
        "whole_program_vm": {
            **whole_program_vm,
            "bytecode_path": _project_path(OUT_WHOLE_PROGRAM_VM_BIN),
            "target_bytecode_path": _project_path(
                OUT_WHOLE_PROGRAM_VM_BIN),
            "proof_bytecode_path": _project_path(
                OUT_WHOLE_PROGRAM_VM_PROOF_BIN),
            "status_path": _project_path(OUT_WHOLE_PROGRAM_VM_STATUS),
        },
        "whole_program_vm_stack_bound": {
            **whole_program_vm_stack_bound,
            "status_path": _project_path(
                OUT_WHOLE_PROGRAM_VM_STACK_BOUND_STATUS),
        },
        "draw_ramdl_shadow_v4": {
            "status": draw_ramdl_shadow_v4["status"],
            "live": draw_ramdl_shadow_v4["live"],
            "status_path": _project_path(OUT_DRAW_RAMDL_SHADOW_V4_STATUS),
            "analysis_sha256": draw_ramdl_shadow_v4["analysis_sha256"],
            "layout": draw_ramdl_shadow_v4["layout"],
            "raster": draw_ramdl_shadow_v4["raster"],
            "target_object": draw_ramdl_shadow_v4["target_object"],
            "target_stack": draw_ramdl_shadow_v4["target_stack"],
            "allocation": draw_ramdl_shadow_v4["allocation"],
            "timing": draw_ramdl_shadow_v4["timing"],
            "proofs": draw_ramdl_shadow_v4["proofs"],
            "blockers": draw_ramdl_shadow_v4["blockers"],
        },
        "draw_fast_pipeline": draw_fast_pipeline,
        "draw_target_bundle": draw_target_bundle,
        "draw_bank_placement": draw_bank_placement,
        "draw_c_backend": draw_c_backend,
        "frame_record_bound": frame_record_bound_report,
        "frame_record_reachability": frame_record_reachability_report,
        "frame_sprite_fragment_envelope": frame_sprite_fragment_envelope,
        "full_hqt3_inventory": {
            "status": full_hqt3_inventory["status"],
            "live": full_hqt3_inventory["live"],
            "status_path": _project_path(OUT_FULL_HQT3_INVENTORY_STATUS),
            "analysis_sha256": full_hqt3_inventory["analysis_sha256"],
            "source_binding_sha256":
                full_hqt3_inventory["source_binding_sha256"],
            "template_count":
                full_hqt3_inventory["global_catalog"]["template_count"],
            "template_cell_reference_count":
                full_hqt3_inventory["global_catalog"]
                ["template_cell_reference_count"],
            "unique_logical_cell_count":
                full_hqt3_inventory["global_catalog"]
                ["unique_logical_cell_count"],
            "load_scope_count":
                full_hqt3_inventory["load_plan"]["scope_storage"]
                ["scope_count"],
            "resident_combinations":
                full_hqt3_inventory["load_plan"]["resident_combinations"],
            "frame_sprite_fragment_envelope_crosscheck":
                full_hqt3_inventory
                ["frame_sprite_fragment_envelope_crosscheck"],
            "blockers": full_hqt3_inventory["blockers"],
        },
        "hqt3_ramg_schedule": {
            "status": hqt3_ramg_schedule["status"],
            "live": hqt3_ramg_schedule["live"],
            "status_path": _project_path(OUT_HQT3_RAMG_SCHEDULE_STATUS),
            "analysis_sha256": hqt3_ramg_schedule["analysis_sha256"],
            "inventory_binding": hqt3_ramg_schedule["inventory_binding"],
            "capacities": hqt3_ramg_schedule["capacities"],
            "scope_pack_census": hqt3_ramg_schedule["scope_pack_census"],
            "event_transition_summary": {
                name: hqt3_ramg_schedule["event_transitions"][name]
                for name in (
                    "event_obligation_count",
                    "event_correlation_exact_count",
                    "event_correlation_ambiguous_count",
                    "event_count_without_independent_scope_pack",
                    "unique_event_pixel_pack_count",
                    "event_scope_eviction_never_inferred_from_next_event",
                    "force_epoch_at_most_one_live",
                    "force_epoch_switch_timeline_proved",
                )
            },
            "blockers": hqt3_ramg_schedule["blockers"],
        },
        "hqt3_partition_solver": {
            "status": hqt3_partition_solver["status"],
            "live": hqt3_partition_solver["live"],
            "status_path": _project_path(OUT_HQT3_PARTITION_SOLVER_STATUS),
            "analysis_sha256": hqt3_partition_solver["analysis_sha256"],
            "input_binding": hqt3_partition_solver["input_binding"],
            "structural_partition_proof_complete":
                hqt3_partition_solver["structural_partition_proof_complete"],
            "ram_g_runtime_paging_complete":
                hqt3_partition_solver["ram_g_runtime_paging_complete"],
            "problem_scope_count": hqt3_partition_solver["problem_scope_count"],
            "event_cost_census": hqt3_partition_solver["event_cost_census"],
            "blocker_resolution": hqt3_partition_solver["blocker_resolution"],
            "proof_boundaries": hqt3_partition_solver["proof_boundaries"],
            "resident_combinations":
                hqt3_partition_solver["resident_combinations"],
            "eviction_inferences": hqt3_partition_solver["eviction_inferences"],
            "blockers": hqt3_partition_solver["blockers"],
        },
        "hqt3_frame_page_solver": {
            "status": hqt3_frame_page_solver["status"],
            "live": hqt3_frame_page_solver["live"],
            "status_path": _project_path(
                OUT_HQT3_FRAME_PAGE_SOLVER_STATUS),
            "analysis_sha256": hqt3_frame_page_solver["analysis_sha256"],
            "input_binding": hqt3_frame_page_solver["input_binding"],
            "frame_record_contract":
                hqt3_frame_page_solver["frame_record_contract"],
            "hardware_contract":
                hqt3_frame_page_solver["hardware_contract"],
            "exact_bcab_page_catalog": {
                name: hqt3_frame_page_solver["exact_bcab_page_catalog"][name]
                for name in (
                    "scope_id", "page_atom_count", "union_ram_g_bytes",
                    "union_ram_g_overflow_bytes",
                    "all_atoms_individually_strict_ram_g_fit",
                    "exact_per_frame_page_set_proved",
                )
            },
            "strict_lower_bounds":
                hqt3_frame_page_solver["strict_lower_bounds"],
            "double_buffer_capacity":
                hqt3_frame_page_solver["double_buffer_capacity"],
            "upload_bandwidth":
                hqt3_frame_page_solver["upload_bandwidth"],
            "tsconf_staging": hqt3_frame_page_solver["tsconf_staging"],
            "proof_boundaries":
                hqt3_frame_page_solver["proof_boundaries"],
            "minimum_missing_facts":
                hqt3_frame_page_solver["minimum_missing_facts"],
            "resident_combinations":
                hqt3_frame_page_solver["resident_combinations"],
            "eviction_inferences":
                hqt3_frame_page_solver["eviction_inferences"],
            "blockers": hqt3_frame_page_solver["blockers"],
        },
        "frame_fragment_budget_contract": frame_budget_contract_artifact,
        "whole_frame_ft812_budget": frame_budget,
        "frame_budget_live_hook": frame_budget_live_hook,
        "translation_closure": translation_closure,
        "generated_fragments": [
            {
                "source": "rtype_port.game.Game.__init__ / "
                          "rtype_port.enemies.M72EnemyWorld.__init__",
                "target": "RTypePyGameplay_LoadInitialSnapshot",
                "status": "legacy_template_not_translation",
            },
            {
                "source": "rtype_port.game.Game.update.m72_frame_counter",
                "target": "RTypePyGameplay_AdvanceFrameCounter",
                "status": "legacy_template_not_translation",
            },
            {
                "source": "rtype_port.enemies.M72ObjectPool.bind/release Q8 residue",
                "target": "RTypePyObjects_ClearScratchWithResidue",
                "status": "legacy_template_not_translation",
            },
            {
                "source": "rtype_port.stage.M72Scroll.dispatch_progression",
                "target": "RTypePyGameplay_GetDispatchProgression",
                "status": "legacy_template_not_translation",
            },
            {
                "source": "rtype_port.stage.M72Scroll dispatch deltas",
                "target": "RTypePyGameplay_ObjectsUpdateWithDispatchDeltas",
                "status": "legacy_template_not_translation",
            },
            {
                "source": "rtype_port.enemies.M72EnemyWorld.update RNG reset",
                "target": "RTypePyGameplay_RngReseedAndUpdate",
                "status": "legacy_template_not_translation",
            },
        ],
        "z80_stack": z80_stack,
        "dataclasses": schemas,
        "assets": asset_literals(trees),
        "coverage": {
            "compiled_z80": len(compiler_result.functions),
            "translated_lut": len(compiled_tables),
            "generated_state": 1,
            "translated_symbols": len(translated),
            "pending": len(pending),
            "pending_definition":
                "source-proven reachable active Python callables only",
            "imported_pending_diagnostic": len(imported_pending),
            "complete": bool(translation_closure["complete"]),
            "closure_blocker_count": translation_closure["blocker_count"],
            "sprite_working_sets_ready": bool(
                sprite_working_sets["ready"]),
            "frame_record_bound_proved": bool(
                frame_record_bound_report["proof_complete"]),
            "frame_record_bound_kind":
                frame_record_bound_report.get("bound_kind"),
            "frame_record_max_records":
                frame_record_bound_report.get(
                    "certified_frame_max_records"),
            "frame_sprite_fragment_envelope_proved": bool(
                frame_sprite_fragment_envelope["proof_complete"]),
            "frame_sprite_fragment_missing_template_count": sum(
                int(item.get("missing_template_count", 0))
                for item in frame_sprite_fragment_envelope["blockers"]
                if isinstance(item, dict)),
            "frame_budget_proved": (
                frame_budget.get("status") == "PASS" and
                frame_budget.get("full_frame_proved") is True),
            "frame_budget_live": bool(frame_budget_live_hook["present"]),
            "draw_target_bundle_live": bool(draw_target_bundle["live"]),
            "draw_target_linked_code_bytes":
                draw_target_bundle["link"]["code"]["bytes"],
            "draw_target_linked_data_bytes":
                draw_target_bundle["link"]["data"]["bytes"],
            "draw_target_linked_code_banks":
                draw_target_bundle["link"]["code"]["banks_required"],
            "draw_target_known_stack_bytes":
                draw_target_bundle["stack"]
                ["maximum_known_candidate_bytes"],
            "draw_bank_placement_live": bool(
                draw_bank_placement["live"]),
            "draw_bank_f1_linked_code_bytes":
                draw_bank_placement["links"]["page_f1"]["code"]["bytes"],
            "draw_bank_f2_linked_code_bytes":
                draw_bank_placement["links"]["page_f2"]["code"]["bytes"],
            "draw_bank_resident_gate_bytes":
                draw_bank_placement["resident_gate"]["bytes"],
            "mutation_hooks_lowered":
                mutation_hook_ir["coverage"]["counts"]
                ["direct_and_implicit_lowered"],
            "mutation_hooks_live": bool(mutation_hook_ir["live"]),
            "object_store_fragments_lowered":
                object_store_ir["coverage"]["runtime_hook_fragments"],
            "object_expression_programs_lowered":
                object_store_ir["coverage"]["expression_census"]
                ["expression_cfg_programs"],
            "object_expression_ssa_instructions":
                object_store_ir["coverage"]["expression_census"]
                ["expression_ssa_instructions"],
            "object_store_ir_live": bool(object_store_ir["live"]),
            "active_function_cfg_complete": bool(
                function_cfg_ir["coverage"]["full_function_cfg_lowered"]),
            "active_function_cfg_live": bool(function_cfg_ir["live"]),
            "active_function_cfg_functions":
                function_cfg_ir["coverage"]["function_count"],
            "active_function_cfg_blocks":
                function_cfg_ir["coverage"]["cfg_block_count"],
            "active_function_cfg_exception_edges":
                function_cfg_ir["coverage"]["cfg_exception_edge_count"],
            "active_call_graph_live": bool(active_call_graph["live"]),
            "active_call_graph_modules":
                active_call_graph["source_graph"]["module_count"],
            "active_call_graph_callables":
                active_call_graph["callable_inventory"]["callable_count"],
            "active_call_graph_cfg_lowered":
                active_call_graph["callable_inventory"]
                ["cfg_lowered_callable_count"],
            "active_call_graph_proven_reachable":
                active_call_graph["call_graph"]
                ["proven_reachable_callable_count"],
            "active_call_graph_not_proven_reachable":
                active_call_graph["call_graph"]
                ["not_proven_reachable_callable_count"],
            "active_call_graph_reachable_unresolved_calls":
                active_call_graph["call_graph"]
                ["reachable_unresolved_call_site_count"],
            "active_call_graph_reachable_host_boundaries":
                active_call_graph["call_graph"]
                ["reachable_host_boundary_call_site_count"],
            "active_call_graph_module_initialization_calls":
                active_call_graph["module_initialization"]["call_site_count"],
            "active_call_site_lowering_live": bool(
                active_call_site_lowering["live"]),
            "active_call_site_lowering_backend_consumer_bound": bool(
                active_call_site_lowering["proof"]
                ["backend_consumer_bound"]),
            "active_call_site_lowering_reachable_graph_sites":
                active_call_site_lowering["mapping"]
                ["reachable_graph_call_site_count"],
            "active_call_site_lowering_represented_graph_sites":
                active_call_site_lowering["mapping"]
                ["represented_graph_call_site_count"],
            "active_call_site_lowering_unrepresented_graph_sites":
                active_call_site_lowering["mapping"]
                ["unrepresented_graph_call_site_count"],
            "active_call_site_lowering_cfg_occurrences":
                active_call_site_lowering["mapping"]
                ["cfg_python_call_occurrence_count"],
            "active_call_site_lowering_duplicate_cfg_occurrences":
                active_call_site_lowering["mapping"]
                ["duplicate_cfg_occurrence_count"],
            "active_call_site_lowering_classification_counts":
                active_call_site_lowering["mapping"]
                ["classification_counts"],
            "active_call_site_lowering_blocker_site_counts":
                active_call_site_lowering["blocker_site_counts"],
            "active_call_site_lowering_semantic_sha256":
                active_call_site_lowering["semantic_sha256"],
            "whole_program_vm_call_abi_live": bool(
                whole_program_vm_call_abi["live"]),
            "whole_program_vm_call_abi_backend_consumer_bound": bool(
                whole_program_vm_call_abi["proof"]
                ["current_vm_backend_consumes_call_abi"]),
            "whole_program_vm_call_abi_function_count":
                whole_program_vm_call_abi["function_id_contract"]
                ["function_count"],
            "whole_program_vm_call_abi_site_descriptors":
                whole_program_vm_call_abi["census"]
                ["represented_call_site_count"],
            "whole_program_vm_call_abi_occurrence_descriptors":
                whole_program_vm_call_abi["census"]
                ["call_occurrence_descriptor_count"],
            "whole_program_vm_call_abi_exact_ssa_provenance":
                whole_program_vm_call_abi["census"]
                ["exact_callable_ssa_provenance_count"],
            "whole_program_vm_call_abi_ambiguous_ssa_provenance":
                whole_program_vm_call_abi["census"]
                ["ambiguous_callable_ssa_provenance_count"],
            "whole_program_vm_call_abi_classification_counts":
                whole_program_vm_call_abi["census"]
                ["classification_counts"],
            "whole_program_vm_call_abi_binding_mode_counts":
                whole_program_vm_call_abi["census"]
                ["binding_mode_counts"],
            "whole_program_vm_call_abi_blocker_descriptor_counts":
                whole_program_vm_call_abi["census"]
                ["blocker_descriptor_counts"],
            "whole_program_vm_call_abi_semantic_sha256":
                whole_program_vm_call_abi["semantic_sha256"],
            "active_target_adapter_sites":
                active_target_adapters["inventory"]["site_count"],
            "active_target_adapter_exact_semantics":
                active_target_adapters["inventory"]
                ["exact_callable_semantics_count"],
            "active_target_adapter_unresolved_semantics":
                active_target_adapters["inventory"]
                ["unresolved_callable_semantics_count"],
            "active_target_adapter_capability_matches":
                active_target_adapters["inventory"]
                ["provider_capability_match_site_count"],
            "active_target_adapter_pending":
                active_target_adapters["inventory"]
                ["adapter_pending_site_count"],
            "active_target_adapters_live": bool(active_target_adapters["live"]),
            "frame_timing_provider_live": bool(frame_timing_provider["live"]),
            "frame_timing_target_millihz": 55000,
            "frame_timing_ft812_vcycle":
                frame_timing_provider["contract"]["selected_profile"]
                ["registers"]["FT_REG_VCYCLE"],
            "frame_timing_safe_scanline_cycles":
                frame_timing_provider["contract"]["scanline_budget"]
                ["practical_cycle_limit_floor"],
            "whole_program_vm_live": bool(whole_program_vm["live"]),
            "whole_program_vm_encoded_functions":
                whole_program_vm["proof_coverage"]["function_count"],
            "whole_program_vm_expression_programs":
                whole_program_vm["proof_coverage"]
                ["expression_program_count"],
            "whole_program_vm_bytecode_bytes":
                whole_program_vm["target_bytecode"]["bytes"],
            "whole_program_vm_target_bytecode_bytes":
                whole_program_vm["target_bytecode"]["bytes"],
            "whole_program_vm_proof_bytecode_bytes":
                whole_program_vm["host_proof"]["bytes"],
            "whole_program_vm_max_frame_slots":
                whole_program_vm["target_coverage"]
                ["max_frame_slot_count"],
            "whole_program_vm_call_abi_enabled":
                whole_program_vm["call_abi_binding"]["enabled"],
            "whole_program_vm_call_abi_exact_cfg_path_binding":
                whole_program_vm["call_abi_binding"]
                ["occurrences_bound_by_exact_cfg_path"],
            "whole_program_vm_active_call_site_lowering_semantic_sha256":
                whole_program_vm["call_abi_binding"]
                ["active_call_site_lowering_semantic_sha256"],
            "whole_program_vm_call_abi_input_semantic_sha256":
                whole_program_vm["call_abi_binding"]
                ["whole_program_vm_call_abi_semantic_sha256"],
            "whole_program_vm_abi_eligible_call_instructions":
                whole_program_vm["target_coverage"]
                ["abi_eligible_call_instruction_count"],
            "whole_program_vm_abi_lowered_call_instructions":
                whole_program_vm["target_coverage"]
                ["abi_lowered_call_instruction_count"],
            "whole_program_vm_abi_unlowered_call_instructions":
                whole_program_vm["target_coverage"]
                ["abi_unlowered_call_instruction_count"],
            "whole_program_vm_abi_eligible_call_sites":
                whole_program_vm["target_coverage"]
                ["abi_eligible_call_site_count"],
            "whole_program_vm_abi_lowered_call_sites":
                whole_program_vm["target_coverage"]
                ["abi_lowered_call_site_count"],
            "whole_program_vm_abi_unlowered_call_sites":
                whole_program_vm["target_coverage"]
                ["abi_unlowered_call_site_count"],
            "whole_program_vm_legacy_direct_call_instructions":
                whole_program_vm["call_abi_binding"]
                ["legacy_direct_call_instruction_count"],
            "whole_program_vm_legacy_direct_call_sites":
                whole_program_vm["call_abi_binding"]
                ["legacy_direct_call_site_count"],
            "whole_program_vm_abi_additional_direct_call_instructions":
                whole_program_vm["call_abi_binding"]
                ["additional_direct_call_instruction_count"],
            "whole_program_vm_guarded_finite_dispatch_instructions":
                whole_program_vm["call_abi_binding"]
                ["guarded_finite_dispatch_instruction_count"],
            "whole_program_vm_guarded_finite_dispatch_sites":
                whole_program_vm["call_abi_binding"]
                ["guarded_finite_dispatch_site_count"],
            "whole_program_vm_guarded_finite_bound_dispatch_instructions":
                whole_program_vm["call_abi_binding"]
                ["guarded_finite_bound_dispatch_instruction_count"],
            "whole_program_vm_guarded_finite_bound_dispatch_sites":
                whole_program_vm["call_abi_binding"]
                ["guarded_finite_bound_dispatch_site_count"],
            "whole_program_vm_abi_additional_fully_lowered_call_sites":
                whole_program_vm["call_abi_binding"]
                ["additional_fully_lowered_call_site_count"],
            "whole_program_vm_translated_symbols":
                len(vm_translated_symbols),
            "whole_program_vm_stack_bound_live": bool(
                whole_program_vm_stack_bound["live"]),
            "whole_program_vm_complete_stack_bound_proved": bool(
                whole_program_vm_stack_bound["complete_bound_proved"]),
            "whole_program_vm_arena_lower_bound_bytes":
                whole_program_vm_stack_bound["arena"]
                ["whole_program_arena_lower_bound_bytes"],
            "draw_ramdl_shadow_v4_live": bool(
                draw_ramdl_shadow_v4["live"]),
            "draw_ramdl_shadow_v4_active_words":
                draw_ramdl_shadow_v4["layout"]
                ["active_catalog_cyclic_words"],
            "draw_ramdl_shadow_v4_strict_word_limit":
                draw_ramdl_shadow_v4["layout"]["strict_limit_words"],
            "draw_ramdl_shadow_v4_scratch_bytes":
                draw_ramdl_shadow_v4["allocation"]
                ["target_struct_sizes_bytes"]["dedup_scratch"],
            "full_hqt3_inventory_complete": bool(
                full_hqt3_inventory["inventory_complete"]),
            "full_hqt3_inventory_live": bool(full_hqt3_inventory["live"]),
            "full_hqt3_template_count":
                full_hqt3_inventory["global_catalog"]["template_count"],
            "full_hqt3_load_scope_count":
                full_hqt3_inventory["load_plan"]["scope_storage"]
                ["scope_count"],
            "hqt3_ramg_scope_pack_proof_complete": bool(
                hqt3_ramg_schedule["scope_pack_proof_complete"]),
            "hqt3_ramg_schedule_live": bool(hqt3_ramg_schedule["live"]),
            "hqt3_ramg_isolated_fit_count":
                hqt3_ramg_schedule["scope_pack_census"]
                ["ram_g_isolated_fit_count"],
            "hqt3_ramg_isolated_nonfit_count":
                hqt3_ramg_schedule["scope_pack_census"]
                ["ram_g_isolated_nonfit_count"],
            "hqt3_event_correlation_exact_count":
                hqt3_ramg_schedule["event_transitions"]
                ["event_correlation_exact_count"],
            "hqt3_event_correlation_ambiguous_count":
                hqt3_ramg_schedule["event_transitions"]
                ["event_correlation_ambiguous_count"],
            "hqt3_partition_structural_proof_complete": bool(
                hqt3_partition_solver["structural_partition_proof_complete"]),
            "hqt3_partition_runtime_paging_complete": bool(
                hqt3_partition_solver["ram_g_runtime_paging_complete"]),
            "hqt3_partition_live": bool(hqt3_partition_solver["live"]),
            "hqt3_partition_problem_scope_count":
                hqt3_partition_solver["problem_scope_count"],
            "hqt3_partition_exact_event_count":
                hqt3_partition_solver["event_cost_census"]
                ["exact_event_count"],
            "hqt3_partition_ambiguous_event_count":
                hqt3_partition_solver["event_cost_census"]
                ["ambiguous_event_count"],
            "hqt3_frame_page_exact_frame_sets_proved": bool(
                hqt3_frame_page_solver["proof_boundaries"]
                ["exact_per_frame_page_sets_proved"]),
            "hqt3_frame_page_two_generation_fit_proved": bool(
                hqt3_frame_page_solver["proof_boundaries"]
                ["two_generation_ram_g_fit_proved"]),
            "hqt3_frame_page_upload_deadline_proved": bool(
                hqt3_frame_page_solver["proof_boundaries"]
                ["upload_deadline_proved"]),
            "hqt3_frame_page_live": bool(hqt3_frame_page_solver["live"]),
            "hqt3_bcab_union_ram_g_bytes":
                hqt3_frame_page_solver["exact_bcab_page_catalog"]
                ["union_ram_g_bytes"],
            "hqt3_bcab_union_ram_g_overflow_bytes":
                hqt3_frame_page_solver["exact_bcab_page_catalog"]
                ["union_ram_g_overflow_bytes"],
            "game_ram_dl_words": (
                frame_budget.get("report", {}).get("game", {}).get(
                    "word_count")
                if isinstance(frame_budget.get("report"), dict) else None),
            "game_worst_line_cycles": (
                frame_budget.get("report", {}).get("game", {}).get(
                    "worst_cycles")
                if isinstance(frame_budget.get("report"), dict) else None),
            "title_ram_dl_words": (
                frame_budget.get("report", {}).get("title", {}).get(
                    "word_count")
                if isinstance(frame_budget.get("report"), dict) else None),
            "title_worst_line_cycles": (
                frame_budget.get("report", {}).get("title", {}).get(
                    "worst_cycles")
                if isinstance(frame_budget.get("report"), dict) else None),
            "symbols": symbols,
        },
    }

    try:
        translation_checkpoint = write_translation_checkpoint(
            ROOT, OUT_TRANSLATION_CHECKPOINT)
    except TranslationCheckpointError as exc:
        raise TranslationError(
            f"cross-artifact checkpoint failed: {exc}") from exc
    if not translation_checkpoint.get("coherent"):
        issues = translation_checkpoint.get("issues", [])
        raise TranslationError(
            "cross-artifact checkpoint is incoherent: "
            f"{issues[:3] if isinstance(issues, list) else issues}")
    report["translation_checkpoint"] = {
        "path": _project_path(OUT_TRANSLATION_CHECKPOINT),
        "coherent": True,
        "issue_count": 0,
        "snapshot_sha256": translation_checkpoint["snapshot_sha256"],
        "semantic_sha256": translation_checkpoint["semantic_sha256"],
        "live_claim": False,
    }

    OUT_BLOB.parent.mkdir(parents=True, exist_ok=True)
    OUT_BLOB.write_bytes(blob)
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")
    OUT_SPRITE_WORKING_SET_STATUS.write_text(
        json.dumps(sprite_working_sets, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    OUT_FRAME_RENDER_PLAN_STATUS.write_text(
        json.dumps(frame_render_plan_report, ensure_ascii=False, indent=2) +
        "\n", encoding="utf-8", newline="\n")
    OUT_FRAME_RECORD_BOUND_STATUS.write_text(
        json.dumps(frame_record_bound_report, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    OUT_FRAME_RECORD_REACHABILITY_STATUS.write_text(
        json.dumps(frame_record_reachability_report, ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    _progress("generation transaction", stage_started)
    return report


def translate(
        require_complete: bool, *, jobs: int | None = None,
        ) -> dict[str, Any]:
    """Translate as one byte-exact generation across all owned artifacts."""
    global _PARALLEL_JOBS
    previous_jobs = _PARALLEL_JOBS
    _PARALLEL_JOBS = _normalise_parallel_jobs(jobs)
    try:
        with translation_generation_transaction(ROOT):
            return _translate_untransactional(require_complete)
    finally:
        _PARALLEL_JOBS = previous_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-complete", action="store_true",
        help="считать ошибкой любой reachable Python-символ со статусом pending",
    )
    parser.add_argument(
        "--jobs", type=int, default=None,
        help=("число CPU-процессов; по умолчанию все доступные "
              "логические CPU"),
    )
    arguments = parser.parse_args()
    try:
        report = translate(
            arguments.require_complete, jobs=arguments.jobs)
    except (OSError, SyntaxError, TranslationError, CompileError,
            AssetCompileError, SpriteCoverageError,
            SpriteWorkingSetError,
            DrawPlanCompileError, DrawCBackendError, DrawVMBackendError,
            GenerationTransactionError, FrameRecordBoundError,
            FrameRenderPlanError, FrameFragmentBudgetError,
            FrameSpriteFragmentEnvelopeError,
            RenderOrderBackendError, DrawTargetBundleError,
            MutationHookIRError, FunctionCFGError, ActiveCallGraphError,
            ActiveCallSiteLoweringError,
            ActiveTargetAdaptersError,
            FrameTimingProviderError,
            WholeProgramVMError,
            WholeProgramVMStackBoundError,
            WholeProgramVMCallABIError,
            TranslationCheckpointError,
            V4CheckError,
            FullHQT3InventoryError, HQT3RAMGScheduleError,
            HQT3PartitionSolverError, HQT3FramePageSolverError) as exc:
        print(f"ОШИБКА ТРАНСЛЯЦИИ PYTHON: {exc}")
        return 1
    coverage = report["coverage"]
    print(
        "Python AST -> TS-Config: "
        f"{coverage['compiled_z80']} compiled Z80, "
        f"{coverage['translated_lut']} LUT, "
        f"{coverage['pending']} pending, "
        f"working sets {report['sprite_working_sets']['status']}, "
        f"{report['target']['table_bytes']} байт, "
        f"fingerprint {report['source_fingerprint'][:16]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
