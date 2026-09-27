#include <string.h>
#include "pyz80_target_defaultdict.h"
#include "pyz80_target_deque.h"

#define COPY_MAPPING 1u
#define COPY_KEYWORDS 2u
#define WAIT_FACTORY 3u
#define STORE_RESULT 4u

static void none(PyZ80VMValue *v) { memset(v,0,sizeof(*v));v->symbol=65535u; }

static uint8_t callable(PyZ80TargetContext *o,const PyZ80VMValue *v)
{
    PyZ80VMValue prototype,receiver;
    PyZ80TargetNode *n;
    uint8_t truth;
    if(v->kind==PYZ80_VM_VALUE_BUILTIN)return PyZ80Target_Truth(o,0,v,&truth);
    n=PyZ80Target_Node(o,v);
    if(n && n->kind==PYZ80_TARGET_NODE_NATIVE_METHOD)return PyZ80Target_NativeMethodValid(o,n);
    if(n && n->kind==PYZ80_TARGET_NODE_CLASS)return !n->reserved;
    return PyZ80Target_UnwrapCallable(o,v,&prototype,&receiver);
}

/* Только точные вызовы без аргументов. Прочие callable требуют своего
   протокола; незнакомый тип не превращается в пустой список или ноль.
   tuple() пока запрещён: новый пустой узел нарушил бы идентичность
   единственного пустого tuple закреплённого CPython. */
static uint8_t empty_native(PyZ80TargetContext *o,const PyZ80VMValue *factory,PyZ80VMValue *result)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,factory);
    uint8_t op,truth;
    none(result);
    if(n && n->kind==PYZ80_TARGET_NODE_NATIVE_METHOD) {
        if(!PyZ80Target_NativeMethodValid(o,n))return 0u;
        switch(n->class_symbol) {
        case PYZ80_BUILTIN_LIST_CLEAR: return PyZ80Target_ListClear(o,&n->current);
        case PYZ80_BUILTIN_LIST_POP: return PyZ80Target_ListPop(o,&n->current,0,result);
        case PYZ80_BUILTIN_DICT_CLEAR: return PyZ80Target_DictClear(o,&n->current);
        case PYZ80_BUILTIN_SET_CLEAR: return PyZ80Target_SetClear(o,&n->current);
        case PYZ80_BUILTIN_DEQUE_CLEAR: return PyZ80Target_DequeClear(o,&n->current);
        case PYZ80_BUILTIN_DEQUE_POPLEFT: return PyZ80Target_DequePopleft(o,&n->current,result);
        case PYZ80_BUILTIN_DICT_KEYS: case PYZ80_BUILTIN_DICT_VALUES: case PYZ80_BUILTIN_DICT_ITEMS:
            return PyZ80Target_DictView(o,&n->current,n->class_symbol-PYZ80_BUILTIN_DICT_KEYS,result);
        default: return 0u;
        }
    }
    if(factory->kind!=PYZ80_VM_VALUE_BUILTIN || !PyZ80Target_Truth(o,0,factory,&truth))return 0u;
    op=(uint8_t)factory->payload;
    switch(op) {
    case PYZ80_BUILTIN_BOOL: result->kind=PYZ80_VM_VALUE_BOOL;return 1u;
    case PYZ80_BUILTIN_INT: result->kind=PYZ80_VM_VALUE_I32;return 1u;
    case PYZ80_BUILTIN_LIST: return PyZ80Target_EmptyList(o,result);
    case PYZ80_BUILTIN_DICT: return PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_DICT,65535u,result);
    case PYZ80_BUILTIN_SET: case PYZ80_BUILTIN_FROZENSET:
        return PyZ80Target_SetFrom(o,0,op==PYZ80_BUILTIN_FROZENSET,result);
    case PYZ80_BUILTIN_DEQUE: return PyZ80Target_EmptyDeque(o,result);
    case PYZ80_BUILTIN_DEFAULTDICT: {
        PyZ80VMValue value;none(&value);return PyZ80Target_CreateDefaultDict(o,&value,result);
    }
    default: return 0u;
    }
}

