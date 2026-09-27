/* Весь скалярный dataclass сгенерирован из AST, без проекции эффектов. */
#ifndef STAGESCROLL_RECORD_H
#define STAGESCROLL_RECORD_H
#ifndef PY_RECORD_API
#define PY_RECORD_API
#endif
#include <stdint.h>
#ifndef PY_RECORD_MAYBE_I32
#define PY_RECORD_MAYBE_I32
typedef struct { int32_t value; uint8_t present; } PyRecordMaybeI32;
#endif
typedef struct {
    int32_t vblank;
    int32_t foreground_accumulator;
    int32_t foreground_velocity;
    int32_t background_accumulator;
    int32_t background_velocity;
    int32_t stage1_no_fire_reference;
    int32_t progression_accumulator;
    int32_t foreground_delta;
    int32_t background_delta;
    PyRecordMaybeI32 pending_foreground_velocity;
    PyRecordMaybeI32 pending_background_velocity;
    int32_t pending_scroll_accumulator_reset;
    PyRecordMaybeI32 pending_progression_accumulator;
} StageScroll;
PY_RECORD_API void StageScroll_init(StageScroll *record);
PY_RECORD_API void StageScroll_queue_object_velocity_write(StageScroll *record, const PyRecordMaybeI32 *foreground, const PyRecordMaybeI32 *background);
PY_RECORD_API void StageScroll_queue_stage_transition_reset(StageScroll *record);
PY_RECORD_API void StageScroll_queue_stage_init(StageScroll *record, int32_t progression, int32_t foreground_velocity, int32_t background_velocity);
PY_RECORD_API int32_t StageScroll_foreground_x(StageScroll *record);
PY_RECORD_API int32_t StageScroll_background_x(StageScroll *record);
PY_RECORD_API void StageScroll_advance(StageScroll *record);
PY_RECORD_API int32_t StageScroll_progression(StageScroll *record);
PY_RECORD_API int32_t StageScroll_dispatch_progression(StageScroll *record);
PY_RECORD_API int32_t StageScroll_dispatch_foreground_x(StageScroll *record);
PY_RECORD_API int32_t StageScroll_dispatch_background_x(StageScroll *record);
PY_RECORD_API int32_t StageScroll__integrated_delta(int32_t accumulator, int32_t velocity);
PY_RECORD_API int32_t StageScroll_dispatch_foreground_delta(StageScroll *record);
PY_RECORD_API int32_t StageScroll_dispatch_background_delta(StageScroll *record);
#endif
