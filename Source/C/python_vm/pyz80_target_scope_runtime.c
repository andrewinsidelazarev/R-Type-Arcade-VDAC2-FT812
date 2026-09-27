#include <string.h>
#include "pyz80_target_scope_runtime.h"

static void none(PyZ80VMValue *value)
{
    value->kind = PYZ80_VM_VALUE_NONE;
    value->reserved = 0u;
    value->symbol = PYZ80_VM_NO_SYMBOL;
    value->payload = 0u;
}

static PyZ80TargetNode *node(PyZ80TargetContext *objects,
                           const PyZ80VMValue *value, uint8_t kind)
{
    uint16_t link;
    PyZ80TargetNode *found;
    if (value == 0 || objects->nodes == 0 ||
        objects->node_used > objects->node_capacity ||
        value->kind != (kind == PYZ80_TARGET_NODE_CELL ? PYZ80_VM_VALUE_CELL : PYZ80_VM_VALUE_OPAQUE)) return 0;
    link = (uint16_t)value->payload;
    if (!link || link > objects->node_used) return 0;
    found = &objects->nodes[link - 1u];
    if (found->kind != kind || found->generation != (uint16_t)(value->payload >> 16)) return 0;
    return found;
}

static uint8_t cell(void *raw, uint8_t operation, const PyZ80VMValue *reference,
                    const PyZ80VMValue *value, PyZ80VMValue *result)
{
    PyZ80TargetScopes *scopes = raw;
    PyZ80TargetContext *objects = scopes->objects;
    PyZ80TargetNode *found;
    PyZ80VMValue saved;
    if (result == 0) return 0u;
    if (operation == PYZ80_VM_CELL_CREATE) {
        if (value == 0 || value->kind == PYZ80_VM_VALUE_CELL) return 0u;
        saved = *value;
        if (!PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_CELL, PYZ80_VM_NO_SYMBOL, result)) return 0u;
        found = node(objects, result, PYZ80_TARGET_NODE_CELL);
        found->has_current = 1u;
        found->current = saved;
        return 1u;
    }
    found = node(objects, reference, PYZ80_TARGET_NODE_CELL);
    if (found == 0) return 0u;
    if (operation == PYZ80_VM_CELL_READ) {
        if (!found->has_current) return 0u;
        *result = found->current;
        return 1u;
    }
    if (operation != PYZ80_VM_CELL_WRITE || value == 0 || value->kind == PYZ80_VM_VALUE_CELL)
        return 0u;
    saved = *value;
    found->current = saved;
    found->has_current = 1u;
    none(result);
    return 1u;
}

static uint8_t enter(void *raw, PyZ80VM *vm)
{
    PyZ80TargetScopes *scopes = raw;
    if (vm != scopes->vm || !vm->call_depth || vm->call_depth > scopes->frame_capacity) return 0u;
    none(&scopes->frame_closures[vm->call_depth - 1u]);
    return 1u;
}

static uint8_t bind(void *raw, PyZ80VM *vm, uint16_t function, const PyZ80VMValue *callable)
{
    PyZ80TargetScopes *scopes = raw;
    PyZ80VMValue prototype, receiver;
    PyZ80TargetNode *found;
    if (!PyZ80Target_UnwrapCallable(scopes->objects, callable, &prototype, &receiver)) return 0u;
    found = node(scopes->objects, &prototype, PYZ80_TARGET_NODE_CALLABLE);
    if (vm != scopes->vm || !vm->call_depth || vm->call_depth > scopes->frame_capacity ||
        found == 0 || found->reserved > 2u || found->class_symbol != function ||
        function >= scopes->objects->function_count || found->item_count > 254u) return 0u;
    if (found->reserved == 2u) scopes->frame_closures[vm->call_depth - 1u] = prototype;
    else none(&scopes->frame_closures[vm->call_depth - 1u]);
    return 1u;
}

