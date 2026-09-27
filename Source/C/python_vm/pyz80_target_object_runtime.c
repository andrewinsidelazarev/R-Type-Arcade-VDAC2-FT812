#include <string.h>

#include "pyz80_target_object_runtime.h"
#include "pyz80_target_deque.h"
#include "pyz80_target_buffers.h"

#define NO_LINK 0u
#define TARGET_I32_MAX ((int32_t)2147483647L)
#define TARGET_I32_MIN (-TARGET_I32_MAX - 1L)

static const void *flat_table(const PyZ80TargetContext *context, uint8_t table,
    uint16_t *count, uint8_t *width)
{
    *width=2u;
    switch(table) {
    case PYZ80_TABLE_ADAPTERS: *count=context->adapter_count;*width=sizeof(*context->adapters);return context->adapters;
    case PYZ80_TABLE_FIELDS: *count=context->field_key_count;return context->field_keys;
    case PYZ80_TABLE_DISPATCH: *count=context->dispatch_function_count;return context->dispatch_functions;
    case PYZ80_TABLE_ARITIES: *count=context->function_count;return context->positional_call_arities;
    case PYZ80_TABLE_CALL_FLAGS: *count=context->adapter_count;*width=1u;return context->positional_call_flags;
    case PYZ80_TABLE_SIGNATURES: *count=context->function_count;*width=sizeof(*context->call_signatures);return context->call_signatures;
    case PYZ80_TABLE_PARAMETERS: *count=context->parameter_name_count;return context->parameter_names;
    case PYZ80_TABLE_CALL_OFFSETS: *count=context->adapter_count;return context->call_layout_offsets;
    case PYZ80_TABLE_CALL_KEYS: *count=context->call_layout_key_count;return context->call_layout_keys;
    case PYZ80_TABLE_CLASS_FLAGS: *count=context->function_count;*width=1u;return context->class_body_flags;
    default: *count=0u;*width=0u;return 0;
    }
}

uint8_t PyZ80Target_HasTable(const PyZ80TargetContext *context, uint8_t table)
{
    uint16_t count;uint8_t width;
    return context && table<PYZ80_TABLE_COUNT && (context->table_read || flat_table(context,table,&count,&width));
}

uint8_t PyZ80Target_TableStorageSeparate(const PyZ80TargetContext *context, const void *buffer, uint32_t bytes)
{
    uintptr_t address=(uintptr_t)buffer,other;
    uint32_t extent;
    if(!context) return 0u;
    if(!buffer || !bytes || !context->table_read) return 1u;
    other=(uintptr_t)context->table_context;extent=context->table_context_bytes;
    if(other && extent && (address<=other ? other-address<bytes : address-other<extent)) return 0u;
    other=(uintptr_t)context->table_key_scratch;extent=(uint32_t)context->table_key_capacity*2u;
    return !other || !extent || !(address<=other ? other-address<bytes : address-other<extent);
}

uint8_t PyZ80Target_ReadTable(PyZ80TargetContext *context, uint8_t table, uint16_t index, void *record)
{
    uint16_t count;uint8_t width;
    const uint8_t *source;
    uint32_t offset;
    if(!context || !record || table>=PYZ80_TABLE_COUNT) return 0u;
    source=flat_table(context,table,&count,&width);
    if(index>=count) return 0u;
    if(context->table_read) return context->table_read(context->table_context,table,index,record);
    if(!source) return 0u;
    offset=(uint32_t)index*width; /* MUL.U32: host flat oracle may exceed a Z80 address space. */
#ifdef __SDCC
    if(offset>65535UL || (uint32_t)(uintptr_t)source+offset+width>65536UL) return 0u;
#endif
    memcpy(record,source+offset,width);
    return 1u;
}

uint8_t PyZ80Target_ReadAdapter(PyZ80TargetContext *context, uint16_t index, PyZ80TargetAdapterSpec *record)
{ return PyZ80Target_ReadTable(context,PYZ80_TABLE_ADAPTERS,index,record); }
uint8_t PyZ80Target_ReadSignature(PyZ80TargetContext *context, uint16_t index, PyZ80TargetCallSignature *record)
{ return PyZ80Target_ReadTable(context,PYZ80_TABLE_SIGNATURES,index,record); }
uint8_t PyZ80Target_ReadWord(PyZ80TargetContext *context, uint8_t table, uint16_t index, uint16_t *value)
{
    if(table!=PYZ80_TABLE_FIELDS && table!=PYZ80_TABLE_DISPATCH && table!=PYZ80_TABLE_ARITIES &&
       table!=PYZ80_TABLE_PARAMETERS && table!=PYZ80_TABLE_CALL_OFFSETS && table!=PYZ80_TABLE_CALL_KEYS) return 0u;
    return PyZ80Target_ReadTable(context,table,index,value);
}
uint8_t PyZ80Target_ReadByte(PyZ80TargetContext *context, uint8_t table, uint16_t index, uint8_t *value)
{
    if(table!=PYZ80_TABLE_CALL_FLAGS && table!=PYZ80_TABLE_CLASS_FLAGS) return 0u;
    return PyZ80Target_ReadTable(context,table,index,value);
}

static void value_none(PyZ80VMValue *value)
{
    value->kind = PYZ80_VM_VALUE_NONE;
    value->reserved = 0u;
    value->symbol = PYZ80_VM_NO_SYMBOL;
    value->payload = 0u;
}

PyZ80TargetNode *PyZ80Target_Node(
    PyZ80TargetContext *context, const PyZ80VMValue *value)
{
    uint16_t link;
    PyZ80TargetNode *node;
    if (context == 0 || value == 0 || context->nodes == 0 ||
        context->node_used > context->node_capacity ||
        value->kind != PYZ80_VM_VALUE_OPAQUE) return 0;
    link = (uint16_t)value->payload;
    if (!link || link > context->node_used) return 0;
    node = &context->nodes[link - 1u];
    if (node->kind == PYZ80_TARGET_NODE_FREE ||
        node->generation != (uint16_t)(value->payload >> 16)) return 0;
    return node;
}

#define node_from_value PyZ80Target_Node

/* Разделение плоских полей и пар словаря исключает взаимную C-рекурсию. */
static uint8_t field_find(PyZ80TargetContext *, const PyZ80VMValue *, uint16_t, PyZ80VMValue *);
static uint8_t field_store(PyZ80TargetContext *, const PyZ80VMValue *, uint16_t, const PyZ80VMValue *);

static uint8_t dict_key(const PyZ80VMValue *key)
{
    return key && (key->kind==PYZ80_VM_VALUE_NONE || key->kind==PYZ80_VM_VALUE_I32 ||
        (key->kind==PYZ80_VM_VALUE_BOOL && key->payload<=1u) ||
        (key->kind==PYZ80_VM_VALUE_SYMBOL && key->symbol!=PYZ80_VM_NO_SYMBOL));
}

static uint8_t dict_equal(const PyZ80VMValue *left, const PyZ80VMValue *right)
{
    /* bool и int имеют одинаковые ключи при одинаковом числовом значении. */
    if((left->kind==PYZ80_VM_VALUE_I32 || left->kind==PYZ80_VM_VALUE_BOOL) &&
       (right->kind==PYZ80_VM_VALUE_I32 || right->kind==PYZ80_VM_VALUE_BOOL)) return left->payload==right->payload;
    if(left->kind!=right->kind) return 0u;
    return left->kind==PYZ80_VM_VALUE_NONE || left->symbol==right->symbol;
}

static uint8_t dict_valid(PyZ80TargetContext *context, const PyZ80TargetNode *node)
{
    uint16_t link,count=0u;
    if(!node || node->kind!=PYZ80_TARGET_NODE_DICT || node->reserved>1u) return 0u;
    if(node->reserved) {
        return !node->field_head && node->cursor<=32767u && node->item_count==node->cursor*2u &&
            node->source_link>=node->item_count && context->item_used<=context->item_capacity &&
            node->item_start<=context->item_used && node->source_link<=context->item_used-node->item_start &&
            (!node->source_link || context->items);
    }
    if(context->field_used>context->field_capacity || (context->field_used && !context->fields)) return 0u;
    link=node->field_head;
    while(link) {
        if(link>context->field_used || count>=context->field_used || context->fields[link-1u].key==PYZ80_VM_NO_SYMBOL) return 0u;
        ++count;link=context->fields[link-1u].next;
    }
    return count==node->cursor;
}

uint8_t PyZ80Target_DefaultDictParts(PyZ80TargetContext *context,const PyZ80TargetNode *node,PyZ80VMValue **parts)
{
    if(!context || !node || !parts || node->kind!=PYZ80_TARGET_NODE_DEFAULTDICT || node->item_count!=2u ||
       node->field_head || node->reserved || node->has_current || !context->items ||
       context->item_used>context->item_capacity || node->item_start>context->item_used ||
       2u>context->item_used-node->item_start)return 0u;
    *parts=&context->items[node->item_start];
    return dict_valid(context,node_from_value(context,*parts));
}

uint8_t PyZ80Target_Mapping(PyZ80TargetContext *context,const PyZ80VMValue *value,PyZ80VMValue *mapping)
{
    PyZ80TargetNode *node=node_from_value(context,value);
    PyZ80VMValue *parts;
    if(!mapping)return 0u;
    if(node && node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
        if(!PyZ80Target_DefaultDictParts(context,node,&parts))return 0u;
        *mapping=parts[0];return 1u;
    }
    if(!dict_valid(context,node))return 0u;
    *mapping=*value;return 1u;
}

uint8_t PyZ80Target_CreateDefaultDict(PyZ80TargetContext *context,const PyZ80VMValue *factory,PyZ80VMValue *result)
{
    PyZ80TargetNode *node;PyZ80VMValue mapping,saved;
    if(!context || !factory || !result || !context->items || context->item_used>context->item_capacity ||
       2u>context->item_capacity-context->item_used)return 0u;
    saved=*factory;
    if(!PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_DICT,65535u,&mapping) ||
       !PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_DEFAULTDICT,65535u,result))return 0u;
    node=node_from_value(context,result);node->item_start=context->item_used;node->item_count=2u;
    context->items[context->item_used++]=mapping;context->items[context->item_used++]=saved;
    return 1u;
}

uint8_t PyZ80Target_NativeName(PyZ80TargetContext *context,uint16_t key,uint8_t operation)
{
    uint16_t i;
    if(!context || !context->builtin_symbols || key==65535u)return 0u;
    for(i=0u;i<context->builtin_symbol_count;++i)
        if(context->builtin_symbols[i].symbol==key && context->builtin_symbols[i].operation==operation)return 1u;
    return 0u;
}

uint8_t PyZ80Target_DictFind(PyZ80TargetContext *context, const PyZ80VMValue *dictionary,
    const PyZ80VMValue *key, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;PyZ80VMValue mapping;
    uint16_t index;
    if(!PyZ80Target_Mapping(context,dictionary,&mapping))return 0u;
    dictionary=&mapping;node=node_from_value(context,dictionary);
    if(!result || !dict_key(key) || !dict_valid(context,node)) return 0u;
    if(!node->reserved) return key->kind==PYZ80_VM_VALUE_SYMBOL ?
        field_find(context,dictionary,key->symbol,result) : 2u;
    for(index=0u;index<node->item_count;index+=2u) {
        const PyZ80VMValue *stored=&context->items[node->item_start+index];
        if(!dict_key(stored)) return 0u;
        if(dict_equal(stored,key)) { *result=stored[1];return 1u; }
    }
    return 2u;
}

uint8_t PyZ80Target_DictStore(PyZ80TargetContext *context, const PyZ80VMValue *dictionary,
    const PyZ80VMValue *key, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node;
    PyZ80VMValue saved_key,saved_value,mapping;
    uint16_t index,extent,capacity,start,link;
    if(!PyZ80Target_Mapping(context,dictionary,&mapping))return 0u;
    dictionary=&mapping;node=node_from_value(context,dictionary);
    if(!value || !dict_key(key) || !dict_valid(context,node)) return 0u;
    if(!node->reserved && key->kind==PYZ80_VM_VALUE_SYMBOL)
        return field_store(context,dictionary,key->symbol,value);
    saved_key=*key;saved_value=*value;
    if(node->reserved) {
        for(index=0u;index<node->item_count;index+=2u) {
            PyZ80VMValue *stored=&context->items[node->item_start+index];
            if(!dict_key(stored)) return 0u;
            if(dict_equal(stored,key)) { stored[1]=saved_value;return 1u; }
        }
    }
    if(node->current.payload==0xffffffffUL || node->cursor>=32767u || context->item_used>context->item_capacity || !context->items) return 0u;
    extent=node->cursor*2u; /* SHL.U16: две записи Value на один ключ. */
    if(!node->reserved || node->source_link-extent<2u) {
        capacity=extent>32767u ? 65534u : (extent ? extent*2u : 8u);
        if(capacity>context->item_capacity-context->item_used) capacity=extent+2u;
        if(capacity>context->item_capacity-context->item_used) return 0u;
        start=context->item_used;
        /* После проверки ёмкости копирование не вызывает Python и не может
           отказать. Старые поля/пары освобождаются очередным проходом GC. */
        if(node->reserved) {
            for(index=0u;index<extent;++index) context->items[start+index]=context->items[node->item_start+index];
        } else {
            link=node->field_head;
            for(index=0u;index<extent;index+=2u) {
                PyZ80VMValue *stored=&context->items[start+index];
                value_none(stored);stored->kind=PYZ80_VM_VALUE_SYMBOL;stored->symbol=context->fields[link-1u].key;
                stored[1]=context->fields[link-1u].value;link=context->fields[link-1u].next;
            }
        }
        context->item_used+=capacity;node->item_start=start;node->source_link=capacity;
        node->field_head=0u;node->reserved=1u;
    }
    context->items[node->item_start+extent]=saved_key;context->items[node->item_start+extent+1u]=saved_value;
    ++node->cursor;node->item_count=extent+2u; /* INC ключей / ADD.U16 двух Value. */
    ++node->current.payload; /* INC.U32: изменился набор ключей, не только значение. */
    return 1u;
}

