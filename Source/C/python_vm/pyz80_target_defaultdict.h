#ifndef PYZ80_TARGET_DEFAULTDICT_H
#define PYZ80_TARGET_DEFAULTDICT_H
#include "pyz80_target_generators.h"

typedef struct PyZ80TargetDefaultDictFrame {
    uint32_t pc;
    uint16_t adapter;
    uint8_t phase,index;
} PyZ80TargetDefaultDictFrame;
#ifdef __SDCC
typedef char PyZ80DefaultDictFrameMustBe8Bytes[(sizeof(PyZ80TargetDefaultDictFrame)==8u) ? 1 : -1];
#endif
typedef struct PyZ80TargetDefaultDict {
    PyZ80VMControlHooks hooks;
    PyZ80TargetScopes *scopes;
    PyZ80TargetDefaultDictFrame *frames;
    PyZ80VMValue *roots;
    uint8_t capacity;
} PyZ80TargetDefaultDict;

/* Четыре корня на глубину: словарь, ключ, фабрика/итератор, результат.
   Python-фабрика вызывается кадром VM, а не рекурсивным запуском C-интерпретатора. */
uint8_t PyZ80Target_AttachDefaultDict(PyZ80TargetDefaultDict *,PyZ80TargetScopes *,
    PyZ80TargetDefaultDictFrame *,PyZ80VMValue *,uint8_t,uint16_t *);
#endif
