#ifndef PYZ80_TARGET_SORT_H
#define PYZ80_TARGET_SORT_H

#include "pyz80_target_generators.h"

typedef struct PyZ80TargetSortRequest {
    uint32_t pc;
    uint16_t adapter,n,width,left,mid,end,i,j,out;
    uint8_t state,reverse;
} PyZ80TargetSortRequest;

#if defined(__SDCC)
typedef char PyZ80TargetSortRequestSize[(sizeof(PyZ80TargetSortRequest)==24u) ? 1 : -1];
#endif

typedef struct PyZ80TargetSort {
    PyZ80VMControlHooks hooks;
    PyZ80TargetScopes *scopes;
    PyZ80TargetSortRequest *frames;
    PyZ80VMValue *roots;
    uint8_t capacity;
} PyZ80TargetSort;

/* Семь корней на глубину: iterator, key, values, keys, два буфера, key-result.
   min/max разделяют это хранилище: iterator, key, лучший элемент/ключ,
   кандидат, default и key-result; без буферов сортировки или копии входа.
   Подключать после остальных control providers; хранилище caller-owned. */
uint8_t PyZ80Target_AttachSort(PyZ80TargetSort *, PyZ80TargetScopes *,
    PyZ80TargetSortRequest *, PyZ80VMValue *, uint8_t, uint16_t *);

#endif
