"""Source-derived persistent object state for the compact draw VM.

The compact draw VM deliberately accepts a provider which materialises one
28-byte normalized object view at a time.  This module supplies the portable
state half of that provider without recovering object kinds from a handwritten
Z80 handler switch:

* the normalized fields and ``isinstance`` tags come from ``SpriteDrawPlanIR``;
* concrete-class membership masks come from the active Python class graph;
* pool dimensions and list order come from the render-order model;
* every syntactic write to a draw field receives a stable, AST-bound setter
  site id.

The generated state is persistent and indexed by physical pool slot.  It is
not a frame-sized materialisation.  Live mutation hooks and target layout
lowering are intentionally outside this backend; the manifest lists them as
blockers and never claims live readiness.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .draw_plan import SpriteDrawPlanIR, compile_active_enemy_draw_plan
from .draw_vm_backend import (
    VM_OBJECT_VIEW_BYTES,
    build_draw_vm_program,
    emit_draw_vm_backend,
)
from .render_order_backend import (
    NONE_SLOT,
    build_render_order_model,
    emit_render_order_backend,
)


DRAW_STATE_BACKEND_FORMAT = "pyz80.draw-state-sidecar-backend.v1"
DEFAULT_PREFIX = "rtype_python_draw_state"
DEFAULT_VM_PREFIX = "rtype_python_draw_vm"
DEFAULT_ORDER_PREFIX = "rtype_python_render_order"

__all__ = [
    "DRAW_STATE_BACKEND_FORMAT",
    "DEFAULT_PREFIX",
    "DrawStateArtifacts",
    "DrawStateBackendError",
    "DrawStateModel",
    "MutationSite",
    "build_draw_state_model",
    "emit_draw_state_backend",
    "write_draw_state_backend",
]


class DrawStateBackendError(ValueError):
    """A source or ABI shape which cannot be represented safely."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class MutationSite:
    ordinal: int
    field_name: str
    kind: str
    line: int
    column: int
    class_name: str | None
    function_name: str | None
    receiver: str
    source: str
    statement_ast_sha256: str
    site_ast_sha256: str
    hash32: int
    coverage: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "field": self.field_name,
            "kind": self.kind,
            "line": self.line,
            "column": self.column,
            "class": self.class_name,
            "function": self.function_name,
            "receiver": self.receiver,
            "source": self.source,
            "statement_ast_sha256": self.statement_ast_sha256,
            "site_ast_sha256": self.site_ast_sha256,
            "hash32_hex": f"{self.hash32:08x}",
            "setter_schema_coverage": self.coverage,
            "live_hooked": False,
        }


@dataclass(frozen=True)
class DerivedFieldSite:
    field_name: str
    class_name: str
    line: int
    source: str
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field_name,
            "class": self.class_name,
            "line": self.line,
            "source": self.source,
            "ast_sha256": self.ast_sha256,
            "live_dependency_lowering": False,
        }


@dataclass(frozen=True)
class DynamicWriteSite:
    line: int
    class_name: str | None
    function_name: str | None
    source: str
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "line": self.line,
            "class": self.class_name,
            "function": self.function_name,
            "source": self.source,
            "ast_sha256": self.ast_sha256,
            "reason": (
                "dynamic setattr name is not proved disjoint from the "
                "draw-field set"),
            "live_hooked": False,
        }


@dataclass(frozen=True)
class IdentitySite:
    kind: str
    line: int
    class_name: str | None
    function_name: str | None
    source: str
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "line": self.line,
            "class": self.class_name,
            "function": self.function_name,
            "source": self.source,
            "ast_sha256": self.ast_sha256,
            "sidecar_operation_available": {
                "pool-bind": "bind",
                "same-slot-object-replacement": "replace_same_slot",
                "pool-release": "clear",
                "pool-bind-assignment": "bind",
                "checkpoint-bind-assignment": "bind",
                "pool-release-assignment": "clear",
                "same-slot-old-owner-detach": (
                    "no sidecar mutation after replace_same_slot"),
            }[self.kind],
            "live_hooked": False,
        }


@dataclass(frozen=True)
class ConcreteClass:
    name: str
    class_id: int
    membership_tags: tuple[str, ...]
    membership_mask: tuple[int, ...]
    class_ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "class_id": self.class_id,
            "isinstance_tags": list(self.membership_tags),
            "mask_hex": "".join(f"{item:02x}" for item in self.membership_mask),
            "class_ast_sha256": self.class_ast_sha256,
        }


@dataclass(frozen=True)
class DrawStateModel:
    plan: SpriteDrawPlanIR
    source_sha256: str
    launcher_sha256: str
    draw_vm_semantic_sha256: str
    draw_vm_header_sha256: str
    draw_vm_source_sha256: str
    draw_vm_manifest_sha256: str
    render_order_semantic_sha256: str
    render_order_header_sha256: str
    render_order_source_sha256: str
    render_order_manifest_sha256: str
    slot_count: int
    reserved_sentinels: int
    object_root_class: str
    class_bit_bytes: int
    fields: tuple[object, ...]
    concrete_classes: tuple[ConcreteClass, ...]
    mutation_sites: tuple[MutationSite, ...]
    derived_field_sites: tuple[DerivedFieldSite, ...]
    dynamic_write_sites: tuple[DynamicWriteSite, ...]
    identity_sites: tuple[IdentitySite, ...]
    field_storage_bytes: int
    value_bytes: int
    slot_state_bytes: int
    state_bytes: int
    semantic_sha256: str


