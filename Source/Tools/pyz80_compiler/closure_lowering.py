"""Flatten source-sealed nested definitions into native closure operands.

Defaults are retained as the already-evaluated source operands. Coroutines and
variadic signatures remain explicit adapters; no default expression is rerun.
"""
from __future__ import annotations


def lower_closure_definitions(functions, units):
    lowered = 0
    pending = 0
    modules = {row["meta"]["module"]: row["meta"] for row in functions if row["meta"].get("module_body")}
    for unit in units:
        owner = functions[unit["owner"]]
        for block in unit["blocks"]:
            for item in block["instructions"]:
                if item['op'] == 'build-function-annotations':
                    item['op'] = 'build-dict'
                if item["op"] == "python-import-module" and owner["meta"].get("module") in modules:
                    # Source operands are all literals, never user expressions.
                    # Keep their exact values in the proof-bound descriptor.
                    args = item["arguments"]
                    if (len(args) != 4 or not isinstance(args[0], (str, type(None))) or
                            type(args[1]) is not int or args[1] < 0 or
                            not isinstance(args[2], (list, tuple)) or any(not isinstance(n, str) for n in args[2]) or
                            args[3] not in ("root-package", "full-module", "fromlist-module")):
                        raise ValueError("invalid literal source import layout")
                    item["attributes"] = dict(item.get("attributes", {}),
                        source_import={"owner": owner["meta"]["module"], "name": args[0],
                            "level": args[1], "fromlist": list(args[2]), "mode": args[3]})
                if item["op"] in ("load-name", "load-global-name", "store-global-name", "load-class-name", "load-class-free-name", "store-class-name", "setup-class-annotations", "setup-global-annotations"):
                    item["attributes"] = dict(item.get("attributes", {}),
                                              owner_callable_id=owner["callable_id"])
                if item["op"] == "capture-expression-closure-cell":
                    item["op"] = "capture-closure-cell"
                if item["op"] in ("load-current-globals", "load-expression-globals"):
                    item["op"] = "load-source-globals"
                    item["attributes"] = dict(item.get("attributes", {}),
                                              owner_callable_id=owner["callable_id"])
                if item["op"] == "python-apply-decorator":
                    item["op"] = "python-call"
                    item["attributes"] = dict(item.get("attributes", {}), argument_layout=[["positional", None]])
                class_body = item["op"] == "make-class-body"
                if item["op"] != "make-function" and not class_body:
                    continue
                args = item["arguments"]
                if class_body:
                    if len(args) != 4:
                        raise ValueError("malformed sealed class body operands")
                    reference, ast_hash, globals_value, cells = args
                    args = [reference, ast_hash, "class-body", globals_value, [], [], cells, []]
                if len(args) != 8:
                    raise ValueError("malformed nested function operands")
                reference, ast_hash, kind, globals_value, defaults, kwdefaults, cells, annotations = args
                module_body = owner["meta"].get("module_body") is True
                matches = [row for row in functions
                           if row["meta"].get("definition_parent_id", row["meta"].get("lexical_parent_id")) == (None if module_body else owner["callable_id"])
                           and row["meta"].get("ast_sha256") == ast_hash
                           and row["meta"].get("module") == owner["meta"].get("module")
                           and bool(row["meta"].get("class_body")) == class_body
                           # Одинаковый AST двух определений не делает их одним
                           # вхождением: имя и строка берутся из sealed reference.
                           and (("definition_parent_id" in row["meta"] and
                                 row["callable_id"].split("::",1)[-1].rsplit(".",1)[-1] == reference) or
                                ("definition_parent_id" not in row["meta"] and
                                (row["callable_id"] == owner["meta"]["module"] + "::" + reference if module_body
                                 else row["callable_id"].endswith(".<locals>." + reference))))]
                if len(matches) > 1:
                    raise ValueError("ambiguous sealed nested function identity")
                if not matches or kind not in ("function", "class-body"):
                    pending += 1
                    continue
                signature = units[matches[0]["unit"]]["meta"]["signature"]
                if (signature.get("execution_kind") == "generator-frame" and
                        not units[matches[0]["unit"]]["meta"].get("generator_next_body_sha256")):
                    pending += 1
                    continue
                parameters = signature["parameters"]
                if any(p.get("kind") not in ("positional-only", "positional-or-keyword", "keyword-only")
                       for p in parameters):
                    pending += 1
                    continue
                default_pairs = [*defaults, *kwdefaults]
                if ([pair[0] for pair in default_pairs] != [p["name"] for p in parameters if p.get("default") is not None] or
                    any(len(pair) != 2 or not isinstance(pair[1], str) or not pair[1].startswith("%") for pair in default_pairs)):
                    raise ValueError("default operands do not match source signature")
                if (not isinstance(cells, (list, tuple)) or
                        any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                            not isinstance(pair[0], str) or not pair[0] or
                            not isinstance(pair[1], str) or not pair[1].startswith("%") for pair in cells) or
                        len({pair[0] for pair in cells}) != len(cells)):
                    raise ValueError("invalid closure cell identity layout")
                item["op"] = "make-source-function-defaults" if default_pairs else "make-source-function"
                item["arguments"] = [globals_value, *(pair[1] for pair in cells), *(pair[1] for pair in default_pairs)]
                item["attributes"] = dict(item.get("attributes", {}),
                    source_callable_id=matches[0]["callable_id"],
                    definition_ast_sha256=ast_hash,
                    closure_names=[pair[0] for pair in cells],
                    annotations=annotations)
                if signature.get("execution_kind") == "generator-frame":
                    item["attributes"]["generator_next_body_sha256"] = units[matches[0]["unit"]]["meta"]["generator_next_body_sha256"]
                if default_pairs:
                    item["attributes"]["default_names"] = [pair[0] for pair in default_pairs]
                lowered += 1
    return {"source_definitions_lowered": lowered, "definitions_pending": pending,
            "captured_values_are_shared_cells": True,
            "defaults_not_reevaluated_or_discarded": True}
