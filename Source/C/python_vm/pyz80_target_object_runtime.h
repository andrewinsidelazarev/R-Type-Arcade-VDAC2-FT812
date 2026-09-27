#ifndef PYZ80_TARGET_OBJECT_RUNTIME_H
#define PYZ80_TARGET_OBJECT_RUNTIME_H

#include <stdint.h>

#include "pyz80_whole_program_vm.h"

enum PyZ80TargetOperation {
    PYZ80_TARGET_UNSUPPORTED = 0,
    PYZ80_TARGET_ALLOCATE_INSTANCE = 1,
    PYZ80_TARGET_LOAD_ATTRIBUTE = 2,
    PYZ80_TARGET_STORE_ATTRIBUTE = 3,
    PYZ80_TARGET_BUILD_LIST = 4,
    PYZ80_TARGET_BUILD_TUPLE = 5,
    PYZ80_TARGET_LOAD_SUBSCRIPT = 6,
    PYZ80_TARGET_STORE_SUBSCRIPT = 7,
    PYZ80_TARGET_BINARY = 8,
    PYZ80_TARGET_COMPARE = 9,
    PYZ80_TARGET_UNARY = 10,
    PYZ80_TARGET_GET_ITERATOR = 11,
    PYZ80_TARGET_ITER_NEXT = 12,
    PYZ80_TARGET_ITER_HAS_VALUE = 13,
    PYZ80_TARGET_ITER_VALUE = 14,
    PYZ80_TARGET_UNPACK_SEQUENCE = 15,
    PYZ80_TARGET_UNPACK_ITEM = 16,
    PYZ80_TARGET_STORE_DATACLASS_FIELDS = 17,
    PYZ80_TARGET_REQUIRE_CALLABLE = 18,
    PYZ80_TARGET_RESOLVE_CALLABLE = 19,
    PYZ80_TARGET_BOUND_RECEIVER = 20,
    PYZ80_TARGET_CAPTURE_CELL = 21,
    PYZ80_TARGET_MAKE_CLOSURE = 22,
    PYZ80_TARGET_LOAD_GLOBALS = 23,
    PYZ80_TARGET_LOAD_LEXICAL_NAME = 24,
    PYZ80_TARGET_LIST_APPEND = 25,
    PYZ80_TARGET_MAKE_CLOSURE_DEFAULTS = 26,
    PYZ80_TARGET_STORE_GLOBAL_NAME = 27,
    PYZ80_TARGET_LOAD_GLOBAL_NAME = 28,
    PYZ80_TARGET_LOAD_CLASS_NAME = 29,
    PYZ80_TARGET_STORE_CLASS_NAME = 30,
    PYZ80_TARGET_BUILD_CLASS = 31,
    PYZ80_TARGET_LOAD_CLASS_FREE_NAME = 32,
    PYZ80_TARGET_SETUP_CLASS_ANNOTATIONS = 33,
    PYZ80_TARGET_SETUP_GLOBAL_ANNOTATIONS = 34,
    PYZ80_TARGET_BUILD_DICT = 35,
    PYZ80_TARGET_DATACLASS_RESOLVE = 36,
    PYZ80_TARGET_DATACLASS_INSTALL = 37,
    PYZ80_TARGET_DATACLASS_METADATA = 38,
    PYZ80_TARGET_DATACLASS_REPR_PENDING = 39,
    PYZ80_TARGET_BUILD_SET = 40, PYZ80_TARGET_SET_ADD = 41,
    PYZ80_TARGET_GENERATOR_NEXT_ENTER = 42,
    PYZ80_TARGET_MAKE_GENERATOR_CLOSURE = 43,
    PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS = 44,
    PYZ80_TARGET_DELETE_SUBSCRIPT = 45, PYZ80_TARGET_BUILD_SLICE = 46,
    PYZ80_TARGET_COLLECTIONS_DEQUE_TYPE = 47,
    PYZ80_TARGET_COLLECTIONS_DEFAULTDICT_TYPE = 48
};

