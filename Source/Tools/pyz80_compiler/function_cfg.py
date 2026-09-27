"""Target-neutral CFG census for active Python mutation-owning functions.

This module deliberately stops before a C/object ABI.  It lowers ordinary
Python control flow and references the exact already-certified object-store
fragments at their source statements.  Unsupported constructs are explicit
blockers; no source is imported or executed and no opaque expression fallback
exists.
"""

from __future__ import annotations

import ast
import __future__
import dis
import hashlib
import json
import os
import symtable
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from types import CodeType
from functools import lru_cache

from .diagnostics import CompileError, SourceSpan
from .frontend import (ObjectExpressionLowerer, _BINARY_OPERATOR_NAMES,
                       lower_active_object_store_ir)
from .ir import (ActivePythonFunctionIR, ActivePythonFunctionModuleIR,
                 ObjectEffectInstruction, ObjectExpressionIR,
                 ObjectStoreFragmentIR, ObjectStoreModuleIR,
                 PythonFunctionBlock, PythonFunctionCFGBlocker,
                 PythonFunctionTerminator)
from .mutation_hook_ir import MutationHookPlan, build_mutation_hook_ir


FUNCTION_CFG_IR_FORMAT = "pyz80.active-function-cfg-ir.v1"

__all__ = [
    "FUNCTION_CFG_IR_FORMAT",
    "FunctionCFGError",
    "build_active_function_cfg_ir",
    "function_cfg_report",
    "lower_python_function_cfg",
    "lower_python_module_cfg",
    "lower_python_class_cfg",
    "validate_active_function_cfg_ir",
    "write_active_function_cfg_report",
]


class FunctionCFGError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _ast_sha256(node: ast.AST) -> str:
    return hashlib.sha256(
        ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _source(source_text: str, node: ast.AST) -> str:
    return ast.get_source_segment(source_text, node) or ast.unparse(node)


@lru_cache(maxsize=24)
def _future_annotations_enabled(source_text: str) -> bool:
    """Return the source-level ``__future__.annotations`` contract.

    Annotation evaluation is observable at a nested function definition, so
    the lowering must not infer it from the Python version running the
    translator.  The future import is the stable, source-owned contract used
    by every active game module.
    """
    tree = ast.parse(source_text, type_comments=True)
    for index, statement in enumerate(tree.body):
        if (index == 0 and isinstance(statement, ast.Expr) and
                isinstance(statement.value, ast.Constant) and
                isinstance(statement.value.value, str)):
            continue
        if (isinstance(statement, ast.ImportFrom) and
                statement.module == "__future__"):
            if any(alias.name == "annotations"
                   for alias in statement.names):
                return True
            continue
        break
    return False


def _annotation_descriptors(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        source_text: str,
        ) -> tuple[tuple[str, str, str], ...]:
    """Describe annotations without evaluating postponed expressions."""
    rows: list[tuple[str, str, str]] = []
    arguments = node.args
    ordered_arguments = [
        *arguments.args,
        *arguments.posonlyargs,
        *([arguments.vararg] if arguments.vararg is not None else []),
        *arguments.kwonlyargs,
        *([arguments.kwarg] if arguments.kwarg is not None else []),
    ]
    for argument in ordered_arguments:
        if argument.annotation is not None:
            rows.append((
                argument.arg,
                _ast_sha256(argument.annotation),
                _source(source_text, argument.annotation),
            ))
    if node.returns is not None:
        rows.append((
            "return", _ast_sha256(node.returns),
            _source(source_text, node.returns)))
    return tuple(rows)


def _scope_has_annotations(node: ast.AST) -> bool:
    class Visitor(ast.NodeVisitor):
        found = False
        def visit_AnnAssign(self, item): self.found = True
        def visit_FunctionDef(self, item): pass
        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef
    visitor = Visitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.found


def _postponed_annotation_string(annotation: ast.expr, source_path: Path) -> str:
    """Use the pinned CPython compiler's stringization, never an approximation.

    Only syntax-to-string conversion is requested; this tiny annotation AST is
    never executed or name-resolved. It also works for unreachable annotations
    that CPython has optimized out of the enclosing module's bytecode.
    """
    target = ast.copy_location(ast.Name(id="_annotation", ctx=ast.Store()), annotation)
    statement = ast.copy_location(ast.AnnAssign(target=target, annotation=annotation, value=None, simple=1), annotation)
    tree = ast.fix_missing_locations(ast.Module(body=[statement], type_ignores=[]))
    code = compile(tree, str(source_path), "exec", flags=__future__.annotations.compiler_flag,
                   dont_inherit=True, optimize=0)
    instructions = tuple(dis.get_instructions(code))
    matches = [item.argval for item, following in zip(instructions, instructions[1:])
               if item.opname == "LOAD_CONST" and isinstance(item.argval, str) and
               following.opname == "LOAD_NAME" and following.argval == "__annotations__"]
    if len(matches) != 1:
        raise FunctionCFGError("PZFC120", "pinned compiler annotation string contract differs")
    return matches[0]


def _nested_function_free_names(
        source_text: str, source_path: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> tuple[str, ...]:
    """Resolve the lexical cells captured by one nested definition.

    ``symtable`` performs Python's real lexical-scope analysis without
    importing or executing the module.  Cell tuples are carried by name in
    the target-neutral IR, so sorting is deterministic without depending on
    CPython's private cell-index order.
    """
    matches: list[symtable.SymbolTable] = []
    for table in _symbol_table_index(source_text, source_path):
        if (table.get_type() == "function" and
                table.get_name() == node.name and
                table.get_lineno() == node.lineno and
                hasattr(table, "get_frees")):
            matches.append(table)
    if len(matches) != 1:
        raise FunctionCFGError(
            "PZFC110", f"nested function {node.name}@{node.lineno} "
            f"resolves to {len(matches)} symbol tables")
    return tuple(sorted(matches[0].get_frees()))


@lru_cache(maxsize=24)
def _source_code_index(source_text: str, source_path: str) -> tuple[CodeType, ...]:
    """CPython lexical metadata only; no code object is executed on the host.

    3.12 inlines comprehensions (PEP 709), removing their symtable child.
    Positions and co_freevars recover exact cell bindings without wrappers.
    """
    pending = [compile(source_text, source_path, "exec", dont_inherit=True, optimize=0)]
    result = []
    while pending:
        code = pending.pop()
        result.append(code)
        pending.extend(value for value in code.co_consts if isinstance(value, CodeType))
    return tuple(result)


def _class_code(node: ast.ClassDef, source_text: str, source_path: Path) -> CodeType:
    first_line = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    matches = [code for code in _source_code_index(source_text, str(source_path))
               if code.co_name == node.name and code.co_firstlineno == first_line]
    if len(matches) != 1:
        raise FunctionCFGError("PZFC119", "class lexical code identity is missing or ambiguous")
    return matches[0]


@lru_cache(maxsize=24)
def _class_ast_seals(source_text: str) -> frozenset[tuple[int, str]]:
    return frozenset((item.lineno, _ast_sha256(item)) for item in ast.walk(ast.parse(source_text))
                     if isinstance(item, ast.ClassDef))


@lru_cache(maxsize=24)
def _source_cell_loads(source_text: str, source_path: str) -> dict[tuple, frozenset[str]]:
    positions = defaultdict(set)
    for code in _source_code_index(source_text, source_path):
        for instruction in dis.get_instructions(code):
            if instruction.opname not in ("LOAD_DEREF", "LOAD_CLASSDEREF"):
                continue
            if instruction.positions is None or instruction.positions.col_offset is None:
                raise FunctionCFGError("PZFC118", "CPython lexical load has no source position")
            positions[tuple(instruction.positions)].add(instruction.argval)
    return {position: frozenset(names) for position, names in positions.items()}


def _ssa_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.startswith("%fn_") else ()
    if isinstance(value, (tuple, list)):
        result: list[str] = []
        for item in value:
            result.extend(_ssa_values(item))
        return tuple(result)
    return ()


@dataclass
class _Block:
    name: str
    instructions: list[ObjectEffectInstruction]
    terminator: PythonFunctionTerminator | None = None
    exception_target: str | None = None


@dataclass
class _FinalizerContext:
    label: str
    kind: str
    statements: tuple[ast.stmt, ...]
    handler_name: str | None
    exception_block: _Block
    outer_exception_target: str | None
    with_manager: str | None = None
    with_exit: str | None = None
    with_owner: ast.AST | None = None


@dataclass(frozen=True)
class _ControlTarget:
    """A jump destination plus the lexical finalizer depth it retains."""

    name: str
    finalizer_depth: int


_INHERIT_EXCEPTION = object()


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef,
                        source_text: str) -> dict[str, Any]:
    arguments = node.args
    positional = list(arguments.posonlyargs) + list(arguments.args)
    default_offset = len(positional) - len(arguments.defaults)
    defaults: list[str | None] = [None] * default_offset + [
        _source(source_text, item) for item in arguments.defaults]
    parameters: list[dict[str, Any]] = []
    for index, argument in enumerate(arguments.posonlyargs):
        parameters.append({
            "name": argument.arg, "kind": "positional-only",
            "default": defaults[index],
        })
    offset = len(arguments.posonlyargs)
    for index, argument in enumerate(arguments.args, offset):
        parameters.append({
            "name": argument.arg, "kind": "positional-or-keyword",
            "default": defaults[index],
        })
    if arguments.vararg is not None:
        parameters.append({
            "name": arguments.vararg.arg, "kind": "var-positional",
            "default": None,
        })
    for argument, default in zip(arguments.kwonlyargs,
                                 arguments.kw_defaults):
        parameters.append({
            "name": argument.arg, "kind": "keyword-only",
            "default": (_source(source_text, default)
                        if default is not None else None),
            "required": default is None,
        })
    if arguments.kwarg is not None:
        parameters.append({
            "name": arguments.kwarg.arg, "kind": "var-keyword",
            "default": None,
        })
    return {
        "async": isinstance(node, ast.AsyncFunctionDef),
        "parameters": parameters,
        "decorators": [_source(source_text, item)
                       for item in node.decorator_list],
        "returns": (_source(source_text, node.returns)
                    if node.returns is not None else None),
    }


EXTENDED_EXPRESSION_SCOPE_FORMAT = "pyz80.extended-expression-scope.v1"
_SYMBOL_TABLE_INDEX_CACHE: dict[
    tuple[str, str], tuple[symtable.SymbolTable, ...]] = {}


def _symbol_table_index(
        source_text: str, source_path: Path,
        ) -> tuple[symtable.SymbolTable, ...]:
    """Parse one immutable source text once, keyed by its exact SHA-256."""
    key = (source_path.as_posix(), hashlib.sha256(
        source_text.encode("utf-8")).hexdigest())
    known = _SYMBOL_TABLE_INDEX_CACHE.get(key)
    if known is not None:
        return known
    root = symtable.symtable(source_text, str(source_path), "exec")
    result: list[symtable.SymbolTable] = [root]
    pending = list(root.get_children())
    while pending:
        table = pending.pop()
        result.append(table)
        pending.extend(table.get_children())
    frozen = tuple(result)
    _SYMBOL_TABLE_INDEX_CACHE[key] = frozen
    return frozen


def _find_function_symbol_table(
        source_text: str, source_path: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Module,
        ) -> symtable.SymbolTable:
    """Resolve one source function to its lexical symbol table."""
    if isinstance(node, ast.Module):
        return _symbol_table_index(source_text, source_path)[0]
    matches: list[symtable.SymbolTable] = []
    for table in _symbol_table_index(source_text, source_path):
        if (table.get_type() == ("class" if isinstance(node, ast.ClassDef) else "function") and
                table.get_name() == node.name and
                table.get_lineno() == node.lineno):
            matches.append(table)
    if len(matches) != 1:
        raise FunctionCFGError(
            "PZFC111", f"function lexical scope {node.name}@{node.lineno} "
            f"resolves to {len(matches)} symbol tables")
    return matches[0]


def _find_lambda_free_names(
        source_text: str, source_path: Path, node: ast.Lambda,
        ) -> tuple[str, ...]:
    """Return exact cell captures for one lambda, never global names."""
    matches: list[symtable.SymbolTable] = []
    for table in _symbol_table_index(source_text, source_path):
        if (table.get_type() == "function" and
                table.get_name() == "lambda" and
                table.get_lineno() == node.lineno and
                hasattr(table, "get_frees")):
            matches.append(table)
    if len(matches) != 1:
        raise FunctionCFGError(
            "PZFC112", f"lambda@{node.lineno}:{node.col_offset} resolves to "
            f"{len(matches)} symbol tables; same-line lambda identity is "
            "not inferred")
    return tuple(sorted(matches[0].get_frees()))


def _lambda_signature_descriptor(node: ast.Lambda) -> tuple[
        tuple[str, str, bool], ...]:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    default_offset = len(positional) - len(arguments.defaults)
    rows: list[tuple[str, str, bool]] = []
    for index, argument in enumerate(arguments.posonlyargs):
        rows.append((argument.arg, "positional-only",
                     index >= default_offset))
    offset = len(arguments.posonlyargs)
    for index, argument in enumerate(arguments.args, offset):
        rows.append((argument.arg, "positional-or-keyword",
                     index >= default_offset))
    if arguments.vararg is not None:
        rows.append((arguments.vararg.arg, "var-positional", False))
    for argument, default in zip(arguments.kwonlyargs,
                                 arguments.kw_defaults):
        rows.append((argument.arg, "keyword-only", default is not None))
    if arguments.kwarg is not None:
        rows.append((arguments.kwarg.arg, "var-keyword", False))
    return tuple(rows)


def _target_descriptor(source_text: str, node: ast.expr) -> dict[str, Any]:
    """Describe a comprehension target's exact Python assignment protocol."""
    common = {
        "ast_sha256": _ast_sha256(node),
        "source": _source(source_text, node),
    }
    if isinstance(node, ast.Name):
        return {**common, "kind": "local-name", "name": node.id}
    if isinstance(node, ast.Starred):
        return {
            **common, "kind": "starred",
            "value": _target_descriptor(source_text, node.value),
        }
    if isinstance(node, (ast.Tuple, ast.List)):
        starred = [index for index, item in enumerate(node.elts)
                   if isinstance(item, ast.Starred)]
        if len(starred) > 1:
            raise FunctionCFGError(
                "PZFC113", "comprehension target has multiple starred items")
        return {
            **common,
            "kind": "tuple-unpack" if isinstance(node, ast.Tuple)
                    else "list-unpack",
            "items": tuple(_target_descriptor(source_text, item)
                           for item in node.elts),
            "unpack_protocol": (
                ("UNPACK_EX", starred[0], len(node.elts) - starred[0] - 1)
                if starred else ("UNPACK_SEQUENCE", len(node.elts))),
        }
    raise FunctionCFGError(
        "PZFC113", "comprehension target protocol is not proved for "
        f"{type(node).__name__}")


def _target_local_names(node: ast.expr) -> tuple[str, ...]:
    names = sorted({item.id for item in ast.walk(node)
                    if isinstance(item, ast.Name) and
                    isinstance(item.ctx, ast.Store)})
    return tuple(names)


class _DeferredScopeVisitor(ast.NodeVisitor):
    """Inventory nearest nested scopes without entering their deferred body."""
    def __init__(self) -> None:
        self.nodes: list[ast.expr] = []

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self.nodes.append(node)

    def _visit_comprehension(self, node: ast.expr) -> None:
        self.nodes.append(node)

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension


def _expression_descriptor(source_text: str, node: ast.expr) -> dict[str, Any]:
    visitor = _DeferredScopeVisitor()
    for child in ast.iter_child_nodes(node):
        visitor.visit(child)
    return {
        "node_kind": type(node).__name__,
        "ast_sha256": _ast_sha256(node),
        "source": _source(source_text, node),
        "nested_scopes": tuple({
            "node_kind": type(item).__name__,
            "ast_sha256": _ast_sha256(item),
            "line": int(item.lineno),
            "column": int(item.col_offset),
            "source": _source(source_text, item),
        } for item in visitor.nodes),
    }


class _ComprehensionScopeNameVisitor(ast.NodeVisitor):
    """Collect loads executed in this scope, stopping at nested scopes."""
    def __init__(self) -> None:
        self.loads: set[str] = set()
        self.load_nodes: list[ast.Name] = []
        self.named_expression: ast.NamedExpr | None = None
        self.await_node: ast.Await | None = None

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, ast.Load):
            self.loads.add(node.id)
            self.load_nodes.append(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        self.named_expression = self.named_expression or node

    def visit_Await(self, node: ast.Await) -> None:  # noqa: N802
        self.await_node = self.await_node or node

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        # Defaults execute in this scope; the body belongs to the lambda.
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)

    def _visit_nested_comprehension(
            self, node: ast.ListComp | ast.SetComp | ast.DictComp |
            ast.GeneratorExp) -> None:
        # Only the leftmost iterable is evaluated by the creating scope.
        if node.generators:
            self.visit(node.generators[0].iter)

    visit_ListComp = _visit_nested_comprehension
    visit_SetComp = _visit_nested_comprehension
    visit_DictComp = _visit_nested_comprehension
    visit_GeneratorExp = _visit_nested_comprehension


def _comprehension_scope_nodes(
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        ) -> tuple[ast.expr, ...]:
    result: list[ast.expr] = []
    for index, generator in enumerate(node.generators):
        if index:
            result.append(generator.iter)
        result.extend(generator.ifs)
    if isinstance(node, ast.DictComp):
        result.extend((node.key, node.value))
    else:
        result.append(node.elt)
    return tuple(result)


def _comprehension_free_cell_names(
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        enclosing_table: symtable.SymbolTable,
        source_text: str = "", source_path: Path | None = None,
        ) -> tuple[str, ...]:
    local_names = {name for generator in node.generators
                   for name in _target_local_names(generator.target)}
    # Отложенное тело не исполняется сейчас, но его свободные ячейки должны
    # пройти через каждую промежуточную область. Локальные имена дочернего
    # включения не являются зависимостями родительского включения.
    class ClosureVisitor(_ComprehensionScopeNameVisitor):
        def _visit_child(self, child):
            if child.generators:
                self.visit(child.generators[0].iter)
            nested = ClosureVisitor()
            bound = {name for generator in child.generators
                     for name in _target_local_names(generator.target)}
            for generator in child.generators:
                nested.visit(generator.target)
            for expression in _comprehension_scope_nodes(child):
                nested.visit(expression)
            for load in nested.load_nodes:
                if load.id not in bound:
                    self.visit_Name(load)

        visit_ListComp = _visit_child
        visit_SetComp = _visit_child
        visit_DictComp = _visit_child
        visit_GeneratorExp = _visit_child

    visitor = ClosureVisitor()
    for target in (generator.target for generator in node.generators):
        visitor.visit(target)
    for expression in _comprehension_scope_nodes(node):
        visitor.visit(expression)
    if enclosing_table.get_type() in ("class", "module"):
        positions = {(item.lineno, item.end_lineno, item.col_offset, item.end_col_offset)
                     for item in visitor.load_nodes if item.id not in local_names}
        names = set()
        loads = _source_cell_loads(source_text, str(source_path))
        for position in positions:
            names.update(loads.get(position, ()))
        return tuple(sorted(names))
    result: list[str] = []
    for name in sorted(visitor.loads - local_names):
        try:
            symbol = enclosing_table.lookup(name)
        except KeyError:
            continue
        if (symbol.is_local() or symbol.is_free() or
                symbol.is_nonlocal()):
            result.append(name)
    return tuple(result)


