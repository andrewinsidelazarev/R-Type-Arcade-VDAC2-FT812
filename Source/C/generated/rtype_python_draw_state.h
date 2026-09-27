/* Generated from active Python AST/DrawPlanIR. Do not edit. */
#ifndef RTYPE_PYTHON_DRAW_STATE_H
#define RTYPE_PYTHON_DRAW_STATE_H

#include <stdint.h>
#include "rtype_python_draw_vm.h"
#include "rtype_python_render_order.h"

#ifdef __cplusplus
extern "C" {
#endif

#define RTYPE_PYTHON_DRAW_STATE_SLOT_COUNT 96u
#define RTYPE_PYTHON_DRAW_STATE_RESERVED_SENTINELS 2u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_COUNT 73u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_NONE 0xFFu
#define RTYPE_PYTHON_DRAW_STATE_FIELD_COUNT 13u
#define RTYPE_PYTHON_DRAW_STATE_MUTATION_SITE_COUNT 368u
#define RTYPE_PYTHON_DRAW_STATE_VALUE_BYTES 24u
#define RTYPE_PYTHON_DRAW_STATE_SLOT_STATE_BYTES 26u
#define RTYPE_PYTHON_DRAW_STATE_STATE_BYTES 2496u

#define RTYPE_PYTHON_DRAW_STATE_CLASS_ANIMATED86A6 0u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ATTACHEDAC4C 1u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BACKGROUNDPARTICLEE5CD 2u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBCONTROLLER 3u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBCORE 4u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBCORECHILD 5u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBMISSILE 6u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBMISSILESPAWNER 7u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBRANDOMCHILD 8u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBRANDOMSPAWNER 9u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_BOSSB7FBSEGMENT 10u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_CHILD8D85 11u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_CLEANUPTIMERF477 12u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DEBRISAEFB 13u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSARENAANCHOR 14u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSBACK 15u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSBODY 16u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSDEBRISE700 17u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSORB 18u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSORBTRAIL 19u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSROOT 20u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_DOBKERATOPSTENTACLE 21u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY 22u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY5CEA 23u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY5EED 24u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY6F89 25u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY7182 26u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY7294 27u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY7D68 28u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY8469 29u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY8561 30u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMY8F5E 31u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_ENEMYPROJECTILE 32u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_EXPLOSIONE7BE 33u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_EXPLOSIONEFFECT 34u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FINALPROJECTILE9660 35u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FINALSPAWNER9660 36u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FIXEDLARGE6E9B 37u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FORMATION78F8CHILD 38u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FORMATION78F8PARENT 39u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FORMATIONCHILD 40u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_FORMATIONPARENT 41u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_GROUNDWALKER 42u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_HANDLER5CEASHOT 43u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_HANDLER60BA 44u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_HANDLER60BACHILD 45u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_HANDLER60BAPROJECTILE 46u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_INVULNERABILITYTIMERF44E 47u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_LARGETERRAIN74B4 48u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_LARGETERRAINCHILD780E 49u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_MULTIPART915BCHILD 50u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_MULTIPART915BPARENT 51u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_MULTIPARTA71DBODY 52u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_MULTIPARTA71DCONTROLLER 53u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_PALETTECYCLEFBED 54u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_PLAYERSHOTVISUAL4EAF 55u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_PLAYERTARGETING80E3 56u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_PROJECTILE7435 57u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_RADIAL95F1 58u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_REDFLYER 59u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_SPAWNER875D 60u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_SPAWNER875DCHILD 61u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_STAGEOBJECT8C12 62u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_STAGETRANSITIONF1BF 63u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TARGETING80E3ATTACKFLASH 64u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TARGETING80E3PROJECTILE 65u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TERRAINAWARE897E 66u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TERRAINBOUND55E9 67u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TERRAINENEMY696E 68u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TERRAINMODIFIERCHILD6C37 69u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TERRAINMODIFIERPARENT6ACB 70u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TERRAINMODIFIERPROJECTILE6E27 71u
#define RTYPE_PYTHON_DRAW_STATE_CLASS_TIMEDCONTROLF3C1 72u

typedef enum {
    RTYPE_PYTHON_DRAW_STATE_FIELD_ACTIVE_PALETTE = 0,
    RTYPE_PYTHON_DRAW_STATE_FIELD_BODY_KIND = 1,
    RTYPE_PYTHON_DRAW_STATE_FIELD_DESCRIPTOR = 2,
    RTYPE_PYTHON_DRAW_STATE_FIELD_EFFECT = 3,
    RTYPE_PYTHON_DRAW_STATE_FIELD_OVERLAY_DESCRIPTOR = 4,
    RTYPE_PYTHON_DRAW_STATE_FIELD_OVERLAY_X = 5,
    RTYPE_PYTHON_DRAW_STATE_FIELD_OVERLAY_Y = 6,
    RTYPE_PYTHON_DRAW_STATE_FIELD_PALETTE = 7,
    RTYPE_PYTHON_DRAW_STATE_FIELD_RENDER_READY = 8,
    RTYPE_PYTHON_DRAW_STATE_FIELD_STATE = 9,
    RTYPE_PYTHON_DRAW_STATE_FIELD_VISIBLE = 10,
    RTYPE_PYTHON_DRAW_STATE_FIELD_X = 11,
    RTYPE_PYTHON_DRAW_STATE_FIELD_Y = 12,
} rtype_python_draw_state_field_id;

typedef enum {
    RTYPE_PYTHON_DRAW_STATE_OK = 0,
    RTYPE_PYTHON_DRAW_STATE_NULL = 1,
    RTYPE_PYTHON_DRAW_STATE_INVALID_SLOT = 2,
    RTYPE_PYTHON_DRAW_STATE_UNBOUND_SLOT = 3,
    RTYPE_PYTHON_DRAW_STATE_INVALID_CLASS = 4,
    RTYPE_PYTHON_DRAW_STATE_INVALID_FIELD = 5,
    RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE = 6,
    RTYPE_PYTHON_DRAW_STATE_INVALID_SITE = 7,
    RTYPE_PYTHON_DRAW_STATE_INVALID_PATCH_MASK = 8,
    RTYPE_PYTHON_DRAW_STATE_ALREADY_BOUND = 9
} rtype_python_draw_state_status;

typedef struct rtype_python_draw_state_values {
    uint16_t field_active_palette;
    uint16_t field_body_kind;
    uint16_t field_descriptor;
    uint16_t field_effect;
    uint16_t field_overlay_descriptor;
    int16_t field_overlay_x;
    int16_t field_overlay_y;
    uint16_t field_palette;
    uint16_t field_state;
    int16_t field_x;
    int16_t field_y;
    uint8_t field_render_ready;
    uint8_t field_visible;
} rtype_python_draw_state_values;

typedef struct rtype_python_draw_state_slot_state {
    rtype_python_draw_state_values values;
    uint8_t concrete_class;
    uint8_t reserved_zero;
} rtype_python_draw_state_slot_state;

typedef struct rtype_python_draw_state_state {
    rtype_python_draw_state_slot_state slots[RTYPE_PYTHON_DRAW_STATE_SLOT_COUNT];
} rtype_python_draw_state_state;

typedef struct rtype_python_draw_state_provider_context {
    const rtype_python_draw_state_state *state;
    const rtype_python_render_order_state *order;
} rtype_python_draw_state_provider_context;

void rtype_python_draw_state_reset(rtype_python_draw_state_state *state);
rtype_python_draw_state_status rtype_python_draw_state_clear(rtype_python_draw_state_state *state, uint8_t slot);
rtype_python_draw_state_status rtype_python_draw_state_bind(
    rtype_python_draw_state_state *state, uint8_t slot, uint8_t concrete_class,
    const rtype_python_draw_state_values *values);
rtype_python_draw_state_status rtype_python_draw_state_replace_same_slot(
    rtype_python_draw_state_state *state, uint8_t slot, uint8_t concrete_class,
    const rtype_python_draw_state_values *values);
rtype_python_draw_state_status rtype_python_draw_state_patch(
    rtype_python_draw_state_state *state, uint8_t slot, uint16_t field_mask,
    const rtype_python_draw_state_values *values);
rtype_python_draw_state_status rtype_python_draw_state_set_field(
    rtype_python_draw_state_state *state, uint8_t slot, uint8_t field_id,
    int32_t value);
rtype_python_draw_state_status rtype_python_draw_state_set_at_site(
    rtype_python_draw_state_state *state, uint8_t slot, uint16_t site_id,
    int32_t value);
uint32_t rtype_python_draw_state_mutation_site_hash32(uint16_t site_id);
uint8_t rtype_python_draw_state_class_of(
    const rtype_python_draw_state_state *state, uint8_t slot);

/* Compact Draw VM provider: object_index is Python render order. */
uint8_t rtype_python_draw_state_load_object(
    void *context, uint16_t object_index,
    rtype_python_draw_vm_object_view *object_out);

#ifdef __cplusplus
}
#endif

#endif /* RTYPE_PYTHON_DRAW_STATE_H */
