#!/usr/bin/env python3
"""Object-store effect SSA and Python evaluation-order proofs."""

from __future__ import annotations

import ast
import hashlib
import unittest
from pathlib import Path

from pyz80_compiler.diagnostics import CompileError
from pyz80_compiler.frontend import (
    OBJECT_STORE_IR_FORMAT,
    lower_active_object_store_ir,
    lower_object_expression,
    lower_object_store_statement,
    object_store_ir_report,
)


ROOT = Path(__file__).resolve().parents[2]


def _hash(node: ast.AST) -> str:
    return hashlib.sha256(
        ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def _hook(node: ast.AST, *, field: str, field_id: int = 0,
          receiver: str = "obj", source_kind: str = "assign") -> dict[str, object]:
    target = node.target if isinstance(node, ast.AugAssign) else node.targets[0]
    if isinstance(target, (ast.Tuple, ast.List)):
        target = target.elts[0]
    assert isinstance(target, ast.Attribute)
    return {
        "site_id": 7,
        "site_ast_sha256": "a" * 64,
        "statement_ast_sha256": _hash(node),
        "line": node.lineno,
        "column": target.col_offset,
        "class": None,
        "function": None,
        "receiver": receiver,
        "field": field,
        "field_id": field_id,
        "source_kind": source_kind,
        "hook_op": "draw-sync-if-bound",
        "slot_lookup": "receiver.object_slot then checked normalization",
    }


def _statement(source: str) -> tuple[str, ast.stmt]:
    tree = ast.parse(source)
    node = tree.body[0]
    assert isinstance(node, ast.stmt)
    return source, node


class ObjectStoreIRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = lower_active_object_store_ir(ROOT)

    def test_active_store_inventory_is_completely_lowered_but_not_live(self) -> None:
        module = self.module
        self.assertEqual(module.format, OBJECT_STORE_IR_FORMAT)
        self.assertEqual(len(module.fragments), 364)
        self.assertEqual(len(module.bind_schema_site_ids), 4)
        self.assertEqual(module.coverage["runtime_hook_candidates"], 364)
        self.assertEqual(module.coverage["runtime_hook_fragments"], 364)
        self.assertEqual(
            module.coverage["source_kind_counts"],
            {"assign": 363, "augassign": 1})
        self.assertEqual(
            module.coverage["assignment_shape_counts"], {
                "single-attribute": 355,
                "chained-attributes": 2,
                "flat-unpack-attributes": 6,
                "augmented-attribute": 1,
            })
        self.assertEqual(module.coverage["unsupported_active_sites"], 0)
        census = module.coverage["expression_census"]
        self.assertEqual(census["expression_roots"], 364)
        self.assertEqual(census["unsupported_expression_count"], 0)
        self.assertEqual(census["root_ast_kind_counts"], {
            "Attribute": 5,
            "BinOp": 44,
            "Call": 169,
            "Constant": 115,
            "IfExp": 6,
            "Name": 19,
            "Tuple": 6,
        })
        self.assertEqual(census["call_count"], 177)
        self.assertEqual(census["subscript_count"], 0)
        ast_counts = census["all_ast_node_kind_counts"]
        ir_counts = census["expression_ir_op_counts"]
        self.assertEqual(ir_counts["constant"], ast_counts["Constant"])
        self.assertEqual(ir_counts["load-name"], ast_counts["Name"])
        self.assertEqual(ir_counts["load-attribute"],
                         ast_counts["Attribute"])
        self.assertEqual(ir_counts["python-call"], ast_counts["Call"])
        self.assertEqual(ir_counts["require-callable"], ast_counts["Call"])
        self.assertEqual(ir_counts["python-binary"], ast_counts["BinOp"])
        self.assertEqual(ir_counts["python-compare"], ast_counts["Compare"])
        folded_literals = sum(
            isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and
            isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
            for fragment in module.fragments for node in ast.walk(ast.parse('('+fragment.expression.source+'\n)', mode="eval")))
        self.assertGreater(folded_literals, 0)
        self.assertEqual(ir_counts.get("python-unary", 0) + folded_literals, ast_counts["UnaryOp"])
        self.assertEqual(ir_counts["build-tuple"], ast_counts["Tuple"])
        self.assertEqual(ir_counts["phi"], ast_counts["IfExp"])
        self.assertEqual(census["expression_cfg_programs"], 364)
        report = object_store_ir_report(module)
        self.assertFalse(report["live"])
        self.assertTrue(report["coverage"]["opaque_expressions_lowered"])
        self.assertFalse(
            report["coverage"]["current_scalar_pipeline_consumes_object_ir"])
        self.assertGreaterEqual(len(report["live_blockers"]), 5)

    def test_every_fragment_has_single_cfg_execution_and_store_sync(self) -> None:
        for fragment in self.module.fragments:
            operations = [item.op for item in fragment.instructions]
            self.assertNotIn("eval-expression", operations)
            self.assertEqual(operations.count("execute-expression-cfg"), 1)
            self.assertGreaterEqual(len(fragment.expression.blocks), 1)
            self.assertEqual(
                sum(block.terminator.op == "return-expression"
                    for block in fragment.expression.blocks), 1)
            self.assertEqual(operations.count("draw-sync-if-bound"), 1)
            sync_index = operations.index("draw-sync-if-bound")
            self.assertEqual(operations[sync_index - 1], "store-attribute")
            store = fragment.instructions[sync_index - 1]
            sync = fragment.instructions[sync_index]
            self.assertEqual(store.arguments[0], sync.arguments[0])
            self.assertEqual(store.arguments[2], sync.arguments[2])
            self.assertEqual(
                len({item.destination for item in fragment.instructions
                     if item.destination is not None}),
                sum(item.destination is not None
                    for item in fragment.instructions))

    def test_plain_assign_uses_python_rhs_then_receiver_order(self) -> None:
        source, node = _statement("obj.x = rhs()\n")
        fragment = lower_object_store_statement(
            node, _hook(node, field="x", field_id=11),
            source_path=Path("sample.py"), source_text=source)
        self.assertEqual(
            [item.op for item in fragment.instructions],
            ["execute-expression-cfg", "eval-receiver", "store-attribute",
             "draw-sync-if-bound"])
        self.assertEqual(fragment.instructions[0].destination, "%value")
        self.assertEqual(fragment.instructions[1].destination, "%receiver")
        self.assertEqual(
            fragment.instructions[2].arguments,
            ("%receiver", "x", "%value"))
        self.assertEqual(
            fragment.instructions[3].arguments,
            ("%receiver", 11, "%value", 7))

    def test_augassign_loads_old_once_before_rhs_and_reuses_result(self) -> None:
        source, node = _statement("obj.descriptor += rhs()\n")
        assert isinstance(node, ast.AugAssign)
        fragment = lower_object_store_statement(
            node, _hook(node, field="descriptor", field_id=2,
                        source_kind="augassign"),
            source_path=Path("sample.py"), source_text=source)
        self.assertEqual(
            [item.op for item in fragment.instructions],
            ["eval-receiver", "load-attribute", "execute-expression-cfg",
             "python-inplace-binary", "store-attribute",
             "draw-sync-if-bound"])
        self.assertEqual(fragment.instructions[1].destination, "%old")
        self.assertEqual(fragment.instructions[3].arguments,
                         ("add", "%old", "%rhs"))
        self.assertEqual(fragment.instructions[4].arguments,
                         ("%receiver", "descriptor", "%value"))
        self.assertEqual(fragment.instructions[5].arguments,
                         ("%receiver", 2, "%value", 7))

    def test_active_chain_and_unpack_preserve_one_rhs_and_target_order(self) -> None:
        chain = next(fragment for fragment in self.module.fragments
                     if sum(item.op == "store-attribute"
                            for item in fragment.instructions) == 2 and
                     "unpack-sequence" not in
                     [item.op for item in fragment.instructions])
        chain_ops = [item.op for item in chain.instructions]
        self.assertEqual(chain_ops.count("execute-expression-cfg"), 1)
        self.assertEqual(chain_ops.count("eval-receiver"), 2)
        self.assertEqual(chain_ops.count("store-attribute"), 2)

        unpack = next(fragment for fragment in self.module.fragments
                      if any(item.op == "unpack-sequence"
                             for item in fragment.instructions))
        unpack_ops = [item.op for item in unpack.instructions]
        self.assertEqual(unpack_ops[0:4],
                         ["execute-expression-cfg", "unpack-sequence",
                          "unpack-item", "unpack-item"])
        first_receiver = unpack_ops.index("eval-receiver")
        self.assertGreater(first_receiver, unpack_ops.index("unpack-item"))
        self.assertEqual(unpack_ops.count("execute-expression-cfg"), 1)

    def test_if_expression_is_lazy_cfg_with_edge_phi(self) -> None:
        source = "left() if condition else right()"
        expression = ast.parse(source, mode="eval").body
        program = lower_object_expression(
            expression, source_path=Path("sample.py"), source_text=source)
        terminators = [block.terminator.op for block in program.blocks]
        operations = [item.op for block in program.blocks
                      for item in block.instructions]
        self.assertEqual(terminators.count("branch-truth"), 1)
        self.assertEqual(terminators.count("return-expression"), 1)
        self.assertEqual(operations.count("python-call"), 2)
        self.assertEqual(operations.count("phi"), 1)
        self.assertEqual(len({item.destination for block in program.blocks
                              for item in block.instructions}),
                         sum(len(block.instructions)
                             for block in program.blocks))

    def test_generic_attribute_call_subscript_and_arithmetic_are_explicit(self) -> None:
        source = "factory()[index()] + holder.value"
        expression = ast.parse(source, mode="eval").body
        program = lower_object_expression(
            expression, source_path=Path("sample.py"), source_text=source)
        operations = [item.op for block in program.blocks
                      for item in block.instructions]
        self.assertEqual(operations.count("python-call"), 2)
        self.assertEqual(operations.count("load-subscript"), 1)
        self.assertEqual(operations.count("load-attribute"), 1)
        self.assertEqual(operations[-1], "python-binary")

    def test_chained_compare_reuses_middle_operand_through_cfg(self) -> None:
        source = "lower() < middle() < upper()"
        expression = ast.parse(source, mode="eval").body
        program = lower_object_expression(
            expression, source_path=Path("sample.py"), source_text=source)
        operations = [item.op for block in program.blocks
                      for item in block.instructions]
        self.assertEqual(operations.count("python-call"), 3)
        self.assertEqual(operations.count("python-compare"), 2)
        self.assertEqual(operations.count("phi"), 1)
        middle_call = [item.destination for block in program.blocks
                       for item in block.instructions
                       if item.op == "python-call"][1]
        compare_arguments = [item.arguments for block in program.blocks
                             for item in block.instructions
                             if item.op == "python-compare"]
        self.assertEqual(compare_arguments[0][2], middle_call)
        self.assertEqual(compare_arguments[1][1], middle_call)

    def test_keyword_and_star_call_layout_is_explicit(self) -> None:
        source = "call(1, *items, value=2, **options)"
        expression = ast.parse(source, mode="eval").body
        program = lower_object_expression(
            expression, source_path=Path("sample.py"), source_text=source)
        call = next(item for block in program.blocks
                    for item in block.instructions if item.op == "python-call")
        attributes = dict(call.attributes)
        self.assertEqual(attributes["argument_layout"], (
            ("positional", None),
            ("star-positional", None),
            ("keyword", "value"),
            ("star-keyword", None),
        ))

        blocked_source = "lambda value: value"
        blocked = ast.parse(blocked_source, mode="eval").body
        with self.assertRaises(CompileError) as raised:
            lower_object_expression(
                blocked, source_path=Path("sample.py"),
                source_text=blocked_source)
        self.assertEqual(raised.exception.diagnostic.code, "PZ2030")

    def test_unproved_alias_and_suspending_rhs_fail_closed(self) -> None:
        source, node = _statement("factory().x = rhs()\n")
        hook = _hook(node, field="x", receiver="factory()")
        with self.assertRaises(CompileError) as raised:
            lower_object_store_statement(
                node, hook, source_path=Path("sample.py"), source_text=source)
        self.assertEqual(raised.exception.diagnostic.code, "PZ2023")

        async_tree = ast.parse(
            "async def f(obj):\n"
            "    obj.x = await rhs()\n")
        function = async_tree.body[0]
        assert isinstance(function, ast.AsyncFunctionDef)
        await_store = function.body[0]
        assert isinstance(await_store, ast.Assign)
        await_hook = _hook(await_store, field="x")
        with self.assertRaises(CompileError) as raised:
            lower_object_store_statement(
                await_store, await_hook, source_path=Path("sample.py"),
                source_text="obj.x = await rhs()")
        self.assertEqual(raised.exception.diagnostic.code, "PZ2022")


if __name__ == "__main__":
    unittest.main()
