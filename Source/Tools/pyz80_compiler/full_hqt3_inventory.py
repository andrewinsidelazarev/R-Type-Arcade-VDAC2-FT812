"""Complete source-derived HQT3 template inventory for the active Python game.

The existing ``preload_80e3`` asset is a useful Stage-1 warm-up cache, but it
is not a semantic sprite manifest.  This module starts from the exact
``DescriptorResourcePair`` relation proved by :mod:`sprite_coverage` and
builds every concrete ``(Python bank, ROM descriptor)`` resolver key.

The output deliberately separates three different facts which must not be
collapsed by a target adapter:

* the global content-addressed template catalogue is complete;
* common domains, Force palette epochs, and per-stage classes are loadable
  catalogue scopes, not simultaneous RAM_G residency claims;
* upload/eviction order and the physical HQT3 bitmap-state table remain
  blocked until lifetime and placement proofs exist.

Thus this module can remove the false 40-template ceiling without replacing
it with the equally false assertion that all reachable sprites are resident.
"""

from __future__ import annotations

import ast
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .sprite_coverage import (
    ACTIVE_ROOT_MODULE,
    CoverageReport,
    DescriptorRef,
    DescriptorResourcePair,
    PythonBankKey,
    resolve_python_bank,
)
from .sprite_working_sets import (
    FORCE_P3D_DOMAIN_NAMES,
    FORCE_P3D_RESOURCE_TYPE,
    SpriteCellRef,
    SpriteWorkingSetError,
    audit_force_palette_epochs,
    cells_for_pairs,
    derive_sprite_domains,
)


FULL_HQT3_INVENTORY_FORMAT = "pyz80-full-hqt3-template-inventory-v1"
FULL_HQT3_INVENTORY_STATUS = (
    "COMPLETE_TEMPLATE_CATALOG_LOAD_TRANSITIONS_BLOCKED")

HQT3_HEADER_BYTES = 20
HQT3_RECORD_STRUCT_FORMAT = "<HBBHhhHBBHH"
HQT3_RECORD_BYTES = struct.calcsize(HQT3_RECORD_STRUCT_FORMAT)
HQT3_STATE_BYTES = 8
HQT3_CELL_BYTES = 9
HQT3_MAX_RECORDS = 0xFFFF
HQT3_MAX_CELLS = 0xFFFF
HQT3_MAX_STATES = 0x100


