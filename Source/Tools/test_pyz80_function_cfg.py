#!/usr/bin/env python3
"""Whole-function CFG, exact fragment splice and blocker proofs."""

from __future__ import annotations

import ast
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.frontend import lower_active_object_store_ir
from pyz80_compiler.function_cfg import (
    FUNCTION_CFG_IR_FORMAT,
    FunctionCFGError,
    _validate_function,
    build_active_function_cfg_ir,
    function_cfg_report,
    lower_python_function_cfg,
    validate_active_function_cfg_ir,
)
from pyz80_compiler.mutation_hook_ir import build_mutation_hook_ir


ROOT = Path(__file__).resolve().parents[2]


class ActiveFunctionCFGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hooks = build_mutation_hook_ir(ROOT)
        cls.stores = lower_active_object_store_ir(
            ROOT, hook_plan=cls.hooks)
        cls.module = build_active_function_cfg_ir(
            ROOT, hook_plan=cls.hooks,
            object_store_module=cls.stores)

    @staticmethod
    def lower_sample(source: str):
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        return lower_python_function_cfg(
            node, class_name=None, source_path=Path("sample.py"),
            source_text=source)

    @staticmethod
    def expression_sources(function) -> dict[str, str]:
        return {program.program_id: program.source
                for program in function.expression_programs}

    @classmethod
    def block_sources(cls, function, block) -> list[str]:
        sources = cls.expression_sources(function)
        return [sources[item.arguments[0]]
                for item in block.instructions
                if item.op == "execute-expression-cfg"]

    @classmethod
    def block_with_source(cls, function, source: str):
        matches = [block for block in function.blocks
                   if source in cls.block_sources(function, block)]
        if len(matches) != 1:
            raise AssertionError(
                f"expected one block for {source!r}, got {len(matches)}")
        return matches[0]

    def test_active_inventory_and_ast_census_are_exact(self) -> None:
        module = self.module
        coverage = module.coverage
        self.assertEqual(module.format, FUNCTION_CFG_IR_FORMAT)
        self.assertEqual(len(module.functions), 148)
        self.assertEqual(coverage["runtime_mutation_site_count"], 364)
        self.assertEqual(coverage["spliced_store_fragment_count"], 364)
        self.assertEqual(coverage["cfg_block_count"], 1526)
        self.assertEqual(coverage["cfg_exception_edge_count"], 2)
        self.assertEqual(coverage["cfg_instruction_count"], 4862)
        self.assertEqual(coverage["function_expression_program_count"], 2845)
        self.assertEqual(coverage["function_expression_block_count"], 3228)
        folded_literals = sum(
            isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and
            isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
            for function in module.functions for program in function.expression_programs
            for node in ast.walk(ast.parse('('+program.source+'\n)', mode='eval')))
        self.assertEqual(folded_literals, 40)
        self.assertEqual(coverage["function_expression_instruction_count"] + folded_literals, 10417)
        self.assertEqual(coverage["body_statement_count"], 2444)
        self.assertEqual(coverage["statement_ast_kind_counts"], {
            "AnnAssign": 5,
            "Assign": 1495,
            "AugAssign": 108,
            "Break": 2,
            "Continue": 5,
            "Expr": 241,
            "For": 10,
            "If": 441,
            "Raise": 3,
            "Return": 131,
            "Try": 1,
            "While": 2,
        })

    def test_every_store_fragment_is_spliced_once_by_semantic_hash(self) -> None:
        references = [row for function in self.module.functions
                      for row in function.spliced_store_fragments]
        instructions = [item for function in self.module.functions
                        for block in function.blocks
                        for item in block.instructions
                        if item.op == "execute-object-store-fragment"]
        self.assertEqual(len(references), 364)
        self.assertEqual(len(instructions), 364)
        self.assertEqual(len({site_id for site_id, _ in references}), 364)
        expected = {item.site_id: item.semantic_sha256
                    for item in self.stores.fragments}
        self.assertEqual(dict(references), expected)

    def test_expression_subprograms_are_each_executed_once(self) -> None:
        expression_ops: Counter[str] = Counter()
        for function in self.module.functions:
            program_ids = {item.program_id
                           for item in function.expression_programs}
            executions = [item.arguments[0]
                          for block in function.blocks
                          for item in block.instructions
                          if item.op == "execute-expression-cfg"]
            self.assertEqual(Counter(executions), Counter(program_ids))
            self.assertFalse(any(
                item.op == "blocked-expression"
                for block in function.blocks for item in block.instructions))
            expression_ops.update(
                item.op for program in function.expression_programs
                for block in program.blocks for item in block.instructions)
        self.assertGreater(expression_ops["python-call"], 0)
        self.assertGreater(expression_ops["phi"], 0)
        self.assertEqual(expression_ops["build-dict"], 1)
        self.assertGreater(expression_ops["format-value"], 0)

    def test_active_function_cfg_is_complete_but_not_live(self) -> None:
        coverage = self.module.coverage
        self.assertEqual(coverage["unsupported_count"], 0)
        self.assertEqual(coverage["unsupported_code_counts"], {})
        self.assertEqual(coverage["unsupported_ast_kind_counts"], {})
        self.assertEqual(coverage["unsupported"], [])
        self.assertEqual(coverage["functions_without_blockers"], 148)
        self.assertEqual(coverage["functions_with_blockers"], 0)
        report = function_cfg_report(self.module)
        self.assertEqual(
            report["status"], "ACTIVE_FUNCTION_CFG_COMPLETE_LIVE_BLOCKED")
        self.assertFalse(report["live"])
        self.assertTrue(coverage["full_function_cfg_lowered"])
        self.assertFalse(coverage["current_c_backend_consumes_function_cfg"])
        self.assertEqual(len(report["live_blockers"]), 2)

    def test_public_checker_rejects_tampered_coverage(self) -> None:
        coverage = dict(self.module.coverage)
        coverage["spliced_store_fragment_count"] = 363
        tampered = replace(self.module, coverage=coverage)
        with self.assertRaises(FunctionCFGError) as raised:
            validate_active_function_cfg_ir(
                tampered, self.stores, self.hooks)
        self.assertEqual(raised.exception.code, "PZFC406")

    def test_generic_function_api_builds_loop_and_if_cfg(self) -> None:
        source = (
            "def accumulate(items):\n"
            "    total = 0\n"
            "    for item in items:\n"
            "        if item:\n"
            "            total += item\n"
            "    return total\n")
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        function = lower_python_function_cfg(
            node, class_name=None, source_path=Path("sample.py"),
            source_text=source)
        self.assertFalse(function.blockers)
        terminators = Counter(block.terminator.op for block in function.blocks)
        operations = Counter(item.op for block in function.blocks
                             for item in block.instructions)
        self.assertGreaterEqual(terminators["branch-truth"], 2)
        self.assertEqual(operations["python-get-iterator"], 1)
        self.assertEqual(operations["python-inplace-binary"], 1)

    def test_generic_try_except_else_finally_has_explicit_exception_flow(
            self) -> None:
        source = (
            "def decode(values):\n"
            "    try:\n"
            "        value = values[0]\n"
            "    except KeyError as error:\n"
            "        raise ValueError('bad') from error\n"
            "    else:\n"
            "        return value\n"
            "    finally:\n"
            "        values.clear()\n")
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        function = lower_python_function_cfg(
            node, class_name=None, source_path=Path("sample.py"),
            source_text=source)
        self.assertFalse(function.blockers)
        blocks = {block.name: block for block in function.blocks}
        self.assertGreaterEqual(sum(
            block.exception_target is not None
            for block in function.blocks), 4)
        self.assertTrue(all(
            block.exception_target in blocks
            for block in function.blocks
            if block.exception_target is not None))
        operations = Counter(
            item.op for block in function.blocks
            for item in block.instructions)
        terminators = Counter(block.terminator.op for block in function.blocks)
        self.assertEqual(operations["exception-matches"], 1)
        self.assertEqual(operations["begin-except-handler"], 1)
        self.assertGreaterEqual(operations["end-except-handler"], 1)
        self.assertGreaterEqual(operations["clear-except-target"], 1)
        self.assertGreaterEqual(operations["capture-current-exception"], 2)
        self.assertGreaterEqual(terminators["raise-saved"], 1)
        self.assertGreaterEqual(terminators["return"], 1)

    def test_raise_forms_preserve_bare_explicit_and_explicit_cause(
            self) -> None:
        source = (
            "def raise_forms(exc, cause):\n"
            "    try:\n"
            "        raise exc from cause\n"
            "    except LookupError as caught:\n"
            "        if cause:\n"
            "            raise\n"
            "        raise RuntimeError('replacement') from None\n")
        function = self.lower_sample(source)
        self.assertFalse(function.blockers)
        by_line = {block.terminator.span.line: block
                   for block in function.blocks
                   if block.terminator.span.line in {3, 6, 7}}
        self.assertEqual(by_line[3].terminator.op, "raise-explicit-from")
        self.assertEqual(len(by_line[3].terminator.arguments), 2)
        self.assertEqual(
            self.block_sources(function, by_line[3]), ["exc", "cause"])
        self.assertEqual(by_line[6].terminator.op, "raise-current")
        self.assertEqual(by_line[6].terminator.arguments, ())
        self.assertEqual(by_line[7].terminator.op, "raise-explicit-from")
        self.assertEqual(
            self.block_sources(function, by_line[7]),
            ["RuntimeError('replacement')", "None"])
        self.assertTrue(all(by_line[line].exception_target is not None
                            for line in (3, 6, 7)))
        blocks = {block.name: block for block in function.blocks}
        for line in (6, 7):
            handler_cleanup = blocks[by_line[line].exception_target]
            self.assertIn(
                "clear-except-target",
                [item.op for item in handler_cleanup.instructions])
        cleanup = [item for block in function.blocks
                   for item in block.instructions
                   if item.op == "clear-except-target"]
        self.assertTrue(cleanup)
        self.assertTrue(all(item.arguments == ("caught",)
                            for item in cleanup))
        self.assertTrue(all(dict(item.attributes).get(
            "set_none_then_delete") is True for item in cleanup))

    def test_explicit_cause_raised_in_finally_unwinds_outer_finally(
            self) -> None:
        source = (
            "def raise_in_finally(exc, cause):\n"
            "    try:\n"
            "        try:\n"
            "            return value()\n"
            "        finally:\n"
            "            raise exc from cause\n"
            "    finally:\n"
            "        outer_cleanup()\n")
        function = self.lower_sample(source)
        blocks = {block.name: block for block in function.blocks}
        raised = [block for block in function.blocks
                  if block.terminator.span.line == 6 and
                  block.terminator.op == "raise-explicit-from"]
        self.assertEqual(len(raised), 2)
        for block in raised:
            self.assertEqual(
                self.block_sources(function, block), ["exc", "cause"])
            self.assertIsNotNone(block.exception_target)
            outer = blocks[block.exception_target]
            self.assertIn("outer_cleanup()", self.block_sources(
                function, outer))
            self.assertEqual(outer.terminator.op, "raise-saved")
        self.assertFalse(any(
            block.terminator.op == "return" and
            block.terminator.span.line == 4
            for block in function.blocks))

    def test_bare_except_has_no_fictitious_target_cleanup(self) -> None:
        source = (
            "def bare_handler():\n"
            "    try:\n"
            "        danger()\n"
            "    except:\n"
            "        return 1\n")
        function = self.lower_sample(source)
        operations = Counter(item.op for block in function.blocks
                             for item in block.instructions)
        self.assertGreaterEqual(operations["end-except-handler"], 2)
        self.assertEqual(operations["clear-except-target"], 0)

    def test_named_handler_cleanup_precedes_continue_break_and_return(
            self) -> None:
        source = (
            "def handler_controls(items):\n"
            "    for item in items:\n"
            "        try:\n"
            "            danger(item)\n"
            "        except LookupError as error:\n"
            "            if item == 0:\n"
            "                continue\n"
            "            if item == 1:\n"
            "                break\n"
            "            return error\n"
            "    return None\n")
        function = self.lower_sample(source)
        blocks = {block.name: block for block in function.blocks}
        cleanup_entries = []
        for line in (7, 9, 10):
            candidates = [block for block in function.blocks
                          if block.terminator.span.line == line and
                          len(block.terminator.targets) == 1]
            source_block = next(
                block for block in candidates
                if any(item.op == "clear-except-target"
                       for item in blocks[
                           block.terminator.targets[0]].instructions))
            cleanup_entries.append(blocks[
                source_block.terminator.targets[0]])
        for cleanup in cleanup_entries:
            cleanup_ops = [item.op for item in cleanup.instructions]
            self.assertEqual(cleanup_ops[:2], [
                "end-except-handler", "clear-except-target"])
            clear = cleanup.instructions[1]
            self.assertEqual(clear.arguments, ("error",))
        self.assertTrue(cleanup_entries[0].terminator.targets[0].startswith(
            "for_header_"))
        self.assertTrue(cleanup_entries[1].terminator.targets[0].startswith(
            "for_merge_"))
        self.assertEqual(cleanup_entries[2].terminator.op, "return")

    def test_loop_control_unwinds_only_finalizers_whose_scope_is_left(
            self) -> None:
        inner_loop_source = (
            "def inner_loop(flag):\n"
            "    try:\n"
            "        while flag:\n"
            "            if flag > 1:\n"
            "                continue\n"
            "            break\n"
            "        after_loop()\n"
            "    finally:\n"
            "        cleanup()\n")
        inner = self.lower_sample(inner_loop_source)
        inner_by_line = {block.terminator.span.line: block
                         for block in inner.blocks
                         if block.terminator.span.line in {5, 6}}
        self.assertTrue(inner_by_line[5].terminator.targets[0].startswith(
            "while_header_"))
        self.assertTrue(inner_by_line[6].terminator.targets[0].startswith(
            "while_merge_"))
        inner_blocks = {block.name: block for block in inner.blocks}
        self.assertNotIn(
            "cleanup()", self.block_sources(
                inner, inner_blocks[inner_by_line[5].terminator.targets[0]]))
        self.assertNotIn(
            "cleanup()", self.block_sources(
                inner, inner_blocks[inner_by_line[6].terminator.targets[0]]))

        outer_loop_source = (
            "def outer_loop(flag):\n"
            "    while flag:\n"
            "        try:\n"
            "            if flag > 1:\n"
            "                continue\n"
            "            break\n"
            "        finally:\n"
            "            cleanup()\n")
        outer = self.lower_sample(outer_loop_source)
        outer_blocks = {block.name: block for block in outer.blocks}
        outer_by_line = {}
        for line in (5, 6):
            candidates = [block for block in outer.blocks
                          if block.terminator.span.line == line and
                          len(block.terminator.targets) == 1]
            outer_by_line[line] = next(
                block for block in candidates
                if "cleanup()" in self.block_sources(
                    outer, outer_blocks[block.terminator.targets[0]]))
        continue_cleanup = outer_blocks[
            outer_by_line[5].terminator.targets[0]]
        break_cleanup = outer_blocks[
            outer_by_line[6].terminator.targets[0]]
        self.assertIn("cleanup()", self.block_sources(
            outer, continue_cleanup))
        self.assertIn("cleanup()", self.block_sources(
            outer, break_cleanup))
        self.assertTrue(continue_cleanup.terminator.targets[0].startswith(
            "while_header_"))
        self.assertTrue(break_cleanup.terminator.targets[0].startswith(
            "while_merge_"))

    def test_return_crosses_nested_finally_once_in_lexical_order(self) -> None:
        source = (
            "def nested_return():\n"
            "    try:\n"
            "        try:\n"
            "            return value()\n"
            "        finally:\n"
            "            inner_cleanup()\n"
            "    finally:\n"
            "        outer_cleanup()\n")
        function = self.lower_sample(source)
        blocks = {block.name: block for block in function.blocks}
        block = self.block_with_source(function, "value()")
        seen: set[str] = set()
        sources: list[str] = []
        while True:
            self.assertNotIn(block.name, seen)
            seen.add(block.name)
            sources.extend(self.block_sources(function, block))
            if not block.terminator.targets:
                break
            self.assertEqual(len(block.terminator.targets), 1)
            block = blocks[block.terminator.targets[0]]
        self.assertEqual(
            sources, ["value()", "inner_cleanup()", "outer_cleanup()"])
        self.assertEqual(block.terminator.op, "return")
        self.assertEqual(len(block.terminator.arguments), 1)

    def test_nested_normal_exit_does_not_run_outer_finally_early(self) -> None:
        source = (
            "def nested_normal():\n"
            "    try:\n"
            "        try:\n"
            "            work()\n"
            "        finally:\n"
            "            inner_cleanup()\n"
            "        after_inner()\n"
            "    finally:\n"
            "        outer_cleanup()\n")
        function = self.lower_sample(source)
        blocks = {block.name: block for block in function.blocks}
        block = self.block_with_source(function, "work()")
        seen: set[str] = set()
        sources: list[str] = []
        while block.terminator.targets:
            self.assertNotIn(block.name, seen)
            seen.add(block.name)
            sources.extend(self.block_sources(function, block))
            self.assertEqual(len(block.terminator.targets), 1)
            block = blocks[block.terminator.targets[0]]
        sources.extend(self.block_sources(function, block))
        self.assertEqual(sources, [
            "work()", "inner_cleanup()", "after_inner()",
            "outer_cleanup()",
        ])

    def test_try_else_is_normal_only_and_handlers_are_ordered(self) -> None:
        source = (
            "def ordered():\n"
            "    try:\n"
            "        body()\n"
            "    except FirstError:\n"
            "        first_handler()\n"
            "    except SecondError as second:\n"
            "        second_handler()\n"
            "    except:\n"
            "        fallback_handler()\n"
            "    else:\n"
            "        succeeded()\n"
            "    finally:\n"
            "        finished()\n")
        function = self.lower_sample(source)
        blocks = {block.name: block for block in function.blocks}
        body = self.block_with_source(function, "body()")
        normal = blocks[body.terminator.targets[0]]
        self.assertIn("succeeded()", self.block_sources(function, normal))
        dispatch = blocks[body.exception_target]
        self.assertNotIn("succeeded()", self.block_sources(
            function, dispatch))

        matches = []
        for block in function.blocks:
            for item in block.instructions:
                if item.op == "exception-matches":
                    matches.append((dict(item.attributes)["handler_index"],
                                    block))
        matches.sort(key=lambda row: row[0])
        self.assertEqual([index for index, _ in matches], [0, 1])
        self.assertEqual(
            matches[0][1].terminator.targets[1], matches[1][1].name)
        fallback_search = blocks[matches[1][1].terminator.targets[1]]
        fallback = blocks[fallback_search.terminator.targets[0]]
        self.assertIn("fallback_handler()", self.block_sources(
            function, fallback))

        first = blocks[matches[0][1].terminator.targets[0]]
        seen: set[str] = set()
        first_path_sources: list[str] = []
        while True:
            self.assertNotIn(first.name, seen)
            seen.add(first.name)
            first_path_sources.extend(self.block_sources(function, first))
            if not first.terminator.targets:
                break
            self.assertEqual(len(first.terminator.targets), 1)
            first = blocks[first.terminator.targets[0]]
        self.assertIn("first_handler()", first_path_sources)
        self.assertIn("finished()", first_path_sources)
        self.assertNotIn("succeeded()", first_path_sources)

    def test_unmatched_inner_handler_runs_inner_finally_then_outer_handler(
            self) -> None:
        source = (
            "def nested_exception():\n"
            "    try:\n"
            "        try:\n"
            "            danger()\n"
            "        except KeyError:\n"
            "            inner_handler()\n"
            "        finally:\n"
            "            inner_finally()\n"
            "    except ValueError:\n"
            "        outer_handler()\n"
            "    finally:\n"
            "        outer_finally()\n")
        function = self.lower_sample(source)
        blocks = {block.name: block for block in function.blocks}
        danger = self.block_with_source(function, "danger()")
        inner_dispatch = blocks[danger.exception_target]
        inner_unmatched = blocks[inner_dispatch.terminator.targets[1]]
        self.assertEqual(inner_unmatched.terminator.op, "raise-current")
        inner_finally = blocks[inner_unmatched.exception_target]
        self.assertIn("inner_finally()", self.block_sources(
            function, inner_finally))
        self.assertEqual(inner_finally.terminator.op, "raise-saved")
        outer_dispatch = blocks[inner_finally.exception_target]
        self.assertIn("ValueError", self.block_sources(
            function, outer_dispatch))
        outer_handler = blocks[outer_dispatch.terminator.targets[0]]
        self.assertIn("outer_handler()", self.block_sources(
            function, outer_handler))

        block = outer_handler
        seen: set[str] = set()
        handler_path: list[str] = []
        while True:
            self.assertNotIn(block.name, seen)
            seen.add(block.name)
            handler_path.extend(self.block_sources(function, block))
            if not block.terminator.targets:
                break
            self.assertEqual(len(block.terminator.targets), 1)
            block = blocks[block.terminator.targets[0]]
        self.assertIn("outer_finally()", handler_path)

