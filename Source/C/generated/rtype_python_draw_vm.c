/* Generated from SpriteDrawPlanIR. Do not edit. */
/* Compact table program; no handwritten gameplay semantics. */
/* source: Source/Python/rtype_port/enemies.py */
/* plan semantic SHA-256: 8deb7410b166f70abea16a78a5cb472952871c068dde1d17efde1de9356119c8 */
#include "rtype_python_draw_vm.h"
#include <stddef.h>

typedef char rtype_python_draw_vm_assert_record_size[
    (sizeof(rtype_python_draw_vm_record) == 8) ? 1 : -1];
typedef char rtype_python_draw_vm_assert_bank_key_offset[
    (offsetof(rtype_python_draw_vm_record, bank_key) == 0) ? 1 : -1];
typedef char rtype_python_draw_vm_assert_descriptor_offset[
    (offsetof(rtype_python_draw_vm_record, descriptor) == 2) ? 1 : -1];
typedef char rtype_python_draw_vm_assert_anchor_x_offset[
    (offsetof(rtype_python_draw_vm_record, anchor_x) == 4) ? 1 : -1];
typedef char rtype_python_draw_vm_assert_anchor_y_offset[
    (offsetof(rtype_python_draw_vm_record, anchor_y) == 6) ? 1 : -1];
#ifdef __SDCC
typedef char rtype_python_draw_vm_assert_object_view_size[
    (sizeof(rtype_python_draw_vm_object_view) ==
        RTYPE_PYTHON_DRAW_VM_OBJECT_VIEW_BYTES) ? 1 : -1];
#endif

#define RTYPE_PYTHON_DRAW_VM_OP_CONST 0u
#define RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD 1u
#define RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD 2u
#define RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY 3u
#define RTYPE_PYTHON_DRAW_VM_OP_NOT 4u
#define RTYPE_PYTHON_DRAW_VM_OP_AND 5u
#define RTYPE_PYTHON_DRAW_VM_OP_ADD 6u
#define RTYPE_PYTHON_DRAW_VM_OP_EQUAL 7u
#define RTYPE_PYTHON_DRAW_VM_OP_NOT_EQUAL 8u
#define RTYPE_PYTHON_DRAW_VM_OP_SELECT 9u
#define RTYPE_PYTHON_DRAW_VM_OP_RESOURCE_TYPE 10u
#define RTYPE_PYTHON_DRAW_VM_LOOP_OBJECTS 0u
#define RTYPE_PYTHON_DRAW_VM_LOOP_TRANSIENTS 1u
#define RTYPE_PYTHON_DRAW_VM_NODE_COUNT 79u
#define RTYPE_PYTHON_DRAW_VM_ACTION_COUNT 34u
#define RTYPE_PYTHON_DRAW_VM_LOOP_COUNT 2u

typedef struct rtype_python_draw_vm_node {
    uint8_t op, a, b, c;
} rtype_python_draw_vm_node;
typedef char rtype_python_draw_vm_assert_node_size[
    (sizeof(rtype_python_draw_vm_node) == 4) ? 1 : -1];

typedef struct rtype_python_draw_vm_condition_pack {
    uint8_t first, count;
} rtype_python_draw_vm_condition_pack;
typedef char rtype_python_draw_vm_assert_condition_pack_size[
    (sizeof(rtype_python_draw_vm_condition_pack) == 2) ? 1 : -1];

typedef struct rtype_python_draw_vm_action {
    uint8_t condition_pack, descriptor, palette;
    uint8_t resource_type, anchor_x, anchor_y;
} rtype_python_draw_vm_action;
typedef char rtype_python_draw_vm_assert_action_size[
    (sizeof(rtype_python_draw_vm_action) == 6) ? 1 : -1];

typedef struct rtype_python_draw_vm_loop {
    uint8_t kind, first_action, action_count;
} rtype_python_draw_vm_loop;
typedef char rtype_python_draw_vm_assert_loop_size[
    (sizeof(rtype_python_draw_vm_loop) == 3) ? 1 : -1];

