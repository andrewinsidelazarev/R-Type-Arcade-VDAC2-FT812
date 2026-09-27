#ifndef PYZ80_TARGET_SCOPE_RUNTIME_H
#define PYZ80_TARGET_SCOPE_RUNTIME_H
#include "pyz80_target_object_runtime.h"

typedef struct PyZ80TargetScopes {
    PyZ80TargetContext *objects;
    PyZ80VM *vm;
    PyZ80VMScopeHooks hooks;
    PyZ80VMValue *frame_closures;
    uint8_t frame_capacity;
    /* Per-function module mapping identities supplied by the module loader.
       No single guessed global dictionary shared by unrelated modules. */
    const PyZ80VMValue *function_globals;
    uint16_t function_count;
    PyZ80VMValue *binding_scratch;
    uint8_t binding_capacity;
} PyZ80TargetScopes;

/* Retained callable mapping, walking only lexical expression parents; otherwise
   the exact source function mapping. Never a dynamic caller's namespace. */
uint8_t PyZ80Target_CurrentGlobals(PyZ80TargetScopes *scopes,
    uint16_t function, PyZ80VMValue *result);

uint8_t PyZ80Target_AttachScopes(PyZ80TargetScopes *scopes,
    PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80VMValue *frame_closures, uint8_t frame_capacity,
    const PyZ80VMValue *function_globals, uint16_t function_count);
#endif
