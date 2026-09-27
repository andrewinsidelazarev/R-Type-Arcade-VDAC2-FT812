#ifndef PYZ80_WHOLE_PROGRAM_VM_H
#define PYZ80_WHOLE_PROGRAM_VM_H

/*
 * Active-Python compact target VM ABI (PZVT v1).
 *
 * Ownership and memory
 * --------------------
 * The caller owns the bytecode image, reader context, VM object and arena for
 * the entire run.  The runtime allocates nothing.  ``arena`` must be aligned
 * for uint32_t and have at least PyZ80VM_ArenaBytes(limits) bytes.  Call
 * frames, suspended generators, locals and callback argument scratch all live
 * in that arena, never on the Z80 machine stack.  The C interpreter itself is
 * iterative; no VM call or generator resume uses C recursion.
 *
 * Banked image
 * ------------
 * All image offsets are uint32_t. ``read`` must copy exactly ``size`` bytes
 * from a logical image offset, switching TS-Conf banks if necessary, and
 * return 1.  A short/failed read returns 0.  The helper memory reader is for
 * host tests or a resident image only. ``expected_proof_sha256`` is a
 * caller-resident 32-byte digest from the host proof/status manifest and is
 * mandatory: Init compares it with the PZVT proof digest before execution.
 *
 * Adapter boundary (fail closed)
 * --------------------------------
 * PZVT executes layout-independent constants, local loads/stores, i32 test
 * arithmetic, proven internal calls, expression-CFG calls and CFG
 * terminators.  Every other Python operation is passed exactly once and in
 * bytecode/source order to ``invoke`` using a generated numeric adapter ID,
 * unless handled by the explicitly installed iterative control protocol below.
 * The ID-to-Python-operation/attributes table is host-only and hash-bound by
 * the image proof digest. Missing callbacks, callback failure,
 * unsupported values and opaque truth testing stop with PYZ80_VM_ERROR;
 * there is no guessed Python behaviour. ``raw_arguments_offset`` points to
 * the first compact operand in the image; it is UINT32_MAX for synthesized
 * adapter arguments. SSA references are resolved in ``arguments``;
 * compound constants remain SERIALIZED by constant-pool ID.
 *
 * Callback return convention is uint8_t: 1 means success, 0 means failure.
 * Callbacks may inspect the VM but must not recursively call PyZ80VM_Run.
 * Проверенные тела генераторов next/send(None) понижаются в YIELD_NEXT.
 * YIELD остаётся отдельным тестовым примитивом. Непониженные протоколы
 * suspend-yield/from и save/restore/resume требуют адаптеров. An adapter callback
 * for an unknown terminator is observed once, then execution still fails
 * closed because v1 has no adapter control-transfer result.
 * Exact constructor instructions call one allocation adapter with the proven
 * class symbol.  It must return OPAQUE; the core then prepends that object as
 * ``self``, calls the proven ``__init__``, requires a NONE return, and keeps
 * the allocated object in the constructor expression destination.
 * Source-proven generated dataclass initializers are one core instruction:
 * their adapter receives ``self`` followed by every field value in declaration
 * order and must store those fields and return NONE.  The core then calls the
 * exact ``__post_init__`` target, when present, with the real ``self`` and
 * requires its return to be NONE.  The proven single-use ``super()`` callable
 * preparation chain is encoded as core NOPs and never reaches an adapter.
 * Finite internal dispatch remains runtime guarded.  Its identity adapter
 * receives the already evaluated callable and returns an I32 zero-based index
 * into the hash-bound candidate table.  The core validates the index, applies
 * that candidate's independently proven argument binding and pushes only that
 * function.  Missing/unknown identities fail closed; no class is guessed.
 * When the callable came through a local callback parameter, a second
 * hash-bound adapter receives that same callable and the checked candidate
 * index. It must return the actual OPAQUE bound receiver; the core prepends
 * it to the independently rebound explicit arguments. Unbound callables or
 * receiver/identity disagreement fail closed.
 *
 * This header makes no ``live`` claim: adapter binding, final link, complete
 * stack proof and frame-time proof are separate closure obligations.
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PYZ80_VM_IMAGE_VERSION 1u
#define PYZ80_VM_NO_SYMBOL 0xFFFFu
#define PYZ80_VM_NO_GENERATOR 0xFFFFu
#define PYZ80_VM_FRAME_REQUIRE_NONE_RETURN 1u
#define PYZ80_VM_FRAME_CONTROL_RETURN 2u
#define PYZ80_VM_FRAME_GENERATOR 4u
#define PYZ80_VM_FRAME_VALUE_RETURN 8u

enum PyZ80VMStatus {
    PYZ80_VM_IDLE = 0,
    PYZ80_VM_RUNNING = 1,
    PYZ80_VM_RETURNED = 2,
    PYZ80_VM_YIELDED = 3,
    PYZ80_VM_ERROR = 4
};

enum PyZ80VMErrorCode {
    PYZ80_VM_E_NONE = 0,
    PYZ80_VM_E_ARGUMENT = 1,
    PYZ80_VM_E_ARENA = 2,
    PYZ80_VM_E_IMAGE_READ = 3,
    PYZ80_VM_E_IMAGE_HEADER = 4,
    PYZ80_VM_E_IMAGE_CRC = 5,
    PYZ80_VM_E_MALFORMED = 6,
    PYZ80_VM_E_CALL_OVERFLOW = 7,
    PYZ80_VM_E_LOCAL_OVERFLOW = 8,
    PYZ80_VM_E_ARGUMENT_OVERFLOW = 9,
    PYZ80_VM_E_ADAPTER = 10,
    PYZ80_VM_E_UNBOUND = 11,
    PYZ80_VM_E_ARITHMETIC = 12,
    PYZ80_VM_E_GENERATOR_OVERFLOW = 13,
    PYZ80_VM_E_GENERATOR_STATE = 14,
    PYZ80_VM_E_STEP_LIMIT = 15,
    PYZ80_VM_E_PROOF_HASH = 16,
    PYZ80_VM_E_HEAP_ROOTS = 17
};

enum PyZ80VMValueKind {
    PYZ80_VM_VALUE_NONE = 0,
    PYZ80_VM_VALUE_BOOL = 1,
    PYZ80_VM_VALUE_I32 = 2,
    PYZ80_VM_VALUE_SYMBOL = 3,
    PYZ80_VM_VALUE_SERIALIZED = 4,
    PYZ80_VM_VALUE_OPAQUE = 5,
    /* Internal name-slot indirection, never a user-visible Python value. */
    PYZ80_VM_VALUE_CELL = 6,
    /* Immutable builtin identity, not a PZVT function-table index. */
    PYZ80_VM_VALUE_BUILTIN = 7
};