@dataclass(frozen=True)
class DrawStateArtifacts:
    header_name: str
    source_name: str
    manifest_name: str
    header: str
    source: str
    manifest: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _ast_sha256(value: ast.AST) -> str:
    return _sha256_text(ast.dump(value, include_attributes=False))


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_text(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n"


def _identifier(value: str, *, upper: bool = False) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    result = re.sub(r"_+", "_", result).strip("_")
    if not result or result[0].isdigit():
        result = "v_" + result
    return result.upper() if upper else result.lower()


def _storage_bytes(c_type: str) -> int:
    try:
        return {"uint8_t": 1, "uint16_t": 2, "int16_t": 2}[c_type]
    except KeyError as exc:
        raise DrawStateBackendError(
            "PZDS001", f"field C type {c_type!r} has no sidecar encoding") from exc


def _decorator_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    if isinstance(value, ast.Call):
        return _decorator_name(value.func)
    return None


class _MutationInventory(ast.NodeVisitor):
    """Conservative syntactic inventory; no runtime import is performed."""

    def __init__(self, source: str, fields: Iterable[str]) -> None:
        self.source = source
        self.fields = frozenset(fields)
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.raw_mutations: list[tuple[
            str, str, ast.AST, ast.AST, str, str]] = []
        self.derived: list[DerivedFieldSite] = []
        self.dynamic: list[DynamicWriteSite] = []
        self.identity: list[IdentitySite] = []

    @property
    def class_name(self) -> str | None:
        return self.class_stack[-1] if self.class_stack else None

    @property
    def function_name(self) -> str | None:
        return self.function_stack[-1] if self.function_stack else None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        is_property = any(
            _decorator_name(item) == "property" for item in node.decorator_list)
        if is_property and node.name in self.fields and self.class_name:
            self.derived.append(DerivedFieldSite(
                field_name=node.name,
                class_name=self.class_name,
                line=node.lineno,
                source=(ast.get_source_segment(self.source, node) or
                        ast.unparse(node)),
                ast_sha256=_ast_sha256(node),
            ))
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _record_target(
            self, target: ast.AST, statement: ast.AST, kind: str,
            value: ast.AST | None,
            ) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._record_target(item, statement, kind, value)
            return
        if not isinstance(target, ast.Attribute) or target.attr not in self.fields:
            return
        receiver = ast.unparse(target.value)
        expression = (ast.get_source_segment(self.source, statement) or
                      ast.unparse(statement))
        value_dump = ast.dump(value, include_attributes=False) if value else ""
        self.raw_mutations.append((
            target.attr, kind, target, statement, receiver,
            value_dump + "\n" + expression,
        ))

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            self._record_target(target, node, "assign", node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if (isinstance(node.target, ast.Name) and
                node.target.id in self.fields and self.class_name):
            # Dataclass/class declarations are implicit initialisation/read
            # sources, even though the AST target is not an Attribute node.
            self.raw_mutations.append((
                node.target.id, "class-field-initializer", node.target, node,
                self.class_name,
                ((ast.dump(node.value, include_attributes=False)
                  if node.value is not None else "required-constructor-value") +
                 "\n" + (ast.get_source_segment(self.source, node) or
                            ast.unparse(node))),
            ))
        else:
            self._record_target(node.target, node, "annassign", node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self._record_target(node.target, node, "augassign", node.value)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:  # noqa: N802
        for target in node.targets:
            self._record_target(target, node, "delete", None)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        expression = ast.get_source_segment(self.source, node) or ast.unparse(node)
        if (isinstance(node.func, ast.Name) and node.func.id == "setattr" and
                len(node.args) >= 2):
            name_node = node.args[1]
            if (isinstance(name_node, ast.Constant) and
                    isinstance(name_node.value, str)):
                if name_node.value in self.fields:
                    target = ast.Attribute(
                        value=node.args[0], attr=name_node.value,
                        ctx=ast.Store(), lineno=node.lineno,
                        col_offset=node.col_offset,
                    )
                    self._record_target(
                        target, node, "setattr-literal",
                        node.args[2] if len(node.args) >= 3 else None)
            else:
                self.dynamic.append(DynamicWriteSite(
                    line=node.lineno,
                    class_name=self.class_name,
                    function_name=self.function_name,
                    source=expression,
                    ast_sha256=_ast_sha256(node),
                ))
        if isinstance(node.func, ast.Attribute):
            kind: str | None = None
            receiver = ast.unparse(node.func.value)
            if node.func.attr == "bind" and (
                    receiver == "object_pool" or
                    receiver.endswith(".object_pool")):
                kind = "pool-bind"
            elif node.func.attr == "release" and (
                    receiver == "object_pool" or
                    receiver.endswith(".object_pool")):
                kind = "pool-release"
            if kind is not None:
                self.identity.append(IdentitySite(
                    kind=kind,
                    line=node.lineno,
                    class_name=self.class_name,
                    function_name=self.function_name,
                    source=expression,
                    ast_sha256=_ast_sha256(node),
                ))
        self.generic_visit(node)

    def finish(self) -> tuple[
            tuple[MutationSite, ...], tuple[DerivedFieldSite, ...],
            tuple[DynamicWriteSite, ...], tuple[IdentitySite, ...]]:
        raw = sorted(
            self.raw_mutations,
            key=lambda item: (
                getattr(item[2], "lineno", 0),
                getattr(item[2], "col_offset", 0), item[0], item[1]),
        )
        result: list[MutationSite] = []
        seen_hash32: dict[int, str] = {}
        for ordinal, (field, kind, target, statement, receiver, extra) in enumerate(raw):
            statement_hash = _ast_sha256(statement)
            payload = {
                "statement": ast.dump(statement, include_attributes=False),
                "target": ast.dump(target, include_attributes=False),
                "field": field,
                "kind": kind,
                "line": getattr(target, "lineno", getattr(statement, "lineno", 0)),
                "column": getattr(target, "col_offset", 0),
                "extra": extra,
            }
            site_hash = _sha256_bytes(_json_bytes(payload))
            hash32 = int(site_hash[:8], 16)
            prior = seen_hash32.setdefault(hash32, site_hash)
            if prior != site_hash:
                raise DrawStateBackendError(
                    "PZDS002", "32-bit mutation-site hash collision")
            result.append(MutationSite(
                ordinal=ordinal,
                field_name=field,
                kind=kind,
                line=int(payload["line"]),
                column=int(payload["column"]),
                class_name=self.class_name if False else _enclosing_class(
                    statement),
                function_name=_enclosing_function(statement),
                receiver=receiver,
                source=(ast.get_source_segment(self.source, statement) or
                        ast.unparse(statement)),
                statement_ast_sha256=statement_hash,
                site_ast_sha256=site_hash,
                hash32=hash32,
                coverage=("atomic-bind-value-schema" if
                          kind == "class-field-initializer" else
                          "generated-setter-site-id"),
            ))
        # Context is attached below by source-range lookup; the placeholder
        # helpers are replaced in _attach_contexts before this method returns.
        return (tuple(result), tuple(sorted(
            self.derived, key=lambda item: (item.line, item.class_name))),
            tuple(sorted(self.dynamic, key=lambda item: item.line)),
            tuple(sorted(self.identity, key=lambda item: item.line)))


def _enclosing_class(_node: ast.AST) -> str | None:
    return None


def _enclosing_function(_node: ast.AST) -> str | None:
    return None


def _attach_contexts(
        tree: ast.Module, mutations: tuple[MutationSite, ...],
        ) -> tuple[MutationSite, ...]:
    ranges: list[tuple[int, int, str | None, str | None]] = []
    for class_node in (node for node in ast.walk(tree)
                       if isinstance(node, ast.ClassDef)):
        class_line = getattr(class_node, "lineno", 0)
        ranges.append((
            class_line, getattr(class_node, "end_lineno", class_line),
            class_node.name, None))
        for function in (node for node in ast.walk(class_node)
                         if isinstance(node, (ast.FunctionDef,
                                              ast.AsyncFunctionDef))):
            # Reject nested classes accidentally attributed to their parent.
            line = getattr(function, "lineno", 0)
            end = getattr(function, "end_lineno", line)
            ranges.append((line, end, class_node.name, function.name))
    for function in (node for node in tree.body
                     if isinstance(node, (ast.FunctionDef,
                                          ast.AsyncFunctionDef))):
        line = getattr(function, "lineno", 0)
        ranges.append((line, getattr(function, "end_lineno", line),
                       None, function.name))
    result: list[MutationSite] = []
    for item in mutations:
        candidates = [value for value in ranges
                      if value[0] <= item.line <= value[1]]
        if candidates:
            _start, _end, class_name, function_name = max(
                candidates, key=lambda value: value[0])
        else:
            class_name = function_name = None
        result.append(MutationSite(
            **{**item.__dict__, "class_name": class_name,
               "function_name": function_name}))
    return tuple(result)


def _class_graph(tree: ast.Module) -> tuple[
        dict[str, ast.ClassDef], dict[str, tuple[str, ...]]]:
    nodes: dict[str, ast.ClassDef] = {}
    bases: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        names: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                names.append(base.id)
            elif isinstance(base, ast.Attribute):
                names.append(base.attr)
            elif isinstance(base, ast.Subscript):
                root = base.value
                names.append(root.id if isinstance(root, ast.Name)
                             else ast.unparse(root))
            else:
                names.append(ast.unparse(base))
        nodes[node.name] = node
        bases[node.name] = tuple(names)
    return nodes, bases


def _enemy_descendants(
        tree: ast.Module, memberships: dict[str, tuple[str, ...]],
        class_tags: tuple[str, ...], class_bit_bytes: int,
        object_root_class: str,
        ) -> tuple[ConcreteClass, ...]:
    nodes, bases = _class_graph(tree)
    if object_root_class not in nodes:
        raise DrawStateBackendError(
            "PZDS003", f"active AST lacks object root {object_root_class!r}")
    memo: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def ancestors(name: str) -> frozenset[str]:
        known = memo.get(name)
        if known is not None:
            return known
        if name in visiting:
            raise DrawStateBackendError(
                "PZDS003", f"cycle in class graph at {name!r}")
        visiting.add(name)
        result = {name}
        for base in bases.get(name, ()):
            if base in nodes:
                result.update(ancestors(base))
        visiting.remove(name)
        memo[name] = frozenset(result)
        return memo[name]

    names = sorted(
        name for name in nodes if object_root_class in ancestors(name))
    if not names or len(names) >= NONE_SLOT:
        raise DrawStateBackendError(
            "PZDS004", f"concrete Enemy class count {len(names)} is not uint8")
    tag_index = {name: index for index, name in enumerate(class_tags)}
    result: list[ConcreteClass] = []
    for class_id, name in enumerate(names):
        tags = memberships.get(name)
        if tags is None:
            raise DrawStateBackendError(
                "PZDS005", f"class {name!r} missing from VM class graph")
        mask = [0] * class_bit_bytes
        for tag in tags:
            try:
                index = tag_index[tag]
            except KeyError as exc:
                raise DrawStateBackendError(
                    "PZDS005", f"unknown membership tag {tag!r}") from exc
            mask[index >> 3] |= 1 << (index & 7)
        result.append(ConcreteClass(
            name=name, class_id=class_id,
            membership_tags=tags, membership_mask=tuple(mask),
            class_ast_sha256=_ast_sha256(nodes[name]),
        ))
    return tuple(result)


def _object_root_class(
        tree: ast.Module, owner_class: str, iterable_attribute: str,
        ) -> str:
    """Derive ``Enemy`` from ``self.enemies: list[Enemy]`` in active AST."""
    owners = [node for node in tree.body
              if isinstance(node, ast.ClassDef) and node.name == owner_class]
    if len(owners) != 1:
        raise DrawStateBackendError(
            "PZDS015", f"draw owner {owner_class!r} is not one local class")
    candidates: list[str] = []
    for node in ast.walk(owners[0]):
        if not isinstance(node, ast.AnnAssign):
            continue
        target = node.target
        annotation = node.annotation
        if not (isinstance(target, ast.Attribute) and
                isinstance(target.value, ast.Name) and
                target.value.id == "self" and
                target.attr == iterable_attribute and
                isinstance(annotation, ast.Subscript)):
            continue
        container = annotation.value
        if not (isinstance(container, ast.Name) and container.id == "list"):
            raise DrawStateBackendError(
                "PZDS015", "object iterable annotation is not list[CLASS]")
        item = annotation.slice
        if not isinstance(item, ast.Name):
            raise DrawStateBackendError(
                "PZDS015", "object iterable element is not one local class")
        candidates.append(item.id)
    if len(candidates) != 1:
        raise DrawStateBackendError(
            "PZDS015", "expected one annotated object iterable, got "
            f"{len(candidates)}")
    return candidates[0]


def _context_at(
        tree: ast.Module, line: int,
        ) -> tuple[str | None, str | None]:
    class_name: str | None = None
    function_name: str | None = None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
            continue
        class_name = node.name
        for child in node.body:
            if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                    child.lineno <= line <= getattr(
                        child, "end_lineno", child.lineno)):
                function_name = child.name
                break
        break
    return class_name, function_name


def _identity_assignment_sites(
        source: str, tree: ast.Module, current: tuple[IdentitySite, ...],
        ) -> tuple[IdentitySite, ...]:
    result = list(current)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Attribute) and
                   target.attr == "object_slot" for target in targets):
            continue
        value = node.value
        class_name, function_name = _context_at(tree, node.lineno)
        if isinstance(value, ast.Attribute) and value.attr == "object_slot":
            kind = "same-slot-object-replacement"
        elif isinstance(value, ast.Constant) and value.value is None:
            kind = ("same-slot-old-owner-detach" if
                    class_name == "M72EnemyWorld" and
                    function_name == "update" else
                    "pool-release-assignment")
        elif (class_name == "M72ObjectPool" and
              function_name == "bind"):
            kind = "pool-bind-assignment"
        else:
            kind = "checkpoint-bind-assignment"
        result.append(IdentitySite(
            kind=kind,
            line=node.lineno,
            class_name=class_name,
            function_name=function_name,
            source=ast.get_source_segment(source, node) or ast.unparse(node),
            ast_sha256=_ast_sha256(node),
        ))
    return tuple(sorted(result, key=lambda item: (item.line, item.kind)))


