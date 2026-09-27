/* Generated from SpriteDrawPlanIR. Do not edit. */
/* source: Source/Python/rtype_port/enemies.py */
/* plan semantic SHA-256: 8deb7410b166f70abea16a78a5cb472952871c068dde1d17efde1de9356119c8 */
#include "rtype_python_draw_plan.h"
#include <stddef.h>

typedef char rtype_python_draw_plan_assert_record_size[
    (sizeof(rtype_python_draw_plan_record) == 8) ? 1 : -1];
typedef char rtype_python_draw_plan_assert_bank_key_offset[
    (offsetof(rtype_python_draw_plan_record, bank_key) == 0) ? 1 : -1];
typedef char rtype_python_draw_plan_assert_descriptor_offset[
    (offsetof(rtype_python_draw_plan_record, descriptor) == 2) ? 1 : -1];
typedef char rtype_python_draw_plan_assert_anchor_x_offset[
    (offsetof(rtype_python_draw_plan_record, anchor_x) == 4) ? 1 : -1];
typedef char rtype_python_draw_plan_assert_anchor_y_offset[
    (offsetof(rtype_python_draw_plan_record, anchor_y) == 6) ? 1 : -1];

static uint8_t rtype_python_draw_plan_object_is(
        const rtype_python_draw_plan_object_view *object, uint16_t class_tag)
{
    const uint8_t mask = (uint8_t)(1u << (class_tag & 7u));
    return (uint8_t)((object->class_bits[class_tag >> 3] & mask) != 0u);
}

static int32_t rtype_python_draw_plan_object_expr_0(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_1(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_2(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_3(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_4(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_5(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_6(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_7(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_8(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_9(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_10(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_11(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_12(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_13(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_14(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_15(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_16(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_17(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_18(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_19(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_20(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_21(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);
static int32_t rtype_python_draw_plan_object_expr_22(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input);

static int32_t rtype_python_draw_plan_object_expr_0(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((int32_t)object->field_render_ready));
}

static int32_t rtype_python_draw_plan_object_expr_1(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((((int32_t)object->field_descriptor)) + (6)));
}

static int32_t rtype_python_draw_plan_object_expr_2(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((((int32_t)object->field_body_kind) == RTYPE_PYTHON_DRAW_PLAN_STATE_BODY_KIND_MIDDLE));
}

static int32_t rtype_python_draw_plan_object_expr_3(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((((int32_t)object->field_body_kind) == RTYPE_PYTHON_DRAW_PLAN_STATE_BODY_KIND_UPPER));
}

static int32_t rtype_python_draw_plan_object_expr_4(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((((int32_t)object->field_palette)) == (255)));
}

static int32_t rtype_python_draw_plan_object_expr_5(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(((int32_t)object->field_render_ready))));
}

static int32_t rtype_python_draw_plan_object_expr_6(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(((int32_t)object->field_visible))));
}

static int32_t rtype_python_draw_plan_object_expr_7(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_0(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_8(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BACKGROUNDPARTICLEE5CD)));
}

static int32_t rtype_python_draw_plan_object_expr_9(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_FIXEDLARGE6E9B)));
}

static int32_t rtype_python_draw_plan_object_expr_10(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_GROUNDWALKER) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_PLAYERTARGETING80E3) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_LARGETERRAIN74B4) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER60BA) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY8561) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_TERRAINENEMY696E) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY6F89) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY7294) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY5EED) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_FORMATION78F8CHILD) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_MULTIPART915BCHILD) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ATTACHEDAC4C) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_MULTIPARTA71DBODY) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBCORE) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY7D68) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_CHILD8D85) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_DOBKERATOPSBODY)));
}

static int32_t rtype_python_draw_plan_object_expr_11(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_MULTIPARTA71DBODY)));
}

static int32_t rtype_python_draw_plan_object_expr_12(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_TARGETING80E3ATTACKFLASH)));
}