typedef struct PyZ80VMValue {
    uint8_t kind;
    uint8_t reserved;
    uint16_t symbol;
    uint32_t payload;
} PyZ80VMValue;

struct PyZ80VM;
uint8_t PyZ80VM_StringLength(const struct PyZ80VM *vm,
    const PyZ80VMValue *value, uint32_t *length);
uint8_t PyZ80VM_Truth(struct PyZ80VM *vm, const PyZ80VMValue *value,
    uint8_t *truth);

typedef struct PyZ80VMLocal {
    uint16_t symbol;
    PyZ80VMValue value;
} PyZ80VMLocal;

typedef uint8_t (*PyZ80VMRead)(void *context, uint32_t offset,
                               uint8_t *destination, uint16_t size);

typedef struct PyZ80VMImage {
    PyZ80VMRead read;
    void *context;
    uint32_t size;
    const uint8_t *expected_proof_sha256;
} PyZ80VMImage;

typedef struct PyZ80VMMemoryImage {
    const uint8_t *bytes;
    uint32_t size;
} PyZ80VMMemoryImage;

struct PyZ80VM;

typedef uint8_t (*PyZ80VMInvoke)(
    void *context, struct PyZ80VM *vm, uint16_t adapter_id,
    uint16_t destination_symbol, const PyZ80VMValue *arguments,
    uint8_t argument_count, uint32_t raw_arguments_offset,
    PyZ80VMValue *result);

