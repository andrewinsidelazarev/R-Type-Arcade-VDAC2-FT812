#include <string.h>
#include "pyz80_target_classes.h"
#include "pyz80_target_type_checks.h"

#define BUILD 1u
#define INIT 2u
#define WAITING 1u
#define READY 2u

static void none(PyZ80VMValue *value)
{
    value->kind = PYZ80_VM_VALUE_NONE; value->reserved = 0u;
    value->symbol = PYZ80_VM_NO_SYMBOL; value->payload = 0u;
}

static uint8_t is_object(PyZ80TargetContext *objects, const PyZ80VMValue *value)
{
    return value->kind == PYZ80_VM_VALUE_BUILTIN && value->payload == PYZ80_BUILTIN_OBJECT &&
        value->symbol == objects->class_symbols[42];
}

static uint8_t same(const PyZ80VMValue *left, const PyZ80VMValue *right)
{
    return left->kind == right->kind && left->payload == right->payload;
}

static PyZ80TargetNode *tuple(PyZ80TargetContext *objects, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node = PyZ80Target_Node(objects, value);
    if (!node || node->kind != PYZ80_TARGET_NODE_TUPLE || node->item_start > objects->item_used ||
        node->item_count > objects->item_used - node->item_start) return 0;
    return node;
}

static uint8_t new_tuple(PyZ80TargetContext *objects, uint16_t count, PyZ80VMValue *value)
{
    PyZ80TargetNode *node;
    uint16_t index;
    if (objects->item_used > objects->item_capacity || count > objects->item_capacity - objects->item_used ||
        !PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_TUPLE, 65535u, value)) return 0u;
    node = PyZ80Target_Node(objects, value);
    node->item_start = objects->item_used; node->item_count = count;
    for (index = 0u; index < count; ++index) none(&objects->items[objects->item_used++]);
    return 1u;
}

static PyZ80TargetNode *class_table(PyZ80TargetContext *objects, PyZ80TargetNode *node, uint8_t table)
{
    if (!node || node->kind != PYZ80_TARGET_NODE_CLASS || node->item_count != 2u ||
        node->item_start > objects->item_used || 2u > objects->item_used - node->item_start) return 0;
    return tuple(objects, &objects->items[node->item_start + table]);
}

/* No copied method dictionaries: a later Base.method assignment must be seen
   by existing derived instances, while previously saved bound methods stay put. */
static uint8_t lookup_from(PyZ80TargetContext *objects, PyZ80TargetNode *node,
    uint16_t key, PyZ80VMValue *result, uint16_t start)
{
    PyZ80TargetNode *order, *base;
    uint16_t index;
    uint8_t found;
    if (!node || node->reserved || !(order = class_table(objects, node, 1u))) return 0u;
    for (index = start; index < order->item_count; ++index) {
        const PyZ80VMValue *value = &objects->items[order->item_start + index];
        if (is_object(objects, value)) continue;
        base = PyZ80Target_Node(objects, value);
        if (!base || base->kind != PYZ80_TARGET_NODE_CLASS || base->reserved) return 0u;
        if (objects->class_library_guard && !objects->class_library_guard(objects->library_context, base, key)) return 0u;
        found = PyZ80Target_FindField(objects, &base->current, key, result);
        if (found != 2u) return found;
    }
    return 2u;
}

static uint8_t class_lookup(PyZ80TargetContext *objects, PyZ80TargetNode *node,
    uint16_t key, PyZ80VMValue *result)
{
    return lookup_from(objects, node, key, result, 0u);
}

static void cell_reference(PyZ80TargetNode *node, PyZ80VMValue *value)
{
    none(value); value->kind = PYZ80_VM_VALUE_CELL;
    value->payload = ((uint32_t)node->source_generation << 16) | node->source_link;
}

