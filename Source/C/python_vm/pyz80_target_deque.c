#include <string.h>
#include "pyz80_target_deque.h"

static void none(PyZ80VMValue *v)
{
    memset(v,0,sizeof(*v));v->symbol=PYZ80_VM_NO_SYMBOL;
}

static void reference(PyZ80VMValue *v,uint16_t link,uint16_t generation)
{
    none(v);v->kind=PYZ80_VM_VALUE_OPAQUE;
    v->payload=((uint32_t)generation<<16)|link; /* SHL/OR.U32: стабильный handle. */
}

static PyZ80TargetNode *linked(PyZ80TargetContext *o,uint16_t link,uint16_t generation)
{
    PyZ80VMValue v;reference(&v,link,generation);return PyZ80Target_Node(o,&v);
}

static uint8_t owned(const PyZ80TargetNode *b,const PyZ80VMValue *q)
{
    return b && b->source_link==(uint16_t)q->payload &&
        b->source_generation==(uint16_t)(q->payload>>16);
}

uint8_t PyZ80Target_DequeBlockValid(PyZ80TargetContext *o,const PyZ80TargetNode *b)
{
    return o && b && b->kind==PYZ80_TARGET_NODE_DEQUE_BLOCK &&
        b->item_count==PYZ80_DEQUE_BLOCK_ITEMS && b->cursor<b->reserved &&
        b->reserved<=PYZ80_DEQUE_BLOCK_ITEMS && !b->field_head && !b->has_current &&
        o->items && o->item_used<=o->item_capacity && b->item_start<=o->item_used &&
        PYZ80_DEQUE_BLOCK_ITEMS<=o->item_used-b->item_start;
}

uint8_t PyZ80Target_DequeValid(PyZ80TargetContext *o,const PyZ80TargetNode *q)
{
    PyZ80TargetNode *head,*tail;
    if(!o || !q || q->kind!=PYZ80_TARGET_NODE_DEQUE || q->field_head ||
       q->reserved || q->has_current)return 0u;
    if(!q->item_count)return q->current.kind==PYZ80_VM_VALUE_NONE && !q->source_link && !q->source_generation;
    head=PyZ80Target_Node(o,&q->current);tail=linked(o,q->source_link,q->source_generation);
    return PyZ80Target_DequeBlockValid(o,head) && PyZ80Target_DequeBlockValid(o,tail) &&
        tail->current.kind==PYZ80_VM_VALUE_NONE;
}

static uint8_t can_mutate(const PyZ80TargetNode *q)
{
    return q->item_start!=65535u || q->cursor!=65535u;
}

static void changed(PyZ80TargetNode *q)
{
    ++q->item_start; /* INC.U16: младшая половина версии. */
    if(!q->item_start)++q->cursor; /* ADC.U16: перенос; полное переполнение запрещено. */
}

uint8_t PyZ80Target_EmptyDeque(PyZ80TargetContext *o,PyZ80VMValue *out)
{
    return PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_DEQUE,PYZ80_VM_NO_SYMBOL,out);
}

uint8_t PyZ80Target_DequeAppend(PyZ80TargetContext *o,const PyZ80VMValue *owner,const PyZ80VMValue *value)
{
    PyZ80TargetNode *q=PyZ80Target_Node(o,owner),*tail=0,*block;
    PyZ80VMValue new_block;
    uint8_t i;
    if(!value || !PyZ80Target_DequeValid(o,q) || q->item_count==65535u || !can_mutate(q))return 0u;
    if(q->item_count) {
        tail=linked(o,q->source_link,q->source_generation);
        if(!owned(tail,owner))return 0u;
    }
    if(!tail || tail->reserved==PYZ80_DEQUE_BLOCK_ITEMS) {
        if(!o->items || o->item_used>o->item_capacity || PYZ80_DEQUE_BLOCK_ITEMS>o->item_capacity-o->item_used ||
           !PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_DEQUE_BLOCK,PYZ80_VM_NO_SYMBOL,&new_block))return 0u;
        block=PyZ80Target_Node(o,&new_block);block->item_start=o->item_used;
        block->item_count=PYZ80_DEQUE_BLOCK_ITEMS;
        block->source_link=(uint16_t)owner->payload;block->source_generation=q->generation;
        for(i=0u;i<PYZ80_DEQUE_BLOCK_ITEMS;++i)none(&o->items[o->item_used++]);
        if(tail)tail->current=new_block;else q->current=new_block;
        q->source_link=(uint16_t)new_block.payload;q->source_generation=block->generation;
        tail=block;
    }
    o->items[tail->item_start+tail->reserved]=*value;
    ++tail->reserved;++q->item_count; /* INC.U8/U16: один элемент, без сдвига очереди. */
    changed(q);return 1u;
}

