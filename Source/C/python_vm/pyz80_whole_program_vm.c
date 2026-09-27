#include "pyz80_whole_program_vm.h"

#include <stddef.h>
#include <string.h>

#define PZVT_HEADER_SIZE 80u
#define PZVT_ADAPTER_BASE 16u
#define PZVT_OP_CONSTANT 1u
#define PZVT_OP_LOAD_NAME 2u
#define PZVT_OP_STORE_NAME 3u
#define PZVT_OP_BINARY_I32 4u
#define PZVT_OP_CALL 5u
#define PZVT_OP_EXPRESSION 6u
#define PZVT_OP_CONSTRUCT 7u
#define PZVT_OP_NOP 8u
#define PZVT_OP_DATACLASS_INIT 9u
#define PZVT_OP_GUARDED_DISPATCH 10u
#define PZVT_OP_GUARDED_BOUND_DISPATCH 11u
#define PZVT_OP_GUARDED_LEXICAL_DISPATCH 12u
#define PZVT_OP_POSITIONAL_CLOSURE_CALL 13u
#define PZVT_OP_LOAD_LOCAL_NAME 14u
#define PZVT_OP_KEYWORD_CLOSURE_CALL 15u
#define PZVT_TERM_JUMP 1u
#define PZVT_TERM_BRANCH 2u
#define PZVT_TERM_RETURN 3u
#define PZVT_TERM_YIELD 4u
#define PZVT_TERM_YIELD_NEXT 5u
#define PZVT_C_NONE 0u
#define PZVT_C_FALSE 1u
#define PZVT_C_TRUE 2u
#define PZVT_C_I32 3u
#define PZVT_C_F64 4u
#define PZVT_C_STRING 5u
#define PZVT_C_LIST 6u
#define PZVT_C_MAP 7u
#define PZVT_C_BYTES 8u
#define PZVT_C_BIGINT 9u
#define PZVT_NAME_KEY 0x8000u

typedef struct PZVTUnit {
    uint32_t start;
    uint32_t end;
    uint32_t parameter_cursor;
    uint32_t block_directory;
    uint16_t local_limit;
    uint16_t frame_slot_count;
    uint16_t block_count;
    uint16_t entry_block;
    uint16_t parameter_count;
    uint8_t lexical_parent_mode;
} PZVTUnit;

static uint8_t vm_fail(PyZ80VM *vm, uint8_t error)
{
    uint8_t first;
    uint16_t index;
    if (vm == NULL) return PYZ80_VM_ERROR;
    first = vm->status != PYZ80_VM_ERROR;
    vm->error = error;
    vm->status = PYZ80_VM_ERROR;
    /* Необработанная ошибка завершает все выполнявшиеся генераторы.
       Приостановленные независимые генераторы остаются нетронутыми. */
    if (first && vm->generators != NULL) {
        for (index = 0u; index < vm->limits.max_generators; ++index)
            if (vm->generators[index].in_use && vm->generators[index].reserved) {
                vm->generators[index].done = 1u;
                vm->generators[index].reserved = 0u;
            }
        vm->active_generator = PYZ80_VM_NO_GENERATOR;
    }
    if (first && vm->control_hooks != NULL && vm->control_hooks->failed != NULL)
        vm->control_hooks->failed(vm->control_hooks->context, vm);
    return PYZ80_VM_ERROR;
}

uint8_t PyZ80VM_Abort(PyZ80VM *vm, uint8_t error)
{
    if (vm == NULL) return PYZ80_VM_ERROR;
    return vm_fail(vm, error ? error : PYZ80_VM_E_ARGUMENT);
}

static uint8_t image_read(const PyZ80VM *vm, uint32_t offset,
                          uint8_t *destination, uint16_t size)
{
    if (offset > vm->image.size || (uint32_t)size > vm->image.size - offset)
        return 0u;
    return vm->image.read(vm->image.context, offset, destination, size);
}

static uint8_t rd8(const PyZ80VM *vm, uint32_t offset, uint8_t *value)
{
    return image_read(vm, offset, value, 1u);
}

static uint8_t rd16(const PyZ80VM *vm, uint32_t offset, uint16_t *value)
{
    uint8_t bytes[2];
    if (!image_read(vm, offset, bytes, 2u)) return 0u;
    *value = (uint16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8));
    return 1u;
}