static uint8_t make_super(PyZ80TargetClasses *classes, PyZ80VM *vm,
    const PyZ80VMValue *args, uint8_t count, PyZ80VMValue *result)
{
    PyZ80TargetContext *objects = classes->scopes->objects;
    PyZ80VMValue anchor, receiver;
    PyZ80TargetNode *closure, *type, *order, *proxy;
    PyZ80TargetCallSignature signature_record;
    const PyZ80TargetCallSignature *signature = &signature_record;
    uint16_t index, extent, parameter;
    uint8_t depth = vm->call_depth - 1u, parent;
    if (count == 1u) {
        /* Zero-argument super is resolved from this function's actual cell and
           its current first argument, not the receiver from a previous call. */
        /* Expression units are implementation frames, not Python calls. Walk
           only their explicit lexical links; never the dynamic call stack. */
        while (classes->scopes->frame_closures[depth].kind == PYZ80_VM_VALUE_NONE) {
            parent = vm->frames[depth].lexical_parent_depth;
            if (parent >= depth) return 0u;
            depth = parent;
        }
        closure = PyZ80Target_Node(objects, &classes->scopes->frame_closures[depth]);
        if (!closure || closure->kind != PYZ80_TARGET_NODE_CALLABLE || closure->reserved != 2u ||
            closure->class_symbol >= objects->function_count || closure->item_count > 254u) return 0u;
        extent = closure->item_count * 2u;
        if (closure->item_start > objects->item_used || extent > objects->item_used - closure->item_start) return 0u;
        for (index = 0u; index < extent; index += 2u) {
            const PyZ80VMValue *key = &objects->items[closure->item_start + index];
            if (key->kind == PYZ80_VM_VALUE_SYMBOL && key->symbol == objects->class_symbols[19]) break;
        }
        if (index == extent || !classes->scopes->hooks.cell(classes->scopes, PYZ80_VM_CELL_READ,
            &objects->items[closure->item_start + index + 1u], 0, &anchor)) return 0u;
        if (!PyZ80Target_ReadSignature(objects, closure->class_symbol, &signature_record)) return 0u;
        if (!signature->supported || !signature->positional_count || signature->start >= objects->parameter_name_count ||
            !PyZ80Target_ReadWord(objects, PYZ80_TABLE_PARAMETERS, signature->start, &parameter) ||
            !PyZ80VM_ReadLocalName(vm, depth, parameter, &receiver)) return 0u;
    } else if (count == 3u) { anchor = args[1]; receiver = args[2]; }
    else return 0u; /* Unbound super and descriptor rebinding are not implemented. */
    type = PyZ80Target_Node(objects, &anchor);
    if (!type || type->kind != PYZ80_TARGET_NODE_CLASS || type->reserved) return 0u;
    type = PyZ80Target_Node(objects, &receiver);
    if (type && type->kind == PYZ80_TARGET_NODE_INSTANCE) type = PyZ80Target_Node(objects, &type->current);
    if (!type || type->reserved || !(order = class_table(objects, type, 1u))) return 0u;
    for (index = 0u; index < order->item_count; ++index)
        if (same(&objects->items[order->item_start + index], &anchor)) break;
    if (index == order->item_count || !PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_SUPER, 65535u, result)) return 0u;
    proxy = PyZ80Target_Node(objects, result); proxy->current = receiver;
    proxy->source_link = (uint16_t)anchor.payload; proxy->source_generation = (uint16_t)(anchor.payload >> 16);
    proxy->cursor = index + 1u; /* INC.U16: lookup begins AFTER the lexical anchor. */
    return 1u;
}

/* C3 merge uses the output prefix as the consumed-head set. Every walk is
   bounded by heap tuple extents. No recursion or variable-size C stack arrays;
   creation does the work once, attribute loads only traverse the saved order. */
static uint8_t emitted(PyZ80TargetContext *objects, PyZ80TargetNode *output, const PyZ80VMValue *value)
{
    uint16_t index;
    for (index = 0u; index < output->item_count; ++index)
        if (same(&objects->items[output->item_start + index], value)) return 1u;
    return 0u;
}

static uint8_t sequence(PyZ80TargetContext *objects, PyZ80TargetNode *bases, uint16_t row,
    uint16_t *start, uint16_t *count)
{
    PyZ80TargetNode *order;
    const PyZ80VMValue *base;
    if (row == bases->item_count) { *start = bases->item_start; *count = bases->item_count; return 1u; }
    base = &objects->items[bases->item_start + row];
    if (is_object(objects, base)) { *start = bases->item_start + row; *count = 1u; return 1u; }
    order = class_table(objects, PyZ80Target_Node(objects, base), 1u);
    if (!order || !order->item_count) return 0u;
    *start = order->item_start; *count = order->item_count;
    return 1u;
}

static uint8_t make_mro(PyZ80TargetContext *objects, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node = PyZ80Target_Node(objects, value), *bases, *output;
    PyZ80VMValue order, candidate;
    uint16_t row, other, start, count, head, scan;
    uint8_t pending, blocked;
    if (!(bases = class_table(objects, node, 0u)) || !bases->item_count) return 0u;
    for (row = 0u; row < bases->item_count; ++row)
        for (other = row + 1u; other < bases->item_count; ++other)
            if (same(&objects->items[bases->item_start + row], &objects->items[bases->item_start + other])) return 0u;
    if (!new_tuple(objects, 1u, &order)) return 0u;
    objects->items[node->item_start + 1u] = order;
    output = tuple(objects, &order); objects->items[output->item_start] = *value;
    for (;;) {
        pending = blocked = 0u;
        for (row = 0u; row <= bases->item_count; ++row) {
            if (!sequence(objects, bases, row, &start, &count)) return 0u;
            for (head = 0u; head < count && emitted(objects, output, &objects->items[start + head]); ++head) {}
            if (head == count) continue;
            candidate = objects->items[start + head]; pending = 1u; blocked = 0u;
            for (other = 0u; other <= bases->item_count && !blocked; ++other) {
                if (!sequence(objects, bases, other, &start, &count)) return 0u;
                for (head = 0u; head < count && emitted(objects, output, &objects->items[start + head]); ++head) {}
                if (head == count) continue;
                for (scan = head + 1u; scan < count; ++scan)
                    if (same(&candidate, &objects->items[start + scan])) { blocked = 1u; break; }
            }
            if (!blocked) break;
        }
        if (!pending) return 1u;
        if (blocked || objects->item_used >= objects->item_capacity) return 0u;
        objects->items[objects->item_used++] = candidate;
        ++output->item_count; /* INC.U16: bounded by the remaining heap items. */
    }
}