typedef uint8_t (*PyZ80VMTruth)(
    void *context, struct PyZ80VM *vm, const PyZ80VMValue *value,
    uint8_t *truth);

typedef struct PyZ80VMAdapter {
    PyZ80VMInvoke invoke;
    PyZ80VMTruth truth;
    void *context;
} PyZ80VMAdapter;

/* Optional iterative adapter continuation. Ordinary adapters and unresolved
 * closure-call instructions use it; never static constructors/truth/terminators. Dispatch:
 * 0 = unhandled (no mutation); 1 = completed result; 2 = defer until the given
 * zero-argument function returns NONE; 3 = error; 4 = prepare retained call.
 * Значение 5 возобновляет генератор; контракт generator_event описан ниже.
 * Значение 6 повторяет инструкцию на следующем шаге, не добавляя кадр.
 * Значение 7 вызывает retained callable и передаёт произвольный результат
 * обработчику call_result перед освобождением локальных корней callee.
 * Частичный результат хранится в собственных корнях обработчика.
 * On defer the original SSA
 * operands remain in the caller and its instruction is retried, not advanced.
 * A retry consumes a VM step, so step_budget remains a real scheduling bound.
 * No hook may re-enter Run, change frames or retain argument_scratch pointers.
 * returned runs before popping ONLY frames started by this protocol. failed
 * runs after the first VM failure and must not call VM APIs. Storage is owned
 * by the caller and must outlive the VM. This adds no C recursion or frame bytes.
 */
typedef struct PyZ80VMControlHooks {
    uint8_t (*dispatch)(void *context, struct PyZ80VM *vm, uint16_t adapter,
        const PyZ80VMValue *arguments, uint8_t count,
        PyZ80VMValue *result, uint16_t *function);
    uint8_t (*returned)(void *context, struct PyZ80VM *vm);
    void (*failed)(void *context, struct PyZ80VM *vm);
    void *context;
    /* Optional proof-bound adapter_count entries. NO_SYMBOL bypasses dispatch
       entirely; other values belong to the control provider. NULL intercepts
       every ordinary adapter. This avoids a loader callback per gameplay op. */
    const uint16_t *routes;
    /* Dispatch 4: deferred retained callable, arguments prepared in VM scratch.
       The instruction is retried after a NONE return, as for dispatch 2.
       prepare_call must not run the VM or retain the scratch pointer. */
    uint8_t (*prepare_call)(void *context, struct PyZ80VM *vm,
        PyZ80VMValue *callable, PyZ80VMValue *arguments, uint8_t *count,
        uint16_t *function);
    /* Composed provider chain, also traced by GC. Caller-owned, acyclic;
       dispatch/returned/failed delegation is explicit in the outer provider. */
    const struct PyZ80VMControlHooks *previous;
    const PyZ80VMValue *roots;
    uint16_t root_count;
    /* Dispatch 5: function содержит handle генератора, аргументы не меняются.
       VM возобновляет сохранённый кадр поверх вызывающего, без повторного Run.
       После yield/return уведомляет первый обработчик цепочки: 0 = не мой,
       1 = результат сохранён в собственных GC-корнях, 2 = ошибка.
       Исходная инструкция повторяется, как при dispatch 2/4. */
    uint8_t (*generator_event)(void *context, struct PyZ80VM *vm,
        uint16_t handle, uint8_t yielded, const PyZ80VMValue *value);
    /* 0=чужой результат, 1=сохранён в корнях, 2=ошибка. Без повторного Run. */
    uint8_t (*call_result)(void *context, struct PyZ80VM *vm, const PyZ80VMValue *value);
} PyZ80VMControlHooks;

enum PyZ80VMCellOperation {
    PYZ80_VM_CELL_CREATE = 0,
    PYZ80_VM_CELL_READ = 1,
    PYZ80_VM_CELL_WRITE = 2
};

