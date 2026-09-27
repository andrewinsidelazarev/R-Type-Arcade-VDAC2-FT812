#ifndef PYZ80_TARGET_CALL_BINDING_H
#define PYZ80_TARGET_CALL_BINDING_H

#include "pyz80_target_scope_runtime.h"

/* Тот же проверенный binder, но только для фабрики генератора. */
uint8_t PyZ80Target_PrepareGeneratorCall(PyZ80TargetScopes *scopes, uint16_t adapter,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function);
/* Явный positional callback библиотеки; общий binder defaults/self/окружения. */
uint8_t PyZ80Target_PreparePositionalCall(PyZ80TargetScopes *, PyZ80VMValue *, uint8_t *, uint16_t *);

/* Optional native signature binder. Scratch is caller-owned, disjoint from VM
   locals/arguments/heap, and lives until detach/destruction. No GC or recursive
   Run is allowed during binding. Completed binding copies into VM arguments;
   scratch is not a persistent root. Unknown/star/variadic calls fail closed.
   Low-level StartArgs/StartClosure still take a fully bound parameter vector. */
uint8_t PyZ80Target_AttachCallBinding(PyZ80TargetScopes *scopes,
    PyZ80VMValue *scratch, uint8_t capacity);

#endif
