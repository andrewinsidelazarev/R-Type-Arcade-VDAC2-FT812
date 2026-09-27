/* Аппаратно-независимая часть FT812 HAL. Никакого pixel renderer здесь нет. */
#include "pyz80_ft812.h"
#include "rtype_python_hq_templates.h"

#define PYZ80_FT_QUEUE_MAGIC 0x4651u
#define PYZ80_FT_DL_DISPLAY  0x00000000ul
#define PYZ80_FT_DL_BITMAP_SOURCE 0x01000000ul
#define PYZ80_FT_DL_BITMAP_LAYOUT 0x07000000ul
#define PYZ80_FT_DL_PALETTE_SOURCE 0x2A000000ul
#define PYZ80_FT_DL_VERTEX2F      0x40000000ul
#define PYZ80_FT_DL_VERTEX_TRANSLATE_X 0x2B000000ul
#define PYZ80_FT_DL_VERTEX_TRANSLATE_Y 0x2C000000ul
#define PYZ80_FT_DL_COLOR_WHITE       0x04FFFFFFul
#define PYZ80_FT_DL_BITMAP_SIZE_44_48 0x08005830ul
#define PYZ80_FT_DL_TRANSFORM_A_160   0x150000A0ul
#define PYZ80_FT_DL_TRANSFORM_B_0     0x16000000ul
#define PYZ80_FT_DL_TRANSFORM_C_0     0x17000000ul
#define PYZ80_FT_DL_TRANSFORM_D_0     0x18000000ul
#define PYZ80_FT_DL_TRANSFORM_E_160   0x190000A0ul
#define PYZ80_FT_DL_TRANSFORM_F_0     0x1A000000ul
#define PYZ80_FT_DL_VERTEX_FORMAT_3   0x27000003ul
#define PYZ80_FT_DL_BEGIN_BITMAPS     0x1F000001ul
#define PYZ80_FT_DL_END               0x21000000ul
#define PYZ80_FT_CMD_APPEND       0xFFFFFF1Eul
#define PYZ80_FT_BATCH_PREFIX_WORDS 10u
#define PYZ80_FT_BATCH_SUFFIX_WORDS 3u

static const uint32_t PyZ80FT_SpriteBatchPrefix[
        PYZ80_FT_BATCH_PREFIX_WORDS] = {
    PYZ80_FT_DL_COLOR_WHITE,
    PYZ80_FT_DL_TRANSFORM_A_160,
    PYZ80_FT_DL_TRANSFORM_B_0,
    PYZ80_FT_DL_TRANSFORM_C_0,
    PYZ80_FT_DL_TRANSFORM_D_0,
    PYZ80_FT_DL_TRANSFORM_E_160,
    PYZ80_FT_DL_TRANSFORM_F_0,
    PYZ80_FT_DL_BITMAP_SIZE_44_48,
    PYZ80_FT_DL_VERTEX_FORMAT_3,
    PYZ80_FT_DL_BEGIN_BITMAPS
};

/* Private page-#F0 preflight cache. It is outside the mapped ED/EE queue page,
 * so an eventual failure may discard these entries while the public header,
 * payload words and literal source records remain byte-exact. The second pass
 * never rereads volatile records and therefore cannot repeat hash/coordinate
 * lowering or observe a different record image after successful preflight. */
typedef struct PyZ80FtBatchResolved {
    int16_t vertex_x;
    int16_t vertex_y;
    uint32_t address;
    uint16_t byte_size;
} PyZ80FtBatchResolved;

_Static_assert(sizeof(PyZ80FtBatchResolved) == 10,
               "FT812 batch preflight cache ABI changed");

PyZ80FtBatchResolved
    PyZ80FT_BatchResolved[PYZ80_FT_BATCH_MAX_RECORDS];

static uint8_t PyZ80FT_QueuePageValid(uint8_t page)
{
    return page == PYZ80_FT_QUEUE_PAGE_A || page == PYZ80_FT_QUEUE_PAGE_B;
}

static uint8_t PyZ80FT_QueueKindValid(uint8_t kind)
{
    return kind == PYZ80_FT_QUEUE_FULL ||
        kind == PYZ80_FT_QUEUE_FRAGMENT;
}

static uint8_t PyZ80FT_QueueHeaderValid(volatile PyZ80FtQueue *queue)
{
    return queue->header.magic == PYZ80_FT_QUEUE_MAGIC &&
        queue->header.format == PYZ80_FT_QUEUE_FORMAT &&
        PyZ80FT_QueuePageValid(queue->header.page) &&
        PyZ80FT_QueueKindValid(queue->header.kind) &&
        queue->header.reserved == 0u;
}

static uint8_t PyZ80FT_QueueWritable(volatile PyZ80FtQueue *queue)
{
    if (!PyZ80FT_QueueHeaderValid(queue) ||
            queue->header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue->header.overflow != 0u) {
        return 0u;
    }
    return 1u;
}

/* Exact round(value*64/5), symmetric for the whole int16 domain.  The
 * Hacker's Delight shift/add quotient is exact after its residual correction;
 * no Z80 division helper or 32-bit arithmetic is required. */
uint16_t PyZ80FT_LogicalVertex(int16_t value)
    PYZ80_CALL0
{
    uint8_t negative = value < 0;
    uint16_t magnitude = negative ?
        (uint16_t)(0u - (uint16_t)value) : (uint16_t)value;
    uint16_t quotient;
    uint8_t remainder;
    uint16_t result;
    quotient = (uint16_t)((magnitude >> 1) + (magnitude >> 2));
    quotient = (uint16_t)(quotient + (quotient >> 4));
    quotient = (uint16_t)(quotient + (quotient >> 8));
    quotient >>= 2;
    remainder = (uint8_t)(
        magnitude - ((quotient << 2) + quotient));
    quotient = (uint16_t)(quotient + ((remainder + 3u) >> 3));
    remainder = (uint8_t)(
        magnitude - ((quotient << 2) + quotient));
    result = (uint16_t)(quotient << 6);
    switch (remainder) {
    case 1u:
        result = (uint16_t)(result + 13u);
        break;
    case 2u:
        result = (uint16_t)(result + 26u);
        break;
    case 3u:
        result = (uint16_t)(result + 38u);
        break;
    case 4u:
        result = (uint16_t)(result + 51u);
        break;
    default:
        break;
    }
    return negative ? (uint16_t)(0u - result) : result;
}

static void PyZ80FT_ApplyCoordSign(PyZ80FtLoweredCoord *result,
                                   uint8_t negative)
{
    if (negative) {
        result->logical = (int16_t)(-result->logical);
        result->vertex = (int16_t)(-result->vertex);
        if (result->phase != 0u) {
            result->phase = (uint8_t)(5u - result->phase);
        }
    }
}

/* For m=3q+r, round(5m/3) is 5q+{0,2,3}; applying the exact
 * logical->FT812 conversion gives 64q+{0,26,38}. The shift/add divide-by-3
 * below is the exact unsigned-16 algorithm from the geometric 1/3 series;
 * its first quotient is at most two low and its residual correction is
 * floor(11*r/32). This removes even the 16-bit runtime division helper. */
