#ifndef PYZ80_TARGET_DEQUE_H
#define PYZ80_TARGET_DEQUE_H
#include "pyz80_target_object_runtime.h"

#define PYZ80_DEQUE_BLOCK_ITEMS 16u

uint8_t PyZ80Target_EmptyDeque(PyZ80TargetContext *,PyZ80VMValue *);
uint8_t PyZ80Target_DequeValid(PyZ80TargetContext *,const PyZ80TargetNode *);
uint8_t PyZ80Target_DequeBlockValid(PyZ80TargetContext *,const PyZ80TargetNode *);
uint8_t PyZ80Target_DequeAppend(PyZ80TargetContext *,const PyZ80VMValue *,const PyZ80VMValue *);
uint8_t PyZ80Target_DequePopleft(PyZ80TargetContext *,const PyZ80VMValue *,PyZ80VMValue *);
uint8_t PyZ80Target_DequeClear(PyZ80TargetContext *,const PyZ80VMValue *);
uint8_t PyZ80Target_DequeIterator(PyZ80TargetContext *,const PyZ80VMValue *,PyZ80VMValue *);
uint8_t PyZ80Target_DequeIteratorValid(PyZ80TargetContext *,const PyZ80TargetNode *);
uint8_t PyZ80Target_DequeIterNext(PyZ80TargetContext *,const PyZ80VMValue *,PyZ80VMValue *);
#endif
