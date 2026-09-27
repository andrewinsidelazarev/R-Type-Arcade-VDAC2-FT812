#ifndef PYZ80_TARGET_CLASSES_H
#define PYZ80_TARGET_CLASSES_H
#include "pyz80_target_scope_runtime.h"

#define PYZ80_CLASS_GUARD_END 19u
#define PYZ80_CLASS_SYMBOL_COUNT 48u
typedef struct PyZ80TargetClassFrame {
    uint32_t pc; /* Для возобновляемого обхода classinfo. */
    uint16_t adapter;
    uint16_t name;
    uint8_t operation;
    uint8_t phase;
} PyZ80TargetClassFrame;

#if defined(__SDCC)
typedef char PyZ80TargetClassFrameSize[(sizeof(PyZ80TargetClassFrame)==10u) ? 1 : -1];
#endif

typedef struct PyZ80TargetClasses {
    PyZ80TargetScopes *scopes;
    PyZ80VMControlHooks hooks;
    PyZ80TargetClassFrame *frames;
    PyZ80VMValue *roots;
    uint8_t capacity;
} PyZ80TargetClasses;

/* Attach after scopes/binding/imports. All storage is caller-owned and disjoint.
   roots has 3*capacity entries: pending values, retained callables, namespaces.
   routes has objects->adapter_count entries. GC traces roots automatically.
   Native plain bases use retained tuples and C3 computed once at creation.
   Unsupported metaclasses/hooks fail closed; neither class bodies, __init__,
   nor MRO construction recurse on the C stack. */
uint8_t PyZ80Target_AttachClasses(PyZ80TargetClasses *classes,
    PyZ80TargetScopes *scopes, PyZ80TargetClassFrame *frames,
    PyZ80VMValue *roots, uint8_t capacity, uint16_t *routes);
#endif