def _comprehension_plan(
        source_text: str,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        free_cell_names: tuple[str, ...],
        ) -> dict[str, Any]:
    kind = {
        ast.ListComp: "list",
        ast.SetComp: "set",
        ast.DictComp: "dict",
        ast.GeneratorExp: "generator",
    }[type(node)]
    local_names = tuple(sorted({
        name for generator in node.generators
        for name in _target_local_names(generator.target)}))
    generators: list[dict[str, Any]] = []
    for index, generator in enumerate(node.generators):
        generators.append({
            "ordinal": index,
            "iterator": ({
                "mode": "provided-leftmost-iterator",
                "expression": _expression_descriptor(
                    source_text, generator.iter),
            } if index == 0 else {
                "mode": "evaluate-then-get-iterator-in-scope",
                "expression": _expression_descriptor(
                    source_text, generator.iter),
            }),
            "target": _target_descriptor(source_text, generator.target),
            "filters": tuple(_expression_descriptor(source_text, item)
                             for item in generator.ifs),
            "is_async": bool(generator.is_async),
            "step_order": (
                "iterator-next", "target-bind", "filters-left-to-right",
                "descend-next-generator-or-produce"),
        })
    if isinstance(node, ast.DictComp):
        production: dict[str, Any] = {
            "operation": "mapping-setitem",
            "evaluation_order": "key-then-value-then-setitem",
            "key": _expression_descriptor(source_text, node.key),
            "value": _expression_descriptor(source_text, node.value),
        }
    else:
        production = {
            "operation": ({ast.ListComp: "list-append",
                           ast.SetComp: "set-add",
                           ast.GeneratorExp: "yield"}[type(node)]),
            "evaluation_order": "element-then-produce",
            "element": _expression_descriptor(source_text, node.elt),
        }
    plan: dict[str, Any] = {
        "format": EXTENDED_EXPRESSION_SCOPE_FORMAT,
        "kind": kind,
        "ast_sha256": _ast_sha256(node),
        "line": int(node.lineno),
        "column": int(node.col_offset),
        "scope": "separate-implicit-function-scope",
        "local_names": local_names,
        "free_cell_names": free_cell_names,
        "name_resolution": (
            "comprehension-local-then-captured-cell-then-global-builtin"),
        "outer_iterator": (
            "leftmost iterable and iter() evaluated exactly once in creator"),
        "generators": tuple(generators),
        "production": production,
        "loop_order": "depth-first-left-to-right",
        "scope_exit": "target-and-temporary-names-never-leak",
        "exception_protocol": (
            "outer-iterable-or-iter-errors-raise-at-creation",
            "next-target-unpack-filter-inner-iter-production-errors-propagate",
            "iterator-exhaustion-controls-only-its-own-for-loop",
        ),
    }
    if isinstance(node, ast.GeneratorExp):
        plan["resumable_protocol"] = {
            "creation_state": "suspended-before-first-next-with-outer-iterator",
            "next": "resume-until-one-yield-or-completion",
            "yield_resume_point": "after-yield-before-innermost-next",
            "send": (
                "non-None-before-first-yield-TypeError; thereafter-value-"
                "becomes-yield-result"),
            "throw": "inject-at-suspension-point-and-propagate-if-uncaught",
            "close": "inject-GeneratorExit-and-enter-closed-state",
            "completion": "sticky-StopIteration-on-all-later-next-calls",
            "pep479": "escaping-body-StopIteration-becomes-RuntimeError",
        }
    return plan


class _ExtendedObjectExpressionLowerer(ObjectExpressionLowerer):
    """Add lexical function/comprehension objects to the object CFG."""
    def __init__(self, *, source_path: Path, source_text: str,
                 program_id: str,
                 enclosing_function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Module):
        super().__init__(source_path=source_path, source_text=source_text,
                         program_id=program_id)
        self.enclosing_function = enclosing_function
        self.enclosing_table: symtable.SymbolTable | None = None
        self.enclosing_scope_error: str | None = None
        self.enclosing_table_loaded = False

    def lower(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            if not self.enclosing_table_loaded:
                self.enclosing_table_loaded = True
                try:
                    self.enclosing_table = _find_function_symbol_table(
                        self.source_text, self.source_path, self.enclosing_function)
                except (FunctionCFGError, SyntaxError) as error:
                    self.enclosing_scope_error = str(error)
            if self.enclosing_table is None:
                self.unsupported(node, "name lexical scope unresolved: " + str(self.enclosing_scope_error))
            try:
                symbol = self.enclosing_table.lookup(node.id)
            except KeyError:
                self.unsupported(node, "name absent from source symbol table")
            if isinstance(self.enclosing_function, ast.Module) or symbol.is_declared_global():
                return self.emit("load-global-name", (node.id,), "py-value", node,
                                 {"python_resolution": "module-global-then-builtin"})
            if isinstance(self.enclosing_function, ast.ClassDef):
                return self.emit("load-class-free-name" if symbol.is_free() else "load-class-name", (node.id,), "py-value", node,
                                 {"python_resolution": "class-mapping-then-closure-global-builtin"})
            return self.emit("load-name", (node.id,), "py-value", node,
                             {"python_resolution": "lexical-local-closure-global-builtin",
                              "local_only": symbol.is_local()})
        if isinstance(node, ast.Lambda):
            return self.lower_lambda(node)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                             ast.GeneratorExp)):
            return self.lower_comprehension(node)
        return super().lower(node)

    def capture_cells(self, names: tuple[str, ...], node: ast.expr) -> tuple[
            tuple[str, str], ...]:
        result: list[tuple[str, str]] = []
        for name in names:
            cell = self.emit(
                "capture-expression-closure-cell", (name,), "py-cell", node,
                {"capture": "cell-identity", "not_value_snapshot": True})
            result.append((name, cell))
        return tuple(result)

    def load_globals(self, node: ast.expr) -> str:
        return self.emit(
            "load-expression-globals", (), "py-mapping", node,
            {"mapping_identity_preserved": True})

    def lower_lambda(self, node: ast.Lambda) -> str:
        try:
            free_names = _find_lambda_free_names(
                self.source_text, self.source_path, node)
        except (FunctionCFGError, SyntaxError) as error:
            self.unsupported(node, f"lambda lexical scope is unresolved: {error}")
        positional = [*node.args.posonlyargs, *node.args.args]
        default_parameters = positional[
            len(positional) - len(node.args.defaults):]
        positional_defaults = tuple(
            (parameter.arg, self.lower(default))
            for parameter, default in zip(
                default_parameters, node.args.defaults))
        keyword_defaults = tuple(
            (parameter.arg, self.lower(default))
            for parameter, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults)
            if default is not None)
        closure = self.capture_cells(free_names, node)
        globals_mapping = self.load_globals(node)
        body_has_yield = any(isinstance(item, (ast.Yield, ast.YieldFrom))
                             for item in ast.walk(node.body))
        body_has_await = any(isinstance(item, ast.Await)
                             for item in ast.walk(node.body))
        body_kind = ("generator" if body_has_yield else
                     "coroutine" if body_has_await else "ordinary")
        attributes = {
            "format": EXTENDED_EXPRESSION_SCOPE_FORMAT,
            "ast_sha256": _ast_sha256(node),
            "line": int(node.lineno),
            "column": int(node.col_offset),
            "signature": _lambda_signature_descriptor(node),
            "default_expressions": tuple(
                (parameter.arg, _expression_descriptor(self.source_text, default))
                for parameter, default in [*zip(default_parameters, node.args.defaults),
                    *zip(node.args.kwonlyargs, node.args.kw_defaults)] if default is not None),
            "body": _expression_descriptor(self.source_text, node.body),
            "body_kind": body_kind,
            "body_execution": "deferred-until-call",
            "closure_binding": "cell-identity-by-name",
            "default_evaluation_order": (
                "positional-left-to-right-then-keyword-only-left-to-right"),
            "free_cell_names": free_names,
            "function_name": "<lambda>",
            "globals_binding": "mapping-identity",
        }
        attributes["scope_semantic_sha256"] = _json_sha256(attributes)
        return self.emit(
            "make-lambda-function",
            (globals_mapping, positional_defaults, keyword_defaults, closure),
            "py-function", node, attributes)

    def lower_comprehension(
            self, node: ast.ListComp | ast.SetComp | ast.DictComp |
            ast.GeneratorExp) -> str:
        if not node.generators:
            self.unsupported(node, "comprehension has no generator")
        if any(generator.is_async for generator in node.generators):
            self.unsupported(
                node, "async-comprehension suspension protocol is not proved")
        feature_visitor = _ComprehensionScopeNameVisitor()
        for expression in _comprehension_scope_nodes(node):
            feature_visitor.visit(expression)
        if feature_visitor.named_expression is not None:
            self.unsupported(
                feature_visitor.named_expression,
                "comprehension assignment-expression outward binding is not "
                "proved")
        if feature_visitor.await_node is not None:
            self.unsupported(
                feature_visitor.await_node,
                "await inside a comprehension requires async suspension IR")
        try:
            for generator in node.generators:
                _target_descriptor(self.source_text, generator.target)
        except FunctionCFGError as error:
            self.unsupported(node, error.detail)
        if not self.enclosing_table_loaded:
            self.enclosing_table_loaded = True
            try:
                self.enclosing_table = _find_function_symbol_table(
                    self.source_text, self.source_path,
                    self.enclosing_function)
            except (FunctionCFGError, SyntaxError) as error:
                self.enclosing_scope_error = str(error)
        if self.enclosing_table is None:
            self.unsupported(
                node, "enclosing lexical scope is unresolved: " +
                str(self.enclosing_scope_error))
        assert self.enclosing_table is not None
        free_names = _comprehension_free_cell_names(
            node, self.enclosing_table, self.source_text, self.source_path)
        # Python evaluates both the leftmost iterable and iter() immediately,
        # before entering the isolated implicit scope (also for genexpr).
        outer_value = self.lower(node.generators[0].iter)
        outer_iterator = self.emit(
            "python-get-iterator-immediate", (outer_value,), "py-iterator",
            node.generators[0].iter,
            {"evaluation_count": 1,
             "exception_timing": "expression-creation",
             "python_protocol": "iter"})
        closure = self.capture_cells(free_names, node)
        globals_mapping = self.load_globals(node)
        plan = _comprehension_plan(
            self.source_text, node, free_names)
        attributes = {
            "format": EXTENDED_EXPRESSION_SCOPE_FORMAT,
            "plan": plan,
            "plan_semantic_sha256": _json_sha256(plan),
        }
        if isinstance(node, ast.GeneratorExp):
            attributes.update({
                "body_execution": "lazy-on-next-send-throw-close",
                "creation_is_lazy_except_leftmost_iterator": True,
                "result_protocol": "Python-generator-object",
            })
            return self.emit(
                "make-generator-expression",
                (outer_iterator, globals_mapping, closure),
                "py-generator", node, attributes)
        kind = {ast.ListComp: "list", ast.SetComp: "set",
                ast.DictComp: "dict"}[type(node)]
        attributes.update({
            "body_execution": "eager-to-exhaustion",
            "partial_result_on_exception": "discard-and-propagate",
            "result_protocol": f"Python-{kind}-object",
        })
        return self.emit(
            "run-eager-comprehension",
            (outer_iterator, globals_mapping, closure),
            f"py-{kind}", node, attributes)


GENERATOR_FRAME_FORMAT = "pyz80.generator-frame.v1"


