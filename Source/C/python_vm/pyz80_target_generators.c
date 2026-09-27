#include <string.h>
#include "pyz80_target_generators.h"
#include "pyz80_target_deque.h"
#include "pyz80_target_buffers.h"

#define MODE_NEXT 1u
#define MODE_DEFAULT 2u
#define MODE_RECORD 3u
#define MODE_ANY 4u
#define MODE_TUPLE 5u
#define MODE_EXTEND 6u
#define MODE_EXTEND_SELF 7u
#define MODE_LIST 8u
#define MODE_CONTAINS 9u
#define MODE_NOT_CONTAINS 10u
#define MODE_DEQUE 11u
#define MODE_BYTES 12u
#define MODE_BYTEARRAY 13u
#define MODE_ZERO_BYTES 14u
#define MODE_ZERO_BYTEARRAY 15u

static void none(PyZ80VMValue *value)
{
    memset(value,0,sizeof(*value));value->symbol=PYZ80_VM_NO_SYMBOL;
}

static uint8_t overlap(const void *a,uint32_t an,const void *b,uint32_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(!a || !b || !an || !bn)return 0u;
    return x<=y ? y-x<an : x-y<bn;
}

uint8_t PyZ80Target_ControlStorageSeparate(PyZ80TargetScopes *s,const void *buffer,uint32_t bytes)
{
    PyZ80TargetContext *o=s->objects;
    const PyZ80VMControlHooks *h=s->vm->control_hooks;
    uint16_t remaining=255u;
    if(!PyZ80Target_TableStorageSeparate(o,buffer,bytes) ||
       overlap(buffer,bytes,s,sizeof(*s)) || overlap(buffer,bytes,o,sizeof(*o)) ||
       overlap(buffer,bytes,s->vm,sizeof(*s->vm)) ||
       overlap(buffer,bytes,s->vm->frames,PyZ80VM_ArenaBytes(&s->vm->limits)) ||
       overlap(buffer,bytes,o->nodes,(uint32_t)o->node_capacity*sizeof(*o->nodes)) ||
       overlap(buffer,bytes,o->fields,(uint32_t)o->field_capacity*sizeof(*o->fields)) ||
       overlap(buffer,bytes,o->items,(uint32_t)o->item_capacity*sizeof(*o->items)) ||
       overlap(buffer,bytes,s->frame_closures,(uint32_t)s->frame_capacity*sizeof(*s->frame_closures)) ||
       overlap(buffer,bytes,s->function_globals,(uint32_t)s->function_count*sizeof(*s->function_globals)) ||
       overlap(buffer,bytes,s->binding_scratch,(uint32_t)s->binding_capacity*sizeof(*s->binding_scratch)))return 0u;
    while(h) {
        if(!remaining-- || overlap(buffer,bytes,h,sizeof(*h)) ||
           overlap(buffer,bytes,h->roots,(uint32_t)h->root_count*sizeof(*h->roots)) ||
           overlap(buffer,bytes,h->routes,(uint32_t)s->vm->header.adapter_count*sizeof(*h->routes)))return 0u;
        h=h->previous;
    }
    return 1u;
}

static uint8_t delegate(PyZ80TargetGenerators *g,PyZ80VM *vm,uint16_t adapter,
    const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result,uint16_t *function)
{
    const PyZ80VMControlHooks *h=g->hooks.previous;
    return h && h->dispatch && (!h->routes || h->routes[adapter]!=PYZ80_VM_NO_SYMBOL) ?
        h->dispatch(h->context,vm,adapter,args,count,result,function) : 0u;
}

static uint8_t done(PyZ80TargetGeneratorRequest *f,PyZ80VMValue *roots,
    const PyZ80VMValue *value,PyZ80VMValue *result)
{
    *result=*value;memset(f,0,sizeof(*f));
    none(&roots[0]);none(&roots[1]);none(&roots[2]);return 1u;
}

