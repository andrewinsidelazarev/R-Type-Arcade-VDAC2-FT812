#include "pyz80_buffer_span.h"
#ifndef PY_BUFFER_API
#define PY_BUFFER_API
#endif
PY_BUFFER_API uint8_t Terrain_ApplyStrip(PyBufferFault *pybuf_fault,PyBufferSpan *vram,int32_t destination,PyBufferSpan *strip);