static const int32_t rtype_python_draw_vm_constants[] = {
    255L,
    6L,
    1L,
    2L,
    23048L,
    23054L,
    23060L,
    23066L,
    23072L,
    23116L,
    23122L,
    23128L,
    23134L,
    23140L,
    23176L,
    23182L,
    23188L,
    12360L,
    12366L,
    12372L,
    12378L,
    12384L,
    12390L,
    12396L,
};

static const uint8_t rtype_python_draw_vm_class_masks[][
        RTYPE_PYTHON_DRAW_VM_CLASS_BIT_BYTES] = {
    { 0x02u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x80u, 0x00u },
    { 0xE5u, 0xCFu, 0x7Au, 0x02u },
    { 0x00u, 0x00u, 0x40u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x01u },
    { 0x00u, 0x10u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x01u, 0x00u },
    { 0x00u, 0x08u, 0x00u, 0x00u },
    { 0x00u, 0x01u, 0x00u, 0x00u },
    { 0x80u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x02u, 0x00u },
    { 0x00u, 0x40u, 0x00u, 0x00u },
    { 0x20u, 0x04u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x20u, 0x00u },
    { 0x1Cu, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x20u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x04u, 0x00u },
};

static const rtype_python_draw_vm_node rtype_python_draw_vm_nodes[] = {
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 7u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 0u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_EQUAL, 0u, 1u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 2u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 8u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 4u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 5u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 0u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_AND, 7u, 5u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 8u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 1u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 10u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 11u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_AND, 10u, 12u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 13u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 2u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 2u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 0u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_SELECT, 16u, 17u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_RESOURCE_TYPE, 18u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 11u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 12u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 3u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 1u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_ADD, 15u, 23u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 4u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 5u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 3u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 2u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_EQUAL, 27u, 28u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_AND, 26u, 29u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 6u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 7u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 8u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 9u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 10u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 11u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 9u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_EQUAL, 37u, 28u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_AND, 36u, 38u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 12u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 13u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 1u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 3u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_EQUAL, 42u, 43u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 4u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 5u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 6u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 7u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 8u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 44u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_EQUAL, 42u, 28u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 9u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 10u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 11u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 12u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 13u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_NOT, 51u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 14u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 15u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 16u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 14u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 15u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 17u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 18u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 19u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 20u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 21u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 22u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CONST, 23u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY, 16u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 4u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 5u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD, 6u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD, 0u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD, 1u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD, 2u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD, 3u, 0u, 0u },
    { RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD, 4u, 0u, 0u },
};

static const uint8_t rtype_python_draw_vm_condition_ids[] = {
    3u,
    6u,
    9u,
    14u,
    3u,
    6u,
    9u,
    14u,
    22u,
    3u,
    6u,
    9u,
    14u,
    25u,
    3u,
    6u,
    9u,
    14u,
    30u,
    3u,
    6u,
    9u,
    14u,
    31u,
    3u,
    6u,
    9u,
    14u,
    32u,
    3u,
    6u,
    9u,
    14u,
    33u,
    3u,
    6u,
    9u,
    14u,
    34u,
    3u,
    6u,
    9u,
    14u,
    35u,
    3u,
    6u,
    9u,
    14u,
    39u,
    3u,
    6u,
    9u,
    14u,
    40u,
    3u,
    6u,
    9u,
    14u,
    41u,
    44u,
    3u,
    6u,
    9u,
    14u,
    41u,
    50u,
    51u,
    3u,
    6u,
    9u,
    14u,
    41u,
    50u,
    57u,
    3u,
    6u,
    9u,
    14u,
    61u,
    3u,
    6u,
    9u,
    14u,
    62u,
    3u,
    6u,
    9u,
    14u,
    70u,
};

