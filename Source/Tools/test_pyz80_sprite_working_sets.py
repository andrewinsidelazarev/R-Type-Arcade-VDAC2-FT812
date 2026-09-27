from __future__ import annotations

import ast
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pyz80_compiler.assets import CellBankSpec, CellKey, CellSourceKey
from pyz80_compiler.ft812_assets import (
    FT812AssetPackBudget,
    compile_ft812_cell_assets,
)
from pyz80_compiler.sprite_coverage import (
    ClassCoverageProvenance,
    CommonCoverageProvenance,
    CoverageReport,
    DescriptorRef,
    DescriptorResourcePair,
    EventCoverageProvenance,
    PythonBankKey,
    StageCoverageProvenance,
    _WorldRom,
    _force_beam_addresses,
    _force_body_addresses,
    _force_dart_addresses,
    _force_grid_addresses,
    _force_projectile_addresses,
    _force_ray_addresses,
    _pair as _coverage_pair,
)
from pyz80_compiler.sprite_working_sets import (
    SpriteWorkingSetError,
    audit_active_scheduler,
    audit_force_palette_epochs,
    cells_for_pairs,
    derive_sprite_domains,
    plan_sprite_working_sets,
)


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_ENEMIES = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
ACTIVE_FORCE = ROOT / "Source" / "Python" / "rtype_port" / "force.py"
ACTIVE_GAME = ROOT / "Source" / "Python" / "rtype_port" / "game.py"


def _pair(address: int, code: int, resource: int = 1,
          bank: int = 1, *, width: int = 1) -> DescriptorResourcePair:
    return DescriptorResourcePair(
        resource_type=resource,
        descriptor=DescriptorRef(
            address=address,
            dx=0,
            dy=0,
            code=code,
            attribute=0,
            width=width,
            height=1,
            flip_x=False,
            flip_y=False,
        ),
        bank_keys=(PythonBankKey("typed-resource", bank),),
    )


def _report(*, stage1_commands: tuple[int, ...] = (0x0200, 0x0200),
            enemies_sha256: str = "active-enemies") -> CoverageReport:
    common_pair = _pair(0x1000, 0)
    common_cells = cells_for_pairs((common_pair,))
    per_stage: list[tuple[int, tuple[DescriptorResourcePair, ...]]] = []
    provenance: list[StageCoverageProvenance] = []
    for stage in range(1, 9):
        pair = _pair(0x1100 + stage * 6, stage)
        pairs = (pair,)
        commands = stage1_commands if stage == 1 else (0x0200 + stage,)
        events = tuple(
            EventCoverageProvenance(
                address=0x2000 + stage * 0x100 + index * 4,
                threshold=stage * 0x100 + index,
                command=command,
                handler=0x596D,
                classes=("SyntheticEnemy",),
            )
            for index, command in enumerate(commands)
        )
        class_coverage = ClassCoverageProvenance(
            class_name="SyntheticEnemy",
            relation_kind="synthetic-exact-relation",
            selector_sources=("SyntheticEnemy.update:descriptor",),
            constructor_parameters=(("command", tuple(sorted(set(commands)))),),
            pairs=pairs,
            owned_descriptor_sinks=("SyntheticEnemy.update:1:descriptor",),
            owned_resource_sinks=("SyntheticEnemy.__init__:1:palette",),
        )
        per_stage.append((stage, pairs))
        provenance.append(StageCoverageProvenance(
            stage=stage,
            event_first=events[0].address,
            event_last=events[-1].address,
            event_count=len(events),
            event_sha256=f"stage-{stage}",
            pair_count=1,
            cell_count=len(cells_for_pairs(pairs)),
            resource_bank_domains=((1, (PythonBankKey(
                "typed-resource", 1),)),),
            handler_counts=((0x596D, len(events)),),
            handler_classes=((0x596D, ("SyntheticEnemy",)),),
            events=events,
            class_coverage=(class_coverage,),
            owned_handlers=(0x596D,),
            owned_classes=("SyntheticEnemy",),
            owned_descriptor_sinks=("SyntheticEnemy.update:1:descriptor",),
        ))
    return CoverageReport(
        root_module="rtype_port.app",
        reachable_modules=("rtype_port.app", "rtype_port.enemies"),
        source_hashes=(("rtype_port.enemies", enemies_sha256),),
        rom_sha256="synthetic-rom",
        owned_sink_ids=("rtype_port.enemies:SyntheticEnemy.draw",),
        domain_counts=(("synthetic", 1),),
        selector_facts=(),
        common_domain_pairs=(("synthetic-common", (common_pair,)),),
        common_provenance=(CommonCoverageProvenance(
            domain="synthetic-common",
            resource_type=1,
            pair_count=1,
            cell_count=len(common_cells),
            bank_keys=(PythonBankKey("typed-resource", 1),),
            source_symbols=("synthetic.common",),
            owned_sink_ids=("rtype_port.enemies:SyntheticEnemy.draw",),
        ),),
        common_pairs=(common_pair,),
        common_cell_count=len(common_cells),
        per_stage_pairs=tuple(per_stage),
        stage_provenance=tuple(provenance),
        unresolved_domains=(),
    )


