#include "pyz80_buffer_view.h"
#ifndef PY_BUFFER_API
#define PY_BUFFER_API
#endif
PY_BUFFER_API uint8_t Buffer_CopyWord(PyBufferFault *pybuf_fault,PyBufferView *src,PyBufferView *dst,int32_t read,int32_t write);