static uint8_t iterator(PyZ80TargetContext *o,const PyZ80VMValue *value,PyZ80VMValue *result)
{
    PyZ80TargetNode *node=PyZ80Target_Node(o,value);
    if(node && node->kind==PYZ80_TARGET_NODE_GENERATOR) { *result=*value;return 1u; }
    return PyZ80Target_GetIterator(o,value,result);
}

static uint8_t factory(PyZ80TargetGenerators *g,PyZ80VM *vm,uint16_t adapter,
    const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result)
{
    PyZ80TargetContext *o=g->scopes->objects;
    PyZ80VMValue callable=args[0];
    PyZ80TargetNode *node;
    uint16_t function,handle;
    if(PyZ80Target_PrepareGeneratorCall(g->scopes,adapter,vm->argument_scratch,&count,&function)!=1u)return 3u;
    if(PyZ80VM_GeneratorCreateArgs(vm,function,&callable,vm->argument_scratch,count,&handle)!=PYZ80_VM_IDLE)return 3u;
    if(!PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_GENERATOR,PYZ80_VM_NO_SYMBOL,result)) {
        PyZ80VM_GeneratorClose(vm,handle);return 3u;
    }
    node=PyZ80Target_Node(o,result);node->cursor=handle;
    vm->generators[handle].owner=*result;
    return 1u;
}

