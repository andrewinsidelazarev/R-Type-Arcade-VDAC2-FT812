#include <string.h>
#include "pyz80_target_sequences.h"
#include "pyz80_target_buffers.h"

#define REPEAT 1u
#define REPEAT_INPLACE 2u
#define SLICE 3u
#define BUFFER_ASSIGN_SNAPSHOT 4u
#define BUFFER_ASSIGN_WRITE 5u
#define BUFFER_COMPARE 6u
#define BUFFER_CONTAINS 7u

static void none(PyZ80VMValue *v)
{
    memset(v,0,sizeof(*v));v->symbol=PYZ80_VM_NO_SYMBOL;
}

static uint8_t number(const PyZ80VMValue *v)
{
    return v->kind==PYZ80_VM_VALUE_I32 || (v->kind==PYZ80_VM_VALUE_BOOL && v->payload<=1u);
}

static PyZ80TargetNode *sequence(PyZ80TargetContext *o,const PyZ80VMValue *v,uint32_t *length)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);
    return n && (n->kind==PYZ80_TARGET_NODE_LIST || n->kind==PYZ80_TARGET_NODE_TUPLE || PYZ80_IS_BUFFER(n)) &&
        PyZ80Target_Length(o,v,length) ? n : 0;
}

static uint8_t make_slice(PyZ80TargetContext *o,const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result)
{
    PyZ80TargetNode *n;
    uint8_t i;
    if(count!=3u || !o->items || o->item_used>o->item_capacity ||
       3u>o->item_capacity-o->item_used ||
       !PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_SLICE,PYZ80_VM_NO_SYMBOL,result))return 3u;
    n=PyZ80Target_Node(o,result);n->item_start=o->item_used;n->item_count=3u;
    for(i=0u;i<3u;++i)o->items[o->item_used++]=args[i];
    return 1u;
}

static uint8_t bound(const PyZ80VMValue *value,int32_t length,uint8_t negative,
    uint8_t stop,int32_t *result)
{
    int32_t v;
    if(value->kind==PYZ80_VM_VALUE_NONE) {
        *result=negative ? (stop ? -1 : length-1) : (stop ? length : 0);
        return 1u;
    }
    if(!number(value))return 0u;
    v=(int32_t)value->payload; /* LD.I32: явная граница, None обрабатывается отдельно. */
    if(v<0)v+=length; /* ADD.I32: отрицательная граница + длина, без переполнения. */
    if(v<0)v=negative ? -1 : 0;
    else if(v>=length)v=negative ? length-1 : length;
    *result=v;return 1u;
}

static uint8_t normalize(PyZ80TargetContext *o,const PyZ80TargetNode *slice,
    uint16_t length,PyZ80TargetSequenceRequest *f)
{
    const PyZ80VMValue *parts;
    int32_t start,stop,step;
    uint32_t distance,magnitude;
    uint8_t negative;
    if(!slice || slice->kind!=PYZ80_TARGET_NODE_SLICE || slice->item_count!=3u ||
       !o->items || o->item_used>o->item_capacity || slice->item_start>o->item_used ||
       3u>o->item_used-slice->item_start)return 0u;
    parts=&o->items[slice->item_start];
    if(parts[2].kind==PYZ80_VM_VALUE_NONE)step=1;
    else { if(!number(&parts[2]))return 0u;step=(int32_t)parts[2].payload; }
    if(!step)return 0u;
    negative=step<0;
    if(!bound(&parts[0],length,negative,0u,&start) ||
       !bound(&parts[1],length,negative,1u,&stop))return 0u;
    f->step=step;f->index=(uint16_t)start;f->remaining=0u;
    if(negative ? start>stop : start<stop) {
        distance=negative ? (uint32_t)(start-stop) : (uint32_t)(stop-start);
        --distance; /* DEC.U32: правая граница исключена. */
        magnitude=negative ? 0UL-(uint32_t)step : (uint32_t)step; /* NEG.U32: допустим и MIN_I32. */
        distance/=magnitude; /* DIV.U32: число полных интервалов. */
        ++distance; /* INC.U32: включить начальный элемент. */
        f->remaining=(uint16_t)distance;
    }
    return 1u;
}

static uint8_t done(PyZ80TargetSequenceRequest *f,PyZ80VMValue *roots,
    const PyZ80VMValue *value,PyZ80VMValue *result)
{
    *result=*value;memset(f,0,sizeof(*f));none(&roots[0]);none(&roots[1]);return 1u;
}