uint8_t PyZ80Target_DictRemove(PyZ80TargetContext *context, const PyZ80VMValue *dictionary,
    const PyZ80VMValue *key, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    PyZ80VMValue removed,mapping;
    uint16_t index,link,previous=0u;
    uint8_t found=PyZ80Target_DictFind(context,dictionary,key,&removed);
    if(!result || found!=1u) return result ? found : 0u;
    if(!PyZ80Target_Mapping(context,dictionary,&mapping))return 0u;
    dictionary=&mapping;node=node_from_value(context,dictionary);
    if(node->current.payload==0xffffffffUL) return 0u;
    if(node->reserved) {
        for(index=0u;index<node->item_count;index+=2u)
            if(dict_equal(&context->items[node->item_start+index],key)) break;
        for(;index+2u<node->item_count;++index)
            context->items[node->item_start+index]=context->items[node->item_start+index+2u];
        node->item_count-=2u; /* SUB.U16: удаление пары с сохранением порядка остальных. */
    } else {
        link=node->field_head;
        while(context->fields[link-1u].key!=key->symbol) {
            previous=link;link=context->fields[link-1u].next;
        }
        if(previous) context->fields[previous-1u].next=context->fields[link-1u].next;
        else node->field_head=context->fields[link-1u].next;
    }
    --node->cursor; ++node->current.payload; /* DEC.U16 длины / INC.U32 версии. */
    *result=removed;
    return 1u;
}

uint8_t PyZ80Target_DictClear(PyZ80TargetContext *context, const PyZ80VMValue *dictionary)
{
    PyZ80TargetNode *node;PyZ80VMValue mapping;
    if(!PyZ80Target_Mapping(context,dictionary,&mapping))return 0u;
    node=node_from_value(context,&mapping);
    if(!dict_valid(context,node)) return 0u;
    if(!node->cursor) return 1u;
    if(node->current.payload==0xffffffffUL) return 0u;
    node->cursor=0u;node->item_count=0u;node->field_head=0u;
    ++node->current.payload; /* INC.U32: все aliases по-прежнему ссылаются на тот же dict. */
    return 1u;
}

uint8_t PyZ80Target_DictView(PyZ80TargetContext *context, const PyZ80VMValue *dictionary,
    uint8_t mode, PyZ80VMValue *result)
{
    PyZ80VMValue owner,mapping;
    if(!result || mode>2u || !PyZ80Target_Mapping(context,dictionary,&mapping)) return 0u;
    owner=*dictionary;
    if(!PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_DICT_VIEW,mode,result)) return 0u;
    node_from_value(context,result)->current=owner;
    return 1u;
}

static uint8_t list_valid(PyZ80TargetContext *context, const PyZ80TargetNode *node)
{
    return node && node->kind==PYZ80_TARGET_NODE_LIST &&
        context->item_used<=context->item_capacity && node->item_count<=node->cursor &&
        node->item_start<=context->item_used && node->cursor<=context->item_used-node->item_start &&
        (!node->cursor || context->items);
}

static uint8_t set_valid(PyZ80TargetContext *context, const PyZ80TargetNode *node)
{
    return node && node->kind==PYZ80_TARGET_NODE_SET && node->reserved<=1u && !node->field_head &&
        context->item_used<=context->item_capacity && node->item_count<=node->cursor &&
        node->item_start<=context->item_used && node->cursor<=context->item_used-node->item_start &&
        (!node->cursor || context->items);
}

static int8_t set_key_order(const PyZ80VMValue *left, const PyZ80VMValue *right)
{
    uint8_t a=left->kind==PYZ80_VM_VALUE_NONE ? 0u : left->kind==PYZ80_VM_VALUE_SYMBOL ? 2u : 1u;
    uint8_t b=right->kind==PYZ80_VM_VALUE_NONE ? 0u : right->kind==PYZ80_VM_VALUE_SYMBOL ? 2u : 1u;
    if(a!=b) return a<b ? -1 : 1;
    if(a==0u) return 0;
    if(a==2u) return left->symbol==right->symbol ? 0 : left->symbol<right->symbol ? -1 : 1;
    return left->payload==right->payload ? 0 : (int32_t)left->payload<(int32_t)right->payload ? -1 : 1;
}

static uint8_t set_position(PyZ80TargetContext *context, const PyZ80TargetNode *node,
    const PyZ80VMValue *key, uint16_t *position)
{
    uint16_t lo=0u,hi,mid;
    int8_t order;
    if(!set_valid(context,node) || !dict_key(key)) return 0u;
    hi=node->item_count;
    /* Двоичный поиск O(log n); внутренний порядок не выдаётся Python-итератором. */
    while(lo<hi) {
        const PyZ80VMValue *stored;
        mid=lo+((hi-lo)>>1); /* SUB.U16 / SHR / ADD: середина без переполнения. */
        stored=&context->items[node->item_start+mid];
        if(!dict_key(stored)) return 0u;
        order=set_key_order(stored,key);
        if(!order) { *position=mid;return 1u; }
        if(order<0) lo=mid+1u;
        else hi=mid;
    }
    *position=lo;
    return 2u;
}

uint8_t PyZ80Target_SetFind(PyZ80TargetContext *context, const PyZ80VMValue *set, const PyZ80VMValue *key)
{
    uint16_t position;
    return set_position(context,node_from_value(context,set),key,&position);
}

uint8_t PyZ80Target_SetAdd(PyZ80TargetContext *context, const PyZ80VMValue *set, const PyZ80VMValue *key)
{
    PyZ80TargetNode *node=node_from_value(context,set);
    PyZ80VMValue saved;
    uint16_t index,start,capacity,position;
    uint8_t found=set_position(context,node,key,&position);
    if(!found || node->reserved) return 0u;
    if(found==1u) return 1u;
    if(node->item_count==65535u || !context->items) return 0u;
    saved=*key;
    if(node->item_count==node->cursor) {
        capacity=node->cursor>32767u ? 65535u : (node->cursor ? node->cursor*2u : 4u);
        if(capacity>context->item_capacity-context->item_used) capacity=node->item_count+1u;
        if(capacity>context->item_capacity-context->item_used) return 0u;
        start=context->item_used;
        for(index=0u;index<node->item_count;++index) context->items[start+index]=context->items[node->item_start+index];
        context->item_used+=capacity; /* ADD.U16: полный резерв проверен до изменения объекта. */
        node->item_start=start;node->cursor=capacity;
    }
    for(index=node->item_count;index>position;--index) context->items[node->item_start+index]=context->items[node->item_start+index-1u];
    context->items[node->item_start+position]=saved;
    ++node->item_count; /* INC.U16: новый ключ, без дубликатов bool/int. */
    return 1u;
}

uint8_t PyZ80Target_SetRemove(PyZ80TargetContext *context, const PyZ80VMValue *set, const PyZ80VMValue *key, uint8_t discard)
{
    PyZ80TargetNode *node=node_from_value(context,set);
    uint16_t index;
    uint8_t found=set_position(context,node,key,&index);
    if(!found || node->reserved) return 0u;
    if(found==2u) return discard!=0u;
    --node->item_count; /* DEC.U16 / сдвиг хвоста: сохраняется внутренний индекс. */
    for(;index<node->item_count;++index) context->items[node->item_start+index]=context->items[node->item_start+index+1u];
    return 1u;
}

uint8_t PyZ80Target_SetClear(PyZ80TargetContext *context, const PyZ80VMValue *set)
{
    PyZ80TargetNode *node=node_from_value(context,set);
    if(!set_valid(context,node) || node->reserved) return 0u;
    node->item_count=0u;
    return 1u;
}

uint8_t PyZ80Target_SetFrom(PyZ80TargetContext *context, const PyZ80VMValue *source, uint8_t frozen, PyZ80VMValue *result)
{
    PyZ80TargetNode *node=source ? node_from_value(context,source) : 0;
    PyZ80VMValue value,created,mapping;
    uint32_t length=0u,step=0u;
    uint16_t index,link=0u;
    if(!result || frozen>1u) return 0u;
    if(source) {
        if(!node || !PyZ80Target_Length(context,source,&length)) return 0u;
        if(node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
            if(!PyZ80Target_Mapping(context,source,&mapping))return 0u;
            node=node_from_value(context,&mapping);
        }
        if(node->kind!=PYZ80_TARGET_NODE_LIST && node->kind!=PYZ80_TARGET_NODE_TUPLE &&
           node->kind!=PYZ80_TARGET_NODE_SET && node->kind!=PYZ80_TARGET_NODE_DICT && node->kind!=PYZ80_TARGET_NODE_RANGE)return 0u;
        if(node->kind==PYZ80_TARGET_NODE_SET && node->reserved && frozen) { *result=*source;return 1u; }
        if(node->kind==PYZ80_TARGET_NODE_DICT) link=node->field_head;
        if(node->kind==PYZ80_TARGET_NODE_RANGE) {
            value=node->current;step=((uint32_t)node->item_count<<16)|node->item_start;
        }
    }
    if(!PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_SET,65535u,&created)) return 0u;
    for(index=0u;index<length;++index) {
        if(node->kind==PYZ80_TARGET_NODE_DICT) {
            if(node->reserved) value=context->items[node->item_start+index*2u];
            else {
                value_none(&value);value.kind=PYZ80_VM_VALUE_SYMBOL;
                value.symbol=context->fields[link-1u].key;link=context->fields[link-1u].next;
            }
        } else if(node->kind!=PYZ80_TARGET_NODE_RANGE) value=context->items[node->item_start+index];
        if(!PyZ80Target_SetAdd(context,&created,&value)) return 0u;
        if(node->kind==PYZ80_TARGET_NODE_RANGE) value.payload+=step; /* ADD.U32: очередной range, без умножения. */
    }
    node_from_value(context,&created)->reserved=frozen;
    *result=created;
    return 1u;
}

static uint8_t set_compare(PyZ80TargetContext *context, uint8_t operation,
    const PyZ80VMValue *left, const PyZ80VMValue *right, PyZ80VMValue *result)
{
    PyZ80TargetNode *a=node_from_value(context,left), *b=node_from_value(context,right);
    uint16_t index;
    uint8_t found,subset=1u,answer;
    if(!set_valid(context,a) || !set_valid(context,b)) {
        const PyZ80VMValue *other=(a && a->kind==PYZ80_TARGET_NODE_SET) ? right : left;
        PyZ80TargetNode *node=node_from_value(context,other);
        if((operation!=PYZ80_TARGET_OP_EQ && operation!=PYZ80_TARGET_OP_NE) ||
            !((set_valid(context,a) && (!b || b->kind!=PYZ80_TARGET_NODE_SET)) ||
              (set_valid(context,b) && (!a || a->kind!=PYZ80_TARGET_NODE_SET)))) return 0u;
        if(other->kind>PYZ80_VM_VALUE_SYMBOL && (!node || (node->kind!=PYZ80_TARGET_NODE_LIST &&
            node->kind!=PYZ80_TARGET_NODE_TUPLE && node->kind!=PYZ80_TARGET_NODE_DICT && node->kind!=PYZ80_TARGET_NODE_RANGE))) return 0u;
        value_none(result);result->kind=PYZ80_VM_VALUE_BOOL;result->payload=operation==PYZ80_TARGET_OP_NE;
        return 1u; /* Разные встроенные типы; пользовательский __eq__ не обходится. */
    }
    if(operation==PYZ80_TARGET_OP_GT || operation==PYZ80_TARGET_OP_GE) {
        const PyZ80VMValue *swap=left;PyZ80TargetNode *other=a;
        left=right;right=swap;a=b;b=other;
        operation=operation==PYZ80_TARGET_OP_GT ? PYZ80_TARGET_OP_LT : PYZ80_TARGET_OP_LE;
    }
    if(operation!=PYZ80_TARGET_OP_EQ && operation!=PYZ80_TARGET_OP_NE && operation!=PYZ80_TARGET_OP_LT && operation!=PYZ80_TARGET_OP_LE) return 0u;
    for(index=0u;index<a->item_count;++index) {
        found=PyZ80Target_SetFind(context,right,&context->items[a->item_start+index]);
        if(!found) return 0u;
        if(found==2u) { subset=0u;break; }
    }
    answer=subset && (operation==PYZ80_TARGET_OP_LT ? a->item_count<b->item_count :
        (operation==PYZ80_TARGET_OP_LE || a->item_count==b->item_count));
    if(operation==PYZ80_TARGET_OP_NE) answer=!answer;
    value_none(result);result->kind=PYZ80_VM_VALUE_BOOL;result->payload=answer;
    return 1u;
}