static uint8_t resolve(void *raw, PyZ80VM *vm, const PyZ80VMValue *callable,
                       uint8_t count, uint16_t *function)
{
    PyZ80TargetScopes *scopes = raw;
    PyZ80TargetNode *found;
    if (vm != scopes->vm) return 2u;
    found = node(scopes->objects, callable, PYZ80_TARGET_NODE_CALLABLE);
    if (found == 0) {
        /* A stale native arena reference cannot become an external callable. */
        uint16_t link = (uint16_t)callable->payload;
        if (callable->kind == PYZ80_VM_VALUE_OPAQUE && scopes->objects->nodes != 0 &&
            link && link <= scopes->objects->node_used && link <= scopes->objects->node_capacity &&
            scopes->objects->nodes[link - 1u].kind == PYZ80_TARGET_NODE_CALLABLE) return 2u;
        return 0u;
    }
    if (found->reserved != 2u) return 0u;
    if (found->has_current) return found->has_current == 1u ? 0u : 2u;
    if (found->class_symbol >= scopes->objects->function_count) return 2u;
    if (PyZ80Target_HasTable(scopes->objects,PYZ80_TABLE_SIGNATURES)) {
        PyZ80TargetCallSignature signature;
        if (!PyZ80Target_ReadSignature(scopes->objects,found->class_symbol,&signature) || !signature.supported || signature.count != count) return 2u;
    } else {
        uint16_t arity;
        if(!PyZ80Target_ReadWord(scopes->objects,PYZ80_TABLE_ARITIES,found->class_symbol,&arity) || arity!=count) return 2u;
    }
    *function = found->class_symbol;
    return 1u;
}

uint8_t PyZ80Target_CurrentGlobals(PyZ80TargetScopes *scopes,
    uint16_t function, PyZ80VMValue *result)
{
    PyZ80VM *vm;
    PyZ80TargetNode *found;
    const PyZ80VMValue *mapping;
    uint8_t depth, parent;
    if (!scopes || !result || !scopes->vm || !scopes->function_globals || function >= scopes->function_count) return 0u;
    vm = scopes->vm;
    if (!vm->call_depth || vm->call_depth > scopes->frame_capacity) return 0u;
    mapping = &scopes->function_globals[function];
    depth = vm->call_depth - 1u; /* SUB.U8: active frame index. */
    for (;;) {
        found = node(scopes->objects, &scopes->frame_closures[depth], PYZ80_TARGET_NODE_CALLABLE);
        if (!found && scopes->frame_closures[depth].kind != PYZ80_VM_VALUE_NONE) return 0u;
        if (found) {
            if (found->reserved != 2u) return 0u;
            mapping = &found->current;
            break;
        }
        parent = vm->frames[depth].lexical_parent_depth;
        if (parent >= depth) break;
        depth = parent;
    }
    if (!node(scopes->objects, mapping, PYZ80_TARGET_NODE_OBJECT)) return 0u;
    *result = *mapping;
    return 1u;
}