static uint8_t dispatch(void *raw,PyZ80VM *vm,uint16_t adapter,
    const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result,uint16_t *function)
{
    PyZ80TargetGenerators *g=raw;
    PyZ80TargetContext *o=g->scopes->objects;
    PyZ80TargetGeneratorRequest *f;
    PyZ80VMValue *roots,prototype,receiver,value;
    PyZ80TargetNode *node;
    PyZ80TargetAdapterSpec spec;
    uint8_t flags,truth,comparison,operation=0u;
    uint16_t handle;
    if(vm!=g->scopes->vm || !vm->call_depth || vm->call_depth>g->capacity ||
       !PyZ80Target_ReadAdapter(o,adapter,&spec))return 3u;
    f=&g->frames[vm->call_depth-1u];
    roots=&g->roots[(uint16_t)(vm->call_depth-1u)*3u];
    if(f->state) {
        if(f->adapter!=adapter || f->pc!=vm->frames[vm->call_depth-1u].pc || f->state==1u)return 3u;
    } else {
        if(spec.operation==PYZ80_TARGET_COMPARE && count==3u &&
           PyZ80Target_Operator(o,&args[0],&comparison) &&
           (comparison==PYZ80_TARGET_OP_IN || comparison==PYZ80_TARGET_OP_NOT_IN)) {
            node=PyZ80Target_Node(o,&args[2]);
            /* Dict/set сохраняют свой поиск ключей. Не подменяем __contains__
               исходных классов перебором и не угадываем равенство объектов. */
            if(node && (node->kind==PYZ80_TARGET_NODE_LIST || node->kind==PYZ80_TARGET_NODE_TUPLE ||
               node->kind==PYZ80_TARGET_NODE_RANGE || node->kind==PYZ80_TARGET_NODE_DICT_VIEW ||
               node->kind==PYZ80_TARGET_NODE_ITERATOR || node->kind==PYZ80_TARGET_NODE_ENUMERATE ||
               node->kind==PYZ80_TARGET_NODE_GENERATOR || node->kind==PYZ80_TARGET_NODE_DEQUE || node->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR)) {
                operation=comparison==PYZ80_TARGET_OP_IN ? MODE_CONTAINS : MODE_NOT_CONTAINS;
                roots[1]=args[1];
            }
        }
        if(spec.operation==PYZ80_TARGET_UNSUPPORTED && count &&
           PyZ80Target_UnwrapCallable(o,&args[0],&prototype,&receiver)) {
            node=PyZ80Target_Node(o,&prototype);
            if(node->has_current==1u)return factory(g,vm,adapter,args,count,result);
        }
        if(count==1u && (node=PyZ80Target_Node(o,args)) && node->kind==PYZ80_TARGET_NODE_GENERATOR) {
            if(spec.operation==PYZ80_TARGET_GET_ITERATOR) { *result=args[0];return 1u; }
            if(spec.operation==PYZ80_TARGET_ITER_HAS_VALUE) {
                none(result);result->kind=PYZ80_VM_VALUE_BOOL;result->payload=node->has_current;return 1u;
            }
            if(spec.operation==PYZ80_TARGET_ITER_VALUE) {
                if(!node->has_current)return 3u;
                *result=node->current;return 1u;
            }
            if(spec.operation==PYZ80_TARGET_ITER_NEXT)operation=MODE_RECORD;
        }
        if(!operation && spec.operation==PYZ80_TARGET_UNSUPPORTED && count &&
           (node=PyZ80Target_Node(o,args)) && node->kind==PYZ80_TARGET_NODE_NATIVE_METHOD &&
           node->class_symbol==PYZ80_BUILTIN_LIST_EXTEND) {
            if(!PyZ80Target_NativeMethodValid(o,node) || count!=2u ||
               !PyZ80Target_ReadByte(o,PYZ80_TABLE_CALL_FLAGS,adapter,&flags) || !flags)return 3u;
            roots[1]=node->current;
            operation=args[1].kind==roots[1].kind && args[1].payload==roots[1].payload ?
                MODE_EXTEND_SELF : MODE_EXTEND;
        }
        if(!operation && spec.operation==PYZ80_TARGET_UNSUPPORTED && count && args[0].kind==PYZ80_VM_VALUE_BUILTIN &&
           ((args[0].payload>=PYZ80_BUILTIN_NEXT && args[0].payload<=PYZ80_BUILTIN_TUPLE) ||
            args[0].payload==PYZ80_BUILTIN_LIST || args[0].payload==PYZ80_BUILTIN_DEQUE ||
            args[0].payload==PYZ80_BUILTIN_BYTES || args[0].payload==PYZ80_BUILTIN_BYTEARRAY)) {
            if(!PyZ80Target_Truth(o,vm,&args[0],&truth) ||
               !PyZ80Target_ReadByte(o,PYZ80_TABLE_CALL_FLAGS,adapter,&flags) || !flags)return 3u;
            if(args[0].payload==PYZ80_BUILTIN_ITER)
                return count==2u && iterator(o,&args[1],result) ? 1u : 3u;
            if(args[0].payload==PYZ80_BUILTIN_NEXT) {
                if(count!=2u && count!=3u)return 3u;
                operation=count==3u ? MODE_DEFAULT : MODE_NEXT;
            } else if(args[0].payload==PYZ80_BUILTIN_ANY) {
                if(count!=2u)return 3u;
                operation=MODE_ANY;
            } else {
                if(count>2u)return 3u;
                operation=args[0].payload==PYZ80_BUILTIN_BYTES ? MODE_BYTES :
                    (args[0].payload==PYZ80_BUILTIN_BYTEARRAY ? MODE_BYTEARRAY :
                    (args[0].payload==PYZ80_BUILTIN_DEQUE ? MODE_DEQUE :
                    (args[0].payload==PYZ80_BUILTIN_LIST ? MODE_LIST : MODE_TUPLE)));
                if(operation==MODE_BYTES && count==2u && (node=PyZ80Target_Node(o,&args[1])) && node->kind==PYZ80_TARGET_NODE_BYTES)
                    return PyZ80Target_BufferValid(o,node) ? (*result=args[1],1u) : 3u;
                if(operation==MODE_BYTES || operation==MODE_BYTEARRAY) {
                    if(!PyZ80Target_EmptyBuffer(o,&roots[1]))return 3u;
                    if(count==1u) {
                        if(operation==MODE_BYTES && !PyZ80Target_BufferFreeze(o,&roots[1]))return 3u;
                        return done(f,roots,&roots[1],result);
                    }
                    if(args[1].kind==PYZ80_VM_VALUE_I32 || args[1].kind==PYZ80_VM_VALUE_BOOL) {
                        if(args[1].payload>65535u || (args[1].kind==PYZ80_VM_VALUE_BOOL && args[1].payload>1u))return 3u;
                        roots[0]=args[1];f->mode=operation==MODE_BYTES ? MODE_ZERO_BYTES : MODE_ZERO_BYTEARRAY;
                        f->state=3u;f->adapter=adapter;f->pc=vm->frames[vm->call_depth-1u].pc;
                        return 6u;
                    }
                }
                if(operation==MODE_TUPLE && count==2u &&
                   (node=PyZ80Target_Node(o,&args[1])) && node->kind==PYZ80_TARGET_NODE_TUPLE) {
                    *result=args[1];return 1u;
                }
                if(operation!=MODE_BYTES && operation!=MODE_BYTEARRAY &&
                   !(operation==MODE_DEQUE ? PyZ80Target_EmptyDeque(o,&roots[1]) : PyZ80Target_EmptyList(o,&roots[1])))return 3u;
                if(count==1u) {
                    if(operation==MODE_TUPLE)PyZ80Target_Node(o,&roots[1])->kind=PYZ80_TARGET_NODE_TUPLE;
                    return done(f,roots,&roots[1],result);
                }
            }
        }
        if(!operation)return delegate(g,vm,adapter,args,count,result,function);
        if(operation==MODE_RECORD)roots[0]=args[0];
        else if(operation==MODE_NEXT || operation==MODE_DEFAULT)roots[0]=args[1];
        else if(!iterator(o,&args[operation==MODE_CONTAINS || operation==MODE_NOT_CONTAINS ? 2u : 1u],&roots[0]))return 3u;
        node=PyZ80Target_Node(o,&roots[0]);
        if(!node || (node->kind!=PYZ80_TARGET_NODE_GENERATOR && node->kind!=PYZ80_TARGET_NODE_ITERATOR && node->kind!=PYZ80_TARGET_NODE_ENUMERATE && node->kind!=PYZ80_TARGET_NODE_DEQUE_ITERATOR))return 3u;
        f->mode=operation;f->state=3u;f->adapter=adapter;f->pc=vm->frames[vm->call_depth-1u].pc;
    }
    if(f->mode==MODE_ZERO_BYTES || f->mode==MODE_ZERO_BYTEARRAY) {
        if(roots[0].payload) {
            none(&value);value.kind=PYZ80_VM_VALUE_I32;
            if(!PyZ80Target_BufferAppend(o,&roots[1],&value))return 3u;
            --roots[0].payload;return 6u; /* DEC.U32: один нулевой байт за шаг VM. */
        }
        if(f->mode==MODE_ZERO_BYTES && !PyZ80Target_BufferFreeze(o,&roots[1]))return 3u;
        return done(f,roots,&roots[1],result);
    }
    node=PyZ80Target_Node(o,&roots[0]);
    if(!node)return 3u;
    if(f->state==3u) {
        if(node->kind==PYZ80_TARGET_NODE_GENERATOR && !node->reserved) {
            handle=node->cursor;
            if(handle>=vm->limits.max_generators || !vm->generators[handle].in_use ||
               vm->generators[handle].owner.payload!=roots[0].payload)return 3u;
            if(!vm->generators[handle].done) {
                f->state=1u;*function=handle;return 5u;
            }
            f->has_value=0u;
        } else if(node->kind==PYZ80_TARGET_NODE_ITERATOR || node->kind==PYZ80_TARGET_NODE_ENUMERATE || node->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR) {
            /* Только a.extend(a) ограничен исходной длиной списка. Для iter(a)
               рост источника виден итератору, как в Python. Без копии списка. */
            if(f->mode==MODE_EXTEND_SELF && node->cursor>=node->item_count)f->has_value=0u;
            else {
                if(!PyZ80Target_IterNext(o,&roots[0],&value))return 3u;
                f->has_value=node->has_current;roots[2]=node->current;
            }
        } else if(node->kind==PYZ80_TARGET_NODE_GENERATOR && node->reserved==1u)f->has_value=0u;
        else return 3u;
        f->state=2u;
    }
    if(node->kind==PYZ80_TARGET_NODE_GENERATOR) {
        node->has_current=f->has_value;
        if(f->has_value)node->current=roots[2];
        else {
            none(&node->current);
            if(!node->reserved) {
                handle=node->cursor;
                if(PyZ80VM_GeneratorClose(vm,handle)!=PYZ80_VM_IDLE)return 3u;
                node->reserved=1u;node->cursor=65535u;
            }
        }
    }
    if(f->mode==MODE_RECORD)return done(f,roots,&roots[0],result);
    if(f->mode==MODE_NEXT || f->mode==MODE_DEFAULT) {
        if(f->has_value)return done(f,roots,&roots[2],result);
        if(f->mode==MODE_DEFAULT)return done(f,roots,&args[2],result);
        return 3u; /* StopIteration без обработчика: явная остановка VM. */
    }
    if(f->mode==MODE_CONTAINS || f->mode==MODE_NOT_CONTAINS) {
        truth=0u;
        if(f->has_value && !PyZ80Target_ContainerItemEqual(o,&roots[2],&roots[1],&truth))return 3u;
        if(!f->has_value || truth) {
            none(&value);value.kind=PYZ80_VM_VALUE_BOOL;
            value.payload=f->mode==MODE_CONTAINS ? truth : !truth;
            return done(f,roots,&value,result);
        }
    } else if(f->mode==MODE_ANY) {
        truth=0u;
        if(f->has_value && !PyZ80VM_Truth(vm,&roots[2],&truth))return 3u;
        if(!f->has_value || truth) {
            none(&value);value.kind=PYZ80_VM_VALUE_BOOL;value.payload=truth;
            return done(f,roots,&value,result);
        }
    } else {
        if(!f->has_value) {
            if(f->mode==MODE_EXTEND || f->mode==MODE_EXTEND_SELF) {
                none(&value);return done(f,roots,&value,result);
            }
            if(f->mode==MODE_TUPLE)PyZ80Target_Node(o,&roots[1])->kind=PYZ80_TARGET_NODE_TUPLE;
            if(f->mode==MODE_BYTES && !PyZ80Target_BufferFreeze(o,&roots[1]))return 3u;
            return done(f,roots,&roots[1],result);
        }
        if(!((f->mode==MODE_BYTES || f->mode==MODE_BYTEARRAY) ? PyZ80Target_BufferAppend(o,&roots[1],&roots[2]) :
            (f->mode==MODE_DEQUE ? PyZ80Target_DequeAppend(o,&roots[1],&roots[2]) :
             PyZ80Target_ListAppend(o,&roots[1],&roots[2]))))return 3u;
    }
    none(&roots[2]);f->state=3u;
    return 6u; /* Один элемент на шаг, чтобы сохранить предел step_budget. */
}