def _synthetic_force_domains() -> dict[
        str, tuple[DescriptorResourcePair, ...]]:
    counts = {
        "force_body": 31,
        "force_projectiles": 5,
        "force_beams": 192,
        "force_darts": 15,
        "force_grids": 11,
        "force_rays": 16,
    }
    fallback = tuple(
        PythonBankKey("palette-fallback", slot) for slot in range(16))
    result: dict[str, tuple[DescriptorResourcePair, ...]] = {}
    address = 0x3000
    code = 0
    for name, count in counts.items():
        if name == "force_body":
            resource = 0x56
            banks = (PythonBankKey("typed-resource", 0x56),)
        elif name == "force_projectiles":
            resource = 0x02
            banks = (PythonBankKey("typed-resource", 0x02),)
        else:
            resource = 0x3D
            banks = fallback
        pairs: list[DescriptorResourcePair] = []
        for _index in range(count):
            pairs.append(DescriptorResourcePair(
                resource_type=resource,
                descriptor=DescriptorRef(
                    address=address,
                    dx=0,
                    dy=0,
                    code=code,
                    attribute=0,
                    width=1,
                    height=1,
                    flip_x=False,
                    flip_y=False,
                ),
                bank_keys=banks,
            ))
            address += 6
            code += 1
        result[name] = tuple(pairs)
    return result


def _active_force_domains() -> dict[
        str, tuple[DescriptorResourcePair, ...]]:
    force_tree = ast.parse(ACTIVE_FORCE.read_text(encoding="utf-8"))
    rom = _WorldRom((
        ROOT / "Assets" / "Converted" / "Arcade" /
        "RTYPE_MAINCPU_REGION.bin").read_bytes())
    rays = _force_ray_addresses(force_tree, rom)[0]
    addresses = {
        "force_body": (0x56, _force_body_addresses(force_tree, rom)),
        "force_projectiles": (0x02, _force_projectile_addresses(force_tree)),
        "force_beams": (0x3D, _force_beam_addresses(force_tree)),
        "force_darts": (0x3D, _force_dart_addresses(force_tree)),
        "force_grids": (0x3D, _force_grid_addresses(force_tree)),
        "force_rays": (0x3D, rays),
    }
    return {
        name: tuple(sorted(
            _coverage_pair(ROOT, rom, resource, address)
            for address in descriptor_addresses
        ))
        for name, (resource, descriptor_addresses) in addresses.items()
    }


def _active_force_report() -> CoverageReport:
    enemies_text = ACTIVE_ENEMIES.read_text(encoding="utf-8")
    force_text = ACTIVE_FORCE.read_text(encoding="utf-8")
    game_text = ACTIVE_GAME.read_text(encoding="utf-8")
    base = _report(enemies_sha256=hashlib.sha256(
        enemies_text.encode("utf-8")).hexdigest())
    force_domains = _active_force_domains()
    domains = dict(base.common_domain_pairs)
    domains.update(force_domains)
    provenance = {item.domain: item for item in base.common_provenance}
    for name, pairs in force_domains.items():
        provenance[name] = CommonCoverageProvenance(
            domain=name,
            resource_type=pairs[0].resource_type,
            pair_count=len(pairs),
            cell_count=len(cells_for_pairs(pairs)),
            bank_keys=tuple(sorted({
                bank for pair in pairs for bank in pair.bank_keys
            })),
            source_symbols=(f"rtype_port.force.{name}",),
            owned_sink_ids=("rtype_port.force:Force.draw",),
        )
    common_pairs = tuple(sorted({
        pair for pairs in domains.values() for pair in pairs
    }))
    return replace(
        base,
        reachable_modules=(
            "rtype_port.app", "rtype_port.enemies", "rtype_port.force",
            "rtype_port.game",
        ),
        source_hashes=tuple(sorted((
            ("rtype_port.enemies", hashlib.sha256(
                enemies_text.encode("utf-8")).hexdigest()),
            ("rtype_port.force", hashlib.sha256(
                force_text.encode("utf-8")).hexdigest()),
            ("rtype_port.game", hashlib.sha256(
                game_text.encode("utf-8")).hexdigest()),
        ))),
        common_domain_pairs=tuple(sorted(domains.items())),
        common_provenance=tuple(
            provenance[name] for name in sorted(provenance)),
        common_pairs=common_pairs,
        common_cell_count=len(cells_for_pairs(common_pairs)),
    )


