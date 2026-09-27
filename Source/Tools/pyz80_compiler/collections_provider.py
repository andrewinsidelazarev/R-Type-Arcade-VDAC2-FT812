"""Явная частичная граница стандартного collections, без подмены локальных модулей."""
import ast
from pathlib import Path
import sysconfig


INTRINSICS = {'_pyz80_collections_deque_type': 'collections-deque-type',
              '_pyz80_collections_defaultdict_type': 'collections-defaultdict-type'}
SYMBOLS = ('deque','defaultdict')
CONTRACT = {
    'exports': ['deque','defaultdict'],
    'implemented': ['deque()', 'deque(native iterable or source generator)',
                    'append', 'popleft', 'clear', 'len', 'bool', 'forward iteration', 'type identity',
                    'defaultdict(factory=None, native mapping, **named values)',
                    'defaultdict indexed missing key and explicit __missing__',
                    'defaultdict default_factory attribute read/write',
                    'defaultdict source function/bound-method/closure/generator factories',
                    'defaultdict empty list/dict/set/frozenset/deque/defaultdict/int/bool factories',
                    'defaultdict inherited native dict operations and live views'],
    'pending': ['maxlen', 'indexing', 'appendleft/pop/extend/extendleft/rotate/copy',
                'reverse iteration', 'comparison', 'subclassing', 'type/module introspection',
                'defaultdict iterable-pair constructor and additional mapping methods',
                'defaultdict tuple/str/object factories and arbitrary callable instances/classes',
                'tuple/custom keys and custom hash/equality',
                'other collections exports', 'Python exception objects/handlers'],
}


def source_path() -> Path:
    return (Path(sysconfig.get_path('stdlib')) / 'collections/__init__.py').resolve()


def is_provider_source(name: str, path: Path, source: str) -> bool:
    if name != 'collections' or path.resolve() != source_path():
        return False
    if source != path.read_text(encoding='utf-8'):
        raise ValueError('collections source changed before specialization')
    return True


def bootstrap(source: str) -> str:
    # deque/defaultdict в CPython реализованы в C. Это явный импорт native-типов,
    # не эвристическое распознавание имён в исходной игре.
    return repr(ast.get_docstring(ast.parse(source), clean=False)) + '\n' + '''def _pyz80_collections_deque_type():
    raise NotImplementedError('collections-deque-type')
deque = _pyz80_collections_deque_type()
def _pyz80_collections_defaultdict_type():
    raise NotImplementedError('collections-defaultdict-type')
defaultdict = _pyz80_collections_defaultdict_type()
'''
