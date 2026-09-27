"""Независимое от Z80 типизированное трёхадресное IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diagnostics import SourceSpan
from .manifest import ParameterSpec
from .types import ScalarType


@dataclass
class Instruction:
    op: str
    destination: str | None
    arguments: tuple[Any, ...]
    type: ScalarType | None
    span: SourceSpan
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "op": self.op,
            "arguments": list(self.arguments),
            "span": self.span.__dict__,
        }
        if self.destination is not None:
            result["destination"] = self.destination
        if self.type is not None:
            result["type"] = self.type.name
        if self.attributes:
            result["attributes"] = dict(sorted(self.attributes.items()))
        return result


@dataclass
class Terminator:
    op: str
    arguments: tuple[Any, ...]
    targets: tuple[str, ...]
    span: SourceSpan

    def to_json(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "arguments": list(self.arguments),
            "targets": list(self.targets),
            "span": self.span.__dict__,
        }


@dataclass
class BasicBlock:
    name: str
    instructions: list[Instruction] = field(default_factory=list)
    terminator: Terminator | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instructions": [item.to_json() for item in self.instructions],
            "terminator": (self.terminator.to_json()
                           if self.terminator is not None else None),
        }


@dataclass
class FunctionIR:
    symbol: str
    export: str
    parameters: tuple[ParameterSpec, ...]
    return_type: ScalarType
    entry: str
    blocks: dict[str, BasicBlock]
    local_types: dict[str, ScalarType]
    temporary_types: dict[str, ScalarType]
    source_hash: str
    ast_hash: str

    def to_json(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "export": self.export,
            "parameters": [
                {
                    "name": item.name,
                    "type": item.type.name,
                    "minimum": item.minimum,
                    "maximum": item.maximum,
                }
                for item in self.parameters
            ],
            "return": self.return_type.name,
            "entry": self.entry,
            "blocks": [self.blocks[name].to_json()
                       for name in sorted(self.blocks)],
            "locals": {name: kind.name
                       for name, kind in sorted(self.local_types.items())},
            "temporaries": {name: kind.name
                            for name, kind in sorted(self.temporary_types.items())},
            "source_hash": self.source_hash,
            "ast_hash": self.ast_hash,
        }


@dataclass(frozen=True)
class ObjectEffectInstruction:
    """One target-neutral object-effect operation.

    These instructions are intentionally separate from the scalar
    :class:`Instruction` stream consumed by the current C backend.  They
    preserve Python evaluation order and SSA value identity without claiming
    that object layout or expression lowering already exists on Z80.
    """

    sequence: int
    op: str
    destination: str | None
    arguments: tuple[Any, ...]
    value_kind: str | None
    span: SourceSpan
    attributes: tuple[tuple[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sequence": self.sequence,
            "op": self.op,
            "arguments": list(self.arguments),
            "span": self.span.__dict__,
        }
        if self.destination is not None:
            result["destination"] = self.destination
        if self.value_kind is not None:
            result["value_kind"] = self.value_kind
        if self.attributes:
            result["attributes"] = {
                name: value for name, value in self.attributes}
        return result


@dataclass(frozen=True)
class ObjectExpressionTerminator:
    """Control-flow terminator for one source-derived Python expression."""

    op: str
    arguments: tuple[Any, ...]
    targets: tuple[str, ...]
    span: SourceSpan

    def to_json(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "arguments": list(self.arguments),
            "targets": list(self.targets),
            "span": self.span.__dict__,
        }


@dataclass(frozen=True)
class ObjectExpressionBlock:
    """One basic block in the target-neutral object expression CFG."""

    name: str
    instructions: tuple[ObjectEffectInstruction, ...]
    terminator: ObjectExpressionTerminator

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instructions": [item.to_json() for item in self.instructions],
            "terminator": self.terminator.to_json(),
        }


@dataclass(frozen=True)
class ObjectExpressionIR:
    """Typed SSA/CFG lowering of one Python RHS expression.

    This remains backend-neutral: operations retain Python value semantics and
    therefore make no claim about a concrete object ABI or C implementation.
    """

    program_id: str
    entry: str
    result: str
    result_kind: str
    blocks: tuple[ObjectExpressionBlock, ...]
    source: str
    ast_sha256: str
    semantic_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "entry": self.entry,
            "result": self.result,
            "result_kind": self.result_kind,
            "blocks": [item.to_json() for item in self.blocks],
            "source": self.source,
            "ast_sha256": self.ast_sha256,
            "semantic_sha256": self.semantic_sha256,
        }


@dataclass(frozen=True)
class ObjectStoreFragmentIR:
    """SSA effect fragment spliced at one exact Python mutation site."""

    site_id: int
    source_kind: str
    field_name: str
    field_id: int
    class_name: str | None
    function_name: str | None
    statement_ast_sha256: str
    site_ast_sha256: str
    control_context: tuple[str, ...]
    expression: ObjectExpressionIR
    instructions: tuple[ObjectEffectInstruction, ...]
    semantic_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "source_kind": self.source_kind,
            "field": self.field_name,
            "field_id": self.field_id,
            "class": self.class_name,
            "function": self.function_name,
            "statement_ast_sha256": self.statement_ast_sha256,
            "site_ast_sha256": self.site_ast_sha256,
            "control_context": list(self.control_context),
            "expression": self.expression.to_json(),
            "instructions": [item.to_json() for item in self.instructions],
            "semantic_sha256": self.semantic_sha256,
        }


@dataclass(frozen=True)
class ObjectStoreModuleIR:
    """All object-store fragments bound to one active Python module."""

    format: str
    source_path: str
    source_sha256: str
    mutation_hook_semantic_sha256: str
    fragments: tuple[ObjectStoreFragmentIR, ...]
    bind_schema_site_ids: tuple[int, ...]
    coverage: dict[str, Any]
    semantic_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "source": {
                "path": self.source_path,
                "sha256": self.source_sha256,
            },
            "mutation_hook_semantic_sha256": (
                self.mutation_hook_semantic_sha256),
            "fragments": [item.to_json() for item in self.fragments],
            "bind_schema_site_ids": list(self.bind_schema_site_ids),
            "coverage": self.coverage,
            "semantic_sha256": self.semantic_sha256,
        }


@dataclass(frozen=True)
class PythonFunctionCFGBlocker:
    """One exact source construct preventing executable function lowering."""

    code: str
    message: str
    node_kind: str
    span: SourceSpan
    ast_sha256: str
    source: str

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_kind": self.node_kind,
            "span": self.span.__dict__,
            "ast_sha256": self.ast_sha256,
            "source": self.source,
        }


@dataclass(frozen=True)
class PythonFunctionTerminator:
    op: str
    arguments: tuple[Any, ...]
    targets: tuple[str, ...]
    span: SourceSpan

    def to_json(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "arguments": list(self.arguments),
            "targets": list(self.targets),
            "span": self.span.__dict__,
        }


@dataclass(frozen=True)
class PythonFunctionBlock:
    name: str
    instructions: tuple[ObjectEffectInstruction, ...]
    terminator: PythonFunctionTerminator
    exception_target: str | None = None

    def to_json(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "instructions": [item.to_json() for item in self.instructions],
            "terminator": self.terminator.to_json(),
        }
        if self.exception_target is not None:
            result["exception_target"] = self.exception_target
        return result


@dataclass(frozen=True)
class ActivePythonFunctionIR:
    """Target-neutral CFG for one active function owning mutation sites."""

    function_id: str
    class_name: str | None
    function_name: str
    definition_line: int
    ast_sha256: str
    signature: dict[str, Any]
    entry: str
    blocks: tuple[PythonFunctionBlock, ...]
    expression_programs: tuple[ObjectExpressionIR, ...]
    mutation_site_ids: tuple[int, ...]
    spliced_store_fragments: tuple[tuple[int, str], ...]
    blockers: tuple[PythonFunctionCFGBlocker, ...]
    semantic_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "class": self.class_name,
            "function": self.function_name,
            "definition_line": self.definition_line,
            "ast_sha256": self.ast_sha256,
            "signature": self.signature,
            "entry": self.entry,
            "blocks": [item.to_json() for item in self.blocks],
            "expression_programs": [
                item.to_json() for item in self.expression_programs],
            "mutation_site_ids": list(self.mutation_site_ids),
            "spliced_store_fragments": [
                {"site_id": site_id, "semantic_sha256": semantic}
                for site_id, semantic in self.spliced_store_fragments
            ],
            "blockers": [item.to_json() for item in self.blockers],
            "semantic_sha256": self.semantic_sha256,
        }


@dataclass(frozen=True)
class ActivePythonFunctionModuleIR:
    """CFG inventory for every active function owning a mutation hook."""

    format: str
    source_path: str
    source_sha256: str
    mutation_hook_semantic_sha256: str
    object_store_semantic_sha256: str
    functions: tuple[ActivePythonFunctionIR, ...]
    coverage: dict[str, Any]
    semantic_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "source": {
                "path": self.source_path,
                "sha256": self.source_sha256,
            },
            "mutation_hook_semantic_sha256": (
                self.mutation_hook_semantic_sha256),
            "object_store_semantic_sha256": (
                self.object_store_semantic_sha256),
            "functions": [item.to_json() for item in self.functions],
            "coverage": self.coverage,
            "semantic_sha256": self.semantic_sha256,
        }
