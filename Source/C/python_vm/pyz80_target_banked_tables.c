#include <string.h>
#include "pyz80_target_banked_tables.h"

static uint8_t width(uint8_t table)
{
    if(table==PYZ80_TABLE_ADAPTERS) return 4u;
    if(table==PYZ80_TABLE_SIGNATURES) return 6u;
    if(table==PYZ80_TABLE_CALL_FLAGS || table==PYZ80_TABLE_CLASS_FLAGS) return 1u;
    return 2u;
}
static uint16_t u16(const uint8_t *p) { return (uint16_t)p[0] | ((uint16_t)p[1]<<8); }
static uint32_t u32(const uint8_t *p) { return (uint32_t)u16(p) | ((uint32_t)u16(p+2)<<16); }

static uint8_t read_record(void *raw, uint8_t table, uint16_t index, void *record)
{
    PyZ80TargetBankedTables *state=raw;
    uint8_t bytes[6],size;
    uint32_t offset;
    if(!state || !record || table>=PYZ80_TABLE_COUNT || index>=state->counts[table]) return 0u;
    size=width(table);
    offset=state->offsets[table]+(uint32_t)index*size; /* MUL/ADD.U32: NEVER truncate to a near pointer. */
    if(offset>state->image.size || size>state->image.size-offset ||
        !state->image.read(state->image.context,offset,bytes,size)) return 0u;
    if(table==PYZ80_TABLE_ADAPTERS) {
        PyZ80TargetAdapterSpec *spec=record;
        spec->operation=bytes[0];spec->argument_count=bytes[1];spec->auxiliary=u16(bytes+2);
    } else if(table==PYZ80_TABLE_SIGNATURES) {
        PyZ80TargetCallSignature *spec=record;
        spec->start=u16(bytes);spec->count=bytes[2];spec->positional_count=bytes[3];
        spec->positional_only_count=bytes[4];spec->supported=bytes[5];
    } else if(size==1u) *(uint8_t *)record=bytes[0];
    else *(uint16_t *)record=u16(bytes);
    return 1u;
}

static uint8_t overlaps(const void *a, uint32_t size, const void *b, uint32_t extent)
{
    uintptr_t left=(uintptr_t)a,right=(uintptr_t)b;
    if(!a || !b || !size || !extent) return 0u;
    return left<=right ? right-left<size : left-right<extent;
}
static uint8_t isolated(const void *p, uint32_t size, PyZ80TargetContext *objects, PyZ80VM *vm)
{
    return !overlaps(p,size,objects,sizeof(*objects)) && !overlaps(p,size,vm,sizeof(*vm)) &&
        !overlaps(p,size,vm->frames,PyZ80VM_ArenaBytes(&vm->limits)) &&
        !overlaps(p,size,objects->nodes,(uint32_t)objects->node_capacity*sizeof(*objects->nodes)) &&
        !overlaps(p,size,objects->fields,(uint32_t)objects->field_capacity*sizeof(*objects->fields)) &&
        !overlaps(p,size,objects->items,(uint32_t)objects->item_capacity*sizeof(*objects->items)) &&
        !overlaps(p,size,vm->image.expected_proof_sha256,32u);
}

