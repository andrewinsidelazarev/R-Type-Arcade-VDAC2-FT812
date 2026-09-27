#ifndef PYZ80_TARGET_GC_H
#define PYZ80_TARGET_GC_H
#include "pyz80_target_scope_runtime.h"

/* Caller-owned work buffers: O(nodes + fields + items), no recursive tracing.
   Capacities are buffer lengths, not the current heap usage. */
typedef struct PyZ80TargetGC {
    uint8_t *marked;
    uint16_t *queue;
    uint16_t *field_map;
    uint16_t *item_map;
    uint16_t node_capacity;
    uint16_t field_capacity;
    uint16_t item_capacity;
    uint16_t queued;
    uint16_t live_nodes;
    uint16_t live_fields;
    uint16_t live_items;
} PyZ80TargetGC;

/* Explicit safepoint ONLY: call outside Run/provider/ISR, with no borrowed
   node/field/item pointers outstanding. Keep every external handle in roots.
   Foreign opaque values, stale references and corrupt layouts fail closed
   before heap mutation. Runtime locals, suspended frames, vm.result, module
   mappings and attached lexical environments are traced automatically.
   Handles stay stable; field/item indices may move. No automatic retry/GC is
   performed inside an allocation where C temporaries would be invisible.
   This API covers the plain native object protocol only: finalizers, weakrefs
   and foreign provider-owned references need a separate lifetime contract. */
uint8_t PyZ80Target_Collect(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetScopes *scopes, const PyZ80VMValue *roots, uint16_t root_count,
    PyZ80TargetGC *work);

/* Generic host/target scheduler entry: collect at the two safepoints around a
   bounded VM slice. The caller still proves the slice's allocation headroom
   and exposes provider roots. Root failure stops before starting the slice. */
uint8_t PyZ80Target_RunSlice(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetScopes *scopes, const PyZ80VMValue *roots, uint16_t root_count,
    PyZ80TargetGC *work, uint32_t step_budget, PyZ80VMValue *result);
#endif