static uint8_t invoke(void *raw, PyZ80VM *vm, uint16_t adapter,
    uint16_t destination, const PyZ80VMValue *arguments, uint8_t count,
    uint32_t offset, PyZ80VMValue *result)
{
    PyZ80TargetScopes *scopes = raw;
    PyZ80TargetContext *objects = scopes->objects;
    PyZ80TargetAdapterSpec record;
    const PyZ80TargetAdapterSpec *spec = &record;
    PyZ80TargetNode *found;
    uint16_t start;
    uint16_t index;
    uint16_t previous;
    uint16_t function;
    uint16_t amount;
    uint16_t field_key,previous_key;
    uint8_t depth;
    uint8_t parent;
    uint8_t capture = 0u;
    (void)destination; (void)offset;
    if(!PyZ80Target_ReadAdapter(objects,adapter,&record)) return 2u;
    start=spec->auxiliary;
    if (vm != scopes->vm || vm->call_depth > scopes->frame_capacity ||
        (!vm->call_depth && spec->operation != PYZ80_TARGET_MAKE_CLOSURE &&
         spec->operation != PYZ80_TARGET_MAKE_CLOSURE_DEFAULTS &&
         spec->operation != PYZ80_TARGET_MAKE_GENERATOR_CLOSURE &&
         spec->operation != PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS)) return 0u;
    if (spec->operation == PYZ80_TARGET_CAPTURE_CELL) {
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_SYMBOL) return 0u;
        if (PyZ80VM_CaptureName(vm, arguments[0].symbol, result)) return 1u;
        if (vm->status == PYZ80_VM_ERROR) return 2u;
        capture = 1u;
    }
    if (spec->operation == PYZ80_TARGET_LOAD_GLOBALS) {
        return !count && PyZ80Target_CurrentGlobals(scopes, start, result) ? 1u : 2u;
    }
    if (spec->operation == PYZ80_TARGET_SETUP_GLOBAL_ANNOTATIONS) {
        PyZ80VMValue mapping;
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_SYMBOL || arguments[0].symbol >= vm->header.constant_count ||
            !PyZ80Target_CurrentGlobals(scopes, start, &mapping)) return 2u;
        return PyZ80Target_SetupAnnotations(objects, &mapping, arguments[0].symbol) ? 1u : 2u;
    }
    if (spec->operation == PYZ80_TARGET_MAKE_CLOSURE || spec->operation == PYZ80_TARGET_MAKE_CLOSURE_DEFAULTS ||
        spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE || spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS) {
        /* Source definitions retain the identity of their actual module mapping. */
        uint16_t captures;
        uint16_t defaults = 0u;
        if (!count || start >= objects->field_key_count ||
            count > objects->field_key_count - start ||
            node(objects, &arguments[0], PYZ80_TARGET_NODE_OBJECT) == 0) return 0u;
        if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_FIELDS,start++,&function)) return 0u;
        if (function >= objects->function_count) return 0u;
        captures = count - 1u;
        if (spec->operation == PYZ80_TARGET_MAKE_CLOSURE_DEFAULTS || spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS) {
            if (start > objects->field_key_count || objects->field_key_count - start < 2u) return 0u;
            if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_FIELDS,start++,&captures) ||
               !PyZ80Target_ReadWord(objects,PYZ80_TABLE_FIELDS,start++,&defaults)) return 0u;
            if (captures > 254u || defaults > 254u || captures + defaults != count - 1u ||
                count - 1u > objects->field_key_count - start) return 0u;
        }
        amount = (uint16_t)(count - 1u) * 2u; /* MUL.U16 closure count, name/cell pair */
        if (objects->item_used > objects->item_capacity || amount > objects->item_capacity - objects->item_used ||
            (amount && objects->items == 0)) return 0u;
        for (index = 0u; index < count - 1u; ++index) {
            if (!PyZ80Target_ReadWord(objects,PYZ80_TABLE_FIELDS,start+index,&field_key) || field_key >= vm->header.constant_count ||
                (index < captures && node(objects, &arguments[index + 1u], PYZ80_TARGET_NODE_CELL) == 0) ||
                (index >= captures && arguments[index + 1u].kind == PYZ80_VM_VALUE_CELL)) return 0u;
            for (previous = index < captures ? 0u : captures; previous < index; ++previous) {
                if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_FIELDS,start+previous,&previous_key) || previous_key==field_key) return 0u;
            }
        }
        if (!PyZ80Target_Callable(objects, function, 0, result)) return 0u;
        found = node(objects, result, PYZ80_TARGET_NODE_CALLABLE);
        found->reserved = 2u;
        found->has_current = spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE ||
                             spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS;
        found->current = arguments[0];
        found->item_start = objects->item_used;
        found->item_count = captures;
        found->cursor = defaults; /* Trailing name/value pairs retain evaluated defaults. */
        for (index = 0u; index < count - 1u; ++index) {
            if(!PyZ80Target_ReadWord(objects,PYZ80_TABLE_FIELDS,start+index,&field_key)) return 0u;
            PyZ80VMValue *key = &objects->items[objects->item_used++];
            none(key); key->kind = PYZ80_VM_VALUE_SYMBOL; key->symbol = field_key;
            objects->items[objects->item_used++] = arguments[index + 1u];
        }
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_LOAD_GLOBAL_NAME || spec->operation == PYZ80_TARGET_STORE_GLOBAL_NAME) {
        PyZ80VMValue mapping;
        if (count != (spec->operation == PYZ80_TARGET_STORE_GLOBAL_NAME ? 2u : 1u) ||
            arguments[0].kind != PYZ80_VM_VALUE_SYMBOL || arguments[0].symbol >= vm->header.constant_count ||
            scopes->function_globals == 0 || start >= scopes->function_count) return 2u;
        if (!PyZ80Target_CurrentGlobals(scopes, start, &mapping)) return 2u;
        if (spec->operation == PYZ80_TARGET_STORE_GLOBAL_NAME)
            return PyZ80Target_StoreField(objects, &mapping, arguments[0].symbol, &arguments[1]) ? 1u : 2u;
        function = PyZ80Target_FindField(objects, &mapping, arguments[0].symbol, result);
        return function == 1u ? 1u : (function == 2u ? 0u : 2u);
    }
    if ((!capture && spec->operation != PYZ80_TARGET_LOAD_LEXICAL_NAME && spec->operation != PYZ80_TARGET_LOAD_CLASS_FREE_NAME) || count != 1u ||
        arguments[0].kind != PYZ80_VM_VALUE_SYMBOL) return 0u;
    depth = vm->call_depth - 1u;
    for (;;) {
        found = node(objects, &scopes->frame_closures[depth], PYZ80_TARGET_NODE_CALLABLE);
        if (found == 0 && scopes->frame_closures[depth].kind != PYZ80_VM_VALUE_NONE) return 2u;
        if (found != 0 && found->reserved == 2u) {
            start = found->item_start;
            if (found->item_count > 254u) return 2u;
            amount = found->item_count * 2u;
            if (start > objects->item_used || amount > objects->item_used - start ||
                objects->item_used > objects->item_capacity || (amount && objects->items == 0)) return 2u;
            for (index = 0u; index < amount; index += 2u) {
                if (objects->items[start + index].kind != PYZ80_VM_VALUE_SYMBOL) return 2u;
                if (objects->items[start + index].symbol == arguments[0].symbol) {
                    if (capture) {
                        if (node(objects, &objects->items[start + index + 1u], PYZ80_TARGET_NODE_CELL) == 0) return 2u;
                        *result = objects->items[start + index + 1u];
                        return 1u;
                    }
                    return cell(scopes, PYZ80_VM_CELL_READ, &objects->items[start + index + 1u], 0, result) ? 1u : 2u;
                }
            }
            if (capture) return 0u; /* Globals are not closure cells. */
            function = PyZ80Target_FindField(objects, &found->current, arguments[0].symbol, result);
            return function == 1u ? 1u : (function == 2u ? 0u : 2u);
        }
        parent = vm->frames[depth].lexical_parent_depth;
        if (parent >= depth) {
            if (capture) return 0u;
            if (scopes->function_globals == 0 || spec->auxiliary >= scopes->function_count) return 2u;
            function = PyZ80Target_FindField(objects, &scopes->function_globals[spec->auxiliary],
                                             arguments[0].symbol, result);
            return function == 1u ? 1u : (function == 2u ? 0u : 2u);
        }
        depth = parent;
    }
}