static uint8_t set_binary(PyZ80TargetContext *context, uint8_t operation, uint8_t inplace,
    const PyZ80VMValue *left, const PyZ80VMValue *right, PyZ80VMValue *result)
{
    PyZ80TargetNode *a=node_from_value(context,left), *b=node_from_value(context,right), *out;
    PyZ80VMValue created;
    uint16_t index;
    uint8_t found;
    if(!set_valid(context,a) || !set_valid(context,b) ||
        (operation!=PYZ80_TARGET_OP_SUB && operation!=PYZ80_TARGET_OP_BITAND &&
         operation!=PYZ80_TARGET_OP_BITOR && operation!=PYZ80_TARGET_OP_BITXOR)) return 0u;
    if(!PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_SET,65535u,&created)) return 0u;
    for(index=0u;index<a->item_count;++index) {
        const PyZ80VMValue *key=&context->items[a->item_start+index];
        found=PyZ80Target_SetFind(context,right,key);
        if(!found) return 0u;
        if(operation==PYZ80_TARGET_OP_BITOR || (operation==PYZ80_TARGET_OP_BITAND ? found==1u : found==2u))
            if(!PyZ80Target_SetAdd(context,&created,key)) return 0u;
    }
    if(operation==PYZ80_TARGET_OP_BITOR || operation==PYZ80_TARGET_OP_BITXOR) {
        for(index=0u;index<b->item_count;++index) {
            const PyZ80VMValue *key=&context->items[b->item_start+index];
            found=PyZ80Target_SetFind(context,left,key);
            if(!found) return 0u;
            if((operation==PYZ80_TARGET_OP_BITOR || found==2u) && !PyZ80Target_SetAdd(context,&created,key)) return 0u;
        }
    }
    out=node_from_value(context,&created);out->reserved=a->reserved;
    if(inplace && !a->reserved) {
        a->item_start=out->item_start;a->item_count=out->item_count;a->cursor=out->cursor;
        out->item_count=out->cursor=0u;out->item_start=0u;
        *result=*left; /* Сохраняется объект и все его aliases; commit после полного успеха. */
    } else *result=created;
    return 1u;
}

static uint8_t native_owner_valid(PyZ80TargetContext *context, const PyZ80TargetNode *owner, uint16_t operation)
{
    PyZ80VMValue *parts;
    if(operation==PYZ80_BUILTIN_DEFAULTDICT_MISSING)return PyZ80Target_DefaultDictParts(context,owner,&parts);
    if(operation>=PYZ80_BUILTIN_DEQUE_APPEND && operation<=PYZ80_BUILTIN_DEQUE_CLEAR)
        return PyZ80Target_DequeValid(context,owner);
    if(operation==PYZ80_BUILTIN_DICT_GET || (operation>=PYZ80_BUILTIN_DICT_POP && operation<=PYZ80_BUILTIN_DICT_ITEMS))
        return owner && owner->kind==PYZ80_TARGET_NODE_DEFAULTDICT ?
            PyZ80Target_DefaultDictParts(context,owner,&parts) : dict_valid(context,owner);
    if((operation>=PYZ80_BUILTIN_LIST_APPEND && operation<=PYZ80_BUILTIN_LIST_POP) ||
       operation==PYZ80_BUILTIN_LIST_EXTEND) return list_valid(context,owner);
    return operation>=PYZ80_BUILTIN_SET_ADD && operation<=PYZ80_BUILTIN_SET_CLEAR &&
        set_valid(context,owner) && !owner->reserved;
}

uint8_t PyZ80Target_NativeMethodValid(PyZ80TargetContext *context, const PyZ80TargetNode *method)
{
    PyZ80TargetNode *owner;
    if(!method || method->kind!=PYZ80_TARGET_NODE_NATIVE_METHOD) return 0u;
    owner=node_from_value(context,&method->current);
    return native_owner_valid(context,owner,method->class_symbol);
}

uint8_t PyZ80Target_UnwrapCallable(PyZ80TargetContext *context, const PyZ80VMValue *value,
    PyZ80VMValue *prototype, PyZ80VMValue *receiver)
{
    PyZ80TargetNode *node = node_from_value(context, value);
    uint16_t remaining=context ? context->node_used : 0u;
    while(node && node->kind==PYZ80_TARGET_NODE_STATICMETHOD) {
        if(!remaining-- || node->reserved || node->item_count || node->field_head)return 0u;
        value=&node->current;node=node_from_value(context,value);
    }
    if (!node || !prototype || !receiver || node->kind != PYZ80_TARGET_NODE_CALLABLE ||
        node->reserved > 3u || node->class_symbol >= context->function_count) return 0u;
    *prototype = *value;
    value_none(receiver);
    if (node->reserved == 1u) *receiver = node->current;
    else if (node->reserved == 3u) {
        uint16_t function = node->class_symbol;
        *prototype = node->current;
        receiver->kind = PYZ80_VM_VALUE_OPAQUE;
        receiver->payload = ((uint32_t)node->source_generation << 16) | node->source_link;
        node = node_from_value(context, prototype);
        if (!node || node->kind != PYZ80_TARGET_NODE_CALLABLE ||
            (node->reserved != 0u && node->reserved != 2u) || node->class_symbol != function) return 0u;
    }
    return receiver->kind == PYZ80_VM_VALUE_NONE || node_from_value(context, receiver) != 0;
}

uint8_t PyZ80Target_BindMethod(PyZ80TargetContext *context, const PyZ80VMValue *function,
    const PyZ80VMValue *receiver, PyZ80VMValue *result)
{
    PyZ80TargetNode *node = node_from_value(context, function);
    PyZ80VMValue saved_function, saved_receiver;
    if (!node || node->kind != PYZ80_TARGET_NODE_CALLABLE || (node->reserved != 0u && node->reserved != 2u) ||
        !node_from_value(context, receiver)) return 0u;
    saved_function = *function; saved_receiver = *receiver;
    if (!PyZ80Target_Callable(context, node->class_symbol, 0, result)) return 0u;
    node = node_from_value(context, result);
    node->reserved = 3u; node->current = saved_function;
    node->source_link = (uint16_t)saved_receiver.payload;
    node->source_generation = (uint16_t)(saved_receiver.payload >> 16);
    return 1u;
}

uint8_t PyZ80Target_FindAttribute(PyZ80TargetContext *context,
    const PyZ80VMValue *object, uint16_t key, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    if (!context || !object || !result || key == PYZ80_VM_NO_SYMBOL) return 0u;
    if(object->kind==PYZ80_VM_VALUE_NONE) {
        uint16_t i;uint8_t sealed=0u;
        if(!context->builtin_provider || !context->builtin_symbols)return 0u;
        for(i=0u;i<context->builtin_symbol_count;++i)if(context->builtin_symbols[i].operation==PYZ80_NONE_ATTRIBUTE_KNOWN) {
            if(context->builtin_symbols[i].symbol==key)return 0u; /* Существующий, но ещё не связанный протокол. */
            if(context->builtin_symbols[i].symbol==65535u)sealed=1u;
        }
        return sealed ? 2u : 0u; /* Только доказанное отсутствие разрешает getattr default. */
    }
    node = node_from_value(context, object);
    if(node && node->kind==PYZ80_TARGET_NODE_DEFAULTDICT && PyZ80Target_NativeName(context,key,PYZ80_DEFAULT_FACTORY_ATTRIBUTE)) {
        PyZ80VMValue *parts;
        if(!PyZ80Target_DefaultDictParts(context,node,&parts))return 0u;
        *result=parts[1];return 1u;
    }
    if (node && (node->kind == PYZ80_TARGET_NODE_DICT || node->kind==PYZ80_TARGET_NODE_DEFAULTDICT || node->kind==PYZ80_TARGET_NODE_SET || node->kind==PYZ80_TARGET_NODE_LIST || node->kind==PYZ80_TARGET_NODE_DEQUE)) {
        uint16_t index;
        PyZ80VMValue owner=*object;
        if(!context->builtin_provider || !context->builtin_symbols) return 0u;
        for(index=0u;index<context->builtin_symbol_count;++index) {
            uint8_t operation=context->builtin_symbols[index].operation;
            if(context->builtin_symbols[index].symbol==key &&
                native_owner_valid(context,node,operation)) {
                if(!PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_NATIVE_METHOD,operation,result)) return 0u;
                node_from_value(context,result)->current=owner;
                return 1u;
            }
        }
        return 0u; /* Остальные протоколы dict пока не заменяются обычными полями. */
    }
    if (node && node->kind == PYZ80_TARGET_NODE_CALLABLE) {
        PyZ80VMValue prototype, receiver, annotations;
        uint8_t found;
        if (!context->class_symbols || key != context->class_symbols[47] ||
            !PyZ80Target_UnwrapCallable(context, object, &prototype, &receiver)) return 0u;
        /* Bound methods expose the function's dictionary, never a copy. */
        found = PyZ80Target_FindField(context, &prototype, key, &annotations);
        if (!found) return 0u;
        if (found == 2u || annotations.kind == PYZ80_VM_VALUE_NONE) {
            if (!PyZ80Target_AllocateNode(context, PYZ80_TARGET_NODE_DICT, 65535u, &annotations) ||
                !PyZ80Target_StoreField(context, &prototype, key, &annotations)) return 0u;
        }
        *result = annotations;
        return 1u;
    }
    if ((node && (node->kind == PYZ80_TARGET_NODE_CLASS || node->kind == PYZ80_TARGET_NODE_INSTANCE || node->kind == PYZ80_TARGET_NODE_SUPER)) ||
        (object && object->kind == PYZ80_VM_VALUE_BUILTIN && object->payload == PYZ80_BUILTIN_OBJECT))
        return context->class_attribute ? context->class_attribute(context->class_context, object, key, result) : 0u;
    return PyZ80Target_FindField(context, object, key, result);
}

uint8_t PyZ80Target_AllocateNode(
    PyZ80TargetContext *context, uint8_t kind, uint16_t class_symbol,
    PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    uint16_t index;
    uint16_t generation;
    if (context == 0 || context->nodes == 0 || result == 0 ||
        context->node_used > context->node_capacity ||
        kind == PYZ80_TARGET_NODE_FREE || kind > PYZ80_TARGET_NODE_STATICMETHOD)
        return 0u;
    if (context->free_node_head) {
        index = context->free_node_head - 1u;
        if (index >= context->node_used || context->nodes[index].kind != PYZ80_TARGET_NODE_FREE ||
            context->nodes[index].generation == 65535u) return 0u;
        context->free_node_head = context->nodes[index].field_head;
    } else {
        if (context->node_used == context->node_capacity) return 0u;
        index = context->node_used++;
    }
    node = &context->nodes[index];
    generation = node->generation + 1u; /* INC.U16 generation; exhausted slots never enter free list. */
    memset(node, 0, sizeof(*node));
    node->kind = kind;
    node->generation = generation;
    node->class_symbol = class_symbol;
    result->kind = kind == PYZ80_TARGET_NODE_CELL ? PYZ80_VM_VALUE_CELL : PYZ80_VM_VALUE_OPAQUE;
    result->reserved = 0u;
    result->symbol = class_symbol;
    result->payload = ((uint32_t)generation << 16) | (index + 1u);
    return 1u;
}

#define allocate_node PyZ80Target_AllocateNode

uint8_t PyZ80Target_FindField(
    PyZ80TargetContext *context, const PyZ80VMValue *object,
    uint16_t key, PyZ80VMValue *result)
{
    PyZ80TargetNode *node = node_from_value(context, object);
    if(node && node->kind==PYZ80_TARGET_NODE_DICT && node->reserved) {
        PyZ80VMValue key_value;
        value_none(&key_value);key_value.kind=PYZ80_VM_VALUE_SYMBOL;key_value.symbol=key;
        return PyZ80Target_DictFind(context,object,&key_value,result);
    }
    return field_find(context,object,key,result);
}

static uint8_t field_find(PyZ80TargetContext *context, const PyZ80VMValue *object,
    uint16_t key, PyZ80VMValue *result)
{
    PyZ80TargetNode *node=node_from_value(context,object);
    uint16_t link,remaining;
    if (node == 0 || (node->kind != PYZ80_TARGET_NODE_OBJECT && node->kind != PYZ80_TARGET_NODE_INSTANCE && node->kind != PYZ80_TARGET_NODE_DICT &&
        !(node->kind == PYZ80_TARGET_NODE_CALLABLE && (node->reserved == 0u || node->reserved == 2u))) || result == 0 ||
        context->field_used > context->field_capacity ||
        (context->field_used && context->fields == 0))
        return 0u;
    link = node->field_head;
    remaining = context->field_used;
    while (link) {
        PyZ80TargetField *field;
        if (!remaining || link > context->field_used) return 0u;
        --remaining;
        field = &context->fields[link - 1u];
        if (field->key == key) {
            *result = field->value;
            return 1u;
        }
        link = field->next;
    }
    return 2u;
}

uint8_t PyZ80Target_LoadField(PyZ80TargetContext *context,
    const PyZ80VMValue *object, uint16_t key, PyZ80VMValue *result)
{
    return PyZ80Target_FindField(context, object, key, result) == 1u;
}

