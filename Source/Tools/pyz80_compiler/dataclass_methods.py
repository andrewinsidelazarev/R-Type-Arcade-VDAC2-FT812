"""Capture CPython's dataclass method generator, not a handwritten constructor.

Input fields are an already-resolved runtime schema. This module deliberately
does NOT infer decorator identity, inherit fields, evaluate application defaults
or pretend to implement ``dataclasses.dataclass``. Its output is an ordinary
closure factory for the existing Python -> PZVT -> C compiler. A decorator
provider must supply the retained annotation/default/factory objects.
"""
from __future__ import annotations

import ast
import dataclasses as dc
import hashlib
import keyword
from pathlib import Path
import sys
import sysconfig


@dc.dataclass(frozen=True)
class InitField:
    name: str
    kind: str = 'field'  # field, initvar, classvar
    init: bool = True
    kw_only: bool = False
    default: str = 'missing'  # missing, value, factory


@dc.dataclass(frozen=True)
class InitFactory:
    source: str
    bindings: tuple[tuple[str, str, str | None], ...]
    stdlib_path: Path
    stdlib_sha256: str
    generator_ast_sha256: str

    def proof(self) -> dict:
        return {'format': 'pyz80.cpython-dataclass-init-factory.v1',
                'source': self.source, 'bindings': [list(row) for row in self.bindings],
                'stdlib_path': str(self.stdlib_path), 'stdlib_sha256': self.stdlib_sha256,
                'generator_ast_sha256': self.generator_ast_sha256,
                'source_sha256': hashlib.sha256(self.source.encode()).hexdigest(),
                'contract': 'resolved fields only; decorator/field resolution is not implemented here'}


@dc.dataclass(frozen=True)
class _Binding:
    kind: str
    field: str | None = None


def dataclass_source_path() -> Path:
    path = (Path(sysconfig.get_path('stdlib')) / 'dataclasses.py').resolve()
    if sys.version_info[:2] != (3, 12) or Path(dc.__file__).resolve() != path or not path.is_file():
        raise ValueError('dataclass generator requires the pinned CPython 3.12 standard library')
    return path


def capture_eq_factory(names: tuple[str, ...]) -> InitFactory:
    """Capture the exact CPython equality method; never evaluate user fields."""
    if type(names) is not tuple or len(set(names)) != len(names) or any(
            not isinstance(n, str) or not n.isidentifier() or keyword.iskeyword(n) for n in names):
        raise ValueError('invalid dataclass equality field names')
    path = dataclass_source_path()
    data = path.read_bytes()
    tree = ast.parse(data, filename=str(path))
    required = {'_cmp_fn', '_tuple_str', '_create_fn'}
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in required]
    if {n.name for n in selected} != required:
        raise ValueError('pinned equality generator functions missing')
    generator = ast.Module(body=selected, type_ignores=[])
    namespace = dict(vars(dc))
    exec(compile(generator, str(path), 'exec', dont_inherit=True), namespace)
    captured = []
    class Captured(Exception):
        pass
    def capture(source, globals, locals):
        caller = sys._getframe(1)
        if caller.f_code.co_name != '_create_fn' or captured or caller.f_locals['locals']:
            raise ValueError('unexpected equality factory exec boundary')
        captured.append(source)
        raise Captured
    namespace['exec'] = capture
    fields = [type('ResolvedField', (), {'name': n})() for n in names]
    try:
        namespace['_cmp_fn']('__eq__', '==', namespace['_tuple_str']('self', fields),
                             namespace['_tuple_str']('other', fields), globals={})
    except Captured:
        pass
    if len(captured) != 1:
        raise ValueError('equality generator did not emit one factory')
    return InitFactory(captured[0], (), path, hashlib.sha256(data).hexdigest(),
        hashlib.sha256(ast.dump(generator, include_attributes=False).encode()).hexdigest())