static uint8_t done(PyZ80TargetDefaultDictFrame *f,PyZ80VMValue *r,const PyZ80VMValue *v,PyZ80VMValue *out)
{
    uint8_t i;*out=*v;memset(f,0,sizeof(*f));for(i=0u;i<4u;++i)none(&r[i]);return 1u;
}

static uint8_t construct(PyZ80TargetDefaultDict *s,PyZ80VM *vm,uint16_t adapter,
    PyZ80TargetDefaultDictFrame *f,PyZ80VMValue *r,const PyZ80VMValue *args,uint8_t count)
{
    PyZ80TargetContext *o=s->scopes->objects;
    PyZ80VMValue factory,mapping;
    uint16_t start,key;
    uint8_t i,positional=0u,seen_keyword=0u;
    none(&factory);
    if(!PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_OFFSETS,adapter,&start) || start==65535u)return 0u;
    for(i=1u;i<count;++i) {
        if(!PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_KEYS,start+i-1u,&key))return 0u;
        if(key==65535u) { if(seen_keyword || positional==2u)return 0u;++positional; }
        else seen_keyword=1u;
    }
    if(positional)factory=args[1];
    if(factory.kind!=PYZ80_VM_VALUE_NONE && !callable(o,&factory))return 0u;
    if(!PyZ80Target_CreateDefaultDict(o,&factory,&r[0]))return 0u;
    f->index=positional+1u; /* ADD.U8: пропустить callable и позиционные аргументы. */
    f->phase=COPY_KEYWORDS;
    if(positional==2u) {
        if(!PyZ80Target_Mapping(o,&args[2],&mapping) || !PyZ80Target_GetIterator(o,&args[2],&r[2]))return 0u;
        f->phase=COPY_MAPPING;
    }
    f->pc=vm->frames[vm->call_depth-1u].pc;f->adapter=adapter;return 1u;
}