static uint8_t safe_key(PyZ80TargetContext *objects, uint16_t key)
{
    uint8_t index;
    if (key == PYZ80_VM_NO_SYMBOL) return 0u;
    for (index = 3u; index < PYZ80_CLASS_GUARD_END; ++index)
        if (key == objects->class_symbols[index]) return 0u;
    for (index = 19u; index <= 22u; ++index)
        if (key == objects->class_symbols[index]) return 0u; /* Metatype data descriptors. */
    return 1u;
}

static uint8_t attribute(void *raw, const PyZ80VMValue *object,
    uint16_t key, PyZ80VMValue *result)
{
    PyZ80TargetClasses *classes = raw;
    PyZ80TargetContext *objects = classes->scopes->objects;
    PyZ80TargetNode *node = PyZ80Target_Node(objects, object), *member;
    uint8_t instance, found, index;
    if (!result) return 0u;
    if (is_object(objects, object)) {
        if (key != objects->class_symbols[2] && key != objects->class_symbols[41]) return 0u;
        none(result); result->kind = PYZ80_VM_VALUE_SYMBOL; result->symbol = objects->class_symbols[42];
        return 1u;
    }
    if (!node) return 0u;
    if (node->kind == PYZ80_TARGET_NODE_SUPER) {
        PyZ80VMValue receiver = node->current;
        PyZ80TargetNode *receiver_node = PyZ80Target_Node(objects, &receiver), *type = receiver_node;
        if (!receiver_node) return 0u;
        instance = receiver_node->kind == PYZ80_TARGET_NODE_INSTANCE;
        if (instance) type = PyZ80Target_Node(objects, &receiver_node->current);
        if (key == objects->class_symbols[44]) { *result = receiver; return 1u; }
        if (key == objects->class_symbols[45]) { *result = instance ? receiver_node->current : receiver; return 1u; }
        if (key == objects->class_symbols[46]) {
            none(result); result->kind = PYZ80_VM_VALUE_OPAQUE;
            result->payload = ((uint32_t)node->source_generation << 16) | node->source_link;
            return PyZ80Target_Node(objects, result) != 0;
        }
        if (key == objects->class_symbols[19]) return 0u;
        found = lookup_from(objects, type, key, result, node->cursor);
        if (found == 2u) {
            for (index = 0u; index < 42u; ++index)
                if (objects->class_symbols[index] == key) return 0u;
        }
        if(found!=1u)return found;
        member=PyZ80Target_Node(objects,result);
        if(member && member->kind==PYZ80_TARGET_NODE_STATICMETHOD) {
            if(member->reserved || member->item_count || member->field_head)return 0u;
            *result=member->current;return 1u;
        }
        if(!instance)return found;
        member = PyZ80Target_Node(objects, result);
        if (member && member->kind == PYZ80_TARGET_NODE_CALLABLE && (member->reserved == 0u || member->reserved == 2u))
            return PyZ80Target_BindMethod(objects, result, &receiver, result);
        return 1u;
    }
    instance = node->kind == PYZ80_TARGET_NODE_INSTANCE;
    if (instance) {
        if (key == objects->class_symbols[19]) { *result = node->current; return 1u; }
        found = PyZ80Target_FindField(objects, object, key, result);
        if (found != 2u) return found;
        if (is_object(objects, &node->current)) {
            for (index = 0u; index < 42u; ++index)
                if (objects->class_symbols[index] == key) return 0u;
            return 2u;
        }
        node = PyZ80Target_Node(objects, &node->current);
    }
    if (!node || node->kind != PYZ80_TARGET_NODE_CLASS || node->reserved) return 0u;
    if (!instance && key == objects->class_symbols[47]) {
        if (!PyZ80Target_SetupAnnotations(objects, &node->current, key)) return 0u;
        return PyZ80Target_FindField(objects, &node->current, key, result);
    }
    if (!instance && key == objects->class_symbols[2]) {
        none(result); result->kind = PYZ80_VM_VALUE_SYMBOL; result->symbol = node->class_symbol;
        return 1u;
    }
    if (!instance && (key == objects->class_symbols[20] || key == objects->class_symbols[22])) {
        uint8_t table = key == objects->class_symbols[22];
        if (!class_table(objects, node, table)) return 0u;
        *result = objects->items[node->item_start + table]; return 1u;
    }
    if (!instance && key == objects->class_symbols[21]) {
        PyZ80TargetNode *bases = class_table(objects, node, 0u);
        if (!bases || !bases->item_count) return 0u;
        *result = objects->items[bases->item_start]; return 1u;
    }
    found = class_lookup(objects, node, key, result);
    if (found == 2u) {
        for (index = 0u; index < 42u; ++index)
            if (objects->class_symbols[index] == key) return 0u;
    }
    if(found!=1u)return found;
    member=PyZ80Target_Node(objects,result);
    if(member && member->kind==PYZ80_TARGET_NODE_STATICMETHOD) {
        if(member->reserved || member->item_count || member->field_head)return 0u;
        *result=member->current;return 1u;
    }
    if(!instance)return found;
    member = PyZ80Target_Node(objects, result);
    if (member && member->kind == PYZ80_TARGET_NODE_CALLABLE &&
        (member->reserved == 0u || member->reserved == 2u))
        return PyZ80Target_BindMethod(objects, result, object, result);
    return 1u;
}

