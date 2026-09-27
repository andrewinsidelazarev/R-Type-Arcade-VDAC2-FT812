#include "pyz80_target_builtins.h"
#include "pyz80_target_deque.h"

static uint8_t lookup(PyZ80TargetContext *context, uint16_t symbol)
{
    uint16_t index;
    if (context->builtin_symbols == 0) return 0u;
    for (index = 0u; index < context->builtin_symbol_count; ++index)
        if (context->builtin_symbols[index].symbol == symbol &&
            PYZ80_BUILTIN_IS_GLOBAL(context->builtin_symbols[index].operation))
            return context->builtin_symbols[index].operation;
    return 0u;
}

uint8_t PyZ80Target_Keyword(PyZ80TargetContext *context, uint16_t symbol)
{
    uint16_t index;
    if(!context || !context->builtin_symbols || symbol==65535u) return 0u;
    for(index=0u;index<context->builtin_symbol_count;++index)
        if(context->builtin_symbols[index].symbol==symbol && context->builtin_symbols[index].operation>=PYZ80_KEYWORD_KEY &&
            context->builtin_symbols[index].operation<=PYZ80_KEYWORD_DEFAULT) return context->builtin_symbols[index].operation;
    return 0u;
}

uint8_t PyZ80Target_FastExtremum(uint8_t operation,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result)
{
    uint8_t i,right;
    if(!args || !result || count!=2u ||
       (operation!=PYZ80_BUILTIN_MIN && operation!=PYZ80_BUILTIN_MAX))return 0u;
    for(i=0u;i<2u;++i)
        if(args[i].kind!=PYZ80_VM_VALUE_I32 &&
           (args[i].kind!=PYZ80_VM_VALUE_BOOL || args[i].payload>1u))return 0u;
    /* CMP.I32: без вычитания, которое переполнилось бы между MIN и MAX. */
    right=operation==PYZ80_BUILTIN_MIN ? (int32_t)args[1].payload<(int32_t)args[0].payload :
        (int32_t)args[1].payload>(int32_t)args[0].payload;
    *result=args[right];return 1u;
}

static uint8_t make_range(PyZ80TargetContext *context,
    const PyZ80VMValue *args, uint8_t count, PyZ80VMValue *result)
{
    int32_t start = 0, stop, step = 1;
    uint32_t distance, magnitude, extent = 0u;
    uint8_t index;
    PyZ80TargetNode *node;
    if (!count || count > 3u) return 0u;
    for (index = 0u; index < count; ++index)
        if (args[index].kind != PYZ80_VM_VALUE_I32 && args[index].kind != PYZ80_VM_VALUE_BOOL) return 0u;
    stop = (int32_t)args[0].payload;
    if (count > 1u) { start = stop; stop = (int32_t)args[1].payload; }
    if (count > 2u) step = (int32_t)args[2].payload;
    if (!step) return 0u;
    if ((step > 0 && start < stop) || (step < 0 && start > stop)) {
        if (step > 0) {
            distance = (uint32_t)stop;       /* LD.U32 stop bits */
            distance -= (uint32_t)start;    /* SUB.U32 positive mathematical distance */
            magnitude = (uint32_t)step;
        } else {
            distance = (uint32_t)start;
            distance -= (uint32_t)stop;     /* SUB.U32 handles crossing signed zero */
            magnitude = 0UL - (uint32_t)step; /* NEG.U32 also handles MIN_I32 */
        }
        --distance;                        /* DEC.U32: exclusive stop */
        extent = distance / magnitude;     /* DIV.U32: full step intervals */
        ++extent;                          /* INC.U32: include starting element */
    }
    if (extent > 65535UL || !PyZ80Target_AllocateNode(context,
            PYZ80_TARGET_NODE_RANGE, PYZ80_VM_NO_SYMBOL, result)) return 0u;
    node = &context->nodes[(uint16_t)result->payload - 1u];
    node->current.kind = PYZ80_VM_VALUE_I32;
    node->current.symbol = PYZ80_VM_NO_SYMBOL;
    node->current.payload = (uint32_t)start;
    node->item_start = (uint16_t)(uint32_t)step; /* ST.U16 low step word */
    node->item_count = (uint16_t)((uint32_t)step >> 16); /* SHR.U32 high step word */
    node->cursor = (uint16_t)extent;
    return 1u;
}

/* Tri-state: absent/foreign=0, success=1, recognized but unsupported/invalid=2.
   A bad builtin call must not fall through to a permissive external provider. */