enum PyZ80TargetOperator {
    PYZ80_TARGET_OP_ADD = 1,
    PYZ80_TARGET_OP_SUB = 2,
    PYZ80_TARGET_OP_MUL = 3,
    PYZ80_TARGET_OP_FLOORDIV = 4,
    PYZ80_TARGET_OP_TRUEDIV = 5,
    PYZ80_TARGET_OP_MOD = 6,
    PYZ80_TARGET_OP_BITAND = 7,
    PYZ80_TARGET_OP_BITOR = 8,
    PYZ80_TARGET_OP_BITXOR = 9,
    PYZ80_TARGET_OP_LSHIFT = 10,
    PYZ80_TARGET_OP_RSHIFT = 11,
    PYZ80_TARGET_OP_EQ = 12,
    PYZ80_TARGET_OP_NE = 13,
    PYZ80_TARGET_OP_LT = 14,
    PYZ80_TARGET_OP_LE = 15,
    PYZ80_TARGET_OP_GT = 16,
    PYZ80_TARGET_OP_GE = 17,
    PYZ80_TARGET_OP_NEG = 18,
    PYZ80_TARGET_OP_POS = 19,
    PYZ80_TARGET_OP_INVERT = 20,
    PYZ80_TARGET_OP_NOT = 21,
    PYZ80_TARGET_OP_IS = 22, PYZ80_TARGET_OP_IS_NOT = 23,
    PYZ80_TARGET_OP_IN = 24, PYZ80_TARGET_OP_NOT_IN = 25
};

enum PyZ80TargetNodeKind {
    PYZ80_TARGET_NODE_FREE = 0,
    PYZ80_TARGET_NODE_OBJECT = 1,
    PYZ80_TARGET_NODE_LIST = 2,
    PYZ80_TARGET_NODE_TUPLE = 3,
    PYZ80_TARGET_NODE_ITERATOR = 4,
    /* class_symbol holds the exact PZVT function ID; current holds __self__.
       reserved is 1 for bound methods and 0 for free functions. */
    PYZ80_TARGET_NODE_CALLABLE = 5,
    PYZ80_TARGET_NODE_CELL = 6,
    /* current.payload=start; item_start/item_count=step lo/hi; cursor=len.
       Native range extent is bounded to 65535; no backing item allocation. */
    PYZ80_TARGET_NODE_RANGE = 7,
    /* current=namespace, items=[bases tuple, C3 MRO tuple]. reserved=1 while
       executing the class body; only that pending state may have no MRO yet. */
    PYZ80_TARGET_NODE_CLASS = 8,
    PYZ80_TARGET_NODE_INSTANCE = 9, /* current = actual class; fields = instance dict */
    PYZ80_TARGET_NODE_SUPER = 10, /* current=receiver, source_link/generation=anchor type */
    /* reserved=0: строковые ключи в fields; reserved=1: пары key/value в items.
       cursor=число ключей; в парном режиме source_link=ёмкость items.
       current.payload=версия набора ключей, без циклического переполнения. */
    PYZ80_TARGET_NODE_DICT = 11,
    PYZ80_TARGET_NODE_NATIVE_METHOD = 12, /* current=владелец, class_symbol=операция native builtin. */
    PYZ80_TARGET_NODE_SET = 13, /* items=ключи, cursor=ёмкость, reserved=1 для frozenset. */
    /* cursor=слот VM; reserved=1 после исчерпания, current=значение итерации. */
    PYZ80_TARGET_NODE_GENERATOR = 14,
    /* current=исходный dict; class_symbol: 0=keys, 1=values, 2=items. */
    PYZ80_TARGET_NODE_DICT_VIEW = 15,
    /* source_link/generation=iterator, item_start/count=индекс int32;
       current=выданная пара, reserved: 1=исчерпан, 2=индекс вышел за int32. */
    PYZ80_TARGET_NODE_ENUMERATE = 16,
    /* items: lower, upper, step; None отличается от явного -1. */
    PYZ80_TARGET_NODE_SLICE = 17,
    /* current=голова блоков, source=хвост, item_count=длина;
       item_start/cursor=младшее/старшее слово версии мутаций. */
    PYZ80_TARGET_NODE_DEQUE = 18,
    /* current=следующий блок, source=владелец; items[16], cursor=начало,
       reserved=конец живого интервала. Пустые ячейки строго None. */
    PYZ80_TARGET_NODE_DEQUE_BLOCK = 19,
    /* source=очередь, field_head/class_symbol=блок/поколение;
       item_start/cursor=версия, item_count=индекс внутри блока. */
    PYZ80_TARGET_NODE_DEQUE_ITERATOR = 20,
    /* items=[native dict, default_factory]; оболочка сохраняет свой тип/identity. */
    PYZ80_TARGET_NODE_DEFAULTDICT = 21,
    /* current=голова, source=хвост, item_count=байты;
       field_head/class_symbol/cursor=кэш блока: handle/generation/ordinal. */
    PYZ80_TARGET_NODE_BYTES = 22, PYZ80_TARGET_NODE_BYTEARRAY = 23,
    /* Восемь сырых item-слотов (64 байта), current=следующий блок,
       source=владелец, field_head=номер блока, cursor=число записанных байтов. */
    PYZ80_TARGET_NODE_BUFFER_BLOCK = 24,
    PYZ80_TARGET_NODE_STATICMETHOD = 25 /* current=обёрнутый объект, без неявного self. */
};