class FullHQT3InventoryError(ValueError):
    """The source relation cannot be represented without guessing."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha256_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise FullHQT3InventoryError(
            f"cannot hash active sprite source {path}: {exc}") from exc
    return digest.hexdigest()


def encode_bank_key(bank: PythonBankKey) -> int:
    """Encode the exact active ``M72SpriteAtlas._asset`` identity."""
    if bank.kind == "typed-resource" and 0 <= bank.value <= 0xFF:
        return 0x100 | bank.value
    if bank.kind == "palette-fallback" and 0 <= bank.value <= 0x0F:
        return bank.value
    raise FullHQT3InventoryError(f"invalid active Python bank key: {bank!r}")


def _bank_dict(bank: PythonBankKey) -> dict[str, object]:
    return {
        "kind": bank.kind,
        "value": bank.value,
        "encoded_hqt3_key": encode_bank_key(bank),
    }


def _descriptor_row(descriptor: DescriptorRef) -> dict[str, object]:
    return {
        "address": descriptor.address,
        "dx": descriptor.dx,
        "dy": descriptor.dy,
        "code": descriptor.code,
        "attribute": descriptor.attribute,
        "width": descriptor.width,
        "height": descriptor.height,
        "flip_x": descriptor.flip_x,
        "flip_y": descriptor.flip_y,
    }


def _pair_row(pair: DescriptorResourcePair) -> dict[str, object]:
    return {
        "resource_type": pair.resource_type,
        "descriptor": _descriptor_row(pair.descriptor),
        "banks": [_bank_dict(bank) for bank in pair.bank_keys],
    }


def relation_sha256(pairs: Iterable[DescriptorResourcePair]) -> str:
    return _sha256_value([
        _pair_row(pair) for pair in sorted(set(pairs))
    ])


def _working_set_pair_sha256(
        pairs: Iterable[DescriptorResourcePair],
        ) -> str:
    """Reproduce the source-bound digest carried by Force epoch evidence."""
    rows: list[str] = []
    for pair in sorted(set(pairs)):
        descriptor = pair.descriptor
        banks = ",".join(
            f"{bank.kind}:{bank.value:02X}" for bank in pair.bank_keys)
        rows.append(
            f"{pair.resource_type:02X}:{descriptor.address:04X}:"
            f"{descriptor.dx}:{descriptor.dy}:{descriptor.code:04X}:"
            f"{descriptor.attribute:04X}:{descriptor.width}x{descriptor.height}:"
            f"{int(descriptor.flip_x)}{int(descriptor.flip_y)}:{banks}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _template_cell_rows(
        bank: PythonBankKey, descriptor: DescriptorRef,
        ) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for cell_x in range(descriptor.width):
        for cell_y in range(descriptor.height):
            source_x = (descriptor.width - 1 - cell_x
                        if descriptor.flip_x else cell_x)
            source_y = (descriptor.height - 1 - cell_y
                        if descriptor.flip_y else cell_y)
            rows.append({
                "bank": _bank_dict(bank),
                "code": (
                    descriptor.code + 8 * source_x + source_y) & 0x0FFF,
                "flip_x": descriptor.flip_x,
                "flip_y": descriptor.flip_y,
                "cell_x": cell_x,
                "cell_y": cell_y,
            })
    return tuple(rows)


@dataclass(frozen=True)
class ConcreteTemplate:
    """One immutable HQT resolver key and all exact resource aliases."""

    bank: PythonBankKey
    descriptor: DescriptorRef
    resource_types: tuple[int, ...]

    @property
    def key(self) -> tuple[PythonBankKey, int]:
        return self.bank, self.descriptor.address

    @property
    def key_id(self) -> str:
        return (
            f"hqt3:{encode_bank_key(self.bank):04X}:"
            f"{self.descriptor.address:04X}")

    @property
    def cell_rows(self) -> tuple[dict[str, object], ...]:
        return _template_cell_rows(self.bank, self.descriptor)

    @property
    def cell_count(self) -> int:
        return self.descriptor.width * self.descriptor.height

    def semantic_row(self) -> dict[str, object]:
        cells = self.cell_rows
        return {
            "key_id": self.key_id,
            "bank": _bank_dict(self.bank),
            "descriptor": _descriptor_row(self.descriptor),
            "resource_types": list(self.resource_types),
            "resource_hint": self.resource_types[0],
            "resource_hint_is_semantic": False,
            "resource_alias_count": len(self.resource_types),
            "cell_count": self.cell_count,
            "cell_sequence_sha256": _sha256_value(cells),
            # A self-contained appended cell needs at most layout, palette,
            # source and vertex words.  This is a safe source-only envelope;
            # the packed HQT3 generator may prove a smaller exact value.
            "append_words_conservative_max": 4 * self.cell_count,
        }


def concrete_templates_for_pairs(
        pairs: Iterable[DescriptorResourcePair],
        ) -> tuple[ConcreteTemplate, ...]:
    """Collapse only exact resolver-key aliases, never relation products."""
    owners: dict[
        tuple[PythonBankKey, int], tuple[DescriptorRef, set[int]],
    ] = {}
    for pair in sorted(set(pairs)):
        if not 0 <= pair.resource_type <= 0xFF:
            raise FullHQT3InventoryError("resource type is not uint8")
        if not pair.bank_keys:
            raise FullHQT3InventoryError(
                f"descriptor ${pair.descriptor.address:04X} has no bank")
        for bank in pair.bank_keys:
            encode_bank_key(bank)
            key = (bank, pair.descriptor.address)
            previous = owners.get(key)
            if previous is None:
                owners[key] = (pair.descriptor, {pair.resource_type})
            else:
                descriptor, resources = previous
                if descriptor != pair.descriptor:
                    raise FullHQT3InventoryError(
                        "one HQT resolver key decoded to different ROM "
                        f"descriptors: {bank!r}/${pair.descriptor.address:04X}")
                resources.add(pair.resource_type)
    return tuple(sorted(
        (
            ConcreteTemplate(bank, descriptor, tuple(sorted(resources)))
            for (bank, _address), (descriptor, resources) in owners.items()
        ),
        key=lambda item: (encode_bank_key(item.bank), item.descriptor.address),
    ))


def fixed_hqt3_bytes(templates: Iterable[ConcreteTemplate]) -> dict[str, int]:
    """Return exact HQT3 bytes independent of RAM_G state placement."""
    records = tuple(templates)
    cells = sum(item.cell_count for item in records)
    if len(records) > HQT3_MAX_RECORDS:
        raise FullHQT3InventoryError(
            f"HQT3 record count {len(records)} exceeds uint16")
    if cells > HQT3_MAX_CELLS:
        raise FullHQT3InventoryError(
            f"HQT3 cell count {cells} exceeds uint16")
    fixed = (
        HQT3_HEADER_BYTES + HQT3_RECORD_BYTES * len(records) +
        HQT3_CELL_BYTES * cells)
    return {
        "header_bytes": HQT3_HEADER_BYTES,
        "record_count": len(records),
        "record_bytes": HQT3_RECORD_BYTES * len(records),
        "cell_count": cells,
        "cell_bytes": HQT3_CELL_BYTES * cells,
        "fixed_bytes_excluding_state_table": fixed,
        "state_record_bytes": HQT3_STATE_BYTES,
    }


def _source_path(root: Path, module: str) -> Path:
    if not module.startswith("rtype_port."):
        raise FullHQT3InventoryError(
            f"active source module is outside rtype_port: {module!r}")
    return root / "Source" / "Python" / Path(
        *module.split(".")).with_suffix(".py")


def _bound_source_text(
        root: Path, report: CoverageReport, module: str,
        ) -> tuple[str, str]:
    path = _source_path(root, module)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FullHQT3InventoryError(
            f"cannot read active source {path}: {exc}") from exc
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if dict(report.source_hashes).get(module) != digest:
        raise FullHQT3InventoryError(
            f"CoverageReport is stale for active {module}")
    return text, digest


def _class_method(
        tree: ast.Module, class_name: str, method_name: str,
        ) -> ast.FunctionDef:
    classes = [
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == class_name
    ]
    if len(classes) != 1:
        raise FullHQT3InventoryError(
            f"active class {class_name} is missing or duplicated")
    methods = [
        item for item in classes[0].body
        if isinstance(item, ast.FunctionDef) and item.name == method_name
    ]
    if len(methods) != 1:
        raise FullHQT3InventoryError(
            f"active method {class_name}.{method_name} is missing or duplicated")
    return methods[0]


def _module_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    functions = [
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    ]
    if len(functions) != 1:
        raise FullHQT3InventoryError(
            f"active function {name} is missing or duplicated")
    return functions[0]


def _ast_sha256(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(
        node, include_attributes=False).encode("utf-8")).hexdigest()


def _literal_int(tree: ast.Module, name: str) -> int:
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                isinstance(node.targets[0], ast.Name) and
                node.targets[0].id == name):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError) as exc:
                raise FullHQT3InventoryError(
                    f"active {name} is not a literal") from exc
            if isinstance(value, int) and value > 0:
                return value
    raise FullHQT3InventoryError(f"active literal {name} is missing")


def _validate_read_descriptor_ast(tree: ast.Module) -> str:
    function = _module_function(tree, "read_descriptor")
    returns = [item for item in function.body if isinstance(item, ast.Return)]
    if len(returns) != 1 or returns[0].value is None:
        raise FullHQT3InventoryError(
            "active read_descriptor no longer has one direct return")
    expected = ast.parse(
        "SpriteDescriptor(_s8(rom.byte(address)), "
        "_s8(rom.byte(address + 1)), rom.word(address + 2), "
        "rom.word(address + 4))",
        mode="eval",
    ).body
    if ast.dump(returns[0].value, include_attributes=False) != ast.dump(
            expected, include_attributes=False):
        raise FullHQT3InventoryError(
            "active read_descriptor formula changed without an inventory "
            "decoder model")
    return _ast_sha256(function)


def _decode_descriptor(rom: bytes, address: int) -> DescriptorRef:
    if len(rom) != 0x100000:
        raise FullHQT3InventoryError(
            f"active World ROM size is {len(rom)}, expected 1048576")
    address &= 0xFFFF
    base = 0x10000 + address
    dx = rom[base]
    dy = rom[base + 1]
    dx = dx - 0x100 if dx & 0x80 else dx
    dy = dy - 0x100 if dy & 0x80 else dy
    code = int.from_bytes(rom[base + 2:base + 4], "little")
    attribute = int.from_bytes(rom[base + 4:base + 6], "little")
    return DescriptorRef(
        address=address,
        dx=dx,
        dy=dy,
        code=code,
        attribute=attribute,
        width=1 << ((attribute >> 14) & 3),
        height=1 << ((attribute >> 12) & 3),
        flip_x=bool(attribute & 0x0800),
        flip_y=bool(attribute & 0x0400),
    )


def validate_descriptor_witnesses(
        rom: bytes, descriptors: Iterable[DescriptorRef],
        ) -> dict[str, object]:
    unique: dict[int, DescriptorRef] = {}
    rows: list[dict[str, object]] = []
    for expected in sorted(set(descriptors)):
        previous = unique.get(expected.address)
        if previous is not None and previous != expected:
            raise FullHQT3InventoryError(
                f"ROM descriptor ${expected.address:04X} has two values")
        unique[expected.address] = expected
    for address, expected in sorted(unique.items()):
        actual = _decode_descriptor(rom, address)
        if actual != expected:
            raise FullHQT3InventoryError(
                f"coverage descriptor ${address:04X} differs from active ROM")
        rows.append(_descriptor_row(actual))
    return {
        "descriptor_count": len(rows),
        "descriptor_rows_sha256": _sha256_value(rows),
        "first_witnesses": rows[:8],
        "last_witnesses": rows[-8:],
    }


def _asset_path(root: Path, bank: PythonBankKey) -> Path:
    arcade = root / "Assets" / "Converted" / "Arcade"
    if bank.kind == "typed-resource":
        return arcade / "ResourceHQ" / (
            f"RTYPE_SPRITES_TYPE{bank.value:02X}_HQ_ARGB4444.bin")
    if bank.kind == "palette-fallback":
        return arcade / "FullHQ" / (
            f"RTYPE_SPRITES_PAL{bank.value:02X}_HQ_ARGB4444.bin")
    raise FullHQT3InventoryError(f"unknown bank {bank!r}")


def _asset_witnesses(
        root: Path, report: CoverageReport,
        pairs: Sequence[DescriptorResourcePair], cell_bytes: int,
        ) -> dict[str, object]:
    resolution_rows: set[tuple[int, int, str, int]] = set()
    used_banks: set[PythonBankKey] = set()
    for pair in pairs:
        resolved = tuple(sorted({
            resolve_python_bank(root, palette, pair.resource_type)
            for palette in range(16)
        }))
        if resolved != pair.bank_keys:
            raise FullHQT3InventoryError(
                "CoverageReport bank relation differs from active _asset for "
                f"resource ${pair.resource_type:02X}/descriptor "
                f"${pair.descriptor.address:04X}")
        for palette in range(16):
            bank = resolve_python_bank(root, palette, pair.resource_type)
            resolution_rows.add((
                pair.resource_type, palette, bank.kind, bank.value))
        used_banks.update(pair.bank_keys)

    files: list[dict[str, object]] = []
    expected_size = 4096 * cell_bytes
    for bank in sorted(used_banks):
        path = _asset_path(root, bank)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise FullHQT3InventoryError(
                f"active sprite bank is unavailable: {path}: {exc}") from exc
        if size != expected_size:
            raise FullHQT3InventoryError(
                f"active sprite bank has size {size}, expected "
                f"{expected_size}: {path}")
        files.append({
            "bank": _bank_dict(bank),
            "path": path.resolve().relative_to(root).as_posix(),
            "size": size,
            "sha256": _sha256_file(path),
        })
    resolution_payload = [
        {
            "resource_type": resource,
            "palette": palette,
            "bank_kind": kind,
            "bank_value": value,
        }
        for resource, palette, kind, value in sorted(resolution_rows)
    ]
    return {
        "asset_resolution_witness_count": len(resolution_payload),
        "asset_resolution_sha256": _sha256_value(resolution_payload),
        "asset_resolution_first_witnesses": resolution_payload[:16],
        "used_bank_count": len(files),
        "used_bank_source_bytes": sum(int(item["size"]) for item in files),
        "used_bank_files_sha256": _sha256_value(files),
        "used_bank_files": files,
        "coverage_source_binding_sha256": _sha256_value({
            "root_module": report.root_module,
            "source_hashes": list(report.source_hashes),
            "rom_sha256": report.rom_sha256,
        }),
    }


def _narrow_force_pairs(
        common_pairs: Mapping[str, tuple[DescriptorResourcePair, ...]],
        slot: int,
        ) -> tuple[DescriptorResourcePair, ...]:
    bank = PythonBankKey("palette-fallback", slot)
    source = {
        pair
        for name in FORCE_P3D_DOMAIN_NAMES
        for pair in common_pairs[name]
    }
    return tuple(sorted(
        DescriptorResourcePair(
            resource_type=pair.resource_type,
            descriptor=pair.descriptor,
            bank_keys=(bank,),
        )
        for pair in source
    ))


def _scope_report(
        scope_id: str, kind: str, pairs: Sequence[DescriptorResourcePair],
        template_index: Mapping[tuple[PythonBankKey, int], int],
        cell_bytes: int, *, stage: int | None = None,
        class_name: str | None = None, source_symbols: Sequence[str] = (),
        ) -> dict[str, object]:
    templates = concrete_templates_for_pairs(pairs)
    indices = tuple(template_index[item.key] for item in templates)
    cells = cells_for_pairs(pairs)
    fixed = fixed_hqt3_bytes(templates)
    return {
        "scope_id": scope_id,
        "kind": kind,
        "stage": stage,
        "class_name": class_name,
        "source_symbols": list(source_symbols),
        "pair_count": len(set(pairs)),
        "pair_relation_sha256": relation_sha256(pairs),
        "template_count": len(templates),
        "template_indices": list(indices),
        "template_indices_sha256": _sha256_value(list(indices)),
        "template_cell_reference_count": sum(
            item.cell_count for item in templates),
        "unique_logical_cell_count": len(cells),
        "selected_argb4444_bytes": len(cells) * cell_bytes,
        "hqt3_fixed_layout": fixed,
        "pixel_pack_id": "sprite-" + hashlib.sha256(
            "\n".join(cell.stable_name for cell in cells).encode("utf-8")
        ).hexdigest()[:24],
        "residency_claimed": False,
        "load_role": "catalogue-scope-awaiting-lifetime-transition-proof",
    }


def _current_bootstrap_report(
        root: Path, manifest_path: Path,
        full_index: Mapping[tuple[int, int], int],
        ) -> dict[str, object]:
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullHQT3InventoryError(
            f"cannot read current asset manifest {manifest_path}: {exc}") from exc
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise FullHQT3InventoryError("asset manifest has no artifacts list")
    sprite = [
        item for item in artifacts
        if isinstance(item, dict) and
        item.get("kind") == "sprite-bootstrap-working-set"
    ]
    if len(sprite) != 1:
        raise FullHQT3InventoryError(
            "asset manifest must contain one sprite bootstrap artifact")
    templates = sprite[0].get("templates")
    if not isinstance(templates, dict) or not isinstance(
            templates.get("records"), list):
        raise FullHQT3InventoryError(
            "sprite bootstrap artifact has no HQT3 records")
    keys: list[tuple[int, int]] = []
    for record in templates["records"]:
        if not isinstance(record, dict):
            raise FullHQT3InventoryError("current HQT3 record is not an object")
        try:
            key = (int(record["bank_key"]),
                   int(record["descriptor_address"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise FullHQT3InventoryError(
                "current HQT3 record key is malformed") from exc
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise FullHQT3InventoryError("current HQT3 contains duplicate keys")
    unknown = sorted(set(keys) - set(full_index))
    covered = sorted(set(keys) & set(full_index))
    binary_relative = templates.get("path")
    if not isinstance(binary_relative, str):
        raise FullHQT3InventoryError("current HQT3 path is missing")
    binary_path = root / binary_relative
    binary_sha = _sha256_file(binary_path)
    if templates.get("sha256") != binary_sha:
        raise FullHQT3InventoryError("current HQT3 binary hash is stale")
    full_count = len(full_index)
    return {
        "manifest_path": manifest_path.resolve().relative_to(root).as_posix(),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "hqt3_path": binary_relative,
        "hqt3_sha256": binary_sha,
        "hqt3_size": int(templates.get("size", -1)),
        "record_count": len(keys),
        "record_key_sha256": _sha256_value(sorted(keys)),
        "record_keys": [list(key) for key in sorted(keys)],
        "covered_active_template_count": len(covered),
        "covered_full_template_indices": sorted(
            full_index[key] for key in covered),
        "outside_active_coverage_count": len(unknown),
        "outside_active_coverage_keys": [list(key) for key in unknown],
        "full_template_count": full_count,
        "missing_template_count": full_count - len(covered),
        "complete_semantic_manifest": set(keys) == set(full_index),
        "interpretation": (
            "preload_80e3 warm-up cache only; never a coverage authority"),
    }


def _frame_envelope_crosscheck(
        root: Path, coverage: CoverageReport,
        full_keys: set[tuple[int, int]],
        current_keys: set[tuple[int, int]],
        ) -> dict[str, object]:
    """Bind the catalogue to the independent weighted-frame join evidence."""
    # These helpers are intentionally consumed as an independent proof.  The
    # full inventory does not redefine which DrawPlan classes need templates.
    from .frame_sprite_fragment_envelope import (
        FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT,
        _coverage_domains,
        _domain_hash,
    )

    domains, nonrendering, provenance = _coverage_domains(coverage)
    required = {
        key for keys in domains.values() for key in keys
    }
    outside = sorted(required - full_keys)
    if outside:
        raise FullHQT3InventoryError(
            f"weighted frame join needs {len(outside)} identities outside the "
            "full DescriptorResourcePair catalogue")
    missing = sorted(required - current_keys)
    missing_sha = _domain_hash(missing)

    status_path = (
        root / "Build" /
        "rtype_python_frame_sprite_fragment_envelope_status.json")
    try:
        status_raw = status_path.read_bytes()
        status = json.loads(status_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullHQT3InventoryError(
            f"cannot read weighted frame-envelope status: {exc}") from exc
    if status.get("format") != FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT:
        raise FullHQT3InventoryError("weighted frame-envelope format changed")
    blockers = status.get("blockers")
    if not isinstance(blockers, list):
        raise FullHQT3InventoryError("weighted frame-envelope blockers missing")
    hqt_blockers = [
        item for item in blockers
        if isinstance(item, dict) and item.get("code") == "PZFSFE102"
    ]
    action_blockers = [
        item for item in blockers
        if isinstance(item, dict) and item.get("code") == "PZFSFE101"
    ]
    if len(hqt_blockers) != 1 or action_blockers:
        raise FullHQT3InventoryError(
            "weighted frame-envelope blocker topology changed")
    hqt = hqt_blockers[0]
    if (hqt.get("missing_template_count") != len(missing) or
            hqt.get("missing_template_domain_sha256") != missing_sha):
        raise FullHQT3InventoryError(
            "full inventory/current HQT3 join differs from weighted envelope")
    witnesses = status.get("class_action_witnesses")
    if not isinstance(witnesses, list):
        raise FullHQT3InventoryError(
            "weighted frame-envelope class-action witnesses missing")
    nonrendering_classes = tuple(sorted({
        str(item.get("class_name"))
        for item in witnesses if isinstance(item, dict) and
        item.get("source_coverage_nonrendering") is True
    }))
    try:
        unreachable_raw = status["input_bindings"]["sprite_coverage"][
            "source_rom_unreachable_draw_classes"]
    except (KeyError, TypeError) as exc:
        raise FullHQT3InventoryError(
            "weighted frame-envelope lost source/ROM unreachable classes") from exc
    if not isinstance(unreachable_raw, list) or not all(
            isinstance(item, str) for item in unreachable_raw):
        raise FullHQT3InventoryError(
            "weighted frame-envelope unreachable class proof is malformed")
    unreachable = frozenset(unreachable_raw)
    classified_nonrendering = set(nonrendering) | set(unreachable)
    for name in nonrendering_classes:
        if domains.get(name) or name not in classified_nonrendering:
            raise FullHQT3InventoryError(
                f"weighted envelope non-rendering class {name} is not "
                "source-classified as non-rendering")
    unresolved_empty = [
        str(item.get("class_name"))
        for item in witnesses
        if isinstance(item, dict) and
        int(item.get("max_records_per_object", 0)) > 0 and
        int(item.get("candidate_template_count", 0)) == 0 and
        item.get("source_coverage_nonrendering") is not True
    ]
    if unresolved_empty:
        raise FullHQT3InventoryError(
            "weighted envelope contains unresolved empty draw-action domains: "
            + ", ".join(sorted(unresolved_empty)))
    return {
        "status_path": status_path.resolve().relative_to(root).as_posix(),
        "status_sha256": hashlib.sha256(status_raw).hexdigest(),
        "status": status.get("status"),
        "coverage_domain_sha256": _sha256_value(provenance),
        "required_template_count": len(required),
        "required_template_domain_sha256": _domain_hash(required),
        "missing_from_current_hqt3_count": len(missing),
        "missing_from_current_hqt3_domain_sha256": missing_sha,
        "missing_from_current_hqt3_first_witnesses": [
            list(key) for key in missing[:32]
        ],
        "missing_current_identities_present_in_full_catalog": True,
        "unresolved_empty_draw_action_domain_count": 0,
        "unresolved_empty_draw_action_classes": [],
        "source_proved_nonrendering_witness_count": len(
            nonrendering_classes),
        "source_proved_nonrendering_witness_classes": list(
            nonrendering_classes),
        "source_rom_unreachable_draw_class_count": len(unreachable),
        "source_rom_unreachable_draw_classes": sorted(unreachable),
        "empty_draw_action_domains_resolved": True,
    }


def analyze_full_hqt3_inventory(
        project_root: Path | str | None = None, *,
        coverage_report: CoverageReport | None = None,
        asset_manifest_path: Path | None = None,
        ) -> dict[str, object]:
    """Build the complete active template catalogue and blocked load plan."""
    root = (Path(__file__).resolve().parents[3] if project_root is None
            else Path(project_root)).resolve()
    if coverage_report is None:
        # Delayed import keeps pure inventory unit tests lightweight.
        from .sprite_coverage import analyze_sprite_coverage
        coverage_report = analyze_sprite_coverage(root)
    report = coverage_report
    if report.root_module != ACTIVE_ROOT_MODULE:
        raise FullHQT3InventoryError(
            f"coverage root is {report.root_module!r}, expected "
            f"{ACTIVE_ROOT_MODULE!r}")
    if report.unresolved_domains:
        raise FullHQT3InventoryError(
            "coverage has unresolved sprite domains: " +
            ", ".join(report.unresolved_domains))

    common_domains, class_domains, events, ambient = derive_sprite_domains(
        report)
    enemies_text, enemies_sha = _bound_source_text(
        root, report, "rtype_port.enemies")
    enemy_tree = ast.parse(enemies_text, filename="rtype_port.enemies")
    read_descriptor_sha = _validate_read_descriptor_ast(enemy_tree)
    asset_method = _class_method(enemy_tree, "M72SpriteAtlas", "_asset")
    asset_method_sha = _ast_sha256(asset_method)
    sprite_width = _literal_int(enemy_tree, "SPRITE_CELL_W")
    sprite_height = _literal_int(enemy_tree, "SPRITE_CELL_H")
    cell_bytes = sprite_width * sprite_height * 2

    all_pairs = tuple(sorted({
        pair for pair in report.common_pairs
    } | {
        pair for _stage, pairs in report.per_stage_pairs for pair in pairs
    }))
    rom_path = root / "Assets" / "Converted" / "Arcade" / \
        "RTYPE_MAINCPU_REGION.bin"
    try:
        rom = rom_path.read_bytes()
    except OSError as exc:
        raise FullHQT3InventoryError(
            f"cannot read active World ROM: {exc}") from exc
    rom_sha = hashlib.sha256(rom).hexdigest()
    if rom_sha != report.rom_sha256:
        raise FullHQT3InventoryError("CoverageReport World ROM hash is stale")
    descriptor_witnesses = validate_descriptor_witnesses(
        rom, (pair.descriptor for pair in all_pairs))
    asset_witnesses = _asset_witnesses(
        root, report, all_pairs, cell_bytes)

    templates = concrete_templates_for_pairs(all_pairs)
    template_index = {item.key: index for index, item in enumerate(templates)}
    encoded_index = {
        (encode_bank_key(item.bank), item.descriptor.address): index
        for index, item in enumerate(templates)
    }
    if len(template_index) != len(templates) or len(encoded_index) != len(templates):
        raise FullHQT3InventoryError("full HQT3 resolver key is not unique")
    template_rows: list[dict[str, object]] = []
    for index, template in enumerate(templates):
        row = template.semantic_row()
        row["template_index"] = index
        template_rows.append(row)

    scopes: list[dict[str, object]] = []
    common_pair_map = dict(report.common_domain_pairs)
    force_names = set(FORCE_P3D_DOMAIN_NAMES)
    present_force = force_names & set(common_pair_map)
    force_epoch_evidence: dict[str, object] | None = None
    if present_force:
        if present_force != force_names:
            raise FullHQT3InventoryError(
                "coverage has an incomplete Force P3D domain family")
        force_text, _force_sha = _bound_source_text(
            root, report, "rtype_port.force")
        game_text, _game_sha = _bound_source_text(
            root, report, "rtype_port.game")
        try:
            force_proof = audit_force_palette_epochs(
                force_text, game_text, enemies_text, common_pair_map)
        except SpriteWorkingSetError as exc:
            raise FullHQT3InventoryError(str(exc)) from exc
        epoch_scopes: list[str] = []
        for candidate in force_proof.candidates:
            pairs = _narrow_force_pairs(
                common_pair_map, candidate.palette_slot)
            if (_working_set_pair_sha256(pairs) != candidate.pair_sha256 or
                    cells_for_pairs(pairs) != candidate.cells):
                raise FullHQT3InventoryError(
                    "Force palette epoch relation differs from source proof")
            scope_id = candidate.domain_id
            epoch_scopes.append(scope_id)
            scopes.append(_scope_report(
                scope_id, "force-p3d-palette-epoch", pairs,
                template_index, cell_bytes,
                source_symbols=tuple(force_proof.epoch_source_domain_ids),
            ))
        force_epoch_evidence = {
            "evidence_sha256": force_proof.evidence_sha256,
            "at_most_one_live_epoch": True,
            "candidate_scope_ids": epoch_scopes,
            "resident_combination_claimed": False,
        }

    common_scope_ids: list[str] = []
    for domain in common_domains:
        source_name = domain.domain_id.split(":", 1)[1]
        if source_name in force_names:
            continue
        common_scope_ids.append(domain.domain_id)
        scopes.append(_scope_report(
            domain.domain_id, "common-domain", domain.pairs,
            template_index, cell_bytes,
            source_symbols=domain.source_symbols,
        ))

    stage_scope_ids: dict[int, list[str]] = {stage: [] for stage in range(1, 9)}
    for domain in class_domains:
        if domain.stage is None:
            raise FullHQT3InventoryError(
                f"stage class domain {domain.domain_id} lost its stage")
        stage_scope_ids[domain.stage].append(domain.domain_id)
        scopes.append(_scope_report(
            domain.domain_id, "stage-class", domain.pairs,
            template_index, cell_bytes, stage=domain.stage,
            class_name=domain.class_name, source_symbols=domain.source_symbols,
        ))
    scopes.sort(key=lambda item: str(item["scope_id"]))
    scope_by_id = {str(item["scope_id"]): item for item in scopes}
    if len(scope_by_id) != len(scopes):
        raise FullHQT3InventoryError("load scope identifier is not unique")

    stage_catalogs: list[dict[str, object]] = []
    for stage, stage_pairs in report.per_stage_pairs:
        ids = tuple(sorted(stage_scope_ids[stage]))
        catalog_indices = sorted({
            int(index)
            for scope_id in ids
            for index in scope_by_id[scope_id]["template_indices"]
        })
        expected = {
            template_index[item.key]
            for item in concrete_templates_for_pairs(stage_pairs)
        }
        if set(catalog_indices) != expected:
            raise FullHQT3InventoryError(
                f"stage {stage} class scopes do not equal its exact relation")
        stage_catalogs.append({
            "stage": stage,
            "scope_ids": list(ids),
            "scope_count": len(ids),
            "catalog_template_count": len(catalog_indices),
            "catalog_template_indices": catalog_indices,
            "catalog_template_indices_sha256": _sha256_value(catalog_indices),
            "common_catalog_is_separate": True,
            "whole_stage_residency_claimed": False,
        })

    represented = {
        (templates[int(index)].bank, templates[int(index)].descriptor.address)
        for scope in scopes for index in scope["template_indices"]
    }
    if represented != set(template_index):
        raise FullHQT3InventoryError(
            "load-scope union does not equal the complete template catalogue")

    event_rows = [
        {
            "event_id": event.event_id,
            "stage": event.stage,
            "address": event.address,
            "class_scope_ids": list(event.class_domain_ids),
            "correlation_exact": event.correlation_exact,
            "ambiguous_classes": list(event.ambiguous_classes),
            "pair_sha256": event.pair_sha256,
            "pack_id": event.pack_id,
        }
        for event in events
    ]
    exact_events = sum(bool(item["correlation_exact"]) for item in event_rows)
    all_cells = cells_for_pairs(all_pairs)
    global_fixed = fixed_hqt3_bytes(templates)

    current_manifest = (
        root / "Build" / "rtype_python_assets.json"
        if asset_manifest_path is None else asset_manifest_path)
    current = _current_bootstrap_report(root, current_manifest, encoded_index)
    current_keys = {
        (int(item[0]), int(item[1]))
        for item in current["record_keys"]
    }
    frame_envelope = _frame_envelope_crosscheck(
        root, report, set(encoded_index), current_keys)

    blockers = [
        {
            "code": "PZHQT201",
            "scope": "event-to-template-correlation",
            "reason": (
                f"{len(event_rows) - exact_events} ROM events reuse class "
                "relations which coverage cannot yet narrow per event"),
        },
        {
            "code": "PZHQT202",
            "scope": "cross-event-and-common-lifetimes",
            "reason": (
                "the scheduler retains objects while later events and common "
                "player/Force/effect domains can coexist; no exact live-set "
                "interval proof exists"),
        },
        {
            "code": "PZHQT203",
            "scope": "load-transition-order",
            "reason": (
                "upload-before-first-draw, eviction-after-last-draw and "
                "same-frame spawn transitions are not yet proved"),
        },
        {
            "code": "PZHQT204",
            "scope": "physical-hqt3-state-and-ram-g-placement",
            "reason": (
                "template records/cells are exact, but BITMAP_LAYOUT/palette "
                "state indices and RAM_G addresses depend on the still-unbound "
                "resident pack selected by the lifetime proof"),
        },
    ]

    source_binding = {
        "root_module": report.root_module,
        "coverage_source_hashes": dict(report.source_hashes),
        "rom_path": rom_path.resolve().relative_to(root).as_posix(),
        "rom_sha256": rom_sha,
        "enemies_source_sha256": enemies_sha,
        "m72_sprite_atlas_asset_ast_sha256": asset_method_sha,
        "read_descriptor_ast_sha256": read_descriptor_sha,
        "sprite_cell_width": sprite_width,
        "sprite_cell_height": sprite_height,
        "sprite_cell_argb4444_bytes": cell_bytes,
    }
    scope_storage = {
        "scope_count": len(scopes),
        "sum_scope_template_records": sum(
            int(item["template_count"]) for item in scopes),
        "sum_scope_template_cell_references": sum(
            int(item["template_cell_reference_count"]) for item in scopes),
        "sum_scope_fixed_hqt3_bytes_excluding_state_tables": sum(
            int(item["hqt3_fixed_layout"][
                "fixed_bytes_excluding_state_table"])
            for item in scopes),
        "interpretation": (
            "content may repeat between independently loadable scopes; this "
            "is catalogue storage arithmetic, not simultaneous RAM_G usage"),
    }
    inventory = {
        "format": FULL_HQT3_INVENTORY_FORMAT,
        "status": FULL_HQT3_INVENTORY_STATUS,
        "inventory_complete": True,
        "live": False,
        "source_binding": source_binding,
        "source_binding_sha256": _sha256_value(source_binding),
        "descriptor_decoder_witnesses": descriptor_witnesses,
        "asset_resolution_witnesses": asset_witnesses,
        "relation": {
            "common_pair_count": len(report.common_pairs),
            "per_stage_pair_counts": {
                str(stage): len(pairs)
                for stage, pairs in report.per_stage_pairs
            },
            "unique_pair_count": len(all_pairs),
            "unique_pair_relation_sha256": relation_sha256(all_pairs),
            "descriptor_resource_cartesian_product": False,
        },
        "global_catalog": {
            "template_count": len(templates),
            "resource_alias_template_count": sum(
                len(item.resource_types) > 1 for item in templates),
            "template_cell_reference_count": sum(
                item.cell_count for item in templates),
            "unique_logical_cell_count": len(all_cells),
            "selected_argb4444_bytes": len(all_cells) * cell_bytes,
            "hqt3_fixed_layout": global_fixed,
            "template_rows_sha256": _sha256_value(template_rows),
            "templates": template_rows,
        },
        "load_plan": {
            "common_scope_ids": sorted(common_scope_ids),
            "force_palette_epochs": force_epoch_evidence,
            "ambient_stage_scope_ids": list(ambient),
            "scopes": scopes,
            "stage_catalogs": stage_catalogs,
            "events": event_rows,
            "event_count": len(event_rows),
            "event_correlation_exact_count": exact_events,
            "event_correlation_ambiguous_count": len(event_rows) - exact_events,
            "resident_combinations": [],
            "whole_inventory_resident": False,
            "whole_stage_union_resident": False,
            "scope_storage": scope_storage,
        },
        "current_bootstrap_hqt3": current,
        "frame_sprite_fragment_envelope_crosscheck": frame_envelope,
        "blockers": blockers,
        "proof_boundaries": {
            "complete_template_key_inventory": True,
            "complete_descriptor_decoder_witness": True,
            "complete_asset_bank_resolution_witness": True,
            "exact_template_record_and_cell_byte_counts": True,
            "physical_bitmap_state_table_bound": False,
            "ram_g_residency_bound": False,
            "load_transition_bound": False,
        },
    }
    semantic = dict(inventory)
    semantic.pop("status")
    inventory["analysis_sha256"] = _sha256_value(semantic)
    return inventory


__all__ = [
    "ConcreteTemplate",
    "FULL_HQT3_INVENTORY_FORMAT",
    "FULL_HQT3_INVENTORY_STATUS",
    "HQT3_CELL_BYTES",
    "HQT3_HEADER_BYTES",
    "HQT3_RECORD_BYTES",
    "HQT3_RECORD_STRUCT_FORMAT",
    "HQT3_STATE_BYTES",
    "FullHQT3InventoryError",
    "analyze_full_hqt3_inventory",
    "concrete_templates_for_pairs",
    "encode_bank_key",
    "fixed_hqt3_bytes",
    "relation_sha256",
    "validate_descriptor_witnesses",
]