static uint8_t invoke(void *raw, PyZ80VM *vm, uint16_t adapter_id,
    uint16_t destination, const PyZ80VMValue *args, uint8_t count,
    uint32_t raw_offset, PyZ80VMValue *result)
{
    PyZ80TargetContext *context = (PyZ80TargetContext *)raw;
    PyZ80TargetAdapterSpec record;
    const PyZ80TargetAdapterSpec *spec = &record;
    uint8_t operation, found, truth;
    uint32_t length;
    PyZ80TargetNode *method;
    (void)destination; (void)raw_offset;
    if(!PyZ80Target_ReadAdapter(context,adapter_id,&record)) return 2u;
    if(spec->operation==PYZ80_TARGET_COLLECTIONS_DEQUE_TYPE || spec->operation==PYZ80_TARGET_COLLECTIONS_DEFAULTDICT_TYPE) {
        uint16_t i;
        uint8_t type=spec->operation==PYZ80_TARGET_COLLECTIONS_DEQUE_TYPE ? PYZ80_BUILTIN_DEQUE : PYZ80_BUILTIN_DEFAULTDICT;
        if(count || !context->builtin_symbols)return 2u;
        for(i=0u;i<context->builtin_symbol_count;++i)if(context->builtin_symbols[i].operation==type) {
            result->kind=PYZ80_VM_VALUE_BUILTIN;result->symbol=context->builtin_symbols[i].symbol;
            result->payload=type;return 1u;
        }
        return 2u;
    }
    if(count && args[0].kind==PYZ80_VM_VALUE_OPAQUE &&
        (method=PyZ80Target_Node(context,args)) && method->kind==PYZ80_TARGET_NODE_NATIVE_METHOD) {
        if(!PyZ80Target_NativeMethodValid(context,method) || spec->operation!=PYZ80_TARGET_UNSUPPORTED ||
            !PyZ80Target_ReadByte(context,PYZ80_TABLE_CALL_FLAGS,adapter_id,&found) || !found) return 2u;
        operation=(uint8_t)method->class_symbol;
        if(operation==PYZ80_BUILTIN_DEQUE_CLEAR) return count==1u && PyZ80Target_DequeClear(context,&method->current) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_DEQUE_APPEND) return count==2u && PyZ80Target_DequeAppend(context,&method->current,&args[1]) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_DEQUE_POPLEFT) return count==1u && PyZ80Target_DequePopleft(context,&method->current,result) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_SET_CLEAR) return count==1u && PyZ80Target_SetClear(context,&method->current) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_LIST_CLEAR) return count==1u && PyZ80Target_ListClear(context,&method->current) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_DICT_CLEAR) return count==1u && PyZ80Target_DictClear(context,&method->current) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_LIST_APPEND) return count==2u && PyZ80Target_ListAppend(context,&method->current,&args[1]) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_LIST_POP) return count<=2u && PyZ80Target_ListPop(context,&method->current,count==2u ? &args[1] : 0,result) ? 1u : 2u;
        if(operation>=PYZ80_BUILTIN_DICT_KEYS && operation<=PYZ80_BUILTIN_DICT_ITEMS)
            return count==1u && PyZ80Target_DictView(context,&method->current,operation-PYZ80_BUILTIN_DICT_KEYS,result) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_SET_ADD) return count==2u && PyZ80Target_SetAdd(context,&method->current,&args[1]) ? 1u : 2u;
        if(operation==PYZ80_BUILTIN_SET_REMOVE || operation==PYZ80_BUILTIN_SET_DISCARD)
            return count==2u && PyZ80Target_SetRemove(context,&method->current,&args[1],operation==PYZ80_BUILTIN_SET_DISCARD) ? 1u : 2u;
        if(operation!=PYZ80_BUILTIN_DICT_GET && operation!=PYZ80_BUILTIN_DICT_POP) return 2u;
        if(count<2u || count>3u) return 2u;
        found=operation==PYZ80_BUILTIN_DICT_GET ? PyZ80Target_DictFind(context,&method->current,&args[1],result) :
            PyZ80Target_DictRemove(context,&method->current,&args[1],result);
        if(!found) return 2u;
        if(found==2u) {
            if(operation==PYZ80_BUILTIN_DICT_POP && count!=3u) return 2u;
            if(count==3u) *result=args[2];
            else { result->kind=PYZ80_VM_VALUE_NONE;result->reserved=0u;result->symbol=PYZ80_VM_NO_SYMBOL;result->payload=0u; }
        }
        return 1u;
    }
    if (spec->operation == PYZ80_TARGET_LOAD_LEXICAL_NAME || spec->operation == PYZ80_TARGET_LOAD_GLOBAL_NAME ||
        spec->operation == PYZ80_TARGET_LOAD_CLASS_NAME || spec->operation == PYZ80_TARGET_LOAD_CLASS_FREE_NAME) {
        if (count != 1u || args[0].kind != PYZ80_VM_VALUE_SYMBOL) return 2u;
        operation = lookup(context, args[0].symbol);
        if (!operation) return 0u;
        result->kind = PYZ80_VM_VALUE_BUILTIN;
        result->symbol = args[0].symbol;
        result->payload = operation;
        return 1u;
    }
    if (!count || args[0].kind != PYZ80_VM_VALUE_BUILTIN) return 0u;
    if(!PyZ80Target_Truth(context,vm,&args[0],&truth))return 2u;
    operation = (uint8_t)args[0].payload;
    if (spec->operation == PYZ80_TARGET_REQUIRE_CALLABLE) {
        if (count != 1u) return 2u;
        *result = args[0];
        return 1u;
    }
    if(operation==PYZ80_BUILTIN_ENUMERATE && spec->operation==PYZ80_TARGET_UNSUPPORTED) {
        uint16_t start,key;
        uint8_t i,source_index=0u,start_index=0u,keyword_seen=0u;
        if(count<2u || count>3u || !PyZ80Target_ReadWord(context,PYZ80_TABLE_CALL_OFFSETS,adapter_id,&start) || start==65535u) return 2u;
        for(i=1u;i<count;++i) {
            if(!PyZ80Target_ReadWord(context,PYZ80_TABLE_CALL_KEYS,start+i-1u,&key))return 2u;
            if(key==65535u) {
                if(keyword_seen)return 2u;
                if(i==1u)source_index=i;else start_index=i;
            } else {
                keyword_seen=1u;
                if(PyZ80Target_Keyword(context,key)==PYZ80_KEYWORD_ITERABLE && !source_index)source_index=i;
                else if(PyZ80Target_Keyword(context,key)==PYZ80_KEYWORD_START && !start_index)start_index=i;
                else return 2u;
            }
        }
        return source_index && PyZ80Target_Enumerate(context,&args[source_index],start_index ? &args[start_index] : 0,result) ? 1u : 2u;
    }
    if (spec->operation != PYZ80_TARGET_UNSUPPORTED ||
        !PyZ80Target_ReadByte(context,PYZ80_TABLE_CALL_FLAGS,adapter_id,&found) || !found) return 2u;
    ++args; --count; /* Remove the already-evaluated callable, preserve argument order. */
    if(operation==PYZ80_BUILTIN_STATICMETHOD) {
        PyZ80VMValue wrapped;
        if(count!=1u)return 2u;
        wrapped=args[0];
        if(!PyZ80Target_AllocateNode(context,PYZ80_TARGET_NODE_STATICMETHOD,65535u,result))return 2u;
        PyZ80Target_Node(context,result)->current=wrapped;return 1u;
    }
    if(operation==PYZ80_BUILTIN_MIN || operation==PYZ80_BUILTIN_MAX)
        return PyZ80Target_FastExtremum(operation,args,count,result) ? 1u : 2u;
    if (operation == PYZ80_BUILTIN_BOOL) {
        if (count > 1u) return 2u;
        truth = 0u;
        if (count && !PyZ80VM_Truth(vm, args, &truth)) return 2u;
        result->kind = PYZ80_VM_VALUE_BOOL;
        result->payload = truth;
        return 1u;
    }
    if (operation == PYZ80_BUILTIN_LEN) {
        if (count != 1u) return 2u;
        if (!(args[0].kind == PYZ80_VM_VALUE_SYMBOL ? PyZ80VM_StringLength(vm, args, &length) :
                PyZ80Target_Length(context, args, &length))) return 2u;
        result->kind = PYZ80_VM_VALUE_I32;
        result->payload = length;
        return 1u;
    }
    if (operation == PYZ80_BUILTIN_GETATTR || operation==PYZ80_BUILTIN_HASATTR) {
        if ((count != 2u && count != 3u) || args[1].kind != PYZ80_VM_VALUE_SYMBOL) return 2u;
        if(operation==PYZ80_BUILTIN_HASATTR && count!=2u)return 2u;
        found = PyZ80Target_FindAttribute(context, &args[0], args[1].symbol, result);
        if(operation==PYZ80_BUILTIN_HASATTR) {
            /* Ошибка/неподдержанный протокол — не отсутствие атрибута. */
            if(!found)return 2u;
            result->kind=PYZ80_VM_VALUE_BOOL;result->reserved=0u;
            result->symbol=PYZ80_VM_NO_SYMBOL;result->payload=found==1u;return 1u;
        }
        if (found == 1u) return 1u;
        if (found == 2u && count == 3u) { *result = args[2]; return 1u; }
        return 2u;
    }
    if (operation == PYZ80_BUILTIN_RANGE) return make_range(context, args, count, result) ? 1u : 2u;
    if(operation==PYZ80_BUILTIN_REVERSED)
        return count==1u && PyZ80Target_Reversed(context,args,result) ? 1u : 2u;
    if(operation==PYZ80_BUILTIN_SET || operation==PYZ80_BUILTIN_FROZENSET)
        return count<=1u && PyZ80Target_SetFrom(context,count ? args : 0,operation==PYZ80_BUILTIN_FROZENSET,result) ? 1u : 2u;
    return 2u; /* object construction belongs to the attached class protocol. */
}

void PyZ80Target_EnableBuiltins(PyZ80TargetContext *context)
{
    if (context != 0) context->builtin_provider = invoke;
}