enum PyZ80TargetBuiltin {
    PYZ80_BUILTIN_BOOL = 1, PYZ80_BUILTIN_LEN = 2,
    PYZ80_BUILTIN_GETATTR = 3, PYZ80_BUILTIN_RANGE = 4, PYZ80_BUILTIN_OBJECT = 5,
    PYZ80_BUILTIN_SUPER = 6,
    PYZ80_BUILTIN_DICT_GET = 7, /* Метод, а не глобальная функция Python. */
    PYZ80_BUILTIN_SET = 8, PYZ80_BUILTIN_FROZENSET = 9,
    PYZ80_BUILTIN_SET_ADD = 10, PYZ80_BUILTIN_SET_REMOVE = 11,
    PYZ80_BUILTIN_SET_DISCARD = 12, PYZ80_BUILTIN_SET_CLEAR = 13,
    PYZ80_BUILTIN_NEXT = 14, PYZ80_BUILTIN_ITER = 15,
    PYZ80_BUILTIN_ANY = 16, PYZ80_BUILTIN_TUPLE = 17,
    PYZ80_BUILTIN_LIST_APPEND = 18, PYZ80_BUILTIN_LIST_CLEAR = 19,
    PYZ80_BUILTIN_LIST_POP = 20, PYZ80_BUILTIN_DICT_POP = 21,
    PYZ80_BUILTIN_DICT_CLEAR = 22, PYZ80_BUILTIN_DICT_KEYS = 23,
    PYZ80_BUILTIN_DICT_VALUES = 24, PYZ80_BUILTIN_DICT_ITEMS = 25,
    PYZ80_BUILTIN_ENUMERATE = 26, PYZ80_BUILTIN_SORTED = 27,
    PYZ80_BUILTIN_LIST_EXTEND = 28,
    PYZ80_BUILTIN_MIN = 29, PYZ80_BUILTIN_MAX = 30,
    PYZ80_BUILTIN_ISINSTANCE = 31, PYZ80_BUILTIN_ISSUBCLASS = 32,
    PYZ80_BUILTIN_HASATTR = 33,
    /* Идентичности типов; наличие имени не объявляет поддержку конструктора. */
    PYZ80_BUILTIN_INT = 34, PYZ80_BUILTIN_STR = 35,
    PYZ80_BUILTIN_LIST = 36, PYZ80_BUILTIN_DICT = 37,
    PYZ80_BUILTIN_REVERSED = 38,
    /* Импортируемый тип, не глобальное имя builtin. */
    PYZ80_BUILTIN_DEQUE = 39, PYZ80_BUILTIN_DEQUE_APPEND = 40,
    PYZ80_BUILTIN_DEQUE_POPLEFT = 41, PYZ80_BUILTIN_DEQUE_CLEAR = 42,
    PYZ80_BUILTIN_DEFAULTDICT = 43, PYZ80_BUILTIN_DEFAULTDICT_MISSING = 44,
    PYZ80_BUILTIN_BYTES = 45, PYZ80_BUILTIN_BYTEARRAY = 46,
    PYZ80_BUILTIN_STATICMETHOD = 47,
    PYZ80_DEFAULT_FACTORY_ATTRIBUTE = 248,
    /* Запечатанный список существующих атрибутов None; symbol=65535 — маркер полноты. */
    PYZ80_NONE_ATTRIBUTE_KNOWN = 249,
    /* Метки keyword-параметров, не callable и не глобальные builtin. */
    PYZ80_KEYWORD_KEY = 250, PYZ80_KEYWORD_REVERSE = 251, PYZ80_KEYWORD_START = 252,
    PYZ80_KEYWORD_ITERABLE = 253, PYZ80_KEYWORD_DEFAULT = 254
};

