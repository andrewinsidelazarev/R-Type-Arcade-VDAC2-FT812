#!/usr/bin/env python3
"""Generate the fail-closed Z80 adapter dispatch table from coherent PZVT."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source/Tools"))

from pyz80_compiler.whole_program_vm_backend import decode_compact_target_vm
from pyz80_compiler.class_protocol import CLASS_PROTOCOL_NAMES
from pyz80_translation_checkpoint import validate_translation_checkpoint


OP_NAMES = {
    "allocate-instance": "PYZ80_TARGET_ALLOCATE_INSTANCE",
    "load-attribute": "PYZ80_TARGET_LOAD_ATTRIBUTE",
    "store-attribute": "PYZ80_TARGET_STORE_ATTRIBUTE",
    "build-list": "PYZ80_TARGET_BUILD_LIST",
    "build-tuple": "PYZ80_TARGET_BUILD_TUPLE",
    "build-slice": "PYZ80_TARGET_BUILD_SLICE",
    "collections-deque-type": "PYZ80_TARGET_COLLECTIONS_DEQUE_TYPE",
    "collections-defaultdict-type": "PYZ80_TARGET_COLLECTIONS_DEFAULTDICT_TYPE",
    "list-append": "PYZ80_TARGET_LIST_APPEND",
    "load-subscript": "PYZ80_TARGET_LOAD_SUBSCRIPT",
    "store-subscript": "PYZ80_TARGET_STORE_SUBSCRIPT",
    "delete-subscript": "PYZ80_TARGET_DELETE_SUBSCRIPT",
    "python-binary": "PYZ80_TARGET_BINARY",
    "python-inplace-binary": "PYZ80_TARGET_BINARY",
    "python-compare": "PYZ80_TARGET_COMPARE",
    "python-unary": "PYZ80_TARGET_UNARY",
    "python-get-iterator": "PYZ80_TARGET_GET_ITERATOR",
    "python-get-iterator-immediate": "PYZ80_TARGET_GET_ITERATOR",
    "python-iter-next": "PYZ80_TARGET_ITER_NEXT",
    "iteration-has-value": "PYZ80_TARGET_ITER_HAS_VALUE",
    "iteration-value": "PYZ80_TARGET_ITER_VALUE",
    "unpack-sequence": "PYZ80_TARGET_UNPACK_SEQUENCE",
    "unpack-item": "PYZ80_TARGET_UNPACK_ITEM",
    "store-generated-dataclass-fields": "PYZ80_TARGET_STORE_DATACLASS_FIELDS",
    "require-callable": "PYZ80_TARGET_REQUIRE_CALLABLE",
    "resolve-finite-callable-identity": "PYZ80_TARGET_RESOLVE_CALLABLE",
    "extract-finite-bound-callable-receiver": "PYZ80_TARGET_BOUND_RECEIVER",
    "capture-closure-cell": "PYZ80_TARGET_CAPTURE_CELL",
    "make-source-function": "PYZ80_TARGET_MAKE_CLOSURE",
    "make-source-function-defaults": "PYZ80_TARGET_MAKE_CLOSURE_DEFAULTS",
    "load-source-globals": "PYZ80_TARGET_LOAD_GLOBALS",
    "load-name": "PYZ80_TARGET_LOAD_LEXICAL_NAME",
    "load-global-name": "PYZ80_TARGET_LOAD_GLOBAL_NAME",
    "store-global-name": "PYZ80_TARGET_STORE_GLOBAL_NAME",
    "load-class-name": "PYZ80_TARGET_LOAD_CLASS_NAME",
    "load-class-free-name": "PYZ80_TARGET_LOAD_CLASS_FREE_NAME",
    "store-class-name": "PYZ80_TARGET_STORE_CLASS_NAME",
    "python-build-class": "PYZ80_TARGET_BUILD_CLASS",
    "setup-class-annotations": "PYZ80_TARGET_SETUP_CLASS_ANNOTATIONS",
    "setup-global-annotations": "PYZ80_TARGET_SETUP_GLOBAL_ANNOTATIONS",
    "build-dict": "PYZ80_TARGET_BUILD_DICT",
    "build-set": "PYZ80_TARGET_BUILD_SET",
    "set-add": "PYZ80_TARGET_SET_ADD",
    "generator-next-enter": "PYZ80_TARGET_GENERATOR_NEXT_ENTER",
    "dataclass-resolve": "PYZ80_TARGET_DATACLASS_RESOLVE",
    "dataclass-install": "PYZ80_TARGET_DATACLASS_INSTALL",
    "dataclass-metadata": "PYZ80_TARGET_DATACLASS_METADATA",
    "dataclass-repr-pending": "PYZ80_TARGET_DATACLASS_REPR_PENDING",
}

OPERATORS = {
    "add": "PYZ80_TARGET_OP_ADD",
    "sub": "PYZ80_TARGET_OP_SUB",
    "mul": "PYZ80_TARGET_OP_MUL",
    "floordiv": "PYZ80_TARGET_OP_FLOORDIV",
    "truediv": "PYZ80_TARGET_OP_TRUEDIV",
    "mod": "PYZ80_TARGET_OP_MOD",
    "bitand": "PYZ80_TARGET_OP_BITAND",
    "bitor": "PYZ80_TARGET_OP_BITOR",
    "bitxor": "PYZ80_TARGET_OP_BITXOR",
    "lshift": "PYZ80_TARGET_OP_LSHIFT",
    "rshift": "PYZ80_TARGET_OP_RSHIFT",
    "eq": "PYZ80_TARGET_OP_EQ",
    "ne": "PYZ80_TARGET_OP_NE",
    "lt": "PYZ80_TARGET_OP_LT",
    "le": "PYZ80_TARGET_OP_LE",
    "gt": "PYZ80_TARGET_OP_GT",
    "ge": "PYZ80_TARGET_OP_GE",
    "neg": "PYZ80_TARGET_OP_NEG",
    "pos": "PYZ80_TARGET_OP_POS",
    "invert": "PYZ80_TARGET_OP_INVERT",
    "not": "PYZ80_TARGET_OP_NOT",
    "is": "PYZ80_TARGET_OP_IS",
    "is-not": "PYZ80_TARGET_OP_IS_NOT",
    "in": "PYZ80_TARGET_OP_IN",
    "not-in": "PYZ80_TARGET_OP_NOT_IN",
}

BUILTINS = {name: f"PYZ80_BUILTIN_{name.upper()}" for name in ("bool", "len", "getattr", "range", "object", "super", "set", "frozenset")}
BUILTINS['get'] = 'PYZ80_BUILTIN_DICT_GET'
BUILTINS.update({name:f'PYZ80_BUILTIN_SET_{name.upper()}' for name in ('add','remove','discard','clear')})
BUILTINS.update({name:f'PYZ80_BUILTIN_{name.upper()}' for name in ('next','iter','any','tuple')})
BUILTINS.update({name:f'PYZ80_BUILTIN_{name.upper()}' for name in ('enumerate','sorted','min','max','reversed')})
BUILTINS.update({name:f'PYZ80_BUILTIN_{name.upper()}' for name in ('isinstance','issubclass','hasattr','int','str','list','dict')})
BUILTINS.update({name:f'PYZ80_KEYWORD_{name.upper()}' for name in ('key','reverse','start','iterable','default')})
# Идентичность импортируемого типа. Не входит в PYZ80_BUILTIN_IS_GLOBAL.
BUILTINS['deque'] = 'PYZ80_BUILTIN_DEQUE'
BUILTINS['defaultdict'] = 'PYZ80_BUILTIN_DEFAULTDICT'
BUILTINS['default_factory'] = 'PYZ80_DEFAULT_FACTORY_ATTRIBUTE'
BUILTINS['__missing__'] = 'PYZ80_BUILTIN_DEFAULTDICT_MISSING'
BUILTINS['bytes'] = 'PYZ80_BUILTIN_BYTES'
BUILTINS['bytearray'] = 'PYZ80_BUILTIN_BYTEARRAY'
BUILTINS['staticmethod'] = 'PYZ80_BUILTIN_STATICMETHOD'
# Одно имя метода может принадлежать разным типам; выбор делает тип получателя.
COLLECTION_METHODS = tuple((name, f'PYZ80_BUILTIN_{kind}_{name.upper()}')
    for kind, names in (('LIST', ('append', 'clear', 'pop', 'extend')),
                        ('DICT', ('pop', 'clear', 'keys', 'values', 'items')),
                        ('DEQUE', ('append', 'popleft', 'clear')))
    for name in names)


def container_protocol(symbols: dict[str, int]) -> dict:
    """Возможности runtime, а не утверждение о разрешении динамических вызовов."""
    methods = [('dict', 'get', BUILTINS['get'])]
    methods += [('set', name, BUILTINS[name]) for name in ('add', 'remove', 'discard', 'clear')]
    methods += [(operation.split('_')[2].lower(), name, operation) for name, operation in COLLECTION_METHODS]
    methods += [('defaultdict',name,'PYZ80_BUILTIN_DICT_'+name.upper())
                for name in ('get','pop','clear','keys','values','items')]
    methods += [('defaultdict','__missing__','PYZ80_BUILTIN_DEFAULTDICT_MISSING')]
    return {
        'dispatch': 'exact native receiver type; source class methods remain class-provider calls',
        'registered_methods': [{'receiver':kind, 'name':name, 'symbol':symbols[name], 'operation':operation}
                               for kind,name,operation in methods if name in symbols],
        'dynamic_call_sites_proved': False,
        'buffer_protocol': {
            'attachment': 'PyZ80Target_AttachGenerators for construction; PyZ80Target_AttachSequences for transforms/comparison',
            'storage': '64 raw bytes per block in eight existing 8-byte item slots; stable owner/generation handles; GC does not interpret payload bytes as references',
            'construction': 'zero arguments, nonnegative int32/bool length, or native iterable/source generator of octets; bytes(existing bytes) retains identity',
            'operations': ['len/truth', 'indexed read', 'bytearray indexed write', 'forward/reverse iteration',
                           'slices and repetition', 'same-length bytearray slice assignment from bytes/bytearray',
                           'lexicographic comparison between bytes/bytearray', 'integer in/not in', 'native type checks'],
            'identity': 'bytearray copies are distinct; bytes full unit-stride slice and repeat by one retain identity; live empty bytes are shared',
            'mutation': 'slice assignment snapshots the complete right-hand buffer before writes, including self/negative-stride aliases; resizing is rejected',
            'budget': 'one consumed/copied/compared byte per VM step; append allocates at most one 64-byte block, never copies the prefix; random access may traverse block links',
            'limits': '65535 bytes per buffer plus caller-owned heap capacity; checked overflow, no truncation or wrapping',
            'pending': ['serialized bytes literals', 'str/encoding/custom buffer protocol constructors', 'resizing slice assignment/deletion',
                        'bytearray in-place repetition by more than one', 'byte methods and subsequence membership',
                        'mixed-type comparison/custom equality and byte keys/hash', 'subclassing/introspection',
                        'catchable Python exceptions', 'full banked heap/stack/frame-time integration'],
        },
        'staticmethod_protocol': {
            'storage': 'GC-retained raw wrapped value; class/instance/inherited/super lookup returns it without binding self',
            'direct_call': 'supported source function/closure/bound method through ordinary argument binder and VM frames',
            'types': 'native staticmethod identity for isinstance/issubclass',
            'pending': ['direct wrapped builtin/custom callables', '__func__/__wrapped__/metadata introspection',
                        'subclassing and general descriptor protocol', 'classmethod', 'catchable exceptions'],
        },
        'defaultdict_protocol': {
            'binding': 'sealed partial collections provider; imported type identity, never an implicit global builtin',
            'attachment': 'PyZ80Target_AttachDefaultDict; 8-byte SDCC continuation and four GC roots per VM depth',
            'storage': 'GC-traced native dict plus retained raw default_factory; inherited dict key ordering and epochs',
            'missing': 'indexed lookup and explicit __missing__; zero-argument factory, insert only after successful return',
            'factories': ['source functions/closures/bound methods', 'lazy source generator creation',
                          'empty list/dict/set/frozenset/deque/defaultdict/int/bool', 'supported zero-argument native methods'],
            'mapping': ['native mapping/keyword constructor', 'get/pop/clear/keys/values/items',
                        'len/truth/subscript/assignment/deletion/membership', 'forward/reverse iteration and live views'],
            'budget': 'constructor copies at most one entry per VM step; source factories use VM frames, never recursive C VM runs',
            'pending': ['iterable-pair constructor and other dict methods', 'tuple/str/object factories',
                        'source class/custom-callable factories', 'custom keys/hash/equality', 'subclassing/introspection',
                        'catchable Python exceptions', 'final bank/stack/frame-time proof'],
        },
        'deque_protocol': {
            'binding': 'sealed partial collections source provider; deque is not a global builtin',
            'storage': 'linked blocks of 16 GC-traced items; stable owner and generation handles',
            'operations': ['constructor from native iterable/source generator', 'append', 'popleft', 'clear',
                           'len', 'truth', 'forward iteration', 'native type identity'],
            'budget': 'one consumed item per VM step; append initializes at most 16 cells; popleft/clear never shift the queue',
            'mutation': 'iteration checks a non-wrapping 32-bit epoch, including after exhaustion',
            'limits': '65535 elements plus configured heap capacity; no silent drops on exhaustion',
            'pending': ['maxlen', 'indexing', 'other deque methods', 'reverse iteration', 'custom equality',
                        'subclassing/introspection', 'full collections exports', 'final Z80 frame-time proof'],
        },
        'none_attribute_protocol': {
            'known_attributes': dir(None),
            'contract': 'sealed pinned-CPython inventory; absent getattr/hasattr works, present unbound attributes fail closed',
        },
        'sequence_transform_protocol': {
            'attachment': 'PyZ80Target_AttachSequences; 20-byte SDCC request and two GC roots per VM depth',
            'repetition': 'native list/tuple/bytes/bytearray times int32/bool, either operand order; shallow element identities',
            'inplace': 'list *= commits a completed item vector to the same owner; failure does not publish a partial repeat',
            'slices': 'list/tuple/bytes/bytearray lower:upper:step with None/int32/bool; negative bounds and steps clipped without signed overflow',
            'identity': 'new list copies; full unit-stride tuple slice and tuple times one retain their owner',
            'budget': 'one copied item per VM step, no C recursion; bounds and checked result extent computed before copying',
            'append': 'tail-of-arena list growth uses one new item slot without relocating its prefix, including after GC',
            'capacity': 'full temporary result must fit before copying; final target storage and stack/frame budgets remain unproved',
            'pending': ['list slice assignment, resizing bytearray slices, slice deletion and standalone slice constructor', 'range/string/custom slicing and __index__',
                        'string/custom sequence repetition', 'catchable allocation/type errors', 'final banked integration'],
        },
        'type_check_protocol': {
            'attachment': 'PyZ80Target_AttachClasses and existing call-binding workspace',
            'source_classes': 'retained class identity and C3 MRO; no per-game names or copied type dictionaries',
            'native_types': ['object','bool','int','str','list','tuple','dict','set','frozenset','range','enumerate','deque','defaultdict','bytes','bytearray','staticmethod'],
            'constructor_support': 'list uses the attached generator consumer; int/str/dict constructors remain unsupported',
            'classinfo': 'type or nested tuple; left-to-right short circuit, including invalid later members',
            'storage': 'no heap; tuple path borrows binding_scratch, depth bounded by binding_capacity; 10-byte SDCC class frame',
            'budget': 'at most one tuple/leaf traversal per VM step; each leaf scans saved MRO without C recursion',
            'hasattr': 'native attribute lookup; unsupported/error is distinct from absence',
            'pending': ['custom metaclasses and instance/subclass checks', 'union classinfo and serialized/float types',
                        'custom attribute/descriptors and catchable exceptions', 'final source-specific stack/frame-time bounds'],
        },
        'list_constructor_protocol': {
            'attachment': 'PyZ80Target_AttachGenerators; existing three GC roots per VM depth',
            'sources': 'zero arguments or one native list/tuple/range/dict/view/iterator/enumerate or source generator',
            'result': 'new mutable shallow copy, including empty input; no tuple/list identity shortcut',
            'budget': 'at most one copied element per VM step; nested consumers use VM continuations, not C recursion',
            'pending': ['set/string/custom iteration', 'catchable exceptions', 'source-bounded capacity and target frame-time proof'],
        },
        'sequence_membership_protocol': {
            'attachment': 'PyZ80Target_AttachGenerators; same request and three GC roots per depth',
            'sources': 'native list/tuple/range/dict views/iterator/enumerate and source generator; dict/set retain key lookup',
            'comparison': 'identity shortcut then supported scalar/flat-tuple equality; unknown rich equality fails explicitly',
            'consumption': 'in/not in short circuit at first match; iterator/source generator retains remaining position',
            'budget': 'one candidate per VM step, without C recursion; a flat-tuple candidate scans its scalar prefix',
            'pending': ['custom __contains__/__eq__ and nested tuple comparison', 'string iteration', 'catchable exceptions', 'target frame-time proof'],
        },
        'reversed_protocol': {
            'sources': 'native list/tuple/bytes/bytearray/range/dict/views; no source copy; retained owner and original end index',
            'mutation': 'live list indices, appended tail ignored, sticky exhaustion; dict key mutation rejected, value overwrite allowed',
            'storage': 'one existing iterator node; same GC roots, no C recursion',
            'arithmetic': 'range uses one unsigned multiplication on first next, then subtraction; sequence cursor decrements with zero guard',
            'pending': ['string/custom reversal and sequence protocol', 'reversed as classinfo', 'catchable exceptions', 'target frame-time proof'],
        },
        'list_extend_protocol': {
            'attachment': 'PyZ80Target_AttachGenerators; existing three GC roots per VM depth',
            'sources': 'native list/tuple/range/dict/view/iterator/enumerate and source generators',
            'mutation': 'same owner and None result; one appended item per VM step; partial prefix retained on iterator failure',
            'self_extension': 'initial list length only for direct self; an iterator alias observes live growth',
            'pending': ['custom and string iteration', 'catchable iterator exceptions',
                        'source-bounded capacity and target frame-time proof'],
        },
        'extrema_protocol': {
            'attachment': 'PyZ80Target_AttachSort; two positional int32/bool values also supported without control provider',
            'forms': 'multiple positional values or one iterable; keyword-only key/default; default only for iterable form',
            'sources': 'native list/tuple/range/dict/view/iterator/enumerate and source generators',
            'key': 'None or retained ordinary source callable; called once per item before advancing iterator',
            'ordering': 'int32/bool or flat tuple keys with supported scalar comparisons; first equal item retained',
            'storage': 'existing seven GC roots and request per depth; no materialized input or sort buffers',
            'budget': 'at most one candidate per VM step; two scalar arguments use one comparison without heap/continuation',
            'pending': ['custom/string iteration and arbitrary builtin key callables',
                        'general __lt__/__gt__/nested tuple/string/float comparisons',
                        'catchable exceptions and target frame-time proof'],
        },
        'enumerate_protocol': {
            'sources': 'native list/tuple/range/dict/view/iterator/enumerate; source iterator acquired at construction',
            'indices': 'signed int32, bool start converted to int; overflow fails without wrapping',
            'keywords': ['iterable', 'start'],
            'pending': ['generator and custom iterators', 'string iteration', 'arbitrary-precision index'],
        },
        'sorted_protocol': {
            'attachment': 'PyZ80Target_AttachSort after the other control providers',
            'algorithm': 'stable bottom-up merge, O(n log n); at most one merged element per VM step',
            'input': 'native iterable/iterator/enumerate; snapshot completed before key calls',
            'key': 'None or sealed ordinary Python callable; retained self/defaults/cells; one call per item',
            'ordering': 'int32/bool or flat tuple keys with supported scalar comparisons',
            'keywords': ['key', 'reverse'],
            'reverse': 'int32/bool, stable in both directions',
            'storage': 'caller-owned request and seven GC roots per VM depth; four heap vectors up to n values each',
            'pending': ['generator/custom input iterator', 'general __lt__/nested tuple/string/float comparisons',
                        'arbitrary builtin key callables', 'source-bounded capacity and target frame-time proof'],
        },
        'dict_views': ['len', 'truth', 'iter', 'reversed', 'keys', 'values', 'items'],
        'dict_view_owner': 'retained live dictionary; tuple(view) and list(view) create snapshots',
        'dict_iteration_key_mutation': 'unsupported: next fails after a key-set change, including same-size replacement; value overwrites allowed',
        'dict_keys': ['None', 'bool', 'int32', 'sealed_string_symbol'],
        'list_indices': ['int32', 'bool'],
        'pending': ['slice assignment/deletion and custom __index__', 'view set operations',
                    'custom key hash/equality', 'catchable container exceptions'],
    }


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def build_adapter_specs(adapters: list[dict], constants: list,
                        function_ids: list[str] | None = None,
                        function_signatures: list | None = None) -> dict:
    """Bind generic operations and source field keys, without per-game code."""
    specs = []
    positional_call_flags = []
    field_keys = []
    field_slices = {}
    dataclass_slices = set()
    closure_slices = set()
    function_ids = function_ids or []
    if (any(not isinstance(value, str) or not value for value in function_ids) or
            len(set(function_ids)) != len(function_ids) or len(function_ids) >= 65535):
        raise RuntimeError("invalid numeric function identity table")
    functions = {value: index for index, value in enumerate(function_ids)}
    class_bodies = {row.get("attributes", {}).get("source_callable_id"):
                    3 if row.get("attributes", {}).get("implicit_class_cell") else 1 for row in adapters
                    if row.get("op") == "make-source-function" and
                    row.get("attributes", {}).get("body_execution") == "class-suite"}
    dispatch_functions = []
    dispatch_slices = {}
    symbols = {value: index for index, value in enumerate(constants)
               if isinstance(value, str)}
    call_layout_offsets, call_layout_keys = [], []
    layout_slices = {}
    call_signatures, parameter_names = [], []
    if function_signatures is not None and len(function_signatures) != len(function_ids):
        raise RuntimeError("signature table differs from function identities")
    for parameters in function_signatures or [None] * len(function_ids):
        if parameters is None or any(p.get("kind") not in
                ("positional-only", "positional-or-keyword", "keyword-only") for p in parameters):
            call_signatures.append((0, 0, 0, 0, 0))
            continue
        names = [p["name"] for p in parameters]
        kinds = [p["kind"] for p in parameters]
        order = {"positional-only":0, "positional-or-keyword":1, "keyword-only":2}
        if (len(names) > 255 or len(names) != len(set(names)) or
                any(name not in symbols for name in names) or
                kinds != sorted(kinds, key=order.__getitem__)):
            raise RuntimeError("invalid source call signature")
        call_signatures.append((len(parameter_names), len(names),
            sum(kind != "keyword-only" for kind in kinds), kinds.count("positional-only"), 1))
        parameter_names.extend(symbols[name] for name in names)
        if len(parameter_names) > 65535:
            raise RuntimeError("parameter-name table exceeds uint16")
    supported = Counter()
    unsupported = Counter()
    for row in adapters:
        source_op = str(row.get("op", ""))
        target_op = OP_NAMES.get(source_op, "PYZ80_TARGET_UNSUPPORTED")
        attributes = row.get("attributes", {})
        if source_op in {"build-list", "build-tuple", "build-set"} and any(
                item != "item" for item in attributes.get("item_layout", [])):
            target_op = "PYZ80_TARGET_UNSUPPORTED"
        if source_op == "build-dict" and any(item != "key-value" for item in attributes.get("entry_layout", [])):
            target_op = "PYZ80_TARGET_UNSUPPORTED"
        count = row.get("argument_count")
        if type(count) is not int or not 0 <= count <= 255:
            raise RuntimeError(f"invalid argument count in adapter {row}")
        layout = attributes.get("argument_layout")
        positional_call_flags.append(int(source_op == "python-call" and isinstance(layout, (list, tuple))
            and count == len(layout) + 1 and all(isinstance(pair, (list, tuple)) and
                tuple(pair) == ("positional", None) for pair in layout)))
        ordinary = (source_op == "python-call" and isinstance(layout, (list, tuple)) and count == len(layout) + 1 and
            all(isinstance(pair, (list, tuple)) and len(pair) == 2 and
                (tuple(pair) == ("positional", None) or (pair[0] == "keyword" and isinstance(pair[1], str)))
                for pair in layout))
        if ordinary:
            if any(kind == "keyword" and name not in symbols for kind, name in layout):
                raise RuntimeError("keyword identity absent from constant pool")
            key = tuple(65535 if kind == "positional" else symbols[name] for kind, name in layout)
            if key not in layout_slices:
                layout_slices[key] = len(call_layout_keys)
                call_layout_keys.extend(key)
            call_layout_offsets.append(layout_slices[key])
            if len(call_layout_keys) > 65534:
                raise RuntimeError("call layout table exceeds uint16 sentinel")
        else:
            call_layout_offsets.append(65535)
        auxiliary = int(source_op == "python-inplace-binary")
        if source_op in ('collections-deque-type','collections-defaultdict-type') and (count != 0 or attributes.get('library') != 'cpython-3.12.collections'):
            raise RuntimeError('invalid explicit collections library entry')
        if source_op.startswith('dataclass-'):
            counts = {'dataclass-resolve': 11, 'dataclass-install': 3,
                      'dataclass-metadata': 11, 'dataclass-repr-pending': 1}
            if source_op not in counts or count != counts[source_op] or attributes.get('library') != 'cpython-3.12.dataclasses':
                raise RuntimeError('invalid explicit dataclass library entry')
        if source_op in ("load-source-globals", "load-global-name", "store-global-name", "load-class-name", "load-class-free-name", "store-class-name", "setup-class-annotations", "setup-global-annotations") or (source_op == "load-name" and "owner_callable_id" in attributes):
            identity = attributes.get("owner_callable_id")
            expected_count = 2 if source_op in ("store-global-name", "store-class-name") else (0 if source_op == "load-source-globals" else 1)
            if identity not in functions or count != expected_count:
                raise RuntimeError("source globals have no exact function owner")
            auxiliary = functions[identity]
        if source_op in ("make-source-function", "make-source-function-defaults"):
            if attributes.get("generator_next_body_sha256"):
                target_op = ("PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS" if source_op.endswith("-defaults")
                             else "PYZ80_TARGET_MAKE_GENERATOR_CLOSURE")
            identity = attributes.get("source_callable_id")
            names = attributes.get("closure_names")
            defaults = attributes.get("default_names", []) if source_op == "make-source-function-defaults" else []
            if (identity not in functions or not isinstance(names, list) or not isinstance(defaults, list) or
                    count != len(names) + len(defaults) + 1 or
                    any(not isinstance(name, str) or name not in symbols for name in names) or
                    any(not isinstance(name, str) or name not in symbols for name in defaults) or
                    len(set(defaults)) != len(defaults) or len(set(names)) != len(names)):
                raise RuntimeError("source closure has no exact target/cell schema")
            key = ((functions[identity], len(names), len(defaults), *(symbols[name] for name in [*names, *defaults]))
                   if source_op == "make-source-function-defaults" else
                   (functions[identity], *(symbols[name] for name in names)))
            closure_slices.add(key)
            if key not in field_slices:
                field_slices[key] = len(field_keys)
                field_keys.extend(key)
            auxiliary = field_slices[key]
            if len(field_keys) > 65535:
                raise RuntimeError("closure field-key table exceeds uint16")
        if source_op in {"resolve-finite-callable-identity", "extract-finite-bound-callable-receiver"}:
            candidates = row.get("candidate_callable_ids")
            if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 255 or
                    any(not isinstance(value, str) or value not in functions for value in candidates) or
                    len(set(candidates)) != len(candidates) or
                    count != (2 if source_op == "extract-finite-bound-callable-receiver" else 1)):
                raise RuntimeError("finite callable dispatch has no exact numeric candidates")
            key = tuple(functions[value] for value in candidates)
            if key not in dispatch_slices:
                dispatch_slices[key] = len(dispatch_functions)
                dispatch_functions.extend((len(key), *key))
            auxiliary = dispatch_slices[key]
            if len(dispatch_functions) > 65535:
                raise RuntimeError("finite callable dispatch table exceeds uint16")
        if source_op == "store-generated-dataclass-fields":
            names = row.get("field_names")
            if (not isinstance(names, list) or count != len(names) + 1 or
                    any(not isinstance(name, str) or not name for name in names) or
                    len(set(names)) != len(names)):
                raise RuntimeError("invalid generated dataclass field schema")
            if any(name not in symbols for name in names):
                raise RuntimeError("dataclass field identity absent from compact constant pool")
            keys = tuple(symbols[name] for name in names)
            dataclass_slices.add(keys)
            if keys not in field_slices:
                field_slices[keys] = len(field_keys)
                field_keys.extend(keys)
            auxiliary = field_slices[keys]
            if len(field_keys) > 65535:
                raise RuntimeError("dataclass field-key table exceeds uint16")
        specs.append((target_op, count, auxiliary))
        (unsupported if target_op == "PYZ80_TARGET_UNSUPPORTED" else supported)[source_op] += 1
    return {"specs": specs, "field_keys": field_keys,
            "class_body_flags": [class_bodies.get(name, 0) for name in function_ids],
            "class_symbols": [symbols.get(name, 65535) for name in CLASS_PROTOCOL_NAMES],
            "call_signatures": call_signatures, "parameter_names": parameter_names,
            "call_layout_offsets": call_layout_offsets, "call_layout_keys": call_layout_keys,
            "positional_call_flags": positional_call_flags,
            "builtin_symbols": [(symbols[name], operation) for name, operation in (*BUILTINS.items(), *COLLECTION_METHODS) if name in symbols] +
                [(symbols[name], 'PYZ80_NONE_ATTRIBUTE_KNOWN') for name in dir(None) if name in symbols] +
                [(65535, 'PYZ80_NONE_ATTRIBUTE_KNOWN')],
            "container_protocol": container_protocol(symbols),
            "dataclass_key_count": sum(map(len, dataclass_slices)),
            "closure_key_word_count": sum(map(len, closure_slices)),
            "dispatch_functions": dispatch_functions, "function_count": len(function_ids),
            "operators": [(index, OPERATORS[value]) for index, value in enumerate(constants)
                          if isinstance(value, str) and value in OPERATORS],
            "supported": supported, "unsupported": unsupported}


def render_adapter_tables(plan: dict, arities: list[int]) -> tuple[str, str]:
    """Render one validated numeric plan for either game or module images."""
    specs, operator_specs, field_keys = plan["specs"], plan["operators"], plan["field_keys"]
    if len(arities) != plan['function_count'] or any(type(value) is not int or not 0 <= value <= 65535 for value in arities):
        raise RuntimeError("positional signature table differs from adapter plan")
    header = (
        "/* Generated from the coherent PZVT adapter table. */\n"
        "#ifndef PYZ80_TARGET_ADAPTER_PLAN_GENERATED_H\n"
        "#define PYZ80_TARGET_ADAPTER_PLAN_GENERATED_H\n\n"
        "#include \"pyz80_target_object_runtime.h\"\n\n"
        f"#define PYZ80_GENERATED_ADAPTER_COUNT {len(specs)}u\n"
        f"#define PYZ80_GENERATED_OPERATOR_COUNT {len(operator_specs)}u\n"
        f"#define PYZ80_GENERATED_FIELD_KEY_COUNT {len(field_keys)}u\n"
        f"#define PYZ80_GENERATED_FUNCTION_COUNT {plan['function_count']}u\n"
        f"#define PYZ80_GENERATED_DISPATCH_WORD_COUNT {len(plan['dispatch_functions'])}u\n"
        "extern const PyZ80TargetAdapterSpec PyZ80GeneratedAdapters["
        "PYZ80_GENERATED_ADAPTER_COUNT ? PYZ80_GENERATED_ADAPTER_COUNT : 1];\n"
        "extern const PyZ80TargetOperatorSpec PyZ80GeneratedOperators["
        "PYZ80_GENERATED_OPERATOR_COUNT ? PYZ80_GENERATED_OPERATOR_COUNT : 1];\n"
        "extern const uint16_t PyZ80GeneratedFieldKeys["
        "PYZ80_GENERATED_FIELD_KEY_COUNT ? PYZ80_GENERATED_FIELD_KEY_COUNT : 1];\n"
        "extern const uint16_t PyZ80GeneratedDispatchFunctions["
        "PYZ80_GENERATED_DISPATCH_WORD_COUNT ? PYZ80_GENERATED_DISPATCH_WORD_COUNT : 1];\n"
        "void PyZ80Generated_Bind(PyZ80TargetContext *context);\n\n"
        "#endif\n"
    )
    source_lines = [
        "/* Generated from the coherent PZVT adapter table. */",
        '#include "pyz80_target_adapter_plan_generated.h"',
        "",
        "const PyZ80TargetAdapterSpec PyZ80GeneratedAdapters[",
        "    PYZ80_GENERATED_ADAPTER_COUNT ? PYZ80_GENERATED_ADAPTER_COUNT : 1] = {",
    ]
    source_lines.extend(
        f"    {{{operation}, {count}u, {aux}u}},"
        for operation, count, aux in specs)
    if not specs:
        source_lines.append("    {0u, 0u, 0u},")
    source_lines.extend([
        "};", "",
        "const PyZ80TargetOperatorSpec PyZ80GeneratedOperators[",
        "    PYZ80_GENERATED_OPERATOR_COUNT ? PYZ80_GENERATED_OPERATOR_COUNT : 1] = {",
    ])
    source_lines.extend(
        f"    {{{symbol}u, {operation}, 0u}},"
        for symbol, operation in operator_specs)
    if not operator_specs:
        source_lines.append("    {0u, 0u, 0u},")
    source_lines.extend(["};", "", "const uint16_t PyZ80GeneratedFieldKeys[",
                         "    PYZ80_GENERATED_FIELD_KEY_COUNT ? PYZ80_GENERATED_FIELD_KEY_COUNT : 1] = {",
                         "    " + ", ".join(f"{key}u" for key in (field_keys or [0])),
                         "};", "", "const uint16_t PyZ80GeneratedDispatchFunctions[",
                         "    PYZ80_GENERATED_DISPATCH_WORD_COUNT ? PYZ80_GENERATED_DISPATCH_WORD_COUNT : 1] = {",
                         "    " + ", ".join(f"{value}u" for value in (plan['dispatch_functions'] or [0])),
                         "};", "", "static const uint16_t positional_arities[] = {",
                         "    " + ", ".join(f"{value}u" for value in (arities or [65535])),
                         "};", "", "static const uint8_t positional_call_flags[] = {",
                         "    " + ", ".join(f"{value}u" for value in (plan['positional_call_flags'] or [0])),
                         "};", "", "static const PyZ80TargetBuiltinSpec builtin_symbols[] = {",
                         "    " + ", ".join(f"{{{key}u, {op}}}" for key, op in plan['builtin_symbols']) if plan['builtin_symbols'] else "    {0u, 0u}",
                         "};", "", "static const PyZ80TargetCallSignature call_signatures[] = {",
                         "    " + ", ".join("{" + ",".join(map(str, row)) + "}" for row in plan['call_signatures']) if plan['call_signatures'] else "    {0,0,0,0,0}",
                         "};", "", "static const uint16_t parameter_names[] = {",
                         "    " + ",".join(map(str, plan['parameter_names'] or [0])),
                         "};", "", "static const uint16_t call_layout_offsets[] = {",
                         "    " + ",".join(map(str, plan['call_layout_offsets'] or [65535])),
                         "};", "", "static const uint16_t call_layout_keys[] = {",
                         "    " + ",".join(map(str, plan['call_layout_keys'] or [0])),
                         "};", "", "static const uint8_t class_body_flags[] = {",
                         "    " + ",".join(map(str, plan['class_body_flags'] or [0])),
                         "};", "", "static const uint16_t class_symbols[] = {",
                         "    " + ",".join(map(str, plan['class_symbols'])),
                         "};", "", "void PyZ80Generated_Bind(PyZ80TargetContext *context)", "{",
                         "    context->adapters = PyZ80GeneratedAdapters;",
                         "    context->table_read = 0; context->table_context = 0; context->table_context_bytes = 0;",
                         "    context->table_key_scratch = 0; context->table_key_capacity = 0;",
                         "    context->adapter_count = PYZ80_GENERATED_ADAPTER_COUNT;",
                         "    context->operators = PyZ80GeneratedOperators;",
                         "    context->operator_count = PYZ80_GENERATED_OPERATOR_COUNT;",
                         "    context->field_keys = PyZ80GeneratedFieldKeys;",
                         "    context->field_key_count = PYZ80_GENERATED_FIELD_KEY_COUNT;",
                         "    context->dispatch_functions = PyZ80GeneratedDispatchFunctions;",
                         "    context->dispatch_function_count = PYZ80_GENERATED_DISPATCH_WORD_COUNT;",
                         "    context->function_count = PYZ80_GENERATED_FUNCTION_COUNT;",
                         "    context->positional_call_arities = positional_arities;",
                         "    context->positional_call_flags = positional_call_flags;",
                         "    context->builtin_symbols = builtin_symbols;",
                         f"    context->builtin_symbol_count = {len(plan['builtin_symbols'])}u;",
                         "    context->call_signatures = call_signatures;",
                         "    context->parameter_names = parameter_names;",
                         f"    context->parameter_name_count = {len(plan['parameter_names'])}u;",
                         "    context->call_layout_offsets = call_layout_offsets;",
                         "    context->call_layout_keys = call_layout_keys;",
                         f"    context->call_layout_key_count = {len(plan['call_layout_keys'])}u;",
                         "    context->class_body_flags = class_body_flags;",
                         "    context->class_symbols = class_symbols;",
                         "}", ""])

    return header, "\n".join(source_lines)


def generate(project_root: Path = ROOT, *, build_directory: Path | None = None,
             source_directory: Path | None = None) -> dict:
    project_root = project_root.resolve()
    build = build_directory or project_root / "Build"
    source_directory = source_directory or project_root / "Source/C/python_vm"
    status_path = build / "rtype_python_whole_program_vm_status.json"
    image_path = build / "rtype_python_whole_program_vm.bin"
    checkpoint_path = build / "rtype_python_translation_checkpoint.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    validate_translation_checkpoint(checkpoint)
    image = image_path.read_bytes()
    target = status["target_bytecode"]
    if checkpoint.get("coherent") is not True:
        raise RuntimeError("translator checkpoint is not coherent")
    # A saved coherent=True is not evidence that the current files match it.
    for record in checkpoint["report_files"]:
        raw = (project_root / record["path"]).read_bytes()
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise RuntimeError(f"stale checkpoint: {record['path']}")
    if (len(image) != target["bytes"] or
            hashlib.sha256(image).hexdigest() != target["sha256"]):
        raise RuntimeError("PZVT image differs from its signed status")
    program = decode_compact_target_vm(
        image,
        expected_proof_semantic_sha256=status["artifact_semantic_sha256"])
    adapters = status["adapter_table"]
    if len(adapters) != program["adapter_count"]:
        raise RuntimeError("adapter table count differs from PZVT")
    if [row["adapter_id"] for row in adapters] != list(range(len(adapters))):
        raise RuntimeError("adapter IDs are not dense and ordered")

    function_ids = status.get("function_id_table", [])
    if len(function_ids) != len(program["functions"]):
        raise RuntimeError("function identity table differs from PZVT")
    arities = status.get("target_coverage", {}).get("positional_call_arities")
    if arities is None:
        arities = [65535] * len(function_ids)  # Older fixtures: no guessed signatures.
    if (len(arities) != len(function_ids) or any(type(value) is not int or
            not 0 <= value <= 65535 for value in arities)):
        raise RuntimeError("positional signature table differs from PZVT")
    plan = build_adapter_specs(adapters, program["constants"], function_ids,
        status.get("target_coverage", {}).get("function_call_signatures"))
    specs, operator_specs, field_keys = plan["specs"], plan["operators"], plan["field_keys"]
    supported, unsupported = plan["supported"], plan["unsupported"]
    header, source_text = render_adapter_tables(plan, arities)
    from pyz80_compiler.banked_tables import build_banked_tables
    banked, bank_h, bank_c, bank_report = build_banked_tables(plan, arities, status['artifact_semantic_sha256'])

    out_h = source_directory / "pyz80_target_adapter_plan_generated.h"
    out_c = source_directory / "pyz80_target_adapter_plan_generated.c"
    out_status = build / "rtype_python_target_adapter_backend_status.json"
    atomic_text(out_h, header)
    atomic_text(out_c, source_text)
    bank_paths = [build/'core_tables.pztb', source_directory/'pyz80_target_banked_plan_generated.h',
                  source_directory/'pyz80_target_banked_plan_generated.c', build/'core_tables.json']
    bank_paths[0].write_bytes(banked)
    atomic_text(bank_paths[1], bank_h)
    atomic_text(bank_paths[2], bank_c)
    atomic_text(bank_paths[3], json.dumps(bank_report,indent=2,sort_keys=True)+'\n')
    report = {
        "format": "pyz80.target-adapter-backend.v1",
        "status": "GENERIC_OBJECT_ADAPTERS_GENERATED_PROVIDER_BINDING_PENDING",
        "live": False,
        "banked_core_tables": bank_report,
        "input": {
            "pZVT_sha256": target["sha256"],
            "pZVT_bytes": target["bytes"],
            "artifact_semantic_sha256": status["artifact_semantic_sha256"],
            "adapter_count": len(adapters),
        },
        "coverage": {
            "generic_adapter_count": sum(supported.values()),
            "unsupported_adapter_count": sum(unsupported.values()),
            "generic_source_operation_counts": dict(sorted(supported.items())),
            "provider_source_operation_counts": dict(sorted(unsupported.items())),
            "operator_symbol_count": len(operator_specs),
            "persistent_object_fields": True,
            "persistent_list_tuple_storage": True,
            "persistent_iterator_state": True,
            "container_protocol": plan['container_protocol'],
            "explicit_safepoint_gc_available": True,
            "gc_automatically_scheduled": False,
            "gc_external_roots_and_finalizers_bound": False,
            "field_key_word_count": len(field_keys),
            "dataclass_field_key_count": plan["dataclass_key_count"],
            "closure_key_word_count": plan["closure_key_word_count"],
            "finite_dispatch_word_count": len(plan["dispatch_functions"]),
            "callable_reference_scope": "exact internal refs and sealed ordinary source definitions with retained defaults; requires attached scopes, call binder and per-function module mappings; generators remain explicit adapters",
            "lexical_name_scope": "captured initialized cells and retained module fields; absent names still require module/builtin providers",
            "dataclass_storage_scope": "plain target object nodes only; custom descriptors require provider",
            "opaque_object_store_fragment_adapters": sum(
                row.get("op") == "execute-object-store-fragment"
                for row in adapters),
        },
        "outputs": [],
        "live_blockers": [
            "exact Python call adapters are not all bound to target providers",
            "FT812/TSFM/GS/level provider table is not final-linked",
            "persistent store capacities are not yet source-lifetime bounded",
            "class descriptor and special-method binding is not closed",
        ],
    }
    for path in (out_h, out_c, *bank_paths):
        data = path.read_bytes()
        report["outputs"].append({
            "path": path.relative_to(project_root).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    semantic_payload = {
        key: value for key, value in report.items()
        if key not in {"status", "live", "live_blockers", "semantic_sha256"}
    }
    report["semantic_sha256"] = hashlib.sha256(json.dumps(
        semantic_payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    atomic_text(out_status, json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    report = generate()
    print(json.dumps(report["coverage"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