static uint8_t dispatch(void *raw,PyZ80VM *vm,uint16_t adapter,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result,uint16_t *function)
{
    PyZ80TargetDefaultDict *s=raw;
    PyZ80TargetContext *o=s->scopes->objects;
    PyZ80TargetDefaultDictFrame *f;
    PyZ80VMValue *r,*parts,prototype,receiver,value;
    PyZ80TargetNode *node;
    PyZ80TargetAdapterSpec spec;
    uint16_t start,key,handle;
    uint8_t found,truth,call_count;
    const PyZ80VMControlHooks *previous=s->hooks.previous;
    if(vm!=s->scopes->vm || !vm->call_depth || vm->call_depth>s->capacity ||
       !PyZ80Target_ReadAdapter(o,adapter,&spec))return 3u;
    f=&s->frames[vm->call_depth-1u];r=&s->roots[(uint16_t)(vm->call_depth-1u)*4u];
    if(f->phase) {
        if(f->adapter!=adapter || f->pc!=vm->frames[vm->call_depth-1u].pc || f->phase==WAIT_FACTORY)return 3u;
    } else if(spec.operation==PYZ80_TARGET_UNSUPPORTED && count && args[0].kind==PYZ80_VM_VALUE_BUILTIN &&
              args[0].payload==PYZ80_BUILTIN_DEFAULTDICT) {
        if(!PyZ80Target_Truth(o,vm,args,&truth) || !construct(s,vm,adapter,f,r,args,count))return 3u;
    } else {
        if(spec.operation==PYZ80_TARGET_LOAD_SUBSCRIPT && count==2u &&
           (node=PyZ80Target_Node(o,args)) && node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
            found=PyZ80Target_DictFind(o,&args[0],&args[1],result);
            if(found==1u)return 1u;
            if(found!=2u)return 3u;
            r[0]=args[0];r[1]=args[1];
        } else if(spec.operation==PYZ80_TARGET_UNSUPPORTED && count &&
                  (node=PyZ80Target_Node(o,args)) && node->kind==PYZ80_TARGET_NODE_NATIVE_METHOD &&
                  node->class_symbol==PYZ80_BUILTIN_DEFAULTDICT_MISSING) {
            if(count!=2u || !PyZ80Target_NativeMethodValid(o,node) ||
               !PyZ80Target_ReadByte(o,PYZ80_TABLE_CALL_FLAGS,adapter,&found) || !found)return 3u;
            r[0]=node->current;r[1]=args[1];
        } else goto delegate;
        if(!PyZ80Target_DefaultDictParts(o,PyZ80Target_Node(o,&r[0]),&parts))return 3u;
        /* Сохраняем именно текущую фабрику и исходный ключ. Callback может
           поменять default_factory, globals и даже значение этого ключа. */
        r[2]=parts[1];f->pc=vm->frames[vm->call_depth-1u].pc;f->adapter=adapter;
        if(empty_native(o,&r[2],&r[3]))f->phase=STORE_RESULT;
        else if(PyZ80Target_UnwrapCallable(o,&r[2],&prototype,&receiver)) {
            node=PyZ80Target_Node(o,&prototype);
            if(node->has_current==1u) {
                vm->argument_scratch[0]=r[2];call_count=1u;
                if(PyZ80Target_PrepareGeneratorCall(s->scopes,65535u,vm->argument_scratch,&call_count,function)!=1u ||
                   PyZ80VM_GeneratorCreateArgs(vm,*function,&r[2],vm->argument_scratch,call_count,&handle)!=PYZ80_VM_IDLE)return 3u;
                if(!PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_GENERATOR,65535u,&r[3])) {
                    PyZ80VM_GeneratorClose(vm,handle);return 3u;
                }
                node=PyZ80Target_Node(o,&r[3]);node->cursor=handle;vm->generators[handle].owner=r[3];f->phase=STORE_RESULT;
            } else { f->phase=WAIT_FACTORY;return 7u; }
        } else return 3u;
    }
    if(f->phase==COPY_MAPPING) {
        if(!PyZ80Target_IterNext(o,&r[2],&value))return 3u;
        node=PyZ80Target_Node(o,&r[2]);
        if(node->has_current) {
            r[1]=node->current;
            if(PyZ80Target_DictFind(o,&args[2],&r[1],&r[3])!=1u || !PyZ80Target_DictStore(o,&r[0],&r[1],&r[3]))return 3u;
            none(&r[3]);return 6u;
        }
        none(&r[2]);f->phase=COPY_KEYWORDS;
    }
    if(f->phase==COPY_KEYWORDS) {
        if(f->index<count) {
            if(!PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_OFFSETS,adapter,&start) || start==65535u ||
               !PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_KEYS,start+f->index-1u,&key) || key==65535u)return 3u;
            none(&value);value.kind=PYZ80_VM_VALUE_SYMBOL;value.symbol=key;
            if(!PyZ80Target_DictStore(o,&r[0],&value,&args[f->index]))return 3u;
            ++f->index;return 6u;
        }
        return done(f,r,&r[0],result);
    }
    if(f->phase!=STORE_RESULT || !PyZ80Target_DictStore(o,&r[0],&r[1],&r[3]))return 3u;
    return done(f,r,&r[3],result);
delegate:
    return previous && previous->dispatch && (!previous->routes || previous->routes[adapter]!=65535u) ?
        previous->dispatch(previous->context,vm,adapter,args,count,result,function) : 0u;
}

static uint8_t prepare(void *raw,PyZ80VM *vm,PyZ80VMValue *callable_value,PyZ80VMValue *args,uint8_t *count,uint16_t *function)
{
    PyZ80TargetDefaultDict *s=raw;
    const PyZ80VMControlHooks *h=s->hooks.previous;
    if(vm!=s->scopes->vm || !vm->call_depth || vm->call_depth>s->capacity)return 0u;
    if(s->frames[vm->call_depth-1u].phase!=WAIT_FACTORY)
        return h && h->prepare_call ? h->prepare_call(h->context,vm,callable_value,args,count,function) : 0u;
    *callable_value=s->roots[(uint16_t)(vm->call_depth-1u)*4u+2u];args[0]=*callable_value;*count=1u;
    return PyZ80Target_PreparePositionalCall(s->scopes,args,count,function)==1u;
}

