#include <string.h>
#include "pyz80_target_sort.h"
#include "pyz80_target_builtins.h"

#define COLLECT 1u
#define KEY 2u
#define WAIT_KEY 3u
#define GOT_KEY 4u
#define BUFFER 5u
#define MERGE 6u
#define SELECT_NEXT 7u
#define SELECT_KEY 8u
#define SELECT_WAIT_KEY 9u
#define SELECT_GOT_KEY 10u
#define SELECT_WAIT_ITER 11u
#define SELECT_END 12u

static void none(PyZ80VMValue *v) { memset(v,0,sizeof(*v));v->symbol=65535u; }

static PyZ80VMValue *items(PyZ80TargetContext *o,const PyZ80VMValue *v,uint16_t *length)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);
    uint32_t size;
    if(!n || (n->kind!=PYZ80_TARGET_NODE_LIST && n->kind!=PYZ80_TARGET_NODE_TUPLE) ||
        !PyZ80Target_Length(o,v,&size))return 0;
    *length=(uint16_t)size;
    return o->items ? &o->items[n->item_start] : 0;
}

static uint8_t number(const PyZ80VMValue *v)
{
    return v->kind==PYZ80_VM_VALUE_I32 || (v->kind==PYZ80_VM_VALUE_BOOL && v->payload<=1u);
}

static uint8_t less(PyZ80TargetContext *o,const PyZ80VMValue *a,const PyZ80VMValue *b,uint8_t *out)
{
    PyZ80VMValue *aa,*bb;
    PyZ80TargetNode *an,*bn;
    uint16_t na,nb,index;
    if(number(a) && number(b)) { *out=(int32_t)a->payload<(int32_t)b->payload;return 1u; }
    an=PyZ80Target_Node(o,a);bn=PyZ80Target_Node(o,b);
    if(!an || !bn || an->kind!=PYZ80_TARGET_NODE_TUPLE || bn->kind!=PYZ80_TARGET_NODE_TUPLE)return 0u;
    aa=items(o,a,&na);bb=items(o,b,&nb);
    if(!aa || !bb)return 0u;
    for(index=0u;index<na && index<nb;++index) {
        if(number(&aa[index]) && number(&bb[index])) {
            if(aa[index].payload==bb[index].payload)continue;
            *out=(int32_t)aa[index].payload<(int32_t)bb[index].payload;return 1u;
        }
        /* Равные неизменяемые скаляры можно пропустить; произвольные __eq__
           и вложенные сравнения пока не исполняются этим обработчиком. */
        if(aa[index].kind==PYZ80_VM_VALUE_NONE && bb[index].kind==PYZ80_VM_VALUE_NONE)continue;
        if(aa[index].kind==PYZ80_VM_VALUE_SYMBOL && bb[index].kind==PYZ80_VM_VALUE_SYMBOL && aa[index].symbol==bb[index].symbol)continue;
        return 0u;
    }
    *out=na<nb;return 1u;
}

static uint8_t done(PyZ80TargetSortRequest *f,PyZ80VMValue *r,PyZ80VMValue *result)
{
    uint8_t i;
    *result=r[2];memset(f,0,sizeof(*f));for(i=0u;i<7u;++i)none(&r[i]);return 1u;
}

/* min/max используют тот же ограниченный кадр, но не сортируют коллекцию.
   Корни: iterator, key, победитель, его ключ, кандидат, default, новый ключ.
   n — число positional, i — следующий аргумент; width/left — наличие результата/default. */
