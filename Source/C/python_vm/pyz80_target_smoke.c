/* First real Z80 execution harness for the whole-program PZVT backend.
 *
 * This file contains no translated game rule.  It supplies only the target
 * machine's bank reader and the generic Python ``<`` adapter needed by the
 * source-generated wave_power unit.  Function/image identities are generated
 * by build_pzvt_smoke.py from the coherent translator checkpoint.
 */
#include <stdint.h>

#include "pyz80_whole_program_vm.h"
#include "pyz80_target_smoke_generated.h"

#define TS_PAGE1_REGISTER (*(volatile uint8_t *)0x0411u)
#define PZVT_WINDOW ((const uint8_t *)0x4000u)
#define PZVT_PAGE_BYTES 16384u

#define RESULT_STATUS (*(volatile uint8_t *)0x2f00u)
#define RESULT_ERROR  (*(volatile uint8_t *)0x2f01u)
#define RESULT_KIND   (*(volatile uint8_t *)0x2f02u)
#define RESULT_VALUE  (*(volatile uint8_t *)0x2f03u)
#define RESULT_VM_STATUS (*(volatile uint8_t *)0x2f04u)
#define RESULT_CALL_DEPTH (*(volatile uint8_t *)0x2f05u)
#define RESULT_FRAME_UNIT_LO (*(volatile uint8_t *)0x2f06u)
#define RESULT_FRAME_PC_LO (*(volatile uint8_t *)0x2f07u)

static PyZ80VM vm;
static uint8_t arena[PZVT_SMOKE_ARENA_BYTES];

static uint8_t bank_read(void *context, uint32_t offset,
                         uint8_t *destination, uint16_t size)
{
    uint8_t saved_page = TS_PAGE1_REGISTER;
    (void)context;
    if (destination == 0 || offset > PZVT_IMAGE_BYTES ||
        (uint32_t)size > PZVT_IMAGE_BYTES - offset)
        return 0u;
    while (size != 0u) {
        uint16_t within = (uint16_t)(offset & (PZVT_PAGE_BYTES - 1u));
        uint16_t count = (uint16_t)(PZVT_PAGE_BYTES - within);
        uint16_t copied;
        const uint8_t *source;
        if (count > size) count = size;
        copied = count;
        TS_PAGE1_REGISTER = (uint8_t)(PZVT_FIRST_PAGE +
                                      (uint8_t)(offset >> 14));
        source = PZVT_WINDOW + within;
        while (count-- != 0u) *destination++ = *source++;
        offset += copied;
        size = (uint16_t)(size - copied);
    }
    TS_PAGE1_REGISTER = saved_page;
    return 1u;
}

static uint8_t invoke(void *context, struct PyZ80VM *current,
                      uint16_t adapter_id, uint16_t destination_symbol,
                      const PyZ80VMValue *arguments, uint8_t argument_count,
                      uint32_t raw_arguments_offset, PyZ80VMValue *result)
{
    (void)context;
    (void)current;
    (void)destination_symbol;
    (void)raw_arguments_offset;
    *(volatile uint8_t *)0x2f10u = (uint8_t)adapter_id;
    *(volatile uint8_t *)0x2f11u = (uint8_t)(adapter_id >> 8);
    *(volatile uint8_t *)0x2f12u = argument_count;
    if (arguments != 0 && argument_count >= 3u) {
        *(volatile uint8_t *)0x2f13u = arguments[0].kind;
        *(volatile uint8_t *)0x2f14u = (uint8_t)arguments[0].symbol;
        *(volatile uint8_t *)0x2f15u = (uint8_t)(arguments[0].symbol >> 8);
        *(volatile uint8_t *)0x2f16u = arguments[1].kind;
        *(volatile uint8_t *)0x2f17u = arguments[2].kind;
    }
    if (adapter_id != PZVT_COMPARE_ADAPTER || argument_count != 3u ||
        arguments == 0 || result == 0 ||
        arguments[0].kind != PYZ80_VM_VALUE_SYMBOL ||
        arguments[0].symbol != PZVT_LT_SYMBOL ||
        arguments[1].kind != PYZ80_VM_VALUE_I32 ||
        arguments[2].kind != PYZ80_VM_VALUE_I32)
        return 0u;
    result->kind = PYZ80_VM_VALUE_BOOL;
    result->reserved = 0u;
    result->symbol = PYZ80_VM_NO_SYMBOL;
    result->payload = ((int32_t)arguments[1].payload <
                       (int32_t)arguments[2].payload);
    return 1u;
}

uint8_t PZVTSmoke_Run(void) __sdcccall(0)
{
    static const uint8_t proof[32] = PZVT_PROOF_SHA256_BYTES;
    PyZ80VMImage image;
    PyZ80VMAdapter adapter;
    PyZ80VMLimits limits;
    PyZ80VMValue argument;
    PyZ80VMValue result;
    uint8_t status;

    RESULT_STATUS = 0u;
    RESULT_ERROR = 0u;
    RESULT_KIND = 0u;
    RESULT_VALUE = 0u;
    RESULT_VM_STATUS = 0u;
    RESULT_CALL_DEPTH = 0u;
    RESULT_FRAME_UNIT_LO = 0u;
    RESULT_FRAME_PC_LO = 0u;
    image.read = bank_read;
    image.context = 0;
    image.size = PZVT_IMAGE_BYTES;
    image.expected_proof_sha256 = proof;
    adapter.invoke = invoke;
    adapter.truth = 0;
    adapter.context = 0;
    limits.max_call_depth = PZVT_WAVE_MAX_DEPTH;
    limits.max_generators = 0u;
    limits.locals_per_frame = PZVT_WAVE_FRAME_SLOTS;
    limits.max_arguments = 3u;
    status = PyZ80VM_Init(&vm, &image, &adapter, arena, sizeof(arena), &limits);
    if (status != PYZ80_VM_IDLE) goto done;
    argument.kind = PYZ80_VM_VALUE_I32;
    argument.reserved = 0u;
    argument.symbol = PYZ80_VM_NO_SYMBOL;
    argument.payload = PZVT_SMOKE_CHARGE;
    status = PyZ80VM_StartArgs(&vm, PZVT_WAVE_FUNCTION, &argument, 1u);
    if (status != PYZ80_VM_RUNNING) goto done;
    status = PyZ80VM_Run(&vm, 100000ul, &result);
    RESULT_KIND = result.kind;
    RESULT_VALUE = (uint8_t)result.payload;
done:
    RESULT_STATUS = status;
    RESULT_ERROR = PyZ80VM_LastError(&vm);
    RESULT_VM_STATUS = vm.status;
    RESULT_CALL_DEPTH = vm.call_depth;
    if (vm.call_depth != 0u) {
        RESULT_FRAME_UNIT_LO = (uint8_t)vm.frames[vm.call_depth - 1u].unit;
        RESULT_FRAME_PC_LO = (uint8_t)vm.frames[vm.call_depth - 1u].pc;
    }
    return status;
}