static uint8_t invoke(void *raw, PyZ80VM *vm, uint16_t adapter,
    uint16_t destination, const PyZ80VMValue *args, uint8_t count,
    uint32_t offset, PyZ80VMValue *result)
{
    PyZ80TargetClasses *classes = raw;
    PyZ80TargetScopes *scopes = classes->scopes;
    PyZ80TargetContext *objects = scopes->objects;
    PyZ80TargetAdapterSpec spec_record;
    const PyZ80TargetAdapterSpec *spec = &spec_record;
    PyZ80TargetNode *node;
    PyZ80VMValue *mapping, globals;
    uint8_t depth, parent, found;
    if (vm != scopes->vm || !vm->call_depth || vm->call_depth > classes->capacity) return 2u;
    if (!PyZ80Target_ReadAdapter(objects, adapter, &spec_record)) return 2u;
    if (spec->operation == PYZ80_TARGET_CAPTURE_CELL) {
        if (count != 1u || args[0].kind != PYZ80_VM_VALUE_SYMBOL) return 2u;
        depth = vm->call_depth - 1u;
        if (args[0].symbol != objects->class_symbols[19]) return 0u;
        while (classes->roots[(uint16_t)classes->capacity * 2u + depth].kind == PYZ80_VM_VALUE_NONE) {
            parent = vm->frames[depth].lexical_parent_depth;
            if (parent >= depth) return 0u;
            depth = parent;
        }
        if (!depth) return 0u;
        node = PyZ80Target_Node(objects, &classes->roots[depth - 1u]);
        if (!node || node->kind != PYZ80_TARGET_NODE_CLASS || node->reserved != 1u || !node->source_link) return 0u;
        cell_reference(node, result); return 1u;
    }
    if (spec->operation == PYZ80_TARGET_STORE_ATTRIBUTE) {
        if (count != 3u || args[1].kind != PYZ80_VM_VALUE_SYMBOL) return 2u;
        node = PyZ80Target_Node(objects, args);
        if (node && node->kind == PYZ80_TARGET_NODE_INSTANCE) {
            if (is_object(objects, &node->current) || args[1].symbol == objects->class_symbols[17] ||
                args[1].symbol == objects->class_symbols[18] || args[1].symbol == objects->class_symbols[19]) return 2u;
            return 0u;
        }
        if (!node || node->kind != PYZ80_TARGET_NODE_CLASS) return 0u;
        /* Mutating protocol slots needs dynamic descriptor/type invalidation. */
        if (!safe_key(objects, args[1].symbol) || args[1].symbol == objects->class_symbols[2] ||
            (args[1].symbol == objects->class_symbols[41] && args[2].kind != PYZ80_VM_VALUE_SYMBOL)) return 2u;
        return PyZ80Target_StoreField(objects, &node->current, args[1].symbol, &args[2]) ? 1u : 2u;
    }
    if ((spec->operation != PYZ80_TARGET_LOAD_CLASS_NAME && spec->operation != PYZ80_TARGET_LOAD_CLASS_FREE_NAME && spec->operation != PYZ80_TARGET_STORE_CLASS_NAME &&
         spec->operation != PYZ80_TARGET_SETUP_CLASS_ANNOTATIONS) ||
        count != (spec->operation == PYZ80_TARGET_STORE_CLASS_NAME ? 2u : 1u) ||
        args[0].kind != PYZ80_VM_VALUE_SYMBOL || args[0].symbol >= vm->header.constant_count) return 2u;
    depth = vm->call_depth - 1u; /* SUB.U8 active frame index */
    for (;;) {
        mapping = &classes->roots[(uint16_t)classes->capacity * 2u + depth];
        if (mapping->kind != PYZ80_VM_VALUE_NONE) break;
        parent = vm->frames[depth].lexical_parent_depth;
        if (parent >= depth) return 2u; /* Never search an unrelated caller. */
        depth = parent;
    }
    if (spec->operation == PYZ80_TARGET_STORE_CLASS_NAME)
        return PyZ80Target_StoreField(objects, mapping, args[0].symbol, &args[1]) ? 1u : 2u;
    if (spec->operation == PYZ80_TARGET_SETUP_CLASS_ANNOTATIONS)
        return PyZ80Target_SetupAnnotations(objects, mapping, args[0].symbol) ? 1u : 2u;
    found = PyZ80Target_FindField(objects, mapping, args[0].symbol, result);
    if (found == 1u) return 1u;
    if (found != 2u || !objects->scope_provider) return 2u;
    if (spec->operation == PYZ80_TARGET_LOAD_CLASS_NAME) {
        if (!PyZ80Target_CurrentGlobals(scopes, spec->auxiliary, &globals)) return 2u;
        found = PyZ80Target_FindField(objects, &globals, args[0].symbol, result);
        return found == 1u ? 1u : (found == 2u ? 0u : 2u);
    }
    /* LOAD_CLASSDEREF / LOAD_NAME fallback uses the body's retained globals and
       outer cells. Class mapping stores never become lexical local slots. */
    return objects->scope_provider(objects->scope_context, vm, adapter, destination,
        args, count, offset, result);
}

