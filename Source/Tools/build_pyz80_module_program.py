#!/usr/bin/env python3
"""Build explicit module-body entries from the active launcher, never an SPG.

Uses the same adapter C renderer as the whole-program backend. The output
records unresolved imports/classes/operations and cannot claim a live game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from generate_pzvt_target_adapters import build_adapter_specs, render_adapter_tables
from pyz80_compiler.active_call_graph import _launcher_entry, _build_module_graph
from pyz80_compiler.generation_transaction import GenerationTransaction
from pyz80_compiler.module_program import build_module_program
from pyz80_compiler.module_imports import build_import_plan, render_import_plan, collect_source_imports, pinned_stdlib_sources
from pyz80_compiler.dataclass_provider import build_plan as build_dataclass_plan, render_plan as render_dataclass_plan
from pyz80_compiler.banked_tables import build_banked_tables

ROOT = Path(__file__).resolve().parents[2]


def _record(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    return {'path': path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix(), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}


def build(root: Path = ROOT, modules: tuple[str, ...] = (), with_imports: bool = False) -> dict:
    root = root.resolve()
    launcher, entry = _launcher_entry(root)
    active = _build_module_graph(root, entry)
    selected = modules or (entry,)
    if len(set(selected)) != len(selected) or any(name not in active for name in selected):
        raise ValueError('select distinct modules belonging to the active launcher graph')
    sources = collect_source_imports(root/'Source/Python', selected, library_sources=pinned_stdlib_sources()) if with_imports else {
        name:(active[name].path, active[name].source) for name in selected}
    source_paths = [path for path, _ in sources.values()]
    dependencies = sorted(set([root/'run_python.cmd', Path(__file__).resolve(),
        root/'Source/Tools/generate_pzvt_target_adapters.py', Path(sys.executable).resolve(), *source_paths,
        *(root/'Source/Tools/pyz80_compiler').glob('*.py'),
        *(root/'Source/C/python_vm').glob('*.c'), *(root/'Source/C/python_vm').glob('*.h')]))
    before = [_record(path, root) for path in dependencies]
    for name in selected:
        if hashlib.sha256(active[name].path.read_bytes()).hexdigest() != active[name].source_sha256:
            raise RuntimeError('source changed while resolving modules')
    for path, source in sources.values():
        if path.read_text(encoding='utf-8') != source:
            raise RuntimeError('source changed while resolving import closure')
    program = build_module_program(sources)
    artifact = program.artifact
    plan = build_adapter_specs(artifact.adapter_table, artifact.compact_document['constants'],
                              artifact.target_coverage['function_id_table'], artifact.target_coverage['function_call_signatures'])
    header, code = render_adapter_tables(plan, artifact.target_coverage['positional_call_arities'])
    banked, bank_h, bank_c, bank_report = build_banked_tables(plan, artifact.target_coverage['positional_call_arities'], artifact.semantic_sha256)
    imports = build_import_plan(program)
    import_header, import_code = render_import_plan(imports)
    key = selected[0] if len(selected)==1 else 'selection_' + hashlib.sha256('\n'.join(selected).encode()).hexdigest()[:16]
    if with_imports:
        key += '_imports'
    output = (root/'Build/ModulePrograms'/key).resolve()
    if not output.is_relative_to(root/'Build/ModulePrograms'):
        raise ValueError('output must remain inside the dedicated module build directory')
    files = {
        'module_program.pzvt': artifact.target_bytecode,
        'module_program.pzvm': artifact.proof_bytecode,
        'module_program.proof.bin': bytes.fromhex(artifact.semantic_sha256),
        'source_graph.json': (json.dumps(program.graph,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(),
        'pyz80_target_adapter_plan_generated.h': header.encode(),
        'pyz80_target_adapter_plan_generated.c': code.encode(),
        'core_tables.pztb': banked,
        'pyz80_target_banked_plan_generated.h': bank_h.encode(),
        'pyz80_target_banked_plan_generated.c': bank_c.encode(),
        'core_tables.json': (json.dumps(bank_report,indent=2,sort_keys=True)+'\n').encode(),
        'pyz80_import_plan_generated.h': import_header.encode(),
        'pyz80_import_plan_generated.c': import_code.encode(),
        'import_plan.json': (json.dumps(imports,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(),
        'pyz80_module_plan_generated.h': (
            '/* Source-owned module entries; no inferred import execution order. */\n'
            '#ifndef PYZ80_MODULE_PLAN_GENERATED_H\n#define PYZ80_MODULE_PLAN_GENERATED_H\n#include <stdint.h>\n'
            f'#define PYZ80_MODULE_COUNT {len(sources)}u\n'
            'static const uint16_t PyZ80ModuleEntryFunctions[] = {' + ','.join(map(str,program.initializer_functions)) + '};\n'
            'static const uint16_t PyZ80FunctionModuleIds[] = {' + ','.join(map(str,program.function_module_ids)) + '};\n#endif\n').encode(),
    }
    dataclasses = build_dataclass_plan(program) if any(row['kind']=='partial-cpython-dataclasses'
        for row in program.graph.get('provider_sources',[])) else None
    if dataclasses is not None:
        dataclass_header, dataclass_code = render_dataclass_plan(dataclasses)
        files.update({
            'pyz80_dataclass_plan_generated.h': dataclass_header.encode(),
            'pyz80_dataclass_plan_generated.c': dataclass_code.encode(),
            'dataclass_plan.json': (json.dumps(dataclasses,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(),
        })
    report = {'format':'pyz80.source-module-program.v1', 'live':False,
              'scope':'module-body backend with demand-driven closed-source import plan; not a linked game', 'launcher':launcher,
              'selected_modules':list(selected), 'modules':list(sources), 'inputs':before, 'target_bytes':len(artifact.target_bytecode),
              'target_sha256':artifact.target_bytecode_sha256, 'proof_semantic_sha256':artifact.semantic_sha256,
              'banked_core_tables':bank_report,
              'container_protocol':plan['container_protocol'],
              'initializers':list(program.initializer_functions), 'function_modules':list(program.function_module_ids),
              'definition_only_functions':artifact.target_coverage['definition_only_function_count'],
              'generator_lowering':artifact.target_coverage['generator_lowering'],
              'comprehension_lowering':artifact.target_coverage['comprehension_lowering'],
              'native_class_bodies':sum(bool(flags) for flags in plan['class_body_flags']),
              'native_class_cell_bodies':sum(bool(flags & 2) for flags in plan['class_body_flags']),
              'partial_library_providers':[row['kind'] for row in program.graph.get('provider_sources',[])],
              'partial_library_contracts':{row['module']:row['contract'] for row in program.graph.get('provider_sources',[]) if 'contract' in row},
              'dataclass_candidate_classes':len(dataclasses['classes']) if dataclasses else 0,
              'dataclass_candidate_fields':len(dataclasses['fields']) if dataclasses else 0,
              'dataclass_contract':dataclasses['contract'] if dataclasses else None,
              'function_ids':artifact.target_coverage['function_id_table'],
              'provider_operations':dict(plan['unsupported']),
              'import_requests_bound':len(imports['requests']), 'import_requests_pending':imports['pending'],
              'adapter_control_imports':sum(key != 65535 for key in imports['dispatch']),
              'cfg_blockers':[{"callable_id":row['callable_id'],**blocker}
                  for row in program.graph['callable_inventory']['callables'] for blocker in row['cfg']['blockers']],
              'blockers':['external imports, custom import protocols and import-star not all bound',
                          'module __main__/__spec__ bootstrap providers not all bound',
                          'metaclasses, private mangling, builtin bases, unbound super and descriptor protocols not all bound',
                          'dataclass frozen/slots/field, metadata introspection, recursive repr and dynamic comparison protocols pending',
                          'generator next/iter/any/tuple require explicit provider attachment; send/throw/yield-from/finally and exception handling pending',
                          'final Z80 stack, memory banking and frame-time bounds not proved'], 'outputs':[]}
    output.mkdir(parents=True,exist_ok=True)
    with GenerationTransaction(files=[*(output/name for name in files),output/'module_build.json']):
        for name,data in files.items():
            (output/name).write_bytes(data)
            report['outputs'].append(_record(output/name,root))
        if before != [_record(path,root) for path in dependencies]:
            raise RuntimeError('compiler/source changed during module build')
        report['semantic_sha256']=hashlib.sha256(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        (output/'module_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return {'output':str(output),'modules':list(sources),'target_bytes':len(artifact.target_bytecode),
            'definition_only_functions':report['definition_only_functions'], 'provider_operations':report['provider_operations'],
            'generator_bodies':len(report['generator_lowering']['bodies']),
            'comprehensions_by_kind':report['comprehension_lowering']['definitions_by_kind'],
            'native_class_bodies':report['native_class_bodies'],
            'dataclass_candidate_classes':report['dataclass_candidate_classes'],
            'import_requests_bound':len(imports['requests']), 'import_requests_pending':len(imports['pending']),
            'cfg_blocker_count':len(report['cfg_blockers']), 'live':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module',action='append',default=[],help='Active source module; may be repeated. Default: launcher entry.')
    parser.add_argument('--with-imports',action='store_true',help='Include literal local dependencies, including conditional and function imports; do not execute them at build time.')
    args=parser.parse_args()
    print(json.dumps(build(modules=tuple(args.module),with_imports=args.with_imports),ensure_ascii=False,indent=2))
