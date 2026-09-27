/* Generated from active Python AST.  Do not hand-edit. */
#include "rtype_python_render_order.h"

static const uint8_t rtype_python_render_order_checkpoint_slots[
        RTYPE_PYTHON_RENDER_ORDER_CHECKPOINT_COUNT] = { 53u, 52u, 51u, 50u, 49u, 48u, 47u, 46u, 45u, 44u, 43u, 42u, 41u, 40u, 39u, 38u, 37u, 36u, 35u, 33u, 34u, 32u, 31u, 30u, 29u, 28u, 24u };

static uint8_t rtype_python_render_order_valid_slot(uint8_t slot)
{
    return (uint8_t)(slot >= RTYPE_PYTHON_RENDER_ORDER_RESERVED_SENTINELS &&
                     slot < RTYPE_PYTHON_RENDER_ORDER_SLOT_COUNT);
}

static uint8_t rtype_python_render_order_kept(const uint8_t *mask, uint8_t slot)
{
    return (uint8_t)((mask[slot >> 3] >> (slot & 7u)) & 1u);
}

void rtype_python_render_order_reset(rtype_python_render_order_state *state)
{
    uint8_t index;
    if (state == 0) return;
    state->count = 0u;
    for (index = 0u; index < RTYPE_PYTHON_RENDER_ORDER_CAPACITY; ++index)
        state->order[index] = RTYPE_PYTHON_RENDER_ORDER_NONE;
    for (index = 0u; index < RTYPE_PYTHON_RENDER_ORDER_SLOT_COUNT; ++index)
        state->position[index] = RTYPE_PYTHON_RENDER_ORDER_NONE;
}