static uint8_t dispatch(void *raw, PyZ80VM *vm, uint16_t adapter,
    const PyZ80VMValue *args, uint8_t count, PyZ80VMValue *result, uint16_t *function)
{
    PyZ80TargetClasses *classes = raw;
    PyZ80TargetContext *objects = classes->scopes->objects;
    const PyZ80VMControlHooks *previous = classes->hooks.previous;
    PyZ80TargetClassFrame *frame;
    PyZ80TargetNode *node;
    PyZ80VMValue *pending, *callable, initializer, mapping, bases;
    PyZ80TargetNode *base_tuple;
    PyZ80TargetAdapterSpec spec;
    uint16_t layout_offset;
    uint8_t depth, operation = 0u, found, index, base_count, flags;
    if (vm != classes->scopes->vm || !vm->call_depth || vm->call_depth > classes->capacity ||
        adapter >= objects->adapter_count) return 3u;
    if (!PyZ80Target_ReadAdapter(objects, adapter, &spec) ||
        !PyZ80Target_ReadWord(objects, PYZ80_TABLE_CALL_OFFSETS, adapter, &layout_offset)) return 3u;
    depth = vm->call_depth - 1u;
    frame = &classes->frames[depth];
    pending = &classes->roots[depth];
    callable = &classes->roots[classes->capacity + depth];
    if(spec.operation==PYZ80_TARGET_UNSUPPORTED && count && args[0].kind==PYZ80_VM_VALUE_BUILTIN &&
       (args[0].payload==PYZ80_BUILTIN_ISINSTANCE || args[0].payload==PYZ80_BUILTIN_ISSUBCLASS)) {
        if(count!=3u || !PyZ80Target_Truth(objects,vm,args,&found) ||
           !PyZ80Target_ReadByte(objects,PYZ80_TABLE_CALL_FLAGS,adapter,&flags) || !flags)return 3u;
        return PyZ80Target_TypeCheck(classes,vm,adapter,args,result);
    }
    if (count && args[0].kind == PYZ80_VM_VALUE_BUILTIN && args[0].payload == PYZ80_BUILTIN_SUPER &&
        args[0].symbol == objects->class_symbols[43] && layout_offset != 65535u) {
        if (!PyZ80Target_ReadByte(objects, PYZ80_TABLE_CALL_FLAGS, adapter, &flags) || !flags) return 3u;
        return make_super(classes, vm, args, count, result) ? 1u : 3u;
    }
    if (spec.operation == PYZ80_TARGET_BUILD_CLASS) operation = BUILD;
    else if (count && layout_offset != 65535u) {
        node = PyZ80Target_Node(objects, args);
        if ((node && node->kind == PYZ80_TARGET_NODE_CLASS) || is_object(objects, args)) operation = INIT;
    }
    if (!operation) {
        if (previous && previous->dispatch && (!previous->routes || previous->routes[adapter] != 65535u))
            return previous->dispatch(previous->context, vm, adapter, args, count, result, function);
        return 0u;
    }
    if (frame->phase) {
        if (frame->phase != READY || frame->operation != operation || frame->adapter != adapter) return 3u;
        *result = *pending; none(pending); none(callable);
        memset(frame, 0, sizeof(*frame));
        return 1u;
    }
    if (operation == BUILD) {
        if (count < 2u || args[1].kind != PYZ80_VM_VALUE_SYMBOL || args[1].symbol >= vm->header.constant_count ||
            !(node = PyZ80Target_Node(objects, args)) || node->kind != PYZ80_TARGET_NODE_CALLABLE ||
            node->reserved != 2u || node->class_symbol >= objects->function_count ||
            !PyZ80Target_ReadByte(objects, PYZ80_TABLE_CLASS_FLAGS, node->class_symbol, &flags) || !flags) return 3u;
        for (index = 2u; index < count; ++index) {
            node = PyZ80Target_Node(objects, &args[index]);
            if (!is_object(objects, &args[index]) && (!node || node->kind != PYZ80_TARGET_NODE_CLASS ||
                node->reserved || !class_table(objects, node, 1u))) return 3u; /* No guessed __mro_entries__. */
        }
        if (objects->item_used > objects->item_capacity || 2u > objects->item_capacity - objects->item_used ||
            !PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_OBJECT, PYZ80_VM_NO_SYMBOL, &mapping) ||
            !PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_CLASS, args[1].symbol, pending)) return 3u;
        node = PyZ80Target_Node(objects, pending); node->current = mapping; node->reserved = 1u;
        node->cursor = PyZ80Target_Node(objects, args)->class_symbol; /* Retain exact sealed class-body identity. */
        if (flags & 2u) {
            if (!PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_CELL, 65535u, &initializer)) return 3u;
            node->source_link = (uint16_t)initializer.payload;
            node->source_generation = (uint16_t)(initializer.payload >> 16);
        }
        node->item_start = objects->item_used; node->item_count = 2u;
        none(&objects->items[objects->item_used++]); none(&objects->items[objects->item_used++]);
        base_count = count == 2u ? 1u : count - 2u; /* SUB.U8: body/name are not bases. */
        if (!new_tuple(objects, base_count, &bases)) return 3u;
        objects->items[node->item_start] = bases; base_tuple = tuple(objects, &bases);
        for (index = 0u; index < base_count; ++index) {
            if (count == 2u) {
                initializer.kind = PYZ80_VM_VALUE_BUILTIN; initializer.reserved = 0u;
                initializer.symbol = objects->class_symbols[42]; initializer.payload = PYZ80_BUILTIN_OBJECT;
            } else initializer = args[index + 2u];
            objects->items[base_tuple->item_start + index] = initializer;
        }
        *callable = args[0]; frame->name = args[1].symbol;
        if ((uint16_t)depth + 1u < classes->capacity)
            classes->roots[(uint16_t)classes->capacity * 2u + depth + 1u] = mapping;
    } else {
        node = PyZ80Target_Node(objects, args);
        found = is_object(objects, args) ? 2u : class_lookup(objects, node, objects->class_symbols[0], &initializer);
        if (!found || (found == 2u && count != 1u)) return 3u;
        if (!PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_INSTANCE, PYZ80_VM_NO_SYMBOL, pending)) return 3u;
        PyZ80Target_Node(objects, pending)->current = args[0];
        if (found == 2u) { *result = *pending; none(pending); return 1u; }
        if (!PyZ80Target_BindMethod(objects, &initializer, pending, callable)) return 3u;
    }
    frame->adapter = adapter; frame->operation = operation; frame->phase = WAITING;
    return 4u;
}