static uint8_t rd32(const PyZ80VM *vm, uint32_t offset, uint32_t *value)
{
    uint8_t bytes[4];
    if (!image_read(vm, offset, bytes, 4u)) return 0u;
    *value = (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
             ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
    return 1u;
}

static uint8_t rd24(const PyZ80VM *vm, uint32_t offset, uint32_t *value)
{
    uint8_t bytes[3];
    if (!image_read(vm, offset, bytes, 3u)) return 0u;
    *value = (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
             ((uint32_t)bytes[2] << 16);
    return 1u;
}

static uint8_t read_uvar(const PyZ80VM *vm, uint32_t *cursor,
                         uint32_t end, uint32_t *value)
{
    uint8_t byte;
    uint8_t count;
    uint8_t shift = 0u;
    uint32_t result = 0u;
    for (count = 0u; count != 5u; ++count) {
        if (*cursor >= end || !rd8(vm, *cursor, &byte)) return 0u;
        ++*cursor;
        result |= ((uint32_t)(byte & 0x7Fu)) << shift;
        if (!(byte & 0x80u)) {
            *value = result;
            return 1u;
        }
        shift = (uint8_t)(shift + 7u);
    }
    return 0u;
}

static uint32_t crc32_image(const PyZ80VM *vm, uint32_t offset,
                            uint32_t size, uint8_t *ok)
{
    uint32_t crc = 0xFFFFFFFFul;
    uint32_t index;
    uint8_t byte;
    uint8_t bit;
    *ok = 0u;
    for (index = 0u; index < size; ++index) {
        if (!rd8(vm, offset + index, &byte)) return 0u;
        crc ^= byte;
        for (bit = 0u; bit != 8u; ++bit)
            crc = (crc >> 1) ^ ((crc & 1u) ? 0xEDB88320ul : 0u);
    }
    *ok = 1u;
    return crc ^ 0xFFFFFFFFul;
}

static PyZ80VMLocal *frame_locals(PyZ80VM *vm, uint8_t depth)
{
    return vm->locals + (uint16_t)depth * vm->limits.locals_per_frame;
}

static PyZ80VMLocal *generator_locals(PyZ80VM *vm, uint16_t handle)
{
    uint16_t base = (uint16_t)vm->limits.max_call_depth + handle;
    return vm->locals + base * vm->limits.locals_per_frame;
}

static uint8_t local_get_frame(PyZ80VM *vm, uint8_t depth, uint16_t key,
                               PyZ80VMValue *value)
{
    PyZ80VMFrame *frame = &vm->frames[depth];
    PyZ80VMLocal *locals = frame_locals(vm, depth);
    uint16_t index;
    for (index = 0u; index < frame->local_count; ++index) {
        if (locals[index].symbol == key) {
            *value = locals[index].value;
            return 1u;
        }
    }
    return 0u;
}

static uint8_t local_get_name_until(PyZ80VM *vm, uint16_t constant,
                              PyZ80VMValue *value, uint16_t owner_unit)
{
    uint8_t depth;
    uint8_t parent;
    PyZ80VMFrame *frame;
    uint16_t key = (uint16_t)(PZVT_NAME_KEY | constant);
    if (!vm->call_depth) return 0u;
    depth = (uint8_t)(vm->call_depth - 1u);
    for (;;) {
        frame = &vm->frames[depth];
        if (local_get_frame(vm, depth, key, value)) {
            if (value->kind != PYZ80_VM_VALUE_CELL) return 1u;
            if (vm->scope_hooks == NULL || vm->scope_hooks->cell == NULL ||
                !vm->scope_hooks->cell(vm->scope_hooks->context,
                    PYZ80_VM_CELL_READ, value, NULL, value)) {
                vm_fail(vm, PYZ80_VM_E_UNBOUND);
                return 0u;
            }
            return 1u;
        }
        if (frame->unit == owner_unit) return 0u;
        parent = frame->lexical_parent_depth;
        /* A lexical link must point strictly down the explicit VM stack.
         * This bounded walk cannot escape into arbitrary caller frames. */
        if (parent == 0xFFu) return 0u;
        if (parent >= depth) return 0u;
        depth = parent;
    }
}

static uint8_t local_get_name(PyZ80VM *vm, uint16_t constant, PyZ80VMValue *value)
{
    return local_get_name_until(vm, constant, value, 65535u);
}

uint8_t PyZ80VM_ReadLocalName(PyZ80VM *vm, uint8_t depth, uint16_t name, PyZ80VMValue *result)
{
    if (!vm || !result || depth >= vm->call_depth || name >= 0x8000u || name >= vm->header.constant_count ||
        !local_get_frame(vm, depth, (uint16_t)(PZVT_NAME_KEY | name), result)) return 0u;
    return result->kind != PYZ80_VM_VALUE_CELL || (vm->scope_hooks && vm->scope_hooks->cell &&
        vm->scope_hooks->cell(vm->scope_hooks->context, PYZ80_VM_CELL_READ, result, NULL, result));
}

static uint8_t local_put(PyZ80VM *vm, uint8_t depth, uint16_t key,
                         const PyZ80VMValue *value)
{
    PyZ80VMFrame *frame = &vm->frames[depth];
    PyZ80VMLocal *locals = frame_locals(vm, depth);
    uint16_t index;
    for (index = 0u; index < frame->local_count; ++index) {
        if (locals[index].symbol == key) {
            if ((key & PZVT_NAME_KEY) &&
                locals[index].value.kind == PYZ80_VM_VALUE_CELL) {
                PyZ80VMValue ignored;
                return vm->scope_hooks != NULL && vm->scope_hooks->cell != NULL &&
                    vm->scope_hooks->cell(vm->scope_hooks->context,
                        PYZ80_VM_CELL_WRITE, &locals[index].value, value, &ignored);
            }
            locals[index].value = *value;
            return 1u;
        }
    }
    if (frame->local_count >= vm->limits.locals_per_frame) return 0u;
    locals[frame->local_count].symbol = key;
    locals[frame->local_count].value = *value;
    ++frame->local_count;
    return 1u;
}

uint8_t PyZ80VM_CaptureName(PyZ80VM *vm, uint16_t name, PyZ80VMValue *result)
{
    uint8_t depth;
    uint8_t parent;
    uint16_t index;
    uint16_t key;
    PyZ80VMFrame *frame;
    PyZ80VMLocal *locals;
    PyZ80VMValue cell;
    if (vm == NULL || result == NULL || !vm->call_depth || name >= 0x8000u ||
        name >= vm->header.constant_count || vm->scope_hooks == NULL ||
        vm->scope_hooks->cell == NULL) return 0u;
    key = PZVT_NAME_KEY | name;
    depth = vm->call_depth - 1u;
    for (;;) {
        frame = &vm->frames[depth];
        locals = frame_locals(vm, depth);
        for (index = 0u; index < frame->local_count; ++index) {
            if (locals[index].symbol != key) continue;
            if (locals[index].value.kind == PYZ80_VM_VALUE_CELL) {
                *result = locals[index].value;
                return 1u;
            }
            if (!vm->scope_hooks->cell(vm->scope_hooks->context,
                    PYZ80_VM_CELL_CREATE, NULL, &locals[index].value, &cell) ||
                cell.kind != PYZ80_VM_VALUE_CELL) {
                vm_fail(vm, PYZ80_VM_E_ADAPTER);
                return 0u;
            }
            locals[index].value = cell;
            *result = cell;
            return 1u;
        }
        parent = frame->lexical_parent_depth;
        if (parent >= depth) return 0u;
        depth = parent;
    }
}

static uint8_t constant_bounds(const PyZ80VM *vm, uint16_t index,
                               uint32_t *start, uint32_t *end)
{
    uint32_t relative;
    uint32_t next;
    if (index >= vm->header.constant_count ||
        !rd24(vm, vm->header.constant_directory_offset + (uint32_t)index * 3u,
              &relative)) return 0u;
    if ((uint16_t)(index + 1u) < vm->header.constant_count) {
        if (!rd24(vm, vm->header.constant_directory_offset +
                  (uint32_t)(index + 1u) * 3u, &next)) return 0u;
    } else next = vm->header.unit_data_offset - vm->header.constant_data_offset;
    *start = vm->header.constant_data_offset + relative;
    *end = vm->header.constant_data_offset + next;
    return *start < *end && *start >= vm->header.constant_data_offset &&
           *end <= vm->header.unit_data_offset;
}

uint8_t PyZ80VM_StringLength(const PyZ80VM *vm,
    const PyZ80VMValue *value, uint32_t *length)
{
    uint32_t cursor, end, bytes, scalar, minimum, count = 0u;
    uint8_t byte, remaining;
    if (vm == NULL || value == NULL || length == NULL ||
        value->kind != PYZ80_VM_VALUE_SYMBOL ||
        !constant_bounds(vm, value->symbol, &cursor, &end) ||
        !rd8(vm, cursor++, &byte) || byte != PZVT_C_STRING ||
        !read_uvar(vm, &cursor, end, &bytes) || bytes != end - cursor) return 0u;
    while (cursor < end) {
        if (!rd8(vm, cursor++, &byte)) return 0u;
        if (byte < 0x80u) { scalar = byte; remaining = 0u; minimum = 0u; }
        else if (byte >= 0xc2u && byte <= 0xdfu) {
            scalar = byte & 0x1fu; remaining = 1u; minimum = 0x80u;
        } else if (byte >= 0xe0u && byte <= 0xefu) {
            scalar = byte & 0x0fu; remaining = 2u; minimum = 0x800u;
        } else if (byte >= 0xf0u && byte <= 0xf4u) {
            scalar = byte & 7u; remaining = 3u; minimum = 0x10000UL;
        } else return 0u;
        while (remaining--) {
            if (cursor >= end || !rd8(vm, cursor++, &byte) || (byte & 0xc0u) != 0x80u) return 0u;
            scalar <<= 6;             /* SHL.U32 UTF-8 accumulator */
            scalar |= byte & 0x3fu;   /* OR.U32 continuation payload */
        }
        if (scalar < minimum || scalar > 0x10ffffUL ||
            (scalar >= 0xd800u && scalar <= 0xdfffu)) return 0u;
        ++count; /* INC.U32 Python counts code points, not UTF-8 bytes. */
    }
    *length = count;
    return 1u;
}

static uint8_t constant_value(PyZ80VM *vm, uint16_t index,
                              PyZ80VMValue *value)
{
    uint32_t start;
    uint32_t end;
    uint32_t cursor;
    uint32_t raw;
    uint8_t tag;
    if (!constant_bounds(vm, index, &start, &end) || !rd8(vm, start, &tag))
        return 0u;
    cursor = start + 1u;
    value->reserved = 0u;
    value->symbol = PYZ80_VM_NO_SYMBOL;
    value->payload = 0u;
    if (tag == PZVT_C_NONE) value->kind = PYZ80_VM_VALUE_NONE;
    else if (tag == PZVT_C_FALSE || tag == PZVT_C_TRUE) {
        value->kind = PYZ80_VM_VALUE_BOOL;
        value->payload = tag == PZVT_C_TRUE;
    } else if (tag == PZVT_C_I32) {
        if (!read_uvar(vm, &cursor, end, &raw) || cursor != end) return 0u;
        value->kind = PYZ80_VM_VALUE_I32;
        value->payload = (raw >> 1) ^ (uint32_t)-(int32_t)(raw & 1u);
    } else if (tag == PZVT_C_STRING) {
        value->kind = PYZ80_VM_VALUE_SYMBOL;
        value->symbol = index;
    } else if (tag == PZVT_C_F64 || tag == PZVT_C_LIST || tag == PZVT_C_MAP ||
               tag == PZVT_C_BYTES || tag == PZVT_C_BIGINT) {
        value->kind = PYZ80_VM_VALUE_SERIALIZED;
        value->payload = index;
    } else return 0u;
    return 1u;
}

static uint8_t read_operand(PyZ80VM *vm, uint32_t *cursor, uint32_t end,
                            PyZ80VMValue *value)
{
    uint32_t encoded;
    uint16_t index;
    if (!read_uvar(vm, cursor, end, &encoded)) return 0u;
    index = (uint16_t)(encoded >> 1);
    if (encoded & 1u) return constant_value(vm, index, value);
    return local_get_frame(vm, (uint8_t)(vm->call_depth - 1u), index, value);
}

static uint8_t read_unit(const PyZ80VM *vm, uint16_t index, PZVTUnit *unit)
{
    uint32_t relative;
    uint32_t next;
    uint32_t cursor;
    uint32_t value;
    uint32_t remaining;
    if (index >= vm->header.unit_count ||
        !rd24(vm, vm->header.unit_directory_offset + (uint32_t)index * 3u,
              &relative)) return 0u;
    if ((uint16_t)(index + 1u) < vm->header.unit_count) {
        if (!rd24(vm, vm->header.unit_directory_offset +
                  (uint32_t)(index + 1u) * 3u, &next)) return 0u;
    } else next = vm->header.unit_data_size;
    unit->start = vm->header.unit_data_offset + relative;
    unit->end = vm->header.unit_data_offset + next;
    if (unit->start >= unit->end || unit->end > vm->image.size) return 0u;
    cursor = unit->start;
    if (!read_uvar(vm, &cursor, unit->end, &value) || value > 0x7FFFu) return 0u;
    unit->local_limit = (uint16_t)value;
    if (!read_uvar(vm, &cursor, unit->end, &value) ||
        value < unit->local_limit || value > 0xFFFFu) return 0u;
    unit->frame_slot_count = (uint16_t)value;
    if (!read_uvar(vm, &cursor, unit->end, &value) || !value || value > 0xFFFFu)
        return 0u;
    unit->block_count = (uint16_t)value;
    if (!read_uvar(vm, &cursor, unit->end, &value) || value >= unit->block_count)
        return 0u;
    unit->entry_block = (uint16_t)value;
    if (!read_uvar(vm, &cursor, unit->end, &value) || value > 1u) return 0u;
    unit->lexical_parent_mode = (uint8_t)value;
    if (!read_uvar(vm, &cursor, unit->end, &value) || value > 0xFFFFu) return 0u;
    unit->parameter_count = (uint16_t)value;
    unit->parameter_cursor = cursor;
    remaining = value;
    while (remaining != 0u) {
        if (!read_uvar(vm, &cursor, unit->end, &value) ||
            value >= vm->header.constant_count) return 0u;
        --remaining;
    }
    unit->block_directory = cursor;
    return cursor + (uint32_t)unit->block_count * 3u <= unit->end;
}

static uint8_t enter_block(PyZ80VM *vm, PyZ80VMFrame *frame, uint16_t block)
{
    PZVTUnit unit;
    uint32_t relative;
    uint32_t next;
    uint32_t cursor;
    uint32_t value;
    if (!read_unit(vm, frame->unit, &unit) || block >= unit.block_count ||
        !rd24(vm, unit.block_directory + (uint32_t)block * 3u, &relative))
        return 0u;
    if ((uint16_t)(block + 1u) < unit.block_count) {
        if (!rd24(vm, unit.block_directory + (uint32_t)(block + 1u) * 3u,
                  &next)) return 0u;
    } else next = unit.end - unit.start;
    cursor = unit.start + relative;
    frame->end = unit.start + next;
    if (cursor >= frame->end || frame->end > unit.end ||
        !read_uvar(vm, &cursor, frame->end, &value) ||
        (value && value - 1u >= unit.block_count) ||
        !read_uvar(vm, &cursor, frame->end, &value) || value > 0xFFFFu)
        return 0u;
    frame->instructions_remaining = (uint16_t)value;
    frame->pc = cursor;
    return 1u;
}

static uint8_t function_unit(const PyZ80VM *vm, uint16_t function,
                             uint16_t *unit)
{
    if (function >= vm->header.function_count ||
        !rd16(vm, vm->header.function_offset + (uint32_t)function * 2u, unit))
        return 0u;
    return *unit < vm->header.unit_count;
}

static uint8_t invoke_adapter(PyZ80VM *vm, uint16_t adapter_id,
                              uint16_t destination, uint8_t count,
                              uint32_t raw, PyZ80VMValue *result)
{
    if (adapter_id >= vm->header.adapter_count || vm->adapter.invoke == NULL)
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    if (!vm->adapter.invoke(vm->adapter.context, vm, adapter_id, destination,
                            vm->argument_scratch, count, raw, result))
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    return PYZ80_VM_RUNNING;
}

uint8_t PyZ80VM_Truth(PyZ80VM *vm, const PyZ80VMValue *value,
                           uint8_t *truth)
{
    uint32_t length;
    if (vm == NULL || value == NULL || truth == NULL) return 0u;
    if (value->kind == PYZ80_VM_VALUE_NONE) *truth = 0u;
    else if (value->kind == PYZ80_VM_VALUE_BOOL ||
             value->kind == PYZ80_VM_VALUE_I32) *truth = value->payload != 0u;
    else if (value->kind == PYZ80_VM_VALUE_SYMBOL) {
        if (!PyZ80VM_StringLength(vm, value, &length)) return 0u;
        *truth = length != 0u;
    } else {
        if (vm->adapter.truth == NULL ||
            !vm->adapter.truth(vm->adapter.context, vm, value, truth)) return 0u;
        *truth = *truth != 0u;
    }
    return 1u;
}

static uint8_t push_unit(PyZ80VM *vm, uint16_t unit_index,
                         uint16_t return_symbol,
                         const PyZ80VMValue *arguments, uint8_t argument_count,
                         uint8_t lexical_parent_depth)
{
    PZVTUnit unit;
    PyZ80VMFrame *frame;
    uint32_t cursor;
    uint32_t constant;
    uint16_t index;
    uint8_t depth;
    if (vm->call_depth >= vm->limits.max_call_depth)
        return vm_fail(vm, PYZ80_VM_E_CALL_OVERFLOW);
    if (!read_unit(vm, unit_index, &unit) || argument_count != unit.parameter_count)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    if (unit.frame_slot_count > vm->limits.locals_per_frame)
        return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
    if ((unit.lexical_parent_mode && lexical_parent_depth == 0xFFu) ||
        (!unit.lexical_parent_mode && lexical_parent_depth != 0xFFu))
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    depth = vm->call_depth;
    frame = &vm->frames[depth];
    frame->unit = unit_index;
    frame->local_count = 0u;
    frame->return_symbol = return_symbol;
    frame->lexical_parent_depth = lexical_parent_depth;
    frame->reserved = 0u;
    ++vm->call_depth;
    if (vm->scope_hooks != NULL && vm->scope_hooks->enter != NULL &&
        !vm->scope_hooks->enter(vm->scope_hooks->context, vm))
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    cursor = unit.parameter_cursor;
    for (index = 0u; index < argument_count; ++index) {
        if (!read_uvar(vm, &cursor, unit.end, &constant) || constant >= 0x8000u ||
            !local_put(vm, depth, (uint16_t)(PZVT_NAME_KEY | constant),
                       &arguments[index]))
            return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
    }
    if (!enter_block(vm, frame, unit.entry_block))
        return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    return PYZ80_VM_RUNNING;
}

/* Добавляет сохранённый кадр; не выполняет ни одной инструкции тела.
   reserved у генератора равен глубине его активного кадра, либо нулю. */
static uint8_t push_generator(PyZ80VM *vm, uint16_t handle)
{
    PyZ80VMGenerator *generator;
    PyZ80VMFrame *frame;
    uint16_t index;
    PyZ80VMLocal *source;
    PyZ80VMLocal *destination;
    if (handle >= vm->limits.max_generators)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    generator = &vm->generators[handle];
    if (!generator->in_use || generator->done || generator->reserved)
        return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
    if (vm->call_depth >= vm->limits.max_call_depth)
        return vm_fail(vm, PYZ80_VM_E_CALL_OVERFLOW);
    if (generator->local_count > vm->limits.locals_per_frame ||
        (generator->lexical_parent_depth != 0xFEu && generator->lexical_parent_depth != 0xFFu))
        return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
    frame = &vm->frames[vm->call_depth];
    frame->unit = generator->unit;
    frame->local_count = generator->local_count;
    frame->return_symbol = handle;
    frame->instructions_remaining = generator->instructions_remaining;
    frame->lexical_parent_depth = generator->lexical_parent_depth;
    frame->reserved = PYZ80_VM_FRAME_GENERATOR;
    frame->pc = generator->pc;
    frame->end = generator->end;
    source = generator_locals(vm, handle);
    destination = frame_locals(vm, vm->call_depth);
    for (index = 0u; index < generator->local_count; ++index)
        destination[index] = source[index];
    generator->parent_generator = vm->active_generator;
    vm->active_generator = handle;
    ++vm->call_depth; /* INC.U8: новый кадр поверх вызывающего. */
    generator->reserved = vm->call_depth;
    if (vm->scope_hooks != NULL && vm->scope_hooks->enter != NULL &&
        !vm->scope_hooks->enter(vm->scope_hooks->context, vm))
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    if (generator->callable.kind != PYZ80_VM_VALUE_NONE &&
        (vm->scope_hooks == NULL || vm->scope_hooks->bind == NULL ||
         !vm->scope_hooks->bind(vm->scope_hooks->context, vm,
             generator->function, &generator->callable)))
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    return PYZ80_VM_RUNNING;
}

static uint8_t run_instruction(PyZ80VM *vm, PyZ80VMFrame *frame)
{
    PZVTUnit unit;
    uint32_t cursor = frame->pc;
    uint32_t token;
    uint32_t raw;
    uint32_t value;
    uint32_t destination_plus;
    uint16_t destination;
    uint16_t name;
    uint16_t adapter;
    uint16_t receiver_adapter;
    uint16_t target;
    uint16_t candidate_target;
    uint16_t candidate_owner_unit;
    uint16_t selected_owner_unit;
    uint16_t selected_function;
    uint8_t count;
    uint8_t index;
    uint8_t candidate_index;
    uint8_t selected_index;
    uint8_t selected_count;
    uint8_t bound_dispatch;
    uint8_t lexical_dispatch;
    uint8_t lexical_match_count;
    uint8_t lexical_parent_depth;
    uint8_t argument_base;
    PyZ80VMValue first;
    PyZ80VMValue second;
    PyZ80VMValue result;
    int32_t left;
    int32_t right;
    int32_t output;
    if (!read_unit(vm, frame->unit, &unit) ||
        !read_uvar(vm, &cursor, frame->end, &token))
        return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    if (token == PZVT_OP_CONSTANT) {
        if (!read_uvar(vm, &cursor, frame->end, &value) ||
            value >= unit.local_limit ||
            !read_operand(vm, &cursor, frame->end, &result))
            return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        destination = (uint16_t)value;
    } else if (token == PZVT_OP_LOAD_NAME || token == PZVT_OP_LOAD_LOCAL_NAME) {
        if (!read_uvar(vm, &cursor, frame->end, &value) ||
            value >= unit.local_limit) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        destination = (uint16_t)value;
        if (!read_uvar(vm, &cursor, frame->end, &value) ||
            value >= vm->header.constant_count) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        name = (uint16_t)value;
        if (!read_uvar(vm, &cursor, frame->end, &value) ||
            value >= (token == PZVT_OP_LOAD_LOCAL_NAME ? vm->header.function_count : vm->header.adapter_count))
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        adapter = (uint16_t)value;
        if (token == PZVT_OP_LOAD_LOCAL_NAME) {
            if (!function_unit(vm, adapter, &target)) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
            if (!local_get_name_until(vm, name, &result, target)) return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        } else if (!local_get_name(vm, name, &result)) {
            if (vm->status == PYZ80_VM_ERROR) return PYZ80_VM_ERROR;
            if (!constant_value(vm, name, &vm->argument_scratch[0]))
                return vm_fail(vm, PYZ80_VM_E_MALFORMED);
            if (invoke_adapter(vm, adapter, destination, 1u, 0xFFFFFFFFul, &result)
                    == PYZ80_VM_ERROR) return PYZ80_VM_ERROR;
        }
    } else if (token == PZVT_OP_STORE_NAME) {
        if (!read_uvar(vm, &cursor, frame->end, &value) || value >= 0x8000u ||
            value >= vm->header.constant_count) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        name = (uint16_t)value;
        if (!read_operand(vm, &cursor, frame->end, &result) ||
            !local_put(vm, (uint8_t)(vm->call_depth - 1u),
                       (uint16_t)(PZVT_NAME_KEY | name), &result))
            return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
        frame->pc = cursor;
        return PYZ80_VM_RUNNING;
    } else if (token == PZVT_OP_BINARY_I32) {
        if (!read_uvar(vm, &cursor, frame->end, &value) ||
            value >= unit.local_limit) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        destination = (uint16_t)value;
        if (!read_uvar(vm, &cursor, frame->end, &value) || value > 7u ||
            !read_operand(vm, &cursor, frame->end, &first) ||
            !read_operand(vm, &cursor, frame->end, &second) ||
            first.kind != PYZ80_VM_VALUE_I32 || second.kind != PYZ80_VM_VALUE_I32)
            return vm_fail(vm, PYZ80_VM_E_ARITHMETIC);
        left = (int32_t)first.payload;
        right = (int32_t)second.payload;
        if (value == 0u) output = left + right;
        else if (value == 1u) output = left - right;
        else if (value == 2u) output = left * right;
        else if (value == 3u) {
            if (!right) return vm_fail(vm, PYZ80_VM_E_ARITHMETIC);
            output = left / right;
        } else if (value == 4u) {
            if (!right) return vm_fail(vm, PYZ80_VM_E_ARITHMETIC);
            output = left % right;
        } else if (value == 5u) output = left == right;
        else if (value == 6u) output = left < right;
        else output = left <= right;
        result.kind = PYZ80_VM_VALUE_I32;
        result.reserved = 0u;
        result.symbol = PYZ80_VM_NO_SYMBOL;
        result.payload = (uint32_t)output;
    } else if (token == PZVT_OP_CONSTRUCT) {
        if (!read_uvar(vm, &cursor, frame->end, &destination_plus) ||
            !destination_plus || destination_plus > unit.local_limit ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value >= vm->header.adapter_count)
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        destination = (uint16_t)(destination_plus - 1u);
        adapter = (uint16_t)value;
        raw = cursor;
        if (!read_operand(vm, &cursor, frame->end, &first) ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value >= vm->header.function_count ||
            !function_unit(vm, (uint16_t)value, &target) ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value >= vm->limits.max_arguments)
            return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
        count = (uint8_t)value;
        for (index = 0u; index < count; ++index)
            if (!read_operand(vm, &cursor, frame->end,
                              &vm->argument_scratch[index + 1u]))
                return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        vm->argument_scratch[0] = first;
        if (invoke_adapter(vm, adapter, destination, 1u, raw, &result) ==
                PYZ80_VM_ERROR || result.kind != PYZ80_VM_VALUE_OPAQUE)
            return vm_fail(vm, PYZ80_VM_E_ADAPTER);
        if (!local_put(vm, (uint8_t)(vm->call_depth - 1u), destination,
                       &result))
            return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
        vm->argument_scratch[0] = result;
        frame->pc = cursor;
        if (push_unit(vm, target, PYZ80_VM_NO_SYMBOL,
                      vm->argument_scratch, (uint8_t)(count + 1u),
                      0xFFu) == PYZ80_VM_ERROR)
            return PYZ80_VM_ERROR;
        vm->frames[vm->call_depth - 1u].reserved =
            PYZ80_VM_FRAME_REQUIRE_NONE_RETURN;
        return PYZ80_VM_RUNNING;
    } else if (token == PZVT_OP_NOP) {
        frame->pc = cursor;
        return PYZ80_VM_RUNNING;
    } else if (token == PZVT_OP_DATACLASS_INIT) {
        uint32_t post_plus;
        if (!read_uvar(vm, &cursor, frame->end, &destination_plus) ||
            !destination_plus || destination_plus > unit.local_limit ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value >= vm->header.adapter_count)
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        destination = (uint16_t)(destination_plus - 1u);
        adapter = (uint16_t)value;
        if (!read_uvar(vm, &cursor, frame->end, &post_plus) ||
            post_plus > vm->header.function_count ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            !value || value > vm->limits.max_arguments)
            return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
        count = (uint8_t)value;
        raw = cursor;
        for (index = 0u; index < count; ++index)
            if (!read_operand(vm, &cursor, frame->end,
                              &vm->argument_scratch[index]))
                return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        first = vm->argument_scratch[0];
        if (invoke_adapter(vm, adapter, destination, count, raw, &result) ==
                PYZ80_VM_ERROR || result.kind != PYZ80_VM_VALUE_NONE)
            return vm_fail(vm, PYZ80_VM_E_ADAPTER);
        if (!local_put(vm, (uint8_t)(vm->call_depth - 1u), destination,
                       &result))
            return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
        frame->pc = cursor;
        if (!post_plus) return PYZ80_VM_RUNNING;
        vm->argument_scratch[0] = first;
        if (!function_unit(vm, (uint16_t)(post_plus - 1u), &target) ||
            push_unit(vm, target, destination, vm->argument_scratch, 1u,
                      0xFFu) == PYZ80_VM_ERROR)
            return PYZ80_VM_ERROR;
        vm->frames[vm->call_depth - 1u].reserved =
            PYZ80_VM_FRAME_REQUIRE_NONE_RETURN;
        return PYZ80_VM_RUNNING;
    } else if (token == PZVT_OP_GUARDED_DISPATCH ||
               token == PZVT_OP_GUARDED_BOUND_DISPATCH ||
               token == PZVT_OP_GUARDED_LEXICAL_DISPATCH) {
        bound_dispatch = token == PZVT_OP_GUARDED_BOUND_DISPATCH;
        lexical_dispatch = token == PZVT_OP_GUARDED_LEXICAL_DISPATCH;
        argument_base = bound_dispatch ? 1u : 0u;
        if (!read_uvar(vm, &cursor, frame->end, &destination_plus) ||
            !destination_plus || destination_plus > unit.local_limit ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value >= vm->header.adapter_count)
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        destination = (uint16_t)(destination_plus - 1u);
        adapter = (uint16_t)value;
        receiver_adapter = 0u;
        if (bound_dispatch &&
            (!read_uvar(vm, &cursor, frame->end, &value) ||
             value >= vm->header.adapter_count))
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        if (bound_dispatch) receiver_adapter = (uint16_t)value;
        raw = cursor;
        if (!read_operand(vm, &cursor, frame->end,
                          &vm->argument_scratch[0]) ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            !value || value > 0xFFu)
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        count = (uint8_t)value;
        first = vm->argument_scratch[0];
        if (invoke_adapter(vm, adapter, PYZ80_VM_NO_SYMBOL, 1u, raw,
                           &result) == PYZ80_VM_ERROR ||
            result.kind != PYZ80_VM_VALUE_I32 || result.payload >= count)
            return vm_fail(vm, PYZ80_VM_E_ADAPTER);
        selected_index = (uint8_t)result.payload;
        if (bound_dispatch) {
            vm->argument_scratch[0] = first;
            vm->argument_scratch[1] = result;
            if (invoke_adapter(vm, receiver_adapter, PYZ80_VM_NO_SYMBOL, 2u,
                               0xFFFFFFFFul, &result) == PYZ80_VM_ERROR ||
                result.kind != PYZ80_VM_VALUE_OPAQUE)
                return vm_fail(vm, PYZ80_VM_E_ADAPTER);
            vm->argument_scratch[0] = result;
        }
        selected_count = 0u;
        target = 0u;
        selected_owner_unit = 0u;
        selected_function = 0u;
        for (candidate_index = 0u; candidate_index < count;
             ++candidate_index) {
            if (!read_uvar(vm, &cursor, frame->end, &value) ||
                value >= vm->header.function_count ||
                !function_unit(vm, (uint16_t)value, &candidate_target))
                return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
            if (candidate_index == selected_index) selected_function = (uint16_t)value;
            candidate_owner_unit = 0u;
            if (lexical_dispatch &&
                (!read_uvar(vm, &cursor, frame->end, &value) ||
                 value >= vm->header.function_count ||
                 !function_unit(vm, (uint16_t)value,
                                &candidate_owner_unit)))
                return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
            if (
                !read_uvar(vm, &cursor, frame->end, &raw) ||
                raw > vm->limits.max_arguments ||
                (argument_base && (raw >= vm->limits.max_arguments ||
                                   raw >= 0xFFu)))
                return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
            if (candidate_index == selected_index) {
                target = candidate_target;
                selected_owner_unit = candidate_owner_unit;
                selected_count = (uint8_t)(raw + argument_base);
            }
            for (index = 0u; index < (uint8_t)raw; ++index) {
                if (!read_operand(vm, &cursor, frame->end, &second))
                    return vm_fail(vm, PYZ80_VM_E_UNBOUND);
                if (candidate_index == selected_index)
                    vm->argument_scratch[index + argument_base] = second;
            }
        }
        frame->pc = cursor;
        lexical_parent_depth = 0xFFu;
        if (lexical_dispatch && vm->scope_hooks != NULL && vm->scope_hooks->bind != NULL) {
            /* A retained closure replaces a pointer into an active owner frame. */
            if (push_unit(vm, target, destination, vm->argument_scratch,
                          selected_count, 0xFEu) == PYZ80_VM_ERROR)
                return PYZ80_VM_ERROR;
            if (!vm->scope_hooks->bind(vm->scope_hooks->context, vm,
                                      selected_function, &first))
                return vm_fail(vm, PYZ80_VM_E_ADAPTER);
            return PYZ80_VM_RUNNING;
        }
        if (lexical_dispatch) {
            lexical_match_count = 0u;
            for (index = 0u; index < vm->call_depth; ++index) {
                if (vm->frames[index].unit == selected_owner_unit) {
                    lexical_parent_depth = index;
                    ++lexical_match_count;
                }
            }
            if (lexical_match_count != 1u)
                return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
        }
        return push_unit(vm, target, destination, vm->argument_scratch,
                         selected_count, lexical_parent_depth);
    } else if (token == PZVT_OP_CALL || token == PZVT_OP_EXPRESSION) {
        if (!read_uvar(vm, &cursor, frame->end, &destination_plus) ||
            destination_plus > unit.local_limit ||
            !read_uvar(vm, &cursor, frame->end, &value))
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        if (token == PZVT_OP_CALL) {
            if (value >= vm->header.function_count ||
                !function_unit(vm, (uint16_t)value, &target) ||
                !read_uvar(vm, &cursor, frame->end, &value) ||
                value > vm->limits.max_arguments)
                return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
            count = (uint8_t)value;
            for (index = 0u; index < count; ++index)
                if (!read_operand(vm, &cursor, frame->end,
                                  &vm->argument_scratch[index]))
                    return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        } else {
            if (value >= vm->header.unit_count)
                return vm_fail(vm, PYZ80_VM_E_MALFORMED);
            target = (uint16_t)value;
            count = 0u;
        }
        frame->pc = cursor;
        return push_unit(vm, target,
                         destination_plus ? (uint16_t)(destination_plus - 1u) :
                                            PYZ80_VM_NO_SYMBOL,
                         vm->argument_scratch, count,
                         token == PZVT_OP_EXPRESSION ?
                             (uint8_t)(vm->call_depth - 1u) : 0xFFu);
    } else if (token >= PZVT_ADAPTER_BASE || token == PZVT_OP_POSITIONAL_CLOSURE_CALL || token == PZVT_OP_KEYWORD_CLOSURE_CALL) {
        if (token == PZVT_OP_POSITIONAL_CLOSURE_CALL || token == PZVT_OP_KEYWORD_CLOSURE_CALL) {
            if (!read_uvar(vm, &cursor, frame->end, &value) || value >= vm->header.adapter_count)
                return vm_fail(vm, PYZ80_VM_E_MALFORMED);
            adapter = (uint16_t)value;
        } else adapter = (uint16_t)(token - PZVT_ADAPTER_BASE);
        if (!read_uvar(vm, &cursor, frame->end, &destination_plus) ||
            destination_plus > unit.local_limit ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value > vm->limits.max_arguments)
            return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
        count = (uint8_t)value;
        raw = cursor;
        for (index = 0u; index < count; ++index)
            if (!read_operand(vm, &cursor, frame->end,
                              &vm->argument_scratch[index]))
                return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        if (token == PZVT_OP_POSITIONAL_CLOSURE_CALL || token == PZVT_OP_KEYWORD_CLOSURE_CALL) {
            if (!count) return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
            selected_index = 0u;
            /* A callback claiming success must supply a valid function ID. */
            selected_function = PYZ80_VM_NO_SYMBOL;
            first = vm->argument_scratch[0];
            if (vm->scope_hooks != NULL && vm->scope_hooks->prepare != NULL)
                selected_index = vm->scope_hooks->prepare(vm->scope_hooks->context,
                    vm, adapter, vm->argument_scratch, &count, &selected_function);
            else if (vm->scope_hooks != NULL && vm->scope_hooks->resolve != NULL)
                selected_index = vm->scope_hooks->resolve(vm->scope_hooks->context,
                    vm, &first, (uint8_t)(count - 1u), &selected_function);
            if (token == PZVT_OP_KEYWORD_CLOSURE_CALL && selected_index &&
                vm->scope_hooks->prepare == NULL) return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
            if (selected_index > 1u) return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
            if (selected_index) {
                if (vm->scope_hooks->bind == NULL || !function_unit(vm, selected_function, &target))
                    return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
                if (vm->scope_hooks->prepare == NULL) {
                    --count; /* SUB.U8 argc, callable operand; prepare already removed it. */
                    for (index = 0u; index < count; ++index)
                        vm->argument_scratch[index] = vm->argument_scratch[index + 1u];
                }
                frame->pc = cursor;
                if (!read_unit(vm, target, &unit)) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
                if (push_unit(vm, target, destination_plus ? (uint16_t)(destination_plus - 1u) :
                              PYZ80_VM_NO_SYMBOL, vm->argument_scratch, count,
                              unit.lexical_parent_mode ? 0xFEu : 0xFFu) == PYZ80_VM_ERROR)
                    return PYZ80_VM_ERROR;
                if (!vm->scope_hooks->bind(vm->scope_hooks->context, vm, selected_function, &first))
                    return vm_fail(vm, PYZ80_VM_E_ADAPTER);
                return PYZ80_VM_RUNNING;
            }
        }
        selected_index = 0u;
        if (vm->control_hooks != NULL &&
            vm->control_hooks->dispatch != NULL && adapter < vm->header.adapter_count &&
            (vm->control_hooks->routes == NULL || vm->control_hooks->routes[adapter] != PYZ80_VM_NO_SYMBOL)) {
            selected_function = PYZ80_VM_NO_SYMBOL;
            selected_index = vm->control_hooks->dispatch(vm->control_hooks->context,
                vm, adapter, vm->argument_scratch, count, &result, &selected_function);
            if (vm->status == PYZ80_VM_ERROR) return PYZ80_VM_ERROR;
            if (selected_index == 3u || selected_index > 7u) return vm_fail(vm, PYZ80_VM_E_ADAPTER);
            if (selected_index == 6u) {
                ++frame->instructions_remaining; /* INC.U16: следующий шаг потребителя без вложенного вызова. */
                return PYZ80_VM_RUNNING;
            }
            if (selected_index == 5u) {
                ++frame->instructions_remaining; /* INC.U16: повтор после yield/return. */
                return push_generator(vm, selected_function);
            }
            if (selected_index == 2u || selected_index == 4u || selected_index == 7u) {
                if (selected_index != 2u) {
                    if (vm->control_hooks->prepare_call == NULL || vm->scope_hooks == NULL ||
                        vm->scope_hooks->bind == NULL ||
                        !vm->control_hooks->prepare_call(vm->control_hooks->context, vm,
                            &first, vm->argument_scratch, &count, &selected_function) ||
                        count > vm->limits.max_arguments)
                        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
                } else count = 0u;
                if ((selected_index!=7u && vm->control_hooks->returned == NULL) ||
                    !function_unit(vm, selected_function, &target) || !read_unit(vm, target, &unit))
                    return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
                /* INC.U16: Run already consumed this instruction; retry it
                   after the initializer, keeping pc and evaluated SSA values. */
                ++frame->instructions_remaining;
                if (push_unit(vm, target, PYZ80_VM_NO_SYMBOL, vm->argument_scratch, count,
                        selected_index != 2u && unit.lexical_parent_mode ? 0xFEu : 0xFFu)
                    == PYZ80_VM_ERROR) return PYZ80_VM_ERROR;
                vm->frames[vm->call_depth - 1u].reserved |=
                    selected_index==7u ? PYZ80_VM_FRAME_VALUE_RETURN :
                    PYZ80_VM_FRAME_CONTROL_RETURN | PYZ80_VM_FRAME_REQUIRE_NONE_RETURN;
                if (selected_index != 2u && !vm->scope_hooks->bind(vm->scope_hooks->context, vm,
                        selected_function, &first)) return vm_fail(vm, PYZ80_VM_E_ADAPTER);
                return PYZ80_VM_RUNNING;
            }
        }
        if (!selected_index && invoke_adapter(vm, adapter,
                           destination_plus ? (uint16_t)(destination_plus - 1u) :
                                              PYZ80_VM_NO_SYMBOL,
                           count, raw, &result) == PYZ80_VM_ERROR)
            return PYZ80_VM_ERROR;
        if (!destination_plus) {
            frame->pc = cursor;
            return PYZ80_VM_RUNNING;
        }
        destination = (uint16_t)(destination_plus - 1u);
    } else return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    if (!local_put(vm, (uint8_t)(vm->call_depth - 1u), destination, &result))
        return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
    frame->pc = cursor;
    return PYZ80_VM_RUNNING;
}

static uint8_t finish_generator(PyZ80VM *vm, const PyZ80VMValue *value, uint8_t yielded)
{
    PyZ80VMFrame *frame = &vm->frames[vm->call_depth - 1u];
    uint16_t handle = frame->return_symbol;
    PyZ80VMGenerator *generator;
    PyZ80VMLocal *source;
    PyZ80VMLocal *destination;
    const PyZ80VMControlHooks *hooks;
    uint16_t index, remaining;
    uint8_t handled;
    if (handle >= vm->limits.max_generators || vm->active_generator != handle)
        return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
    generator = &vm->generators[handle];
    if (!generator->in_use || generator->done || generator->reserved != vm->call_depth ||
        frame->local_count > vm->limits.locals_per_frame)
        return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
    if (yielded) {
        generator->pc = frame->pc;
        generator->end = frame->end;
        generator->unit = frame->unit;
        generator->local_count = frame->local_count;
        generator->instructions_remaining = frame->instructions_remaining;
        source = frame_locals(vm, (uint8_t)(vm->call_depth - 1u));
        destination = generator_locals(vm, handle);
        for (index = 0u; index < frame->local_count; ++index)
            destination[index] = source[index];
    }
    /* Уведомление ещё видит активные локальные корни. Повтор инструкции
       сможет забрать результат из корней своего обработчика. */
    if (vm->call_depth > 1u) {
        hooks = vm->control_hooks;
        remaining = 255u;
        handled = 0u;
        while (hooks != NULL && remaining-- && !handled) {
            if (hooks->generator_event != NULL)
                handled = hooks->generator_event(hooks->context, vm, handle, yielded, value);
            hooks = hooks->previous;
        }
        if (handled != 1u || vm->status == PYZ80_VM_ERROR)
            return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    }
    generator->done = !yielded;
    generator->reserved = 0u;
    vm->active_generator = generator->parent_generator;
    generator->parent_generator = PYZ80_VM_NO_GENERATOR;
    --vm->call_depth; /* DEC.U8: вызывающий кадр не переписывается. */
    if (vm->call_depth) return PYZ80_VM_RUNNING;
    vm->result = *value;
    vm->status = yielded ? PYZ80_VM_YIELDED : PYZ80_VM_RETURNED;
    return vm->status;
}

static uint8_t return_value(PyZ80VM *vm, const PyZ80VMValue *value)
{
    uint16_t destination;
    if (!vm->call_depth) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    if (vm->frames[vm->call_depth - 1u].reserved & PYZ80_VM_FRAME_GENERATOR)
        return finish_generator(vm, value, 0u);
    if ((vm->frames[vm->call_depth - 1u].reserved &
         PYZ80_VM_FRAME_REQUIRE_NONE_RETURN) &&
        value->kind != PYZ80_VM_VALUE_NONE)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    destination = vm->frames[vm->call_depth - 1u].return_symbol;
    if(vm->frames[vm->call_depth-1u].reserved & PYZ80_VM_FRAME_VALUE_RETURN) {
        const PyZ80VMControlHooks *hooks=vm->control_hooks;
        uint16_t remaining=255u;
        uint8_t handled=0u;
        while(hooks && remaining-- && !handled) {
            if(hooks->call_result) handled=hooks->call_result(hooks->context,vm,value);
            hooks=hooks->previous;
        }
        if(handled!=1u || vm->status==PYZ80_VM_ERROR) return vm_fail(vm,PYZ80_VM_E_ADAPTER);
    }
    if ((vm->frames[vm->call_depth - 1u].reserved & PYZ80_VM_FRAME_CONTROL_RETURN) &&
        (vm->control_hooks == NULL || vm->control_hooks->returned == NULL ||
         !vm->control_hooks->returned(vm->control_hooks->context, vm)))
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    --vm->call_depth;
    if (!vm->call_depth) {
        vm->result = *value;
        vm->status = PYZ80_VM_RETURNED;
        return PYZ80_VM_RETURNED;
    }
    if (destination != PYZ80_VM_NO_SYMBOL &&
        !local_put(vm, (uint8_t)(vm->call_depth - 1u), destination, value))
        return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
    return PYZ80_VM_RUNNING;
}

static uint8_t run_terminator(PyZ80VM *vm, PyZ80VMFrame *frame)
{
    PZVTUnit unit;
    uint32_t cursor = frame->pc;
    uint32_t token;
    uint32_t value;
    uint32_t raw;
    uint32_t first_target;
    uint32_t second_target;
    uint16_t adapter;
    uint8_t count;
    uint8_t index;
    uint8_t truth;
    PyZ80VMValue result;
    if (!read_unit(vm, frame->unit, &unit) ||
        !read_uvar(vm, &cursor, frame->end, &token))
        return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    if (token == PZVT_TERM_JUMP) {
        if (!read_uvar(vm, &cursor, frame->end, &value) ||
            value >= unit.block_count || cursor != frame->end ||
            !enter_block(vm, frame, (uint16_t)value))
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        return PYZ80_VM_RUNNING;
    }
    if (token == PZVT_TERM_BRANCH) {
        if (!read_operand(vm, &cursor, frame->end, &result) ||
            !read_uvar(vm, &cursor, frame->end, &first_target) ||
            !read_uvar(vm, &cursor, frame->end, &second_target) ||
            first_target >= unit.block_count || second_target >= unit.block_count ||
            cursor != frame->end || !PyZ80VM_Truth(vm, &result, &truth) ||
            !enter_block(vm, frame,
                         (uint16_t)(truth ? first_target : second_target)))
            return vm_fail(vm, PYZ80_VM_E_ADAPTER);
        return PYZ80_VM_RUNNING;
    }
    if (token == PZVT_TERM_RETURN || token == PZVT_TERM_YIELD || token == PZVT_TERM_YIELD_NEXT) {
        if (!read_uvar(vm, &cursor, frame->end, &value) || value > 1u)
            return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        result.kind = PYZ80_VM_VALUE_NONE;
        result.reserved = 0u;
        result.symbol = PYZ80_VM_NO_SYMBOL;
        result.payload = 0u;
        if (value && !read_operand(vm, &cursor, frame->end, &result))
            return vm_fail(vm, PYZ80_VM_E_UNBOUND);
        if (token == PZVT_TERM_RETURN) {
            if (cursor != frame->end) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
            return return_value(vm, &result);
        }
        if (!(frame->reserved & PYZ80_VM_FRAME_GENERATOR) ||
            !read_uvar(vm, &cursor, frame->end, &value) ||
            value >= unit.block_count || cursor != frame->end ||
            !enter_block(vm, frame, (uint16_t)value))
            return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
        return finish_generator(vm, &result, 1u);
    }
    if (token < PZVT_ADAPTER_BASE)
        return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    adapter = (uint16_t)(token - PZVT_ADAPTER_BASE);
    if (!read_uvar(vm, &cursor, frame->end, &value) ||
        value > vm->limits.max_arguments) return vm_fail(vm, PYZ80_VM_E_ARGUMENT_OVERFLOW);
    count = (uint8_t)value;
    raw = cursor;
    for (index = 0u; index < count; ++index)
        if (!read_operand(vm, &cursor, frame->end,
                          &vm->argument_scratch[index]))
            return vm_fail(vm, PYZ80_VM_E_UNBOUND);
    if (!read_uvar(vm, &cursor, frame->end, &value))
        return vm_fail(vm, PYZ80_VM_E_MALFORMED);
    while (value != 0u) {
        if (!read_uvar(vm, &cursor, frame->end, &first_target) ||
            first_target >= unit.block_count) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        --value;
    }
    if (cursor != frame->end ||
        invoke_adapter(vm, adapter, PYZ80_VM_NO_SYMBOL, count, raw, &result)
            == PYZ80_VM_ERROR) return PYZ80_VM_ERROR;
    return vm_fail(vm, PYZ80_VM_E_ADAPTER);
}

uint16_t PyZ80VM_ArenaBytes(const PyZ80VMLimits *limits)
{
    uint32_t bytes;
    uint32_t local_count;
    if (limits == NULL || !limits->max_call_depth ||
        !limits->locals_per_frame || !limits->max_arguments) return 0u;
    local_count = ((uint32_t)limits->max_call_depth + limits->max_generators) *
                  limits->locals_per_frame;
    bytes = (uint32_t)limits->max_call_depth * sizeof(PyZ80VMFrame) +
            (uint32_t)limits->max_generators * sizeof(PyZ80VMGenerator) +
            local_count * sizeof(PyZ80VMLocal) +
            (uint32_t)limits->max_arguments * sizeof(PyZ80VMValue);
    return bytes > 65535u ? 0u : (uint16_t)bytes;
}

uint8_t PyZ80VM_MemoryRead(void *context, uint32_t offset,
                           uint8_t *destination, uint16_t size)
{
    PyZ80VMMemoryImage *image = (PyZ80VMMemoryImage *)context;
    if (image == NULL || image->bytes == NULL || offset > image->size ||
        (uint32_t)size > image->size - offset) return 0u;
    memcpy(destination, image->bytes + offset, size);
    return 1u;
}

uint8_t PyZ80VM_Init(PyZ80VM *vm, const PyZ80VMImage *image,
                     const PyZ80VMAdapter *adapter, void *arena,
                     uint16_t arena_size, const PyZ80VMLimits *limits)
{
    uint8_t fixed[16];
    uint8_t proof_digest[32];
    uint8_t ok;
    uint8_t *bytes = (uint8_t *)arena;
    uint16_t required;
    uint16_t offset;
    uint32_t total;
    uint32_t expected_crc;
    uint32_t actual_crc;
    if (vm == NULL) return PYZ80_VM_ERROR;
    memset(vm, 0, sizeof(*vm));
    if (image == NULL || image->read == NULL || arena == NULL ||
        limits == NULL || image->expected_proof_sha256 == NULL)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    vm->image = *image;
    if (adapter != NULL) vm->adapter = *adapter;
    vm->limits = *limits;
    vm->active_generator = PYZ80_VM_NO_GENERATOR;
    required = PyZ80VM_ArenaBytes(limits);
    if (!required || arena_size < required) return vm_fail(vm, PYZ80_VM_E_ARENA);
    if (!image_read(vm, 0u, fixed, 16u) || fixed[0] != 'P' || fixed[1] != 'Z' ||
        fixed[2] != 'V' || fixed[3] != 'T' || fixed[4] != 1u || fixed[5] != 0u ||
        fixed[6] != PZVT_HEADER_SIZE || fixed[7] != 0u ||
        !rd32(vm, 8u, &total) || total != image->size ||
        !rd32(vm, 12u, &expected_crc)) return vm_fail(vm, PYZ80_VM_E_IMAGE_HEADER);
    if (!image_read(vm, 16u, proof_digest, 32u))
        return vm_fail(vm, PYZ80_VM_E_IMAGE_READ);
    if (memcmp(proof_digest, image->expected_proof_sha256, 32u) != 0)
        return vm_fail(vm, PYZ80_VM_E_PROOF_HASH);
#if !defined(PYZ80_VM_TRUST_PACKAGED_IMAGE)
    actual_crc = crc32_image(vm, PZVT_HEADER_SIZE,
                             image->size - PZVT_HEADER_SIZE, &ok);
    if (!ok) return vm_fail(vm, PYZ80_VM_E_IMAGE_READ);
    if (actual_crc != expected_crc) return vm_fail(vm, PYZ80_VM_E_IMAGE_CRC);
#else
    /* A smoke SPG is SHA-256-bound by its builder before pages are packed.
     * Avoid a multi-second bitwise CRC pass on Z80; the proof digest and all
     * structural bounds below are still checked by the real runtime. */
    (void)expected_crc;
    (void)actual_crc;
    (void)ok;
#endif
    if (!rd16(vm, 48u, &vm->header.function_count) ||
        !rd16(vm, 50u, &vm->header.unit_count) ||
        !rd16(vm, 52u, &vm->header.adapter_count) ||
        !rd16(vm, 54u, &vm->header.constant_count) ||
        !rd32(vm, 56u, &vm->header.function_offset) ||
        !rd32(vm, 60u, &vm->header.unit_directory_offset) ||
        !rd32(vm, 64u, &vm->header.constant_directory_offset) ||
        !rd32(vm, 68u, &vm->header.constant_data_offset) ||
        !rd32(vm, 72u, &vm->header.unit_data_offset) ||
        !rd32(vm, 76u, &vm->header.unit_data_size))
        return vm_fail(vm, PYZ80_VM_E_IMAGE_READ);
    if (vm->header.function_offset != PZVT_HEADER_SIZE ||
        vm->header.unit_directory_offset != vm->header.function_offset +
            (uint32_t)vm->header.function_count * 2u ||
        vm->header.constant_directory_offset != vm->header.unit_directory_offset +
            (uint32_t)vm->header.unit_count * 3u ||
        vm->header.constant_data_offset != vm->header.constant_directory_offset +
            (uint32_t)vm->header.constant_count * 3u ||
        vm->header.constant_data_offset > vm->header.unit_data_offset ||
        vm->header.unit_data_offset + vm->header.unit_data_size != image->size)
        return vm_fail(vm, PYZ80_VM_E_IMAGE_HEADER);
    offset = 0u;
    vm->frames = (PyZ80VMFrame *)(void *)(bytes + offset);
    offset += (uint16_t)limits->max_call_depth * sizeof(PyZ80VMFrame);
    vm->generators = (PyZ80VMGenerator *)(void *)(bytes + offset);
    offset += (uint16_t)limits->max_generators * sizeof(PyZ80VMGenerator);
    vm->locals = (PyZ80VMLocal *)(void *)(bytes + offset);
    offset += ((uint16_t)limits->max_call_depth + limits->max_generators) *
              limits->locals_per_frame * sizeof(PyZ80VMLocal);
    vm->argument_scratch = (PyZ80VMValue *)(void *)(bytes + offset);
    memset(arena, 0, required);
    vm->status = PYZ80_VM_IDLE;
    return PYZ80_VM_IDLE;
}

uint8_t PyZ80VM_StartArgs(PyZ80VM *vm, uint16_t function_index,
                          const PyZ80VMValue *arguments,
                          uint8_t argument_count)
{
    uint16_t unit;
    if (vm == NULL || vm->status == PYZ80_VM_RUNNING) return PYZ80_VM_ERROR;
    vm->call_depth = 0u;
    vm->active_generator = PYZ80_VM_NO_GENERATOR;
    vm->error = PYZ80_VM_E_NONE;
    if ((argument_count != 0u && arguments == NULL) ||
        argument_count > vm->limits.max_arguments)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    if (!function_unit(vm, function_index, &unit))
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    vm->status = PYZ80_VM_RUNNING;
    return push_unit(vm, unit, PYZ80_VM_NO_SYMBOL, arguments,
                     argument_count, 0xFFu);
}

uint8_t PyZ80VM_Start(PyZ80VM *vm, uint16_t function_index)
{
    return PyZ80VM_StartArgs(vm, function_index, NULL, 0u);
}

uint8_t PyZ80VM_StartClosure(PyZ80VM *vm, uint16_t function,
                            const PyZ80VMValue *callable,
                            const PyZ80VMValue *arguments, uint8_t count)
{
    uint16_t unit;
    PZVTUnit view;
    if (vm == NULL || vm->status == PYZ80_VM_RUNNING) return PYZ80_VM_ERROR;
    if (callable == NULL || vm->scope_hooks == NULL || vm->scope_hooks->bind == NULL ||
        count > vm->limits.max_arguments || (count && arguments == NULL))
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    vm->call_depth = 0u;
    vm->active_generator = PYZ80_VM_NO_GENERATOR;
    vm->error = PYZ80_VM_E_NONE;
    if (!function_unit(vm, function, &unit) || !read_unit(vm, unit, &view))
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    vm->status = PYZ80_VM_RUNNING;
    if (push_unit(vm, unit, PYZ80_VM_NO_SYMBOL, arguments, count,
                  view.lexical_parent_mode ? 0xFEu : 0xFFu) == PYZ80_VM_ERROR)
        return PYZ80_VM_ERROR;
    if (!vm->scope_hooks->bind(vm->scope_hooks->context, vm, function, callable))
        return vm_fail(vm, PYZ80_VM_E_ADAPTER);
    return PYZ80_VM_RUNNING;
}

uint8_t PyZ80VM_Run(PyZ80VM *vm, uint32_t step_budget,
                    PyZ80VMValue *result)
{
    uint32_t step;
    uint8_t status;
    PyZ80VMFrame *frame;
    if (vm == NULL || vm->status != PYZ80_VM_RUNNING)
        return vm == NULL ? PYZ80_VM_ERROR : vm->status;
    for (step = 0u; step < step_budget; ++step) {
        if (!vm->call_depth) return vm_fail(vm, PYZ80_VM_E_MALFORMED);
        frame = &vm->frames[vm->call_depth - 1u];
        if (frame->instructions_remaining) {
            --frame->instructions_remaining;
            status = run_instruction(vm, frame);
        } else status = run_terminator(vm, frame);
        if (status != PYZ80_VM_RUNNING) {
            if (result != NULL) *result = vm->result;
            return status;
        }
    }
    vm->error = PYZ80_VM_E_STEP_LIMIT;
    if (result != NULL) *result = vm->result;
    return PYZ80_VM_RUNNING;
}

uint8_t PyZ80VM_GeneratorCreate(PyZ80VM *vm, uint16_t function_index,
                                uint16_t *handle)
{
    return PyZ80VM_GeneratorCreateArgs(vm, function_index, NULL, NULL, 0u, handle);
}

uint8_t PyZ80VM_GeneratorCreateArgs(PyZ80VM *vm, uint16_t function_index,
    const PyZ80VMValue *callable, const PyZ80VMValue *arguments,
    uint8_t count, uint16_t *handle)
{
    uint16_t index;
    uint16_t argument;
    uint16_t unit_index;
    uint32_t cursor, constant;
    PZVTUnit unit;
    PyZ80VMFrame temporary;
    PyZ80VMGenerator *generator;
    PyZ80VMLocal *locals;
    if (vm == NULL || handle == NULL || !function_unit(vm, function_index, &unit_index) ||
        !read_unit(vm, unit_index, &unit) || unit.parameter_count != count ||
        count > vm->limits.max_arguments || (count && arguments == NULL))
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    if (unit.frame_slot_count > vm->limits.locals_per_frame || count > vm->limits.locals_per_frame)
        return vm_fail(vm, PYZ80_VM_E_LOCAL_OVERFLOW);
    if ((unit.lexical_parent_mode && (callable == NULL || callable->kind == PYZ80_VM_VALUE_NONE)) ||
        (callable != NULL && callable->kind != PYZ80_VM_VALUE_NONE &&
         (vm->scope_hooks == NULL || vm->scope_hooks->bind == NULL)))
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    for (index = 0u; index < vm->limits.max_generators; ++index) {
        if (!vm->generators[index].in_use) {
            memset(&temporary, 0, sizeof(temporary));
            temporary.unit = unit_index;
            if (!enter_block(vm, &temporary, unit.entry_block))
                return vm_fail(vm, PYZ80_VM_E_MALFORMED);
            locals = generator_locals(vm, index);
            cursor = unit.parameter_cursor;
            for (argument = 0u; argument < count; ++argument) {
                if (!read_uvar(vm, &cursor, unit.end, &constant) || constant >= 0x8000u)
                    return vm_fail(vm, PYZ80_VM_E_MALFORMED);
                locals[argument].symbol = (uint16_t)(PZVT_NAME_KEY | constant);
                locals[argument].value = arguments[argument];
            }
            generator = &vm->generators[index];
            memset(generator, 0, sizeof(*generator));
            generator->in_use = 1u;
            generator->unit = unit_index;
            generator->function = function_index;
            generator->parent_generator = PYZ80_VM_NO_GENERATOR;
            generator->local_count = count;
            generator->instructions_remaining = temporary.instructions_remaining;
            generator->lexical_parent_depth = unit.lexical_parent_mode ? 0xFEu : 0xFFu;
            generator->pc = temporary.pc;
            generator->end = temporary.end;
            if (callable != NULL) generator->callable = *callable;
            *handle = index;
            return PYZ80_VM_IDLE;
        }
    }
    return vm_fail(vm, PYZ80_VM_E_GENERATOR_OVERFLOW);
}

uint8_t PyZ80VM_GeneratorResume(PyZ80VM *vm, uint16_t handle,
                                const PyZ80VMValue *send_value,
                                uint32_t step_budget, PyZ80VMValue *result)
{
    if (vm == NULL || handle >= vm->limits.max_generators)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    /* Ранее ненулевой send молча отбрасывался. Неподдержанный протокол
       обязан завершиться ошибкой до выполнения тела. */
    if ((send_value != NULL && send_value->kind != PYZ80_VM_VALUE_NONE) ||
        vm->status == PYZ80_VM_RUNNING || vm->call_depth)
        return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
    vm->active_generator = PYZ80_VM_NO_GENERATOR;
    vm->error = PYZ80_VM_E_NONE;
    vm->status = PYZ80_VM_RUNNING;
    if (push_generator(vm, handle) == PYZ80_VM_ERROR) return PYZ80_VM_ERROR;
    return PyZ80VM_Run(vm, step_budget, result);
}

uint8_t PyZ80VM_GeneratorClose(PyZ80VM *vm, uint16_t handle)
{
    if (vm == NULL || handle >= vm->limits.max_generators ||
        !vm->generators[handle].in_use)
        return vm_fail(vm, PYZ80_VM_E_ARGUMENT);
    if (vm->generators[handle].reserved)
        return vm_fail(vm, PYZ80_VM_E_GENERATOR_STATE);
    memset(&vm->generators[handle], 0, sizeof(PyZ80VMGenerator));
    if (vm->active_generator == handle)
        vm->active_generator = PYZ80_VM_NO_GENERATOR;
    return PYZ80_VM_IDLE;
}

uint8_t PyZ80VM_LastError(const PyZ80VM *vm)
{
    return vm == NULL ? PYZ80_VM_E_ARGUMENT : vm->error;
}