rtype_python_render_order_status rtype_python_render_order_seed(
        rtype_python_render_order_state *state, const uint8_t *slots, uint8_t count)
{
    uint8_t index;
    uint8_t other;
    uint8_t slot;
    if (state == 0 || (count != 0u && slots == 0)) return RTYPE_PYTHON_RENDER_ORDER_NULL;
    if (count > RTYPE_PYTHON_RENDER_ORDER_CAPACITY) return RTYPE_PYTHON_RENDER_ORDER_CAPACITY_EXCEEDED;
    for (index = 0u; index < count; ++index) {
        slot = slots[index];
        if (!rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT;
        for (other = 0u; other < index; ++other)
            if (slots[other] == slot) return RTYPE_PYTHON_RENDER_ORDER_DUPLICATE_SLOT;
    }
    rtype_python_render_order_reset(state);
    for (index = 0u; index < count; ++index) {
        slot = slots[index];
        state->order[index] = slot;
        state->position[slot] = index;
    }
    state->count = count;
    return RTYPE_PYTHON_RENDER_ORDER_OK;
}

rtype_python_render_order_status rtype_python_render_order_seed_checkpoint(rtype_python_render_order_state *state)
{
    return rtype_python_render_order_seed(state, rtype_python_render_order_checkpoint_slots,
                         RTYPE_PYTHON_RENDER_ORDER_CHECKPOINT_COUNT);
}

rtype_python_render_order_status rtype_python_render_order_append(rtype_python_render_order_state *state, uint8_t slot)
{
    uint8_t position;
    if (state == 0) return RTYPE_PYTHON_RENDER_ORDER_NULL;
    if (state->count >= RTYPE_PYTHON_RENDER_ORDER_CAPACITY)
        return RTYPE_PYTHON_RENDER_ORDER_CAPACITY_EXCEEDED;
    if (!rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT;
    if (state->position[slot] != RTYPE_PYTHON_RENDER_ORDER_NONE)
        return RTYPE_PYTHON_RENDER_ORDER_DUPLICATE_SLOT;
    position = state->count;
    state->order[position] = slot;
    state->position[slot] = position;
    state->count = (uint8_t)(position + 1u);
    return RTYPE_PYTHON_RENDER_ORDER_OK;
}

rtype_python_render_order_status rtype_python_render_order_extend(
        rtype_python_render_order_state *state, const uint8_t *slots, uint8_t count)
{
    uint8_t index;
    uint8_t other;
    uint8_t slot;
    uint8_t position;
    if (state == 0 || (count != 0u && slots == 0)) return RTYPE_PYTHON_RENDER_ORDER_NULL;
    if ((uint16_t)state->count + (uint16_t)count > RTYPE_PYTHON_RENDER_ORDER_CAPACITY)
        return RTYPE_PYTHON_RENDER_ORDER_CAPACITY_EXCEEDED;
    for (index = 0u; index < count; ++index) {
        slot = slots[index];
        if (!rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT;
        if (state->position[slot] != RTYPE_PYTHON_RENDER_ORDER_NONE)
            return RTYPE_PYTHON_RENDER_ORDER_DUPLICATE_SLOT;
        for (other = 0u; other < index; ++other)
            if (slots[other] == slot) return RTYPE_PYTHON_RENDER_ORDER_DUPLICATE_SLOT;
    }
    position = state->count;
    for (index = 0u; index < count; ++index) {
        slot = slots[index];
        state->order[position] = slot;
        state->position[slot] = position;
        ++position;
    }
    state->count = position;
    return RTYPE_PYTHON_RENDER_ORDER_OK;
}

rtype_python_render_order_status rtype_python_render_order_remove(rtype_python_render_order_state *state, uint8_t slot)
{
    uint8_t position;
    uint8_t next;
    if (state == 0) return RTYPE_PYTHON_RENDER_ORDER_NULL;
    if (!rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT;
    position = state->position[slot];
    if (position == RTYPE_PYTHON_RENDER_ORDER_NONE) return RTYPE_PYTHON_RENDER_ORDER_NOT_MEMBER;
    for (; (uint8_t)(position + 1u) < state->count; ++position) {
        next = state->order[(uint8_t)(position + 1u)];
        state->order[position] = next;
        state->position[next] = position;
    }
    --state->count;
    state->order[state->count] = RTYPE_PYTHON_RENDER_ORDER_NONE;
    state->position[slot] = RTYPE_PYTHON_RENDER_ORDER_NONE;
    return RTYPE_PYTHON_RENDER_ORDER_OK;
}

rtype_python_render_order_status rtype_python_render_order_filter(
        rtype_python_render_order_state *state,
        const uint8_t keep_mask[RTYPE_PYTHON_RENDER_ORDER_KEEP_MASK_BYTES])
{
    uint8_t slot;
    uint8_t read_position;
    uint8_t write_position = 0u;
    uint8_t old_count;
    if (state == 0 || keep_mask == 0) return RTYPE_PYTHON_RENDER_ORDER_NULL;
    for (slot = 0u; slot < RTYPE_PYTHON_RENDER_ORDER_SLOT_COUNT; ++slot) {
        if (!rtype_python_render_order_kept(keep_mask, slot)) continue;
        if (!rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT;
        if (state->position[slot] == RTYPE_PYTHON_RENDER_ORDER_NONE)
            return RTYPE_PYTHON_RENDER_ORDER_NOT_MEMBER;
    }
    old_count = state->count;
    for (read_position = 0u; read_position < old_count; ++read_position) {
        slot = state->order[read_position];
        if (rtype_python_render_order_kept(keep_mask, slot)) {
            state->order[write_position] = slot;
            state->position[slot] = write_position;
            ++write_position;
        } else {
            state->position[slot] = RTYPE_PYTHON_RENDER_ORDER_NONE;
        }
    }
    for (read_position = write_position; read_position < old_count;
            ++read_position)
        state->order[read_position] = RTYPE_PYTHON_RENDER_ORDER_NONE;
    state->count = write_position;
    return RTYPE_PYTHON_RENDER_ORDER_OK;
}

rtype_python_render_order_status rtype_python_render_order_replace_same_slot(
        rtype_python_render_order_state *state, uint8_t slot)
{
    if (state == 0) return RTYPE_PYTHON_RENDER_ORDER_NULL;
    if (!rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_INVALID_SLOT;
    if (state->position[slot] == RTYPE_PYTHON_RENDER_ORDER_NONE) return RTYPE_PYTHON_RENDER_ORDER_NOT_MEMBER;
    /* Object identity/class sidecars change; list position deliberately does not. */
    return RTYPE_PYTHON_RENDER_ORDER_OK;
}

uint8_t rtype_python_render_order_slot_at(
        const rtype_python_render_order_state *state, uint8_t order_position)
{
    if (state == 0 || order_position >= state->count) return RTYPE_PYTHON_RENDER_ORDER_NONE;
    return state->order[order_position];
}

uint8_t rtype_python_render_order_position_of(
        const rtype_python_render_order_state *state, uint8_t slot)
{
    if (state == 0 || !rtype_python_render_order_valid_slot(slot)) return RTYPE_PYTHON_RENDER_ORDER_NONE;
    return state->position[slot];
}

uint8_t rtype_python_render_order_contains(
        const rtype_python_render_order_state *state, uint8_t slot)
{
    return (uint8_t)(rtype_python_render_order_position_of(state, slot) != RTYPE_PYTHON_RENDER_ORDER_NONE);
}