static uint8_t select_start(PyZ80TargetContext *o,PyZ80VM *vm,PyZ80TargetSortRequest *f,
    PyZ80VMValue *r,uint16_t adapter,const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result)
{
    uint16_t start,key;
    uint8_t k,seen=0u,flags;
    PyZ80TargetNode *node;
    if(!PyZ80Target_ReadByte(o,PYZ80_TABLE_CALL_FLAGS,adapter,&flags))return 3u;
    if(flags && PyZ80Target_FastExtremum((uint8_t)args[0].payload,args+1,count-1u,result))return 1u;
    if(count<2u || !PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_OFFSETS,adapter,&start) || start==65535u)return 3u;
    f->reverse=args[0].payload==PYZ80_BUILTIN_MAX;
    for(k=1u;k<count;++k) {
        if(!PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_KEYS,start+k-1u,&key))return 3u;
        if(key==65535u) { if(seen)return 3u;++f->n; }
        else if(PyZ80Target_Keyword(o,key)==PYZ80_KEYWORD_KEY && !(seen&1u)) { seen|=1u;r[1]=args[k]; }
        else if(PyZ80Target_Keyword(o,key)==PYZ80_KEYWORD_DEFAULT && !(seen&2u)) { seen|=2u;r[5]=args[k];f->left=1u; }
        else return 3u;
    }
    if(!f->n || (f->n>1u && f->left))return 3u;
    if(f->n==1u) {
        node=PyZ80Target_Node(o,&args[1]);
        if(node && node->kind==PYZ80_TARGET_NODE_GENERATOR)r[0]=args[1];
        else if(!PyZ80Target_GetIterator(o,&args[1],&r[0]))return 3u;
    }
    f->i=1u;f->state=SELECT_NEXT;f->adapter=adapter;f->pc=vm->frames[vm->call_depth-1u].pc;
    return 6u;
}

static uint8_t select_step(PyZ80TargetContext *o,PyZ80VM *vm,PyZ80TargetSortRequest *f,
    PyZ80VMValue *r,const PyZ80VMValue *args,PyZ80VMValue *result,uint16_t *function)
{
    PyZ80TargetNode *node;
    PyZ80VMValue value;
    uint16_t handle;
    uint8_t better;
    if(f->state==SELECT_NEXT) {
        if(f->n>1u) {
            if(f->i>f->n)f->state=SELECT_END;
            else { r[4]=args[f->i++];f->state=SELECT_KEY; }
        } else {
            node=PyZ80Target_Node(o,&r[0]);if(!node)return 3u;
            if(node->kind==PYZ80_TARGET_NODE_GENERATOR) {
                if(node->reserved>1u)return 3u;
                if(!node->reserved) {
                    handle=node->cursor;
                    if(handle>=vm->limits.max_generators || !vm->generators[handle].in_use ||
                       vm->generators[handle].owner.payload!=r[0].payload)return 3u;
                    if(!vm->generators[handle].done) { f->state=SELECT_WAIT_ITER;*function=handle;return 5u; }
                }
                f->state=SELECT_END;
            } else {
                if(!PyZ80Target_IterNext(o,&r[0],&value))return 3u;
                r[4]=node->current;f->state=node->has_current ? SELECT_KEY : SELECT_END;
            }
        }
    }
    if(f->state==SELECT_END) {
        node=PyZ80Target_Node(o,&r[0]);
        if(node && node->kind==PYZ80_TARGET_NODE_GENERATOR && !node->reserved) {
            if(PyZ80VM_GeneratorClose(vm,node->cursor)!=PYZ80_VM_IDLE)return 3u;
            node->reserved=1u;node->cursor=65535u;node->has_current=0u;none(&node->current);
        }
        if(!f->width) { if(!f->left)return 3u;r[2]=r[5]; }
        return done(f,r,result);
    }
    if(f->state==SELECT_KEY) {
        if(r[1].kind!=PYZ80_VM_VALUE_NONE) { f->state=SELECT_WAIT_KEY;return 7u; }
        r[6]=r[4];f->state=SELECT_GOT_KEY;
    }
    if(f->state!=SELECT_GOT_KEY)return 3u;
    better=1u;
    if(f->width && !less(o,&r[f->reverse ? 3u : 6u],&r[f->reverse ? 6u : 3u],&better))return 3u;
    if(better) { r[2]=r[4];r[3]=r[6];f->width=1u; }
    none(&r[4]);none(&r[6]);f->state=SELECT_NEXT;
    return 6u;
}

