/* Generated from active Python AST.  Do not hand-edit. */
#ifndef RTYPE_PYTHON_RENDER_ORDER_H
#define RTYPE_PYTHON_RENDER_ORDER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RTYPE_PYTHON_RENDER_ORDER_SLOT_COUNT 96u
#define RTYPE_PYTHON_RENDER_ORDER_RESERVED_SENTINELS 2u
#define RTYPE_PYTHON_RENDER_ORDER_CAPACITY 94u
#define RTYPE_PYTHON_RENDER_ORDER_NONE 0xFFu
#define RTYPE_PYTHON_RENDER_ORDER_KEEP_MASK_BYTES 12u
#define RTYPE_PYTHON_RENDER_ORDER_CHECKPOINT_COUNT 27u
#define RTYPE_PYTHON_RENDER_ORDER_STATE_BYTES 191u

typedef enum {
    RTYPE_PYTHON_RENDER_ORDER_OK = 0,
    RTYPE_PYTHON_RENDER_ORDER_NULL = 1,
    RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT = 2,
    RTYPE_PYTHON_RENDER_ORDER_DUPLICATE_SLOT = 3,
    RTYPE_PYTHON_RENDER_ORDER_CAPACITY_EXCEEDED = 4,
    RTYPE_PYTHON_RENDER_ORDER_NOT_MEMBER = 5
} rtype_python_render_order_status;

typedef struct {
    uint8_t count;
    uint8_t order[RTYPE_PYTHON_RENDER_ORDER_CAPACITY];
    /* 0xFF means absent; otherwise this is the direct order position. */
    uint8_t position[RTYPE_PYTHON_RENDER_ORDER_SLOT_COUNT];
} rtype_python_render_order_state;

void rtype_python_render_order_reset(rtype_python_render_order_state *state);
rtype_python_render_order_status rtype_python_render_order_seed(
    rtype_python_render_order_state *state, const uint8_t *slots, uint8_t count);
rtype_python_render_order_status rtype_python_render_order_seed_checkpoint(rtype_python_render_order_state *state);
rtype_python_render_order_status rtype_python_render_order_append(rtype_python_render_order_state *state, uint8_t slot);
rtype_python_render_order_status rtype_python_render_order_extend(
    rtype_python_render_order_state *state, const uint8_t *slots, uint8_t count);
rtype_python_render_order_status rtype_python_render_order_remove(rtype_python_render_order_state *state, uint8_t slot);
rtype_python_render_order_status rtype_python_render_order_filter(
    rtype_python_render_order_state *state,
    const uint8_t keep_mask[RTYPE_PYTHON_RENDER_ORDER_KEEP_MASK_BYTES]);
rtype_python_render_order_status rtype_python_render_order_replace_same_slot(
    rtype_python_render_order_state *state, uint8_t slot);

/* O(1) accessors for the compact draw-VM object loader. */
uint8_t rtype_python_render_order_slot_at(
    const rtype_python_render_order_state *state, uint8_t order_position);
uint8_t rtype_python_render_order_position_of(
    const rtype_python_render_order_state *state, uint8_t slot);
uint8_t rtype_python_render_order_contains(
    const rtype_python_render_order_state *state, uint8_t slot);

#ifdef __cplusplus
}
#endif

#endif