def build_draw_state_model(
        project_root: Path | str, *, plan: SpriteDrawPlanIR | None = None,
        ) -> DrawStateModel:
    """Build and cross-bind the sidecar model from active source artifacts."""
    root = Path(project_root).resolve()
    source_path = root / "Source" / "Python" / "rtype_port" / "enemies.py"
    source_bytes = source_path.read_bytes()
    source = source_bytes.decode("utf-8")
    launcher_bytes = (root / "run_python.cmd").read_bytes()
    active_plan = compile_active_enemy_draw_plan(root)
    actual_plan = plan or active_plan
    for label in (
            "format", "source_path", "source_sha256", "method_ast_sha256",
            "sink_order_sha256", "semantic_sha256"):
        if getattr(actual_plan, label) != getattr(active_plan, label):
            raise DrawStateBackendError(
                "PZDS006", f"provided draw plan differs from active plan: {label}")
    if actual_plan.source_sha256 != _sha256_bytes(source_bytes):
        raise DrawStateBackendError(
            "PZDS006", "SpriteDrawPlanIR source hash is not the active source")
    try:
        tree = ast.parse(source, filename=actual_plan.source_path)
    except SyntaxError as exc:
        raise DrawStateBackendError(
            "PZDS007", f"cannot parse active source: {exc.msg}") from exc

    vm_program = build_draw_vm_program(actual_plan, source_text=source)
    vm_artifacts = emit_draw_vm_backend(actual_plan, source_text=source)
    order_model = build_render_order_model(root)
    order_artifacts = emit_render_order_backend(root)
    if order_model.source_sha256 != actual_plan.source_sha256:
        raise DrawStateBackendError(
            "PZDS008", "render-order and draw-plan source hashes differ")
    if (order_model.slot_count <= order_model.reserved_sentinel_count or
            order_model.slot_count > NONE_SLOT):
        raise DrawStateBackendError(
            "PZDS009", f"source-derived pool size {order_model.slot_count} "
            "does not fit compact slot indices")
    model = vm_program.model
    if model.class_bit_bytes + sum(
            _storage_bytes(item.c_type) for item in model.fields
            ) != VM_OBJECT_VIEW_BYTES:
        raise DrawStateBackendError(
            "PZDS010", "VM object view is no longer the proved 28-byte ABI")
    if len(model.fields) > 16:
        raise DrawStateBackendError(
            "PZDS011", "field patch mask no longer fits uint16")

    inventory = _MutationInventory(source, (item.name for item in model.fields))
    inventory.visit(tree)
    mutations, derived, dynamic, identities = inventory.finish()
    mutations = _attach_contexts(tree, mutations)
    if len(mutations) > 0xFFFF:
        raise DrawStateBackendError(
            "PZDS011", "mutation-site table no longer fits uint16 ids")
    identities = _identity_assignment_sites(source, tree, identities)
    memberships = dict(model.class_memberships)
    object_loops = [item for item in model.loops if item.kind == "objects"]
    if len(object_loops) != 1:
        raise DrawStateBackendError(
            "PZDS015", "normalized VM model lacks one object loop")
    object_root = _object_root_class(
        tree, actual_plan.class_name, object_loops[0].iterable_attribute)
    concrete = _enemy_descendants(
        tree, memberships, model.class_tags, model.class_bit_bytes,
        object_root)
    field_bytes = sum(_storage_bytes(item.c_type) for item in model.fields)
    value_bytes = field_bytes
    # Values are 24 bytes in the current ABI.  Class id plus one explicit
    # reserved byte make each persistent slot exactly 26 bytes on SDCC.
    if field_bytes & 1:
        raise DrawStateBackendError(
            "PZDS012", "odd field payload has no pinned slot-state packing")
    slot_state_bytes = value_bytes + 2
    state_bytes = slot_state_bytes * order_model.slot_count

    semantic_payload = {
        "format": DRAW_STATE_BACKEND_FORMAT,
        "plan": actual_plan.semantic_sha256,
        "vm": _sha256_text(vm_artifacts.manifest),
        "order": order_model.semantic_sha256,
        "slot_count": order_model.slot_count,
        "reserved_sentinels": order_model.reserved_sentinel_count,
        "fields": [item.as_dict() for item in model.fields],
        "classes": [item.as_dict() for item in concrete],
        "object_root_class": object_root,
        "mutation_sites": [item.as_dict() for item in mutations],
        "derived_field_sites": [item.as_dict() for item in derived],
        "dynamic_write_sites": [item.as_dict() for item in dynamic],
        "identity_sites": [item.as_dict() for item in identities],
        "state_bytes": state_bytes,
    }
    return DrawStateModel(
        plan=actual_plan,
        source_sha256=_sha256_bytes(source_bytes),
        launcher_sha256=_sha256_bytes(launcher_bytes),
        draw_vm_semantic_sha256=actual_plan.semantic_sha256,
        draw_vm_header_sha256=_sha256_text(vm_artifacts.header),
        draw_vm_source_sha256=_sha256_text(vm_artifacts.source),
        draw_vm_manifest_sha256=_sha256_text(vm_artifacts.manifest),
        render_order_semantic_sha256=order_model.semantic_sha256,
        render_order_header_sha256=_sha256_text(order_artifacts.header),
        render_order_source_sha256=_sha256_text(order_artifacts.source),
        render_order_manifest_sha256=_sha256_text(order_artifacts.manifest),
        slot_count=order_model.slot_count,
        reserved_sentinels=order_model.reserved_sentinel_count,
        object_root_class=object_root,
        class_bit_bytes=model.class_bit_bytes,
        fields=tuple(model.fields),
        concrete_classes=concrete,
        mutation_sites=mutations,
        derived_field_sites=derived,
        dynamic_write_sites=dynamic,
        identity_sites=identities,
        field_storage_bytes=field_bytes,
        value_bytes=value_bytes,
        slot_state_bytes=slot_state_bytes,
        state_bytes=state_bytes,
        semantic_sha256=_sha256_bytes(_json_bytes(semantic_payload)),
    )