uint8_t PyZ80Target_DequePopleft(PyZ80TargetContext *o,const PyZ80VMValue *owner,PyZ80VMValue *out)
{
    PyZ80TargetNode *q=PyZ80Target_Node(o,owner),*head,*next;
    if(!out || !PyZ80Target_DequeValid(o,q) || !q->item_count || !can_mutate(q))return 0u;
    head=PyZ80Target_Node(o,&q->current);
    if(!owned(head,owner))return 0u;
    if(head->cursor+1u==head->reserved) {
        if(q->item_count==1u) {
            if(head->current.kind!=PYZ80_VM_VALUE_NONE)return 0u;
        } else {
            next=PyZ80Target_Node(o,&head->current);
            if(!PyZ80Target_DequeBlockValid(o,next) || !owned(next,owner))return 0u;
        }
    }
    *out=o->items[head->item_start+head->cursor];
    none(&o->items[head->item_start+head->cursor]);
    ++head->cursor;--q->item_count; /* INC/DEC.U16: удалить ровно голову. */
    if(!q->item_count) {
        none(&q->current);q->source_link=q->source_generation=0u;
    } else if(head->cursor==head->reserved)q->current=head->current;
    changed(q);return 1u;
}

uint8_t PyZ80Target_DequeClear(PyZ80TargetContext *o,const PyZ80VMValue *owner)
{
    PyZ80TargetNode *q=PyZ80Target_Node(o,owner);
    if(!PyZ80Target_DequeValid(o,q))return 0u;
    if(!q->item_count)return 1u;
    if(!can_mutate(q))return 0u;
    q->item_count=q->source_link=q->source_generation=0u;none(&q->current);
    changed(q);return 1u; /* Блоки освобождает общий GC, без обхода в clear. */
}

uint8_t PyZ80Target_DequeIterator(PyZ80TargetContext *o,const PyZ80VMValue *owner,PyZ80VMValue *out)
{
    PyZ80TargetNode *q=PyZ80Target_Node(o,owner),*it,*head;
    if(!PyZ80Target_DequeValid(o,q) ||
       !PyZ80Target_AllocateNode(o,PYZ80_TARGET_NODE_DEQUE_ITERATOR,PYZ80_VM_NO_SYMBOL,out))return 0u;
    it=PyZ80Target_Node(o,out);it->source_link=(uint16_t)owner->payload;it->source_generation=q->generation;
    it->item_start=q->item_start;it->cursor=q->cursor;
    if(q->item_count) {
        head=PyZ80Target_Node(o,&q->current);
        it->field_head=(uint16_t)q->current.payload;it->class_symbol=head->generation;it->item_count=head->cursor;
    } else it->class_symbol=0u;
    return 1u;
}

uint8_t PyZ80Target_DequeIteratorValid(PyZ80TargetContext *o,const PyZ80TargetNode *it)
{
    PyZ80TargetNode *q,*block;
    PyZ80VMValue owner;
    if(!it || it->kind!=PYZ80_TARGET_NODE_DEQUE_ITERATOR || it->reserved>1u || it->has_current>1u)return 0u;
    reference(&owner,it->source_link,it->source_generation);q=PyZ80Target_Node(o,&owner);
    if(!PyZ80Target_DequeValid(o,q))return 0u;
    /* Мутация делает next ошибкой, но не повреждает граф корней GC.
       Старый блок мог быть уже освобождён: его handle здесь не разыменовываем. */
    if(it->item_start!=q->item_start || it->cursor!=q->cursor)return 1u;
    if(!it->field_head)return !it->class_symbol;
    block=linked(o,it->field_head,it->class_symbol);
    return PyZ80Target_DequeBlockValid(o,block) && owned(block,&owner) &&
        it->item_count>=block->cursor && it->item_count<block->reserved;
}

uint8_t PyZ80Target_DequeIterNext(PyZ80TargetContext *o,const PyZ80VMValue *value,PyZ80VMValue *out)
{
    PyZ80TargetNode *it=PyZ80Target_Node(o,value),*q,*block,*next;
    if(!out || !PyZ80Target_DequeIteratorValid(o,it))return 0u;
    q=linked(o,it->source_link,it->source_generation);
    if(it->item_start!=q->item_start || it->cursor!=q->cursor)return 0u;
    if(!it->field_head) {
        it->reserved=1u;it->has_current=0u;none(&it->current);*out=*value;return 1u;
    }
    block=linked(o,it->field_head,it->class_symbol);
    it->current=o->items[block->item_start+it->item_count];it->has_current=1u;
    ++it->item_count; /* INC.U16: один элемент на шаг VM. */
    if(it->item_count==block->reserved) {
        if(block->current.kind==PYZ80_VM_VALUE_NONE)it->field_head=it->class_symbol=it->item_count=0u;
        else {
            next=PyZ80Target_Node(o,&block->current);
            if(!PyZ80Target_DequeBlockValid(o,next))return 0u;
            it->field_head=(uint16_t)block->current.payload;it->class_symbol=next->generation;it->item_count=next->cursor;
        }
    }
    *out=*value;return 1u;
}
