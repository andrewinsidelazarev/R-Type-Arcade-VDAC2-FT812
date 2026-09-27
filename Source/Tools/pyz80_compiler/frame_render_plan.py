"""Source-derived full-frame Z-order for the active Python runtime.

The object DrawPlan deliberately covers only ``M72EnemyWorld.draw``.  This
module captures the surrounding ``Game.render`` order, including conditional
player/effect branches and shot/wave loops, so a target backend cannot move the
background, foreground, HUD or distance indicator around by convention.

This is an IR/audit only.  It does not claim that every layer has a live FT812
lowering; that remains an explicit blocker until the generated frame pipeline
and whole-frame budget certificate consume this exact plan.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


FRAME_RENDER_PLAN_FORMAT = "pyz80.frame-render-plan.v1"

__all__ = [
    "FRAME_RENDER_PLAN_FORMAT",
    "FrameRenderPlan",
    "FrameRenderPlanError",
    "RenderGroup",
    "RenderSink",
    "compile_active_frame_render_plan",
]


class FrameRenderPlanError(ValueError):
    """The active render source no longer fits the proved finite shape."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ast_sha256(value: ast.AST) -> str:
    return _sha256_bytes(
        ast.dump(value, annotate_fields=True, include_attributes=False).encode(
            "utf-8"))


def _attribute_path(value: ast.AST) -> str | None:
    parts: list[str] = []
    cursor = value
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    parts.append(cursor.id)
    return ".".join(reversed(parts))


def _is_render_sink(call: ast.Call) -> bool:
    path = _attribute_path(call.func)
    if path is None:
        return False
    if path in ("target.fill", "target.blit"):
        return True
    parts = path.split(".")
    if parts[0] != "self":
        return False
    method = parts[-1]
    return method in ("draw", "draw_back", "draw_front") or method.startswith(
        "_draw_")


def _target_calls(method: ast.FunctionDef) -> tuple[ast.Call, ...]:
    return tuple(
        node for node in ast.walk(method)
        if isinstance(node, ast.Call) and
        (_attribute_path(node.func) or "").startswith("target.")
    )


@dataclass(frozen=True)
class RenderSink:
    ordinal: int
    group_ordinal: int
    call_path: str
    line: int
    column: int
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "group_ordinal": self.group_ordinal,
            "call_path": self.call_path,
            "line": self.line,
            "column": self.column,
            "ast_sha256": self.ast_sha256,
        }


@dataclass(frozen=True)
class RenderGroup:
    ordinal: int
    control_kind: str
    first_line: int
    last_line: int
    ast_sha256: str
    sink_ordinals: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "control_kind": self.control_kind,
            "first_line": self.first_line,
            "last_line": self.last_line,
            "ast_sha256": self.ast_sha256,
            "sink_ordinals": list(self.sink_ordinals),
        }


@dataclass(frozen=True)
class FrameRenderPlan:
    source_path: str
    source_sha256: str
    launcher_sha256: str
    method_ast_sha256: str
    sinks: tuple[RenderSink, ...]
    groups: tuple[RenderGroup, ...]
    sink_order_sha256: str
    semantic_sha256: str

    def as_dict(self) -> dict[str, object]:
        paths = [item.call_path for item in self.sinks]
        background = paths.index("self.stage.draw_back")
        foreground = paths.index("self.stage.draw_front")
        return {
            "format": FRAME_RENDER_PLAN_FORMAT,
            "status": "SOURCE_DERIVED_IR_LIVE_LOWERING_BLOCKED",
            "source_program": {
                "launcher": "run_python.cmd",
                "module": "rtype_port.app",
                "canonical": False,
            },
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "launcher_sha256": self.launcher_sha256,
            "symbol": "rtype_port.game.Game.render",
            "method_ast_sha256": self.method_ast_sha256,
            "sink_order_sha256": self.sink_order_sha256,
            "semantic_sha256": self.semantic_sha256,
            "groups": [item.as_dict() for item in self.groups],
            "sinks": [item.as_dict() for item in self.sinks],
            "z_order_contract": {
                "clear_ordinal": paths.index("target.fill"),
                "background_ordinal": background,
                "background_is_lowest_visible_layer": background == 1,
                "enemy_world_ordinal": paths.index("self.enemy_world.draw"),
                "force_ordinal": paths.index("self.force.draw"),
                "bits_ordinal": paths.index("self.bits.draw"),
                "foreground_ordinal": foreground,
                "hud_ordinal": paths.index("target.blit", foreground + 1),
                "distance_ordinal": paths.index("self._draw_debug_distance"),
                "distance_is_last": paths[-1] == "self._draw_debug_distance",
            },
            "live_target_lowering_present": False,
            "live_blockers": [
                "each source-derived render group needs a generated FT812 lowering",
                "the complete frame stream must consume this sink order without fallback",
                "RAM_DL and every scanline must pass the 2048/1209 certificate",
            ],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))