def _macro(prefix: str) -> str:
    return prefix.upper()


def _field_bounds(field: object) -> tuple[int, int]:
    c_type = field.c_type
    if field.kind == "boolean":
        return 0, 1
    if field.kind == "string_state":
        return 0, len(field.string_values)
    if c_type == "uint16_t":
        return 0, 65535
    if c_type == "int16_t":
        return -32768, 32767
    raise DrawStateBackendError(
        "PZDS013", f"field {field.name!r} lacks scalar bounds")


def _header(
        model: DrawStateModel, prefix: str, header_name: str,
        vm_prefix: str, order_prefix: str,
        ) -> str:
    macro = _macro(prefix)
    guard = _identifier(header_name.replace(".", "_"), upper=True)
    lines = [
        "/* Generated from active Python AST/DrawPlanIR. Do not edit. */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        f'#include "{vm_prefix}.h"',
        f'#include "{order_prefix}.h"',
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        f"#define {macro}_SLOT_COUNT {model.slot_count}u",
        f"#define {macro}_RESERVED_SENTINELS {model.reserved_sentinels}u",
        f"#define {macro}_CLASS_COUNT {len(model.concrete_classes)}u",
        f"#define {macro}_CLASS_NONE 0xFFu",
        f"#define {macro}_FIELD_COUNT {len(model.fields)}u",
        f"#define {macro}_MUTATION_SITE_COUNT {len(model.mutation_sites)}u",
        f"#define {macro}_VALUE_BYTES {model.value_bytes}u",
        f"#define {macro}_SLOT_STATE_BYTES {model.slot_state_bytes}u",
        f"#define {macro}_STATE_BYTES {model.state_bytes}u",
        "",
    ]
    for item in model.concrete_classes:
        lines.append(
            f"#define {macro}_CLASS_{_identifier(item.name, upper=True)} "
            f"{item.class_id}u")
    lines.extend(["", "typedef enum {"])
    for index, field in enumerate(model.fields):
        lines.append(
            f"    {macro}_FIELD_{_identifier(field.name, upper=True)} = "
            f"{index},")
    lines.extend([
        f"}} {prefix}_field_id;",
        "",
        "typedef enum {",
        f"    {macro}_OK = 0,",
        f"    {macro}_NULL = 1,",
        f"    {macro}_INVALID_SLOT = 2,",
        f"    {macro}_UNBOUND_SLOT = 3,",
        f"    {macro}_INVALID_CLASS = 4,",
        f"    {macro}_INVALID_FIELD = 5,",
        f"    {macro}_VALUE_RANGE = 6,",
        f"    {macro}_INVALID_SITE = 7,",
        f"    {macro}_INVALID_PATCH_MASK = 8,",
        f"    {macro}_ALREADY_BOUND = 9",
        f"}} {prefix}_status;",
        "",
        f"typedef struct {prefix}_values {{",
    ])
    # Keep the portable values structure byte-exact without relying on a
    # compiler-specific packed attribute: all 16-bit fields precede bytes.
    value_layout = tuple(
        item for item in model.fields if item.c_type != "uint8_t") + tuple(
        item for item in model.fields if item.c_type == "uint8_t")
    for field in value_layout:
        lines.append(
            f"    {field.c_type} field_{_identifier(field.name)};")
    lines.extend([
        f"}} {prefix}_values;",
        "",
        f"typedef struct {prefix}_slot_state {{",
        f"    {prefix}_values values;",
        "    uint8_t concrete_class;",
        "    uint8_t reserved_zero;",
        f"}} {prefix}_slot_state;",
        "",
        f"typedef struct {prefix}_state {{",
        f"    {prefix}_slot_state slots[{macro}_SLOT_COUNT];",
        f"}} {prefix}_state;",
        "",
        f"typedef struct {prefix}_provider_context {{",
        f"    const {prefix}_state *state;",
        f"    const {order_prefix}_state *order;",
        f"}} {prefix}_provider_context;",
        "",
        f"void {prefix}_reset({prefix}_state *state);",
        f"{prefix}_status {prefix}_clear({prefix}_state *state, uint8_t slot);",
        f"{prefix}_status {prefix}_bind(",
        f"    {prefix}_state *state, uint8_t slot, uint8_t concrete_class,",
        f"    const {prefix}_values *values);",
        f"{prefix}_status {prefix}_replace_same_slot(",
        f"    {prefix}_state *state, uint8_t slot, uint8_t concrete_class,",
        f"    const {prefix}_values *values);",
        f"{prefix}_status {prefix}_patch(",
        f"    {prefix}_state *state, uint8_t slot, uint16_t field_mask,",
        f"    const {prefix}_values *values);",
        f"{prefix}_status {prefix}_set_field(",
        f"    {prefix}_state *state, uint8_t slot, uint8_t field_id,",
        "    int32_t value);",
        f"{prefix}_status {prefix}_set_at_site(",
        f"    {prefix}_state *state, uint8_t slot, uint16_t site_id,",
        "    int32_t value);",
        f"uint32_t {prefix}_mutation_site_hash32(uint16_t site_id);",
        f"uint8_t {prefix}_class_of(",
        f"    const {prefix}_state *state, uint8_t slot);",
        "",
        "/* Compact Draw VM provider: object_index is Python render order. */",
        f"uint8_t {prefix}_load_object(",
        "    void *context, uint16_t object_index,",
        f"    {vm_prefix}_object_view *object_out);",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        f"#endif /* {guard} */",
        "",
    ])
    return "\n".join(lines)