uint8_t PyZ80Target_Length(PyZ80TargetContext *context,
    const PyZ80VMValue *value, uint32_t *length)
{
    PyZ80TargetNode *node = node_from_value(context, value);
    if (node == 0 || length == 0) return 0u;
    if (node->kind == PYZ80_TARGET_NODE_RANGE) {
        if (node->current.kind != PYZ80_VM_VALUE_I32 || !(node->item_start || node->item_count)) return 0u;
        *length = node->cursor;
    } else if (node->kind == PYZ80_TARGET_NODE_LIST || node->kind == PYZ80_TARGET_NODE_TUPLE) {
        if (context->item_used > context->item_capacity || node->item_start > context->item_used ||
            node->item_count > context->item_used - node->item_start ||
            (node->item_count && context->items == 0)) return 0u;
        *length = node->item_count;
    } else if (PYZ80_IS_BUFFER(node)) {
        if(!PyZ80Target_BufferValid(context,node))return 0u;
        *length=node->item_count;
    } else if (node->kind == PYZ80_TARGET_NODE_DEQUE) {
        if(!PyZ80Target_DequeValid(context,node))return 0u;
        *length=node->item_count;
    } else if (node->kind == PYZ80_TARGET_NODE_SET) {
        if(!set_valid(context,node)) return 0u;
        *length=node->item_count;
    } else if (node->kind == PYZ80_TARGET_NODE_DICT || node->kind == PYZ80_TARGET_NODE_DICT_VIEW || node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
        PyZ80VMValue *parts;
        if(node->kind==PYZ80_TARGET_NODE_DICT_VIEW) {
            if(node->class_symbol>2u) return 0u;
            node=node_from_value(context,&node->current);
        }
        if(node && node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
            if(!PyZ80Target_DefaultDictParts(context,node,&parts))return 0u;
            node=node_from_value(context,parts);
        }
        if(!dict_valid(context,node)) return 0u;
        *length = node->cursor;
    }
    else return 0u;
    return 1u;
}

uint8_t PyZ80Target_Callable(
    PyZ80TargetContext *context, uint16_t function,
    const PyZ80VMValue *receiver, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    PyZ80VMValue saved_receiver;
    if (context == 0 || result == 0 || function >= context->function_count)
        return 0u;
    if (receiver != 0 && receiver->kind != PYZ80_VM_VALUE_NONE &&
        node_from_value(context, receiver) == 0) return 0u;
    value_none(&saved_receiver);
    if (receiver != 0) saved_receiver = *receiver;
    if (!allocate_node(context, PYZ80_TARGET_NODE_CALLABLE, function, result))
        return 0u;
    node = node_from_value(context, result);
    value_none(&node->current);
    if (saved_receiver.kind != PYZ80_VM_VALUE_NONE) {
        node->reserved = 1u;
        node->current = saved_receiver;
    }
    return 1u;
}

uint8_t PyZ80Target_StoreField(
    PyZ80TargetContext *context, const PyZ80VMValue *object,
    uint16_t key, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node = node_from_value(context, object);
    if(node && node->kind==PYZ80_TARGET_NODE_DICT && node->reserved) {
        PyZ80VMValue key_value;
        value_none(&key_value);key_value.kind=PYZ80_VM_VALUE_SYMBOL;key_value.symbol=key;
        return PyZ80Target_DictStore(context,object,&key_value,value);
    }
    return field_store(context,object,key,value);
}

static uint8_t field_store(PyZ80TargetContext *context, const PyZ80VMValue *object,
    uint16_t key, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node=node_from_value(context,object);
    uint16_t link,remaining,tail=0u;
    PyZ80TargetField *field;
    if (node == 0 || (node->kind != PYZ80_TARGET_NODE_OBJECT && node->kind != PYZ80_TARGET_NODE_INSTANCE && node->kind != PYZ80_TARGET_NODE_DICT &&
        !(node->kind == PYZ80_TARGET_NODE_CALLABLE && (node->reserved == 0u || node->reserved == 2u))) || value == 0 ||
        context->field_used > context->field_capacity ||
        (context->field_capacity && context->fields == 0))
        return 0u;
    link = node->field_head;
    remaining = context->field_used;
    while (link) {
        if (!remaining || link > context->field_used) return 0u;
        --remaining;
        field = &context->fields[link - 1u];
        if (field->key == key) {
            field->value = *value;
            return 1u;
        }
        tail = link;
        link = field->next;
    }
    if (context->field_used >= context->field_capacity ||
        (node->kind==PYZ80_TARGET_NODE_DICT && (node->cursor==65535u || node->current.payload==0xffffffffUL || key==65535u))) return 0u;
    field = &context->fields[context->field_used];
    field->key = key;
    field->value = *value;
    ++context->field_used;
    if (node->kind == PYZ80_TARGET_NODE_DICT) {
        field->next = 0u;
        if (tail) context->fields[tail - 1u].next = context->field_used;
        else node->field_head = context->field_used;
        ++node->cursor; /* INC.U16: overwriting an existing key never moves it. */
        ++node->current.payload; /* INC.U32: новый ключ; перезапись значения версию не меняет. */
    } else {
        field->next = node->field_head;
        node->field_head = context->field_used;
    }
    return 1u;
}

uint8_t PyZ80Target_SetupAnnotations(PyZ80TargetContext *context,
    const PyZ80VMValue *mapping, uint16_t key)
{
    PyZ80VMValue annotations;
    uint8_t found = PyZ80Target_FindField(context, mapping, key, &annotations);
    if (found != 2u) return found == 1u;
    return PyZ80Target_AllocateNode(context, PYZ80_TARGET_NODE_DICT, 65535u, &annotations) &&
        PyZ80Target_StoreField(context, mapping, key, &annotations);
}

static uint8_t collection(
    PyZ80TargetContext *context, uint8_t kind,
    const PyZ80VMValue *arguments, uint8_t count, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    uint16_t index;
    if (context->item_used > context->item_capacity ||
        (count && (context->items == 0 || arguments == 0)) ||
        (uint16_t)(context->item_capacity - context->item_used) < count ||
        !allocate_node(context, kind, PYZ80_VM_NO_SYMBOL, result)) return 0u;
    node = node_from_value(context, result);
    if (node == 0) return 0u;
    node->item_start = context->item_used;
    node->item_count = count;
    node->cursor = count; /* Collection capacity; iterator cursor is separate. */
    for (index = 0u; index < count; ++index)
        context->items[context->item_used++] = arguments[index];
    return 1u;
}

static uint8_t list_append(PyZ80TargetContext *context,
    const PyZ80VMValue *list, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node = node_from_value(context, list);
    PyZ80VMValue saved;
    uint16_t capacity;
    uint16_t index;
    uint16_t start;
    if (node == 0 || node->kind != PYZ80_TARGET_NODE_LIST || value == 0 ||
        context->item_used > context->item_capacity || context->items == 0 ||
        node->item_count > node->cursor || node->item_start > context->item_used ||
        node->cursor > context->item_used - node->item_start) return 0u;
    saved = *value; /* LD value before relocating a possibly aliased item slice. */
    if (node->item_count == node->cursor &&
        node->item_start+node->cursor==context->item_used && context->item_used<context->item_capacity) {
        /* Хвост общего arena можно нарастить без копирования всего списка.
           Особенно важно после GC, который оставляет только занятые элементы. */
        ++node->cursor;++context->item_used; /* INC.U16: место ровно для одного элемента. */
    } else if (node->item_count == node->cursor) {
        if (node->cursor == 65535u) return 0u;
        capacity = node->cursor > 32767u ? 65535u :
                   (node->cursor ? node->cursor * 2u : 4u); /* SHL.U16 capacity, 1; saturate */
        if (capacity > context->item_capacity - context->item_used) {
            capacity = node->item_count + 1u; /* ADD.U16 exact minimum after geometric growth fails */
            if (capacity > context->item_capacity - context->item_used) return 0u;
        }
        start = context->item_used;
        for (index = 0u; index < node->item_count; ++index)
            context->items[start + index] = context->items[node->item_start + index];
        context->item_used += capacity; /* ADD.U16 reserved slice, checked above */
        node->item_start = start;
        node->cursor = capacity;
    }
    context->items[node->item_start + node->item_count] = saved;
    ++node->item_count; /* INC.U16 logical list length */
    return 1u;
}

uint8_t PyZ80Target_StoreFields(
    PyZ80TargetContext *context, const PyZ80VMValue *object,
    const uint16_t *keys, const PyZ80VMValue *values, uint8_t count)
{
    PyZ80TargetNode *node = node_from_value(context, object);
    uint16_t link;
    uint16_t remaining;
    uint16_t missing = 0u;
    uint8_t index;
    uint8_t previous;
    uint8_t found;
    if (node == 0 || node->kind != PYZ80_TARGET_NODE_OBJECT ||
        (count && (keys == 0 || values == 0)) ||
        context->field_used > context->field_capacity ||
        (context->field_capacity && context->fields == 0)) return 0u;
    /* Preflight: validate the schema and bounded linked field chains first.
       A missing field consumes one arena slot; an overwrite consumes none. */
    for (index = 0u; index < count; ++index) {
        if (keys[index] == PYZ80_VM_NO_SYMBOL) return 0u;
        for (previous = 0u; previous < index; ++previous)
            if (keys[previous] == keys[index]) return 0u;
        link = node->field_head;
        remaining = context->field_used;
        found = 0u;
        while (link) {
            if (!remaining || link > context->field_used) return 0u;
            --remaining;
            if (context->fields[link - 1u].key == keys[index]) found = 1u;
            link = context->fields[link - 1u].next;
        }
        if (!found) ++missing;
    }
    if (missing > context->field_capacity - context->field_used) return 0u;
    /* Commit: the validated plain-field stores cannot fail or invoke user code. */
    for (index = 0u; index < count; ++index)
        if (!PyZ80Target_StoreField(context, object, keys[index], &values[index]))
            return 0u;
    return 1u;
}

static uint8_t collection_item(
    PyZ80TargetContext *context, const PyZ80VMValue *collection_value,
    const PyZ80VMValue *index_value, PyZ80VMValue **slot)
{
    PyZ80TargetNode *node = node_from_value(context, collection_value);
    int32_t index;
    if (node == 0 || (node->kind != PYZ80_TARGET_NODE_LIST &&
                      node->kind != PYZ80_TARGET_NODE_TUPLE) ||
        index_value == 0 || (index_value->kind != PYZ80_VM_VALUE_I32 &&
            !(index_value->kind==PYZ80_VM_VALUE_BOOL && index_value->payload<=1u)) ||
        context->item_used > context->item_capacity || context->items == 0 ||
        node->item_start > context->item_used ||
        node->item_count > context->item_used - node->item_start)
        return 0u;
    index = (int32_t)index_value->payload;
    if (index < 0) index += node->item_count;
    if (index < 0 || (uint32_t)index >= node->item_count) return 0u;
    *slot = &context->items[node->item_start + (uint16_t)index];
    return 1u;
}

uint8_t PyZ80Target_ListClear(PyZ80TargetContext *context, const PyZ80VMValue *list)
{
    PyZ80TargetNode *node=node_from_value(context,list);
    if(!list_valid(context,node)) return 0u;
    node->item_count=0u;
    return 1u;
}

uint8_t PyZ80Target_ListPop(PyZ80TargetContext *context, const PyZ80VMValue *list,
    const PyZ80VMValue *index_value, PyZ80VMValue *result)
{
    PyZ80TargetNode *node=node_from_value(context,list);
    PyZ80VMValue last,removed,*slot;
    uint16_t index;
    if(!result || !list_valid(context,node)) return 0u;
    value_none(&last);last.kind=PYZ80_VM_VALUE_I32;last.payload=0xffffffffUL;
    if(!collection_item(context,list,index_value ? index_value : &last,&slot)) return 0u;
    removed=*slot;index=(uint16_t)(slot-&context->items[node->item_start]);
    for(;index+1u<node->item_count;++index)
        context->items[node->item_start+index]=context->items[node->item_start+index+1u];
    --node->item_count; /* DEC.U16: сдвиг оставшихся элементов выполнен после проверки индекса. */
    *result=removed;
    return 1u;
}

uint8_t PyZ80Target_Operator(
    PyZ80TargetContext *context, const PyZ80VMValue *value, uint8_t *result)
{
    uint16_t index;
    if (!context || !result || !context->operators || value == 0 || value->kind != PYZ80_VM_VALUE_SYMBOL) return 0u;
    for (index = 0u; index < context->operator_count; ++index)
        if (context->operators[index].symbol == value->symbol) {
            *result = context->operators[index].operation;
            return 1u;
        }
    return 0u;
}

