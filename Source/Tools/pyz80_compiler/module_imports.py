"""Numeric import plans for a closed, source-sealed set of regular modules.

No topological execution order is inferred. Each original IMPORT_NAME has its
own request and the target loader schedules missing initializers on demand.
External modules, import hooks, import-star and module __getattr__ need providers.
"""
from __future__ import annotations

import ast
from collections import deque
from importlib.util import resolve_name
from pathlib import Path
import sysconfig

from .module_program import ModuleProgram

NONE = 65535
FROM = 65534


def pinned_stdlib_sources() -> dict[str, Path]:
    """Explicit source allowlist from the pinned compiler installation.

    __future__ uses the ordinary AST importer. dataclasses uses an explicitly
    partial source/native provider, recorded separately in the module graph.
    Original source bytes and the executable enter the seal in both cases.
    """
    path = Path(sysconfig.get_path('stdlib')) / '__future__.py'
    if not path.is_file():
        raise ValueError('pinned CPython __future__.py source is unavailable')
    from .dataclass_methods import dataclass_source_path
    from .collections_provider import source_path
    return {'__future__': path.resolve(), 'dataclasses': dataclass_source_path(),
            'collections': source_path()}


def collect_source_imports(source_root: Path, entries: tuple[str, ...], *,
                           library_sources: dict[str, Path] | None = None) -> dict[str, tuple[Path, str]]:
    """Inventory all literal local imports, including conditional/function ones.

    This expands the available image, not proven runtime reachability. Import
    statements still decide if/when initialization happens. Nonlocal libraries
    are left to providers; no modules are imported or executed on the host.
    """
    source_root = source_root.resolve()
    result = {}
    queue = deque(entries)

    def locate(name):
        if not name or any(not part.isidentifier() for part in name.split('.')):
            return None
        base = source_root.joinpath(*name.split('.'))
        for path in (base/'__init__.py', base.with_suffix('.py')):
            if path.is_file():
                path = path.resolve()
                if not path.is_relative_to(source_root):
                    raise ValueError('source import escapes the selected Python source root')
                return path
        if library_sources and name in library_sources:
            path = library_sources[name].resolve()
            if not path.is_file():
                raise ValueError(f'missing explicit library source: {name}')
            return path
        return None

    while queue:
        name = queue.popleft()
        if name in result:
            continue
        path = locate(name)
        if path is None:
            if name in entries:
                raise ValueError(f'missing selected source module: {name}')
            continue
        source = path.read_text(encoding='utf-8')
        result[name] = (path, source)
        from .dataclass_provider import is_provider_source
        from .collections_provider import is_provider_source as is_collections_source
        if is_provider_source(name, path, source) or is_collections_source(name, path, source):
            continue  # Explicit partial native boundary; do not pretend to load unused stdlib dependencies.
        parts = name.split('.')
        queue.extend('.'.join(parts[:size]) for size in range(1, len(parts)))
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                try:
                    base = resolve_name('.'*node.level+(node.module or ''), package) if node.level else node.module
                except (ImportError, ValueError):
                    continue
                if base:
                    queue.append(base)
                    queue.extend(base+'.'+alias.name for alias in node.names if alias.name != '*')
    return result