static const rtype_python_draw_vm_condition_pack rtype_python_draw_vm_condition_packs[] = {
    { 0u, 4u },
    { 4u, 5u },
    { 9u, 5u },
    { 14u, 5u },
    { 19u, 5u },
    { 24u, 5u },
    { 29u, 5u },
    { 34u, 5u },
    { 39u, 5u },
    { 44u, 5u },
    { 49u, 5u },
    { 54u, 6u },
    { 60u, 7u },
    { 67u, 7u },
    { 74u, 5u },
    { 79u, 5u },
    { 84u, 5u },
    { 89u, 0u },
};

static const rtype_python_draw_vm_action rtype_python_draw_vm_actions[] = {
    { 0u, 15u, 18u, 19u, 20u, 21u },
    { 1u, 24u, 18u, 19u, 20u, 21u },
    { 2u, 24u, 18u, 19u, 20u, 21u },
    { 3u, 24u, 18u, 19u, 20u, 21u },
    { 4u, 24u, 18u, 19u, 20u, 21u },
    { 5u, 24u, 18u, 19u, 20u, 21u },
    { 6u, 24u, 18u, 19u, 20u, 21u },
    { 7u, 24u, 18u, 19u, 20u, 21u },
    { 8u, 24u, 18u, 19u, 20u, 21u },
    { 9u, 24u, 18u, 19u, 20u, 21u },
    { 10u, 24u, 18u, 19u, 20u, 21u },
    { 11u, 45u, 18u, 19u, 20u, 21u },
    { 11u, 46u, 18u, 19u, 20u, 21u },
    { 11u, 47u, 18u, 19u, 20u, 21u },
    { 11u, 48u, 18u, 19u, 20u, 21u },
    { 11u, 49u, 18u, 19u, 20u, 21u },
    { 12u, 52u, 18u, 19u, 20u, 21u },
    { 12u, 53u, 18u, 19u, 20u, 21u },
    { 12u, 54u, 18u, 19u, 20u, 21u },
    { 12u, 55u, 18u, 19u, 20u, 21u },
    { 12u, 56u, 18u, 19u, 20u, 21u },
    { 13u, 58u, 18u, 19u, 20u, 21u },
    { 13u, 59u, 18u, 19u, 20u, 21u },
    { 13u, 60u, 18u, 19u, 20u, 21u },
    { 14u, 24u, 18u, 19u, 20u, 21u },
    { 15u, 63u, 18u, 19u, 20u, 21u },
    { 15u, 64u, 18u, 19u, 20u, 21u },
    { 15u, 65u, 18u, 19u, 20u, 21u },
    { 15u, 66u, 18u, 19u, 20u, 21u },
    { 15u, 67u, 18u, 19u, 20u, 21u },
    { 15u, 68u, 18u, 19u, 20u, 21u },
    { 15u, 69u, 18u, 19u, 20u, 21u },
    { 16u, 71u, 18u, 19u, 72u, 73u },
    { 17u, 74u, 75u, 76u, 77u, 78u },
};

static const rtype_python_draw_vm_loop rtype_python_draw_vm_loops[] = {
    { RTYPE_PYTHON_DRAW_VM_LOOP_OBJECTS, 0u, 33u },
    { RTYPE_PYTHON_DRAW_VM_LOOP_TRANSIENTS, 33u, 1u },
};

typedef struct rtype_python_draw_vm_eval_context {
    const rtype_python_draw_vm_input *input;
    const rtype_python_draw_vm_object_view *object;
    const rtype_python_draw_vm_transient_view *transient;
} rtype_python_draw_vm_eval_context;