static uint8_t integer_binary(
    uint8_t operation, const PyZ80VMValue *left_value,
    const PyZ80VMValue *right_value, PyZ80VMValue *result)
{
    int32_t left;
    int32_t right;
    int32_t quotient;
    int32_t remainder;
    uint32_t accumulator;
    uint32_t temporary;
    uint32_t magnitude_left, magnitude_right, limit;
    uint8_t different_signs;
    uint8_t result_kind;
    uint8_t shift;
    /* Pseudo-instructions below describe the actual width and action.
       They are NOT single Z80 opcodes or promises about instruction timing.
       Unsigned registers wrap modulo 2^32; signed overflow is never executed. */
    if ((left_value->kind != PYZ80_VM_VALUE_I32 &&
         left_value->kind != PYZ80_VM_VALUE_BOOL) ||
        (right_value->kind != PYZ80_VM_VALUE_I32 &&
         right_value->kind != PYZ80_VM_VALUE_BOOL)) return 0u;
    left = (int32_t)left_value->payload;       /* LD.S32 left, operand[0] */
    right = (int32_t)right_value->payload;     /* LD.S32 right, operand[1] */
    different_signs = (left < 0) != (right < 0); /* XOR sign bits */
    result_kind = PYZ80_VM_VALUE_I32;
    if (operation == PYZ80_TARGET_OP_ADD) {
        accumulator = (uint32_t)left;         /* LD.U32 acc, left bits */
        accumulator += (uint32_t)right;       /* ADD.U32 acc, right; wrap */
        temporary = accumulator ^ (uint32_t)left; /* XOR result/input signs */
        /* Overflow iff equal input signs produced the opposite result sign. */
        if (!different_signs && (int32_t)temporary < 0) return 0u;
    } else if (operation == PYZ80_TARGET_OP_SUB) {
        accumulator = (uint32_t)left;         /* LD.U32 acc, left bits */
        accumulator -= (uint32_t)right;       /* SUB.U32 acc, right; wrap */
        temporary = accumulator ^ (uint32_t)left; /* XOR result/left signs */
        /* Overflow iff unlike input signs produced a sign unlike left. */
        if (different_signs && (int32_t)temporary < 0) return 0u;
    } else if (operation == PYZ80_TARGET_OP_MUL) {
        /* Common small operands need no division for the overflow check. */
        if (left >= -32768L && left <= 32767L &&
            right >= -32768L && right <= 32767L) {
            quotient = left * right;          /* MUL.S32; proven i16 inputs */
            accumulator = (uint32_t)quotient; /* LD.U32 acc, product bits */
        }
        else {
            magnitude_left = (uint32_t)left;  /* LD.U32 magnitude, left bits */
            if (left < 0) magnitude_left = 0UL - magnitude_left; /* NEG.U32 */
            magnitude_right = (uint32_t)right;
            if (right < 0) magnitude_right = 0UL - magnitude_right; /* NEG.U32 */
            limit = 2147483647UL;             /* Positive i32 magnitude bound */
            if (different_signs) limit = 2147483648UL; /* Negative bound */
            if (magnitude_right) {
                temporary = limit / magnitude_right; /* DIV.U32 overflow bound */
                if (magnitude_left > temporary) return 0u; /* CP.U32 / reject */
            }
            accumulator = magnitude_left;    /* LD.U32 acc, |left| */
            accumulator *= magnitude_right;  /* MUL.U32; proven within bound */
            if (different_signs) accumulator = 0UL - accumulator; /* NEG.U32 */
        }
    } else if (operation == PYZ80_TARGET_OP_FLOORDIV) {
        /* Guard C's two invalid signed-division cases before DIV.S32. */
        if (!right || (left == TARGET_I32_MIN && right == -1)) return 0u;
        quotient = left / right;              /* DIV.S32; truncate toward zero */
        remainder = left % right;             /* REM.S32; sign follows left */
        if (remainder && different_signs) --quotient; /* DEC.S32: Python floor */
        accumulator = (uint32_t)quotient;     /* LD.U32 acc, quotient bits */
    } else if (operation == PYZ80_TARGET_OP_MOD) {
        if (!right) return 0u;
        if (left == TARGET_I32_MIN && right == -1) accumulator = 0u;
        else {
            remainder = left % right;        /* REM.S32; sign follows left */
            if (remainder && different_signs) remainder += right; /* ADD.S32:
                nonzero Python remainder must have the divisor's sign */
            accumulator = (uint32_t)remainder; /* LD.U32 acc, remainder bits */
        }
    } else if (operation == PYZ80_TARGET_OP_BITAND ||
               operation == PYZ80_TARGET_OP_BITOR ||
               operation == PYZ80_TARGET_OP_BITXOR) {
        accumulator = (uint32_t)left;         /* LD.U32 acc, left bits */
        if (operation == PYZ80_TARGET_OP_BITAND)
            accumulator &= (uint32_t)right;  /* AND.U32 acc, right */
        else if (operation == PYZ80_TARGET_OP_BITOR)
            accumulator |= (uint32_t)right;  /* OR.U32 acc, right */
        else accumulator ^= (uint32_t)right; /* XOR.U32 acc, right */
        if (left_value->kind == PYZ80_VM_VALUE_BOOL &&
            right_value->kind == PYZ80_VM_VALUE_BOOL)
            result_kind = PYZ80_VM_VALUE_BOOL; /* Python bool &/|/^ bool -> bool */
    } else if (operation == PYZ80_TARGET_OP_LSHIFT) {
        if (right < 0) return 0u;
        if (!left) accumulator = 0u;          /* Zero << any nonnegative count */
        else {
            if (right >= 32) return 0u;
            shift = (uint8_t)right;           /* LD.U8 shift; proven 0..31 */
            limit = 2147483647UL;
            if (left < 0) limit = 2147483648UL;
            limit >>= shift;                 /* SHR.U32: max unshifted magnitude */
            magnitude_left = (uint32_t)left;
            if (left < 0) magnitude_left = 0UL - magnitude_left; /* NEG.U32 */
            if (magnitude_left > limit) return 0u; /* CP.U32 / overflow */
            accumulator = (uint32_t)left;
            accumulator <<= shift;           /* SHL.U32; never shift signed x */
        }
    } else if (operation == PYZ80_TARGET_OP_RSHIFT) {
        if (right < 0) return 0u;
        accumulator = (uint32_t)left;
        if (right >= 32) {
            accumulator = 0u;
            if (left < 0) accumulator = 0xFFFFFFFFUL; /* Fill with sign bits */
        }
        else if (!right) { /* MOV: shifting zero bits leaves acc unchanged. */ }
        else {
            shift = (uint8_t)right;           /* LD.U8 shift; proven 1..31 */
            accumulator >>= shift;           /* SHR.U32: zero-fill high bits */
            if (left < 0) {
                temporary = 0xFFFFFFFFUL;
                temporary >>= shift;         /* SHR.U32 all-ones mask */
                temporary = ~temporary;      /* NOT.U32: isolate vacated bits */
                accumulator |= temporary;    /* OR.U32: explicit sign extension */
            }
        }
    }
    /* Python / always returns float, even when the quotient is integral.
       It and integers outside i32 must be handled by an exact provider. */
    else return 0u;
    result->kind = result_kind;               /* ST.U8 value tag */
    result->reserved = 0u;
    result->symbol = PYZ80_VM_NO_SYMBOL;
    result->payload = accumulator;           /* ST.U32 exact result bits */
    return 1u;
}

static uint8_t integer_compare(
    uint8_t operation, const PyZ80VMValue *left_value,
    const PyZ80VMValue *right_value, PyZ80VMValue *result)
{
    int32_t left;
    int32_t right;
    uint8_t output;
    if ((operation == PYZ80_TARGET_OP_EQ || operation == PYZ80_TARGET_OP_NE) &&
        left_value->kind <= PYZ80_VM_VALUE_SYMBOL && right_value->kind <= PYZ80_VM_VALUE_SYMBOL &&
        (left_value->kind == PYZ80_VM_VALUE_NONE || left_value->kind == PYZ80_VM_VALUE_SYMBOL ||
         right_value->kind == PYZ80_VM_VALUE_NONE || right_value->kind == PYZ80_VM_VALUE_SYMBOL)) {
        /* Interned source strings share the image's unique constant ID.
           Only builtin scalars enter here; objects retain Python __eq__ dispatch. */
        output = left_value->kind == right_value->kind &&
            (left_value->kind == PYZ80_VM_VALUE_NONE || left_value->symbol == right_value->symbol);
        if (operation == PYZ80_TARGET_OP_NE) output = !output; /* XOR.U8 bool, 1 */
        value_none(result);
        result->kind = PYZ80_VM_VALUE_BOOL;
        result->payload = output;
        return 1u;
    }
    if ((left_value->kind != PYZ80_VM_VALUE_I32 &&
         left_value->kind != PYZ80_VM_VALUE_BOOL) ||
        (right_value->kind != PYZ80_VM_VALUE_I32 &&
         right_value->kind != PYZ80_VM_VALUE_BOOL)) return 0u;
    left = (int32_t)left_value->payload;      /* LD.S32 left, operand[0] */
    right = (int32_t)right_value->payload;    /* LD.S32 right, operand[1] */
    /* CP.S32 and SET.U8: compare without subtracting (which could overflow). */
    if (operation == PYZ80_TARGET_OP_EQ) output = left == right;
    else if (operation == PYZ80_TARGET_OP_NE) output = left != right;
    else if (operation == PYZ80_TARGET_OP_LT) output = left < right;
    else if (operation == PYZ80_TARGET_OP_LE) output = left <= right;
    else if (operation == PYZ80_TARGET_OP_GT) output = left > right;
    else if (operation == PYZ80_TARGET_OP_GE) output = left >= right;
    else return 0u;
    result->kind = PYZ80_VM_VALUE_BOOL;
    result->reserved = 0u;
    result->symbol = PYZ80_VM_NO_SYMBOL;
    result->payload = output;                /* ST.U32 normalized bool, 0 or 1 */
    return 1u;
}

/* Exact tuple ==/!= for a flat builtin-scalar prefix. Reference-identical
   items use CPython's identity shortcut; other object equality needs the
   resumable rich-comparison protocol. Never recurse on Z80's C stack. */
static uint8_t tuple_compare(PyZ80TargetContext *context, uint8_t operation,
    const PyZ80VMValue *left, const PyZ80VMValue *right, PyZ80VMValue *result)
{
    PyZ80TargetNode *a=node_from_value(context,left), *b=node_from_value(context,right);
    uint32_t size_a,size_b;
    uint16_t i,count;
    uint8_t equal=1u;
    if((operation!=PYZ80_TARGET_OP_EQ && operation!=PYZ80_TARGET_OP_NE) || !a || !b ||
        a->kind!=PYZ80_TARGET_NODE_TUPLE || b->kind!=PYZ80_TARGET_NODE_TUPLE ||
        !PyZ80Target_Length(context,left,&size_a) || !PyZ80Target_Length(context,right,&size_b)) return 0u;
    count=(uint16_t)(size_a<size_b ? size_a : size_b); /* MIN.U16 checked heap extents. */
    for(i=0u;i<count;++i) {
        const PyZ80VMValue *x=&context->items[a->item_start+i], *y=&context->items[b->item_start+i];
        if(x->kind==PYZ80_VM_VALUE_OPAQUE && y->kind==PYZ80_VM_VALUE_OPAQUE &&
            x->payload==y->payload && node_from_value(context,x)) continue;
        if(!integer_compare(PYZ80_TARGET_OP_EQ,x,y,result)) return 0u;
        if(!result->payload) { equal=0u; break; }
    }
    if(equal) equal=size_a==size_b;
    value_none(result); result->kind=PYZ80_VM_VALUE_BOOL;
    result->payload=operation==PYZ80_TARGET_OP_NE ? !equal : equal;
    return 1u;
}

static uint8_t identity_compare(PyZ80TargetContext *context, uint8_t operation,
    const PyZ80VMValue *left, const PyZ80VMValue *right, PyZ80VMValue *result)
{
    uint8_t equal;
    PyZ80TargetNode *left_node, *right_node;
    if (operation != PYZ80_TARGET_OP_IS && operation != PYZ80_TARGET_OP_IS_NOT) return 0u;
    left_node = node_from_value(context, left); right_node = node_from_value(context, right);
    if ((left->kind == PYZ80_VM_VALUE_OPAQUE && !left_node) ||
        (right->kind == PYZ80_VM_VALUE_OPAQUE && !right_node)) return 0u;
    /* Identity is NOT equality. Unboxed numbers/strings do not retain their
       allocation identity, so two such operands still require a provider. */
    if (left->kind == PYZ80_VM_VALUE_NONE || right->kind == PYZ80_VM_VALUE_NONE) {
        if ((left->kind > PYZ80_VM_VALUE_SYMBOL && left->kind != PYZ80_VM_VALUE_OPAQUE && left->kind != PYZ80_VM_VALUE_BUILTIN) ||
            (right->kind > PYZ80_VM_VALUE_SYMBOL && right->kind != PYZ80_VM_VALUE_OPAQUE && right->kind != PYZ80_VM_VALUE_BUILTIN)) return 0u;
        equal = left->kind == right->kind;
    } else if (left->kind == PYZ80_VM_VALUE_OPAQUE || right->kind == PYZ80_VM_VALUE_OPAQUE) {
        if ((left->kind > PYZ80_VM_VALUE_SYMBOL && left->kind != PYZ80_VM_VALUE_OPAQUE && left->kind != PYZ80_VM_VALUE_BUILTIN) ||
            (right->kind > PYZ80_VM_VALUE_SYMBOL && right->kind != PYZ80_VM_VALUE_OPAQUE && right->kind != PYZ80_VM_VALUE_BUILTIN)) return 0u;
        equal = left->kind == right->kind && left->payload == right->payload; /* CP.U32 stable handle + generation */
        if (!equal && left_node && right_node && left_node->kind == PYZ80_TARGET_NODE_TUPLE &&
            right_node->kind == PYZ80_TARGET_NODE_TUPLE) {
            /* CPython interns the empty tuple. Nonempty constant tuples may
               also be shared, but BUILD_TUPLE has not retained that provenance.
               Never report false identity from two reconstructed constants. */
            if (left_node->item_count || right_node->item_count) return 0u;
            equal = 1u;
        }
    } else if (left->kind==PYZ80_VM_VALUE_BUILTIN || right->kind==PYZ80_VM_VALUE_BUILTIN) {
        uint8_t truth;
        if((left->kind==PYZ80_VM_VALUE_BUILTIN && !PyZ80Target_Truth(context,0,left,&truth)) ||
           (right->kind==PYZ80_VM_VALUE_BUILTIN && !PyZ80Target_Truth(context,0,right,&truth)))return 0u;
        equal=left->kind==right->kind && left->payload==right->payload;
    } else if (left->kind == PYZ80_VM_VALUE_BOOL && right->kind == PYZ80_VM_VALUE_BOOL)
        equal = left->payload == right->payload;
    else if ((left->kind==PYZ80_VM_VALUE_BOOL && (right->kind==PYZ80_VM_VALUE_I32 || right->kind==PYZ80_VM_VALUE_SYMBOL)) ||
             (right->kind==PYZ80_VM_VALUE_BOOL && (left->kind==PYZ80_VM_VALUE_I32 || left->kind==PYZ80_VM_VALUE_SYMBOL)))
        equal=0u; /* bool — отдельный singleton, а не объект равного ему int. */
    else return 0u;
    value_none(result); result->kind = PYZ80_VM_VALUE_BOOL;
    result->payload = operation == PYZ80_TARGET_OP_IS ? equal : !equal;
    return 1u;
}

