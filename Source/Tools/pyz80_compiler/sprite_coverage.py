"""Fail-closed sprite coverage for the active ``run_python.cmd`` program.

This module deliberately does not use a preload routine as a semantic asset
manifest.  It starts at the module named by ``run_python.cmd``, inventories
every reachable :class:`M72SpriteAtlas` draw sink, and evaluates the finite
common player/weapon descriptor domains directly from the active Python AST
and its World ROM.

Stage enemy domains are rooted in the 788 active ROM event records, joined to
the Python dispatcher and class-construction graph, then interpreted over
finite selector/ROM domains.  Unknown draw sinks, handlers, selector shapes,
missing banks, and malformed descriptors are hard errors; no incomplete
report is returned.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import re
import struct
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping


ACTIVE_ROOT_MODULE = "rtype_port.app"
SINK_MODULES = frozenset({
    "rtype_port.enemies",
    "rtype_port.force",
    "rtype_port.bits",
    "rtype_port.game",
})
EXPECTED_COMMON_PAIR_COUNT = 309
_STAGE_COVERAGE_CACHE: dict[
    tuple[str, str, str, tuple[tuple[str, int, int], ...]],
    tuple[
        tuple[tuple[int, tuple["DescriptorResourcePair", ...]], ...],
        tuple["StageCoverageProvenance", ...],
    ],
] = {}


class SpriteCoverageError(ValueError):
    """The active Python program no longer satisfies the coverage contract."""


@dataclass(frozen=True, order=True)
class DescriptorRef:
    """A decoded descriptor which never loses its immutable World-ROM address."""

    address: int
    dx: int
    dy: int
    code: int
    attribute: int
    width: int
    height: int
    flip_x: bool
    flip_y: bool


@dataclass(frozen=True, order=True)
class PythonBankKey:
    """The exact source-bank identity returned by ``M72SpriteAtlas._asset``."""

    kind: str
    value: int


@dataclass(frozen=True, order=True)
class DescriptorResourcePair:
    """One semantic draw pair and every concrete Python bank it can select."""

    resource_type: int
    descriptor: DescriptorRef
    bank_keys: tuple[PythonBankKey, ...]


@dataclass(frozen=True)
class CommonCoverageProvenance:
    """Ownership proof for one independently loadable common domain."""

    domain: str
    resource_type: int
    pair_count: int
    cell_count: int
    bank_keys: tuple[PythonBankKey, ...]
    source_symbols: tuple[str, ...]
    owned_sink_ids: tuple[str, ...]


@dataclass(frozen=True)
class EventCoverageProvenance:
    """One immutable active ROM event and its dispatch class ownership."""

    address: int
    threshold: int
    command: int
    handler: int
    classes: tuple[str, ...]


@dataclass(frozen=True)
class ClassCoverageProvenance:
    """Exact relational pairs and selector sinks owned by one class."""

    class_name: str
    relation_kind: str
    selector_sources: tuple[str, ...]
    constructor_parameters: tuple[tuple[str, tuple[object, ...]], ...]
    pairs: tuple[DescriptorResourcePair, ...]
    owned_descriptor_sinks: tuple[str, ...]
    owned_resource_sinks: tuple[str, ...]


@dataclass(frozen=True)
class StageCoverageProvenance:
    """Event/handler/source ownership proving one stage's sprite domain."""

    stage: int
    event_first: int
    event_last: int
    event_count: int
    event_sha256: str
    pair_count: int
    cell_count: int
    resource_bank_domains: tuple[
        tuple[int, tuple[PythonBankKey, ...]], ...]
    handler_counts: tuple[tuple[int, int], ...]
    handler_classes: tuple[tuple[int, tuple[str, ...]], ...]
    events: tuple[EventCoverageProvenance, ...]
    class_coverage: tuple[ClassCoverageProvenance, ...]
    owned_handlers: tuple[int, ...]
    owned_classes: tuple[str, ...]
    owned_descriptor_sinks: tuple[str, ...]


@dataclass(frozen=True)
class CoverageReport:
    """Deterministic proof object for the currently owned common domains."""

    root_module: str
    reachable_modules: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    rom_sha256: str
    owned_sink_ids: tuple[str, ...]
    domain_counts: tuple[tuple[str, int], ...]
    selector_facts: tuple[tuple[str, tuple[int, ...]], ...]
    common_domain_pairs: tuple[
        tuple[str, tuple[DescriptorResourcePair, ...]], ...]
    common_provenance: tuple[CommonCoverageProvenance, ...]
    common_pairs: tuple[DescriptorResourcePair, ...]
    common_cell_count: int
    per_stage_pairs: tuple[tuple[int, tuple[DescriptorResourcePair, ...]], ...]
    stage_provenance: tuple[StageCoverageProvenance, ...]
    unresolved_domains: tuple[str, ...]

    @property
    def pairs(self) -> tuple[DescriptorResourcePair, ...]:
        """Compatibility name for the common player/weapon domain."""
        return self.common_pairs

    def as_dict(self) -> dict[str, object]:
        return {
            "root_module": self.root_module,
            "reachable_modules": list(self.reachable_modules),
            "source_hashes": dict(self.source_hashes),
            "rom_sha256": self.rom_sha256,
            "owned_sink_ids": list(self.owned_sink_ids),
            "domain_counts": dict(self.domain_counts),
            "selector_facts": {
                name: list(values) for name, values in self.selector_facts
            },
            "common_domain_pair_counts": {
                name: len(pairs)
                for name, pairs in self.common_domain_pairs
            },
            "common_provenance": [
                {
                    "domain": item.domain,
                    "resource_type": item.resource_type,
                    "pair_count": item.pair_count,
                    "cell_count": item.cell_count,
                    "bank_keys": [
                        {"kind": key.kind, "value": key.value}
                        for key in item.bank_keys
                    ],
                    "source_symbols": list(item.source_symbols),
                    "owned_sink_ids": list(item.owned_sink_ids),
                }
                for item in self.common_provenance
            ],
            "common_pair_count": len(self.common_pairs),
            "common_cell_count": self.common_cell_count,
            "common_pairs": [
                {
                    "resource_type": pair.resource_type,
                    "descriptor_address": pair.descriptor.address,
                    "banks": [
                        {"kind": bank.kind, "value": bank.value}
                        for bank in pair.bank_keys
                    ],
                }
                for pair in self.common_pairs
            ],
            "per_stage_pair_counts": {
                str(stage): len(pairs) for stage, pairs in self.per_stage_pairs
            },
            "stage_provenance": [
                {
                    "stage": item.stage,
                    "event_first": item.event_first,
                    "event_last": item.event_last,
                    "event_count": item.event_count,
                    "event_sha256": item.event_sha256,
                    "pair_count": item.pair_count,
                    "cell_count": item.cell_count,
                    "resource_bank_domains": {
                        f"{resource:02X}": [
                            {"kind": key.kind, "value": key.value}
                            for key in keys
                        ]
                        for resource, keys in item.resource_bank_domains
                    },
                    "handler_counts": dict(item.handler_counts),
                    "handler_classes": {
                        f"{handler:04X}": list(classes)
                        for handler, classes in item.handler_classes
                    },
                    "events": [
                        {
                            "address": event.address,
                            "threshold": event.threshold,
                            "command": event.command,
                            "handler": event.handler,
                            "classes": list(event.classes),
                        }
                        for event in item.events
                    ],
                    "class_coverage": [
                        {
                            "class_name": coverage.class_name,
                            "relation_kind": coverage.relation_kind,
                            "selector_sources": list(
                                coverage.selector_sources),
                            "constructor_parameters": {
                                name: list(values)
                                for name, values in
                                coverage.constructor_parameters
                            },
                            "pair_count": len(coverage.pairs),
                            "owned_descriptor_sinks": list(
                                coverage.owned_descriptor_sinks),
                            "owned_resource_sinks": list(
                                coverage.owned_resource_sinks),
                        }
                        for coverage in item.class_coverage
                    ],
                    "owned_handlers": list(item.owned_handlers),
                    "owned_classes": list(item.owned_classes),
                    "owned_descriptor_sinks": list(
                        item.owned_descriptor_sinks),
                }
                for item in self.stage_provenance
            ],
            "unresolved_domains": list(self.unresolved_domains),
        }


@dataclass(frozen=True, order=True)
class _SinkShape:
    module: str
    qualname: str
    receiver: str
    arguments: tuple[str, ...]
    keywords: tuple[tuple[str | None, str], ...]

    def digest(self) -> str:
        payload = repr((
            self.module, self.qualname, self.receiver,
            self.arguments, self.keywords,
        )).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


@dataclass(frozen=True)
class _SinkOccurrence:
    shape: _SinkShape
    line: int
    column: int


class _WorldRom:
    FILE_BASE = 0x10000

    def __init__(self, data: bytes) -> None:
        if len(data) != 0x100000:
            raise SpriteCoverageError(
                f"active World ROM has size {len(data)}, expected 1048576")
        self.data = data

    def byte(self, address: int) -> int:
        return self.data[self.FILE_BASE + (address & 0xFFFF)]

    def word(self, address: int) -> int:
        return struct.unpack_from(
            "<H", self.data, self.FILE_BASE + (address & 0xFFFF))[0]

    def descriptor(self, address: int) -> DescriptorRef:
        address &= 0xFFFF
        dx = self.byte(address)
        dy = self.byte(address + 1)
        dx = dx - 0x100 if dx & 0x80 else dx
        dy = dy - 0x100 if dy & 0x80 else dy
        code = self.word(address + 2)
        attribute = self.word(address + 4)
        width = 1 << ((attribute >> 14) & 3)
        height = 1 << ((attribute >> 12) & 3)
        if width not in (1, 2, 4, 8) or height not in (1, 2, 4, 8):
            raise SpriteCoverageError(
                f"descriptor ${address:04X} has invalid geometry {width}x{height}")
        return DescriptorRef(
            address=address,
            dx=dx,
            dy=dy,
            code=code,
            attribute=attribute,
            width=width,
            height=height,
            flip_x=bool(attribute & 0x0800),
            flip_y=bool(attribute & 0x0400),
        )


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _module_path(project_root: Path, module: str) -> Path:
    parts = module.split(".")
    path = project_root / "Source" / "Python" / Path(*parts)
    source = path.with_suffix(".py")
    if source.is_file():
        return source
    package = path / "__init__.py"
    if package.is_file():
        return package
    raise SpriteCoverageError(f"reachable local module has no source: {module}")


def _read_module_source(
        project_root: Path, module: str,
        overrides: Mapping[str, str],
        ) -> str:
    if module in overrides:
        return overrides[module]
    return _module_path(project_root, module).read_text(encoding="utf-8")


def _relative_import(module: str, level: int, imported: str | None) -> str:
    parts = module.split(".")
    if level <= 0 or level >= len(parts) + 1:
        raise SpriteCoverageError(
            f"invalid relative import level {level} in {module}")
    base = parts[:-level]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _local_imports(module: str, tree: ast.Module) -> tuple[str, ...]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "rtype_port" or alias.name.startswith("rtype_port."):
                    result.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_import(module, node.level, node.module)
            else:
                base = node.module or ""
            if not (base == "rtype_port" or base.startswith("rtype_port.")):
                continue
            if node.module is None:
                for alias in node.names:
                    if alias.name != "*":
                        result.add(base + "." + alias.name)
            else:
                result.add(base)
    return tuple(sorted(result))


def _active_graph(
        project_root: Path, overrides: Mapping[str, str],
        ) -> tuple[dict[str, ast.Module], dict[str, str]]:
    command_path = project_root / "run_python.cmd"
    command = command_path.read_text(encoding="utf-8")
    match = re.search(r"(?:^|\s)-m\s+([A-Za-z_][\w.]*)", command, re.MULTILINE)
    if match is None or match.group(1) != ACTIVE_ROOT_MODULE:
        actual = None if match is None else match.group(1)
        raise SpriteCoverageError(
            f"run_python.cmd root changed: {actual!r}, expected {ACTIVE_ROOT_MODULE}")

    trees: dict[str, ast.Module] = {}
    texts: dict[str, str] = {}
    pending = deque((ACTIVE_ROOT_MODULE,))
    while pending:
        module = pending.popleft()
        if module in trees:
            continue
        text = _read_module_source(project_root, module, overrides)
        try:
            tree = ast.parse(text, filename=str(_module_path(project_root, module)))
        except SyntaxError as exc:
            raise SpriteCoverageError(
                f"cannot parse reachable module {module}: {exc}") from exc
        trees[module] = tree
        texts[module] = text
        for imported in _local_imports(module, tree):
            # A symbol imported from a package can look like a submodule. Only
            # enqueue it when this project actually owns a Python source file.
            try:
                _module_path(project_root, imported)
            except SpriteCoverageError:
                continue
            pending.append(imported)

    missing = sorted(SINK_MODULES - trees.keys())
    if missing:
        raise SpriteCoverageError(
            "active run_python.cmd graph lost sprite modules: " + ", ".join(missing))
    return trees, texts


def _contains_read_descriptor(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Call) and
        ((isinstance(item.func, ast.Name) and item.func.id == "read_descriptor") or
         (isinstance(item.func, ast.Attribute) and
          item.func.attr == "read_descriptor"))
        for item in ast.walk(node)
    )


class _SinkVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.stack: list[str] = []
        self.sinks: list[_SinkOccurrence] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(  # noqa: N802
            self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Attribute) and node.func.attr == "draw":
            receiver = ast.unparse(node.func.value)
            descriptor_argument = node.args[1] if len(node.args) > 1 else None
            looks_like_atlas = (
                receiver == "atlas" or receiver.endswith(".atlas") or
                (descriptor_argument is not None and
                 _contains_read_descriptor(descriptor_argument))
            )
            if looks_like_atlas:
                shape = _SinkShape(
                    module=self.module,
                    qualname=".".join(self.stack),
                    receiver=receiver,
                    arguments=tuple(ast.unparse(argument) for argument in node.args),
                    keywords=tuple(
                        (keyword.arg, ast.unparse(keyword.value))
                        for keyword in node.keywords
                    ),
                )
                self.sinks.append(_SinkOccurrence(
                    shape, node.lineno, node.col_offset))
        self.generic_visit(node)


def _shape(module: str, qualname: str, receiver: str,
           *arguments: str) -> _SinkShape:
    normalized = tuple(
        ast.unparse(ast.parse(argument, mode="eval").body)
        for argument in arguments
    )
    return _SinkShape(module, qualname, receiver, normalized, ())


def _expected_sink_shapes() -> Counter[_SinkShape]:
    result: Counter[_SinkShape] = Counter()
    enemy = "rtype_port.enemies"
    enemy_common = (
        "target", "read_descriptor(self.rom, enemy.descriptor)",
        "palette", "resource_type", "enemy.x", "enemy.y",
    )
    result[_shape(enemy, "M72EnemyWorld.draw", "self.atlas", *enemy_common)] = 1
    result[_shape(
        enemy, "M72EnemyWorld.draw", "self.atlas",
        "target", "read_descriptor(self.rom, enemy.descriptor + 6)",
        "palette", "resource_type", "enemy.x", "enemy.y",
    )] = 11
    result[_shape(
        enemy, "M72EnemyWorld.draw", "self.atlas",
        "target", "read_descriptor(self.rom, descriptor)",
        "palette", "resource_type", "enemy.x", "enemy.y",
    )] = 2
    result[_shape(
        enemy, "M72EnemyWorld.draw", "self.atlas",
        "target", "read_descriptor(self.rom, enemy.overlay_descriptor)",
        "palette", "resource_type", "enemy.overlay_x", "enemy.overlay_y",
    )] = 1
    result[_shape(
        enemy, "M72EnemyWorld.draw", "self.atlas",
        "target", "read_descriptor(self.rom, descriptor)",
        "palette", "resource_type", "x", "y",
    )] = 1

    force = "rtype_port.force"
    result[_shape(
        force, "Force.draw", "atlas", "target",
        "read_descriptor(self.rom, self.descriptor)",
        "self.resource_slot", "FORCE_RESOURCE_TYPE", "self.x", "self.y",
    )] = 1
    result[_shape(
        force, "Force.draw", "atlas", "target",
        "read_descriptor(self.rom, projectile.descriptor)",
        "projectile.resource_slot", "0x02", "projectile.x", "projectile.y",
    )] = 1
    result[_shape(
        force, "Force.draw", "atlas", "target",
        "read_descriptor(self.rom, segment.descriptor)",
        "segment.resource_slot", "0x3D", "segment.x", "segment.y",
    )] = 2
    result[_shape(
        force, "Force.draw", "atlas", "target",
        "read_descriptor(self.rom, descriptor)",
        "beam.resource_slot", "0x3D", "beam.x", "beam.y",
    )] = 1
    result[_shape(
        force, "Force.draw", "atlas", "target",
        "read_descriptor(self.rom, dart.descriptor)",
        "dart.resource_slot", "0x3D", "dart.x", "dart.y",
    )] = 1

    result[_shape(
        "rtype_port.bits", "PlayerBits.draw", "atlas", "target",
        "read_descriptor(self.rom, bit.descriptor)",
        "bit.resource_slot", "0x56", "bit.x", "bit.y",
    )] = 1
    result[_shape(
        "rtype_port.game", "Game.render", "self.enemy_world.atlas", "target",
        "read_descriptor(self.enemy_world.rom, descriptor)",
        "self.death_palette", "0x09", "self.death_native[0]",
        "self.death_native[1]",
    )] = 1
    result[_shape(
        "rtype_port.game", "Game.render", "self.enemy_world.atlas", "target",
        "read_descriptor(self.enemy_world.rom, shot.terminal_descriptor)",
        "0", "0x01", "shot.native_x", "shot.native_y",
    )] = 1
    return result


def _validate_sinks(trees: Mapping[str, ast.Module]) -> tuple[str, ...]:
    found: list[_SinkOccurrence] = []
    for module in sorted(trees):
        visitor = _SinkVisitor(module)
        visitor.visit(trees[module])
        found.extend(visitor.sinks)

    expected = _expected_sink_shapes()
    actual = Counter(item.shape for item in found)
    if actual != expected:
        extra = list((actual - expected).elements())
        missing = list((expected - actual).elements())
        details: list[str] = []
        if extra:
            details.append("unknown/new=" + "; ".join(
                f"{item.module}:{item.qualname}:{item.receiver}"
                f"({', '.join(item.arguments)})" for item in extra))
        if missing:
            details.append("missing/changed=" + "; ".join(
                f"{item.module}:{item.qualname}:{item.receiver}"
                f"({', '.join(item.arguments)})" for item in missing))
        raise SpriteCoverageError(
            "unknown/new M72SpriteAtlas.draw sink or changed sink shape: " +
            " | ".join(details))

    grouped: dict[_SinkShape, list[_SinkOccurrence]] = {}
    for item in found:
        grouped.setdefault(item.shape, []).append(item)
    identifiers: list[str] = []
    for shape in sorted(grouped):
        occurrences = sorted(grouped[shape], key=lambda item: (item.line, item.column))
        for ordinal, _item in enumerate(occurrences):
            identifiers.append(
                f"{shape.module}:{shape.qualname}:{shape.digest()}:{ordinal}")
    if len(identifiers) != 25:
        raise SpriteCoverageError(
            f"owned sink inventory has {len(identifiers)} entries, expected 25")
    return tuple(sorted(identifiers))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    node = next((
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == name
    ), None)
    if node is None:
        raise SpriteCoverageError(f"active Python class disappeared: {name}")
    return node


def _find_function(tree: ast.Module, class_name: str,
                   name: str) -> ast.FunctionDef:
    class_node = _find_class(tree, class_name)
    node = next((
        item for item in class_node.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    ), None)
    if node is None:
        raise SpriteCoverageError(
            f"active Python method disappeared: {class_name}.{name}")
    return node