#define PYZ80_BUILTIN_IS_GLOBAL(op) (((op)>=PYZ80_BUILTIN_BOOL && (op)<=PYZ80_BUILTIN_SUPER) || (op)==PYZ80_BUILTIN_SET || (op)==PYZ80_BUILTIN_FROZENSET || ((op)>=PYZ80_BUILTIN_NEXT && (op)<=PYZ80_BUILTIN_TUPLE) || (op)==PYZ80_BUILTIN_ENUMERATE || (op)==PYZ80_BUILTIN_SORTED || ((op)>=PYZ80_BUILTIN_MIN && (op)<=PYZ80_BUILTIN_REVERSED) || (op)==PYZ80_BUILTIN_BYTES || (op)==PYZ80_BUILTIN_BYTEARRAY || (op)==PYZ80_BUILTIN_STATICMETHOD)

/* Флаг направления в item_start обычного итератора; младшие биты — вид dict.
   Обратный cursor хранит следующий индекс + 1, поэтому ноль не переполняется. */
#define PYZ80_TARGET_ITER_REVERSE 128u

typedef struct PyZ80TargetBuiltinSpec {
    uint16_t symbol;
    uint8_t operation;
} PyZ80TargetBuiltinSpec;

typedef struct PyZ80TargetCallSignature {
    uint16_t start;
    uint8_t count;
    uint8_t positional_count;
    uint8_t positional_only_count;
    uint8_t supported;
} PyZ80TargetCallSignature;

typedef struct PyZ80TargetAdapterSpec {
    uint8_t operation;
    uint8_t argument_count;
    uint16_t auxiliary;
} PyZ80TargetAdapterSpec;

typedef struct PyZ80TargetOperatorSpec {
    uint16_t symbol;
    uint8_t operation;
    uint8_t reserved;
} PyZ80TargetOperatorSpec;

enum PyZ80TargetTable {
    PYZ80_TABLE_ADAPTERS=0, PYZ80_TABLE_FIELDS=1, PYZ80_TABLE_DISPATCH=2,
    PYZ80_TABLE_ARITIES=3, PYZ80_TABLE_CALL_FLAGS=4, PYZ80_TABLE_SIGNATURES=5,
    PYZ80_TABLE_PARAMETERS=6, PYZ80_TABLE_CALL_OFFSETS=7, PYZ80_TABLE_CALL_KEYS=8,
    PYZ80_TABLE_CLASS_FLAGS=9, PYZ80_TABLE_COUNT=10
};
/* Copy one decoded record into caller storage. Never return a pointer into a
   pageable window. A reader must not reenter the VM or mutate its source. */
typedef uint8_t (*PyZ80TargetTableRead)(void *context, uint8_t table,
    uint16_t index, void *record);