static int32_t rtype_python_draw_vm_object_field(
        const rtype_python_draw_vm_object_view *object, uint8_t field)
{
    switch (field) {
    case 0u: return (int32_t)object->field_active_palette;
    case 1u: return (int32_t)object->field_body_kind;
    case 2u: return (int32_t)object->field_descriptor;
    case 3u: return (int32_t)object->field_effect;
    case 4u: return (int32_t)object->field_overlay_descriptor;
    case 5u: return (int32_t)object->field_overlay_x;
    case 6u: return (int32_t)object->field_overlay_y;
    case 7u: return (int32_t)object->field_palette;
    case 8u: return (int32_t)object->field_render_ready;
    case 9u: return (int32_t)object->field_state;
    case 10u: return (int32_t)object->field_visible;
    case 11u: return (int32_t)object->field_x;
    case 12u: return (int32_t)object->field_y;
    default: return 0L;
    }
}

static int32_t rtype_python_draw_vm_transient_field(
        const rtype_python_draw_vm_transient_view *transient, uint8_t field)
{
    switch (field) {
    case 0u: return (int32_t)transient->descriptor;
    case 1u: return (int32_t)transient->palette;
    case 2u: return (int32_t)transient->resource_type;
    case 3u: return (int32_t)transient->x;
    case 4u: return (int32_t)transient->y;
    default: return 0L;
    }
}

static int32_t rtype_python_draw_vm_eval(
        const rtype_python_draw_vm_eval_context *context, uint8_t node_id)
{
    const rtype_python_draw_vm_node *node = &rtype_python_draw_vm_nodes[node_id];
    int32_t left, right;
    uint8_t index;
    switch (node->op) {
    case RTYPE_PYTHON_DRAW_VM_OP_CONST:
        return rtype_python_draw_vm_constants[node->a];
    case RTYPE_PYTHON_DRAW_VM_OP_OBJECT_FIELD:
        return rtype_python_draw_vm_object_field(context->object, node->a);
    case RTYPE_PYTHON_DRAW_VM_OP_TRANSIENT_FIELD:
        return rtype_python_draw_vm_transient_field(context->transient, node->a);
    case RTYPE_PYTHON_DRAW_VM_OP_CLASS_ANY:
        for (index = 0u; index < RTYPE_PYTHON_DRAW_VM_CLASS_BIT_BYTES; ++index) {
            if ((context->object->class_bits[index] &
                    rtype_python_draw_vm_class_masks[node->a][index]) != 0u) {
                return 1L;
            }
        }
        return 0L;
    case RTYPE_PYTHON_DRAW_VM_OP_NOT:
        return rtype_python_draw_vm_eval(context, node->a) == 0L;
    case RTYPE_PYTHON_DRAW_VM_OP_AND:
        left = rtype_python_draw_vm_eval(context, node->a);
        return left != 0L ? (rtype_python_draw_vm_eval(context, node->b) != 0L) : 0L;
    case RTYPE_PYTHON_DRAW_VM_OP_ADD:
        left = rtype_python_draw_vm_eval(context, node->a);
        right = rtype_python_draw_vm_eval(context, node->b);
        return left + right;
    case RTYPE_PYTHON_DRAW_VM_OP_EQUAL:
        left = rtype_python_draw_vm_eval(context, node->a);
        right = rtype_python_draw_vm_eval(context, node->b);
        return left == right;
    case RTYPE_PYTHON_DRAW_VM_OP_NOT_EQUAL:
        left = rtype_python_draw_vm_eval(context, node->a);
        right = rtype_python_draw_vm_eval(context, node->b);
        return left != right;
    case RTYPE_PYTHON_DRAW_VM_OP_SELECT:
        return rtype_python_draw_vm_eval(context, node->a) != 0L ?
            rtype_python_draw_vm_eval(context, node->b) :
            rtype_python_draw_vm_eval(context, node->c);
    case RTYPE_PYTHON_DRAW_VM_OP_RESOURCE_TYPE:
        return (int32_t)context->input->resolve_resource_type(
            context->input->resource_context,
            (uint16_t)rtype_python_draw_vm_eval(context, node->a));
    default:
        return 0L;
    }
}