/* Только для поиска элемента контейнером: Python сначала проверяет identity,
   затем равенство. Обычный оператор == не вправе пропускать пользовательский __eq__. */
uint8_t PyZ80Target_ContainerItemEqual(PyZ80TargetContext *context,
    const PyZ80VMValue *left,const PyZ80VMValue *right,uint8_t *equal)
{
    PyZ80VMValue result;
    uint8_t truth;
    if(!context || !left || !right || !equal ||
       (left->kind==PYZ80_VM_VALUE_BOOL && left->payload>1u) ||
       (right->kind==PYZ80_VM_VALUE_BOOL && right->payload>1u))return 0u;
    if(left->kind==right->kind && left->payload==right->payload &&
       ((left->kind==PYZ80_VM_VALUE_OPAQUE && node_from_value(context,left)) ||
        (left->kind==PYZ80_VM_VALUE_BUILTIN && PyZ80Target_Truth(context,0,left,&truth) &&
         PyZ80Target_Truth(context,0,right,&truth)))) { *equal=1u;return 1u; }
    if(!integer_compare(PYZ80_TARGET_OP_EQ,left,right,&result) &&
       !tuple_compare(context,PYZ80_TARGET_OP_EQ,left,right,&result))return 0u;
    *equal=result.payload!=0u;return 1u;
}

void PyZ80Target_Init(
    PyZ80TargetContext *context, PyZ80TargetNode *nodes,
    uint16_t node_capacity, PyZ80TargetField *fields,
    uint16_t field_capacity, PyZ80VMValue *items, uint16_t item_capacity,
    const PyZ80TargetAdapterSpec *adapters, uint16_t adapter_count,
    const PyZ80TargetOperatorSpec *operators, uint16_t operator_count,
    PyZ80TargetProviderInvoke provider, void *provider_context)
{
    memset(context, 0, sizeof(*context));
    context->nodes = nodes;
    context->fields = fields;
    context->items = items;
    context->node_capacity = node_capacity;
    context->field_capacity = field_capacity;
    context->item_capacity = item_capacity;
    context->adapters = adapters;
    context->adapter_count = adapter_count;
    context->operators = operators;
    context->operator_count = operator_count;
    context->provider = provider;
    context->provider_context = provider_context;
    if (nodes != 0) memset(nodes, 0, node_capacity * sizeof(*nodes));
    if (fields != 0) memset(fields, 0, field_capacity * sizeof(*fields));
}

PyZ80VMAdapter PyZ80Target_VMAdapter(PyZ80TargetContext *context)
{
    PyZ80VMAdapter adapter;
    adapter.invoke = PyZ80Target_Invoke;
    adapter.truth = PyZ80Target_Truth;
    adapter.context = context;
    return adapter;
}

uint8_t PyZ80Target_EmptyList(PyZ80TargetContext *context, PyZ80VMValue *result)
{
    return collection(context,PYZ80_TARGET_NODE_LIST,0,0,result);
}

uint8_t PyZ80Target_ListAppend(PyZ80TargetContext *context, const PyZ80VMValue *list, const PyZ80VMValue *value)
{
    return list_append(context,list,value);
}

static uint8_t make_iterator(PyZ80TargetContext *context,
    const PyZ80VMValue *arguments, uint8_t reverse, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    PyZ80TargetNode *source;
    PyZ80VMValue owner,mapping;
    uint8_t mode=0u;
    uint32_t length;
    if (!context || !arguments || !result) return 0u;
    source = node_from_value(context, &arguments[0]);
    if(source && source->kind==PYZ80_TARGET_NODE_DEQUE)
        return !reverse && PyZ80Target_DequeIterator(context,arguments,result);
    if (source != 0 && (source->kind == PYZ80_TARGET_NODE_ITERATOR || source->kind==PYZ80_TARGET_NODE_ENUMERATE || source->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR)) {
        if(reverse)return 0u; /* reversed не превращает произвольный iterator в последовательность. */
        *result = arguments[0]; /* iter(iterator) сохраняет объект и позицию. */
        return 1u;
    }
    owner=arguments[0];
    if(source && source->kind==PYZ80_TARGET_NODE_DICT_VIEW) {
        if(source->class_symbol>2u) return 0u;
        mode=(uint8_t)source->class_symbol;owner=source->current;
        source=node_from_value(context,&owner);
        if(!PyZ80Target_Mapping(context,&owner,&mapping)) return 0u;
    }
    if(source && source->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
        if(!PyZ80Target_Mapping(context,&owner,&mapping))return 0u;
        source=node_from_value(context,&mapping);
    }
    if (!source || (source->kind!=PYZ80_TARGET_NODE_LIST && source->kind!=PYZ80_TARGET_NODE_TUPLE &&
        source->kind!=PYZ80_TARGET_NODE_RANGE && source->kind!=PYZ80_TARGET_NODE_DICT && !PYZ80_IS_BUFFER(source)) ||
        !PyZ80Target_Length(context,&owner,&length) ||
        !allocate_node(context, PYZ80_TARGET_NODE_ITERATOR,
                       PYZ80_VM_NO_SYMBOL, result)) return 0u;
    node = node_from_value(context, result);
    node->item_start = mode | reverse;
    node->item_count = (uint16_t)length;
    if(reverse)node->cursor=(uint16_t)length;
    node->source_link = (uint16_t)owner.payload;
    node->source_generation = node_from_value(context,&owner)->generation;
    if(source->kind==PYZ80_TARGET_NODE_DICT) {
        node->field_head=(uint16_t)source->current.payload;
        node->class_symbol=(uint16_t)(source->current.payload>>16); /* SHR.U32: старшая половина версии ключей. */
    }
    return 1u;

}

uint8_t PyZ80Target_GetIterator(PyZ80TargetContext *context,
    const PyZ80VMValue *arguments, PyZ80VMValue *result)
{
    return make_iterator(context,arguments,0u,result);
}

uint8_t PyZ80Target_Reversed(PyZ80TargetContext *context,
    const PyZ80VMValue *arguments, PyZ80VMValue *result)
{
    return make_iterator(context,arguments,PYZ80_TARGET_ITER_REVERSE,result);
}

static uint8_t iter_next_plain(PyZ80TargetContext *context,
    const PyZ80VMValue *arguments, PyZ80VMValue *result)
{
    PyZ80TargetNode *node;
    PyZ80TargetNode *source;
    uint16_t length,index;
    uint8_t reverse,mode;
    if (!context || !arguments || !result ||
        (node = node_from_value(context, &arguments[0])) == 0 ||
        node->kind != PYZ80_TARGET_NODE_ITERATOR) return 0u;
    if (!node->source_link || node->source_link > context->node_used ||
        context->node_used > context->node_capacity) return 0u;
    source = &context->nodes[node->source_link - 1u];
    if (source->generation != node->source_generation) return 0u;
    if(source->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
        PyZ80VMValue *parts;
        if(!PyZ80Target_DefaultDictParts(context,source,&parts))return 0u;
        source=node_from_value(context,parts);
    }
    reverse=(node->item_start & PYZ80_TARGET_ITER_REVERSE)!=0u;
    mode=(uint8_t)(node->item_start & 3u);
    if((node->item_start & ~(PYZ80_TARGET_ITER_REVERSE|3u)) || mode>2u ||
       (source->kind!=PYZ80_TARGET_NODE_DICT && mode) || node->reserved>1u ||
       (reverse && node->cursor>node->item_count))return 0u;
    if(source->kind==PYZ80_TARGET_NODE_DICT) {
        if(!dict_valid(context,source)) return 0u;
        if(node->reserved) { node->has_current=0u;*result=arguments[0];return 1u; }
        /* Изменение набора ключей во время активного обхода пока не поддержано.
           Версия ловит и удаление/вставку при прежнем размере, не выдавая неверный порядок. */
        if(source->cursor!=node->item_count ||
            source->current.payload!=(((uint32_t)node->class_symbol<<16)|node->field_head)) return 0u;
        length=source->cursor;
    } else if(PYZ80_IS_BUFFER(source)) {
        if(!PyZ80Target_BufferValid(context,source))return 0u;
        length=source->item_count;
    } else if (source->kind == PYZ80_TARGET_NODE_RANGE) {
        if (source->current.kind != PYZ80_VM_VALUE_I32 ||
            !(source->item_start || source->item_count)) return 0u;
        length = source->cursor;
    } else {
        if ((source->kind != PYZ80_TARGET_NODE_LIST && source->kind != PYZ80_TARGET_NODE_TUPLE) ||
            context->item_used > context->item_capacity || source->item_start > context->item_used ||
            source->item_count > context->item_used - source->item_start ||
            (source->item_count && context->items == 0)) return 0u;
        length = source->item_count;
    }
    /* Исчерпанный итератор не оживает при последующем росте источника. */
    index=node->cursor;
    if(reverse && index)--index; /* DEC.U16: обратный индекс, только после проверки нуля. */
    if (!node->reserved && (!reverse || node->cursor) && index < length) {
        if(PYZ80_IS_BUFFER(source)) {
            PyZ80VMValue owner;
            value_none(&owner);owner.kind=PYZ80_VM_VALUE_OPAQUE;
            owner.payload=((uint32_t)node->source_generation<<16)|node->source_link;
            if(!PyZ80Target_BufferRead(context,&owner,index,&node->current))return 0u;
        } else if(source->kind==PYZ80_TARGET_NODE_DICT) {
            PyZ80VMValue pair[2];
            if(source->reserved) {
                pair[0]=context->items[source->item_start+index*2u];
                pair[1]=context->items[source->item_start+index*2u+1u];
                if(!dict_key(&pair[0])) return 0u;
            } else {
                uint16_t link=source->field_head,offset;
                for(offset=0u;offset<index;++offset) link=context->fields[link-1u].next;
                value_none(&pair[0]);pair[0].kind=PYZ80_VM_VALUE_SYMBOL;
                pair[0].symbol=context->fields[link-1u].key;
                pair[1]=context->fields[link-1u].value;
            }
            if(mode==2u) {
                if(!collection(context,PYZ80_TARGET_NODE_TUPLE,pair,2u,&node->current)) return 0u;
            } else node->current=pair[mode];
        } else if (source->kind == PYZ80_TARGET_NODE_RANGE) {
            uint32_t step = ((uint32_t)source->item_count << 16) | source->item_start;
            if(reverse) {
                if(node->cursor==node->item_count) {
                    node->current=source->current;
                    step*=index; /* MUL.U32: смещение последнего элемента, лишь при первом next. */
                    node->current.payload+=step; /* ADD.U32: биты результата int32, без signed overflow. */
                } else node->current.payload-=step; /* SUB.U32: предыдущий элемент range. */
            } else if (!node->cursor) node->current = source->current;
            else node->current.payload += step; /* ADD.U32: следующий элемент без умножения на каждом шаге. */
        } else node->current = context->items[source->item_start + index];
        if(reverse)--node->cursor; /* DEC.U16: положительный обратный cursor. */
        else ++node->cursor;
        node->has_current=1u;
    } else { node->reserved=1u;node->has_current=0u;value_none(&node->current); }
    *result = arguments[0];
    return 1u;

}

uint8_t PyZ80Target_Enumerate(PyZ80TargetContext *context, const PyZ80VMValue *source,
    const PyZ80VMValue *start, PyZ80VMValue *result)
{
    PyZ80VMValue iterator;
    PyZ80TargetNode *node;
    uint32_t index=0u;
    if(!result || (start && start->kind!=PYZ80_VM_VALUE_I32 &&
        !(start->kind==PYZ80_VM_VALUE_BOOL && start->payload<=1u))) return 0u;
    if(start) index=start->payload;
    if(!PyZ80Target_GetIterator(context,source,&iterator) ||
        !allocate_node(context,PYZ80_TARGET_NODE_ENUMERATE,65535u,result)) return 0u;
    node=node_from_value(context,result);
    node->source_link=(uint16_t)iterator.payload;node->source_generation=(uint16_t)(iterator.payload>>16);
    node->item_start=(uint16_t)index;node->item_count=(uint16_t)(index>>16);
    return 1u;
}

static uint8_t enumerate_source(PyZ80TargetContext *context, const PyZ80TargetNode *node, PyZ80VMValue *source)
{
    PyZ80TargetNode *child;
    if(!node || node->kind!=PYZ80_TARGET_NODE_ENUMERATE || node->reserved>2u) return 0u;
    value_none(source);source->kind=PYZ80_VM_VALUE_OPAQUE;
    source->payload=((uint32_t)node->source_generation<<16)|node->source_link;
    child=node_from_value(context,source);
    return child && (child->kind==PYZ80_TARGET_NODE_ITERATOR || child->kind==PYZ80_TARGET_NODE_ENUMERATE || child->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR);
}

