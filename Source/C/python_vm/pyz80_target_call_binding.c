#include "pyz80_target_call_binding.h"

static uint8_t overlaps(const void *left, uint32_t left_bytes,
    const void *right, uint32_t right_bytes)
{
    uintptr_t a = (uintptr_t)left, b = (uintptr_t)right;
    if (left == 0 || right == 0 || !left_bytes || !right_bytes) return 0u;
    /* Address differences avoid overflowing an end-address addition. */
    return a <= b ? b - a < left_bytes : a - b < right_bytes;
}

static uint8_t prepare_kind(void *raw, PyZ80VM *vm, uint16_t adapter,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function, uint8_t generator)
{
    PyZ80TargetScopes *scopes = raw;
    PyZ80TargetContext *objects = scopes->objects;
    PyZ80TargetNode *node;
    PyZ80TargetCallSignature signature_record;
    const PyZ80TargetCallSignature *signature=&signature_record;
    PyZ80TargetAdapterSpec adapter_record;
    const PyZ80VMValue *value;
    PyZ80VMValue prototype, receiver;
    uint16_t link, start, total, position, parameter, index, key, defaults;
    uint16_t candidate;
    uint8_t positional = 0u, keyword_seen = 0u, implicit, explicit_positional=adapter==65535u;
    if (vm != scopes->vm || args == 0 || count == 0 || !*count || function == 0) return 2u;
    if (args[0].kind != PYZ80_VM_VALUE_OPAQUE) return 0u;
    link = (uint16_t)args[0].payload;
    if (!link || link > objects->node_used || objects->nodes == 0) return 0u;
    if (objects->node_used > objects->node_capacity) return 2u;
    node = &objects->nodes[link - 1u];
    if (node->generation != (uint16_t)(args[0].payload >> 16)) return 2u;
    if (node->kind == PYZ80_TARGET_NODE_NATIVE_METHOD) return 0u;
    if (node->kind == PYZ80_TARGET_NODE_CLASS && objects->class_provider) return 0u;
    if (!PyZ80Target_UnwrapCallable(objects, &args[0], &prototype, &receiver)) return 2u;
    node = PyZ80Target_Node(objects, &prototype);
    if (node->has_current > 1u) return 2u;
    if (node->has_current != generator) return 0u;
    implicit = receiver.kind != PYZ80_VM_VALUE_NONE;
    positional = implicit; /* Bound method supplies exactly its retained receiver. */
    start=0u;
    if ((!explicit_positional && (!PyZ80Target_ReadAdapter(objects,adapter,&adapter_record) || adapter_record.argument_count!=*count ||
        !PyZ80Target_ReadWord(objects,PYZ80_TABLE_CALL_OFFSETS,adapter,&start))) ||
        !PyZ80Target_ReadSignature(objects,node->class_symbol,&signature_record)) return 2u;
    total = *count - 1u; /* SUB.U16: callable is not an argument. */
    if (!signature->supported || signature->count > scopes->binding_capacity ||
        signature->count > vm->limits.max_arguments ||
        signature->positional_only_count > signature->positional_count ||
        signature->positional_count > signature->count ||
        implicit > signature->positional_count ||
        signature->start > objects->parameter_name_count ||
        signature->count > objects->parameter_name_count - signature->start ||
        (signature->count && (!PyZ80Target_HasTable(objects,PYZ80_TABLE_PARAMETERS) || scopes->binding_scratch == 0)) ||
        (!explicit_positional && (start == 65535u || start > objects->call_layout_key_count ||
        total > objects->call_layout_key_count - start ||
        (total && !PyZ80Target_HasTable(objects,PYZ80_TABLE_CALL_KEYS))))) return 2u;
    if (node->item_count > 254u || node->cursor > 254u || node->item_count + node->cursor > 254u ||
        objects->item_used > objects->item_capacity || node->item_start > objects->item_used ||
        (node->item_count + node->cursor) * 2u > objects->item_used - node->item_start ||
        ((node->item_count || node->cursor) && objects->items == 0) ||
        (node->reserved != 2u && (node->item_count || node->cursor))) return 2u;
    defaults = node->item_start + node->item_count * 2u; /* SHL/ADD.U16 default-pair slice */
    /* Check every supplied argument, including unknown and duplicate keywords. */
    for (index = 0u; index < total; ++index) {
        key=65535u;
        if(!explicit_positional && !PyZ80Target_ReadWord(objects,PYZ80_TABLE_CALL_KEYS,start+index,&key)) return 2u;
        if (key == 65535u) {
            if (keyword_seen || positional >= signature->positional_count) return 2u;
            ++positional;
        } else {
            keyword_seen = 1u;
            for (parameter = signature->positional_only_count; parameter < signature->count; ++parameter) {
                if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_PARAMETERS,signature->start+parameter,&candidate)) return 2u;
                if(candidate==key) break;
            }
            if (parameter == signature->count || parameter < positional) return 2u;
            for (position = 0u; position < index; ++position) {
                if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_CALL_KEYS,start+position,&candidate) || candidate==key) return 2u;
            }
        }
    }
    /* Build in disjoint scratch; caller arguments remain intact on any error. */
    for (parameter = 0u; parameter < signature->count; ++parameter) {
        if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_PARAMETERS,signature->start+parameter,&key)) return 2u;
        value = 0;
        if (parameter < positional)
            value = implicit && !parameter ? &receiver : &args[parameter + 1u - implicit];
        else if (parameter >= signature->positional_only_count) {
            for (index = positional - implicit; index < total; ++index) {
                if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_CALL_KEYS,start+index,&candidate)) return 2u;
                if (candidate == key) {
                    value = &args[index + 1u];
                    break;
                }
            }
        }
        if (value == 0) {
            for (index = 0u; index < node->cursor; ++index) {
                position = defaults + index * 2u; /* SHL/ADD.U16 pair offset */
                if (objects->items[position].kind != PYZ80_VM_VALUE_SYMBOL) return 2u;
                if (objects->items[position].symbol == key) {
                    value = &objects->items[position + 1u];
                    if (value->kind == PYZ80_VM_VALUE_CELL) return 2u;
                    break;
                }
            }
        }
        if (value == 0) return 2u; /* Missing required argument; never guess None. */
        scopes->binding_scratch[parameter] = *value;
    }
    for (parameter = 0u; parameter < signature->count; ++parameter)
        args[parameter] = scopes->binding_scratch[parameter];
    *count = signature->count;
    *function = node->class_symbol;
    return 1u;
}