class _FunctionSuspensionVisitor(ast.NodeVisitor):
    """Collect suspensions owned by one function, excluding child scopes."""
    def __init__(self) -> None:
        self.nodes: list[ast.Yield | ast.YieldFrom] = []

    def visit_Yield(self, node: ast.Yield) -> None:  # noqa: N802
        self.nodes.append(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:  # noqa: N802
        self.nodes.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(  # noqa: N802
            self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return


def _function_suspension_nodes(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> tuple[ast.Yield | ast.YieldFrom, ...]:
    visitor = _FunctionSuspensionVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return tuple(visitor.nodes)


def _yield_from_protocol() -> dict[str, str]:
    """PEP 380 delegation contract carried by a target-neutral terminator."""
    return {
        "initial": "next(delegate)",
        "yield": "delegate-value-suspends-outward-with-delegation-state",
        "resume-none": "next(delegate)",
        "resume-value": "delegate.send(value)",
        "missing-send": "AttributeError-propagates",
        "throw-generator-exit": (
            "delegate.close-if-present-then-reraise-GeneratorExit"),
        "throw-other": (
            "delegate.throw-if-present-else-reraise-into-delegator"),
        "stop-iteration": "complete-with-StopIteration.value",
        "other-exception": "propagate-at-yield-from-site",
        "close": "same-as-throw-GeneratorExit",
    }


class _FunctionLowerer:
    def __init__(
            self, *, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Module,
            class_name: str | None, source_path: Path, source_text: str,
            fragments: Mapping[ast.AST, ObjectStoreFragmentIR],
            ) -> None:
        self.node = node
        self.class_name = class_name
        self.source_path = source_path
        self.source_text = source_text
        owner = f"{class_name}." if class_name is not None else ""
        self.is_module = isinstance(node, ast.Module)
        self.is_class = isinstance(node, ast.ClassDef)
        self.class_qualname = node.name if self.is_class else None
        self.function_name = "<module>" if self.is_module else node.name
        self.definition_line = 1 if self.is_module else node.lineno
        self.function_id = f"{owner}{self.function_name}@{self.definition_line}"
        try:
            table = _find_function_symbol_table(source_text, source_path, node)
            self.global_store_names = {symbol.get_name() for symbol in table.get_symbols()
                                       if symbol.is_declared_global()}
        except (FunctionCFGError, SyntaxError):
            self.global_store_names = set()  # Expression lowering reports unresolved scopes.
        self.fragments = dict(fragments)
        self.blocks: dict[str, _Block] = {}
        self.current: _Block | None = None
        self.block_counter = 0
        self.temp_counter = 0
        self.sequence_counter = 0
        self.expression_counter = 0
        self.expression_programs: list[ObjectExpressionIR] = []
        self.blockers: list[PythonFunctionCFGBlocker] = []
        self.break_targets: list[_ControlTarget] = []
        self.continue_targets: list[_ControlTarget] = []
        self.exception_target: str | None = None
        self.finalizers: list[_FinalizerContext] = []
        self.visited_sites: list[int] = []
        self.suspension_nodes = _function_suspension_nodes(node)
        self.is_generator = (
            bool(self.suspension_nodes) and
            not isinstance(node, ast.AsyncFunctionDef))
        self.generator_state_counter = 0
        self.generator_frame_states: list[dict[str, Any]] = []
        self.generator_scope_error: str | None = None
        self.generator_local_names: tuple[str, ...] = ()
        if self.is_generator:
            try:
                table = _find_function_symbol_table(
                    source_text, source_path, node)
                if not hasattr(table, "get_locals"):
                    raise FunctionCFGError(
                        "PZFC114", "generator symbol table has no locals API")
                self.generator_local_names = tuple(sorted(table.get_locals()))
            except (FunctionCFGError, SyntaxError) as error:
                self.generator_scope_error = str(error)

    def span(self, node: ast.AST) -> SourceSpan:
        return SourceSpan.from_node(self.source_path, node)

    def new_block(
            self, stem: str, *,
            exception_target: str | None | object = _INHERIT_EXCEPTION,
            ) -> _Block:
        name = f"{stem}_{self.block_counter:04d}"
        self.block_counter += 1
        inherited = (self.exception_target
                     if exception_target is _INHERIT_EXCEPTION
                     else exception_target)
        assert inherited is None or isinstance(inherited, str)
        block = _Block(name, [], exception_target=inherited)
        self.blocks[name] = block
        return block

    def set_current(self, block: _Block | None) -> None:
        self.current = block

    def emit(
            self, op: str, arguments: tuple[Any, ...], node: ast.AST,
            *, value_kind: str | None = None,
            attributes: Mapping[str, Any] | None = None,
            ) -> str | None:
        if self.current is None or self.current.terminator is not None:
            raise FunctionCFGError(
                "PZFC101", f"instruction after terminator in "
                f"{self.function_id}:{getattr(node, 'lineno', 0)}")
        destination: str | None = None
        if op == "store-name" and (self.is_module or arguments[0] in self.global_store_names):
            op = "store-global-name"
        elif op == "store-name" and self.is_class:
            op = "store-class-name"
        if value_kind is not None:
            destination = f"%fn_{self.temp_counter}"
            self.temp_counter += 1
        self.current.instructions.append(ObjectEffectInstruction(
            sequence=self.sequence_counter,
            op=op,
            destination=destination,
            arguments=arguments,
            value_kind=value_kind,
            span=self.span(node),
            attributes=tuple(sorted((attributes or {}).items())),
        ))
        self.sequence_counter += 1
        return destination

    def terminate(self, op: str, arguments: tuple[Any, ...],
                  targets: tuple[str, ...], node: ast.AST) -> None:
        if self.current is None or self.current.terminator is not None:
            raise FunctionCFGError(
                "PZFC102", f"duplicate terminator in {self.function_id}")
        self.current.terminator = PythonFunctionTerminator(
            op=op, arguments=arguments, targets=targets,
            span=self.span(node))

    def add_blocker(self, code: str, message: str, node: ast.AST,
                    *, span: SourceSpan | None = None) -> int:
        blocker = PythonFunctionCFGBlocker(
            code=code,
            message=message,
            node_kind=type(node).__name__,
            span=span or self.span(node),
            ast_sha256=_ast_sha256(node),
            source=_source(self.source_text, node),
        )
        self.blockers.append(blocker)
        return len(self.blockers) - 1

    def lower_expression(self, node: ast.expr) -> str:
        program_id = (
            f"{self.function_id}:expression:{self.expression_counter:04d}")
        self.expression_counter += 1
        try:
            program = _ExtendedObjectExpressionLowerer(
                source_path=self.source_path,
                source_text=self.source_text,
                program_id=program_id,
                enclosing_function=self.node,
            ).build(node)
            _validate_extended_expression_program(
                program, owner=node, source_text=self.source_text)
        except CompileError as error:
            diagnostic = error.diagnostic
            blocker_index = self.add_blocker(
                diagnostic.code, diagnostic.message, node,
                span=diagnostic.span or self.span(node))
            destination = self.emit(
                "blocked-expression", (blocker_index,), node,
                value_kind="py-blocked",
                attributes={
                    "non_executable": True,
                    "root_ast_sha256": _ast_sha256(node),
                })
            assert destination is not None
            return destination
        self.expression_programs.append(program)
        destination = self.emit(
            "execute-expression-cfg", (program.program_id,), node,
            value_kind=program.result_kind,
            attributes={
                "program_result": program.result,
                "program_semantic_sha256": program.semantic_sha256,
                "single_evaluation": True,
            })
        assert destination is not None
        return destination

    def _new_generator_frame_state(
            self, node: ast.Yield | ast.YieldFrom, *,
            resume_target: str, spill_slots: tuple[str, ...] = (),
            operand_stack_slots: int = 0,
            ) -> dict[str, Any]:
        if not self.is_generator or self.generator_scope_error is not None:
            raise FunctionCFGError(
                "PZFC115", "generator frame requested without a proved "
                "lexical generator scope")
        self.generator_state_counter += 1
        state = self.generator_state_counter
        loop_depth = len(self.break_targets)
        finalizer_depth = len(self.finalizers)
        exception_slots = 1 if (
            self.current is not None and
            self.current.exception_target is not None) else 0
        bounded_slot_count = (
            len(self.generator_local_names) +  # lexical locals/cells
            1 +  # instruction/state slot
            1 +  # resume command/value slot
            loop_depth + finalizer_depth + exception_slots +
            len(spill_slots))
        descriptor: dict[str, Any] = {
            "format": GENERATOR_FRAME_FORMAT,
            "state": state,
            "suspension_kind": (
                "yield-from" if isinstance(node, ast.YieldFrom) else
                "yield"),
            "source_ast_sha256": _ast_sha256(node),
            "line": int(node.lineno),
            "column": int(node.col_offset),
            "resume_target": resume_target,
            "local_slots": self.generator_local_names,
            "loop_stack": tuple(
                (break_target.name, continue_target.name)
                for break_target, continue_target in zip(
                    self.break_targets, self.continue_targets)),
            "finalizer_stack": tuple(context.label
                                     for context in self.finalizers),
            "exception_target": (self.current.exception_target
                                 if self.current is not None else None),
            "operand_stack_slots": operand_stack_slots,
            "spill_slots": spill_slots,
            "bounded_slot_count": bounded_slot_count,
            "bounded_by_source_ast": True,
        }
        self.generator_frame_states.append(descriptor)
        return descriptor

    def lower_yield(self, node: ast.Yield) -> str:
        """Lower a root yield expression to one explicit suspend state."""
        if node.value is None:
            yielded = self.emit(
                "constant", (None,), node, value_kind="py-none")
            assert yielded is not None
        else:
            yielded = self.lower_expression(node.value)
        if self.current is None:
            raise FunctionCFGError("PZFC116", "yield has no source block")
        suspension_exception_target = self.current.exception_target
        resume = self.new_block(
            "generator_resume",
            exception_target=suspension_exception_target)
        descriptor = self._new_generator_frame_state(
            node, resume_target=resume.name)
        state = int(descriptor["state"])
        self.emit(
            "generator-save-frame", (state, descriptor), node,
            attributes={
                "evaluation_stack_empty_at_suspend": True,
                "locals_and_control_state_by_identity": True,
            })
        self.terminate(
            "suspend-yield", (yielded, state), (resume.name,), node)
        self.set_current(resume)
        self.emit(
            "generator-restore-frame", (state, descriptor), node,
            attributes={
                "restore_before_resume_command": True,
                "same_frame_object": True,
            })
        resumed = self.emit(
            "generator-resume-value", (state,), node,
            value_kind="py-value",
            attributes={
                "close": "raise-GeneratorExit-at-yield-site",
                "next": "result-is-None",
                "send": "result-is-sent-value",
                "throw": "raise-injected-exception-at-yield-site",
            })
        assert resumed is not None
        return resumed

    def lower_yield_from(self, node: ast.YieldFrom) -> str:
        """Lower PEP 380 delegation as an explicit resumable terminator."""
        iterable = self.lower_expression(node.value)
        delegate = self.emit(
            "generator-delegation-start", (iterable,), node,
            value_kind="py-delegation-iterator",
            attributes={
                "evaluation_count": 1,
                "python_protocol": "iter",
                "start_before_first-delegate-next": True,
            })
        assert delegate is not None
        if self.current is None:
            raise FunctionCFGError(
                "PZFC116", "yield from has no source block")
        suspension_exception_target = self.current.exception_target
        complete = self.new_block(
            "generator_delegate_complete",
            exception_target=suspension_exception_target)
        descriptor = self._new_generator_frame_state(
            node, resume_target=complete.name,
            spill_slots=(delegate,), operand_stack_slots=1)
        state = int(descriptor["state"])
        self.emit(
            "generator-save-frame", (state, descriptor), node,
            attributes={
                "evaluation_stack_empty_at_suspend": False,
                "locals_and_control_state_by_identity": True,
            })
        self.terminate(
            "suspend-yield-from",
            (delegate, state, _yield_from_protocol()),
            (complete.name,), node)
        self.set_current(complete)
        self.emit(
            "generator-restore-frame", (state, descriptor), node,
            attributes={
                "restore_before_resume_command": True,
                "same_frame_object": True,
            })
        result = self.emit(
            "generator-yield-from-result", (state,), node,
            value_kind="py-value",
            attributes={
                "result": "StopIteration.value",
                "available_only_after_delegate_exhaustion": True,
            })
        assert result is not None
        return result

    def _finalize_generator_frame_states(
            self, blocks: tuple[PythonFunctionBlock, ...]) -> None:
        """Bind each suspension to the exact SSA values live across it.

        Lexical locals live in named frame slots.  Compiler SSA temporaries
        (notably a ``for`` iterator) are separate: standard backward
        liveness over the finished CFG proves the finite set which must keep
        object identity while the generator is suspended.  ``yield from``'s
        delegate is additionally live inside its repeated protocol state.
        """
        if not self.is_generator or not self.generator_frame_states:
            return
        by_name = {block.name: block for block in blocks}
        definitions: dict[str, int] = {}
        use: dict[str, set[str]] = {}
        defined: dict[str, set[str]] = {}
        successors: dict[str, tuple[str, ...]] = {}
        for block in blocks:
            block_use: set[str] = set()
            block_defined: set[str] = set()
            for item in block.instructions:
                for value in _ssa_values(item.arguments):
                    if value not in block_defined:
                        block_use.add(value)
                if item.destination is not None:
                    block_defined.add(item.destination)
                    definitions[item.destination] = item.sequence
            for value in _ssa_values(block.terminator.arguments):
                if value not in block_defined:
                    block_use.add(value)
            use[block.name] = block_use
            defined[block.name] = block_defined
            targets = list(block.terminator.targets)
            if block.exception_target is not None:
                targets.append(block.exception_target)
            successors[block.name] = tuple(targets)

        live_in = {name: set(values) for name, values in use.items()}
        live_out = {name: set() for name in by_name}
        changed = True
        while changed:
            changed = False
            for block in reversed(blocks):
                outgoing: set[str] = set()
                for target in successors[block.name]:
                    outgoing.update(live_in[target])
                incoming = use[block.name] | (
                    outgoing - defined[block.name])
                if (outgoing != live_out[block.name] or
                        incoming != live_in[block.name]):
                    live_out[block.name] = outgoing
                    live_in[block.name] = incoming
                    changed = True

        descriptors = {
            int(item["state"]): item
            for item in self.generator_frame_states}
        for block in blocks:
            terminator = block.terminator
            if terminator.op not in {"suspend-yield",
                                     "suspend-yield-from"}:
                continue
            state = int(terminator.arguments[1])
            descriptor = descriptors[state]
            spill_values = set(descriptor["spill_slots"])
            spill_values.update(live_in[terminator.targets[0]])
            unknown = spill_values - definitions.keys()
            if unknown:
                raise FunctionCFGError(
                    "PZFC117", f"generator state {state} has undefined "
                    f"live values {sorted(unknown)}")
            ordered = tuple(sorted(
                spill_values, key=lambda value: definitions[value]))
            descriptor["spill_slots"] = ordered
            descriptor["bounded_slot_count"] = (
                len(descriptor["local_slots"]) + 2 +
                len(descriptor["loop_stack"]) +
                len(descriptor["finalizer_stack"]) +
                (1 if descriptor["exception_target"] is not None else 0) +
                len(ordered))

    def lower_suspending_expression(
            self, node: ast.Yield | ast.YieldFrom) -> str:
        if self.generator_scope_error is not None:
            blocker = self.add_blocker(
                "PZFC211", "generator lexical frame is unresolved: " +
                self.generator_scope_error, node)
            blocked = self.emit(
                "blocked-expression", (blocker,), node,
                value_kind="py-blocked",
                attributes={"non_executable": True,
                            "root_ast_sha256": _ast_sha256(node)})
            assert blocked is not None
            return blocked
        if isinstance(node, ast.Yield):
            return self.lower_yield(node)
        return self.lower_yield_from(node)

    def function_signature(self) -> dict[str, Any]:
        if self.is_module:
            return {"async": False, "parameters": [], "decorators": [], "returns": None,
                    "execution_kind": "module-body", "namespace": "module-mapping"}
        if self.is_class:
            return {"async": False, "parameters": [], "decorators": [], "returns": None,
                    "execution_kind": "class-body", "namespace": "class-mapping"}
        signature = _function_signature(self.node, self.source_text)
        if not self.is_generator:
            return signature
        max_slots = max(
            (int(item["bounded_slot_count"])
             for item in self.generator_frame_states),
            default=len(self.generator_local_names) + 2)
        max_operand = max(
            (int(item["operand_stack_slots"])
             for item in self.generator_frame_states), default=0)
        signature.update({
            "execution_kind": "generator-frame",
            "invocation": "return-generator-object-without-running-body",
            "first_resume": {
                "next": "enter-body-with-None",
                "send-none": "enter-body-with-None",
                "send-non-none": "TypeError-before-body",
                "throw": "raise-at-function-entry",
                "close": "complete-without-running-body",
            },
            "completion": (
                "return-or-fallthrough-closes-frame-and-raises-"
                "StopIteration(return-value)"),
            "source_suspension_count": len(self.suspension_nodes),
            "source_yield_from_count": sum(
                isinstance(item, ast.YieldFrom)
                for item in self.suspension_nodes),
            "lowered_suspension_state_count": len(
                self.generator_frame_states),
            "yield_from_state_count": sum(
                item["suspension_kind"] == "yield-from"
                for item in self.generator_frame_states),
            "frame": {
                "format": GENERATOR_FRAME_FORMAT,
                "local_slots": self.generator_local_names,
                "state_slot_count": 1,
                "resume_command_value_slot_count": 1,
                "max_operand_stack_slots": max_operand,
                "bounded_slot_count": max_slots,
                "bounded_by_source_ast": True,
                "states": tuple(self.generator_frame_states),
            },
        })
        return signature

    def lower_index(self, node: ast.expr | ast.slice) -> str:
        if isinstance(node, ast.Slice):
            parts: list[str] = []
            for part in (node.lower, node.upper, node.step):
                if part is None:
                    value = self.emit(
                        "constant", (None,), node, value_kind="py-none")
                    assert value is not None
                    parts.append(value)
                else:
                    parts.append(self.lower_expression(part))
            result = self.emit(
                "build-slice", tuple(parts), node, value_kind="py-slice",
                attributes={"evaluation_order": "lower-upper-step"})
            assert result is not None
            return result
        assert isinstance(node, ast.expr)
        return self.lower_expression(node)

    def lower_store_target(self, target: ast.expr, value: str) -> None:
        if isinstance(target, ast.Name):
            self.emit("store-name", (target.id, value), target,
                      attributes={"python_store": True})
            return
        if isinstance(target, ast.Attribute):
            receiver = self.lower_expression(target.value)
            self.emit(
                "store-attribute", (receiver, target.attr, value), target,
                attributes={"python_store": True})
            return
        if isinstance(target, ast.Subscript):
            container = self.lower_expression(target.value)
            index = self.lower_index(target.slice)
            self.emit(
                "store-subscript", (container, index, value), target,
                attributes={"python_store": True})
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            starred = [index for index, item in enumerate(target.elts)
                       if isinstance(item, ast.Starred)]
            if len(starred) > 1:
                blocker = self.add_blocker(
                    "PZFC203", "multiple starred assignment targets", target)
                self.emit("blocked-store-target", (blocker, value), target,
                          attributes={"non_executable": True})
                return
            if starred:
                star_index = starred[0]
                unpacked = self.emit(
                    "unpack-extended", (value, star_index,
                                        len(target.elts) - star_index - 1),
                    target, value_kind="unpacked-values",
                    attributes={"python_protocol": "UNPACK_EX"})
            else:
                unpacked = self.emit(
                    "unpack-sequence", (value, len(target.elts)), target,
                    value_kind="unpacked-values",
                    attributes={"python_protocol": "UNPACK_SEQUENCE"})
            assert unpacked is not None
            unpacked_values: list[str] = []
            for index, item in enumerate(target.elts):
                if starred and index == starred[0]:
                    op = "unpack-star-item"
                    arguments = (unpacked, index)
                    kind = "py-list"
                elif starred and index > starred[0]:
                    op = "unpack-item-from-end"
                    arguments = (unpacked, len(target.elts) - index)
                    kind = "py-value"
                else:
                    op = "unpack-item"
                    arguments = (unpacked, index)
                    kind = "py-value"
                item_value = self.emit(op, arguments, item, value_kind=kind)
                assert item_value is not None
                unpacked_values.append(item_value)
            for item, item_value in zip(target.elts, unpacked_values):
                actual_target = item.value if isinstance(item, ast.Starred) else item
                self.lower_store_target(actual_target, item_value)
            return
        blocker = self.add_blocker(
            "PZFC203", "unsupported assignment target", target)
        self.emit("blocked-store-target", (blocker, value), target,
                  attributes={"non_executable": True})

    def lower_delete_target(self, target: ast.expr) -> None:
        """Lower one ``del`` target in Python's left-to-right order."""
        if isinstance(target, ast.Name):
            self.emit(
                "delete-name", (target.id,), target,
                attributes={
                    "python_delete": True,
                    "scope_resolution": "compiled-lexical-symbol-table",
                })
            return
        if isinstance(target, ast.Attribute):
            receiver = self.lower_expression(target.value)
            self.emit(
                "delete-attribute", (receiver, target.attr), target,
                attributes={
                    "python_delete": True,
                    "receiver_evaluated_once": True,
                })
            return
        if isinstance(target, ast.Subscript):
            container = self.lower_expression(target.value)
            index = self.lower_index(target.slice)
            self.emit(
                "delete-subscript", (container, index), target,
                attributes={
                    "container_then_index": True,
                    "operands_evaluated_once": True,
                    "python_delete": True,
                })
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.lower_delete_target(item)
            return
        blocker = self.add_blocker(
            "PZFC207", "unsupported delete target", target)
        self.emit(
            "blocked-delete-target", (blocker,), target,
            attributes={"non_executable": True})

    def lower_assert(self, node: ast.Assert) -> None:
        """Preserve assert's branch and failure-only message evaluation."""
        condition = self.lower_expression(node.test)
        passed = self.new_block("assert_pass")
        failed = self.new_block("assert_fail")
        self.terminate(
            "branch-truth", (condition,),
            (passed.name, failed.name), node.test)
        self.set_current(failed)
        arguments: tuple[str, ...] = ()
        if node.msg is not None:
            arguments = (self.lower_expression(node.msg),)
        exception = self.emit(
            "construct-assertion-error", arguments, node,
            value_kind="py-exception",
            attributes={
                "builtin": "AssertionError",
                "message_evaluated_on_failure_only": True,
                "python_optimize_level": 0,
            })
        assert exception is not None
        self.terminate("raise-explicit", (exception,), (), node)
        self.set_current(passed)

    def lower_import(self, node: ast.Import) -> None:
        """Lower every alias as one ordered ``__import__`` operation."""
        for alias in node.names:
            imported = self.emit(
                "python-import-module",
                (alias.name, 0, (), "root-package"), node,
                value_kind="py-value",
                attributes={
                    "current_frame_globals_locals": True,
                    "import_hook": "builtins.__import__",
                    "single_import_call": True,
                })
            assert imported is not None
            if alias.asname:
                # IMPORT_NAME with an empty fromlist returns the root. Dotted
                # aliases traverse IMPORT_FROM, including rebound attributes
                # and the circular-import cache fallback; returning the cached
                # leaf directly is observably different Python semantics.
                for component in alias.name.split(".")[1:]:
                    imported = self.emit("python-import-from", (imported, component), node,
                        value_kind="py-value", attributes={
                            "attribute_then_sys_modules_fallback": True,
                            "python_opcode_semantics": "IMPORT_FROM"})
                    assert imported is not None
            binding = alias.asname or alias.name.split(".", 1)[0]
            self.emit(
                "store-name", (binding, imported), node,
                attributes={
                    "import_binding": True,
                    "python_store": True,
                })

    def lower_import_from(self, node: ast.ImportFrom) -> None:
        """Lower IMPORT_NAME once, then ordered IMPORT_FROM bindings."""
        from_names = tuple(alias.name for alias in node.names)
        imported = self.emit(
            "python-import-module",
            (node.module, node.level, from_names, "fromlist-module"), node,
            value_kind="py-value",
            attributes={
                "current_frame_globals_locals": True,
                "import_hook": "builtins.__import__",
                "single_import_call": True,
            })
        assert imported is not None
        for alias in node.names:
            if alias.name == "*":
                self.emit(
                    "python-import-star", (imported,), node,
                    attributes={
                        "binding_namespace": "current-locals",
                        "names_rule": "__all__-else-public-module-names",
                    })
                continue
            value = self.emit(
                "python-import-from", (imported, alias.name), node,
                value_kind="py-value",
                attributes={
                    "attribute_then_sys_modules_fallback": True,
                    "python_opcode_semantics": "IMPORT_FROM",
                })
            assert value is not None
            self.emit(
                "store-name", (alias.asname or alias.name, value), node,
                attributes={
                    "import_binding": True,
                    "python_store": True,
                })

    def lower_class(self, node: ast.ClassDef) -> None:
        """Execute the original suite in its own mapping, never a def wrapper."""
        _find_function_symbol_table(self.source_text, self.source_path, node)
        def identifiers(item):
            if isinstance(item, ast.Name): return (item.id,)
            if isinstance(item, ast.Attribute): return (item.attr,)
            if isinstance(item, ast.arg): return (item.arg,)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return (item.name,)
            if isinstance(item, (ast.Global, ast.Nonlocal)): return item.names
            if isinstance(item, ast.alias): return (item.asname or item.name.split('.')[0],)
            return ()
        private = any(name.startswith('__') and not name.endswith('__')
                      for item in ast.walk(node) for name in identifiers(item))
        class_code = _class_code(node, self.source_text, self.source_path)
        explicit_classcell = any(isinstance(item, ast.Name) and item.id == "__classcell__" for item in ast.walk(node))
        if any(isinstance(base, ast.Starred) for base in node.bases) or node.keywords or getattr(node, "type_params", ()) or private or explicit_classcell:
            blocker = self.add_blocker("PZFC214", "expanded bases/metaclass, private mangling or explicit __classcell__ manipulation is not lowered", node)
            self.emit("blocked-class-definition", (blocker,), node, attributes={"non_executable": True})
            return
        decorators = [self.lower_expression(item) for item in node.decorator_list]
        closure = []
        for name in sorted(class_code.co_freevars):
            cell = self.emit("capture-closure-cell", (name,), node, value_kind="py-cell",
                             attributes={"capture": "cell-identity", "not_value_snapshot": True})
            closure.append((name, cell))
        mapping = self.emit("load-current-globals", (), node, value_kind="py-mapping",
                            attributes={"mapping_identity_preserved": True})
        body = self.emit("make-class-body", (f"{node.name}@{node.lineno}", _ast_sha256(node), mapping, tuple(closure)),
                         node, value_kind="py-function", attributes={"body_execution": "class-suite", "source_sealed": True,
                             "implicit_class_cell": "__class__" in class_code.co_cellvars})
        bases = tuple(self.lower_expression(base) for base in node.bases)
        value = self.emit("python-build-class", (body, node.name, *bases), node, value_kind="py-value",
                          attributes={"namespace": "new-class-mapping", "implicit_object_base": not bases,
                                      "base_evaluation": "left-to-right", "method_resolution": "C3"})
        for decorator_node, decorator in reversed(list(zip(node.decorator_list, decorators))):
            value = self.emit("python-apply-decorator", (decorator, value), decorator_node, value_kind="py-value",
                             attributes={"application_order": "bottom-up", "decorator_expression_pre_evaluated": True,
                                         "single_positional_function_argument": True})
        self.emit("store-name", (node.name, value), node, attributes={"python_store": True})

    def lower_nested_function(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Create a nested function without executing its body.

        Decorator expressions are evaluated top-to-bottom before defaults;
        decorator calls are then applied bottom-to-top.  Closure cells are
        captured by identity, never snapshotted as values.
        """
        if getattr(node, "type_params", ()):
            blocker = self.add_blocker(
                "PZFC208", "generic type-parameter definition protocol "
                "is not lowered", node)
            self.emit(
                "blocked-function-definition", (blocker,), node,
                attributes={"non_executable": True})
            return
        annotations = _annotation_descriptors(node, self.source_text)
        future_annotations = _future_annotations_enabled(self.source_text)
        try:
            free_names = _nested_function_free_names(
                self.source_text, self.source_path, node)
        except (FunctionCFGError, SyntaxError) as error:
            blocker = self.add_blocker(
                "PZFC210", f"nested lexical scope is unresolved: {error}",
                node)
            self.emit(
                "blocked-function-definition", (blocker,), node,
                attributes={"non_executable": True})
            return

        decorators = [self.lower_expression(item)
                      for item in node.decorator_list]
        positional_parameters = [
            *node.args.posonlyargs, *node.args.args]
        default_parameters = positional_parameters[
            len(positional_parameters) - len(node.args.defaults):]
        positional_defaults = tuple(
            (parameter.arg, self.lower_expression(default))
            for parameter, default in zip(
                default_parameters, node.args.defaults))
        keyword_defaults = tuple(
            (parameter.arg, self.lower_expression(default))
            for parameter, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults)
            if default is not None)
        # CPython 3.12 evaluates ordinary positional annotations BEFORE
        # positional-only annotations, then vararg/kw-only/kwarg/return.
        # Defaults precede all annotations; decorators observe the final dict.
        annotation_nodes = {arg.arg: arg.annotation for arg in
            [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
             *([node.args.vararg] if node.args.vararg else []),
             *([node.args.kwarg] if node.args.kwarg else [])] if arg.annotation is not None}
        if node.returns is not None:
            annotation_nodes['return'] = node.returns
        annotation_values = []
        for name, _, _ in annotations:
            expression = annotation_nodes[name]
            if future_annotations:
                value = self.lower_expression(ast.copy_location(
                    ast.Constant(_postponed_annotation_string(expression, self.source_path)), expression))
            else:
                value = self.lower_expression(expression)
            annotation_values.extend((name, value))
        closure: list[tuple[str, str]] = []
        for name in free_names:
            cell = self.emit(
                "capture-closure-cell", (name,), node,
                value_kind="py-cell",
                attributes={
                    "capture": "cell-identity",
                    "not_value_snapshot": True,
                })
            assert cell is not None
            closure.append((name, cell))
        globals_mapping = self.emit(
            "load-current-globals", (), node,
            value_kind="py-mapping",
            attributes={"mapping_identity_preserved": True})
        assert globals_mapping is not None
        definition_ast_sha256 = _ast_sha256(node)
        function = self.emit(
            "make-function",
            (
                f"{node.name}@{node.lineno}",
                definition_ast_sha256,
                ("async-function" if isinstance(
                    node, ast.AsyncFunctionDef) else "function"),
                globals_mapping,
                positional_defaults,
                keyword_defaults,
                tuple(closure),
                annotations,
            ),
            node, value_kind="py-function",
            attributes={
                "annotation_mode": (
                    ("future-stringized" if future_annotations else "evaluated-cpython-3.12") if annotations else "none"),
                "async": isinstance(node, ast.AsyncFunctionDef),
                "body_execution": "deferred-until-call",
                "closure_binding": "cell-identity-by-name",
                "definition_evaluation_order": (
                    "decorators-top-down;positional-defaults-left-to-right;"
                    "keyword-only-defaults-left-to-right;annotations-cpython-3.12;make;"
                    "decorators-bottom-up;bind"),
                "globals_binding": "mapping-identity",
                "lexical_qualname": True,
            })
        assert function is not None
        if annotation_values:
            mapping = self.emit('build-function-annotations', tuple(annotation_values), node,
                                value_kind='py-dict', attributes={'order': 'cpython-3.12'})
            self.emit('store-attribute', (function, '__annotations__', mapping), node)
        for decorator_node, decorator in reversed(list(zip(
                node.decorator_list, decorators))):
            decorated = self.emit(
                "python-apply-decorator", (decorator, function),
                decorator_node, value_kind="py-value",
                attributes={
                    "application_order": "bottom-up",
                    "decorator_expression_pre_evaluated": True,
                    "single_positional_function_argument": True,
                })
            assert decorated is not None
            function = decorated
        self.emit(
            "store-name", (node.name, function), node,
            attributes={
                "function_definition_binding": True,
                "python_store": True,
            })

    def lower_augassign(self, node: ast.AugAssign) -> None:
        operator = _BINARY_OPERATOR_NAMES.get(type(node.op))
        if operator is None:
            blocker = self.add_blocker(
                "PZFC204", "unsupported augmented operator", node)
            self.emit("blocked-statement", (blocker,), node,
                      attributes={"non_executable": True})
            return
        target = node.target
        receiver: str | None = None
        index: str | None = None
        if isinstance(target, ast.Name):
            old = self.lower_expression(target)
        elif isinstance(target, ast.Attribute):
            receiver = self.lower_expression(target.value)
            old = self.emit(
                "load-attribute", (receiver, target.attr), target,
                value_kind="py-value")
            assert old is not None
        elif isinstance(target, ast.Subscript):
            receiver = self.lower_expression(target.value)
            index = self.lower_index(target.slice)
            old = self.emit(
                "load-subscript", (receiver, index), target,
                value_kind="py-value")
            assert old is not None
        else:
            blocker = self.add_blocker(
                "PZFC204", "unsupported augmented assignment target", target)
            self.emit("blocked-statement", (blocker,), node,
                      attributes={"non_executable": True})
            return
        rhs = self.lower_expression(node.value)
        value = self.emit(
            "python-inplace-binary", (operator, old, rhs), node,
            value_kind="py-value",
            attributes={"receiver_old_rhs_evaluated_once": True})
        assert value is not None
        if isinstance(target, ast.Name):
            self.emit("store-name", (target.id, value), target,
                      attributes={"python_store": True})
        elif isinstance(target, ast.Attribute):
            assert receiver is not None
            self.emit("store-attribute", (receiver, target.attr, value),
                      target, attributes={"python_store": True,
                                          "reuses_receiver": True})
        else:
            assert receiver is not None and index is not None
            self.emit("store-subscript", (receiver, index, value), target,
                      attributes={"python_store": True,
                                  "reuses_receiver_and_index": True})

    def _lower_finalizer_body(
            self, context: _FinalizerContext, owner: ast.AST) -> None:
        if context.kind == "handler":
            self.emit(
                "end-except-handler", (), owner,
                attributes={"restores_previous_exception_context": True})
            if context.handler_name is not None:
                self.emit(
                    "clear-except-target", (context.handler_name,), owner,
                    attributes={
                        "python_handler_target_cleanup": True,
                        "set_none_then_delete": True,
                    })
            return
        if context.kind == "with":
            if (context.with_manager is None or
                    context.with_exit is None or
                    context.with_owner is None):
                raise FunctionCFGError(
                    "PZFC118", "with finalizer lacks its entered manager")
            result = self.emit(
                "python-with-call-exit-normal",
                (context.with_exit, None, None, None),
                context.with_owner, value_kind="py-value",
                attributes={
                    "exception_arguments": "None,None,None",
                    "return_value_ignored": True,
                    "special_method_call": "saved-bound-__exit__(None,None,None)",
                })
            assert result is not None
            return
        self.lower_statements(list(context.statements))

    def _route_transfer(
            self, kind: str, node: ast.AST, *,
            payload: tuple[str, ...] = (), target: str | None = None,
            finalizer_depth: int = 0,
            ) -> None:
        """Route a non-exception exit through only the scopes it leaves.

        ``finalizer_depth`` is the lexical finalizer-stack depth retained at
        the destination.  This distinction is essential: a ``continue`` in a
        loop nested *inside* a try suite must not execute that try's finally,
        while a ``continue`` from a try nested inside an outer loop must.
        Exception transfers do not use this routine; their exact next unwind
        scope is the block's ``exception_target``.
        """
        if self.current is None:
            raise FunctionCFGError(
                "PZFC105", f"missing source block for {kind} transfer")
        if not 0 <= finalizer_depth <= len(self.finalizers):
            raise FunctionCFGError(
                "PZFC106", f"invalid finalizer depth {finalizer_depth} for "
                f"{kind} transfer at depth {len(self.finalizers)}")
        if len(self.finalizers) > finalizer_depth:
            context = self.finalizers.pop()
            source_block = self.current
            clone = self.new_block(
                f"{context.label}_{kind}",
                exception_target=context.outer_exception_target)
            self.set_current(source_block)
            self.terminate("jump", (), (clone.name,), node)
            saved_exception_target = self.exception_target
            self.exception_target = context.outer_exception_target
            self.set_current(clone)
            self._lower_finalizer_body(context, node)
            if self.current is not None:
                self._route_transfer(
                    kind, node, payload=payload, target=target,
                    finalizer_depth=finalizer_depth)
            self.exception_target = saved_exception_target
            self.finalizers.append(context)
            self.set_current(None)
            return
        if kind in {"normal", "jump"}:
            if target is None:
                raise FunctionCFGError(
                    "PZFC106", f"{kind} transfer lacks target")
            self.terminate("jump", (), (target,), node)
        elif kind == "return":
            self.terminate(
                "generator-return" if self.is_generator else "return",
                payload, (), node)
        else:
            raise FunctionCFGError(
                "PZFC106", f"unknown control transfer {kind!r}")
        self.set_current(None)

    def _compile_exception_finalizer(
            self, context: _FinalizerContext, owner: ast.AST) -> None:
        saved_exception_target = self.exception_target
        self.exception_target = context.outer_exception_target
        self.set_current(context.exception_block)
        exception = self.emit(
            "capture-current-exception", (), owner,
            value_kind="py-exception",
            attributes={"preserved_across_finalizer": True})
        assert exception is not None
        self._lower_finalizer_body(context, owner)
        if self.current is not None:
            # Exceptional propagation follows the explicit exceptional edge.
            # Unwinding every lexically active finalizer here is wrong when an
            # enclosing try has a handler which may catch this exception.
            self.terminate("raise-saved", (exception,), (), owner)
            self.set_current(None)
        self.exception_target = saved_exception_target
        self.set_current(None)

    def _compile_with_exception_finalizer(
            self, context: _FinalizerContext, owner: ast.With, *,
            continuation: str, retained_finalizer_depth: int,
            ) -> None:
        """Call one entered manager's ``__exit__`` on an exception edge.

        The manager being exited is already absent from ``self.finalizers``;
        therefore an exception raised by ``__exit__`` reaches the next outer
        manager/finalizer, never recursively re-enters the same manager.  A
        truthy result suppresses the saved exception and resumes the normal
        unwind of the still-active outer managers.
        """
        if (context.kind != "with" or context.with_manager is None or
                context.with_exit is None or context.with_owner is None):
            raise FunctionCFGError(
                "PZFC119", "exceptional with finalizer is malformed")
        saved_exception_target = self.exception_target
        self.exception_target = context.outer_exception_target
        self.set_current(context.exception_block)
        exception = self.emit(
            "capture-current-exception", (), context.with_owner,
            value_kind="py-exception",
            attributes={
                "preserved_across_finalizer": True,
                "with_exception_value": True,
            })
        assert exception is not None
        exception_type = self.emit(
            "python-exception-type", (exception,), context.with_owner,
            value_kind="py-type",
            attributes={"identity": "type(exception)"})
        traceback = self.emit(
            "python-exception-traceback", (exception,), context.with_owner,
            value_kind="py-traceback",
            attributes={"identity": "exception.__traceback__"})
        assert exception_type is not None and traceback is not None
        suppress = self.emit(
            "python-with-call-exit-exception",
            (context.with_exit, exception_type, exception, traceback),
            context.with_owner, value_kind="py-value",
            attributes={
                "arguments": "exc_type,exc,traceback",
                "special_method_call": (
                    "saved-bound-__exit__(exc_type,exc,traceback)"),
                "truthy_result_suppresses": True,
            })
        assert suppress is not None
        suppressed = self.new_block(
            "with_exception_suppressed",
            exception_target=context.outer_exception_target)
        propagate = self.new_block(
            "with_exception_propagate",
            exception_target=context.outer_exception_target)
        self.terminate(
            "branch-truth", (suppress,),
            (suppressed.name, propagate.name), context.with_owner)

        self.set_current(propagate)
        self.terminate("raise-saved", (exception,), (), context.with_owner)
        self.set_current(None)

        self.set_current(suppressed)
        self.emit(
            "suppress-with-exception", (exception,), context.with_owner,
            attributes={
                "restore_previous_exception_context": True,
                "suppression_requires_truthy_exit_result": True,
            })
        self._route_transfer(
            "normal", owner, target=continuation,
            finalizer_depth=retained_finalizer_depth)
        self.exception_target = saved_exception_target
        self.set_current(None)

    def lower_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if self.current is None:
                self.add_blocker(
                    "PZFC205", "syntactically unreachable statement after "
                    "terminating control flow", statement)
                continue
            self.lower_statement(statement)

    def lower_statement(self, node: ast.stmt) -> None:
        if isinstance(node, ast.ClassDef):
            self.lower_class(node)
            return
        if isinstance(node, ast.Global):
            return  # Scope is fixed by symtable, not by the runtime statement order.
        if (self.is_module or self.is_class) and isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.lower_store_target(node.target, self.lower_expression(node.value))
            elif isinstance(node.target, ast.Attribute):
                self.lower_expression(node.target.value)  # Evaluate the receiver, not getattr.
            elif isinstance(node.target, ast.Subscript):
                self.lower_expression(node.target.value)
                if isinstance(node.target.slice, ast.Slice):
                    for item in (node.target.slice.lower, node.target.slice.upper, node.target.slice.step):
                        if item is not None: self.lower_expression(item)
                else:
                    self.lower_expression(node.target.slice)
            postponed = _future_annotations_enabled(self.source_text)
            if node.simple or not postponed:
                annotation = (ast.copy_location(ast.Constant(_postponed_annotation_string(node.annotation, self.source_path)), node.annotation)
                              if postponed else node.annotation)
                value = self.lower_expression(annotation)
                if node.simple:
                    mapping = self.emit("load-class-name" if self.is_class else "load-global-name",
                                        ("__annotations__",), node, value_kind="py-value")
                    key = self.lower_expression(ast.copy_location(ast.Constant(node.target.id), node.target))
                    self.emit("store-subscript", (mapping, key, value), node, attributes={"python_store": True})
            return
        fragment = self.fragments.get(node)
        if fragment is not None:
            self.emit(
                "execute-object-store-fragment",
                (fragment.site_id, fragment.semantic_sha256), node,
                attributes={
                    "exact_fragment_splice": True,
                    "statement_ast_sha256": fragment.statement_ast_sha256,
                    "expression_store_sync_single_execution": True,
                })
            self.visited_sites.append(fragment.site_id)
            return
        if isinstance(node, ast.Assign):
            value = (self.lower_suspending_expression(node.value)
                     if isinstance(node.value, (ast.Yield, ast.YieldFrom))
                     else self.lower_expression(node.value))
            for target in node.targets:
                self.lower_store_target(target, value)
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                value = (self.lower_suspending_expression(node.value)
                         if isinstance(node.value, (ast.Yield, ast.YieldFrom))
                         else self.lower_expression(node.value))
                self.lower_store_target(node.target, value)
            elif isinstance(node.target, ast.Attribute):
                self.lower_expression(node.target.value)
            elif isinstance(node.target, ast.Subscript):
                self.lower_expression(node.target.value)
                if isinstance(node.target.slice, ast.Slice):
                    for item in (node.target.slice.lower, node.target.slice.upper, node.target.slice.step):
                        if item is not None: self.lower_expression(item)
                else:
                    self.lower_expression(node.target.slice)
            return
        if isinstance(node, ast.AugAssign):
            self.lower_augassign(node)
            return
        if isinstance(node, ast.Delete):
            for target in node.targets:
                self.lower_delete_target(target)
            return
        if isinstance(node, ast.Assert):
            self.lower_assert(node)
            return
        if isinstance(node, ast.Import):
            self.lower_import(node)
            return
        if isinstance(node, ast.ImportFrom):
            self.lower_import_from(node)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.lower_nested_function(node)
            return
        if isinstance(node, ast.Expr):
            if isinstance(node.value, (ast.Yield, ast.YieldFrom)):
                self.lower_suspending_expression(node.value)
            else:
                self.lower_expression(node.value)
            return
        if isinstance(node, ast.If):
            self.lower_if(node)
            return
        if isinstance(node, ast.While):
            self.lower_while(node)
            return
        if isinstance(node, ast.For):
            self.lower_for(node)
            return
        if isinstance(node, ast.Try):
            self.lower_try(node)
            return
        if isinstance(node, ast.With):
            self.lower_with(node)
            return
        if isinstance(node, ast.AsyncWith):
            blocker = self.add_blocker(
                "PZFC212", "async-with await protocol is not lowered", node)
            self.emit("blocked-statement", (blocker,), node,
                      attributes={"non_executable": True})
            return
        if isinstance(node, ast.Return):
            arguments: tuple[Any, ...] = ()
            if node.value is not None:
                value = (self.lower_suspending_expression(node.value)
                         if isinstance(node.value, (ast.Yield, ast.YieldFrom))
                         else self.lower_expression(node.value))
                arguments = (value,)
            self._route_transfer(
                "return", node,
                payload=tuple(str(item) for item in arguments))
            return
        if isinstance(node, ast.Raise):
            if node.exc is None:
                # The runtime must re-use the active handled exception, or
                # raise RuntimeError when no exception context is active.
                self.terminate("raise-current", (), (), node)
            else:
                exception = self.lower_expression(node.exc)
                if node.cause is None:
                    self.terminate(
                        "raise-explicit", (exception,), (), node)
                else:
                    # Keep an explicit ``from None`` distinct from an omitted
                    # cause; evaluation order is exception, then cause.
                    cause = self.lower_expression(node.cause)
                    self.terminate(
                        "raise-explicit-from",
                        (exception, cause), (), node)
            self.set_current(None)
            return
        if isinstance(node, ast.Break):
            if not self.break_targets:
                blocker = self.add_blocker(
                    "PZFC206", "break outside lowered loop", node)
                self.emit("blocked-statement", (blocker,), node,
                          attributes={"non_executable": True})
                return
            control = self.break_targets[-1]
            self._route_transfer(
                "jump", node, target=control.name,
                finalizer_depth=control.finalizer_depth)
            return
        if isinstance(node, ast.Continue):
            if not self.continue_targets:
                blocker = self.add_blocker(
                    "PZFC206", "continue outside lowered loop", node)
                self.emit("blocked-statement", (blocker,), node,
                          attributes={"non_executable": True})
                return
            control = self.continue_targets[-1]
            self._route_transfer(
                "jump", node, target=control.name,
                finalizer_depth=control.finalizer_depth)
            return
        if isinstance(node, ast.Pass):
            return
        blocker = self.add_blocker(
            "PZFC201",
            "statement needs semantics not present in target-neutral CFG",
            node)
        self.emit("blocked-statement", (blocker,), node,
                  attributes={"non_executable": True})

    def _has_predecessor(self, target: str) -> bool:
        return any(
            (block.terminator is not None and
             target in block.terminator.targets) or
            block.exception_target == target
            for block in self.blocks.values())

    def lower_with(self, node: ast.With) -> None:
        """Lower synchronous context managers as exact nested finalizers."""
        retained_finalizer_depth = len(self.finalizers)
        outer_exception_target = self.exception_target
        continuation = self.new_block(
            "with_merge", exception_target=outer_exception_target)
        contexts: list[_FinalizerContext] = []

        for item_index, item in enumerate(node.items):
            # All work through a successful __enter__ remains outside this
            # manager's protected region.  A failure here unwinds only
            # managers which were entered by earlier items.
            manager = self.lower_expression(item.context_expr)
            enter = self.emit(
                "python-with-load-enter", (manager,), item.context_expr,
                value_kind="py-callable",
                attributes={
                    "lookup": "type(manager).__enter__",
                    "descriptor_binding": "manager-instance",
                    "lookup_order": "before-exit",
                    "special_method_lookup": True,
                })
            exit_callable = self.emit(
                "python-with-load-exit", (manager,), item.context_expr,
                value_kind="py-callable",
                attributes={
                    "lookup": "type(manager).__exit__",
                    "descriptor_binding": "manager-instance",
                    "lookup_order": "after-enter-before-enter-call",
                    "saved_for_all_exit_paths": True,
                    "special_method_lookup": True,
                })
            assert enter is not None and exit_callable is not None
            entered = self.emit(
                "python-with-call-enter", (enter,),
                item.context_expr, value_kind="py-value",
                attributes={
                    "call": "saved-bound-__enter__()",
                    "manager_not_active_until_success": True,
                })
            assert entered is not None

            exception_block = self.new_block(
                "with_exception",
                exception_target=self.exception_target)
            context = _FinalizerContext(
                label=f"with_exit[{item_index}]",
                kind="with",
                statements=(),
                handler_name=None,
                exception_block=exception_block,
                outer_exception_target=self.exception_target,
                with_manager=manager,
                with_exit=exit_callable,
                with_owner=item.context_expr,
            )
            protected = self.new_block(
                "with_protected",
                exception_target=exception_block.name)
            self.terminate("jump", (), (protected.name,), item.context_expr)
            self.finalizers.append(context)
            contexts.append(context)
            self.exception_target = exception_block.name
            self.set_current(protected)

            # Assignment belongs to the protected region: if it fails, this
            # manager has entered and must receive the resulting exception.
            if item.optional_vars is not None:
                self.lower_store_target(item.optional_vars, entered)

        self.lower_statements(node.body)
        if self.current is not None:
            self._route_transfer(
                "normal", node, target=continuation.name,
                finalizer_depth=retained_finalizer_depth)

        for context in reversed(contexts):
            if not self.finalizers or self.finalizers[-1] is not context:
                raise FunctionCFGError(
                    "PZFC120", "with finalizer stack is unbalanced")
            self.finalizers.pop()
            self._compile_with_exception_finalizer(
                context, node, continuation=continuation.name,
                retained_finalizer_depth=retained_finalizer_depth)

        self.exception_target = outer_exception_target
        if self._has_predecessor(continuation.name):
            self.set_current(continuation)
        else:
            self.blocks.pop(continuation.name)
            self.set_current(None)

    def lower_try(self, node: ast.Try) -> None:
        """Lower Python try/except/else/finally with explicit throw edges."""
        outer_finalizer_depth = len(self.finalizers)
        outer_exception_target = self.exception_target
        continuation = self.new_block(
            "try_merge", exception_target=outer_exception_target)

        user_finalizer: _FinalizerContext | None = None
        protected_exception_target = outer_exception_target
        if node.finalbody:
            exception_block = self.new_block(
                "finally_exception",
                exception_target=outer_exception_target)
            user_finalizer = _FinalizerContext(
                label="finally",
                kind="user",
                statements=tuple(node.finalbody),
                handler_name=None,
                exception_block=exception_block,
                outer_exception_target=outer_exception_target,
            )
            protected_exception_target = exception_block.name

        dispatch = (self.new_block(
            "except_dispatch",
            exception_target=protected_exception_target)
                    if node.handlers else None)
        body_exception_target = (
            dispatch.name if dispatch is not None
            else protected_exception_target)
        body = self.new_block(
            "try_body", exception_target=body_exception_target)
        self.terminate("jump", (), (body.name,), node)
        if user_finalizer is not None:
            self.finalizers.append(user_finalizer)

        self.exception_target = body_exception_target
        self.set_current(body)
        self.lower_statements(node.body)
        body_end = self.current
        if body_end is not None:
            otherwise = self.new_block(
                "try_else", exception_target=protected_exception_target)
            self.set_current(body_end)
            self.terminate("jump", (), (otherwise.name,), node)
            self.exception_target = protected_exception_target
            self.set_current(otherwise)
            self.lower_statements(node.orelse)
            if self.current is not None:
                self._route_transfer(
                    "normal", node, target=continuation.name,
                    finalizer_depth=outer_finalizer_depth)

        if dispatch is not None:
            self.exception_target = protected_exception_target
            self.set_current(dispatch)
            exception = self.emit(
                "load-current-exception", (), node,
                value_kind="py-exception",
                attributes={"from_exceptional_edge": True})
            assert exception is not None
            search_block: _Block | None = dispatch
            for handler_index, handler in enumerate(node.handlers):
                if search_block is None:
                    raise FunctionCFGError(
                        "PZFC107", "handler follows catch-all handler")
                self.exception_target = protected_exception_target
                self.set_current(search_block)
                cleanup_exception = self.new_block(
                    "handler_cleanup_exception",
                    exception_target=protected_exception_target)
                handler_body = self.new_block(
                    "except_handler",
                    exception_target=cleanup_exception.name)
                if handler.type is None:
                    self.terminate(
                        "jump", (), (handler_body.name,), handler)
                    next_search = None
                else:
                    handler_type = self.lower_expression(handler.type)
                    matches = self.emit(
                        "exception-matches", (exception, handler_type),
                        handler, value_kind="bool",
                        attributes={
                            "handler_index": handler_index,
                            "python_exception_match": True,
                        })
                    assert matches is not None
                    next_search = self.new_block(
                        "except_next",
                        exception_target=protected_exception_target)
                    self.terminate(
                        "branch-truth", (matches,),
                        (handler_body.name, next_search.name), handler)

                self.exception_target = cleanup_exception.name
                self.set_current(handler_body)
                self.emit(
                    "begin-except-handler", (exception,), handler,
                    attributes={"handler_index": handler_index})
                if handler.name is not None:
                    self.emit(
                        "store-name", (handler.name, exception), handler,
                        attributes={"exception_target_binding": True})
                cleanup = _FinalizerContext(
                    label="handler_cleanup",
                    kind="handler",
                    statements=(),
                    handler_name=handler.name,
                    exception_block=cleanup_exception,
                    outer_exception_target=protected_exception_target,
                )
                self.finalizers.append(cleanup)
                self.lower_statements(handler.body)
                if self.current is not None:
                    self._route_transfer(
                        "normal", handler, target=continuation.name,
                        finalizer_depth=outer_finalizer_depth)
                if not self.finalizers or self.finalizers[-1] is not cleanup:
                    raise FunctionCFGError(
                        "PZFC108", "handler cleanup stack is unbalanced")
                self.finalizers.pop()
                self._compile_exception_finalizer(cleanup, handler)
                search_block = next_search
            if search_block is not None:
                self.exception_target = protected_exception_target
                self.set_current(search_block)
                self.terminate("raise-current", (), (), node)
                self.set_current(None)

        if user_finalizer is not None:
            if (not self.finalizers or
                    self.finalizers[-1] is not user_finalizer):
                raise FunctionCFGError(
                    "PZFC109", "finally stack is unbalanced")
            self.finalizers.pop()
            self._compile_exception_finalizer(user_finalizer, node)

        self.exception_target = outer_exception_target
        if self._has_predecessor(continuation.name):
            self.set_current(continuation)
        else:
            self.blocks.pop(continuation.name)
            self.set_current(None)

    def lower_if(self, node: ast.If) -> None:
        condition = self.lower_expression(node.test)
        true_block = self.new_block("if_true")
        false_block = self.new_block("if_false")
        self.terminate("branch-truth", (condition,),
                       (true_block.name, false_block.name), node.test)
        self.set_current(true_block)
        self.lower_statements(node.body)
        true_end = self.current
        self.set_current(false_block)
        self.lower_statements(node.orelse)
        false_end = self.current
        if true_end is None and false_end is None:
            self.set_current(None)
            return
        merge = self.new_block("if_merge")
        if true_end is not None:
            self.set_current(true_end)
            self.terminate("jump", (), (merge.name,), node)
        if false_end is not None:
            self.set_current(false_end)
            self.terminate("jump", (), (merge.name,), node)
        self.set_current(merge)

    def lower_while(self, node: ast.While) -> None:
        header = self.new_block("while_header")
        body = self.new_block("while_body")
        otherwise = self.new_block("while_else")
        merge = self.new_block("while_merge")
        self.terminate("jump", (), (header.name,), node)
        self.set_current(header)
        condition = self.lower_expression(node.test)
        self.terminate("branch-truth", (condition,),
                       (body.name, otherwise.name), node.test)
        loop_depth = len(self.finalizers)
        self.break_targets.append(_ControlTarget(merge.name, loop_depth))
        self.continue_targets.append(_ControlTarget(header.name, loop_depth))
        self.set_current(body)
        self.lower_statements(node.body)
        if self.current is not None:
            self.terminate("jump", (), (header.name,), node)
        self.set_current(otherwise)
        self.lower_statements(node.orelse)
        if self.current is not None:
            self.terminate("jump", (), (merge.name,), node)
        self.break_targets.pop()
        self.continue_targets.pop()
        self.set_current(merge)

    def lower_for(self, node: ast.For) -> None:
        iterable = self.lower_expression(node.iter)
        iterator = self.emit(
            "python-get-iterator", (iterable,), node.iter,
            value_kind="py-iterator")
        assert iterator is not None
        header = self.new_block("for_header")
        body = self.new_block("for_body")
        otherwise = self.new_block("for_else")
        merge = self.new_block("for_merge")
        self.terminate("jump", (), (header.name,), node)
        self.set_current(header)
        record = self.emit(
            "python-iter-next", (iterator,), node,
            value_kind="py-iteration-record",
            attributes={"stop_iteration_is_normal_exit": True})
        assert record is not None
        has_value = self.emit(
            "iteration-has-value", (record,), node,
            value_kind="bool")
        assert has_value is not None
        self.terminate("branch-truth", (has_value,),
                       (body.name, otherwise.name), node)
        loop_depth = len(self.finalizers)
        self.break_targets.append(_ControlTarget(merge.name, loop_depth))
        self.continue_targets.append(_ControlTarget(header.name, loop_depth))
        self.set_current(body)
        item = self.emit(
            "iteration-value", (record,), node.target,
            value_kind="py-value")
        assert item is not None
        self.lower_store_target(node.target, item)
        self.lower_statements(node.body)
        if self.current is not None:
            self.terminate("jump", (), (header.name,), node)
        self.set_current(otherwise)
        self.lower_statements(node.orelse)
        if self.current is not None:
            self.terminate("jump", (), (merge.name,), node)
        self.break_targets.pop()
        self.continue_targets.pop()
        self.set_current(merge)

    def build(self, native_operation: str | None = None) -> ActivePythonFunctionIR:
        if isinstance(self.node, ast.AsyncFunctionDef):
            self.add_blocker(
                "PZFC200", "async function suspension CFG is unsupported",
                self.node)
        entry = self.new_block("function_entry")
        self.set_current(entry)
        if self.is_generator and self.generator_scope_error is None:
            entered = self.emit(
                "generator-frame-enter", (self.generator_local_names,),
                self.node, value_kind="py-none",
                attributes={
                    "call_body_execution": "deferred-until-first-resume",
                    "close_before_start": "complete-without-running-body",
                    "first_next_or_send_none": "enter-body-with-None",
                    "first_send_non_none": "TypeError-before-body",
                    "first_throw": "raise-at-function-entry",
                    "frame_format": GENERATOR_FRAME_FORMAT,
                })
            assert entered is not None
        body = list(self.node.body)
        if self.is_class:
            module = self.emit("load-class-name", ("__name__",), self.node, value_kind="py-value")
            self.emit("store-name", ("__module__", module), self.node)
            qualname = ast.copy_location(ast.Constant(self.class_qualname), self.node)
            self.emit("store-name", ("__qualname__", self.lower_expression(qualname)), self.node)
        if (self.is_class or self.is_module) and _scope_has_annotations(self.node):
            self.emit("setup-class-annotations" if self.is_class else "setup-global-annotations",
                      ("__annotations__",), self.node, attributes={"existing_mapping_preserved": True})
        if (body and isinstance(body[0], ast.Expr) and
                isinstance(body[0].value, ast.Constant) and
                isinstance(body[0].value.value, str)):
            if self.is_module or self.is_class:
                doc = self.lower_expression(body[0].value)
                self.emit("store-name", ("__doc__", doc), body[0], attributes={"python_store": True})
            body = body[1:]
        if native_operation is not None:
            if native_operation not in ('dataclass-resolve', 'dataclass-install', 'dataclass-metadata', 'dataclass-repr-pending', 'collections-deque-type', 'collections-defaultdict-type'):
                raise ValueError('unregistered native library operation')
            if self.is_module or self.is_class or self.node.args.vararg or self.node.args.kwarg:
                raise ValueError('native library entry needs a fixed function signature')
            values = tuple(self.emit('load-name', (arg.arg,), arg, value_kind='py-value')
                           for arg in [*self.node.args.posonlyargs, *self.node.args.args, *self.node.args.kwonlyargs])
            value = self.emit(native_operation, values, self.node, value_kind='py-value',
                              attributes={'library': 'cpython-3.12.collections' if native_operation.startswith('collections-')
                                          else 'cpython-3.12.dataclasses'})
            self.terminate('return', (value,), (), self.node)
            self.current = None
        else:
            self.lower_statements(body)
        if self.current is not None:
            self.terminate(
                "generator-return" if self.is_generator else "return",
                (), (), self.node)
        expected_sites = sorted(fragment.site_id
                                for fragment in self.fragments.values())
        if sorted(self.visited_sites) != expected_sites:
            raise FunctionCFGError(
                "PZFC103", f"{self.function_id} spliced sites "
                f"{sorted(self.visited_sites)}, expected {expected_sites}")
        blocks = tuple(PythonFunctionBlock(
            name=block.name,
            instructions=tuple(block.instructions),
            terminator=block.terminator,
            exception_target=block.exception_target,
        ) for block in self.blocks.values() if block.terminator is not None)
        if len(blocks) != len(self.blocks):
            raise FunctionCFGError(
                "PZFC104", f"unterminated block in {self.function_id}")
        spliced = tuple(sorted(
            ((fragment.site_id, fragment.semantic_sha256)
             for fragment in self.fragments.values()),
            key=lambda item: item[0]))
        self._finalize_generator_frame_states(blocks)
        signature = self.function_signature()
        payload = {
            "function_id": self.function_id,
            "class": self.class_name,
            "function": self.function_name,
            "definition_line": self.definition_line,
            "ast_sha256": _ast_sha256(self.node),
            "signature": signature,
            "entry": entry.name,
            "blocks": [block.to_json() for block in blocks],
            "expression_programs": [
                program.to_json() for program in self.expression_programs],
            "mutation_site_ids": expected_sites,
            "spliced_store_fragments": [
                {"site_id": site_id, "semantic_sha256": semantic}
                for site_id, semantic in spliced],
            "blockers": [blocker.to_json() for blocker in self.blockers],
        }
        result = ActivePythonFunctionIR(
            function_id=self.function_id,
            class_name=self.class_name,
            function_name=self.function_name,
            definition_line=self.definition_line,
            ast_sha256=_ast_sha256(self.node),
            signature=signature,
            entry=entry.name,
            blocks=blocks,
            expression_programs=tuple(self.expression_programs),
            mutation_site_ids=tuple(expected_sites),
            spliced_store_fragments=spliced,
            blockers=tuple(self.blockers),
            semantic_sha256=_json_sha256(payload),
        )
        _validate_function(result)
        return result


def lower_python_function_cfg(
        node: ast.FunctionDef | ast.AsyncFunctionDef, *,
        class_name: str | None, source_path: Path, source_text: str,
        fragments: Mapping[ast.AST, ObjectStoreFragmentIR] | None = None,
        callable_id: str | None = None,
        native_operation: str | None = None,
        ) -> ActivePythonFunctionIR:
    """Lower one parsed function without importing or executing its module."""
    lowerer = _FunctionLowerer(
        node=node,
        class_name=class_name,
        source_path=source_path,
        source_text=source_text,
        fragments=fragments or {},
    )
    if callable_id is not None:
        lowerer.function_id = callable_id
    return lowerer.build(native_operation)


def lower_python_class_cfg(node: ast.ClassDef, *, source_path: Path, source_text: str,
                           callable_id: str, qualname: str) -> ActivePythonFunctionIR:
    if not isinstance(node, ast.ClassDef) or (node.lineno, _ast_sha256(node)) not in _class_ast_seals(source_text):
        raise FunctionCFGError("PZFC117", "class AST differs from source text")
    lowerer = _FunctionLowerer(node=node, class_name=None, source_path=source_path,
                              source_text=source_text, fragments={})
    lowerer.function_id = callable_id
    lowerer.class_qualname = qualname
    return lowerer.build()


def lower_python_module_cfg(node: ast.Module, *, source_path: Path,
                            source_text: str, module_name: str | None = None) -> ActivePythonFunctionIR:
    """Compile with the actual module symbol table, never a wrapper def.

    Imports/classes/annotation protocols remain explicit adapters or blockers.
    A namespace owner starts this entry once; this is not an import scheduler.
    """
    if not isinstance(node, ast.Module) or _ast_sha256(node) != _ast_sha256(ast.parse(source_text)):
        raise FunctionCFGError("PZFC116", "module AST differs from source text")
    # symtable alone accepts e.g. a module-level return; compile validates it
    # without importing or executing any source code.
    compile(source_text, str(source_path), "exec", dont_inherit=True)
    _symbol_table_index(source_text, source_path)
    lowerer = _FunctionLowerer(node=node, class_name=None, source_path=source_path,
                              source_text=source_text, fragments={})
    if module_name is not None:
        lowerer.function_id = module_name + "::<module>@1"
    return lowerer.build()


def _validate_extended_expression_program(
        program: ObjectExpressionIR, *, owner: ast.expr | None = None,
        source_text: str | None = None,
        ) -> None:
    """Strictly validate expression-scope operations added in this module.

    The frontend's base validator already proves SSA dominance/reachability.
    This pass proves the operand schema and, while the source AST is available,
    re-derives every lambda/comprehension plan instead of trusting metadata.
    """
    custom_ops = {
        "capture-expression-closure-cell",
        "load-expression-globals",
        "python-get-iterator-immediate",
        "make-lambda-function",
        "run-eager-comprehension",
        "make-generator-expression",
    }

    def fail_contract(op: str, detail: str) -> "None":
        raise FunctionCFGError(
            "PZFC318", f"malformed extended expression {op}: {detail}")

    def is_sha256(value: object) -> bool:
        return (isinstance(value, str) and len(value) == 64 and
                all(character in "0123456789abcdef" for character in value))

    def is_ssa(value: object) -> bool:
        return isinstance(value, str) and value.startswith("%expr_")

    def named_ssa_pairs(value: object) -> bool:
        return (isinstance(value, tuple) and all(
            isinstance(row, tuple) and len(row) == 2 and
            isinstance(row[0], str) and bool(row[0]) and is_ssa(row[1])
            for row in value))

    def validate_expression_descriptor(value: object, op: str) -> None:
        if not isinstance(value, dict) or set(value) != {
                "node_kind", "ast_sha256", "source", "nested_scopes"}:
            fail_contract(op, "expression descriptor keys differ")
        if (not isinstance(value["node_kind"], str) or
                not is_sha256(value["ast_sha256"]) or
                not isinstance(value["source"], str) or
                not isinstance(value["nested_scopes"], tuple)):
            fail_contract(op, "expression descriptor values differ")
        for scope in value["nested_scopes"]:
            if (not isinstance(scope, dict) or set(scope) != {
                    "node_kind", "ast_sha256", "line", "column", "source"} or
                    not isinstance(scope["node_kind"], str) or
                    not is_sha256(scope["ast_sha256"]) or
                    not isinstance(scope["line"], int) or
                    not isinstance(scope["column"], int) or
                    not isinstance(scope["source"], str)):
                fail_contract(op, "nested scope descriptor differs")

    def validate_target_descriptor(value: object, op: str) -> None:
        if not isinstance(value, dict):
            fail_contract(op, "target descriptor is not a mapping")
        common = {"kind", "ast_sha256", "source"}
        if not common.issubset(value) or not is_sha256(
                value["ast_sha256"]) or not isinstance(value["source"], str):
            fail_contract(op, "target descriptor binding differs")
        kind = value["kind"]
        if kind == "local-name":
            if (set(value) != common | {"name"} or
                    not isinstance(value["name"], str) or not value["name"]):
                fail_contract(op, "local target differs")
            return
        if kind == "starred":
            if set(value) != common | {"value"}:
                fail_contract(op, "starred target keys differ")
            validate_target_descriptor(value["value"], op)
            return
        if kind in {"tuple-unpack", "list-unpack"}:
            if set(value) != common | {"items", "unpack_protocol"}:
                fail_contract(op, "unpack target keys differ")
            if (not isinstance(value["items"], tuple) or
                    not value["items"] or
                    not isinstance(value["unpack_protocol"], tuple)):
                fail_contract(op, "unpack target values differ")
            for item in value["items"]:
                validate_target_descriptor(item, op)
            protocol = value["unpack_protocol"]
            if (not protocol or protocol[0] not in {
                    "UNPACK_SEQUENCE", "UNPACK_EX"}):
                fail_contract(op, "unpack opcode differs")
            return
        fail_contract(op, f"unknown target kind {kind!r}")

    def validate_plan(plan: object, op: str) -> None:
        if not isinstance(plan, dict):
            fail_contract(op, "scope plan is not a mapping")
        base_keys = {
            "format", "kind", "ast_sha256", "line", "column", "scope",
            "local_names", "free_cell_names", "name_resolution",
            "outer_iterator", "generators", "production", "loop_order",
            "scope_exit", "exception_protocol",
        }
        expected_keys = (base_keys | {"resumable_protocol"}
                         if plan.get("kind") == "generator" else base_keys)
        if set(plan) != expected_keys:
            fail_contract(op, "scope plan keys differ")
        if (plan["format"] != EXTENDED_EXPRESSION_SCOPE_FORMAT or
                plan["kind"] not in {"list", "set", "dict", "generator"} or
                not is_sha256(plan["ast_sha256"]) or
                not isinstance(plan["line"], int) or
                not isinstance(plan["column"], int) or
                plan["scope"] != "separate-implicit-function-scope"):
            fail_contract(op, "scope plan identity differs")
        for key in ("local_names", "free_cell_names"):
            names = plan[key]
            if (not isinstance(names, tuple) or
                    tuple(sorted(names)) != names or
                    len(names) != len(set(names)) or
                    not all(isinstance(name, str) and name for name in names)):
                fail_contract(op, f"{key} is not a deterministic name tuple")
        generators = plan["generators"]
        if not isinstance(generators, tuple) or not generators:
            fail_contract(op, "generator stages are absent")
        for index, generator in enumerate(generators):
            if (not isinstance(generator, dict) or set(generator) != {
                    "ordinal", "iterator", "target", "filters", "is_async",
                    "step_order"} or generator["ordinal"] != index or
                    generator["is_async"] is not False):
                fail_contract(op, "generator stage identity differs")
            iterator = generator["iterator"]
            expected_mode = ("provided-leftmost-iterator" if index == 0 else
                             "evaluate-then-get-iterator-in-scope")
            if (not isinstance(iterator, dict) or set(iterator) != {
                    "mode", "expression"} or
                    iterator["mode"] != expected_mode):
                fail_contract(op, "generator iterator timing differs")
            validate_expression_descriptor(iterator["expression"], op)
            validate_target_descriptor(generator["target"], op)
            filters = generator["filters"]
            if not isinstance(filters, tuple):
                fail_contract(op, "filter sequence differs")
            for item in filters:
                validate_expression_descriptor(item, op)
        production = plan["production"]
        if not isinstance(production, dict):
            fail_contract(op, "production descriptor differs")
        if plan["kind"] == "dict":
            if (set(production) != {
                    "operation", "evaluation_order", "key", "value"} or
                    production["operation"] != "mapping-setitem" or
                    production["evaluation_order"] != (
                        "key-then-value-then-setitem")):
                fail_contract(op, "dict key/value order differs")
            validate_expression_descriptor(production["key"], op)
            validate_expression_descriptor(production["value"], op)
        else:
            expected_operation = {
                "list": "list-append", "set": "set-add",
                "generator": "yield",
            }[plan["kind"]]
            if (set(production) != {
                    "operation", "evaluation_order", "element"} or
                    production["operation"] != expected_operation or
                    production["evaluation_order"] != "element-then-produce"):
                fail_contract(op, "element production order differs")
            validate_expression_descriptor(production["element"], op)
        if plan["kind"] == "generator":
            resumable = plan["resumable_protocol"]
            if (not isinstance(resumable, dict) or set(resumable) != {
                    "creation_state", "next", "yield_resume_point", "send",
                    "throw", "close", "completion", "pep479"} or
                    "StopIteration" not in resumable["completion"] or
                    "RuntimeError" not in resumable["pep479"]):
                fail_contract(op, "generator resumable protocol differs")

    custom_instructions = [
        item for block in program.blocks for item in block.instructions
        if item.op in custom_ops]
    for item in custom_instructions:
        op = item.op
        attributes = dict(item.attributes)
        if op == "capture-expression-closure-cell":
            if (item.value_kind != "py-cell" or
                    len(item.arguments) != 1 or
                    not isinstance(item.arguments[0], str) or
                    not item.arguments[0] or attributes != {
                        "capture": "cell-identity",
                        "not_value_snapshot": True}):
                fail_contract(op, "cell capture contract differs")
            continue
        if op == "load-expression-globals":
            if (item.value_kind != "py-mapping" or item.arguments or
                    attributes != {"mapping_identity_preserved": True}):
                fail_contract(op, "globals mapping contract differs")
            continue
        if op == "python-get-iterator-immediate":
            if (item.value_kind != "py-iterator" or
                    len(item.arguments) != 1 or
                    not is_ssa(item.arguments[0]) or attributes != {
                        "evaluation_count": 1,
                        "exception_timing": "expression-creation",
                        "python_protocol": "iter"}):
                fail_contract(op, "leftmost iterator timing differs")
            continue
        if op == "make-lambda-function":
            if item.value_kind != "py-function" or len(item.arguments) != 4:
                fail_contract(op, "lambda result/arity differs")
            globals_mapping, positional, keyword, closure = item.arguments
            if (not is_ssa(globals_mapping) or
                    not named_ssa_pairs(positional) or
                    not named_ssa_pairs(keyword) or
                    not named_ssa_pairs(closure)):
                fail_contract(op, "lambda SSA operands differ")
            required = {
                "format", "ast_sha256", "line", "column", "signature",
                "body", "body_kind", "body_execution", "closure_binding",
                "default_evaluation_order", "free_cell_names",
                "function_name", "globals_binding", "scope_semantic_sha256", "default_expressions",
            }
            if (set(attributes) != required or
                    attributes["format"] != EXTENDED_EXPRESSION_SCOPE_FORMAT or
                    not is_sha256(attributes["ast_sha256"]) or
                    attributes["function_name"] != "<lambda>" or
                    attributes["body_execution"] != "deferred-until-call" or
                    attributes["body_kind"] not in {
                        "ordinary", "generator", "coroutine"}):
                fail_contract(op, "lambda metadata differs")
            validate_expression_descriptor(attributes["body"], op)
            descriptors = attributes["default_expressions"]
            if (not isinstance(descriptors, tuple) or
                tuple(name for name, _ in descriptors) != tuple(name for name, _ in (*positional, *keyword))):
                fail_contract(op, "default expression identities differ from evaluated operands")
            for _name, descriptor in descriptors:
                validate_expression_descriptor(descriptor, op)
            free_names = attributes["free_cell_names"]
            if (not isinstance(free_names, tuple) or
                    tuple(name for name, _value in closure) != free_names or
                    tuple(sorted(free_names)) != free_names):
                fail_contract(op, "lambda closure names differ")
            semantic = attributes.pop("scope_semantic_sha256")
            if not is_sha256(semantic) or _json_sha256(attributes) != semantic:
                fail_contract(op, "lambda semantic hash differs")
            continue
        if op in {"run-eager-comprehension", "make-generator-expression"}:
            if len(item.arguments) != 3:
                fail_contract(op, "comprehension operand arity differs")
            outer_iterator, globals_mapping, closure = item.arguments
            if (not is_ssa(outer_iterator) or not is_ssa(globals_mapping) or
                    not named_ssa_pairs(closure)):
                fail_contract(op, "comprehension SSA operands differ")
            plan = attributes.get("plan")
            validate_plan(plan, op)
            assert isinstance(plan, dict)
            if (attributes.get("format") != EXTENDED_EXPRESSION_SCOPE_FORMAT or
                    attributes.get("plan_semantic_sha256") !=
                    _json_sha256(plan) or
                    tuple(name for name, _value in closure) !=
                    plan["free_cell_names"]):
                fail_contract(op, "comprehension plan binding differs")
            if op == "run-eager-comprehension":
                expected_kind = f"py-{plan['kind']}"
                expected_extra = {
                    "body_execution": "eager-to-exhaustion",
                    "partial_result_on_exception": "discard-and-propagate",
                    "result_protocol": f"Python-{plan['kind']}-object",
                }
                if plan["kind"] == "generator":
                    fail_contract(op, "eager operation owns generator plan")
            else:
                expected_kind = "py-generator"
                expected_extra = {
                    "body_execution": "lazy-on-next-send-throw-close",
                    "creation_is_lazy_except_leftmost_iterator": True,
                    "result_protocol": "Python-generator-object",
                }
                if plan["kind"] != "generator":
                    fail_contract(op, "generator operation owns eager plan")
            if item.value_kind != expected_kind:
                fail_contract(op, "comprehension result kind differs")
            if ({key: value for key, value in attributes.items()
                 if key not in {"format", "plan", "plan_semantic_sha256"}} !=
                    expected_extra):
                fail_contract(op, "comprehension execution contract differs")

    if owner is None or source_text is None:
        return
    candidates: dict[tuple[str, int, int, str], list[ast.expr]] = defaultdict(list)
    for node in ast.walk(owner):
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp,
                             ast.DictComp, ast.GeneratorExp)):
            key = (type(node).__name__, int(node.lineno), int(node.col_offset),
                   _ast_sha256(node))
            candidates[key].append(node)
    for item in custom_instructions:
        if item.op not in {"make-lambda-function", "run-eager-comprehension",
                           "make-generator-expression"}:
            continue
        attributes = dict(item.attributes)
        if item.op == "make-lambda-function":
            key = ("Lambda", attributes["line"], attributes["column"],
                   attributes["ast_sha256"])
            matches = candidates.get(key, ())
            if len(matches) != 1 or not isinstance(matches[0], ast.Lambda):
                fail_contract(item.op, "lambda does not bind one source node")
            lambda_node = matches[0]
            expected_positional = [
                parameter.arg for parameter in
                [*lambda_node.args.posonlyargs, *lambda_node.args.args][
                    -len(lambda_node.args.defaults):]
            ] if lambda_node.args.defaults else []
            expected_keyword = [
                parameter.arg for parameter, default in zip(
                    lambda_node.args.kwonlyargs,
                    lambda_node.args.kw_defaults) if default is not None]
            if ([name for name, _value in item.arguments[1]] !=
                    expected_positional or
                    [name for name, _value in item.arguments[2]] !=
                    expected_keyword or
                    attributes["signature"] !=
                    _lambda_signature_descriptor(lambda_node) or
                    attributes["body"] !=
                    _expression_descriptor(source_text, lambda_node.body)):
                fail_contract(item.op, "lambda differs from source AST")
        else:
            plan = attributes["plan"]
            node_kind = {
                "list": "ListComp", "set": "SetComp", "dict": "DictComp",
                "generator": "GeneratorExp",
            }[plan["kind"]]
            key = (node_kind, plan["line"], plan["column"],
                   plan["ast_sha256"])
            matches = candidates.get(key, ())
            if len(matches) != 1 or not isinstance(matches[0], (
                    ast.ListComp, ast.SetComp, ast.DictComp,
                    ast.GeneratorExp)):
                fail_contract(item.op,
                              "comprehension does not bind one source node")
            expected_plan = _comprehension_plan(
                source_text, matches[0], plan["free_cell_names"])
            if plan != expected_plan:
                fail_contract(item.op,
                              "comprehension plan differs from source AST")


def _validated_generator_frame_descriptor(
        value: object, *, code: str, context: str,
        ) -> dict[str, Any]:
    """Return one strictly shaped, source-bounded generator frame state."""
    if not isinstance(value, dict):
        raise FunctionCFGError(code, f"{context}: descriptor is not a dict")
    expected_keys = {
        "format", "state", "suspension_kind", "source_ast_sha256",
        "line", "column", "resume_target", "local_slots", "loop_stack",
        "finalizer_stack", "exception_target", "operand_stack_slots",
        "spill_slots", "bounded_slot_count", "bounded_by_source_ast",
    }
    if set(value) != expected_keys:
        raise FunctionCFGError(
            code, f"{context}: descriptor keys differ")

    def positive_integer(item: object) -> bool:
        return (isinstance(item, int) and not isinstance(item, bool) and
                item > 0)

    def non_negative_integer(item: object) -> bool:
        return (isinstance(item, int) and not isinstance(item, bool) and
                item >= 0)

    def sha256(item: object) -> bool:
        return (isinstance(item, str) and len(item) == 64 and
                all(character in "0123456789abcdef"
                    for character in item))

    state = value["state"]
    if value["format"] != GENERATOR_FRAME_FORMAT:
        raise FunctionCFGError(code, f"{context}: frame format differs")
    if not positive_integer(state):
        raise FunctionCFGError(code, f"{context}: invalid state id")
    if value["suspension_kind"] not in {"yield", "yield-from"}:
        raise FunctionCFGError(code, f"{context}: suspension kind differs")
    if not sha256(value["source_ast_sha256"]):
        raise FunctionCFGError(code, f"{context}: invalid source AST hash")
    if (not positive_integer(value["line"]) or
            not non_negative_integer(value["column"])):
        raise FunctionCFGError(code, f"{context}: invalid source location")
    if (not isinstance(value["resume_target"], str) or
            not value["resume_target"]):
        raise FunctionCFGError(code, f"{context}: invalid resume target")

    local_slots = value["local_slots"]
    if (not isinstance(local_slots, tuple) or
            not all(isinstance(name, str) and name
                    for name in local_slots) or
            tuple(sorted(set(local_slots))) != local_slots):
        raise FunctionCFGError(
            code, f"{context}: local slots are not deterministic")
    loop_stack = value["loop_stack"]
    if (not isinstance(loop_stack, tuple) or not all(
            isinstance(row, tuple) and len(row) == 2 and
            all(isinstance(target, str) and target for target in row)
            for row in loop_stack)):
        raise FunctionCFGError(code, f"{context}: invalid loop stack")
    finalizer_stack = value["finalizer_stack"]
    if (not isinstance(finalizer_stack, tuple) or
            not all(isinstance(label, str) and label
                    for label in finalizer_stack)):
        raise FunctionCFGError(code, f"{context}: invalid finalizer stack")
    exception_target = value["exception_target"]
    if (exception_target is not None and
            (not isinstance(exception_target, str) or
             not exception_target)):
        raise FunctionCFGError(code, f"{context}: invalid exception target")
    spill_slots = value["spill_slots"]
    if (not isinstance(spill_slots, tuple) or
            len(spill_slots) != len(set(spill_slots)) or
            not all(isinstance(slot, str) and slot.startswith("%fn_")
                    for slot in spill_slots)):
        raise FunctionCFGError(code, f"{context}: invalid SSA spill slots")
    operand_slots = value["operand_stack_slots"]
    if (not non_negative_integer(operand_slots) or
            operand_slots > len(spill_slots)):
        raise FunctionCFGError(
            code, f"{context}: invalid operand-stack slot count")
    expected_bound = (
        len(local_slots) + 2 + len(loop_stack) + len(finalizer_stack) +
        (1 if exception_target is not None else 0) + len(spill_slots))
    if (value["bounded_slot_count"] != expected_bound or
            value["bounded_by_source_ast"] is not True):
        raise FunctionCFGError(code, f"{context}: frame bound differs")
    return value


def _validate_statement_instruction(item: ObjectEffectInstruction) -> None:
    """Validate the exact operand/result contract of statement-level ops."""
    op = item.op
    attributes = dict(item.attributes)

    def malformed(detail: str) -> None:
        raise FunctionCFGError(
            "PZFC316", f"malformed {op} instruction: {detail}")

    def require_result(kind: str) -> None:
        if (not isinstance(item.destination, str) or
                not item.destination.startswith("%fn_") or
                item.value_kind != kind):
            malformed(f"expected {kind} SSA result")

    def require_no_result() -> None:
        if item.destination is not None or item.value_kind is not None:
            malformed("unexpected result")

    def require_attributes(expected: Mapping[str, Any]) -> None:
        if attributes != dict(expected):
            malformed("attribute contract differs")

    def is_ssa(value: object) -> bool:
        return isinstance(value, str) and value.startswith("%fn_")

    def is_sha256(value: object) -> bool:
        return (isinstance(value, str) and len(value) == 64 and
                all(character in "0123456789abcdef" for character in value))

    if op == "generator-frame-enter":
        require_result("py-none")
        if (len(item.arguments) != 1 or
                not isinstance(item.arguments[0], tuple) or
                tuple(sorted(set(item.arguments[0]))) != item.arguments[0] or
                not all(isinstance(name, str) and name
                        for name in item.arguments[0])):
            malformed("expected deterministic lexical-local slots")
        require_attributes({
            "call_body_execution": "deferred-until-first-resume",
            "close_before_start": "complete-without-running-body",
            "first_next_or_send_none": "enter-body-with-None",
            "first_send_non_none": "TypeError-before-body",
            "first_throw": "raise-at-function-entry",
            "frame_format": GENERATOR_FRAME_FORMAT,
        })
    elif op in {"generator-save-frame", "generator-restore-frame"}:
        require_no_result()
        if (len(item.arguments) != 2 or
                not isinstance(item.arguments[0], int) or
                isinstance(item.arguments[0], bool) or
                item.arguments[0] <= 0):
            malformed("expected positive state and frame descriptor")
        descriptor = _validated_generator_frame_descriptor(
            item.arguments[1], code="PZFC316", context=op)
        if descriptor["state"] != item.arguments[0]:
            malformed("state does not bind descriptor")
        if op == "generator-save-frame":
            require_attributes({
                "evaluation_stack_empty_at_suspend": (
                    descriptor["operand_stack_slots"] == 0),
                "locals_and_control_state_by_identity": True,
            })
        else:
            require_attributes({
                "restore_before_resume_command": True,
                "same_frame_object": True,
            })
    elif op == "generator-resume-value":
        require_result("py-value")
        if (len(item.arguments) != 1 or
                not isinstance(item.arguments[0], int) or
                isinstance(item.arguments[0], bool) or
                item.arguments[0] <= 0):
            malformed("expected positive suspension state")
        require_attributes({
            "close": "raise-GeneratorExit-at-yield-site",
            "next": "result-is-None",
            "send": "result-is-sent-value",
            "throw": "raise-injected-exception-at-yield-site",
        })
    elif op == "generator-delegation-start":
        require_result("py-delegation-iterator")
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one iterable SSA")
        require_attributes({
            "evaluation_count": 1,
            "python_protocol": "iter",
            "start_before_first-delegate-next": True,
        })
    elif op == "generator-yield-from-result":
        require_result("py-value")
        if (len(item.arguments) != 1 or
                not isinstance(item.arguments[0], int) or
                isinstance(item.arguments[0], bool) or
                item.arguments[0] <= 0):
            malformed("expected positive delegation state")
        require_attributes({
            "available_only_after_delegate_exhaustion": True,
            "result": "StopIteration.value",
        })
    elif op in ("store-name", "store-global-name", "store-class-name") and (
            "import_binding" in attributes or
            "function_definition_binding" in attributes):
        require_no_result()
        if (len(item.arguments) != 2 or
                not isinstance(item.arguments[0], str) or
                not item.arguments[0] or not is_ssa(item.arguments[1])):
            malformed("expected binding name and value SSA")
        if "import_binding" in attributes:
            require_attributes({
                "import_binding": True,
                "python_store": True,
            })
        else:
            require_attributes({
                "function_definition_binding": True,
                "python_store": True,
            })
    elif op == "delete-name":
        require_no_result()
        if (len(item.arguments) != 1 or
                not isinstance(item.arguments[0], str) or
                not item.arguments[0]):
            malformed("expected one lexical name")
        require_attributes({
            "python_delete": True,
            "scope_resolution": "compiled-lexical-symbol-table",
        })
    elif op == "delete-attribute":
        require_no_result()
        if (len(item.arguments) != 2 or
                not is_ssa(item.arguments[0]) or
                not isinstance(item.arguments[1], str) or
                not item.arguments[1]):
            malformed("expected receiver SSA and attribute name")
        require_attributes({
            "python_delete": True,
            "receiver_evaluated_once": True,
        })
    elif op == "delete-subscript":
        require_no_result()
        if (len(item.arguments) != 2 or
                not all(is_ssa(value) for value in item.arguments)):
            malformed("expected container and index SSA values")
        require_attributes({
            "container_then_index": True,
            "operands_evaluated_once": True,
            "python_delete": True,
        })
    elif op == "construct-assertion-error":
        require_result("py-exception")
        if (len(item.arguments) not in {0, 1} or
                not all(is_ssa(value) for value in item.arguments)):
            malformed("expected zero or one message SSA")
        require_attributes({
            "builtin": "AssertionError",
            "message_evaluated_on_failure_only": True,
            "python_optimize_level": 0,
        })
    elif op == "python-import-module":
        require_result("py-value")
        if len(item.arguments) != 4:
            malformed("expected module, level, fromlist and return mode")
        module, level, from_names, return_mode = item.arguments
        if (module is not None and not isinstance(module, str)):
            malformed("module must be text or None")
        if not isinstance(level, int) or isinstance(level, bool) or level < 0:
            malformed("relative level must be a non-negative integer")
        if (not isinstance(from_names, tuple) or
                not all(isinstance(name, str) and name
                        for name in from_names)):
            malformed("fromlist must be a tuple of names")
        if return_mode not in {
                "root-package", "full-module", "fromlist-module"}:
            malformed("unknown return mode")
        if return_mode in {"root-package", "full-module"} and (
                not isinstance(module, str) or not module or level != 0 or
                from_names):
            malformed("plain import contract differs")
        if return_mode == "fromlist-module" and not from_names:
            malformed("from import requires a non-empty fromlist")
        require_attributes({
            "current_frame_globals_locals": True,
            "import_hook": "builtins.__import__",
            "single_import_call": True,
        })
    elif op == "python-import-from":
        require_result("py-value")
        if (len(item.arguments) != 2 or
                not is_ssa(item.arguments[0]) or
                not isinstance(item.arguments[1], str) or
                not item.arguments[1] or item.arguments[1] == "*"):
            malformed("expected imported object SSA and member name")
        require_attributes({
            "attribute_then_sys_modules_fallback": True,
            "python_opcode_semantics": "IMPORT_FROM",
        })
    elif op == "python-import-star":
        require_no_result()
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected imported object SSA")
        require_attributes({
            "binding_namespace": "current-locals",
            "names_rule": "__all__-else-public-module-names",
        })
    elif op == "capture-closure-cell":
        require_result("py-cell")
        if (len(item.arguments) != 1 or
                not isinstance(item.arguments[0], str) or
                not item.arguments[0]):
            malformed("expected one free-variable name")
        require_attributes({
            "capture": "cell-identity",
            "not_value_snapshot": True,
        })
    elif op == "load-current-globals":
        require_result("py-mapping")
        if item.arguments:
            malformed("globals load takes no operands")
        require_attributes({"mapping_identity_preserved": True})
    elif op == "make-class-body":
        require_result("py-function")
        if (len(item.arguments) != 4 or not isinstance(item.arguments[0], str) or
                "@" not in item.arguments[0] or not is_sha256(item.arguments[1]) or not is_ssa(item.arguments[2])):
            malformed("expected sealed class identity, globals and cells")
        cells = item.arguments[3]
        if (not isinstance(cells, tuple) or any(not isinstance(pair, tuple) or len(pair) != 2 or
                not isinstance(pair[0], str) or not pair[0] or not is_ssa(pair[1]) for pair in cells) or
                [name for name, _ in cells] != sorted({name for name, _ in cells})):
            malformed("class closure must contain unique sorted name/cell pairs")
        if type(attributes.get("implicit_class_cell")) is not bool:
            malformed("missing source __class__ cell contract")
        require_attributes({"body_execution": "class-suite", "source_sealed": True,
                            "implicit_class_cell": attributes["implicit_class_cell"]})
    elif op == "python-build-class":
        require_result("py-value")
        if (len(item.arguments) < 2 or not is_ssa(item.arguments[0]) or not isinstance(item.arguments[1], str) or not item.arguments[1]
                or not all(is_ssa(base) for base in item.arguments[2:])):
            malformed("expected class suite callable, source name and evaluated base SSA values")
        require_attributes({"namespace": "new-class-mapping", "implicit_object_base": len(item.arguments) == 2,
                            "base_evaluation": "left-to-right", "method_resolution": "C3"})
    elif op in {"setup-class-annotations", "setup-global-annotations"}:
        require_no_result()
        if item.arguments != ("__annotations__",):
            malformed("expected annotation namespace key")
        require_attributes({"existing_mapping_preserved": True})
    elif op == "make-function":
        require_result("py-function")
        if len(item.arguments) != 8:
            malformed("expected eight definition operands")
        (reference, ast_hash, definition_kind, globals_mapping,
         positional_defaults,
         keyword_defaults, closure, annotations) = item.arguments
        if (not isinstance(reference, str) or "@" not in reference or
                not reference.rsplit("@", 1)[1].isdigit()):
            malformed("invalid nested function reference")
        if (not is_sha256(ast_hash) or
                definition_kind not in {"function", "async-function"} or
                not is_ssa(globals_mapping)):
            malformed("invalid AST binding or globals SSA")

        def valid_pairs(value: object) -> bool:
            return (isinstance(value, tuple) and all(
                isinstance(row, tuple) and len(row) == 2 and
                isinstance(row[0], str) and bool(row[0]) and
                is_ssa(row[1]) for row in value))

        if (not valid_pairs(positional_defaults) or
                not valid_pairs(keyword_defaults) or
                not valid_pairs(closure)):
            malformed("defaults/closure must be named SSA pairs")
        for rows, label in (
                (positional_defaults, "positional defaults"),
                (keyword_defaults, "keyword defaults"),
                (closure, "closure")):
            names = [row[0] for row in rows]
            if len(names) != len(set(names)):
                malformed(f"duplicate name in {label}")
        if [row[0] for row in closure] != sorted(
                row[0] for row in closure):
            malformed("closure names are not deterministic")
        if (not isinstance(annotations, tuple) or not all(
                isinstance(row, tuple) and len(row) == 3 and
                isinstance(row[0], str) and bool(row[0]) and
                is_sha256(row[1]) and isinstance(row[2], str)
                for row in annotations)):
            malformed("annotation descriptors differ")
        annotation_names = [row[0] for row in annotations]
        if len(annotation_names) != len(set(annotation_names)):
            malformed("duplicate annotation name")
        annotation_mode = dict(item.attributes).get('annotation_mode')
        if annotation_mode not in (("future-stringized", "evaluated-cpython-3.12") if annotations else ("none",)):
            malformed('invalid annotation evaluation mode')
        require_attributes({
            "annotation_mode": annotation_mode,
            "async": definition_kind == "async-function",
            "body_execution": "deferred-until-call",
            "closure_binding": "cell-identity-by-name",
            "definition_evaluation_order": (
                "decorators-top-down;positional-defaults-left-to-right;"
                "keyword-only-defaults-left-to-right;annotations-cpython-3.12;make;"
                "decorators-bottom-up;bind"),
            "globals_binding": "mapping-identity",
            "lexical_qualname": True,
        })
    elif op in ('dataclass-resolve', 'dataclass-install', 'dataclass-metadata', 'dataclass-repr-pending'):
        require_result('py-value')
        if not item.arguments or not all(is_ssa(value) for value in item.arguments):
            malformed('native dataclass arguments must be evaluated SSA values')
        require_attributes({'library': 'cpython-3.12.dataclasses'})
    elif op == 'build-function-annotations':
        require_result('py-dict')
        if len(item.arguments) % 2 or not item.arguments or any(
                not isinstance(key, str) or not key or not is_ssa(value)
                for key, value in zip(item.arguments[::2], item.arguments[1::2])):
            malformed('expected annotation names and evaluated SSA values')
        if len(set(item.arguments[::2])) != len(item.arguments) // 2:
            malformed('duplicate annotation key')
        require_attributes({'order': 'cpython-3.12'})
    elif op == "python-apply-decorator":
        require_result("py-value")
        if (len(item.arguments) != 2 or
                not all(is_ssa(value) for value in item.arguments)):
            malformed("expected decorator and function SSA values")
        require_attributes({
            "application_order": "bottom-up",
            "decorator_expression_pre_evaluated": True,
            "single_positional_function_argument": True,
        })
    elif op == "python-with-load-enter":
        require_result("py-callable")
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one manager SSA")
        require_attributes({
            "descriptor_binding": "manager-instance",
            "lookup": "type(manager).__enter__",
            "lookup_order": "before-exit",
            "special_method_lookup": True,
        })
    elif op == "python-with-load-exit":
        require_result("py-callable")
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one manager SSA")
        require_attributes({
            "descriptor_binding": "manager-instance",
            "lookup": "type(manager).__exit__",
            "lookup_order": "after-enter-before-enter-call",
            "saved_for_all_exit_paths": True,
            "special_method_lookup": True,
        })
    elif op == "python-with-call-enter":
        require_result("py-value")
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one saved bound enter callable")
        require_attributes({
            "call": "saved-bound-__enter__()",
            "manager_not_active_until_success": True,
        })
    elif op == "python-with-call-exit-normal":
        require_result("py-value")
        if (len(item.arguments) != 4 or
                not is_ssa(item.arguments[0]) or
                item.arguments[1:] != (None, None, None)):
            malformed("expected saved bound exit and three None values")
        require_attributes({
            "exception_arguments": "None,None,None",
            "return_value_ignored": True,
            "special_method_call": "saved-bound-__exit__(None,None,None)",
        })
    elif op == "capture-current-exception" and attributes.get(
            "with_exception_value") is True:
        require_result("py-exception")
        if item.arguments:
            malformed("with exception capture takes no operands")
        require_attributes({
            "preserved_across_finalizer": True,
            "with_exception_value": True,
        })
    elif op == "python-exception-type":
        require_result("py-type")
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one exception SSA")
        require_attributes({"identity": "type(exception)"})
    elif op == "python-exception-traceback":
        require_result("py-traceback")
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one exception SSA")
        require_attributes({"identity": "exception.__traceback__"})
    elif op == "python-with-call-exit-exception":
        require_result("py-value")
        if (len(item.arguments) != 4 or
                not all(is_ssa(value) for value in item.arguments)):
            malformed("expected bound exit and exception-triple SSA")
        require_attributes({
            "arguments": "exc_type,exc,traceback",
            "special_method_call": (
                "saved-bound-__exit__(exc_type,exc,traceback)"),
            "truthy_result_suppresses": True,
        })
    elif op == "suppress-with-exception":
        require_no_result()
        if len(item.arguments) != 1 or not is_ssa(item.arguments[0]):
            malformed("expected one saved exception SSA")
        require_attributes({
            "restore_previous_exception_context": True,
            "suppression_requires_truthy_exit_result": True,
        })
    elif op in {"blocked-delete-target", "blocked-function-definition"}:
        require_no_result()
        if (len(item.arguments) != 1 or
                not isinstance(item.arguments[0], int) or
                isinstance(item.arguments[0], bool) or
                item.arguments[0] < 0):
            malformed("expected blocker index")
        require_attributes({"non_executable": True})


def _validate_with_protocol(function: ActivePythonFunctionIR) -> None:
    """Prove that every lowered manager has one exact enter/exit skeleton."""
    blocks = {block.name: block for block in function.blocks}
    located = [
        (block, item) for block in function.blocks
        for item in block.instructions]

    def rows(op: str) -> list[tuple[PythonFunctionBlock,
                                    ObjectEffectInstruction]]:
        return [(block, item) for block, item in located if item.op == op]

    loads_enter = {item.arguments[0]: (block, item)
                   for block, item in rows("python-with-load-enter")}
    loads_exit = {item.arguments[0]: (block, item)
                  for block, item in rows("python-with-load-exit")}
    enter_to_manager = {item.destination: item.arguments[0]
                        for _block, item in rows("python-with-load-enter")}
    exit_to_manager = {item.destination: item.arguments[0]
                       for _block, item in rows("python-with-load-exit")}
    calls_enter = {enter_to_manager.get(item.arguments[0]): (block, item)
                   for block, item in rows("python-with-call-enter")}
    exception_exits: dict[
        str, tuple[PythonFunctionBlock, ObjectEffectInstruction]] = {}
    for block, item in rows("python-with-call-exit-exception"):
        manager = exit_to_manager.get(item.arguments[0])
        if manager in exception_exits:
            raise FunctionCFGError(
                "PZFC320", "manager has multiple exceptional exits")
        exception_exits[manager] = (block, item)
    managers = set(loads_enter)
    if (managers != set(loads_exit) or managers != set(calls_enter) or
            managers != set(exception_exits) or
            len(loads_enter) != len(rows("python-with-load-enter")) or
            len(loads_exit) != len(rows("python-with-load-exit")) or
            len(calls_enter) != len(rows("python-with-call-enter"))):
        raise FunctionCFGError(
            "PZFC320", "with enter/exit manager sets differ")

    normal_exits: dict[
        str, list[tuple[PythonFunctionBlock, ObjectEffectInstruction]]] = (
            defaultdict(list))
    for block, item in rows("python-with-call-exit-normal"):
        manager = exit_to_manager.get(item.arguments[0])
        normal_exits[manager].append((block, item))
        if manager not in managers:
            raise FunctionCFGError(
                "PZFC320", "normal exit refers to an unknown manager")

    for manager in managers:
        enter_block, enter_load = loads_enter[manager]
        exit_load_block, exit_load = loads_exit[manager]
        call_block, enter_call = calls_enter[manager]
        exit_block, exceptional_exit = exception_exits[manager]
        if (enter_block.name != exit_load_block.name or
                enter_block.name != call_block.name or
                not (enter_load.sequence < exit_load.sequence <
                     enter_call.sequence) or
                enter_call.arguments[0] != enter_load.destination or
                exceptional_exit.arguments[0] != exit_load.destination or
                call_block.instructions[-1] != enter_call or
                call_block.terminator.op != "jump" or
                len(call_block.terminator.targets) != 1):
            raise FunctionCFGError(
                "PZFC320", "with lookup/enter order or binding differs")
        protected = blocks[call_block.terminator.targets[0]]
        if (protected.exception_target != exit_block.name or
                call_block.exception_target != exit_block.exception_target):
            raise FunctionCFGError(
                "PZFC320", "__enter__ failure/protected-region edge differs")
        if (exit_block.terminator.op != "branch-truth" or
                exit_block.terminator.arguments != (
                    exceptional_exit.destination,) or
                len(exit_block.terminator.targets) != 2):
            raise FunctionCFGError(
                "PZFC320", "exceptional __exit__ suppression branch differs")

        exception = exceptional_exit.arguments[2]
        exception_type = exceptional_exit.arguments[1]
        traceback = exceptional_exit.arguments[3]
        definitions = {item.destination: (block, item)
                       for block, item in located
                       if item.destination is not None}
        required = {
            exception: "capture-current-exception",
            exception_type: "python-exception-type",
            traceback: "python-exception-traceback",
        }
        if any(value not in definitions or definitions[value][0] != exit_block
               or definitions[value][1].op != op
               for value, op in required.items()):
            raise FunctionCFGError(
                "PZFC320", "exception triple is not captured in exit block")
        type_item = definitions[exception_type][1]
        traceback_item = definitions[traceback][1]
        if (type_item.arguments != (exception,) or
                traceback_item.arguments != (exception,)):
            raise FunctionCFGError(
                "PZFC320", "exception triple does not share saved value")

        first, second = (blocks[name]
                         for name in exit_block.terminator.targets)
        suppression_blocks = [block for block in (first, second)
                              if any(item.op == "suppress-with-exception"
                                     for item in block.instructions)]
        propagation_blocks = [block for block in (first, second)
                              if block.terminator.op == "raise-saved"]
        if (len(suppression_blocks) != 1 or
                len(propagation_blocks) != 1 or
                propagation_blocks[0].terminator.arguments != (exception,)):
            raise FunctionCFGError(
                "PZFC320", "with suppression/propagation successors differ")
        suppress_ops = [item for item in suppression_blocks[0].instructions
                        if item.op == "suppress-with-exception"]
        if (len(suppress_ops) != 1 or
                suppress_ops[0].arguments != (exception,)):
            raise FunctionCFGError(
                "PZFC320", "with suppression loses saved exception")
        for normal_block, normal_exit in normal_exits.get(manager, ()):
            if (normal_exit.arguments[0] != exit_load.destination or
                    normal_block.exception_target !=
                    exit_block.exception_target):
                raise FunctionCFGError(
                    "PZFC320", "normal __exit__ binding/throw edge differs")


def _validate_function(function: ActivePythonFunctionIR) -> None:
    blocks = {block.name: block for block in function.blocks}
    if function.entry not in blocks or len(blocks) != len(function.blocks):
        raise FunctionCFGError(
            "PZFC301", f"invalid entry/blocks in {function.function_id}")
    instructions = [item for block in function.blocks
                    for item in block.instructions]
    if sorted(item.sequence for item in instructions) != list(range(
            len(instructions))):
        raise FunctionCFGError(
            "PZFC302", f"non-contiguous sequence in {function.function_id}")
    definitions: dict[str, tuple[str, int]] = {}
    definition_kinds: dict[str, str | None] = {}
    expression_ids = {program.program_id
                      for program in function.expression_programs}
    if len(expression_ids) != len(function.expression_programs):
        raise FunctionCFGError(
            "PZFC303", f"duplicate expression program in "
            f"{function.function_id}")
    for program in function.expression_programs:
        _validate_extended_expression_program(program)
    executed_expressions: list[str] = []
    spliced: list[tuple[int, str]] = []
    raise_arities = {
        "raise-current": 0,
        "raise-explicit": 1,
        "raise-explicit-from": 2,
        "raise-saved": 1,
    }
    for block in function.blocks:
        for item in block.instructions:
            _validate_statement_instruction(item)
            if item.destination is not None:
                if item.destination in definitions:
                    raise FunctionCFGError(
                        "PZFC304", f"duplicate SSA {item.destination}")
                definitions[item.destination] = (block.name, item.sequence)
                definition_kinds[item.destination] = item.value_kind
            if item.op == "execute-expression-cfg":
                if len(item.arguments) != 1 or not isinstance(
                        item.arguments[0], str):
                    raise FunctionCFGError(
                        "PZFC305", "malformed expression reference")
                executed_expressions.append(item.arguments[0])
            if item.op == "execute-object-store-fragment":
                if (len(item.arguments) != 2 or
                        not isinstance(item.arguments[0], int) or
                        not isinstance(item.arguments[1], str)):
                    raise FunctionCFGError(
                        "PZFC306", "malformed store-fragment reference")
                spliced.append((item.arguments[0], item.arguments[1]))
            if item.op == "clear-except-target" and (
                    len(item.arguments) != 1 or
                    not isinstance(item.arguments[0], str) or
                    not item.arguments[0]):
                raise FunctionCFGError(
                    "PZFC314", "malformed except-target cleanup")
        for target in block.terminator.targets:
            if target not in blocks:
                raise FunctionCFGError(
                    "PZFC307", f"missing block target {target}")
        if (block.exception_target is not None and
                block.exception_target not in blocks):
            raise FunctionCFGError(
                "PZFC307", f"missing exception target "
                f"{block.exception_target}")
        expected_raise_arity = raise_arities.get(block.terminator.op)
        if expected_raise_arity is not None and (
                len(block.terminator.arguments) != expected_raise_arity or
                block.terminator.targets):
            raise FunctionCFGError(
                "PZFC315", f"malformed {block.terminator.op} terminator")
        if block.terminator.op == "suspend-yield":
            arguments = block.terminator.arguments
            if (len(arguments) != 2 or
                    not isinstance(arguments[0], str) or
                    not arguments[0].startswith("%fn_") or
                    not isinstance(arguments[1], int) or
                    isinstance(arguments[1], bool) or
                    arguments[1] <= 0 or
                    len(block.terminator.targets) != 1):
                raise FunctionCFGError(
                    "PZFC319", "malformed suspend-yield terminator")
        if block.terminator.op == "suspend-yield-from":
            arguments = block.terminator.arguments
            if (len(arguments) != 3 or
                    not isinstance(arguments[0], str) or
                    not arguments[0].startswith("%fn_") or
                    not isinstance(arguments[1], int) or
                    isinstance(arguments[1], bool) or
                    arguments[1] <= 0 or
                    arguments[2] != _yield_from_protocol() or
                    len(block.terminator.targets) != 1):
                raise FunctionCFGError(
                    "PZFC319", "malformed suspend-yield-from terminator")
        if block.terminator.op == "generator-return":
            arguments = block.terminator.arguments
            if (len(arguments) not in {0, 1} or
                    not all(isinstance(value, str) and
                            value.startswith("%fn_")
                            for value in arguments) or
                    block.terminator.targets):
                raise FunctionCFGError(
                    "PZFC319", "malformed generator-return terminator")
        if block.terminator.op == "raise":
            raise FunctionCFGError(
                "PZFC315", "ambiguous legacy raise terminator")
    _validate_with_protocol(function)
    if Counter(executed_expressions) != Counter(expression_ids):
        raise FunctionCFGError(
            "PZFC308", f"expression programs are not executed once in "
            f"{function.function_id}")
    if sorted(spliced) != sorted(function.spliced_store_fragments):
        raise FunctionCFGError(
            "PZFC309", f"fragment splices differ in {function.function_id}")

    for block in function.blocks:
        for item in block.instructions:
            if item.op == "make-class-body":
                if definition_kinds.get(item.arguments[2]) != "py-mapping" or any(
                        definition_kinds.get(cell) != "py-cell" for _, cell in item.arguments[3]):
                    raise FunctionCFGError("PZFC317", "class body globals/cells have invalid SSA kinds")
            if item.op == "python-build-class" and definition_kinds.get(item.arguments[0]) != "py-function":
                raise FunctionCFGError("PZFC317", "class body operand is not a source function")
            if item.op == "make-function":
                globals_mapping = item.arguments[3]
                closure = item.arguments[6]
                if definition_kinds.get(globals_mapping) != "py-mapping":
                    raise FunctionCFGError(
                        "PZFC317", "make-function globals operand is not "
                        "a globals mapping")
                if any(definition_kinds.get(cell) != "py-cell"
                       for _name, cell in closure):
                    raise FunctionCFGError(
                        "PZFC317", "make-function closure operand is not "
                        "a captured cell")
            if item.op == "python-apply-decorator" and (
                    definition_kinds.get(item.arguments[1]) not in
                    {"py-function", "py-value"}):
                raise FunctionCFGError(
                    "PZFC317", "decorator input is not the function or "
                    "previous decorator result")
            attributes = dict(item.attributes)
            if (item.op in ("store-name", "store-global-name") and
                    attributes.get("import_binding") is True and
                    definition_kinds.get(item.arguments[1]) != "py-value"):
                raise FunctionCFGError(
                    "PZFC317", "import binding source is not an imported "
                    "Python value")
            if (item.op in ("store-name", "store-global-name") and
                    attributes.get("function_definition_binding") is True and
                    definition_kinds.get(item.arguments[1]) not in
                    {"py-function", "py-value"}):
                raise FunctionCFGError(
                    "PZFC317", "function binding source is not a function "
                    "or decorator result")

    predecessors: dict[str, set[str]] = {name: set() for name in blocks}
    reachable = {function.entry}
    pending = [function.entry]
    while pending:
        name = pending.pop()
        successors = list(blocks[name].terminator.targets)
        if blocks[name].exception_target is not None:
            successors.append(blocks[name].exception_target)
        for target in successors:
            predecessors[target].add(name)
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    if reachable != set(blocks):
        raise FunctionCFGError(
            "PZFC310", f"unreachable CFG blocks in {function.function_id}")
    dominators: dict[str, set[str]] = {
        name: ({name} if name == function.entry else set(blocks))
        for name in blocks}
    changed = True
    while changed:
        changed = False
        for name in blocks:
            if name == function.entry:
                continue
            incoming = predecessors[name]
            common = (set.intersection(*(dominators[item]
                                         for item in incoming))
                      if incoming else set())
            updated = {name} | common
            if updated != dominators[name]:
                dominators[name] = updated
                changed = True

    def require(value: str, block_name: str,
                sequence: int | None) -> None:
        definition = definitions.get(value)
        if definition is None:
            raise FunctionCFGError("PZFC311", f"undefined SSA {value}")
        definition_block, definition_sequence = definition
        if definition_block not in dominators[block_name]:
            raise FunctionCFGError(
                "PZFC312", f"SSA {value} does not dominate {block_name}")
        if (definition_block == block_name and sequence is not None and
                definition_sequence >= sequence):
            raise FunctionCFGError(
                "PZFC313", f"SSA {value} used before definition")

    generator_instruction_ops = {
        "generator-frame-enter", "generator-save-frame",
        "generator-restore-frame", "generator-resume-value",
        "generator-delegation-start", "generator-yield-from-result",
    }
    generator_instructions = [
        (block, item) for block in function.blocks
        for item in block.instructions if item.op in generator_instruction_ops]
    suspension_blocks = [
        block for block in function.blocks
        if block.terminator.op in {"suspend-yield", "suspend-yield-from"}]
    generator_returns = [
        block for block in function.blocks
        if block.terminator.op == "generator-return"]
    ordinary_returns = [
        block for block in function.blocks if block.terminator.op == "return"]
    signature_is_generator = (
        function.signature.get("execution_kind") == "generator-frame")
    has_generator_ir = bool(
        generator_instructions or suspension_blocks or generator_returns)

    def generator_contract_error(detail: str) -> None:
        raise FunctionCFGError(
            "PZFC319", f"generator contract differs in "
            f"{function.function_id}: {detail}")

    if signature_is_generator != has_generator_ir:
        generator_contract_error("signature and CFG kind disagree")
    if not signature_is_generator:
        if any(key in function.signature for key in {
                "invocation", "first_resume", "completion",
                "source_suspension_count", "source_yield_from_count",
                "lowered_suspension_state_count",
                "yield_from_state_count", "frame"}):
            generator_contract_error("ordinary signature carries frame data")
    else:
        if ordinary_returns:
            generator_contract_error("ordinary return in generator CFG")
        if function.signature.get("invocation") != (
                "return-generator-object-without-running-body"):
            generator_contract_error("invocation timing differs")
        if function.signature.get("first_resume") != {
                "next": "enter-body-with-None",
                "send-none": "enter-body-with-None",
                "send-non-none": "TypeError-before-body",
                "throw": "raise-at-function-entry",
                "close": "complete-without-running-body",
        }:
            generator_contract_error("first-resume protocol differs")
        if function.signature.get("completion") != (
                "return-or-fallthrough-closes-frame-and-raises-"
                "StopIteration(return-value)"):
            generator_contract_error("completion protocol differs")
        frame = function.signature.get("frame")
        expected_frame_keys = {
            "format", "local_slots", "state_slot_count",
            "resume_command_value_slot_count", "max_operand_stack_slots",
            "bounded_slot_count", "bounded_by_source_ast", "states",
        }
        if not isinstance(frame, dict) or set(frame) != expected_frame_keys:
            generator_contract_error("frame signature keys differ")
        assert isinstance(frame, dict)
        local_slots = frame["local_slots"]
        if (frame["format"] != GENERATOR_FRAME_FORMAT or
                frame["state_slot_count"] != 1 or
                frame["resume_command_value_slot_count"] != 1 or
                frame["bounded_by_source_ast"] is not True or
                not isinstance(local_slots, tuple) or
                tuple(sorted(set(local_slots))) != local_slots or
                not all(isinstance(name, str) and name
                        for name in local_slots)):
            generator_contract_error("frame header differs")
        states = frame["states"]
        if not isinstance(states, tuple):
            generator_contract_error("frame states are not immutable")
        assert isinstance(states, tuple)
        descriptors = [
            _validated_generator_frame_descriptor(
                descriptor, code="PZFC319",
                context=f"generator state {index}")
            for index, descriptor in enumerate(states, 1)]
        state_ids = [int(descriptor["state"])
                     for descriptor in descriptors]
        if state_ids != list(range(1, len(descriptors) + 1)):
            generator_contract_error("state ids are not contiguous")
        if any(descriptor["local_slots"] != local_slots
               for descriptor in descriptors):
            generator_contract_error("state local slots differ")
        max_operand = max(
            (int(descriptor["operand_stack_slots"])
             for descriptor in descriptors), default=0)
        max_bound = max(
            (int(descriptor["bounded_slot_count"])
             for descriptor in descriptors), default=len(local_slots) + 2)
        if (frame["max_operand_stack_slots"] != max_operand or
                frame["bounded_slot_count"] != max_bound):
            generator_contract_error("frame maxima differ")

        def non_negative_count(value: object) -> bool:
            return (isinstance(value, int) and
                    not isinstance(value, bool) and value >= 0)

        source_count = function.signature.get("source_suspension_count")
        source_yield_from = function.signature.get(
            "source_yield_from_count")
        lowered_count = function.signature.get(
            "lowered_suspension_state_count")
        lowered_yield_from = function.signature.get(
            "yield_from_state_count")
        if not all(non_negative_count(value) for value in (
                source_count, source_yield_from, lowered_count,
                lowered_yield_from)):
            generator_contract_error("suspension counts are malformed")
        assert isinstance(source_count, int)
        assert isinstance(source_yield_from, int)
        assert isinstance(lowered_count, int)
        assert isinstance(lowered_yield_from, int)
        expected_yield_from = sum(
            descriptor["suspension_kind"] == "yield-from"
            for descriptor in descriptors)
        if (lowered_count != len(descriptors) or
                lowered_count != len(suspension_blocks) or
                lowered_yield_from != expected_yield_from or
                source_count < lowered_count or
                source_yield_from < lowered_yield_from or
                source_yield_from > source_count):
            generator_contract_error("suspension counts differ")
        if (not function.blockers and
                (source_count != lowered_count or
                 source_yield_from != lowered_yield_from)):
            generator_contract_error(
                "unblocked source suspension lacks a state")

        entry_rows = [
            (block, item) for block, item in generator_instructions
            if item.op == "generator-frame-enter"]
        if (len(entry_rows) != 1 or
                entry_rows[0][0].name != function.entry or
                not blocks[function.entry].instructions or
                blocks[function.entry].instructions[0] != entry_rows[0][1] or
                entry_rows[0][1].arguments != (local_slots,)):
            generator_contract_error("frame entry is not unique and first")

        saves: dict[int, list[tuple[PythonFunctionBlock,
                                    ObjectEffectInstruction]]] = defaultdict(list)
        restores: dict[int, list[tuple[PythonFunctionBlock,
                                       ObjectEffectInstruction]]] = defaultdict(list)
        resumes: dict[int, list[tuple[PythonFunctionBlock,
                                      ObjectEffectInstruction]]] = defaultdict(list)
        delegation_results: dict[
            int, list[tuple[PythonFunctionBlock,
                            ObjectEffectInstruction]]] = defaultdict(list)
        for block, item in generator_instructions:
            if item.op == "generator-save-frame":
                saves[int(item.arguments[0])].append((block, item))
            elif item.op == "generator-restore-frame":
                restores[int(item.arguments[0])].append((block, item))
            elif item.op == "generator-resume-value":
                resumes[int(item.arguments[0])].append((block, item))
            elif item.op == "generator-yield-from-result":
                delegation_results[int(item.arguments[0])].append(
                    (block, item))
        suspensions: dict[int, list[PythonFunctionBlock]] = defaultdict(list)
        for block in suspension_blocks:
            suspensions[int(block.terminator.arguments[1])].append(block)

        for descriptor in descriptors:
            state = int(descriptor["state"])
            if (len(saves[state]) != 1 or len(restores[state]) != 1 or
                    len(suspensions[state]) != 1):
                generator_contract_error(
                    f"state {state} save/restore/suspend cardinality differs")
            suspension = suspensions[state][0]
            save_block, save = saves[state][0]
            restore_block, restore = restores[state][0]
            if (save.arguments[1] != descriptor or
                    restore.arguments[1] != descriptor):
                generator_contract_error(
                    f"state {state} descriptor binding differs")
            if (save_block != suspension or
                    not suspension.instructions or
                    suspension.instructions[-1] != save):
                generator_contract_error(
                    f"state {state} save is not immediately before suspend")
            if (suspension.terminator.targets != (
                    descriptor["resume_target"],) or
                    restore_block.name != descriptor["resume_target"] or
                    not restore_block.instructions or
                    restore_block.instructions[0] != restore or
                    suspension.exception_target !=
                    descriptor["exception_target"] or
                    restore_block.exception_target !=
                    descriptor["exception_target"]):
                generator_contract_error(
                    f"state {state} resume/control binding differs")
            if any(target not in blocks for pair in descriptor["loop_stack"]
                   for target in pair):
                generator_contract_error(
                    f"state {state} loop target is absent")
            spill_slots = descriptor["spill_slots"]
            if any(value not in definitions for value in spill_slots):
                generator_contract_error(
                    f"state {state} spills an undefined SSA value")
            if tuple(sorted(
                    spill_slots,
                    key=lambda value: definitions[value][1])) != (
                    spill_slots):
                generator_contract_error(
                    f"state {state} spill order is not definition order")
            for value in spill_slots:
                definition = definitions.get(value)
                if definition is None:
                    generator_contract_error(
                        f"state {state} spills undefined {value}")
                definition_block, definition_sequence = definitions[value]
                if definition_block not in dominators[suspension.name]:
                    generator_contract_error(
                        f"state {state} spill does not dominate suspend")
                if (definition_block == suspension.name and
                        definition_sequence >= save.sequence):
                    generator_contract_error(
                        f"state {state} spill is defined after save")

            if descriptor["suspension_kind"] == "yield":
                if (suspension.terminator.op != "suspend-yield" or
                        descriptor["operand_stack_slots"] != 0 or
                        len(resumes[state]) != 1 or
                        delegation_results[state]):
                    generator_contract_error(
                        f"state {state} yield protocol differs")
                result_block, result = resumes[state][0]
            else:
                delegate = suspension.terminator.arguments[0]
                if (suspension.terminator.op != "suspend-yield-from" or
                        descriptor["operand_stack_slots"] != 1 or
                        delegate not in spill_slots or resumes[state] or
                        len(delegation_results[state]) != 1):
                    generator_contract_error(
                        f"state {state} yield-from protocol differs")
                result_block, result = delegation_results[state][0]
            if (result_block != restore_block or
                    result.sequence <= restore.sequence):
                generator_contract_error(
                    f"state {state} resume result precedes restore")

        known_states = set(state_ids)
        if (set(saves) != known_states or set(restores) != known_states or
                set(suspensions) != known_states or
                set(resumes) | set(delegation_results) != known_states):
            generator_contract_error("orphan generator state operation")

    for block in function.blocks:
        for item in block.instructions:
            for value in _ssa_values(item.arguments):
                require(value, block.name, item.sequence)
        for value in _ssa_values(block.terminator.arguments):
            require(value, block.name, None)


def _owner_scope(node: ast.AST,
                 parents: Mapping[ast.AST, ast.AST]) -> tuple[
                     ast.FunctionDef | ast.AsyncFunctionDef | None,
                     str | None]:
    cursor = node
    function: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    class_name: str | None = None
    while cursor in parents:
        cursor = parents[cursor]
        if function is None and isinstance(
                cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = cursor
        if isinstance(cursor, ast.ClassDef):
            class_name = cursor.name
            break
    return function, class_name


def _statement_census(
        functions: list[ast.FunctionDef | ast.AsyncFunctionDef],
        function_irs: list[ActivePythonFunctionIR],
        ) -> dict[str, Any]:
    statements: Counter[str] = Counter()
    controls: Counter[str] = Counter()
    expression_nodes: Counter[str] = Counter()
    for function in functions:
        for node in ast.walk(function):
            if node is function:
                continue
            if isinstance(node, ast.stmt):
                statements[type(node).__name__] += 1
            if isinstance(node, ast.expr):
                expression_nodes[type(node).__name__] += 1
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try,
                                 ast.With, ast.AsyncWith, ast.Match)):
                controls[type(node).__name__] += 1
    blockers = [blocker for function in function_irs
                for blocker in function.blockers]
    blocker_codes = Counter(item.code for item in blockers)
    blocker_kinds = Counter(item.node_kind for item in blockers)
    return {
        "body_statement_count": sum(statements.values()),
        "statement_ast_kind_counts": dict(sorted(statements.items())),
        "control_ast_kind_counts": dict(sorted(controls.items())),
        "expression_ast_kind_counts": dict(sorted(expression_nodes.items())),
        "unsupported_count": len(blockers),
        "unsupported_code_counts": dict(sorted(blocker_codes.items())),
        "unsupported_ast_kind_counts": dict(sorted(blocker_kinds.items())),
        "unsupported": [item.to_json() for item in blockers],
    }


def build_active_function_cfg_ir(
        project_root: Path | str, *,
        hook_plan: MutationHookPlan | None = None,
        object_store_module: ObjectStoreModuleIR | None = None,
        ) -> ActivePythonFunctionModuleIR:
    root = Path(project_root).resolve()
    active_hooks = hook_plan or build_mutation_hook_ir(root)
    stores = object_store_module or lower_active_object_store_ir(
        root, hook_plan=active_hooks)
    if (stores.mutation_hook_semantic_sha256 !=
            active_hooks.semantic_sha256):
        raise FunctionCFGError(
            "PZFC001", "object-store module does not bind active hooks")
    source_path = root / str(active_hooks.source_path)
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if (source_hash != active_hooks.source_sha256 or
            source_hash != stores.source_sha256):
        raise FunctionCFGError(
            "PZFC002", "function CFG inputs are stale against source")
    source_text = source_bytes.decode("utf-8")
    tree = ast.parse(source_text, filename=str(source_path), type_comments=True)
    parents = {child: parent for parent in ast.walk(tree)
               for child in ast.iter_child_nodes(parent)}
    candidates: dict[tuple[int, str], list[ast.AST]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                             ast.Delete, ast.Call)):
            candidates[(int(getattr(node, "lineno", 0)),
                        _ast_sha256(node))].append(node)
    fragments = {item.site_id: item for item in stores.fragments}
    by_function: dict[
        ast.FunctionDef | ast.AsyncFunctionDef,
        dict[ast.AST, ObjectStoreFragmentIR]] = defaultdict(dict)
    classes: dict[ast.FunctionDef | ast.AsyncFunctionDef, str | None] = {}
    runtime_hooks = [item for item in active_hooks.mutation_hooks
                     if item["runtime_hook_required"]]
    for hook in runtime_hooks:
        key = (int(hook["line"]), str(hook["statement_ast_sha256"]))
        matches = candidates.get(key, ())
        if len(matches) != 1:
            raise FunctionCFGError(
                "PZFC003", f"site {hook['site_id']} resolves to "
                f"{len(matches)} statements")
        function, class_name = _owner_scope(matches[0], parents)
        if function is None:
            raise FunctionCFGError(
                "PZFC004", f"site {hook['site_id']} has no function owner")
        if (function.name != hook.get("function") or
                class_name != hook.get("class")):
            raise FunctionCFGError(
                "PZFC005", f"site {hook['site_id']} owner differs")
        fragment = fragments.get(int(hook["site_id"]))
        if fragment is None:
            raise FunctionCFGError(
                "PZFC006", f"site {hook['site_id']} has no store fragment")
        by_function[function][matches[0]] = fragment
        classes[function] = class_name
    function_nodes = sorted(by_function, key=lambda item: item.lineno)
    function_irs = [
        lower_python_function_cfg(
            node=node,
            class_name=classes[node],
            source_path=Path(active_hooks.source_path),
            source_text=source_text,
            fragments=by_function[node],
        )
        for node in function_nodes
    ]
    census = _statement_census(function_nodes, function_irs)
    site_distribution = Counter(len(item.mutation_site_ids)
                                for item in function_irs)
    all_instructions = [instruction for function in function_irs
                        for block in function.blocks
                        for instruction in block.instructions]
    all_programs = [program for function in function_irs
                    for program in function.expression_programs]
    coverage: dict[str, Any] = {
        "function_count": len(function_irs),
        "runtime_mutation_site_count": len(runtime_hooks),
        "spliced_store_fragment_count": sum(
            len(item.spliced_store_fragments) for item in function_irs),
        "site_count_per_function_distribution": {
            str(key): value for key, value in sorted(site_distribution.items())},
        "cfg_block_count": sum(len(item.blocks) for item in function_irs),
        "cfg_exception_edge_count": sum(
            block.exception_target is not None
            for item in function_irs for block in item.blocks),
        "cfg_instruction_count": len(all_instructions),
        "function_expression_program_count": len(all_programs),
        "function_expression_block_count": sum(
            len(item.blocks) for item in all_programs),
        "function_expression_instruction_count": sum(
            len(block.instructions) for item in all_programs
            for block in item.blocks),
        "functions_without_blockers": sum(
            not item.blockers for item in function_irs),
        "functions_with_blockers": sum(
            bool(item.blockers) for item in function_irs),
        **census,
        "all_runtime_sites_spliced_once": True,
        "exact_object_store_fragments_reused": True,
        "expressions_use_object_expression_ir": True,
        "full_function_cfg_lowered": census["unsupported_count"] == 0,
        "current_c_backend_consumes_function_cfg": False,
        "live_claimed": False,
        "compiler_input_sha256": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in (
                "Source/Tools/pyz80_compiler/function_cfg.py",
                "Source/Tools/pyz80_compiler/frontend.py",
                "Source/Tools/pyz80_compiler/ir.py",
            )
        },
    }
    payload = {
        "format": FUNCTION_CFG_IR_FORMAT,
        "source_path": active_hooks.source_path,
        "source_sha256": source_hash,
        "mutation_hook_semantic_sha256": active_hooks.semantic_sha256,
        "object_store_semantic_sha256": stores.semantic_sha256,
        "functions": [item.to_json() for item in function_irs],
        "coverage": coverage,
    }
    module = ActivePythonFunctionModuleIR(
        format=FUNCTION_CFG_IR_FORMAT,
        source_path=str(active_hooks.source_path),
        source_sha256=source_hash,
        mutation_hook_semantic_sha256=active_hooks.semantic_sha256,
        object_store_semantic_sha256=stores.semantic_sha256,
        functions=tuple(function_irs),
        coverage=coverage,
        semantic_sha256=_json_sha256(payload),
    )
    validate_active_function_cfg_ir(module, stores, active_hooks)
    return module


def validate_active_function_cfg_ir(
        module: ActivePythonFunctionModuleIR,
        stores: ObjectStoreModuleIR,
        hooks: MutationHookPlan,
        ) -> None:
    if module.format != FUNCTION_CFG_IR_FORMAT:
        raise FunctionCFGError("PZFC401", "function CFG format mismatch")
    if (module.source_path != stores.source_path or
            module.source_sha256 != stores.source_sha256 or
            module.mutation_hook_semantic_sha256 != hooks.semantic_sha256 or
            module.object_store_semantic_sha256 != stores.semantic_sha256):
        raise FunctionCFGError("PZFC402", "function CFG binding mismatch")
    if len({item.function_id for item in module.functions}) != len(
            module.functions):
        raise FunctionCFGError("PZFC403", "duplicate function id")
    for function in module.functions:
        _validate_function(function)
    expected_ids = sorted(int(item["site_id"])
                          for item in hooks.mutation_hooks
                          if item["runtime_hook_required"])
    mutation_ids = sorted(site_id for function in module.functions
                          for site_id in function.mutation_site_ids)
    splice_rows = [row for function in module.functions
                   for row in function.spliced_store_fragments]
    splice_ids = sorted(site_id for site_id, _ in splice_rows)
    fragment_semantics = {item.site_id: item.semantic_sha256
                          for item in stores.fragments}
    if mutation_ids != expected_ids or splice_ids != expected_ids:
        raise FunctionCFGError(
            "PZFC404", "runtime sites are not covered exactly once")
    for site_id, semantic in splice_rows:
        if fragment_semantics.get(site_id) != semantic:
            raise FunctionCFGError(
                "PZFC405", f"site {site_id} fragment semantic differs")
    coverage = module.coverage
    if (coverage.get("function_count") != len(module.functions) or
            coverage.get("runtime_mutation_site_count") != len(expected_ids) or
            coverage.get("spliced_store_fragment_count") != len(expected_ids) or
            coverage.get("all_runtime_sites_spliced_once") is not True or
            coverage.get("exact_object_store_fragments_reused") is not True or
            coverage.get("current_c_backend_consumes_function_cfg") is not False or
            coverage.get("live_claimed") is not False):
        raise FunctionCFGError("PZFC406", "coverage invariant mismatch")


def function_cfg_report(
        module: ActivePythonFunctionModuleIR) -> dict[str, Any]:
    unsupported = int(module.coverage["unsupported_count"])
    blocker_rows = ([
        f"{unsupported} exact unsupported AST construct(s) remain"
    ] if unsupported else [])
    return {
        **module.to_json(),
        "status": ("ACTIVE_FUNCTION_CFG_COMPLETE_LIVE_BLOCKED"
                   if unsupported == 0 else
                   "ACTIVE_FUNCTION_CFG_PARTIAL_LIVE_BLOCKED"),
        "live": False,
        "supported_contract": {
            "statements": (
                "Assign, AnnAssign, AugAssign, Expr, If, While, For, "
                "Try/Except/Else/Finally, With, Return, Raise, Break, "
                "Continue, "
                "Delete, Assert, Import, ImportFrom, nested FunctionDef, "
                "Pass"),
            "assignment_targets": (
                "name, attribute, subscript, recursive tuple/list unpack"),
            "delete_targets": (
                "name, attribute, subscript, recursive tuple/list; "
                "left-to-right and single evaluation"),
            "nested_functions": (
                "decorators/defaults/closure/globals/make/bind are explicit; "
                "postponed annotations are source-bound"),
            "loops": "explicit header/body/else/merge CFG",
            "exceptions": (
                "block exceptional successors, ordered handler matching, "
                "normal-only else and cleanup on every control transfer"),
            "context_managers": (
                "left-to-right special-method lookup and enter; nested "
                "reverse-order exit on normal/control/exception paths; "
                "truthy exceptional exit suppresses; AsyncWith remains "
                "explicitly blocked until an await CFG exists"),
            "expressions": "ObjectExpressionIR subprograms executed once",
            "mutations": "exact ObjectStoreFragmentIR semantic references",
        },
        "live_blockers": blocker_rows + [
            "the C backend and VM provider do not consume function CFG",
            "linked object layout, provider, stack and tstate proofs are absent",
        ],
    }


def write_active_function_cfg_report(
        project_root: Path | str, output_path: Path | str,
        ) -> ActivePythonFunctionModuleIR:
    module = build_active_function_cfg_ir(project_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(json.dumps(
        function_cfg_report(module), ensure_ascii=False,
        sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return module