def _source(
        model: DrawStateModel, prefix: str, header_name: str,
        vm_prefix: str, order_prefix: str,
        ) -> str:
    macro = _macro(prefix)
    class_rows = ",\n".join(
        "    { " + ", ".join(f"0x{value:02X}u" for value in item.membership_mask) + " }"
        for item in model.concrete_classes)
    site_fields = ", ".join(
        f"{index}u" for item in model.mutation_sites
        for index, field in enumerate(model.fields)
        if field.name == item.field_name)
    site_hashes = ",\n    ".join(
        f"0x{item.hash32:08X}UL" for item in model.mutation_sites)
    allowed_mask = (1 << len(model.fields)) - 1
    lines = [
        "/* Generated from active Python AST/DrawPlanIR. Do not edit. */",
        f'#include "{header_name}"',
        "",
        f"static const uint8_t {prefix}_class_masks[",
        f"        {macro}_CLASS_COUNT][{vm_prefix.upper()}_CLASS_BIT_BYTES] = {{",
        class_rows,
        "};",
        "",
        f"static const uint8_t {prefix}_site_fields[",
        f"        {macro}_MUTATION_SITE_COUNT] = {{ {site_fields} }};",
        f"static const uint32_t {prefix}_site_hashes[",
        f"        {macro}_MUTATION_SITE_COUNT] = {{",
        f"    {site_hashes}",
        "};",
        "",
        f"static uint8_t {prefix}_valid_slot(uint8_t slot)",
        "{",
        f"    return (uint8_t)(slot >= {macro}_RESERVED_SENTINELS &&",
        f"                     slot < {macro}_SLOT_COUNT);",
        "}",
        "",
        f"static uint8_t {prefix}_valid_values(",
        f"        const {prefix}_values *values, uint16_t mask)",
        "{",
        "    if (values == 0) return 0u;",
    ]
    for index, field in enumerate(model.fields):
        low, high = _field_bounds(field)
        if low == 0 and high == 65535 or low == -32768 and high == 32767:
            continue
        member = f"values->field_{_identifier(field.name)}"
        lines.extend([
            f"    if ((mask & 0x{1 << index:04X}u) != 0u &&",
            f"            ((int32_t){member} < {low}L ||",
            f"             (int32_t){member} > {high}L)) return 0u;",
        ])
    lines.extend([
        "    return 1u;",
        "}",
        "",
        f"static void {prefix}_zero_slot({prefix}_slot_state *slot_state)",
        "{",
    ])
    for field in model.fields:
        lines.append(
            f"    slot_state->values.field_{_identifier(field.name)} = 0;")
    lines.extend([
        f"    slot_state->concrete_class = {macro}_CLASS_NONE;",
        "    slot_state->reserved_zero = 0u;",
        "}",
        "",
        f"void {prefix}_reset({prefix}_state *state)",
        "{",
        "    uint8_t slot;",
        "    if (state == 0) return;",
        f"    for (slot = 0u; slot < {macro}_SLOT_COUNT; ++slot)",
        f"        {prefix}_zero_slot(&state->slots[slot]);",
        "}",
        "",
        f"{prefix}_status {prefix}_clear({prefix}_state *state, uint8_t slot)",
        "{",
        f"    if (state == 0) return {macro}_NULL;",
        f"    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;",
        f"    if (state->slots[slot].concrete_class == {macro}_CLASS_NONE)",
        f"        return {macro}_UNBOUND_SLOT;",
        f"    {prefix}_zero_slot(&state->slots[slot]);",
        "    return " + macro + "_OK;",
        "}",
        "",
        f"static {prefix}_status {prefix}_write(",
        f"        {prefix}_state *state, uint8_t slot, uint8_t concrete_class,",
        f"        const {prefix}_values *values, uint8_t require_bound)",
        "{",
        f"    if (state == 0 || values == 0) return {macro}_NULL;",
        f"    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;",
        f"    if (concrete_class >= {macro}_CLASS_COUNT)",
        f"        return {macro}_INVALID_CLASS;",
        "    if (require_bound != 0u &&",
        f"            state->slots[slot].concrete_class == {macro}_CLASS_NONE)",
        f"        return {macro}_UNBOUND_SLOT;",
        "    if (require_bound == 0u &&",
        f"            state->slots[slot].concrete_class != {macro}_CLASS_NONE)",
        f"        return {macro}_ALREADY_BOUND;",
        f"    if (!{prefix}_valid_values(values, 0x{allowed_mask:04X}u))",
        f"        return {macro}_VALUE_RANGE;",
        "    state->slots[slot].values = *values;",
        "    state->slots[slot].reserved_zero = 0u;",
        "    state->slots[slot].concrete_class = concrete_class;",
        f"    return {macro}_OK;",
        "}",
        "",
        f"{prefix}_status {prefix}_bind(",
        f"        {prefix}_state *state, uint8_t slot, uint8_t concrete_class,",
        f"        const {prefix}_values *values)",
        "{",
        f"    return {prefix}_write(state, slot, concrete_class, values, 0u);",
        "}",
        "",
        f"{prefix}_status {prefix}_replace_same_slot(",
        f"        {prefix}_state *state, uint8_t slot, uint8_t concrete_class,",
        f"        const {prefix}_values *values)",
        "{",
        f"    return {prefix}_write(state, slot, concrete_class, values, 1u);",
        "}",
        "",
        f"{prefix}_status {prefix}_patch(",
        f"        {prefix}_state *state, uint8_t slot, uint16_t field_mask,",
        f"        const {prefix}_values *values)",
        "{",
        f"    if (state == 0 || values == 0) return {macro}_NULL;",
        f"    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;",
        f"    if (state->slots[slot].concrete_class == {macro}_CLASS_NONE)",
        f"        return {macro}_UNBOUND_SLOT;",
        f"    if ((field_mask & (uint16_t)~0x{allowed_mask:04X}u) != 0u)",
        f"        return {macro}_INVALID_PATCH_MASK;",
        f"    if (!{prefix}_valid_values(values, field_mask))",
        f"        return {macro}_VALUE_RANGE;",
    ])
    for index, field in enumerate(model.fields):
        member = f"field_{_identifier(field.name)}"
        lines.append(
            f"    if ((field_mask & 0x{1 << index:04X}u) != 0u) "
            f"state->slots[slot].values.{member} = values->{member};")
    lines.extend([
        f"    return {macro}_OK;",
        "}",
        "",
        f"{prefix}_status {prefix}_set_field(",
        f"        {prefix}_state *state, uint8_t slot, uint8_t field_id,",
        "        int32_t value)",
        "{",
        f"    if (state == 0) return {macro}_NULL;",
        f"    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;",
        f"    if (state->slots[slot].concrete_class == {macro}_CLASS_NONE)",
        f"        return {macro}_UNBOUND_SLOT;",
        "    switch (field_id) {",
    ])
    for index, field in enumerate(model.fields):
        low, high = _field_bounds(field)
        member = f"field_{_identifier(field.name)}"
        cast = field.c_type
        lines.extend([
            f"    case {index}u:",
            f"        if (value < {low}L || value > {high}L)",
            f"            return {macro}_VALUE_RANGE;",
            f"        state->slots[slot].values.{member} = ({cast})value;",
            f"        return {macro}_OK;",
        ])
    lines.extend([
        f"    default: return {macro}_INVALID_FIELD;",
        "    }",
        "}",
        "",
        f"{prefix}_status {prefix}_set_at_site(",
        f"        {prefix}_state *state, uint8_t slot, uint16_t site_id,",
        "        int32_t value)",
        "{",
        f"    if (site_id >= {macro}_MUTATION_SITE_COUNT)",
        f"        return {macro}_INVALID_SITE;",
        f"    return {prefix}_set_field(",
        f"        state, slot, {prefix}_site_fields[site_id], value);",
        "}",
        "",
        f"uint32_t {prefix}_mutation_site_hash32(uint16_t site_id)",
        "{",
        f"    if (site_id >= {macro}_MUTATION_SITE_COUNT) return 0UL;",
        f"    return {prefix}_site_hashes[site_id];",
        "}",
        "",
        f"uint8_t {prefix}_class_of(",
        f"        const {prefix}_state *state, uint8_t slot)",
        "{",
        f"    if (state == 0 || !{prefix}_valid_slot(slot))",
        f"        return {macro}_CLASS_NONE;",
        "    return state->slots[slot].concrete_class;",
        "}",
        "",
        f"uint8_t {prefix}_load_object(",
        "        void *context, uint16_t object_index,",
        f"        {vm_prefix}_object_view *object_out)",
        "{",
        f"    const {prefix}_provider_context *provider =",
        f"        (const {prefix}_provider_context *)context;",
        f"    const {prefix}_slot_state *slot_state;",
        "    uint8_t slot;",
        "    uint8_t index;",
        "    if (provider == 0 || provider->state == 0 ||",
        "            provider->order == 0 || object_out == 0 ||",
        "            object_index > 0xFFu) return 0u;",
        f"    slot = {order_prefix}_slot_at(",
        "        provider->order, (uint8_t)object_index);",
        f"    if (!{prefix}_valid_slot(slot)) return 0u;",
        "    slot_state = &provider->state->slots[slot];",
        f"    if (slot_state->concrete_class >= {macro}_CLASS_COUNT) return 0u;",
        f"    for (index = 0u; index < {vm_prefix.upper()}_CLASS_BIT_BYTES;",
        "            ++index)",
        f"        object_out->class_bits[index] = {prefix}_class_masks[",
        "            slot_state->concrete_class][index];",
    ])
    for field in model.fields:
        member = f"field_{_identifier(field.name)}"
        lines.append(
            f"    object_out->{member} = slot_state->values.{member};")
    lines.extend([
        "    return 1u;",
        "}",
        "",
    ])
    return "\n".join(lines)


