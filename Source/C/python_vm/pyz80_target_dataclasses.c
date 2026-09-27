#include <string.h>
#include "pyz80_target_dataclasses.h"

/* Symbol offsets are the generated library ABI, not game class/field names. */
#define ANNOTATIONS 0u
#define POST_INIT 1u
#define FIELDS 2u
#define PARAMS 3u
#define MATCH_ARGS 4u
#define INIT 5u
#define REPR 6u
#define EQ 7u
#define HASH 8u
#define DOC 9u
#define QUALNAME 10u
#define MODULE 28u
#define PENDING_METADATA 1u
#define PENDING_DOC 2u

static void none(PyZ80VMValue *value)
{
    memset(value,0,sizeof(*value)); value->symbol=PYZ80_VM_NO_SYMBOL;
}

static uint8_t overlaps(const void *a, uint32_t size, const void *b, uint32_t extent)
{
    uintptr_t left=(uintptr_t)a,right=(uintptr_t)b;
    if(!a || !b || !size || !extent) return 0u;
    return left<=right ? right-left<size : left-right<extent;
}

static uint8_t separate(PyZ80TargetDataclasses *context, PyZ80TargetScopes *scopes, const PyZ80DataclassPlan *plan)
{
    PyZ80TargetContext *objects=scopes->objects;
    PyZ80VM *vm=scopes->vm;
    const PyZ80VMControlHooks *hook=vm->control_hooks;
    uint16_t remaining=256u;
    uint32_t size=sizeof(*context);
    if(!PyZ80Target_TableStorageSeparate(objects,context,size)) return 0u;
    if(overlaps(context,size,scopes,sizeof(*scopes)) || overlaps(context,size,objects,sizeof(*objects)) ||
        overlaps(context,size,vm,sizeof(*vm)) || overlaps(context,size,plan,sizeof(*plan)) ||
        overlaps(context,size,plan->classes,(uint32_t)plan->class_count*sizeof(*plan->classes)) ||
        overlaps(context,size,plan->fields,(uint32_t)plan->field_count*sizeof(*plan->fields)) ||
        overlaps(context,size,plan->symbols,PYZ80_DATACLASS_SYMBOL_COUNT*sizeof(*plan->symbols)) || overlaps(context,size,plan->proof,32u) ||
        overlaps(context,size,objects->nodes,(uint32_t)objects->node_capacity*sizeof(*objects->nodes)) ||
        overlaps(context,size,objects->fields,(uint32_t)objects->field_capacity*sizeof(*objects->fields)) ||
        overlaps(context,size,objects->items,(uint32_t)objects->item_capacity*sizeof(*objects->items)) ||
        overlaps(context,size,objects->adapters,(uint32_t)objects->adapter_count*sizeof(*objects->adapters)) ||
        overlaps(context,size,vm->frames,(uint32_t)vm->limits.max_call_depth*sizeof(*vm->frames)) ||
        overlaps(context,size,vm->generators,(uint32_t)vm->limits.max_generators*sizeof(*vm->generators)) ||
        overlaps(context,size,vm->locals,((uint32_t)vm->limits.max_call_depth+vm->limits.max_generators)*vm->limits.locals_per_frame*sizeof(*vm->locals)) ||
        overlaps(context,size,vm->argument_scratch,(uint32_t)vm->limits.max_arguments*sizeof(*vm->argument_scratch)) ||
        overlaps(context,size,scopes->frame_closures,(uint32_t)scopes->frame_capacity*sizeof(*scopes->frame_closures)) ||
        overlaps(context,size,scopes->function_globals,(uint32_t)scopes->function_count*sizeof(*scopes->function_globals)) ||
        overlaps(context,size,scopes->binding_scratch,(uint32_t)scopes->binding_capacity*sizeof(*scopes->binding_scratch))) return 0u;
    while(hook && remaining--) {
        if(overlaps(context,size,hook,sizeof(*hook)) || overlaps(context,size,hook->roots,(uint32_t)hook->root_count*sizeof(*hook->roots))) return 0u;
        hook=hook->previous;
    }
    return hook==0;
}

static PyZ80TargetNode *ready_class(PyZ80TargetContext *objects, const PyZ80VMValue *value)
{
    PyZ80TargetNode *node=PyZ80Target_Node(objects,value);
    return node && node->kind==PYZ80_TARGET_NODE_CLASS && !node->reserved ? node : 0;
}

