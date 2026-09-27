#ifndef PYZ80_TARGET_SEQUENCES_H
#define PYZ80_TARGET_SEQUENCES_H

#include "pyz80_target_generators.h"

typedef struct PyZ80TargetSequenceRequest {
    uint32_t pc;
    int32_t step;
    uint16_t adapter, source_count, index, remaining, produced;
    uint8_t mode, kind;
} PyZ80TargetSequenceRequest;

#ifdef __SDCC
typedef char PyZ80SequenceFrameMustBe20Bytes[(sizeof(PyZ80TargetSequenceRequest)==20u) ? 1 : -1];
#endif

typedef struct PyZ80TargetSequences {
    PyZ80VMControlHooks hooks;
    PyZ80TargetScopes *scopes;
    PyZ80TargetSequenceRequest *frames;
    PyZ80VMValue *roots;
    uint8_t capacity;
} PyZ80TargetSequences;

/* Два корня на глубину: источник и строящийся результат. За шаг копируется
   один элемент; *= публикует новый срез только после полного успеха. */
uint8_t PyZ80Target_AttachSequences(PyZ80TargetSequences *,PyZ80TargetScopes *,
    PyZ80TargetSequenceRequest *,PyZ80VMValue *,uint8_t,uint16_t *);

#endif