typedef struct PyZ80TargetNode {
    uint8_t kind;
    uint16_t generation;
    uint16_t class_symbol;
    uint16_t field_head;
    uint16_t item_start;
    uint16_t item_count;
    uint16_t cursor;
    /* For iterators: retained source collection, not a stale item slice. */
    uint16_t source_link;
    uint16_t source_generation;
    uint8_t has_current;
    uint8_t reserved;
    PyZ80VMValue current;
} PyZ80TargetNode;

typedef struct PyZ80TargetField {
    uint16_t next;
    uint16_t key;
    PyZ80VMValue value;
} PyZ80TargetField;

typedef uint8_t (*PyZ80TargetProviderInvoke)(
    void *context, struct PyZ80VM *vm, uint16_t adapter_id,
    uint16_t destination_symbol, const PyZ80VMValue *arguments,
    uint8_t argument_count, uint32_t raw_arguments_offset,
    PyZ80VMValue *result);

typedef struct PyZ80TargetContext {
    PyZ80TargetNode *nodes;
    PyZ80TargetField *fields;
    PyZ80VMValue *items;
    uint16_t node_capacity;
    uint16_t field_capacity;
    uint16_t item_capacity;
    uint16_t node_used;
    uint16_t free_node_head;
    uint16_t field_used;
    uint16_t item_used;
    const PyZ80TargetAdapterSpec *adapters;
    uint16_t adapter_count;
    const PyZ80TargetOperatorSpec *operators;
    uint16_t operator_count;
    /* Hash-bound generated field-symbol slices; adapter.auxiliary is the start.
       The caller owns this immutable table for the context's entire lifetime. */
    const uint16_t *field_keys;
    uint16_t field_key_count;
    const uint16_t *dispatch_functions;
    uint16_t dispatch_function_count;
    uint16_t function_count;
    /* Source-signature positional arities; 0xffff requires another binder. */
    const uint16_t *positional_call_arities;
    PyZ80TargetProviderInvoke provider;
    void *provider_context;
    /* Installed by the optional persistent scope runtime. */
    PyZ80TargetProviderInvoke scope_provider;
    void *scope_context;
    const PyZ80TargetBuiltinSpec *builtin_symbols;
    uint16_t builtin_symbol_count;
    const uint8_t *positional_call_flags; /* One source-layout flag per adapter. */
    PyZ80TargetProviderInvoke builtin_provider;
    const PyZ80TargetCallSignature *call_signatures; /* function_count records */
    const uint16_t *parameter_names;
    uint16_t parameter_name_count;
    const uint16_t *call_layout_offsets; /* adapter_count records, 65535 unsupported */
    const uint16_t *call_layout_keys; /* positional=65535, keyword=constant symbol */
    uint16_t call_layout_key_count;
    const uint8_t *class_body_flags; /* function_count entries; exact sealed bodies */
    const uint16_t *class_symbols; /* class_protocol ABI; also function __annotations__, even without classes */
    PyZ80TargetProviderInvoke class_provider;
    void *class_context;
    /* Attribute protocol: 1 found, 2 absent, 0 invalid/unsupported. */
    uint8_t (*class_attribute)(void *context, const PyZ80VMValue *object,
        uint16_t key, PyZ80VMValue *result);
    PyZ80TargetProviderInvoke library_provider;
    void *library_context;
    /* Partial library protocols must not masquerade as absent attributes. */
    uint8_t (*class_library_guard)(void *context, PyZ80TargetNode *type, uint16_t key);
    PyZ80TargetTableRead table_read;
    void *table_context;
    uint16_t table_context_bytes; /* Resident reader state excluded from provider/GC scratch. */
    uint16_t *table_key_scratch; /* Caller-owned, for atomic multi-field stores. */
    uint16_t table_key_capacity;
} PyZ80TargetContext;