static const PyZ80DataclassClass *origin(PyZ80TargetDataclasses *context, PyZ80TargetNode *node)
{
    uint16_t i;
    for(i=0u;i<context->plan->class_count;++i)
        if(context->plan->classes[i].origin==node->cursor) return &context->plan->classes[i];
    return 0;
}

static uint8_t guard(void *raw, PyZ80TargetNode *node, uint16_t key)
{
    PyZ80TargetDataclasses *context=raw;
    const uint16_t *symbols=context->plan->symbols;
    PyZ80VMValue value;
    uint8_t truth;
    if((node->has_current & PENDING_METADATA) && (key==symbols[FIELDS] || key==symbols[PARAMS])) return 0u;
    if((node->has_current & PENDING_DOC) && key==symbols[DOC])
        return PyZ80Target_FindField(context->scopes->objects,&node->current,key,&value)==1u &&
            PyZ80VM_Truth(context->scopes->vm,&value,&truth) && truth;
    return 1u;
}

static uint8_t resolve(PyZ80TargetDataclasses *context, const PyZ80VMValue *args, PyZ80VMValue *result)
{
    PyZ80TargetContext *objects=context->scopes->objects;
    PyZ80TargetNode *node=ready_class(objects,args), *bases, *annotations;
    const PyZ80DataclassClass *spec;
    const PyZ80DataclassField *field;
    const uint16_t *symbols=context->plan->symbols;
    PyZ80VMValue value;
    uint16_t i,link;
    uint8_t found,post;
    if(!node || !(spec=origin(context,node))) return 0u;
    /* Options with arbitrary truth hooks require a separate protocol. */
    for(i=1u;i<11u;++i) if(args[i].kind!=PYZ80_VM_VALUE_BOOL || args[i].payload>1u) return 0u;
    if(args[4].payload || args[5].payload || args[6].payload || args[8].payload || args[9].payload || args[10].payload ||
        (args[1].payload && !spec->valid_init)) return 0u;
    if(node->item_count!=2u || node->item_start>objects->item_used || 2u>objects->item_used-node->item_start) return 0u;
    bases=PyZ80Target_Node(objects,&objects->items[node->item_start]);
    if(!bases || bases->kind!=PYZ80_TARGET_NODE_TUPLE || bases->item_count!=1u || bases->item_start>=objects->item_used) return 0u;
    value=objects->items[bases->item_start];
    if(value.kind!=PYZ80_VM_VALUE_BUILTIN || value.payload!=PYZ80_BUILTIN_OBJECT || value.symbol!=objects->class_symbols[42]) return 0u;
    if(!PyZ80Target_LoadField(objects,&node->current,symbols[QUALNAME],&value) ||
        value.kind!=PYZ80_VM_VALUE_SYMBOL || value.symbol!=spec->qualname) return 0u;
    /* CPython selects generated-method globals by cls.__module__, not by the
       caller of dataclass(). Reassigned module identities need module lookup;
       never silently bind the source class's old module instead. */
    if(!PyZ80Target_LoadField(objects,&node->current,symbols[MODULE],&value) ||
        value.kind!=PYZ80_VM_VALUE_SYMBOL || value.symbol!=spec->module) return 0u;
    found=PyZ80Target_FindField(objects,&node->current,symbols[ANNOTATIONS],&value);
    if(!found || (found==2u && spec->field_count)) return 0u;
    annotations=found==1u ? PyZ80Target_Node(objects,&value) : 0;
    if(found==1u && (!annotations || annotations->kind!=PYZ80_TARGET_NODE_DICT || annotations->cursor!=spec->field_count)) return 0u;
    link=annotations ? annotations->field_head : 0u;
    /* Dict links preserve insertion order. Reject mutated/reordered schemas;
       read defaults from the live namespace, never from host-side guesses. */
    for(i=0u;i<spec->field_count;++i) {
        field=&context->plan->fields[spec->field_start+i]; /* ADD.U16 bounded plan slice. */
        if(!link || link>objects->field_used || objects->fields[link-1u].key!=field->name) return 0u;
        value=objects->fields[link-1u].value;
        if(value.kind!=PYZ80_VM_VALUE_SYMBOL || value.symbol!=field->annotation) return 0u;
        link=objects->fields[link-1u].next;
        found=PyZ80Target_FindField(objects,&node->current,field->name,&value);
        if(!found || (found==1u)!=field->has_default) return 0u;
        /* Hash/descriptor hooks on opaque defaults are not bypassed. */
        if(found==1u && value.kind>PYZ80_VM_VALUE_SYMBOL) return 0u;
    }
    if(link) return 0u;
    found=PyZ80Target_FindAttribute(objects,args,symbols[POST_INIT],&value);
    if(!found) return 0u;
    post=found==1u;
    return PyZ80Target_Callable(objects,post ? spec->apply_post : spec->apply_plain,0,result);
}

