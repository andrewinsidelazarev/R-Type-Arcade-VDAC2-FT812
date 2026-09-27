#include <string.h>
#include "pyz80_target_type_checks.h"

#define TYPE_CHECK 3u

static uint8_t builtin_type(PyZ80TargetContext *o,const PyZ80VMValue *v)
{
    uint8_t truth;
    if(v->kind!=PYZ80_VM_VALUE_BUILTIN || !PyZ80Target_Truth(o,0,v,&truth))return 0u;
    switch(v->payload) {
    case PYZ80_BUILTIN_OBJECT: case PYZ80_BUILTIN_BOOL: case PYZ80_BUILTIN_INT:
    case PYZ80_BUILTIN_STR: case PYZ80_BUILTIN_LIST: case PYZ80_BUILTIN_TUPLE:
    case PYZ80_BUILTIN_DICT: case PYZ80_BUILTIN_SET: case PYZ80_BUILTIN_FROZENSET:
    case PYZ80_BUILTIN_RANGE: case PYZ80_BUILTIN_ENUMERATE: case PYZ80_BUILTIN_DEQUE: case PYZ80_BUILTIN_DEFAULTDICT:
    case PYZ80_BUILTIN_BYTES: case PYZ80_BUILTIN_BYTEARRAY: case PYZ80_BUILTIN_STATICMETHOD: return (uint8_t)v->payload;
    default: return 0u;
    }
}

static PyZ80TargetNode *tuple(PyZ80TargetContext *o,const PyZ80VMValue *v)
{
    uint32_t length;
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);
    return n && n->kind==PYZ80_TARGET_NODE_TUPLE && PyZ80Target_Length(o,v,&length) ? n : 0;
}

/* Проверяем сохранённый MRO, но не строим его заново и не копируем классы. */
static PyZ80TargetNode *mro(PyZ80TargetContext *o,const PyZ80VMValue *v)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v),*order,*base;
    const PyZ80VMValue *item;
    uint16_t i;
    if(!n || n->kind!=PYZ80_TARGET_NODE_CLASS || n->reserved || n->item_count!=2u ||
       o->item_used>o->item_capacity || n->item_start>o->item_used ||
       2u>o->item_used-n->item_start || !o->items)return 0;
    order=tuple(o,&o->items[n->item_start+1u]);
    if(!order || order->item_count<2u || o->items[order->item_start].kind!=v->kind ||
       o->items[order->item_start].payload!=v->payload)return 0;
    for(i=0u;i<order->item_count;++i) {
        item=&o->items[order->item_start+i];
        if(i==order->item_count-1u) {
            if(builtin_type(o,item)!=PYZ80_BUILTIN_OBJECT)return 0;
        } else {
            base=PyZ80Target_Node(o,item);
            if(!base || base->kind!=PYZ80_TARGET_NODE_CLASS || base->reserved)return 0;
        }
    }
    return order;
}

static uint8_t instance_type(PyZ80TargetContext *o,PyZ80VM *vm,const PyZ80VMValue *v,
    uint8_t *native,PyZ80TargetNode **order)
{
    PyZ80TargetNode *n;
    uint32_t length;
    uint8_t truth;
    *native=0u;*order=0;
    switch(v->kind) {
    case PYZ80_VM_VALUE_NONE: return 1u;
    case PYZ80_VM_VALUE_BOOL: *native=PYZ80_BUILTIN_BOOL;return v->payload<=1u;
    case PYZ80_VM_VALUE_I32: *native=PYZ80_BUILTIN_INT;return 1u;
    case PYZ80_VM_VALUE_SYMBOL: *native=PYZ80_BUILTIN_STR;return PyZ80VM_StringLength(vm,v,&length);
    case PYZ80_VM_VALUE_BUILTIN: return PyZ80Target_Truth(o,vm,v,&truth);
    case PYZ80_VM_VALUE_OPAQUE: break;
    default: return 0u; /* CELL и неразобранные serialized-значения не угадываются. */
    }
    n=PyZ80Target_Node(o,v);
    if(!n || n->kind==PYZ80_TARGET_NODE_CELL || n->kind==PYZ80_TARGET_NODE_DEQUE_BLOCK || n->kind==PYZ80_TARGET_NODE_BUFFER_BLOCK || n->kind>PYZ80_TARGET_NODE_STATICMETHOD)return 0u;
    switch(n->kind) {
    case PYZ80_TARGET_NODE_INSTANCE:
        *native=builtin_type(o,&n->current);
        if(*native)return *native==PYZ80_BUILTIN_OBJECT;
        *order=mro(o,&n->current);return *order!=0;
    case PYZ80_TARGET_NODE_CLASS: return mro(o,v)!=0;
    case PYZ80_TARGET_NODE_LIST: *native=PYZ80_BUILTIN_LIST;break;
    case PYZ80_TARGET_NODE_DEQUE: *native=PYZ80_BUILTIN_DEQUE;break;
    case PYZ80_TARGET_NODE_TUPLE: *native=PYZ80_BUILTIN_TUPLE;break;
    case PYZ80_TARGET_NODE_DICT: *native=PYZ80_BUILTIN_DICT;break;
    case PYZ80_TARGET_NODE_DEFAULTDICT: *native=PYZ80_BUILTIN_DEFAULTDICT;break;
    case PYZ80_TARGET_NODE_BYTES: *native=PYZ80_BUILTIN_BYTES;break;
    case PYZ80_TARGET_NODE_BYTEARRAY: *native=PYZ80_BUILTIN_BYTEARRAY;break;
    case PYZ80_TARGET_NODE_STATICMETHOD: *native=PYZ80_BUILTIN_STATICMETHOD;return !n->reserved && !n->item_count && !n->field_head;
    case PYZ80_TARGET_NODE_SET: *native=n->reserved ? PYZ80_BUILTIN_FROZENSET : PYZ80_BUILTIN_SET;break;
    case PYZ80_TARGET_NODE_RANGE: *native=PYZ80_BUILTIN_RANGE;break;
    case PYZ80_TARGET_NODE_ENUMERATE: *native=PYZ80_BUILTIN_ENUMERATE;return 1u;
    default: return 1u; /* Остальные известные native-объекты наследуются только от object. */
    }
    return PyZ80Target_Length(o,v,&length);
}

