#include "pyz80_buffer_view.h"
#ifndef PY_BUFFER_API
#define PY_BUFFER_API
#endif
PY_BUFFER_API uint8_t Tilemaps_DrawStrip(PyBufferFault *pybuf_fault,PyBufferView *pybuf_field_0,PyBufferViewArray *pybuf_field_1,int32_t layer,int32_t source,int32_t destination);
