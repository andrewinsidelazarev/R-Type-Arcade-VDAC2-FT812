"""Source-derived inventory of active Python -> TS-Config adapter obligations.

This stage deliberately consumes the already materialized whole-program active
call graph.  It does not change reachability, lower a call, or claim that a
provider exists because a Python annotation names a compatible type.  Every
provider family is backed by a real C/ASM/tool symbol and a current file hash;
calls whose exact semantics or ABI do not match remain fail-closed.
"""

from __future__ import annotations

import ast
import builtins
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .active_call_graph import (
    ACTIVE_CALL_GRAPH_FORMAT,
    ActiveCallGraphError,
    validate_active_call_graph_report,
)


ACTIVE_TARGET_ADAPTERS_FORMAT = "pyz80.active-target-adapters.v1"
ACTIVE_TARGET_ADAPTERS_STATUS = (
    "ACTIVE_TARGET_ADAPTERS_INVENTORIED_LIVE_BACKEND_BLOCKED")

__all__ = [
    "ACTIVE_TARGET_ADAPTERS_FORMAT",
    "ACTIVE_TARGET_ADAPTERS_STATUS",
    "ActiveTargetAdaptersError",
    "analyze_active_target_adapters",
    "validate_active_target_adapters_report",
]


class ActiveTargetAdaptersError(ValueError):
    """A fail-closed adapter inventory or validation error."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))


def _ast_sha256(node: ast.AST) -> str:
    return _sha256(ast.dump(
        node, annotate_fields=True, include_attributes=False).encode("utf-8"))


def _norm(path: Path) -> str:
    return path.as_posix()


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    for key in ("semantic_sha256", "status", "live", "live_blockers"):
        payload.pop(key, None)
    return payload


@dataclass(frozen=True)
class _ModuleSource:
    module: str
    relative_path: str
    path: Path
    data: bytes
    text: str
    tree: ast.Module
    calls: Mapping[tuple[int, int, str], ast.Call]
    definitions: Mapping[tuple[int, str], ast.FunctionDef | ast.AsyncFunctionDef]
    classes: Mapping[tuple[int, str], ast.ClassDef]
    module_bound_names: frozenset[str]
    imports: Mapping[str, str]
    globals: Mapping[str, frozenset[str]]


def _walk_exclusive(root: ast.AST) -> Iterable[ast.AST]:
    """Walk one scope without entering nested callable/class scopes."""
    stack = [root]
    first = True
    while stack:
        node = stack.pop()
        if not first and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef,
                       ast.Lambda, ast.ClassDef)):
            continue
        first = False
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in target.elts)) \
            if target.elts else set()
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _module_bindings(tree: ast.Module, module_name: str,
                     is_package: bool) -> tuple[
        frozenset[str], dict[str, str], dict[str, frozenset[str]]]:
    bound: set[str] = set()
    imports: dict[str, str] = {}
    global_types: defaultdict[str, set[str]] = defaultdict(set)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                bound.add(name)
                imports[name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            imported_module = node.module or ""
            if node.level:
                package = (module_name.split(".") if is_package else
                           module_name.split(".")[:-1])
                remove = node.level - 1
                if remove > len(package):
                    resolved_module = imported_module
                else:
                    base = package[:len(package) - remove]
                    resolved_module = ".".join(
                        base + (imported_module.split(".")
                                if imported_module else []))
            else:
                resolved_module = imported_module
            for alias in node.names:
                if alias.name == "*":
                    continue
                name = alias.asname or alias.name
                bound.add(name)
                imports[name] = (f"{resolved_module}.{alias.name}"
                                 if resolved_module else alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets: list[ast.expr]
            value: ast.expr | None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            else:
                targets, value = [node.target], node.value
            names = set().union(*(_target_names(item) for item in targets))
            bound.update(names)
            kind = _literal_kind(value)
            if kind is not None:
                for name in names:
                    global_types[name].add(kind)
    return (frozenset(bound), imports,
            {key: frozenset(value) for key, value in global_types.items()})


def _literal_kind(node: ast.expr | None) -> str | None:
    if isinstance(node, (ast.List, ast.ListComp)):
        return "container:list"
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return "container:dict"
    if isinstance(node, (ast.Set, ast.SetComp)):
        return "container:set"
    if isinstance(node, (ast.Tuple, ast.GeneratorExp)):
        return "container:tuple"
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return "builtin:str"
        if isinstance(node.value, bytes):
            return "builtin:bytes"
        if isinstance(node.value, bool):
            return "builtin:bool"
        if isinstance(node.value, int):
            return "builtin:int"
        if node.value is None:
            return "builtin:none"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        containers = {
            "list": "container:list", "dict": "container:dict",
            "set": "container:set", "tuple": "container:tuple",
            "bytearray": "container:bytearray", "deque": "container:deque",
            "defaultdict": "container:defaultdict",
        }
        return containers.get(node.func.id)
    return None


def _load_modules(root: Path, graph: Mapping[str, Any]) -> dict[str, _ModuleSource]:
    result: dict[str, _ModuleSource] = {}
    for row in graph["source_graph"]["modules"]:
        module = str(row["module"])
        relative = str(row["path"])
        path = root / Path(relative)
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
            tree = ast.parse(text, filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ActiveTargetAdaptersError(
                "PZATA101", f"cannot parse active source {relative}: {exc}") from exc
        if _sha256(data) != row.get("sha256"):
            raise ActiveTargetAdaptersError(
                "PZATA102", f"active source hash changed: {relative}")
        calls: dict[tuple[int, int, str], ast.Call] = {}
        definitions: dict[
            tuple[int, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}
        classes: dict[tuple[int, str], ast.ClassDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                calls[(node.lineno, node.col_offset, _ast_sha256(node))] = node
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions[(node.lineno, node.name)] = node
            elif isinstance(node, ast.ClassDef):
                classes[(node.lineno, node.name)] = node
        bound, imports, globals_ = _module_bindings(
            tree, module, bool(row.get("is_package")))
        result[module] = _ModuleSource(
            module=module, relative_path=relative, path=path, data=data,
            text=text, tree=tree, calls=calls, definitions=definitions,
            classes=classes, module_bound_names=bound, imports=imports,
            globals=globals_)
    return result


def _signature(node: ast.Call | None, operation_kind: str) -> dict[str, Any]:
    if operation_kind == "decorator-application":
        return {
            "implicit_argument_count": 1,
            "positional_count": 0,
            "starred_count": 0,
            "keyword_names": [],
            "kwargs_expansion_count": 0,
            "evaluation_order": "decorator then decorated class/function object",
        }
    if node is None:
        return {
            "implicit_argument_count": 0,
            "positional_count": None,
            "starred_count": None,
            "keyword_names": None,
            "kwargs_expansion_count": None,
            "evaluation_order": "unavailable-fail-closed",
        }
    return {
        "implicit_argument_count": 0,
        "positional_count": sum(not isinstance(item, ast.Starred)
                                for item in node.args),
        "starred_count": sum(isinstance(item, ast.Starred)
                             for item in node.args),
        "keyword_names": [item.arg for item in node.keywords
                          if item.arg is not None],
        "kwargs_expansion_count": sum(item.arg is None
                                      for item in node.keywords),
        "evaluation_order": (
            "callable, positional/starred, keyword/** in AST order"),
    }


def _callable_node(row: Mapping[str, Any],
                   modules: Mapping[str, _ModuleSource]) -> (
                       ast.FunctionDef | ast.AsyncFunctionDef):
    module = modules[str(row["module"])]
    name = str(row["qualname"]).split(".")[-1]
    node = module.definitions.get((int(row["definition_line"]), name))
    if node is None:
        raise ActiveTargetAdaptersError(
            "PZATA103", f"callable AST missing: {row['callable_id']}")
    return node


def _local_bound_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {arg.arg for arg in (list(node.args.posonlyargs) +
             list(node.args.args) + list(node.args.kwonlyargs))}
    if node.args.vararg:
        names.add(node.args.vararg.arg)
    if node.args.kwarg:
        names.add(node.args.kwarg.arg)
    for item in _walk_exclusive(node):
        if isinstance(item, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = (list(item.targets) if isinstance(item, ast.Assign)
                       else [item.target])
            names.update(set().union(*(_target_names(t) for t in targets)))
        elif isinstance(item, (ast.For, ast.AsyncFor)):
            names.update(_target_names(item.target))
        elif isinstance(item, (ast.With, ast.AsyncWith)):
            for with_item in item.items:
                if with_item.optional_vars:
                    names.update(_target_names(with_item.optional_vars))
        elif isinstance(item, ast.ExceptHandler) and item.name:
            names.add(item.name)
    return names


class _Resolver:
    """Conservative receiver/callable facts from executable source only."""

    _EXACT_BUILTINS = frozenset({
        "AssertionError", "EOFError", "FileNotFoundError", "RuntimeError",
        "SystemExit", "ValueError", "abs", "all", "any", "bool",
        "bytearray", "bytes", "dict", "divmod", "enumerate", "frozenset",
        "getattr", "hasattr", "int", "isinstance", "len", "list", "max",
        "min", "next", "ord", "range", "reversed", "round", "set",
        "sorted", "str", "sum", "super", "tuple",
    })

    def __init__(self, graph: Mapping[str, Any],
                 modules: Mapping[str, _ModuleSource]) -> None:
        self.graph = graph
        self.modules = modules
        callable_rows = graph["callable_inventory"]["callables"]
        self.callables = {str(row["callable_id"]): row
                          for row in callable_rows}
        self.callable_nodes = {
            key: _callable_node(row, modules)
            for key, row in self.callables.items()
        }
        self.local_names = {
            key: _local_bound_names(node)
            for key, node in self.callable_nodes.items()
        }
        self.classes = {str(row["class_id"]): row
                        for row in graph["class_inventory"]["classes"]}
        self.classes_by_module_name: dict[tuple[str, str], str] = {}
        self.functions_by_module_name: dict[tuple[str, str], str] = {}
        for identifier, row in self.classes.items():
            self.classes_by_module_name[(str(row["module"]),
                                         str(row["qualname"]).split(".")[-1])] = identifier
        for identifier, row in self.callables.items():
            if row.get("class_id") is None and ".<locals>." not in str(row["qualname"]):
                self.functions_by_module_name[(str(row["module"]),
                                               str(row["qualname"]))] = identifier
        self._parameter_candidates: dict[
            tuple[str, str], frozenset[str]] = {}
        self._parameter_facts: dict[tuple[str, str], str] = {}
        (self._class_attr_candidates,
         self._class_attrs,
         deferred_parameters) = self._build_class_attributes()
        self._apply_constructor_parameter_facts(deferred_parameters)

    def _binding(self, module: str, name: str) -> str | None:
        direct_class = self.classes_by_module_name.get((module, name))
        if direct_class:
            return f"class:{direct_class}"
        direct_function = self.functions_by_module_name.get((module, name))
        if direct_function:
            return f"callable:{direct_function}"
        imported = self.modules[module].imports.get(name)
        if imported:
            parts = imported.rsplit(".", 1)
            if len(parts) == 2:
                other_module, member = parts
                class_id = self.classes_by_module_name.get((other_module, member))
                if class_id:
                    return f"class:{class_id}"
                callable_id = self.functions_by_module_name.get(
                    (other_module, member))
                if callable_id:
                    return f"callable:{callable_id}"
            return f"external:{imported}"
        global_kinds = self.modules[module].globals.get(name, frozenset())
        if len(global_kinds) == 1:
            return next(iter(global_kinds))
        return None

    def _simple_rhs(self, module: str, node: ast.expr | None) -> str | None:
        literal = _literal_kind(node)
        if literal is not None:
            return literal
        if isinstance(node, ast.Name):
            return self._binding(module, node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            binding = self._binding(module, node.func.id)
            if binding and binding.startswith("class:"):
                return binding
        return None

    def _simple_rhs_candidates(self, module: str,
                               node: ast.expr | None) -> set[str] | None:
        if isinstance(node, ast.IfExp):
            body = self._simple_rhs_candidates(module, node.body)
            other = self._simple_rhs_candidates(module, node.orelse)
            if body is None or other is None:
                return None
            return body | other
        simple = self._simple_rhs(module, node)
        return {simple} if simple is not None else None

    def _build_class_attributes(self) -> tuple[
            dict[tuple[str, str], frozenset[str]],
            dict[tuple[str, str], str],
            list[tuple[str, str, str, str]]]:
        candidates: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        unknown: set[tuple[str, str]] = set()
        deferred_parameters: list[tuple[str, str, str, str]] = []
        for callable_id, row in self.callables.items():
            class_id = row.get("class_id")
            if class_id is None:
                continue
            node = self.callable_nodes[callable_id]
            module = str(row["module"])
            for item in _walk_exclusive(node):
                if isinstance(item, ast.Assign):
                    pairs = [(target, item.value) for target in item.targets]
                elif isinstance(item, ast.AnnAssign):
                    pairs = [(item.target, item.value)]
                elif isinstance(item, ast.NamedExpr):
                    pairs = [(item.target, item.value)]
                else:
                    continue
                for target, value in pairs:
                    if (isinstance(target, ast.Attribute) and
                            isinstance(target.value, ast.Name) and
                            target.value.id == "self"):
                        key = (str(class_id), target.attr)
                        if (str(row["qualname"]).endswith(".__init__") and
                                isinstance(value, ast.Name) and
                                value.id in {arg.arg for arg in
                                             (list(node.args.posonlyargs) +
                                              list(node.args.args) +
                                              list(node.args.kwonlyargs))} and
                                value.id != "self"):
                            deferred_parameters.append(
                                (str(class_id), target.attr, value.id, "direct"))
                            continue
                        if (str(row["qualname"]).endswith(".__init__") and
                                isinstance(value, ast.BoolOp) and
                                isinstance(value.op, ast.Or) and
                                len(value.values) == 2 and
                                isinstance(value.values[0], ast.Name) and
                                value.values[0].id in {arg.arg for arg in
                                    (list(node.args.posonlyargs) +
                                     list(node.args.args) +
                                     list(node.args.kwonlyargs))} and
                                value.values[0].id != "self" and
                                isinstance(value.values[1], ast.Lambda)):
                            deferred_parameters.append((
                                str(class_id), target.attr, value.values[0].id,
                                "truthy-callable-or-lambda"))
                            continue
                        kinds = self._simple_rhs_candidates(module, value)
                        if kinds is None:
                            unknown.add(key)
                        else:
                            candidates[key].update(kinds)
        frozen = {key: frozenset(values)
                  for key, values in candidates.items() if key not in unknown}
        exact = {
            key: next(iter(values))
            for key, values in frozen.items()
            if len(values) == 1 and key not in unknown
        }
        return frozen, exact, deferred_parameters

    def _expr_candidates(self, callable_id: str, expr: ast.expr,
                         before_line: int) -> set[str] | None:
        row = self.callables[callable_id]
        module = str(row["module"])
        class_id = row.get("class_id")
        if isinstance(expr, ast.Name):
            if expr.id == "self" and class_id:
                return {f"class:{class_id}"}
            parameter = self._parameter_candidates.get(
                (callable_id, expr.id), frozenset())
            if parameter:
                return set(parameter)
            local = self._local_facts(callable_id, before_line).get(expr.id)
            if local:
                return {local}
            binding = self._binding(module, expr.id)
            return {binding} if binding else None
        literal = _literal_kind(expr)
        if literal:
            return {literal}
        if (isinstance(expr, ast.Attribute) and
                isinstance(expr.value, ast.Name) and expr.value.id == "self" and
                class_id):
            return set(self._class_attr_candidates.get(
                (str(class_id), expr.attr), frozenset())) or None
        if isinstance(expr, ast.Attribute):
            owners = self._expr_candidates(callable_id, expr.value, before_line)
            if not owners:
                return None
            values: set[str] = set()
            for owner in owners:
                if not owner.startswith("class:"):
                    return None
                available = self._class_attr_candidates.get(
                    (owner[6:], expr.attr), frozenset())
                if available:
                    values.update(available)
                    continue
                methods = self._lookup_method(owner[6:], expr.attr)
                if len(methods) != 1:
                    return None
                values.add(f"callable:{methods[0]}")
            return values or None
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
            binding = self._binding(module, expr.func.id)
            if binding and binding.startswith("class:"):
                return {binding}
        return None

    @staticmethod
    def _bind_call_arguments(
            node: ast.Call,
            target: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> dict[str, ast.expr] | None:
        parameters = list(target.args.posonlyargs) + list(target.args.args)
        if parameters and parameters[0].arg in {"self", "cls"}:
            parameters = parameters[1:]
        if any(isinstance(item, ast.Starred) for item in node.args) or any(
                item.arg is None for item in node.keywords):
            return None
        if len(node.args) > len(parameters):
            return None
        result = {parameter.arg: value for parameter, value in
                  zip(parameters, node.args)}
        valid = {parameter.arg for parameter in parameters} | {
            argument.arg for argument in target.args.kwonlyargs}
        for keyword in node.keywords:
            assert keyword.arg is not None
            if keyword.arg not in valid or keyword.arg in result:
                return None
            result[keyword.arg] = keyword.value
        return result

    def _apply_constructor_parameter_facts(
            self, deferred: Sequence[tuple[str, str, str, str]]) -> None:
        reachable = set(self.graph["call_graph"]["proven_reachable_callable_ids"])
        constructor_sites: list[tuple[
            str, str, ast.FunctionDef | ast.AsyncFunctionDef, ast.Call]] = []
        for row in self.graph["call_graph"]["call_sites"]:
            resolution = row["resolution"]
            if row["caller"] not in reachable:
                continue
            caller_id = str(row["caller"])
            caller_module = self.modules[str(
                self.callables[caller_id]["module"])]
            call = caller_module.calls.get((
                int(row["line"]), int(row["column"]), str(row["ast_sha256"])))
            class_id: str | None = None
            target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
            if (resolution["kind"] == "exact-internal-constructor" and
                    len(resolution.get("targets", [])) == 1):
                raw_class = resolution.get("constructed_class")
                if isinstance(raw_class, str):
                    class_id = raw_class
                    target = self.callable_nodes.get(str(resolution["targets"][0]))
            elif (str(resolution["kind"]).startswith("unresolved-") and
                  call is not None and isinstance(call.func, ast.Name)):
                binding = self._binding(
                    str(self.callables[caller_id]["module"]), call.func.id)
                if binding and binding.startswith("class:"):
                    class_id = binding[6:]
                    methods = self._lookup_method(class_id, "__init__")
                    if len(methods) == 1:
                        target = self.callable_nodes.get(methods[0])
            elif (len(resolution.get("targets", [])) == 1 and
                  str(self.callables.get(
                      str(resolution["targets"][0]), {}).get(
                          "qualname", "")).endswith(".__init__")):
                target_id = str(resolution["targets"][0])
                class_id = str(self.callables[target_id].get("class_id"))
                target = self.callable_nodes.get(target_id)
            if class_id is None:
                continue
            if target is None or call is None:
                continue
            target_id = next((
                identifier for identifier, node in self.callable_nodes.items()
                if node is target), None)
            if target_id is not None:
                constructor_sites.append((caller_id, target_id, target, call))

        # A small fixpoint is enough for constructor chains such as
        # World -> Parent(world=self) -> Child(world=world).  Facts are kept
        # only when every active source-bound construction supplies a value
        # with a finite executable-source identity; annotations never enter.
        for _iteration in range(len(constructor_sites) + 2):
            candidates: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
            unknown: set[tuple[str, str]] = set()
            incoming: Counter[str] = Counter()
            for caller_id, target_id, target, call in constructor_sites:
                incoming[target_id] += 1
                bound = self._bind_call_arguments(call, target)
                parameters = [
                    argument.arg for argument in
                    (list(target.args.posonlyargs) + list(target.args.args) +
                     list(target.args.kwonlyargs))
                    if argument.arg not in {"self", "cls"}
                ]
                for parameter in parameters:
                    key = (target_id, parameter)
                    if bound is None or parameter not in bound:
                        unknown.add(key)
                        continue
                    kinds = self._expr_candidates(
                        caller_id, bound[parameter], int(call.lineno))
                    if kinds is None:
                        unknown.add(key)
                    else:
                        candidates[key].update(kinds)
            next_candidates = {
                key: frozenset(values)
                for key, values in candidates.items()
                if incoming[key[0]] and key not in unknown and values
            }
            next_facts = {
                key: next(iter(values))
                for key, values in next_candidates.items()
                if len(values) == 1
            }
            changed = (next_candidates != self._parameter_candidates or
                       next_facts != self._parameter_facts)
            self._parameter_candidates = next_candidates
            self._parameter_facts = next_facts

            for class_id, attribute, parameter, mode in deferred:
                methods = self._lookup_method(class_id, "__init__")
                if len(methods) != 1:
                    continue
                values = self._parameter_candidates.get(
                    (methods[0], parameter), frozenset())
                if not values or (mode == "truthy-callable-or-lambda" and
                                  not all(value.startswith("callable:")
                                          for value in values)):
                    continue
                attr_key = (class_id, attribute)
                if self._class_attr_candidates.get(attr_key) != values:
                    self._class_attr_candidates[attr_key] = values
                    changed = True
                if len(values) == 1:
                    value = next(iter(values))
                    if self._class_attrs.get(attr_key) != value:
                        self._class_attrs[attr_key] = value
                        changed = True
            if not changed:
                break

    @staticmethod
    def _test_proves_non_none(test: ast.expr, attribute: str) -> bool:
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            return any(_Resolver._test_proves_non_none(item, attribute)
                       for item in test.values)
        if (not isinstance(test, ast.Compare) or len(test.ops) != 1 or
                len(test.comparators) != 1 or
                not isinstance(test.ops[0], ast.IsNot)):
            return False
        left, right = test.left, test.comparators[0]
        return (isinstance(left, ast.Attribute) and
                isinstance(left.value, ast.Name) and
                left.value.id == "self" and left.attr == attribute and
                isinstance(right, ast.Constant) and right.value is None)

    def _guard_narrows_class(self, callable_id: str, attribute: str,
                             line: int) -> str | None:
        node = self.callable_nodes[callable_id]
        for item in _walk_exclusive(node):
            if not isinstance(item, ast.If) or not item.body:
                continue
            first = min(getattr(child, "lineno", line + 1) for child in item.body)
            last = max(getattr(child, "end_lineno", getattr(child, "lineno", 0))
                       for child in item.body)
            if (first <= line <= last and
                    self._test_proves_non_none(item.test, attribute)):
                row = self.callables[callable_id]
                values = self._class_attr_candidates.get(
                    (str(row.get("class_id")), attribute), frozenset())
                non_none = {value for value in values if value != "builtin:none"}
                if len(non_none) == 1 and "builtin:none" in values:
                    result = next(iter(non_none))
                    return result if result.startswith("class:") else None
        return None

    def _local_facts(self, callable_id: str, before_line: int) -> dict[str, str]:
        row = self.callables[callable_id]
        node = self.callable_nodes[callable_id]
        module = str(row["module"])
        candidates: defaultdict[str, set[str]] = defaultdict(set)
        unknown: set[str] = set()
        parameters = {arg.arg for arg in (list(node.args.posonlyargs) +
                      list(node.args.args) + list(node.args.kwonlyargs))}
        if node.args.vararg:
            parameters.add(node.args.vararg.arg)
        if node.args.kwarg:
            parameters.add(node.args.kwarg.arg)
        unknown.update(parameters)
        for item in _walk_exclusive(node):
            if getattr(item, "lineno", before_line) >= before_line:
                continue
            if isinstance(item, ast.Assign):
                pairs = [(target, item.value) for target in item.targets]
            elif isinstance(item, ast.AnnAssign):
                pairs = [(item.target, item.value)]
            elif isinstance(item, ast.NamedExpr):
                pairs = [(item.target, item.value)]
            else:
                continue
            for target, value in pairs:
                kind = self._simple_rhs(module, value)
                for name in _target_names(target):
                    if kind is None:
                        unknown.add(name)
                    else:
                        candidates[name].add(kind)
        return {
            name: next(iter(values))
            for name, values in candidates.items()
            if len(values) == 1 and name not in unknown
        }

    def _lookup_method(self, class_id: str, name: str,
                       seen: set[str] | None = None) -> list[str]:
        seen = set() if seen is None else seen
        if class_id in seen or class_id not in self.classes:
            return []
        seen.add(class_id)
        row = self.classes[class_id]
        method = row.get("methods", {}).get(name)
        if method:
            return [str(method)]
        answers: list[str] = []
        for base in row.get("internal_bases", []):
            answers.extend(self._lookup_method(str(base), name, seen))
        return sorted(set(answers))

    def _class_is_dataclass(self, class_id: str) -> bool:
        row = self.classes[class_id]
        module = self.modules[str(row["module"])]
        name = str(row["qualname"]).split(".")[-1]
        node = module.classes.get((int(row["definition_line"]), name))
        if node is None:
            return False
        for decorator in node.decorator_list:
            function = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(function, ast.Name) and function.id == "dataclass":
                imported = module.imports.get("dataclass")
                return imported == "dataclasses.dataclass"
            if (isinstance(function, ast.Attribute) and
                    isinstance(function.value, ast.Name) and
                    function.value.id == "dataclasses" and
                    function.attr == "dataclass"):
                return module.imports.get("dataclasses") == "dataclasses"
        return False

    def _expr_kind(self, callable_id: str, expr: ast.expr,
                   before_line: int, depth: int = 0) -> str | None:
        if depth > 4:
            return None
        row = self.callables[callable_id]
        module = str(row["module"])
        class_id = row.get("class_id")
        if isinstance(expr, ast.Name):
            if expr.id == "self" and class_id:
                return f"class:{class_id}"
            parameter = self._parameter_facts.get((callable_id, expr.id))
            if parameter:
                return parameter
            local = self._local_facts(callable_id, before_line).get(expr.id)
            if local:
                return local
            return self._binding(module, expr.id)
        literal = _literal_kind(expr)
        if literal:
            return literal
        if isinstance(expr, ast.Attribute):
            if (isinstance(expr.value, ast.Name) and expr.value.id == "self" and
                    class_id):
                narrowed = self._guard_narrows_class(
                    callable_id, expr.attr, before_line)
                if narrowed:
                    return narrowed
            owner = self._expr_kind(callable_id, expr.value, before_line,
                                    depth + 1)
            if owner and owner.startswith("class:"):
                return self._class_attrs.get((owner[6:], expr.attr))
        if isinstance(expr, ast.Call):
            resolved = self._resolve_func(callable_id, expr.func,
                                          before_line, depth + 1)
            if resolved and resolved["semantic_kind"] == "internal-constructor":
                return f"class:{resolved['target_id']}"
        return None

    def _resolve_func(self, callable_id: str, func: ast.expr,
                      before_line: int, depth: int = 0) -> dict[str, Any] | None:
        if depth > 4:
            return None
        row = self.callables[callable_id]
        module = str(row["module"])
        class_id = row.get("class_id")
        if isinstance(func, ast.Name):
            local = self._local_facts(callable_id, before_line)
            if func.id in local and local[func.id].startswith("callable:"):
                target = local[func.id][9:]
                return {"semantic_kind": "internal-callable", "target_id": target,
                        "semantic": target, "evidence": "local executable RHS"}
            binding = self._binding(module, func.id)
            if binding and binding.startswith("callable:"):
                target = binding[9:]
                return {"semantic_kind": "internal-callable", "target_id": target,
                        "semantic": target, "evidence": "module/import symbol table"}
            if binding and binding.startswith("class:"):
                target = binding[6:]
                methods = self._lookup_method(target, "__init__")
                return {
                    "semantic_kind": "internal-constructor",
                    "target_id": target,
                    "semantic": (methods[0] if len(methods) == 1 else
                                 f"dataclasses.generated.__init__:{target}"),
                    "evidence": "module/import class symbol table",
                }
            if (func.id in self._EXACT_BUILTINS and
                    func.id not in self.local_names[callable_id] and
                    func.id not in self.modules[module].module_bound_names and
                    hasattr(builtins, func.id)):
                return {
                    "semantic_kind": "python-builtin",
                    "target_id": f"builtins.{func.id}",
                    "semantic": f"builtins.{func.id}",
                    "evidence": "lexical absence plus Python builtin binding",
                }
            return None
        if not isinstance(func, ast.Attribute):
            return None
        if (func.attr == "__init__" and isinstance(func.value, ast.Call) and
                isinstance(func.value.func, ast.Name) and
                func.value.func.id == "super" and class_id):
            bases = [str(item) for item in
                     self.classes[str(class_id)].get("internal_bases", [])]
            if len(bases) == 1:
                methods = self._lookup_method(bases[0], "__init__")
                if len(methods) == 1:
                    return {
                        "semantic_kind": "internal-callable",
                        "target_id": methods[0], "semantic": methods[0],
                        "evidence": "single source base and base method table",
                    }
                if not methods and self._class_is_dataclass(bases[0]):
                    return {
                        "semantic_kind": "internal-constructor",
                        "target_id": bases[0],
                        "semantic": f"dataclasses.generated.__init__:{bases[0]}",
                        "evidence": (
                            "single source base and executable @dataclass decorator"),
                    }
            return None
        exact_attribute = self._expr_kind(
            callable_id, func, before_line, depth + 1)
        if exact_attribute and exact_attribute.startswith("callable:"):
            target = exact_attribute[9:]
            return {
                "semantic_kind": "internal-callable",
                "target_id": target, "semantic": target,
                "evidence": (
                    "constructor argument flow to callable instance attribute"),
            }
        owner = self._expr_kind(callable_id, func.value, before_line, depth + 1)
        if owner is None:
            return None
        if owner.startswith("class:"):
            methods = self._lookup_method(owner[6:], func.attr)
            if len(methods) == 1:
                uses_parameter_fact = any(
                    isinstance(item, ast.Name) and
                    (callable_id, item.id) in self._parameter_facts
                    for item in ast.walk(func.value))
                return {
                    "semantic_kind": "internal-callable",
                    "target_id": methods[0], "semantic": methods[0],
                    "evidence": (
                        "active constructor-argument flow plus executable "
                        "receiver/class-attribute assignments"
                        if uses_parameter_fact else
                        "executable receiver construction/assignment"),
                }
        if owner.startswith("container:"):
            container = owner.split(":", 1)[1]
            return {
                "semantic_kind": "python-container-protocol",
                "target_id": f"python.{container}.{func.attr}",
                "semantic": f"python.{container}.{func.attr}",
                "evidence": "literal/container-constructor executable RHS",
            }
        if owner.startswith("builtin:"):
            kind = owner.split(":", 1)[1]
            return {
                "semantic_kind": "python-builtin-method",
                "target_id": f"python.{kind}.{func.attr}",
                "semantic": f"python.{kind}.{func.attr}",
                "evidence": "literal executable RHS",
            }
        return None

    def resolve(self, row: Mapping[str, Any], node: ast.Call | None
                ) -> dict[str, Any] | None:
        if "caller" not in row:
            module = str(row["module"])
            if (row.get("operation_kind") == "decorator-application" and
                    str(row.get("source", "")).startswith("@dataclass(") and
                    self.modules[module].imports.get("dataclass") ==
                    "dataclasses.dataclass"):
                return {
                    "semantic_kind": "host-library-generated-callable",
                    "target_id": "dataclasses.dataclass.decorator-application",
                    "semantic": "dataclasses.dataclass.decorator-application",
                    "boundary": "python-runtime",
                    "evidence": (
                        "executable imported dataclass decorator factory and "
                        "synthetic decorator-application operation"),
                }
            if node is None:
                return None
            if isinstance(node.func, ast.Name):
                name = node.func.id
                binding = self._binding(module, name)
                if binding and binding.startswith("callable:"):
                    target = binding[9:]
                    return {
                        "semantic_kind": "internal-callable",
                        "target_id": target, "semantic": target,
                        "evidence": "module initialization symbol table",
                    }
                if binding and binding.startswith("class:"):
                    target = binding[6:]
                    return {
                        "semantic_kind": "internal-constructor",
                        "target_id": target,
                        "semantic": f"class-constructor:{target}",
                        "evidence": "module initialization class symbol table",
                    }
                if (name in self._EXACT_BUILTINS and
                        name not in self.modules[module].module_bound_names and
                        hasattr(builtins, name)):
                    return {
                        "semantic_kind": "python-builtin",
                        "target_id": f"builtins.{name}",
                        "semantic": f"builtins.{name}",
                        "evidence": (
                            "module lexical absence plus Python builtin binding"),
                    }
            if (isinstance(node.func, ast.Attribute) and
                    isinstance(node.func.value, ast.Call) and
                    isinstance(node.func.value.func, ast.Name)):
                constructor = self._binding(module, node.func.value.func.id)
                if constructor == "external:pathlib.Path":
                    target = f"pathlib.Path.{node.func.attr}"
                    return {
                        "semantic_kind": "host-library-method",
                        "target_id": target, "semantic": target,
                        "boundary": "filesystem",
                        "evidence": (
                            "module import plus direct pathlib.Path construction"),
                    }
            return None
        if node is None:
            return None
        callable_id = str(row["caller"])
        if callable_id not in self.callables:
            return None
        return self._resolve_func(callable_id, node.func, int(row["line"]))


def _symbol_evidence(root: Path, relative: str, symbol: str,
                     kind: str) -> dict[str, Any]:
    path = root / Path(relative)
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ActiveTargetAdaptersError(
            "PZATA110", f"provider source unavailable {relative}: {exc}") from exc
    patterns = {
        "asm-label": rf"(?m)^{re.escape(symbol)}\s*:",
        "c-function": rf"(?m)^\s*[A-Za-z_][^;\n]*\b{re.escape(symbol)}\s*\(",
        "python-function": rf"(?m)^def\s+{re.escape(symbol)}\s*\(",
        "python-method": rf"(?m)^\s+def\s+{re.escape(symbol)}\s*\(",
    }
    pattern = patterns.get(kind)
    match = re.search(pattern, text) if pattern else None
    if match is None:
        raise ActiveTargetAdaptersError(
            "PZATA111", f"provider symbol {symbol} absent from {relative}")
    line = text.count("\n", 0, match.start()) + 1
    source_line = text.splitlines()[line - 1].strip()
    return {
        "kind": kind,
        "symbol": symbol,
        "path": relative,
        "line": line,
        "source": source_line,
        "source_span_sha256": _sha256(source_line.encode("utf-8")),
        "file_sha256": _sha256(data),
    }


def _manifest_evidence(root: Path, relative: str, pointer: str,
                       expected: object) -> dict[str, Any]:
    path = root / Path(relative)
    try:
        data = path.read_bytes()
        value: Any = json.loads(data.decode("utf-8"))
        for component in pointer.strip("/").split("/"):
            value = value[int(component)] if isinstance(value, list) else value[component]
    except (OSError, UnicodeError, ValueError, KeyError, IndexError,
            TypeError) as exc:
        raise ActiveTargetAdaptersError(
            "PZATA112", f"manifest evidence unavailable {relative}{pointer}: {exc}") from exc
    if value != expected:
        raise ActiveTargetAdaptersError(
            "PZATA113", f"manifest claim changed {relative}{pointer}: {value!r}")
    return {
        "kind": "manifest-claim", "symbol": pointer, "path": relative,
        "value": value, "value_sha256": _json_sha256(value),
        "file_sha256": _sha256(data),
    }


def _provider_catalog(root: Path) -> dict[str, Any]:
    specs: list[tuple[str, str, str, str]] = [
        ("ft812-video-draw", "Source/ASM/platform.asm", "Platform_Init", "asm-label"),
        ("ft812-video-draw", "Source/ASM/render.asm", "Render_Frame", "asm-label"),
        ("ft812-video-draw", "Source/ASM/render.asm", "Render_SubmitFrame", "asm-label"),
        ("ft812-video-draw", "Source/ASM/render.asm", "Render_WaitPreviousSwap", "asm-label"),
        ("ft812-video-draw", "Source/C/ft812/pyz80_ft812.c", "PyZ80FT_QueuePushDescriptor", "c-function"),
        ("ft812-video-draw", "Source/C/ft812/pyz80_ft812.c", "PyZ80FT_BuildSpriteBatchFast", "c-function"),
        ("tsconf-input-mouse", "Source/ASM/input.asm", "Input_Poll", "asm-label"),
        ("tsconf-input-mouse", "Source/ASM/input.asm", "Input_MouseX", "asm-label"),
        ("tsconf-input-mouse", "Source/ASM/input.asm", "Input_MouseY", "asm-label"),
        ("tsconf-input-mouse", "Source/ASM/input.asm", "Input_Fire", "asm-label"),
        ("tsconf-input-mouse", "Source/ASM/input.asm", "Input_Release", "asm-label"),
        ("frame-timing-55hz", "Source/Tools/pyz80_compiler/frame_timing_provider.py",
         "analyze_frame_timing_provider", "python-function"),
        ("frame-timing-55hz", "Source/Tools/pyz80_compiler/frame_timing_provider.py",
         "render_frame_timing_include", "python-function"),
        ("frame-timing-55hz", "Source/ASM/platform.asm",
         "RTypeFrameTiming_ApplyGenerated", "asm-label"),
        ("tsfm-music", "Source/ASM/tsfm_music.asm", "TsfmMusic_Start", "asm-label"),
        ("tsfm-music", "Source/ASM/tsfm_music.asm", "TsfmMusic_Update", "asm-label"),
        ("tsfm-music", "Source/ASM/tsfm_music.asm", "TsfmMusic_Stop", "asm-label"),
        ("tsfm-music", "Source/ASM/tsfm_music.asm", "TsfmMusic_Write", "asm-label"),
        ("gs-sfx", "Source/ASM/general_sound.asm", "GeneralSound_Init", "asm-label"),
        ("gs-sfx", "Source/ASM/general_sound.asm", "GeneralSound_Update", "asm-label"),
        ("gs-sfx", "Source/ASM/general_sound.asm", "GeneralSound_PlayHandle", "asm-label"),
        ("gs-sfx", "Source/ASM/general_sound.asm", "GeneralSound_SendCommand", "asm-label"),
        ("asset-level-loader-4mb", "Source/ASM/main.asm", "RTypeStage_LoadAndSelect", "asm-label"),
        ("asset-level-loader-4mb", "Source/ASM/main.asm", "RTypeStage_LoadPack", "asm-label"),
        ("asset-level-loader-4mb", "Source/ASM/main.asm", "Loader_OpenFile", "asm-label"),
        ("asset-level-loader-4mb", "Source/ASM/main.asm", "Loader_ReadSectors", "asm-label"),
        ("c-z80-intrinsics", "Source/Tools/pyz80_compiler/frontend.py", "lower_expression", "python-method"),
        ("c-z80-intrinsics", "Source/Tools/pyz80_compiler/c_backend.py", "_instruction_lines", "python-function"),
    ]
    evidence: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for family, relative, symbol, kind in specs:
        evidence[family].append(_symbol_evidence(root, relative, symbol, kind))
    evidence["asset-level-loader-4mb"].extend([
        _manifest_evidence(root, "Source/Tools/rtype_memory_layout.json",
                           "/physical_page_size", 16384),
        _manifest_evidence(root, "Source/Tools/rtype_memory_layout.json",
                           "/physical_page_count", 256),
    ])
    timing_candidates = [
        _symbol_evidence(root, "Source/ASM/platform.asm", "INT_Handler", "asm-label"),
        _symbol_evidence(root, "Source/ASM/render.asm", "Render_WaitPreviousSwap", "asm-label"),
        _manifest_evidence(root, "Source/Tools/rtype_python_compiler.json",
                           "/target/ft812/mode", "VM_1024_768_59Hz"),
    ]
    requirements = {
        "ft812-video-draw": "pygame video/draw effects via FT812, preserving Python Z order",
        "tsconf-input-mouse": "pygame input with mouse as coordinate/button hardware state",
        "frame-timing-55hz": "one logical Python game/audio tick at exactly 55 Hz",
        "tsfm-music": "music commands and one stream tick through TSFM",
        "gs-sfx": "SFX commands through General Sound",
        "asset-level-loader-4mb": "asset/level loading in 256x16KiB TS RAM with level transitions",
        "c-z80-intrinsics": "pure Python builtin/math/collection semantics in C/Z80",
    }
    families: list[dict[str, Any]] = []
    for family in requirements:
        row: dict[str, Any] = {
            "family_id": family,
            "requirement": requirements[family],
            "provider_evidence": evidence.get(family, []),
        }
        if family == "frame-timing-55hz":
            row.update({
                "status": "SOURCE_DERIVED_55HZ_PROVIDER_UNMEASURED_UNLINKED",
                "incompatible_candidate_evidence": timing_candidates,
                "reason": (
                    "the exact source-derived timing provider and generic target "
                    "hook exist, but the generated VCYCLE contract has no "
                    "assembler/link proof and REG_CLOCK/scanout cadence is "
                    "unmeasured on FT812"),
            })
        elif family == "c-z80-intrinsics":
            row.update({
                "status": "NARROW_MIN_MAX_PROVIDER_ONLY",
                "proven_capabilities": ["builtins.min/2", "builtins.max/2"],
            })
        else:
            row["status"] = "PROVIDER_FAMILY_SYMBOLS_PROVEN"
        row["semantic_sha256"] = _json_sha256(row)
        families.append(row)
    return {
        "family_count": len(families),
        "families": families,
        "physical_ts_ram_bytes": 16384 * 256,
        "physical_ts_ram_is_4mib": True,
        "exact_55hz_source_derived_provider_present": True,
        "exact_55hz_isr_provider_present": False,
        "provider_existence_does_not_prove_site_abi_match": True,
    }


def _family_for(semantic: str | None, boundary: str | None,
                caller: str | None, source: str,
                call: ast.Call | None = None) -> str | None:
    target = semantic or ""
    if any(token in target for token in (
            "::_BassMixer.push_music@", "::_BassMixer.reset_music@")):
        return "tsfm-music"
    if any(token in target for token in (
            "::_BassMixer.play_gs@", "::_BassMixer.stop_charge@",
            "::_BassMixer.stop_gs@")):
        return "gs-sfx"
    if "::TargetAudio.play@" in target:
        if (call is not None and call.args and
                isinstance(call.args[0], ast.Constant) and
                isinstance(call.args[0].value, int) and
                not isinstance(call.args[0].value, bool)):
            command = int(call.args[0].value) & 0xFF
            return "tsfm-music" if command < 0x30 else "gs-sfx"
    if "::M72SpriteAtlas.draw@" in target:
        return "ft812-video-draw"
    if boundary == "pygame" or target.startswith("pygame.") or target in {
            "target.blit", "target.fill", "target.get_width",
            "target.get_height", "image.get_width", "image.get_height"}:
        if ("event.get" in target or "key.get_pressed" in target or
                "mouse.get_pressed" in target):
            return "tsconf-input-mouse"
        if ("image.load" in target or "image.frombytes" in target or
                "convert_alpha" in target):
            return "asset-level-loader-4mb"
        return "ft812-video-draw"
    if boundary == "host-timing" or target.startswith("time."):
        return "frame-timing-55hz"
    if boundary == "filesystem":
        return "asset-level-loader-4mb"
    if boundary == "bass":
        identity = (caller or "") + " " + source
        if ("BASS_Stream" in target or "BASS_Channel" in target or
                "BASS_STREAM" in source):
            return "tsfm-music"
        if any(token in identity for token in (
                "push_music", "reset_music", "TurboSoundFm", "TSFM")):
            return "tsfm-music"
        if any(token in identity for token in (
                "play_gs", "stop_charge", "stop_gs", "GeneralSound", "GS")):
            return "gs-sfx"
        return None
    if boundary in {"python-runtime", "host-numeric"}:
        return "c-z80-intrinsics"
    if target.startswith(("builtins.", "python.", "collections.",
                          "dataclasses.", "struct.", "numpy.")):
        return "c-z80-intrinsics"
    return None


def _abi_obligations(family: str | None, signature: Mapping[str, Any],
                     semantic: str | None) -> list[str]:
    obligations = [
        "evaluate callable and every argument exactly once in Python order",
        "preserve positional/keyword/starred binding represented by signature",
        "preserve result width/sign/None and exception behavior or prove impossible",
    ]
    if family == "ft812-video-draw":
        obligations.extend([
            "resolve Python surface/asset identity to immutable FT812 resource identity",
            "preserve literal Python draw and Z order",
            "publish one atomic frame with RAM_DL strictly below 2048 words",
            "keep practical scanline transfer at or below 1209 clocks",
            "perform no Z80 pixel rendering",
        ])
    elif family == "tsconf-input-mouse":
        obligations.extend([
            "sample input exactly once per logical tick",
            "treat mouse position providers as coordinates, never as direction",
            "adapt pygame button/key collection shape without changing controls",
        ])
    elif family == "frame-timing-55hz":
        obligations.extend([
            "advance game, enemy, projectile and TSFM state exactly once per 55 Hz tick",
            "consume only a source-derived FT812 timing contract whose closest physical cadence is proven",
            "remain non-live until generated timing is assembled, linked and measured on FT812",
        ])
    elif family == "tsfm-music":
        obligations.extend([
            "route melodies only to TSFM",
            "execute exactly one TSFM stream tick per 55 Hz logical frame",
        ])
    elif family == "gs-sfx":
        obligations.append("route SFX commands only to General Sound")
    elif family == "asset-level-loader-4mb":
        obligations.extend([
            "replace host paths with source-proven pack/resource identities",
            "load level working sets on transition instead of claiming all-resident RAM",
            "respect the proven 256 x 16KiB physical TS RAM map",
        ])
    elif family == "c-z80-intrinsics":
        obligations.extend([
            "match Python integer/container semantics for the exact callable",
            "do not infer receiver type from annotations",
        ])
    if semantic in {"builtins.min", "builtins.max"}:
        obligations.append("use narrow two-positional-argument intrinsic only")
    if signature.get("starred_count") or signature.get("kwargs_expansion_count"):
        obligations.append("materialize dynamic *args/**kwargs shape before target call")
    return obligations


def _site_row(row: Mapping[str, Any], context: str,
              modules: Mapping[str, _ModuleSource], resolver: _Resolver
              ) -> dict[str, Any]:
    module_name = str(row.get("module") or str(row["caller"]).split("::", 1)[0])
    operation_kind = str(row.get("operation_kind", "explicit-call"))
    call = modules[module_name].calls.get((
        int(row["line"]), int(row["column"]), str(row["ast_sha256"])))
    if operation_kind == "explicit-call" and call is None:
        raise ActiveTargetAdaptersError(
            "PZATA120", f"call AST missing for {row['call_site_id']}")
    resolution = row["resolution"]
    source_resolution = None
    if str(resolution["kind"]).startswith("unresolved-"):
        source_resolution = resolver.resolve(row, call)
    exact_semantics = resolution["kind"] == "host-boundary"
    semantic: str | None = None
    boundary: str | None = None
    evidence: str | None = None
    semantic_kind = str(resolution["kind"])
    target_id: str | None = None
    if exact_semantics:
        semantic = str(resolution["external_target"])
        boundary = str(resolution["boundary"])
        evidence = str(resolution["evidence"])
        target_id = semantic
    elif source_resolution is not None:
        exact_semantics = True
        semantic = str(source_resolution["semantic"])
        semantic_kind = str(source_resolution["semantic_kind"])
        evidence = str(source_resolution["evidence"])
        target_id = str(source_resolution["target_id"])
        if source_resolution.get("boundary") is not None:
            boundary = str(source_resolution["boundary"])
    sig = _signature(call, operation_kind)
    family = _family_for(
        semantic, boundary, str(row.get("caller")) if "caller" in row else None,
        str(row["source"]), call)
    family_ids = [family] if family is not None else []
    internal = semantic_kind == "internal-callable"
    constructor = semantic_kind == "internal-constructor"
    if constructor and family is None:
        family = "c-z80-intrinsics"
        family_ids = [family]
    if (internal and semantic is not None and "::TargetAudio.play@" in semantic and
            not family_ids):
        family_ids = ["gs-sfx", "tsfm-music"]
    internal_target_substitution = internal and bool(
        {"ft812-video-draw", "tsfm-music", "gs-sfx"} & set(family_ids))
    capability = False
    if (semantic in {"builtins.min", "builtins.max"} and
            sig["positional_count"] == 2 and sig["starred_count"] == 0 and
            not sig["keyword_names"] and sig["kwargs_expansion_count"] == 0):
        capability = True
    if internal_target_substitution:
        binding = "SOURCE_RESOLVED_INTERNAL_HOST_IMPLEMENTATION_ADAPTER_PENDING"
    elif internal:
        binding = "SOURCE_RESOLVED_INTERNAL_CALL_NO_HOST_ADAPTER"
    elif capability:
        binding = "PROVIDER_CAPABILITY_PROVEN_BACKEND_SITE_BINDING_PENDING"
    elif family_ids:
        binding = "PROVIDER_FAMILY_PROVEN_ADAPTER_ABI_PENDING"
    elif constructor:
        binding = "EXACT_CONSTRUCTOR_TARGET_PROVIDER_MISSING"
    elif exact_semantics:
        binding = "EXACT_SEMANTICS_TARGET_PROVIDER_MISSING"
    else:
        binding = "EXACT_CALLABLE_SEMANTICS_UNRESOLVED"
    unresolved_expression = None
    if not exact_semantics:
        if call is not None:
            unresolved_expression = ast.unparse(call.func)
        else:
            unresolved_expression = str(row["source"])
    identity = {
        "context": context,
        "callable_identity": semantic if exact_semantics else unresolved_expression,
        "semantic_kind": semantic_kind,
        "signature": sig,
    }
    source_span = {
        "module": module_name,
        "line": int(row["line"]),
        "column": int(row["column"]),
        "source": str(row["source"]),
        "ast_sha256": str(row["ast_sha256"]),
    }
    return {
        "call_site_id": row["call_site_id"],
        "context": context,
        "module": module_name,
        **({"caller": row["caller"]} if "caller" in row else {}),
        "line": row["line"], "column": row["column"],
        "source": row["source"], "ast_sha256": row["ast_sha256"],
        "source_span_sha256": _json_sha256(source_span),
        "input_resolution_kind": resolution["kind"],
        "exact_callable_semantics": exact_semantics,
        "semantic_kind": semantic_kind,
        "semantic": semantic,
        "unresolved_callable_expression": unresolved_expression,
        "target_id": target_id,
        "source_resolution_evidence": evidence,
        "annotations_used_as_type_evidence": False,
        "signature": sig,
        "provider_family_id": family_ids[0] if len(family_ids) == 1 else None,
        "provider_family_ids": family_ids,
        "provider_capability_match": capability,
        "adapter_binding_status": binding,
        "adapter_abi_obligations": sorted({
            item for family_item in (family_ids or [None])
            for item in _abi_obligations(family_item, sig, semantic)}),
        "semantic_group_id": _json_sha256(identity),
    }


def _groups(sites: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sites:
        grouped[str(row["semantic_group_id"])].append(row)
    result: list[dict[str, Any]] = []
    for group_id, rows in sorted(grouped.items()):
        first = rows[0]
        contexts = sorted({str(row["context"]) for row in rows})
        statuses = sorted({str(row["adapter_binding_status"]) for row in rows})
        families = sorted({str(family) for row in rows
                           for family in row.get("provider_family_ids", [])})
        obligations = sorted({str(item) for row in rows
                              for item in row["adapter_abi_obligations"]})
        result.append({
            "group_id": group_id,
            "exact_callable_semantics": first["exact_callable_semantics"],
            "semantic_kind": first["semantic_kind"],
            "semantic": first["semantic"],
            "signature": first["signature"],
            "contexts": contexts,
            "provider_family_id": families[0] if len(families) == 1 else None,
            "provider_family_ids": families,
            "adapter_binding_statuses": statuses,
            "adapter_abi_obligations": obligations,
            "site_count": len(rows),
            "call_site_ids": sorted(str(row["call_site_id"]) for row in rows),
        })
    return result


def _counter(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key)) for row in rows).items()))


def analyze_active_target_adapters(
        project_root: Path | str,
        active_call_graph_path: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    graph_path = (Path(active_call_graph_path) if active_call_graph_path
                  else root / "Build" /
                  "rtype_python_active_call_graph_status.json")
    if not graph_path.is_absolute():
        graph_path = root / graph_path
    try:
        graph_bytes = graph_path.read_bytes()
        graph = json.loads(graph_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActiveTargetAdaptersError(
            "PZATA001", f"cannot read active call graph: {exc}") from exc
    try:
        validate_active_call_graph_report(root, graph)
    except ActiveCallGraphError as exc:
        raise ActiveTargetAdaptersError(
            "PZATA002", f"active call graph rejected: {exc}") from exc
    if graph.get("format") != ACTIVE_CALL_GRAPH_FORMAT:
        raise ActiveTargetAdaptersError("PZATA003", "active call graph format changed")
    modules = _load_modules(root, graph)
    resolver = _Resolver(graph, modules)
    reachable = set(graph["call_graph"]["proven_reachable_callable_ids"])
    runtime_input = [
        row for row in graph["call_graph"]["call_sites"]
        if row["caller"] in reachable and (
            row["resolution"]["kind"] == "host-boundary" or
            str(row["resolution"]["kind"]).startswith("unresolved-") or
            row["resolution"]["kind"] == "finite-dynamic-dispatch")
    ]
    module_input = [
        row for row in graph["module_initialization"]["call_sites"]
        if (row["resolution"]["kind"] == "host-boundary" or
            str(row["resolution"]["kind"]).startswith("unresolved-") or
            row["resolution"]["kind"] == "finite-dynamic-dispatch")
    ]
    runtime_sites = [_site_row(row, "runtime", modules, resolver)
                     for row in runtime_input]
    module_sites = [_site_row(row, "module-initialization", modules, resolver)
                    for row in module_input]
    sites = sorted(runtime_sites + module_sites,
                   key=lambda row: (str(row["context"]), str(row["module"]),
                                    int(row["line"]), int(row["column"]),
                                    str(row["call_site_id"])))
    groups = _groups(sites)
    provider_catalog = _provider_catalog(root)
    exact = [row for row in sites if row["exact_callable_semantics"]]
    unresolved = [row for row in sites if not row["exact_callable_semantics"]]
    internal_semantics = [row for row in sites
                          if row["semantic_kind"] == "internal-callable"]
    internal_no_adapter = [
        row for row in sites if row["adapter_binding_status"] ==
        "SOURCE_RESOLVED_INTERNAL_CALL_NO_HOST_ADAPTER"]
    internal_substitutions = [
        row for row in sites if row["adapter_binding_status"] ==
        "SOURCE_RESOLVED_INTERNAL_HOST_IMPLEMENTATION_ADAPTER_PENDING"]
    capability = [row for row in sites if row["provider_capability_match"]]
    family_mapped = [row for row in sites if row.get("provider_family_ids")]
    family_counts = dict(sorted(Counter(
        family for row in family_mapped
        for family in row["provider_family_ids"]).items()))
    adapter_pending = [row for row in sites if row not in internal_no_adapter]
    source_rows = [{
        "module": module,
        "path": info.relative_path,
        "sha256": _sha256(info.data),
    } for module, info in sorted(modules.items())]
    interprocedural_facts = [{
        "callable_id": callable_id,
        "parameter": parameter,
        "value_identity": value,
    } for (callable_id, parameter), value in sorted(
        resolver._parameter_facts.items())]
    interprocedural_fact_proof = {
        "kind": "active-source-constructor-argument-fixpoint",
        "exact_fact_count": len(interprocedural_facts),
        "facts": interprocedural_facts,
        "uses_only_executable_call_actuals": True,
        "unknown_or_conflicting_actuals_fail_closed": True,
        "annotations_used_as_type_evidence": False,
    }
    interprocedural_fact_proof["semantic_sha256"] = _json_sha256(
        interprocedural_fact_proof)
    inventory = {
        "site_count": len(sites),
        "sites": sites,
        "unique_call_site_count": len({row["call_site_id"] for row in sites}),
        "runtime": {
            "site_count": len(runtime_sites),
            "input_host_boundary_count": sum(
                row["input_resolution_kind"] == "host-boundary"
                for row in runtime_sites),
            "input_unresolved_count": sum(
                str(row["input_resolution_kind"]).startswith("unresolved-")
                for row in runtime_sites),
            "input_finite_dynamic_count": sum(
                row["input_resolution_kind"] == "finite-dynamic-dispatch"
                for row in runtime_sites),
        },
        "module_initialization": {
            "separate_from_runtime": True,
            "site_count": len(module_sites),
            "input_host_boundary_count": sum(
                row["input_resolution_kind"] == "host-boundary"
                for row in module_sites),
            "input_unresolved_count": sum(
                str(row["input_resolution_kind"]).startswith("unresolved-")
                for row in module_sites),
        },
        "exact_callable_semantics_count": len(exact),
        "resolved_call_site_ids": sorted(
            str(row["call_site_id"]) for row in exact),
        "unresolved_callable_semantics_count": len(unresolved),
        "unresolved_call_site_ids": sorted(
            str(row["call_site_id"]) for row in unresolved),
        "source_resolved_internal_call_count": len(internal_semantics),
        "source_resolved_call_site_ids": sorted(
            str(row["call_site_id"]) for row in sites
            if row["input_resolution_kind"] != "host-boundary" and
            row["exact_callable_semantics"]),
        "source_resolved_internal_no_adapter_count": len(internal_no_adapter),
        "source_resolved_internal_target_substitution_count": len(
            internal_substitutions),
        "provider_family_mapped_site_count": len(family_mapped),
        "provider_capability_match_site_count": len(capability),
        "adapter_pending_site_count": len(adapter_pending),
        "semantic_group_count": len(groups),
        "semantic_groups": groups,
        "input_resolution_kind_counts": _counter(sites, "input_resolution_kind"),
        "semantic_kind_counts": _counter(sites, "semantic_kind"),
        "provider_family_counts": family_counts,
        "multi_provider_routing_site_count": sum(
            len(row["provider_family_ids"]) > 1 for row in sites),
        "adapter_binding_status_counts": _counter(sites, "adapter_binding_status"),
        "interprocedural_fact_proof": interprocedural_fact_proof,
    }
    blockers = [
        {
            "code": "PZATA201", "count": len(adapter_pending),
            "detail": "active backend does not consume this adapter inventory",
        },
        {
            "code": "PZATA202", "count": len(unresolved),
            "detail": "callable identity is not source-proven; annotations are ignored",
        },
        {
            "code": "PZATA203",
            "count": len(adapter_pending) - len(capability),
            "detail": "exact per-site provider ABI binding is not proven",
        },
        {
            "code": "PZATA204", "count": len(module_sites),
            "detail": "module/class initialization adapters are inventoried but not lowered",
        },
        {
            "code": "PZATA205", "count": 1,
            "detail": (
                "source-derived 55 Hz timing provider is unlinked and FT812 "
                "REG_CLOCK/VCYCLE/scanout cadence is unmeasured"),
        },
    ]
    report: dict[str, Any] = {
        "format": ACTIVE_TARGET_ADAPTERS_FORMAT,
        "input_binding": {
            "active_call_graph": {
                "path": _norm(graph_path.relative_to(root)),
                "file_sha256": _sha256(graph_bytes),
                "format": graph["format"],
                "status": graph["status"],
                "semantic_sha256": graph["semantic_sha256"],
                "source_graph_semantic_sha256": graph["source_graph"]["semantic_sha256"],
            },
            "active_sources": source_rows,
        },
        "provider_catalog": provider_catalog,
        "inventory": inventory,
        "adapter_abi_obligation_count": sum(
            len(row["adapter_abi_obligations"]) for row in groups),
        "proof": {
            "reachability_source": "active call graph proven reachable callable ids only",
            "all_reachable_host_boundaries_inventoried": (
                inventory["runtime"]["input_host_boundary_count"] ==
                graph["call_graph"]["reachable_host_boundary_call_site_count"]),
            "all_reachable_unresolved_calls_inventoried": (
                inventory["runtime"]["input_unresolved_count"] ==
                graph["call_graph"]["reachable_unresolved_call_site_count"]),
            "finite_dynamic_dispatch_inventoried_fail_closed": True,
            "module_initialization_adapters_separate": True,
            "annotations_do_not_prove_types": True,
            "provider_requires_existing_symbol_and_file_hash": True,
            "unmatched_calls_remain_fail_closed": True,
            "target_backend_consumes_inventory": False,
            "spg_or_emulator_touched": False,
        },
    }
    report["semantic_sha256"] = _json_sha256(_semantic_payload(report))
    report["status"] = ACTIVE_TARGET_ADAPTERS_STATUS
    report["live"] = False
    report["live_blockers"] = blockers
    validate_active_target_adapters_report(root, report, graph)
    return report


def validate_active_target_adapters_report(
        project_root: Path | str,
        report: Mapping[str, Any],
        active_call_graph_report: Mapping[str, Any] | None = None) -> None:
    root = Path(project_root).resolve()
    if report.get("format") != ACTIVE_TARGET_ADAPTERS_FORMAT:
        raise ActiveTargetAdaptersError("PZATA401", "report format mismatch")
    if (report.get("status") != ACTIVE_TARGET_ADAPTERS_STATUS or
            report.get("live") is not False):
        raise ActiveTargetAdaptersError("PZATA402", "status/live claim mismatch")
    semantic = report.get("semantic_sha256")
    if semantic != _json_sha256(_semantic_payload(report)):
        raise ActiveTargetAdaptersError("PZATA403", "semantic hash mismatch")
    binding = report.get("input_binding", {}).get("active_call_graph", {})
    relative = binding.get("path")
    if not isinstance(relative, str):
        raise ActiveTargetAdaptersError("PZATA404", "call graph path missing")
    graph_path = root / Path(relative)
    try:
        graph_bytes = graph_path.read_bytes()
        graph = (active_call_graph_report if active_call_graph_report is not None
                 else json.loads(graph_bytes.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActiveTargetAdaptersError(
            "PZATA405", f"cannot re-read active call graph: {exc}") from exc
    if (_sha256(graph_bytes) != binding.get("file_sha256") or
            graph.get("format") != binding.get("format") or
            graph.get("status") != binding.get("status") or
            graph.get("semantic_sha256") != binding.get("semantic_sha256") or
            graph.get("source_graph", {}).get("semantic_sha256") !=
            binding.get("source_graph_semantic_sha256")):
        raise ActiveTargetAdaptersError("PZATA406", "call graph binding changed")
    try:
        validate_active_call_graph_report(root, graph)
    except ActiveCallGraphError as exc:
        raise ActiveTargetAdaptersError(
            "PZATA426", f"bound active call graph is stale or invalid: {exc}") from exc
    sources = report.get("input_binding", {}).get("active_sources")
    if not isinstance(sources, list):
        raise ActiveTargetAdaptersError("PZATA407", "active source binding missing")
    for row in sources:
        path = root / Path(str(row.get("path")))
        try:
            digest = _sha256(path.read_bytes())
        except OSError as exc:
            raise ActiveTargetAdaptersError(
                "PZATA408", f"cannot read active source {path}: {exc}") from exc
        if digest != row.get("sha256"):
            raise ActiveTargetAdaptersError(
                "PZATA409", f"active source hash changed: {row.get('path')}")
    catalog = report.get("provider_catalog")
    if not isinstance(catalog, dict):
        raise ActiveTargetAdaptersError("PZATA410", "provider catalog missing")
    families = catalog.get("families")
    if (not isinstance(families, list) or
            catalog.get("family_count") != len(families) or
            len({row.get("family_id") for row in families}) != len(families)):
        raise ActiveTargetAdaptersError("PZATA411", "provider family census mismatch")
    for family in families:
        copy = dict(family)
        digest = copy.pop("semantic_sha256", None)
        if digest != _json_sha256(copy):
            raise ActiveTargetAdaptersError(
                "PZATA412", f"provider family hash mismatch: {family.get('family_id')}")
        for evidence_key in ("provider_evidence", "incompatible_candidate_evidence"):
            for evidence in family.get(evidence_key, []):
                path = root / Path(str(evidence.get("path")))
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    raise ActiveTargetAdaptersError(
                        "PZATA413", f"provider file unavailable {path}: {exc}") from exc
                if _sha256(data) != evidence.get("file_sha256"):
                    raise ActiveTargetAdaptersError(
                        "PZATA414", f"provider file hash changed: {path}")
    family_ids = {str(row["family_id"]) for row in families}
    inventory = report.get("inventory")
    if not isinstance(inventory, dict) or not isinstance(inventory.get("sites"), list):
        raise ActiveTargetAdaptersError("PZATA415", "site inventory missing")
    sites = inventory["sites"]
    if any(not isinstance(row.get("provider_family_ids"), list) or
           not set(row["provider_family_ids"]).issubset(family_ids)
           for row in sites):
        raise ActiveTargetAdaptersError(
            "PZATA423", "site references an unproven provider family")
    if (inventory.get("site_count") != len(sites) or
            inventory.get("unique_call_site_count") !=
            len({row.get("call_site_id") for row in sites}) or
            inventory.get("exact_callable_semantics_count") !=
            sum(row.get("exact_callable_semantics") is True for row in sites) or
            inventory.get("unresolved_callable_semantics_count") !=
            sum(row.get("exact_callable_semantics") is False for row in sites)):
        raise ActiveTargetAdaptersError("PZATA416", "site census mismatch")
    resolved_ids = sorted(str(row["call_site_id"]) for row in sites
                          if row.get("exact_callable_semantics") is True)
    unresolved_ids = sorted(str(row["call_site_id"]) for row in sites
                            if row.get("exact_callable_semantics") is False)
    source_resolved_ids = sorted(
        str(row["call_site_id"]) for row in sites
        if row.get("input_resolution_kind") != "host-boundary" and
        row.get("exact_callable_semantics") is True)
    if (inventory.get("resolved_call_site_ids") != resolved_ids or
            inventory.get("unresolved_call_site_ids") != unresolved_ids or
            inventory.get("source_resolved_call_site_ids") !=
            source_resolved_ids):
        raise ActiveTargetAdaptersError(
            "PZATA424", "resolved/unresolved id partition mismatch")
    if any(row.get("source_span_sha256") != _json_sha256({
            "module": str(row.get("module")),
            "line": int(row.get("line")),
            "column": int(row.get("column")),
            "source": str(row.get("source")),
            "ast_sha256": str(row.get("ast_sha256")),
    }) for row in sites):
        raise ActiveTargetAdaptersError("PZATA425", "source span hash mismatch")
    fact_proof = inventory.get("interprocedural_fact_proof")
    if not isinstance(fact_proof, dict):
        raise ActiveTargetAdaptersError(
            "PZATA427", "interprocedural fact proof missing")
    fact_copy = dict(fact_proof)
    fact_digest = fact_copy.pop("semantic_sha256", None)
    facts = fact_copy.get("facts")
    if (not isinstance(facts, list) or
            fact_copy.get("exact_fact_count") != len(facts) or
            fact_copy.get("annotations_used_as_type_evidence") is not False or
            fact_digest != _json_sha256(fact_copy)):
        raise ActiveTargetAdaptersError(
            "PZATA427", "interprocedural fact proof mismatch")
    runtime = [row for row in sites if row.get("context") == "runtime"]
    module = [row for row in sites if row.get("context") == "module-initialization"]
    if (inventory.get("runtime", {}).get("site_count") != len(runtime) or
            inventory.get("module_initialization", {}).get("site_count") != len(module)):
        raise ActiveTargetAdaptersError("PZATA417", "context census mismatch")
    groups = inventory.get("semantic_groups")
    if (not isinstance(groups, list) or
            inventory.get("semantic_group_count") != len(groups) or
            sorted(site for row in groups for site in row.get("call_site_ids", [])) !=
            sorted(str(row["call_site_id"]) for row in sites)):
        raise ActiveTargetAdaptersError("PZATA418", "semantic groups mismatch")
    if any(row.get("annotations_used_as_type_evidence") is not False
           for row in sites):
        raise ActiveTargetAdaptersError("PZATA419", "annotation promoted to type proof")
    expected_runtime_host = int(
        graph["call_graph"]["reachable_host_boundary_call_site_count"])
    expected_runtime_unresolved = int(
        graph["call_graph"]["reachable_unresolved_call_site_count"])
    if (inventory["runtime"].get("input_host_boundary_count") !=
            expected_runtime_host or
            inventory["runtime"].get("input_unresolved_count") !=
            expected_runtime_unresolved):
        raise ActiveTargetAdaptersError("PZATA420", "active graph coverage mismatch")
    blocker_counts = {row.get("code"): row.get("count")
                      for row in report.get("live_blockers", [])}
    if (blocker_counts.get("PZATA201") !=
            inventory.get("adapter_pending_site_count") or
            blocker_counts.get("PZATA202") !=
            inventory.get("unresolved_callable_semantics_count") or
            blocker_counts.get("PZATA204") != len(module) or
            blocker_counts.get("PZATA205") != 1):
        raise ActiveTargetAdaptersError("PZATA421", "live blocker census mismatch")
    if (catalog.get("exact_55hz_source_derived_provider_present") is not True or
            catalog.get("exact_55hz_isr_provider_present") is not False or
            report.get("proof", {}).get("target_backend_consumes_inventory") is not False):
        raise ActiveTargetAdaptersError("PZATA422", "unsupported live claim")