uint8_t PyZ80FT_LowerNativeX(int16_t native,
                             PyZ80FtLoweredCoord *result)
    PYZ80_CALL0
{
    uint8_t negative;
    uint16_t magnitude;
    uint16_t quotient;
    uint8_t remainder;
    PyZ80FtLoweredCoord lowered;
    if (native < PYZ80_FT_NATIVE_X_MIN ||
            native > PYZ80_FT_NATIVE_X_MAX || result == 0) {
        return 0u;
    }
    negative = native < 0;
    magnitude = negative ? (uint16_t)(-native) : (uint16_t)native;
    quotient = (uint16_t)((magnitude >> 1) + (magnitude >> 3));
    quotient = (uint16_t)(quotient + (quotient >> 4));
    quotient = (uint16_t)(quotient + (quotient >> 8));
    quotient >>= 1;
    remainder = (uint8_t)(magnitude - quotient * 3u);
    quotient = (uint16_t)(quotient +
        ((((uint16_t)remainder << 3) +
          ((uint16_t)remainder << 1) + remainder) >> 5));
    remainder = (uint8_t)(magnitude - quotient * 3u);
    lowered.logical = (int16_t)(quotient * 5u);
    lowered.vertex = (int16_t)(quotient << 6);
    if (remainder == 1u) {
        lowered.logical = (int16_t)(lowered.logical + 2);
        lowered.vertex = (int16_t)(lowered.vertex + 26);
        lowered.phase = 2u;
    } else if (remainder == 2u) {
        lowered.logical = (int16_t)(lowered.logical + 3);
        lowered.vertex = (int16_t)(lowered.vertex + 38);
        lowered.phase = 3u;
    } else {
        lowered.phase = 0u;
    }
    PyZ80FT_ApplyCoordSign(&lowered, negative);
    *result = lowered;
    return 1u;
}

/* For m=8q+r, the denominator is a shift. The r=4 half-way case is the only
 * parity-dependent one: 15q+7.5 rounds to +8 for even q and +7 for odd q.
 * The vertex constants are exact round(logical*64/5) residuals. */
uint8_t PyZ80FT_LowerNativeY(int16_t native,
                             PyZ80FtLoweredCoord *result)
    PYZ80_CALL0
{
    uint8_t negative;
    uint16_t magnitude;
    uint16_t quotient;
    uint8_t remainder;
    PyZ80FtLoweredCoord lowered;
    if (native < PYZ80_FT_NATIVE_Y_MIN ||
            native > PYZ80_FT_NATIVE_Y_MAX || result == 0) {
        return 0u;
    }
    negative = native < 0;
    magnitude = negative ? (uint16_t)(-native) : (uint16_t)native;
    quotient = magnitude >> 3;
    remainder = (uint8_t)(magnitude & 7u);
    lowered.logical = (int16_t)((quotient << 4) - quotient);
    lowered.vertex = (int16_t)((quotient << 7) + (quotient << 6));
    switch (remainder) {
    case 0u:
        lowered.phase = 0u;
        break;
    case 1u:
        lowered.logical = (int16_t)(lowered.logical + 2);
        lowered.vertex = (int16_t)(lowered.vertex + 26);
        lowered.phase = 2u;
        break;
    case 2u:
        lowered.logical = (int16_t)(lowered.logical + 4);
        lowered.vertex = (int16_t)(lowered.vertex + 51);
        lowered.phase = 4u;
        break;
    case 3u:
        lowered.logical = (int16_t)(lowered.logical + 6);
        lowered.vertex = (int16_t)(lowered.vertex + 77);
        lowered.phase = 1u;
        break;
    case 4u:
        if ((quotient & 1u) != 0u) {
            lowered.logical = (int16_t)(lowered.logical + 7);
            lowered.vertex = (int16_t)(lowered.vertex + 90);
            lowered.phase = 2u;
        } else {
            lowered.logical = (int16_t)(lowered.logical + 8);
            lowered.vertex = (int16_t)(lowered.vertex + 102);
            lowered.phase = 3u;
        }
        break;
    case 5u:
        lowered.logical = (int16_t)(lowered.logical + 9);
        lowered.vertex = (int16_t)(lowered.vertex + 115);
        lowered.phase = 4u;
        break;
    case 6u:
        lowered.logical = (int16_t)(lowered.logical + 11);
        lowered.vertex = (int16_t)(lowered.vertex + 141);
        lowered.phase = 1u;
        break;
    default:
        lowered.logical = (int16_t)(lowered.logical + 13);
        lowered.vertex = (int16_t)(lowered.vertex + 166);
        lowered.phase = 3u;
        break;
    }
    PyZ80FT_ApplyCoordSign(&lowered, negative);
    *result = lowered;
    return 1u;
}

static uint8_t PyZ80FT_QueuePushWord(volatile PyZ80FtQueue *queue,
                                     uint32_t word, uint8_t display_list)
{
    uint16_t index;
    uint16_t command_reserve;
    uint16_t dl_reserve;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    index = queue->header.count;
    command_reserve = queue->header.kind == PYZ80_FT_QUEUE_FULL ? 2u : 0u;
    dl_reserve = queue->header.kind == PYZ80_FT_QUEUE_FULL ? 1u : 0u;
    /* Only a full-frame commit needs room for DISPLAY and CMD_SWAP. */
    if (index >= PYZ80_FT_QUEUE_CAPACITY - command_reserve ||
            (display_list &&
             queue->header.dl_words >=
             PYZ80_FT_RAM_DL_WORD_LIMIT - dl_reserve)) {
        queue->header.overflow = 1u;
        return 0u;
    }
    queue->words[index] = word;
    queue->header.count = (uint16_t)(index + 1u);
    if (display_list) {
        queue->header.dl_words++;
    }
    return 1u;
}

uint8_t PyZ80FT_QueueInitialize(volatile PyZ80FtQueue *queue, uint16_t page)
    PYZ80_CALL0
{
    if (page != PYZ80_FT_QUEUE_PAGE_A && page != PYZ80_FT_QUEUE_PAGE_B) {
        return 0u;
    }
    queue->header.magic = PYZ80_FT_QUEUE_MAGIC;
    queue->header.format = PYZ80_FT_QUEUE_FORMAT;
    queue->header.page = (uint8_t)page;
    queue->header.frame_sequence = 0u;
    queue->header.count = 0u;
    queue->header.payload_bytes = 0u;
    queue->header.dl_words = 0u;
    queue->header.overflow = 0u;
    queue->header.kind = PYZ80_FT_QUEUE_FULL;
    queue->header.reserved = 0u;
    /* FREE is the publication store for a completely initialized page. */
    queue->header.state = PYZ80_FT_QUEUE_FREE;
    return 1u;
}

static uint8_t PyZ80FT_QueueAcquireKind(volatile PyZ80FtQueue *queue,
                                       uint16_t frame_sequence,
                                       uint8_t kind)
{
    if (!PyZ80FT_QueueHeaderValid(queue) ||
            queue->header.state != PYZ80_FT_QUEUE_FREE ||
            !PyZ80FT_QueueKindValid(kind)) {
        return 0u;
    }
    /* Claim first: an interrupt-side producer can no longer acquire this
     * page while the frame header and initial command are being prepared. */
    queue->header.state = PYZ80_FT_QUEUE_BUILDING;
    queue->header.frame_sequence = frame_sequence;
    queue->header.count = 0u;
    queue->header.payload_bytes = 0u;
    queue->header.dl_words = 0u;
    queue->header.overflow = 0u;
    queue->header.kind = kind;
    queue->header.reserved = 0u;
    if (kind == PYZ80_FT_QUEUE_FULL) {
        queue->words[0] = PYZ80_FT_CMD_DLSTART;
        queue->header.count = 1u;
    }
    return 1u;
}