static uint8_t dispatch(void *raw,PyZ80VM *vm,uint16_t adapter,
    const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result,uint16_t *function)
{
    PyZ80TargetSort *s=raw;
    PyZ80TargetContext *o=s->scopes->objects;
    PyZ80TargetSortRequest *f;
    PyZ80VMValue *r,*values,*keys,*workvalues,*workkeys,value;
    PyZ80TargetNode *it;
    PyZ80TargetAdapterSpec spec;
    uint16_t start,key,length,index;
    uint8_t k,seen=0u,take_right,truth;
    if(vm!=s->scopes->vm || !vm->call_depth || vm->call_depth>s->capacity ||
        !PyZ80Target_ReadAdapter(o,adapter,&spec))return 3u;
    f=&s->frames[vm->call_depth-1u];r=&s->roots[(uint16_t)(vm->call_depth-1u)*7u];
    if(!f->state) {
        const PyZ80VMControlHooks *h=s->hooks.previous;
        if(spec.operation!=PYZ80_TARGET_UNSUPPORTED || !count || args[0].kind!=PYZ80_VM_VALUE_BUILTIN ||
           (args[0].payload!=PYZ80_BUILTIN_SORTED && args[0].payload!=PYZ80_BUILTIN_MIN && args[0].payload!=PYZ80_BUILTIN_MAX))
            return h && h->dispatch && (!h->routes || h->routes[adapter]!=65535u) ? h->dispatch(h->context,vm,adapter,args,count,result,function) : 0u;
        if(!PyZ80Target_Truth(o,vm,args,&truth))return 3u;
        if(args[0].payload!=PYZ80_BUILTIN_SORTED)return select_start(o,vm,f,r,adapter,args,count,result);
        if(count<2u || count>4u ||
            !PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_OFFSETS,adapter,&start) || start==65535u ||
            !PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_KEYS,start,&key) || key!=65535u)return 3u;
        none(&value);f->reverse=0u;
        for(k=2u;k<count;++k) {
            if(!PyZ80Target_ReadWord(o,PYZ80_TABLE_CALL_KEYS,start+k-1u,&key))return 3u;
            if(PyZ80Target_Keyword(o,key)==PYZ80_KEYWORD_KEY && !(seen&1u)) { seen|=1u;value=args[k]; }
            else if(PyZ80Target_Keyword(o,key)==PYZ80_KEYWORD_REVERSE && !(seen&2u) && number(&args[k])) {
                seen|=2u;f->reverse=args[k].payload!=0u;
            } else return 3u;
        }
        r[1]=value;
        if(!PyZ80Target_GetIterator(o,&args[1],&r[0]) || !PyZ80Target_EmptyList(o,&r[2]) || !PyZ80Target_EmptyList(o,&r[3]))return 3u;
        f->state=COLLECT;f->pc=vm->frames[vm->call_depth-1u].pc;f->adapter=adapter;
    } else if(f->adapter!=adapter || f->pc!=vm->frames[vm->call_depth-1u].pc || f->state==WAIT_KEY)return 3u;
    if(f->state>=SELECT_NEXT)return select_step(o,vm,f,r,args,result,function);
    if(f->state==COLLECT) {
        if(!PyZ80Target_IterNext(o,&r[0],&value))return 3u;
        it=PyZ80Target_Node(o,&r[0]);
        if(it->has_current) {
            if(!PyZ80Target_ListAppend(o,&r[2],&it->current))return 3u;
        } else {
            if(!items(o,&r[2],&f->n))return 3u;
            none(&r[0]);f->i=0u;f->state=KEY;
        }
        return 6u;
    }
    if(f->state==KEY) {
        if(f->i==f->n) {
            if(f->n<2u)return done(f,r,result);
            if(!PyZ80Target_EmptyList(o,&r[4]) || !PyZ80Target_EmptyList(o,&r[5]))return 3u;
            f->i=0u;f->state=BUFFER;return 6u;
        }
        values=items(o,&r[2],&length);if(!values || length!=f->n)return 3u;
        r[6]=values[f->i];
        if(r[1].kind!=PYZ80_VM_VALUE_NONE) { f->state=WAIT_KEY;return 7u; }
        f->state=GOT_KEY;
    }
    if(f->state==GOT_KEY) {
        if(!PyZ80Target_ListAppend(o,&r[3],&r[6]))return 3u;
        none(&r[6]);++f->i;f->state=KEY;return 6u;
    }
    if(f->state==BUFFER) {
        none(&value);
        if(!PyZ80Target_ListAppend(o,&r[4],&value) || !PyZ80Target_ListAppend(o,&r[5],&value))return 3u;
        if(++f->i==f->n) { f->width=1u;f->left=0u;f->out=0u;f->end=0u;f->state=MERGE; }
        return 6u;
    }
    if(f->state!=MERGE)return 3u;
    if(f->out==f->end) {
        f->left=f->end;
        if(f->left==f->n) {
            value=r[2];r[2]=r[4];r[4]=value;value=r[3];r[3]=r[5];r[5]=value;
            if(f->width>=f->n-f->width)return done(f,r,result);
            f->width*=2u;f->left=0u;f->out=0u; /* SHL.U16: ширина серии, удвоение проверено через n-width. */
        }
        f->mid=f->left+(f->width<f->n-f->left ? f->width : f->n-f->left);
        f->end=f->mid+(f->width<f->n-f->mid ? f->width : f->n-f->mid);
        f->i=f->left;f->j=f->mid;
    }
    values=items(o,&r[2],&length);if(!values || length!=f->n)return 3u;
    keys=items(o,&r[3],&length);if(!keys || length!=f->n)return 3u;
    workvalues=items(o,&r[4],&length);if(!workvalues || length!=f->n)return 3u;
    workkeys=items(o,&r[5],&length);if(!workkeys || length!=f->n)return 3u;
    if(f->j==f->end)take_right=0u;
    else if(f->i==f->mid)take_right=1u;
    else if(!less(o,&keys[f->reverse ? f->i : f->j],&keys[f->reverse ? f->j : f->i],&take_right))return 3u;
    index=take_right ? f->j++ : f->i++;
    workvalues[f->out]=values[index];workkeys[f->out]=keys[index];++f->out;
    return 6u; /* Одно слияние элемента за VM-шаг; всего O(n log n), без рекурсии. */
}