static uint8_t event(void *raw,PyZ80VM *vm,uint16_t handle,uint8_t yielded,const PyZ80VMValue *value)
{
    PyZ80TargetGenerators *g=raw;
    PyZ80TargetGeneratorRequest *f;
    PyZ80VMValue *roots;
    PyZ80TargetNode *node;
    if(vm!=g->scopes->vm || vm->call_depth>g->capacity)return 2u;
    if(vm->call_depth<2u)return 0u;
    f=&g->frames[vm->call_depth-2u];roots=&g->roots[(uint16_t)(vm->call_depth-2u)*3u];
    if(!f->state)return 0u;
    node=PyZ80Target_Node(g->scopes->objects,&roots[0]);
    if(f->state!=1u || !node || node->kind!=PYZ80_TARGET_NODE_GENERATOR || node->cursor!=handle)return 2u;
    roots[2]=*value;f->has_value=yielded;f->state=2u;return 1u;
}

static uint8_t returned(void *raw,PyZ80VM *vm)
{
    const PyZ80VMControlHooks *h=((PyZ80TargetGenerators *)raw)->hooks.previous;
    return h && h->returned ? h->returned(h->context,vm) : 0u;
}

static uint8_t prepare_call(void *raw,PyZ80VM *vm,PyZ80VMValue *callable,
    PyZ80VMValue *args,uint8_t *count,uint16_t *function)
{
    const PyZ80VMControlHooks *h=((PyZ80TargetGenerators *)raw)->hooks.previous;
    return h && h->prepare_call ? h->prepare_call(h->context,vm,callable,args,count,function) : 0u;
}

