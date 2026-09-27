"""Понижение проверенных включений и генераторных выражений через function CFG."""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

from .function_cfg import lower_python_function_cfg
from .lambda_lowering import _hash


def _ast_hash(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def _expression(descriptor, *, target=False):
    # В исходном включении перенос строки разрешён внешними скобками.
    # Восстанавливаем этот контекст, не меняя AST и его контрольную сумму.
    node = ast.parse('('+descriptor["source"]+'\n)', mode="eval").body
    if target:
        for child in ast.walk(node):
            if isinstance(child, (ast.Name, ast.Tuple, ast.List, ast.Starred)):
                child.ctx = ast.Store()
    if _ast_hash(node) != descriptor["ast_sha256"]:
        raise ValueError("comprehension expression seal mismatch")
    return node


def materialize_list_comprehensions(functions, units):
    added = []
    pending = 0
    kinds = {"list":0, "dict":0, "set":0, "generator":0}
    # Добавленные тела также обрабатываются: вложенный AST строго меньше родительского.
    for unit in units:
        owner = functions[unit["owner"]]
        for block in unit["blocks"]:
            expanded = []
            for index, item in enumerate(block["instructions"]):
                if item["op"] not in ("run-eager-comprehension", "make-generator-expression"):
                    expanded.append(item)
                    continue
                attrs = item["attributes"]
                plan = attrs["plan"]
                if _hash(plan) != attrs["plan_semantic_sha256"]:
                    raise ValueError("comprehension plan seal mismatch")
                generators = plan["generators"]
                kind = plan["kind"]
                if (kind=="generator") != (item["op"]=="make-generator-expression"):
                    raise ValueError("comprehension eager/lazy contract mismatch")
                production_fields = ("key", "value") if kind == "dict" else ("element",)
                if (kind not in ("list", "dict", "set", "generator") or not generators or
                        any(g["is_async"] for g in generators)):
                    pending += 1
                    expanded.append(item)
                    continue
                production_op = {"dict":"store-subscript", "list":"list-append", "set":"set-add", "generator":"yield"}[kind]
                if (plan["production"]["operation"] != ("mapping-setitem" if kind=="dict" else production_op) or
                        plan["production"]["evaluation_order"] != ("key-then-value-then-setitem" if kind=="dict" else "element-then-produce") or
                        plan["scope"] != "separate-implicit-function-scope" or
                        plan["loop_order"] != "depth-first-left-to-right"):
                    raise ValueError("comprehension execution contract mismatch")
                source_generators = [ast.comprehension(
                    target=_expression(g["target"], target=True),
                    iter=_expression(g["iterator"]["expression"]),
                    ifs=[_expression(f) for f in g["filters"]], is_async=0)
                    for g in generators]
                produced = [_expression(plan["production"][field]) for field in production_fields]
                original = ast.DictComp(key=produced[0],value=produced[1],generators=source_generators) if kind=="dict" else {"set":ast.SetComp,"list":ast.ListComp,"generator":ast.GeneratorExp}[kind](elt=produced[0], generators=source_generators)
                if _ast_hash(original) != plan["ast_sha256"]:
                    raise ValueError("comprehension AST identity mismatch")
                # Вложенная lambda пока требует отдельного доказательства области.
                if any(child is not original and isinstance(child, ast.Lambda)
                        for child in ast.walk(original)):
                    pending += 1
                    expanded.append(item)
                    continue
                iterator, globals_value, cells = item["arguments"]
                if ([pair[0] for pair in cells] != list(plan["free_cell_names"]) or
                        len({pair[0] for pair in cells}) != len(cells)):
                    raise ValueError("comprehension captured-cell identity mismatch")
                names = {node.id for node in ast.walk(original) if isinstance(node, ast.Name)}
                def fresh(base):
                    while base in names:
                        base += "_"
                    names.add(base)
                    return base
                iterator_name = fresh("_pz_iterator")
                result_name = fresh("_pz_result")
                append_name = fresh("_pz_append")
                identity = owner["callable_id"] + f"::<{kind}comp>:" + _hash(
                    [unit["name"], block["name"], index, attrs["plan_semantic_sha256"]])
                # Аргументы marker-call дают точный порядок key -> value.
                # Обычный result[key] = value вычислил бы value раньше key.
                body = [ast.Expr(value=ast.Call(func=ast.Name(id=append_name, ctx=ast.Load()),
                    args=[ast.Name(id=result_name, ctx=ast.Load()), *produced], keywords=[]))]
                if kind=="generator":
                    body=[ast.Expr(value=ast.Yield(value=produced[0]))]
                for number in reversed(range(len(source_generators))):
                    generator = source_generators[number]
                    for condition in reversed(generator.ifs):
                        body = [ast.If(test=condition, body=body, orelse=[])]
                    body = [ast.For(target=generator.target,
                        iter=ast.Name(id=iterator_name, ctx=ast.Load()) if number == 0 else generator.iter,
                        body=body, orelse=[])]
                node = ast.fix_missing_locations(ast.FunctionDef(name=f"_{kind}comp_body",
                    args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=iterator_name)],
                        vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
                    body=([*body,ast.Return(value=None)] if kind=="generator" else [ast.Assign(targets=[ast.Name(id=result_name, ctx=ast.Store())],
                            value=(ast.Dict(keys=[], values=[]) if kind=="dict" else
                                   ast.Call(func=ast.Name(id=append_name,ctx=ast.Load()),args=[],keywords=[]) if kind=="set" else
                                   ast.List(elts=[], ctx=ast.Load()))), *body,
                          ast.Return(value=ast.Name(id=result_name, ctx=ast.Load()))]), decorator_list=[]))
                # Обёртка нужна только анализатору областей: реальные захваты уже
                # передаются ячейками. Без неё свободная переменная превращается
                # в глобальную при анализе вложенного генераторного выражения.
                wrapper = ast.fix_missing_locations(ast.FunctionDef(name="_pz_lexical_owner",
                    args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=pair[0]) for pair in cells],
                        vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
                    body=[node], decorator_list=[]))
                source = ast.unparse(wrapper)
                cfg = lower_python_function_cfg(ast.parse(source).body[0].body[0], class_name=None,
                    source_path=Path(f"<sealed-{kind}comp>"), source_text=source).to_json()
                function_index = len(functions)
                functions.append({"callable_id": identity, "unit": len(units), "parameter_count": 1,
                    "meta": {"module": owner["meta"].get("module"), "definition_only": True,
                             "lexical_parent_id": owner["callable_id"], "ast_sha256": plan["ast_sha256"]}})
                new_units = [{"kind": 1, "owner": function_index, "name": identity, "result": None,
                    "entry": cfg["entry"], "blocks": cfg["blocks"],
                    "lexical_parent_callable_id": owner["callable_id"],
                    "meta": {k: copy.deepcopy(v) for k, v in cfg.items() if k not in ("blocks", "expression_programs")}}]
                rename = {p["program_id"]: identity + f":expression:{n}"
                          for n, p in enumerate(cfg["expression_programs"])}
                for program in cfg["expression_programs"]:
                    new_units.append({"kind": 2, "owner": function_index, "name": rename[program["program_id"]],
                        "result": program["result"], "entry": program["entry"], "blocks": program["blocks"],
                        "meta": {k: copy.deepcopy(v) for k, v in program.items() if k != "blocks"}})
                append_count = 0
                create_count = 0
                for new_unit in new_units:
                    marker_values = {instruction["destination"] for b in new_unit["blocks"]
                        for instruction in b["instructions"] if instruction["op"] == "load-name"
                        and instruction["arguments"] == [append_name]}
                    for b in new_unit["blocks"]:
                        for instruction in b["instructions"]:
                            if instruction["op"] == "require-callable" and instruction["arguments"][0] in marker_values:
                                marker_values.add(instruction["destination"])
                                instruction.update(op="vm-copy", attributes={})
                    for b in new_unit["blocks"]:
                        for sequence, instruction in enumerate(b["instructions"]):
                            if instruction["op"] == "execute-expression-cfg":
                                instruction["arguments"][0] = rename[instruction["arguments"][0]]
                            if instruction["op"] == "load-name" and instruction["arguments"] == [append_name]:
                                instruction.update(op="constant", arguments=[None], attributes={})
                            if instruction["op"] == "python-call":
                                if instruction["arguments"][0] in marker_values:
                                    # Нулевой marker создаёт именно пустой set, не вызов затеняемого set().
                                    create = kind=="set" and len(instruction["arguments"])==1
                                    instruction.update(op="build-set" if create else production_op, arguments=instruction["arguments"][1:],
                                        attributes={"sealed_comprehension": identity})
                                    create_count += int(create)
                                    append_count += int(not create)
                                else:
                                    instruction["_target_call_site"] = {"call_site_id": identity +
                                        f":{new_unit['name']}:{b['name']}:{sequence}", "resolution_kind": "unresolved-comprehension-body",
                                        "targets": []}
                if append_count != int(kind!="generator") or create_count != int(kind=="set"):
                    raise ValueError("comprehension production instruction missing/ambiguous")
                units.extend(new_units)
                # Внешний iter() уже выполнен создателем. Передаём реальные
                # ячейки и этот итератор в изолированную область.
                closure = f"%{kind}comp_closure_" + identity.rsplit(":", 1)[1]
                if any(i.get("destination") == closure for b in unit["blocks"] for i in b["instructions"]):
                    raise ValueError("comprehension temporary collision")
                create = copy.deepcopy(item)
                create.update(op="make-source-function", destination=closure,
                    arguments=[globals_value, *(pair[1] for pair in cells)],
                    attributes={"source_callable_id": identity, "closure_names": [pair[0] for pair in cells],
                                "definition_ast_sha256": plan["ast_sha256"]}, value_kind="py-function")
                call = copy.deepcopy(item)
                call.update(op="python-call", arguments=[closure, iterator],
                    attributes={"argument_layout": [["positional", None]], "argument_count": 1,
                                "generated_comprehension_invocation": identity},
                    _target_call_site={"call_site_id": identity + ":invoke", "resolution_kind": "sealed-comprehension",
                                       "targets": [identity]})
                expanded.extend((create, call))
                added.append(identity)
                kinds[kind] += 1
            block["instructions"] = expanded
    return {"definition_only_callable_ids": added, "definitions_pending": pending, "definitions_by_kind":kinds}