static uint8_t prepare(void *raw,PyZ80VM *vm,PyZ80VMValue *callable,PyZ80VMValue *args,uint8_t *count,uint16_t *function)
{
    PyZ80TargetSort *s=raw;
    PyZ80VMValue *r;
    const PyZ80VMControlHooks *h=s->hooks.previous;
    if(vm!=s->scopes->vm || !vm->call_depth || vm->call_depth>s->capacity)return 0u;
    if(s->frames[vm->call_depth-1u].state!=WAIT_KEY && s->frames[vm->call_depth-1u].state!=SELECT_WAIT_KEY)
        return h && h->prepare_call ? h->prepare_call(h->context,vm,callable,args,count,function) : 0u;
    if(vm->limits.max_arguments<2u)return 0u;
    r=&s->roots[(uint16_t)(vm->call_depth-1u)*7u];
    *callable=r[1];args[0]=r[1];args[1]=r[s->frames[vm->call_depth-1u].state==WAIT_KEY ? 6u : 4u];*count=2u;
    return PyZ80Target_PreparePositionalCall(s->scopes,args,count,function)==1u;
}

static uint8_t call_result(void *raw,PyZ80VM *vm,const PyZ80VMValue *value)
{
    PyZ80TargetSort *s=raw;
    PyZ80TargetSortRequest *f;
    if(vm!=s->scopes->vm || vm->call_depth>s->capacity)return 2u;
    if(vm->call_depth<2u)return 0u;
    f=&s->frames[vm->call_depth-2u];
    if(f->state!=WAIT_KEY && f->state!=SELECT_WAIT_KEY)return 0u;
    s->roots[(uint16_t)(vm->call_depth-2u)*7u+6u]=*value;
    f->state=f->state==WAIT_KEY ? GOT_KEY : SELECT_GOT_KEY;return 1u;
}

