#ifndef PYZ80_TARGET_BUILTINS_H
#define PYZ80_TARGET_BUILTINS_H

#include "pyz80_target_object_runtime.h"

/* Install only after binding the hash-bound symbol/layout tables. No globals,
   no heap allocation for builtin identities, and no recursive VM execution.
   Supports ordinary positional calls. Unknown protocols fail closed.
   Range: i32 endpoints/step, <=65535 elements, lazy iteration; no bigint/slice.
   getattr: native plain fields only; descriptors remain a separate protocol. */
void PyZ80Target_EnableBuiltins(PyZ80TargetContext *context);

/* Ровно два int32/bool: одно сравнение, без heap и кадров продолжения.
   На равенстве сохраняется первый объект, включая тип bool. */
uint8_t PyZ80Target_FastExtremum(uint8_t operation,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result);

#endif
