#include <string.h>
#include "pyz80_target_gc.h"
#include "pyz80_target_deque.h"
#include "pyz80_target_buffers.h"

#define UNUSED 65535u

static uint8_t mark(PyZ80TargetContext *objects, PyZ80TargetGC *work,
                    const PyZ80VMValue *value)
{
    uint16_t index;
    PyZ80TargetNode *node;
    if (value->kind == PYZ80_VM_VALUE_BUILTIN) {
        uint8_t truth;
        return PyZ80Target_Truth(objects, 0, value, &truth);
    }
    if (value->kind != PYZ80_VM_VALUE_OPAQUE && value->kind != PYZ80_VM_VALUE_CELL)
        return value->kind <= PYZ80_VM_VALUE_SERIALIZED;
    index = (uint16_t)value->payload;
    if (!index || index > objects->node_used) return 0u;
    --index; /* DEC.U16 one-based object handle */
    node = &objects->nodes[index];
    if (!node->generation || node->generation != (uint16_t)(value->payload >> 16) ||
        node->kind == PYZ80_TARGET_NODE_FREE || node->kind > PYZ80_TARGET_NODE_STATICMETHOD ||
        (node->kind == PYZ80_TARGET_NODE_CELL) != (value->kind == PYZ80_VM_VALUE_CELL)) return 0u;
    if (!work->marked[index]) {
        if (work->queued >= work->node_capacity) return 0u;
        work->marked[index] = 1u;
        work->queue[work->queued++] = index;
    }
    return 1u;
}

static uint8_t mark_locals(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetGC *work, uint16_t frame, uint16_t count)
{
    uint16_t index;
    uint32_t start = (uint32_t)frame * vm->limits.locals_per_frame; /* MUL.U32 frame stride */
    if (count > vm->limits.locals_per_frame || (count && vm->locals == 0)) return 0u;
    for (index = 0u; index < count; ++index)
        if (!mark(objects, work, &vm->locals[start + index].value)) return 0u;
    return 1u;
}