static uint8_t rtype_python_draw_vm_conditions(
        const rtype_python_draw_vm_eval_context *context, uint8_t pack_id)
{
    const rtype_python_draw_vm_condition_pack *pack =
        &rtype_python_draw_vm_condition_packs[pack_id];
    uint8_t index;
    for (index = 0u; index < pack->count; ++index) {
        if (rtype_python_draw_vm_eval(context,
                rtype_python_draw_vm_condition_ids[pack->first + index]) == 0L) {
            return 0u;
        }
    }
    return 1u;
}

static uint8_t rtype_python_draw_vm_input_valid(const rtype_python_draw_vm_input *input)
{
    return (uint8_t)(input != NULL &&
            input->resolve_resource_type != NULL &&
            input->resolve_bank_key != NULL &&
            (input->object_count == 0u ||
                input->load_object != NULL || input->objects != NULL) &&
            (input->transient_count == 0u || input->transients != NULL));
}

static rtype_python_draw_vm_status rtype_python_draw_vm_walk(
        const rtype_python_draw_vm_input *input, uint8_t emitting,
        rtype_python_draw_vm_record_emitter emit_record, void *emit_context,
        uint16_t *count_out)
{
    rtype_python_draw_vm_eval_context context;
    rtype_python_draw_vm_object_view loaded_object;
    uint32_t needed = 0UL;
    uint16_t emitted = 0u;
    uint16_t item_index, item_count;
    uint8_t loop_index, action_offset;
    context.input = input;
    context.object = NULL;
    context.transient = NULL;
    for (loop_index = 0u; loop_index < RTYPE_PYTHON_DRAW_VM_LOOP_COUNT; ++loop_index) {
        const rtype_python_draw_vm_loop *loop = &rtype_python_draw_vm_loops[loop_index];
        item_count = loop->kind == RTYPE_PYTHON_DRAW_VM_LOOP_OBJECTS ?
            input->object_count : input->transient_count;
        for (item_index = 0u; item_index < item_count; ++item_index) {
            if (loop->kind == RTYPE_PYTHON_DRAW_VM_LOOP_OBJECTS) {
                if (input->load_object != NULL) {
                    if (input->load_object(input->object_context,
                            item_index, &loaded_object) == 0u) {
                        *count_out = emitted;
                        return RTYPE_PYTHON_DRAW_VM_OBJECT_LOADER;
                    }
                    context.object = &loaded_object;
                } else {
                    context.object = &input->objects[item_index];
                }
                context.transient = NULL;
            } else {
                context.object = NULL;
                context.transient = &input->transients[item_index];
            }
            for (action_offset = 0u;
                    action_offset < loop->action_count; ++action_offset) {
                const rtype_python_draw_vm_action *action = &rtype_python_draw_vm_actions[
                    loop->first_action + action_offset];
                if (rtype_python_draw_vm_conditions(&context,
                        action->condition_pack) != 0u) {
                    const int32_t descriptor = rtype_python_draw_vm_eval(
                        &context, action->descriptor);
                    const int32_t palette = rtype_python_draw_vm_eval(
                        &context, action->palette);
                    const int32_t anchor_x = rtype_python_draw_vm_eval(
                        &context, action->anchor_x);
                    const int32_t anchor_y = rtype_python_draw_vm_eval(
                        &context, action->anchor_y);
                    if (emitting == 0u) {
                        if (descriptor < 0L || descriptor > 65535L ||
                                palette < 0L || palette > 65535L ||
                                anchor_x < -32768L || anchor_x > 32767L ||
                                anchor_y < -32768L || anchor_y > 32767L) {
                            return RTYPE_PYTHON_DRAW_VM_RANGE;
                        }
                        ++needed;
                        if (needed > 65535UL) {
                            return RTYPE_PYTHON_DRAW_VM_CAPACITY;
                        }
                    } else {
                        rtype_python_draw_vm_record record;
                        const uint16_t resource_type = (uint16_t)
                            rtype_python_draw_vm_eval(&context, action->resource_type);
                        record.bank_key = input->resolve_bank_key(
                            input->bank_context, (uint16_t)palette,
                            resource_type);
                        record.descriptor = (uint16_t)descriptor;
                        record.anchor_x = (int16_t)anchor_x;
                        record.anchor_y = (int16_t)anchor_y;
                        if (emit_record(emit_context, &record) == 0u) {
                            *count_out = emitted;
                            return RTYPE_PYTHON_DRAW_VM_EMITTER;
                        }
                        ++emitted;
                    }
                }
            }
        }
    }
    *count_out = emitting != 0u ? emitted : (uint16_t)needed;
    return RTYPE_PYTHON_DRAW_VM_OK;
}