def _ast_sha256(node: ast.AST) -> str:
    return hashlib.sha256(
        ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


# These hashes cover only selector methods whose finite-domain interpretation
# is owned below. Comments and line movements do not affect them. A semantic
# edit requires updating the evaluator and its focused tests in the same change.
_DOMAIN_AST_SHA256 = {
    ("rtype_port.enemies", "PlayerShotVisual4EAF", "__init__"):
        "52c27e6c466a50557dafdc5450f72a4b8058c09312a06391f053995cca80ec2d",
    ("rtype_port.enemies", "M72SpriteAtlas", "_asset"):
        "14f85eed88b2ff082cdc54a73477167e8142da762f66a4b4b847a3bfaa3a2546",
    ("rtype_port.force", "Force", "__init__"):
        "217c9dd8f12878d60b780fcf311875fc3b1732cbb27793db994c759b9a751b46",
    ("rtype_port.force", "Force", "_return_descriptor"):
        "e116a1348991fdd041c9e2ce5aa43549147297adbf5bdff08bed4826ca1dbc43",
    ("rtype_port.force", "Force", "_attached_descriptor"):
        "236a55a2f6a0dfa931540c27d101e0e19f6519a5d1786bf634922ea9a5718f9d",
    ("rtype_port.force", "Force", "_detached_descriptor"):
        "be05c82b5c3d9bb77dd80e98979b03b7237b57e462ff5ac75589f859c38c6433",
    ("rtype_port.force", "Force", "fire_unattached_matrix"):
        "797b678acb56a8f88a86808b328a7e29213214176b7e3448e620311ed1cc2b98",
    ("rtype_port.force", "Force", "_fire_attached_type0"):
        "d17945dae1ad59b9825fbdd32a8658a6d44b765da108aae5d93427c4de54fa94",
    ("rtype_port.force", "Force", "update_ray_segments"):
        "391b31c307f06134b547bcb49256346d56965506cab336b1b80dd161f2372142",
    ("rtype_port.force", "Force", "_update_turning_ray"):
        "3e86ce7cd2a8da2e92125c1690522ac57e2755a35121d5c5b51cb3bf9d540405",
    ("rtype_port.force", "Force", "_update_mirrored_ray"):
        "e7a1b5293ccda77ed14d340207fdc3fe4ebd9b6301ebed1ae3a1f08789c48a56",
    ("rtype_port.force", "Force", "update_grid_segments"):
        "8fd0ed0effdf70dc0eb65e4c5a9f3be67378160f49005b2b5ece6d9469ad69b1",
    ("rtype_port.force", "Force", "_fire_attached_type6"):
        "236ad773c08393c639c07286d645860a767b1faf1e636b06f7540a33ff13e248",
    ("rtype_port.force", "Force", "update_type6"):
        "f9e59954e4258cd01e69d3f4bf9810967d96e8eb3152ac6c72749bcf482d6573",
    ("rtype_port.bits", "PlayerBits", "_update_one"):
        "ddbd98977bddca071e6fa61aeac9a1fe33af922e375e61856d9ffe0b7193e28f",
    ("rtype_port.game", "Game", "update"):
        "2d33c3a614a39272248d8f223ac5161551015887e05361fa4b432529856b8e9d",
    ("rtype_port.player_lifecycle", "PlayerLifecycle", "explosion_descriptor"):
        "8042bdc7b4e1fbbd7b1487ef8ca4c73d7742110eb30fa86bea439b571efc4281",
}


def _verify_domain_ast(trees: Mapping[str, ast.Module]) -> None:
    for (module, class_name, function_name), expected in _DOMAIN_AST_SHA256.items():
        tree = trees.get(module)
        if tree is None:
            raise SpriteCoverageError(
                f"domain source is not reachable from run_python.cmd: {module}")
        actual = _ast_sha256(_find_function(tree, class_name, function_name))
        if actual != expected:
            raise SpriteCoverageError(
                "owned sprite selector AST changed without a coverage model: "
                f"{module}.{class_name}.{function_name} {actual}")


def _module_literal(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not any(
                isinstance(target, ast.Name) and target.id == name
                for target in targets):
            continue
        try:
            return ast.literal_eval(value)
        except (TypeError, ValueError) as exc:
            raise SpriteCoverageError(
                f"module constant is no longer literal: {name}") from exc
    raise SpriteCoverageError(f"module constant disappeared: {name}")


def _target_text(node: ast.expr) -> str:
    return ast.unparse(node)


def _assigned_ints(function: ast.FunctionDef, target_text: str) -> set[int]:
    result: set[int] = set()
    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if value is None or not any(
                _target_text(target) == target_text for target in targets):
            continue
        try:
            literal = ast.literal_eval(value)
        except (TypeError, ValueError):
            continue
        if isinstance(literal, int):
            result.add(literal)
    return result


def _dataclass_int_default(tree: ast.Module, class_name: str,
                           field: str) -> int:
    class_node = _find_class(tree, class_name)
    for node in class_node.body:
        if (isinstance(node, ast.AnnAssign) and
                isinstance(node.target, ast.Name) and node.target.id == field and
                node.value is not None):
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError) as exc:
                raise SpriteCoverageError(
                    f"{class_name}.{field} default is not literal") from exc
            if isinstance(value, int):
                return value
    raise SpriteCoverageError(f"dataclass field disappeared: {class_name}.{field}")


def _strip_annotations(function: ast.FunctionDef) -> ast.FunctionDef:
    result = copy.deepcopy(function)
    result.decorator_list = []
    result.returns = None
    for argument in (
            list(result.args.posonlyargs) + list(result.args.args) +
            list(result.args.kwonlyargs)):
        argument.annotation = None
    if result.args.vararg is not None:
        result.args.vararg.annotation = None
    if result.args.kwarg is not None:
        result.args.kwarg.annotation = None
    return result


def _compile_method(function: ast.FunctionDef,
                    globals_: Mapping[str, object] | None = None):
    node = _strip_annotations(function)
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = dict(globals_ or {})
    exec(compile(module, "<sprite-coverage-selector>", "exec"), namespace)
    return namespace[function.name]


def _signed_word(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _u16(value: int) -> int:
    return value & 0xFFFF


def _force_body_addresses(force_tree: ast.Module, rom: _WorldRom) -> set[int]:
    methods = {
        name: _compile_method(_find_function(force_tree, "Force", name))
        for name in (
            "_return_descriptor", "_attached_descriptor", "_detached_descriptor")
    }
    result: set[int] = set()
    for level in (1, 2, 3):
        # Levels 1/2 use the modulo-six tables.  Level 3 masks its animation
        # state with ``& 3`` everywhere, so states four and five are not part
        # of the reachable Python domain (and would read unrelated ROM words).
        for animation in range(4 if level == 3 else 6):
            for frame in range(16):
                for last_vertical in (-1, 0, 1):
                    for behind in (False, True):
                        for horizontal in (-1, 0, 1):
                            stub = SimpleNamespace(
                                rom=rom, level=level, animation=animation,
                                animation_group=0, last_vertical=last_vertical,
                                behind=behind, velocity_x=(-1 if horizontal < 0 else 1),
                                x_q8=horizontal, old_x_q8=0,
                            )
                            result.add(methods["_return_descriptor"](stub, frame))
                            # ForceInput.direction is a four-bit input domain;
                            # keep it exhaustive and let the active selector
                            # map those values through its ROM group table.
                            for direction in range(16):
                                stub.animation = animation
                                result.add(methods["_attached_descriptor"](
                                    stub, frame, direction))
                            stub.animation = animation
                            result.add(methods["_detached_descriptor"](stub, frame))

    initial = _assigned_ints(
        _find_function(force_tree, "Force", "__init__"), "self.descriptor")
    if len(initial) != 1:
        raise SpriteCoverageError("Force.__init__ descriptor is not one literal")
    result.update(initial)
    if len(result) != 31:
        raise SpriteCoverageError(
            f"Force body domain has {len(result)} descriptors, expected 31")
    return result


def _force_projectile_addresses(force_tree: ast.Module) -> set[int]:
    setups = _module_literal(force_tree, "MATRIX_STRAIGHT_SETUPS")
    if not isinstance(setups, dict):
        raise SpriteCoverageError("MATRIX_STRAIGHT_SETUPS is not a literal dict")
    result = {
        int(value[2]) for value in setups.values()
        if isinstance(value, tuple) and len(value) == 3
    }
    if len(result) != 5:
        raise SpriteCoverageError(
            f"Force projectile domain has {len(result)} descriptors, expected 5")
    return result


class _CollisionSequence:
    def __init__(self, values: Iterable[tuple[int, int]]) -> None:
        self.values = deque(values)

    def __call__(self, _x: int, _y: int) -> tuple[int, int]:
        return self.values.popleft() if self.values else (0, 0)


def _ray_seed_phases(force_tree: ast.Module) -> tuple[set[int], set[int]]:
    """Execute the active constructor loop and retain its two phase domains."""

    def capture(*args: object) -> SimpleNamespace:
        if len(args) != 8:
            raise SpriteCoverageError(
                "ForceRaySegment constructor shape changed")
        phase = args[4]
        mirrored = args[7]
        if not isinstance(phase, int) or not isinstance(mirrored, bool):
            raise SpriteCoverageError(
                "ForceRaySegment phase/mirrored arguments changed type")
        return SimpleNamespace(phase=phase, mirrored=mirrored)

    constructor = _compile_method(
        _find_function(force_tree, "Force", "_fire_attached_type0"),
        {"ForceRaySegment": capture},
    )
    turning: set[int] = set()
    mirrored: set[int] = set()
    for level in (1, 2, 3):
        owner = SimpleNamespace(
            level=level,
            x=0x0180,
            y=0x0100,
            projectiles={},
            ray_segments={},
        )
        constructor(owner)
        for segment in owner.ray_segments.values():
            (mirrored if segment.mirrored else turning).add(segment.phase)
    if turning != {0, 2} or mirrored != {0}:
        raise SpriteCoverageError(
            "Force ray constructor seed phases changed: "
            f"turning={sorted(turning)!r}, mirrored={sorted(mirrored)!r}")
    return turning, mirrored


def _terminal_domain(tree: ast.Module, class_name: str,
                     function: ast.FunctionDef, base: int) -> set[int]:
    initial = _dataclass_int_default(tree, class_name, "terminal_offset")
    steps = {
        int(node.value.value)
        for node in ast.walk(function)
        if (isinstance(node, ast.AugAssign) and
            ast.unparse(node.target).endswith(".terminal_offset") and
            isinstance(node.op, ast.Sub) and
            isinstance(node.value, ast.Constant) and
            isinstance(node.value.value, int))
    }
    if len(steps) != 1:
        raise SpriteCoverageError(
            f"{class_name} terminal decrement is not one literal")
    step = steps.pop()
    if initial <= 0 or step <= 0 or initial % step:
        raise SpriteCoverageError(f"invalid terminal domain {initial}/{step}")
    # The zero-offset pass releases the record before rendering.
    return {base + offset for offset in range(step, initial, step)}


def _force_ray_addresses(
        force_tree: ast.Module, rom: _WorldRom,
        ) -> tuple[set[int], set[int], set[int]]:
    globals_ = {"_u16": _u16, "_signed_word": _signed_word}
    turning = _compile_method(
        _find_function(force_tree, "Force", "_update_turning_ray"), globals_)
    mirrored = _compile_method(
        _find_function(force_tree, "Force", "_update_mirrored_ray"), globals_)
    result: set[int] = set()
    clear = (0x0DFC, 0x07D0)
    blocked = (0, 0)
    sequences = (
        (clear,),
        (blocked, clear),
        (blocked, blocked, clear),
        (blocked, blocked, blocked),
    )
    turning_seeds, mirrored_seeds = _ray_seed_phases(force_tree)

    # Close the finite phase graph under every branch of the active selector.
    # This is deliberately seeded by the constructor above: feeding arbitrary
    # odd phases to the mirrored selector reads misaligned ROM words.
    turning_phases = set(turning_seeds)
    pending = deque(sorted(turning_phases))
    while pending:
        phase = pending.popleft()
        for sequence in sequences:
            segment = SimpleNamespace(phase=phase, x=0x0180, y=0x0100,
                                      descriptor=0)
            turning(SimpleNamespace(rom=rom), segment,
                    _CollisionSequence(sequence))
            result.add(segment.descriptor)
            if segment.phase not in turning_phases:
                turning_phases.add(segment.phase)
                pending.append(segment.phase)

    mirrored_phases = set(mirrored_seeds)
    pending = deque(sorted(mirrored_phases))
    while pending:
        phase = pending.popleft()
        for collision in (clear, blocked):
            segment = SimpleNamespace(phase=phase, x=0x0180, y=0x0100,
                                      descriptor=0)
            mirrored(SimpleNamespace(rom=rom), segment,
                     _CollisionSequence((collision,)))
            result.add(segment.descriptor)
            if segment.phase not in mirrored_phases:
                mirrored_phases.add(segment.phase)
                pending.append(segment.phase)

    if turning_phases != {0, 2, 4, 6} or mirrored_phases != {0, 2}:
        raise SpriteCoverageError(
            "Force ray phase closure changed: "
            f"turning={sorted(turning_phases)!r}, "
            f"mirrored={sorted(mirrored_phases)!r}")

    update = _find_function(force_tree, "Force", "update_ray_segments")
    bases = {
        int(node.value.left.value)
        for node in ast.walk(update)
        if (isinstance(node, ast.Assign) and
            any(ast.unparse(target) == "segment.descriptor"
                for target in node.targets) and
            isinstance(node.value, ast.BinOp) and
            isinstance(node.value.op, ast.Add) and
            isinstance(node.value.left, ast.Constant) and
            isinstance(node.value.left.value, int) and
            ast.unparse(node.value.right) == "segment.terminal_offset")
    }
    if len(bases) != 1:
        raise SpriteCoverageError("Force ray terminal base is not one literal")
    result.update(_terminal_domain(
        force_tree, "ForceRaySegment", update, bases.pop()))
    if len(result) != 16:
        raise SpriteCoverageError(
            f"Force ray domain has {len(result)} descriptors, expected 16")
    return result, turning_seeds, mirrored_seeds


def _force_grid_addresses(force_tree: ast.Module) -> set[int]:
    update = _find_function(force_tree, "Force", "update_grid_segments")
    bases = _assigned_ints(update, "descriptor_base")
    if len(bases) != 2:
        raise SpriteCoverageError("Force grid has no exact two descriptor bases")
    active = {base + phase * 3 for base in bases for phase in (0, 2, 4, 6)}
    terminal_bases = {
        int(node.value.left.value)
        for node in ast.walk(update)
        if (isinstance(node, ast.Assign) and
            any(ast.unparse(target) == "segment.descriptor"
                for target in node.targets) and
            isinstance(node.value, ast.BinOp) and
            isinstance(node.value.op, ast.Add) and
            isinstance(node.value.left, ast.Constant) and
            isinstance(node.value.left.value, int) and
            ast.unparse(node.value.right) == "segment.terminal_offset")
    }
    if len(terminal_bases) != 1:
        raise SpriteCoverageError("Force grid terminal base is not one literal")
    result = active | _terminal_domain(
        force_tree, "ForceGridSegment", update, terminal_bases.pop())
    if len(result) != 11:
        raise SpriteCoverageError(
            f"Force grid domain has {len(result)} descriptors, expected 11")
    return result


def _keyword_int_domain(call: ast.Call, keyword_name: str) -> set[int]:
    keyword = next((item for item in call.keywords if item.arg == keyword_name), None)
    if keyword is None:
        raise SpriteCoverageError(f"ForceBeam lost keyword {keyword_name}")
    result = {
        int(item.value) for item in ast.walk(keyword.value)
        if isinstance(item, ast.Constant) and isinstance(item.value, int)
    }
    return result


def _force_beam_addresses(force_tree: ast.Module) -> set[int]:
    fire = _find_function(force_tree, "Force", "_fire_attached_type6")
    calls = [
        node for node in ast.walk(fire)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "ForceBeam"
    ]
    if len(calls) != 1:
        raise SpriteCoverageError("ForceBeam constructor is not unique")
    expansion_bases = _keyword_int_domain(calls[0], "expansion_base")
    flight_bases = _keyword_int_domain(calls[0], "flight_base")
    if len(expansion_bases) != 2 or len(flight_bases) != 2:
        raise SpriteCoverageError("ForceBeam bases are not two finite alternatives")

    update = _find_function(force_tree, "Force", "update_type6")
    base_domains: dict[str, tuple[int, int]] = {}
    for node in ast.walk(update):
        if (not isinstance(node, ast.Assign) or
                not any(isinstance(target, ast.Name) and target.id == "base"
                        for target in node.targets) or
                not isinstance(node.value, ast.BinOp) or
                not isinstance(node.value.op, ast.Add) or
                not isinstance(node.value.left, ast.Attribute)):
            continue
        name = node.value.left.attr
        if name not in ("expansion_base", "flight_base"):
            continue
        multiplier = next((
            int(item.right.value)
            for item in ast.walk(node.value.right)
            if (isinstance(item, ast.BinOp) and isinstance(item.op, ast.Mult) and
                isinstance(item.right, ast.Constant) and
                isinstance(item.right.value, int))
        ), None)
        mask = next((
            int(item.right.value)
            for item in ast.walk(node.value.right)
            if (isinstance(item, ast.BinOp) and isinstance(item.op, ast.BitAnd) and
                isinstance(item.right, ast.Constant) and
                isinstance(item.right.value, int))
        ), None)
        if multiplier is None or mask is None:
            raise SpriteCoverageError(f"ForceBeam {name} phase is not finite")
        base_domains[name] = (mask, multiplier)
    if set(base_domains) != {"expansion_base", "flight_base"}:
        raise SpriteCoverageError("ForceBeam update lost a phase domain")

    result: set[int] = set()
    for name, bases in (("expansion_base", expansion_bases),
                        ("flight_base", flight_bases)):
        mask, multiplier = base_domains[name]
        phases = {frame & mask for frame in range(256)}
        for base in bases:
            for phase in phases:
                for part in range(4):
                    result.add(base + phase * multiplier + part * 6)
    if len(result) != 192:
        raise SpriteCoverageError(
            f"Force beam domain has {len(result)} descriptors, expected 192")
    return result


def _force_dart_addresses(force_tree: ast.Module) -> set[int]:
    fire = _find_function(force_tree, "Force", "_fire_attached_type6")
    candidate_assign = next((
        node for node in ast.walk(fire)
        if isinstance(node, ast.AnnAssign) and
        isinstance(node.target, ast.Name) and node.target.id == "candidates"
    ), None)
    if candidate_assign is None or not isinstance(candidate_assign.value, ast.List):
        raise SpriteCoverageError("Force dart candidates are not a finite list")
    roots = {
        int(item.elts[2].value)
        for item in candidate_assign.value.elts
        if (isinstance(item, ast.Tuple) and len(item.elts) == 3 and
            isinstance(item.elts[2], ast.Constant) and
            isinstance(item.elts[2].value, int))
    }
    # The level-2 extension repeats the same two roots. Both front/rear variants
    # are emitted through the literal conditional offset in the constructor.
    constructor = next((
        node for node in ast.walk(fire)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "ForceDart"
    ), None)
    if constructor is None or len(constructor.args) < 4:
        raise SpriteCoverageError("ForceDart constructor disappeared")
    offset_literals = {
        int(item.value) for item in ast.walk(constructor.args[3])
        if isinstance(item, ast.Constant) and isinstance(item.value, int)
    }
    offsets = {0} | {value for value in offset_literals if value != 0}
    bases = {root + offset for root in roots for offset in offsets}

    update = _find_function(force_tree, "Force", "update_type6")
    descriptor_assignment = next((
        node for node in ast.walk(update)
        if (isinstance(node, ast.Assign) and
            any(ast.unparse(target) == "dart.descriptor" for target in node.targets) and
            "dart.descriptor_base" in ast.unparse(node.value) and
            "frame_counter" in ast.unparse(node.value))
    ), None)
    if descriptor_assignment is None:
        raise SpriteCoverageError("Force dart animation expression disappeared")
    expression = ast.Expression(copy.deepcopy(descriptor_assignment.value))
    ast.fix_missing_locations(expression)
    code = compile(expression, "<force-dart-domain>", "eval")
    active = {
        int(eval(code, {}, {
            "dart": SimpleNamespace(descriptor_base=base),
            "frame_counter": frame,
        }))
        for base in bases for frame in range(256)
    }

    terminal_assignment = next((
        node for node in ast.walk(update)
        if (isinstance(node, ast.Assign) and
            any(ast.unparse(target) == "dart.descriptor" for target in node.targets) and
            isinstance(node.value, ast.BinOp) and
            isinstance(node.value.left, ast.Constant) and
            isinstance(node.value.left.value, int) and
            ast.unparse(node.value.right) == "dart.terminal_offset")
    ), None)
    if terminal_assignment is None:
        raise SpriteCoverageError("Force dart terminal expression disappeared")
    terminal = _terminal_domain(
        force_tree, "ForceDart", update,
        int(terminal_assignment.value.left.value))
    result = active | terminal
    if len(result) != 15:
        raise SpriteCoverageError(
            f"Force dart domain has {len(result)} descriptors, expected 15")
    return result


def _bits_addresses(bits_tree: ast.Module) -> set[int]:
    update = _find_function(bits_tree, "PlayerBits", "_update_one")
    base_assignment = next((
        node for node in ast.walk(update)
        if isinstance(node, ast.Assign) and
        any(isinstance(target, ast.Name) and target.id == "descriptor_base"
            for target in node.targets)
    ), None)
    if base_assignment is None:
        raise SpriteCoverageError("Bits descriptor base disappeared")
    if not isinstance(base_assignment.value, ast.IfExp):
        raise SpriteCoverageError("Bits descriptor base is not a binary selector")
    try:
        bases = {
            int(ast.literal_eval(base_assignment.value.body)),
            int(ast.literal_eval(base_assignment.value.orelse)),
        }
    except (TypeError, ValueError) as exc:
        raise SpriteCoverageError(
            "Bits descriptor bases are no longer literals") from exc
    moduli = {
        int(item.right.value)
        for item in ast.walk(update)
        if (isinstance(item, ast.BinOp) and isinstance(item.op, ast.Mod) and
            isinstance(item.right, ast.Constant) and
            isinstance(item.right.value, int) and
            "bit.animation" in ast.unparse(item.left))
    }
    if len(bases) != 2 or len(moduli) != 1:
        raise SpriteCoverageError("Bits animation domain is not finite 2xN")
    count = moduli.pop()
    result = {base + phase * 6 for base in bases for phase in range(count)}
    if len(result) != 24:
        raise SpriteCoverageError(
            f"Bits domain has {len(result)} descriptors, expected 24")
    return result


def _death_addresses(lifecycle_tree: ast.Module) -> set[int]:
    ranges = _module_literal(lifecycle_tree, "DEATH_DESCRIPTOR_RANGES")
    if not isinstance(ranges, tuple):
        raise SpriteCoverageError("DEATH_DESCRIPTOR_RANGES is not a tuple")
    result = {
        int(record[2]) for record in ranges
        if isinstance(record, tuple) and len(record) == 3
    }
    function = _find_function(
        lifecycle_tree, "PlayerLifecycle", "explosion_descriptor")
    result.update(
        int(node.value.value)
        for node in ast.walk(function)
        if (isinstance(node, ast.Return) and
            isinstance(node.value, ast.Constant) and
            isinstance(node.value.value, int))
    )
    if len(result) != 8:
        raise SpriteCoverageError(
            f"death domain has {len(result)} descriptors, expected 8")
    return result


def _terminal_shot_addresses(game_tree: ast.Module) -> set[int]:
    game_class = _find_class(game_tree, "Game")
    update = _find_function(game_tree, "Game", "update")
    # The two terminal initialisers intentionally live in different methods:
    # terrain impact is initialised by ``_advance_native_shot`` while an enemy
    # impact is converted in ``update``.  Scan the active Game class, rather
    # than copying the two ROM descriptor bases into the compiler.
    bases = _assigned_ints(game_class, "shot.terminal_base")
    timers = _assigned_ints(game_class, "shot.terminal_timer")
    expressions = [
        ast.unparse(node.value)
        for node in ast.walk(update)
        if (isinstance(node, ast.Assign) and
            any(ast.unparse(target) == "shot.terminal_descriptor"
                for target in node.targets) and
            not isinstance(node.value, ast.Constant))
    ]
    reset_values = _assigned_ints(update, "shot.terminal_descriptor")
    if (len(bases) != 2 or timers != {3} or reset_values != {0} or expressions !=
            ["shot.terminal_base + shot.terminal_timer * 6"]):
        raise SpriteCoverageError("terminal-shot descriptor domain changed")
    result = {base + timer * 6 for base in bases for timer in range(1, 4)}
    if len(result) != 6:
        raise SpriteCoverageError("terminal-shot domain is not six descriptors")
    return result


def _fixed_shot_address(enemy_tree: ast.Module) -> int:
    function = _find_function(
        enemy_tree, "PlayerShotVisual4EAF", "__init__")
    calls = [
        node for node in ast.walk(function)
        if (isinstance(node, ast.Call) and
            isinstance(node.func, ast.Attribute) and node.func.attr == "__init__" and
            ast.unparse(node.func.value) == "super()")
    ]
    if len(calls) != 1 or len(calls[0].args) < 5:
        raise SpriteCoverageError("PlayerShotVisual4EAF descriptor disappeared")
    try:
        value = ast.literal_eval(calls[0].args[4])
    except (TypeError, ValueError) as exc:
        raise SpriteCoverageError(
            "PlayerShotVisual4EAF descriptor is not literal") from exc
    if not isinstance(value, int):
        raise SpriteCoverageError("PlayerShotVisual4EAF descriptor is not int")
    return value


def resolve_python_bank(project_root: Path | str, palette: int,
                        resource_type: int) -> PythonBankKey:
    """Resolve exactly the same typed/fallback key as active Python ``_asset``."""

    root = Path(project_root).resolve()
    resource_type &= 0xFF
    palette &= 0x0F
    arcade = root / "Assets" / "Converted" / "Arcade"
    typed = arcade / "ResourceHQ" / (
        f"RTYPE_SPRITES_TYPE{resource_type:02X}_HQ_ARGB4444.bin")
    if typed.is_file():
        return PythonBankKey("typed-resource", resource_type)
    fallback = arcade / "FullHQ" / (
        f"RTYPE_SPRITES_PAL{palette:02X}_HQ_ARGB4444.bin")
    if not fallback.is_file():
        raise SpriteCoverageError(
            "active Python palette fallback is missing: " + str(fallback))
    return PythonBankKey("palette-fallback", palette)


def _pair(project_root: Path, rom: _WorldRom, resource_type: int,
          descriptor_address: int) -> DescriptorResourcePair:
    resource_type &= 0xFF
    banks = tuple(sorted({
        resolve_python_bank(project_root, palette, resource_type)
        for palette in range(16)
    }))
    return DescriptorResourcePair(
        resource_type=resource_type,
        descriptor=rom.descriptor(descriptor_address),
        bank_keys=banks,
    )


# ---------------------------------------------------------------------------
# Stage enemy coverage
# ---------------------------------------------------------------------------

_ABSTRACT_UNKNOWN = object()
_ABSTRACT_U16 = object()
_DOMAIN_LIMIT = 0x10000


@dataclass(frozen=True)
class _FrozenMap:
    items: tuple[tuple[object, object], ...]

    def lookup(self, key: object) -> object:
        for candidate, value in self.items:
            if candidate == key:
                return value
        raise KeyError(key)


def _frozen_literal(value: object) -> object:
    if isinstance(value, dict):
        return _FrozenMap(tuple(
            (_frozen_literal(key), _frozen_literal(item))
            for key, item in value.items()
        ))
    if isinstance(value, list):
        return tuple(_frozen_literal(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_frozen_literal(item) for item in value)
    if isinstance(value, set):
        return frozenset(_frozen_literal(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_frozen_literal(item) for item in value)
    return value


def _safe_ast_literal(node: ast.AST) -> object:
    try:
        return _frozen_literal(ast.literal_eval(node))
    except (TypeError, ValueError):
        if (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name) and
                node.func.id == "frozenset" and len(node.args) == 1 and
                not node.keywords):
            value = _safe_ast_literal(node.args[0])
            if isinstance(value, (tuple, frozenset)):
                return frozenset(value)
        return _ABSTRACT_UNKNOWN


def _finite(value: object) -> frozenset[object] | None:
    return value if isinstance(value, frozenset) else None


def _one_domain(value: object) -> frozenset[object]:
    return frozenset((_frozen_literal(value),))


def _merge_domain(old: object, new: object) -> tuple[object, bool]:
    if new is _ABSTRACT_UNKNOWN:
        return old, False
    if old is _ABSTRACT_UNKNOWN:
        return new, True
    if old is _ABSTRACT_U16 or new is _ABSTRACT_U16:
        return _ABSTRACT_U16, old is not _ABSTRACT_U16
    old_values = _finite(old)
    new_values = _finite(new)
    if old_values is None or new_values is None:
        return old, False
    merged = old_values | new_values
    if len(merged) > _DOMAIN_LIMIT:
        merged_value: object = _ABSTRACT_U16
    else:
        merged_value = merged
    return merged_value, merged_value != old


def _submasks(mask: int) -> frozenset[object]:
    mask &= 0xFFFF
    result: set[object] = set()
    value = mask
    while True:
        result.add(value)
        if value == 0:
            return frozenset(result)
        value = (value - 1) & mask


def _int_values(domain: object) -> frozenset[int] | None:
    values = _finite(domain)
    if values is None or not all(
            isinstance(item, int) for item in values):
        return None
    return frozenset(int(item) for item in values)


def _apply_binary(operator: ast.operator, left: object,
                  right: object) -> object:
    left_values = _int_values(left)
    right_values = _int_values(right)
    if isinstance(operator, ast.BitAnd):
        if left is _ABSTRACT_U16 and right_values is not None:
            return frozenset().union(*(_submasks(value)
                                       for value in right_values))
        if right is _ABSTRACT_U16 and left_values is not None:
            return frozenset().union(*(_submasks(value)
                                       for value in left_values))
    if isinstance(operator, ast.Mod):
        if left is _ABSTRACT_U16 and right_values is not None:
            if all(0 < value <= 0x100 for value in right_values):
                return frozenset(
                    item for value in right_values for item in range(value))
    if isinstance(operator, (ast.Add, ast.Sub, ast.BitXor)):
        if (left is _ABSTRACT_U16 or right is _ABSTRACT_U16):
            return _ABSTRACT_U16
    if isinstance(operator, ast.RShift) and left is _ABSTRACT_U16:
        if right_values is not None and right_values:
            result: set[object] = set()
            for shift in right_values:
                if 0 <= shift <= 16:
                    result.update(range(1 << (16 - shift)))
            return (frozenset(result) if len(result) <= _DOMAIN_LIMIT
                    else _ABSTRACT_U16)
    if left is _ABSTRACT_U16 or right is _ABSTRACT_U16:
        return _ABSTRACT_UNKNOWN
    if left_values is None or right_values is None:
        return _ABSTRACT_UNKNOWN
    if len(left_values) * len(right_values) > 0x40000:
        return _ABSTRACT_UNKNOWN
    result: set[object] = set()
    for lhs in left_values:
        for rhs in right_values:
            try:
                if isinstance(operator, ast.Add):
                    value = lhs + rhs
                elif isinstance(operator, ast.Sub):
                    value = lhs - rhs
                elif isinstance(operator, ast.Mult):
                    value = lhs * rhs
                elif isinstance(operator, ast.FloorDiv):
                    value = lhs // rhs
                elif isinstance(operator, ast.Mod):
                    value = lhs % rhs
                elif isinstance(operator, ast.LShift):
                    value = lhs << rhs
                elif isinstance(operator, ast.RShift):
                    value = lhs >> rhs
                elif isinstance(operator, ast.BitOr):
                    value = lhs | rhs
                elif isinstance(operator, ast.BitXor):
                    value = lhs ^ rhs
                elif isinstance(operator, ast.BitAnd):
                    value = lhs & rhs
                else:
                    return _ABSTRACT_UNKNOWN
            except (ArithmeticError, ValueError):
                return _ABSTRACT_UNKNOWN
            result.add(value)
            if len(result) > _DOMAIN_LIMIT:
                return _ABSTRACT_U16
    return frozenset(result)


def _class_constant(tree: ast.Module, class_name: str,
                    name: str) -> object:
    class_node = _find_class(tree, class_name)
    for node in class_node.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if (value is not None and any(
                isinstance(target, ast.Name) and target.id == name
                for target in targets)):
            literal = _safe_ast_literal(value)
            if literal is _ABSTRACT_UNKNOWN:
                raise SpriteCoverageError(
                    f"{class_name}.{name} is not a static Python constant")
            return literal
    raise SpriteCoverageError(
        f"active Python class constant disappeared: {class_name}.{name}")


@dataclass(frozen=True)
class _StageEventRecord:
    address: int
    threshold: int
    command: int
    handler: int


@dataclass
class _StageAbstractResult:
    descriptors: dict[str, set[int]]
    overlays: dict[str, set[int]]
    resources: dict[str, set[int]]
    descriptor_sink_values: dict[str, set[int]]
    resource_sink_values: dict[str, set[int]]
    transient_sink_values: dict[str, tuple[set[int], set[int]]]
    parameter_domains: tuple[
        tuple[tuple[str, str, str], tuple[object, ...]], ...]
    field_domains: tuple[
        tuple[tuple[str, str], tuple[object, ...]], ...]
    transient_pairs: set[tuple[int, int]]
    sink_ids: set[str]
    unresolved: set[str]

    def parameter_domain(self, class_name: str, function_name: str,
                         name: str) -> frozenset[object] | None:
        key = (class_name, function_name, name)
        return next((frozenset(values) for item, values in
                     self.parameter_domains if item == key), None)

    def field_domain(self, class_name: str,
                     name: str) -> frozenset[object] | None:
        key = (class_name, name)
        return next((frozenset(values) for item, values in
                     self.field_domains if item == key), None)

    def replace_parameter_domain(
            self, class_name: str, function_name: str, name: str,
            values: Iterable[object],
            ) -> None:
        """Install one deterministic finite domain at the result boundary."""
        key = (class_name, function_name, name)
        mapping = dict(self.parameter_domains)
        domain = tuple(sorted(set(values), key=repr))
        if not domain:
            raise SpriteCoverageError(
                f"{class_name}.{function_name}.{name} domain is empty")
        mapping[key] = domain
        self.parameter_domains = tuple(sorted(mapping.items()))


class _StageAbstractInterpreter:
    """Flow-insensitive finite-domain evaluator for active enemy selectors.

    It deliberately interprets only immutable arithmetic, ROM reads and
    literal Python containers. Unknown operations do not widen silently: a
    descriptor/resource sink which still depends on one is reported and the
    public analysis fails closed.
    """

    def __init__(self, tree: ast.Module, rom: _WorldRom,
                 reachable: set[str], command_domains: Mapping[str, set[int]]) -> None:
        self.tree = tree
        self.rom = rom
        self.classes = {
            node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.reachable = set(reachable)
        self.command_domains = {
            name: frozenset(values) for name, values in command_domains.items()
        }
        self.functions: dict[tuple[str, str], ast.FunctionDef] = {}
        for class_name, class_node in self.classes.items():
            if class_name not in self.reachable and class_name != "ScriptedMotion":
                continue
            for node in class_node.body:
                if isinstance(node, ast.FunctionDef):
                    self.functions[(class_name, node.name)] = node
        module_functions = {
            node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        called_module_functions: set[str] = set()
        pending_module_functions: list[str] = []
        for (owner, _method), function in self.functions.items():
            if not owner:
                continue
            for call in ast.walk(function):
                if (isinstance(call, ast.Call) and
                        isinstance(call.func, ast.Name) and
                        call.func.id in module_functions and
                        call.func.id not in called_module_functions):
                    called_module_functions.add(call.func.id)
                    pending_module_functions.append(call.func.id)
        while pending_module_functions:
            name = pending_module_functions.pop()
            function = module_functions[name]
            for call in ast.walk(function):
                if (isinstance(call, ast.Call) and
                        isinstance(call.func, ast.Name) and
                        call.func.id in module_functions and
                        call.func.id not in called_module_functions):
                    called_module_functions.add(call.func.id)
                    pending_module_functions.append(call.func.id)
        for name in called_module_functions:
            self.functions[("", name)] = module_functions[name]
        self.module_callers: dict[str, set[str]] = {}
        for (owner, _method), function in self.functions.items():
            if not owner:
                continue
            for call in ast.walk(function):
                if (isinstance(call, ast.Call) and
                        isinstance(call.func, ast.Name) and
                        ("", call.func.id) in self.functions):
                    self.module_callers.setdefault(call.func.id, set()).add(owner)
        self.bases = {
            name: tuple(ast.unparse(base) for base in node.bases)
            for name, node in self.classes.items()
        }
        self.module_constants: dict[str, object] = {}
        self.class_constants: dict[tuple[str, str], object] = {}
        self._load_constants()
        self.locals: dict[tuple[str, str, str], object] = {}
        self.params: dict[tuple[str, str, str], object] = {}
        self.fields: dict[tuple[str, str], object] = {}
        self.returns: dict[tuple[str, str], object] = {}
        self.descriptors: dict[str, set[int]] = {
            name: set() for name in self.reachable
        }
        self.overlays: dict[str, set[int]] = {
            name: set() for name in self.reachable
        }
        self.resources: dict[str, set[int]] = {
            name: set() for name in self.reachable
        }
        # Preserve relational ownership instead of retaining only the class
        # unions.  The stage pair builder consumes these exact sink domains;
        # class unions remain useful solely for diagnostics/inheritance.
        self.descriptor_sink_values: dict[str, set[int]] = {}
        self.resource_sink_values: dict[str, set[int]] = {}
        self.transient_pairs: set[tuple[int, int]] = set()
        self.transient_sink_values: dict[
            str, tuple[set[int], set[int]]] = {}
        self.sink_ids: set[str] = set()
        self.unresolved: set[str] = set()
        self._seed_parameters()

    def _load_constants(self) -> None:
        for node in self.tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if value is None:
                    continue
                literal = _safe_ast_literal(value)
                if literal is _ABSTRACT_UNKNOWN:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.module_constants[target.id] = literal
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                        continue
                    targets = (item.targets if isinstance(item, ast.Assign)
                               else [item.target])
                    value = item.value
                    if value is None:
                        continue
                    literal = _safe_ast_literal(value)
                    if literal is _ABSTRACT_UNKNOWN:
                        continue
                    for target in targets:
                        if isinstance(target, ast.Name):
                            self.class_constants[(node.name, target.id)] = literal

    def _seed_parameters(self) -> None:
        for (class_name, function_name), function in self.functions.items():
            arguments = list(function.args.posonlyargs) + list(function.args.args)
            defaults = [None] * (len(arguments) - len(function.args.defaults)) + list(
                function.args.defaults)
            for argument, default in zip(arguments, defaults):
                if argument.arg in ("self", "world", "rom", "target"):
                    continue
                domain: object = _ABSTRACT_UNKNOWN
                if default is not None:
                    literal = _safe_ast_literal(default)
                    if literal is not _ABSTRACT_UNKNOWN:
                        domain = _one_domain(literal)
                annotation = ast.unparse(argument.annotation) if argument.annotation else ""
                if (function_name in ("update", "take_damage", "player_contact") and
                        annotation == "int"):
                    domain = _ABSTRACT_U16
                if class_name == "" and annotation == "int":
                    domain = _ABSTRACT_U16
                if domain is not _ABSTRACT_UNKNOWN:
                    self.params[(class_name, function_name, argument.arg)] = domain

        for class_name, commands in self.command_domains.items():
            function = self.functions.get((class_name, "__init__"))
            if function is None:
                continue
            if any(argument.arg == "command" for argument in function.args.args):
                self.params[(class_name, "__init__", "command")] = commands

        checkpoint = self.module_constants.get(
            "STAGE1_CHECKPOINT_PARTICLES", _ABSTRACT_UNKNOWN)
        if isinstance(checkpoint, tuple) and checkpoint:
            self.params[("BackgroundParticleE5CD",
                         "from_stage1_checkpoint", "record")] = frozenset(
                             checkpoint)

        # Values exposed by the active world, not guessed host timing.
        for key, function in self.functions.items():
            for argument in function.args.args:
                if argument.arg in ("frame", "frame_counter", "foreground_delta"):
                    self.params[(key[0], key[1], argument.arg)] = _ABSTRACT_U16

    def _base_chain(self, class_name: str) -> tuple[str, ...]:
        result: list[str] = []
        pending = [class_name]
        while pending:
            current = pending.pop()
            for base in self.bases.get(current, ()):
                if base in self.classes and base not in result:
                    result.append(base)
                    pending.append(base)
        return tuple(result)

    def _constant_value(self, class_name: str, node: ast.AST) -> object:
        if isinstance(node, ast.Name):
            return self.module_constants.get(node.id, _ABSTRACT_UNKNOWN)
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in ("self", class_name):
                for owner in (class_name,) + self._base_chain(class_name):
                    value = self.class_constants.get((owner, node.attr),
                                                     _ABSTRACT_UNKNOWN)
                    if value is not _ABSTRACT_UNKNOWN:
                        return value
        return _ABSTRACT_UNKNOWN

    def _lookup_field(self, class_name: str, attr: str) -> object:
        result: object = _ABSTRACT_UNKNOWN
        for owner in (class_name,) + self._base_chain(class_name):
            value = self.fields.get((owner, attr), _ABSTRACT_UNKNOWN)
            result, _ = _merge_domain(result, value)
        return result

    def _lookup_any_field(self, attr: str) -> object:
        result: object = _ABSTRACT_UNKNOWN
        for owner in self.reachable | {"ScriptedMotion"}:
            result, _ = _merge_domain(
                result, self.fields.get((owner, attr), _ABSTRACT_UNKNOWN))
        return result

    def _eval(self, class_name: str, function_name: str,
              node: ast.AST | None) -> object:
        if node is None:
            return _ABSTRACT_UNKNOWN
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, str, bool)) or node.value is None:
                return _one_domain(node.value)
            return _ABSTRACT_UNKNOWN
        if isinstance(node, (ast.Tuple, ast.List)):
            items = [self._eval(class_name, function_name, item)
                     for item in node.elts]
            finite = [_finite(item) for item in items]
            if any(item is None for item in finite):
                return _ABSTRACT_UNKNOWN
            product: list[tuple[object, ...]] = [()]
            for values in finite:
                assert values is not None
                product = [prefix + (value,) for prefix in product
                           for value in values]
                if len(product) > _DOMAIN_LIMIT:
                    return _ABSTRACT_UNKNOWN
            return frozenset(product)
        if isinstance(node, ast.Name):
            for mapping_key in (
                    (class_name, function_name, node.id),):
                if mapping_key in self.locals:
                    return self.locals[mapping_key]
                if mapping_key in self.params:
                    return self.params[mapping_key]
            value = self.module_constants.get(node.id, _ABSTRACT_UNKNOWN)
            if value is not _ABSTRACT_UNKNOWN:
                return _one_domain(value)
            return _ABSTRACT_UNKNOWN
        if isinstance(node, ast.Attribute):
            constant = self._constant_value(class_name, node)
            if constant is not _ABSTRACT_UNKNOWN:
                return _one_domain(constant)
            text = ast.unparse(node.value)
            if class_name == "" and text == "enemy":
                result: object = _ABSTRACT_UNKNOWN
                for owner in self.module_callers.get(function_name, ()):
                    value = self._lookup_field(owner, node.attr)
                    if (value is _ABSTRACT_UNKNOWN and node.attr == "descriptor"):
                        addresses = self.descriptors.get(owner, set())
                        value = (frozenset(addresses) if addresses
                                 else _ABSTRACT_UNKNOWN)
                    result, _ = _merge_domain(result, value)
                return result
            if text == "self":
                value = self._lookup_field(class_name, node.attr)
                # Pool slots are words supplied by M72ObjectPool rather than
                # constructor arguments.  Their exact value is irrelevant to
                # sprite selection until the active code masks it.
                if value is _ABSTRACT_UNKNOWN and node.attr == "object_slot":
                    return _ABSTRACT_U16
                return value
            if text.endswith(".motion") and node.attr == "phase":
                return self._lookup_field("ScriptedMotion", "phase")
            if text == "world" and node.attr in (
                    "frame_counter", "projectile_spawns",
                    "background_delta", "foreground_delta"):
                return _ABSTRACT_U16
            if text == "world" and node.attr == "difficulty":
                return frozenset(range(4))
            return self._lookup_any_field(node.attr)
        if isinstance(node, ast.BoolOp):
            # The selector code only uses ``value or literal`` / finite
            # boolean alternatives.  Union is the exact value domain without
            # pretending to prove which truth branch was taken.
            result: object = _ABSTRACT_UNKNOWN
            for item in node.values:
                result, _ = _merge_domain(
                    result, self._eval(class_name, function_name, item))
            return result
        if isinstance(node, ast.IfExp):
            left = self._eval(class_name, function_name, node.body)
            right = self._eval(class_name, function_name, node.orelse)
            merged, _ = _merge_domain(left, right)
            return merged
        if isinstance(node, ast.BinOp):
            return _apply_binary(
                node.op,
                self._eval(class_name, function_name, node.left),
                self._eval(class_name, function_name, node.right),
            )
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(class_name, function_name, node.operand)
            values = _int_values(operand)
            if values is None:
                return _ABSTRACT_U16 if operand is _ABSTRACT_U16 else _ABSTRACT_UNKNOWN
            if isinstance(node.op, ast.USub):
                return frozenset(-value for value in values)
            if isinstance(node.op, ast.UAdd):
                return frozenset(values)
            if isinstance(node.op, ast.Invert):
                return frozenset(~value for value in values)
            if isinstance(node.op, ast.Not):
                return frozenset(not value for value in values)
            return _ABSTRACT_UNKNOWN
        if isinstance(node, ast.Subscript):
            if ast.unparse(node.value) == "world.resources.types":
                resources = self.resources.get(class_name, set())
                return (frozenset(resources) if resources
                        else _ABSTRACT_UNKNOWN)
            container = self._constant_value(class_name, node.value)
            if container is _ABSTRACT_UNKNOWN:
                container_domain = self._eval(class_name, function_name, node.value)
                containers = _finite(container_domain)
            else:
                containers = frozenset((container,))
            indexes = _finite(self._eval(class_name, function_name, node.slice))
            if containers is None or indexes is None:
                return _ABSTRACT_UNKNOWN
            result: set[object] = set()
            for item in containers:
                for index in indexes:
                    try:
                        if isinstance(item, tuple) and isinstance(index, int):
                            result.add(_frozen_literal(item[index]))
                        elif isinstance(item, frozenset):
                            values = tuple(sorted(item))
                            if isinstance(index, int):
                                result.add(_frozen_literal(values[index]))
                        elif isinstance(item, _FrozenMap):
                            result.add(_frozen_literal(item.lookup(index)))
                    except (IndexError, KeyError, TypeError):
                        continue
            return frozenset(result) if result else _ABSTRACT_UNKNOWN
        if isinstance(node, ast.Call):
            function_text = ast.unparse(node.func)
            if function_text.endswith(".word") and node.args:
                address_expression = node.args[0]
                # A zero pointer is an inactive-state sentinel even when the
                # ROM operand is ``self.sequence_pointer + 2`` rather than
                # the bare field.  Bind the non-zero cursor before evaluating
                # the address expression; filtering the already-added result
                # would not tell `$0002` from a legitimate ROM address.
                pointer_nodes: dict[str, ast.Attribute] = {}
                for item in ast.walk(address_expression):
                    if (isinstance(item, ast.Attribute) and
                            ast.unparse(item.value) == "self" and
                            ("pointer" in item.attr or
                             "sequence" in item.attr)):
                        pointer_nodes.setdefault(ast.unparse(item), item)
                pointer_domains: list[tuple[str, tuple[int, ...]]] = []
                for text, item in sorted(pointer_nodes.items()):
                    values = _int_values(self._eval(
                        class_name, function_name, item))
                    if values is not None and 0 in values and len(values) > 1:
                        pointer_domains.append((
                            text, tuple(sorted(value for value in values
                                               if value != 0))))
                if pointer_domains:
                    class PointerBinder(ast.NodeTransformer):
                        def __init__(self, values: Mapping[str, int]) -> None:
                            self.values = values

                        def visit_Attribute(self, item: ast.Attribute) -> ast.AST:
                            text = ast.unparse(item)
                            if text in self.values:
                                return ast.copy_location(
                                    ast.Constant(self.values[text]), item)
                            return self.generic_visit(item)

                    valuations: list[dict[str, int]] = [{}]
                    for text, values in pointer_domains:
                        valuations = [dict(previous, **{text: value})
                                      for previous in valuations
                                      for value in values]
                    address_values: set[int] = set()
                    for valuation in valuations:
                        bound = PointerBinder(valuation).visit(
                            copy.deepcopy(address_expression))
                        values = _int_values(self._eval(
                            class_name, function_name, bound))
                        if values is not None:
                            address_values.update(values)
                    addresses = (frozenset(address_values)
                                 if address_values else None)
                else:
                    addresses = _int_values(self._eval(
                        class_name, function_name, address_expression))
                if addresses is None:
                    return _ABSTRACT_UNKNOWN
                if (isinstance(address_expression, ast.Attribute) and
                        "pointer" in address_expression.attr and
                        len(addresses) > 1):
                    addresses = frozenset(
                        address for address in addresses if address != 0)
                return frozenset(self.rom.word(address) for address in addresses)
            if function_text.endswith(".byte") and node.args:
                addresses = _int_values(self._eval(
                    class_name, function_name, node.args[0]))
                if addresses is None:
                    return _ABSTRACT_UNKNOWN
                return frozenset(self.rom.byte(address) for address in addresses)
            if function_text.endswith(".next"):
                return _ABSTRACT_U16
            if function_text.endswith(".bit_count"):
                owner = (node.func.value if isinstance(node.func, ast.Attribute)
                         else None)
                values = _int_values(self._eval(class_name, function_name, owner))
                return (frozenset(value.bit_count() for value in values)
                        if values is not None else _ABSTRACT_UNKNOWN)
            simple = node.func.id if isinstance(node.func, ast.Name) else ""
            if simple == "enumerate" and node.args:
                containers = _finite(self._eval(
                    class_name, function_name, node.args[0]))
                if containers is None:
                    return _ABSTRACT_UNKNOWN
                starts = ({0} if len(node.args) == 1 else
                          _int_values(self._eval(
                              class_name, function_name, node.args[1])))
                if starts is None:
                    return _ABSTRACT_UNKNOWN
                result: set[object] = set()
                for container in containers:
                    if not isinstance(container, tuple):
                        continue
                    for start in starts:
                        result.add(tuple(enumerate(container, start)))
                return (frozenset(result) if result
                        else _ABSTRACT_UNKNOWN)
            if simple in ("_u16", "_signed_word", "_s8", "int", "bool"):
                if not node.args:
                    return _ABSTRACT_UNKNOWN
                value = self._eval(class_name, function_name, node.args[0])
                values = _int_values(value)
                if value is _ABSTRACT_U16:
                    return _ABSTRACT_U16
                if values is None:
                    return _ABSTRACT_UNKNOWN
                if simple == "_u16":
                    return frozenset(item & 0xFFFF for item in values)
                if simple == "_signed_word":
                    return frozenset(
                        (item & 0xFFFF) - 0x10000
                        if item & 0x8000 else item & 0xFFFF
                        for item in values)
                if simple == "_s8":
                    return frozenset(item - 0x100 if item & 0x80 else item
                                     for item in values)
                if simple == "bool":
                    return frozenset(bool(item) for item in values)
                return frozenset(int(item) for item in values)
            if simple in ("abs", "round") and node.args:
                values = _int_values(self._eval(
                    class_name, function_name, node.args[0]))
                if values is None:
                    return _ABSTRACT_UNKNOWN
                return frozenset(abs(value) if simple == "abs" else round(value)
                                 for value in values)
            if simple in ("min", "max") and node.args:
                domains = [self._eval(class_name, function_name, arg)
                           for arg in node.args]
                finite = [_int_values(item) for item in domains]
                if any(item is None for item in finite):
                    return _ABSTRACT_UNKNOWN
                result = finite[0]
                assert result is not None
                for values in finite[1:]:
                    assert values is not None
                    result = frozenset(
                        (min(lhs, rhs) if simple == "min" else max(lhs, rhs))
                        for lhs in result for rhs in values)
                return result
            if simple == "getattr" and len(node.args) >= 3:
                attr_values = _finite(self._eval(
                    class_name, function_name, node.args[1]))
                default = self._eval(class_name, function_name, node.args[2])
                result = default
                if attr_values is not None:
                    for attr in attr_values:
                        if isinstance(attr, str):
                            result, _ = _merge_domain(
                                result, self._lookup_any_field(attr))
                return result
            if isinstance(node.func, ast.Attribute) and ast.unparse(
                    node.func.value) == "self":
                owner = self._method_owner(class_name, node.func.attr)
                return self.returns.get((owner, node.func.attr),
                                        _ABSTRACT_UNKNOWN)
            if simple and ("", simple) in self.functions:
                return self.returns.get(("", simple), _ABSTRACT_UNKNOWN)
        return _ABSTRACT_UNKNOWN

    def _method_owner(self, class_name: str, method: str) -> str:
        for owner in (class_name,) + self._base_chain(class_name):
            if (owner, method) in self.functions:
                return owner
        return class_name

    def _eval_correlated(self, class_name: str, function_name: str,
                         node: ast.AST | None) -> object:
        """Evaluate repeated finite selector operands with shared identity.

        A plain set product loses that ``phase`` in ``base + phase +
        (phase >> 1)`` is the same value twice and invents intermediate ROM
        addresses.  Bind repeated locals/fields once per valuation before
        joining results.
        """
        if node is None:
            return _ABSTRACT_UNKNOWN
        occurrences: Counter[str] = Counter()
        representatives: dict[str, ast.AST] = {}
        for item in ast.walk(node):
            key = ""
            if isinstance(item, ast.Name):
                local_key = (class_name, function_name, item.id)
                if local_key in self.locals or local_key in self.params:
                    key = item.id
            elif (isinstance(item, ast.Attribute) and
                  ast.unparse(item.value) == "self"):
                key = ast.unparse(item)
            if key:
                occurrences[key] += 1
                representatives.setdefault(key, item)
        domains: list[tuple[str, tuple[int, ...]]] = []
        product_size = 1
        for key in sorted(name for name, count in occurrences.items()
                          if count > 1):
            values = _int_values(self._eval(
                class_name, function_name, representatives[key]))
            if values is None or len(values) <= 1:
                continue
            product_size *= len(values)
            if product_size > 0x10000:
                return self._eval(class_name, function_name, node)
            domains.append((key, tuple(sorted(values))))
        if not domains:
            return self._eval(class_name, function_name, node)

        class Binder(ast.NodeTransformer):
            def __init__(self, values: Mapping[str, int]) -> None:
                self.values = values

            def visit_Name(self, item: ast.Name) -> ast.AST:
                if item.id in self.values:
                    return ast.copy_location(
                        ast.Constant(self.values[item.id]), item)
                return item

            def visit_Attribute(self, item: ast.Attribute) -> ast.AST:
                text = ast.unparse(item)
                if text in self.values:
                    return ast.copy_location(
                        ast.Constant(self.values[text]), item)
                return self.generic_visit(item)

        valuations: list[dict[str, int]] = [{}]
        for key, values in domains:
            valuations = [dict(previous, **{key: value})
                          for previous in valuations for value in values]
        result: object = _ABSTRACT_UNKNOWN
        for valuation in valuations:
            expression = Binder(valuation).visit(copy.deepcopy(node))
            value = self._eval(class_name, function_name, expression)
            result, _ = _merge_domain(result, value)
        return result

    def _eval_with_local_env(self, class_name: str, function_name: str,
                             node: ast.AST, env: Mapping[str, object]) -> object:
        prefix = (class_name, function_name)
        saved = {key: value for key, value in self.locals.items()
                 if key[:2] == prefix}
        for key in tuple(self.locals):
            if key[:2] == prefix:
                del self.locals[key]
        for name, value in env.items():
            self.locals[(class_name, function_name, name)] = value
        try:
            return self._eval_correlated(class_name, function_name, node)
        finally:
            for key in tuple(self.locals):
                if key[:2] == prefix:
                    del self.locals[key]
            self.locals.update(saved)

    @staticmethod
    def _merge_local_envs(environments: Iterable[Mapping[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for environment in environments:
            for name, value in environment.items():
                merged, _ = _merge_domain(
                    result.get(name, _ABSTRACT_UNKNOWN), value)
                if merged is not _ABSTRACT_UNKNOWN:
                    result[name] = merged
        return result

    def _store_local_env(self, target: ast.AST, value: object,
                         env: dict[str, object]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            tuples = _finite(value)
            if tuples is None:
                return
            for index, item_target in enumerate(target.elts):
                values = frozenset(
                    item[index] for item in tuples
                    if isinstance(item, tuple) and
                    len(item) == len(target.elts))
                if values:
                    self._store_local_env(item_target, values, env)

    def _exec_local_block(self, class_name: str, function_name: str,
                          statements: Iterable[ast.stmt],
                          initial: Mapping[str, object]) -> dict[str, object]:
        env = dict(initial)
        for statement in statements:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                if statement.value is None:
                    continue
                value = self._eval_with_local_env(
                    class_name, function_name, statement.value, env)
                targets = (statement.targets if isinstance(statement, ast.Assign)
                           else [statement.target])
                for target in targets:
                    if isinstance(target, (ast.Name, ast.Tuple, ast.List)):
                        self._store_local_env(target, value, env)
            elif isinstance(statement, ast.AugAssign) and isinstance(
                    statement.target, ast.Name):
                current = env.get(
                    statement.target.id,
                    self._eval_with_local_env(
                        class_name, function_name, statement.target, env))
                values = _int_values(current)
                updated: object = _ABSTRACT_UNKNOWN
                if values is not None:
                    for bound in values:
                        bound_env = dict(env)
                        bound_env[statement.target.id] = _one_domain(bound)
                        rhs = self._eval_with_local_env(
                            class_name, function_name,
                            statement.value, bound_env)
                        item = _apply_binary(
                            statement.op, _one_domain(bound), rhs)
                        updated, _ = _merge_domain(updated, item)
                if updated is not _ABSTRACT_UNKNOWN:
                    env[statement.target.id] = updated
            elif isinstance(statement, ast.If):
                body = self._exec_local_block(
                    class_name, function_name, statement.body, env)
                alternate = self._exec_local_block(
                    class_name, function_name, statement.orelse, env)
                env = self._merge_local_envs((body, alternate))
            elif isinstance(statement, ast.For):
                domain = self._eval_with_local_env(
                    class_name, function_name, statement.iter, env)
                values = _finite(domain)
                iterable: set[object] = set()
                if values is not None:
                    for item in values:
                        if isinstance(item, (tuple, frozenset)):
                            iterable.update(item)
                        else:
                            iterable.add(item)
                iterations: list[dict[str, object]] = [dict(env)]
                if iterable:
                    loop_env = dict(env)
                    self._store_local_env(
                        statement.target, frozenset(iterable), loop_env)
                    iterations.append(self._exec_local_block(
                        class_name, function_name, statement.body, loop_env))
                env = self._merge_local_envs(iterations)
        return env

    def _eval_at_statement(self, class_name: str, function_name: str,
                           function: ast.FunctionDef, target: ast.stmt,
                           expression: ast.AST) -> object:
        """Evaluate a sink with lexical local assignment/branch semantics."""
        path: list[tuple[list[ast.stmt], int]] = []

        def locate(statements: list[ast.stmt]) -> bool:
            for index, statement in enumerate(statements):
                if statement is target:
                    path.append((statements, index))
                    return True
                child_lists: list[list[ast.stmt]] = []
                for field in ("body", "orelse", "finalbody"):
                    value = getattr(statement, field, None)
                    if isinstance(value, list):
                        child_lists.append(value)
                for child in child_lists:
                    if locate(child):
                        path.append((statements, index))
                        return True
            return False

        if not locate(function.body):
            return self._eval_correlated(
                class_name, function_name, expression)
        path.reverse()
        env: dict[str, object] = {}
        for depth, (statements, index) in enumerate(path):
            env = self._exec_local_block(
                class_name, function_name, statements[:index], env)
            if depth + 1 < len(path):
                ancestor = statements[index]
                if isinstance(ancestor, ast.For):
                    domain = self._eval_with_local_env(
                        class_name, function_name, ancestor.iter, env)
                    values = _finite(domain)
                    iterable: set[object] = set()
                    if values is not None:
                        for item in values:
                            if isinstance(item, (tuple, frozenset)):
                                iterable.update(item)
                            else:
                                iterable.add(item)
                    if iterable:
                        self._store_local_env(
                            ancestor.target, frozenset(iterable), env)
        return self._eval_with_local_env(
            class_name, function_name, expression, env)

    def _store(self, class_name: str, function_name: str,
               target: ast.AST, value: object) -> bool:
        changed = False
        if isinstance(target, (ast.Tuple, ast.List)):
            tuples = _finite(value)
            if tuples is None:
                return False
            for index, item_target in enumerate(target.elts):
                item_values = {
                    item[index] for item in tuples
                    if isinstance(item, tuple) and len(item) == len(target.elts)
                }
                if item_values:
                    changed |= self._store(
                        class_name, function_name, item_target,
                        frozenset(item_values))
            return changed
        if isinstance(target, ast.Name):
            key = (class_name, function_name, target.id)
            merged, item_changed = _merge_domain(
                self.locals.get(key, _ABSTRACT_UNKNOWN), value)
            if item_changed:
                self.locals[key] = merged
            return item_changed
        if (isinstance(target, ast.Attribute) and
                isinstance(target.value, ast.Name) and
                target.value.id == "self"):
            key = (class_name, target.attr)
            merged, item_changed = _merge_domain(
                self.fields.get(key, _ABSTRACT_UNKNOWN), value)
            if item_changed:
                self.fields[key] = merged
            return item_changed
        return False

    @staticmethod
    def _self_referential(target: ast.AST, value: ast.AST) -> bool:
        if not isinstance(target, ast.Attribute):
            return False
        text = ast.unparse(target)
        return any(ast.unparse(item) == text for item in ast.walk(value)
                   if isinstance(item, ast.Attribute))

    def _bind_call(self, caller_class: str, caller_function: str,
                   callee_class: str, callee_function: str,
                   call: ast.Call, *, skip_first_argument: bool = False) -> bool:
        function = self.functions.get((callee_class, callee_function))
        if function is None:
            return False
        parameters = [argument.arg for argument in (
            list(function.args.posonlyargs) + list(function.args.args))
            if argument.arg != "self"]
        arguments = list(call.args[1:] if skip_first_argument else call.args)
        changed = False
        for name, argument in zip(parameters, arguments):
            value = self._eval(caller_class, caller_function, argument)
            key = (callee_class, callee_function, name)
            merged, item_changed = _merge_domain(
                self.params.get(key, _ABSTRACT_UNKNOWN), value)
            if item_changed:
                self.params[key] = merged
                changed = True
        for keyword in call.keywords:
            if keyword.arg in parameters:
                value = self._eval(caller_class, caller_function, keyword.value)
                key = (callee_class, callee_function, keyword.arg)
                merged, item_changed = _merge_domain(
                    self.params.get(key, _ABSTRACT_UNKNOWN), value)
                if item_changed:
                    self.params[key] = merged
                    changed = True
        return changed

    def _process_function(self, class_name: str, function_name: str,
                          function: ast.FunctionDef) -> bool:
        # Locals describe one invocation. Keeping them across fixed-point
        # passes turns ``descriptor = base; descriptor += 6`` into an
        # impossible unbounded arithmetic progression.
        for key in tuple(self.locals):
            if key[:2] == (class_name, function_name):
                del self.locals[key]
        # ``ast.walk`` is breadth-first, so a top-level ``for table in
        # tables`` can precede the assignments to ``tables`` nested in its
        # preceding if/else. Prime only local names to a small fixed point;
        # object fields remain handled once by the sink-aware pass below.
        for _ in range(4):
            local_changed = False
            for prime in ast.walk(function):
                if isinstance(prime, (ast.Assign, ast.AnnAssign)):
                    targets = (prime.targets if isinstance(prime, ast.Assign)
                               else [prime.target])
                    if prime.value is None:
                        continue
                    value = self._eval_correlated(
                        class_name, function_name, prime.value)
                    for target in targets:
                        if isinstance(target, (ast.Name, ast.Tuple, ast.List)):
                            local_changed |= self._store(
                                class_name, function_name, target, value)
                elif isinstance(prime, ast.For):
                    iterable: object = _ABSTRACT_UNKNOWN
                    if (isinstance(prime.iter, ast.Call) and
                            isinstance(prime.iter.func, ast.Name) and
                            prime.iter.func.id == "range"):
                        args = [_int_values(self._eval(
                            class_name, function_name, arg))
                                for arg in prime.iter.args]
                        if all(item is not None and len(item) == 1
                               for item in args):
                            numeric = [next(iter(item)) for item in args
                                       if item is not None]
                            iterable = frozenset(range(*numeric))
                    else:
                        values = _finite(self._eval(
                            class_name, function_name, prime.iter))
                        if values is not None:
                            flattened: set[object] = set()
                            for item in values:
                                if isinstance(item, (tuple, frozenset)):
                                    flattened.update(item)
                            iterable = (frozenset(flattened) if flattened
                                        else values)
                    if isinstance(prime.target,
                                  (ast.Name, ast.Tuple, ast.List)):
                        local_changed |= self._store(
                            class_name, function_name, prime.target, iterable)
            if not local_changed:
                break
        primed_self_augments: set[int] = set()
        primed_self_augment_keys: set[tuple[str, str, str]] = set()
        for prime in ast.walk(function):
            if (not isinstance(prime, ast.AugAssign) or
                    not isinstance(prime.target, ast.Name) or
                    not any(isinstance(item, ast.Name) and
                            item.id == prime.target.id
                            for item in ast.walk(prime.value))):
                continue
            key = (class_name, function_name, prime.target.id)
            if key in primed_self_augment_keys:
                primed_self_augments.add(prime.lineno)
                continue
            current_values = _int_values(
                self.locals.get(key, _ABSTRACT_UNKNOWN))
            if current_values is None:
                continue
            transformed: object = _ABSTRACT_UNKNOWN
            for bound in current_values:
                class NameBinder(ast.NodeTransformer):
                    def visit_Name(self, item: ast.Name) -> ast.AST:
                        if item.id == prime.target.id:
                            return ast.copy_location(
                                ast.Constant(bound), item)
                        return item
                expression = NameBinder().visit(copy.deepcopy(prime.value))
                rhs = self._eval(class_name, function_name, expression)
                item_value = _apply_binary(
                    prime.op, _one_domain(bound), rhs)
                transformed, _ = _merge_domain(transformed, item_value)
            if transformed is not _ABSTRACT_UNKNOWN:
                self.locals[key] = transformed
                primed_self_augments.add(prime.lineno)
                primed_self_augment_keys.add(key)
        changed = False
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value_node = node.value
                if value_node is None:
                    continue
                value = self._eval_correlated(
                    class_name, function_name, value_node)
                for target in targets:
                    # Unbounded counters/cursors must not grow one value per
                    # fixed-point iteration. Their selector masks or ROM
                    # cursor expansion below establish the finite domain.
                    if self._self_referential(target, value_node):
                        text = ast.unparse(target)
                        if ("pointer" in text or "sequence" in text):
                            continue
                        if not any(isinstance(item, (ast.Mod, ast.BitAnd))
                                   for item in ast.walk(value_node)):
                            value = _ABSTRACT_U16
                    changed |= self._store(
                        class_name, function_name, target, value)
                    if (isinstance(target, ast.Attribute) and
                            target.attr in ("descriptor", "overlay_descriptor") and
                            class_name in self.reachable):
                        # Descriptor selection is path-sensitive even though
                        # the wider field fixed point is intentionally not.
                        # Re-evaluate this exact assignment with only the
                        # lexical locals reaching its branch.  Otherwise a
                        # reused name such as ``offset`` in sibling state
                        # branches creates descriptors that Python can never
                        # select.
                        sink_value = self._eval_at_statement(
                            class_name, function_name, function, node,
                            value_node)
                        sink = (f"{class_name}.{function_name}:{node.lineno}:"
                                f"{target.attr}")
                        self.sink_ids.add(sink)
                        values = _int_values(sink_value)
                        if values is None:
                            self.unresolved.add(sink)
                        else:
                            self.unresolved.discard(sink)
                            destination = (self.overlays if
                                           target.attr == "overlay_descriptor"
                                           else self.descriptors)
                            destination[class_name].update(
                                item & 0xFFFF for item in values)
                            self.descriptor_sink_values.setdefault(
                                sink, set()).update(
                                    item & 0xFFFF for item in values)
            elif isinstance(node, ast.AugAssign):
                if node.lineno in primed_self_augments:
                    continue
                if (isinstance(node.target, ast.Attribute) and
                        isinstance(node.target.value, ast.Name) and
                        node.target.value.id == "self" and
                        node.target.attr in ("descriptor",
                                             "overlay_descriptor")):
                    increment = _int_values(self._eval(
                        class_name, function_name, node.value))
                    bases: set[int] = set()
                    for assignment in ast.walk(function):
                        if not isinstance(assignment, (ast.Assign,
                                                       ast.AnnAssign)):
                            continue
                        targets = (assignment.targets if isinstance(
                            assignment, ast.Assign) else [assignment.target])
                        if any(ast.unparse(target) == ast.unparse(node.target)
                               for target in targets):
                            values = _int_values(self._eval_correlated(
                                class_name, function_name, assignment.value))
                            if values is not None:
                                bases.update(values)
                    sink = (f"{class_name}.{function_name}:{node.lineno}:"
                            f"{node.target.attr}")
                    self.sink_ids.add(sink)
                    if increment is None or not bases:
                        self.unresolved.add(sink)
                    else:
                        self.unresolved.discard(sink)
                        destination = (self.overlays if
                                       node.target.attr == "overlay_descriptor"
                                       else self.descriptors)
                        destination[class_name].update(
                            (base + delta) & 0xFFFF
                            for base in bases for delta in increment)
                        self.descriptor_sink_values.setdefault(
                            sink, set()).update(
                                (base + delta) & 0xFFFF
                                for base in bases for delta in increment)
                    continue
                if (isinstance(node.target, ast.Attribute) and
                        ("pointer" in node.target.attr or
                         "sequence" in node.target.attr)):
                    continue
                current = self._eval(class_name, function_name, node.target)
                value = self._eval_correlated(
                    class_name, function_name, node.value)
                if (isinstance(node.target, ast.Attribute) and
                        isinstance(node.target.value, ast.Name) and
                        node.target.value.id == "self"):
                    if isinstance(node.op, (ast.BitXor, ast.BitAnd)):
                        updated = _apply_binary(node.op, current, value)
                    else:
                        updated = _ABSTRACT_U16
                        current_values = _int_values(current)
                        deltas = _int_values(value)
                        sentinels: set[int] = set()
                        resets: set[int] = set()
                        target_text = ast.unparse(node.target)
                        for item in ast.walk(function):
                            if (isinstance(item, ast.Compare) and
                                    len(item.ops) == 1 and
                                    isinstance(item.ops[0], ast.Eq) and
                                    ast.unparse(item.left) == target_text and
                                    len(item.comparators) == 1 and
                                    isinstance(item.comparators[0], ast.Constant) and
                                    isinstance(item.comparators[0].value, int)):
                                sentinels.add(int(item.comparators[0].value))
                            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                                targets = (item.targets if isinstance(
                                    item, ast.Assign) else [item.target])
                                if (any(ast.unparse(candidate) == target_text
                                        for candidate in targets) and
                                        isinstance(item.value, ast.Constant) and
                                        isinstance(item.value.value, int)):
                                    resets.add(int(item.value.value))
                        if (current_values is not None and deltas is not None and
                                len(deltas) == 1 and sentinels and resets):
                            delta = next(iter(deltas))
                            if isinstance(node.op, ast.Sub):
                                delta = -delta
                            elif not isinstance(node.op, ast.Add):
                                delta = 0
                            closure = set(current_values)
                            pending_values = list(current_values)
                            for _ in range(0x1000):
                                if not pending_values:
                                    updated = frozenset(closure)
                                    break
                                before = pending_values.pop()
                                after = before + delta
                                successors = resets if after in sentinels else {after}
                                for successor in successors:
                                    if successor not in closure:
                                        closure.add(successor)
                                        pending_values.append(successor)
                else:
                    if (isinstance(node.target, ast.Name) and
                            any(isinstance(item, ast.Name) and
                                item.id == node.target.id
                                for item in ast.walk(node.value))):
                        current_values = _int_values(current)
                        result: object = _ABSTRACT_UNKNOWN
                        if current_values is not None:
                            class NameBinder(ast.NodeTransformer):
                                def visit_Name(self, item: ast.Name) -> ast.AST:
                                    if item.id == node.target.id:
                                        return ast.copy_location(
                                            ast.Constant(bound), item)
                                    return item
                            for bound in current_values:
                                expression = NameBinder().visit(
                                    copy.deepcopy(node.value))
                                rhs = self._eval(
                                    class_name, function_name, expression)
                                item_value = _apply_binary(
                                    node.op, _one_domain(bound), rhs)
                                result, _ = _merge_domain(
                                    result, item_value)
                        updated = result
                    else:
                        updated = _apply_binary(node.op, current, value)
                changed |= self._store(
                    class_name, function_name, node.target,
                    updated)
            elif isinstance(node, ast.For):
                iterable: object = _ABSTRACT_UNKNOWN
                if (isinstance(node.iter, ast.Call) and
                        isinstance(node.iter.func, ast.Name) and
                        node.iter.func.id == "range"):
                    args = [_int_values(self._eval(
                        class_name, function_name, arg)) for arg in node.iter.args]
                    if all(item is not None and len(item) == 1 for item in args):
                        numeric = [next(iter(item)) for item in args if item is not None]
                        iterable = frozenset(range(*numeric))
                else:
                    domain = self._eval(class_name, function_name, node.iter)
                    values = _finite(domain)
                    if values is not None:
                        flattened: set[object] = set()
                        for item in values:
                            if isinstance(item, (tuple, frozenset)):
                                flattened.update(item)
                        iterable = (frozenset(flattened) if flattened
                                    else domain)
                changed |= self._store(
                    class_name, function_name, node.target, iterable)
            elif isinstance(node, ast.Return) and node.value is not None:
                value = self._eval_correlated(
                    class_name, function_name, node.value)
                key = (class_name, function_name)
                merged, item_changed = _merge_domain(
                    self.returns.get(key, _ABSTRACT_UNKNOWN), value)
                if item_changed:
                    self.returns[key] = merged
                    changed = True
            elif isinstance(node, ast.Call):
                simple = node.func.id if isinstance(node.func, ast.Name) else ""
                if simple in self.reachable or simple == "ScriptedMotion":
                    changed |= self._bind_call(
                        class_name, function_name, simple, "__init__", node)
                elif (isinstance(node.func, ast.Attribute) and
                      ast.unparse(node.func.value) == "self"):
                    owner = self._method_owner(class_name, node.func.attr)
                    changed |= self._bind_call(
                        class_name, function_name, owner, node.func.attr, node)
                elif (isinstance(node.func, ast.Attribute) and
                      node.func.attr == "__init__" and
                      ast.unparse(node.func.value) == "super()"):
                    bases = self.bases.get(class_name, ())
                    base = bases[0] if bases else ""
                    if base == "Enemy":
                        if len(node.args) >= 5:
                            # The constructor descriptor may depend on a
                            # local selected by an enclosing branch.  Find
                            # the statement owning the nested call so the
                            # same lexical evaluation used by assignments
                            # applies here as well.
                            owner_statement = next(
                                (candidate for candidate in ast.walk(function)
                                 if isinstance(candidate, ast.stmt) and
                                 any(item is node for item in ast.walk(candidate))),
                                None)
                            value = (self._eval_at_statement(
                                class_name, function_name, function,
                                owner_statement, node.args[4])
                                if owner_statement is not None else
                                self._eval_correlated(
                                    class_name, function_name, node.args[4]))
                            sink = (f"{class_name}.{function_name}:{node.lineno}:"
                                    "Enemy.__init__.descriptor")
                            self.sink_ids.add(sink)
                            values = _int_values(value)
                            if values is None:
                                self.unresolved.add(sink)
                            else:
                                self.unresolved.discard(sink)
                                descriptor_values = {
                                    item & 0xFFFF for item in values}
                                self.descriptors[class_name].update(
                                    descriptor_values)
                                self.descriptor_sink_values.setdefault(
                                    sink, set()).update(descriptor_values)
                                field_key = (class_name, "descriptor")
                                merged, item_changed = _merge_domain(
                                    self.fields.get(
                                        field_key, _ABSTRACT_UNKNOWN),
                                    frozenset(descriptor_values))
                                if item_changed:
                                    self.fields[field_key] = merged
                                    changed = True
                        death_keyword = next((
                            keyword.value for keyword in node.keywords
                            if keyword.arg == "death_effect"), None)
                        death_value = (self._eval_correlated(
                            class_name, function_name, death_keyword)
                            if death_keyword is not None else
                            _one_domain(self.class_constants.get(
                                ("Enemy", "death_effect"), "e7be")))
                        changed |= self._store(
                            class_name, function_name,
                            ast.Attribute(value=ast.Name(id="self"),
                                          attr="death_effect",
                                          ctx=ast.Store()),
                            death_value)
                    elif base in self.classes:
                        changed |= self._bind_call(
                            class_name, function_name, base, "__init__", node)

                if (isinstance(node.func, ast.Attribute) and
                        node.func.attr == "acquire" and node.args and
                        class_name in self.reachable):
                    value = self._eval_correlated(
                        class_name, function_name, node.args[0])
                    sink = f"{class_name}.{function_name}:{node.lineno}:resource"
                    values = _int_values(value)
                    if values is None:
                        self.unresolved.add(sink)
                    else:
                        self.unresolved.discard(sink)
                        self.resources[class_name].update(
                            item & 0xFF for item in values)
                        self.resource_sink_values.setdefault(
                            sink, set()).update(
                                item & 0xFF for item in values)
                if (isinstance(node.func, ast.Attribute) and
                        node.func.attr == "emit_transient_sprite" and
                        len(node.args) >= 3):
                    descriptors = _int_values(self._eval_correlated(
                        class_name, function_name, node.args[0]))
                    resources = _int_values(self._eval_correlated(
                        class_name, function_name, node.args[2]))
                    sink = (f"{class_name}.{function_name}:{node.lineno}:"
                            "transient")
                    self.sink_ids.add(sink)
                    if descriptors is None or resources is None:
                        self.unresolved.add(sink)
                    else:
                        self.unresolved.discard(sink)
                        descriptor_domain, resource_domain = (
                            self.transient_sink_values.setdefault(
                                sink, (set(), set())))
                        descriptor_domain.update(
                            descriptor & 0xFFFF
                            for descriptor in descriptors)
                        resource_domain.update(
                            resource & 0xFF for resource in resources)
                        self.transient_pairs.update(
                            (descriptor & 0xFFFF, resource & 0xFF)
                            for descriptor in descriptors for resource in resources)
        return changed

    def _expand_rom_cursors(self) -> bool:
        changed = False
        for (class_name, field), domain in tuple(self.fields.items()):
            if field not in ("sequence_pointer", "explosion_pointer",
                             "animation_pointer"):
                continue
            seeds = _int_values(domain)
            if seeds is None:
                continue
            # Zero is the inactive sentinel installed before a state selects
            # a ROM stream. No active descriptor read occurs in that state;
            # treating ES:$0000 as a stream walks executable code as if it
            # were descriptor pointers.
            expanded = {seed for seed in seeds if seed != 0}
            for seed in seeds:
                if seed == 0:
                    continue
                pointer = seed
                for _ in range(128):
                    if field == "animation_pointer":
                        if self.rom.word(pointer) == 0:
                            break
                        expanded.add(pointer)
                        pointer = _u16(pointer + 2)
                    else:
                        if self.rom.word(pointer) == 0:
                            break
                        expanded.add(pointer)
                        pointer = _u16(pointer + 4)
                else:
                    self.unresolved.add(
                        f"{class_name}.{field}:unterminated-ROM-cursor")
            closed_domain = frozenset(expanded)
            if closed_domain != domain:
                self.fields[(class_name, field)] = closed_domain
                changed = True
        return changed

    def _expand_scripted_motion_phases(self) -> bool:
        """Close `$F5C1` phase commands from every active script root.

        `ScriptedMotion.phase` is not an arbitrary five-bit value: it is set
        only by bytes with bit 7 in the ROM command streams selected by the
        reachable constructors.  Treating it as zero misses animation frames;
        treating it as 0..31 invents frames.  This small graph walk follows
        the same script-table transitions as the active Python method.
        """
        scripts = _int_values(self.params.get(
            ("ScriptedMotion", "__init__", "script"), _ABSTRACT_UNKNOWN))
        if scripts is None:
            return False
        phases = {0}
        pending_tables = list(scripts)
        visited_tables: set[int] = set()
        while pending_tables:
            table = _u16(pending_tables.pop())
            for _ in range(0x400):
                if table in visited_tables:
                    break
                visited_tables.add(table)
                word = self.rom.word(table)
                if word == 0:
                    # `$F5C1` returns carry immediately after installing the
                    # redirect.  Every reachable sprite owner either removes
                    # the object, changes state/script, or uses a cyclic root
                    # whose pre-carry segment already contains its complete
                    # phase alphabet.  Following the newly installed pointer
                    # here would execute the *next handler state* without its
                    # caller transition and eventually interpret arbitrary
                    # data as an unbounded script table.
                    break
                if word & 0xFF00 == 0xF000:
                    table = _u16(table + 2)
                    continue
                pointer = word
                for _ in range(0x1000):
                    command = self.rom.byte(pointer)
                    if command & 0x80:
                        phases.add(command & 0x1F)
                    pointer = _u16(pointer + 1)
                    if command & 0x04:
                        break
                else:
                    self.unresolved.add(
                        f"ScriptedMotion:${table:04X}:unterminated-command-stream")
                    break
                table = _u16(table + 2)
            else:
                self.unresolved.add(
                    f"ScriptedMotion:${table:04X}:unterminated-script-table")
        key = ("ScriptedMotion", "phase")
        domain = frozenset(phases)
        if self.fields.get(key) != domain:
            self.fields[key] = domain
            return True
        return False

    def analyze(self) -> _StageAbstractResult:
        # Constructor/call propagation and local arithmetic converge quickly;
        # a hard bound converts accidental recursive widening into an error.
        last_sprite_signature: object = None
        stable_sprite_passes = 0
        for iteration in range(48):
            changed = False
            for key, function in sorted(self.functions.items()):
                changed |= self._process_function(key[0], key[1], function)
            if iteration == 4:
                changed |= self._expand_rom_cursors()
                changed |= self._expand_scripted_motion_phases()
            sprite_signature = (
                tuple((name, tuple(sorted(values)))
                      for name, values in sorted(self.descriptors.items())),
                tuple((name, tuple(sorted(values)))
                      for name, values in sorted(self.overlays.items())),
                tuple((name, tuple(sorted(values)))
                      for name, values in sorted(self.resources.items())),
                tuple(sorted(self.transient_pairs)),
                tuple(sorted(self.unresolved)),
            )
            if sprite_signature == last_sprite_signature:
                stable_sprite_passes += 1
            else:
                stable_sprite_passes = 0
                last_sprite_signature = sprite_signature
            # State variables unrelated to rendering (coordinates, timers,
            # collision accumulators) may keep widening.  Once every sprite
            # sink has observed the same domain for four complete passes,
            # further widening cannot affect this backwards slice.
            if stable_sprite_passes >= 4 or not changed:
                break
        else:
            self.unresolved.add(
                "stage-abstract-interpreter:sprite-domain-no-fixed-point")
        self._expand_rom_cursors()
        # One final evaluation observes the cursor closure and emits final
        # sink values without depending on traversal order.
        for key, function in sorted(self.functions.items()):
            self._process_function(key[0], key[1], function)

        # Resource/descriptor behavior inherited by concrete subclasses.
        for class_name in sorted(self.reachable):
            for base in self._base_chain(class_name):
                if base in self.resources:
                    self.resources[class_name].update(self.resources[base])
                if (not self.descriptors[class_name] and
                        base in self.descriptors):
                    self.descriptors[class_name].update(self.descriptors[base])

        return _StageAbstractResult(
            descriptors=self.descriptors,
            overlays=self.overlays,
            resources=self.resources,
            descriptor_sink_values=self.descriptor_sink_values,
            resource_sink_values=self.resource_sink_values,
            transient_sink_values=self.transient_sink_values,
            parameter_domains=tuple(sorted(
                (key, tuple(sorted(values, key=repr)))
                for key, domain in self.params.items()
                if (values := _finite(domain)) is not None)),
            field_domains=tuple(sorted(
                (key, tuple(sorted(values, key=repr)))
                for key, domain in self.fields.items()
                if (values := _finite(domain)) is not None)),
            transient_pairs=self.transient_pairs,
            sink_ids=self.sink_ids,
            unresolved=self.unresolved,
        )


def _enemy_class_graph(enemy_tree: ast.Module) -> tuple[
        set[str], dict[str, set[str]]]:
    classes = {
        node.name: node for node in enemy_tree.body
        if isinstance(node, ast.ClassDef)
    }

    def is_enemy(name: str) -> bool:
        seen: set[str] = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            node = classes.get(current)
            if node is None:
                continue
            for base in node.bases:
                base_name = ast.unparse(base)
                if base_name == "Enemy":
                    return True
                if base_name in classes:
                    pending.append(base_name)
        return False

    enemy_classes = {name for name in classes if is_enemy(name)}
    graph: dict[str, set[str]] = {name: set() for name in enemy_classes}
    for name in enemy_classes:
        for node in ast.walk(classes[name]):
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and
                    node.func.id in enemy_classes):
                graph[name].add(node.func.id)
    return enemy_classes, graph


def _handler_test_value(node: ast.AST) -> int | None:
    if (isinstance(node, ast.Compare) and len(node.ops) == 1 and
            isinstance(node.ops[0], ast.Eq) and len(node.comparators) == 1 and
            ast.unparse(node.left) == "event.handler" and
            isinstance(node.comparators[0], ast.Constant) and
            isinstance(node.comparators[0].value, int)):
        return int(node.comparators[0].value)
    return None


def _dispatch_class_roots(enemy_tree: ast.Module,
                          enemy_classes: set[str]) -> dict[int, set[str]]:
    dispatch = _find_function(enemy_tree, "M72EnemyWorld", "_dispatch")
    roots: dict[int, set[str]] = {}
    for node in ast.walk(dispatch):
        if not isinstance(node, ast.If):
            continue
        handler = _handler_test_value(node.test)
        if handler is None:
            continue
        classes = {
            call.func.id
            for statement in node.body
            for call in ast.walk(statement)
            if (isinstance(call, ast.Call) and
                isinstance(call.func, ast.Name) and
                call.func.id in enemy_classes)
        }
        roots[handler] = classes
    return roots


def _stage_event_records(enemy_tree: ast.Module,
                         rom: _WorldRom) -> dict[int, tuple[_StageEventRecord, ...]]:
    ranges = _module_literal(enemy_tree, "STAGE_EVENT_RANGES")
    dispatch_table = _module_literal(enemy_tree, "DISPATCH_TABLE")
    if (not isinstance(ranges, dict) or set(ranges) != set(range(1, 9)) or
            not isinstance(dispatch_table, int)):
        raise SpriteCoverageError(
            "active Python eight-stage event constants changed")
    result: dict[int, tuple[_StageEventRecord, ...]] = {}
    total = 0
    for stage in range(1, 9):
        bounds = ranges[stage]
        if (not isinstance(bounds, tuple) or len(bounds) != 2 or
                not all(isinstance(value, int) for value in bounds)):
            raise SpriteCoverageError(
                f"stage {stage} event bounds are not an integer pair")
        first, last = (int(bounds[0]), int(bounds[1]))
        if last < first or (last - first) % 4:
            raise SpriteCoverageError(
                f"stage {stage} event bounds are not closed 4-byte records")
        records: list[_StageEventRecord] = []
        for address in range(first, last + 1, 4):
            threshold = rom.word(address)
            command = rom.word(address + 2)
            offset = ((command >> 9) & 0x7E)
            handler = rom.word(int(dispatch_table) + offset)
            records.append(_StageEventRecord(
                address, threshold, command, handler))
        total += len(records)
        result[stage] = tuple(records)
    if total != 788:
        raise SpriteCoverageError(
            f"active Python event streams contain {total} records, expected 788")
    return result


def _draw_isinstance_classes(test: ast.AST,
                             enemy_classes: set[str]) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(test):
        if (not isinstance(node, ast.Call) or
                not isinstance(node.func, ast.Name) or
                node.func.id != "isinstance" or len(node.args) != 2 or
                ast.unparse(node.args[0]) != "enemy"):
            continue
        candidates = (node.args[1].elts
                      if isinstance(node.args[1], ast.Tuple)
                      else [node.args[1]])
        for candidate in candidates:
            name = ast.unparse(candidate)
            if name in enemy_classes:
                result.add(name)
    return result


def _draw_extra_addresses(
        enemy_tree: ast.Module, enemy_classes: set[str],
        result: _StageAbstractResult,
        ) -> dict[str, set[int]]:
    """Interpret descriptor expressions guarded by active draw ``isinstance``."""
    draw = _find_function(enemy_tree, "M72EnemyWorld", "draw")
    extras = {name: set() for name in enemy_classes}

    def descriptor_argument(call: ast.Call) -> ast.AST | None:
        if (not isinstance(call.func, ast.Attribute) or
                call.func.attr != "draw" or len(call.args) < 2):
            return None
        argument = call.args[1]
        if (isinstance(argument, ast.Call) and len(argument.args) >= 2 and
                ((isinstance(argument.func, ast.Name) and
                  argument.func.id == "read_descriptor") or
                 (isinstance(argument.func, ast.Attribute) and
                  argument.func.attr == "read_descriptor"))):
            return argument.args[1]
        return None

    for conditional in ast.walk(draw):
        if not isinstance(conditional, ast.If):
            continue
        guarded = _draw_isinstance_classes(conditional.test, enemy_classes)
        if not guarded:
            continue
        # Flow-insensitive local tuple domains inside the guarded block are
        # sufficient for ``extra`` and the fixed seven-root composite.
        local_values: dict[str, set[int]] = {}
        for node in ast.walk(ast.Module(body=conditional.body, type_ignores=[])):
            if isinstance(node, ast.Assign):
                literal = _safe_ast_literal(node.value)
                integers: set[int] = set()
                if isinstance(literal, int):
                    integers.add(literal)
                elif isinstance(literal, tuple):
                    integers.update(item for item in literal
                                    if isinstance(item, int))
                for target in node.targets:
                    if isinstance(target, ast.Name) and integers:
                        local_values.setdefault(target.id, set()).update(integers)
        for node in ast.walk(ast.Module(body=conditional.body, type_ignores=[])):
            if not isinstance(node, ast.Call):
                continue
            expression = descriptor_argument(node)
            if expression is None:
                continue
            for class_name in guarded:
                if (isinstance(expression, ast.BinOp) and
                        isinstance(expression.op, ast.Add) and
                        ast.unparse(expression.left) == "enemy.descriptor" and
                        isinstance(expression.right, ast.Constant) and
                        isinstance(expression.right.value, int)):
                    extras[class_name].update(
                        (address + int(expression.right.value)) & 0xFFFF
                        for address in result.descriptors.get(class_name, ()))
                elif ast.unparse(expression) == "enemy.overlay_descriptor":
                    extras[class_name].update(
                        result.overlays.get(class_name, ()))
                elif isinstance(expression, ast.Constant) and isinstance(
                        expression.value, int):
                    extras[class_name].add(int(expression.value) & 0xFFFF)
                elif isinstance(expression, ast.Name):
                    extras[class_name].update(
                        value & 0xFFFF
                        for value in local_values.get(expression.id, ()))
    return extras


def _cell_count(pairs: Iterable[DescriptorResourcePair]) -> int:
    cells: set[tuple[PythonBankKey, int, bool, bool]] = set()
    for pair in pairs:
        descriptor = pair.descriptor
        for bank in pair.bank_keys:
            for cell_x in range(descriptor.width):
                for cell_y in range(descriptor.height):
                    source_x = (descriptor.width - 1 - cell_x
                                if descriptor.flip_x else cell_x)
                    source_y = (descriptor.height - 1 - cell_y
                                if descriptor.flip_y else cell_y)
                    cells.add((
                        bank,
                        (descriptor.code + 8 * source_x + source_y) & 0x0FFF,
                        descriptor.flip_x,
                        descriptor.flip_y,
                    ))
    return len(cells)


def _sink_owner(sink: str) -> tuple[str, str]:
    """Return the class/function portion of an abstract sink id."""
    qualified = sink.split(":", 1)[0]
    if "." not in qualified:
        return "", qualified
    return tuple(qualified.split(".", 1))  # type: ignore[return-value]


def _class_sink_addresses(
        abstract: _StageAbstractResult, class_name: str, *,
        methods: Iterable[str] | None = None,
        exclude_methods: Iterable[str] = (),
        overlays: bool = True,
        ) -> set[int]:
    selected = set(methods) if methods is not None else None
    excluded = set(exclude_methods)
    result: set[int] = set()
    for sink, values in abstract.descriptor_sink_values.items():
        owner, method = _sink_owner(sink)
        if owner != class_name or method in excluded:
            continue
        if selected is not None and method not in selected:
            continue
        if not overlays and sink.endswith(":overlay_descriptor"):
            continue
        result.update(values)
    return result


def _resource_sink_target(
        enemy_tree: ast.Module, sink: str) -> str:
    """Recover the assignment target owning one ``acquire`` call."""
    owner, method = _sink_owner(sink)
    try:
        line = int(sink.split(":", 2)[1])
    except (IndexError, ValueError) as exc:
        raise SpriteCoverageError(f"malformed resource sink id: {sink}") from exc
    function = _find_function(enemy_tree, owner, method)
    call = next((
        node for node in ast.walk(function)
        if (isinstance(node, ast.Call) and node.lineno == line and
            isinstance(node.func, ast.Attribute) and
            node.func.attr == "acquire")
    ), None)
    if call is None:
        raise SpriteCoverageError(
            f"resource sink no longer resolves to acquire(): {sink}")
    for statement in ast.walk(function):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        if value is None or not any(item is call for item in ast.walk(value)):
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target])
        if len(targets) != 1:
            break
        return ast.unparse(targets[0])
    raise SpriteCoverageError(
        f"resource acquire is not owned by one assignment: {sink}")


def _class_resource_sources(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        class_name: str,
        ) -> dict[tuple[str, str], set[int]]:
    """Map ``(method,target)`` to the exact resource-type domain."""
    result: dict[tuple[str, str], set[int]] = {}
    for sink, values in abstract.resource_sink_values.items():
        owner, method = _sink_owner(sink)
        if owner != class_name:
            continue
        target = _resource_sink_target(enemy_tree, sink)
        result.setdefault((method, target), set()).update(values)
    return result


def _background_particle_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        ) -> set[tuple[int, int]]:
    """Execute the active finite `$E581` descriptor/resource selector."""
    update = _compile_method(
        _find_function(enemy_tree, "BackgroundParticleE5CD", "update"),
        {"_signed_word": _signed_word, "_u16": _u16},
    )

    class FixedRng:
        def __init__(self, values: Iterable[int]) -> None:
            self.values = deque(values)

        def next(self) -> int:
            return self.values.popleft()

    class IdentityResources:
        @staticmethod
        def acquire(resource_type: int) -> int:
            return resource_type & 0xFF

    result: set[tuple[int, int]] = set()
    # The source mask controls the finite selector.  Supplying all byte-low
    # values is exhaustive without copying the ROM table addresses here.
    for selector in range(0x100):
        particle = SimpleNamespace(
            initialized=False, render_ready=False, velocity_table=0x832C,
            x_velocity=0, x_fraction=0, y_fraction=0,
            descriptor=0, palette=0, x=0, y=0,
        )
        world = SimpleNamespace(
            rng=FixedRng((0, selector, 0)), rom=rom,
            resources=IdentityResources())
        update(particle, world, 0)
        if not particle.initialized:
            raise SpriteCoverageError(
                "BackgroundParticleE5CD selector no longer initializes")
        result.add((particle.descriptor & 0xFFFF,
                    particle.palette & 0xFF))
    if not result:
        raise SpriteCoverageError("background particle pair domain is empty")
    return result


def _pure_selector(expression: ast.AST, **bindings: object) -> object:
    """Evaluate a side-effect-free selector after rejecting unsafe syntax."""
    allowed = (
        ast.Expression, ast.Constant, ast.Name, ast.IfExp, ast.Compare,
        ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.BoolOp, ast.And, ast.Or,
        ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add,
        ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.LShift, ast.RShift,
        ast.BitAnd, ast.BitOr, ast.BitXor, ast.Tuple, ast.List,
        ast.Load,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(expression)):
        raise SpriteCoverageError(
            "resource selector contains unsupported dynamic syntax: " +
            ast.unparse(expression))
    body = copy.deepcopy(expression)
    ast.fix_missing_locations(body)
    return eval(  # noqa: S307 - syntax and globals are explicitly closed.
        compile(ast.Expression(body), "<sprite-resource-selector>", "eval"),
        {"__builtins__": {}}, dict(bindings))


def _masked_frame_counter_domain(function: ast.FunctionDef) -> range:
    """Return exact low-bit representatives for a masked 16-bit counter.

    Every active use must be contained by an integral ``& mask``.  Low
    ``mask.bit_length()`` residues then preserve additions/XORs below that
    mask while avoiding 65,536 duplicate executions.  A new unmasked use is
    deliberately unresolved rather than sampled heuristically.
    """
    occurrences = {
        (node.lineno, node.col_offset)
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute) and
        ast.unparse(node) == "world.frame_counter"
    }
    if not occurrences:
        return range(1)
    covered: set[tuple[int, int]] = set()
    masks: set[int] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.BitAnd):
            continue
        if isinstance(node.right, ast.Constant) and isinstance(
                node.right.value, int):
            expression, mask = node.left, int(node.right.value)
        elif isinstance(node.left, ast.Constant) and isinstance(
                node.left.value, int):
            expression, mask = node.right, int(node.left.value)
        else:
            continue
        owned = {
            (item.lineno, item.col_offset)
            for item in ast.walk(expression)
            if isinstance(item, ast.Attribute) and
            ast.unparse(item) == "world.frame_counter"
        }
        if owned:
            if not 0 <= mask <= 0xFFFF:
                raise SpriteCoverageError(
                    f"{function.name} frame-counter mask is not 16-bit")
            covered.update(owned)
            masks.add(mask)
    if covered != occurrences or not masks:
        raise SpriteCoverageError(
            f"{function.name} has an unmasked frame-counter selector")
    width = max(mask.bit_length() for mask in masks)
    return range(1 << width)


def _explosion_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    constructor = _find_function(enemy_tree, "ExplosionEffect", "__init__")
    sequences = _class_constant(enemy_tree, "ExplosionEffect", "SEQUENCES")
    if not isinstance(sequences, _FrozenMap):
        raise SpriteCoverageError("ExplosionEffect.SEQUENCES is not static")
    sequence_map = dict(sequences.items)
    effect_values = abstract.parameter_domain(
        "ExplosionEffect", "__init__", "effect")
    effects = set(effect_values or ())
    for (owner, field), values in abstract.field_domains:
        if field == "death_effect":
            effects.update(value for value in values
                           if isinstance(value, str))
    if not effects or not all(isinstance(effect, str) for effect in effects):
        raise SpriteCoverageError("ExplosionEffect.effect domain is unresolved")
    resource_expression = next((
        node.value for node in ast.walk(constructor)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and
        node.value is not None and any(
            isinstance(target, ast.Name) and target.id == "resource_type"
            for target in (node.targets if isinstance(node, ast.Assign)
                           else [node.target]))
    ), None)
    if resource_expression is None:
        raise SpriteCoverageError("ExplosionEffect resource selector disappeared")

    result: set[tuple[int, int]] = set()
    for effect in sorted(effects):
        record = sequence_map.get(effect)
        if (not isinstance(record, tuple) or len(record) != 2 or
                not all(isinstance(value, int) for value in record)):
            raise SpriteCoverageError(
                f"ExplosionEffect sequence is not finite for {effect!r}")
        resource = _pure_selector(resource_expression, effect=effect)
        if not isinstance(resource, int):
            raise SpriteCoverageError(
                f"ExplosionEffect resource is not integral for {effect!r}")
        pointer = int(record[0]) & 0xFFFF
        for _ in range(128):
            duration = rom.word(pointer)
            if duration == 0:
                break
            descriptor = rom.word(pointer + 2)
            result.add((descriptor, resource & 0xFF))
            # `$E817` is the only explosion variant emitted by the adjacent
            # two-record draw sink; the predicate comes from the active draw
            # method and the effect value propagated through constructors.
            if effect == "e817":
                result.add((_u16(descriptor + 6), resource & 0xFF))
            pointer = _u16(pointer + 4)
        else:
            raise SpriteCoverageError(
                f"unterminated ExplosionEffect sequence {effect!r}")
    return result


def _state_test_values(test: ast.AST) -> tuple[set[str], bool] | None:
    """Decode a direct ``self.state`` equality/membership test.

    The boolean is true for the listed set and false when the test is its
    negation.  More complicated predicates are intentionally not guessed.
    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(
            test.comparators) != 1:
        return None
    if ast.unparse(test.left) != "self.state":
        return None
    comparator = test.comparators[0]
    values: set[str] = set()
    if isinstance(comparator, ast.Constant) and isinstance(
            comparator.value, str):
        values.add(comparator.value)
    elif isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
        for item in comparator.elts:
            if not isinstance(item, ast.Constant) or not isinstance(
                    item.value, str):
                return None
            values.add(item.value)
    else:
        return None
    if isinstance(test.ops[0], (ast.Eq, ast.In)):
        return values, True
    if isinstance(test.ops[0], (ast.NotEq, ast.NotIn)):
        return values, False
    return None


def _statement_state_guard(
        function: ast.FunctionDef, line: int,
        ) -> tuple[set[str], set[str]]:
    """Return positive/negative state guards on the lexical sink path."""
    positive: set[str] = set()
    negative: set[str] = set()

    def descend(statements: list[ast.stmt],
                pos: set[str], neg: set[str]) -> bool:
        nonlocal positive, negative
        for statement in statements:
            if statement.lineno == line:
                positive, negative = set(pos), set(neg)
                return True
            if not (statement.lineno <= line <= (statement.end_lineno or
                                                  statement.lineno)):
                continue
            if isinstance(statement, ast.If):
                decoded = _state_test_values(statement.test)
                body_pos, body_neg = set(pos), set(neg)
                else_pos, else_neg = set(pos), set(neg)
                if decoded is not None:
                    states, direct = decoded
                    if direct:
                        body_pos.update(states)
                        else_neg.update(states)
                    else:
                        body_neg.update(states)
                        else_pos.update(states)
                if descend(statement.body, body_pos, body_neg):
                    return True
                if descend(statement.orelse, else_pos, else_neg):
                    return True
            else:
                for field in ("body", "orelse", "finalbody"):
                    child = getattr(statement, field, None)
                    if isinstance(child, list) and descend(child, pos, neg):
                        return True
        return False

    if not descend(function.body, set(), set()):
        raise SpriteCoverageError(
            f"descriptor sink line {line} disappeared from {function.name}")
    return positive, negative


def _ground_walker_pairs(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    sources = _class_resource_sources(
        enemy_tree, abstract, "GroundWalker")
    primary = sources.get(("__init__", "palette"), set())
    secondary = sources.get(("__init__", "self.secondary_palette"), set())
    if len(primary) != 1 or len(secondary) != 1:
        raise SpriteCoverageError(
            "GroundWalker primary/secondary resources are not singular")
    primary_resource = next(iter(primary))
    secondary_resource = next(iter(secondary))
    active = _find_function(enemy_tree, "GroundWalker", "active_palette")
    secondary_states = {
        str(item.value) for item in ast.walk(active)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }
    if not secondary_states:
        raise SpriteCoverageError(
            "GroundWalker.active_palette state domain disappeared")

    result: set[tuple[int, int]] = set()
    for sink, addresses in abstract.descriptor_sink_values.items():
        owner, method = _sink_owner(sink)
        if owner != "GroundWalker":
            continue
        if method == "_fall":
            resource = secondary_resource
        elif method == "__init__":
            # The constructor installs ``state='falling'`` before the event
            # object is first drawn.
            resource = (secondary_resource if "falling" in secondary_states
                        else primary_resource)
        elif method == "update":
            try:
                line = int(sink.split(":", 2)[1])
            except (IndexError, ValueError) as exc:
                raise SpriteCoverageError(
                    f"malformed GroundWalker sink {sink}") from exc
            positive, _negative = _statement_state_guard(
                _find_function(enemy_tree, "GroundWalker", "update"), line)
            resource = (secondary_resource
                        if positive & secondary_states else primary_resource)
        else:
            raise SpriteCoverageError(
                f"unknown GroundWalker descriptor owner {sink}")
        result.update((address, resource) for address in addresses)
    return result


def _terrain_bound_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    sources = _class_resource_sources(
        enemy_tree, abstract, "TerrainBound55E9")
    normal = sources.get(("__init__", "palette"), set())
    speed = sources.get(("_collect", "self.palette"), set())
    if len(normal) != 1 or len(speed) != 1:
        raise SpriteCoverageError(
            "TerrainBound55E9 fixed resource epochs changed")
    normal_resource = next(iter(normal))
    speed_resource = next(iter(speed))
    result = {
        (address, normal_resource)
        for address in _class_sink_addresses(
            abstract, "TerrainBound55E9",
            exclude_methods=("take_damage", "_update_pickup",
                             "_update_speed_indicator"))
    }
    result.update(
        (address, speed_resource)
        for address in _class_sink_addresses(
            abstract, "TerrainBound55E9",
            methods=("_update_speed_indicator",)))

    take_damage = _compile_method(
        _find_function(enemy_tree, "TerrainBound55E9", "take_damage"),
        {"ExplosionE7BE": lambda *_args, **_kwargs: object()},
    )

    class IdentityResources:
        @staticmethod
        def acquire(resource_type: int) -> int:
            return resource_type & 0xFF

        @staticmethod
        def release(_slot: int) -> None:
            return None

    pickup_indexes = _int_values(abstract.field_domain(
        "TerrainBound55E9", "pickup_index"))
    if pickup_indexes is None:
        raise SpriteCoverageError(
            "TerrainBound55E9 pickup_index is not finite")
    pickup_domains: set[tuple[int, int]] = set()
    for pickup_index in pickup_indexes:
        for frame_counter in (0, 2):
            enemy = SimpleNamespace(
                state="script", hp=1, palette=0, pickup_index=pickup_index,
                pickup_type=0, pickup_phase=0, shootable=True, hostile=True,
                collision_table=0, descriptor=0, x=0, y=0,
            )
            world = SimpleNamespace(
                resources=IdentityResources(), rom=rom,
                frame_counter=frame_counter, pending=[],
                award_score_pointer=lambda _pointer: None,
            )
            take_damage(enemy, world, 1)
            pickup_domains.add((enemy.pickup_type & 0xFF,
                                enemy.palette & 0xFF))
            result.add((enemy.descriptor & 0xFFFF,
                        enemy.palette & 0xFF))

    update_pickup = _compile_method(
        _find_function(enemy_tree, "TerrainBound55E9", "_update_pickup"),
        {"_u16": _u16},
    )
    for pickup_type, resource in pickup_domains:
        phases = range(12) if pickup_type == 8 else range(1)
        for phase in phases:
            enemy = SimpleNamespace(
                pickup_type=pickup_type, pickup_phase=phase,
                x=0x0180, y=0x0100, descriptor=0, alive=True,
                _overlaps_player=lambda *_args: False,
                _collect=lambda _world: None,
            )
            world = SimpleNamespace(
                frame_counter=1, player_native=(0, 0))
            update_pickup(enemy, world, 0)
            result.add((enemy.descriptor & 0xFFFF, resource))
    return result


def _transition_stream_addresses(
        enemy_tree: ast.Module, rom: _WorldRom, class_name: str,
        transition_method: str,
        ) -> set[int]:
    function = _find_function(enemy_tree, class_name, transition_method)
    pointer_fields: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target])
        if not any(isinstance(target, ast.Attribute) and
                   target.attr == "descriptor" for target in targets):
            continue
        for item in ast.walk(node.value):
            if (isinstance(item, ast.Attribute) and
                    ast.unparse(item.value) == "self" and
                    "pointer" in item.attr):
                pointer_fields.add(item.attr)
    if len(pointer_fields) != 1:
        raise SpriteCoverageError(
            f"{class_name}.{transition_method} cursor shape changed")
    field = next(iter(pointer_fields))
    seeds: set[int] = set()
    class_node = _find_class(enemy_tree, class_name)
    for node in ast.walk(class_node):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target])
        if not any(isinstance(target, ast.Attribute) and
                   ast.unparse(target.value) == "self" and
                   target.attr == field for target in targets):
            continue
        literal = _safe_ast_literal(node.value)
        if isinstance(literal, int) and literal:
            seeds.add(literal & 0xFFFF)
    if not seeds:
        raise SpriteCoverageError(
            f"{class_name}.{field} has no finite active seed")
    result: set[int] = set()
    for seed in seeds:
        pointer = seed
        for _ in range(128):
            if rom.word(pointer) == 0:
                break
            result.add(rom.word(pointer + 2))
            pointer = _u16(pointer + 4)
        else:
            raise SpriteCoverageError(
                f"{class_name}.{field} ROM stream is unterminated")
    return result


def _resource_epoch_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        class_name: str, *, normal_method: str = "__init__",
        transition_method: str = "_update_explosion",
        ) -> set[tuple[int, int]]:
    """Pair normal and in-place transition descriptor epochs exactly."""
    sources = _class_resource_sources(enemy_tree, abstract, class_name)
    normal_values: set[int] = set()
    transition_values: set[int] = set()
    for (method, target), values in sources.items():
        if method == normal_method and target in ("palette", "self.palette"):
            normal_values.update(values)
        elif method in (transition_method, "_begin_explosion") and target == "self.palette":
            transition_values.update(values)
    if len(normal_values) != 1 or len(transition_values) != 1:
        raise SpriteCoverageError(
            f"{class_name} resource epochs are not singular: "
            f"normal={sorted(normal_values)}, transition={sorted(transition_values)}")
    normal = next(iter(normal_values))
    transition = next(iter(transition_values))
    transitioned = _transition_stream_addresses(
        enemy_tree, rom, class_name, transition_method)
    ordinary = _class_sink_addresses(
        abstract, class_name, exclude_methods=(transition_method,))
    if not transitioned or not ordinary:
        raise SpriteCoverageError(
            f"{class_name} lost a normal/transition descriptor epoch")
    return ({(address, normal) for address in ordinary} |
            {(address, transition) for address in transitioned})


def _terrain_modifier_pairs(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    class_name = "TerrainModifierChild6C37"
    sources = _class_resource_sources(enemy_tree, abstract, class_name)
    normal = sources.get(("__init__", "palette"), set())
    death = sources.get(("take_damage", "self.palette"), set())
    if len(normal) != 1 or len(death) != 1:
        raise SpriteCoverageError(
            "TerrainModifierChild6C37 resource epochs changed")
    normal_resource = next(iter(normal))
    death_resource = next(iter(death))
    update = _find_function(enemy_tree, class_name, "update")
    result: set[tuple[int, int]] = set()
    for sink, addresses in abstract.descriptor_sink_values.items():
        owner, method = _sink_owner(sink)
        if owner != class_name or method != "update":
            continue
        line = int(sink.split(":", 2)[1])
        positive, _negative = _statement_state_guard(update, line)
        resource = (death_resource if "death_6d15" in positive
                    else normal_resource)
        result.update((address, resource) for address in addresses)
    if not result:
        raise SpriteCoverageError(
            "TerrainModifierChild6C37 has no rendered descriptor epoch")
    return result


def _dobkeratops_body_pairs(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    class_name = "DobkeratopsBody"
    sources = _class_resource_sources(enemy_tree, abstract, class_name)
    intro = sources.get(("__init__", "palette"), set())
    emerged = sources.get(("update", "self.palette"), set())
    flash = sources.get(("update", "self.flash_palette"), set())
    if len(intro) != 1 or len(emerged) != 1 or len(flash) != 1:
        raise SpriteCoverageError("DobkeratopsBody palette epochs changed")
    intro_resource = next(iter(intro))
    emerged_resource = next(iter(emerged))
    flash_resource = next(iter(flash))
    update = _find_function(enemy_tree, class_name, "update")
    result: set[tuple[int, int]] = set()
    active_addresses: set[int] = set()
    for sink, addresses in abstract.descriptor_sink_values.items():
        owner, method = _sink_owner(sink)
        if owner != class_name:
            continue
        if method == "__init__":
            states = {"intro"}
        elif method == "update":
            states, _negative = _statement_state_guard(
                update, int(sink.split(":", 2)[1]))
        else:
            raise SpriteCoverageError(
                f"unknown DobkeratopsBody descriptor owner {sink}")
        if "active" in states:
            active_addresses.update(addresses)
            result.update((address, emerged_resource)
                          for address in addresses)
            result.update((address, flash_resource)
                          for address in addresses)
        elif "emerge" in states:
            result.update((address, emerged_resource)
                          for address in addresses)
        else:
            result.update((address, intro_resource)
                          for address in addresses)
    if not active_addresses:
        raise SpriteCoverageError(
            "DobkeratopsBody active descriptor epoch disappeared")
    return result


def _child_8d85_pairs(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        extras: Mapping[str, set[int]],
        ) -> set[tuple[int, int]]:
    class_name = "Child8D85"
    sources = _class_resource_sources(enemy_tree, abstract, class_name)
    normal = sources.get(("__init__", "palette"), set())
    flash = sources.get(("__init__", "self.flash_palette"), set())
    if len(normal) != 1 or len(flash) != 1:
        raise SpriteCoverageError("Child8D85 palette sources changed")
    normal_resource = next(iter(normal))
    flash_resource = next(iter(flash))
    all_addresses = (_class_sink_addresses(abstract, class_name) |
                     extras.get(class_name, set()))
    update = _find_function(enemy_tree, class_name, "update")
    active_addresses: set[int] = set()
    for sink, addresses in abstract.descriptor_sink_values.items():
        owner, method = _sink_owner(sink)
        if owner != class_name or method != "update":
            continue
        positive, negative = _statement_state_guard(
            update, int(sink.split(":", 2)[1]))
        # The final active body is reached only after the scripted and
        # terminal early-return branches.  Its descriptor sink has no
        # positive lexical state, but both states are excluded by control
        # flow; distinguish it by the two known guarded sinks above rather
        # than widening flash to them.
        if not positive or positive.isdisjoint({"scripted", "terminal"}):
            active_addresses.update(addresses)
    # The adjacent composite draw applies to every Child8D85 descriptor.
    active_addresses |= {
        _u16(address + 6) for address in active_addresses
    }
    return ({(address, normal_resource) for address in all_addresses} |
            {(address, flash_resource) for address in active_addresses})


def _initializer_resource_roots(
        enemy_tree: ast.Module, class_name: str,
        ) -> dict[int, tuple[str, int, int]]:
    """Read constructor initializer branches/constant table relationally."""
    constant = None
    try:
        constant = _class_constant(enemy_tree, class_name, "INITIALIZERS")
    except SpriteCoverageError:
        pass
    if isinstance(constant, _FrozenMap):
        result: dict[int, tuple[str, int, int]] = {}
        for key, value in constant.items:
            if (not isinstance(key, int) or not isinstance(value, tuple) or
                    len(value) != 3 or not isinstance(value[0], str) or
                    not isinstance(value[1], int) or
                    not isinstance(value[2], int)):
                raise SpriteCoverageError(
                    f"{class_name}.INITIALIZERS changed shape")
            result[key] = (value[0], value[1] & 0xFF,
                           value[2] & 0xFFFF)
        return result

    constructor = _find_function(enemy_tree, class_name, "__init__")
    result = {}
    for branch in ast.walk(constructor):
        if not isinstance(branch, ast.If) or not isinstance(
                branch.test, ast.Compare):
            continue
        test = branch.test
        if (ast.unparse(test.left) != "initializer" or
                len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq) or
                len(test.comparators) != 1 or not isinstance(
                    test.comparators[0], ast.Constant) or not isinstance(
                    test.comparators[0].value, int)):
            continue
        values: dict[str, object] = {}
        for statement in branch.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (statement.targets if isinstance(statement, ast.Assign)
                       else [statement.target])
            if (len(targets) == 1 and
                    (isinstance(targets[0], ast.Name) or
                     (isinstance(targets[0], ast.Attribute) and
                      ast.unparse(targets[0].value) == "self")) and
                    statement.value is not None):
                literal = _safe_ast_literal(statement.value)
                if literal is not _ABSTRACT_UNKNOWN:
                    name = (targets[0].id if isinstance(targets[0], ast.Name)
                            else targets[0].attr)
                    values[name] = literal
        if (isinstance(values.get("state"), str) and
                isinstance(values.get("resource_type"), int) and
                isinstance(values.get("descriptor"), int)):
            result[int(test.comparators[0].value)] = (
                str(values["state"]), int(values["resource_type"]) & 0xFF,
                int(values["descriptor"]) & 0xFFFF)
    if not result:
        raise SpriteCoverageError(
            f"{class_name} initializer relation is not finite")
    return result


def _scripted_motion_phase_domain(
        rom: _WorldRom, scripts: Iterable[int],
        ) -> set[int]:
    """Execute the finite phase alphabet of concrete `$F5C1` script roots."""
    phases = {0}
    pending_tables = [_u16(script) for script in scripts]
    visited_tables: set[int] = set()
    if not pending_tables:
        raise SpriteCoverageError("ScriptedMotion relation has no script roots")
    while pending_tables:
        table = pending_tables.pop()
        for _ in range(0x400):
            if table in visited_tables:
                break
            visited_tables.add(table)
            word = rom.word(table)
            if word == 0:
                # This is the same carry/return boundary as active
                # ``ScriptedMotion.update``.  The redirect belongs to the
                # caller's next state, not to the current render path.
                break
            if word & 0xFF00 == 0xF000:
                table = _u16(table + 2)
                continue
            pointer = word
            for _ in range(0x1000):
                command = rom.byte(pointer)
                if command & 0x80:
                    phases.add(command & 0x1F)
                pointer = _u16(pointer + 1)
                if command & 0x04:
                    break
            else:
                raise SpriteCoverageError(
                    f"ScriptedMotion ${table:04X} command stream is unterminated")
            table = _u16(table + 2)
        else:
            raise SpriteCoverageError(
                f"ScriptedMotion ${table:04X} table is unterminated")
    return phases


def _parent_sequence_initializers(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult, parent_name: str, child_name: str,
        ) -> set[int]:
    """Read every child initializer from the active parent's ROM sequence.

    The AST proof deliberately owns the call argument, ROM read, four-byte
    cursor advance and zero-delay terminator before any bytes are interpreted.
    """
    update = _find_function(enemy_tree, parent_name, "update")
    constructor = _find_function(enemy_tree, child_name, "__init__")
    parameters = [
        argument.arg for argument in
        list(constructor.args.posonlyargs) + list(constructor.args.args)
        if argument.arg != "self"
    ]
    try:
        initializer_index = parameters.index("initializer")
    except ValueError as exc:
        raise SpriteCoverageError(
            f"{child_name} constructor lost initializer parameter") from exc
    calls = [
        node for node in ast.walk(update)
        if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and node.func.id == child_name
    ]
    if len(calls) != 1 or len(calls[0].args) <= initializer_index:
        raise SpriteCoverageError(
            f"{parent_name} child-construction shape changed")
    initializer_argument = calls[0].args[initializer_index]
    if not isinstance(initializer_argument, ast.Name):
        raise SpriteCoverageError(
            f"{parent_name} initializer argument is no longer a local")
    initializer_local = initializer_argument.id

    initializer_reads = []
    delay_locals: set[str] = set()
    for statement in ast.walk(update):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or \
                statement.value is None:
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target])
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        value = statement.value
        if (isinstance(value, ast.Call) and
                isinstance(value.func, ast.Attribute) and
                value.func.attr == "word" and len(value.args) == 1):
            expression = ast.unparse(value.args[0])
            if (targets[0].id == initializer_local and
                    expression == "self.sequence"):
                initializer_reads.append(statement)
            elif expression == "self.sequence + 2":
                delay_locals.add(targets[0].id)
    advances = [
        node for node in ast.walk(update)
        if (isinstance(node, ast.AugAssign) and
            ast.unparse(node.target) == "self.sequence" and
            isinstance(node.op, ast.Add) and
            isinstance(node.value, ast.Constant) and node.value.value == 4)
    ]
    terminal_tests = [
        node for node in ast.walk(update)
        if (isinstance(node, ast.Compare) and len(node.ops) == 1 and
            isinstance(node.ops[0], ast.Eq) and
            isinstance(node.left, ast.Name) and node.left.id in delay_locals and
            len(node.comparators) == 1 and
            isinstance(node.comparators[0], ast.Constant) and
            node.comparators[0].value == 0)
    ]
    if (len(initializer_reads) != 1 or len(delay_locals) != 1 or
            len(advances) != 1 or len(terminal_tests) != 1):
        raise SpriteCoverageError(
            f"{parent_name} ROM initializer stream shape changed")

    seeds = _int_values(abstract.field_domain(parent_name, "sequence"))
    if seeds is None or not seeds:
        raise SpriteCoverageError(
            f"{parent_name}.sequence domain is unresolved")
    result: set[int] = set()
    for seed in seeds:
        pointer = _u16(seed)
        for _ in range(128):
            result.add(rom.word(pointer))
            delay = rom.word(pointer + 2)
            if delay == 0:
                break
            pointer = _u16(pointer + 4)
        else:
            raise SpriteCoverageError(
                f"{parent_name} initializer stream is unterminated")
    return result


def _class_flash_resource(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        class_name: str,
        ) -> int:
    sources = _class_resource_sources(enemy_tree, abstract, class_name)
    values = set().union(*(
        domain for (method, target), domain in sources.items()
        if method == "__init__" and target == "self.flash_palette"
    )) if sources else set()
    if len(values) != 1:
        raise SpriteCoverageError(
            f"{class_name} flash resource is not singular")
    return next(iter(values))


def _multipart915b_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    """Execute each reachable `$915B` child state without base×phase widening."""
    class_name = "Multipart915BChild"
    initializers = _initializer_resource_roots(enemy_tree, class_name)
    possible = _parent_sequence_initializers(
        enemy_tree, rom, abstract, "Multipart915BParent", class_name)
    unknown = possible - set(initializers)
    if unknown:
        raise SpriteCoverageError(
            f"{class_name} unknown ROM initializers: " +
            ", ".join(f"${value:04X}" for value in sorted(unknown)))
    roots = _int_values(abstract.field_domain(
        "Multipart915BParent", "motion_root"))
    if roots is None:
        raise SpriteCoverageError(
            "Multipart915BParent.motion_root domain is unresolved")
    phases = _scripted_motion_phase_domain(rom, roots)

    state_resources: dict[str, set[int]] = {}
    initial_descriptors: list[tuple[int, int]] = []
    for initializer in sorted(possible):
        state, resource, descriptor = initializers[initializer]
        state_resources.setdefault(state, set()).add(resource)
        initial_descriptors.append((descriptor, resource))

    contact = _find_function(enemy_tree, class_name, "player_contact")
    guards = [
        str(test.comparators[0].value)
        for test in ast.walk(contact)
        if (isinstance(test, ast.Compare) and len(test.ops) == 1 and
            isinstance(test.ops[0], ast.NotEq) and
            ast.unparse(test.left) == "self.state" and
            len(test.comparators) == 1 and
            isinstance(test.comparators[0], ast.Constant) and
            isinstance(test.comparators[0].value, str))
    ]
    targets = [
        str(statement.value.value)
        for statement in ast.walk(contact)
        if (isinstance(statement, (ast.Assign, ast.AnnAssign)) and
            statement.value is not None and
            isinstance(statement.value, ast.Constant) and
            isinstance(statement.value.value, str) and
            any(isinstance(target, ast.Attribute) and
                ast.unparse(target.value) == "self" and target.attr == "state"
                for target in (statement.targets if isinstance(
                    statement, ast.Assign) else [statement.target])))
    ]
    if len(guards) != 1 or len(targets) != 1 or guards[0] not in state_resources:
        raise SpriteCoverageError(
            f"{class_name}.player_contact state transition changed")
    state_resources[targets[0]] = set(state_resources[guards[0]])

    update_node = _find_function(enemy_tree, class_name, "update")
    frame_domain = _masked_frame_counter_domain(update_node)
    render = _compile_method(
        _find_function(enemy_tree, class_name, "_render_phase"))
    update = _compile_method(
        update_node, {"_u16": _u16})

    class FixedRng:
        @staticmethod
        def next() -> int:
            return 0

    descriptors_by_state: dict[str, set[int]] = {
        state: set() for state in state_resources
    }
    # The full 16-bit frame domain and the exact ROM phase alphabet preserve
    # any correlation in the active state branch.  This is intentionally not
    # the old Cartesian arithmetic on helper parameters: each pair is the
    # result of one concrete method execution.
    for state in sorted(state_resources):
        for phase in sorted(phases):
            for frame_counter in frame_domain:
                owner = SimpleNamespace(
                    root=SimpleNamespace(
                        controller_flash=False, controller_handler=0),
                    state=state,
                    motion=SimpleNamespace(phase=phase),
                    descriptor=0,
                    pulse_timer=1,
                    pulse_reload=1,
                    pulse=0,
                    previous=SimpleNamespace(pulse=1, state="main"),
                    x=0x0180,
                    y=0x0100,
                )
                owner._render_phase = lambda base, selected=None, _owner=owner: (
                    render(_owner, base, selected))
                owner._controller_cleanup = lambda: None
                owner._motion = lambda _world: True
                owner._spawn_radial = lambda _world: None
                world = SimpleNamespace(
                    stage_controller_handler=0,
                    frame_counter=frame_counter,
                    rng=FixedRng(),
                    player_native=(0, 0),
                )
                update(owner, world, 0)
                descriptors_by_state[state].add(owner.descriptor & 0xFFFF)

    result = set(initial_descriptors)
    for state, resources in state_resources.items():
        if not descriptors_by_state[state]:
            raise SpriteCoverageError(
                f"{class_name}.{state} produced no descriptors")
        result.update(
            (descriptor, resource)
            for descriptor in descriptors_by_state[state]
            for resource in resources)
    flash = _class_flash_resource(enemy_tree, abstract, class_name)
    result.update((descriptor, flash)
                  for descriptors in descriptors_by_state.values()
                  for descriptor in descriptors)
    result.update((descriptor, flash)
                  for descriptor, _resource in initial_descriptors)
    return result


def _formation78f8_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    """Execute correlated `$78F8` initializer/state render paths."""
    class_name = "Formation78F8Child"
    initializers = _initializer_resource_roots(enemy_tree, class_name)
    possible = _parent_sequence_initializers(
        enemy_tree, rom, abstract, "Formation78F8Parent", class_name)
    unknown = possible - set(initializers)
    if unknown:
        raise SpriteCoverageError(
            f"{class_name} unknown ROM initializers: " +
            ", ".join(f"${value:04X}" for value in sorted(unknown)))

    parent_roots = _int_values(abstract.field_domain(
        "Formation78F8Parent", "motion_root"))
    follow_roots = _int_values(abstract.parameter_domain(
        class_name, "_set_motion_state", "root"))
    if parent_roots is None or follow_roots is None:
        raise SpriteCoverageError(
            f"{class_name} motion-root relation is unresolved")
    parent_phases = _scripted_motion_phase_domain(rom, parent_roots)
    follow_phases = _scripted_motion_phase_domain(rom, follow_roots)

    state_resources: dict[str, set[int]] = {}
    base_by_state: dict[str, int] = {}
    initial_descriptors: list[tuple[int, int]] = []
    for initializer in sorted(possible):
        state, resource, descriptor = initializers[initializer]
        state_resources.setdefault(state, set()).add(resource)
        previous = base_by_state.setdefault(state, descriptor)
        if previous != descriptor:
            raise SpriteCoverageError(
                f"{class_name}.{state} has conflicting descriptor roots")
        initial_descriptors.append((descriptor, resource))

    update_node = _find_function(enemy_tree, class_name, "update")
    linked_calls: dict[str, tuple[int, str]] = {}
    for call in ast.walk(update_node):
        if (not isinstance(call, ast.Call) or
                not isinstance(call.func, ast.Attribute) or
                ast.unparse(call.func.value) != "self" or
                call.func.attr != "_update_linked" or len(call.args) < 5):
            continue
        positive, _negative = _statement_state_guard(update_node, call.lineno)
        base = _safe_ast_literal(call.args[2])
        follow = _safe_ast_literal(call.args[4])
        if (len(positive) != 1 or not isinstance(base, int) or
                not isinstance(follow, str)):
            raise SpriteCoverageError(
                f"{class_name} linked-state call shape changed")
        state = next(iter(positive))
        linked_calls[state] = (base & 0xFFFF, follow)
    if not linked_calls or not set(linked_calls).issubset(state_resources):
        raise SpriteCoverageError(
            f"{class_name} linked-state ownership changed")

    begin_escape = _find_function(enemy_tree, class_name, "_begin_escape")
    escape_states = {
        str(statement.value.value)
        for statement in ast.walk(begin_escape)
        if (isinstance(statement, (ast.Assign, ast.AnnAssign)) and
            statement.value is not None and
            isinstance(statement.value, ast.Constant) and
            isinstance(statement.value.value, str) and
            any(isinstance(target, ast.Attribute) and
                ast.unparse(target.value) == "self" and target.attr == "state"
                for target in (statement.targets if isinstance(
                    statement, ast.Assign) else [statement.target])))
    }
    if len(escape_states) != 1:
        raise SpriteCoverageError(
            f"{class_name} escape state selector changed")
    escape_state = next(iter(escape_states))
    for state, (base, follow) in linked_calls.items():
        if base_by_state.get(state) != base:
            raise SpriteCoverageError(
                f"{class_name}.{state} update root no longer matches constructor")
        state_resources.setdefault(follow, set()).update(
            state_resources[state])

    frame_domain = _masked_frame_counter_domain(update_node)
    draw_phase = _compile_method(
        _find_function(enemy_tree, class_name, "_draw_phase"))
    update = _compile_method(
        update_node, {"_u16": _u16})

    parent_name = "Formation78F8Parent"
    commands = _int_values(abstract.parameter_domain(
        parent_name, "__init__", "command"))
    if commands is None:
        raise SpriteCoverageError(
            f"{parent_name}.command domain is unresolved")
    parent_constructor = _find_function(enemy_tree, parent_name, "__init__")
    priority_statement_index = next((
        index for index, statement in enumerate(parent_constructor.body)
        if (isinstance(statement, (ast.Assign, ast.AnnAssign)) and
            any(isinstance(target, ast.Attribute) and
                ast.unparse(target.value) == "self" and
                target.attr == "priority"
                for target in (statement.targets if isinstance(
                    statement, ast.Assign) else [statement.target])))
    ), None)
    if priority_statement_index is None:
        raise SpriteCoverageError(
            f"{parent_name}.priority constructor selector disappeared")
    priority_prefix = _strip_annotations(parent_constructor)
    priority_prefix.body = (
        priority_prefix.body[:priority_statement_index + 1] +
        [ast.Return(value=ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="priority", ctx=ast.Load()))]
    )
    ast.fix_missing_locations(priority_prefix)
    priority_function = _compile_method(priority_prefix)
    initial_priorities = {
        int(priority_function(
            SimpleNamespace(), SimpleNamespace(rom=rom), command)) & 0xFFFF
        for command in commands
    }
    # Only actually emitted ordinals are needed; count them from the same ROM
    # delay terminator already proved by `_parent_sequence_initializers`.
    child_counts: list[int] = []
    for seed in _int_values(abstract.field_domain(
            parent_name, "sequence")) or ():
        pointer = seed
        for count in range(1, 129):
            if rom.word(pointer + 2) == 0:
                child_counts.append(count)
                break
            pointer = _u16(pointer + 4)
    if not child_counts:
        raise SpriteCoverageError(
            f"{parent_name}.priority has no emitted child ordinals")
    max_children = max(child_counts)
    priorities = {
        _u16(initial - ordinal)
        for initial in initial_priorities
        for ordinal in range(1, max_children + 1)
    }

    def execute(state: str, phase: int, descriptor_base: int,
                priority: int, frame_counter: int) -> int:
        owner = SimpleNamespace(
            state=state,
            motion=SimpleNamespace(phase=phase, commands=2),
            descriptor=0,
            descriptor_base=descriptor_base,
            motion_timer=0,
            shootable=False,
            animation_seed=0,
            x=0x0180,
            y=0x0100,
            priority=priority,
        )
        owner._draw_phase = lambda base, composite=False, _owner=owner: (
            draw_phase(_owner, base, composite))
        owner._motion_or_remove = lambda _world: True
        owner._update_linked = (
            lambda _world, _foreground, base, _collision, _expiry,
            _owner=owner: draw_phase(_owner, base, False))
        owner._integrate_escape = lambda: None
        owner._update_flash = lambda: None
        world = SimpleNamespace(frame_counter=frame_counter)
        update(owner, world, 0)
        return owner.descriptor & 0xFFFF

    descriptors_by_state: dict[str, set[int]] = {}
    for state in sorted(state_resources):
        phases = (follow_phases if state.endswith("_follow")
                  else parent_phases)
        base = base_by_state.get(state)
        if base is None:
            source = next((initial for initial, (_base, follow) in
                           linked_calls.items() if follow == state), None)
            if source is None:
                raise SpriteCoverageError(
                    f"{class_name}.{state} has no descriptor-root provenance")
            base = base_by_state[source]
        descriptors_by_state[state] = {
            execute(state, phase, base, priority, frame_counter)
            for phase in phases
            for priority in priorities
            for frame_counter in frame_domain
        }

    escape_by_resource: dict[int, set[int]] = {}
    # Every animation seed is a live 16-bit RNG result.  Execute the active
    # escape branch so its mask/multiplier remain sourced from Python.
    for state, (base, _follow) in linked_calls.items():
        for resource in state_resources[state]:
            values = escape_by_resource.setdefault(resource, set())
            for animation_seed in range(0x10000):
                owner = SimpleNamespace(
                    state=escape_state,
                    motion=SimpleNamespace(phase=0, commands=2),
                    descriptor=0,
                    descriptor_base=base,
                    motion_timer=0,
                    shootable=False,
                    animation_seed=animation_seed,
                    x=0x0180,
                    y=0x0100,
                    priority=next(iter(priorities)),
                )
                owner._draw_phase = lambda *_args: None
                owner._motion_or_remove = lambda _world: True
                owner._update_linked = lambda *_args: None
                owner._integrate_escape = lambda: None
                owner._update_flash = lambda: None
                update(owner, SimpleNamespace(frame_counter=0), 0)
                values.add(owner.descriptor & 0xFFFF)

    result = set(initial_descriptors)
    for state, resources in state_resources.items():
        descriptors = descriptors_by_state[state]
        if not descriptors:
            raise SpriteCoverageError(
                f"{class_name}.{state} produced no descriptors")
        result.update((descriptor, resource)
                      for descriptor in descriptors for resource in resources)
    for resource, descriptors in escape_by_resource.items():
        result.update((descriptor, resource) for descriptor in descriptors)
    flash = _class_flash_resource(enemy_tree, abstract, class_name)
    visible_descriptors = {descriptor for descriptor, _resource in result}
    result.update((descriptor, flash) for descriptor in visible_descriptors)
    return result


def _root_partition_pairs(
        addresses: Iterable[int], roots: Mapping[int, int],
        ) -> set[tuple[int, int]]:
    """Associate non-overlapping descriptor families with their ROM root."""
    ordered = sorted(roots)
    result: set[tuple[int, int]] = set()
    for address in addresses:
        candidates = [root for root in ordered if address >= root]
        if not candidates:
            raise SpriteCoverageError(
                f"descriptor ${address:04X} precedes every initializer root")
        root = candidates[-1]
        result.add((address & 0xFFFF, roots[root] & 0xFF))
    return result


def _linked_initializer_pairs(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        extras: Mapping[str, set[int]], class_name: str,
        ) -> set[tuple[int, int]]:
    initializers = _initializer_resource_roots(enemy_tree, class_name)
    possible = _int_values(abstract.parameter_domain(
        class_name, "__init__", "initializer"))
    if possible is None:
        raise SpriteCoverageError(
            f"{class_name}.initializer domain is unresolved")
    unknown = set(possible) - set(initializers)
    if unknown:
        raise SpriteCoverageError(
            f"{class_name} unknown initializer values: " +
            ", ".join(f"${value:04X}" for value in sorted(unknown)))
    roots = {
        descriptor: resource
        for initializer, (_state, resource, descriptor) in initializers.items()
        if initializer in possible
    }
    addresses = (_class_sink_addresses(abstract, class_name) |
                 extras.get(class_name, set()))
    result = _root_partition_pairs(addresses, roots)
    sources = _class_resource_sources(enemy_tree, abstract, class_name)
    flash = set().union(*(
        values for (method, target), values in sources.items()
        if method == "__init__" and target == "self.flash_palette"
    )) if sources else set()
    if len(flash) != 1:
        raise SpriteCoverageError(
            f"{class_name} flash resource is not singular")
    flash_resource = next(iter(flash))
    result.update((address, flash_resource) for address in addresses)
    return result


def _boss_random_pairs(
        enemy_tree: ast.Module, abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    class_name = "BossB7FBRandomChild"
    roots = _class_constant(enemy_tree, "BossB7FBRandomChild", "ROOTS")
    if not isinstance(roots, _FrozenMap):
        raise SpriteCoverageError("BossB7FBRandomChild.ROOTS is not static")
    possible = _int_values(abstract.parameter_domain(
        class_name, "__init__", "handler"))
    if possible is None:
        raise SpriteCoverageError(
            "BossB7FBRandomChild.handler domain is unresolved")

    constructor = _find_function(enemy_tree, class_name, "__init__")
    mirror_rules: list[tuple[set[int], int]] = []
    for conditional in ast.walk(constructor):
        if not isinstance(conditional, ast.If):
            continue
        handlers: set[int] | None = None
        for comparison in ast.walk(conditional.test):
            if (not isinstance(comparison, ast.Compare) or
                    len(comparison.ops) != 1 or
                    not isinstance(comparison.ops[0], ast.In) or
                    len(comparison.comparators) != 1 or
                    ast.unparse(comparison.left) != "handler"):
                continue
            literal = _safe_ast_literal(comparison.comparators[0])
            if (isinstance(literal, tuple) and literal and
                    all(isinstance(value, int) for value in literal)):
                handlers = {int(value) for value in literal}
        increments = {
            int(statement.value.value)
            for statement in conditional.body
            if (isinstance(statement, ast.AugAssign) and
                isinstance(statement.target, ast.Name) and
                statement.target.id == "descriptor" and
                isinstance(statement.op, ast.Add) and
                isinstance(statement.value, ast.Constant) and
                isinstance(statement.value.value, int))
        }
        if handlers is not None:
            if len(increments) != 1:
                raise SpriteCoverageError(
                    "BossB7FBRandomChild mirror selector changed shape")
            mirror_rules.append((handlers, next(iter(increments))))
    if len(mirror_rules) != 1:
        raise SpriteCoverageError(
            "BossB7FBRandomChild mirror relation is not singular")
    mirror_handlers, mirror_delta = mirror_rules[0]

    update = _find_function(enemy_tree, class_name, "update")
    phase_expression: ast.AST | None = None
    descriptor_expression: ast.AST | None = None
    for statement in ast.walk(update):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or \
                statement.value is None:
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target])
        if any(isinstance(target, ast.Name) and target.id == "phase"
               for target in targets):
            phase_expression = statement.value
        if any(isinstance(target, ast.Attribute) and
               ast.unparse(target.value) == "self" and
               target.attr == "descriptor" for target in targets):
            descriptor_expression = statement.value
    if phase_expression is None or descriptor_expression is None:
        raise SpriteCoverageError(
            "BossB7FBRandomChild animated descriptor selector disappeared")

    class BossSelectorBinder(ast.NodeTransformer):
        def __init__(self, frame_counter: int) -> None:
            self.frame_counter = frame_counter

        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id == "phase":
                return ast.copy_location(
                    self.visit(copy.deepcopy(phase_expression)), node)
            return node

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            if ast.unparse(node) == "world.frame_counter":
                return ast.copy_location(
                    ast.Constant(self.frame_counter), node)
            return self.generic_visit(node)

    animated_descriptors: set[int] = set()
    # ``frame_counter`` is explicitly a 16-bit world counter.  Exhausting its
    # complete active domain proves the phase relation without copying either
    # the mask or descriptor base from the Python source.
    for frame_counter in range(0x10000):
        expression = BossSelectorBinder(frame_counter).visit(
            copy.deepcopy(descriptor_expression))
        ast.fix_missing_locations(expression)
        value = _pure_selector(expression)
        if not isinstance(value, int):
            raise SpriteCoverageError(
                "BossB7FBRandomChild animated descriptor is not integral")
        animated_descriptors.add(value & 0xFFFF)

    mapping = dict(roots.items)
    result: set[tuple[int, int]] = set()
    for handler in possible:
        value = mapping.get(handler)
        if (not isinstance(value, tuple) or len(value) != 5 or
                not isinstance(value[0], int) or
                not isinstance(value[2], int) or
                not isinstance(value[4], bool)):
            raise SpriteCoverageError(
                f"BossB7FBRandomChild unknown root ${handler:04X}")
        descriptor = value[0] & 0xFFFF
        resource = value[2] & 0xFF
        result.add((descriptor, resource))
        if handler in mirror_handlers:
            result.add((_u16(descriptor + mirror_delta), resource))
        if value[4]:
            result.update((descriptor_address, resource)
                          for descriptor_address in animated_descriptors)
    return result


def _literal_branch_values(expression: ast.AST) -> set[int]:
    """Collect integral leaves from one literal conditional selector."""
    if isinstance(expression, ast.Constant) and isinstance(
            expression.value, int):
        return {int(expression.value)}
    if isinstance(expression, ast.IfExp):
        return (_literal_branch_values(expression.body) |
                _literal_branch_values(expression.orelse))
    raise SpriteCoverageError("selector gained a dynamic branch value")


def _dobkeratops_tentacle_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    """Correlate `$A035` body records with the distinct aimed-tip path."""
    class_name = "DobkeratopsTentacle"
    root_initializer = _find_function(
        enemy_tree, "DobkeratopsRoot", "_spawn_parts")
    constructor = _find_function(enemy_tree, class_name, "__init__")
    calls = [
        node for node in ast.walk(root_initializer)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
        node.func.id == class_name
    ]
    if len(calls) != 2:
        raise SpriteCoverageError(
            "DobkeratopsRoot tentacle allocation shape changed")

    parameters = [
        argument.arg for argument in
        list(constructor.args.posonlyargs) + list(constructor.args.args)
        if argument.arg != "self"
    ]
    record_index = parameters.index("record")
    tip_index = parameters.index("tip")
    defaults = list(constructor.args.defaults)
    positional = list(constructor.args.posonlyargs) + list(constructor.args.args)
    default_offset = len(positional) - len(defaults)
    tip_position = next(index for index, argument in enumerate(positional)
                        if argument.arg == "tip")
    default_tip = _safe_ast_literal(defaults[tip_position - default_offset])
    if not isinstance(default_tip, bool):
        raise SpriteCoverageError(
            "DobkeratopsTentacle.tip default is no longer boolean")

    call_domain: set[tuple[int, bool]] = set()
    for call in calls:
        record_expression = call.args[record_index]
        tip_expression = next((
            keyword.value for keyword in call.keywords
            if keyword.arg == "tip"), None)
        if tip_expression is None and len(call.args) > tip_index:
            tip_expression = call.args[tip_index]
        tip_value = (default_tip if tip_expression is None
                     else _safe_ast_literal(tip_expression))
        if not isinstance(tip_value, bool):
            raise SpriteCoverageError(
                "DobkeratopsTentacle call has dynamic tip selector")
        owner_loop = next((
            loop for loop in ast.walk(root_initializer)
            if isinstance(loop, ast.For) and
            any(item is call for item in ast.walk(loop))
        ), None)
        if owner_loop is None:
            record = _safe_ast_literal(record_expression)
            if not isinstance(record, int):
                raise SpriteCoverageError(
                    "Dobkeratops tip record is not a literal")
            call_domain.add((record & 0xFFFF, tip_value))
            continue
        if not isinstance(owner_loop.target, ast.Name):
            raise SpriteCoverageError(
                "Dobkeratops tentacle loop target changed")
        if (not isinstance(owner_loop.iter, ast.Call) or
                not isinstance(owner_loop.iter.func, ast.Name) or
                owner_loop.iter.func.id != "range"):
            raise SpriteCoverageError(
                "Dobkeratops tentacle loop is no longer a finite range")
        bounds = [_safe_ast_literal(argument)
                  for argument in owner_loop.iter.args]
        if not bounds or not all(isinstance(value, int) for value in bounds):
            raise SpriteCoverageError(
                "Dobkeratops tentacle range is not integral")
        for index in range(*[int(value) for value in bounds]):
            record = _pure_selector(
                record_expression, **{owner_loop.target.id: index})
            if not isinstance(record, int):
                raise SpriteCoverageError(
                    "Dobkeratops tentacle record is not integral")
            call_domain.add((record & 0xFFFF, tip_value))

    selector_if = next((
        node for node in constructor.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "tip"
    ), None)
    if selector_if is None:
        raise SpriteCoverageError(
            "DobkeratopsTentacle descriptor selector disappeared")
    selector = _strip_annotations(constructor)
    selector.body = [
        copy.deepcopy(selector_if),
        ast.Return(value=ast.Name(id="descriptor", ctx=ast.Load())),
    ]
    ast.fix_missing_locations(selector)
    select_descriptor = _compile_method(selector)
    world = SimpleNamespace(rom=rom)
    fixed_descriptors = {
        int(select_descriptor(
            SimpleNamespace(), world, SimpleNamespace(), record, tip)) & 0xFFFF
        for record, tip in call_domain
    }

    direction_function = next((
        node for node in enemy_tree.body
        if isinstance(node, ast.FunctionDef) and
        node.name == "_direction_offset"
    ), None)
    if direction_function is None:
        raise SpriteCoverageError("_direction_offset disappeared")

    directions: set[int] = set()
    for statement in ast.walk(direction_function):
        if isinstance(statement, ast.Return) and statement.value is not None:
            directions.update(_literal_branch_values(statement.value))
    if not directions:
        raise SpriteCoverageError("_direction_offset domain is empty")

    update = _find_function(enemy_tree, class_name, "update")
    tip_assignment = next((
        statement for statement in ast.walk(update)
        if (isinstance(statement, (ast.Assign, ast.AnnAssign)) and
            statement.value is not None and
            any(isinstance(target, ast.Attribute) and
                ast.unparse(target.value) == "self" and
                target.attr == "descriptor"
                for target in (statement.targets if isinstance(
                    statement, ast.Assign) else [statement.target])) and
            any(isinstance(item, ast.Name) and item.id == "direction"
                for item in ast.walk(statement.value)))
    ), None)
    if tip_assignment is None or tip_assignment.value is None:
        raise SpriteCoverageError(
            "DobkeratopsTentacle tip descriptor selector disappeared")
    allowed = (
        ast.Expression, ast.Call, ast.Attribute, ast.Name, ast.Load,
        ast.Constant, ast.BinOp, ast.Add, ast.RShift,
    )
    if any(not isinstance(node, allowed)
           for node in ast.walk(tip_assignment.value)):
        raise SpriteCoverageError(
            "DobkeratopsTentacle tip descriptor selector changed shape")
    expression = ast.Expression(copy.deepcopy(tip_assignment.value))
    ast.fix_missing_locations(expression)
    code = compile(expression, "<tentacle-descriptor-selector>", "eval")
    tip_descriptors = {
        int(eval(code, {"__builtins__": {}},  # noqa: S307 - closed AST.
                 {"world": world, "direction": direction})) & 0xFFFF
        for direction in directions
    }
    resources = abstract.resources.get(class_name, set())
    if len(resources) != 1:
        raise SpriteCoverageError(
            "DobkeratopsTentacle resource is not singular")
    resource = next(iter(resources))
    return {(descriptor, resource)
            for descriptor in fixed_descriptors | tip_descriptors}


def _enemy8f5e_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult,
        ) -> set[tuple[int, int]]:
    """Execute `$8F5E` normal/turn descriptors with direction correlation."""
    class_name = "Enemy8F5E"
    directions = _int_values(abstract.field_domain(class_name, "direction"))
    if directions is None or not directions:
        raise SpriteCoverageError("Enemy8F5E.direction domain is unresolved")

    begin_turn = _find_function(
        enemy_tree, class_name, "_begin_turn_if_near_player")
    direction_branch = next((
        statement for statement in begin_turn.body
        if isinstance(statement, ast.If) and
        any(isinstance(item, ast.Attribute) and
            ast.unparse(item) == "self.direction"
            for item in ast.walk(statement.test))
    ), None)
    if direction_branch is None:
        raise SpriteCoverageError("Enemy8F5E direction branch disappeared")

    class DirectionBinder(ast.NodeTransformer):
        def __init__(self, direction: int) -> None:
            self.direction = direction

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            if ast.unparse(node) == "self.direction":
                return ast.copy_location(ast.Constant(self.direction), node)
            return self.generic_visit(node)

    transitions: set[tuple[int, int]] = set()
    for direction in directions:
        test = DirectionBinder(direction).visit(
            copy.deepcopy(direction_branch.test))
        ast.fix_missing_locations(test)
        selected = (direction_branch.body if _pure_selector(test)
                    else direction_branch.orelse)
        assignments = [
            statement for statement in ast.walk(ast.Module(
                body=selected, type_ignores=[]))
            if (isinstance(statement, (ast.Assign, ast.AnnAssign)) and
                statement.value is not None and
                any(isinstance(target, ast.Attribute) and
                    ast.unparse(target.value) == "self" and
                    target.attr == "next_direction"
                    for target in (statement.targets if isinstance(
                        statement, ast.Assign) else [statement.target])))
        ]
        if len(assignments) != 1 or not isinstance(
                assignments[0].value, ast.IfExp):
            raise SpriteCoverageError(
                "Enemy8F5E next-direction selector changed shape")
        values = _literal_branch_values(assignments[0].value)
        transitions.update((direction, value) for value in values)

    tail_statements: list[ast.stmt] = []
    for target_name in ("matrix_index", "turn_table"):
        statement = next((
            item for item in ast.walk(begin_turn)
            if (isinstance(item, (ast.Assign, ast.AnnAssign)) and
                item.value is not None and any(
                    (isinstance(target, ast.Name) and
                     target_name == "matrix_index" and
                     target.id == target_name) or
                    (isinstance(target, ast.Attribute) and
                     target_name == "turn_table" and
                     ast.unparse(target.value) == "self" and
                     target.attr == target_name)
                    for target in (item.targets if isinstance(
                        item, ast.Assign) else [item.target])))
        ), None)
        if statement is None:
            raise SpriteCoverageError(
                f"Enemy8F5E {target_name} selector disappeared")
        tail_statements.append(copy.deepcopy(statement))
    selector = _strip_annotations(begin_turn)
    selector.body = tail_statements + [ast.Return(value=ast.Attribute(
        value=ast.Name(id="self", ctx=ast.Load()),
        attr="turn_table", ctx=ast.Load()))]
    ast.fix_missing_locations(selector)
    select_table = _compile_method(selector)
    world = SimpleNamespace(rom=rom)
    table_by_transition = {
        transition: int(select_table(
            SimpleNamespace(direction=transition[0],
                            next_direction=transition[1]), world)) & 0xFFFF
        for transition in transitions
    }
    if any(table == 0 for table in table_by_transition.values()):
        raise SpriteCoverageError(
            "Enemy8F5E reachable transition selected a null turn table")

    turn_update_node = _find_function(enemy_tree, class_name, "_turn_update")
    turn_update = _compile_method(turn_update_node, {"_u16": _u16})
    turn_descriptors: set[int] = set()
    for (direction, next_direction), table in table_by_transition.items():
        for timer in range(1, 0x20):
            owner = SimpleNamespace(
                x=0, direction=direction, next_direction=next_direction,
                turn_table=table, turn_timer=timer, descriptor=0)
            turn_update(owner, world, 0)
            turn_descriptors.add(owner.descriptor & 0xFFFF)

    update_node = _find_function(enemy_tree, class_name, "update")
    frame_statement = next((
        item for item in ast.walk(update_node)
        if (isinstance(item, (ast.Assign, ast.AnnAssign)) and
            item.value is not None and any(
                isinstance(target, ast.Name) and target.id == "frame"
                for target in (item.targets if isinstance(
                    item, ast.Assign) else [item.target])))
    ), None)
    descriptor_statement = next((
        item for item in ast.walk(update_node)
        if (isinstance(item, (ast.Assign, ast.AnnAssign)) and
            item.value is not None and any(
                isinstance(target, ast.Attribute) and
                ast.unparse(target.value) == "self" and
                target.attr == "descriptor"
                for target in (item.targets if isinstance(
                    item, ast.Assign) else [item.target])))
    ), None)
    if frame_statement is None or descriptor_statement is None:
        raise SpriteCoverageError(
            "Enemy8F5E normal descriptor selector disappeared")
    normal_selector = _strip_annotations(update_node)
    normal_selector.body = [
        copy.deepcopy(frame_statement),
        copy.deepcopy(descriptor_statement),
        ast.Return(value=ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="descriptor", ctx=ast.Load())),
    ]
    ast.fix_missing_locations(normal_selector)
    select_normal = _compile_method(normal_selector)
    normal_descriptors = {
        int(select_normal(
            SimpleNamespace(direction=direction),
            SimpleNamespace(frame_counter=frame_counter), 0)) & 0xFFFF
        for direction in directions
        for frame_counter in _masked_frame_counter_domain(update_node)
    }
    resources = abstract.resources.get(class_name, set())
    if len(resources) != 1:
        raise SpriteCoverageError("Enemy8F5E resource is not singular")
    resource = next(iter(resources))
    return {(descriptor, resource)
            for descriptor in normal_descriptors | turn_descriptors}


def _is_explosion_class(enemy_tree: ast.Module, class_name: str) -> bool:
    pending = [class_name]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current == "ExplosionEffect":
            return True
        node = next((item for item in enemy_tree.body
                     if isinstance(item, ast.ClassDef) and
                     item.name == current), None)
        if node is not None:
            pending.extend(ast.unparse(base) for base in node.bases)
    return False


def _has_active_palette(enemy_tree: ast.Module, class_name: str) -> bool:
    node = _find_class(enemy_tree, class_name)
    return any(isinstance(item, ast.FunctionDef) and
               item.name == "active_palette" for item in node.body)


def _relational_stage_pairs(
        enemy_tree: ast.Module, rom: _WorldRom,
        abstract: _StageAbstractResult, reachable: set[str],
        extras: Mapping[str, set[int]],
        ) -> tuple[set[tuple[int, int]],
                   dict[str, set[tuple[int, int]]],
                   dict[str, tuple[str, tuple[str, ...]]]]:
    """Build exact descriptor/resource relations owned by state paths.

    A class-wide Cartesian product is deliberately impossible here.  Every
    multi-resource class must match one explicit source-semantic adapter; a
    new palette epoch fails closed until its relation is modelled.
    """
    by_class: dict[str, set[tuple[int, int]]] = {
        class_name: set() for class_name in reachable
    }
    evidence: dict[str, tuple[str, tuple[str, ...]]] = {}
    handled: set[str] = set()

    def mark(class_name: str, kind: str, *sources: str) -> None:
        record = (kind, tuple(sorted(set(sources))))
        previous = evidence.get(class_name)
        if previous is not None and previous != record:
            raise SpriteCoverageError(
                f"{class_name} acquired conflicting relation evidence")
        evidence[class_name] = record

    explosion_classes = {
        class_name for class_name in reachable
        if _is_explosion_class(enemy_tree, class_name)
    }
    if explosion_classes:
        pairs = _explosion_pairs(enemy_tree, rom, abstract)
        by_class.setdefault("ExplosionEffect", set()).update(pairs)
        mark(
            "ExplosionEffect", "effect-sequence-resource-selector",
            "ExplosionEffect.SEQUENCES",
            "ExplosionEffect.__init__:resource_type",
            "reachable Enemy.death_effect fields",
        )
        for class_name in explosion_classes - {"ExplosionEffect"}:
            mark(
                class_name, "inherited-explosion-effect",
                "ExplosionEffect.SEQUENCES",
                "ExplosionEffect.__init__:resource_type",
            )
        handled.update(explosion_classes)

    adapters = {
        "BackgroundParticleE5CD": (
            lambda: _background_particle_pairs(enemy_tree, rom),
            "executed-finite-rom-selector",
            ("BackgroundParticleE5CD.update",)),
        "GroundWalker": (
            lambda: _ground_walker_pairs(enemy_tree, abstract),
            "state-conditioned-active-palette",
            ("GroundWalker.__init__", "GroundWalker.active_palette")),
        "TerrainBound55E9": (
            lambda: _terrain_bound_pairs(enemy_tree, rom, abstract),
            "executed-pickup-state-selector",
            ("TerrainBound55E9.take_damage",
             "TerrainBound55E9._update_pickup")),
        "TerrainModifierChild6C37": (
            lambda: _terrain_modifier_pairs(enemy_tree, abstract),
            "state-conditioned-resource-epoch",
            ("TerrainModifierChild6C37.take_damage",
             "TerrainModifierChild6C37.update")),
        "LargeTerrainChild780E": (
            lambda: _resource_epoch_pairs(
                enemy_tree, rom, abstract, "LargeTerrainChild780E"),
            "normal-versus-transition-rom-stream",
            ("LargeTerrainChild780E.__init__",
             "LargeTerrainChild780E._update_explosion")),
        "Handler60BAProjectile": (
            lambda: _resource_epoch_pairs(
                enemy_tree, rom, abstract, "Handler60BAProjectile"),
            "normal-versus-transition-rom-stream",
            ("Handler60BAProjectile.__init__",
             "Handler60BAProjectile._update_explosion")),
        "Handler60BAChild": (
            lambda: _resource_epoch_pairs(
                enemy_tree, rom, abstract, "Handler60BAChild"),
            "normal-versus-transition-rom-stream",
            ("Handler60BAChild.__init__",
             "Handler60BAChild._update_explosion")),
        "DobkeratopsBody": (
            lambda: _dobkeratops_body_pairs(enemy_tree, abstract),
            "state-conditioned-intro-active-flash",
            ("DobkeratopsBody.__init__", "DobkeratopsBody.update")),
        "DobkeratopsTentacle": (
            lambda: _dobkeratops_tentacle_pairs(
                enemy_tree, rom, abstract),
            "constructor-call-record-tip-correlation",
            ("DobkeratopsRoot._spawn_parts",
             "DobkeratopsTentacle.__init__",
             "DobkeratopsTentacle.update",
             "_direction_offset")),
        "Enemy8F5E": (
            lambda: _enemy8f5e_pairs(enemy_tree, rom, abstract),
            "direction-transition-rom-table-correlation",
            ("Enemy8F5E.__init__",
             "Enemy8F5E._begin_turn_if_near_player",
             "Enemy8F5E._turn_update",
             "Enemy8F5E.update")),
        "Formation78F8Child": (
            lambda: _formation78f8_pairs(enemy_tree, rom, abstract),
            "executed-rom-initializer-state-path-plus-live-flash",
            ("Formation78F8Parent.update",
             "Formation78F8Child.__init__",
             "Formation78F8Child.update",
             "Formation78F8Child.active_palette")),
        "Multipart915BChild": (
            lambda: _multipart915b_pairs(enemy_tree, rom, abstract),
            "executed-rom-initializer-state-path-plus-live-flash",
            ("Multipart915BParent.update",
             "Multipart915BChild.INITIALIZERS",
             "Multipart915BChild.update",
             "Multipart915BChild.active_palette")),
        "BossB7FBRandomChild": (
            lambda: _boss_random_pairs(enemy_tree, abstract),
            "handler-root-mirror-animation-selector",
            ("BossB7FBRandomChild.ROOTS",
             "BossB7FBRandomChild.__init__",
             "BossB7FBRandomChild.update")),
        "Child8D85": (
            lambda: _child_8d85_pairs(enemy_tree, abstract, extras),
            "state-conditioned-active-flash",
            ("Child8D85.__init__", "Child8D85.update")),
    }
    for class_name, (adapter, kind, sources) in adapters.items():
        if class_name not in reachable:
            continue
        pairs = adapter()
        if not pairs:
            raise SpriteCoverageError(
                f"{class_name} relational pair domain is empty")
        by_class[class_name].update(pairs)
        mark(class_name, kind, *sources)
        handled.add(class_name)

    for class_name in sorted(reachable - handled):
        addresses = (_class_sink_addresses(abstract, class_name) |
                     extras.get(class_name, set()))
        resources = abstract.resources.get(class_name, set())
        if not addresses:
            mark(class_name, "no-visible-descriptor-domain", class_name)
            continue
        if not resources:
            # Controllers and palette-$FF records deliberately do not reach
            # the common draw sink.  The caller performs the visible-super
            # validation before accepting the report.
            mark(class_name, "non-visible-controller", class_name)
            continue
        if len(resources) == 1:
            resource = next(iter(resources))
            by_class[class_name].update(
                (address, resource) for address in addresses)
            owned_sources = [
                sink for sink in sorted(abstract.resource_sink_values)
                if _sink_owner(sink)[0] == class_name
            ]
            if not owned_sources:
                # A subclass may inherit its one resource acquisition from a
                # base constructor.  Its concrete descriptor assignment is
                # still the exact source path owning this class relation.
                owned_sources = [
                    sink for sink in sorted(abstract.descriptor_sink_values)
                    if _sink_owner(sink)[0] == class_name
                ]
            mark(
                class_name, "single-resource-exact",
                *owned_sources,
            )
            continue

        sources = _class_resource_sources(
            enemy_tree, abstract, class_name)
        constructor_only = all(
            method == "__init__" for method, _target in sources)
        if _has_active_palette(enemy_tree, class_name) and constructor_only:
            # The active property exposes independently reachable live
            # palette slots (damage flash/controller parity), not a state
            # replacement.  This is the one exact all-address alternative
            # relation; replacement epochs are handled above.
            for resource in sorted(resources):
                by_class[class_name].update(
                    (address, resource) for address in addresses)
            mark(
                class_name, "live-palette-alternative",
                f"{class_name}.active_palette",
                *(sink for sink in sorted(abstract.resource_sink_values)
                  if _sink_owner(sink)[0] == class_name),
            )
            continue
        raise SpriteCoverageError(
            f"{class_name} has unmodelled relational resource domains: "
            f"{sorted(resources)}")

    # `$E7D4` terminal-frame writes occur after the object released itself;
    # retain them with their own sink relation rather than the old global
    # descriptor/resource product.
    body_pairs = by_class.get("DobkeratopsBody", set())
    body_active = {
        pair for pair in body_pairs if pair[1] in {
            value for value in abstract.resources.get("DobkeratopsBody", set())
            if value != 0x15}
    }
    for sink, (descriptors, resources) in sorted(
            abstract.transient_sink_values.items()):
        owner, method = _sink_owner(sink)
        if owner == "DobkeratopsBody":
            by_class[owner].update(body_active)
            continue
        if owner == "" and method == "_update_dobkeratops_e7be":
            # This helper installs the same literal `e7be` `$8530` stream
            # already owned by ExplosionEffect.  Its flow-insensitive
            # `enemy.explosion_pointer` union spans several caller classes;
            # re-adding that union here would recreate the cross-caller
            # pollution this relational pass is designed to reject.
            if resources != {0x01}:
                raise SpriteCoverageError(
                    "_update_dobkeratops_e7be resource changed")
            continue
        if len(resources) != 1:
            raise SpriteCoverageError(
                f"transient sink lost descriptor/resource relation: {sink}")
        resource = next(iter(resources))
        destination = owner if owner in by_class else "ExplosionEffect"
        by_class.setdefault(destination, set()).update(
            (descriptor, resource) for descriptor in descriptors)

    union: set[tuple[int, int]] = set()
    for pairs in by_class.values():
        union.update(pairs)
    missing_evidence = set(by_class) - set(evidence)
    if missing_evidence:
        raise SpriteCoverageError(
            "classes lost relational provenance: " +
            ", ".join(sorted(missing_evidence)))
    return union, by_class, evidence


def _stage_domains(
        project_root: Path, enemy_tree: ast.Module, rom: _WorldRom,
        stages: Iterable[int] = range(1, 9),
        ) -> tuple[
            tuple[tuple[int, tuple[DescriptorResourcePair, ...]], ...],
            tuple[StageCoverageProvenance, ...],
        ]:
    records_by_stage = _stage_event_records(enemy_tree, rom)
    stage_numbers = tuple(stages)
    if (not stage_numbers or len(set(stage_numbers)) != len(stage_numbers) or
            any(stage not in records_by_stage for stage in stage_numbers)):
        raise SpriteCoverageError(
            f"invalid stage coverage selection: {stage_numbers!r}")
    enemy_classes, class_graph = _enemy_class_graph(enemy_tree)
    dispatch_roots = _dispatch_class_roots(enemy_tree, enemy_classes)
    handlers_constant = _class_constant(enemy_tree, "M72EnemyWorld", "HANDLERS")
    delegated_constant = _class_constant(
        enemy_tree, "M72EnemyWorld", "DELEGATED_HANDLERS")
    if not isinstance(handlers_constant, _FrozenMap):
        raise SpriteCoverageError("M72EnemyWorld.HANDLERS is not a static dict")
    implemented_handlers = {
        int(key) for key, _value in handlers_constant.items
        if isinstance(key, int)
    } | {0xE430}
    if not isinstance(delegated_constant, frozenset) or not all(
            isinstance(item, int) for item in delegated_constant):
        raise SpriteCoverageError(
            "M72EnemyWorld.DELEGATED_HANDLERS is not a static frozenset")
    delegated_handlers = {int(item) for item in delegated_constant}
    observed_handlers = {
        record.handler for records in records_by_stage.values()
        for record in records
    }
    unknown_handlers = observed_handlers - implemented_handlers - delegated_handlers
    if unknown_handlers:
        raise SpriteCoverageError(
            "active stage event stream contains unknown handlers: " +
            ", ".join(f"${handler:04X}" for handler in sorted(unknown_handlers)))
    missing_dispatch = {
        handler for handler in implemented_handlers
        if handler != 0xE430 and handler not in dispatch_roots
    }
    if missing_dispatch:
        raise SpriteCoverageError(
            "implemented handler has no AST dispatch ownership: " +
            ", ".join(f"${handler:04X}" for handler in sorted(missing_dispatch)))

    per_stage: list[tuple[int, tuple[DescriptorResourcePair, ...]]] = []
    provenance: list[StageCoverageProvenance] = []

    def class_closure(initial: Iterable[str]) -> set[str]:
        closure: set[str] = set()
        pending = list(initial)
        while pending:
            class_name = pending.pop()
            if class_name in closure:
                continue
            if class_name not in enemy_classes:
                raise SpriteCoverageError(
                    f"dispatch selected non-Enemy class {class_name}")
            closure.add(class_name)
            pending.extend(class_graph[class_name])
        return closure

    for stage in stage_numbers:
        records = records_by_stage[stage]
        handler_counts = Counter(record.handler for record in records)
        command_domains: dict[str, set[int]] = {}
        roots: set[str] = set()
        for record in records:
            for class_name in dispatch_roots.get(record.handler, ()):
                roots.add(class_name)
                command_domains.setdefault(class_name, set()).add(record.command)
        if 0xE430 in handler_counts:
            roots.add("BackgroundParticleE5CD")
        # Both calls are generic active-world consequences of any shootable
        # enemy. Including them is source reachability, not an arcade fallback.
        roots.update(("ExplosionEffect", "EnemyProjectile"))
        handler_classes = []
        for handler in sorted(handler_counts):
            handler_roots = set(dispatch_roots.get(handler, ()))
            if handler == 0xE430:
                handler_roots.add("BackgroundParticleE5CD")
            handler_classes.append((
                handler, tuple(sorted(class_closure(handler_roots)))
                if handler_roots else ()))
        reachable = class_closure(roots)

        abstract = _StageAbstractInterpreter(
            enemy_tree, rom, reachable, command_domains).analyze()
        # `$E430` owns exactly the four resource requests in its active loop;
        # recover them from AST rather than copying the resource bytes.
        if "BackgroundParticleE5CD" in reachable:
            dispatch = _find_function(enemy_tree, "M72EnemyWorld", "_dispatch")
            particle_resources: set[int] = set()
            for node in ast.walk(dispatch):
                if not isinstance(node, ast.If) or _handler_test_value(node.test) != 0xE430:
                    continue
                for loop in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    iterable: ast.AST | None = None
                    if (isinstance(loop, ast.For) and
                            isinstance(loop.target, ast.Name) and
                            loop.target.id == "kind"):
                        iterable = loop.iter
                    elif (isinstance(loop, ast.GeneratorExp) and
                          len(loop.generators) == 1 and
                          isinstance(loop.generators[0].target, ast.Name) and
                          loop.generators[0].target.id == "kind"):
                        iterable = loop.generators[0].iter
                    if iterable is not None:
                        literal = _safe_ast_literal(iterable)
                        if isinstance(literal, tuple):
                            particle_resources.update(
                                int(item) & 0xFF for item in literal
                                if isinstance(item, int))
            if not particle_resources:
                abstract.unresolved.add("E430:particle-resource-domain")
            abstract.resources["BackgroundParticleE5CD"].update(
                particle_resources)

        # Parent allocators read child initializer handlers from terminated
        # ROM streams.  Flow-insensitive call binding sees only the seed
        # cursor; replace that partial constructor parameter with the proven
        # complete stream domain before it crosses the immutable result API.
        for parent_name, child_name in (
                ("Multipart915BParent", "Multipart915BChild"),
                ("Formation78F8Parent", "Formation78F8Child")):
            if child_name not in reachable:
                continue
            abstract.replace_parameter_domain(
                child_name, "__init__", "initializer",
                _parent_sequence_initializers(
                    enemy_tree, rom, abstract, parent_name, child_name))

        extras = _draw_extra_addresses(
            enemy_tree, enemy_classes, abstract)
        (semantic_pairs, class_semantic_pairs,
         relation_evidence) = _relational_stage_pairs(
            enemy_tree, rom, abstract, reachable, extras)
        for class_name in sorted(reachable):
            resources = abstract.resources.get(class_name, set())
            addresses = (_class_sink_addresses(abstract, class_name) |
                         extras.get(class_name, set()))
            if addresses and not resources:
                # Controllers and palette-$FF records are intentionally not
                # rendered. A descriptor-bearing class without provenance is
                # different and must stop compilation.
                class_node = next(
                    node for node in enemy_tree.body
                    if isinstance(node, ast.ClassDef) and node.name == class_name)
                has_visible_super = any(
                    isinstance(call, ast.Call) and
                    isinstance(call.func, ast.Attribute) and
                    call.func.attr == "__init__" and
                    ast.unparse(call.func.value) == "super()" and
                    len(call.args) >= 4 and not (
                        isinstance(call.args[3], ast.Constant) and
                        call.args[3].value == 0xFF)
                    for call in ast.walk(class_node)
                )
                if has_visible_super:
                    abstract.unresolved.add(
                        f"{class_name}:descriptor-without-resource-provenance")

        if abstract.unresolved:
            raise SpriteCoverageError(
                f"stage {stage} has unresolved dynamic sprite domains: " +
                "; ".join(sorted(abstract.unresolved)))
        pairs = tuple(sorted(
            (_pair(project_root, rom, resource, address)
             for address, resource in semantic_pairs),
        ))
        pair_lookup = {
            (pair.descriptor.address, pair.resource_type): pair
            for pair in pairs
        }
        class_coverage: list[ClassCoverageProvenance] = []
        for class_name in sorted(reachable):
            kind, selector_sources = relation_evidence[class_name]
            raw_class_pairs = class_semantic_pairs[class_name]
            missing_pairs = raw_class_pairs - set(pair_lookup)
            if missing_pairs:
                raise AssertionError(
                    f"{class_name} relation escaped stage union: "
                    f"{sorted(missing_pairs)!r}")
            class_coverage.append(ClassCoverageProvenance(
                class_name=class_name,
                relation_kind=kind,
                selector_sources=selector_sources,
                constructor_parameters=tuple(
                    (key[2], values)
                    for key, values in abstract.parameter_domains
                    if key[:2] == (class_name, "__init__")),
                pairs=tuple(sorted(pair_lookup[pair]
                                   for pair in raw_class_pairs)),
                owned_descriptor_sinks=tuple(sorted(
                    sink for sink in abstract.descriptor_sink_values
                    if _sink_owner(sink)[0] == class_name)),
                owned_resource_sinks=tuple(sorted(
                    sink for sink in abstract.resource_sink_values
                    if _sink_owner(sink)[0] == class_name)),
            ))
        raw = b"".join(
            struct.pack("<HHHH", record.address, record.threshold,
                        record.command, record.handler)
            for record in records
        )
        event_first = records[0].address
        event_last = records[-1].address
        cell_count = _cell_count(pairs)
        resource_banks: dict[int, set[PythonBankKey]] = {}
        for pair in pairs:
            resource_banks.setdefault(pair.resource_type, set()).update(
                pair.bank_keys)
        event_class_map = dict(handler_classes)
        per_stage.append((stage, pairs))
        provenance.append(StageCoverageProvenance(
            stage=stage,
            event_first=event_first,
            event_last=event_last,
            event_count=len(records),
            event_sha256=hashlib.sha256(raw).hexdigest(),
            pair_count=len(pairs),
            cell_count=cell_count,
            resource_bank_domains=tuple(
                (resource, tuple(sorted(keys)))
                for resource, keys in sorted(resource_banks.items())),
            handler_counts=tuple(sorted(handler_counts.items())),
            handler_classes=tuple(handler_classes),
            events=tuple(EventCoverageProvenance(
                address=record.address,
                threshold=record.threshold,
                command=record.command,
                handler=record.handler,
                classes=event_class_map[record.handler],
            ) for record in records),
            class_coverage=tuple(class_coverage),
            owned_handlers=tuple(sorted(handler_counts)),
            owned_classes=tuple(sorted(reachable)),
            owned_descriptor_sinks=tuple(sorted(abstract.sink_ids)),
        ))
    return tuple(per_stage), tuple(provenance)


def _common_domains(
        project_root: Path, trees: Mapping[str, ast.Module], rom: _WorldRom,
        owned_sink_ids: tuple[str, ...],
        ) -> tuple[
            tuple[tuple[str, int], ...],
            tuple[tuple[str, tuple[int, ...]], ...],
            tuple[tuple[str, tuple[DescriptorResourcePair, ...]], ...],
            tuple[CommonCoverageProvenance, ...],
            tuple[DescriptorResourcePair, ...],
        ]:
    enemy_tree = trees["rtype_port.enemies"]
    force_tree = trees["rtype_port.force"]
    bits_tree = trees["rtype_port.bits"]
    game_tree = trees["rtype_port.game"]
    lifecycle_tree = trees["rtype_port.player_lifecycle"]
    force_resource = _module_literal(force_tree, "FORCE_RESOURCE_TYPE")
    if force_resource != 0x56:
        raise SpriteCoverageError(
            f"Force resource changed to {force_resource!r} without a model")

    ray_addresses, turning_seeds, mirrored_seeds = _force_ray_addresses(
        force_tree, rom)
    selector_facts = {
        "force_ray_turning_seed_phases": tuple(sorted(turning_seeds)),
        "force_ray_mirrored_seed_phases": tuple(sorted(mirrored_seeds)),
        "force_ray_terminal_initial": (
            _dataclass_int_default(force_tree, "ForceRaySegment",
                                   "terminal_offset"),),
        "force_grid_terminal_initial": (
            _dataclass_int_default(force_tree, "ForceGridSegment",
                                   "terminal_offset"),),
        "force_dart_terminal_initial": (
            _dataclass_int_default(force_tree, "ForceDart",
                                   "terminal_offset"),),
    }

    raw_domains: dict[str, tuple[int, set[int]]] = {
        "player_death": (0x09, _death_addresses(lifecycle_tree)),
        "terminal_shots": (0x01, _terminal_shot_addresses(game_tree)),
        "fixed_shot_visual": (0x02, {_fixed_shot_address(enemy_tree)}),
        "force_body": (int(force_resource),
                       _force_body_addresses(force_tree, rom)),
        "force_projectiles": (0x02,
                              _force_projectile_addresses(force_tree)),
        "force_rays": (0x3D, ray_addresses),
        "force_grids": (0x3D, _force_grid_addresses(force_tree)),
        "force_beams": (0x3D, _force_beam_addresses(force_tree)),
        "force_darts": (0x3D, _force_dart_addresses(force_tree)),
        "player_bits": (0x56, _bits_addresses(bits_tree)),
    }
    expected_counts = {
        "player_death": 8,
        "terminal_shots": 6,
        "fixed_shot_visual": 1,
        "force_body": 31,
        "force_projectiles": 5,
        "force_rays": 16,
        "force_grids": 11,
        "force_beams": 192,
        "force_darts": 15,
        "player_bits": 24,
    }
    actual_counts = {name: len(addresses)
                     for name, (_resource, addresses) in raw_domains.items()}
    if actual_counts != expected_counts:
        raise SpriteCoverageError(
            f"common sprite domains changed: {actual_counts!r}")

    common_domain_pairs = tuple(sorted(
        (name, tuple(sorted(
            _pair(project_root, rom, resource, address)
            for address in addresses
        )))
        for name, (resource, addresses) in raw_domains.items()
    ))
    pairs = {
        pair for _name, domain_pairs in common_domain_pairs
        for pair in domain_pairs
    }
    if len(pairs) != EXPECTED_COMMON_PAIR_COUNT:
        raise SpriteCoverageError(
            f"common sprite coverage has {len(pairs)} pairs, "
            f"expected {EXPECTED_COMMON_PAIR_COUNT}")
    source_symbols = {
        "player_death": (
            "rtype_port.player_lifecycle.DEATH_DESCRIPTOR_RANGES",
            "rtype_port.player_lifecycle.PlayerLifecycle.explosion_descriptor",
        ),
        "terminal_shots": (
            "rtype_port.game.Game._advance_native_shot",
            "rtype_port.game.Game.update",
        ),
        "fixed_shot_visual": (
            "rtype_port.enemies.PlayerShotVisual4EAF.__init__",
        ),
        "force_body": (
            "rtype_port.force.Force._return_descriptor",
            "rtype_port.force.Force._attached_descriptor",
            "rtype_port.force.Force._detached_descriptor",
        ),
        "force_projectiles": (
            "rtype_port.force.Force.update_projectiles",
            "rtype_port.force.Force.draw",
        ),
        "force_rays": (
            "rtype_port.force.Force._fire_attached_type0",
            "rtype_port.force.Force._update_turning_ray",
            "rtype_port.force.Force._update_mirrored_ray",
        ),
        "force_grids": ("rtype_port.force.Force.update_grid_segments",),
        "force_beams": ("rtype_port.force.Force.update_type6",),
        "force_darts": ("rtype_port.force.Force.update_type6",),
        "player_bits": ("rtype_port.bits.PlayerBits._update_one",),
    }
    if set(source_symbols) != set(raw_domains):
        raise AssertionError("common provenance does not own every domain")
    sink_module = {
        "player_death": "rtype_port.game:",
        "terminal_shots": "rtype_port.game:",
        "fixed_shot_visual": "rtype_port.enemies:",
        "force_body": "rtype_port.force:",
        "force_projectiles": "rtype_port.force:",
        "force_rays": "rtype_port.force:",
        "force_grids": "rtype_port.force:",
        "force_beams": "rtype_port.force:",
        "force_darts": "rtype_port.force:",
        "player_bits": "rtype_port.bits:",
    }
    pair_map = dict(common_domain_pairs)
    provenance = tuple(
        CommonCoverageProvenance(
            domain=name,
            resource_type=raw_domains[name][0],
            pair_count=len(pair_map[name]),
            cell_count=_cell_count(pair_map[name]),
            bank_keys=tuple(sorted({
                key for pair in pair_map[name] for key in pair.bank_keys
            })),
            source_symbols=source_symbols[name],
            owned_sink_ids=tuple(
                sink for sink in owned_sink_ids
                if sink.startswith(sink_module[name])),
        )
        for name in sorted(raw_domains)
    )
    return (
        tuple(sorted(actual_counts.items())),
        tuple(sorted(selector_facts.items())),
        common_domain_pairs,
        provenance,
        tuple(sorted(pairs)),
    )


def analyze_sprite_coverage(
        project_root: Path | str | None = None, *,
        source_overrides: Mapping[str, str] | None = None,
        ) -> CoverageReport:
    """Analyze common sprite coverage for the active ``run_python.cmd`` graph.

    ``source_overrides`` exists for focused mutation tests. It never changes the
    source root, ROM, or asset provenance.
    """

    root = (_default_project_root() if project_root is None
            else Path(project_root)).resolve()
    overrides = dict(source_overrides or {})
    trees, texts = _active_graph(root, overrides)
    owned_sinks = _validate_sinks(trees)
    _verify_domain_ast(trees)

    rom_path = (root / "Assets" / "Converted" / "Arcade" /
                "RTYPE_MAINCPU_REGION.bin")
    rom_data = rom_path.read_bytes()
    rom = _WorldRom(rom_data)
    rom_sha256 = hashlib.sha256(rom_data).hexdigest()
    (domain_counts, selector_facts, common_domain_pairs,
     common_provenance, pairs) = _common_domains(
         root, trees, rom, owned_sinks)
    arcade = root / "Assets" / "Converted" / "Arcade"
    asset_signature = tuple(sorted(
        (str(path.relative_to(arcade)).replace("\\", "/"),
         path.stat().st_size, path.stat().st_mtime_ns)
        for directory in (arcade / "ResourceHQ", arcade / "FullHQ")
        if directory.is_dir()
        for path in directory.glob("*.bin")
    ))
    stage_key = (
        str(root),
        hashlib.sha256(texts["rtype_port.enemies"].encode("utf-8")).hexdigest(),
        rom_sha256,
        asset_signature,
    )
    stage_cached = _STAGE_COVERAGE_CACHE.get(stage_key)
    if stage_cached is None:
        stage_cached = _stage_domains(
            root, trees["rtype_port.enemies"], rom)
        _STAGE_COVERAGE_CACHE[stage_key] = stage_cached
    per_stage_pairs, stage_provenance = stage_cached

    command_data = (root / "run_python.cmd").read_bytes()
    source_hashes = [("run_python.cmd", hashlib.sha256(command_data).hexdigest())]
    source_hashes.extend(
        (module, hashlib.sha256(texts[module].encode("utf-8")).hexdigest())
        for module in sorted(texts)
    )
    return CoverageReport(
        root_module=ACTIVE_ROOT_MODULE,
        reachable_modules=tuple(sorted(trees)),
        source_hashes=tuple(source_hashes),
        rom_sha256=rom_sha256,
        owned_sink_ids=owned_sinks,
        domain_counts=domain_counts,
        selector_facts=selector_facts,
        common_domain_pairs=common_domain_pairs,
        common_provenance=common_provenance,
        common_pairs=pairs,
        common_cell_count=_cell_count(pairs),
        per_stage_pairs=per_stage_pairs,
        stage_provenance=stage_provenance,
        unresolved_domains=(),
    )


__all__ = [
    "ACTIVE_ROOT_MODULE",
    "ClassCoverageProvenance",
    "CommonCoverageProvenance",
    "CoverageReport",
    "DescriptorRef",
    "DescriptorResourcePair",
    "EventCoverageProvenance",
    "EXPECTED_COMMON_PAIR_COUNT",
    "PythonBankKey",
    "StageCoverageProvenance",
    "SpriteCoverageError",
    "analyze_sprite_coverage",
    "resolve_python_bank",
]