def capture_init_factory(fields: tuple[InitField, ...], *, frozen: bool = False,
                         slots: bool = False, has_post_init: bool = False) -> InitFactory:
    """Run ONLY sealed stdlib string generation; intercept its exec boundary.

    Default values are opaque binding tokens: no user value is imported, called,
    represented, copied or evaluated. The factory source, including annotations,
    sentinel tests, assignment order and dynamic post-init lookup, is returned
    byte-for-byte from CPython's own ``_create_fn``.
    """
    if type(fields) is not tuple:
        raise ValueError('resolved dataclass fields must be an immutable tuple')
    if any(type(flag) is not bool for flag in (frozen, slots, has_post_init)):
        raise ValueError('resolved dataclass flags must be bools')
    names = set()
    for field in fields:
        if (type(field) is not InitField or not isinstance(field.name, str) or
                not field.name.isidentifier() or keyword.iskeyword(field.name) or
                field.name in names or field.kind not in ('field', 'initvar', 'classvar') or
                type(field.init) is not bool or type(field.kw_only) is not bool or
                field.default not in ('missing', 'value', 'factory') or
                (field.kind != 'field' and field.default == 'factory')):
            raise ValueError('invalid resolved dataclass field schema')
        names.add(field.name)
    path = dataclass_source_path()
    data = path.read_bytes()
    tree = ast.parse(data, filename=str(path))
    required = {'_fields_in_init_order', '_field_assign', '_field_init',
                '_init_param', '_init_fn', '_create_fn'}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in required]
    if {node.name for node in selected} != required:
        raise ValueError('pinned dataclass generator functions are missing')
    generator = ast.Module(body=selected, type_ignores=[])
    generator_hash = hashlib.sha256(ast.dump(generator, include_attributes=False).encode()).hexdigest()
    # A private namespace, never monkey-patch the host dataclasses module.
    namespace = dict(vars(dc))
    exec(compile(generator, str(path), 'exec', dont_inherit=True, optimize=0), namespace)
    resolved = []
    for field in fields:
        if field.kind == 'classvar':
            continue  # _process_class excludes ClassVars before calling _init_fn.
        value = _Binding('default', field.name) if field.default == 'value' else dc.MISSING
        factory = _Binding('factory', field.name) if field.default == 'factory' else dc.MISSING
        row = dc.field(default=value, default_factory=factory, init=field.init, kw_only=field.kw_only)
        row.name = field.name
        row.type = _Binding('annotation', field.name)
        row._field_type = dc._FIELD_INITVAR if field.kind == 'initvar' else dc._FIELD
        resolved.append(row)

    class Captured(Exception):
        pass

    captured = []
    def capture(source, globals, locals):
        # The private generator calls exec only once, from _create_fn. Snapshot
        # its argument bindings, not application objects or a generated function.
        caller = sys._getframe(1)
        if caller.f_code.co_name != '_create_fn' or captured or type(source) is not str:
            raise ValueError('unexpected dataclass generator exec boundary')
        captured.append((source, dict(caller.f_locals['locals'])))
        raise Captured

    namespace['exec'] = capture
    std, kw = namespace['_fields_in_init_order'](resolved)
    try:
        namespace['_init_fn'](resolved, std, kw, frozen, has_post_init,
                              '__dataclass_self__' if 'self' in names else 'self', {}, slots)
    except Captured:
        pass
    if len(captured) != 1:
        raise ValueError('dataclass generator did not emit exactly one closure factory')
    source, values = captured[0]
    compile(source, '<dataclass-init-factory>', 'exec', dont_inherit=True, optimize=0)
    bindings = []
    for name, value in values.items():
        if type(value) is _Binding:
            bindings.append((name, value.kind, value.field))
        elif value is dc._HAS_DEFAULT_FACTORY:
            bindings.append((name, 'factory-sentinel', None))
        elif value is object:
            bindings.append((name, 'builtin-object', None))
        elif value is None:
            bindings.append((name, 'none', None))
        else:
            raise ValueError('unrecognized binding produced by pinned dataclass generator')
    return InitFactory(source, tuple(bindings), path, hashlib.sha256(data).hexdigest(), generator_hash)
