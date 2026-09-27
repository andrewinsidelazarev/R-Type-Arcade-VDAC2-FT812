#include "pyz80_write_table.h"
#ifndef PY_BUFFER_API
#define PY_BUFFER_API
#endif
PY_BUFFER_API uint8_t Tilemaps_TryTable(PyBufferView *table,PyBufferViewArray *targets,PyBufferSpan *scratch,int32_t pywt_arg0,int32_t pywt_arg1,int32_t pywt_arg2,uint8_t *error);