static uint8_t dispatch(void *raw,PyZ80VM *vm,uint16_t adapter,
    const PyZ80VMValue *args,uint8_t count,PyZ80VMValue *result,uint16_t *function)
{
    PyZ80TargetSequences *s=raw;
    PyZ80TargetContext *o=s->scopes->objects;
    PyZ80TargetSequenceRequest *f;
    PyZ80VMValue *roots,value;
    PyZ80TargetNode *source,*output,*slice;
    PyZ80TargetAdapterSpec spec;
    uint32_t length,extent;
    int32_t factor;
    uint8_t op,source_index;
    const PyZ80VMControlHooks *previous=s->hooks.previous;
    if(vm!=s->scopes->vm || !vm->call_depth || vm->call_depth>s->capacity ||
       !PyZ80Target_ReadAdapter(o,adapter,&spec))return 3u;
    f=&s->frames[vm->call_depth-1u];roots=&s->roots[(uint16_t)(vm->call_depth-1u)*2u];
    if(f->mode) {
        if(f->adapter!=adapter || f->pc!=vm->frames[vm->call_depth-1u].pc)return 3u;
    } else {
        if(spec.operation==PYZ80_TARGET_COMPARE && count==3u && PyZ80Target_Operator(o,args,&op)) {
            PyZ80TargetNode *a=PyZ80Target_Node(o,&args[1]),*b=PyZ80Target_Node(o,&args[2]);
            if((op==PYZ80_TARGET_OP_IN || op==PYZ80_TARGET_OP_NOT_IN) && PYZ80_IS_BUFFER(b)) {
                if(!number(&args[1]) || args[1].payload>255u || !PyZ80Target_BufferValid(o,b))return 3u;
                roots[0]=args[2];roots[1]=args[1];f->mode=BUFFER_CONTAINS;f->remaining=b->item_count;f->kind=op;
                f->adapter=adapter;f->pc=vm->frames[vm->call_depth-1u].pc;return 6u;
            }
            if(op>=PYZ80_TARGET_OP_EQ && op<=PYZ80_TARGET_OP_GE && (PYZ80_IS_BUFFER(a) || PYZ80_IS_BUFFER(b))) {
                if(!PYZ80_IS_BUFFER(a) || !PYZ80_IS_BUFFER(b))return 3u;
                if(!PyZ80Target_BufferValid(o,a) || !PyZ80Target_BufferValid(o,b))return 3u;
                roots[0]=args[1];roots[1]=args[2];f->mode=BUFFER_COMPARE;f->kind=op;
                f->source_count=a->item_count;f->produced=b->item_count;
                f->remaining=a->item_count<b->item_count ? a->item_count : b->item_count;
                f->adapter=adapter;f->pc=vm->frames[vm->call_depth-1u].pc;return 6u;
            }
        }
        if(spec.operation==PYZ80_TARGET_BUILD_SLICE)return make_slice(o,args,count,result);
        if(spec.operation==PYZ80_TARGET_BINARY && count==3u &&
           PyZ80Target_Operator(o,&args[0],&op) && op==PYZ80_TARGET_OP_MUL) {
            source_index=1u;source=sequence(o,&args[1],&length);
            if(!source) { source_index=2u;source=sequence(o,&args[2],&length); }
            if(!source)goto delegate;
            if(!number(&args[3u-source_index]))return 3u;
            factor=(int32_t)args[3u-source_index].payload;
            roots[0]=args[source_index];
            if(spec.auxiliary && source_index==1u && source->kind==PYZ80_TARGET_NODE_BYTEARRAY) {
                if(!length || factor==1)return done(f,roots,&roots[0],result);
                if(factor<=0) {
                    if(!PyZ80Target_BufferClear(o,&roots[0]))return 3u;
                    return done(f,roots,&roots[0],result);
                }
                return 3u; /* Передача цепочки блоков при *= пока не реализована. */
            }
            if(spec.auxiliary && source_index==1u && source->kind==PYZ80_TARGET_NODE_LIST) {
                if(!length || factor==1)return done(f,roots,&roots[0],result);
                if(factor<=0) {
                    if(!PyZ80Target_ListClear(o,&roots[0]))return 3u;
                    return done(f,roots,&roots[0],result);
                }
            }
            if((source->kind==PYZ80_TARGET_NODE_TUPLE || source->kind==PYZ80_TARGET_NODE_BYTES) && (!length || factor==1))
                return done(f,roots,&roots[0],result);
            extent=0u;
            if(factor>0 && length) {
                if((uint32_t)factor>(PYZ80_IS_BUFFER(source) ? 65535UL : o->item_capacity)/length)return 3u;
                extent=length*(uint32_t)factor; /* MUL.U32: только после проверки ёмкости. */
            }
            f->remaining=(uint16_t)extent;
            f->mode=spec.auxiliary && source_index==1u && source->kind==PYZ80_TARGET_NODE_LIST ? REPEAT_INPLACE : REPEAT;
            f->index=0u;
        } else if(spec.operation==PYZ80_TARGET_LOAD_SUBSCRIPT && count==2u &&
                  (slice=PyZ80Target_Node(o,&args[1])) && slice->kind==PYZ80_TARGET_NODE_SLICE) {
            source=sequence(o,&args[0],&length);
            if(!source || !normalize(o,slice,(uint16_t)length,f))return 3u;
            roots[0]=args[0];
            if((source->kind==PYZ80_TARGET_NODE_TUPLE || source->kind==PYZ80_TARGET_NODE_BYTES) && f->step==1 &&
               !f->index && f->remaining==length)return done(f,roots,&roots[0],result);
            f->mode=SLICE;
        } else if(spec.operation==PYZ80_TARGET_STORE_SUBSCRIPT && count==3u &&
                  (source=sequence(o,&args[0],&length)) && source->kind==PYZ80_TARGET_NODE_BYTEARRAY &&
                  (slice=PyZ80Target_Node(o,&args[1])) && slice->kind==PYZ80_TARGET_NODE_SLICE) {
            uint32_t rhs_length;
            if(!normalize(o,slice,(uint16_t)length,f) || !PYZ80_IS_BUFFER(PyZ80Target_Node(o,&args[2])) ||
               !PyZ80Target_Length(o,&args[2],&rhs_length) || rhs_length!=f->remaining)return 3u;
            roots[0]=args[0];f->mode=BUFFER_ASSIGN_SNAPSHOT;
        } else if((spec.operation==PYZ80_TARGET_STORE_SUBSCRIPT || spec.operation==PYZ80_TARGET_DELETE_SUBSCRIPT) &&
                  count>=2u && (slice=PyZ80Target_Node(o,&args[1])) && slice->kind==PYZ80_TARGET_NODE_SLICE)
            return 3u; /* Изменяющие срезы пока не объявлены реализованными. */
        else goto delegate;
        /* Буфер результата зарезервирован логически до начала операции. Нет
           частичной мутации *= при нехватке ёмкости или неверном множителе. */
        extent=PYZ80_IS_BUFFER(source) ? ((uint32_t)f->remaining+63u)/64u*PYZ80_BUFFER_BLOCK_SLOTS : f->remaining;
        if(o->item_used>o->item_capacity || extent>o->item_capacity-o->item_used ||
           !(PYZ80_IS_BUFFER(source) ? PyZ80Target_EmptyBuffer(o,&roots[1]) : PyZ80Target_EmptyList(o,&roots[1])))return 3u;
        f->source_count=(uint16_t)length;f->kind=source->kind;f->produced=0u;
        f->adapter=adapter;f->pc=vm->frames[vm->call_depth-1u].pc;
    }
    if(f->mode==BUFFER_COMPARE || f->mode==BUFFER_CONTAINS) {
        PyZ80VMValue right;
        if(f->remaining) {
            if(!PyZ80Target_BufferRead(o,&roots[0],f->index,&value))return 3u;
            if(f->mode==BUFFER_CONTAINS) {
                if(value.payload==roots[1].payload) {
                    value.payload=f->kind==PYZ80_TARGET_OP_IN;value.kind=PYZ80_VM_VALUE_BOOL;
                    return done(f,roots,&value,result);
                }
            } else {
                if(!PyZ80Target_BufferRead(o,&roots[1],f->index,&right))return 3u;
                if(value.payload!=right.payload) {
                    f->step=value.payload<right.payload ? -1 : 1;f->remaining=0u;
                }
            }
            if(f->remaining) { --f->remaining;++f->index;return 6u; }
        }
        none(&value);value.kind=PYZ80_VM_VALUE_BOOL;
        if(f->mode==BUFFER_CONTAINS)value.payload=f->kind==PYZ80_TARGET_OP_NOT_IN;
        else {
            if(!f->step)f->step=f->source_count<f->produced ? -1 : (f->source_count>f->produced ? 1 : 0);
            switch(f->kind) {
            case PYZ80_TARGET_OP_EQ: value.payload=f->step==0;break;
            case PYZ80_TARGET_OP_NE: value.payload=f->step!=0;break;
            case PYZ80_TARGET_OP_LT: value.payload=f->step<0;break;
            case PYZ80_TARGET_OP_LE: value.payload=f->step<=0;break;
            case PYZ80_TARGET_OP_GT: value.payload=f->step>0;break;
            case PYZ80_TARGET_OP_GE: value.payload=f->step>=0;break;
            default:return 3u;
            }
        }
        return done(f,roots,&value,result);
    }
    source=sequence(o,&roots[0],&length);
    output=PyZ80Target_Node(o,&roots[1]);
    if(f->mode==BUFFER_ASSIGN_SNAPSHOT || f->mode==BUFFER_ASSIGN_WRITE) {
        if(!source || source->kind!=PYZ80_TARGET_NODE_BYTEARRAY || length!=f->source_count ||
           !PyZ80Target_BufferValid(o,output) || output->kind!=PYZ80_TARGET_NODE_BYTEARRAY || !f->step)return 3u;
        if(f->mode==BUFFER_ASSIGN_SNAPSHOT) {
            uint32_t rhs_length;
            if(!PyZ80Target_Length(o,&args[2],&rhs_length) || rhs_length!=f->remaining || output->item_count!=f->produced)return 3u;
            if(f->produced<f->remaining) {
                if(!PyZ80Target_BufferRead(o,&args[2],f->produced,&value) || !PyZ80Target_BufferAppend(o,&roots[1],&value))return 3u;
                ++f->produced;return 6u;
            }
            if(!PyZ80Target_BufferTraceValid(o,source))return 3u;
            f->mode=BUFFER_ASSIGN_WRITE;f->produced=0u;
        }
        if(f->remaining) {
            if(!PyZ80Target_BufferRead(o,&roots[1],f->produced,&value) ||
               !PyZ80Target_BufferWrite(o,&roots[0],f->index,&value))return 3u;
            --f->remaining;++f->produced;
            if(f->remaining)f->index=(uint16_t)((uint32_t)f->index+(uint32_t)f->step);
            return 6u;
        }
        none(&value);return done(f,roots,&value,result);
    }
    if(f->mode>SLICE || (f->mode==SLICE && !f->step) ||
       (f->mode==REPEAT_INPLACE && f->kind!=PYZ80_TARGET_NODE_LIST) ||
       (!PYZ80_IS_BUFFER(source) && (uint32_t)f->remaining+f->produced>o->item_capacity) ||
       !source || source->kind!=f->kind || length!=f->source_count || !output ||
       (PYZ80_IS_BUFFER(source) ? !PyZ80Target_BufferValid(o,output) : output->kind!=PYZ80_TARGET_NODE_LIST) ||
       output->item_count!=f->produced)return 3u;
    if(f->remaining) {
        if(f->index>=length)return 3u;
        if(PYZ80_IS_BUFFER(source)) {
            if(!PyZ80Target_BufferRead(o,&roots[0],f->index,&value) || !PyZ80Target_BufferAppend(o,&roots[1],&value))return 3u;
        } else {
            value=o->items[source->item_start+f->index];
            if(!PyZ80Target_ListAppend(o,&roots[1],&value))return 3u;
        }
        --f->remaining;++f->produced; /* DEC/INC.U16: один скопированный элемент. */
        if(f->remaining) {
            if(f->mode==SLICE)f->index=(uint16_t)((uint32_t)f->index+(uint32_t)f->step);
            else { ++f->index;if(f->index==f->source_count)f->index=0u; }
        }
        return 6u;
    }
    if(f->mode==REPEAT_INPLACE) {
        /* Атомарная передача item-среза прежнему объекту: alias/итераторы
           сохраняют владельца. У временного списка больше нет этого среза. */
        source->item_start=output->item_start;source->item_count=output->item_count;source->cursor=output->cursor;
        output->item_start=0u;output->item_count=0u;output->cursor=0u;
        return done(f,roots,&roots[0],result);
    }
    if(f->kind==PYZ80_TARGET_NODE_BYTES) {
        if(!PyZ80Target_BufferFreeze(o,&roots[1]))return 3u;
    } else output->kind=f->kind;
    return done(f,roots,&roots[1],result);
delegate:
    return previous && previous->dispatch && (!previous->routes || previous->routes[adapter]!=PYZ80_VM_NO_SYMBOL) ?
        previous->dispatch(previous->context,vm,adapter,args,count,result,function) : 0u;
}