static uint8_t trace_node(PyZ80TargetContext *objects, PyZ80VM *vm, PyZ80TargetGC *work, uint16_t index)
{
    PyZ80TargetNode *node = &objects->nodes[index];
    uint16_t link;
    uint16_t count = 0u;
    uint16_t item;
    if (node->kind == PYZ80_TARGET_NODE_GENERATOR) {
        PyZ80VMGenerator *generator;
        if (node->reserved > 1u || node->has_current > 1u ||
            (node->has_current && !mark(objects,work,&node->current))) return 0u;
        if (node->reserved) return node->cursor == 65535u && !node->has_current;
        if (!vm || node->cursor >= vm->limits.max_generators) return 0u;
        generator = &vm->generators[node->cursor];
        if (!generator->in_use || generator->owner.kind != PYZ80_VM_VALUE_OPAQUE ||
            generator->owner.payload != (((uint32_t)node->generation << 16) | (index + 1u))) return 0u;
        return generator->done || (mark(objects,work,&generator->callable) &&
            mark_locals(objects,vm,work,vm->limits.max_call_depth + node->cursor,generator->local_count));
    }
    if (node->kind == PYZ80_TARGET_NODE_OBJECT || node->kind == PYZ80_TARGET_NODE_INSTANCE ||
        (node->kind == PYZ80_TARGET_NODE_DICT && !node->reserved) ||
        node->kind == PYZ80_TARGET_NODE_CALLABLE) {
        if (node->kind == PYZ80_TARGET_NODE_INSTANCE && !mark(objects, work, &node->current)) return 0u;
        link = node->field_head;
        while (link) {
            PyZ80TargetField *field;
            if (link > objects->field_used || work->field_map[link - 1u] != UNUSED) return 0u;
            field = &objects->fields[link - 1u];
            work->field_map[link - 1u] = 0u; /* Mark owned field; cycles/shared field chains are invalid. */
            if (!mark(objects, work, &field->value)) return 0u;
            ++count;
            link = field->next;
        }
        if (node->kind == PYZ80_TARGET_NODE_DICT && count != node->cursor) return 0u;
        count = 0u;
        if (node->kind != PYZ80_TARGET_NODE_CALLABLE) return 1u;
    }
    if(node->kind==PYZ80_TARGET_NODE_DEQUE) {
        PyZ80VMValue block=node->current;
        PyZ80TargetNode *b;
        uint16_t remaining=objects->node_used,total=0u,tail=0u,generation=0u;
        if(!PyZ80Target_DequeValid(objects,node))return 0u;
        while(block.kind!=PYZ80_VM_VALUE_NONE) {
            b=PyZ80Target_Node(objects,&block);
            if(!remaining-- || !PyZ80Target_DequeBlockValid(objects,b) ||
               b->source_link!=index+1u || b->source_generation!=node->generation ||
               b->reserved-b->cursor>node->item_count-total || !mark(objects,work,&block))return 0u;
            total+=b->reserved-b->cursor; /* ADD.U16: сумма после проверки границы. */
            tail=(uint16_t)block.payload;generation=b->generation;block=b->current;
        }
        return total==node->item_count && tail==node->source_link && generation==node->source_generation;
    } else if(node->kind==PYZ80_TARGET_NODE_DEQUE_BLOCK) {
        if(!PyZ80Target_DequeBlockValid(objects,node))return 0u;
        count=PYZ80_DEQUE_BLOCK_ITEMS;
        for(item=0u;item<count;++item)
            if((item<node->cursor || item>=node->reserved) && objects->items[node->item_start+item].kind!=PYZ80_VM_VALUE_NONE)return 0u;
        if(!mark(objects,work,&node->current))return 0u;
    } else if(node->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR) {
        PyZ80VMValue owner;
        owner.kind=PYZ80_VM_VALUE_OPAQUE;owner.payload=((uint32_t)node->source_generation<<16)|node->source_link;
        if(!PyZ80Target_DequeIteratorValid(objects,node) || !mark(objects,work,&owner) ||
           (node->has_current && !mark(objects,work,&node->current)))return 0u;
    } else if(PYZ80_IS_BUFFER(node)) {
        return PyZ80Target_BufferTraceValid(objects,node) && mark(objects,work,&node->current);
    } else if(node->kind==PYZ80_TARGET_NODE_BUFFER_BLOCK) {
        PyZ80VMValue owner;PyZ80TargetNode *n;
        owner.kind=PYZ80_VM_VALUE_OPAQUE;owner.payload=((uint32_t)node->source_generation<<16)|node->source_link;
        n=PyZ80Target_Node(objects,&owner);
        if(!PyZ80Target_BufferBlockValid(objects,node) || !PYZ80_IS_BUFFER(n) ||
            !mark(objects,work,&owner) || !mark(objects,work,&node->current))return 0u;
        count=PYZ80_BUFFER_BLOCK_SLOTS;
    } else if(node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
        PyZ80VMValue *parts;
        if(!PyZ80Target_DefaultDictParts(objects,node,&parts))return 0u;
        count=2u;
    } else if (node->kind == PYZ80_TARGET_NODE_LIST || node->kind == PYZ80_TARGET_NODE_TUPLE || node->kind==PYZ80_TARGET_NODE_SLICE) {
        if(node->kind==PYZ80_TARGET_NODE_SLICE && node->item_count!=3u)return 0u;
        count = node->item_count;
        if (node->kind == PYZ80_TARGET_NODE_LIST &&
            (count > node->cursor || node->item_start > objects->item_used ||
             node->cursor > objects->item_used - node->item_start)) return 0u;
    } else if(node->kind==PYZ80_TARGET_NODE_SET) {
        if(node->reserved>1u || node->field_head || node->item_count>node->cursor ||
            node->item_start>objects->item_used || node->cursor>objects->item_used-node->item_start) return 0u;
        count=node->item_count;
        for(item=0u;item<count;++item) {
            const PyZ80VMValue *key=&objects->items[node->item_start+item];
            if(key->kind!=PYZ80_VM_VALUE_NONE && key->kind!=PYZ80_VM_VALUE_I32 &&
                !(key->kind==PYZ80_VM_VALUE_BOOL && key->payload<=1u) &&
                !(key->kind==PYZ80_VM_VALUE_SYMBOL && key->symbol!=65535u)) return 0u;
        }
    } else if(node->kind==PYZ80_TARGET_NODE_DICT) {
        if(node->reserved!=1u || node->field_head || node->cursor>32767u || node->item_count!=node->cursor*2u ||
            node->item_count>node->source_link || node->item_start>objects->item_used ||
            node->source_link>objects->item_used-node->item_start) return 0u;
        count=node->item_count;
        for(item=0u;item<count;item+=2u) {
            const PyZ80VMValue *key=&objects->items[node->item_start+item];
            if(key->kind!=PYZ80_VM_VALUE_NONE && key->kind!=PYZ80_VM_VALUE_I32 &&
                !(key->kind==PYZ80_VM_VALUE_BOOL && key->payload<=1u) &&
                !(key->kind==PYZ80_VM_VALUE_SYMBOL && key->symbol!=65535u)) return 0u;
        }
    } else if (node->kind == PYZ80_TARGET_NODE_CALLABLE) {
        if (node->class_symbol >= objects->function_count || node->reserved > 3u) return 0u;
        if (node->reserved && !mark(objects, work, &node->current)) return 0u;
        if (node->reserved == 3u) {
            PyZ80VMValue reference, prototype, receiver;
            reference.kind = PYZ80_VM_VALUE_OPAQUE;
            reference.payload = ((uint32_t)node->generation << 16) | (index + 1u);
            if (!PyZ80Target_UnwrapCallable(objects, &reference, &prototype, &receiver) ||
                !mark(objects, work, &receiver)) return 0u;
        }
        if (node->reserved == 2u) {
            if (node->item_count > 254u || node->cursor > 254u ||
                node->item_count + node->cursor > 254u) return 0u;
            count = (node->item_count + node->cursor) * 2u; /* SHL.U16 capture/default pairs */
        }
    } else if(node->kind==PYZ80_TARGET_NODE_DICT_VIEW) {
        uint32_t length;
        PyZ80TargetNode *owner=PyZ80Target_Node(objects,&node->current);
        if(node->class_symbol>2u || !owner || (owner->kind!=PYZ80_TARGET_NODE_DICT && owner->kind!=PYZ80_TARGET_NODE_DEFAULTDICT) ||
            !PyZ80Target_Length(objects,&node->current,&length) || !mark(objects,work,&node->current)) return 0u;
    } else if(node->kind==PYZ80_TARGET_NODE_STATICMETHOD) {
        return !node->reserved && !node->item_count && !node->field_head && mark(objects,work,&node->current);
    } else if(node->kind==PYZ80_TARGET_NODE_NATIVE_METHOD) {
        if(!PyZ80Target_NativeMethodValid(objects,node) ||
            !mark(objects,work,&node->current)) return 0u;
    } else if (node->kind == PYZ80_TARGET_NODE_CELL) {
        if (node->has_current && !mark(objects, work, &node->current)) return 0u;
    } else if (node->kind == PYZ80_TARGET_NODE_ENUMERATE) {
        PyZ80VMValue source;
        PyZ80TargetNode *owner;
        source.kind=PYZ80_VM_VALUE_OPAQUE;
        source.payload=((uint32_t)node->source_generation<<16)|node->source_link;
        owner=PyZ80Target_Node(objects,&source);
        if(node->reserved>2u || !owner || (owner->kind!=PYZ80_TARGET_NODE_ITERATOR && owner->kind!=PYZ80_TARGET_NODE_ENUMERATE && owner->kind!=PYZ80_TARGET_NODE_DEQUE_ITERATOR) ||
            !mark(objects,work,&source) || (node->has_current && !mark(objects,work,&node->current))) return 0u;
    } else if (node->kind == PYZ80_TARGET_NODE_ITERATOR) {
        PyZ80VMValue source;
        uint8_t mode=(uint8_t)(node->item_start & 3u);
        if (!node->source_link || node->source_link > objects->node_used ||
            (objects->nodes[node->source_link - 1u].kind != PYZ80_TARGET_NODE_LIST &&
             objects->nodes[node->source_link - 1u].kind != PYZ80_TARGET_NODE_TUPLE &&
             objects->nodes[node->source_link - 1u].kind != PYZ80_TARGET_NODE_RANGE &&
             objects->nodes[node->source_link - 1u].kind != PYZ80_TARGET_NODE_DICT &&
             objects->nodes[node->source_link - 1u].kind != PYZ80_TARGET_NODE_DEFAULTDICT &&
             !PYZ80_IS_BUFFER(&objects->nodes[node->source_link-1u]))) return 0u;
        if((node->item_start & ~(PYZ80_TARGET_ITER_REVERSE|3u)) || mode>2u || node->reserved>1u ||
           (mode && objects->nodes[node->source_link-1u].kind!=PYZ80_TARGET_NODE_DICT && objects->nodes[node->source_link-1u].kind!=PYZ80_TARGET_NODE_DEFAULTDICT) ||
           ((node->item_start & PYZ80_TARGET_ITER_REVERSE) && node->cursor>node->item_count))return 0u;
        source.kind = PYZ80_VM_VALUE_OPAQUE;
        source.payload = ((uint32_t)node->source_generation << 16) | node->source_link;
        if (!mark(objects, work, &source) ||
            (node->has_current && !mark(objects, work, &node->current))) return 0u;
    } else if (node->kind == PYZ80_TARGET_NODE_CLASS) {
        PyZ80TargetNode *mapping = PyZ80Target_Node(objects, &node->current);
        PyZ80TargetNode *bases, *order;
        if (!mapping || mapping->kind != PYZ80_TARGET_NODE_OBJECT || !mark(objects, work, &node->current) ||
            node->reserved > 1u || node->item_count != 2u || node->item_start > objects->item_used ||
            2u > objects->item_used - node->item_start) return 0u;
        bases = PyZ80Target_Node(objects, &objects->items[node->item_start]);
        order = PyZ80Target_Node(objects, &objects->items[node->item_start + 1u]);
        if (!bases || bases->kind != PYZ80_TARGET_NODE_TUPLE || !bases->item_count ||
            (!node->reserved && (!order || order->kind != PYZ80_TARGET_NODE_TUPLE || !order->item_count)) ||
            (node->reserved && objects->items[node->item_start + 1u].kind != PYZ80_VM_VALUE_NONE)) return 0u;
        if (node->source_link) {
            PyZ80VMValue reference;
            reference.kind = PYZ80_VM_VALUE_CELL;
            reference.payload = ((uint32_t)node->source_generation << 16) | node->source_link;
            if (!mark(objects, work, &reference)) return 0u;
        }
        count = 2u;
    } else if (node->kind == PYZ80_TARGET_NODE_SUPER) {
        PyZ80VMValue anchor;
        PyZ80TargetNode *type;
        anchor.kind = PYZ80_VM_VALUE_OPAQUE;
        anchor.payload = ((uint32_t)node->source_generation << 16) | node->source_link;
        type = PyZ80Target_Node(objects, &anchor);
        if (!type || type->kind != PYZ80_TARGET_NODE_CLASS || type->reserved ||
            !mark(objects, work, &anchor) || !mark(objects, work, &node->current)) return 0u;
    } else if (node->kind == PYZ80_TARGET_NODE_RANGE) {
        if (node->current.kind != PYZ80_VM_VALUE_I32 ||
            !(node->item_start || node->item_count)) return 0u;
    } else return 0u;
    if (count && (node->item_start > objects->item_used || count > objects->item_used - node->item_start)) return 0u;
    for (item = 0u; item < count; ++item) {
        link = node->item_start + item; /* ADD.U16 bounded slice offset */
        if (work->item_map[link] != UNUSED) return 0u;
        work->item_map[link] = 0u;
        if (node->kind!=PYZ80_TARGET_NODE_BUFFER_BLOCK && !mark(objects, work, &objects->items[link])) return 0u;
    }
    return 1u;
}