uint8_t PyZ80FT_QueueAcquire(volatile PyZ80FtQueue *queue,
                             uint16_t frame_sequence)
    PYZ80_CALL0
{
    return PyZ80FT_QueueAcquireKind(
        queue, frame_sequence, PYZ80_FT_QUEUE_FULL);
}

uint8_t PyZ80FT_QueueAcquireFragment(volatile PyZ80FtQueue *queue,
                                     uint16_t frame_sequence)
    PYZ80_CALL0
{
    return PyZ80FT_QueueAcquireKind(
        queue, frame_sequence, PYZ80_FT_QUEUE_FRAGMENT);
}

uint8_t PyZ80FT_QueuePushCommand(volatile PyZ80FtQueue *queue, uint32_t word)
    PYZ80_CALL0
{
    return PyZ80FT_QueuePushWord(queue, word, 0u);
}

uint8_t PyZ80FT_QueuePushDL(volatile PyZ80FtQueue *queue, uint32_t word)
    PYZ80_CALL0
{
    return PyZ80FT_QueuePushWord(queue, word, 1u);
}

uint16_t PyZ80FT_FindHQTemplate(uint16_t bank_key,
                                uint16_t descriptor_address)
    PYZ80_CALL0
{
    uint16_t slot = (uint16_t)(
        bank_key ^ (bank_key >> 8) ^ descriptor_address ^
        (descriptor_address >> 8));
    uint8_t probes = (uint8_t)(
        PYZ80_FT_HQ_TEMPLATE_HASH_MAX_PROBE + 1u);
    slot &= PYZ80_FT_HQ_TEMPLATE_HASH_MASK;
    do {
        uint16_t stored = PyZ80FT_HQTemplateHash[slot];
        uint16_t candidate_index;
        const PyZ80FtHQTemplate *candidate;
        if (stored == 0u) {
            return PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
        }
        candidate_index = (uint16_t)(stored - 1u);
        if (candidate_index >= PYZ80_FT_HQ_TEMPLATE_COUNT) {
            return PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
        }
        candidate = &PyZ80FT_HQTemplates[candidate_index];
        if (candidate->bank_key == bank_key &&
                candidate->descriptor_address == descriptor_address) {
            return candidate_index;
        }
        slot = (uint16_t)((slot + 1u) &
            PYZ80_FT_HQ_TEMPLATE_HASH_MASK);
        --probes;
    } while (probes != 0u);
    return PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
}

uint16_t PyZ80FT_ResolveBankKey(uint16_t palette,
                               uint16_t resource_type)
    PYZ80_CALL0
{
    uint8_t resource = (uint8_t)resource_type;
    if ((PyZ80FT_TypedResources[resource >> 3] &
            (uint8_t)(1u << (resource & 7u))) != 0u) {
        return (uint16_t)(PYZ80_FT_BANK_TYPED | resource);
    }
    return (uint16_t)(PYZ80_FT_BANK_FALLBACK | ((uint8_t)palette & 0x0Fu));
}

uint8_t PyZ80FT_QueuePushTemplate(volatile PyZ80FtQueue *queue,
                                  uint16_t template_index,
                                  int16_t logical_x, int16_t logical_y)
    PYZ80_CALL0
{
    const PyZ80FtHQTemplate *template;
    const PyZ80FtHQTemplateCell *cell;
    uint16_t index;
    uint16_t remaining;
    uint16_t needed;
    uint16_t command_reserve;
    uint16_t dl_reserve;
    uint32_t current_layout;
    uint32_t current_palette;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    if (template_index >= PYZ80_FT_HQ_TEMPLATE_COUNT) {
        queue->header.overflow = 1u;
        return 0u;
    }
    template = &PyZ80FT_HQTemplates[template_index];
    remaining = template->cell_count;
    if (template->cell_first + remaining >
            PYZ80_FT_HQ_TEMPLATE_CELL_COUNT) {
        queue->header.overflow = 1u;
        return 0u;
    }
    cell = &PyZ80FT_HQTemplateCells[template->cell_first];
    needed = 0u;
    current_layout = 0xFFFFFFFFul;
    current_palette = PYZ80_FT_NO_PALETTE;
    while (remaining != 0u) {
        const PyZ80FtHQBitmapState *state;
        uint8_t format;
        uint16_t stride;
        uint16_t height;
        uint32_t cell_bytes;
        if (cell->state_index >= PYZ80_FT_HQ_BITMAP_STATE_COUNT) {
            queue->header.overflow = 1u;
            return 0u;
        }
        state = &PyZ80FT_HQBitmapStates[cell->state_index];
        format = (uint8_t)((state->layout >> 19) & 0x1Ful);
        stride = (uint16_t)((state->layout >> 9) & 0x03FFul);
        height = (uint16_t)(state->layout & 0x01FFul);
        cell_bytes = (uint32_t)stride * height;
        if ((state->layout & 0xFF000000ul) != PYZ80_FT_DL_BITMAP_LAYOUT ||
                (format != PYZ80_FT_BITMAP_ARGB4 &&
                 format != PYZ80_FT_BITMAP_PALETTED4444) ||
                height == 0u ||
                cell->ram_g + cell_bytes > 0x00100000ul) {
            queue->header.overflow = 1u;
            return 0u;
        }
        if (state->layout != current_layout) {
            ++needed;
            current_layout = state->layout;
        }
        if (format == PYZ80_FT_BITMAP_PALETTED4444) {
            if (state->palette_ram_g == PYZ80_FT_NO_PALETTE ||
                    (state->palette_ram_g & 1ul) != 0ul ||
                    state->palette_ram_g + 512ul > 0x00100000ul) {
                queue->header.overflow = 1u;
                return 0u;
            }
            if (state->palette_ram_g != current_palette) {
                ++needed;
                current_palette = state->palette_ram_g;
            }
        } else if (state->palette_ram_g != PYZ80_FT_NO_PALETTE) {
            queue->header.overflow = 1u;
            return 0u;
        }
        needed = (uint16_t)(needed + 2u);
        ++cell;
        --remaining;
    }
    command_reserve = queue->header.kind == PYZ80_FT_QUEUE_FULL ? 2u : 0u;
    dl_reserve = queue->header.kind == PYZ80_FT_QUEUE_FULL ? 1u : 0u;
    index = queue->header.count;
    if (index > PYZ80_FT_QUEUE_CAPACITY - needed - command_reserve ||
            queue->header.dl_words >
            PYZ80_FT_RAM_DL_WORD_LIMIT - needed - dl_reserve) {
        queue->header.overflow = 1u;
        return 0u;
    }
    cell = &PyZ80FT_HQTemplateCells[template->cell_first];
    remaining = template->cell_count;
    current_layout = 0xFFFFFFFFul;
    current_palette = PYZ80_FT_NO_PALETTE;
    while (remaining != 0u) {
        const PyZ80FtHQBitmapState *state =
            &PyZ80FT_HQBitmapStates[cell->state_index];
        uint8_t format =
            (uint8_t)((state->layout >> 19) & 0x1Ful);
        uint16_t vertex_x = PyZ80FT_LogicalVertex(
            (int16_t)(logical_x + cell->local_x));
        uint16_t vertex_y = PyZ80FT_LogicalVertex(
            (int16_t)(logical_y + cell->local_y));
        if (state->layout != current_layout) {
            queue->words[index++] = state->layout;
            current_layout = state->layout;
        }
        if (format == PYZ80_FT_BITMAP_PALETTED4444 &&
                state->palette_ram_g != current_palette) {
            queue->words[index++] = PYZ80_FT_DL_PALETTE_SOURCE |
                state->palette_ram_g;
            current_palette = state->palette_ram_g;
        }
        queue->words[index++] =
            PYZ80_FT_DL_BITMAP_SOURCE | (cell->ram_g & 0x003FFFFFul);
        queue->words[index++] = PYZ80_FT_DL_VERTEX2F |
            (((uint32_t)vertex_x & 0x7FFFul) << 15) |
            ((uint32_t)vertex_y & 0x7FFFul);
        ++cell;
        --remaining;
    }
    queue->header.count = index;
    queue->header.dl_words = (uint16_t)(queue->header.dl_words + needed);
    return 1u;
}

