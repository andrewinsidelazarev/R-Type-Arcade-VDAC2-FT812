#ifndef PYZ80_TARGET_GENERATORS_H
#define PYZ80_TARGET_GENERATORS_H

#include "pyz80_target_call_binding.h"

typedef struct PyZ80TargetGeneratorRequest {
    uint32_t pc;
    uint16_t adapter;
    uint8_t state, mode, has_value;
} PyZ80TargetGeneratorRequest;

typedef struct PyZ80TargetGenerators {
    PyZ80VMControlHooks hooks;
    PyZ80TargetScopes *scopes;
    PyZ80TargetGeneratorRequest *frames;
    PyZ80VMValue *roots;
    uint8_t capacity;
} PyZ80TargetGenerators;

/* Проверка отсутствия пересечения нового буфера с VM, heap и корнями цепочки. */
uint8_t PyZ80Target_ControlStorageSeparate(PyZ80TargetScopes *, const void *, uint32_t);

/* По три корня на глубину: iterator, накапливаемая коллекция, результат.
   Подключать после imports/classes; буферы принадлежат вызывающему коду. */
uint8_t PyZ80Target_AttachGenerators(PyZ80TargetGenerators *, PyZ80TargetScopes *,
    PyZ80TargetGeneratorRequest *, PyZ80VMValue *, uint8_t, uint16_t *);

#endif
