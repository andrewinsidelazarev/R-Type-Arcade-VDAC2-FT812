"""Materialize sealed lambda bodies without promoting them to call-graph edges."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

from .function_cfg import lower_python_function_cfg


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def materialize_lambda_definitions(functions, units):
    """Append definition-only units in source order; keep existing indices intact.

    Fixed positional/keyword-only signatures retain definition-time defaults.
    Variadic forms retain their original explicit adapter.
    """
    added = []
    pending = 0
    for unit in list(units):
        owner = functions[unit["owner"]]
        for block in unit["blocks"]:
            for index, item in enumerate(block["instructions"]):
                if item["op"] != "make-lambda-function":
                    continue
                attrs = item["attributes"]
                seal = {key: value for key, value in attrs.items()
                        if key != "scope_semantic_sha256"}
                if _hash(seal) != attrs.get("scope_semantic_sha256"):
                    raise ValueError("lambda scope seal mismatch")
                args = item["arguments"]
                if len(args) != 4:
                    raise ValueError("lambda operand layout mismatch")
                globals_value, defaults, kwdefaults, cells = args
                signature = attrs["signature"]
                body = attrs["body"]
                if (attrs["body_kind"] != "ordinary" or
                        body.get("nested_scopes") or any(
                            kind not in ("positional-only", "positional-or-keyword", "keyword-only")
                            for name, kind, default in signature)):
                    pending += 1
                    continue
                expression = ast.parse(body["source"], mode="eval").body
                if hashlib.sha256(ast.dump(expression, include_attributes=False).encode()).hexdigest() != body["ast_sha256"]:
                    raise ValueError("lambda body seal mismatch")
                if any(isinstance(child, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                       for child in ast.walk(expression)):
                    pending += 1
                    continue
                default_pairs = [*defaults, *kwdefaults]
                descriptors = attrs.get("default_expressions", [])
                if ([pair[0] for pair in default_pairs] != [name for name, _, has_default in signature if has_default] or
                        [pair[0] for pair in descriptors] != [pair[0] for pair in default_pairs] or
                        any(len(pair) != 2 or not isinstance(pair[1], str) or not pair[1].startswith("%") for pair in default_pairs)):
                    raise ValueError("lambda default operands do not match source signature")
                default_nodes = {}
                for name, descriptor in descriptors:
                    default_node = ast.parse(descriptor["source"], mode="eval").body
                    if hashlib.sha256(ast.dump(default_node, include_attributes=False).encode()).hexdigest() != descriptor["ast_sha256"]:
                        raise ValueError("lambda default expression seal mismatch")
                    default_nodes[name] = default_node
                arguments = ast.arguments(
                    posonlyargs=[ast.arg(arg=name) for name, kind, _ in signature if kind == "positional-only"],
                    args=[ast.arg(arg=name) for name, kind, _ in signature if kind == "positional-or-keyword"],
                    vararg=None,
                    kwonlyargs=[ast.arg(arg=name) for name, kind, _ in signature if kind == "keyword-only"],
                    kw_defaults=[default_nodes.get(name) for name, kind, _ in signature if kind == "keyword-only"],
                    kwarg=None,
                    defaults=[default_nodes[name] for name, kind, has_default in signature if kind != "keyword-only" and has_default])
                sealed_lambda = ast.Lambda(args=arguments, body=expression)
                if hashlib.sha256(ast.dump(sealed_lambda, include_attributes=False).encode()).hexdigest() != attrs["ast_sha256"]:
                    raise ValueError("lambda signature/body identity mismatch")
                if ([pair[0] for pair in cells] != list(attrs["free_cell_names"]) or
                        len({pair[0] for pair in cells}) != len(cells) or
                        any(len(pair) != 2 or not isinstance(pair[1], str) or
                            not pair[1].startswith("%") for pair in cells)):
                    raise ValueError("lambda closure identity mismatch")
                identity = owner["callable_id"] + "::<lambda>:" + _hash(
                    [unit["name"], block["name"], index, attrs["scope_semantic_sha256"]])
                # A lambda is precisely a function returning its expression;
                # use the existing AST lowerer, not a second expression compiler.
                node = ast.fix_missing_locations(ast.FunctionDef(
                    name="_lambda_body", args=arguments,
                    body=[ast.Return(value=expression)], decorator_list=[]))
                source = ast.unparse(node)
                node = ast.parse(source).body[0]
                cfg = lower_python_function_cfg(node, class_name=None,
                    source_path=Path("<sealed-lambda>"), source_text=source).to_json()
                function_index = len(functions)
                functions.append({"callable_id": identity, "unit": len(units),
                    "parameter_count": len(signature), "meta": {
                        "module": owner["meta"].get("module"),
                        "lexical_parent_id": owner["callable_id"],
                        "ast_sha256": attrs["ast_sha256"], "definition_only": True}})
                new_units = [{"kind": 1, "owner": function_index, "name": identity,
                    "result": None, "entry": cfg["entry"], "blocks": cfg["blocks"],
                    "lexical_parent_callable_id": owner["callable_id"],
                    "meta": {k: copy.deepcopy(v) for k, v in cfg.items()
                             if k not in ("blocks", "expression_programs")}}]
                for number, program in enumerate(cfg["expression_programs"]):
                    old_name = program["program_id"]
                    new_name = identity + f":expression:{number}"
                    for b in cfg["blocks"]:
                        for instruction in b["instructions"]:
                            if instruction["op"] == "execute-expression-cfg" and instruction["arguments"][0] == old_name:
                                instruction["arguments"][0] = new_name
                    new_units.append({"kind": 2, "owner": function_index, "name": new_name,
                        "result": program["result"], "entry": program["entry"],
                        "blocks": program["blocks"], "meta": {
                            k: copy.deepcopy(v) for k, v in program.items() if k != "blocks"}})
                for new_unit in new_units:
                    for b in new_unit["blocks"]:
                        for sequence, instruction in enumerate(b["instructions"]):
                            if instruction["op"] == "python-call":
                                instruction["_target_call_site"] = {
                                    "call_site_id": identity + f":{new_unit['name']}:{b['name']}:{sequence}",
                                    "resolution_kind": "unresolved-lambda-body", "target_callable_ids": []}
                units.extend(new_units)
                item["op"] = "make-source-function-defaults" if default_pairs else "make-source-function"
                item["arguments"] = [globals_value, *(pair[1] for pair in cells), *(pair[1] for pair in default_pairs)]
                item["attributes"] = dict(attrs, source_callable_id=identity,
                    definition_ast_sha256=attrs["ast_sha256"],
                    closure_names=[pair[0] for pair in cells])
                if default_pairs:
                    item["attributes"]["default_names"] = [pair[0] for pair in default_pairs]
                added.append(identity)
    return {"definition_only_callable_ids": added, "definitions_pending": pending}