uint8_t PyZ80Target_IterNext(PyZ80TargetContext *context, const PyZ80VMValue *arguments, PyZ80VMValue *result)
{
    PyZ80VMValue outer,leaf,child,probe,pair[2],out;
    PyZ80TargetNode *node,*source;
    uint16_t depth=0u,remaining;
    uint32_t index;
    if(!arguments || !result) return 0u;
    outer=*arguments;leaf=outer;node=node_from_value(context,&leaf);
    if(!node) return 0u;
    if(node->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR)return PyZ80Target_DequeIterNext(context,arguments,result);
    if(node->kind!=PYZ80_TARGET_NODE_ENUMERATE) return iter_next_plain(context,arguments,result);
    /* Проверить всю цепочку до изменения источника; ограничение числа узлов
       обнаруживает цикл. Аппаратный стек C от глубины enumerate не растёт. */
    while(node->kind==PYZ80_TARGET_NODE_ENUMERATE) {
        if(depth>=context->node_used || !enumerate_source(context,node,&child)) return 0u;
        ++depth; /* INC.U16 после проверки: даже 65535 узлов не обнуляют защиту цикла. */
        if(node->reserved==1u) break;
        leaf=child;node=node_from_value(context,&leaf);
    }
    if(node->kind==PYZ80_TARGET_NODE_ITERATOR && !iter_next_plain(context,&leaf,&out)) return 0u;
    if(node->kind==PYZ80_TARGET_NODE_DEQUE_ITERATOR && !PyZ80Target_DequeIterNext(context,&leaf,&out))return 0u;
    /* Поднимать пары от внутреннего iterator к внешнему, без рекурсивного next. */
    while(leaf.payload!=outer.payload) {
        probe=outer;remaining=context->node_used;
        do {
            node=node_from_value(context,&probe);
            if(!remaining-- || !enumerate_source(context,node,&child)) return 0u;
            if(child.payload==leaf.payload) break;
            probe=child;
        } while(1);
        source=node_from_value(context,&leaf);
        if(!source->has_current) { node->reserved=1u;node->has_current=0u;value_none(&node->current); }
        else {
            if(node->reserved==2u) return 0u;
            index=((uint32_t)node->item_count<<16)|node->item_start;
            value_none(&pair[0]);pair[0].kind=PYZ80_VM_VALUE_I32;pair[0].payload=index;
            pair[1]=source->current;
            if(!collection(context,PYZ80_TARGET_NODE_TUPLE,pair,2u,&node->current)) return 0u;
            node->has_current=1u;
            if(index==0x7fffffffUL) node->reserved=2u;
            else { ++index;node->item_start=(uint16_t)index;node->item_count=(uint16_t)(index>>16); }
        }
        leaf=probe;
    }
    *result=outer;return 1u;
}