uint8_t PyZ80Target_HasTable(const PyZ80TargetContext *context, uint8_t table);
/* Невозобновляемые операции над стандартными native-коллекциями. */
uint8_t PyZ80Target_GetIterator(PyZ80TargetContext *, const PyZ80VMValue *, PyZ80VMValue *);
uint8_t PyZ80Target_Reversed(PyZ80TargetContext *, const PyZ80VMValue *, PyZ80VMValue *);
uint8_t PyZ80Target_Operator(PyZ80TargetContext *, const PyZ80VMValue *, uint8_t *);
/* Identity shortcut разрешён именно контейнерному поиску, не обычному ==. */
uint8_t PyZ80Target_ContainerItemEqual(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *, uint8_t *);
uint8_t PyZ80Target_IterNext(PyZ80TargetContext *, const PyZ80VMValue *, PyZ80VMValue *);
uint8_t PyZ80Target_Enumerate(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *, PyZ80VMValue *);
uint8_t PyZ80Target_Keyword(PyZ80TargetContext *, uint16_t);
uint8_t PyZ80Target_EmptyList(PyZ80TargetContext *, PyZ80VMValue *);
uint8_t PyZ80Target_ListAppend(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *);
uint8_t PyZ80Target_ListClear(PyZ80TargetContext *, const PyZ80VMValue *);
uint8_t PyZ80Target_ListPop(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *, PyZ80VMValue *);
/* 1=удалён, 2=ключ отсутствует, 0=ошибка; default обрабатывает вызывающая сторона. */
uint8_t PyZ80Target_DictRemove(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *, PyZ80VMValue *);
uint8_t PyZ80Target_DictClear(PyZ80TargetContext *, const PyZ80VMValue *);
uint8_t PyZ80Target_DictView(PyZ80TargetContext *, const PyZ80VMValue *, uint8_t, PyZ80VMValue *);
/* 1: найден, 2: отсутствует, 0: неподдержанный ключ/повреждённое хранилище. */
uint8_t PyZ80Target_DictFind(PyZ80TargetContext *context, const PyZ80VMValue *dictionary,
    const PyZ80VMValue *key, PyZ80VMValue *result);
uint8_t PyZ80Target_DictStore(PyZ80TargetContext *context, const PyZ80VMValue *dictionary,
    const PyZ80VMValue *key, const PyZ80VMValue *value);
/* Оболочка defaultdict не меняет протоколы обычного dict. Указатель parts
   используется только до ближайшего шага/GC; продолжения сохраняют Value. */
uint8_t PyZ80Target_DefaultDictParts(PyZ80TargetContext *,const PyZ80TargetNode *,PyZ80VMValue **);
uint8_t PyZ80Target_Mapping(PyZ80TargetContext *,const PyZ80VMValue *,PyZ80VMValue *);
uint8_t PyZ80Target_CreateDefaultDict(PyZ80TargetContext *,const PyZ80VMValue *,PyZ80VMValue *);
uint8_t PyZ80Target_NativeName(PyZ80TargetContext *,uint16_t,uint8_t);
/* Только доказанные скалярные ключи; 1=найден, 2=нет, 0=неподдержан/повреждён. */
uint8_t PyZ80Target_SetFind(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *);
uint8_t PyZ80Target_SetAdd(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *);
uint8_t PyZ80Target_SetRemove(PyZ80TargetContext *, const PyZ80VMValue *, const PyZ80VMValue *, uint8_t);
uint8_t PyZ80Target_SetClear(PyZ80TargetContext *, const PyZ80VMValue *);
uint8_t PyZ80Target_SetFrom(PyZ80TargetContext *, const PyZ80VMValue *, uint8_t, PyZ80VMValue *);
uint8_t PyZ80Target_NativeMethodValid(PyZ80TargetContext *, const PyZ80TargetNode *);
uint8_t PyZ80Target_TableStorageSeparate(const PyZ80TargetContext *context, const void *buffer, uint32_t bytes);
uint8_t PyZ80Target_ReadTable(PyZ80TargetContext *context, uint8_t table, uint16_t index, void *record);
uint8_t PyZ80Target_ReadAdapter(PyZ80TargetContext *context, uint16_t index, PyZ80TargetAdapterSpec *record);
uint8_t PyZ80Target_ReadSignature(PyZ80TargetContext *context, uint16_t index, PyZ80TargetCallSignature *record);
uint8_t PyZ80Target_ReadWord(PyZ80TargetContext *context, uint8_t table, uint16_t index, uint16_t *value);
uint8_t PyZ80Target_ReadByte(PyZ80TargetContext *context, uint8_t table, uint16_t index, uint8_t *value);

