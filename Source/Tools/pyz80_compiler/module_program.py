"""Source-owned module body entries and definition-only function inventories.

No source is imported/evaluated on the build host. Initializers are explicitly
selected independent roots, not a fabricated static import order. Imports,
classes and unsupported protocols remain executable blockers in the image.
The optional closed-source import plan schedules module bodies at runtime.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .function_cfg import lower_python_module_cfg, lower_python_function_cfg, lower_python_class_cfg, _ast_sha256
from .whole_program_vm_backend import WholeProgramVMArtifact, build_whole_program_vm, _sha256_json
from .class_protocol import CLASS_PROTOCOL_NAMES
from . import dataclass_provider, collections_provider


@dataclass(frozen=True)
class ModuleProgram:
    artifact: WholeProgramVMArtifact
    graph: dict
    module_names: tuple[str, ...]
    initializer_functions: tuple[int, ...]
    function_module_ids: tuple[int, ...]


def build_module_program(sources: Mapping[str, tuple[Path, str]]) -> ModuleProgram:
    """Build independently startable source modules; do not execute imports.

    Each entry writes into its own caller-owned module mapping. Merely being
    defined does not promote a function body into static reachability.
    """
    if not sources or any(not isinstance(name, str) or not name or
            any(not part.isidentifier() for part in name.split(".")) for name in sources):
        raise ValueError("explicit nonempty Python module names are required")
    names = tuple(sources)
    initializers = []
    definitions = []
    rows = []
    providers, candidates = [], []
    with_dataclasses = any(dataclass_provider.is_provider_source(name, path, text)
                          for name, (path, text) in sources.items())
    for module, (path, source) in sources.items():
        provider = next((p for p in (dataclass_provider, collections_provider)
                         if p.is_provider_source(module, path, source)), None)
        if provider:
            source = provider.bootstrap(source)
            providers.append({'module': module, 'source': source, 'kind': 'partial-cpython-' + module,
                              'original_source_sha256': hashlib.sha256(sources[module][1].encode()).hexdigest()})
            if provider is collections_provider:
                providers[-1]['contract'] = collections_provider.CONTRACT
        tree = ast.parse(source)
        entry = module + "::<module>@1"
        cfg = lower_python_module_cfg(tree, source_path=path, source_text=source,
                                      module_name=module).to_json()
        initializers.append(entry)
        rows.append({"callable_id": entry, "module": module, "module_body": True,
                     "module_is_package": path.name == "__init__.py",
                     "module_bootstrap_constants": ["__name__", "__package__", "__file__", "__doc__", "__path__", "__getattr__",
                         module, module.rpartition(".")[2],
                         module if path.name == "__init__.py" else module.rpartition(".")[0],
                         str(path), str(path.parent), *(provider.SYMBOLS if provider else ())],
                     "lexical_parent_id": None, "ast_sha256": _ast_sha256(tree), "cfg": cfg})

        def visit(statements, parent=None, qualifier="", lexical=None, source_text=source, generated=False):
            for statement in statements:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = qualifier + statement.name
                    identity = f"{module}::{qualname}@{statement.lineno}"
                    lowered = lower_python_function_cfg(statement, class_name=None,
                        source_path=path, source_text=source_text, callable_id=identity,
                        native_operation=provider.INTRINSICS.get(statement.name)
                            if provider and parent is None and not generated else None).to_json()
                    definitions.append(identity)
                    rows.append({"callable_id": identity, "module": module,
                                 "lexical_parent_id": lexical, "definition_parent_id": parent,
                                 "definition_only": True,
                                 "ast_sha256": _ast_sha256(statement), "cfg": lowered})
                    visit(statement.body, identity, qualname + ".<locals>.", identity, source_text, generated)
                elif isinstance(statement, ast.ClassDef):
                    qualname = qualifier + statement.name
                    identity = f"{module}::{qualname}@{statement.lineno}"
                    lowered = lower_python_class_cfg(statement, source_path=path, source_text=source_text,
                        callable_id=identity, qualname=qualname).to_json()
                    definitions.append(identity)
                    rows.append({"callable_id": identity, "module": module, "class_body": True,
                                 "module_bootstrap_constants": list(CLASS_PROTOCOL_NAMES),
                                 "definition_parent_id": parent, "lexical_parent_id": lexical,
                                 "definition_only": True, "ast_sha256": _ast_sha256(statement), "cfg": lowered})
                    visit(statement.body, identity, qualname + ".", lexical, source_text, generated)
                    if with_dataclasses and not provider and not generated:
                        specialization = dataclass_provider.candidate(statement, identity, qualname, source_text, path, module)
                        if specialization:
                            for variant in specialization['variants']:
                                text = variant['source']
                                prefix = qualname + f'.<dataclass-{statement.lineno}-post{int(variant["post_init"])}>.'
                                variant['function_id'] = f'{module}::{prefix}__apply__@1'
                                visit(ast.parse(text).body, None, prefix, None, text, True)
                            candidates.append(specialization)
                else:
                    # Find definitions in control-flow suites without changing their order.
                    for _, value in ast.iter_fields(statement):
                        if isinstance(value, list):
                            for child in value:
                                if isinstance(child, ast.stmt):
                                    visit([child], parent, qualifier, lexical, source_text, generated)
                                elif isinstance(child, (ast.ExceptHandler, ast.match_case)):
                                    visit(child.body, parent, qualifier, lexical, source_text, generated)

        visit(tree.body)
    graph = {"format": "pyz80.explicit-module-entry-graph.v1",
             "provider_sources": providers, "dataclass_candidates": candidates,
             "scope": "independently started modules; not a proved import graph",
             "source_modules": [{"module": name, "path": str(sources[name][0]),
                                 "source": sources[name][1]} for name in names],
             "call_graph": {"proven_reachable_callable_ids": initializers, "call_sites": [],
                            "exact_internal_edge_count": 0},
             "callable_inventory": {"callables": rows, "definition_callable_ids": definitions}}
    graph["semantic_sha256"] = _sha256_json(graph)
    artifact = build_whole_program_vm(graph)
    ids = artifact.target_coverage["function_id_table"]
    modules = artifact.target_coverage["function_modules"]
    if len(modules) != len(ids) or any(module not in names for module in modules):
        raise ValueError("compiled function has no exact source module identity")
    return ModuleProgram(artifact, graph, names, tuple(ids.index(name) for name in initializers),
                         tuple(names.index(module) for module in modules))