uint8_t PyZ80Target_AttachScopes(PyZ80TargetScopes *scopes,
    PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80VMValue *frame_closures, uint8_t frame_capacity,
    const PyZ80VMValue *function_globals, uint16_t function_count)
{
    if (scopes == 0 || objects == 0 || vm == 0 || vm->status == PYZ80_VM_RUNNING ||
        frame_closures == 0 || frame_capacity < vm->limits.max_call_depth ||
        vm->adapter.context != objects || vm->adapter.invoke != PyZ80Target_Invoke) return 0u;
    if (!PyZ80Target_TableStorageSeparate(objects,scopes,sizeof(*scopes)) ||
        !PyZ80Target_TableStorageSeparate(objects,frame_closures,(uint32_t)frame_capacity*sizeof(*frame_closures)) ||
        !PyZ80Target_TableStorageSeparate(objects,function_globals,(uint32_t)function_count*sizeof(*function_globals))) return 0u;
    memset(scopes, 0, sizeof(*scopes));
    scopes->objects = objects; scopes->vm = vm;
    scopes->frame_closures = frame_closures; scopes->frame_capacity = frame_capacity;
    scopes->function_globals = function_globals; scopes->function_count = function_count;
    scopes->hooks.cell = cell; scopes->hooks.enter = enter; scopes->hooks.bind = bind;
    scopes->hooks.resolve = resolve;
    scopes->hooks.context = scopes;
    vm->scope_hooks = &scopes->hooks;
    objects->scope_provider = invoke; objects->scope_context = scopes;
    return 1u;
}