static uint8_t prepare(void *raw, PyZ80VM *vm, uint16_t adapter,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function)
{
    return prepare_kind(raw,vm,adapter,args,count,function,0u);
}

uint8_t PyZ80Target_PrepareGeneratorCall(PyZ80TargetScopes *scopes, uint16_t adapter,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function)
{
    return prepare_kind(scopes,scopes->vm,adapter,args,count,function,1u);
}

uint8_t PyZ80Target_PreparePositionalCall(PyZ80TargetScopes *scopes,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function)
{
    if(!scopes || !scopes->vm || !scopes->objects) return 2u;
    return prepare_kind(scopes,scopes->vm,65535u,args,count,function,0u);
}

uint8_t PyZ80Target_AttachCallBinding(PyZ80TargetScopes *scopes,
    PyZ80VMValue *scratch, uint8_t capacity)
{
    uint32_t bytes = (uint32_t)capacity * sizeof(PyZ80VMValue); /* MUL.U32 scratch extent */
    PyZ80TargetContext *objects;
    if (scopes == 0 || scopes->vm == 0 || scopes->objects == 0 || scratch == 0 ||
        !capacity || capacity < scopes->vm->limits.max_arguments ||
        scratch == scopes->vm->argument_scratch || scopes->vm->status == PYZ80_VM_RUNNING ||
        scopes->vm->scope_hooks != &scopes->hooks) return 0u;
    objects = scopes->objects;
    if (!PyZ80Target_TableStorageSeparate(objects,scratch,bytes)) return 0u;
    if (overlaps(scratch, bytes, scopes, sizeof(*scopes)) ||
        overlaps(scratch, bytes, objects, sizeof(*objects)) ||
        overlaps(scratch, bytes, scopes->vm, sizeof(*scopes->vm)) ||
        overlaps(scratch, bytes, scopes->vm->frames, PyZ80VM_ArenaBytes(&scopes->vm->limits)) ||
        overlaps(scratch, bytes, objects->nodes, (uint32_t)objects->node_capacity * sizeof(PyZ80TargetNode)) ||
        overlaps(scratch, bytes, objects->fields, (uint32_t)objects->field_capacity * sizeof(PyZ80TargetField)) ||
        overlaps(scratch, bytes, objects->items, (uint32_t)objects->item_capacity * sizeof(PyZ80VMValue)) ||
        overlaps(scratch, bytes, scopes->frame_closures, (uint32_t)scopes->frame_capacity * sizeof(PyZ80VMValue)) ||
        overlaps(scratch, bytes, scopes->function_globals, (uint32_t)scopes->function_count * sizeof(PyZ80VMValue))) return 0u;
    scopes->binding_scratch = scratch;
    scopes->binding_capacity = capacity;
    scopes->hooks.prepare = prepare;
    return 1u;
}