def _manifest(
        model: DrawStateModel, prefix: str, header_name: str,
        source_name: str, header: str, source: str,
        ) -> str:
    field_counts = Counter(item.field_name for item in model.mutation_sites)
    kind_counts = Counter(item.kind for item in model.mutation_sites)
    value: dict[str, object] = {
        "format": DRAW_STATE_BACKEND_FORMAT,
        "status": "TARGET_NEUTRAL_PERSISTENT_SIDECAR_LIVE_BLOCKED",
        "live": False,
        "semantic_sha256": model.semantic_sha256,
        "active_source": {
            "launcher": "run_python.cmd",
            "launcher_sha256": model.launcher_sha256,
            "entrypoint": "rtype_port.app",
            "module": model.plan.source_path,
            "module_sha256": model.source_sha256,
            "draw_method_ast_sha256": model.plan.method_ast_sha256,
        },
        "pinned_inputs": {
            "draw_plan_semantic_sha256": model.plan.semantic_sha256,
            "draw_vm": {
                "semantic_sha256": model.draw_vm_semantic_sha256,
                "header_sha256": model.draw_vm_header_sha256,
                "source_sha256": model.draw_vm_source_sha256,
                "manifest_sha256": model.draw_vm_manifest_sha256,
            },
            "render_order": {
                "semantic_sha256": model.render_order_semantic_sha256,
                "header_sha256": model.render_order_header_sha256,
                "source_sha256": model.render_order_source_sha256,
                "manifest_sha256": model.render_order_manifest_sha256,
            },
        },
        "persistent_state": {
            "slot_count": model.slot_count,
            "reserved_sentinels": model.reserved_sentinels,
            "field_values_bytes_per_slot": model.value_bytes,
            "concrete_class_id_bytes_per_slot": 1,
            "explicit_reserved_bytes_per_slot": 1,
            "slot_state_bytes": model.slot_state_bytes,
            "state_bytes": model.state_bytes,
            "frame_materialization": False,
            "representation": (
                "source-derived concrete class id plus exact normalized "
                "draw fields; class bitset expanded into one VM view on load"),
        },
        "normalized_fields": [
            {**item.as_dict(), "field_id": index,
             "scalar_range": list(_field_bounds(item))}
            for index, item in enumerate(model.fields)
        ],
        "concrete_classes": {
            "object_root_class": model.object_root_class,
            "object_root_derivation": (
                "active draw-owner iterable annotation list[CLASS]"),
            "derivation": (
                "active object-root subclass graph intersected with VM "
                "isinstance tags"),
            "count": len(model.concrete_classes),
            "class_bit_bytes": model.class_bit_bytes,
            "items": [item.as_dict() for item in model.concrete_classes],
            "manual_type_switch": False,
        },
        "mutation_inventory": {
            "direct_and_implicit_count": len(model.mutation_sites),
            "field_counts": dict(sorted(field_counts.items())),
            "kind_counts": dict(sorted(kind_counts.items())),
            "sites": [item.as_dict() for item in model.mutation_sites],
            "derived_field_count": len(model.derived_field_sites),
            "derived_fields": [item.as_dict() for item in model.derived_field_sites],
            "dynamic_write_blocker_count": len(model.dynamic_write_sites),
            "dynamic_write_blockers": [item.as_dict() for item in model.dynamic_write_sites],
            "setter_site_table": {
                "id_type": "uint16_t",
                "field_id_table_generated": True,
                "ast_hash32_table_generated": True,
                "full_ast_sha256_in_manifest": True,
                "rejected_site_is_atomic": True,
            },
            "coverage": {
                "syntactic_direct_writes_have_setter_ids": True,
                "implicit_class_field_initializers_fit_bind_values": True,
                "runtime_hooks_present": False,
                "reachable_write_sync_certified": False,
            },
        },
        "concrete_identity_inventory": {
            "count": len(model.identity_sites),
            "sites": [item.as_dict() for item in model.identity_sites],
            "runtime_hooks_present": False,
        },
        "provider_abi": {
            "function": f"{prefix}_load_object",
            "object_index_semantics": "Python render-order position",
            "physical_slot_source": f"{DEFAULT_ORDER_PREFIX}_slot_at",
            "output": f"one {DEFAULT_VM_PREFIX}_object_view",
            "output_bytes": VM_OBJECT_VIEW_BYTES,
            "full_pool_copy_per_frame": False,
            "failure_leaves_object_out_unchanged": True,
            "unbound_or_invalid_slot_fails": True,
        },
        "failure_atomicity": {
            "init_reset": (
                "null is a no-op; every value byte is zeroed and every "
                "slot becomes unbound"),
            "clear": (
                "bounds and bound state checked before deterministic zero"),
            "bind": (
                "slot/class/unbound state/all value ranges checked before "
                "mutation"),
            "replace_same_slot": (
                "requires an already-bound physical slot and does not alter "
                "render-order position"),
            "patch": "mask and every selected value checked before mutation",
            "set_field_and_site": "all ids/ranges checked before mutation",
            "meaning": "rejected operations leave persistent state unchanged",
        },
        "verification_contract": {
            "host_randomized_differential": {
                "required": True,
                "path": (
                    "persistent slots + randomized render order -> provider "
                    "views -> compact VM records"),
                "oracle": "direct SpriteDrawPlanIR Python interpreter",
            },
            "pinned_sdcc_size_status": (
                "Build/rtype_python_draw_state_size_status.json"),
            "live_blockers": [
                "all generated mutation-site ids still lack target lowering/hooks",
                "derived active_palette property dependencies are not lowered",
                "dynamic setattr sites are not proved disjoint or hooked",
                "pool bind/release/same-slot replacement sites are not hooked",
                "linked VM+order+sidecar placement, stack bytes and tstates are unproved",
            ],
        },
        "artifacts": {
            "header": {"name": header_name, "sha256": _sha256_text(header),
                       "utf8_bytes": len(header.encode("utf-8"))},
            "source": {"name": source_name, "sha256": _sha256_text(source),
                       "utf8_bytes": len(source.encode("utf-8"))},
        },
        "prefix": prefix,
    }
    return _json_text(value)


