/* Host-only differential runner for one integer-argument PZVT function.
 *
 * The executable is deliberately artifact-independent: it reads a PZVT image
 * at runtime, so changing translated Python does not require recompiling this
 * harness.  The Python driver supplies the exact proof digest, function ID and
 * the one allowed ``python-compare/lt`` adapter identity.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pyz80_whole_program_vm.h"

#define TRACE_LIMIT 16u

static uint16_t allowed_adapter;
static uint16_t lt_symbol;
static uint8_t trace_count;
static int32_t trace_right[TRACE_LIMIT];

static int hex_nibble(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static uint8_t parse_digest(const char *text, uint8_t digest[32])
{
    uint8_t index;
    if (text == NULL || strlen(text) != 64u) return 0u;
    for (index = 0u; index < 32u; ++index) {
        int high = hex_nibble(text[index * 2u]);
        int low = hex_nibble(text[index * 2u + 1u]);
        if (high < 0 || low < 0) return 0u;
        digest[index] = (uint8_t)((high << 4) | low);
    }
    return 1u;
}

static uint8_t parse_u32(const char *text, uint32_t maximum, uint32_t *value)
{
    char *end;
    unsigned long parsed;
    if (text == NULL || *text == '\0') return 0u;
    parsed = strtoul(text, &end, 10);
    if (*end != '\0' || parsed > maximum) return 0u;
    *value = (uint32_t)parsed;
    return 1u;
}

static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t adapter_id,
                      uint16_t destination_symbol,
                      const PyZ80VMValue *arguments, uint8_t argument_count,
                      uint32_t raw_arguments_offset, PyZ80VMValue *result)
{
    int32_t left;
    int32_t right;
    (void)context;
    (void)vm;
    (void)destination_symbol;
    (void)raw_arguments_offset;
    if (adapter_id != allowed_adapter || arguments == NULL || result == NULL ||
        argument_count != 3u || arguments[0].kind != PYZ80_VM_VALUE_SYMBOL ||
        arguments[0].symbol != lt_symbol ||
        arguments[1].kind != PYZ80_VM_VALUE_I32 ||
        arguments[2].kind != PYZ80_VM_VALUE_I32 || trace_count >= TRACE_LIMIT)
        return 0u;
    left = (int32_t)arguments[1].payload;
    right = (int32_t)arguments[2].payload;
    trace_right[trace_count++] = right;
    result->kind = PYZ80_VM_VALUE_BOOL;
    result->reserved = 0u;
    result->symbol = PYZ80_VM_NO_SYMBOL;
    result->payload = left < right;
    return 1u;
}

static uint8_t *read_image(const char *path, uint32_t *size)
{
    FILE *stream;
    long length;
    uint8_t *bytes;
    stream = fopen(path, "rb");
    if (stream == NULL || fseek(stream, 0, SEEK_END) != 0) {
        if (stream != NULL) fclose(stream);
        return NULL;
    }
    length = ftell(stream);
    if (length <= 0 || (unsigned long)length > 0xFFFFFFFFul ||
        fseek(stream, 0, SEEK_SET) != 0) {
        fclose(stream);
        return NULL;
    }
    bytes = (uint8_t *)malloc((size_t)length);
    if (bytes == NULL || fread(bytes, 1u, (size_t)length, stream) !=
            (size_t)length) {
        free(bytes);
        fclose(stream);
        return NULL;
    }
    fclose(stream);
    *size = (uint32_t)length;
    return bytes;
}

int main(int argc, char **argv)
{
    uint8_t proof_digest[32];
    uint8_t *image_bytes;
    uint8_t *arena;
    uint32_t image_size;
    uint32_t function_index;
    uint32_t adapter_id;
    uint32_t operator_symbol;
    uint32_t max_depth;
    uint32_t locals_per_frame;
    uint32_t max_arguments;
    uint16_t arena_size;
    uint16_t charge;
    PyZ80VMMemoryImage memory;
    PyZ80VMImage image;
    PyZ80VMAdapter adapter;
    PyZ80VMLimits limits;
    PyZ80VM vm;
    PyZ80VMValue argument;
    PyZ80VMValue result;
    if (argc != 9 || !parse_digest(argv[2], proof_digest) ||
        !parse_u32(argv[3], 0xFFFFu, &function_index) ||
        !parse_u32(argv[4], 0xFFFFu, &adapter_id) ||
        !parse_u32(argv[5], 0xFFFFu, &operator_symbol) ||
        !parse_u32(argv[6], 0xFFu, &max_depth) || max_depth == 0u ||
        !parse_u32(argv[7], 0xFFFFu, &locals_per_frame) ||
        locals_per_frame == 0u ||
        !parse_u32(argv[8], 0xFFu, &max_arguments) || max_arguments == 0u) {
        fputs("usage/input error\n", stderr);
        return 2;
    }
    image_bytes = read_image(argv[1], &image_size);
    if (image_bytes == NULL) return 3;
    allowed_adapter = (uint16_t)adapter_id;
    lt_symbol = (uint16_t)operator_symbol;
    memory.bytes = image_bytes;
    memory.size = image_size;
    image.read = PyZ80VM_MemoryRead;
    image.context = &memory;
    image.size = image_size;
    image.expected_proof_sha256 = proof_digest;
    adapter.invoke = invoke;
    adapter.truth = NULL;
    adapter.context = NULL;
    limits.max_call_depth = (uint8_t)max_depth;
    limits.max_generators = 0u;
    limits.locals_per_frame = (uint16_t)locals_per_frame;
    limits.max_arguments = (uint8_t)max_arguments;
    arena_size = PyZ80VM_ArenaBytes(&limits);
    if (arena_size == 0u || (arena = (uint8_t *)malloc(arena_size)) == NULL) {
        free(image_bytes);
        return 4;
    }
    if (PyZ80VM_Init(&vm, &image, &adapter, arena, arena_size, &limits) !=
            PYZ80_VM_IDLE) {
        free(arena);
        free(image_bytes);
        return 5;
    }
    argument.kind = PYZ80_VM_VALUE_I32;
    argument.reserved = 0u;
    argument.symbol = PYZ80_VM_NO_SYMBOL;
    for (charge = 0u; charge <= 128u; ++charge) {
        uint8_t index;
        argument.payload = charge;
        trace_count = 0u;
        if (PyZ80VM_StartArgs(&vm, (uint16_t)function_index, &argument, 1u) !=
                PYZ80_VM_RUNNING ||
            PyZ80VM_Run(&vm, 100000u, &result) != PYZ80_VM_RETURNED ||
            result.kind != PYZ80_VM_VALUE_I32) {
            fprintf(stderr, "vm error charge=%u code=%u\n",
                    charge, PyZ80VM_LastError(&vm));
            free(arena);
            free(image_bytes);
            return 6;
        }
        printf("%u %ld %u", charge, (long)(int32_t)result.payload,
               trace_count);
        for (index = 0u; index < trace_count; ++index)
            printf(" %ld", (long)trace_right[index]);
        putchar('\n');
    }
    free(arena);
    free(image_bytes);
    return 0;
}