uint8_t PyZ80Target_Collect(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetScopes *scopes, const PyZ80VMValue *roots, uint16_t root_count,
    PyZ80TargetGC *work)
{
    uint16_t index;
    uint16_t count;
    uint16_t next;
    if (objects == 0 || work == 0 || (root_count && roots == 0) ||
        objects->node_used > objects->node_capacity || objects->field_used > objects->field_capacity ||
        objects->item_used > objects->item_capacity ||
        work->node_capacity < objects->node_used || work->field_capacity < objects->field_used ||
        work->item_capacity < objects->item_used ||
        (objects->node_used && (objects->nodes == 0 || work->marked == 0 || work->queue == 0)) ||
        (objects->field_used && (objects->fields == 0 || work->field_map == 0)) ||
        (objects->item_used && (objects->items == 0 || work->item_map == 0))) return 0u;
    if (!PyZ80Target_TableStorageSeparate(objects,work,sizeof(*work)) ||
        !PyZ80Target_TableStorageSeparate(objects,work->marked,objects->node_used) ||
        !PyZ80Target_TableStorageSeparate(objects,work->queue,(uint32_t)objects->node_used*sizeof(*work->queue)) ||
        !PyZ80Target_TableStorageSeparate(objects,work->field_map,(uint32_t)objects->field_used*sizeof(*work->field_map)) ||
        !PyZ80Target_TableStorageSeparate(objects,work->item_map,(uint32_t)objects->item_used*sizeof(*work->item_map))) return 0u;
    work->queued = work->live_nodes = work->live_fields = work->live_items = 0u;
    for (index = 0u; index < objects->node_used; ++index) work->marked[index] = 0u;
    for (index = 0u; index < objects->field_used; ++index) work->field_map[index] = UNUSED;
    for (index = 0u; index < objects->item_used; ++index) work->item_map[index] = UNUSED;
    for (index = 0u; index < root_count; ++index)
        if (!mark(objects, work, &roots[index])) return 0u;
    if (vm != 0) {
        const PyZ80VMControlHooks *hooks = vm->control_hooks;
        uint16_t remaining = 255u;
        while (hooks) {
            if (!remaining-- || (hooks->root_count && !hooks->roots)) return 0u;
            for (index = 0u; index < hooks->root_count; ++index)
                if (!mark(objects, work, &hooks->roots[index])) return 0u;
            hooks = hooks->previous;
        }
        if (vm->adapter.context != objects || vm->adapter.invoke != PyZ80Target_Invoke ||
            vm->call_depth > vm->limits.max_call_depth ||
            (vm->call_depth && vm->frames == 0) ||
            (vm->limits.max_generators && vm->generators == 0) ||
            (vm->scope_hooks != 0 && (scopes == 0 || vm->scope_hooks != &scopes->hooks))) return 0u;
        if (!mark(objects, work, &vm->result)) return 0u;
        for (index = 0u; index < vm->call_depth; ++index)
            if (!mark_locals(objects, vm, work, index, vm->frames[index].local_count)) return 0u;
        for (index = 0u; index < vm->limits.max_generators; ++index)
            if (vm->generators[index].in_use) {
                PyZ80VMGenerator *generator = &vm->generators[index];
                if (generator->owner.kind != PYZ80_VM_VALUE_NONE) {
                    PyZ80TargetNode *owner = PyZ80Target_Node(objects,&generator->owner);
                    if (generator->owner.kind != PYZ80_VM_VALUE_OPAQUE || !owner ||
                        owner->kind != PYZ80_TARGET_NODE_GENERATOR || owner->reserved || owner->cursor != index ||
                        (generator->reserved && !mark(objects,work,&generator->owner))) return 0u;
                } else if (!generator->done && (!mark(objects, work, &generator->callable) ||
                    !mark_locals(objects, vm, work, vm->limits.max_call_depth + index,
                                 generator->local_count))) return 0u;
            }
    }
    if (scopes != 0) {
        if (vm == 0 || scopes->vm != vm || scopes->objects != objects ||
            vm->scope_hooks != &scopes->hooks || scopes->frame_capacity < vm->call_depth ||
            (vm->call_depth && scopes->frame_closures == 0) ||
            (scopes->function_count && scopes->function_globals == 0)) return 0u;
        for (index = 0u; index < scopes->function_count; ++index)
            if (!mark(objects, work, &scopes->function_globals[index])) return 0u;
        for (index = 0u; index < vm->call_depth; ++index)
            if (!mark(objects, work, &scopes->frame_closures[index])) return 0u;
    }
    for (index = 0u; index < work->queued; ++index)
        if (!trace_node(objects, vm, work, work->queue[index])) return 0u;
    /* Validation is complete. Assign dense field/item maps before any moves. */
    if (vm) for (index = 0u; index < vm->limits.max_generators; ++index) {
        PyZ80VMGenerator *generator = &vm->generators[index];
        if (generator->in_use && generator->owner.kind != PYZ80_VM_VALUE_NONE &&
            !work->marked[(uint16_t)generator->owner.payload - 1u])
            memset(generator,0,sizeof(*generator));
    }
    for (index = 0u; index < objects->field_used; ++index)
        if (work->field_map[index] != UNUSED) work->field_map[index] = work->live_fields++;
    for (index = 0u; index < objects->item_used; ++index)
        if (work->item_map[index] != UNUSED) work->item_map[index] = work->live_items++;
    for (index = 0u; index < objects->field_used; ++index) {
        if (work->field_map[index] == UNUSED) continue;
        next = objects->fields[index].next;
        objects->fields[index].next = next ? work->field_map[next - 1u] + 1u : 0u;
        objects->fields[work->field_map[index]] = objects->fields[index];
    }
    for (index = 0u; index < objects->item_used; ++index)
        if (work->item_map[index] != UNUSED) objects->items[work->item_map[index]] = objects->items[index];
    objects->free_node_head = 0u;
    for (index = objects->node_used; index != 0u;) {
        PyZ80TargetNode *node;
        --index; /* DEC.U16 builds ascending free chain without a second scan. */
        node = &objects->nodes[index];
        if (!work->marked[index]) {
            node->kind = PYZ80_TARGET_NODE_FREE;
            if (node->generation != 65535u) {
                node->field_head = objects->free_node_head;
                objects->free_node_head = index + 1u;
            }
            continue;
        }
        ++work->live_nodes;
        if ((node->kind == PYZ80_TARGET_NODE_OBJECT || node->kind == PYZ80_TARGET_NODE_INSTANCE || node->kind == PYZ80_TARGET_NODE_DICT ||
            node->kind == PYZ80_TARGET_NODE_CALLABLE) && node->field_head)
            node->field_head = work->field_map[node->field_head - 1u] + 1u;
        count = node->item_count;
        if (node->kind == PYZ80_TARGET_NODE_CALLABLE && node->reserved == 2u) count += node->cursor;
        if (node->kind == PYZ80_TARGET_NODE_LIST || node->kind == PYZ80_TARGET_NODE_TUPLE || node->kind==PYZ80_TARGET_NODE_SLICE || node->kind==PYZ80_TARGET_NODE_DEQUE_BLOCK || node->kind==PYZ80_TARGET_NODE_BUFFER_BLOCK || node->kind==PYZ80_TARGET_NODE_DEFAULTDICT || node->kind == PYZ80_TARGET_NODE_CLASS || node->kind==PYZ80_TARGET_NODE_SET ||
            (node->kind == PYZ80_TARGET_NODE_DICT && node->reserved==1u) ||
            (node->kind == PYZ80_TARGET_NODE_CALLABLE && node->reserved == 2u)) {
            node->item_start = count ? work->item_map[node->item_start] : 0u;
            if (node->kind == PYZ80_TARGET_NODE_LIST || node->kind==PYZ80_TARGET_NODE_SET) node->cursor = count;
            if (node->kind == PYZ80_TARGET_NODE_DICT) node->source_link=count;
        }
    }
    objects->field_used = work->live_fields;
    objects->item_used = work->live_items;
    return 1u;
}

uint8_t PyZ80Target_RunSlice(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetScopes *scopes, const PyZ80VMValue *roots, uint16_t root_count,
    PyZ80TargetGC *work, uint32_t step_budget, PyZ80VMValue *result)
{
    uint8_t status;
    if (vm == 0) return PYZ80_VM_ERROR;
    if (vm->status != PYZ80_VM_RUNNING) return vm->status;
    if (!PyZ80Target_Collect(objects, vm, scopes, roots, root_count, work)) {
        return PyZ80VM_Abort(vm, PYZ80_VM_E_HEAP_ROOTS);
    }
    status = PyZ80VM_Run(vm, step_budget, result);
    if (status != PYZ80_VM_ERROR &&
        !PyZ80Target_Collect(objects, vm, scopes, roots, root_count, work)) {
        return PyZ80VM_Abort(vm, PYZ80_VM_E_HEAP_ROOTS);
    }
    return status;
}