static uint8_t PyZ80FT_ResolveBankDescriptor(
        uint16_t bank_key,
        uint16_t descriptor_address,
        int16_t anchor_x, int16_t anchor_y,
        uint16_t *template_index_out,
        PyZ80FtLoweredCoord *lowered_x_out,
        PyZ80FtLoweredCoord *lowered_y_out)
{
    uint16_t template_index = PyZ80FT_FindHQTemplate(
        bank_key, descriptor_address);
    const PyZ80FtHQTemplate *template;
    int32_t native_x;
    int32_t native_y;
    if (template_index == PYZ80_FT_HQ_TEMPLATE_NOT_FOUND) {
        return 0u;
    }
    template = &PyZ80FT_HQTemplates[template_index];
    native_x = (int32_t)anchor_x + (int32_t)template->dx - 320l;
    native_y = 384l - (int32_t)anchor_y - (int32_t)template->dy -
        (int32_t)template->height * 16l;
    if (native_x < PYZ80_FT_NATIVE_X_MIN ||
            native_x > PYZ80_FT_NATIVE_X_MAX ||
            native_y < PYZ80_FT_NATIVE_Y_MIN ||
            native_y > PYZ80_FT_NATIVE_Y_MAX ||
            !PyZ80FT_LowerNativeX((int16_t)native_x, lowered_x_out) ||
            !PyZ80FT_LowerNativeY((int16_t)native_y, lowered_y_out)) {
        return 0u;
    }
    *template_index_out = template_index;
    return 1u;
}

static uint8_t PyZ80FT_ResolveDescriptor(
        uint16_t palette, uint16_t resource_type,
        uint16_t descriptor_address,
        int16_t anchor_x, int16_t anchor_y,
        uint16_t *template_index_out,
        PyZ80FtLoweredCoord *lowered_x_out,
        PyZ80FtLoweredCoord *lowered_y_out)
{
    return PyZ80FT_ResolveBankDescriptor(
        PyZ80FT_ResolveBankKey(palette, resource_type), descriptor_address,
        anchor_x, anchor_y, template_index_out,
        lowered_x_out, lowered_y_out);
}

uint8_t PyZ80FT_QueuePushDescriptor(volatile PyZ80FtQueue *queue,
                                    uint16_t palette,
                                    uint16_t resource_type,
                                    uint16_t descriptor_address,
                                    int16_t anchor_x, int16_t anchor_y)
    PYZ80_CALL0
{
    uint16_t template_index;
    PyZ80FtLoweredCoord lowered_x;
    PyZ80FtLoweredCoord lowered_y;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    if (!PyZ80FT_ResolveDescriptor(
            palette, resource_type, descriptor_address, anchor_x, anchor_y,
            &template_index, &lowered_x, &lowered_y)) {
        queue->header.overflow = 1u;
        return 0u;
    }
    return PyZ80FT_QueuePushTemplate(
        queue, template_index, lowered_x.logical, lowered_y.logical);
}

static uint8_t PyZ80FT_ResolveTemplateAppend(
        uint16_t template_index,
        const PyZ80FtLoweredCoord *lowered_x,
        const PyZ80FtLoweredCoord *lowered_y,
        uint32_t *address_out, uint16_t *byte_size_out)
{
    uint16_t map_index;
    uint8_t blob_index;
    uint16_t byte_size;
    uint32_t address;
    if (template_index >= PYZ80_FT_HQ_TEMPLATE_COUNT ||
            lowered_x->phase >= 5u || lowered_y->phase >= 5u) {
        return 0u;
    }
    map_index = (uint16_t)(template_index * 25u);
    map_index = (uint16_t)(map_index +
        (uint16_t)lowered_x->phase * 5u + lowered_y->phase);
    if (map_index >= PYZ80_FT_HQ_APPEND_ENTRY_COUNT) {
        return 0u;
    }
    blob_index = PyZ80FT_HQAppendMap[map_index];
    if (blob_index >= PYZ80_FT_HQ_APPEND_BLOB_COUNT) {
        return 0u;
    }
    address = PyZ80FT_HQAppendAddress[blob_index];
    byte_size = PyZ80FT_HQAppendSize[blob_index];
    if (byte_size == 0u || (byte_size & 3u) != 0u ||
            address + byte_size > 0x00100000ul) {
        return 0u;
    }
    *address_out = address;
    *byte_size_out = byte_size;
    return 1u;
}

static uint8_t PyZ80FT_QueuePushTemplateAppend(
        volatile PyZ80FtQueue *queue, uint16_t template_index,
        const PyZ80FtLoweredCoord *lowered_x,
        const PyZ80FtLoweredCoord *lowered_y)
{
    uint16_t byte_size;
    uint16_t appended_words;
    uint16_t needed_dl_words;
    uint16_t index;
    uint16_t command_reserve;
    uint16_t dl_reserve;
    uint32_t address;
    int16_t vertex_x;
    int16_t vertex_y;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    if (!PyZ80FT_ResolveTemplateAppend(
            template_index, lowered_x, lowered_y, &address, &byte_size)) {
        queue->header.overflow = 1u;
        return 0u;
    }
    appended_words = (uint16_t)(byte_size >> 2);
    needed_dl_words = (uint16_t)(appended_words + 2u);
    command_reserve = queue->header.kind == PYZ80_FT_QUEUE_FULL ? 2u : 0u;
    dl_reserve = queue->header.kind == PYZ80_FT_QUEUE_FULL ? 1u : 0u;
    index = queue->header.count;
    if (index > PYZ80_FT_QUEUE_CAPACITY - 5u - command_reserve ||
            queue->header.dl_words >
            PYZ80_FT_RAM_DL_WORD_LIMIT - needed_dl_words - dl_reserve) {
        queue->header.overflow = 1u;
        return 0u;
    }
    vertex_x = lowered_x->vertex;
    vertex_y = lowered_y->vertex;
    queue->words[index++] = PYZ80_FT_DL_VERTEX_TRANSLATE_X |
        (((uint32_t)(uint16_t)vertex_x << 1) & 0x0001FFFFul);
    queue->words[index++] = PYZ80_FT_DL_VERTEX_TRANSLATE_Y |
        (((uint32_t)(uint16_t)vertex_y << 1) & 0x0001FFFFul);
    queue->words[index++] = PYZ80_FT_CMD_APPEND;
    queue->words[index++] = address;
    queue->words[index++] = byte_size;
    queue->header.count = index;
    queue->header.dl_words = (uint16_t)(
        queue->header.dl_words + needed_dl_words);
    return 1u;
}