uint8_t PyZ80Target_AttachBankedTables(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetBankedTables *state, const PyZ80VMImage *image, uint32_t expected_crc,
    uint16_t *keys, uint16_t key_capacity)
{
    PyZ80TargetBankedTables candidate;
    uint8_t bytes[44],table,bit,i;
    uint16_t size;
    uint32_t offset,extent,crc=0xffffffffUL,key_bytes=(uint32_t)key_capacity*2u;
    if(!objects || !vm || !state || !image || !image->read || !image->expected_proof_sha256 ||
        !vm->image.expected_proof_sha256 || vm->status!=PYZ80_VM_IDLE || vm->scope_hooks || vm->control_hooks ||
        objects->table_read || objects->scope_provider || objects->class_provider || objects->library_provider ||
        image->size<PYZ80_TABLE_IMAGE_HEADER || image->size>4194304UL || key_capacity>254u || (key_capacity && !keys) ||
        !isolated(state,sizeof(*state),objects,vm) || !isolated(keys,key_bytes,objects,vm) ||
        overlaps(state,sizeof(*state),keys,key_bytes) || overlaps(state,sizeof(*state),image,sizeof(*image)) ||
        overlaps(keys,key_bytes,image,sizeof(*image)) || overlaps(state,sizeof(*state),image->expected_proof_sha256,32u) ||
        overlaps(keys,key_bytes,image->expected_proof_sha256,32u) ||
        memcmp(image->expected_proof_sha256,vm->image.expected_proof_sha256,32u)) return 0u;
    if(!image->read(image->context,0u,bytes,44u) || memcmp(bytes,"PZTB",4u) || bytes[4]!=1u ||
        bytes[5]!=PYZ80_TABLE_COUNT || u16(bytes+6)!=PYZ80_TABLE_IMAGE_HEADER || u32(bytes+8)!=image->size ||
        memcmp(bytes+12,image->expected_proof_sha256,32u)) return 0u;
    candidate.image=*image;
    offset=PYZ80_TABLE_IMAGE_HEADER;
    for(table=0u;table<PYZ80_TABLE_COUNT;++table) {
        if(!image->read(image->context,44UL+(uint32_t)table*6u,bytes,6u)) return 0u;
        candidate.offsets[table]=u32(bytes);candidate.counts[table]=u16(bytes+4);
        extent=(uint32_t)candidate.counts[table]*width(table); /* MUL.U32: record extent can exceed 64 KiB. */
        if(candidate.offsets[table]!=offset || offset>image->size || extent>image->size-offset) return 0u;
        offset+=extent;
    }
    if(offset!=image->size || candidate.counts[PYZ80_TABLE_ADAPTERS]!=vm->header.adapter_count ||
        candidate.counts[PYZ80_TABLE_CALL_FLAGS]!=vm->header.adapter_count ||
        candidate.counts[PYZ80_TABLE_CALL_OFFSETS]!=vm->header.adapter_count ||
        candidate.counts[PYZ80_TABLE_ARITIES]!=vm->header.function_count ||
        candidate.counts[PYZ80_TABLE_SIGNATURES]!=vm->header.function_count ||
        candidate.counts[PYZ80_TABLE_CLASS_FLAGS]!=vm->header.function_count) return 0u;
    /* Startup only. No CRC loop in per-frame table access. Expected CRC is
       generated beside the proof, not accepted from potentially corrupt RAM. */
    for(offset=0u;offset<image->size;offset+=size) {
        size=image->size-offset>sizeof(bytes) ? sizeof(bytes) : (uint16_t)(image->size-offset);
        if(!image->read(image->context,offset,bytes,size)) return 0u;
        for(i=0u;i<size;++i) {
            crc^=bytes[i];
            for(bit=0u;bit<8u;++bit) crc=(crc>>1)^((crc & 1u) ? 0xedb88320UL : 0u);
        }
    }
    if((crc^0xffffffffUL)!=expected_crc) return 0u;
    *state=candidate;
    objects->adapters=0;objects->field_keys=0;objects->dispatch_functions=0;objects->positional_call_arities=0;
    objects->positional_call_flags=0;objects->call_signatures=0;objects->parameter_names=0;
    objects->call_layout_offsets=0;objects->call_layout_keys=0;objects->class_body_flags=0;
    objects->adapter_count=vm->header.adapter_count;objects->function_count=vm->header.function_count;
    objects->field_key_count=candidate.counts[PYZ80_TABLE_FIELDS];
    objects->dispatch_function_count=candidate.counts[PYZ80_TABLE_DISPATCH];
    objects->parameter_name_count=candidate.counts[PYZ80_TABLE_PARAMETERS];
    objects->call_layout_key_count=candidate.counts[PYZ80_TABLE_CALL_KEYS];
    objects->table_key_scratch=keys;objects->table_key_capacity=key_capacity;
    objects->table_context=state;objects->table_context_bytes=sizeof(*state);objects->table_read=read_record;
    return 1u;
}