static uint8_t metadata(PyZ80TargetDataclasses *context, const PyZ80VMValue *args, PyZ80VMValue *result)
{
    PyZ80TargetContext *objects=context->scopes->objects;
    PyZ80TargetNode *node=ready_class(objects,args), *tuple;
    const PyZ80DataclassClass *spec;
    const uint16_t *symbols=context->plan->symbols;
    PyZ80VMValue value,other;
    uint16_t i;
    uint8_t found,explicit_hash,truth;
    if(!node || !(spec=origin(context,node))) return 0u;
    /* The resolver has checked options/schema immediately before this source
       helper. Recheck booleans when it is called explicitly as a library API. */
    for(i=1u;i<11u;++i) if(args[i].kind!=PYZ80_VM_VALUE_BOOL || args[i].payload>1u) return 0u;
    if(args[4].payload || args[5].payload || args[6].payload || args[8].payload || args[9].payload || args[10].payload) return 0u;
    if(args[7].payload) {
        found=PyZ80Target_FindField(objects,&node->current,symbols[MATCH_ARGS],&value);
        if(!found) return 0u;
        if(found==2u) {
            if(objects->item_used>objects->item_capacity || spec->field_count>objects->item_capacity-objects->item_used ||
                !PyZ80Target_AllocateNode(objects,PYZ80_TARGET_NODE_TUPLE,65535u,&value)) return 0u;
            tuple=PyZ80Target_Node(objects,&value); tuple->item_start=objects->item_used; tuple->item_count=spec->field_count;
            for(i=0u;i<spec->field_count;++i) {
                none(&other); other.kind=PYZ80_VM_VALUE_SYMBOL; other.symbol=context->plan->fields[spec->field_start+i].name;
                objects->items[objects->item_used++]=other; /* INC.U16 bounded item cursor. */
            }
            if(!PyZ80Target_StoreField(objects,&node->current,symbols[MATCH_ARGS],&value)) return 0u;
        }
    }
    found=PyZ80Target_FindField(objects,&node->current,symbols[HASH],&value);
    if(!found) return 0u;
    explicit_hash=found==1u;
    if(explicit_hash && value.kind==PYZ80_VM_VALUE_NONE) {
        found=PyZ80Target_FindField(objects,&node->current,symbols[EQ],&other);
        if(!found) return 0u;
        if(found==1u) explicit_hash=0u;
    }
    if(args[3].payload && !explicit_hash) {
        none(&value);
        if(!PyZ80Target_StoreField(objects,&node->current,symbols[HASH],&value)) return 0u;
    }
    node->has_current |= PENDING_METADATA;
    found=PyZ80Target_FindField(objects,&node->current,symbols[DOC],&value);
    if(!found) return 0u;
    truth=0u;
    if(found==1u && !PyZ80VM_Truth(context->scopes->vm,&value,&truth)) return 0u;
    if(!truth) node->has_current |= PENDING_DOC;
    none(result);
    return 1u;
}