def _method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    classes = [node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(classes) != 1:
        raise FrameRenderPlanError(
            "PZFRP001", f"expected one class {class_name}, got {len(classes)}")
    methods = [node for node in classes[0].body
               if isinstance(node, ast.FunctionDef) and node.name == method_name]
    if len(methods) != 1:
        raise FrameRenderPlanError(
            "PZFRP001", f"expected one {class_name}.{method_name}")
    return methods[0]


def compile_active_frame_render_plan(
        project_root: Path | str, *, game_source_override: str | None = None,
        ) -> FrameRenderPlan:
    """Compile the lexical/control-preserving active ``Game.render`` plan."""
    root = Path(project_root).resolve()
    launcher_bytes = (root / "run_python.cmd").read_bytes()
    try:
        launcher_text = launcher_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrameRenderPlanError(
            "PZFRP002", "run_python.cmd is not UTF-8") from exc
    if "-m rtype_port.app" not in launcher_text:
        raise FrameRenderPlanError(
            "PZFRP002", "run_python.cmd does not launch rtype_port.app")
    source_path = root / "Source" / "Python" / "rtype_port" / "game.py"
    source_text = (
        game_source_override if game_source_override is not None
        else source_path.read_text(encoding="utf-8"))
    try:
        tree = ast.parse(source_text, filename=source_path.as_posix())
    except SyntaxError as exc:
        raise FrameRenderPlanError(
            "PZFRP003", f"cannot parse active game.py: {exc}") from exc
    method = _method(tree, "Game", "render")

    target_calls = _target_calls(method)
    unexpected_target_calls = sorted({
        _attribute_path(call.func) or "<dynamic>"
        for call in target_calls if not _is_render_sink(call)
    })
    if unexpected_target_calls:
        raise FrameRenderPlanError(
            "PZFRP004", "unclassified target rendering calls: " +
            ", ".join(unexpected_target_calls))

    sink_values: list[RenderSink] = []
    group_values: list[RenderGroup] = []
    for statement in method.body:
        calls = sorted(
            (node for node in ast.walk(statement)
             if isinstance(node, ast.Call) and _is_render_sink(node)),
            key=lambda node: (node.lineno, node.col_offset,
                              getattr(node, "end_lineno", node.lineno),
                              getattr(node, "end_col_offset", node.col_offset)),
        )
        if not calls:
            continue
        group_ordinal = len(group_values)
        first_sink = len(sink_values)
        for call in calls:
            path = _attribute_path(call.func)
            if path is None:
                raise FrameRenderPlanError(
                    "PZFRP005", "dynamic draw target escaped classification")
            sink_values.append(RenderSink(
                ordinal=len(sink_values),
                group_ordinal=group_ordinal,
                call_path=path,
                line=call.lineno,
                column=call.col_offset,
                ast_sha256=_ast_sha256(call),
            ))
        group_values.append(RenderGroup(
            ordinal=group_ordinal,
            control_kind=type(statement).__name__,
            first_line=statement.lineno,
            last_line=getattr(statement, "end_lineno", statement.lineno),
            ast_sha256=_ast_sha256(statement),
            sink_ordinals=tuple(range(first_sink, len(sink_values))),
        ))

    paths = [item.call_path for item in sink_values]
    required_once = (
        "target.fill",
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
    missing_or_repeated = [
        f"{path}={paths.count(path)}" for path in required_once
        if paths.count(path) != 1
    ]
    if missing_or_repeated:
        raise FrameRenderPlanError(
            "PZFRP006", "required full-frame sinks changed: " +
            ", ".join(missing_or_repeated))
    if paths[0] != "target.fill" or paths[1] != "self.stage.draw_back":
        raise FrameRenderPlanError(
            "PZFRP007", "background must be the lowest visible layer after clear")
    if paths[-1] != "self._draw_debug_distance":
        raise FrameRenderPlanError(
            "PZFRP008", "distance indicator must remain the final Python layer")
    foreground_ordinal = paths.index("self.stage.draw_front")
    if "target.blit" not in paths[foreground_ordinal + 1:]:
        raise FrameRenderPlanError(
            "PZFRP010", "no direct HUD blit follows the foreground layer")
    required_relative_order = (
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
    ordinals = [paths.index(path) for path in required_relative_order]
    if ordinals != sorted(ordinals):
        raise FrameRenderPlanError(
            "PZFRP009", "major Python render layers changed relative order")

    sink_order_text = "\n".join(
        f"{item.ordinal}:{item.group_ordinal}:{item.call_path}:"
        f"{item.ast_sha256}" for item in sink_values)
    sink_order_sha256 = _sha256_bytes(sink_order_text.encode("utf-8"))
    semantic_payload = {
        "format": FRAME_RENDER_PLAN_FORMAT,
        "method_ast_sha256": _ast_sha256(method),
        "sink_order_sha256": sink_order_sha256,
        "groups": [item.as_dict() for item in group_values],
        "sinks": [item.as_dict() for item in sink_values],
    }
    semantic_sha256 = _sha256_bytes(json.dumps(
        semantic_payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    return FrameRenderPlan(
        source_path="Source/Python/rtype_port/game.py",
        source_sha256=_sha256_bytes(source_text.encode("utf-8")),
        launcher_sha256=_sha256_bytes(launcher_bytes),
        method_ast_sha256=_ast_sha256(method),
        sinks=tuple(sink_values),
        groups=tuple(group_values),
        sink_order_sha256=sink_order_sha256,
        semantic_sha256=semantic_sha256,
    )
