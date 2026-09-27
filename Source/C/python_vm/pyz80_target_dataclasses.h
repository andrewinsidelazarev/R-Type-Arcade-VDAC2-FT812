#ifndef PYZ80_TARGET_DATACLASSES_H
#define PYZ80_TARGET_DATACLASSES_H
#include "pyz80_target_classes.h"

#define PYZ80_DATACLASS_SYMBOL_COUNT 29u
typedef struct PyZ80DataclassField { uint16_t name, has_default, annotation; } PyZ80DataclassField;
typedef struct PyZ80DataclassClass {
    uint16_t origin, qualname, field_start, field_count, apply_plain, apply_post, valid_init, module;
} PyZ80DataclassClass;
typedef struct PyZ80DataclassPlan {
    const PyZ80DataclassClass *classes;
    const PyZ80DataclassField *fields;
    const uint16_t *symbols;
    const uint8_t *proof;
    uint16_t class_count, field_count;
} PyZ80DataclassPlan;
typedef struct PyZ80TargetDataclasses {
    PyZ80TargetScopes *scopes;
    const PyZ80DataclassPlan *plan;
} PyZ80TargetDataclasses;

/* Caller-owned lifetime, attach once while idle after classes/imports. The
   provider only selects source functions; all factories use normal VM frames.
   No recursive C execution, hidden Python stack or retained untraced values.
   Unsupported frozen/slots/field descriptors and metadata/repr operations fail
   closed, never fabricate values or silently omit the generated methods. */
uint8_t PyZ80Target_AttachDataclasses(PyZ80TargetDataclasses *context,
    PyZ80TargetScopes *scopes, const PyZ80DataclassPlan *plan);
#endif