PyZ80TargetNode *PyZ80Target_Node(PyZ80TargetContext *context, const PyZ80VMValue *value);
/* Unwrap one retained bound method without copying captures/defaults. */
uint8_t PyZ80Target_UnwrapCallable(PyZ80TargetContext *context, const PyZ80VMValue *value,
    PyZ80VMValue *prototype, PyZ80VMValue *receiver);
uint8_t PyZ80Target_BindMethod(PyZ80TargetContext *context, const PyZ80VMValue *function,
    const PyZ80VMValue *receiver, PyZ80VMValue *result);
uint8_t PyZ80Target_FindAttribute(PyZ80TargetContext *context,
    const PyZ80VMValue *object, uint16_t key, PyZ80VMValue *result);

void PyZ80Target_Init(
    PyZ80TargetContext *context, PyZ80TargetNode *nodes,
    uint16_t node_capacity, PyZ80TargetField *fields,
    uint16_t field_capacity, PyZ80VMValue *items, uint16_t item_capacity,
    const PyZ80TargetAdapterSpec *adapters, uint16_t adapter_count,
    const PyZ80TargetOperatorSpec *operators, uint16_t operator_count,
    PyZ80TargetProviderInvoke provider, void *provider_context);

/* Shared allocator for object and scope runtimes. Handles never wrap their
   16-bit generation: exhausted slots are retired instead of aliasing old IDs. */
uint8_t PyZ80Target_AllocateNode(PyZ80TargetContext *context,
    uint8_t kind, uint16_t class_symbol, PyZ80VMValue *result);

PyZ80VMAdapter PyZ80Target_VMAdapter(PyZ80TargetContext *context);

uint8_t PyZ80Target_Invoke(
    void *context, struct PyZ80VM *vm, uint16_t adapter_id,
    uint16_t destination_symbol, const PyZ80VMValue *arguments,
    uint8_t argument_count, uint32_t raw_arguments_offset,
    PyZ80VMValue *result);

uint8_t PyZ80Target_Truth(
    void *context, struct PyZ80VM *vm, const PyZ80VMValue *value,
    uint8_t *truth);

uint8_t PyZ80Target_LoadField(
    PyZ80TargetContext *context, const PyZ80VMValue *object,
        uint16_t key, PyZ80VMValue *result);
uint8_t PyZ80Target_SetupAnnotations(PyZ80TargetContext *context,
    const PyZ80VMValue *mapping, uint16_t key);
/* 1 found, 2 absent on a valid plain object, 0 corrupt/unsupported object. */
uint8_t PyZ80Target_FindField(PyZ80TargetContext *context,
    const PyZ80VMValue *object, uint16_t key, PyZ80VMValue *result);
uint8_t PyZ80Target_Length(PyZ80TargetContext *context,
    const PyZ80VMValue *value, uint32_t *length);
uint8_t PyZ80Target_StoreField(
    PyZ80TargetContext *context, const PyZ80VMValue *object,
    uint16_t key, const PyZ80VMValue *value);

/* Generic plain-instance dataclass initializer. No allocation on the C stack,
   no per-class code: fields are stored in the source declaration order.
   Capacity/layout validation precedes all writes. Descriptors/properties need
   a separate object protocol; this API only accepts this runtime's plain nodes. */
uint8_t PyZ80Target_StoreFields(
    PyZ80TargetContext *context, const PyZ80VMValue *object,
    const uint16_t *keys, const PyZ80VMValue *values, uint8_t count);

/* Create an exact function reference, optionally retaining its actual receiver.
   No class-name inference or candidate-index guessing occurs at invocation. */
uint8_t PyZ80Target_Callable(
    PyZ80TargetContext *context, uint16_t function,
    const PyZ80VMValue *receiver, PyZ80VMValue *result);

#endif