static uint8_t generator_event(void *raw,PyZ80VM *vm,uint16_t handle,uint8_t yielded,const PyZ80VMValue *value)
{
    PyZ80TargetSort *s=raw;
    PyZ80TargetSortRequest *f;
    PyZ80VMValue *r;
    PyZ80TargetNode *node;
    if(vm!=s->scopes->vm || vm->call_depth>s->capacity)return 2u;
    if(vm->call_depth<2u)return 0u;
    f=&s->frames[vm->call_depth-2u];if(f->state!=SELECT_WAIT_ITER)return 0u;
    r=&s->roots[(uint16_t)(vm->call_depth-2u)*7u];node=PyZ80Target_Node(s->scopes->objects,&r[0]);
    if(!node || node->kind!=PYZ80_TARGET_NODE_GENERATOR || node->cursor!=handle)return 2u;
    node->has_current=yielded;
    if(yielded) { r[4]=*value;node->current=*value;f->state=SELECT_KEY; }
    else { none(&node->current);f->state=SELECT_END; }
    return 1u;
}

static uint8_t returned(void *raw,PyZ80VM *vm)
{
    const PyZ80VMControlHooks *h=((PyZ80TargetSort *)raw)->hooks.previous;
    return h && h->returned ? h->returned(h->context,vm) : 0u;
}

static void failed(void *raw,PyZ80VM *vm)
{
    PyZ80TargetSort *s=raw;
    const PyZ80VMControlHooks *h=s->hooks.previous;
    memset(s->frames,0,(uint16_t)s->capacity*sizeof(*s->frames));
    memset(s->roots,0,(uint16_t)s->capacity*7u*sizeof(*s->roots));
    if(h && h->failed)h->failed(h->context,vm);
}

static uint8_t overlap(const void *a,uint32_t an,const void *b,uint32_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && an && bn && (x<=y ? y-x<an : x-y<bn);
}

uint8_t PyZ80Target_AttachSort(PyZ80TargetSort *s,PyZ80TargetScopes *scopes,
    PyZ80TargetSortRequest *frames,PyZ80VMValue *roots,uint8_t capacity,uint16_t *routes)
{
    PyZ80VM *vm;
    PyZ80TargetAdapterSpec spec;
    const PyZ80VMControlHooks *previous;
    uint32_t fb=(uint32_t)capacity*sizeof(*frames),rb=(uint32_t)capacity*7u*sizeof(*roots),tb;
    uint16_t i;
    if(!s || !scopes || !scopes->vm || !scopes->objects || !frames || !roots || !routes)return 0u;
    vm=scopes->vm;previous=vm->control_hooks;tb=(uint32_t)vm->header.adapter_count*sizeof(*routes);
    if(vm->status!=PYZ80_VM_IDLE || vm->scope_hooks!=&scopes->hooks || !scopes->hooks.prepare ||
        capacity<vm->limits.max_call_depth || !capacity ||
        !PyZ80Target_ControlStorageSeparate(scopes,s,sizeof(*s)) || !PyZ80Target_ControlStorageSeparate(scopes,frames,fb) ||
        !PyZ80Target_ControlStorageSeparate(scopes,roots,rb) || !PyZ80Target_ControlStorageSeparate(scopes,routes,tb) ||
        overlap(s,sizeof(*s),frames,fb) || overlap(s,sizeof(*s),roots,rb) || overlap(s,sizeof(*s),routes,tb) ||
        overlap(frames,fb,roots,rb) || overlap(frames,fb,routes,tb) || overlap(roots,rb,routes,tb))return 0u;
    for(i=0u;i<vm->header.adapter_count;++i) {
        if(!PyZ80Target_ReadAdapter(scopes->objects,i,&spec))return 0u;
        routes[i]=(spec.operation==PYZ80_TARGET_UNSUPPORTED ||
            (previous && previous->dispatch && (!previous->routes || previous->routes[i]!=65535u))) ? 0u : 65535u;
    }
    memset(s,0,sizeof(*s));memset(frames,0,fb);memset(roots,0,rb);
    s->scopes=scopes;s->frames=frames;s->roots=roots;s->capacity=capacity;
    s->hooks.context=s;s->hooks.previous=previous;s->hooks.dispatch=dispatch;s->hooks.prepare_call=prepare;
    s->hooks.call_result=call_result;s->hooks.returned=returned;s->hooks.failed=failed;
    s->hooks.generator_event=generator_event;
    s->hooks.routes=routes;s->hooks.roots=roots;s->hooks.root_count=(uint16_t)capacity*7u;
    vm->control_hooks=&s->hooks;return 1u;
}
