#ifndef TILEMAPSTATE_AGGREGATE_H
#define TILEMAPSTATE_AGGREGATE_H
#include "pyz80_buffer_view.h"
#ifndef PY_AGGREGATE_API
#define PY_AGGREGATE_API
#endif
#include "stage_scroll_generated.h"
typedef struct {
    PyBufferView rom;
    PyBufferViewArray vram;
    int32_t target[2];
    int32_t tracker[2];
    int32_t source[2];
} TilemapState;
PY_AGGREGATE_API uint8_t TilemapState___init__(PyBufferFault *pybuf_fault,TilemapState *record);
PY_AGGREGATE_API uint8_t TilemapState__crossing(PyBufferFault *pybuf_fault,TilemapState *record,int32_t layer,int32_t old,int32_t new);
PY_AGGREGATE_API uint8_t TilemapState_advance(PyBufferFault *pybuf_fault,TilemapState *record,const StageScroll *scroll);
PY_AGGREGATE_API uint8_t TilemapState__pump(PyBufferFault *pybuf_fault,TilemapState *record);
PY_AGGREGATE_API uint8_t TilemapState__draw_strip(PyBufferFault *pybuf_fault,TilemapState *record,int32_t layer,int32_t source,int32_t destination);
PY_AGGREGATE_API uint8_t TilemapState_state(PyBufferFault *pybuf_fault,TilemapState *record,int32_t layer,int32_t row,int32_t column,int32_t *result);
#endif