static uint8_t prepare_call(void *raw, PyZ80VM *vm, PyZ80VMValue *callable,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function)
{
    PyZ80TargetClasses *classes = raw;
    uint8_t depth = vm->call_depth - 1u;
    PyZ80TargetClassFrame *frame = &classes->frames[depth];
    PyZ80TargetNode *node;
    if (frame->phase != WAITING) {
        const PyZ80VMControlHooks *previous = classes->hooks.previous;
        return previous && previous->prepare_call ? previous->prepare_call(previous->context, vm, callable, args, count, function) : 0u;
    }
    *callable = classes->roots[classes->capacity + depth];
    if (frame->operation == BUILD) {
        node = PyZ80Target_Node(classes->scopes->objects, callable);
        if (!node || node->kind != PYZ80_TARGET_NODE_CALLABLE) return 0u;
        *function = node->class_symbol; *count = 0u;
        return 1u;
    }
    args[0] = *callable;
    return classes->scopes->hooks.prepare(classes->scopes, vm, frame->adapter, args, count, function) == 1u;
}

static uint8_t returned(void *raw, PyZ80VM *vm)
{
    PyZ80TargetClasses *classes = raw;
    PyZ80TargetContext *objects = classes->scopes->objects;
    PyZ80TargetClassFrame *frame;
    PyZ80VMValue *pending, value, mapping;
    PyZ80TargetNode *node;
    uint8_t parent, index, found;
    if (vm->call_depth < 2u || classes->frames[vm->call_depth - 2u].phase != WAITING) {
        const PyZ80VMControlHooks *previous = classes->hooks.previous;
        return previous && previous->returned ? previous->returned(previous->context, vm) : 0u;
    }
    parent = vm->call_depth - 2u; /* SUB.U8 suspended instruction's frame */
    frame = &classes->frames[parent]; pending = &classes->roots[parent];
    if (frame->operation == BUILD) {
        node = PyZ80Target_Node(objects, pending);
        if (!node || node->kind != PYZ80_TARGET_NODE_CLASS || node->reserved != 1u) return 0u;
        mapping = node->current;
        for (index = 3u; index < PYZ80_CLASS_GUARD_END; ++index)
            if (objects->class_symbols[index] != 65535u &&
                PyZ80Target_FindField(objects, &mapping, objects->class_symbols[index], &value) != 2u) return 0u;
        for (index = 19u; index <= 22u; ++index)
            if (objects->class_symbols[index] != 65535u &&
                PyZ80Target_FindField(objects, &mapping, objects->class_symbols[index], &value) != 2u) return 0u;
        if (PyZ80Target_FindField(objects, &mapping, objects->class_symbols[41], &value) != 1u ||
            value.kind != PYZ80_VM_VALUE_SYMBOL) return 0u;
        found = PyZ80Target_FindField(objects, &mapping, objects->class_symbols[1], &value);
        if (found == 2u) {
            none(&value);
            if (!PyZ80Target_StoreField(objects, &mapping, objects->class_symbols[1], &value)) return 0u;
        } else if (!found) return 0u;
        if (!make_mro(objects, pending)) return 0u;
        if (node->source_link) {
            PyZ80VMValue reference;
            cell_reference(node, &reference);
            if (!classes->scopes->hooks.cell(classes->scopes, PYZ80_VM_CELL_WRITE, &reference, pending, &value)) return 0u;
        }
        node->reserved = 0u;
        none(&classes->roots[(uint16_t)classes->capacity * 2u + parent + 1u]);
    }
    frame->phase = READY;
    return 1u;
}

