/* Generated from SpriteDrawPlanIR. Do not edit. */
/* Compact target-neutral draw VM ABI. */
/* plan semantic SHA-256: 8deb7410b166f70abea16a78a5cb472952871c068dde1d17efde1de9356119c8 */
#ifndef RTYPE_PYTHON_DRAW_VM_H
#define RTYPE_PYTHON_DRAW_VM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RTYPE_PYTHON_DRAW_VM_CLASS_TAG_COUNT 26u
#define RTYPE_PYTHON_DRAW_VM_CLASS_BIT_BYTES 4u
#define RTYPE_PYTHON_DRAW_VM_MAX_EVAL_DEPTH 4u
#define RTYPE_PYTHON_DRAW_VM_OBJECT_VIEW_BYTES 28u
#define RTYPE_PYTHON_DRAW_VM_CLASS_ATTACHEDAC4C 0u
#define RTYPE_PYTHON_DRAW_VM_CLASS_BACKGROUNDPARTICLEE5CD 1u
#define RTYPE_PYTHON_DRAW_VM_CLASS_BOSSB7FBCORE 2u
#define RTYPE_PYTHON_DRAW_VM_CLASS_BOSSB7FBMISSILE 3u
#define RTYPE_PYTHON_DRAW_VM_CLASS_BOSSB7FBSEGMENT 4u
#define RTYPE_PYTHON_DRAW_VM_CLASS_CHILD8D85 5u
#define RTYPE_PYTHON_DRAW_VM_CLASS_DOBKERATOPSBODY 6u
#define RTYPE_PYTHON_DRAW_VM_CLASS_ENEMY5EED 7u
#define RTYPE_PYTHON_DRAW_VM_CLASS_ENEMY6F89 8u
#define RTYPE_PYTHON_DRAW_VM_CLASS_ENEMY7294 9u
#define RTYPE_PYTHON_DRAW_VM_CLASS_ENEMY7D68 10u
#define RTYPE_PYTHON_DRAW_VM_CLASS_ENEMY8561 11u
#define RTYPE_PYTHON_DRAW_VM_CLASS_EXPLOSIONEFFECT 12u
#define RTYPE_PYTHON_DRAW_VM_CLASS_FIXEDLARGE6E9B 13u
#define RTYPE_PYTHON_DRAW_VM_CLASS_FORMATION78F8CHILD 14u
#define RTYPE_PYTHON_DRAW_VM_CLASS_GROUNDWALKER 15u
#define RTYPE_PYTHON_DRAW_VM_CLASS_HANDLER5CEASHOT 16u
#define RTYPE_PYTHON_DRAW_VM_CLASS_HANDLER60BA 17u
#define RTYPE_PYTHON_DRAW_VM_CLASS_HANDLER60BACHILD 18u
#define RTYPE_PYTHON_DRAW_VM_CLASS_LARGETERRAIN74B4 19u
#define RTYPE_PYTHON_DRAW_VM_CLASS_MULTIPART915BCHILD 20u
#define RTYPE_PYTHON_DRAW_VM_CLASS_MULTIPARTA71DBODY 21u
#define RTYPE_PYTHON_DRAW_VM_CLASS_PLAYERTARGETING80E3 22u
#define RTYPE_PYTHON_DRAW_VM_CLASS_TARGETING80E3ATTACKFLASH 23u
#define RTYPE_PYTHON_DRAW_VM_CLASS_TARGETING80E3PROJECTILE 24u
#define RTYPE_PYTHON_DRAW_VM_CLASS_TERRAINENEMY696E 25u

#define RTYPE_PYTHON_DRAW_VM_STATE_BODY_KIND_OTHER 0u
#define RTYPE_PYTHON_DRAW_VM_STATE_BODY_KIND_MIDDLE 1u
#define RTYPE_PYTHON_DRAW_VM_STATE_BODY_KIND_UPPER 2u
#define RTYPE_PYTHON_DRAW_VM_STATE_EFFECT_OTHER 0u
#define RTYPE_PYTHON_DRAW_VM_STATE_EFFECT_E817 1u
#define RTYPE_PYTHON_DRAW_VM_STATE_STATE_OTHER 0u
#define RTYPE_PYTHON_DRAW_VM_STATE_STATE_FIRST 1u

typedef struct rtype_python_draw_vm_object_view {
    uint8_t class_bits[RTYPE_PYTHON_DRAW_VM_CLASS_BIT_BYTES];
    uint16_t field_active_palette;
    uint16_t field_body_kind;
    uint16_t field_descriptor;
    uint16_t field_effect;
    uint16_t field_overlay_descriptor;
    int16_t field_overlay_x;
    int16_t field_overlay_y;
    uint16_t field_palette;
    uint8_t field_render_ready;
    uint16_t field_state;
    uint8_t field_visible;
    int16_t field_x;
    int16_t field_y;
} rtype_python_draw_vm_object_view;

typedef struct rtype_python_draw_vm_transient_view {
    uint16_t descriptor;
    uint16_t palette;
    uint16_t resource_type;
    int16_t x;
    int16_t y;
} rtype_python_draw_vm_transient_view;

typedef struct rtype_python_draw_vm_record {
    uint16_t bank_key;
    uint16_t descriptor;
    int16_t anchor_x;
    int16_t anchor_y;
} rtype_python_draw_vm_record;

typedef uint16_t (*rtype_python_draw_vm_resource_type_resolver)(
    void *context, uint16_t palette);
typedef uint16_t (*rtype_python_draw_vm_bank_key_resolver)(
    void *context, uint16_t palette, uint16_t resource_type);
typedef uint8_t (*rtype_python_draw_vm_record_emitter)(
    void *context, const rtype_python_draw_vm_record *record);
typedef uint8_t (*rtype_python_draw_vm_object_loader)(
    void *context, uint16_t object_index,
    rtype_python_draw_vm_object_view *object_out);

typedef struct rtype_python_draw_vm_input {
    const rtype_python_draw_vm_object_view *objects;
    uint16_t object_count;
    rtype_python_draw_vm_object_loader load_object;
    void *object_context;
    const rtype_python_draw_vm_transient_view *transients;
    uint16_t transient_count;
    rtype_python_draw_vm_resource_type_resolver resolve_resource_type;
    void *resource_context;
    rtype_python_draw_vm_bank_key_resolver resolve_bank_key;
    void *bank_context;
} rtype_python_draw_vm_input;

typedef enum rtype_python_draw_vm_status {
    RTYPE_PYTHON_DRAW_VM_OK = 0,
    RTYPE_PYTHON_DRAW_VM_INVALID_INPUT = 1,
    RTYPE_PYTHON_DRAW_VM_CAPACITY = 2,
    RTYPE_PYTHON_DRAW_VM_RANGE = 3,
    RTYPE_PYTHON_DRAW_VM_EMITTER = 4,
    RTYPE_PYTHON_DRAW_VM_OBJECT_LOADER = 5
} rtype_python_draw_vm_status;

/* Preflight invokes only load_object; no resolver, emitter or write. */
rtype_python_draw_vm_status rtype_python_draw_vm_produce(
    const rtype_python_draw_vm_input *input,
    rtype_python_draw_vm_record *output, uint16_t capacity,
    uint16_t *output_count);

/* Strict Python record order, with no frame-sized output required. */
rtype_python_draw_vm_status rtype_python_draw_vm_stream(
    const rtype_python_draw_vm_input *input,
    rtype_python_draw_vm_record_emitter emit_record, void *emit_context,
    uint16_t *output_count);

#ifdef __cplusplus
}
#endif

#endif /* RTYPE_PYTHON_DRAW_VM_H */