/* Optional persistent lexical storage. Caller-owned; no hook may re-enter Run. */
typedef struct PyZ80VMScopeHooks {
    uint8_t (*cell)(void *context, uint8_t operation,
                    const PyZ80VMValue *cell, const PyZ80VMValue *value,
                    PyZ80VMValue *result);
    uint8_t (*enter)(void *context, struct PyZ80VM *vm);
    uint8_t (*bind)(void *context, struct PyZ80VM *vm,
                    uint16_t function, const PyZ80VMValue *callable);
    /* 0: external callable; 1: native closure; 2: invalid native call. */
    uint8_t (*resolve)(void *context, struct PyZ80VM *vm,
                       const PyZ80VMValue *callable, uint8_t count,
                       uint16_t *function);
    void *context;
    /* 0 foreign (arguments unchanged), 1 native (bound arguments committed),
       2 invalid. Uses caller-owned scratch, never recursively runs the VM. */
    uint8_t (*prepare)(void *context, struct PyZ80VM *vm, uint16_t adapter,
                       PyZ80VMValue *arguments, uint8_t *count, uint16_t *function);
} PyZ80VMScopeHooks;

typedef struct PyZ80VMLimits {
    uint8_t max_call_depth;
    uint8_t max_generators;
    /* Exact per-frame union bound: SSA slots plus distinct bound-name slots. */
    uint16_t locals_per_frame;
    uint8_t max_arguments;
} PyZ80VMLimits;

typedef struct PyZ80VMFrame {
    uint16_t unit;
    uint16_t local_count;
    uint16_t return_symbol;
    uint16_t instructions_remaining;
    uint8_t lexical_parent_depth;
    uint8_t reserved;
    uint32_t pc;
    uint32_t end;
} PyZ80VMFrame;

typedef struct PyZ80VMGenerator {
    uint8_t in_use;
    uint8_t done;
    uint16_t unit;
    uint16_t local_count;
    uint16_t instructions_remaining;
    uint8_t lexical_parent_depth;
    /* Ноль = приостановлен; иначе глубина активного кадра (защита входа). */
    uint8_t reserved;
    uint32_t pc;
    uint32_t end;
    uint16_t function;
    uint16_t parent_generator;
    /* Удерживает глобальное окружение и ячейки замыкания между next(). */
    PyZ80VMValue callable;
    /* NONE — внешний владелец API; иначе heap-объект управляет временем жизни. */
    PyZ80VMValue owner;
} PyZ80VMGenerator;

/* Public layout terms used by the stack/arena proof.  On pinned SDCC/Z80 the
 * ABI is intentionally asserted so a compiler packing change fails closed. */
#define PYZ80_VM_VALUE_BYTES ((uint16_t)sizeof(PyZ80VMValue))
#define PYZ80_VM_LOCAL_BYTES ((uint16_t)sizeof(PyZ80VMLocal))
#define PYZ80_VM_FRAME_BYTES ((uint16_t)sizeof(PyZ80VMFrame))
#define PYZ80_VM_GENERATOR_BYTES ((uint16_t)sizeof(PyZ80VMGenerator))
#if defined(__SDCC)
typedef char PyZ80VMAssertValueBytes[(sizeof(PyZ80VMValue) == 8u) ? 1 : -1];
typedef char PyZ80VMAssertLocalBytes[(sizeof(PyZ80VMLocal) == 10u) ? 1 : -1];
typedef char PyZ80VMAssertFrameBytes[(sizeof(PyZ80VMFrame) == 18u) ? 1 : -1];
typedef char PyZ80VMAssertGeneratorBytes[
    (sizeof(PyZ80VMGenerator) == 38u) ? 1 : -1];
typedef char PyZ80VMAssertLimitsBytes[(sizeof(PyZ80VMLimits) == 5u) ? 1 : -1];
#endif

typedef struct PyZ80VMHeader {
    uint16_t function_count;
    uint16_t unit_count;
    uint16_t adapter_count;
    uint16_t constant_count;
    uint32_t function_offset;
    uint32_t unit_directory_offset;
    uint32_t constant_directory_offset;
    uint32_t constant_data_offset;
    uint32_t unit_data_offset;
    uint32_t unit_data_size;
} PyZ80VMHeader;