uint8_t PyZ80Target_Invoke(
    void *raw_context, struct PyZ80VM *vm, uint16_t adapter_id,
    uint16_t destination_symbol, const PyZ80VMValue *arguments,
    uint8_t argument_count, uint32_t raw_arguments_offset,
    PyZ80VMValue *result)
{
    PyZ80TargetContext *context = (PyZ80TargetContext *)raw_context;
    PyZ80TargetAdapterSpec record;
    const PyZ80TargetAdapterSpec *spec=&record;
    PyZ80TargetNode *node;
    PyZ80VMValue *slot;
    uint8_t operation;
    (void)destination_symbol;
    if (context == 0 || result == 0 ||
        adapter_id >= context->adapter_count ||
        (argument_count && arguments == 0))
        return 0u;
    if (!PyZ80Target_ReadAdapter(context,adapter_id,&record)) return 0u;
    if (argument_count != spec->argument_count) return 0u;
    value_none(result);
    if (spec->operation >= PYZ80_TARGET_DATACLASS_RESOLVE && spec->operation <= PYZ80_TARGET_DATACLASS_REPR_PENDING)
        return context->library_provider ? context->library_provider(context->library_context, vm,
            adapter_id, destination_symbol, arguments, argument_count, raw_arguments_offset, result) : 0u;
    if (spec->operation == PYZ80_TARGET_LOAD_CLASS_NAME || spec->operation == PYZ80_TARGET_LOAD_CLASS_FREE_NAME || spec->operation == PYZ80_TARGET_STORE_CLASS_NAME ||
        spec->operation == PYZ80_TARGET_STORE_ATTRIBUTE || spec->operation == PYZ80_TARGET_CAPTURE_CELL ||
        spec->operation == PYZ80_TARGET_SETUP_CLASS_ANNOTATIONS) {
        uint8_t found = context->class_provider ? context->class_provider(context->class_context, vm,
            adapter_id, destination_symbol, arguments, argument_count, raw_arguments_offset, result) : 0u;
        if (found) return found == 1u;
        if (spec->operation == PYZ80_TARGET_STORE_CLASS_NAME || spec->operation == PYZ80_TARGET_SETUP_CLASS_ANNOTATIONS) return 0u;
        if (spec->operation == PYZ80_TARGET_LOAD_CLASS_NAME || spec->operation == PYZ80_TARGET_LOAD_CLASS_FREE_NAME) goto provider;
    }
    if ((spec->operation >= PYZ80_TARGET_CAPTURE_CELL &&
        spec->operation <= PYZ80_TARGET_LOAD_LEXICAL_NAME) ||
        (spec->operation >= PYZ80_TARGET_MAKE_CLOSURE_DEFAULTS && spec->operation <= PYZ80_TARGET_LOAD_GLOBAL_NAME) ||
        spec->operation == PYZ80_TARGET_SETUP_GLOBAL_ANNOTATIONS ||
        spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE ||
        spec->operation == PYZ80_TARGET_MAKE_GENERATOR_CLOSURE_DEFAULTS) {
        uint8_t scope_status = 0u;
        if (context->scope_provider != 0) scope_status = context->scope_provider(
                context->scope_context, vm, adapter_id, destination_symbol,
                arguments, argument_count, raw_arguments_offset, result);
        if (scope_status == 1u) return 1u;
        if (scope_status != 0u) return 0u;
        /* Only an absent ordinary name may continue to external/builtin lookup.
           Creation/capture failures cannot be hidden by a permissive provider. */
        if (spec->operation == PYZ80_TARGET_LOAD_LEXICAL_NAME || spec->operation == PYZ80_TARGET_LOAD_GLOBAL_NAME) goto provider;
        return 0u;
    }
    if (spec->operation == PYZ80_TARGET_REQUIRE_CALLABLE) {
        if (argument_count != 1u) return 0u;
        if (arguments[0].kind <= PYZ80_VM_VALUE_SYMBOL) return 0u;
        node = node_from_value(context, &arguments[0]);
        if (node == 0) goto provider;
        if(node->kind==PYZ80_TARGET_NODE_NATIVE_METHOD)
            return PyZ80Target_NativeMethodValid(context,node) ? (*result=arguments[0],1u) : 0u;
        if (node->kind == PYZ80_TARGET_NODE_CLASS && context->class_provider) { *result = arguments[0]; return 1u; }
        if (node->kind == PYZ80_TARGET_NODE_STATICMETHOD) {
            PyZ80VMValue prototype, receiver;
            /* Декоратор сохраняет объект вызова; аргументы связывает общий binder. */
            if (!PyZ80Target_UnwrapCallable(context, &arguments[0], &prototype, &receiver)) return 0u;
            *result = arguments[0];
            return 1u;
        }
        if (node->kind != PYZ80_TARGET_NODE_CALLABLE) return 0u;
        if (node->class_symbol >= context->function_count) return 0u;
        *result = arguments[0];
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_RESOLVE_CALLABLE ||
        spec->operation == PYZ80_TARGET_BOUND_RECEIVER) {
        uint16_t start = spec->auxiliary;
        uint16_t count;
        uint16_t index;
        uint16_t candidate;
        uint8_t bound = spec->operation == PYZ80_TARGET_BOUND_RECEIVER;
        if (argument_count != (bound ? 2u : 1u)) return 0u;
        node = node_from_value(context, &arguments[0]);
        if (node == 0 || node->kind != PYZ80_TARGET_NODE_CALLABLE) goto provider;
        if (node->class_symbol >= context->function_count ||
            start >= context->dispatch_function_count)
            return 0u;
        if(!PyZ80Target_ReadWord(context,PYZ80_TABLE_DISPATCH,start++,&count)) return 0u;
        if (!count || count > 255u || count > context->dispatch_function_count - start)
            return 0u;
        if (bound) {
            if (arguments[1].kind != PYZ80_VM_VALUE_I32 || arguments[1].payload >= count)
                return 0u;
            index = (uint16_t)arguments[1].payload;
            if (!PyZ80Target_ReadWord(context,PYZ80_TABLE_DISPATCH,start+index,&candidate) || candidate != node->class_symbol ||
                node->reserved != 1u || node_from_value(context, &node->current) == 0)
                return 0u;
            *result = node->current;
            return 1u;
        }
        for (index = 0u; index < count; ++index) {
            if(!PyZ80Target_ReadWord(context,PYZ80_TABLE_DISPATCH,start+index,&candidate)) return 0u;
            if (candidate == node->class_symbol) {
                result->kind = PYZ80_VM_VALUE_I32;
                result->payload = index;
                return 1u;
            }
        }
        return 0u;
    }
    if (spec->operation == PYZ80_TARGET_GENERATOR_NEXT_ENTER) {
        /* Тело нельзя исполнить обычным вызовом до первого next(). */
        return !argument_count && vm != NULL && vm->call_depth &&
            (vm->frames[vm->call_depth - 1u].reserved & PYZ80_VM_FRAME_GENERATOR) &&
            vm->active_generator < vm->limits.max_generators &&
            vm->generators[vm->active_generator].reserved == vm->call_depth;
    }
    if (spec->operation == PYZ80_TARGET_ALLOCATE_INSTANCE) {
        if (argument_count != 1u || arguments[0].kind != PYZ80_VM_VALUE_SYMBOL)
            return 0u;
        return allocate_node(context, PYZ80_TARGET_NODE_OBJECT,
                             arguments[0].symbol, result);
    }
    if (spec->operation == PYZ80_TARGET_LOAD_ATTRIBUTE) {
        if (argument_count != 2u || arguments[1].kind != PYZ80_VM_VALUE_SYMBOL)
            return 0u;
        return PyZ80Target_FindAttribute(context, &arguments[0], arguments[1].symbol, result) == 1u;
    }
    if (spec->operation == PYZ80_TARGET_STORE_ATTRIBUTE) {
        if (argument_count != 3u || arguments[1].kind != PYZ80_VM_VALUE_SYMBOL)
            return 0u;
        node = node_from_value(context, &arguments[0]);
        if (node && node->kind == PYZ80_TARGET_NODE_DICT) return 0u;
        if(node && node->kind==PYZ80_TARGET_NODE_DEFAULTDICT) {
            PyZ80VMValue *parts;
            if(!PyZ80Target_NativeName(context,arguments[1].symbol,PYZ80_DEFAULT_FACTORY_ATTRIBUTE) ||
               !PyZ80Target_DefaultDictParts(context,node,&parts))return 0u;
            parts[1]=arguments[2];return 1u; /* Присваивание не требует callable, как в Python. */
        }
        if (node && node->kind == PYZ80_TARGET_NODE_CALLABLE) {
            PyZ80TargetNode *mapping = node_from_value(context, &arguments[2]);
            if ((node->reserved != 0u && node->reserved != 2u) || !context->class_symbols ||
                arguments[1].symbol != context->class_symbols[47] ||
                (arguments[2].kind != PYZ80_VM_VALUE_NONE && (!mapping || mapping->kind != PYZ80_TARGET_NODE_DICT))) return 0u;
        }
        return PyZ80Target_StoreField(
            context, &arguments[0], arguments[1].symbol, &arguments[2]);
    }
    if (spec->operation == PYZ80_TARGET_STORE_DATACLASS_FIELDS) {
        uint16_t start = spec->auxiliary;
        uint8_t count;
        uint16_t i;
        if (!argument_count) return 0u;
        count = argument_count - 1u;
        if (start > context->field_key_count ||
            count > context->field_key_count - start ||
            (count && !PyZ80Target_HasTable(context,PYZ80_TABLE_FIELDS))) return 0u;
        if(context->table_read) {
            if(count>context->table_key_capacity || (count && !context->table_key_scratch)) return 0u;
            for(i=0u;i<count;++i)
                if(!PyZ80Target_ReadWord(context,PYZ80_TABLE_FIELDS,start+i,&context->table_key_scratch[i])) return 0u;
            return PyZ80Target_StoreFields(context,&arguments[0],context->table_key_scratch,&arguments[1],count);
        }
        return PyZ80Target_StoreFields(context, &arguments[0],
            count ? &context->field_keys[start] : 0, &arguments[1], count);
    }
    if (spec->operation == PYZ80_TARGET_BUILD_LIST ||
        spec->operation == PYZ80_TARGET_BUILD_TUPLE)
        return collection(context,
            spec->operation == PYZ80_TARGET_BUILD_LIST ?
                PYZ80_TARGET_NODE_LIST : PYZ80_TARGET_NODE_TUPLE,
            arguments, argument_count, result);
    if (spec->operation == PYZ80_TARGET_LIST_APPEND) {
        if (argument_count != 2u) return 0u;
        return list_append(context, &arguments[0], &arguments[1]);
    }
    if(spec->operation==PYZ80_TARGET_BUILD_SET) {
        uint16_t index;
        for(index=0u;index<argument_count;++index) if(!dict_key(&arguments[index])) return 0u;
        if(!PyZ80Target_SetFrom(context,0,0u,result)) return 0u;
        for(index=0u;index<argument_count;++index) if(!PyZ80Target_SetAdd(context,result,&arguments[index])) return 0u;
        return 1u;
    }
    if(spec->operation==PYZ80_TARGET_SET_ADD)
        return argument_count==2u && PyZ80Target_SetAdd(context,&arguments[0],&arguments[1]);
    if (spec->operation == PYZ80_TARGET_LOAD_SUBSCRIPT ||
        spec->operation == PYZ80_TARGET_UNPACK_ITEM) {
        if(argument_count==2u && PYZ80_IS_BUFFER(node_from_value(context,arguments))) {
            uint16_t index;
            return PyZ80Target_BufferIndex(context,arguments,&arguments[1],&index) &&
                PyZ80Target_BufferRead(context,arguments,index,result);
        }
        if (spec->operation == PYZ80_TARGET_LOAD_SUBSCRIPT && argument_count == 2u) {
            node = node_from_value(context, &arguments[0]);
            if (node && (node->kind == PYZ80_TARGET_NODE_DICT || node->kind==PYZ80_TARGET_NODE_DEFAULTDICT))
                return PyZ80Target_DictFind(context,&arguments[0],&arguments[1],result)==1u;
        }
        if (argument_count != 2u || !collection_item(
                context, &arguments[0], &arguments[1], &slot)) return 0u;
        *result = *slot;
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_STORE_SUBSCRIPT) {
        if(argument_count==3u && PYZ80_IS_BUFFER(node_from_value(context,arguments))) {
            uint16_t index;
            return PyZ80Target_BufferIndex(context,arguments,&arguments[1],&index) &&
                PyZ80Target_BufferWrite(context,arguments,index,&arguments[2]);
        }
        if (argument_count == 3u) {
            node = node_from_value(context, &arguments[0]);
            if (node && (node->kind == PYZ80_TARGET_NODE_DICT || node->kind==PYZ80_TARGET_NODE_DEFAULTDICT))
                return PyZ80Target_DictStore(context,&arguments[0],&arguments[1],&arguments[2]);
        }
        if (argument_count != 3u || !collection_item(
                context, &arguments[0], &arguments[1], &slot)) return 0u;
        node = node_from_value(context, &arguments[0]);
        if (node == 0 || node->kind != PYZ80_TARGET_NODE_LIST) return 0u;
        *slot = arguments[2];
        return 1u;
    }
    if(spec->operation==PYZ80_TARGET_DELETE_SUBSCRIPT) {
        PyZ80VMValue removed;
        if(argument_count!=2u) return 0u;
        node=node_from_value(context,&arguments[0]);
        if(node && (node->kind==PYZ80_TARGET_NODE_DICT || node->kind==PYZ80_TARGET_NODE_DEFAULTDICT))
            return PyZ80Target_DictRemove(context,&arguments[0],&arguments[1],&removed)==1u;
        return PyZ80Target_ListPop(context,&arguments[0],&arguments[1],&removed);
    }
    if (spec->operation == PYZ80_TARGET_BUILD_DICT) {
        uint16_t index;
        if (argument_count & 1u) return 0u;
        for (index = 0u; index < argument_count; index += 2u)
            if (!dict_key(&arguments[index]) || (arguments[index].kind==PYZ80_VM_VALUE_SYMBOL &&
                (!vm || arguments[index].symbol>=vm->header.constant_count))) return 0u;
        if (!PyZ80Target_AllocateNode(context, PYZ80_TARGET_NODE_DICT, 65535u, result)) return 0u;
        for (index = 0u; index < argument_count; index += 2u)
            if (!PyZ80Target_DictStore(context,result,&arguments[index],&arguments[index+1u])) return 0u;
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_BINARY ||
        spec->operation == PYZ80_TARGET_COMPARE) {
        if (argument_count != 3u) return 0u;
        if (!PyZ80Target_Operator(context, &arguments[0], &operation)) goto provider;
        if(spec->operation==PYZ80_TARGET_COMPARE &&
            (operation==PYZ80_TARGET_OP_IN || operation==PYZ80_TARGET_OP_NOT_IN)) {
            uint8_t found;
            node=node_from_value(context,&arguments[2]);
            if(!node || (node->kind!=PYZ80_TARGET_NODE_DICT && node->kind!=PYZ80_TARGET_NODE_DEFAULTDICT && node->kind!=PYZ80_TARGET_NODE_SET)) goto provider;
            found=node->kind==PYZ80_TARGET_NODE_SET ? PyZ80Target_SetFind(context,&arguments[2],&arguments[1]) :
                PyZ80Target_DictFind(context,&arguments[2],&arguments[1],result);
            if(!found) return 0u;
            value_none(result);result->kind=PYZ80_VM_VALUE_BOOL;
            result->payload=operation==PYZ80_TARGET_OP_IN ? found==1u : found==2u;
            return 1u;
        }
        {
            PyZ80TargetNode *left=node_from_value(context,&arguments[1]), *right=node_from_value(context,&arguments[2]);
            if(((left && left->kind==PYZ80_TARGET_NODE_SET) || (right && right->kind==PYZ80_TARGET_NODE_SET)) &&
                operation!=PYZ80_TARGET_OP_IS && operation!=PYZ80_TARGET_OP_IS_NOT)
                return spec->operation==PYZ80_TARGET_BINARY ?
                    set_binary(context,operation,spec->auxiliary!=0u,&arguments[1],&arguments[2],result) :
                    set_compare(context,operation,&arguments[1],&arguments[2],result);
        }
        if (spec->operation == PYZ80_TARGET_COMPARE && identity_compare(context, operation, &arguments[1], &arguments[2], result)) return 1u;
        if (spec->operation == PYZ80_TARGET_COMPARE && tuple_compare(context, operation, &arguments[1], &arguments[2], result)) return 1u;
        if (spec->operation == PYZ80_TARGET_BINARY && !spec->auxiliary && operation == PYZ80_TARGET_OP_ADD) {
            PyZ80TargetNode *left = node_from_value(context, &arguments[1]), *right = node_from_value(context, &arguments[2]);
            if (left && right && left->kind == PYZ80_TARGET_NODE_LIST && right->kind == PYZ80_TARGET_NODE_LIST) {
                uint32_t left_count, right_count, extent;
                uint16_t index;
                if (!PyZ80Target_Length(context, &arguments[1], &left_count) || !PyZ80Target_Length(context, &arguments[2], &right_count)) return 0u;
                extent = left_count + right_count; /* ADD.U32: do not wrap a 16-bit item extent. */
                if (context->item_used > context->item_capacity || extent > context->item_capacity - context->item_used ||
                    !PyZ80Target_AllocateNode(context, PYZ80_TARGET_NODE_LIST, 65535u, result)) return 0u;
                node = node_from_value(context, result); node->item_start = context->item_used;
                node->item_count = node->cursor = (uint16_t)extent;
                for (index = 0u; index < left_count; ++index) context->items[context->item_used++] = context->items[left->item_start + index];
                for (index = 0u; index < right_count; ++index) context->items[context->item_used++] = context->items[right->item_start + index];
                return 1u;
            }
        }
        if (spec->operation == PYZ80_TARGET_BINARY ?
            integer_binary(operation, &arguments[1], &arguments[2], result) :
            integer_compare(operation, &arguments[1], &arguments[2], result))
            return 1u;
        goto provider;
    }
    if (spec->operation == PYZ80_TARGET_UNARY) {
        int32_t value;
        uint32_t accumulator;
        if (argument_count != 2u ||
            !PyZ80Target_Operator(context, &arguments[0], &operation)) goto provider;
        if (operation == PYZ80_TARGET_OP_NOT && vm) {
            uint8_t truth;
            if (!PyZ80VM_Truth(vm,&arguments[1],&truth)) return 0u;
            value_none(result);result->kind=PYZ80_VM_VALUE_BOOL;
            result->payload=!truth; /* TEST / SETZ: отрицание истинности, не только числа. */
            return 1u;
        }
        if (arguments[1].kind != PYZ80_VM_VALUE_I32 &&
            arguments[1].kind != PYZ80_VM_VALUE_BOOL) goto provider;
        value = (int32_t)arguments[1].payload; /* LD.S32 value, operand */
        if (operation == PYZ80_TARGET_OP_NEG && value == TARGET_I32_MIN)
            goto provider;
        result->kind = (operation == PYZ80_TARGET_OP_NOT) ?
            PYZ80_VM_VALUE_BOOL : PYZ80_VM_VALUE_I32;
        result->reserved = 0u;
        result->symbol = PYZ80_VM_NO_SYMBOL;
        accumulator = (uint32_t)value;        /* LD.U32 acc, operand bits */
        if (operation == PYZ80_TARGET_OP_NEG)
            accumulator = 0UL - accumulator; /* NEG.U32; MIN_I32 excluded above */
        else if (operation == PYZ80_TARGET_OP_POS) { /* MOV; bool becomes int */ }
        else if (operation == PYZ80_TARGET_OP_INVERT)
            accumulator = ~accumulator;      /* NOT.U32: complement all bits */
        else if (operation == PYZ80_TARGET_OP_NOT)
            accumulator = !accumulator;     /* TEST.U32 / SETZ: bool 0 or 1 */
        else goto provider;
        result->payload = accumulator;       /* ST.U32 exact result bits */
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_GET_ITERATOR)
        return argument_count == 1u && PyZ80Target_GetIterator(context,arguments,result);
    if (spec->operation == PYZ80_TARGET_ITER_NEXT)
        return argument_count == 1u && PyZ80Target_IterNext(context,arguments,result);
    if (spec->operation == PYZ80_TARGET_ITER_HAS_VALUE ||
        spec->operation == PYZ80_TARGET_ITER_VALUE) {
        if (argument_count != 1u ||
            (node = node_from_value(context, &arguments[0])) == 0 ||
            (node->kind != PYZ80_TARGET_NODE_ITERATOR && node->kind != PYZ80_TARGET_NODE_ENUMERATE && node->kind != PYZ80_TARGET_NODE_DEQUE_ITERATOR)) return 0u;
        if (spec->operation == PYZ80_TARGET_ITER_HAS_VALUE) {
            result->kind = PYZ80_VM_VALUE_BOOL;
            result->reserved = 0u;
            result->symbol = PYZ80_VM_NO_SYMBOL;
            result->payload = node->has_current;
            return 1u;
        }
        if (!node->has_current) return 0u;
        *result = node->current;
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_UNPACK_SEQUENCE) {
        if (argument_count != 2u || arguments[1].kind != PYZ80_VM_VALUE_I32 ||
            (node = node_from_value(context, &arguments[0])) == 0 ||
            node->item_count != (uint16_t)arguments[1].payload) return 0u;
        *result = arguments[0];
        return 1u;
    }
provider:
    value_none(result);
    if (spec->operation == PYZ80_TARGET_UNSUPPORTED && argument_count) {
        PyZ80VMValue prototype,receiver;
        if (PyZ80Target_UnwrapCallable(context,&arguments[0],&prototype,&receiver) &&
            PyZ80Target_Node(context,&prototype)->has_current) return 0u;
    }
    if (context->builtin_provider != 0) {
        uint8_t found = context->builtin_provider(context, vm, adapter_id, destination_symbol,
            arguments, argument_count, raw_arguments_offset, result);
        if (found) return found == 1u;
    }
    if (context->provider != 0)
        return context->provider(
            context->provider_context, vm, adapter_id, destination_symbol,
            arguments, argument_count, raw_arguments_offset, result);
    return 0u;
}

uint8_t PyZ80Target_Truth(
    void *raw_context, struct PyZ80VM *vm, const PyZ80VMValue *value,
    uint8_t *truth)
{
    PyZ80TargetContext *context = (PyZ80TargetContext *)raw_context;
    PyZ80TargetNode *node;
    (void)vm;
    if (context != 0 && value != 0 && truth != 0 && value->kind == PYZ80_VM_VALUE_BUILTIN) {
        uint16_t index;
        if (context->builtin_symbols == 0) return 0u;
        for (index = 0u; index < context->builtin_symbol_count; ++index)
            if (context->builtin_symbols[index].symbol == value->symbol &&
                context->builtin_symbols[index].operation == value->payload &&
                (PYZ80_BUILTIN_IS_GLOBAL(value->payload) || value->payload==PYZ80_BUILTIN_DEQUE || value->payload==PYZ80_BUILTIN_DEFAULTDICT)) {
                *truth = 1u;
                return 1u;
            }
        return 0u;
    }
    if (truth == 0 || (node = node_from_value(context, value)) == 0) return 0u;
    if (node->kind == PYZ80_TARGET_NODE_LIST ||
        node->kind == PYZ80_TARGET_NODE_TUPLE)
        *truth = node->item_count != 0u;
    else if(node->kind==PYZ80_TARGET_NODE_SET) {
        if(!set_valid(context,node)) return 0u;
        *truth=node->item_count!=0u;
    }
    else if (node->kind == PYZ80_TARGET_NODE_DICT || node->kind == PYZ80_TARGET_NODE_DEFAULTDICT || node->kind == PYZ80_TARGET_NODE_DICT_VIEW || node->kind == PYZ80_TARGET_NODE_DEQUE || PYZ80_IS_BUFFER(node)) {
        uint32_t length;
        if(!PyZ80Target_Length(context,value,&length)) return 0u;
        *truth=length!=0u;
    }
    else if (node->kind == PYZ80_TARGET_NODE_RANGE) *truth = node->cursor != 0u;
    else *truth = 1u;
    return 1u;
}