static int32_t rtype_python_draw_plan_object_expr_13(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((rtype_python_draw_plan_object_expr_8(object, input)) && (rtype_python_draw_plan_object_expr_5(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_14(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((rtype_python_draw_plan_object_expr_12(object, input)) && (rtype_python_draw_plan_object_expr_6(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_15(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_2(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_16(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_3(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_17(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_4(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_18(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_7(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_19(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((rtype_python_draw_plan_object_expr_10(object, input)) ? (((int32_t)object->field_active_palette)) : (((int32_t)object->field_palette))));
}

static int32_t rtype_python_draw_plan_object_expr_20(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_13(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_21(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)((!(rtype_python_draw_plan_object_expr_14(object, input))));
}

static int32_t rtype_python_draw_plan_object_expr_22(
    const rtype_python_draw_plan_object_view *object,
    const rtype_python_draw_plan_input *input)
{
    return (int32_t)(((int32_t)input->resolve_resource_type(input->resource_context, (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input)))));
}

static uint8_t rtype_python_draw_plan_input_valid(
        const rtype_python_draw_plan_input *input)
{
    return (uint8_t)(input != NULL &&
            input->resolve_resource_type != NULL &&
            input->resolve_bank_key != NULL &&
            (input->object_count == 0u || input->objects != NULL) &&
            (input->transient_count == 0u || input->transients != NULL));
}

static rtype_python_draw_plan_status rtype_python_draw_plan_preflight(
        const rtype_python_draw_plan_input *input, uint16_t *needed_out)
{
    uint32_t needed = 0;
    uint16_t item_index;

    /* Pass one: exact count and all fallible range checks, no writes. */
    for (item_index = 0; item_index < input->object_count; ++item_index) {
        const rtype_python_draw_plan_object_view *object =
            &input->objects[item_index];
        /* IR action 0, source sink 0, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input))) {
            const int32_t descriptor_value = ((int32_t)object->field_descriptor);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 1, source sink 1, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_PLAYERTARGETING80E3)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 2, source sink 2, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_TARGETING80E3PROJECTILE)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 3, source sink 3, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_EXPLOSIONEFFECT))) && ((((int32_t)object->field_effect) == RTYPE_PYTHON_DRAW_PLAN_STATE_EFFECT_E817))))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 4, source sink 4, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER5CEASHOT)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 5, source sink 5, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY8561)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 6, source sink 6, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY6F89)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 7, source sink 7, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY5EED)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 8, source sink 8, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER60BA)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 9, source sink 9, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_FORMATION78F8CHILD))) && ((((int32_t)object->field_state) == RTYPE_PYTHON_DRAW_PLAN_STATE_STATE_FIRST))))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 10, source sink 10, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY7D68) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_CHILD8D85)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 11, source sink 11, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const int32_t descriptor_value = 23048;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 12, source sink 11, expansion 1. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const int32_t descriptor_value = 23054;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 13, source sink 11, expansion 2. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const int32_t descriptor_value = 23060;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 14, source sink 11, expansion 3. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const int32_t descriptor_value = 23066;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 15, source sink 11, expansion 4. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const int32_t descriptor_value = 23072;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 16, source sink 11, expansion 5. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const int32_t descriptor_value = 23116;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 17, source sink 11, expansion 6. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const int32_t descriptor_value = 23122;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 18, source sink 11, expansion 7. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const int32_t descriptor_value = 23128;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 19, source sink 11, expansion 8. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const int32_t descriptor_value = 23134;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 20, source sink 11, expansion 9. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const int32_t descriptor_value = 23140;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 21, source sink 11, expansion 10. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_15(object, input))) {
            const int32_t descriptor_value = 23176;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 22, source sink 11, expansion 11. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_15(object, input))) {
            const int32_t descriptor_value = 23182;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 23, source sink 11, expansion 12. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_15(object, input))) {
            const int32_t descriptor_value = 23188;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 24, source sink 12, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBSEGMENT) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBMISSILE) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBCORE)))) {
            const int32_t descriptor_value = rtype_python_draw_plan_object_expr_1(object, input);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 25, source sink 13, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12360;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 26, source sink 13, expansion 1. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12366;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 27, source sink 13, expansion 2. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12372;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 28, source sink 13, expansion 3. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12378;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 29, source sink 13, expansion 4. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12384;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 30, source sink 13, expansion 5. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12390;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 31, source sink 13, expansion 6. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const int32_t descriptor_value = 12396;
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_x);
            const int32_t anchor_y_value = ((int32_t)object->field_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
        /* IR action 32, source sink 14, expansion 0. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER60BACHILD)))) {
            const int32_t descriptor_value = ((int32_t)object->field_overlay_descriptor);
            const int32_t palette_value = rtype_python_draw_plan_object_expr_19(object, input);
            const int32_t anchor_x_value = ((int32_t)object->field_overlay_x);
            const int32_t anchor_y_value = ((int32_t)object->field_overlay_y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
    }
    for (item_index = 0; item_index < input->transient_count; ++item_index) {
        const rtype_python_draw_plan_transient_view *transient =
            &input->transients[item_index];
        /* IR action 33, source sink 15, expansion 0. */
        if (1) {
            const int32_t descriptor_value = ((int32_t)transient->descriptor);
            const int32_t palette_value = ((int32_t)transient->palette);
            const int32_t anchor_x_value = ((int32_t)transient->x);
            const int32_t anchor_y_value = ((int32_t)transient->y);
            if (descriptor_value < 0 || descriptor_value > 65535L ||
                    palette_value < 0 || palette_value > 65535L ||
                    anchor_x_value < -32768L || anchor_x_value > 32767L ||
                    anchor_y_value < -32768L || anchor_y_value > 32767L) {
                return RTYPE_PYTHON_DRAW_PLAN_RANGE;
            }
            ++needed;
            if (needed > 65535UL) {
                return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
            }
        }
    }

    *needed_out = (uint16_t)needed;
    return RTYPE_PYTHON_DRAW_PLAN_OK;
}

static rtype_python_draw_plan_status rtype_python_draw_plan_emit_ordered(
        const rtype_python_draw_plan_input *input,
        rtype_python_draw_plan_record_emitter emit_record, void *emit_context,
        uint16_t *emitted_count)
{
    uint16_t item_index;
    uint16_t write_index = 0;

    /* Pass two: emit the already-proved records in Python loop order. */
    for (item_index = 0; item_index < input->object_count; ++item_index) {
        const rtype_python_draw_plan_object_view *object =
            &input->objects[item_index];
        /* IR action 0, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(((int32_t)object->field_descriptor));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 1, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_PLAYERTARGETING80E3)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 2, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_TARGETING80E3PROJECTILE)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 3, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_EXPLOSIONEFFECT))) && ((((int32_t)object->field_effect) == RTYPE_PYTHON_DRAW_PLAN_STATE_EFFECT_E817))))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 4, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER5CEASHOT)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 5, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY8561)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 6, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY6F89)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 7, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY5EED)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 8, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER60BA)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 9, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_FORMATION78F8CHILD))) && ((((int32_t)object->field_state) == RTYPE_PYTHON_DRAW_PLAN_STATE_STATE_FIRST))))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 10, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_ENEMY7D68) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_CHILD8D85)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 11, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23048);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 12, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23054);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 13, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23060);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 14, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23066);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 15, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_3(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23072);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 16, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23116);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 17, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23122);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 18, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23128);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 19, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23134);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 20, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_2(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23140);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 21, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_15(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23176);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 22, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_15(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23182);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 23, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_11(object, input)) && (rtype_python_draw_plan_object_expr_16(object, input)) && (rtype_python_draw_plan_object_expr_15(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(23188);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 24, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBSEGMENT) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBMISSILE) || rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_BOSSB7FBCORE)))) {
            const uint16_t descriptor_value = (uint16_t)(rtype_python_draw_plan_object_expr_1(object, input));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 25, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12360);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 26, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12366);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 27, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12372);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 28, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12378);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 29, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12384);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 30, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12390);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 31, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && (rtype_python_draw_plan_object_expr_9(object, input))) {
            const uint16_t descriptor_value = (uint16_t)(12396);
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
        /* IR action 32, strict Python order. */
        if ((rtype_python_draw_plan_object_expr_17(object, input)) && (rtype_python_draw_plan_object_expr_18(object, input)) && (rtype_python_draw_plan_object_expr_20(object, input)) && (rtype_python_draw_plan_object_expr_21(object, input)) && ((rtype_python_draw_plan_object_is(object, RTYPE_PYTHON_DRAW_PLAN_CLASS_HANDLER60BACHILD)))) {
            const uint16_t descriptor_value = (uint16_t)(((int32_t)object->field_overlay_descriptor));
            const uint16_t palette_value = (uint16_t)(rtype_python_draw_plan_object_expr_19(object, input));
            const uint16_t resource_type_value = (uint16_t)(rtype_python_draw_plan_object_expr_22(object, input));
            const int16_t anchor_x_value = (int16_t)(((int32_t)object->field_overlay_x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)object->field_overlay_y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
    }
    for (item_index = 0; item_index < input->transient_count; ++item_index) {
        const rtype_python_draw_plan_transient_view *transient =
            &input->transients[item_index];
        /* IR action 33, strict Python order. */
        if (1) {
            const uint16_t descriptor_value = (uint16_t)(((int32_t)transient->descriptor));
            const uint16_t palette_value = (uint16_t)(((int32_t)transient->palette));
            const uint16_t resource_type_value = (uint16_t)(((int32_t)transient->resource_type));
            const int16_t anchor_x_value = (int16_t)(((int32_t)transient->x));
            const int16_t anchor_y_value = (int16_t)(((int32_t)transient->y));
            rtype_python_draw_plan_record record_value;
            record_value.bank_key = input->resolve_bank_key(
                input->bank_context, palette_value, resource_type_value);
            record_value.descriptor = descriptor_value;
            record_value.anchor_x = anchor_x_value;
            record_value.anchor_y = anchor_y_value;
            if (emit_record(emit_context, &record_value) == 0u) {
                *emitted_count = write_index;
                return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
            }
            ++write_index;
        }
    }

    *emitted_count = write_index;
    return RTYPE_PYTHON_DRAW_PLAN_OK;
}

typedef struct rtype_python_draw_plan_buffer_sink {
    rtype_python_draw_plan_record *next;
} rtype_python_draw_plan_buffer_sink;

static uint8_t rtype_python_draw_plan_emit_to_buffer(
        void *context, const rtype_python_draw_plan_record *record)
{
    rtype_python_draw_plan_buffer_sink *sink = (rtype_python_draw_plan_buffer_sink *)context;
    *sink->next = *record;
    ++sink->next;
    return 1u;
}

rtype_python_draw_plan_status rtype_python_draw_plan_produce(
        const rtype_python_draw_plan_input *input,
        rtype_python_draw_plan_record *output, uint16_t capacity,
        uint16_t *output_count)
{
    rtype_python_draw_plan_status status;
    rtype_python_draw_plan_buffer_sink sink;
    uint16_t needed;
    uint16_t emitted;

    if (output_count == NULL || !rtype_python_draw_plan_input_valid(input)) {
        return RTYPE_PYTHON_DRAW_PLAN_INVALID_INPUT;
    }
    status = rtype_python_draw_plan_preflight(input, &needed);
    if (status != RTYPE_PYTHON_DRAW_PLAN_OK) {
        return status;
    }
    if (needed > capacity) {
        return RTYPE_PYTHON_DRAW_PLAN_CAPACITY;
    }
    if (needed != 0u && output == NULL) {
        return RTYPE_PYTHON_DRAW_PLAN_INVALID_INPUT;
    }
    sink.next = output;
    status = rtype_python_draw_plan_emit_ordered(
        input, rtype_python_draw_plan_emit_to_buffer, &sink, &emitted);
    if (status != RTYPE_PYTHON_DRAW_PLAN_OK) {
        return status;
    }
    if (emitted != needed) {
        return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
    }
    *output_count = emitted;
    return RTYPE_PYTHON_DRAW_PLAN_OK;
}

rtype_python_draw_plan_status rtype_python_draw_plan_stream(
        const rtype_python_draw_plan_input *input,
        rtype_python_draw_plan_record_emitter emit_record, void *emit_context,
        uint16_t *output_count)
{
    rtype_python_draw_plan_status status;
    uint16_t needed;
    uint16_t emitted = 0;

    if (output_count == NULL || !rtype_python_draw_plan_input_valid(input)) {
        return RTYPE_PYTHON_DRAW_PLAN_INVALID_INPUT;
    }
    status = rtype_python_draw_plan_preflight(input, &needed);
    if (status != RTYPE_PYTHON_DRAW_PLAN_OK) {
        return status;
    }
    if (needed != 0u && emit_record == NULL) {
        return RTYPE_PYTHON_DRAW_PLAN_INVALID_INPUT;
    }
    if (needed != 0u) {
        status = rtype_python_draw_plan_emit_ordered(
            input, emit_record, emit_context, &emitted);
        if (status == RTYPE_PYTHON_DRAW_PLAN_EMITTER) {
            *output_count = emitted;
            return status;
        }
        if (status != RTYPE_PYTHON_DRAW_PLAN_OK || emitted != needed) {
            return status;
        }
    }
    *output_count = emitted;
    return RTYPE_PYTHON_DRAW_PLAN_OK;
}