static void failed(void *raw, PyZ80VM *vm)
{
    PyZ80TargetClasses *classes = raw;
    uint8_t depth;
    for(depth=0u;depth<classes->capacity;++depth)PyZ80Target_TypeCheckClear(classes,depth);
    uint16_t index;
    for (index = 0u; index < (uint16_t)classes->capacity * 3u; ++index) none(&classes->roots[index]);
    memset(classes->frames, 0, (uint16_t)classes->capacity * sizeof(*classes->frames));
    if (classes->hooks.previous && classes->hooks.previous->failed && classes->hooks.previous->failed != failed)
        classes->hooks.previous->failed(classes->hooks.previous->context, vm);
}

static uint8_t overlaps(const void *left, uint32_t left_bytes, const void *right, uint32_t right_bytes)
{
    uintptr_t a = (uintptr_t)left, b = (uintptr_t)right;
    if (!left || !right || !left_bytes || !right_bytes) return 0u;
    return a <= b ? b-a < left_bytes : a-b < right_bytes;
}

static uint8_t isolated(const void *buffer, uint32_t bytes, PyZ80TargetScopes *scopes)
{
    PyZ80TargetContext *objects = scopes->objects;
    PyZ80VM *vm = scopes->vm;
    const PyZ80VMControlHooks *hooks = vm->control_hooks;
    uint16_t remaining = 255u;
    while (hooks) {
        if (!remaining-- || overlaps(buffer, bytes, hooks, sizeof(*hooks)) ||
            overlaps(buffer, bytes, hooks->roots, (uint32_t)hooks->root_count * sizeof(PyZ80VMValue)) ||
            overlaps(buffer, bytes, hooks->routes, (uint32_t)objects->adapter_count * sizeof(uint16_t))) return 0u;
        hooks = hooks->previous;
    }
    return PyZ80Target_TableStorageSeparate(objects,buffer,bytes) && !overlaps(buffer, bytes, scopes, sizeof(*scopes)) &&
        !overlaps(buffer, bytes, vm, sizeof(*vm)) && !overlaps(buffer, bytes, objects, sizeof(*objects)) &&
        !overlaps(buffer, bytes, vm->frames, PyZ80VM_ArenaBytes(&vm->limits)) &&
        !overlaps(buffer, bytes, objects->nodes, (uint32_t)objects->node_capacity * sizeof(*objects->nodes)) &&
        !overlaps(buffer, bytes, objects->fields, (uint32_t)objects->field_capacity * sizeof(*objects->fields)) &&
        !overlaps(buffer, bytes, objects->items, (uint32_t)objects->item_capacity * sizeof(*objects->items)) &&
        !overlaps(buffer, bytes, scopes->frame_closures, (uint32_t)scopes->frame_capacity * sizeof(PyZ80VMValue)) &&
        !overlaps(buffer, bytes, scopes->function_globals, (uint32_t)scopes->function_count * sizeof(PyZ80VMValue)) &&
        !overlaps(buffer, bytes, scopes->binding_scratch, (uint32_t)scopes->binding_capacity * sizeof(PyZ80VMValue));
}