static void failed(void *raw,PyZ80VM *vm)
{
    PyZ80TargetGenerators *g=raw;
    const PyZ80VMControlHooks *h=g->hooks.previous;
    memset(g->frames,0,(uint16_t)g->capacity*sizeof(*g->frames));
    memset(g->roots,0,(uint16_t)g->capacity*3u*sizeof(*g->roots));
    if(h && h->failed)h->failed(h->context,vm);
}

uint8_t PyZ80Target_AttachGenerators(PyZ80TargetGenerators *g,PyZ80TargetScopes *s,
    PyZ80TargetGeneratorRequest *frames,PyZ80VMValue *roots,uint8_t capacity,uint16_t *routes)
{
    uint32_t fb=(uint32_t)capacity*sizeof(*frames),rb=(uint32_t)capacity*3u*sizeof(*roots),tb;
    uint16_t index;
    PyZ80TargetAdapterSpec spec;
    PyZ80VM *vm;
    const PyZ80VMControlHooks *previous;
    if(!g || !s || !s->objects || !s->vm || !frames || !roots || !routes)return 0u;
    vm=s->vm;previous=vm->control_hooks;tb=(uint32_t)vm->header.adapter_count*sizeof(*routes);
    if(vm->status!=PYZ80_VM_IDLE || vm->scope_hooks!=&s->hooks || !s->hooks.prepare ||
       !vm->limits.max_generators || capacity<vm->limits.max_call_depth ||
       !PyZ80Target_ControlStorageSeparate(s,g,sizeof(*g)) || !PyZ80Target_ControlStorageSeparate(s,frames,fb) ||
       !PyZ80Target_ControlStorageSeparate(s,roots,rb) || !PyZ80Target_ControlStorageSeparate(s,routes,tb) ||
       overlap(g,sizeof(*g),frames,fb) || overlap(g,sizeof(*g),roots,rb) || overlap(g,sizeof(*g),routes,tb) ||
       overlap(frames,fb,roots,rb) || overlap(frames,fb,routes,tb) || overlap(roots,rb,routes,tb))return 0u;
    for(index=0u;index<vm->header.adapter_count;++index) {
        if(!PyZ80Target_ReadAdapter(s->objects,index,&spec))return 0u;
        routes[index]=(spec.operation==PYZ80_TARGET_UNSUPPORTED || spec.operation==PYZ80_TARGET_COMPARE ||
            (spec.operation>=PYZ80_TARGET_GET_ITERATOR && spec.operation<=PYZ80_TARGET_ITER_VALUE) ||
            (previous && previous->dispatch && (!previous->routes || previous->routes[index]!=PYZ80_VM_NO_SYMBOL))) ? 0u : PYZ80_VM_NO_SYMBOL;
    }
    memset(g,0,sizeof(*g));memset(frames,0,fb);memset(roots,0,rb);
    g->scopes=s;g->frames=frames;g->roots=roots;g->capacity=capacity;
    g->hooks.previous=previous;g->hooks.context=g;g->hooks.routes=routes;
    g->hooks.roots=roots;g->hooks.root_count=(uint16_t)capacity*3u;
    g->hooks.dispatch=dispatch;g->hooks.generator_event=event;g->hooks.returned=returned;
    g->hooks.failed=failed;g->hooks.prepare_call=prepare_call;
    vm->control_hooks=&g->hooks;return 1u;
}