static uint8_t call_result(void *raw,PyZ80VM *vm,const PyZ80VMValue *value)
{
    PyZ80TargetDefaultDict *s=raw;
    PyZ80TargetDefaultDictFrame *f;
    if(vm!=s->scopes->vm || vm->call_depth>s->capacity)return 2u;
    if(vm->call_depth<2u)return 0u;
    f=&s->frames[vm->call_depth-2u];if(f->phase!=WAIT_FACTORY)return 0u;
    s->roots[(uint16_t)(vm->call_depth-2u)*4u+3u]=*value;f->phase=STORE_RESULT;return 1u;
}

static uint8_t returned(void *raw,PyZ80VM *vm)
{
    const PyZ80VMControlHooks *h=((PyZ80TargetDefaultDict *)raw)->hooks.previous;
    return h && h->returned ? h->returned(h->context,vm) : 0u;
}

static void failed(void *raw,PyZ80VM *vm)
{
    PyZ80TargetDefaultDict *s=raw;
    const PyZ80VMControlHooks *h=s->hooks.previous;
    memset(s->frames,0,(uint16_t)s->capacity*sizeof(*s->frames));
    memset(s->roots,0,(uint16_t)s->capacity*4u*sizeof(*s->roots));
    if(h && h->failed)h->failed(h->context,vm);
}

static uint8_t overlap(const void *a,uint32_t an,const void *b,uint32_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return x<=y ? y-x<an : x-y<bn;
}

uint8_t PyZ80Target_AttachDefaultDict(PyZ80TargetDefaultDict *s,PyZ80TargetScopes *scopes,
    PyZ80TargetDefaultDictFrame *frames,PyZ80VMValue *roots,uint8_t capacity,uint16_t *routes)
{
    PyZ80VM *vm;const PyZ80VMControlHooks *h;PyZ80TargetAdapterSpec spec;
    uint32_t fb=(uint32_t)capacity*sizeof(*frames),rb=(uint32_t)capacity*4u*sizeof(*roots),tb;
    uint16_t i;
    if(!s || !scopes || !scopes->objects || !scopes->vm || !frames || !roots || !routes)return 0u;
    vm=scopes->vm;h=vm->control_hooks;tb=(uint32_t)vm->header.adapter_count*sizeof(*routes);
    if(vm->status!=PYZ80_VM_IDLE || vm->scope_hooks!=&scopes->hooks || !capacity || capacity<vm->limits.max_call_depth ||
       !PyZ80Target_ControlStorageSeparate(scopes,s,sizeof(*s)) || !PyZ80Target_ControlStorageSeparate(scopes,frames,fb) ||
       !PyZ80Target_ControlStorageSeparate(scopes,roots,rb) || !PyZ80Target_ControlStorageSeparate(scopes,routes,tb) ||
       overlap(s,sizeof(*s),frames,fb) || overlap(s,sizeof(*s),roots,rb) || overlap(s,sizeof(*s),routes,tb) ||
       overlap(frames,fb,roots,rb) || overlap(frames,fb,routes,tb) || overlap(roots,rb,routes,tb))return 0u;
    for(i=0u;i<vm->header.adapter_count;++i) {
        if(!PyZ80Target_ReadAdapter(scopes->objects,i,&spec))return 0u;
        routes[i]=(spec.operation==PYZ80_TARGET_LOAD_SUBSCRIPT || spec.operation==PYZ80_TARGET_UNSUPPORTED ||
            (h && h->dispatch && (!h->routes || h->routes[i]!=65535u))) ? 0u : 65535u;
    }
    memset(s,0,sizeof(*s));memset(frames,0,fb);memset(roots,0,rb);
    s->scopes=scopes;s->frames=frames;s->roots=roots;s->capacity=capacity;
    s->hooks.previous=h;s->hooks.context=s;s->hooks.routes=routes;s->hooks.roots=roots;s->hooks.root_count=(uint16_t)capacity*4u;
    s->hooks.dispatch=dispatch;s->hooks.prepare_call=prepare;s->hooks.call_result=call_result;
    s->hooks.returned=returned;s->hooks.failed=failed;vm->control_hooks=&s->hooks;return 1u;
}