uint8_t PyZ80Target_AttachClasses(PyZ80TargetClasses *classes, PyZ80TargetScopes *scopes,
    PyZ80TargetClassFrame *frames, PyZ80VMValue *roots, uint8_t capacity, uint16_t *routes)
{
    PyZ80TargetContext *objects;
    PyZ80VM *vm;
    const PyZ80VMControlHooks *previous;
    uint16_t index, layout_offset;
    uint8_t flags;
    PyZ80TargetAdapterSpec spec;
    uint32_t frame_bytes = (uint32_t)capacity * sizeof(*frames);
    uint32_t root_bytes = (uint32_t)capacity * 3u * sizeof(*roots);
    uint32_t route_bytes;
    if (!classes || !scopes || !scopes->vm || !scopes->objects || !frames || !roots || !routes || !capacity) return 0u;
    vm = scopes->vm; objects = scopes->objects;
    if (vm->status != PYZ80_VM_IDLE || vm->scope_hooks != &scopes->hooks || !scopes->hooks.prepare ||
        capacity < vm->limits.max_call_depth || objects->class_provider || !PyZ80Target_HasTable(objects, PYZ80_TABLE_CLASS_FLAGS) ||
        !objects->class_symbols || objects->function_count != vm->header.function_count ||
        objects->adapter_count != vm->header.adapter_count || !PyZ80Target_HasTable(objects, PYZ80_TABLE_ADAPTERS) ||
        !PyZ80Target_HasTable(objects, PYZ80_TABLE_CALL_OFFSETS)) return 0u;
    route_bytes = (uint32_t)objects->adapter_count * sizeof(*routes);
    if (!isolated(classes, sizeof(*classes), scopes) || !isolated(frames, frame_bytes, scopes) ||
        !isolated(roots, root_bytes, scopes) || !isolated(routes, route_bytes, scopes) ||
        overlaps(classes, sizeof(*classes), frames, frame_bytes) || overlaps(classes, sizeof(*classes), roots, root_bytes) ||
        overlaps(classes, sizeof(*classes), routes, route_bytes) || overlaps(frames, frame_bytes, roots, root_bytes) ||
        overlaps(frames, frame_bytes, routes, route_bytes) || overlaps(roots, root_bytes, routes, route_bytes)) return 0u;
    previous = vm->control_hooks;
    for (index = 0u; index < PYZ80_CLASS_SYMBOL_COUNT; ++index)
        if (objects->class_symbols[index] != 65535u && objects->class_symbols[index] >= vm->header.constant_count) return 0u;
    for (index = 0u; index < objects->function_count; ++index) {
        if (!PyZ80Target_ReadByte(objects, PYZ80_TABLE_CLASS_FLAGS, index, &flags) ||
            (flags != 0u && flags != 1u && flags != 3u) || (flags &&
            (objects->class_symbols[0] == 65535u || objects->class_symbols[1] == 65535u ||
             objects->class_symbols[2] == 65535u || objects->class_symbols[41] == 65535u ||
             objects->class_symbols[42] == 65535u))) return 0u;
    }
    /* Populate caller scratch before installing hooks; a failed table read must
       never leave a partially attached provider in the VM. */
    for (index = 0u; index < objects->adapter_count; ++index) {
        if (!PyZ80Target_ReadAdapter(objects, index, &spec) ||
            !PyZ80Target_ReadWord(objects, PYZ80_TABLE_CALL_OFFSETS, index, &layout_offset)) return 0u;
        routes[index] = spec.operation == PYZ80_TARGET_BUILD_CLASS || layout_offset != 65535u ||
            (previous && (!previous->routes || previous->routes[index] != 65535u)) ? index : 65535u;
    }
    memset(classes, 0, sizeof(*classes)); memset(frames, 0, frame_bytes);
    for (index = 0u; index < (uint16_t)capacity * 3u; ++index) none(&roots[index]);
    classes->scopes = scopes; classes->frames = frames; classes->roots = roots; classes->capacity = capacity;
    classes->hooks.context = classes; classes->hooks.dispatch = dispatch; classes->hooks.returned = returned;
    classes->hooks.failed = failed; classes->hooks.prepare_call = prepare_call;
    classes->hooks.previous = previous; classes->hooks.routes = routes;
    classes->hooks.roots = roots; classes->hooks.root_count = (uint16_t)capacity * 3u;
    vm->control_hooks = &classes->hooks;
    objects->class_provider = invoke; objects->class_context = classes; objects->class_attribute = attribute;
    return 1u;
}
