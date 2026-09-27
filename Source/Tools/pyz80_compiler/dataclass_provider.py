"""Sealed stdlib entry points + guarded AOT method specializations.

The application's source and decorator calls are not rewritten. The selected
CPython dataclass() function executes normally; only its library boundary is
native. Specializations are candidates, NOT inferred decorator identities.
The C resolver validates the actual class origin, bases, annotation key order,
defaults and options before selecting one. Unsupported cases fail closed.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import textwrap

from .dataclass_methods import InitField, capture_init_factory, capture_eq_factory, dataclass_source_path

PARAMETERS = 'cls, init, repr, eq, order, unsafe_hash, frozen, match_args, kw_only, slots, weakref_slot'
INTRINSICS = {'_pyz80_dataclass_resolve': 'dataclass-resolve',
              '_pyz80_dataclass_install': 'dataclass-install',
              '_pyz80_dataclass_metadata': 'dataclass-metadata',
              '_pyz80_dataclass_repr_pending': 'dataclass-repr-pending'}
SYMBOLS = ('__annotations__', '__post_init__', '__dataclass_fields__', '__dataclass_params__', '__match_args__',
           '__init__', '__repr__', '__eq__', '__hash__', '__doc__', '__qualname__', '__name__',
           'name', 'type', 'default', 'default_factory', 'init', 'repr', 'eq', 'order', 'unsafe_hash', 'frozen',
           'hash', 'compare', 'metadata', 'kw_only', '_field_type', 'Field', '__module__')


def is_provider_source(name: str, path: Path, source: str) -> bool:
    if name != 'dataclasses' or path.resolve() != dataclass_source_path():
        return False
    if source != path.read_text(encoding='utf-8'):
        raise ValueError('dataclasses source changed before specialization')
    return True


def bootstrap(source: str) -> str:
    tree = ast.parse(source)
    selected = {'_HAS_DEFAULT_FACTORY_CLASS', '_MISSING_TYPE', 'dataclass', 'field'}
    parts = [repr(ast.get_docstring(tree, clean=False))]
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in selected:
            parts.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                ('_HAS_DEFAULT_FACTORY', 'MISSING') for t in node.targets):
            parts.append(ast.get_source_segment(source, node))
    parts.append(f'''def _process_class({PARAMETERS}):
    apply = _pyz80_dataclass_resolve({PARAMETERS})
    return apply({PARAMETERS}, MISSING, _HAS_DEFAULT_FACTORY)
''')
    for name, params in (('_pyz80_dataclass_resolve', PARAMETERS),
                         ('_pyz80_dataclass_install', 'cls, name, value'),
                         ('_pyz80_dataclass_metadata', PARAMETERS),
                         ('_pyz80_dataclass_repr_pending', 'self')):
        parts.append(f'def {name}({params}):\n    raise NotImplementedError({name!r})\n')
    return '\n\n'.join(parts) + '\n'


def candidate(node: ast.ClassDef, identity: str, qualname: str, source: str, path: Path, module: str) -> dict | None:
    # These restrictions are ALSO checked on the actual class by the runtime.
    # field(), ClassVar/InitVar, inherited fields and mutated schemas are not
    # silently flattened into this first plain-field provider.
    if node.bases or node.keywords:
        return None
    from .function_cfg import _future_annotations_enabled, _postponed_annotation_string
    postponed = _future_annotations_enabled(source)
    fields = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not statement.simple or not isinstance(statement.target, ast.Name):
            return None
        if any(isinstance(n, (ast.Name, ast.Attribute)) and
               (n.id if isinstance(n, ast.Name) else n.attr) in ('ClassVar', 'InitVar', 'KW_ONLY')
               for n in ast.walk(statement.annotation)):
            return None
        if isinstance(statement.value, ast.Call):
            return None  # Field/factory providers remain an explicit boundary.
        if postponed:
            annotation = _postponed_annotation_string(statement.annotation, path)
        elif isinstance(statement.annotation, ast.Constant) and isinstance(statement.annotation.value, str):
            annotation = statement.annotation.value
        else:
            return None  # Runtime type/marker identity needs its own resolver.
        # _is_type in CPython also resolves aliases through module globals.
        # Do not assume an unknown/qualified name cannot denote ClassVar/InitVar.
        if set(re.findall(r'[A-Za-z_]\w*', annotation)) - {
                'int','str','bool','float','complex','bytes','bytearray','tuple','list','dict','set','frozenset','object','None'}:
            return None
        fields.append({'name': statement.target.id, 'default': statement.value is not None, 'annotation': annotation})
    if len({f['name'] for f in fields}) != len(fields) or len(fields) > 100:
        return None
    result = {'class_id': identity, 'qualname': qualname, 'module': module, 'fields': fields, 'variants': [], 'valid_init': True}
    for post in (False, True):
        schema = tuple(InitField(f['name'], default='value' if f['default'] else 'missing') for f in fields)
        try:
            factory = capture_init_factory(schema, has_post_init=post)
        except TypeError:
            result['valid_init'] = False
            factory = None
        binding_source = {'annotation': lambda field: f"cls.__annotations__[{field!r}]",
                          'default': lambda field: f'cls.{field}',
                          'factory-sentinel': lambda _: 'factory_sentinel',
                          'builtin-object': lambda _: 'object', 'none': lambda _: 'None'}
        equality = capture_eq_factory(tuple(f['name'] for f in fields))
        lines = [f'def __apply__({PARAMETERS}, missing, factory_sentinel):',
                 '    from dataclasses import _pyz80_dataclass_install, _pyz80_dataclass_metadata, _pyz80_dataclass_repr_pending',
                 f'    _pyz80_dataclass_metadata({PARAMETERS})']
        if factory:
            lines.append(textwrap.indent(factory.source, '    '))
            args = ','.join(binding_source[kind](field) for _, kind, field in factory.bindings)
            lines.extend(['    if init:', f"        _pyz80_dataclass_install(cls, '__init__', __create_fn__({args}))"])
        # Until recursive repr and formatting are bound, its existence must not
        # be confused with an executable implementation (even for empty types).
        lines += [textwrap.indent(equality.source, '    '),
                  '    if eq:', "        _pyz80_dataclass_install(cls, '__eq__', __create_fn__())",
                  '    def __repr__(self):', '        return _pyz80_dataclass_repr_pending(self)',
                  '    if repr:', "        _pyz80_dataclass_install(cls, '__repr__', __repr__)",
                  '    return cls']
        result['variants'].append({'post_init': post, 'source': '\n'.join(lines) + '\n',
                                   'factory': factory.proof() if factory else None,
                                   'equality_factory': equality.proof()})
    return result


def build_plan(program) -> dict:
    ids = program.artifact.target_coverage['function_id_table']
    constants = program.artifact.compact_document['constants']
    symbols = {s:i for i,s in enumerate(constants) if isinstance(s,str)}
    fields, classes = [], []
    for row in program.graph.get('dataclass_candidates', []):
        start = len(fields)
        fields.extend((symbols[f['name']], int(f['default']), symbols[f['annotation']]) for f in row['fields'])
        classes.append((ids.index(row['class_id']), symbols[row['qualname']], start, len(row['fields']),
                        ids.index(row['variants'][0]['function_id']), ids.index(row['variants'][1]['function_id']),
                        int(row['valid_init']), symbols[row['module']]))
    if len(classes) >= 65535 or len(fields) >= 65535 or any(
            not 0 <= value < 65535 for row in [*classes,*fields] for value in row):
        raise ValueError('dataclass plan exceeds uint16 tables')
    return {'classes': classes, 'fields': fields, 'symbols': [symbols.get(s,65535) for s in SYMBOLS],
            'proof': program.artifact.semantic_sha256, 'contract': 'guarded plain fields; frozen/slots/field, recursive repr, metadata introspection and dynamic comparison protocols pending'}


def render_plan(plan: dict) -> tuple[str, str]:
    header = '#ifndef PYZ80_DATACLASS_PLAN_H\n#define PYZ80_DATACLASS_PLAN_H\n#include "pyz80_target_dataclasses.h"\nextern const PyZ80DataclassPlan PyZ80GeneratedDataclassPlan;\n#endif\n'
    def array(kind, name, rows):
        return f'static const {kind} {name}[]={{' + ','.join('{' + ','.join(str(v)+'u' for v in row) + '}' for row in rows) + '};\n'
    source = '#include "pyz80_dataclass_plan_generated.h"\n'
    source += array('PyZ80DataclassClass', 'classes', plan['classes'] or [(65535,)*8])
    source += array('PyZ80DataclassField', 'fields', plan['fields'] or [(65535,0,65535)])
    source += 'static const uint16_t symbols[]={' + ','.join(str(v)+'u' for v in plan['symbols']) + '};\n'
    source += 'static const uint8_t proof[]={' + ','.join(str(v) for v in bytes.fromhex(plan['proof'])) + '};\n'
    source += 'const PyZ80DataclassPlan PyZ80GeneratedDataclassPlan={classes,fields,symbols,proof,' + str(len(plan['classes'])) + 'u,' + str(len(plan['fields'])) + 'u};\n'
    return header, source