class TargetNeutralStatementLoweringTests(unittest.TestCase):
    @staticmethod
    def lower_sample(source: str):
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        return lower_python_function_cfg(
            node, class_name=None, source_path=Path("sample.py"),
            source_text=source)

    @staticmethod
    def expression_sources(function) -> dict[str, str]:
        return {program.program_id: program.source
                for program in function.expression_programs}

    @classmethod
    def block_sources(cls, function, block) -> list[str]:
        sources = cls.expression_sources(function)
        return [sources[item.arguments[0]]
                for item in block.instructions
                if item.op == "execute-expression-cfg"]

    @staticmethod
    def expression_instructions(function):
        return sorted(
            (item for program in function.expression_programs
             for block in program.blocks for item in block.instructions),
            key=lambda item: item.sequence)

    def test_delete_targets_preserve_left_to_right_single_evaluation(
            self) -> None:
        source = (
            "def delete_targets():\n"
            "    del first, object_factory().field, "
            "sequence_factory()[index_factory()], "
            "(second, nested_factory().leaf), "
            "table_factory()[lower():upper():step()]\n")
        function = self.lower_sample(source)
        self.assertFalse(function.blockers)
        expression_sources = self.expression_sources(function)
        instructions = sorted(
            (item for block in function.blocks
             for item in block.instructions),
            key=lambda item: item.sequence)
        trace = [
            (f"eval:{expression_sources[item.arguments[0]]}"
             if item.op == "execute-expression-cfg" else item.op)
            for item in instructions]
        self.assertEqual(trace, [
            "delete-name",
            "eval:object_factory()", "delete-attribute",
            "eval:sequence_factory()", "eval:index_factory()",
            "delete-subscript",
            "delete-name", "eval:nested_factory()", "delete-attribute",
            "eval:table_factory()", "eval:lower()", "eval:upper()",
            "eval:step()", "build-slice", "delete-subscript",
        ])
        self.assertEqual(instructions[0].arguments, ("first",))
        self.assertEqual(
            next(item for item in instructions
                 if item.op == "delete-attribute").arguments[1],
            "field")

    def test_assert_message_exists_only_on_failure_cfg_edge(self) -> None:
        source = (
            "def checked(value):\n"
            "    assert probe(value), message()\n"
            "    after_success()\n")
        function = self.lower_sample(source)
        self.assertFalse(function.blockers)
        blocks = {block.name: block for block in function.blocks}
        branch = next(block for block in function.blocks
                      if block.terminator.op == "branch-truth")
        passed = blocks[branch.terminator.targets[0]]
        failed = blocks[branch.terminator.targets[1]]
        self.assertEqual(
            self.block_sources(function, branch), ["probe(value)"])
        self.assertEqual(
            self.block_sources(function, passed), ["after_success()"])
        self.assertEqual(
            self.block_sources(function, failed), ["message()"])
        self.assertEqual(failed.terminator.op, "raise-explicit")
        constructed = [item for item in failed.instructions
                       if item.op == "construct-assertion-error"]
        self.assertEqual(len(constructed), 1)
        self.assertEqual(
            failed.terminator.arguments, (constructed[0].destination,))

    def test_imports_have_explicit_calls_member_resolution_and_bindings(
            self) -> None:
        source = (
            "def imports():\n"
            "    import alpha.beta, gamma.delta as gd\n"
            "    from .relative import value as renamed, other\n"
            "    from starry import *\n")
        function = self.lower_sample(source)
        self.assertFalse(function.blockers)
        instructions = sorted(
            (item for block in function.blocks
             for item in block.instructions),
            key=lambda item: item.sequence)
        module_ops = [item for item in instructions
                      if item.op == "python-import-module"]
        self.assertEqual([item.arguments for item in module_ops], [
            ("alpha.beta", 0, (), "root-package"),
            ("gamma.delta", 0, (), "root-package"),
            ("relative", 1, ("value", "other"), "fromlist-module"),
            ("starry", 0, ("*",), "fromlist-module"),
        ])
        stores = [item.arguments[0] for item in instructions
                  if item.op == "store-name"]
        self.assertEqual(stores, ["alpha", "gd", "renamed", "other"])
        self.assertEqual(sum(item.op == "python-import-from"
                             for item in instructions), 3)
        self.assertEqual(sum(item.op == "python-import-star"
                             for item in instructions), 1)

    def test_nested_function_definition_orders_decorators_defaults_and_cells(
            self) -> None:
        source = (
            "from __future__ import annotations\n"
            "def outer(cell):\n"
            "    @first(mark('decorator-1'))\n"
            "    @second(mark('decorator-2'))\n"
            "    def inner(a: Input = mark('default-a'), "
            "b=mark('default-b'), *, c=mark('default-c'), "
            "d: Kind = mark('default-d')) -> Result:\n"
            "        return cell, a, b, c, d\n"
            "    return inner\n")
        tree = ast.parse(source)
        node = tree.body[1]
        assert isinstance(node, ast.FunctionDef)
        function = lower_python_function_cfg(
            node, class_name=None, source_path=Path("sample.py"),
            source_text=source)
        self.assertFalse(function.blockers)
        sources = self.expression_sources(function)
        instructions = sorted(
            (item for block in function.blocks
             for item in block.instructions),
            key=lambda item: item.sequence)
        expression_items = [item for item in instructions
                            if item.op == "execute-expression-cfg"]
        self.assertEqual(
            [sources[item.arguments[0]] for item in expression_items[:6]],
            [
                "first(mark('decorator-1'))",
                "second(mark('decorator-2'))",
                "mark('default-a')", "mark('default-b')",
                "mark('default-c')", "mark('default-d')",
            ])
        make = next(item for item in instructions
                    if item.op == "make-function")
        self.assertEqual(make.arguments[0], "inner@5")
        self.assertEqual(make.arguments[2], "function")
        self.assertEqual(
            [name for name, _value in make.arguments[4]], ["a", "b"])
        self.assertEqual(
            [name for name, _value in make.arguments[5]], ["c", "d"])
        self.assertEqual(
            [name for name, _cell in make.arguments[6]], ["cell"])
        self.assertEqual(
            [(name, text) for name, _digest, text in make.arguments[7]],
            [("a", "Input"), ("d", "Kind"), ("return", "Result")])
        applies = [item for item in instructions
                   if item.op == "python-apply-decorator"]
        self.assertEqual(len(applies), 2)
        self.assertEqual(
            applies[0].arguments,
            (expression_items[1].destination, make.destination))
        self.assertEqual(
            applies[1].arguments,
            (expression_items[0].destination, applies[0].destination))
        binding = next(item for item in instructions
                       if item.op == "store-name" and
                       item.arguments[0] == "inner")
        self.assertEqual(binding.arguments[1], applies[1].destination)

    def test_new_statement_instruction_validator_is_fail_closed(self) -> None:
        function = self.lower_sample(
            "def remove(obj):\n    del obj.field\n")
        block_index, instruction_index = next(
            (block_index, instruction_index)
            for block_index, block in enumerate(function.blocks)
            for instruction_index, item in enumerate(block.instructions)
            if item.op == "delete-attribute")
        block = function.blocks[block_index]
        instructions = list(block.instructions)
        instructions[instruction_index] = replace(
            instructions[instruction_index],
            arguments=("not-an-ssa", "field"))
        blocks = list(function.blocks)
        blocks[block_index] = replace(
            block, instructions=tuple(instructions))
        with self.assertRaises(FunctionCFGError) as raised:
            _validate_function(replace(function, blocks=tuple(blocks)))
        self.assertEqual(raised.exception.code, "PZFC316")

    def test_lambda_defaults_cells_and_body_are_definition_time_exact(
            self) -> None:
        source = (
            "def outer(cell):\n"
            "    return consume(lambda a=mark('a'), b=mark('b'), "
            "*, c=mark('c'): (a, b, c, cell))\n")
        function = self.lower_sample(source)
        self.assertFalse(function.blockers)
        instructions = self.expression_instructions(function)
        make = next(item for item in instructions
                    if item.op == "make-lambda-function")
        positional = make.arguments[1]
        keyword = make.arguments[2]
        closure = make.arguments[3]
        self.assertEqual([name for name, _value in positional], ["a", "b"])
        self.assertEqual([name for name, _value in keyword], ["c"])
        self.assertEqual([name for name, _cell in closure], ["cell"])
        sequence_by_result = {item.destination: item.sequence
                              for item in instructions}
        default_sequences = [sequence_by_result[value]
                             for _name, value in (*positional, *keyword)]
        self.assertEqual(default_sequences, sorted(default_sequences))
        self.assertTrue(all(value < make.sequence
                            for value in default_sequences))
        attributes = dict(make.attributes)
        self.assertEqual(attributes["body"]["source"], "(a, b, c, cell)")
        self.assertEqual(attributes["body_execution"], "deferred-until-call")
        self.assertEqual(attributes["closure_binding"],
                         "cell-identity-by-name")
        self.assertEqual(attributes["function_name"], "<lambda>")
        self.assertEqual(attributes["body_kind"], "ordinary")

    def test_lambda_inside_boolop_exists_only_on_short_circuit_edge(self) -> None:
        function = self.lower_sample(
            "def choose(callback, cell):\n"
            "    return callback or (lambda _name: cell)\n")
        self.assertFalse(function.blockers)
        program = function.expression_programs[0]
        blocks = {block.name: block for block in program.blocks}
        entry = blocks[program.entry]
        self.assertEqual(entry.terminator.op, "branch-truth")
        make_blocks = [block for block in program.blocks
                       if any(item.op == "make-lambda-function"
                              for item in block.instructions)]
        self.assertEqual(len(make_blocks), 1)
        self.assertEqual(make_blocks[0].name, entry.terminator.targets[1])
        phi = next(item for block in program.blocks
                   for item in block.instructions if item.op == "phi")
        self.assertTrue(dict(phi.attributes)["short_circuit"])

    def test_eager_comprehension_plan_preserves_scope_loop_filter_and_target(
            self) -> None:
        source = (
            "def build(cell):\n"
            "    return [emit(x, tail, cell) for x, *tail in outer() "
            "if keep(x) for y in inner(x) if accept(y)]\n")
        function = self.lower_sample(source)
        self.assertFalse(function.blockers)
        instructions = self.expression_instructions(function)
        run = next(item for item in instructions
                   if item.op == "run-eager-comprehension")
        iterator = next(item for item in instructions
                        if item.op == "python-get-iterator-immediate")
        self.assertLess(iterator.sequence, run.sequence)
        plan = dict(run.attributes)["plan"]
        self.assertEqual(plan["kind"], "list")
        self.assertEqual(plan["scope"], "separate-implicit-function-scope")
        self.assertEqual(plan["local_names"], ("tail", "x", "y"))
        self.assertEqual(plan["free_cell_names"], ("cell",))
        self.assertEqual(plan["scope_exit"],
                         "target-and-temporary-names-never-leak")
        self.assertEqual(
            [item["iterator"]["mode"] for item in plan["generators"]],
            ["provided-leftmost-iterator",
             "evaluate-then-get-iterator-in-scope"])
        self.assertEqual(
            [item["source"] for item in plan["generators"][0]["filters"]],
            ["keep(x)"])
        self.assertEqual(
            [item["source"] for item in plan["generators"][1]["filters"]],
            ["accept(y)"])
        target = plan["generators"][0]["target"]
        self.assertEqual(target["kind"], "tuple-unpack")
        self.assertEqual(target["unpack_protocol"], ("UNPACK_EX", 1, 0))
        self.assertEqual(plan["production"]["operation"], "list-append")
        self.assertEqual(plan["production"]["element"]["source"],
                         "emit(x, tail, cell)")
        self.assertIn(
            "next-target-unpack-filter-inner-iter-production-errors-propagate",
            plan["exception_protocol"])

    def test_list_set_and_dict_comprehensions_have_distinct_exact_production(
            self) -> None:
        samples = (
            ("[value(x) for x in source()]", "py-list", "list-append"),
            ("{value(x) for x in source()}", "py-set", "set-add"),
            ("{key(x): value(x) for x in source()}",
             "py-dict", "mapping-setitem"),
        )
        for expression, result_kind, operation in samples:
            with self.subTest(expression=expression):
                function = self.lower_sample(
                    f"def build():\n    return {expression}\n")
                self.assertFalse(function.blockers)
                run = next(item for item in self.expression_instructions(
                    function) if item.op == "run-eager-comprehension")
                self.assertEqual(run.value_kind, result_kind)
                production = dict(run.attributes)["plan"]["production"]
                self.assertEqual(production["operation"], operation)
                if operation == "mapping-setitem":
                    self.assertEqual(production["evaluation_order"],
                                     "key-then-value-then-setitem")
                    self.assertEqual(production["key"]["source"], "key(x)")
                    self.assertEqual(production["value"]["source"],
                                     "value(x)")

    def test_comprehension_target_does_not_leak_into_parent_scope(self) -> None:
        function = self.lower_sample(
            "def preserve(values, x):\n"
            "    result = [x for x in values]\n"
            "    return result, x\n")
        self.assertFalse(function.blockers)
        run = next(item for item in self.expression_instructions(function)
                   if item.op == "run-eager-comprehension")
        plan = dict(run.attributes)["plan"]
        self.assertEqual(plan["local_names"], ("x",))
        parent_x_stores = [item for block in function.blocks
                           for item in block.instructions
                           if item.op == "store-name" and
                           item.arguments[0] == "x"]
        self.assertEqual(parent_x_stores, [])

    def test_generator_expression_is_lazy_resumable_and_stopiteration_exact(
            self) -> None:
        function = self.lower_sample(
            "def stream(source, cell):\n"
            "    return (produce(x, cell) for x in outer(source) if keep(x))\n")
        self.assertFalse(function.blockers)
        instructions = self.expression_instructions(function)
        generator = next(item for item in instructions
                         if item.op == "make-generator-expression")
        iterator = next(item for item in instructions
                        if item.op == "python-get-iterator-immediate")
        self.assertLess(iterator.sequence, generator.sequence)
        loaded_names = [item.arguments[0] for item in instructions
                        if item.op == "load-name"]
        self.assertIn("outer", loaded_names)
        self.assertNotIn("produce", loaded_names)
        self.assertNotIn("keep", loaded_names)
        attributes = dict(generator.attributes)
        self.assertTrue(
            attributes["creation_is_lazy_except_leftmost_iterator"])
        self.assertEqual(attributes["body_execution"],
                         "lazy-on-next-send-throw-close")
        plan = attributes["plan"]
        self.assertEqual(plan["production"]["operation"], "yield")
        self.assertEqual(plan["free_cell_names"], ("cell",))
        resumable = plan["resumable_protocol"]
        self.assertIn("after-yield", resumable["yield_resume_point"])
        self.assertIn("StopIteration", resumable["completion"])
        self.assertIn("RuntimeError", resumable["pep479"])
        self.assertIn("GeneratorExit", resumable["close"])
        self.assertIn("inject", resumable["throw"])

    def test_boolop_and_unary_unlock_only_through_lazy_child_semantics(
            self) -> None:
        function = self.lower_sample(
            "def test(guard, values):\n"
            "    return guard and not any(value for value in values)\n")
        self.assertFalse(function.blockers)
        program = function.expression_programs[0]
        operations = [item.op for block in program.blocks
                      for item in block.instructions]
        self.assertIn("make-generator-expression", operations)
        self.assertIn("python-unary", operations)
        self.assertIn("phi", operations)
        self.assertGreaterEqual(sum(
            block.terminator.op == "branch-truth"
            for block in program.blocks), 1)

    def test_extended_expression_validator_rejects_resumption_tamper(
            self) -> None:
        function = self.lower_sample(
            "def stream(values):\n"
            "    return (value for value in values)\n")
        program = function.expression_programs[0]
        block_index, instruction_index = next(
            (block_index, instruction_index)
            for block_index, block in enumerate(program.blocks)
            for instruction_index, item in enumerate(block.instructions)
            if item.op == "make-generator-expression")
        block = program.blocks[block_index]
        instructions = list(block.instructions)
        item = instructions[instruction_index]
        attributes = dict(item.attributes)
        plan = dict(attributes["plan"])
        resumable = dict(plan["resumable_protocol"])
        resumable["completion"] = "return-None"
        plan["resumable_protocol"] = resumable
        attributes["plan"] = plan
        instructions[instruction_index] = replace(
            item, attributes=tuple(sorted(attributes.items())))
        blocks = list(program.blocks)
        blocks[block_index] = replace(
            block, instructions=tuple(instructions))
        programs = list(function.expression_programs)
        programs[0] = replace(program, blocks=tuple(blocks))
        with self.assertRaises(FunctionCFGError) as raised:
            _validate_function(replace(
                function, expression_programs=tuple(programs)))
        self.assertEqual(raised.exception.code, "PZFC318")

    def test_unproved_comprehension_walrus_stays_blocked(self) -> None:
        walrus = self.lower_sample(
            "def collect(values):\n"
            "    return [value for value in values if (seen := value)]\n")
        self.assertEqual(
            [(item.code, item.node_kind) for item in walrus.blockers],
            [("PZ2030", "ListComp")])
        self.assertIn("outward binding", walrus.blockers[0].message)

    def test_active_tsfm_frames_has_one_exact_bounded_resume_state(
            self) -> None:
        path = ROOT / "Source/Python/rtype_port/tsfm.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path), type_comments=True)
        owner = next(item for item in tree.body
                     if isinstance(item, ast.ClassDef) and
                     item.name == "TsfmEmulator")
        node = next(item for item in owner.body
                    if isinstance(item, ast.FunctionDef) and
                    item.name == "frames")
        function = lower_python_function_cfg(
            node, class_name=owner.name, source_path=path,
            source_text=source)
        self.assertFalse(function.blockers)
        signature = function.signature
        self.assertEqual(signature["execution_kind"], "generator-frame")
        self.assertEqual(
            signature["invocation"],
            "return-generator-object-without-running-body")
        self.assertIn("StopIteration(return-value)", signature["completion"])
        frame = signature["frame"]
        self.assertEqual(frame["local_slots"], ("_", "count", "self"))
        self.assertEqual(frame["max_operand_stack_slots"], 0)
        self.assertEqual(len(frame["states"]), 1)
        state = frame["states"][0]
        self.assertEqual(state["state"], 1)
        self.assertEqual(state["suspension_kind"], "yield")
        self.assertEqual(state["line"], 125)
        self.assertEqual(state["loop_stack"], (
            ("for_merge_0004", "for_header_0001"),))

        iterator = next(
            item for block in function.blocks for item in block.instructions
            if item.op == "python-get-iterator")
        self.assertEqual(state["spill_slots"], (iterator.destination,))
        self.assertEqual(state["bounded_slot_count"], 7)
        suspension = next(block for block in function.blocks
                          if block.terminator.op == "suspend-yield")
        sources = self.expression_sources(function)
        evaluated = [sources[item.arguments[0]]
                     for item in suspension.instructions
                     if item.op == "execute-expression-cfg"]
        self.assertEqual(evaluated, ["self.step()"])
        self.assertEqual(
            suspension.instructions[-1].op, "generator-save-frame")
        resume = next(block for block in function.blocks
                      if block.name == state["resume_target"])
        self.assertEqual(
            [item.op for item in resume.instructions],
            ["generator-restore-frame", "generator-resume-value"])
        self.assertEqual(resume.terminator.op, "jump")
        self.assertEqual(resume.terminator.targets, ("for_header_0001",))

    def test_yield_send_assignment_and_return_raise_stopiteration_value(
            self) -> None:
        function = self.lower_sample(
            "def exchange():\n"
            "    received = yield produce()\n"
            "    return received\n")
        self.assertFalse(function.blockers)
        state = function.signature["frame"]["states"][0]
        resume = next(block for block in function.blocks
                      if block.name == state["resume_target"])
        restored, resumed, stored = resume.instructions[:3]
        self.assertEqual(restored.op, "generator-restore-frame")
        self.assertEqual(resumed.op, "generator-resume-value")
        self.assertEqual(stored.op, "store-name")
        self.assertEqual(stored.arguments, ("received", resumed.destination))
        protocol = dict(resumed.attributes)
        self.assertEqual(protocol["next"], "result-is-None")
        self.assertEqual(protocol["send"], "result-is-sent-value")
        self.assertIn("injected-exception", protocol["throw"])
        returned = next(block for block in function.blocks
                        if block.terminator.op == "generator-return")
        self.assertEqual(len(returned.terminator.arguments), 1)
        self.assertIn("StopIteration(return-value)",
                      function.signature["completion"])

    def test_bare_yield_suspends_none_and_fallthrough_returns_none(
            self) -> None:
        function = self.lower_sample(
            "def pulse():\n"
            "    yield\n")
        self.assertFalse(function.blockers)
        suspension = next(block for block in function.blocks
                          if block.terminator.op == "suspend-yield")
        yielded = suspension.terminator.arguments[0]
        constant = next(item for item in suspension.instructions
                        if item.destination == yielded)
        self.assertEqual(constant.op, "constant")
        self.assertEqual(constant.arguments, (None,))
        completed = next(block for block in function.blocks
                         if block.terminator.op == "generator-return")
        self.assertEqual(completed.terminator.arguments, ())

    def test_throw_and_close_resume_at_yield_site_through_finally(
            self) -> None:
        function = self.lower_sample(
            "def guarded():\n"
            "    try:\n"
            "        yield produce()\n"
            "    finally:\n"
            "        cleanup()\n")
        self.assertFalse(function.blockers)
        state = function.signature["frame"]["states"][0]
        self.assertEqual(state["finalizer_stack"], ("finally",))
        self.assertIsNotNone(state["exception_target"])
        resume = next(block for block in function.blocks
                      if block.name == state["resume_target"])
        self.assertEqual(resume.exception_target,
                         state["exception_target"])
        resumed = next(item for item in resume.instructions
                       if item.op == "generator-resume-value")
        protocol = dict(resumed.attributes)
        self.assertEqual(
            protocol["throw"],
            "raise-injected-exception-at-yield-site")
        self.assertEqual(
            protocol["close"], "raise-GeneratorExit-at-yield-site")
        exceptional_finally = next(
            block for block in function.blocks
            if block.name == state["exception_target"])
        self.assertEqual(
            self.block_sources(function, exceptional_finally), ["cleanup()"])
        self.assertEqual(
            exceptional_finally.terminator.op, "raise-saved")

    def test_yield_from_is_resumable_and_returns_stopiteration_value(
            self) -> None:
        function = self.lower_sample(
            "def delegate(items):\n"
            "    result = yield from items\n"
            "    return result\n")
        self.assertFalse(function.blockers)
        state = function.signature["frame"]["states"][0]
        self.assertEqual(state["suspension_kind"], "yield-from")
        self.assertEqual(state["operand_stack_slots"], 1)
        suspension = next(block for block in function.blocks
                          if block.terminator.op == "suspend-yield-from")
        delegate = suspension.terminator.arguments[0]
        self.assertIn(delegate, state["spill_slots"])
        protocol = suspension.terminator.arguments[2]
        self.assertEqual(protocol["initial"], "next(delegate)")
        self.assertEqual(protocol["resume-value"], "delegate.send(value)")
        self.assertIn("delegate.throw", protocol["throw-other"])
        self.assertIn("GeneratorExit", protocol["throw-generator-exit"])
        self.assertEqual(
            protocol["stop-iteration"],
            "complete-with-StopIteration.value")
        resume = next(block for block in function.blocks
                      if block.name == state["resume_target"])
        result = next(item for item in resume.instructions
                      if item.op == "generator-yield-from-result")
        stored = next(item for item in resume.instructions
                      if item.op == "store-name")
        self.assertEqual(stored.arguments, ("result", result.destination))
        self.assertEqual(dict(result.attributes)["result"],
                         "StopIteration.value")

    def test_generator_validator_rejects_protocol_and_frame_tamper(
            self) -> None:
        function = self.lower_sample(
            "def delegate(items):\n"
            "    result = yield from items\n"
            "    return result\n")
        block_index = next(
            index for index, block in enumerate(function.blocks)
            if block.terminator.op == "suspend-yield-from")
        block = function.blocks[block_index]
        protocol = dict(block.terminator.arguments[2])
        protocol["resume-value"] = "return-sent-value-without-delegate"
        terminator = replace(
            block.terminator,
            arguments=(block.terminator.arguments[0], 1, protocol))
        blocks = list(function.blocks)
        blocks[block_index] = replace(block, terminator=terminator)
        with self.assertRaises(FunctionCFGError) as raised:
            _validate_function(replace(function, blocks=tuple(blocks)))
        self.assertEqual(raised.exception.code, "PZFC319")

        frame = dict(function.signature["frame"])
        states = list(frame["states"])
        states[0] = {**states[0], "resume_target": "wrong_resume"}
        frame["states"] = tuple(states)
        signature = {**function.signature, "frame": frame}
        with self.assertRaises(FunctionCFGError) as raised:
            _validate_function(replace(function, signature=signature))
        self.assertEqual(raised.exception.code, "PZFC319")

    def test_nested_yield_expression_remains_an_explicit_blocker(
            self) -> None:
        function = self.lower_sample(
            "def nested(value):\n"
            "    result = 1 + (yield value)\n"
            "    return result\n")
        self.assertEqual(
            [(item.code, item.node_kind) for item in function.blockers],
            [("PZ2030", "BinOp")])
        self.assertEqual(
            function.signature["source_suspension_count"], 1)
        self.assertEqual(
            function.signature["lowered_suspension_state_count"], 0)

    def test_fresh_active_graph_has_no_reachable_cfg_blockers(
            self) -> None:
        report = analyze_active_call_graph(ROOT)
        inventory = report["callable_inventory"]
        self.assertEqual(
            inventory["unsupported_lowering_code_counts"].get("PZ2030", 0),
            0)
        self.assertEqual(
            report["call_graph"]["reachable_cfg_blocker_code_counts"].get(
                "PZ2030", 0),
            0)
        self.assertEqual(
            report["call_graph"]["reachable_cfg_blocker_count"], 0)
        self.assertEqual(
            report["call_graph"]["reachable_cfg_blocker_code_counts"], {})
        audio_load = [
            row for row in inventory["callables"]
            if row["module"] == "rtype_port.audio" and
            row["qualname"] == "GeneralSound._load"]
        self.assertEqual(len(audio_load), 1)
        self.assertFalse(audio_load[0]["cfg"]["blockers"])
        frames = [
            row for row in inventory["callables"]
            if row["module"] == "rtype_port.tsfm" and
            row["qualname"] == "TsfmEmulator.frames"]
        self.assertEqual(len(frames), 1)
        self.assertFalse(frames[0]["cfg"]["blockers"])
        self.assertEqual(
            frames[0]["cfg"]["signature"]["execution_kind"],
            "generator-frame")

    def test_with_enters_left_to_right_and_exits_nested_managers_exactly(
            self) -> None:
        function = self.lower_sample(
            "def context(first, second):\n"
            "    with make_first(first) as left, make_second(left) as right:\n"
            "        body(left, right)\n"
            "    after()\n")
        self.assertFalse(function.blockers)
        operations = [item for block in function.blocks
                      for item in block.instructions]
        protocol = [item.op for item in operations if item.op.startswith(
            "python-with-")]
        self.assertEqual(protocol.count("python-with-load-enter"), 2)
        self.assertEqual(protocol.count("python-with-load-exit"), 2)
        self.assertEqual(protocol.count("python-with-call-enter"), 2)
        self.assertEqual(
            protocol.count("python-with-call-exit-exception"), 2)
        self.assertEqual(protocol.count("python-with-call-exit-normal"), 3)
        enter_loads = [item for item in operations
                       if item.op == "python-with-load-enter"]
        exit_loads = [item for item in operations
                      if item.op == "python-with-load-exit"]
        enter_calls = [item for item in operations
                       if item.op == "python-with-call-enter"]
        for enter_load, exit_load, enter_call in zip(
                enter_loads, exit_loads, enter_calls):
            self.assertLess(enter_load.sequence, exit_load.sequence)
            self.assertLess(exit_load.sequence, enter_call.sequence)
            self.assertEqual(enter_call.arguments,
                             (enter_load.destination,))
            self.assertEqual(
                dict(enter_load.attributes)["descriptor_binding"],
                "manager-instance")
        normal_exits = [item for item in operations
                        if item.op == "python-with-call-exit-normal"]
        self.assertTrue(all(item.arguments[1:] == (None, None, None)
                            for item in normal_exits))
        self.assertTrue(all(dict(item.attributes)["return_value_ignored"]
                            for item in normal_exits))
        self.assertEqual(
            [program.source for program in function.expression_programs],
            ["make_first(first)", "make_second(left)",
             "body(left, right)", "after()"])

    def test_with_enter_failure_and_exception_suppression_edges_are_exact(
            self) -> None:
        function = self.lower_sample(
            "def guarded(first, second):\n"
            "    with first as left, second as right:\n"
            "        danger(left, right)\n"
            "    resumed()\n")
        blocks = {block.name: block for block in function.blocks}
        enter_blocks = [
            block for block in function.blocks
            if any(item.op == "python-with-call-enter"
                   for item in block.instructions)]
        self.assertEqual(len(enter_blocks), 2)
        outer_enter, inner_enter = enter_blocks
        outer_protected = blocks[outer_enter.terminator.targets[0]]
        inner_protected = blocks[inner_enter.terminator.targets[0]]
        outer_exception = blocks[outer_protected.exception_target]
        inner_exception = blocks[inner_protected.exception_target]
        self.assertIsNone(outer_enter.exception_target)
        self.assertEqual(inner_enter.exception_target,
                         outer_exception.name)
        self.assertIsNone(outer_exception.exception_target)
        self.assertEqual(inner_exception.exception_target,
                         outer_exception.name)
        for exceptional in (outer_exception, inner_exception):
            ops = [item.op for item in exceptional.instructions]
            self.assertEqual(ops, [
                "capture-current-exception", "python-exception-type",
                "python-exception-traceback",
                "python-with-call-exit-exception"])
            self.assertEqual(exceptional.terminator.op, "branch-truth")
            exit_call = exceptional.instructions[-1]
            self.assertEqual(exceptional.terminator.arguments,
                             (exit_call.destination,))
        inner_true = blocks[inner_exception.terminator.targets[0]]
        outer_normal = blocks[inner_true.terminator.targets[0]]
        self.assertIn("suppress-with-exception",
                      [item.op for item in inner_true.instructions])
        self.assertIn("python-with-call-exit-normal",
                      [item.op for item in outer_normal.instructions])
        inner_false = blocks[inner_exception.terminator.targets[1]]
        self.assertEqual(inner_false.terminator.op, "raise-saved")
        self.assertEqual(inner_false.exception_target,
                         outer_exception.name)

    def test_with_return_break_and_continue_cross_exit_once(self) -> None:
        function = self.lower_sample(
            "def controls(manager, values):\n"
            "    for value in values:\n"
            "        with manager(value):\n"
            "            if value == 0:\n"
            "                continue\n"
            "            if value == 1:\n"
            "                break\n"
            "            return value\n"
            "    return None\n")
        self.assertFalse(function.blockers)
        blocks = {block.name: block for block in function.blocks}
        expectations = {
            5: ("jump", "for_header_"),
            7: ("jump", "for_merge_"),
            8: ("return", None),
        }
        for line, (terminal_op, target_prefix) in expectations.items():
            source = next(
                block for block in function.blocks
                if block.terminator.span.line == line and
                block.terminator.op == "jump" and
                block.terminator.targets[0].startswith("with_exit["))
            exit_block = blocks[source.terminator.targets[0]]
            self.assertEqual(
                [item.op for item in exit_block.instructions],
                ["python-with-call-exit-normal"])
            self.assertEqual(exit_block.terminator.op, terminal_op)
            if target_prefix is None:
                self.assertFalse(exit_block.terminator.targets)
            else:
                self.assertTrue(exit_block.terminator.targets[0].startswith(
                    target_prefix))

    def test_with_validator_rejects_protocol_and_protected_edge_tamper(
            self) -> None:
        function = self.lower_sample(
            "def guarded(manager):\n"
            "    with manager as value:\n"
            "        consume(value)\n")
        block_index, item_index = next(
            (block_index, item_index)
            for block_index, block in enumerate(function.blocks)
            for item_index, item in enumerate(block.instructions)
            if item.op == "python-with-load-exit")
        blocks = list(function.blocks)
        items = list(blocks[block_index].instructions)
        items[item_index] = replace(
            items[item_index], attributes=tuple(sorted({
                **dict(items[item_index].attributes),
                "lookup_order": "after-enter-call",
            }.items())))
        blocks[block_index] = replace(
            blocks[block_index], instructions=tuple(items))
        with self.assertRaises(FunctionCFGError) as raised:
            _validate_function(replace(function, blocks=tuple(blocks)))
        self.assertEqual(raised.exception.code, "PZFC316")

        function = self.lower_sample(
            "def guarded(manager):\n"
            "    with manager:\n"
            "        consume()\n")
        blocks = list(function.blocks)
        enter_index = next(
            index for index, block in enumerate(blocks)
            if any(item.op == "python-with-call-enter"
                   for item in block.instructions))
        protected_name = blocks[enter_index].terminator.targets[0]
        protected_index = next(
            index for index, block in enumerate(blocks)
            if block.name == protected_name)
        blocks[protected_index] = replace(
            blocks[protected_index], exception_target=None)
        with self.assertRaises(FunctionCFGError) as raised:
            _validate_function(replace(function, blocks=tuple(blocks)))
        self.assertEqual(raised.exception.code, "PZFC320")

    def test_generator_with_spills_saved_exit_and_routes_throw_to_it(
            self) -> None:
        function = self.lower_sample(
            "def guarded(manager):\n"
            "    with manager:\n"
            "        yield produce()\n")
        self.assertFalse(function.blockers)
        state = function.signature["frame"]["states"][0]
        self.assertEqual(state["finalizer_stack"], ("with_exit[0]",))
        self.assertIsNotNone(state["exception_target"])
        exit_load = next(
            item for block in function.blocks
            for item in block.instructions
            if item.op == "python-with-load-exit")
        self.assertIn(exit_load.destination, state["spill_slots"])
        resume = next(block for block in function.blocks
                      if block.name == state["resume_target"])
        self.assertEqual(resume.exception_target,
                         state["exception_target"])
        exceptional = next(
            block for block in function.blocks
            if block.name == state["exception_target"])
        self.assertIn(
            "python-with-call-exit-exception",
            [item.op for item in exceptional.instructions])
        self.assertEqual(exceptional.terminator.op, "branch-truth")

    def test_async_with_is_a_distinct_honest_blocker(self) -> None:
        source = (
            "async def context(manager):\n"
            "    async with manager:\n"
            "        await body()\n")
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.AsyncFunctionDef)
        function = lower_python_function_cfg(
            node, class_name=None, source_path=Path("sample.py"),
            source_text=source)
        self.assertIn(
            ("PZFC212", "AsyncWith"),
            [(item.code, item.node_kind) for item in function.blockers])
        self.assertFalse(any(item.code == "PZFC201"
                             for item in function.blockers))


if __name__ == "__main__":
    unittest.main()
