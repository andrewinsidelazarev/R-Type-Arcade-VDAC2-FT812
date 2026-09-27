"""Понижение поддержанного Python AST в независимое трёхадресное IR."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .diagnostics import CompileError, Diagnostic, SourceSpan, fail
from .ir import (BasicBlock, FunctionIR, Instruction,
                 ObjectEffectInstruction, ObjectExpressionBlock,
                 ObjectExpressionIR, ObjectExpressionTerminator,
                 ObjectStoreFragmentIR, ObjectStoreModuleIR, Terminator)
from .manifest import FunctionSpec
from .types import BOOL, PYINT, ScalarType


def _semantic_hash(node: ast.AST) -> str:
    payload = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_BINARY_OPERATOR_NAMES: dict[type[ast.operator], str] = {
    ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul",
    ast.Div: "truediv", ast.FloorDiv: "floordiv", ast.Mod: "mod",
    ast.Pow: "pow", ast.LShift: "lshift", ast.RShift: "rshift",
    ast.BitAnd: "bitand", ast.BitOr: "bitor", ast.BitXor: "bitxor",
    ast.MatMult: "matmul",
}

_UNARY_OPERATOR_NAMES: dict[type[ast.unaryop], str] = {
    ast.UAdd: "pos", ast.USub: "neg", ast.Invert: "invert",
    ast.Not: "not",
}

_BOOLEAN_OPERATOR_NAMES: dict[type[ast.boolop], str] = {
    ast.And: "and", ast.Or: "or",
}

_COMPARISON_OPERATOR_NAMES: dict[type[ast.cmpop], str] = {
    ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le",
    ast.Gt: "gt", ast.GtE: "ge", ast.Is: "is", ast.IsNot: "is-not",
    ast.In: "in", ast.NotIn: "not-in",
}


def _safe_constant(node: ast.AST, values: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant) and isinstance(
            node.value, (int, bool, str, bytes, type(None))):
        return node.value
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _safe_constant(node.operand, values)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Invert):
            return ~operand
        if isinstance(node.op, ast.Not):
            return not operand
    if isinstance(node, (ast.Tuple, ast.List)):
        result = tuple(_safe_constant(item, values) for item in node.elts)
        return result if isinstance(node, ast.Tuple) else list(result)
    if isinstance(node, ast.BinOp):
        left = _safe_constant(node.left, values)
        right = _safe_constant(node.right, values)
        operations = {
            ast.Add: lambda: left + right,
            ast.Sub: lambda: left - right,
            ast.Mult: lambda: left * right,
            ast.FloorDiv: lambda: left // right,
            ast.Mod: lambda: left % right,
            ast.LShift: lambda: left << right,
            ast.RShift: lambda: left >> right,
            ast.BitAnd: lambda: left & right,
            ast.BitOr: lambda: left | right,
            ast.BitXor: lambda: left ^ right,
        }
        action = operations.get(type(node.op))
        if action is not None:
            return action()
    raise ValueError("не константное выражение")


def module_constants(tree: ast.Module) -> dict[str, Any]:
    """Вычислить только чистые верхнеуровневые литеральные выражения."""
    values: dict[str, Any] = {}
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target])
        value_node = statement.value
        if value_node is None or len(targets) != 1:
            continue
        target = targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = _safe_constant(value_node, values)
        except (ArithmeticError, TypeError, ValueError):
            continue
    return values


@dataclass(frozen=True)
class LocatedFunction:
    path: Path
    relative_path: Path
    tree: ast.Module
    node: ast.FunctionDef | ast.AsyncFunctionDef
    constants: dict[str, Any]
    source_hash: str


def locate_function(python_root: Path, spec: FunctionSpec) -> LocatedFunction:
    """Найти функцию без импорта и исполнения её модуля."""
    parts = spec.symbol.split(".")
    selected: tuple[str, Path] | None = None
    for split in range(len(parts) - 1, 0, -1):
        module = ".".join(parts[:split])
        path = python_root.joinpath(*module.split(".")).with_suffix(".py")
        if path.exists():
            selected = module, path
            owner_parts = parts[split:-1]
            function_name = parts[-1]
            break
    if selected is None:
        raise CompileError(Diagnostic(
            "PZ2001", f"модуль для {spec.symbol} не найден"))
    _, path = selected
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path), type_comments=True)
    scope: list[ast.stmt] = list(tree.body)
    for owner in owner_parts:
        class_node = next((item for item in scope
                           if isinstance(item, ast.ClassDef) and item.name == owner),
                          None)
        if class_node is None:
            raise CompileError(Diagnostic(
                "PZ2002", f"класс {owner!r} для {spec.symbol} не найден"))
        scope = list(class_node.body)
    candidates = [item for item in scope
                  if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and item.name == function_name]
    if len(candidates) != 1:
        raise CompileError(Diagnostic(
            "PZ2003", f"функция {spec.symbol} найдена {len(candidates)} раз"))
    relative = path.relative_to(python_root)
    return LocatedFunction(
        path=path,
        relative_path=relative,
        tree=tree,
        node=candidates[0],
        constants=module_constants(tree),
        source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )


class FunctionLowerer:
    """Строгий lowering без fallback и исполнения пользовательского кода."""

    def __init__(self, located: LocatedFunction, spec: FunctionSpec):
        self.located = located
        self.spec = spec
        self.blocks: dict[str, BasicBlock] = {}
        self.current: BasicBlock | None = None
        self.block_counter = 0
        self.temp_counter = 0
        self.temporary_types: dict[str, ScalarType] = {}
        self.local_types = {item.name: item.type for item in spec.parameters}
        self.break_targets: list[str] = []
        self.continue_targets: list[str] = []

    def span(self, node: ast.AST) -> SourceSpan:
        return SourceSpan.from_node(self.located.relative_path, node)

    def unsupported(self, node: ast.AST, detail: str | None = None) -> "None":
        suffix = f": {detail}" if detail else ""
        fail("PZ2004", f"неподдержанный AST {type(node).__name__}{suffix}",
             self.span(node))

    def new_block(self, stem: str) -> BasicBlock:
        name = f"{stem}_{self.block_counter:03d}"
        self.block_counter += 1
        block = BasicBlock(name)
        self.blocks[name] = block
        return block

    def set_current(self, block: BasicBlock | None) -> None:
        self.current = block

    def emit(self, op: str, arguments: tuple[Any, ...], value_type: ScalarType,
             node: ast.AST, attributes: dict[str, Any] | None = None) -> str:
        if self.current is None or self.current.terminator is not None:
            fail("PZ2005", "инструкция после terminator", self.span(node))
        name = f"%{self.temp_counter}"
        self.temp_counter += 1
        self.temporary_types[name] = value_type
        self.current.instructions.append(Instruction(
            op=op,
            destination=name,
            arguments=arguments,
            type=value_type,
            span=self.span(node),
            attributes=attributes or {},
        ))
        return name

    def terminate(self, op: str, arguments: tuple[Any, ...],
                  targets: tuple[str, ...], node: ast.AST) -> None:
        if self.current is None or self.current.terminator is not None:
            fail("PZ2006", "повторный terminator", self.span(node))
        self.current.terminator = Terminator(
            op=op, arguments=arguments, targets=targets, span=self.span(node))

    def lower(self) -> FunctionIR:
        node = self.located.node
        if isinstance(node, ast.AsyncFunctionDef):
            self.unsupported(node, "async-функции запрещены")
        if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            self.unsupported(node, "varargs/kwargs/keyword-only пока запрещены")
        names = tuple(argument.arg for argument in node.args.posonlyargs + node.args.args)
        expected = tuple(item.name for item in self.spec.parameters)
        if names != expected:
            fail("PZ2007", f"параметры {names!r} не совпали с manifest {expected!r}",
                 self.span(node))
        entry = self.new_block("entry")
        self.set_current(entry)
        self.lower_statements(node.body)
        if self.current is not None and self.current.terminator is None:
            fail("PZ2008", "не все пути функции возвращают значение",
                 self.span(node))
        return FunctionIR(
            symbol=self.spec.symbol,
            export=self.spec.export,
            parameters=self.spec.parameters,
            return_type=self.spec.return_type,
            entry=entry.name,
            blocks=self.blocks,
            local_types=self.local_types,
            temporary_types=self.temporary_types,
            source_hash=self.located.source_hash,
            ast_hash=_semantic_hash(node),
        )

    def lower_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if (isinstance(statement, ast.Expr) and
                    isinstance(statement.value, ast.Constant) and
                    isinstance(statement.value.value, str)):
                continue
            if self.current is None:
                fail("PZ2009", "недостижимый код после полного возврата",
                     self.span(statement))
            self.lower_statement(statement)

    def lower_statement(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Return):
            if node.value is None:
                self.unsupported(node, "void-return пока запрещён")
            value = self.lower_expression(node.value)
            self.terminate("return", (value,), (), node)
            self.set_current(None)
            return
        if isinstance(node, ast.If):
            self.lower_if(node)
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_node = node.value
            if value_node is None or len(targets) != 1 or not isinstance(targets[0], ast.Name):
                self.unsupported(node, "поддерживается одно простое имя слева")
            value = self.lower_expression(value_node)
            target = targets[0].id
            value_type = self.temporary_types[value]
            previous = self.local_types.get(target)
            if previous is not None and previous != value_type and previous != PYINT:
                # Точные диапазоны и совместимость проверяются следующим проходом.
                value_type = previous
            self.local_types.setdefault(target, value_type)
            assert self.current is not None
            self.current.instructions.append(Instruction(
                op="store_local", destination=None, arguments=(target, value),
                type=None, span=self.span(node)))
            return
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            left = self.lower_name(node.target)
            right = self.lower_expression(node.value)
            operator = self.binary_name(node.op, node)
            value = self.emit("binary", (operator, left, right), PYINT, node)
            target = node.target.id
            assert self.current is not None
            self.current.instructions.append(Instruction(
                op="store_local", destination=None, arguments=(target, value),
                type=None, span=self.span(node)))
            return
        self.unsupported(node)

    def lower_if(self, node: ast.If) -> None:
        condition = self.lower_expression(node.test)
        then_block = self.new_block("if_true")
        else_block = self.new_block("if_false")
        self.terminate("branch", (condition,),
                       (then_block.name, else_block.name), node.test)

        self.set_current(then_block)
        self.lower_statements(node.body)
        then_fallthrough = self.current

        self.set_current(else_block)
        self.lower_statements(node.orelse)
        else_fallthrough = self.current

        if then_fallthrough is None and else_fallthrough is None:
            self.set_current(None)
            return
        merge = self.new_block("if_merge")
        if then_fallthrough is not None:
            self.set_current(then_fallthrough)
            self.terminate("jump", (), (merge.name,), node)
        if else_fallthrough is not None:
            self.set_current(else_fallthrough)
            self.terminate("jump", (), (merge.name,), node)
        self.set_current(merge)

    def lower_expression(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return self.emit("const", (int(node.value),), BOOL, node)
            if isinstance(node.value, int):
                return self.emit("const", (node.value,), PYINT, node)
            self.unsupported(node, f"литерал {node.value!r}")
        if isinstance(node, ast.Name):
            return self.lower_name(node)
        if isinstance(node, ast.UnaryOp):
            value = self.lower_expression(node.operand)
            operator = _UNARY_OPERATOR_NAMES.get(type(node.op))
            if operator is None:
                self.unsupported(node)
            result_type = BOOL if operator == "not" else PYINT
            return self.emit("unary", (operator, value), result_type, node)
        if isinstance(node, ast.BinOp):
            left = self.lower_expression(node.left)
            right = self.lower_expression(node.right)
            return self.emit(
                "binary", (self.binary_name(node.op, node), left, right),
                PYINT, node)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                self.unsupported(node, "chained comparison будет добавлен отдельным lowering")
            left = self.lower_expression(node.left)
            right = self.lower_expression(node.comparators[0])
            operator = _COMPARISON_OPERATOR_NAMES.get(type(node.ops[0]))
            if operator not in {"eq", "ne", "lt", "le", "gt", "ge"}:
                self.unsupported(node, "membership/is пока запрещены")
            return self.emit("compare", (operator, left, right), BOOL, node)
        if isinstance(node, ast.IfExp):
            if not self.is_pure(node.body) or not self.is_pure(node.orelse):
                self.unsupported(node, "ветви ternary с эффектами требуют CFG phi")
            condition = self.lower_expression(node.test)
            when_true = self.lower_expression(node.body)
            when_false = self.lower_expression(node.orelse)
            return self.emit("select", (condition, when_true, when_false),
                             PYINT, node)
        if isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Name) or
                    node.func.id not in ("min", "max") or
                    node.keywords or len(node.args) != 2):
                self.unsupported(node, "разрешены только чистые min/max с двумя аргументами")
            left = self.lower_expression(node.args[0])
            right = self.lower_expression(node.args[1])
            return self.emit("intrinsic", (node.func.id, left, right),
                             PYINT, node)
        self.unsupported(node)

    def lower_name(self, node: ast.Name) -> str:
        if node.id in self.local_types:
            return self.emit("load_local", (node.id,),
                             self.local_types[node.id], node)
        if node.id in self.located.constants:
            value = self.located.constants[node.id]
            if isinstance(value, bool):
                return self.emit("const", (int(value),), BOOL, node)
            if isinstance(value, int):
                return self.emit("const", (value,), PYINT, node)
        fail("PZ2010", f"неразрешённое имя {node.id!r}", self.span(node))

    def binary_name(self, node: ast.operator, owner: ast.AST) -> str:
        result = _BINARY_OPERATOR_NAMES.get(type(node))
        if result not in {
                "add", "sub", "mul", "floordiv", "mod", "lshift",
                "rshift", "bitand", "bitor", "bitxor"}:
            self.unsupported(owner)
        return result

    def is_pure(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if not isinstance(child.func, ast.Name) or child.func.id not in ("min", "max"):
                    return False
            if isinstance(child, (ast.Await, ast.Yield, ast.YieldFrom,
                                  ast.NamedExpr, ast.Lambda)):
                return False
        return True


def lower_function(python_root: Path, spec: FunctionSpec) -> tuple[FunctionIR, LocatedFunction]:
    located = locate_function(python_root, spec)
    return FunctionLowerer(located, spec).lower(), located


# This IR is additive: the existing scalar manifest pipeline above remains
# unchanged until object layout, provider and target resource certificates are
# ready to consume the fragments.
OBJECT_STORE_IR_FORMAT = "pyz80.object-store-module-ir.v2"


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _object_fail(
        code: str, message: str, path: Path, node: ast.AST,
        ) -> "None":
    fail(code, message, SourceSpan.from_node(path, node))


def _object_operator(node: ast.operator, path: Path, owner: ast.AST) -> str:
    result = _BINARY_OPERATOR_NAMES.get(type(node))
    if result is None:
        _object_fail(
            "PZ2024", f"неподдержанный augmented operator "
            f"{type(node).__name__}", path, owner)
    return result


def _object_scope(
        node: ast.AST, parents: Mapping[ast.AST, ast.AST],
        ) -> tuple[str | None, str | None]:
    function_name: str | None = None
    class_name: str | None = None
    cursor = node
    while cursor in parents:
        cursor = parents[cursor]
        if (function_name is None and
                isinstance(cursor, (ast.FunctionDef,
                                     ast.AsyncFunctionDef))):
            function_name = cursor.name
        if isinstance(cursor, ast.ClassDef):
            class_name = cursor.name
            break
    return class_name, function_name


def _object_control_context(
        node: ast.AST, parents: Mapping[ast.AST, ast.AST],
        ) -> tuple[str, ...]:
    control_nodes = (
        ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
        ast.With, ast.AsyncWith, ast.Match,
    )
    result: list[str] = []
    cursor = node
    while cursor in parents:
        cursor = parents[cursor]
        if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            break
        if isinstance(cursor, control_nodes):
            result.append(type(cursor).__name__)
    return tuple(reversed(result))


def _reject_suspending_expression(
        expression: ast.expr, path: Path, owner: ast.AST,
        ) -> None:
    unsupported = next((node for node in ast.walk(expression)
                        if isinstance(node, (ast.Await, ast.Yield,
                                             ast.YieldFrom))), None)
    if unsupported is not None:
        _object_fail(
            "PZ2022", "object-store fragment cannot cross await/yield",
            path, owner)


def _effect(
        sequence: int, op: str, destination: str | None,
        arguments: tuple[Any, ...], value_kind: str | None,
        path: Path, node: ast.AST,
        attributes: Mapping[str, Any] | None = None,
        ) -> ObjectEffectInstruction:
    return ObjectEffectInstruction(
        sequence=sequence,
        op=op,
        destination=destination,
        arguments=arguments,
        value_kind=value_kind,
        span=SourceSpan.from_node(path, node),
        attributes=tuple(sorted((attributes or {}).items())),
    )


@dataclass
class _ObjectExpressionBlockBuilder:
    name: str
    instructions: list[ObjectEffectInstruction]
    terminator: ObjectExpressionTerminator | None = None


def _expression_value_kind(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "py-int"
    if isinstance(value, float):
        return "py-float"
    if isinstance(value, str):
        return "py-str"
    if value is None:
        return "py-none"
    return "py-value"


def _ssa_arguments(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.startswith("%") else ()
    if isinstance(value, (tuple, list)):
        result: list[str] = []
        for item in value:
            result.extend(_ssa_arguments(item))
        return tuple(result)
    return ()


class ObjectExpressionLowerer:
    """Lower one Python expression to typed, target-neutral SSA/CFG.

    The operations deliberately retain Python protocols.  For example,
    ``python-call`` and ``python-binary`` are not target ABI promises; they
    make the evaluation graph explicit so a later backend must either provide
    those protocols or reject the exact operation.
    """

    def __init__(self, *, source_path: Path, source_text: str,
                 program_id: str):
        self.source_path = source_path
        self.source_text = source_text
        self.program_id = program_id
        self.blocks: dict[str, _ObjectExpressionBlockBuilder] = {}
        self.current: _ObjectExpressionBlockBuilder | None = None
        self.block_counter = 0
        self.temp_counter = 0
        self.sequence_counter = 0
        self.value_kinds: dict[str, str] = {}

    def span(self, node: ast.AST) -> SourceSpan:
        return SourceSpan.from_node(self.source_path, node)

    def unsupported(self, node: ast.AST, detail: str) -> "None":
        fail(
            "PZ2030",
            f"object expression AST {type(node).__name__} is unsupported: "
            f"{detail}", self.span(node))

    def new_block(self, stem: str) -> _ObjectExpressionBlockBuilder:
        name = f"{stem}_{self.block_counter:03d}"
        self.block_counter += 1
        block = _ObjectExpressionBlockBuilder(name, [])
        self.blocks[name] = block
        return block

    def set_current(self, block: _ObjectExpressionBlockBuilder) -> None:
        self.current = block

    def emit(self, op: str, arguments: tuple[Any, ...], value_kind: str,
             node: ast.AST,
             attributes: Mapping[str, Any] | None = None) -> str:
        if self.current is None or self.current.terminator is not None:
            fail("PZ2031", "expression instruction after terminator",
                 self.span(node))
        destination = f"%expr_{self.temp_counter}"
        self.temp_counter += 1
        self.value_kinds[destination] = value_kind
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
            fail("PZ2031", "duplicate expression terminator",
                 self.span(node))
        self.current.terminator = ObjectExpressionTerminator(
            op=op, arguments=arguments, targets=targets,
            span=self.span(node))

    def constant(self, value: object, node: ast.AST) -> str:
        if not isinstance(value, (bool, int, float, str, type(None))):
            self.unsupported(
                node, f"constant {type(value).__name__} has no JSON-safe IR")
        return self.emit("constant", (value,), _expression_value_kind(value),
                         node)

    def lower(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            return self.constant(node.value, node)
        if isinstance(node, ast.Name):
            return self.emit(
                "load-name", (node.id,), "py-value", node,
                {"python_resolution": "lexical-local-closure-global-builtin"})
        if isinstance(node, ast.Attribute):
            receiver = self.lower(node.value)
            return self.emit(
                "load-attribute", (receiver, node.attr), "py-value", node,
                {"python_protocol": "PyObject_GetAttr"})
        if isinstance(node, ast.Subscript):
            container = self.lower(node.value)
            index = self.lower_slice(node.slice)
            return self.emit(
                "load-subscript", (container, index), "py-value", node,
                {"python_protocol": "PyObject_GetItem"})
        if isinstance(node, ast.Tuple):
            return self.lower_sequence_display(node, "tuple")
        if isinstance(node, ast.List):
            return self.lower_sequence_display(node, "list")
        if isinstance(node, ast.Set):
            return self.lower_sequence_display(node, "set")
        if isinstance(node, ast.Dict):
            return self.lower_dict(node)
        if isinstance(node, ast.UnaryOp):
            operator = _UNARY_OPERATOR_NAMES.get(type(node.op))
            if operator is None:
                self.unsupported(node, "unknown unary operator")
            if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int:
                # Знак входит в значение целого литерала. В частности, у
                # -2147483648 нет промежуточного положительного i32; вычисляем
                # литерал на хосте, не вызывая пользовательские протоколы.
                return self.constant(-node.operand.value, node)
            operand = self.lower(node.operand)
            result_kind = "bool" if operator == "not" else "py-value"
            return self.emit(
                "python-unary", (operator, operand), result_kind, node,
                {"python_data_model": True})
        if isinstance(node, ast.BinOp):
            operator = _BINARY_OPERATOR_NAMES.get(type(node.op))
            if operator is None:
                self.unsupported(node, "unknown binary operator")
            left = self.lower(node.left)
            right = self.lower(node.right)
            return self.emit(
                "python-binary", (operator, left, right), "py-value", node,
                {"evaluation_order": "left-then-right",
                 "python_data_model": True})
        if isinstance(node, ast.Compare):
            return self.lower_compare(node)
        if isinstance(node, ast.BoolOp):
            return self.lower_boolop(node)
        if isinstance(node, ast.IfExp):
            return self.lower_conditional(node)
        if isinstance(node, ast.Call):
            return self.lower_call(node)
        if isinstance(node, ast.JoinedStr):
            return self.lower_joined_string(node)
        if isinstance(node, ast.FormattedValue):
            return self.lower_formatted_value(node)
        if isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom)):
            self.unsupported(node, "suspension cannot occur inside a hook")
        if isinstance(node, (ast.Lambda, ast.NamedExpr,
                             ast.ListComp, ast.SetComp,
                             ast.DictComp, ast.GeneratorExp, ast.JoinedStr)):
            self.unsupported(node, "no target-neutral lowering is defined")
        self.unsupported(node, "unrecognized expression form")

    def lower_slice(self, node: ast.expr | ast.slice) -> str:
        if isinstance(node, ast.Slice):
            parts: list[str] = []
            for part in (node.lower, node.upper, node.step):
                parts.append(self.constant(None, node) if part is None
                             else self.lower(part))
            return self.emit(
                "build-slice", tuple(parts), "py-slice", node,
                {"evaluation_order": "lower-upper-step"})
        if isinstance(node, ast.expr):
            return self.lower(node)
        self.unsupported(node, "extended slice node is unsupported")

    def lower_call(self, node: ast.Call) -> str:
        callable_value = self.lower(node.func)
        arguments: list[str] = []
        layout: list[tuple[str, str | None]] = []
        for item in node.args:
            if isinstance(item, ast.Starred):
                arguments.append(self.lower(item.value))
                layout.append(("star-positional", None))
            else:
                arguments.append(self.lower(item))
                layout.append(("positional", None))
        for item in node.keywords:
            arguments.append(self.lower(item.value))
            layout.append(("keyword" if item.arg is not None else
                           "star-keyword", item.arg))
        # Resolve the callee first, but Python evaluates arguments before
        # raising TypeError for a non-callable value. Keep that original value;
        # argument side effects must not trigger another name/attribute lookup.
        callable_temp = self.emit(
            "require-callable", (callable_value,), "callable", node.func,
            {"does_not_repeat_lookup": True})
        return self.emit(
            "python-call", (callable_temp, *arguments), "py-value", node,
            {"argument_count": len(arguments),
             "argument_layout": tuple(layout),
             "evaluation_order": (
                 "callable, positional/starred, then keyword/** in AST "
                 "evaluation order"),
             "keywords": bool(node.keywords)})

    def lower_sequence_display(
            self, node: ast.Tuple | ast.List | ast.Set,
            sequence_kind: str) -> str:
        values: list[str] = []
        layout: list[str] = []
        for item in node.elts:
            if isinstance(item, ast.Starred):
                values.append(self.lower(item.value))
                layout.append("iterable-unpack")
            else:
                values.append(self.lower(item))
                layout.append("item")
        return self.emit(
            f"build-{sequence_kind}", tuple(values), f"py-{sequence_kind}",
            node, {"item_count": len(values),
                   "item_layout": tuple(layout),
                   "evaluation_order": "left-to-right"})

    def lower_dict(self, node: ast.Dict) -> str:
        values: list[str] = []
        layout: list[str] = []
        for key, value in zip(node.keys, node.values):
            if key is None:
                values.append(self.lower(value))
                layout.append("mapping-unpack")
            else:
                values.append(self.lower(key))
                values.append(self.lower(value))
                layout.append("key-value")
        return self.emit(
            "build-dict", tuple(values), "py-dict", node,
            {"entry_count": len(node.values),
             "entry_layout": tuple(layout),
             "evaluation_order": "key-then-value-left-to-right"})

    def lower_joined_string(self, node: ast.JoinedStr) -> str:
        values = tuple(self.lower(item) for item in node.values)
        return self.emit(
            "build-joined-string", values, "py-str", node,
            {"part_count": len(values), "evaluation_order": "left-to-right"})

    def lower_formatted_value(self, node: ast.FormattedValue) -> str:
        value = self.lower(node.value)
        arguments: list[str] = [value]
        if node.format_spec is not None:
            arguments.append(self.lower(node.format_spec))
        return self.emit(
            "format-value", tuple(arguments), "py-str", node,
            {"conversion": node.conversion,
             "has_format_spec": node.format_spec is not None,
             "evaluation_order": "value-then-format-spec"})

    def lower_boolop(self, node: ast.BoolOp) -> str:
        operator = _BOOLEAN_OPERATOR_NAMES.get(type(node.op))
        if operator is None or not node.values:
            self.unsupported(node, "malformed boolean operation")
        if len(node.values) == 1:
            return self.lower(node.values[0])
        current_value = self.lower(node.values[0])
        incoming: list[tuple[str, str]] = []
        merge = self.new_block("boolop_merge")
        for index, value_node in enumerate(node.values[1:], 1):
            predecessor = self.current
            assert predecessor is not None
            next_block = self.new_block("boolop_next")
            targets = ((next_block.name, merge.name) if operator == "and"
                       else (merge.name, next_block.name))
            self.terminate("branch-truth", (current_value,), targets, node)
            incoming.append((predecessor.name, current_value))
            self.set_current(next_block)
            current_value = self.lower(value_node)
            if index + 1 == len(node.values):
                final_predecessor = self.current
                assert final_predecessor is not None
                self.terminate("jump", (), (merge.name,), value_node)
                incoming.append((final_predecessor.name, current_value))
        self.set_current(merge)
        kinds = {self.value_kinds[value] for _, value in incoming}
        result_kind = next(iter(kinds)) if len(kinds) == 1 else "py-value"
        phi_arguments = tuple(item for pair in incoming for item in pair)
        return self.emit(
            "phi", phi_arguments, result_kind, node,
            {"incoming_count": len(incoming),
             "python_boolean_operator": operator,
             "short_circuit": True})

    def lower_compare(self, node: ast.Compare) -> str:
        if not node.ops or len(node.ops) != len(node.comparators):
            self.unsupported(node, "malformed comparison chain")
        operators: list[str] = []
        for operation in node.ops:
            name = _COMPARISON_OPERATOR_NAMES.get(type(operation))
            if name is None:
                self.unsupported(node, "unknown comparison operator")
            operators.append(name)
        left = self.lower(node.left)
        if len(operators) == 1:
            right = self.lower(node.comparators[0])
            return self.emit(
                "python-compare", (operators[0], left, right), "py-value", node,
                {"python_data_model": True})

        merge = self.new_block("compare_merge")
        incoming: list[tuple[str, str]] = []
        for index, (operator, comparator) in enumerate(zip(
                operators, node.comparators)):
            right = self.lower(comparator)
            comparison = self.emit(
                "python-compare", (operator, left, right), "py-value", node,
                {"chain_index": index, "python_data_model": True})
            assert self.current is not None
            incoming.append((self.current.name, comparison))
            if index + 1 < len(operators):
                next_block = self.new_block("compare_next")
                self.terminate(
                    "branch-truth", (comparison,),
                    (next_block.name, merge.name), node)
                self.set_current(next_block)
                left = right
            else:
                self.terminate("jump", (), (merge.name,), node)
        self.set_current(merge)
        # Python returns the first false-y comparison object, or the final
        # comparison result, not necessarily bool. Do not substitute False
        # or call __bool__ on the final result.
        return self.emit(
            "phi", tuple(value for pair in incoming for value in pair),
            "py-value", node, {"incoming_count": len(incoming), "short_circuit": True})

    def lower_conditional(self, node: ast.IfExp) -> str:
        condition = self.lower(node.test)
        true_block = self.new_block("ifexp_true")
        false_block = self.new_block("ifexp_false")
        merge = self.new_block("ifexp_merge")
        self.terminate(
            "branch-truth", (condition,),
            (true_block.name, false_block.name), node.test)

        self.set_current(true_block)
        true_value = self.lower(node.body)
        true_predecessor = self.current
        self.terminate("jump", (), (merge.name,), node.body)

        self.set_current(false_block)
        false_value = self.lower(node.orelse)
        false_predecessor = self.current
        self.terminate("jump", (), (merge.name,), node.orelse)

        assert true_predecessor is not None and false_predecessor is not None
        self.set_current(merge)
        true_kind = self.value_kinds[true_value]
        false_kind = self.value_kinds[false_value]
        result_kind = true_kind if true_kind == false_kind else "py-value"
        return self.emit(
            "phi", (true_predecessor.name, true_value,
                    false_predecessor.name, false_value), result_kind, node,
            {"incoming_count": 2, "short_circuit": True})

    def build(self, node: ast.expr) -> ObjectExpressionIR:
        entry = self.new_block("expression_entry")
        self.set_current(entry)
        result = self.lower(node)
        self.terminate("return-expression", (result,), (), node)
        immutable_blocks = tuple(ObjectExpressionBlock(
            name=block.name,
            instructions=tuple(block.instructions),
            terminator=block.terminator,
        ) for block in self.blocks.values()
          if block.terminator is not None)
        if len(immutable_blocks) != len(self.blocks):
            fail("PZ2031", "expression CFG contains unterminated block",
                 self.span(node))
        payload = {
            "program_id": self.program_id,
            "entry": entry.name,
            "result": result,
            "result_kind": self.value_kinds[result],
            "blocks": [block.to_json() for block in immutable_blocks],
            "source": (ast.get_source_segment(self.source_text, node) or
                       ast.unparse(node)),
            "ast_sha256": _semantic_hash(node),
        }
        program = ObjectExpressionIR(
            program_id=self.program_id,
            entry=entry.name,
            result=result,
            result_kind=self.value_kinds[result],
            blocks=immutable_blocks,
            source=str(payload["source"]),
            ast_sha256=str(payload["ast_sha256"]),
            semantic_sha256=_json_sha256(payload),
        )
        _validate_object_expression(program, self.source_path, node)
        return program


def _validate_object_expression(
        program: ObjectExpressionIR, path: Path, owner: ast.AST) -> None:
    """Prove closed SSA names, reachable CFG and edge-correct phi inputs."""
    blocks = {block.name: block for block in program.blocks}
    if program.entry not in blocks or len(blocks) != len(program.blocks):
        _object_fail("PZ2033", "invalid expression entry/blocks", path, owner)
    all_instructions = [instruction for block in program.blocks
                        for instruction in block.instructions]
    if sorted(item.sequence for item in all_instructions) != list(range(
            len(all_instructions))):
        _object_fail(
            "PZ2033", "expression instruction sequence is not contiguous",
            path, owner)
    definitions: dict[str, tuple[str, int]] = {}
    for block in program.blocks:
        for instruction in block.instructions:
            destination = instruction.destination
            if destination is None or destination in definitions:
                _object_fail(
                    "PZ2033", "expression SSA destination is missing/duplicate",
                    path, owner)
            definitions[destination] = (block.name, instruction.sequence)
        for target in block.terminator.targets:
            if target not in blocks:
                _object_fail(
                    "PZ2033", f"expression target {target!r} is absent",
                    path, owner)
    if program.result not in definitions:
        _object_fail("PZ2033", "expression result is undefined", path, owner)

    predecessors: dict[str, set[str]] = {name: set() for name in blocks}
    reachable = {program.entry}
    pending = [program.entry]
    while pending:
        name = pending.pop()
        for target in blocks[name].terminator.targets:
            predecessors[target].add(name)
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    if reachable != set(blocks):
        _object_fail("PZ2033", "expression CFG has unreachable blocks",
                     path, owner)
    dominators: dict[str, set[str]] = {
        name: ({name} if name == program.entry else set(blocks))
        for name in blocks}
    changed = True
    while changed:
        changed = False
        for name in blocks:
            if name == program.entry:
                continue
            incoming = predecessors[name]
            common = (set.intersection(*(dominators[item]
                                         for item in incoming))
                      if incoming else set())
            updated = {name} | common
            if updated != dominators[name]:
                dominators[name] = updated
                changed = True

    def require_use(value: str, use_block: str, use_sequence: int | None,
                    *, edge_predecessor: str | None = None) -> None:
        definition = definitions.get(value)
        if definition is None:
            _object_fail(
                "PZ2033", f"expression SSA use is undefined: {value}",
                path, owner)
        definition_block, definition_sequence = definition
        destination_block = edge_predecessor or use_block
        if definition_block not in dominators[destination_block]:
            _object_fail(
                "PZ2033", f"expression SSA use is not dominated: {value}",
                path, owner)
        if (edge_predecessor is None and definition_block == use_block and
                use_sequence is not None and
                definition_sequence >= use_sequence):
            _object_fail(
                "PZ2033", f"expression SSA local use precedes: {value}",
                path, owner)

    for block in program.blocks:
        for instruction in block.instructions:
            if instruction.op == "phi":
                if len(instruction.arguments) % 2:
                    _object_fail("PZ2033", "malformed expression phi",
                                 path, owner)
                for index in range(0, len(instruction.arguments), 2):
                    predecessor = instruction.arguments[index]
                    value = instruction.arguments[index + 1]
                    if (not isinstance(predecessor, str) or
                            predecessor not in predecessors[block.name] or
                            not isinstance(value, str) or
                            not value.startswith("%")):
                        _object_fail(
                            "PZ2033", "phi input is not a CFG predecessor SSA",
                            path, owner)
                    require_use(value, block.name, None,
                                edge_predecessor=predecessor)
            elif instruction.op != "constant":
                for value in _ssa_arguments(instruction.arguments):
                    require_use(value, block.name, instruction.sequence)
        for value in _ssa_arguments(block.terminator.arguments):
            require_use(value, block.name, None)
    return_blocks = [block for block in program.blocks
                     if block.terminator.op == "return-expression"]
    if (len(return_blocks) != 1 or
            return_blocks[0].terminator.arguments != (program.result,)):
        _object_fail("PZ2033", "expression has no unique result terminator",
                     path, owner)


def lower_object_expression(
        node: ast.expr, *, source_path: Path, source_text: str,
        program_id: str = "expression",
        ) -> ObjectExpressionIR:
    """Public fail-closed frontend for one object-valued expression."""
    return ObjectExpressionLowerer(
        source_path=source_path, source_text=source_text,
        program_id=program_id).build(node)


def _validate_object_fragment(
        fragment: ObjectStoreFragmentIR, path: Path, owner: ast.AST,
        ) -> None:
    instructions = fragment.instructions
    if tuple(item.sequence for item in instructions) != tuple(range(
            len(instructions))):
        _object_fail("PZ2025", "object IR sequence is not contiguous", path,
                     owner)
    definitions: set[str] = set()
    for item in instructions:
        for argument in item.arguments:
            if isinstance(argument, str) and argument.startswith("%"):
                if argument not in definitions:
                    _object_fail(
                        "PZ2025", f"SSA use before definition: {argument}",
                        path, owner)
        if item.destination is not None:
            if item.destination in definitions:
                _object_fail(
                    "PZ2025", f"duplicate SSA definition: {item.destination}",
                    path, owner)
            definitions.add(item.destination)
    sync_indices = [index for index, item in enumerate(instructions)
                    if item.op == "draw-sync-if-bound"]
    sync_index = sync_indices[0] if len(sync_indices) == 1 else None
    store_index = sync_index - 1 if sync_index is not None else None
    if (store_index is None or store_index < 0 or
            instructions[store_index].op != "store-attribute" or
            instructions[store_index].arguments[0] !=
            instructions[sync_index].arguments[0] or
            instructions[store_index].arguments[2] !=
            instructions[sync_index].arguments[2]):
        _object_fail(
            "PZ2025", "store/sync do not reuse adjacent receiver/value SSA",
            path, owner)


def lower_object_store_statement(
        node: ast.AST, hook_site: Mapping[str, Any], *, source_path: Path,
        source_text: str,
        parents: Mapping[ast.AST, ast.AST] | None = None,
        ) -> ObjectStoreFragmentIR:
    """Lower one AST-bound draw mutation plus its source-derived RHS CFG."""
    if hook_site.get("hook_op") != "draw-sync-if-bound":
        _object_fail(
            "PZ2020", "site is not a runtime draw-sync mutation",
            source_path, node)
    if (_semantic_hash(node) != hook_site.get("statement_ast_sha256") or
            int(getattr(node, "lineno", 0)) != int(hook_site.get("line", -1))):
        _object_fail(
            "PZ2020", "hook site hash/line differs from the supplied AST",
            source_path, node)
    source_kind = str(hook_site["source_kind"])
    target: ast.Attribute
    assignment_targets: tuple[ast.Attribute, ...]
    assignment_mode = "single"
    rhs: ast.expr
    operator: str | None = None
    if source_kind == "assign":
        if not isinstance(node, ast.Assign) or not node.targets:
            _object_fail(
                "PZ2021", "assignment has no target", source_path, node)
        if all(isinstance(item, ast.Attribute) for item in node.targets):
            assignment_targets = tuple(
                item for item in node.targets
                if isinstance(item, ast.Attribute))
            assignment_mode = ("single" if len(assignment_targets) == 1
                               else "chained")
        elif (len(node.targets) == 1 and
              isinstance(node.targets[0], (ast.Tuple, ast.List)) and
              all(isinstance(item, ast.Attribute)
                  for item in node.targets[0].elts)):
            assignment_targets = tuple(
                item for item in node.targets[0].elts
                if isinstance(item, ast.Attribute))
            assignment_mode = "unpack-sequence"
        else:
            _object_fail(
                "PZ2021", "assignment requires simple-name attribute "
                "targets, with one flat tuple/list unpack allowed",
                source_path, node)
        compound = next((item.value for item in assignment_targets
                         if not isinstance(item.value, ast.Name)), None)
        if compound is not None:
            _object_fail(
                "PZ2023", "compound/call/subscript attribute receiver has no "
                "proved alias lowering", source_path, compound)
        matches = [item for item in assignment_targets
                   if item.attr == hook_site.get("field") and
                   int(getattr(item, "col_offset", -1)) ==
                   int(hook_site.get("column", -2))]
        if len(matches) != 1:
            _object_fail(
                "PZ2021", "hook does not select exactly one chained target",
                source_path, node)
        target = matches[0]
        rhs = node.value
    elif source_kind == "augassign":
        if not isinstance(node, ast.AugAssign) or not isinstance(
                node.target, ast.Attribute):
            _object_fail(
                "PZ2021", "augmented target is not one attribute",
                source_path, node)
        target = node.target
        assignment_targets = (target,)
        rhs = node.value
        operator = _object_operator(node.op, source_path, node)
    else:
        _object_fail(
            "PZ2021", f"runtime source kind {source_kind!r} has no object "
            "statement lowering", source_path, node)

    if not isinstance(target.value, ast.Name):
        _object_fail(
            "PZ2023", "compound/call/subscript attribute receiver has no "
            "proved alias lowering", source_path, target.value)
    receiver_name = target.value.id
    if receiver_name != hook_site.get("receiver"):
        _object_fail(
            "PZ2023", "hook receiver differs from active AST receiver",
            source_path, target.value)
    if target.attr != hook_site.get("field"):
        _object_fail(
            "PZ2021", "hook field differs from active AST target",
            source_path, target)
    _reject_suspending_expression(rhs, source_path, node)

    expression = lower_object_expression(
        rhs, source_path=source_path, source_text=source_text,
        program_id=f"store-site-{int(hook_site['site_id']):04d}-rhs")
    expression_attributes = {
        "program_id": expression.program_id,
        "program_semantic_sha256": expression.semantic_sha256,
        "program_result": expression.result,
        "lowering": "typed-expression-cfg-single-evaluation",
    }
    receiver_attributes = {
        "name": receiver_name,
        "alias_contract": "exact-runtime-object-reference",
        "source": ast.get_source_segment(source_text, target.value) or
        receiver_name,
    }
    instructions: list[ObjectEffectInstruction] = []
    if source_kind == "assign":
        # Python evaluates the complete RHS before assignment targets.
        rhs_temp = "%value" if assignment_mode != "unpack-sequence" else "%rhs"
        instructions.append(_effect(
            0, "execute-expression-cfg", rhs_temp,
            (expression.program_id,), expression.result_kind,
            source_path, rhs, expression_attributes))
        target_values: list[str]
        if assignment_mode == "unpack-sequence":
            instructions.append(_effect(
                len(instructions), "unpack-sequence", "%unpacked",
                (rhs_temp, len(assignment_targets)), "unpacked-values",
                source_path, node,
                {"python_protocol": "UNPACK_SEQUENCE",
                 "all_values_materialized_before_target_stores": True}))
            target_values = []
            for target_index, assignment_target in enumerate(assignment_targets):
                value_temp = ("%value" if assignment_target is target else
                              f"%value_target_{target_index}")
                instructions.append(_effect(
                    len(instructions), "unpack-item", value_temp,
                    ("%unpacked", target_index), "py-value",
                    source_path, assignment_target,
                    {"assignment_target_index": target_index}))
                target_values.append(value_temp)
        else:
            target_values = [rhs_temp] * len(assignment_targets)
        for target_index, assignment_target in enumerate(assignment_targets):
            assert isinstance(assignment_target.value, ast.Name)
            selected = assignment_target is target
            receiver_temp = ("%receiver" if selected else
                             f"%receiver_target_{target_index}")
            target_receiver = assignment_target.value.id
            instructions.append(_effect(
                len(instructions), "eval-receiver", receiver_temp,
                (target_receiver,), "object-ref", source_path,
                assignment_target.value,
                {"name": target_receiver,
                 "alias_contract": "exact-runtime-object-reference",
                 "source": (ast.get_source_segment(
                     source_text, assignment_target.value) or target_receiver),
                 "assignment_target_index": target_index}))
            instructions.append(_effect(
                len(instructions), "store-attribute", None,
                (receiver_temp, assignment_target.attr,
                 target_values[target_index]), None,
                source_path, assignment_target,
                {"executes_original_gameplay_store": True,
                 "sync_runs_only_after_successful_store": True,
                 "assignment_target_index": target_index}))
            if selected:
                instructions.append(_effect(
                    len(instructions), "draw-sync-if-bound", None,
                    (receiver_temp, int(hook_site["field_id"]),
                     target_values[target_index],
                     int(hook_site["site_id"])), None,
                    source_path, assignment_target,
                    {"slot_lookup": hook_site.get("slot_lookup"),
                     "reuses_store_receiver": True,
                     "reuses_store_value": True,
                     "assignment_target_index": target_index}))
    else:
        # AugAssign evaluates the target, reads the old value, then evaluates
        # the RHS and performs Python's in-place binary protocol.
        assert operator is not None
        instructions.append(_effect(
            0, "eval-receiver", "%receiver", (receiver_name,), "object-ref",
            source_path, target.value, receiver_attributes))
        instructions.append(_effect(
            1, "load-attribute", "%old", ("%receiver", target.attr),
            "py-value", source_path, target))
        instructions.append(_effect(
            2, "execute-expression-cfg", "%rhs",
            (expression.program_id,), expression.result_kind,
            source_path, rhs, expression_attributes))
        instructions.append(_effect(
            3, "python-inplace-binary", "%value",
            (operator, "%old", "%rhs"), "py-value", source_path, node,
            {"python_protocol": "__iop__ then binary fallback"}))

        sequence = len(instructions)
        instructions.append(_effect(
            sequence, "store-attribute", None,
            ("%receiver", target.attr, "%value"), None,
            source_path, target,
            {"executes_original_gameplay_store": True,
             "sync_runs_only_after_successful_store": True}))
        instructions.append(_effect(
            sequence + 1, "draw-sync-if-bound", None,
            ("%receiver", int(hook_site["field_id"]), "%value",
             int(hook_site["site_id"])), None,
            source_path, target,
            {"slot_lookup": hook_site.get("slot_lookup"),
             "reuses_store_receiver": True,
             "reuses_store_value": True}))

    parent_map = parents or {}
    class_name, function_name = _object_scope(node, parent_map)
    expected_class = hook_site.get("class")
    expected_function = hook_site.get("function")
    if parent_map and (class_name != expected_class or
                       function_name != expected_function):
        _object_fail(
            "PZ2026", "hook scope differs from active AST scope",
            source_path, node)
    control_context = _object_control_context(node, parent_map)
    payload = {
        "site_id": int(hook_site["site_id"]),
        "source_kind": source_kind,
        "field": target.attr,
        "field_id": int(hook_site["field_id"]),
        "class": expected_class,
        "function": expected_function,
        "statement_ast_sha256": str(hook_site["statement_ast_sha256"]),
        "site_ast_sha256": str(hook_site["site_ast_sha256"]),
        "control_context": control_context,
        "expression": expression.to_json(),
        "instructions": [item.to_json() for item in instructions],
    }
    fragment = ObjectStoreFragmentIR(
        site_id=int(hook_site["site_id"]),
        source_kind=source_kind,
        field_name=target.attr,
        field_id=int(hook_site["field_id"]),
        class_name=(str(expected_class) if expected_class is not None else None),
        function_name=(str(expected_function)
                       if expected_function is not None else None),
        statement_ast_sha256=str(hook_site["statement_ast_sha256"]),
        site_ast_sha256=str(hook_site["site_ast_sha256"]),
        control_context=control_context,
        expression=expression,
        instructions=tuple(instructions),
        semantic_sha256=_json_sha256(payload),
    )
    _validate_object_fragment(fragment, source_path, node)
    return fragment


def _call_shape(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _call_shape(node.value)
        return f"{owner}.{node.attr}"
    return type(node).__name__


def _object_expression_census(
        expressions: list[ast.expr],
        fragments: list[ObjectStoreFragmentIR],
        ) -> dict[str, Any]:
    """Return a source-derived census; no expected game constants live here."""
    root_kinds = Counter(type(node).__name__ for node in expressions)
    ast_kinds: Counter[str] = Counter()
    binary_operators: Counter[str] = Counter()
    unary_operators: Counter[str] = Counter()
    comparison_operators: Counter[str] = Counter()
    call_targets: Counter[str] = Counter()
    positional_arguments = 0
    keyword_arguments = 0
    starred_arguments = 0
    for expression in expressions:
        for node in ast.walk(expression):
            ast_kinds[type(node).__name__] += 1
            if isinstance(node, ast.BinOp):
                binary_operators[
                    _BINARY_OPERATOR_NAMES.get(type(node.op),
                                               type(node.op).__name__)] += 1
            elif isinstance(node, ast.UnaryOp):
                unary_operators[
                    _UNARY_OPERATOR_NAMES.get(type(node.op),
                                              type(node.op).__name__)] += 1
            elif isinstance(node, ast.Compare):
                for operation in node.ops:
                    comparison_operators[
                        _COMPARISON_OPERATOR_NAMES.get(
                            type(operation), type(operation).__name__)] += 1
            elif isinstance(node, ast.Call):
                call_targets[_call_shape(node.func)] += 1
                positional_arguments += len(node.args)
                keyword_arguments += len(node.keywords)
                starred_arguments += sum(
                    isinstance(item, ast.Starred) for item in node.args)
                starred_arguments += sum(
                    item.arg is None for item in node.keywords)

    ir_operations: Counter[str] = Counter()
    instruction_count = 0
    block_count = 0
    branch_count = 0
    for fragment in fragments:
        block_count += len(fragment.expression.blocks)
        for block in fragment.expression.blocks:
            instruction_count += len(block.instructions)
            ir_operations.update(item.op for item in block.instructions)
            branch_count += block.terminator.op == "branch-truth"
    return {
        "expression_roots": len(expressions),
        "unique_expression_ast_sha256": len({
            _semantic_hash(node) for node in expressions}),
        "root_ast_kind_counts": dict(sorted(root_kinds.items())),
        "all_ast_node_kind_counts": dict(sorted(ast_kinds.items())),
        "binary_operator_counts": dict(sorted(binary_operators.items())),
        "unary_operator_counts": dict(sorted(unary_operators.items())),
        "comparison_operator_counts": dict(
            sorted(comparison_operators.items())),
        "call_target_counts": dict(sorted(call_targets.items())),
        "call_count": sum(call_targets.values()),
        "positional_argument_count": positional_arguments,
        "keyword_argument_count": keyword_arguments,
        "starred_argument_count": starred_arguments,
        "subscript_count": ast_kinds.get("Subscript", 0),
        "expression_cfg_programs": len(fragments),
        "expression_cfg_blocks": block_count,
        "expression_cfg_branches": branch_count,
        "expression_ssa_instructions": instruction_count,
        "expression_ir_op_counts": dict(sorted(ir_operations.items())),
        "unsupported_expression_count": 0,
        "unsupported_expressions": [],
    }


def lower_active_object_store_ir(
        project_root: Path | str, *, hook_plan: object | None = None,
        ) -> ObjectStoreModuleIR:
    """Lower every active ``draw-sync-if-bound`` site to effect SSA."""
    # Kept local so the established scalar frontend has no import-time
    # dependency on the much larger draw analysis stack.
    from .mutation_hook_ir import build_mutation_hook_ir

    root = Path(project_root).resolve()
    active_hook_plan = hook_plan or build_mutation_hook_ir(root)
    source_path = root / str(active_hook_plan.source_path)
    source_bytes = source_path.read_bytes()
    source_text = source_bytes.decode("utf-8")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if source_hash != active_hook_plan.source_sha256:
        fail("PZ2027", "object hook plan is stale for active source")
    tree = ast.parse(source_text, filename=str(source_path), type_comments=True)
    parents = {child: parent for parent in ast.walk(tree)
               for child in ast.iter_child_nodes(parent)}

    candidates: dict[tuple[int, str], list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                             ast.Delete, ast.Call)):
            candidates.setdefault(
                (int(getattr(node, "lineno", 0)), _semantic_hash(node)),
                []).append(node)

    fragments: list[ObjectStoreFragmentIR] = []
    rhs_expressions: list[ast.expr] = []
    schema_site_ids: list[int] = []
    runtime_hooks = [item for item in active_hook_plan.mutation_hooks
                     if item["runtime_hook_required"]]
    hook_statement_keys = [
        (int(item["line"]), str(item["statement_ast_sha256"]))
        for item in runtime_hooks]
    if len(set(hook_statement_keys)) != len(hook_statement_keys):
        fail(
            "PZ2028", "one statement writes multiple normalized draw fields; "
            "grouped multi-hook lowering is not implemented")
    for hook in active_hook_plan.mutation_hooks:
        if not hook["runtime_hook_required"]:
            if hook["hook_op"] != "bind-schema-field":
                fail("PZ2028", "non-runtime mutation lacks bind schema op")
            schema_site_ids.append(int(hook["site_id"]))
            continue
        key = (int(hook["line"]), str(hook["statement_ast_sha256"]))
        matches = candidates.get(key, ())
        if len(matches) != 1:
            fail(
                "PZ2028", f"mutation site {hook['site_id']} resolves to "
                f"{len(matches)} AST statements")
        statement = matches[0]
        if isinstance(statement, ast.Assign):
            rhs_expressions.append(statement.value)
        elif isinstance(statement, ast.AugAssign):
            rhs_expressions.append(statement.value)
        else:
            fail(
                "PZ2028", f"mutation site {hook['site_id']} has no RHS")
        fragments.append(lower_object_store_statement(
            statement, hook, source_path=Path(active_hook_plan.source_path),
            source_text=source_text, parents=parents))

    fragments.sort(key=lambda item: item.site_id)
    if len({item.site_id for item in fragments}) != len(fragments):
        fail("PZ2028", "duplicate object-store site id")
    kind_counts = {
        kind: sum(item.source_kind == kind for item in fragments)
        for kind in sorted({item.source_kind for item in fragments})
    }
    control_counts: dict[str, int] = {}
    assignment_shape_counts = {
        "single-attribute": 0,
        "chained-attributes": 0,
        "flat-unpack-attributes": 0,
        "augmented-attribute": 0,
    }
    for fragment in fragments:
        for context in fragment.control_context:
            control_counts[context] = control_counts.get(context, 0) + 1
        operations = [item.op for item in fragment.instructions]
        if fragment.source_kind == "augassign":
            assignment_shape_counts["augmented-attribute"] += 1
        elif "unpack-sequence" in operations:
            assignment_shape_counts["flat-unpack-attributes"] += 1
        elif operations.count("store-attribute") > 1:
            assignment_shape_counts["chained-attributes"] += 1
        else:
            assignment_shape_counts["single-attribute"] += 1
    lowerer_inputs = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in (
            "Source/Tools/pyz80_compiler/frontend.py",
            "Source/Tools/pyz80_compiler/ir.py",
            "Source/Tools/pyz80_compiler/mutation_hook_ir.py",
        )
    }
    runtime_candidates = sum(bool(item["runtime_hook_required"])
                             for item in active_hook_plan.mutation_hooks)
    expression_census = _object_expression_census(
        rhs_expressions, fragments)
    coverage: dict[str, Any] = {
        "runtime_hook_candidates": runtime_candidates,
        "runtime_hook_fragments": len(fragments),
        "bind_schema_candidates": len(schema_site_ids),
        "source_kind_counts": kind_counts,
        "assignment_shape_counts": assignment_shape_counts,
        "control_context_counts": dict(sorted(control_counts.items())),
        "unsupported_active_sites": 0,
        "receiver_evaluated_once": True,
        "each_source_receiver_occurrence_evaluated_once": True,
        "rhs_evaluated_once": True,
        "augassign_old_value_loaded_once": True,
        "original_store_precedes_adjacent_sync": True,
        "store_and_sync_reuse_same_ssa_temps": True,
        "simple_name_receiver_aliasing": "exact-runtime-reference",
        "compound_receiver_aliasing_supported": False,
        "multiple_draw_hooks_in_one_statement_supported": False,
        "enclosing_control_flow_preserved_by_site_splice": True,
        "full_gameplay_cfg_lowered": False,
        "opaque_expressions_lowered": True,
        "expression_cfg_is_target_neutral": True,
        "expression_cfg_preserves_python_branch_laziness": True,
        "expression_cfg_ssa_validated": True,
        "expression_census": expression_census,
        "current_scalar_pipeline_consumes_object_ir": False,
        "live_claimed": False,
        "lowerer_input_sha256": lowerer_inputs,
    }
    if len(fragments) != runtime_candidates:
        fail("PZ2028", "object-store runtime coverage is incomplete")
    payload = {
        "format": OBJECT_STORE_IR_FORMAT,
        "source_path": active_hook_plan.source_path,
        "source_sha256": source_hash,
        "hook_semantic": active_hook_plan.semantic_sha256,
        "fragments": [item.to_json() for item in fragments],
        "bind_schema_site_ids": schema_site_ids,
        "coverage": coverage,
    }
    return ObjectStoreModuleIR(
        format=OBJECT_STORE_IR_FORMAT,
        source_path=str(active_hook_plan.source_path),
        source_sha256=source_hash,
        mutation_hook_semantic_sha256=active_hook_plan.semantic_sha256,
        fragments=tuple(fragments),
        bind_schema_site_ids=tuple(schema_site_ids),
        coverage=coverage,
        semantic_sha256=_json_sha256(payload),
    )


def object_store_ir_report(module: ObjectStoreModuleIR) -> dict[str, Any]:
    """Return the honest integration status around the target-neutral IR."""
    return {
        **module.to_json(),
        "status": "OBJECT_STORE_EXPRESSION_CFG_COMPLETE_LIVE_BLOCKED",
        "live": False,
        "supported_contract": {
            "assign": "one RHS expression CFG, receiver, store, sync",
            "chained_assign": (
                "one RHS CFG, then each simple attribute target in source "
                "order"),
            "flat_unpack_assign": (
                "one RHS CFG and Python unpack before ordered attribute "
                "targets"),
            "augassign": (
                "receiver, old-value, one RHS CFG, Python inplace result, "
                "store, sync"),
            "receiver": "one simple runtime object-reference name",
            "control_flow": "fragment remains at the exact AST statement site",
            "exceptions": "sync executes only after a successful source store",
            "expressions": (
                "constants, names, attributes, positional calls, unary and "
                "binary arithmetic, comparisons including chains, lazy "
                "conditional expressions, tuple/list and subscript/slice"),
        },
        "live_blockers": [
            "the full gameplay class/CFG frontend is not lowered",
            "compound receiver alias analysis is deliberately fail-closed",
            "multiple normalized fields in one assignment are deliberately "
            "fail-closed until grouped hook lowering exists",
            "the C backend has no providers for target-neutral Python object "
            "protocol ops such as call/attribute/binary",
            "the VM provider does not execute expression CFG or effect SSA",
            "linked object layout, stack, tstate and queue proofs are absent",
        ],
    }


def write_active_object_store_ir_report(
        project_root: Path | str, output_path: Path | str,
        ) -> ObjectStoreModuleIR:
    module = lower_active_object_store_ir(project_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(
        json.dumps(object_store_ir_report(module), ensure_ascii=False,
                   sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    os.replace(temporary, path)
    return module
