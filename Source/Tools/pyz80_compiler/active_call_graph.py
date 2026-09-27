"""Closed-source-world call/CFG inventory for the active Python launcher.

The analysis starts at the literal ``-m`` target in ``run_python.cmd``.  It
parses source without importing or executing it, computes the module import
closure, lowers every function in that closure through :mod:`function_cfg`,
and distinguishes proven direct calls from unresolved Python dispatch.  A
module being imported is deliberately *not* evidence that every function in
that module is callable from ``app.main``.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .function_cfg import (
    FUNCTION_CFG_IR_FORMAT,
    FunctionCFGError,
    lower_python_function_cfg,
)
from .frontend import lower_active_object_store_ir
from .mutation_hook_ir import MutationHookPlan, build_mutation_hook_ir


ACTIVE_CALL_GRAPH_FORMAT = "pyz80.active-call-graph-cfg-inventory.v1"
ACTIVE_CALL_GRAPH_STATUS = "ACTIVE_CALL_GRAPH_INVENTORIED_LIVE_BLOCKED"

__all__ = [
    "ACTIVE_CALL_GRAPH_FORMAT",
    "ACTIVE_CALL_GRAPH_STATUS",
    "ActiveCallGraphError",
    "analyze_active_call_graph",
    "validate_active_call_graph_report",
    "write_active_call_graph_report",
]


class ActiveCallGraphError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))


def _ast_sha256(node: ast.AST) -> str:
    return _sha256(ast.dump(
        node, include_attributes=False).encode("utf-8"))


def _source(text: str, node: ast.AST) -> str:
    return ast.get_source_segment(text, node) or ast.unparse(node)


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/")


@dataclass
class _Module:
    name: str
    path: Path
    relative_path: str
    source: str
    source_sha256: str
    tree: ast.Module
    is_package: bool
    import_edges: list[dict[str, Any]] = field(default_factory=list)
    bindings: dict[str, "_Binding"] = field(default_factory=dict)
    top_functions: dict[str, str] = field(default_factory=dict)
    top_classes: dict[str, str] = field(default_factory=dict)
    value_provenance: dict[str, set[str]] = field(default_factory=dict)
    value_provenance_unknown: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _Binding:
    kind: str
    target: str


@dataclass
class _Callable:
    callable_id: str
    module: str
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    class_id: str | None
    lexical_parent_id: str | None
    fragments: dict[ast.AST, Any] = field(default_factory=dict)


@dataclass
class _Class:
    class_id: str
    module: str
    qualname: str
    node: ast.ClassDef
    methods: dict[str, str] = field(default_factory=dict)
    base_class_ids: tuple[str, ...] = ()
    external_bases: tuple[str, ...] = ()
    builtin_bases: tuple[str, ...] = ()
    has_custom_metaclass: bool = False


@dataclass
class _Facts:
    local_bound: set[str]
    global_names: set[str]
    rebound_names: set[str]
    nested_callables: dict[str, str]
    exact_local_classes: dict[str, set[str]]
    local_class_unknown: set[str]
    exact_local_provenance: dict[str, set[str]]
    local_provenance_unknown: set[str]
    local_import_bindings: dict[str, _Binding]
    exact_parameter_classes: set[str]
    parameter_class_candidates: set[str]
    parameter_callable_candidates: dict[str, set[str]]
    local_callable_unknown_reasons: dict[str, set[str]]


_BUILTIN_NAMES = frozenset(
    name for name, value in vars(builtins).items() if callable(value))

_BUILTIN_CONTAINER_BASES = frozenset({"dict", "list", "set"})

_FILESYSTEM_METHODS = frozenset({
    "exists", "glob", "is_dir", "is_file", "iterdir", "mkdir", "open",
    "read_bytes", "read_text", "resolve", "rglob", "stat", "unlink",
    "write_bytes", "write_text",
})

_PYGAME_METHODS = frozenset({
    "blit", "blits", "convert", "convert_alpha", "copy", "fill",
    "get_at", "get_bitsize", "get_height", "get_rect", "get_size",
    "get_width", "lock", "map_rgb", "set_alpha", "set_at", "set_colorkey",
    "subsurface", "unlock", "unmap_rgb",
})


def _module_path(source_root: Path, module: str) -> tuple[Path, bool] | None:
    stem = source_root.joinpath(*module.split("."))
    file_path = stem.with_suffix(".py")
    if file_path.is_file():
        return file_path, False
    package_path = stem / "__init__.py"
    if package_path.is_file():
        return package_path, True
    return None


def _module_package(module: _Module) -> list[str]:
    parts = module.name.split(".")
    return parts if module.is_package else parts[:-1]


def _resolve_from_module(module: _Module, node: ast.ImportFrom) -> str:
    if node.level:
        package = _module_package(module)
        remove = node.level - 1
        if remove > len(package):
            return ""
        base = package[:len(package) - remove]
        if node.module:
            base.extend(node.module.split("."))
        return ".".join(base)
    return node.module or ""


def _module_level_imports(tree: ast.Module) -> Iterable[ast.Import | ast.ImportFrom]:
    """Yield imports executed while loading a module, not callable locals."""

    def walk_statement(node: ast.stmt) -> Iterable[ast.Import | ast.ImportFrom]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            return
        bodies: list[list[ast.stmt]] = []
        for field_name in ("body", "orelse", "finalbody"):
            value = getattr(node, field_name, None)
            if isinstance(value, list):
                bodies.append(value)
        for handler in getattr(node, "handlers", ()):  # try/except
            bodies.append(handler.body)
        for body in bodies:
            for statement in body:
                yield from walk_statement(statement)

    for statement in tree.body:
        yield from walk_statement(statement)


def _load_module(source_root: Path, project_root: Path,
                 name: str) -> _Module | None:
    resolved = _module_path(source_root, name)
    if resolved is None:
        return None
    path, is_package = resolved
    data = path.read_bytes()
    source = data.decode("utf-8")
    return _Module(
        name=name,
        path=path,
        relative_path=_norm(path.relative_to(project_root)),
        source=source,
        source_sha256=_sha256(data),
        tree=ast.parse(source, filename=str(path), type_comments=True),
        is_package=is_package,
    )


def _launcher_entry(project_root: Path) -> tuple[dict[str, Any], str]:
    launcher = project_root / "run_python.cmd"
    if not launcher.is_file():
        raise ActiveCallGraphError("PZACG001", "run_python.cmd is absent")
    data = launcher.read_bytes()
    text = data.decode("utf-8-sig")
    modules = re.findall(r"(?:^|\s)-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
                         text, flags=re.MULTILINE)
    if modules != ["rtype_port.app"]:
        raise ActiveCallGraphError(
            "PZACG002", f"launcher -m target is not unique active app: {modules}")
    return ({
        "path": _norm(launcher.relative_to(project_root)),
        "sha256": _sha256(data),
        "module": modules[0],
        "literal_module_invocation_count": len(modules),
    }, modules[0])


def _build_module_graph(project_root: Path, entry_module: str) -> dict[str, _Module]:
    source_root = project_root / "Source" / "Python"
    modules: dict[str, _Module] = {}
    pending = deque([entry_module])
    while pending:
        name = pending.popleft()
        if name in modules:
            continue
        module = _load_module(source_root, project_root, name)
        if module is None:
            raise ActiveCallGraphError(
                "PZACG003", f"active internal module {name!r} has no source")
        modules[name] = module

        # Importing a submodule always loads every source package initializer.
        parts = name.split(".")
        for length in range(1, len(parts)):
            package_name = ".".join(parts[:length])
            package = _module_path(source_root, package_name)
            if package is not None and package[1] and package_name not in modules:
                pending.append(package_name)

        for node in _module_level_imports(module.tree):
            if isinstance(node, ast.Import):
                targets = [(alias.name, alias.asname or alias.name.split(".")[0])
                           for alias in node.names]
            else:
                base = _resolve_from_module(module, node)
                targets = [(base, None)] if base else []
            for target, _ in targets:
                internal = _module_path(source_root, target) is not None
                module.import_edges.append({
                    "target": target,
                    "kind": "internal" if internal else "external",
                    "line": int(node.lineno),
                    "source": _source(module.source, node),
                })
                if internal:
                    pending.append(target)

    # Stable deduplication of repeated imports.
    for module in modules.values():
        unique: dict[tuple[str, str, int, str], dict[str, Any]] = {}
        for row in module.import_edges:
            key = (row["target"], row["kind"], row["line"], row["source"])
            unique[key] = row
        module.import_edges = [unique[key] for key in sorted(unique)]
    return modules


def _callable_id(module: str, qualname: str, line: int) -> str:
    return f"{module}::{qualname}@{line}"


def _class_id(module: str, qualname: str, line: int) -> str:
    return f"{module}::{qualname}@{line}"


def _collect_definitions(
        modules: Mapping[str, _Module],
        ) -> tuple[dict[str, _Callable], dict[str, _Class],
                   dict[ast.AST, str], dict[ast.AST, str]]:
    callables: dict[str, _Callable] = {}
    classes: dict[str, _Class] = {}
    callable_by_node: dict[ast.AST, str] = {}
    class_by_node: dict[ast.AST, str] = {}

    def immediate_nested_statements(node: ast.AST) -> Iterable[ast.stmt]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                yield child
            elif not isinstance(child, ast.expr):
                # ExceptHandler and match_case contain statement lists but are
                # not themselves ast.stmt nodes.
                yield from immediate_nested_statements(child)

    def walk_body(module: _Module, body: list[ast.stmt], *,
                  prefix: str, scope_kind: str,
                  current_class_id: str | None,
                  lexical_parent_id: str | None) -> None:
        for statement in body:
            if isinstance(statement, ast.ClassDef):
                qualname = f"{prefix}.{statement.name}" if prefix else statement.name
                identifier = _class_id(module.name, qualname, statement.lineno)
                info = _Class(
                    class_id=identifier,
                    module=module.name,
                    qualname=qualname,
                    node=statement,
                    has_custom_metaclass=any(
                        keyword.arg == "metaclass" for keyword in statement.keywords),
                )
                classes[identifier] = info
                class_by_node[statement] = identifier
                if scope_kind == "module":
                    module.top_classes[statement.name] = identifier
                walk_body(
                    module, statement.body, prefix=qualname,
                    scope_kind="class", current_class_id=identifier,
                    lexical_parent_id=lexical_parent_id)
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if scope_kind == "function":
                    qualname = f"{prefix}.<locals>.{statement.name}"
                else:
                    qualname = f"{prefix}.{statement.name}" if prefix else statement.name
                identifier = _callable_id(
                    module.name, qualname, statement.lineno)
                method_class = current_class_id if scope_kind == "class" else None
                info = _Callable(
                    callable_id=identifier,
                    module=module.name,
                    qualname=qualname,
                    node=statement,
                    class_id=method_class,
                    lexical_parent_id=lexical_parent_id,
                )
                callables[identifier] = info
                callable_by_node[statement] = identifier
                if scope_kind == "module":
                    module.top_functions[statement.name] = identifier
                if method_class is not None:
                    classes[method_class].methods[statement.name] = identifier
                walk_body(
                    module, statement.body, prefix=qualname,
                    scope_kind="function", current_class_id=None,
                    lexical_parent_id=identifier)
                continue
            for nested_statement in immediate_nested_statements(statement):
                walk_body(
                    module, [nested_statement], prefix=prefix,
                    scope_kind=scope_kind,
                    current_class_id=current_class_id,
                    lexical_parent_id=lexical_parent_id)

    for module in modules.values():
        walk_body(module, module.tree.body, prefix="", scope_kind="module",
                  current_class_id=None, lexical_parent_id=None)
    return callables, classes, callable_by_node, class_by_node


def _populate_bindings(modules: Mapping[str, _Module],
                       callables: Mapping[str, _Callable],
                       classes: Mapping[str, _Class]) -> None:
    source_root = next(iter(modules.values())).path.parents[1]
    del callables, classes  # registries are represented by module top tables
    for module in modules.values():
        bindings: dict[str, _Binding] = {}
        for node in _module_level_imports(module.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    target = alias.name if alias.asname else alias.name.split(".")[0]
                    kind = ("internal-module"
                            if _module_path(source_root, target) is not None
                            else "external-symbol")
                    bindings[local] = _Binding(kind, target)
            else:
                base = _resolve_from_module(module, node)
                if not base:
                    continue
                base_internal = base in modules
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    if base_internal:
                        imported = modules[base]
                        if alias.name in imported.top_functions:
                            binding = _Binding(
                                "internal-function",
                                imported.top_functions[alias.name])
                        elif alias.name in imported.top_classes:
                            binding = _Binding(
                                "internal-class",
                                imported.top_classes[alias.name])
                        else:
                            child_module = f"{base}.{alias.name}"
                            if child_module in modules:
                                binding = _Binding(
                                    "internal-module", child_module)
                            else:
                                binding = _Binding(
                                    "internal-unknown", f"{base}.{alias.name}")
                    else:
                        binding = _Binding(
                            "external-symbol", f"{base}.{alias.name}")
                    bindings[local] = binding
        for name, identifier in module.top_functions.items():
            bindings[name] = _Binding("internal-function", identifier)
        for name, identifier in module.top_classes.items():
            bindings[name] = _Binding("internal-class", identifier)
        # Execute only unconditional, simple module aliases exactly.  Every
        # other ordinary module binding is retained as an explicit unknown so
        # it cannot accidentally fall through to a same-named builtin.
        for statement in module.tree.body:
            targets: list[ast.expr] = []
            rhs: ast.expr | None = None
            if isinstance(statement, ast.Assign):
                targets = list(statement.targets)
                rhs = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                rhs = statement.value
            elif isinstance(statement, (ast.AugAssign, ast.Delete,
                                        ast.For, ast.AsyncFor, ast.With,
                                        ast.AsyncWith)):
                target = getattr(statement, "target", None)
                if target is not None:
                    targets = [target]
                elif isinstance(statement, ast.Delete):
                    targets = list(statement.targets)
            for target in targets:
                for name in _target_names(target):
                    alias_binding: _Binding | None = None
                    if rhs is not None and isinstance(rhs, (ast.Name,
                                                           ast.Attribute)):
                        # Resolve against the bindings established by imports
                        # and definitions, including earlier simple aliases.
                        saved = module.bindings
                        module.bindings = bindings
                        try:
                            alias_binding = _binding_for_expr(rhs, module)
                        finally:
                            module.bindings = saved
                    bindings[name] = (alias_binding if alias_binding is not None
                                      else _Binding("internal-unknown",
                                                    f"{module.name}.{name}"))
        module.bindings = bindings


def _resolve_class_expr(expr: ast.expr, module: _Module,
                        classes: Mapping[str, _Class]) -> str | None:
    if isinstance(expr, ast.Name):
        binding = module.bindings.get(expr.id)
        if binding is not None and binding.kind == "internal-class":
            return binding.target
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        binding = module.bindings.get(expr.value.id)
        if binding is not None and binding.kind == "internal-module":
            target_module = binding.target
            # Caller supplies the global registry; match by module/short name.
            candidates = [identifier for identifier, item in classes.items()
                          if item.module == target_module and
                          item.qualname == expr.attr]
            if len(candidates) == 1:
                return candidates[0]
    return None


def _builtin_class_expr(expr: ast.expr, module: _Module) -> str | None:
    """Return an unshadowed builtin base name, including ``list[T]``."""
    base = expr.value if isinstance(expr, ast.Subscript) else expr
    if not isinstance(base, ast.Name) or base.id not in _BUILTIN_CONTAINER_BASES:
        return None
    binding = module.bindings.get(base.id)
    if binding is not None:
        return None
    return base.id


def _resolve_class_bases(modules: Mapping[str, _Module],
                         classes: dict[str, _Class]) -> None:
    for info in classes.values():
        module = modules[info.module]
        internal: list[str] = []
        external: list[str] = []
        builtin_base_names: list[str] = []
        for base in info.node.bases:
            resolved = _resolve_class_expr(base, module, classes)
            if resolved is not None:
                internal.append(resolved)
            else:
                builtin_base = _builtin_class_expr(base, module)
                if builtin_base is not None:
                    builtin_base_names.append(builtin_base)
                else:
                    external.append(_source(module.source, base))
        info.base_class_ids = tuple(internal)
        info.external_bases = tuple(external)
        info.builtin_bases = tuple(builtin_base_names)


class _ScopeVisitor(ast.NodeVisitor):
    """Visit one callable body without descending into nested callables."""

    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.calls: list[ast.Call] = []
        self.local_bound: set[str] = {
            argument.arg for argument in (
                list(root.args.posonlyargs) + list(root.args.args) +
                list(root.args.kwonlyargs) +
                ([root.args.vararg] if root.args.vararg is not None else []) +
                ([root.args.kwarg] if root.args.kwarg is not None else []))
        }
        self.global_names: set[str] = set()
        self.rebound_names: set[str] = set()
        self.assignments: list[tuple[ast.expr, ast.expr | None]] = []
        self.nested_defs: dict[str, ast.AST] = {}
        self.local_imports: list[ast.Import | ast.ImportFrom] = []
        for statement in root.body:
            self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:  # noqa: N802
        self.local_bound.update(node.names)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.local_bound.add(node.id)
            self.rebound_names.add(node.id)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            self.assignments.append((target, node.value))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if node.value is not None:
            self.assignments.append((node.target, node.value))
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self.assignments.append((node.target, None))
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.assignments.append((node.target, None))
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        for item in node.items:
            if item.optional_vars is not None:
                # ``with factory() as value`` binds the value returned by the
                # exact context-manager expression.  For call-graph boundary
                # classification the factory provenance is conservative: it
                # never manufactures an internal callable edge.
                self.assignments.append(
                    (item.optional_vars, item.context_expr))
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        self.local_imports.append(node)
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.local_bound.add(name)
            self.rebound_names.add(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.local_imports.append(node)
        for alias in node.names:
            if alias.name != "*":
                name = alias.asname or alias.name
                self.local_bound.add(name)
                self.rebound_names.add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.local_bound.add(node.name)
        self.rebound_names.add(node.name)
        self.nested_defs[node.name] = node
        # Defaults/decorators execute in this scope when the def is reached.
        for expression in list(node.decorator_list) + list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.local_bound.add(node.name)
        self.rebound_names.add(node.name)
        for expression in list(node.decorator_list) + list(node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        # The body executes later, while defaults execute when the lambda is
        # created in this scope.
        for expression in list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        result: list[str] = []
        for item in target.elts:
            result.extend(_target_names(
                item.value if isinstance(item, ast.Starred) else item))
        return result
    return []


def _external_category(target: str, *, module: str,
                       attribute: str | None = None) -> str:
    root = target.split(".")[0]
    if root == "pygame":
        return "pygame"
    if root in {"pathlib", "json", "wave"} or target in {"open"}:
        return "filesystem"
    if root == "ctypes":
        return "bass" if module == "rtype_port.audio" else "host-ffi"
    if root in {"numpy", "np"}:
        return "host-numeric"
    if root == "time":
        return "host-timing"
    if root == "os":
        return "filesystem" if attribute in _FILESYSTEM_METHODS else "host-os"
    if root in {"builtins", "collections", "dataclasses", "struct"}:
        return "python-runtime"
    return "python-runtime"


def _dotted(expr: ast.expr) -> str | None:
    parts: list[str] = []
    cursor: ast.expr = expr
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    parts.append(cursor.id)
    return ".".join(reversed(parts))


def _method_lookup(class_id: str, method: str,
                   classes: Mapping[str, _Class],
                   seen: set[str] | None = None) -> str | None:
    visited = set() if seen is None else seen
    if class_id in visited:
        return None
    visited.add(class_id)
    info = classes[class_id]
    if method in info.methods:
        return info.methods[method]
    for base in info.base_class_ids:
        target = _method_lookup(base, method, classes, visited)
        if target is not None:
            return target
    return None


def _all_descendants(classes: Mapping[str, _Class]) -> dict[str, set[str]]:
    direct: dict[str, set[str]] = defaultdict(set)
    for identifier, info in classes.items():
        for base in info.base_class_ids:
            direct[base].add(identifier)
    result: dict[str, set[str]] = {}
    for identifier in classes:
        reached: set[str] = set()
        pending = list(direct.get(identifier, ()))
        while pending:
            child = pending.pop()
            if child in reached:
                continue
            reached.add(child)
            pending.extend(direct.get(child, ()))
        result[identifier] = reached
    return result


def _dataclass_decorator(
        decorator: ast.expr, module: _Module) -> tuple[bool, bool]:
    """Return ``(is_dataclass, generated_init_enabled)`` from exact import proof."""
    expression = decorator.func if isinstance(decorator, ast.Call) else decorator
    binding = _binding_for_expr(expression, module)
    if (binding is None or binding.kind != "external-symbol" or
            binding.target != "dataclasses.dataclass"):
        return False, False
    init_enabled = True
    if isinstance(decorator, ast.Call):
        for keyword in decorator.keywords:
            if keyword.arg == "init":
                if not (isinstance(keyword.value, ast.Constant) and
                        isinstance(keyword.value.value, bool)):
                    return True, False
                init_enabled = keyword.value.value
    return True, init_enabled


def _is_dataclass_class(
        info: _Class, modules: Mapping[str, _Module]) -> bool:
    module = modules[info.module]
    return any(_dataclass_decorator(decorator, module)[0]
               for decorator in info.node.decorator_list)


def _has_generated_dataclass_init(
        class_id: str, classes: Mapping[str, _Class],
        modules: Mapping[str, _Module]) -> bool:
    info = classes[class_id]
    if "__init__" in info.methods:
        return False
    module = modules[info.module]
    return any(_dataclass_decorator(decorator, module) == (True, True)
               for decorator in info.node.decorator_list)


def _generated_dataclass_init_schema(
        class_id: str, classes: Mapping[str, _Class],
        modules: Mapping[str, _Module]) -> dict[str, Any] | None:
    """Return a source-proven subset of the generated dataclass ``__init__``.

    The subset is deliberately closed: a class must have no inherited field
    providers, every init field must be a directly declared annotated field,
    and defaults must be JSON scalar literals.  ``field()``, ``InitVar``,
    ``ClassVar``, keyword-only fields and factories remain blocked until their
    runtime protocols have their own exact lowering.
    """
    if not _has_generated_dataclass_init(class_id, classes, modules):
        return None
    info = classes[class_id]
    if info.base_class_ids or info.external_bases or info.builtin_bases:
        return None
    module = modules[info.module]
    dataclass_calls = [
        decorator for decorator in info.node.decorator_list
        if _dataclass_decorator(decorator, module) == (True, True)
    ]
    if len(dataclass_calls) != 1:
        return None
    decorator = dataclass_calls[0]
    if isinstance(decorator, ast.Call):
        for keyword in decorator.keywords:
            if keyword.arg in {"kw_only", "slots"} and not (
                    isinstance(keyword.value, ast.Constant) and
                    keyword.value.value is False):
                return None
            if keyword.arg is None:
                return None

    parameters: list[dict[str, Any]] = [{
        "name": "self",
        "kind": "positional-or-keyword",
        "has_default": False,
        "default_ast_sha256": None,
        "default_value_proven": False,
        "default_value": None,
        "annotation_ast_sha256": None,
    }]
    fields: list[dict[str, Any]] = []
    saw_default = False
    for statement in info.node.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name) or statement.simple != 1:
            return None
        annotation_text = ast.unparse(statement.annotation)
        if "ClassVar" in annotation_text or "InitVar" in annotation_text:
            return None
        has_default = statement.value is not None
        default_value: Any = None
        if has_default:
            try:
                default_value = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError, MemoryError,
                    RecursionError):
                return None
            if (default_value is not None and
                    not isinstance(default_value, (bool, int, float, str))):
                return None
            saw_default = True
        elif saw_default:
            return None
        field_row = {
            "name": statement.target.id,
            "annotation_ast_sha256": _ast_sha256(statement.annotation),
            "has_default": has_default,
            "default_ast_sha256": (
                _ast_sha256(statement.value) if has_default else None),
            "default_value_proven": has_default,
            "default_value": default_value,
        }
        fields.append(field_row)
        parameters.append({
            "name": statement.target.id,
            "kind": "positional-or-keyword",
            "has_default": has_default,
            "default_ast_sha256": field_row["default_ast_sha256"],
            "default_value_proven": has_default,
            "default_value": default_value,
            "annotation_ast_sha256": field_row[
                "annotation_ast_sha256"],
        })
    post_init_target = info.methods.get("__post_init__")
    schema: dict[str, Any] = {
        "format": "pyz80.generated-dataclass-init.v1",
        "class_id": class_id,
        "parameters": parameters,
        "fields": fields,
        "post_init_target": post_init_target,
    }
    schema["semantic_sha256"] = _json_sha256(schema)
    return schema


def _standard_constructor(
        class_id: str, classes: Mapping[str, _Class],
        modules: Mapping[str, _Module]) -> bool:
    pending = [class_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        info = classes[current]
        if info.has_custom_metaclass or info.external_bases:
            return False
        module = modules[info.module]
        if any(not _dataclass_decorator(decorator, module)[0]
               for decorator in info.node.decorator_list):
            return False
        pending.extend(info.base_class_ids)
    return _method_lookup(class_id, "__new__", classes) is None


def _binding_for_expr(expr: ast.expr, module: _Module,
                      facts: _Facts | None = None) -> _Binding | None:
    if isinstance(expr, ast.Name):
        if facts is not None and expr.id in facts.local_bound and \
                expr.id not in facts.global_names:
            return facts.local_import_bindings.get(expr.id)
        return module.bindings.get(expr.id)
    dotted = _dotted(expr)
    if dotted is None:
        return None
    root, _, suffix = dotted.partition(".")
    if (facts is not None and root in facts.local_bound and
            root not in facts.global_names):
        binding = facts.local_import_bindings.get(root)
    else:
        binding = module.bindings.get(root)
    if binding is None:
        return None
    if binding.kind == "internal-module":
        return _Binding("internal-module-member",
                        f"{binding.target}.{suffix}")
    if binding.kind == "external-symbol":
        return _Binding("external-symbol", f"{binding.target}.{suffix}")
    return None


def _rhs_evidence(rhs: ast.expr | None, module: _Module,
                  facts: _Facts | None,
                  classes: Mapping[str, _Class],
                  modules: Mapping[str, _Module]) -> tuple[set[str], set[str],
                                                          str | None]:
    """Return exact class ids, host provenance and an alias source name."""
    if rhs is None or (isinstance(rhs, ast.Constant) and rhs.value is None):
        return set(), set(), None
    if isinstance(rhs, (ast.List, ast.Dict, ast.Set, ast.Tuple,
                        ast.ListComp, ast.DictComp, ast.SetComp,
                        ast.GeneratorExp)):
        return set(), {"python-runtime"}, None
    if isinstance(rhs, ast.BinOp):
        left = _rhs_evidence(rhs.left, module, facts, classes, modules)
        right = _rhs_evidence(rhs.right, module, facts, classes, modules)
        if (left[1] == {"python-runtime"} or
                right[1] == {"python-runtime"}):
            return set(), {"python-runtime"}, None
    if isinstance(rhs, ast.IfExp):
        body = _rhs_evidence(rhs.body, module, facts, classes, modules)
        other = _rhs_evidence(rhs.orelse, module, facts, classes, modules)
        if body[2] is None and other[2] is None:
            return body[0] | other[0], body[1] | other[1], None
    if isinstance(rhs, ast.Name):
        if facts is not None:
            class_ids = facts.exact_local_classes.get(rhs.id, set())
            categories = facts.exact_local_provenance.get(rhs.id, set())
            if (class_ids and rhs.id not in facts.local_class_unknown) or \
                    (categories and
                     rhs.id not in facts.local_provenance_unknown):
                return set(class_ids), set(categories), None
        return set(), set(), rhs.id
    if isinstance(rhs, ast.Call):
        binding = _binding_for_expr(rhs.func, module, facts)
        if binding is not None and binding.kind == "internal-class":
            if _standard_constructor(binding.target, classes, modules):
                return {binding.target}, set(), None
        if (isinstance(rhs.func, ast.Name) and
                rhs.func.id in _BUILTIN_CONTAINER_BASES and
                _binding_for_expr(rhs.func, module, facts) is None):
            return set(), {"python-runtime"}, None
        dotted = _dotted(rhs.func)
        if dotted is not None:
            root = dotted.split(".")[0]
            root_binding = module.bindings.get(root)
            if root_binding is not None and root_binding.kind == "external-symbol":
                target = root_binding.target + dotted[len(root):]
                return set(), {
                    _external_category(target, module=module.name,
                                       attribute=(dotted.rsplit(".", 1)[-1]))
                }, None
    return set(), set(), None


def _local_import_bindings(
        visitor: _ScopeVisitor, module: _Module,
        modules: Mapping[str, _Module]) -> dict[str, _Binding]:
    """Resolve imports executed in one callable without guessing collisions."""
    candidates: dict[str, set[_Binding]] = defaultdict(set)
    for node in visitor.local_imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                candidates[local].add(_Binding(
                    "internal-module" if target in modules else
                    "external-symbol", target))
            continue
        base = _resolve_from_module(module, node)
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            if base in modules:
                imported = modules[base]
                if alias.name in imported.top_functions:
                    binding = _Binding(
                        "internal-function", imported.top_functions[alias.name])
                elif alias.name in imported.top_classes:
                    binding = _Binding(
                        "internal-class", imported.top_classes[alias.name])
                elif f"{base}.{alias.name}" in modules:
                    binding = _Binding(
                        "internal-module", f"{base}.{alias.name}")
                else:
                    binding = _Binding(
                        "internal-unknown", f"{base}.{alias.name}")
            else:
                binding = _Binding(
                    "external-symbol", f"{base}.{alias.name}")
            candidates[local].add(binding)

    assigned = {
        name for target, _rhs in visitor.assignments
        for name in _target_names(target)
    }
    return {
        name: next(iter(values))
        for name, values in candidates.items()
        if len(values) == 1 and name not in assigned
    }


def _callable_facts(info: _Callable, module: _Module,
                    callable_by_node: Mapping[ast.AST, str],
                    classes: Mapping[str, _Class],
                    modules: Mapping[str, _Module], *,
                    parameter_class_facts: Mapping[str, set[str]] | None = None,
                    parameter_class_candidates: Mapping[str, set[str]] | None = None,
                    parameter_callable_candidates: Mapping[str, set[str]] | None = None,
                    inherited_callable_candidates: Mapping[str, set[str]] | None = None,
                    call_result_classes: Mapping[ast.Call, set[str]] | None = None,
                    ) -> tuple[_Facts, _ScopeVisitor]:
    visitor = _ScopeVisitor(info.node)
    nested = {name: callable_by_node[node]
              for name, node in visitor.nested_defs.items()
              if node in callable_by_node}
    class_values: dict[str, set[str]] = defaultdict(set)
    provenance: dict[str, set[str]] = defaultdict(set)
    unknown_class: set[str] = set()
    unknown_provenance: set[str] = set()
    aliases: list[tuple[str, str]] = []
    callable_unknown_reasons: dict[str, set[str]] = defaultdict(set)
    provisional = _Facts(
        local_bound=visitor.local_bound - visitor.global_names,
        global_names=set(visitor.global_names),
        rebound_names=set(visitor.rebound_names),
        nested_callables=nested,
        exact_local_classes=class_values,
        local_class_unknown=unknown_class,
        exact_local_provenance=provenance,
        local_provenance_unknown=unknown_provenance,
        local_import_bindings=_local_import_bindings(
            visitor, module, modules),
        exact_parameter_classes=set((parameter_class_facts or {}).keys()),
        parameter_class_candidates=set(
            (parameter_class_candidates or {}).keys()),
        parameter_callable_candidates={
            **{
                name: set(targets)
                for name, targets in (
                    inherited_callable_candidates or {}).items()
                if name not in visitor.local_bound
            },
            **{
                name: set(targets)
                for name, targets in (
                    parameter_callable_candidates or {}).items()
            },
        },
        local_callable_unknown_reasons=callable_unknown_reasons,
    )
    for name, class_ids in (parameter_class_facts or {}).items():
        if name in provisional.local_bound:
            class_values[name].update(class_ids)
    for name, class_ids in (parameter_class_candidates or {}).items():
        if name in provisional.local_bound and name not in class_values:
            class_values[name].update(class_ids)
            unknown_class.add(name)
    for target, rhs in visitor.assignments:
        names = _target_names(target)
        if not names:
            continue
        if isinstance(rhs, ast.Call) and rhs in (call_result_classes or {}):
            class_ids = set((call_result_classes or {})[rhs])
            categories: set[str] = set()
            alias = None
        else:
            class_ids, categories, alias = _rhs_evidence(
                rhs, module, provisional, classes, modules)
        for name in names:
            class_values[name].update(class_ids)
            provenance[name].update(categories)
            if alias is not None:
                aliases.append((name, alias))
            elif (rhs is None or (not class_ids and not categories and not (
                    isinstance(rhs, ast.Constant) and rhs.value is None))):
                unknown_class.add(name)
                unknown_provenance.add(name)
    changed = True
    while changed:
        changed = False
        for destination, source in aliases:
            before = (len(class_values[destination]),
                      len(provenance[destination]),
                      destination in unknown_class,
                      destination in unknown_provenance)
            class_values[destination].update(class_values.get(source, ()))
            provenance[destination].update(provenance.get(source, ()))
            if source in unknown_class:
                unknown_class.add(destination)
            if source in unknown_provenance:
                unknown_provenance.add(destination)
            after = (len(class_values[destination]),
                     len(provenance[destination]),
                     destination in unknown_class,
                     destination in unknown_provenance)
            changed |= before != after
    callable_aliases: list[tuple[str, set[str], set[str]]] = []

    def callable_rhs(expression: ast.expr | None) -> tuple[set[str], set[str]]:
        if isinstance(expression, ast.Name):
            direct = provisional.nested_callables.get(expression.id)
            targets = set(provisional.parameter_callable_candidates.get(
                expression.id, ()))
            if direct is not None:
                targets.add(direct)
            binding = _binding_for_expr(expression, module, provisional)
            if binding is not None and binding.kind == "internal-function":
                targets.add(binding.target)
            return targets, {expression.id}
        if isinstance(expression, ast.IfExp):
            left_targets, left_aliases = callable_rhs(expression.body)
            right_targets, right_aliases = callable_rhs(expression.orelse)
            return (left_targets | right_targets,
                    left_aliases | right_aliases)
        if isinstance(expression, ast.BoolOp):
            targets: set[str] = set()
            source_names: set[str] = set()
            for value in expression.values:
                nested_targets, nested_names = callable_rhs(value)
                targets.update(nested_targets)
                source_names.update(nested_names)
            return targets, source_names
        return set(), set()

    for target, rhs in visitor.assignments:
        targets, source_names = callable_rhs(rhs)
        for name in _target_names(target):
            callable_aliases.append((name, targets, source_names))
            if (isinstance(rhs, ast.Call) and
                    isinstance(rhs.func, ast.Name) and
                    rhs.func.id == "getattr" and
                    _binding_for_expr(rhs.func, module, provisional) is None):
                callable_unknown_reasons[name].add(
                    "local value comes from dynamic builtins.getattr result")
            elif isinstance(rhs, ast.Lambda):
                callable_unknown_reasons[name].add(
                    "local lambda has no inventoried callable unit")
            elif isinstance(rhs, (ast.BoolOp, ast.IfExp)) and any(
                    isinstance(node, ast.Lambda) for node in ast.walk(rhs)):
                callable_unknown_reasons[name].add(
                    "local choice contains a lambda without an inventoried "
                    "callable unit")
            elif rhs is None:
                callable_unknown_reasons[name].add(
                    "local value is mutated without callable identity")
    changed = True
    while changed:
        changed = False
        for destination, direct_targets, source_names in callable_aliases:
            before = len(provisional.parameter_callable_candidates.get(
                destination, ()))
            merged = provisional.parameter_callable_candidates.setdefault(
                destination, set())
            merged.update(direct_targets)
            for source_name in source_names:
                merged.update(provisional.parameter_callable_candidates.get(
                    source_name, ()))
            changed |= len(merged) != before
    return provisional, visitor


def _class_attribute_facts(
        callables: Mapping[str, _Callable], modules: Mapping[str, _Module],
        callable_by_node: Mapping[ast.AST, str],
        classes: Mapping[str, _Class],
        parameter_class_facts: Mapping[str, Mapping[str, set[str]]] | None = None,
        parameter_class_candidates: Mapping[str, Mapping[str, set[str]]] | None = None,
        call_result_classes: Mapping[ast.Call, set[str]] | None = None,
        ) -> tuple[dict[tuple[str, str], set[str]], set[tuple[str, str]],
                   dict[tuple[str, str], set[str]], set[tuple[str, str]]]:
    class_values: dict[tuple[str, str], set[str]] = defaultdict(set)
    class_unknown: set[tuple[str, str]] = set()
    provenance: dict[tuple[str, str], set[str]] = defaultdict(set)
    provenance_unknown: set[tuple[str, str]] = set()
    for info in callables.values():
        if info.class_id is None:
            continue
        module = modules[info.module]
        facts, visitor = _callable_facts(
            info, module, callable_by_node, classes, modules,
            parameter_class_facts=(parameter_class_facts or {}).get(
                info.callable_id),
            parameter_class_candidates=(parameter_class_candidates or {}).get(
                info.callable_id),
            call_result_classes=call_result_classes)
        for target, rhs in visitor.assignments:
            if not (isinstance(target, ast.Attribute) and
                    isinstance(target.value, ast.Name) and
                    target.value.id == "self"):
                continue
            key = (info.class_id, target.attr)
            if isinstance(rhs, ast.Call) and rhs in (call_result_classes or {}):
                class_ids = set((call_result_classes or {})[rhs])
                categories: set[str] = set()
                alias = None
            else:
                class_ids, categories, alias = _rhs_evidence(
                    rhs, module, facts, classes, modules)
            class_values[key].update(class_ids)
            provenance[key].update(categories)
            if alias is not None:
                class_unknown.add(key)
                provenance_unknown.add(key)
            elif (rhs is None or (not class_ids and not categories and not (
                    isinstance(rhs, ast.Constant) and rhs.value is None))):
                class_unknown.add(key)
                provenance_unknown.add(key)
    return class_values, class_unknown, provenance, provenance_unknown


def _populate_module_value_facts(
        modules: Mapping[str, _Module], classes: Mapping[str, _Class]) -> None:
    """Record exact runtime provenance of ordinary module-level values."""
    for module in modules.values():
        values: dict[str, set[str]] = defaultdict(set)
        unknown: set[str] = set()
        for statement in module.tree.body:
            assignments: list[tuple[ast.expr, ast.expr | None]] = []
            if isinstance(statement, ast.Assign):
                assignments.extend((target, statement.value)
                                   for target in statement.targets)
            elif isinstance(statement, ast.AnnAssign):
                assignments.append((statement.target, statement.value))
            elif isinstance(statement, ast.AugAssign):
                assignments.append((statement.target, None))
            for target, rhs in assignments:
                names = _target_names(target)
                if not names:
                    continue
                _class_ids, categories, alias = _rhs_evidence(
                    rhs, module, None, classes, modules)
                for name in names:
                    values[name].update(categories)
                    if alias is not None or (
                            rhs is not None and not categories and not (
                                isinstance(rhs, ast.Constant) and
                                rhs.value is None)):
                        unknown.add(name)
        module.value_provenance = dict(values)
        module.value_provenance_unknown = unknown
    for module in modules.values():
        for node in _module_level_imports(module.tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            base = _resolve_from_module(module, node)
            imported = modules.get(base)
            if imported is None:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                if (alias.name in imported.value_provenance and
                        alias.name not in imported.value_provenance_unknown and
                        module.bindings.get(local, _Binding("", "")).kind ==
                        "internal-unknown"):
                    module.bindings[local] = _Binding(
                        "internal-value", f"{base}.{alias.name}")


def _internal_value_provenance(
        target: str, modules: Mapping[str, _Module]) -> set[str]:
    module_name, separator, name = target.rpartition(".")
    if not separator or module_name not in modules:
        return set()
    module = modules[module_name]
    if name in module.value_provenance_unknown:
        return set()
    return set(module.value_provenance.get(name, ()))


def _attribute_fact(
        class_id: str, attribute: str,
        classes: Mapping[str, _Class],
        values: Mapping[tuple[str, str], set[str]],
        unknown: set[tuple[str, str]],
        ) -> tuple[set[str], bool]:
    result: set[str] = set()
    uncertain = False
    pending = [class_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        key = (current, attribute)
        result.update(values.get(key, ()))
        uncertain |= key in unknown
        pending.extend(classes[current].base_class_ids)
    return result, uncertain


def _receiver_class_fact(
        expression: ast.expr, *, effective_class_id: str | None,
        direct_method_class_id: str | None, facts: _Facts, module: _Module,
        modules: Mapping[str, _Module], classes: Mapping[str, _Class],
        descendants: Mapping[str, set[str]],
        values: Mapping[tuple[str, str], set[str]],
        unknown: set[tuple[str, str]],
        call_result_classes: Mapping[ast.Call, set[str]] | None = None,
        ) -> tuple[set[str], bool]:
    """Evaluate a finite receiver-class chain from constructor evidence."""
    if isinstance(expression, ast.Name):
        if (expression.id in {"self", "cls"} and
                effective_class_id is not None and
                (direct_method_class_id is not None or
                 expression.id not in facts.local_bound)):
            possible = ({effective_class_id} |
                        descendants.get(effective_class_id, set()))
            return possible, False
        return (set(facts.exact_local_classes.get(expression.id, ())),
                expression.id in facts.local_class_unknown)
    if isinstance(expression, ast.Call):
        returned = (call_result_classes or {}).get(expression)
        if returned:
            return set(returned), False
        binding = _binding_for_expr(expression.func, module, facts)
        if (binding is not None and binding.kind == "internal-class" and
                _standard_constructor(binding.target, classes, modules)):
            return {binding.target}, False
        return set(), True
    if isinstance(expression, ast.Attribute):
        base_classes, uncertain = _receiver_class_fact(
            expression.value, effective_class_id=effective_class_id,
            direct_method_class_id=direct_method_class_id, facts=facts,
            module=module, modules=modules, classes=classes,
            descendants=descendants, values=values, unknown=unknown,
            call_result_classes=call_result_classes)
        if not base_classes:
            return set(), uncertain
        result: set[str] = set()
        for class_id in base_classes:
            attribute_values, attribute_unknown = _attribute_fact(
                class_id, expression.attr, classes, values, unknown)
            if not attribute_values:
                uncertain = True
            result.update(attribute_values)
            uncertain |= attribute_unknown
        return result, uncertain
    return set(), True


def _builtin_method_target(
        class_ids: set[str], method: str,
        classes: Mapping[str, _Class]) -> str | None:
    targets: set[str] = set()
    for class_id in class_ids:
        pending = [class_id]
        visited: set[str] = set()
        class_targets: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            info = classes[current]
            for base_name in info.builtin_bases:
                base = getattr(builtins, base_name, None)
                if base is not None and hasattr(base, method):
                    class_targets.add(f"builtins.{base_name}.{method}")
            pending.extend(info.base_class_ids)
        if len(class_targets) != 1:
            return None
        targets.update(class_targets)
    return next(iter(targets)) if len(targets) == 1 else None


def _direct_class_method_result(
        class_id: str, method: str, classes: Mapping[str, _Class], *,
        evidence: str) -> dict[str, Any] | None:
    target = _method_lookup(class_id, method, classes)
    if target is None:
        return None
    owner = next((item for item in classes.values()
                  if target in item.methods.values()), None)
    if owner is None:
        return None
    node = next((statement for statement in owner.node.body
                 if isinstance(statement, (ast.FunctionDef,
                                           ast.AsyncFunctionDef)) and
                 owner.methods.get(statement.name) == target), None)
    if node is None:
        return None
    for decorator in node.decorator_list:
        expression = decorator.func if isinstance(decorator, ast.Call) else decorator
        if not (isinstance(expression, ast.Name) and
                expression.id in {"classmethod", "staticmethod"}):
            return None
    return {
        "kind": "exact-internal-class-method",
        "proven": True,
        "targets": [target],
        "evidence": evidence,
    }


def _internal_module_member(
        target: str, modules: Mapping[str, _Module]) -> _Binding | None:
    module_name, separator, member = target.rpartition(".")
    if not separator or module_name not in modules:
        return None
    module = modules[module_name]
    if member in module.top_functions:
        return _Binding("internal-function", module.top_functions[member])
    if member in module.top_classes:
        return _Binding("internal-class", module.top_classes[member])
    return None


def _constructor_result(
        class_id: str, classes: Mapping[str, _Class],
        modules: Mapping[str, _Module], *,
        evidence: str) -> dict[str, Any]:
    init = _method_lookup(class_id, "__init__", classes)
    targets = [init] if init is not None else []
    standard = _standard_constructor(class_id, classes, modules)
    if not standard:
        return {
            "kind": ("finite-dynamic-dispatch" if targets else
                     "unresolved-constructor-dispatch"),
            "proven": False,
            "targets": targets,
            "constructed_class": class_id,
            "evidence": evidence + "; constructor/metaclass path is not "
            "fully source-defined",
        }
    if init is None and _is_dataclass_class(classes[class_id], modules):
        return {
            "kind": "host-boundary",
            "proven": False,
            "targets": [],
            "boundary": "python-runtime",
            "external_target": "dataclasses.generated.__init__",
            "constructed_class": class_id,
            "evidence": evidence + "; @dataclass generated constructor",
        }
    return {
        "kind": "exact-internal-constructor",
        "proven": True,
        "targets": targets,
        "constructed_class": class_id,
        "evidence": evidence,
    }


def _method_result(class_ids: set[str], method: str,
                   classes: Mapping[str, _Class], *,
                   evidence: str, exact_receiver: bool) -> dict[str, Any] | None:
    lookups = {
        class_id: _method_lookup(class_id, method, classes)
        for class_id in class_ids
    }
    implementations = sorted({target for target in lookups.values()
                              if target is not None})
    if not implementations:
        return None
    missing = sorted(class_id for class_id, target in lookups.items()
                     if target is None)
    if missing:
        return {
            "kind": "finite-dynamic-dispatch",
            "proven": False,
            "targets": implementations,
            "evidence": (evidence + f"; {len(missing)} possible class(es) "
                         "have no source-defined method target"),
        }
    if exact_receiver and len(class_ids) == 1:
        return {
            "kind": "exact-internal-method",
            "proven": True,
            "targets": implementations,
            "evidence": evidence,
        }
    if len(implementations) == 1:
        return {
            "kind": "exact-common-dispatch",
            "proven": True,
            "targets": implementations,
            "evidence": evidence,
        }
    return {
        "kind": "finite-dynamic-dispatch",
        "proven": False,
        "targets": implementations,
        "evidence": evidence,
    }


def _boundary_result(category: str, target: str,
                     evidence: str) -> dict[str, Any]:
    return {
        "kind": "host-boundary",
        "proven": False,
        "targets": [],
        "boundary": category,
        "external_target": target,
        "evidence": evidence,
    }


def _class_namespace_bound_before(
        info: _Callable, name: str,
        classes: Mapping[str, _Class]) -> bool:
    """Conservatively detect a decorator name shadowed in its class body."""
    if info.class_id is None:
        return False
    owner = classes[info.class_id]
    for statement in owner.node.body:
        if statement is info.node:
            return False
        if (isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)) and
                statement.name == name):
            return True
        if any(isinstance(node, ast.Name) and node.id == name and
               isinstance(node.ctx, (ast.Store, ast.Del))
               for node in ast.walk(statement)):
            return True
        if isinstance(statement, ast.Import):
            if any((alias.asname or alias.name.split(".")[0]) == name
                   for alias in statement.names):
                return True
        if isinstance(statement, ast.ImportFrom):
            if any(alias.name != "*" and
                   (alias.asname or alias.name) == name
                   for alias in statement.names):
                return True
    return True


def _has_exact_builtin_decorator(
        info: _Callable, name: str, module: _Module,
        classes: Mapping[str, _Class]) -> bool:
    """Prove an undecorated builtin descriptor wrapper by lexical binding."""
    if len(info.node.decorator_list) != 1:
        return False
    decorator = info.node.decorator_list[0]
    return (isinstance(decorator, ast.Name) and decorator.id == name and
            module.bindings.get(name) is None and
            not _class_namespace_bound_before(info, name, classes))


def _first_parameter_name(info: _Callable) -> str | None:
    positional = (list(info.node.args.posonlyargs) +
                  list(info.node.args.args))
    return positional[0].arg if positional else None


def _unresolved_local_callable_evidence(
        name: str, info: _Callable, facts: _Facts) -> str:
    reasons = sorted(facts.local_callable_unknown_reasons.get(name, ()))
    if reasons:
        return "; ".join(reasons)
    parameters = {
        argument.arg for argument in (
            list(info.node.args.posonlyargs) + list(info.node.args.args) +
            list(info.node.args.kwonlyargs) +
            ([info.node.args.vararg]
             if info.node.args.vararg is not None else []) +
            ([info.node.args.kwarg]
             if info.node.args.kwarg is not None else []))
    }
    if name in parameters:
        return ("parameter actuals have no complete source-proven "
                "inventoried callable identity")
    return "local value has no source-proven callable identity"


def _resolve_call(
        call: ast.Call, info: _Callable, module: _Module, facts: _Facts,
        modules: Mapping[str, _Module], classes: Mapping[str, _Class],
        descendants: Mapping[str, set[str]],
        class_attr_values: Mapping[tuple[str, str], set[str]],
        class_attr_unknown: set[tuple[str, str]],
        class_attr_provenance: Mapping[tuple[str, str], set[str]],
        class_attr_provenance_unknown: set[tuple[str, str]],
        effective_class_id: str | None,
        closed_constructor_classes: set[str],
        call_result_classes: Mapping[ast.Call, set[str]] | None = None,
        ) -> dict[str, Any]:
    function = call.func
    if isinstance(function, ast.Name):
        name = function.id
        nested = facts.nested_callables.get(name)
        if nested is not None:
            return {
                "kind": "exact-nested-function", "proven": True,
                "targets": [nested], "evidence": "lexical nested def binding",
            }
        if (effective_class_id is not None and
                info.class_id == effective_class_id and
                name == _first_parameter_name(info) and
                name not in facts.rebound_names and
                _has_exact_builtin_decorator(
                    info, "classmethod", module, classes)):
            if (effective_class_id in closed_constructor_classes and
                    not descendants.get(effective_class_id)):
                result = _constructor_result(
                    effective_class_id, classes, modules,
                    evidence="closed non-escaping leaf classmethod cls")
                if result.get("kind") == "exact-internal-constructor":
                    result["source_proof"] = {
                        "kind": "closed-classmethod-cls-constructor",
                        "class_id": effective_class_id,
                        "parameter": name,
                    }
                return result
            return {
                "kind": "unresolved-local-callable", "proven": False,
                "targets": [], "evidence": "classmethod cls is not proven "
                "to be a closed non-escaping leaf class",
            }
        candidate_targets = facts.parameter_callable_candidates.get(name, set())
        if candidate_targets:
            return {
                "kind": "finite-dynamic-dispatch", "proven": False,
                "targets": sorted(candidate_targets),
                "evidence": "source-proven incoming callable candidates; "
                "candidate set never drives proven reachability",
            }
        is_local = name in facts.local_bound and name not in facts.global_names
        binding = (facts.local_import_bindings.get(name) if is_local else
                   module.bindings.get(name))
        if binding is not None:
            if binding.kind == "internal-function":
                return {
                    "kind": "exact-internal-function", "proven": True,
                    "targets": [binding.target],
                    "evidence": "module/import symbol binding",
                }
            if binding.kind == "internal-class":
                return _constructor_result(
                    binding.target, classes, modules,
                    evidence="module/import class binding")
            if binding.kind == "external-symbol":
                return _boundary_result(
                    _external_category(binding.target, module=module.name),
                    binding.target, ("callable-local import binding" if is_local
                                     else "external import binding"))
        if is_local:
            return {
                "kind": "unresolved-local-callable", "proven": False,
                "targets": [], "evidence":
                _unresolved_local_callable_evidence(name, info, facts),
            }
        if name in _BUILTIN_NAMES:
            return _boundary_result(
                "python-runtime", f"builtins.{name}", "Python builtin name")
        return {
            "kind": "unresolved-global-callable", "proven": False,
            "targets": [], "evidence": "name has no internal/import binding",
        }

    if not isinstance(function, ast.Attribute):
        return {
            "kind": "unresolved-callable-expression", "proven": False,
            "targets": [], "evidence": type(function).__name__,
        }

    method = function.attr
    receiver = function.value

    # Zero-argument super() has a source-defined next base only when the
    # lexical class has one direct base and the active closed hierarchy cannot
    # insert a descendant-specific MRO entry after that class.
    if (isinstance(receiver, ast.Call) and
            isinstance(receiver.func, ast.Name) and
            receiver.func.id == "super" and not receiver.args and
            not receiver.keywords and effective_class_id is not None):
        class_info = classes[effective_class_id]
        internal_bases = class_info.base_class_ids
        builtin_bases = class_info.builtin_bases
        direct_base_count = (len(internal_bases) + len(builtin_bases) +
                             len(class_info.external_bases))
        closed_leaf = (info.class_id == effective_class_id and
                       _first_parameter_name(info) is not None and
                       effective_class_id in closed_constructor_classes and
                       not descendants.get(effective_class_id))
        if direct_base_count == 1 and len(internal_bases) == 1:
            target = _method_lookup(internal_bases[0], method, classes)
            if target is not None:
                return {
                    "kind": "exact-super-method", "proven": True,
                    "targets": [target],
                    "evidence": "zero-argument super and one internal base",
                }
            if (method == "__init__" and
                    _has_generated_dataclass_init(
                        internal_bases[0], classes, modules)):
                schema = _generated_dataclass_init_schema(
                    internal_bases[0], classes, modules)
                if schema is not None:
                    post_init = schema.get("post_init_target")
                    return {
                        "kind": "exact-generated-dataclass-init",
                        "proven": True,
                        "targets": ([post_init]
                                    if isinstance(post_init, str) else []),
                        "evidence": "zero-argument super and one exact "
                        "source-proven generated dataclass base",
                        "generated_dataclass_init": schema,
                        "receiver_parameter": _first_parameter_name(info),
                    }
                return _boundary_result(
                    "python-runtime", "dataclasses.generated.__init__",
                    "generated dataclass shape is outside the proven subset")
            builtin_target = _builtin_method_target(
                {internal_bases[0]}, method, classes)
            if builtin_target is not None:
                return _boundary_result(
                    "python-runtime", builtin_target,
                    "zero-argument super and one exact builtin-backed base")
        if (direct_base_count == 1 and len(builtin_bases) == 1 and
                closed_leaf):
            base_name = builtin_bases[0]
            base = getattr(builtins, base_name, None)
            if base is not None and hasattr(base, method):
                result = _boundary_result(
                    "python-runtime", f"builtins.{base_name}.{method}",
                    "zero-argument super, one builtin base and closed "
                    "leaf active hierarchy")
                result["source_proof"] = {
                    "kind": "closed-single-builtin-super-mro",
                    "class_id": effective_class_id,
                    "direct_builtin_base": base_name,
                    "method": method,
                }
                return result
        reason = ("base/MRO is not uniquely internal or a closed single-"
                  "builtin leaf")
        return {
            "kind": "unresolved-super-dispatch", "proven": False,
            "targets": [], "evidence": reason,
        }

    binding = _binding_for_expr(function, module, facts)
    if binding is not None:
        if binding.kind == "external-symbol":
            return _boundary_result(
                _external_category(binding.target, module=module.name,
                                   attribute=method),
                binding.target, "external module/symbol attribute")
        if binding.kind == "internal-module-member":
            member = _internal_module_member(binding.target, modules)
            if member is not None:
                if member.kind == "internal-function":
                    return {
                        "kind": "exact-internal-function", "proven": True,
                        "targets": [member.target],
                        "evidence": "internal module attribute binding",
                    }
                return _constructor_result(
                    member.target, classes, modules,
                    evidence="internal module class attribute binding")

    # A class object attribute has exact descriptor ownership.  Ordinary,
    # classmethod and staticmethod functions all have one source target;
    # property/arbitrarily decorated descriptors deliberately remain closed.
    receiver_binding = _binding_for_expr(receiver, module, facts)
    receiver_class_id: str | None = None
    if receiver_binding is not None and receiver_binding.kind == "internal-class":
        receiver_class_id = receiver_binding.target
    elif (receiver_binding is not None and
          receiver_binding.kind == "internal-module-member"):
        member = _internal_module_member(receiver_binding.target, modules)
        if member is not None and member.kind == "internal-class":
            receiver_class_id = member.target
    if receiver_class_id is not None:
        result = _direct_class_method_result(
            receiver_class_id, method, classes,
            evidence="exact internal class attribute binding")
        if result is not None:
            return result

    if isinstance(receiver, ast.Name):
        if receiver.id in {"self", "cls"} and effective_class_id is not None:
            possible = ({effective_class_id} |
                        descendants.get(effective_class_id, set()))
            result = _method_result(
                possible, method, classes,
                evidence=f"closed active hierarchy for {receiver.id}",
                exact_receiver=False)
            if result is not None:
                return result
        class_ids = facts.exact_local_classes.get(receiver.id, set())
        unknown = receiver.id in facts.local_class_unknown
        if class_ids:
            local_evidence = (
                "closed non-escaping constructor argument flow"
                if receiver.id in facts.exact_parameter_classes else
                "local constructor/alias assignment")
            result = _method_result(
                set(class_ids), method, classes,
                evidence=local_evidence,
                exact_receiver=not unknown)
            if result is not None:
                if unknown:
                    result["kind"] = "finite-dynamic-dispatch"
                    result["proven"] = False
                    result["evidence"] += "; other assignments exist"
                return result
        categories = facts.exact_local_provenance.get(receiver.id, set())
        if categories and receiver.id not in facts.local_provenance_unknown:
            category = sorted(categories)[0] if len(categories) == 1 \
                else "host-object"
            return _boundary_result(
                category, f"{receiver.id}.{method}",
                "local value returned by external boundary")
        if (receiver.id not in facts.local_bound or
                receiver.id in facts.global_names):
            categories = module.value_provenance.get(receiver.id, set())
            value_binding = _binding_for_expr(receiver, module, facts)
            if (value_binding is not None and
                    value_binding.kind == "internal-value"):
                categories = _internal_value_provenance(
                    value_binding.target, modules)
            if (categories and
                    receiver.id not in module.value_provenance_unknown):
                category = (sorted(categories)[0]
                            if len(categories) == 1 else "host-object")
                return _boundary_result(
                    category, f"{receiver.id}.{method}",
                    "module value has exact source expression provenance")

    if (isinstance(receiver, ast.Attribute) and
            isinstance(receiver.value, ast.Name) and
            receiver.value.id == "self" and
            effective_class_id is not None):
        attribute = receiver.attr
        class_ids, unknown = _attribute_fact(
            effective_class_id, attribute, classes,
            class_attr_values, class_attr_unknown)
        if class_ids:
            result = _method_result(
                class_ids, method, classes,
                evidence=f"self.{attribute} constructor assignment",
                exact_receiver=not unknown)
            if result is not None:
                if unknown:
                    result["kind"] = "finite-dynamic-dispatch"
                    result["proven"] = False
                    result["evidence"] += "; unknown assignments exist"
                return result
        categories, provenance_unknown = _attribute_fact(
            effective_class_id, attribute, classes,
            class_attr_provenance, class_attr_provenance_unknown)
        if (categories and not provenance_unknown) or method.startswith("BASS_"):
            category = ("bass" if method.startswith("BASS_") else
                        (sorted(categories)[0] if len(categories) == 1
                         else "host-object"))
            return _boundary_result(
                category, f"self.{attribute}.{method}",
                "self attribute external-constructor provenance")

    # General exact receiver chains such as ``self.world.rom.word`` use only
    # source constructor assignments.  Missing/ambiguous links never become
    # proven edges.
    receiver_classes, receiver_unknown = _receiver_class_fact(
        receiver, effective_class_id=effective_class_id,
        direct_method_class_id=info.class_id, facts=facts, module=module,
        modules=modules, classes=classes, descendants=descendants,
        values=class_attr_values, unknown=class_attr_unknown,
        call_result_classes=call_result_classes)
    if receiver_classes:
        result = _method_result(
            receiver_classes, method, classes,
            evidence="finite constructor-assignment receiver chain",
            exact_receiver=not receiver_unknown)
        if result is not None:
            if receiver_unknown:
                result["kind"] = "finite-dynamic-dispatch"
                result["proven"] = False
                result["evidence"] += "; unknown receiver-chain links exist"
            return result
        if not receiver_unknown:
            builtin_target = _builtin_method_target(
                receiver_classes, method, classes)
            if builtin_target is not None:
                return _boundary_result(
                    "python-runtime", builtin_target,
                    "finite constructor chain ends at one builtin base")

    if isinstance(receiver, ast.Call):
        receiver_binding = _binding_for_expr(receiver.func, module, facts)
        if (receiver_binding is not None and
                receiver_binding.kind == "internal-class"):
            result = _method_result(
                {receiver_binding.target}, method, classes,
                evidence="method on direct internal constructor result",
                exact_receiver=True)
            if result is not None:
                return result
        dotted_receiver = _dotted(receiver.func)
        if dotted_receiver is not None:
            root = dotted_receiver.split(".")[0]
            root_binding = module.bindings.get(root)
            if root_binding is not None and root_binding.kind == "external-symbol":
                target = root_binding.target + dotted_receiver[len(root):]
                return _boundary_result(
                    _external_category(target, module=module.name,
                                       attribute=method),
                    f"{target}(...).{method}",
                    "method on direct external call result")

    if method in _FILESYSTEM_METHODS:
        return _boundary_result(
            "filesystem", _source(module.source, function),
            "filesystem protocol method name; receiver type unresolved")
    if method in _PYGAME_METHODS:
        return _boundary_result(
            "pygame", _source(module.source, function),
            "pygame surface protocol method; receiver type unresolved")
    return {
        "kind": "unresolved-dynamic-attribute", "proven": False,
        "targets": [],
        "evidence": "receiver has no source-proven finite class identity",
    }


class _ExclusiveCensus(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.statements: Counter[str] = Counter()
        self.expressions: Counter[str] = Counter()
        self.lambdas = 0
        for statement in root.body:
            self.visit(statement)

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.stmt):
            self.statements[type(node).__name__] += 1
        if isinstance(node, ast.expr):
            self.expressions[type(node).__name__] += 1
        return super().visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        # Count the def statement in its parent, but its body belongs to its
        # own callable inventory row.  Defaults/decorators execute here.
        for expression in list(node.decorator_list) + list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        # A nested class body is a separate execution namespace.
        for expression in list(node.decorator_list) + list(node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self.lambdas += 1
        for expression in list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)


class _ModuleInitializationVisitor(ast.NodeVisitor):
    """Calls evaluated while a module and its class bodies are created."""

    def __init__(self, tree: ast.Module) -> None:
        self.calls: list[ast.Call] = []
        self.decorators: list[tuple[ast.AST, ast.expr]] = []
        self.visit(tree)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        # With future annotations enabled in every active module, annotations
        # are stored rather than evaluated.  Defaults/decorators still execute.
        self.decorators.extend((node, decorator)
                               for decorator in node.decorator_list)
        for expression in list(node.decorator_list) + list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.decorators.extend((node, decorator)
                               for decorator in node.decorator_list)
        for expression in list(node.decorator_list) + list(node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        # Unlike a function body, a class body executes during module load.
        for statement in node.body:
            self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        for expression in list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)


def _resolve_module_initialization_call(
        call: ast.Call, module: _Module,
        modules: Mapping[str, _Module], classes: Mapping[str, _Class],
        ) -> dict[str, Any]:
    function = call.func
    if isinstance(function, ast.Name):
        binding = module.bindings.get(function.id)
        if binding is not None:
            if binding.kind == "internal-function":
                return {
                    "kind": "exact-internal-function", "proven": True,
                    "targets": [binding.target],
                    "evidence": "module initialization symbol binding",
                }
            if binding.kind == "internal-class":
                return _constructor_result(
                    binding.target, classes, modules,
                    evidence="module initialization class binding")
            if binding.kind == "external-symbol":
                return _boundary_result(
                    _external_category(binding.target, module=module.name),
                    binding.target, "module initialization external import")
        if function.id in _BUILTIN_NAMES:
            return _boundary_result(
                "python-runtime", f"builtins.{function.id}",
                "module initialization builtin")
    if isinstance(function, ast.Attribute):
        binding = _binding_for_expr(function, module)
        if binding is not None and binding.kind == "external-symbol":
            return _boundary_result(
                _external_category(binding.target, module=module.name,
                                   attribute=function.attr),
                binding.target, "module initialization external attribute")
        if binding is not None and binding.kind == "internal-module-member":
            member = _internal_module_member(binding.target, modules)
            if member is not None and member.kind == "internal-function":
                return {
                    "kind": "exact-internal-function", "proven": True,
                    "targets": [member.target],
                    "evidence": "module initialization internal attribute",
                }
            if member is not None and member.kind == "internal-class":
                return _constructor_result(
                    member.target, classes, modules,
                    evidence="module initialization internal class attribute")
    return {
        "kind": "unresolved-module-initialization-call",
        "proven": False,
        "targets": [],
        "evidence": "module/class initialization expression is not exact",
    }


def _module_initialization_inventory(
        modules: Mapping[str, _Module], classes: Mapping[str, _Class],
        ) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for module in sorted(modules.values(), key=lambda item: item.name):
        visitor = _ModuleInitializationVisitor(module.tree)
        for call in sorted(visitor.calls,
                           key=lambda item: (item.lineno, item.col_offset,
                                             item.end_lineno or item.lineno,
                                             item.end_col_offset or 0)):
            identity = {
                "module": module.name,
                "line": int(call.lineno),
                "column": int(call.col_offset),
                "ast_sha256": _ast_sha256(call),
                "operation_kind": "explicit-call",
            }
            rows.append({
                "call_site_id": _json_sha256(identity),
                **identity,
                "source": _source(module.source, call),
                "resolution": _resolve_module_initialization_call(
                    call, module, modules, classes),
            })
        for owner, decorator in sorted(
                visitor.decorators,
                key=lambda item: (item[1].lineno, item[1].col_offset,
                                  item[0].lineno)):
            identity = {
                "module": module.name,
                "line": int(decorator.lineno),
                "column": int(decorator.col_offset),
                "ast_sha256": _ast_sha256(decorator),
                "operation_kind": "decorator-application",
            }
            synthetic = ast.Call(func=decorator, args=[], keywords=[])
            rows.append({
                "call_site_id": _json_sha256(identity),
                **identity,
                "owner_kind": type(owner).__name__,
                "owner_line": int(getattr(owner, "lineno", decorator.lineno)),
                "source": "@" + _source(module.source, decorator),
                "resolution": _resolve_module_initialization_call(
                    synthetic, module, modules, classes),
            })
    property_getters = 0
    property_setters = 0
    for info in classes.values():
        for statement in info.node.body:
            if not isinstance(statement, (ast.FunctionDef,
                                          ast.AsyncFunctionDef)):
                continue
            for decorator in statement.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "property":
                    property_getters += 1
                elif (isinstance(decorator, ast.Attribute) and
                      decorator.attr in {"setter", "deleter"}):
                    property_setters += 1
    result = {
        "status": "INVENTORIED_NOT_CFG_LOWERED",
        "call_site_count": len(rows),
        "call_sites": rows,
        "resolution_kind_counts": _resolution_summary(rows),
        "host_boundary_call_site_count": sum(
            row["resolution"]["kind"] == "host-boundary" for row in rows),
        "unresolved_call_site_count": sum(
            row["resolution"]["kind"].startswith("unresolved-")
            for row in rows),
        "explicit_call_site_count": sum(
            row["operation_kind"] == "explicit-call" for row in rows),
        "decorator_application_count": sum(
            row["operation_kind"] == "decorator-application" for row in rows),
        "property_getter_definition_count": property_getters,
        "property_setter_or_deleter_definition_count": property_setters,
        "module_initializers_have_no_function_cfg": True,
        "descriptor_dispatch_remains_in_python_expression_semantics": True,
    }
    result["semantic_sha256"] = _json_sha256(result)
    return result


def _attach_object_store_fragments(
        project_root: Path, modules: Mapping[str, _Module],
        callables: Mapping[str, _Callable],
        callable_by_node: Mapping[ast.AST, str],
        hooks: MutationHookPlan, stores: Any,
        ) -> dict[str, Any]:
    source_relative = _norm(Path(hooks.source_path))
    matching = [module for module in modules.values()
                if module.relative_path == source_relative]
    if len(matching) != 1:
        raise ActiveCallGraphError(
            "PZACG004", "object-store source is outside active module graph")
    module = matching[0]
    if (module.source_sha256 != hooks.source_sha256 or
            module.source_sha256 != stores.source_sha256 or
            stores.mutation_hook_semantic_sha256 != hooks.semantic_sha256):
        raise ActiveCallGraphError(
            "PZACG005", "object-store inputs are stale against module graph")
    parents = {child: parent for parent in ast.walk(module.tree)
               for child in ast.iter_child_nodes(parent)}
    candidates: dict[tuple[int, str], list[ast.AST]] = defaultdict(list)
    for node in ast.walk(module.tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                             ast.Delete, ast.Call)):
            candidates[(int(getattr(node, "lineno", 0)),
                        _ast_sha256(node))].append(node)
    fragment_by_id = {item.site_id: item for item in stores.fragments}
    runtime_hooks = [item for item in hooks.mutation_hooks
                     if item["runtime_hook_required"]]
    owner_counts: Counter[str] = Counter()
    attached_ids: list[int] = []
    for hook in runtime_hooks:
        key = (int(hook["line"]), str(hook["statement_ast_sha256"]))
        matches = candidates.get(key, ())
        if len(matches) != 1:
            raise ActiveCallGraphError(
                "PZACG006", f"mutation site {hook['site_id']} resolves to "
                f"{len(matches)} AST nodes")
        cursor: ast.AST = matches[0]
        owner_id: str | None = None
        while cursor in parents:
            cursor = parents[cursor]
            owner_id = callable_by_node.get(cursor)
            if owner_id is not None:
                break
        if owner_id is None or owner_id not in callables:
            raise ActiveCallGraphError(
                "PZACG007", f"mutation site {hook['site_id']} has no callable")
        fragment = fragment_by_id.get(int(hook["site_id"]))
        if fragment is None:
            raise ActiveCallGraphError(
                "PZACG008", f"mutation site {hook['site_id']} has no fragment")
        callables[owner_id].fragments[matches[0]] = fragment
        owner_counts[owner_id] += 1
        attached_ids.append(fragment.site_id)
    expected_ids = sorted(fragment_by_id)
    if sorted(attached_ids) != expected_ids:
        raise ActiveCallGraphError(
            "PZACG009", "not every exact object-store fragment was attached")
    return {
        "source_path": source_relative,
        "source_sha256": module.source_sha256,
        "mutation_hook_semantic_sha256": hooks.semantic_sha256,
        "object_store_semantic_sha256": stores.semantic_sha256,
        "runtime_site_count": len(runtime_hooks),
        "fragment_count": len(stores.fragments),
        "attached_fragment_count": len(attached_ids),
        "owner_callable_count": len(owner_counts),
        "site_count_per_owner_distribution": {
            str(key): value for key, value in sorted(Counter(
                owner_counts.values()).items())
        },
        "all_fragments_attached_exactly_once": True,
    }


def _lower_all_callables(
        callables: Mapping[str, _Callable], modules: Mapping[str, _Module],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    statement_counts: Counter[str] = Counter()
    expression_counts: Counter[str] = Counter()
    blocker_codes: Counter[str] = Counter()
    blocker_kinds: Counter[str] = Counter()
    lowering_failures: list[dict[str, Any]] = []
    total_blocks = 0
    total_instructions = 0
    total_expression_programs = 0
    total_expression_blocks = 0
    total_expression_instructions = 0
    total_exception_edges = 0
    total_splice_instructions = 0
    lambda_count = 0
    for identifier in sorted(callables):
        info = callables[identifier]
        module = modules[info.module]
        census = _ExclusiveCensus(info.node)
        statement_counts.update(census.statements)
        expression_counts.update(census.expressions)
        lambda_count += census.lambdas
        row: dict[str, Any] = {
            "callable_id": identifier,
            "module": info.module,
            "qualname": info.qualname,
            "class_id": info.class_id,
            "lexical_parent_id": info.lexical_parent_id,
            "definition_line": int(info.node.lineno),
            "ast_sha256": _ast_sha256(info.node),
            "source": _source(module.source, info.node).splitlines()[0],
            "attached_object_store_fragment_count": len(info.fragments),
        }
        try:
            cfg = lower_python_function_cfg(
                info.node,
                class_name=(
                    info.qualname.rsplit(".", 1)[0]
                    if info.class_id is not None else None),
                source_path=Path(module.relative_path),
                source_text=module.source,
                fragments=info.fragments,
            )
        except FunctionCFGError as error:
            failure = {
                "code": error.code,
                "detail": error.detail,
                "callable_id": identifier,
            }
            lowering_failures.append(failure)
            row["cfg"] = None
            row["lowering_failure"] = failure
        else:
            cfg_json = cfg.to_json()
            row["cfg"] = cfg_json
            blockers = cfg_json["blockers"]
            blocker_codes.update(item["code"] for item in blockers)
            blocker_kinds.update(item["node_kind"] for item in blockers)
            blocks = cfg_json["blocks"]
            programs = cfg_json["expression_programs"]
            total_blocks += len(blocks)
            total_exception_edges += sum(
                "exception_target" in block for block in blocks)
            total_instructions += sum(
                len(block["instructions"]) for block in blocks)
            total_splice_instructions += sum(
                instruction["op"] == "execute-object-store-fragment"
                for block in blocks for instruction in block["instructions"])
            total_expression_programs += len(programs)
            total_expression_blocks += sum(
                len(program["blocks"]) for program in programs)
            total_expression_instructions += sum(
                len(block["instructions"])
                for program in programs for block in program["blocks"])
        semantic_payload = dict(row)
        row["semantic_sha256"] = _json_sha256(semantic_payload)
        rows.append(row)

    cfg_rows = [row for row in rows if row["cfg"] is not None]
    blocked_rows = [row for row in cfg_rows if row["cfg"]["blockers"]]
    census = {
        "callable_count": len(rows),
        "cfg_lowered_callable_count": len(cfg_rows),
        "cfg_lowering_failure_count": len(lowering_failures),
        "cfg_blocker_free_callable_count": len(cfg_rows) - len(blocked_rows),
        "cfg_blocked_callable_count": len(blocked_rows),
        "cfg_block_count": total_blocks,
        "cfg_exception_edge_count": total_exception_edges,
        "cfg_instruction_count": total_instructions,
        "cfg_expression_program_count": total_expression_programs,
        "cfg_expression_block_count": total_expression_blocks,
        "cfg_expression_instruction_count": total_expression_instructions,
        "cfg_object_store_splice_instruction_count": total_splice_instructions,
        "exclusive_body_statement_count": sum(statement_counts.values()),
        "exclusive_statement_ast_kind_counts": dict(sorted(
            statement_counts.items())),
        "exclusive_expression_ast_kind_counts": dict(sorted(
            expression_counts.items())),
        "lambda_definition_count": lambda_count,
        "unsupported_lowering_blocker_count": sum(blocker_codes.values()),
        "unsupported_lowering_code_counts": dict(sorted(blocker_codes.items())),
        "unsupported_lowering_ast_kind_counts": dict(sorted(
            blocker_kinds.items())),
        "lowering_failures": lowering_failures,
        "all_callables_in_module_graph_inventoried": True,
        "function_cfg_format": FUNCTION_CFG_IR_FORMAT,
    }
    return rows, census


def _closed_constructor_classes(
        modules: Mapping[str, _Module], callables: Mapping[str, _Callable],
        callable_by_node: Mapping[ast.AST, str],
        classes: Mapping[str, _Class], facts: Mapping[str, _Facts],
        ) -> set[str]:
    """Classes whose source-bound class object never escapes direct use."""
    escaped: set[str] = set()
    annotation_nodes: set[ast.AST] = set()
    for info in callables.values():
        node = info.node
        annotations = [argument.annotation for argument in (
            list(node.args.posonlyargs) + list(node.args.args) +
            list(node.args.kwonlyargs)) if argument.annotation is not None]
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            annotations.append(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            annotations.append(node.args.kwarg.annotation)
        if node.returns is not None:
            annotations.append(node.returns)
        for annotation in annotations:
            annotation_nodes.update(ast.walk(annotation))
    for module in modules.values():
        for node in ast.walk(module.tree):
            if isinstance(node, ast.AnnAssign):
                annotation_nodes.update(ast.walk(node.annotation))

        parents = {child: parent for parent in ast.walk(module.tree)
                   for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                continue
            owner: str | None = None
            cursor: ast.AST = node
            while cursor in parents:
                cursor = parents[cursor]
                owner = callable_by_node.get(cursor)
                if owner is not None:
                    break
            binding = _binding_for_expr(
                node, module, facts.get(owner) if owner is not None else None)
            if binding is None or binding.kind != "internal-class":
                continue
            if node in annotation_nodes:
                continue
            parent = parents.get(node)
            grandparent = parents.get(parent) if parent is not None else None
            if isinstance(parent, ast.Call) and parent.func is node:
                continue
            if (isinstance(parent, ast.Attribute) and parent.value is node and
                    isinstance(grandparent, ast.Call) and
                    grandparent.func is parent):
                continue
            if isinstance(parent, ast.ClassDef) and node in parent.bases:
                continue
            # Class-info operands are consumed by the exact Python builtins;
            # they do not make the class object callable through another path.
            classinfo_call: ast.Call | None = None
            if isinstance(parent, ast.Call):
                classinfo_call = parent
            elif (isinstance(parent, (ast.Tuple, ast.List)) and
                  isinstance(grandparent, ast.Call)):
                classinfo_call = grandparent
            if (classinfo_call is not None and
                    isinstance(classinfo_call.func, ast.Name) and
                    classinfo_call.func.id in {"isinstance", "issubclass"} and
                    _binding_for_expr(
                        classinfo_call.func, module,
                        facts.get(owner) if owner is not None else None) is None):
                continue
            escaped.add(binding.target)
    return set(classes) - escaped


def _call_actuals(
        call: ast.Call, target: _Callable, *, skip_implicit: bool,
        ) -> dict[str, ast.expr | None]:
    positional = list(target.node.args.posonlyargs) + list(target.node.args.args)
    if skip_implicit and positional:
        positional = positional[1:]
    result: dict[str, ast.expr | None] = {argument.arg: None
                                         for argument in positional}
    result.update({argument.arg: None
                   for argument in target.node.args.kwonlyargs})
    if any(isinstance(argument, ast.Starred) for argument in call.args) or \
            any(keyword.arg is None for keyword in call.keywords):
        return result
    for argument, value in zip(positional, call.args):
        result[argument.arg] = value
    for keyword in call.keywords:
        if keyword.arg in result:
            result[keyword.arg] = keyword.value
    return result


def _callable_expr_candidates(
        expression: ast.expr, *, info: _Callable, facts: _Facts,
        module: _Module, modules: Mapping[str, _Module],
        classes: Mapping[str, _Class], descendants: Mapping[str, set[str]],
        class_attr_values: Mapping[tuple[str, str], set[str]],
        class_attr_unknown: set[tuple[str, str]],
        effective_class_id: str | None,
        call_result_classes: Mapping[ast.Call, set[str]] | None = None,
        ) -> set[str]:
    if isinstance(expression, ast.Name):
        nested = facts.nested_callables.get(expression.id)
        if nested is not None:
            return {nested}
        candidates = facts.parameter_callable_candidates.get(expression.id)
        if candidates:
            return set(candidates)
        binding = _binding_for_expr(expression, module, facts)
        if binding is not None and binding.kind == "internal-function":
            return {binding.target}
        return set()
    if isinstance(expression, (ast.IfExp, ast.BoolOp)):
        values = ([expression.body, expression.orelse]
                  if isinstance(expression, ast.IfExp) else expression.values)
        result: set[str] = set()
        for value in values:
            result.update(_callable_expr_candidates(
                value, info=info, facts=facts, module=module, modules=modules,
                classes=classes, descendants=descendants,
                class_attr_values=class_attr_values,
                class_attr_unknown=class_attr_unknown,
                effective_class_id=effective_class_id,
                call_result_classes=call_result_classes))
        return result
    if not isinstance(expression, ast.Attribute):
        return set()
    binding = _binding_for_expr(expression, module, facts)
    if binding is not None and binding.kind == "internal-module-member":
        member = _internal_module_member(binding.target, modules)
        if member is not None and member.kind == "internal-function":
            return {member.target}
    receiver_binding = _binding_for_expr(expression.value, module, facts)
    if receiver_binding is not None and receiver_binding.kind == "internal-class":
        target = _method_lookup(receiver_binding.target, expression.attr, classes)
        return {target} if target is not None else set()
    receiver_classes, _uncertain = _receiver_class_fact(
        expression.value, effective_class_id=effective_class_id,
        direct_method_class_id=info.class_id, facts=facts, module=module,
        modules=modules, classes=classes, descendants=descendants,
        values=class_attr_values, unknown=class_attr_unknown,
        call_result_classes=call_result_classes)
    return {
        target for class_id in receiver_classes
        for target in [_method_lookup(class_id, expression.attr, classes)]
        if target is not None
    }


class _ReturnVisitor(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.returns: list[ast.Return] = []
        for statement in root.body:
            self.visit(statement)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        self.returns.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return


def _sequence_definitely_returns(body: list[ast.stmt]) -> bool:
    for statement in body:
        if isinstance(statement, (ast.Return, ast.Raise)):
            return True
        if (isinstance(statement, ast.If) and statement.orelse and
                _sequence_definitely_returns(statement.body) and
                _sequence_definitely_returns(statement.orelse)):
            return True
    return False


def _return_class_summaries(
        callables: Mapping[str, _Callable], modules: Mapping[str, _Module],
        classes: Mapping[str, _Class], facts: Mapping[str, _Facts],
        ) -> dict[str, set[str]]:
    summaries: dict[str, set[str]] = {}
    for identifier, info in callables.items():
        if not _sequence_definitely_returns(info.node.body):
            continue
        visitor = _ReturnVisitor(info.node)
        if not visitor.returns:
            continue
        result: set[str] = set()
        exact = True
        module = modules[info.module]
        for statement in visitor.returns:
            if statement.value is None:
                exact = False
                break
            class_ids, _categories, alias = _rhs_evidence(
                statement.value, module, facts[identifier], classes, modules)
            if alias is not None or not class_ids:
                exact = False
                break
            result.update(class_ids)
        if exact and result:
            summaries[identifier] = result
    return summaries


def _build_call_sites(
        callables: Mapping[str, _Callable], modules: Mapping[str, _Module],
        callable_by_node: Mapping[ast.AST, str],
        classes: Mapping[str, _Class],
        ) -> tuple[list[dict[str, Any]], dict[str, _Facts]]:
    descendants = _all_descendants(classes)
    effective_classes: dict[str, str | None] = {}
    for identifier, info in callables.items():
        cursor: _Callable | None = info
        visited: set[str] = set()
        effective: str | None = None
        while cursor is not None and cursor.callable_id not in visited:
            visited.add(cursor.callable_id)
            if cursor.class_id is not None:
                effective = cursor.class_id
                break
            cursor = (callables.get(cursor.lexical_parent_id)
                      if cursor.lexical_parent_id is not None else None)
        effective_classes[identifier] = effective

    parameter_class_facts: dict[str, dict[str, set[str]]] = {}
    class_parameter_candidates: dict[str, dict[str, set[str]]] = {}
    callable_parameter_candidates: dict[str, dict[str, set[str]]] = {}
    call_result_classes: dict[ast.Call, set[str]] = {}
    resolved_entries: list[tuple[str, _Callable, _Module, _Facts,
                                 ast.Call, dict[str, Any]]] = []
    facts_and_visitors: dict[str, tuple[_Facts, _ScopeVisitor]] = {}
    for _iteration in range(len(classes) + 2):
        inherited_candidates: dict[str, dict[str, set[str]]] = {}
        for identifier, info in callables.items():
            inherited: dict[str, set[str]] = defaultdict(set)
            parent_id = info.lexical_parent_id
            visited: set[str] = set()
            while parent_id is not None and parent_id not in visited:
                visited.add(parent_id)
                for name, targets in callable_parameter_candidates.get(
                        parent_id, {}).items():
                    inherited[name].update(targets)
                parent = callables.get(parent_id)
                parent_id = (parent.lexical_parent_id
                             if parent is not None else None)
            inherited_candidates[identifier] = dict(inherited)
        facts_and_visitors = {
            identifier: _callable_facts(
                info, modules[info.module], callable_by_node, classes, modules,
                parameter_class_facts=parameter_class_facts.get(identifier),
                parameter_class_candidates=(
                    class_parameter_candidates.get(identifier)),
                parameter_callable_candidates=(
                    callable_parameter_candidates.get(identifier)),
                inherited_callable_candidates=(
                    inherited_candidates.get(identifier)),
                call_result_classes=call_result_classes)
            for identifier, info in callables.items()
        }
        (class_attr_values, class_attr_unknown,
         class_attr_provenance, class_attr_provenance_unknown) = (
            _class_attribute_facts(
                callables, modules, callable_by_node, classes,
                parameter_class_facts, class_parameter_candidates,
                call_result_classes))
        return_class_summaries = _return_class_summaries(
            callables, modules, classes,
            {identifier: pair[0]
             for identifier, pair in facts_and_visitors.items()})
        closed_classes = _closed_constructor_classes(
            modules, callables, callable_by_node, classes,
            {identifier: pair[0]
             for identifier, pair in facts_and_visitors.items()})
        resolved_entries = []
        for identifier in sorted(callables):
            info = callables[identifier]
            module = modules[info.module]
            facts, visitor = facts_and_visitors[identifier]
            for call in sorted(
                    visitor.calls,
                    key=lambda item: (item.lineno, item.col_offset,
                                      item.end_lineno or item.lineno,
                                      item.end_col_offset or 0)):
                resolution = _resolve_call(
                    call, info, module, facts, modules, classes, descendants,
                    class_attr_values, class_attr_unknown,
                    class_attr_provenance, class_attr_provenance_unknown,
                    effective_classes[identifier], closed_classes,
                    call_result_classes)
                resolved_entries.append(
                    (identifier, info, module, facts, call, resolution))

        nonconstructor_targets = {
            target
            for _identifier, _info, _module, _facts, _call, resolution
            in resolved_entries
            if resolution.get("kind") != "exact-internal-constructor"
            for target in resolution.get("targets", ())
        }
        totals: Counter[tuple[str, str]] = Counter()
        exacts: Counter[tuple[str, str]] = Counter()
        values: dict[tuple[str, str], set[str]] = defaultdict(set)
        for (identifier, info, module, facts, call,
             resolution) in resolved_entries:
            if (resolution.get("kind") != "exact-internal-constructor" or
                    resolution.get("proven") is not True or
                    resolution.get("constructed_class") not in closed_classes or
                    len(resolution.get("targets", ())) != 1):
                continue
            target_id = resolution["targets"][0]
            if (target_id not in callables or
                    target_id in nonconstructor_targets):
                continue
            target = callables[target_id]
            positional = (list(target.node.args.posonlyargs) +
                          list(target.node.args.args))
            if positional:
                key = (target_id, positional[0].arg)
                totals[key] += 1
                exacts[key] += 1
                values[key].add(str(resolution["constructed_class"]))
            for name, actual in _call_actuals(
                    call, target, skip_implicit=True).items():
                key = (target_id, name)
                totals[key] += 1
                if actual is None:
                    continue
                class_ids, uncertain = _receiver_class_fact(
                    actual, effective_class_id=effective_classes[identifier],
                    direct_method_class_id=info.class_id, facts=facts,
                    module=module, modules=modules, classes=classes,
                    descendants=descendants, values=class_attr_values,
                    unknown=class_attr_unknown,
                    call_result_classes=call_result_classes)
                if class_ids and not uncertain:
                    exacts[key] += 1
                    values[key].update(class_ids)
        next_parameter_facts: dict[str, dict[str, set[str]]] = defaultdict(dict)
        for key, total in totals.items():
            if exacts[key] == total and values[key]:
                target_id, name = key
                next_parameter_facts[target_id][name] = set(values[key])
        normalized = {identifier: dict(names)
                      for identifier, names in next_parameter_facts.items()}
        next_callable_candidates: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set))
        next_class_candidates: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set))
        for (identifier, info, module, facts, call,
             resolution) in resolved_entries:
            if resolution.get("proven") is not True:
                continue
            for target_id in resolution.get("targets", ()):
                target = callables.get(target_id)
                if target is None:
                    continue
                kind = str(resolution.get("kind"))
                static_method = any(
                    isinstance(decorator, ast.Name) and
                    decorator.id == "staticmethod"
                    for decorator in target.node.decorator_list)
                class_method = any(
                    isinstance(decorator, ast.Name) and
                    decorator.id == "classmethod"
                    for decorator in target.node.decorator_list)
                skip_implicit = (
                    kind == "exact-internal-constructor" or
                    (kind in {"exact-internal-method",
                              "exact-common-dispatch",
                              "exact-super-method"} and not static_method) or
                    (kind == "exact-internal-class-method" and class_method))
                for name, actual in _call_actuals(
                        call, target, skip_implicit=skip_implicit).items():
                    if actual is None:
                        continue
                    class_ids, _uncertain = _receiver_class_fact(
                        actual, effective_class_id=effective_classes[identifier],
                        direct_method_class_id=info.class_id, facts=facts,
                        module=module, modules=modules, classes=classes,
                        descendants=descendants, values=class_attr_values,
                        unknown=class_attr_unknown,
                        call_result_classes=call_result_classes)
                    next_class_candidates[target_id][name].update(class_ids)
                    candidates = _callable_expr_candidates(
                        actual, info=info, facts=facts, module=module,
                        modules=modules, classes=classes,
                        descendants=descendants,
                        class_attr_values=class_attr_values,
                        class_attr_unknown=class_attr_unknown,
                        effective_class_id=effective_classes[identifier],
                        call_result_classes=call_result_classes)
                    next_callable_candidates[target_id][name].update(
                        candidates)
        normalized_callable_candidates = {
            identifier: {
                name: set(targets) for name, targets in names.items()
                if targets
            }
            for identifier, names in next_callable_candidates.items()
            if any(names.values())
        }
        normalized_class_candidates = {
            identifier: {
                name: set(targets) for name, targets in names.items()
                if targets and name not in parameter_class_facts.get(
                    identifier, {})
            }
            for identifier, names in next_class_candidates.items()
            if any(
                targets and name not in parameter_class_facts.get(
                    identifier, {})
                for name, targets in names.items())
        }
        next_call_result_classes: dict[ast.Call, set[str]] = {}
        for (_identifier, _info, _module, _facts, call,
             resolution) in resolved_entries:
            if (resolution.get("proven") is True and
                    len(resolution.get("targets", ())) == 1):
                returned = return_class_summaries.get(
                    resolution["targets"][0])
                if returned:
                    next_call_result_classes[call] = set(returned)
            constructed = resolution.get("constructed_class")
            if constructed is not None:
                next_call_result_classes[call] = {str(constructed)}
        if (normalized == parameter_class_facts and
                normalized_class_candidates == class_parameter_candidates and
                normalized_callable_candidates ==
                callable_parameter_candidates and
                next_call_result_classes == call_result_classes):
            break
        parameter_class_facts = normalized
        class_parameter_candidates = normalized_class_candidates
        callable_parameter_candidates = normalized_callable_candidates
        call_result_classes = next_call_result_classes
    else:
        raise ActiveCallGraphError(
            "PZACG011", "constructor argument fact propagation did not converge")

    facts_by_callable = {
        identifier: pair[0] for identifier, pair in facts_and_visitors.items()}
    rows: list[dict[str, Any]] = []
    for identifier, _info, module, _facts, call, resolution in resolved_entries:
        identity_payload = {
            "caller": identifier,
            "line": int(call.lineno),
            "column": int(call.col_offset),
            "ast_sha256": _ast_sha256(call),
        }
        row = {
            "call_site_id": _json_sha256(identity_payload),
            **identity_payload,
            "end_line": int(call.end_lineno or call.lineno),
            "end_column": int(call.end_col_offset or call.col_offset + 1),
            "source": _source(module.source, call),
            "callee_source": _source(module.source, call.func),
            "resolution": resolution,
        }
        rows.append(row)
    return rows, facts_by_callable


def _reachable_callables(entrypoint: str, call_sites: list[dict[str, Any]],
                         known: set[str]) -> list[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for row in call_sites:
        resolution = row["resolution"]
        if resolution["proven"] is True:
            adjacency[row["caller"]].update(
                target for target in resolution["targets"] if target in known)
    reached = {entrypoint}
    pending = [entrypoint]
    while pending:
        caller = pending.pop()
        for target in adjacency.get(caller, ()):
            if target not in reached:
                reached.add(target)
                pending.append(target)
    return sorted(reached)


def _source_graph_rows(modules: Mapping[str, _Module]) -> list[dict[str, Any]]:
    return [{
        "module": module.name,
        "path": module.relative_path,
        "sha256": module.source_sha256,
        "is_package": module.is_package,
        "imports": module.import_edges,
        "function_count": sum(
            1 for node in ast.walk(module.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
        "class_count": sum(
            1 for node in ast.walk(module.tree) if isinstance(node, ast.ClassDef)),
    } for module in sorted(modules.values(), key=lambda item: item.name)]


def _compiler_hashes(project_root: Path) -> dict[str, str]:
    paths = (
        "Source/Tools/pyz80_compiler/active_call_graph.py",
        "Source/Tools/pyz80_compiler/function_cfg.py",
        "Source/Tools/pyz80_compiler/frontend.py",
        "Source/Tools/pyz80_compiler/ir.py",
        "Source/Tools/pyz80_compiler/mutation_hook_ir.py",
    )
    return {path: _sha256((project_root / path).read_bytes()) for path in paths}


def _resolution_summary(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(
        row["resolution"]["kind"] for row in rows).items()))


def _boundary_inventory(
        project_root: Path, call_sites: list[dict[str, Any]],
        reachable: set[str], modules: Mapping[str, _Module],
        module_initialization_sites: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
    categories = {
        str(row["resolution"]["boundary"])
        for row in call_sites
        if row["resolution"]["kind"] == "host-boundary"
    } | {
        str(row["resolution"]["boundary"])
        for row in module_initialization_sites
        if row["resolution"]["kind"] == "host-boundary"
    } | {"pygame", "bass", "filesystem", "ft812-transport"}
    result: list[dict[str, Any]] = []
    for category in sorted(categories):
        sites = [row["call_site_id"] for row in call_sites
                 if row["resolution"].get("boundary") == category]
        reachable_sites = [row["call_site_id"] for row in call_sites
                           if row["resolution"].get("boundary") == category and
                           row["caller"] in reachable]
        initialization_sites = [
            row["call_site_id"] for row in module_initialization_sites
            if row["resolution"].get("boundary") == category]
        row: dict[str, Any] = {
            "boundary": category,
            "status": ("ACTIVE_HOST_BOUNDARY_UNBOUND"
                       if sites else "NO_ACTIVE_CALL_SITE"),
            "call_site_count": len(sites),
            "reachable_call_site_count": len(reachable_sites),
            "call_site_ids": sites,
            "reachable_call_site_ids": reachable_sites,
            "module_initialization_call_site_count": len(
                initialization_sites),
            "module_initialization_call_site_ids": initialization_sites,
            "total_inventoried_call_site_count": (
                len(sites) + len(initialization_sites)),
        }
        if category == "ft812-transport":
            hardware = project_root / "Source" / "Python" / "rtype_port" / "hardware.py"
            hardware_module_active = "rtype_port.hardware" in modules
            row.update({
                "status": ("ACTIVE_HOST_BOUNDARY_UNBOUND"
                           if hardware_module_active else
                           "ABSENT_FROM_ACTIVE_MODULE_GRAPH"),
                "inactive_source": ({
                    "path": _norm(hardware.relative_to(project_root)),
                    "sha256": _sha256(hardware.read_bytes()),
                } if hardware.is_file() else None),
                "hardware_module_in_active_import_closure": hardware_module_active,
                "target_transport_provider_bound": False,
            })
        result.append(row)
    return result


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    for key in ("semantic_sha256", "status", "live", "live_blockers"):
        payload.pop(key, None)
    return payload


def analyze_active_call_graph(
        project_root: Path | str, *,
        hook_plan: MutationHookPlan | None = None,
        object_store_module: Any | None = None,
        ) -> dict[str, Any]:
    """Build a source-only inventory rooted at the literal active launcher."""
    root = Path(project_root).resolve()
    launcher, entry_module = _launcher_entry(root)
    modules = _build_module_graph(root, entry_module)
    (callables, classes, callable_by_node,
     _class_by_node) = _collect_definitions(modules)
    _populate_bindings(modules, callables, classes)
    _resolve_class_bases(modules, classes)
    _populate_module_value_facts(modules, classes)

    hooks = hook_plan or build_mutation_hook_ir(root)
    stores = object_store_module or lower_active_object_store_ir(
        root, hook_plan=hooks)
    mutation_binding = _attach_object_store_fragments(
        root, modules, callables, callable_by_node, hooks, stores)

    callable_rows, cfg_census = _lower_all_callables(callables, modules)
    call_sites, _facts = _build_call_sites(
        callables, modules, callable_by_node, classes)
    del _facts
    module_initialization = _module_initialization_inventory(
        modules, classes)
    app_module = modules.get(entry_module)
    if app_module is None or "main" not in app_module.top_functions:
        raise ActiveCallGraphError(
            "PZACG010", f"{entry_module}.main is absent")
    entrypoint = app_module.top_functions["main"]
    known_ids = set(callables)
    reachable_list = _reachable_callables(entrypoint, call_sites, known_ids)
    reachable = set(reachable_list)
    unreachable = sorted(known_ids - reachable)

    exact_edges = sorted({
        (row["caller"], target, row["call_site_id"])
        for row in call_sites
        if row["resolution"]["proven"] is True
        for target in row["resolution"]["targets"]
        if target in known_ids
    })
    dynamic_sites = [row for row in call_sites
                     if row["resolution"]["kind"] ==
                     "finite-dynamic-dispatch"]
    unresolved_sites = [row for row in call_sites
                        if row["resolution"]["kind"].startswith("unresolved-")]
    reachable_dynamic = [row for row in dynamic_sites
                         if row["caller"] in reachable]
    reachable_unresolved = [row for row in unresolved_sites
                            if row["caller"] in reachable]
    reachable_boundaries = [row for row in call_sites
                            if row["caller"] in reachable and
                            row["resolution"]["kind"] == "host-boundary"]

    source_rows = _source_graph_rows(modules)
    source_graph = {
        "module_count": len(source_rows),
        "modules": source_rows,
        "module_names": [row["module"] for row in source_rows],
        "internal_import_edge_count": sum(
            edge["kind"] == "internal" for row in source_rows
            for edge in row["imports"]),
        "external_import_edge_count": sum(
            edge["kind"] == "external" for row in source_rows
            for edge in row["imports"]),
    }
    source_graph["semantic_sha256"] = _json_sha256(source_graph)

    callable_by_id = {row["callable_id"]: row for row in callable_rows}
    reachable_cfg_blockers = [
        blocker
        for identifier in reachable_list
        if callable_by_id[identifier]["cfg"] is not None
        for blocker in callable_by_id[identifier]["cfg"]["blockers"]
    ]
    reachable_lowering_failures = [
        callable_by_id[identifier]["lowering_failure"]
        for identifier in reachable_list
        if callable_by_id[identifier]["cfg"] is None
    ]
    call_graph = {
        "entrypoint": entrypoint,
        "call_site_count": len(call_sites),
        "call_sites": call_sites,
        "resolution_kind_counts": _resolution_summary(call_sites),
        "exact_internal_edge_count": len(exact_edges),
        "exact_internal_edges": [
            {"caller": caller, "callee": callee, "call_site_id": site}
            for caller, callee, site in exact_edges
        ],
        "finite_dynamic_dispatch_site_count": len(dynamic_sites),
        "finite_dynamic_dispatch_site_ids": [
            row["call_site_id"] for row in dynamic_sites],
        "unresolved_call_site_count": len(unresolved_sites),
        "unresolved_call_site_ids": [
            row["call_site_id"] for row in unresolved_sites],
        "proven_reachable_callable_count": len(reachable_list),
        "proven_reachable_callable_ids": reachable_list,
        "not_proven_reachable_callable_count": len(unreachable),
        "not_proven_reachable_callable_ids": unreachable,
        "reachable_resolution_kind_counts": _resolution_summary(
            row for row in call_sites if row["caller"] in reachable),
        "reachable_finite_dynamic_dispatch_site_count": len(reachable_dynamic),
        "reachable_finite_dynamic_dispatch_site_ids": [
            row["call_site_id"] for row in reachable_dynamic],
        "reachable_unresolved_call_site_count": len(reachable_unresolved),
        "reachable_unresolved_call_site_ids": [
            row["call_site_id"] for row in reachable_unresolved],
        "reachable_host_boundary_call_site_count": len(reachable_boundaries),
        "reachable_host_boundary_call_site_ids": [
            row["call_site_id"] for row in reachable_boundaries],
        "reachable_cfg_blocker_count": len(reachable_cfg_blockers),
        "reachable_cfg_blocker_code_counts": dict(sorted(Counter(
            row["code"] for row in reachable_cfg_blockers).items())),
        "reachable_cfg_lowering_failure_count": len(
            reachable_lowering_failures),
        "reachable_cfg_lowering_failures": reachable_lowering_failures,
        "reachability_uses_only_proven_edges": True,
        "module_import_does_not_imply_callable_reachability": True,
        "dynamic_candidates_are_not_promoted_to_proven_reachable": True,
    }
    call_graph["semantic_sha256"] = _json_sha256(call_graph)

    boundaries = _boundary_inventory(
        root, call_sites, reachable, modules,
        module_initialization["call_sites"])
    live_blockers: list[dict[str, Any]] = []
    if reachable_dynamic:
        live_blockers.append({
            "code": "PZACG201",
            "count": len(reachable_dynamic),
            "detail": "reachable finite dynamic dispatch requires exact "
            "runtime receiver selection",
        })
    if reachable_unresolved:
        live_blockers.append({
            "code": "PZACG202",
            "count": len(reachable_unresolved),
            "detail": "reachable calls have no source-proven callable identity",
        })
    if reachable_cfg_blockers or reachable_lowering_failures:
        live_blockers.append({
            "code": "PZACG203",
            "count": len(reachable_cfg_blockers) + len(
                reachable_lowering_failures),
            "detail": "reachable callable CFG lowering is incomplete",
        })
    if reachable_boundaries:
        live_blockers.append({
            "code": "PZACG204",
            "count": len(reachable_boundaries),
            "detail": "reachable host calls require explicit target adapters",
        })
    live_blockers.extend([
        {
            "code": "PZACG205", "count": 1,
            "detail": "FT812 transport is absent from the active Python "
            "import graph and has no bound target provider",
        },
        {
            "code": "PZACG206", "count": 1,
            "detail": "the C/Z80 backend does not consume this whole-program "
            "callable CFG inventory",
        },
        {
            "code": "PZACG207",
            "count": int(module_initialization["call_site_count"]),
            "detail": "module/class initialization calls are inventoried "
            "but do not yet have function CFG lowering",
        },
    ])

    report: dict[str, Any] = {
        "format": ACTIVE_CALL_GRAPH_FORMAT,
        "launcher": launcher,
        "entrypoint": {
            "module": entry_module,
            "function": "main",
            "callable_id": entrypoint,
        },
        "source_graph": source_graph,
        "class_inventory": {
            "class_count": len(classes),
            "classes": [{
                "class_id": identifier,
                "module": info.module,
                "qualname": info.qualname,
                "definition_line": int(info.node.lineno),
                "ast_sha256": _ast_sha256(info.node),
                "methods": dict(sorted(info.methods.items())),
                "internal_bases": list(info.base_class_ids),
                "external_bases": list(info.external_bases),
                "builtin_bases": list(info.builtin_bases),
                "has_custom_metaclass": info.has_custom_metaclass,
                "generated_dataclass_init": _generated_dataclass_init_schema(
                    identifier, classes, modules),
            } for identifier, info in sorted(classes.items())],
        },
        "callable_inventory": {
            **cfg_census,
            "callables": callable_rows,
        },
        "object_store_binding": mutation_binding,
        "call_graph": call_graph,
        "module_initialization": module_initialization,
        "boundaries": boundaries,
        "proof": {
            "launcher_literal_module_bound": True,
            "source_import_graph_sha_bound": True,
            "all_function_defs_in_active_modules_inventoried": True,
            "all_functions_not_claimed_reachable_by_import": (
                len(reachable_list) < len(callables)),
            "only_source_evidenced_exact_edges_drive_reachability": True,
            "annotations_do_not_create_exact_receiver_types": True,
            "closed_constructor_argument_flow_requires_non_escaping_class_object": True,
            "candidate_parameter_flow_never_proves_edges": True,
            "uncertain_receiver_candidates_never_prove_edges": True,
            "closed_classmethod_and_builtin_super_proofs_are_structurally_validated": True,
            "unresolved_dynamic_dispatch_is_fail_closed": True,
            "host_boundaries_are_not_lowered_as_python": True,
            "module_initialization_calls_inventoried": True,
            "module_initialization_cfg_lowered": False,
            "ft812_transport_provider_bound": False,
            "current_backend_consumes_inventory": False,
        },
        "compiler_input_sha256": _compiler_hashes(root),
    }
    report["semantic_sha256"] = _json_sha256(_semantic_payload(report))
    report["status"] = ACTIVE_CALL_GRAPH_STATUS
    report["live"] = False
    report["live_blockers"] = live_blockers
    validate_active_call_graph_report(root, report)
    return report


def validate_active_call_graph_report(
        project_root: Path | str, report: Mapping[str, Any]) -> None:
    root = Path(project_root).resolve()
    if report.get("format") != ACTIVE_CALL_GRAPH_FORMAT:
        raise ActiveCallGraphError("PZACG401", "format mismatch")
    if (report.get("status") != ACTIVE_CALL_GRAPH_STATUS or
            report.get("live") is not False):
        raise ActiveCallGraphError("PZACG402", "status/live claim mismatch")
    if _json_sha256(_semantic_payload(report)) != report.get("semantic_sha256"):
        raise ActiveCallGraphError("PZACG403", "semantic hash mismatch")
    launcher = report.get("launcher")
    if not isinstance(launcher, dict):
        raise ActiveCallGraphError("PZACG404", "launcher is malformed")
    launcher_path = root / str(launcher.get("path", ""))
    if (not launcher_path.is_file() or
            _sha256(launcher_path.read_bytes()) != launcher.get("sha256") or
            launcher.get("module") != "rtype_port.app"):
        raise ActiveCallGraphError("PZACG404", "launcher binding is stale")

    source_graph = report.get("source_graph")
    if not isinstance(source_graph, dict):
        raise ActiveCallGraphError("PZACG405", "source graph is malformed")
    source_payload = dict(source_graph)
    source_semantic = source_payload.pop("semantic_sha256", None)
    if _json_sha256(source_payload) != source_semantic:
        raise ActiveCallGraphError("PZACG405", "source graph hash mismatch")
    modules = source_graph.get("modules")
    if (not isinstance(modules, list) or
            source_graph.get("module_count") != len(modules) or
            len({row.get("module") for row in modules
                 if isinstance(row, dict)}) != len(modules)):
        raise ActiveCallGraphError("PZACG406", "module inventory mismatch")
    for row in modules:
        if not isinstance(row, dict):
            raise ActiveCallGraphError("PZACG406", "module row malformed")
        path = root / str(row.get("path", ""))
        if not path.is_file() or _sha256(path.read_bytes()) != row.get("sha256"):
            raise ActiveCallGraphError(
                "PZACG407", f"module source stale: {row.get('module')}")

    inventory = report.get("callable_inventory")
    if not isinstance(inventory, dict):
        raise ActiveCallGraphError("PZACG408", "callable inventory malformed")
    callables = inventory.get("callables")
    if (not isinstance(callables, list) or
            inventory.get("callable_count") != len(callables)):
        raise ActiveCallGraphError("PZACG408", "callable count mismatch")
    callable_ids: set[str] = set()
    cfg_rows = 0
    blocker_free = 0
    blocked = 0
    total_blocks = 0
    total_exception_edges = 0
    total_instructions = 0
    total_programs = 0
    total_program_blocks = 0
    total_program_instructions = 0
    total_splices = 0
    blocker_codes: Counter[str] = Counter()
    blocker_kinds: Counter[str] = Counter()
    lowering_failures: list[dict[str, Any]] = []
    for row in callables:
        if not isinstance(row, dict):
            raise ActiveCallGraphError("PZACG409", "callable row malformed")
        identifier = row.get("callable_id")
        semantic = row.get("semantic_sha256")
        if (not isinstance(identifier, str) or identifier in callable_ids or
                not isinstance(semantic, str)):
            raise ActiveCallGraphError("PZACG409", "callable identity malformed")
        callable_ids.add(identifier)
        payload = dict(row)
        payload.pop("semantic_sha256", None)
        if _json_sha256(payload) != semantic:
            raise ActiveCallGraphError(
                "PZACG410", f"callable semantic mismatch: {identifier}")
        cfg = row.get("cfg")
        if cfg is None:
            failure = row.get("lowering_failure")
            if not isinstance(failure, dict):
                raise ActiveCallGraphError(
                    "PZACG411", "missing lowering failure")
            lowering_failures.append(failure)
            continue
        if not isinstance(cfg, dict):
            raise ActiveCallGraphError("PZACG411", "CFG row malformed")
        cfg_rows += 1
        if cfg.get("blockers"):
            blocked += 1
        else:
            blocker_free += 1
        blocker_codes.update(item["code"] for item in cfg.get("blockers", ()))
        blocker_kinds.update(item["node_kind"]
                             for item in cfg.get("blockers", ()))
        blocks = cfg.get("blocks")
        programs = cfg.get("expression_programs")
        if not isinstance(blocks, list) or not isinstance(programs, list):
            raise ActiveCallGraphError("PZACG411", "CFG lists malformed")
        total_blocks += len(blocks)
        total_exception_edges += sum(
            isinstance(block, dict) and "exception_target" in block
            for block in blocks)
        total_instructions += sum(len(block["instructions"])
                                  for block in blocks)
        total_splices += sum(
            instruction["op"] == "execute-object-store-fragment"
            for block in blocks for instruction in block["instructions"])
        total_programs += len(programs)
        total_program_blocks += sum(len(program["blocks"])
                                    for program in programs)
        total_program_instructions += sum(
            len(block["instructions"])
            for program in programs for block in program["blocks"])
    expected_cfg_counts = {
        "cfg_lowered_callable_count": cfg_rows,
        "cfg_blocker_free_callable_count": blocker_free,
        "cfg_blocked_callable_count": blocked,
        "cfg_block_count": total_blocks,
        "cfg_exception_edge_count": total_exception_edges,
        "cfg_instruction_count": total_instructions,
        "cfg_expression_program_count": total_programs,
        "cfg_expression_block_count": total_program_blocks,
        "cfg_expression_instruction_count": total_program_instructions,
        "cfg_object_store_splice_instruction_count": total_splices,
        "cfg_lowering_failure_count": len(lowering_failures),
        "unsupported_lowering_blocker_count": sum(blocker_codes.values()),
        "unsupported_lowering_code_counts": dict(sorted(blocker_codes.items())),
        "unsupported_lowering_ast_kind_counts": dict(sorted(
            blocker_kinds.items())),
        "lowering_failures": lowering_failures,
    }
    if any(inventory.get(key) != value
           for key, value in expected_cfg_counts.items()):
        raise ActiveCallGraphError("PZACG412", "CFG census mismatch")

    graph = report.get("call_graph")
    if not isinstance(graph, dict):
        raise ActiveCallGraphError("PZACG413", "call graph malformed")
    graph_payload = dict(graph)
    graph_semantic = graph_payload.pop("semantic_sha256", None)
    if _json_sha256(graph_payload) != graph_semantic:
        raise ActiveCallGraphError("PZACG413", "call graph hash mismatch")
    call_sites = graph.get("call_sites")
    if (not isinstance(call_sites, list) or
            graph.get("call_site_count") != len(call_sites) or
            len({row.get("call_site_id") for row in call_sites
                 if isinstance(row, dict)}) != len(call_sites)):
        raise ActiveCallGraphError("PZACG414", "call-site inventory mismatch")
    callable_class_ids = {
        str(row["callable_id"]): row.get("class_id")
        for row in callables if isinstance(row, dict)
    }
    class_inventory = report.get("class_inventory")
    class_rows = (class_inventory.get("classes")
                  if isinstance(class_inventory, dict) else None)
    if not isinstance(class_rows, list):
        raise ActiveCallGraphError("PZACG414", "class inventory malformed")
    classes_by_id = {
        row.get("class_id"): row for row in class_rows
        if isinstance(row, dict) and isinstance(row.get("class_id"), str)
    }
    if len(classes_by_id) != len(class_rows):
        raise ActiveCallGraphError("PZACG414", "class identity malformed")

    def has_report_descendant(class_id: str) -> bool:
        return any(class_id in candidate.get("internal_bases", ())
                   for candidate in classes_by_id.values())

    def validate_source_proof(row: Mapping[str, Any],
                              resolution: Mapping[str, Any]) -> None:
        proof = resolution.get("source_proof")
        if proof is None:
            return
        if not isinstance(proof, dict):
            raise ActiveCallGraphError(
                "PZACG414", "call source proof malformed")
        proof_kind = proof.get("kind")
        class_id = proof.get("class_id")
        class_row = classes_by_id.get(class_id)
        if (class_row is None or
                callable_class_ids.get(str(row.get("caller"))) != class_id or
                has_report_descendant(str(class_id))):
            raise ActiveCallGraphError(
                "PZACG414", "call source proof class/MRO mismatch")
        if proof_kind == "closed-classmethod-cls-constructor":
            if set(proof) != {"kind", "class_id", "parameter"}:
                raise ActiveCallGraphError(
                    "PZACG414", "classmethod source proof shape mismatch")
            parameter = proof.get("parameter")
            if (not isinstance(parameter, str) or
                    row.get("callee_source") != parameter or
                    resolution.get("constructed_class") != class_id or
                    resolution.get("kind") != "exact-internal-constructor" or
                    resolution.get("proven") is not True):
                raise ActiveCallGraphError(
                    "PZACG414", "classmethod source proof claim mismatch")
            return
        if proof_kind == "closed-single-builtin-super-mro":
            if set(proof) != {
                    "kind", "class_id", "direct_builtin_base", "method"}:
                raise ActiveCallGraphError(
                    "PZACG414", "super source proof shape mismatch")
            base_name = proof.get("direct_builtin_base")
            method = proof.get("method")
            base = (getattr(builtins, base_name, None)
                    if isinstance(base_name, str) else None)
            if (class_row.get("internal_bases") != [] or
                    class_row.get("external_bases") != [] or
                    class_row.get("builtin_bases") != [base_name] or
                    not isinstance(method, str) or base is None or
                    not hasattr(base, method) or
                    row.get("callee_source") != f"super().{method}" or
                    resolution.get("kind") != "host-boundary" or
                    resolution.get("proven") is not False or
                    resolution.get("targets") != [] or
                    resolution.get("boundary") != "python-runtime" or
                    resolution.get("external_target") !=
                    f"builtins.{base_name}.{method}"):
                raise ActiveCallGraphError(
                    "PZACG414", "super source proof claim mismatch")
            return
        raise ActiveCallGraphError("PZACG414", "unknown call source proof")

    for row in call_sites:
        if not isinstance(row, dict) or row.get("caller") not in callable_ids:
            raise ActiveCallGraphError("PZACG414", "call-site caller malformed")
        identity = {
            "caller": row.get("caller"),
            "line": row.get("line"),
            "column": row.get("column"),
            "ast_sha256": row.get("ast_sha256"),
        }
        if _json_sha256(identity) != row.get("call_site_id"):
            raise ActiveCallGraphError("PZACG414", "call-site identity mismatch")
        resolution = row.get("resolution")
        if (not isinstance(resolution, dict) or
                not isinstance(resolution.get("kind"), str) or
                not isinstance(resolution.get("proven"), bool) or
                not isinstance(resolution.get("targets"), list) or
                any(target not in callable_ids
                    for target in resolution.get("targets", []))):
            raise ActiveCallGraphError("PZACG414", "call resolution malformed")
        validate_source_proof(row, resolution)
        kind = resolution["kind"]
        if kind == "exact-generated-dataclass-init":
            caller_class_id = callable_class_ids.get(str(row.get("caller")))
            caller_class = classes_by_id.get(caller_class_id)
            internal_bases = (caller_class.get("internal_bases", ())
                              if caller_class is not None else ())
            base = (classes_by_id.get(internal_bases[0])
                    if len(internal_bases) == 1 else None)
            schema = resolution.get("generated_dataclass_init")
            parameters = (schema.get("parameters")
                          if isinstance(schema, dict) else None)
            post_init = (schema.get("post_init_target")
                         if isinstance(schema, dict) else None)
            expected_targets = ([post_init]
                                if isinstance(post_init, str) else [])
            schema_payload = (dict(schema)
                              if isinstance(schema, dict) else {})
            schema_hash = schema_payload.pop("semantic_sha256", None)
            if (row.get("callee_source") != "super().__init__" or
                    caller_class is None or base is None or
                    base.get("generated_dataclass_init") != schema or
                    not isinstance(resolution.get("receiver_parameter"), str) or
                    not isinstance(parameters, list) or not parameters or
                    parameters[0].get("name") != "self" or
                    resolution.get("targets") != expected_targets or
                    _json_sha256(schema_payload) != schema_hash):
                raise ActiveCallGraphError(
                    "PZACG414", "generated dataclass init proof mismatch")
        if ((kind.startswith("exact-") and
             resolution["proven"] is not True) or
                (resolution["proven"] is True and
                 not kind.startswith("exact-"))):
            raise ActiveCallGraphError(
                "PZACG414", "exact/proven resolution contract mismatch")
        if ((kind.startswith("unresolved-") or kind == "host-boundary") and
                (resolution["proven"] is not False or
                 resolution["targets"] != [])):
            raise ActiveCallGraphError(
                "PZACG414", "unresolved/boundary call was promoted")
        if kind == "finite-dynamic-dispatch" and (
                resolution["proven"] is not False or
                not resolution["targets"]):
            raise ActiveCallGraphError(
                "PZACG414", "finite dispatch claim malformed")
    entrypoint = report.get("entrypoint", {}).get("callable_id")
    if entrypoint not in callable_ids or graph.get("entrypoint") != entrypoint:
        raise ActiveCallGraphError("PZACG415", "entrypoint mismatch")
    recomputed_reachable = _reachable_callables(
        str(entrypoint), call_sites, callable_ids)
    if (graph.get("proven_reachable_callable_ids") != recomputed_reachable or
            graph.get("proven_reachable_callable_count") !=
            len(recomputed_reachable) or
            graph.get("not_proven_reachable_callable_ids") !=
            sorted(callable_ids - set(recomputed_reachable))):
        raise ActiveCallGraphError("PZACG416", "reachability mismatch")
    if graph.get("resolution_kind_counts") != _resolution_summary(call_sites):
        raise ActiveCallGraphError("PZACG417", "resolution census mismatch")
    reachable_set = set(recomputed_reachable)
    finite = [row for row in call_sites
              if row["resolution"]["kind"] == "finite-dynamic-dispatch"]
    unresolved = [row for row in call_sites
                  if row["resolution"]["kind"].startswith("unresolved-")]
    reachable_finite = [row for row in finite
                        if row["caller"] in reachable_set]
    reachable_unresolved = [row for row in unresolved
                            if row["caller"] in reachable_set]
    reachable_boundaries = [row for row in call_sites
                            if row["caller"] in reachable_set and
                            row["resolution"]["kind"] == "host-boundary"]
    exact_edges = sorted({
        (row["caller"], target, row["call_site_id"])
        for row in call_sites if row["resolution"]["proven"] is True
        for target in row["resolution"]["targets"]
        if target in callable_ids
    })
    expected_edge_rows = [
        {"caller": caller, "callee": callee, "call_site_id": site}
        for caller, callee, site in exact_edges
    ]
    expected_graph_derived = {
        "exact_internal_edge_count": len(exact_edges),
        "exact_internal_edges": expected_edge_rows,
        "finite_dynamic_dispatch_site_count": len(finite),
        "finite_dynamic_dispatch_site_ids": [
            row["call_site_id"] for row in finite],
        "unresolved_call_site_count": len(unresolved),
        "unresolved_call_site_ids": [
            row["call_site_id"] for row in unresolved],
        "not_proven_reachable_callable_count": len(
            callable_ids - reachable_set),
        "reachable_resolution_kind_counts": _resolution_summary(
            row for row in call_sites if row["caller"] in reachable_set),
        "reachable_finite_dynamic_dispatch_site_count": len(
            reachable_finite),
        "reachable_finite_dynamic_dispatch_site_ids": [
            row["call_site_id"] for row in reachable_finite],
        "reachable_unresolved_call_site_count": len(reachable_unresolved),
        "reachable_unresolved_call_site_ids": [
            row["call_site_id"] for row in reachable_unresolved],
        "reachable_host_boundary_call_site_count": len(
            reachable_boundaries),
        "reachable_host_boundary_call_site_ids": [
            row["call_site_id"] for row in reachable_boundaries],
    }
    if any(graph.get(key) != value
           for key, value in expected_graph_derived.items()):
        raise ActiveCallGraphError("PZACG417", "derived call graph mismatch")
    rows_by_id = {row["callable_id"]: row for row in callables}
    reachable_cfg_blockers = [
        blocker
        for identifier in recomputed_reachable
        if rows_by_id[identifier]["cfg"] is not None
        for blocker in rows_by_id[identifier]["cfg"]["blockers"]
    ]
    reachable_failures = [
        rows_by_id[identifier]["lowering_failure"]
        for identifier in recomputed_reachable
        if rows_by_id[identifier]["cfg"] is None
    ]
    if (graph.get("reachable_cfg_blocker_count") !=
            len(reachable_cfg_blockers) or
            graph.get("reachable_cfg_blocker_code_counts") != dict(sorted(
                Counter(item["code"] for item in
                        reachable_cfg_blockers).items())) or
            graph.get("reachable_cfg_lowering_failure_count") !=
            len(reachable_failures) or
            graph.get("reachable_cfg_lowering_failures") != reachable_failures):
        raise ActiveCallGraphError("PZACG417", "reachable CFG census mismatch")

    module_initialization = report.get("module_initialization")
    if not isinstance(module_initialization, dict):
        raise ActiveCallGraphError(
            "PZACG423", "module initialization inventory malformed")
    initialization_payload = dict(module_initialization)
    initialization_semantic = initialization_payload.pop(
        "semantic_sha256", None)
    if _json_sha256(initialization_payload) != initialization_semantic:
        raise ActiveCallGraphError(
            "PZACG423", "module initialization semantic mismatch")
    initialization_sites = module_initialization.get("call_sites")
    if (not isinstance(initialization_sites, list) or
            module_initialization.get("call_site_count") !=
            len(initialization_sites) or
            module_initialization.get("explicit_call_site_count") != sum(
                row.get("operation_kind") == "explicit-call"
                for row in initialization_sites) or
            module_initialization.get("decorator_application_count") != sum(
                row.get("operation_kind") == "decorator-application"
                for row in initialization_sites) or
            module_initialization.get("resolution_kind_counts") !=
            _resolution_summary(initialization_sites) or
            len({row.get("call_site_id") for row in initialization_sites
                 if isinstance(row, dict)}) != len(initialization_sites)):
        raise ActiveCallGraphError(
            "PZACG423", "module initialization census mismatch")
    module_names = {row["module"] for row in modules}
    for row in initialization_sites:
        if (not isinstance(row, dict) or row.get("module") not in module_names or
                _json_sha256({
                    "module": row.get("module"),
                    "line": row.get("line"),
                    "column": row.get("column"),
                    "ast_sha256": row.get("ast_sha256"),
                    "operation_kind": row.get("operation_kind"),
                }) != row.get("call_site_id")):
            raise ActiveCallGraphError(
                "PZACG423", "module initialization call identity mismatch")

    binding = report.get("object_store_binding")
    if (not isinstance(binding, dict) or
            binding.get("runtime_site_count") != binding.get("fragment_count") or
            binding.get("fragment_count") !=
            binding.get("attached_fragment_count") or
            binding.get("all_fragments_attached_exactly_once") is not True or
            total_splices != binding.get("fragment_count")):
        raise ActiveCallGraphError("PZACG418", "object-store binding mismatch")
    proof = report.get("proof")
    if (not isinstance(proof, dict) or
            proof.get("all_functions_not_claimed_reachable_by_import") is not True or
            proof.get("only_source_evidenced_exact_edges_drive_reachability")
            is not True or
            proof.get("annotations_do_not_create_exact_receiver_types") is not True or
            proof.get(
                "closed_constructor_argument_flow_requires_non_escaping_class_object")
            is not True or
            proof.get("candidate_parameter_flow_never_proves_edges") is not True or
            proof.get("uncertain_receiver_candidates_never_prove_edges") is not True or
            proof.get(
                "closed_classmethod_and_builtin_super_proofs_are_structurally_validated")
            is not True or
            proof.get("module_initialization_calls_inventoried") is not True or
            proof.get("module_initialization_cfg_lowered") is not False or
            proof.get("ft812_transport_provider_bound") is not False or
            proof.get("current_backend_consumes_inventory") is not False):
        raise ActiveCallGraphError("PZACG419", "proof boundary mismatch")
    if report.get("compiler_input_sha256") != _compiler_hashes(root):
        raise ActiveCallGraphError("PZACG420", "compiler inputs are stale")
    boundaries = report.get("boundaries")
    if (not isinstance(boundaries, list) or
            not {"pygame", "bass", "filesystem", "ft812-transport"}.issubset({
                row.get("boundary") for row in boundaries
                if isinstance(row, dict)})):
        raise ActiveCallGraphError("PZACG421", "required boundaries absent")
    for boundary in boundaries:
        if not isinstance(boundary, dict):
            raise ActiveCallGraphError("PZACG421", "boundary row malformed")
        category = boundary.get("boundary")
        expected_sites = [row["call_site_id"] for row in call_sites
                          if row["resolution"].get("boundary") == category]
        expected_reachable_sites = [
            row["call_site_id"] for row in call_sites
            if row["resolution"].get("boundary") == category and
            row["caller"] in reachable_set]
        expected_initialization_sites = [
            row["call_site_id"] for row in initialization_sites
            if row["resolution"].get("boundary") == category]
        if (boundary.get("call_site_ids") != expected_sites or
                boundary.get("reachable_call_site_ids") !=
                expected_reachable_sites or
                boundary.get("call_site_count") != len(expected_sites) or
                boundary.get("reachable_call_site_count") !=
                len(expected_reachable_sites) or
                boundary.get("module_initialization_call_site_ids") !=
                expected_initialization_sites or
                boundary.get("module_initialization_call_site_count") !=
                len(expected_initialization_sites) or
                boundary.get("total_inventoried_call_site_count") !=
                len(expected_sites) + len(expected_initialization_sites)):
            raise ActiveCallGraphError(
                "PZACG421", f"boundary census mismatch: {category}")
    ft = next(row for row in boundaries
              if row.get("boundary") == "ft812-transport")
    if (ft.get("hardware_module_in_active_import_closure") is not False or
            ft.get("target_transport_provider_bound") is not False):
        raise ActiveCallGraphError("PZACG421", "FT boundary claim mismatch")
    blockers = report.get("live_blockers")
    if (not isinstance(blockers, list) or
            not {"PZACG205", "PZACG206"}.issubset({
                row.get("code") for row in blockers if isinstance(row, dict)})):
        raise ActiveCallGraphError("PZACG422", "live blockers malformed")
    blocker_counts = {row["code"]: row.get("count") for row in blockers}
    expected_blocker_counts = {
        **({"PZACG201": len(reachable_finite)}
           if reachable_finite else {}),
        **({"PZACG202": len(reachable_unresolved)}
           if reachable_unresolved else {}),
        **({"PZACG203": (len(reachable_cfg_blockers) +
                          len(reachable_failures))}
           if reachable_cfg_blockers or reachable_failures else {}),
        **({"PZACG204": len(reachable_boundaries)}
           if reachable_boundaries else {}),
        "PZACG205": 1,
        "PZACG206": 1,
        "PZACG207": len(initialization_sites),
    }
    if blocker_counts != expected_blocker_counts:
        raise ActiveCallGraphError("PZACG422", "live blocker census mismatch")


def write_active_call_graph_report(
        project_root: Path | str, output_path: Path | str,
        ) -> dict[str, Any]:
    report = analyze_active_call_graph(project_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    os.replace(temporary, path)
    return report