static uint8_t leaf(PyZ80TargetContext *o,PyZ80VM *vm,const PyZ80VMValue *value,
    const PyZ80VMValue *info,uint8_t subclass,uint8_t *truth)
{
    uint8_t wanted=builtin_type(o,info),actual;
    uint16_t i;
    PyZ80TargetNode *order;
    const PyZ80VMValue *entry;
    if(!wanted && !mro(o,info))return 0u;
    if(subclass) {
        actual=builtin_type(o,value);order=actual ? 0 : mro(o,value);
        if(!actual && !order)return 0u;
    } else if(!instance_type(o,vm,value,&actual,&order))return 0u;
    *truth=0u;
    if(wanted) {
        *truth=wanted==PYZ80_BUILTIN_OBJECT || wanted==actual ||
            (wanted==PYZ80_BUILTIN_INT && actual==PYZ80_BUILTIN_BOOL) ||
            (wanted==PYZ80_BUILTIN_DICT && actual==PYZ80_BUILTIN_DEFAULTDICT);
    } else if(order) {
        for(i=0u;i<order->item_count;++i) {
            entry=&o->items[order->item_start+i];
            if(entry->kind==info->kind && entry->payload==info->payload) { *truth=1u;break; }
        }
    }
    return 1u;
}

void PyZ80Target_TypeCheckClear(PyZ80TargetClasses *c,uint8_t depth)
{
    PyZ80TargetClassFrame *f;
    if(!c || !c->scopes || !c->frames || !c->roots || depth>=c->capacity)return;
    f=&c->frames[depth];
    if(f->operation!=TYPE_CHECK)return;
    if(c->scopes->binding_scratch)
        memset(c->scopes->binding_scratch,0,(uint16_t)c->scopes->binding_capacity*sizeof(PyZ80VMValue));
    memset(f,0,sizeof(*f));memset(&c->roots[depth],0,sizeof(PyZ80VMValue));
}

uint8_t PyZ80Target_TypeCheck(PyZ80TargetClasses *c,PyZ80VM *vm,uint16_t adapter,
    const PyZ80VMValue *args,PyZ80VMValue *result)
{
    PyZ80TargetScopes *s;
    PyZ80TargetContext *o;
    uint8_t depth,truth;
    PyZ80TargetClassFrame *f;
    PyZ80VMValue candidate,*stack;
    PyZ80TargetNode *node;
    if(!c || !vm || !args || !result || !c->frames || !c->roots ||
       !(s=c->scopes) || !(o=s->objects) || s->vm!=vm || !vm->call_depth ||
       vm->call_depth>c->capacity || !vm->frames)return 3u;
    depth=vm->call_depth-1u;f=&c->frames[depth];stack=s->binding_scratch;
    if(!f->operation) {
        /* Одиночный тип не использует рабочий стек или продолжение. */
        node=PyZ80Target_Node(o,&args[2]);
        if(!node || node->kind!=PYZ80_TARGET_NODE_TUPLE) {
            if(!leaf(o,vm,&args[1],&args[2],args[0].payload==PYZ80_BUILTIN_ISSUBCLASS,&truth))return 3u;
            memset(result,0,sizeof(*result));result->kind=PYZ80_VM_VALUE_BOOL;result->payload=truth;return 1u;
        }
        if(!stack || !s->binding_capacity || !s->hooks.prepare)return 3u;
        f->operation=TYPE_CHECK;f->adapter=adapter;f->pc=vm->frames[depth].pc;
        c->roots[depth]=args[2];candidate=args[2];
    } else {
        if(f->operation!=TYPE_CHECK || f->adapter!=adapter || f->pc!=vm->frames[depth].pc ||
           !stack || !f->phase || f->phase>s->binding_capacity)return 3u;
        node=tuple(o,&stack[f->phase-1u]);if(!node)return 3u;
        if(stack[f->phase-1u].symbol>node->item_count)return 3u;
        if(stack[f->phase-1u].symbol==node->item_count) {
            memset(&stack[--f->phase],0,sizeof(PyZ80VMValue)); /* DEC.U8: снять один завершённый кортеж. */
            if(f->phase)return 6u;
            truth=0u;goto finished;
        }
        candidate=o->items[node->item_start+stack[f->phase-1u].symbol++];
    }
    node=PyZ80Target_Node(o,&candidate);
    if(node && node->kind==PYZ80_TARGET_NODE_TUPLE) {
        if(!tuple(o,&candidate) || f->phase>=s->binding_capacity)return 3u;
        stack[f->phase]=candidate;
        stack[f->phase++].symbol=0u; /* INC.U8: push; symbol хранит курсор только в приватном scratch. */
        return 6u;
    }
    if(!leaf(o,vm,&args[1],&candidate,args[0].payload==PYZ80_BUILTIN_ISSUBCLASS,&truth))return 3u;
    if(!truth)return 6u;
finished:
    PyZ80Target_TypeCheckClear(c,depth);
    memset(result,0,sizeof(*result));result->kind=PYZ80_VM_VALUE_BOOL;result->payload=truth;return 1u;
}