class SpriteWorkingSetTests(unittest.TestCase):
    def test_pair_expansion_preserves_resource_relation(self) -> None:
        left = _pair(0x1000, 0, resource=0x10, bank=0x10, width=2)
        right = _pair(0x1006, 0x20, resource=0x20, bank=0x20)
        cells = set(cells_for_pairs((left, right)))
        self.assertIn(
            ("typed-resource", 0x10, 0),
            {(cell.bank.kind, cell.bank.value, cell.code) for cell in cells})
        self.assertIn(
            ("typed-resource", 0x10, 8),
            {(cell.bank.kind, cell.bank.value, cell.code) for cell in cells})
        self.assertIn(
            ("typed-resource", 0x20, 0x20),
            {(cell.bank.kind, cell.bank.value, cell.code) for cell in cells})
        # These are exactly the false edges a descriptor/resource product
        # would invent.
        self.assertNotIn(
            ("typed-resource", 0x20, 0),
            {(cell.bank.kind, cell.bank.value, cell.code) for cell in cells})
        self.assertNotIn(
            ("typed-resource", 0x10, 0x20),
            {(cell.bank.kind, cell.bank.value, cell.code) for cell in cells})

    def test_identical_event_packs_are_deduplicable(self) -> None:
        _common, _classes, events, _ambient = derive_sprite_domains(_report())
        stage1 = [event for event in events if event.stage == 1]
        self.assertEqual(len(stage1), 2)
        self.assertEqual(stage1[0].pack_id, stage1[1].pack_id)
        self.assertTrue(all(event.correlation_exact for event in stage1))

    def test_reused_class_with_different_command_blocks_exact_event_split(
            self) -> None:
        _common, _classes, events, _ambient = derive_sprite_domains(
            _report(stage1_commands=(0x0200, 0x0400)))
        stage1 = [event for event in events if event.stage == 1]
        self.assertTrue(all(not event.correlation_exact for event in stage1))
        self.assertEqual(
            {event.ambiguous_classes for event in stage1},
            {("SyntheticEnemy",)},
        )

    def test_scheduler_audit_is_fail_closed_on_second_dispatch(self) -> None:
        source = ACTIVE_ENEMIES.read_text(encoding="utf-8")
        proof = audit_active_scheduler(source)
        self.assertEqual(proof.object_pool_slots, 96)
        self.assertEqual(proof.initially_allocatable_slots, 94)
        self.assertTrue(proof.retains_live_objects_across_updates)
        mutated = source.replace(
            "            self._dispatch(event)\n",
            "            self._dispatch(event)\n"
            "            self._dispatch(event)\n",
            1,
        )
        self.assertNotEqual(source, mutated)
        with self.assertRaisesRegex(
                SpriteWorkingSetError, "one _dispatch"):
            audit_active_scheduler(mutated)

    def test_force_palette_epoch_is_source_bound_and_mutation_fails_closed(
            self) -> None:
        force_source = ACTIVE_FORCE.read_text(encoding="utf-8")
        game_source = ACTIVE_GAME.read_text(encoding="utf-8")
        enemies_source = ACTIVE_ENEMIES.read_text(encoding="utf-8")
        domains = _synthetic_force_domains()
        first = audit_force_palette_epochs(
            force_source, game_source, enemies_source, domains)
        second = audit_force_palette_epochs(
            force_source, game_source, enemies_source, domains)
        self.assertEqual(first.evidence_sha256, second.evidence_sha256)
        self.assertEqual(len(first.candidates), 16)
        self.assertEqual(
            first.coexisting_domain_ids,
            (
                "common:force_body", "common:force_projectiles",
                "common:force_beams", "common:force_darts",
                "common:force_grids", "common:force_rays",
            ),
        )
        for slot, candidate in enumerate(first.candidates):
            self.assertEqual(candidate.palette_slot, slot)
            self.assertEqual(candidate.pair_count, 234)
            self.assertEqual(
                {(cell.bank.kind, cell.bank.value)
                 for cell in candidate.cells},
                {("palette-fallback", slot)},
            )

        mutated = force_source.replace(
            "segment.resource_slot = acquire(0x3D)",
            "segment.resource_slot = acquire(0x3E)",
            1,
        )
        self.assertNotEqual(force_source, mutated)
        with self.assertRaisesRegex(
                SpriteWorkingSetError, r"acquire\(0x3D\) invariant"):
            audit_force_palette_epochs(
                mutated, game_source, enemies_source, domains)

    def test_force_palette_epoch_rejects_stale_coverage_hash(self) -> None:
        report = _active_force_report()
        hashes = dict(report.source_hashes)
        hashes["rtype_port.force"] = "0" * 64
        stale = replace(report, source_hashes=tuple(sorted(hashes.items())))
        with self.assertRaisesRegex(
                SpriteWorkingSetError,
                "stale for active rtype_port.force"):
            plan_sprite_working_sets(stale, ROOT)

    def test_active_force_epoch_replaces_false_palette_union_exactly(
            self) -> None:
        report = _active_force_report()
        plan = plan_sprite_working_sets(report, ROOT)
        proof = plan.force_palette_epoch
        self.assertIsNotNone(proof)
        assert proof is not None
        self.assertEqual(len(proof.candidates), 16)
        self.assertTrue(all(len(item.cells) == 445
                            for item in proof.candidates))
        self.assertEqual(plan.proven_resident_combinations, ())
        self.assertEqual(
            {item.code for item in plan.missing_invariants},
            {"PZSW102", "PZSW103", "PZSW104"},
        )

        payload = plan.as_dict()
        epoch = payload["force_palette_epoch"]
        assert isinstance(epoch, dict)
        self.assertTrue(epoch["at_most_one_live_epoch"])
        self.assertFalse(epoch["resident_combination_claimed"])
        self.assertEqual(epoch["candidate_count"], 16)
        self.assertEqual(epoch["exact_max_ft812_bytes"], 268368)
        self.assertLessEqual(epoch["exact_max_ft812_bytes"], 268368)

        measured_ids = {
            item.pack_id for item in plan.unique_pack_measurements
        }
        replaced = set(proof.epoch_source_domain_ids)
        for domain in plan.common_domains:
            if domain.domain_id in replaced:
                self.assertNotIn(domain.pack_id, measured_ids)
        self.assertTrue(all(candidate.pack_id in measured_ids
                            for candidate in proof.candidates))

    def test_ft812_measurement_is_backend_exact_and_plan_stays_blocked(
            self) -> None:
        source_text = ACTIVE_ENEMIES.read_text(encoding="utf-8")
        source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        report = _report(enemies_sha256=source_sha)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            enemy_path = root / "Source" / "Python" / "rtype_port" / "enemies.py"
            enemy_path.parent.mkdir(parents=True)
            enemy_path.write_text(source_text, encoding="utf-8")
            bank_path = root / "Assets" / "Converted" / "Arcade" / \
                "ResourceHQ" / "RTYPE_SPRITES_TYPE01_HQ_ARGB4444.bin"
            bank_path.parent.mkdir(parents=True)
            width, height, count = 27, 30, 32
            cell_payloads = []
            for index in range(count):
                word = (0xF000 | index).to_bytes(2, "little")
                cell_payloads.append(word * (width * height))
            bank_path.write_bytes(b"".join(cell_payloads))

            plan = plan_sprite_working_sets(report, root)
            self.assertFalse(plan.ready)
            self.assertEqual(plan.proven_resident_combinations, ())
            self.assertEqual(
                {item.code for item in plan.missing_invariants},
                {"PZSW102", "PZSW103", "PZSW104"},
            )
            event = next(item for item in plan.event_packs if item.stage == 1)
            measured = {
                item.pack_id: item for item in plan.unique_pack_measurements
            }[event.pack_id]

            source_key = CellSourceKey("sprite", "type01")
            direct = compile_ft812_cell_assets(
                [CellKey(source_key, 1)],
                [CellBankSpec(source_key, bank_path, width, height, count)],
                FT812AssetPackBudget(1, 1, 1, 4096, 4),
                project_root=root,
            )
            self.assertEqual(measured.ft812_bytes, len(direct.data))
            self.assertEqual(measured.blob_sha256, direct.sha256)
            self.assertEqual(measured.raw_argb4444_bytes,
                             direct.raw_argb4444_bytes)

    def test_coverage_class_union_mutation_fails_closed(self) -> None:
        report = _report()
        stage = report.stage_provenance[0]
        broken_stage = replace(stage, class_coverage=())
        broken = replace(
            report,
            stage_provenance=(broken_stage, *report.stage_provenance[1:]),
        )
        with self.assertRaisesRegex(
                SpriteWorkingSetError, "class ownership"):
            derive_sprite_domains(broken)


if __name__ == "__main__":
    unittest.main()
