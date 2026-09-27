#!/usr/bin/env python3
"""Active launcher module/callable/CFG graph proof tests."""

from __future__ import annotations

import copy
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import pyz80_compiler.active_call_graph as active_call_graph

from check_pyz80_active_call_graph import probe, validate_report
from pyz80_compiler.active_call_graph import (
    ACTIVE_CALL_GRAPH_FORMAT,
    ACTIVE_CALL_GRAPH_STATUS,
    ActiveCallGraphError,
)


ROOT = Path(__file__).resolve().parents[2]


def _fixture_call_sites(source: str) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source_root = root / "Source" / "Python"
        source_root.mkdir(parents=True)
        (source_root / "sample.py").write_text(source, encoding="utf-8")
        modules = active_call_graph._build_module_graph(root, "sample")
        (callables, classes, callable_by_node,
         _class_by_node) = active_call_graph._collect_definitions(modules)
        active_call_graph._populate_bindings(modules, callables, classes)
        active_call_graph._resolve_class_bases(modules, classes)
        active_call_graph._populate_module_value_facts(modules, classes)
        rows, _facts = active_call_graph._build_call_sites(
            callables, modules, callable_by_node, classes)
        return rows


class ActiveCallGraphResolverFixtureTests(unittest.TestCase):
    def test_closed_classmethod_cls_and_single_builtin_super_are_proven(
            self) -> None:
        rows = _fixture_call_sites("""
class Leaf:
    def __init__(self, value):
        self.value = value

    @classmethod
    def make(kind):
        return kind(1)

class Items(list):
    def __init__(self):
        super().__init__()

    def add(self, value):
        super().append(value)

def entry():
    Leaf.make()
    Items()
""")
        selected = {str(row["source"]): row["resolution"] for row in rows}
        constructor = selected["kind(1)"]
        self.assertEqual(constructor["kind"], "exact-internal-constructor")
        self.assertTrue(constructor["proven"])
        self.assertEqual(len(constructor["targets"]), 1)
        self.assertTrue(str(constructor["targets"][0]).startswith(
            "sample::Leaf.__init__@"))
        self.assertEqual(
            constructor["source_proof"]["kind"],
            "closed-classmethod-cls-constructor")
        for source, target in (
                ("super().__init__()", "builtins.list.__init__"),
                ("super().append(value)", "builtins.list.append")):
            resolution = selected[source]
            self.assertEqual(resolution["kind"], "host-boundary")
            self.assertFalse(resolution["proven"])
            self.assertEqual(resolution["external_target"], target)
            self.assertEqual(
                resolution["source_proof"]["kind"],
                "closed-single-builtin-super-mro")

    def test_open_cls_and_non_unique_super_mro_stay_unresolved(self) -> None:
        rows = _fixture_call_sites("""
class Parent:
    @classmethod
    def make(cls):
        return cls()

class Child(Parent):
    pass

class Escaped:
    @classmethod
    def make(cls):
        return cls()

def expose():
    return Escaped

class Marker:
    pass

class Mixed(list, Marker):
    def add(self, value):
        super().append(value)
""")
        calls = [row for row in rows
                 if str(row["source"]) in {
                     "cls()", "super().append(value)"}]
        self.assertEqual(len(calls), 3)
        cls_calls = [row["resolution"] for row in calls
                     if row["source"] == "cls()"]
        self.assertEqual(len(cls_calls), 2)
        self.assertTrue(all(
            row["kind"] == "unresolved-local-callable" and
            row["proven"] is False and row["targets"] == []
            for row in cls_calls))
        super_call = next(row["resolution"] for row in calls
                          if row["source"] == "super().append(value)")
        self.assertEqual(super_call["kind"], "unresolved-super-dispatch")
        self.assertFalse(super_call["proven"])
        self.assertEqual(super_call["targets"], [])

    def test_source_proven_constructor_receiver_import_and_builtin_classes(
            self) -> None:
        rows = _fixture_call_sites("""
from dataclasses import dataclass

@dataclass(frozen=True)
class Data:
    value: int

class Leaf:
    @classmethod
    def make(cls):
        return cls()

    def ping(self):
        return 1

class Holder:
    def __init__(self):
        self.leaf = Leaf()
        self.items = []

    def run(self):
        self.leaf.ping()
        self.items.append(1)
        Leaf.make()

@dataclass
class Base:
    value: int

class Child(Base):
    def __init__(self):
        super().__init__(1)

def imports_and_builtins():
    import json as local_json
    local_json.dumps({})
    ValueError("x")
    divmod(5, 2)

def construct():
    Data(1)
    Holder()
    Child()
""")
        by_callee: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_callee.setdefault(str(row["callee_source"]), []).append(row)

        def one(callee: str) -> dict[str, object]:
            self.assertEqual(len(by_callee[callee]), 1)
            return by_callee[callee][0]["resolution"]  # type: ignore[index]

        self.assertEqual(one("Data")["kind"], "host-boundary")
        generated = one("super().__init__")
        self.assertEqual(generated["kind"],
                         "exact-generated-dataclass-init")
        self.assertTrue(generated["proven"])
        self.assertEqual(generated["targets"], [])
        schema = generated["generated_dataclass_init"]
        self.assertEqual(schema["class_id"], "sample::Base@27")
        self.assertEqual(
            [row["name"] for row in schema["parameters"]],
            ["self", "value"])
        self.assertEqual(one("self.leaf.ping")["kind"],
                         "exact-internal-method")
        self.assertTrue(one("self.leaf.ping")["proven"])
        self.assertEqual(one("self.items.append")["kind"], "host-boundary")
        self.assertEqual(one("Leaf.make")["kind"],
                         "exact-internal-class-method")
        self.assertTrue(one("Leaf.make")["proven"])
        self.assertEqual(one("local_json.dumps")["kind"], "host-boundary")
        self.assertEqual(one("ValueError")["external_target"],
                         "builtins.ValueError")
        self.assertEqual(one("divmod")["external_target"],
                         "builtins.divmod")

    def test_ambiguous_or_shadowed_dispatch_stays_fail_closed(self) -> None:
        rows = _fixture_call_sites("""
def replacement(cls):
    return cls

@replacement
class Decorated:
    pass

class A:
    def go(self):
        return 1

class B:
    def go(self):
        return 2

class PropertyOwner:
    @property
    def value(self):
        return 1

def ambiguous(flag):
    receiver = A()
    if flag:
        receiver = B()
    receiver.go()

def shadowed(ValueError):
    ValueError()

def decorated_constructor():
    Decorated()

def descriptor_call():
    PropertyOwner.value()
""")
        selected = {str(row["source"]): row["resolution"] for row in rows}
        ambiguous = selected["receiver.go()"]
        self.assertEqual(ambiguous["kind"], "finite-dynamic-dispatch")
        self.assertFalse(ambiguous["proven"])
        self.assertEqual(len(ambiguous["targets"]), 2)
        shadowed = selected["ValueError()"]
        self.assertEqual(shadowed["kind"], "unresolved-local-callable")
        self.assertFalse(shadowed["proven"])
        decorated = selected["Decorated()"]
        self.assertEqual(decorated["kind"],
                         "unresolved-constructor-dispatch")
        self.assertFalse(decorated["proven"])
        descriptor = selected["PropertyOwner.value()"]
        self.assertTrue(str(descriptor["kind"]).startswith("unresolved-"))
        self.assertFalse(descriptor["proven"])

    def test_callable_parameter_candidates_never_become_proven_edges(self) -> None:
        rows = _fixture_call_sites("""
def left(value):
    return value

def right(value):
    return -value

def invoke(callback, value):
    return callback(value)

def entry(flag):
    invoke(left if flag else right, 1)
""")
        callback = next(row["resolution"] for row in rows
                        if row["source"] == "callback(value)")
        self.assertEqual(callback["kind"], "finite-dynamic-dispatch")
        self.assertFalse(callback["proven"])
        self.assertEqual(len(callback["targets"]), 2)

    def test_unresolved_local_reason_distinguishes_getattr_and_parameter(
            self) -> None:
        rows = _fixture_call_sites("""
def invoke(callback):
    callback(1)

def dynamic(obj):
    contact = getattr(obj, "contact", None)
    if contact is not None:
        contact(1)
""")
        selected = {str(row["source"]): row["resolution"] for row in rows}
        self.assertIn("parameter actuals", selected["callback(1)"]["evidence"])
        self.assertIn("dynamic builtins.getattr",
                      selected["contact(1)"]["evidence"])


class ActiveCallGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = probe(ROOT)
        cls.callable_rows = {
            row["callable_id"]: row
            for row in cls.report["callable_inventory"]["callables"]
        }
        cls.call_sites = cls.report["call_graph"]["call_sites"]

    def test_launcher_and_active_module_closure_are_literal(self) -> None:
        report = self.report
        self.assertEqual(report["format"], ACTIVE_CALL_GRAPH_FORMAT)
        self.assertEqual(report["status"], ACTIVE_CALL_GRAPH_STATUS)
        self.assertFalse(report["live"])
        self.assertEqual(report["launcher"]["module"], "rtype_port.app")
        self.assertEqual(report["entrypoint"], {
            "module": "rtype_port.app",
            "function": "main",
            "callable_id": "rtype_port.app::main@19",
        })
        modules = report["source_graph"]["module_names"]
        self.assertEqual(len(modules), 12)
        self.assertIn("rtype_port", modules)
        self.assertIn("rtype_port.app", modules)
        self.assertNotIn("rtype_port.autopilot", modules)
        self.assertNotIn("rtype_port.full_runtime", modules)
        self.assertNotIn("rtype_port.hardware", modules)
        self.assertFalse(any(name.startswith("rtype_m72") for name in modules))

    def test_every_function_def_in_active_modules_has_one_cfg_row(self) -> None:
        inventory = self.report["callable_inventory"]
        self.assertEqual(inventory["callable_count"], 580)
        self.assertEqual(len(self.callable_rows), 580)
        self.assertEqual(inventory["cfg_lowered_callable_count"], 580)
        self.assertEqual(inventory["cfg_lowering_failure_count"], 0)
        module_function_counts = {
            row["module"]: row["function_count"]
            for row in self.report["source_graph"]["modules"]
        }
        self.assertEqual(sum(module_function_counts.values()), 580)
        self.assertEqual(module_function_counts["rtype_port.enemies"], 367)
        self.assertEqual(module_function_counts["rtype_port.force"], 49)
        self.assertIn(
            "rtype_port.force::Force._vertical_return.<locals>.solid@510",
            self.callable_rows)

    def test_exact_object_store_fragments_are_reused_once(self) -> None:
        binding = self.report["object_store_binding"]
        self.assertEqual(binding["runtime_site_count"], 364)
        self.assertEqual(binding["fragment_count"], 364)
        self.assertEqual(binding["attached_fragment_count"], 364)
        self.assertEqual(binding["owner_callable_count"], 148)
        self.assertTrue(binding["all_fragments_attached_exactly_once"])
        self.assertEqual(
            self.report["callable_inventory"]
            ["cfg_object_store_splice_instruction_count"], 364)

    def test_cfg_unsupported_ast_census_is_exact_and_fail_closed(self) -> None:
        inventory = self.report["callable_inventory"]
        self.assertEqual(inventory["cfg_blocker_free_callable_count"], 580)
        self.assertEqual(inventory["cfg_blocked_callable_count"], 0)
        self.assertEqual(inventory["unsupported_lowering_blocker_count"], 0)
        self.assertEqual(inventory["unsupported_lowering_code_counts"], {})
        self.assertEqual(inventory["unsupported_lowering_ast_kind_counts"], {})
        self.assertEqual(inventory["lambda_definition_count"], 8)
        blocker_rows = [blocker for row in self.callable_rows.values()
                        for blocker in (row["cfg"] or {}).get("blockers", [])]
        self.assertEqual(len(blocker_rows), 0)
        self.assertEqual(
            Counter(row["node_kind"] for row in blocker_rows),
            Counter(inventory["unsupported_lowering_ast_kind_counts"]))

    def test_import_does_not_make_all_callables_reachable(self) -> None:
        graph = self.report["call_graph"]
        reachable = set(graph["proven_reachable_callable_ids"])
        unreachable = set(graph["not_proven_reachable_callable_ids"])
        self.assertEqual(reachable | unreachable, set(self.callable_rows))
        self.assertFalse(reachable & unreachable)
        self.assertLess(len(reachable), len(self.callable_rows))
        self.assertIn("rtype_port.app::main@19", reachable)
        self.assertIn("rtype_port.game::Game.__init__@381", reachable)
        self.assertIn("rtype_port.game::Game.update@689", reachable)
        self.assertIn("rtype_port.game::Game.render@1048", reachable)
        self.assertNotIn("rtype_port.enemies::Enemy.update@490", reachable)
        self.assertTrue(graph["reachability_uses_only_proven_edges"])
        self.assertTrue(
            graph["dynamic_candidates_are_not_promoted_to_proven_reachable"])

    def test_app_local_constructor_flow_is_evidence_not_a_type_guess(self) -> None:
        main_sites = {row["source"]: row for row in self.call_sites
                      if row["caller"] == "rtype_port.app::main@19"}
        for source, target in (
                ("game.update(keys)", "rtype_port.game::Game.update@689"),
                ("game.render(screen)", "rtype_port.game::Game.render@1048"),
                ("title.update()", "rtype_port.title::TitleScreen.update@138"),
                ("sound.step_frame()",
                 "rtype_port.audio::TargetAudio.step_frame@422")):
            resolution = main_sites[source]["resolution"]
            self.assertEqual(resolution["kind"], "exact-internal-method")
            self.assertTrue(resolution["proven"])
            self.assertEqual(resolution["targets"], [target])
            self.assertIn("constructor", resolution["evidence"])
        self.assertTrue(
            self.report["proof"]["annotations_do_not_create_exact_receiver_types"])

    def test_unresolved_calls_remain_non_proven(self) -> None:
        graph = self.report["call_graph"]
        unresolved = [row for row in self.call_sites
                      if row["resolution"]["kind"].startswith("unresolved-")]
        self.assertEqual(len(unresolved), graph["unresolved_call_site_count"])
        self.assertTrue(unresolved)
        self.assertTrue(all(row["resolution"]["proven"] is False
                            for row in unresolved))
        self.assertTrue(all(row["resolution"]["targets"] == []
                            for row in unresolved))
        reachable = set(graph["proven_reachable_callable_ids"])
        self.assertEqual(
            sum(row["caller"] in reachable for row in unresolved),
            graph["reachable_unresolved_call_site_count"])

    def test_reachable_local_and_super_reduction_is_source_proven(self) -> None:
        graph = self.report["call_graph"]
        reachable = set(graph["proven_reachable_callable_ids"])
        rows = [row for row in self.call_sites if row["caller"] in reachable]
        local = [row for row in rows if row["resolution"]["kind"] ==
                 "unresolved-local-callable"]
        super_unresolved = [
            row for row in rows if row["resolution"]["kind"] ==
            "unresolved-super-dispatch"]
        self.assertEqual(len(local), 9)
        self.assertEqual(super_unresolved, [])

        cls_call = next(row for row in rows
                        if row["caller"] ==
                        "rtype_port.enemies::BackgroundParticleE5CD."
                        "from_stage1_checkpoint@612" and
                        row["callee_source"] == "cls")
        self.assertEqual(
            cls_call["resolution"]["kind"], "exact-internal-constructor")
        self.assertEqual(
            cls_call["resolution"]["source_proof"]["kind"],
            "closed-classmethod-cls-constructor")

        pending_super = [
            row for row in rows
            if row["caller"].startswith(
                "rtype_port.enemies::M72PendingList.") and
            row["callee_source"].startswith("super().")]
        self.assertEqual(len(pending_super), 2)
        self.assertEqual(
            {row["resolution"]["external_target"]
             for row in pending_super},
            {"builtins.list.__init__", "builtins.list.append"})
        self.assertTrue(all(
            row["resolution"]["kind"] == "host-boundary" and
            row["resolution"]["source_proof"]["kind"] ==
            "closed-single-builtin-super-mro"
            for row in pending_super))

        contact = next(row for row in local
                       if row["source"] == "contact(self)")
        self.assertIn("dynamic builtins.getattr",
                      contact["resolution"]["evidence"])
        parameter_calls = [row for row in local if row is not contact]
        self.assertEqual(len(parameter_calls), 8)
        self.assertTrue(all(
            "parameter actuals" in row["resolution"]["evidence"]
            for row in parameter_calls))
        self.assertEqual(
            sum(row["resolution"]["kind"] == "finite-dynamic-dispatch"
                for row in rows), 82)

    def test_finite_dynamic_candidates_are_blockers_not_reachability_edges(
            self) -> None:
        graph = self.report["call_graph"]
        finite = [row for row in self.call_sites
                  if row["resolution"]["kind"] ==
                  "finite-dynamic-dispatch"]
        self.assertEqual(
            len(finite), graph["finite_dynamic_dispatch_site_count"])
        self.assertGreater(len(finite), 0)
        self.assertTrue(all(row["resolution"]["proven"] is False
                            for row in finite))
        self.assertTrue(all(row["resolution"]["targets"]
                            for row in finite))
        reachable = set(graph["proven_reachable_callable_ids"])
        reachable_finite = sum(row["caller"] in reachable for row in finite)
        self.assertEqual(
            reachable_finite,
            graph["reachable_finite_dynamic_dispatch_site_count"])
        blocker_counts = {row["code"]: row["count"]
                          for row in self.report["live_blockers"]}
        self.assertEqual(blocker_counts["PZACG201"], reachable_finite)

    def test_required_host_and_hardware_boundaries_are_explicit(self) -> None:
        boundaries = {row["boundary"]: row
                      for row in self.report["boundaries"]}
        for name in ("pygame", "bass", "filesystem"):
            self.assertGreater(boundaries[name]["call_site_count"], 0)
            self.assertGreater(boundaries[name]["reachable_call_site_count"], 0)
            self.assertEqual(
                boundaries[name]["status"], "ACTIVE_HOST_BOUNDARY_UNBOUND")
        ft = boundaries["ft812-transport"]
        self.assertEqual(ft["call_site_count"], 0)
        self.assertEqual(ft["status"], "ABSENT_FROM_ACTIVE_MODULE_GRAPH")
        self.assertFalse(ft["hardware_module_in_active_import_closure"])
        self.assertFalse(ft["target_transport_provider_bound"])
        self.assertIsNotNone(ft["inactive_source"])

    def test_module_and_class_initialization_calls_are_not_hidden(self) -> None:
        initialization = self.report["module_initialization"]
        self.assertEqual(
            initialization["status"], "INVENTORIED_NOT_CFG_LOWERED")
        self.assertEqual(initialization["call_site_count"], 153)
        self.assertEqual(initialization["explicit_call_site_count"], 66)
        self.assertEqual(initialization["decorator_application_count"], 87)
        self.assertEqual(initialization["property_getter_definition_count"], 50)
        self.assertEqual(
            initialization["property_setter_or_deleter_definition_count"], 0)
        self.assertTrue(
            initialization["module_initializers_have_no_function_cfg"])
        blocker_counts = {row["code"]: row["count"]
                          for row in self.report["live_blockers"]}
        self.assertEqual(blocker_counts["PZACG207"], 153)

    def test_semantic_validator_rejects_tampering(self) -> None:
        tampered = copy.deepcopy(self.report)
        tampered["call_graph"]["proven_reachable_callable_count"] += 1
        with self.assertRaises(ActiveCallGraphError) as raised:
            validate_report(ROOT, tampered)
        self.assertEqual(raised.exception.code, "PZACG403")

    def test_semantic_validator_rejects_resigned_dispatch_promotion(
            self) -> None:
        """A candidate edge stays non-proven even after hash re-signing."""
        tampered = copy.deepcopy(self.report)
        candidate = next(
            row for row in tampered["call_graph"]["call_sites"]
            if row["resolution"]["kind"] == "finite-dynamic-dispatch")
        candidate["resolution"]["proven"] = True
        graph = tampered["call_graph"]
        graph_payload = dict(graph)
        graph_payload.pop("semantic_sha256", None)
        graph["semantic_sha256"] = active_call_graph._json_sha256(
            graph_payload)
        tampered["semantic_sha256"] = active_call_graph._json_sha256(
            active_call_graph._semantic_payload(tampered))
        with self.assertRaises(ActiveCallGraphError) as raised:
            validate_report(ROOT, tampered)
        self.assertEqual(raised.exception.code, "PZACG414")

    def test_semantic_validator_rejects_resigned_source_proof_tamper(
            self) -> None:
        tampered = copy.deepcopy(self.report)
        proven = next(
            row for row in tampered["call_graph"]["call_sites"]
            if row["resolution"].get("source_proof"))
        proven["resolution"]["source_proof"]["class_id"] = "sample::Fake@1"
        graph = tampered["call_graph"]
        graph_payload = dict(graph)
        graph_payload.pop("semantic_sha256", None)
        graph["semantic_sha256"] = active_call_graph._json_sha256(
            graph_payload)
        tampered["semantic_sha256"] = active_call_graph._json_sha256(
            active_call_graph._semantic_payload(tampered))
        with self.assertRaises(ActiveCallGraphError) as raised:
            validate_report(ROOT, tampered)
        self.assertEqual(raised.exception.code, "PZACG414")


if __name__ == "__main__":
    unittest.main()