typedef struct PyZ80VM {
    PyZ80VMImage image;
    PyZ80VMAdapter adapter;
    PyZ80VMLimits limits;
    PyZ80VMHeader header;
    PyZ80VMFrame *frames;
    PyZ80VMGenerator *generators;
    PyZ80VMLocal *locals;
    PyZ80VMValue *argument_scratch;
    uint8_t call_depth;
    uint8_t status;
    uint8_t error;
    uint8_t reserved;
    uint16_t active_generator;
    PyZ80VMValue result;
    const PyZ80VMScopeHooks *scope_hooks;
    const PyZ80VMControlHooks *control_hooks;
} PyZ80VM;

/* Box an already-bound lexical name once. Missing declarations fail closed;
   they need a statically resolved owner rather than a guessed current frame. */
uint8_t PyZ80VM_CaptureName(PyZ80VM *vm, uint16_t name, PyZ80VMValue *result);
/* Read exactly this frame's binding (including a cell), never a caller's self. */
uint8_t PyZ80VM_ReadLocalName(PyZ80VM *vm, uint8_t depth, uint16_t name, PyZ80VMValue *result);

/* Arguments must already follow the independently proven positional ABI. */
uint8_t PyZ80VM_StartClosure(PyZ80VM *vm, uint16_t function,
                            const PyZ80VMValue *callable,
                            const PyZ80VMValue *arguments, uint8_t count);

/* Exact arena formula (no hidden allocation):
 *   max_call_depth * FRAME_BYTES
 * + max_generators * GENERATOR_BYTES
 * + (max_call_depth + max_generators) * locals_per_frame * LOCAL_BYTES
 * + max_arguments * VALUE_BYTES
 * Returns zero if the requested layout cannot be represented in uint16_t. */
uint16_t PyZ80VM_ArenaBytes(const PyZ80VMLimits *limits);

uint8_t PyZ80VM_MemoryRead(void *context, uint32_t offset,
                           uint8_t *destination, uint16_t size);

uint8_t PyZ80VM_Init(PyZ80VM *vm, const PyZ80VMImage *image,
                     const PyZ80VMAdapter *adapter, void *arena,
                     uint16_t arena_size, const PyZ80VMLimits *limits);

/* Start an exported function with positional values already ordered according
 * to its PZVT parameter table.  The values are copied into the caller-owned
 * frame arena before this function returns. */
uint8_t PyZ80VM_StartArgs(PyZ80VM *vm, uint16_t function_index,
                          const PyZ80VMValue *arguments,
                          uint8_t argument_count);
uint8_t PyZ80VM_Start(PyZ80VM *vm, uint16_t function_index);
uint8_t PyZ80VM_Run(PyZ80VM *vm, uint32_t step_budget,
                    PyZ80VMValue *result);
/* Abort an external safepoint failure through the same cleanup path as Run.
   Must not be called by a failed control hook. */
uint8_t PyZ80VM_Abort(PyZ80VM *vm, uint8_t error);

uint8_t PyZ80VM_GeneratorCreate(PyZ80VM *vm, uint16_t function_index,
                                uint16_t *handle);
/* Создание не исполняет тело и не меняет активные кадры. Аргументы уже
   упорядочены проверенным ABI. NULL callable допустим без замыкания.
   В этой версии только next/send(None); throw/finally не подменяются. */
uint8_t PyZ80VM_GeneratorCreateArgs(PyZ80VM *vm, uint16_t function_index,
    const PyZ80VMValue *callable, const PyZ80VMValue *arguments,
    uint8_t count, uint16_t *handle);
uint8_t PyZ80VM_GeneratorResume(PyZ80VM *vm, uint16_t handle,
                                const PyZ80VMValue *send_value,
                                uint32_t step_budget, PyZ80VMValue *result);
uint8_t PyZ80VM_GeneratorClose(PyZ80VM *vm, uint16_t handle);

uint8_t PyZ80VM_LastError(const PyZ80VM *vm);

#ifdef __cplusplus
}
#endif

#endif
