#ifndef PYZ80_TARGET_TYPE_CHECKS_H
#define PYZ80_TARGET_TYPE_CHECKS_H
#include "pyz80_target_classes.h"

/* Обычные классы, сохранённый C3 и native-типы; без вызова Python/GC.
   Кортежи classinfo обходятся по одному узлу на VM-шаг. Временно используется
   проверенный binding_scratch: binder во время этого вызова не исполняется. */
uint8_t PyZ80Target_TypeCheck(PyZ80TargetClasses *,PyZ80VM *,uint16_t,
    const PyZ80VMValue *,PyZ80VMValue *);
void PyZ80Target_TypeCheckClear(PyZ80TargetClasses *,uint8_t);
#endif