static void failed(void *raw,PyZ80VM *vm)
{
    PyZ80TargetSequences *s=raw;
    const PyZ80VMControlHooks *previous=s->hooks.previous;
    memset(s->frames,0,(uint16_t)s->capacity*sizeof(*s->frames));
    memset(s->roots,0,(uint16_t)s->capacity*2u*sizeof(*s->roots));
    if(previous && previous->failed)previous->failed(previous->context,vm);
}

static uint8_t returned(void *raw,PyZ80VM *vm)
{
    const PyZ80VMControlHooks *h=((PyZ80TargetSequences *)raw)->hooks.previous;
    return h && h->returned ? h->returned(h->context,vm) : 0u;
}

static uint8_t prepare_call(void *raw,PyZ80VM *vm,PyZ80VMValue *callable,
    PyZ80VMValue *args,uint8_t *count,uint16_t *function)
{
    const PyZ80VMControlHooks *h=((PyZ80TargetSequences *)raw)->hooks.previous;
    return h && h->prepare_call ? h->prepare_call(h->context,vm,callable,args,count,function) : 0u;
}

static uint8_t overlap(const void *a,uint32_t an,const void *b,uint32_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y ? y-x<an : x-y<bn;
}

uint8_t PyZ80Target_AttachSequences(PyZ80TargetSequences *s,PyZ80TargetScopes *scopes,
    PyZ80TargetSequenceRequest *frames,PyZ80VMValue *roots,uint8_t capacity,uint16_t *routes)
{
    PyZ80VM *vm;
    const PyZ80VMControlHooks *previous;
    PyZ80TargetAdapterSpec spec;
    uint32_t fb=(uint32_t)capacity*sizeof(*frames),rb=(uint32_t)capacity*2u*sizeof(*roots),tb;
    uint16_t i;
    if(!s || !scopes || !scopes->objects || !scopes->vm || !frames || !roots || !routes)return 0u;
    vm=scopes->vm;previous=vm->control_hooks;tb=(uint32_t)vm->header.adapter_count*sizeof(*routes);
    if(vm->status!=PYZ80_VM_IDLE || vm->scope_hooks!=&scopes->hooks || !capacity || capacity<vm->limits.max_call_depth ||
       !PyZ80Target_ControlStorageSeparate(scopes,s,sizeof(*s)) ||
       !PyZ80Target_ControlStorageSeparate(scopes,frames,fb) ||
       !PyZ80Target_ControlStorageSeparate(scopes,roots,rb) ||
       !PyZ80Target_ControlStorageSeparate(scopes,routes,tb) ||
       overlap(s,sizeof(*s),frames,fb) || overlap(s,sizeof(*s),roots,rb) || overlap(s,sizeof(*s),routes,tb) ||
       overlap(frames,fb,roots,rb) || overlap(frames,fb,routes,tb) || overlap(roots,rb,routes,tb))return 0u;
    for(i=0u;i<vm->header.adapter_count;++i) {
        if(!PyZ80Target_ReadAdapter(scopes->objects,i,&spec))return 0u;
        routes[i]=(spec.operation==PYZ80_TARGET_BUILD_SLICE || spec.operation==PYZ80_TARGET_BINARY || spec.operation==PYZ80_TARGET_COMPARE ||
            spec.operation==PYZ80_TARGET_LOAD_SUBSCRIPT || spec.operation==PYZ80_TARGET_STORE_SUBSCRIPT ||
            spec.operation==PYZ80_TARGET_DELETE_SUBSCRIPT || (previous && previous->dispatch &&
            (!previous->routes || previous->routes[i]!=PYZ80_VM_NO_SYMBOL))) ? 0u : PYZ80_VM_NO_SYMBOL;
    }
    memset(s,0,sizeof(*s));memset(frames,0,fb);memset(roots,0,rb);
    s->scopes=scopes;s->frames=frames;s->roots=roots;s->capacity=capacity;
    s->hooks.previous=previous;s->hooks.context=s;s->hooks.routes=routes;
    s->hooks.roots=roots;s->hooks.root_count=(uint16_t)capacity*2u;
    s->hooks.dispatch=dispatch;s->hooks.failed=failed;
    s->hooks.returned=returned;s->hooks.prepare_call=prepare_call;
    vm->control_hooks=&s->hooks;return 1u;
}