def emit_draw_state_backend(
        project_root: Path | str, *, prefix: str = DEFAULT_PREFIX,
        stem: str | None = None, plan: SpriteDrawPlanIR | None = None,
        vm_prefix: str = DEFAULT_VM_PREFIX,
        order_prefix: str = DEFAULT_ORDER_PREFIX,
        ) -> DrawStateArtifacts:
    for label, value in (("prefix", prefix), ("vm prefix", vm_prefix),
                         ("order prefix", order_prefix)):
        if _identifier(value) != value:
            raise DrawStateBackendError(
                "PZDS014", f"{label} is not normalized: {value!r}")
    artifact_stem = stem or prefix
    if _identifier(artifact_stem) != artifact_stem:
        raise DrawStateBackendError(
            "PZDS014", f"artifact stem is not normalized: {artifact_stem!r}")
    model = build_draw_state_model(project_root, plan=plan)
    header_name = artifact_stem + ".h"
    source_name = artifact_stem + ".c"
    manifest_name = artifact_stem + ".json"
    header = _header(model, prefix, header_name, vm_prefix, order_prefix)
    source = _source(model, prefix, header_name, vm_prefix, order_prefix)
    manifest = _manifest(
        model, prefix, header_name, source_name, header, source)
    return DrawStateArtifacts(
        header_name=header_name, source_name=source_name,
        manifest_name=manifest_name, header=header, source=source,
        manifest=manifest)


def write_draw_state_backend(
        project_root: Path | str, output_dir: Path | str, **kwargs: object,
        ) -> DrawStateArtifacts:
    artifacts = emit_draw_state_backend(project_root, **kwargs)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (
            (artifacts.header_name, artifacts.header),
            (artifacts.source_name, artifacts.source),
            (artifacts.manifest_name, artifacts.manifest)):
        (destination / name).write_text(value, encoding="utf-8", newline="\n")
    return artifacts