uint8_t PyZ80FT_QueuePushDescriptorAppend(volatile PyZ80FtQueue *queue,
                                          uint16_t palette,
                                          uint16_t resource_type,
                                          uint16_t descriptor_address,
                                          int16_t anchor_x, int16_t anchor_y)
    PYZ80_CALL0
{
    uint16_t template_index;
    PyZ80FtLoweredCoord lowered_x;
    PyZ80FtLoweredCoord lowered_y;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    if (!PyZ80FT_ResolveDescriptor(
            palette, resource_type, descriptor_address, anchor_x, anchor_y,
            &template_index, &lowered_x, &lowered_y)) {
        queue->header.overflow = 1u;
        return 0u;
    }
    return PyZ80FT_QueuePushTemplateAppend(
        queue, template_index, &lowered_x, &lowered_y);
}

#if defined(__SDCC)

/* This is the generated-table-driven Z80 hot path.  The portable C reference
 * below remains compiled by host-side differential tests; the target uses one
 * preflight resolve per record and a cache-only emission pass. */
uint8_t PyZ80FT_BuildSpriteBatchFast(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0 __naked
{
    queue; records; count; remaining_dl_words;
    __asm
        ; The fast and literal ABIs have identical sdcccall(0) argument widths.
        ; Keep a single shared implementation; -26 is the immutable record
        ; stride and selects direct template-index versus hash resolution.
        .globl _PyZ80FT_BuildSpriteBatchShared
        push iy
        push ix
        ld ix, #0
        add ix, sp
        ld hl, #-26
        add hl, sp
        ld sp, hl
        ld -26 (ix), #6
        jp _PyZ80FT_BuildSpriteBatchShared
    __endasm;
}

uint8_t PyZ80FT_BuildSpriteBatch(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0 __naked
{
    queue; records; count; remaining_dl_words;
    __asm
        ; Preserve both SDCC frame registers.  With IY then IX pushed, args are
        ; queue +6, records +8, count +10 and remaining DL budget +12.
        push iy
        push ix
        ld ix, #0
        add ix, sp
        ld hl, #-26
        add hl, sp
        ld sp, hl
        ld -26 (ix), #8

_PyZ80FT_BuildSpriteBatchShared::

        ; QueueWritable, byte for byte, without a helper call.
        ld l, 6 (ix)
        ld h, 7 (ix)
        push hl
        pop iy
        ld a, 0 (iy)
        cp a, #0x51
        jp nz, 82090$
        ld a, 1 (iy)
        cp a, #0x46
        jp nz, 82090$
        ld a, 2 (iy)
        cp a, #3
        jp nz, 82090$
        ld a, 3 (iy)
        cp a, #0xed
        jr z, 82001$
        cp a, #0xee
        jp nz, 82090$
82001$:
        ld a, 14 (iy)
        cp a, #2
        jp nc, 82090$
        ld a, 15 (iy)
        or a, a
        jp nz, 82090$
        ld a, 12 (iy)
        cp a, #1
        jp nz, 82090$
        ld a, 13 (iy)
        or a, a
        jp nz, 82090$

        ; Fresh FRAGMENT and literal queue-page ABI.
        ld a, 6 (ix)
        or a, a
        jp nz, 82081$
        ld a, 7 (ix)
        cp a, #0xc0
        jp nz, 82081$
        ld a, 14 (iy)
        cp a, #1
        jp nz, 82080$
        ld a, 6 (iy)
        or a, 7 (iy)
        or a, 8 (iy)
        or a, 9 (iy)
        or a, 10 (iy)
        or a, 11 (iy)
        jp nz, 82080$

        ; count is uint8-bounded by the public 128-record ABI.
        ld a, 11 (ix)
        or a, a
        jp nz, 82080$
        ld a, 10 (ix)
        cp a, #129
        jp nc, 82080$
        ld -1 (ix), a

        ; Full-frame remaining DL budget is in [13,2048].
        ld a, 13 (ix)
        cp a, #8
        jr c, 82002$
        jp nz, 82080$
        ld a, 12 (ix)
        or a, a
        jp nz, 82080$
82002$:
        ld l, 12 (ix)
        ld h, 13 (ix)
        ld de, #13
        or a, a
        sbc hl, de
        jp c, 82080$
        ld -7 (ix), l
        ld -6 (ix), h

        ; Source records are aligned and wholly inside [#CA44,#10000).
        ld l, 8 (ix)
        ld h, 9 (ix)
        bit 0, l
        jp nz, 82080$
        push hl
        ld de, #0xca44
        or a, a
        sbc hl, de
        pop hl
        jp c, 82080$
        ld -3 (ix), l
        ld -2 (ix), h
        ld e, 10 (ix)
        ld d, #0
        ex de, hl
        ld a, -26 (ix)
        cp a, #6
        jr z, 82005$
        add hl, hl
        add hl, hl
        add hl, hl
        jr 82006$
82005$:
        ld c, l
        ld b, h
        add hl, hl
        add hl, bc
        add hl, hl
82006$:
        ld e, -3 (ix)
        ld d, -2 (ix)
        add hl, de
        jr nc, 82003$
        ld a, h
        or a, l
        jp nz, 82080$
82003$:
        ; Output end #C044 + 20*count must not pass the source pointer.
        ld c, 10 (ix)
        ld b, #0
        ld l, c
        ld h, b
        add hl, hl
        add hl, hl
        add hl, bc
        add hl, hl
        add hl, hl
        ld de, #0xc044
        add hl, de
        ld e, -3 (ix)
        ld d, -2 (ix)
        or a, a
        sbc hl, de
        jr c, 82004$
        jp nz, 82080$
82004$:
        ld hl, #_PyZ80FT_BatchResolved
        ld -5 (ix), l
        ld -4 (ix), h

        ; Pass one: exact record resolution into private page-#F0 cache.
82010$:
        ld a, -1 (ix)
        or a, a
        jr z, 82020$
        call 82400$
        jp c, 82080$
        ; Consume 2 + byte_size/4 from the caller-owned DL budget.
        ld e, 8 (iy)
        ld d, 9 (iy)
        srl d
        rr e
        srl d
        rr e
        inc de
        inc de
        ld l, -7 (ix)
        ld h, -6 (ix)
        or a, a
        sbc hl, de
        jp c, 82080$
        ld -7 (ix), l
        ld -6 (ix), h
        ld l, -3 (ix)
        ld h, -2 (ix)
        ld e, -26 (ix)
        ld d, #0
        add hl, de
        ld -3 (ix), l
        ld -2 (ix), h
        ld l, -5 (ix)
        ld h, -4 (ix)
        ld de, #10
        add hl, de
        ld -5 (ix), l
        ld -4 (ix), h
        dec -1 (ix)
        jr 82010$

        ; Pass two: no records, hashes, coordinates or table validation.
82020$:
        ld hl, #_PyZ80FT_SpriteBatchPrefix
        ld de, #0xc010
        ld bc, #40
        ldir
        ld hl, #_PyZ80FT_BatchResolved
        push hl
        pop iy
        ld a, 10 (ix)
        ld -1 (ix), a
82021$:
        ld a, -1 (ix)
        or a, a
        jr z, 82030$
        ld l, 0 (iy)
        ld h, 1 (iy)
        ld c, #0x2b
        call 82700$
        ld l, 2 (iy)
        ld h, 3 (iy)
        ld c, #0x2c
        call 82700$
        ld a, #0x1e
        ld (de), a
        inc de
        ld a, #0xff
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld a, 4 (iy)
        ld (de), a
        inc de
        ld a, 5 (iy)
        ld (de), a
        inc de
        ld a, 6 (iy)
        ld (de), a
        inc de
        ld a, 7 (iy)
        ld (de), a
        inc de
        ld a, 8 (iy)
        ld (de), a
        inc de
        ld a, 9 (iy)
        ld (de), a
        inc de
        xor a, a
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld bc, #10
        add iy, bc
        dec -1 (ix)
        jr 82021$

82030$:
        xor a, a
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld a, #0x2b
        ld (de), a
        inc de
        xor a, a
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld a, #0x2c
        ld (de), a
        inc de
        xor a, a
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld (de), a
        inc de
        ld a, #0x21
        ld (de), a

        ; Publish count/payload/DL before the sole READY store.
        ld c, 10 (ix)
        ld b, #0
        ld l, c
        ld h, b
        add hl, hl
        add hl, hl
        add hl, bc
        ld bc, #13
        add hl, bc
        ; Reload the fixed queue address for header publication.
        push hl
        ld iy, #0xc000
        pop hl
        ld 6 (iy), l
        ld 7 (iy), h
        add hl, hl
        add hl, hl
        ld 8 (iy), l
        ld 9 (iy), h
        ld l, 12 (ix)
        ld h, 13 (ix)
        ld e, -7 (ix)
        ld d, -6 (ix)
        or a, a
        sbc hl, de
        ld 10 (iy), l
        ld 11 (iy), h
        ld 12 (iy), #2
        ld l, #1
        jr 82099$

        ; Only sticky overflow is observable on any preflight failure.
82080$:
        ld iy, #0xc000
82081$:
        ld 13 (iy), #1
82090$:
        ld l, #0
82099$:
        ld sp, ix
        pop ix
        pop iy
        ret

        ; Signed range test: HL=value, DE=[min,max], DE advances four bytes.
82100$:
        ld a, h
        xor a, #0x80
        ld b, a
        ld a, (de)
        ld c, a
        inc de
        ld a, (de)
        inc de
        xor a, #0x80
        cp a, b
        jr c, 82101$
        jr nz, 82109$
        ld a, l
        cp a, c
        jr c, 82109$
82101$:
        ld a, (de)
        ld c, a
        inc de
        ld a, (de)
        inc de
        xor a, #0x80
        cp a, b
        jr c, 82109$
        jr nz, 82108$
        ld a, c
        cp a, l
        jr c, 82109$
82108$:
        or a, a
        ret
82109$:
        scf
        ret

        ; Exact round(round(native*5/3)*64/5), plus Python-positive phase.
82200$:
        ld a, h
        and a, #0x80
        push af
        jr z, 82201$
        xor a, a
        sub a, l
        ld l, a
        ld a, #0
        sbc a, h
        ld h, a
82201$:
        ld b, h
        ld c, l
        srl h
        rr l
        ld d, b
        ld e, c
        srl d
        rr e
        srl d
        rr e
        srl d
        rr e
        add hl, de
        ld d, h
        ld e, l
        srl d
        rr e
        srl d
        rr e
        srl d
        rr e
        srl d
        rr e
        add hl, de
        ld e, h
        ld d, #0
        add hl, de
        srl h
        rr l
        ld d, h
        ld e, l
        ld h, b
        ld l, c
        or a, a
        sbc hl, de
        sbc hl, de
        sbc hl, de
        ld a, l
        cp a, #3
        jr c, 82202$
        inc de
        sub a, #3
        cp a, #3
        jr c, 82202$
        inc de
        sub a, #3
82202$:
        ex de, hl
        ld b, #6
82203$:
        add hl, hl
        djnz 82203$
        ld c, #0
        or a, a
        jr z, 82206$
        dec a
        jr nz, 82205$
        ld de, #26
        add hl, de
        ld c, #2
        jr 82206$
82205$:
        ld de, #38
        add hl, de
        ld c, #3
82206$:
        pop af
        or a, a
        jr z, 82208$
        xor a, a
        sub a, l
        ld l, a
        ld a, #0
        sbc a, h
        ld h, a
        ld a, c
        or a, a
        jr z, 82208$
        ld a, #5
        sub a, c
        ld c, a
82208$:
        ld a, c
        or a, a
        ret

        ; Exact round(round(native*15/8)*64/5), including ties-to-even r=4.
82300$:
        ld a, h
        and a, #0x80
        push af
        jr z, 82301$
        xor a, a
        sub a, l
        ld l, a
        ld a, #0
        sbc a, h
        ld h, a
82301$:
        ld a, l
        and a, #7
        ld c, a
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld a, c
        cp a, #4
        jr nz, 82302$
        bit 0, l
        jr z, 82302$
        ld a, #8
82302$:
        ld c, a
        ld c, l
        ld b, h
        push bc
        ld h, c
        ld l, #0
        ld d, b
        ld e, c
        ld b, #6
82303$:
        sla e
        rl d
        djnz 82303$
        or a, a
        sbc hl, de
        pop de
        ; The saved Q is no longer needed; rebuild the phase-table index from
        ; the native residual and Q parity before touching the base vertex.
        ld a, -23 (ix)
        bit 7, -22 (ix)
        jr z, 82304$
        neg
82304$:
        and a, #7
        cp a, #4
        jr nz, 82305$
        bit 0, e
        jr z, 82305$
        ld a, #8
82305$:
        ld e, a
        ld d, #0
        push de
        push hl
        ld hl, #82350$
        add hl, de
        ld a, (hl)
        pop hl
        ld c, a
        ld b, #0
        add hl, bc
        pop de
        push hl
        ld hl, #82360$
        add hl, de
        ld c, (hl)
        pop hl
        pop af
        or a, a
        jr z, 82308$
        xor a, a
        sub a, l
        ld l, a
        ld a, #0
        sbc a, h
        ld h, a
        ld a, c
        or a, a
        jr z, 82308$
        ld a, #5
        sub a, c
        ld c, a
82308$:
        ld a, c
        or a, a
        ret

        ; Resolve one literal record and write its private 10-byte cache entry.
82400$:
        ld l, -3 (ix)
        ld h, -2 (ix)
        push hl
        pop iy
        ld a, -26 (ix)
        cp a, #6
        jr z, 82410$
        ld e, 2 (iy)
        ld d, 3 (iy)
        push de
        ld l, 0 (iy)
        ld h, 1 (iy)
        push hl
        call _PyZ80FT_FindHQTemplate
        pop bc
        pop bc
        ld a, h
        and a, l
        inc a
        jp z, 82490$
        jr 82420$
82410$:
        ld l, 0 (iy)
        ld h, 1 (iy)
        ld a, h
        or a, a
        jp nz, 82490$
        ld a, l
        cp a, #PYZ80_FT_ASM_HQ_TEMPLATE_COUNT
        jp nc, 82490$
        ; Rebase the six-byte record so the shared geometry path continues to
        ; read anchors at offsets +4/+6, exactly like the literal ABI.
        dec iy
        dec iy
82420$:
        ld -9 (ix), l
        ld -8 (ix), h
        ld c, l
        ld b, h
        add hl, hl
        add hl, bc
        add hl, hl
        add hl, hl
        ld de, #_PyZ80FT_HQBatchGeometry
        add hl, de
        ex de, hl
        ld l, 4 (iy)
        ld h, 5 (iy)
        call 82100$
        jp c, 82490$
        ld a, (de)
        ld c, a
        inc de
        ld a, (de)
        ld b, a
        inc de
        add hl, bc
        ld -21 (ix), l
        ld -20 (ix), h
        ld l, 6 (iy)
        ld h, 7 (iy)
        call 82100$
        jp c, 82490$
        ld a, (de)
        ld c, a
        inc de
        ld a, (de)
        ld b, a
        ld a, c
        sub a, l
        ld l, a
        ld a, b
        sbc a, h
        ld h, a
        ld -23 (ix), l
        ld -22 (ix), h
        ld l, -21 (ix)
        ld h, -20 (ix)
        call 82200$
        ld -24 (ix), a
        push hl
        ld l, -5 (ix)
        ld h, -4 (ix)
        push hl
        pop iy
        pop hl
        ld 0 (iy), l
        ld 1 (iy), h
        ld l, -23 (ix)
        ld h, -22 (ix)
        call 82300$
        ld -25 (ix), a
        ld 2 (iy), l
        ld 3 (iy), h

        ld c, -9 (ix)
        ld b, -8 (ix)
        ld l, c
        ld h, b
        ld e, c
        ld d, b
        add hl, hl
        add hl, de
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, de
        push hl
        ld a, -24 (ix)
        ld e, a
        ld d, #0
        ld l, e
        ld h, d
        add hl, hl
        add hl, hl
        add hl, de
        ld e, -25 (ix)
        ld d, #0
        add hl, de
        pop de
        add hl, de
        ld de, #_PyZ80FT_HQAppendMap
        add hl, de
        ld a, (hl)
        cp a, #PYZ80_FT_ASM_HQ_APPEND_BLOB_COUNT
        jr nc, 82490$
        ld c, a
        ld l, a
        ld h, #0
        add hl, hl
        add hl, hl
        ld de, #_PyZ80FT_HQAppendAddress
        add hl, de
        ld a, (hl)
        ld 4 (iy), a
        inc hl
        ld a, (hl)
        ld 5 (iy), a
        inc hl
        ld a, (hl)
        ld 6 (iy), a
        inc hl
        ld a, (hl)
        ld 7 (iy), a
        or a, a
        jr nz, 82490$
        ld a, 6 (iy)
        cp a, #0x10
        jr nc, 82490$
        ld l, c
        ld h, #0
        add hl, hl
        ld de, #_PyZ80FT_HQAppendSize
        add hl, de
        ld c, (hl)
        inc hl
        ld b, (hl)
        ld a, b
        or a, c
        jr z, 82490$
        ld a, c
        and a, #3
        jr nz, 82490$
        ld 8 (iy), c
        ld 9 (iy), b
        ld l, 4 (iy)
        ld h, 5 (iy)
        add hl, bc
        ld a, 6 (iy)
        adc a, #0
        cp a, #0x10
        jr c, 82480$
        jr nz, 82490$
        ld a, h
        or a, l
        jr nz, 82490$
82480$:
        or a, a
        ret
82490$:
        scf
        ret

        ; Sequential little-endian VERTEX_TRANSLATE writer.
82700$:
        add hl, hl
        ld a, l
        ld (de), a
        inc de
        ld a, h
        ld (de), a
        inc de
        ld a, #0
        rla
        ld (de), a
        inc de
        ld a, c
        ld (de), a
        inc de
        ret

82350$:
        .db #0, #26, #51, #77, #102, #115, #141, #166, #90
82360$:
        .db #0, #2, #4, #1, #3, #4, #1, #3, #2
    __endasm;
}

#else

static uint8_t PyZ80FT_ResolveTemplateAnchor(
        uint16_t template_index,
        int16_t anchor_x, int16_t anchor_y,
        PyZ80FtLoweredCoord *lowered_x_out,
        PyZ80FtLoweredCoord *lowered_y_out)
{
    const PyZ80FtHQTemplate *template;
    int32_t native_x;
    int32_t native_y;
    if (template_index >= PYZ80_FT_HQ_TEMPLATE_COUNT) {
        return 0u;
    }
    template = &PyZ80FT_HQTemplates[template_index];
    native_x = (int32_t)anchor_x + (int32_t)template->dx - 320l;
    native_y = 384l - (int32_t)anchor_y - (int32_t)template->dy -
        (int32_t)template->height * 16l;
    if (native_x < PYZ80_FT_NATIVE_X_MIN ||
            native_x > PYZ80_FT_NATIVE_X_MAX ||
            native_y < PYZ80_FT_NATIVE_Y_MIN ||
            native_y > PYZ80_FT_NATIVE_Y_MAX ||
            !PyZ80FT_LowerNativeX((int16_t)native_x, lowered_x_out) ||
            !PyZ80FT_LowerNativeY((int16_t)native_y, lowered_y_out)) {
        return 0u;
    }
    return 1u;
}

static uint8_t PyZ80FT_BuildSpriteBatchReference(
        volatile PyZ80FtQueue *queue,
        const volatile void *records,
        uint16_t count, uint16_t remaining_dl_words,
        uint8_t pre_resolved)
{
    const volatile uint8_t *record;
    uint16_t records_address;
    uint16_t records_offset;
    uint16_t records_bytes;
    uint16_t physical_words;
    uint16_t payload_end;
    uint16_t needed_dl_words;
    uint16_t remaining;
    uint16_t template_index;
    uint16_t byte_size;
    uint16_t record_dl_words;
    uint16_t index;
    uint16_t prefix_index;
    PyZ80FtBatchResolved *resolved;
    uint32_t address;
    PyZ80FtLoweredCoord lowered_x;
    PyZ80FtLoweredCoord lowered_y;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    records_address = (uint16_t)records;
    records_bytes = (uint16_t)(
        count * (pre_resolved != 0u ?
            sizeof(PyZ80FtTemplateDrawRecord) : sizeof(PyZ80FtDrawRecord)));
    physical_words = (uint16_t)(
        PYZ80_FT_BATCH_PREFIX_WORDS + PYZ80_FT_BATCH_SUFFIX_WORDS +
        count * 5u);
    payload_end = (uint16_t)(
        PYZ80_FT_QUEUE_VMA + sizeof(PyZ80FtQueueHeader) +
        physical_words * sizeof(uint32_t));
    if ((uint16_t)queue != PYZ80_FT_QUEUE_VMA ||
            queue->header.kind != PYZ80_FT_QUEUE_FRAGMENT ||
            queue->header.count != 0u ||
            queue->header.payload_bytes != 0u ||
            queue->header.dl_words != 0u ||
            count > PYZ80_FT_BATCH_MAX_RECORDS ||
            remaining_dl_words > PYZ80_FT_RAM_DL_WORD_LIMIT ||
            records_address < PYZ80_FT_BATCH_RECORD_VMA ||
            (records_address & 1u) != 0u) {
        queue->header.overflow = 1u;
        return 0u;
    }
    records_offset = (uint16_t)(
        records_address - PYZ80_FT_BATCH_RECORD_VMA);
    if (records_bytes >
            PYZ80_FT_BATCH_RECORD_BYTES - records_offset ||
            payload_end > records_address) {
        queue->header.overflow = 1u;
        return 0u;
    }

    /* Pass one resolves every record and proves global DL budget before any
     * payload/header count is changed. The only failure publication is the
     * existing sticky overflow bit. */
    needed_dl_words = (uint16_t)(
        PYZ80_FT_BATCH_PREFIX_WORDS + PYZ80_FT_BATCH_SUFFIX_WORDS);
    if (needed_dl_words > remaining_dl_words) {
        queue->header.overflow = 1u;
        return 0u;
    }
    record = (const volatile uint8_t *)records;
    resolved = PyZ80FT_BatchResolved;
    remaining = count;
    while (remaining != 0u) {
        if (pre_resolved != 0u) {
            const volatile PyZ80FtTemplateDrawRecord *fast_record =
                (const volatile PyZ80FtTemplateDrawRecord *)record;
            template_index = fast_record->template_index;
            if (!PyZ80FT_ResolveTemplateAnchor(
                    template_index, fast_record->anchor_x,
                    fast_record->anchor_y, &lowered_x, &lowered_y)) {
                queue->header.overflow = 1u;
                return 0u;
            }
        } else {
            const volatile PyZ80FtDrawRecord *literal_record =
                (const volatile PyZ80FtDrawRecord *)record;
            if (!PyZ80FT_ResolveBankDescriptor(
                    literal_record->bank_key,
                    literal_record->descriptor_address,
                    literal_record->anchor_x, literal_record->anchor_y,
                    &template_index, &lowered_x, &lowered_y)) {
                queue->header.overflow = 1u;
                return 0u;
            }
        }
        if (!PyZ80FT_ResolveTemplateAppend(
                template_index, &lowered_x, &lowered_y,
                &address, &byte_size)) {
            queue->header.overflow = 1u;
            return 0u;
        }
        record_dl_words = (uint16_t)(2u + (byte_size >> 2));
        if (record_dl_words >
                (uint16_t)(remaining_dl_words - needed_dl_words)) {
            queue->header.overflow = 1u;
            return 0u;
        }
        needed_dl_words = (uint16_t)(
            needed_dl_words + record_dl_words);
        resolved->vertex_x = lowered_x.vertex;
        resolved->vertex_y = lowered_y.vertex;
        resolved->address = address;
        resolved->byte_size = byte_size;
        ++resolved;
        record += (pre_resolved != 0u ?
            sizeof(PyZ80FtTemplateDrawRecord) : sizeof(PyZ80FtDrawRecord));
        --remaining;
    }

    /* Pass two cannot fail: all generated tables, coordinate phases, RAM_G
     * ranges, queue/record non-overlap and the caller's full-frame budget were
     * proven above. Record order is the active Python Z-order. */
    index = 0u;
    prefix_index = 0u;
    while (prefix_index != PYZ80_FT_BATCH_PREFIX_WORDS) {
        queue->words[index++] = PyZ80FT_SpriteBatchPrefix[prefix_index++];
    }
    resolved = PyZ80FT_BatchResolved;
    remaining = count;
    while (remaining != 0u) {
        queue->words[index++] = PYZ80_FT_DL_VERTEX_TRANSLATE_X |
            (((uint32_t)(uint16_t)resolved->vertex_x << 1) & 0x0001FFFFul);
        queue->words[index++] = PYZ80_FT_DL_VERTEX_TRANSLATE_Y |
            (((uint32_t)(uint16_t)resolved->vertex_y << 1) & 0x0001FFFFul);
        queue->words[index++] = PYZ80_FT_CMD_APPEND;
        queue->words[index++] = resolved->address;
        queue->words[index++] = resolved->byte_size;
        ++resolved;
        --remaining;
    }
    queue->words[index++] = PYZ80_FT_DL_VERTEX_TRANSLATE_X;
    queue->words[index++] = PYZ80_FT_DL_VERTEX_TRANSLATE_Y;
    queue->words[index++] = PYZ80_FT_DL_END;
    queue->header.count = index;
    queue->header.dl_words = needed_dl_words;
    queue->header.payload_bytes = (uint16_t)(index * sizeof(uint32_t));
    /* READY is the sole publication store for the complete fragment. */
    queue->header.state = PYZ80_FT_QUEUE_READY;
    return 1u;
}

uint8_t PyZ80FT_BuildSpriteBatch(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0
{
    return PyZ80FT_BuildSpriteBatchReference(
        queue, records, count, remaining_dl_words, 0u);
}

uint8_t PyZ80FT_BuildSpriteBatchFast(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0
{
    return PyZ80FT_BuildSpriteBatchReference(
        queue, records, count, remaining_dl_words, 1u);
}

#endif

uint8_t PyZ80FT_QueueCommit(volatile PyZ80FtQueue *queue)
    PYZ80_CALL0
{
    uint16_t index;
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    if (queue->header.kind != PYZ80_FT_QUEUE_FULL) {
        queue->header.overflow = 1u;
        return 0u;
    }
    index = queue->header.count;
    if (index > PYZ80_FT_QUEUE_CAPACITY - 2u ||
            queue->header.dl_words >= PYZ80_FT_RAM_DL_WORD_LIMIT) {
        queue->header.overflow = 1u;
        return 0u;
    }
    queue->words[index++] = PYZ80_FT_DL_DISPLAY;
    queue->words[index++] = PYZ80_FT_CMD_SWAP;
    queue->header.count = index;
    queue->header.dl_words++;
    queue->header.payload_bytes =
        (uint16_t)(queue->header.count * sizeof(uint32_t));
    /* READY publishes a complete immutable header and payload to consumer. */
    queue->header.state = PYZ80_FT_QUEUE_READY;
    return 1u;
}

uint8_t PyZ80FT_QueueCommitFragment(volatile PyZ80FtQueue *queue)
    PYZ80_CALL0
{
    if (!PyZ80FT_QueueWritable(queue)) {
        return 0u;
    }
    if (queue->header.kind != PYZ80_FT_QUEUE_FRAGMENT) {
        queue->header.overflow = 1u;
        return 0u;
    }
    queue->header.payload_bytes =
        (uint16_t)(queue->header.count * sizeof(uint32_t));
    /* READY is the sole publication store: count, DL accounting, payload and
     * fragment kind are immutable before a consumer can observe this page. */
    queue->header.state = PYZ80_FT_QUEUE_READY;
    return 1u;
}