typedef struct rtype_python_draw_vm_buffer_sink {
    rtype_python_draw_vm_record *next;
} rtype_python_draw_vm_buffer_sink;

static uint8_t rtype_python_draw_vm_emit_to_buffer(
        void *context, const rtype_python_draw_vm_record *record)
{
    rtype_python_draw_vm_buffer_sink *sink = (rtype_python_draw_vm_buffer_sink *)context;
    *sink->next = *record;
    ++sink->next;
    return 1u;
}

rtype_python_draw_vm_status rtype_python_draw_vm_produce(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record *output, uint16_t capacity,
        uint16_t *output_count)
{
    rtype_python_draw_vm_buffer_sink sink;
    rtype_python_draw_vm_status status;
    uint16_t needed, emitted;
    if (output_count == NULL || !rtype_python_draw_vm_input_valid(input)) {
        return RTYPE_PYTHON_DRAW_VM_INVALID_INPUT;
    }
    status = rtype_python_draw_vm_walk(input, 0u, NULL, NULL, &needed);
    if (status != RTYPE_PYTHON_DRAW_VM_OK) return status;
    if (needed > capacity) return RTYPE_PYTHON_DRAW_VM_CAPACITY;
    if (needed != 0u && output == NULL) return RTYPE_PYTHON_DRAW_VM_INVALID_INPUT;
    sink.next = output;
    status = rtype_python_draw_vm_walk(input, 1u, rtype_python_draw_vm_emit_to_buffer,
        &sink, &emitted);
    if (status != RTYPE_PYTHON_DRAW_VM_OK) return status;
    if (emitted != needed) return RTYPE_PYTHON_DRAW_VM_EMITTER;
    *output_count = emitted;
    return RTYPE_PYTHON_DRAW_VM_OK;
}

rtype_python_draw_vm_status rtype_python_draw_vm_stream(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record_emitter emit_record, void *emit_context,
        uint16_t *output_count)
{
    rtype_python_draw_vm_status status;
    uint16_t needed, emitted = 0u;
    if (output_count == NULL || !rtype_python_draw_vm_input_valid(input)) {
        return RTYPE_PYTHON_DRAW_VM_INVALID_INPUT;
    }
    status = rtype_python_draw_vm_walk(input, 0u, NULL, NULL, &needed);
    if (status != RTYPE_PYTHON_DRAW_VM_OK) return status;
    if (needed != 0u && emit_record == NULL) return RTYPE_PYTHON_DRAW_VM_INVALID_INPUT;
    if (needed != 0u) {
        status = rtype_python_draw_vm_walk(input, 1u, emit_record, emit_context,
            &emitted);
        if (status == RTYPE_PYTHON_DRAW_VM_EMITTER ||
                status == RTYPE_PYTHON_DRAW_VM_OBJECT_LOADER) {
            *output_count = emitted;
            return status;
        }
        if (status != RTYPE_PYTHON_DRAW_VM_OK) return status;
        if (emitted != needed) return RTYPE_PYTHON_DRAW_VM_EMITTER;
    }
    *output_count = emitted;
    return RTYPE_PYTHON_DRAW_VM_OK;
}
