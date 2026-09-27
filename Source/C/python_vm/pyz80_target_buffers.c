#include <string.h>
#include "pyz80_target_buffers.h"

static void reference(PyZ80VMValue *v,uint16_t link,uint16_t generation)
{
    memset(v,0,sizeof(*v));v->kind=PYZ80_VM_VALUE_OPAQUE;v->symbol=65535u;
    v->payload=((uint32_t)generation<<16)|link; /* SHL/OR.U32: стабильный handle. */
}

static uint8_t octet(const PyZ80VMValue *v)
{
    return v && ((v->kind==PYZ80_VM_VALUE_I32 && v->payload<=255u) ||
        (v->kind==PYZ80_VM_VALUE_BOOL && v->payload<=1u));
}

uint8_t PyZ80Target_BufferBlockValid(PyZ80TargetContext *o,const PyZ80TargetNode *b)
{
    return o && b && b->kind==PYZ80_TARGET_NODE_BUFFER_BLOCK && b->item_count==PYZ80_BUFFER_BLOCK_SLOTS &&
        b->cursor && b->cursor<=PYZ80_BUFFER_BLOCK_BYTES && !b->reserved && !b->has_current &&
        b->field_head<=1023u && o->items && o->item_used<=o->item_capacity &&
        b->item_start<=o->item_used && PYZ80_BUFFER_BLOCK_SLOTS<=o->item_used-b->item_start;
}

static uint8_t owned(PyZ80TargetContext *o,const PyZ80TargetNode *b,const PyZ80TargetNode *n)
{
    return PyZ80Target_BufferBlockValid(o,b) && b->source_link==(uint16_t)(n-o->nodes)+1u &&
        b->source_generation==n->generation;
}

uint8_t PyZ80Target_BufferValid(PyZ80TargetContext *o,const PyZ80TargetNode *n)
{
    PyZ80VMValue v;PyZ80TargetNode *b;
    if(!o || !PYZ80_IS_BUFFER(n) || n->item_start || n->reserved || n->has_current)return 0u;
    if(!n->item_count)return n->current.kind==PYZ80_VM_VALUE_NONE && !n->source_link && !n->source_generation && !n->field_head;
    b=PyZ80Target_Node(o,&n->current);
    if(!owned(o,b,n) || b->field_head)return 0u;
    reference(&v,n->source_link,n->source_generation);b=PyZ80Target_Node(o,&v);
    if(!owned(o,b,n) || b->current.kind!=PYZ80_VM_VALUE_NONE ||
       b->field_head!=(n->item_count-1u)/PYZ80_BUFFER_BLOCK_BYTES ||
       b->cursor!=(n->item_count-1u)%PYZ80_BUFFER_BLOCK_BYTES+1u)return 0u;
    if(n->field_head) {
        reference(&v,n->field_head,n->class_symbol);b=PyZ80Target_Node(o,&v);
        if(!owned(o,b,n) || b->field_head!=n->cursor || n->cursor>(n->item_count-1u)/PYZ80_BUFFER_BLOCK_BYTES)return 0u;
    }
    return 1u;
}

uint8_t PyZ80Target_BufferTraceValid(PyZ80TargetContext *o,const PyZ80TargetNode *n)
{
    PyZ80VMValue v;PyZ80TargetNode *b;uint16_t ordinal=0u,total=0u;
    uint8_t cached;
    if(!PyZ80Target_BufferValid(o,n))return 0u;
    v=n->current;cached=!n->field_head;
    while(v.kind!=PYZ80_VM_VALUE_NONE) {
        b=PyZ80Target_Node(o,&v);
        if(!owned(o,b,n) || b->field_head!=ordinal || b->cursor>n->item_count-total ||
           (b->current.kind!=PYZ80_VM_VALUE_NONE && b->cursor!=PYZ80_BUFFER_BLOCK_BYTES))return 0u;
        if((uint16_t)v.payload==n->field_head)cached=1u;
        total+=b->cursor;++ordinal; /* ADD/INC.U16: проверенные длина и номер блока. */
        if(total==n->item_count && ((uint16_t)v.payload!=n->source_link || b->generation!=n->source_generation))return 0u;
        v=b->current;
    }
    return total==n->item_count && cached;
}

uint8_t PyZ80Target_EmptyBuffer(PyZ80TargetContext *o,PyZ80VMValue *v)
{ return PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_BYTEARRAY,65535u,v); }

uint8_t PyZ80Target_BufferClear(PyZ80TargetContext *o,const PyZ80VMValue *v)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);
    if(!PyZ80Target_BufferValid(o,n) || n->kind!=PYZ80_TARGET_NODE_BYTEARRAY)return 0u;
    n->item_count=0u;n->source_link=0u;n->source_generation=0u;n->field_head=0u;n->cursor=0u;n->class_symbol=65535u;
    memset(&n->current,0,sizeof(n->current));n->current.symbol=65535u;return 1u;
}