static uint8_t invoke(void *raw, PyZ80VM *vm, uint16_t adapter, uint16_t destination,
    const PyZ80VMValue *args, uint8_t count, uint32_t offset, PyZ80VMValue *result)
{
    PyZ80TargetDataclasses *context=raw;
    PyZ80TargetContext *objects=context->scopes->objects;
    PyZ80TargetNode *node,*function;
    PyZ80VMValue previous;
    PyZ80TargetAdapterSpec spec;
    uint8_t operation,found;
    (void)destination;(void)offset;
    if(vm!=context->scopes->vm || adapter>=objects->adapter_count || !result || (count && !args)) return 0u;
    if(!PyZ80Target_ReadAdapter(objects,adapter,&spec)) return 0u;
    operation=spec.operation;
    if(operation==PYZ80_TARGET_DATACLASS_RESOLVE) return count==11u && resolve(context,args,result);
    if(operation==PYZ80_TARGET_DATACLASS_METADATA) return count==11u && metadata(context,args,result);
    if(operation!=PYZ80_TARGET_DATACLASS_INSTALL || count!=3u || args[1].kind!=PYZ80_VM_VALUE_SYMBOL ||
        !(node=ready_class(objects,args)) || !origin(context,node) ||
        !(function=PyZ80Target_Node(objects,&args[2])) || function->kind!=PYZ80_TARGET_NODE_CALLABLE ||
        (function->reserved!=0u && function->reserved!=2u)) return 0u;
    if(args[1].symbol!=context->plan->symbols[INIT] && args[1].symbol!=context->plan->symbols[REPR] &&
        args[1].symbol!=context->plan->symbols[EQ]) return 0u;
    found=PyZ80Target_FindField(objects,&node->current,args[1].symbol,&previous);
    if(!found || (found==2u && !PyZ80Target_StoreField(objects,&node->current,args[1].symbol,&args[2]))) return 0u;
    none(result); result->kind=PYZ80_VM_VALUE_BOOL; result->payload=found==1u;
    return 1u;
}

uint8_t PyZ80Target_AttachDataclasses(PyZ80TargetDataclasses *context,
    PyZ80TargetScopes *scopes, const PyZ80DataclassPlan *plan)
{
    PyZ80TargetContext *objects;
    PyZ80VM *vm;
    uint16_t i,j;
    const PyZ80DataclassClass *spec;
    PyZ80TargetCallSignature signature_record;
    const PyZ80TargetCallSignature *signature=&signature_record;
    uint8_t flags;
    if(!context || !scopes || !plan || !(objects=scopes->objects) || !(vm=scopes->vm) ||
        vm->status!=PYZ80_VM_IDLE || !vm->image.expected_proof_sha256 || !objects->class_provider ||
        objects->library_provider || objects->class_library_guard || !objects->class_symbols || !PyZ80Target_HasTable(objects,PYZ80_TABLE_CLASS_FLAGS) ||
        !PyZ80Target_HasTable(objects,PYZ80_TABLE_SIGNATURES) || !plan->symbols || !plan->proof ||
        (plan->class_count && !plan->classes) || (plan->field_count && !plan->fields) ||
        memcmp(plan->proof,vm->image.expected_proof_sha256,32u) || !separate(context,scopes,plan)) return 0u;
    for(i=0u;i<PYZ80_DATACLASS_SYMBOL_COUNT;++i)
        if(plan->symbols[i]>=vm->header.constant_count) return 0u;
    for(i=0u;i<plan->field_count;++i)
        if(plan->fields[i].name>=vm->header.constant_count || plan->fields[i].annotation>=vm->header.constant_count ||
            plan->fields[i].has_default>1u) return 0u;
    for(i=0u;i<plan->class_count;++i) {
        spec=&plan->classes[i];
        if(spec->origin>=objects->function_count || !PyZ80Target_ReadByte(objects,PYZ80_TABLE_CLASS_FLAGS,spec->origin,&flags) || !flags ||
            spec->qualname>=vm->header.constant_count || spec->module>=vm->header.constant_count || spec->field_start>plan->field_count ||
            spec->field_count>plan->field_count-spec->field_start || spec->valid_init>1u ||
            spec->apply_plain>=objects->function_count || spec->apply_post>=objects->function_count) return 0u;
        for(j=0u;j<i;++j) if(plan->classes[j].origin==spec->origin) return 0u;
        if(!PyZ80Target_ReadSignature(objects,spec->apply_plain,&signature_record)) return 0u;
        if(!signature->supported || signature->count!=13u || signature->positional_count!=13u) return 0u;
        if(!PyZ80Target_ReadSignature(objects,spec->apply_post,&signature_record)) return 0u;
        if(!signature->supported || signature->count!=13u || signature->positional_count!=13u) return 0u;
        for(j=0u;j<spec->field_count;++j) {
            uint16_t k;
            for(k=0u;k<j;++k) if(plan->fields[spec->field_start+j].name==plan->fields[spec->field_start+k].name) return 0u;
        }
    }
    context->scopes=scopes; context->plan=plan;
    objects->library_context=context; objects->library_provider=invoke; objects->class_library_guard=guard;
    return 1u;
}