def build_import_plan(program: ModuleProgram) -> dict:
    constants = program.artifact.compact_document['constants']
    symbols = {value: i for i, value in enumerate(constants) if isinstance(value, str)}
    names = program.module_names
    source_rows = {row['module']: row for row in program.graph['source_modules']}
    packages = {name for name in names if Path(source_rows[name]['path']).name == '__init__.py'}
    modules = []
    for name, entry in zip(names, program.initializer_functions):
        path = Path(source_rows[name]['path'])
        parent, _, leaf = name.rpartition('.')
        modules.append({'name': name, 'entry': entry, 'parent': names.index(parent) if parent in names else NONE,
            'leaf': symbols[leaf], 'name_symbol': symbols[name],
            'package': symbols[name if name in packages else parent], 'file': symbols[str(path)],
            'directory': symbols[str(path.parent)], 'is_package': int(name in packages)})

    def available(name):
        if name not in names:
            return False
        while '.' in name:
            name = name.rpartition('.')[0]
            if name not in packages:
                return False
        return True

    requests, from_items, dispatch, pending = [], [], [], []
    for index, adapter in enumerate(program.artifact.adapter_table):
        if adapter['op'] == 'python-import-from':
            if adapter['argument_count'] != 2:
                raise ValueError('invalid IMPORT_FROM operands')
            dispatch.append(FROM)
            continue
        source = adapter.get('attributes', {}).get('source_import')
        if adapter['op'] != 'python-import-module' or source is None:
            dispatch.append(NONE)
            continue
        owner = source['owner']
        package = owner if owner in packages else owner.rpartition('.')[0]
        try:
            target = resolve_name('.' * source['level'] + (source['name'] or ''), package) if source['level'] else source['name']
        except (ImportError, ValueError):
            target = None
        if not target or not available(target) or '*' in source['fromlist']:
            dispatch.append(NONE)
            pending.append({'adapter': index, 'source': source, 'reason': 'external/incomplete module set, invalid relative import or import-star'})
            continue
        if adapter['argument_count'] != 4:
            raise ValueError('invalid IMPORT_NAME operands')
        start = len(from_items)
        for field in source['fromlist']:
            child = target + '.' + field
            from_items.append((symbols[field], names.index(child) if available(child) else NONE))
        request = {'owner': names.index(owner), 'target': names.index(target),
            'result': names.index(target.split('.')[0]) if source['mode'] == 'root-package' else names.index(target),
            'from_start': start, 'from_count': len(source['fromlist']),
            'name': NONE if source['name'] is None else symbols[source['name']], 'level': source['level'],
            'from_constant': constants.index(list(source['fromlist'])), 'mode': symbols[source['mode']]}
        if len(requests) >= FROM or len(from_items) >= NONE or request['level'] > 65535:
            raise ValueError('import plan exceeds uint16 storage')
        dispatch.append(len(requests))
        requests.append(request)
    return {'modules': modules, 'requests': requests, 'from_items': from_items,
        'dispatch': dispatch, 'function_modules': list(program.function_module_ids),
        'metadata_keys': [symbols[key] for key in ('__name__', '__package__', '__file__', '__doc__', '__path__', '__getattr__')],
        'proof_sha256': program.artifact.semantic_sha256, 'pending': pending,
        'contract': 'closed regular modules; runtime imports/cache; no custom import hooks or import-star'}


def render_import_plan(plan: dict) -> tuple[str, str]:
    header = '''/* Generated from the source-module PZVT proof. */
#ifndef PYZ80_IMPORT_PLAN_GENERATED_H
#define PYZ80_IMPORT_PLAN_GENERATED_H
#include "pyz80_target_imports.h"
extern const PyZ80TargetImportPlan PyZ80GeneratedImportPlan;
#endif
'''
    def array(ctype, name, rows):
        return 'static const ' + ctype + ' ' + name + '[] = {\n' + ',\n'.join(rows or ['{0}']) + '\n};\n'
    def record(values):
        return '{' + ','.join(str(v) + 'u' for v in values) + '}'
    code = '#include "pyz80_import_plan_generated.h"\n'
    code += array('PyZ80TargetModuleSpec', 'modules', [record(row[key] for key in
        ('entry','parent','leaf','name_symbol','package','file','directory','is_package')) for row in plan['modules']])
    code += array('PyZ80TargetImportRequest', 'requests', [record(row[key] for key in
        ('owner','target','result','from_start','from_count','name','level','from_constant','mode')) for row in plan['requests']])
    code += array('PyZ80TargetImportFrom', 'from_items', [record(row) for row in plan['from_items']])
    for name in ('dispatch', 'function_modules', 'metadata_keys'):
        code += array('uint16_t', name, [str(v) + 'u' for v in plan[name]])
    code += 'static const uint8_t proof[]={' + ','.join(str(v) for v in bytes.fromhex(plan['proof_sha256'])) + '};\n'
    code += 'const PyZ80TargetImportPlan PyZ80GeneratedImportPlan={modules,requests,from_items,dispatch,function_modules,metadata_keys,proof,'
    code += ','.join(str(len(plan[name])) + 'u' for name in ('modules','requests','from_items','dispatch','function_modules')) + '};\n'
    return header, code
