#ifndef PYZ80_TARGET_BUFFERS_H
#define PYZ80_TARGET_BUFFERS_H
#include "pyz80_target_object_runtime.h"
#define PYZ80_BUFFER_BLOCK_SLOTS 8u
#define PYZ80_BUFFER_BLOCK_BYTES 64u
#define PYZ80_IS_BUFFER(n) ((n) && ((n)->kind==PYZ80_TARGET_NODE_BYTES || (n)->kind==PYZ80_TARGET_NODE_BYTEARRAY))
typedef char PyZ80BufferSlotMustBe8Bytes[(sizeof(PyZ80VMValue)==8u)?1:-1];
uint8_t PyZ80Target_BufferValid(PyZ80TargetContext *,const PyZ80TargetNode *);
uint8_t PyZ80Target_BufferBlockValid(PyZ80TargetContext *,const PyZ80TargetNode *);
uint8_t PyZ80Target_EmptyBuffer(PyZ80TargetContext *,PyZ80VMValue *);
uint8_t PyZ80Target_BufferFreeze(PyZ80TargetContext *,PyZ80VMValue *);
uint8_t PyZ80Target_BufferClear(PyZ80TargetContext *,const PyZ80VMValue *);
uint8_t PyZ80Target_BufferAppend(PyZ80TargetContext *,const PyZ80VMValue *,const PyZ80VMValue *);
uint8_t PyZ80Target_BufferRead(PyZ80TargetContext *,const PyZ80VMValue *,uint16_t,PyZ80VMValue *);
uint8_t PyZ80Target_BufferWrite(PyZ80TargetContext *,const PyZ80VMValue *,uint16_t,const PyZ80VMValue *);
uint8_t PyZ80Target_BufferIndex(PyZ80TargetContext *,const PyZ80VMValue *,const PyZ80VMValue *,uint16_t *);
uint8_t PyZ80Target_BufferTraceValid(PyZ80TargetContext *,const PyZ80TargetNode *);
#endif