uint8_t PyZ80Target_BufferFreeze(PyZ80TargetContext *o,PyZ80VMValue *v)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);uint16_t i;
    if(!PyZ80Target_BufferValid(o,n))return 0u;
    if(!n->item_count)for(i=0u;i<o->node_used;++i)
        if(o->nodes[i].kind==PYZ80_TARGET_NODE_BYTES && !o->nodes[i].item_count) {
            if(!PyZ80Target_BufferValid(o,&o->nodes[i]))return 0u;
            reference(v,i+1u,o->nodes[i].generation);return 1u;
        }
    n->kind=PYZ80_TARGET_NODE_BYTES;return 1u;
}

uint8_t PyZ80Target_BufferAppend(PyZ80TargetContext *o,const PyZ80VMValue *v,const PyZ80VMValue *value)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v),*b,*tail=0;PyZ80VMValue ref;
    uint8_t byte;
    if(!PyZ80Target_BufferValid(o,n) || n->kind!=PYZ80_TARGET_NODE_BYTEARRAY ||
       n->item_count==65535u || !octet(value))return 0u;
    byte=(uint8_t)value->payload;
    if(n->source_link) { reference(&ref,n->source_link,n->source_generation);tail=PyZ80Target_Node(o,&ref); }
    b=tail;
    if(!b || b->cursor==PYZ80_BUFFER_BLOCK_BYTES) {
        if(!o->items || o->item_used>o->item_capacity || PYZ80_BUFFER_BLOCK_SLOTS>o->item_capacity-o->item_used ||
           !PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_BUFFER_BLOCK,65535u,&ref))return 0u;
        b=PyZ80Target_Node(o,&ref);b->item_start=o->item_used;b->item_count=PYZ80_BUFFER_BLOCK_SLOTS;
        memset(&o->items[o->item_used],0,PYZ80_BUFFER_BLOCK_BYTES);
        o->item_used+=PYZ80_BUFFER_BLOCK_SLOTS; /* ADD.U16: только один новый блок, без переноса префикса. */
        b->source_link=(uint16_t)v->payload;b->source_generation=n->generation;
        b->field_head=n->item_count/PYZ80_BUFFER_BLOCK_BYTES;
        if(tail)tail->current=ref;else n->current=ref;
        n->source_link=(uint16_t)ref.payload;n->source_generation=b->generation;
    }
    ((uint8_t*)&o->items[b->item_start])[b->cursor++]=byte;
    ++n->item_count;return 1u;
}

static uint8_t *position(PyZ80TargetContext *o,const PyZ80VMValue *v,uint16_t index)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v),*b;PyZ80VMValue ref;
    uint16_t ordinal=index/PYZ80_BUFFER_BLOCK_BYTES;
    if(!PyZ80Target_BufferValid(o,n) || index>=n->item_count)return 0;
    ref=n->current;
    if(n->field_head && n->cursor<=ordinal)reference(&ref,n->field_head,n->class_symbol);
    b=PyZ80Target_Node(o,&ref);
    while(owned(o,b,n) && b->field_head<ordinal) {
        uint16_t next=b->field_head+1u;
        if(b->cursor!=PYZ80_BUFFER_BLOCK_BYTES)return 0;
        ref=b->current;b=PyZ80Target_Node(o,&ref);
        if(!owned(o,b,n) || b->field_head!=next)return 0;
    }
    if(!owned(o,b,n) || b->field_head!=ordinal || index%PYZ80_BUFFER_BLOCK_BYTES>=b->cursor)return 0;
    n->field_head=(uint16_t)ref.payload;n->class_symbol=b->generation;n->cursor=ordinal;
    return &((uint8_t*)&o->items[b->item_start])[index%PYZ80_BUFFER_BLOCK_BYTES];
}

uint8_t PyZ80Target_BufferIndex(PyZ80TargetContext *o,const PyZ80VMValue *v,const PyZ80VMValue *at,uint16_t *index)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);int32_t i;
    if(!index || !PyZ80Target_BufferValid(o,n) || !at || (at->kind!=PYZ80_VM_VALUE_I32 &&
       !(at->kind==PYZ80_VM_VALUE_BOOL && at->payload<=1u)))return 0u;
    i=(int32_t)at->payload;if(i<0)i+=n->item_count; /* ADD.I32: относительный индекс от конца. */
    if(i<0 || (uint32_t)i>=n->item_count)return 0u;
    *index=(uint16_t)i;return 1u;
}

uint8_t PyZ80Target_BufferRead(PyZ80TargetContext *o,const PyZ80VMValue *v,uint16_t index,PyZ80VMValue *out)
{
    uint8_t *p=position(o,v,index);
    if(!p || !out)return 0u;
    memset(out,0,sizeof(*out));out->kind=PYZ80_VM_VALUE_I32;out->symbol=65535u;out->payload=*p;return 1u;
}

uint8_t PyZ80Target_BufferWrite(PyZ80TargetContext *o,const PyZ80VMValue *v,uint16_t index,const PyZ80VMValue *value)
{
    PyZ80TargetNode *n=PyZ80Target_Node(o,v);uint8_t *p,byte;
    if(!n || n->kind!=PYZ80_TARGET_NODE_BYTEARRAY || !octet(value))return 0u;
    byte=(uint8_t)value->payload;p=position(o,v,index);if(!p)return 0u;*p=byte;return 1u;
}
