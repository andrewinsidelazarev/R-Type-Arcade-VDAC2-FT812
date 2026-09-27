#include "pyz80_draw_ramdl_shadow_v4.h"

#include <stddef.h>
#include <stdint.h>

typedef char PyZ80DrawRamDLV4_ShadowCountIsTwo[
    PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT == 2u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_DoubleShadowFitsOneTSPage[
    PYZ80_DRAW_RAMDL_V4_DOUBLE_SHADOW_BYTES ==
        PYZ80_DRAW_RAMDL_V4_TS_PAGE_BYTES ? 1 : -1];
typedef char PyZ80DrawRamDLV4_RAMDLIs8192Bytes[
    PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS * 4u ==
        PYZ80_DRAW_RAMDL_V4_SHADOW_BYTES ? 1 : -1];
#if defined(__SDCC)
typedef char PyZ80DrawRamDLV4_FastPublishParamsIs14[
    sizeof(PyZ80DrawRamDLV4FastPublishParams) == 14 ? 1 : -1];
typedef char PyZ80DrawRamDLV4_DedupScratchIsCallerOwned1830[
    sizeof(PyZ80DrawRamDLV4DedupScratch) ==
        PYZ80_DRAW_RAMDL_V4_DEDUP_SCRATCH_TARGET_BYTES ? 1 : -1];
typedef char PyZ80DrawRamDLV4_ObjectIs10[
    sizeof(PyZ80DrawRamDLV4Object) == 10u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_FragmentIs10[
    sizeof(PyZ80DrawRamDLV4Fragment) == 10u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_ModelIs10[
    sizeof(PyZ80DrawRamDLV4Model) == 10u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_ShadowIs29[
    sizeof(PyZ80DrawRamDLV4Shadow) == 29u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_DoubleShadowIs66[
    sizeof(PyZ80DrawRamDLV4DoubleShadow) == 66u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_CertificateIs19[
    sizeof(PyZ80DrawRamDLV4Certificate) == 19u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_RasterProofIs10[
    sizeof(PyZ80DrawRamDLV4RasterProof) == 10u ? 1 : -1];
typedef char PyZ80DrawRamDLV4_LayoutIs24[
    sizeof(PyZ80DrawRamDLV4Layout) == 24u ? 1 : -1];
#endif

static uint16_t PyZ80DrawRamDLV4_NextEpoch(uint16_t epoch)
{
    ++epoch;
    return epoch == 0u ? 1u : epoch;
}

static void PyZ80DrawRamDLV4_MarkDirty(
        PyZ80DrawRamDLV4Model *model, uint8_t dirty)
{
    model->dirty = (uint8_t)(model->dirty | dirty);
    model->epoch = PyZ80DrawRamDLV4_NextEpoch(model->epoch);
}

static uint8_t PyZ80DrawRamDLV4_ModelMutable(
        const PyZ80DrawRamDLV4Model *model)
{
    return (uint8_t)(model != NULL && model->objects != NULL &&
        model->capacity <= PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS &&
        model->count <= model->capacity && model->mutation_lock == 0u);
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnSpawn(
        PyZ80DrawRamDLV4Model *model, uint16_t draw_index,
        const PyZ80DrawRamDLV4Object *object)
{
    uint16_t index;
    if (!PyZ80DrawRamDLV4_ModelMutable(model) || object == NULL ||
            draw_index > model->count || model->count >= model->capacity ||
            model->count >= PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    index = model->count;
    while (index > draw_index) {
        model->objects[index] = model->objects[index - 1u];
        --index;
    }
    model->objects[draw_index] = *object;
    ++model->count;
    PyZ80DrawRamDLV4_MarkDirty(
        model, (uint8_t)(PYZ80_DRAW_RAMDL_V4_DIRTY_LIST |
                         PYZ80_DRAW_RAMDL_V4_DIRTY_ORDER));
    return PYZ80_DRAW_RAMDL_V4_OK;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnRemove(
        PyZ80DrawRamDLV4Model *model, uint16_t draw_index)
{
    uint16_t index;
    if (!PyZ80DrawRamDLV4_ModelMutable(model) ||
            draw_index >= model->count) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    index = draw_index;
    while ((uint16_t)(index + 1u) < model->count) {
        model->objects[index] = model->objects[index + 1u];
        ++index;
    }
    --model->count;
    PyZ80DrawRamDLV4_MarkDirty(
        model, (uint8_t)(PYZ80_DRAW_RAMDL_V4_DIRTY_LIST |
                         PYZ80_DRAW_RAMDL_V4_DIRTY_ORDER));
    return PYZ80_DRAW_RAMDL_V4_OK;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnMove(
        PyZ80DrawRamDLV4Model *model, uint16_t from_index,
        uint16_t to_index)
{
    PyZ80DrawRamDLV4Object moved;
    uint16_t index;
    if (!PyZ80DrawRamDLV4_ModelMutable(model) ||
            from_index >= model->count || to_index >= model->count) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    if (from_index == to_index) {
        return PYZ80_DRAW_RAMDL_V4_OK;
    }
    moved = model->objects[from_index];
    if (from_index < to_index) {
        index = from_index;
        while (index < to_index) {
            model->objects[index] = model->objects[index + 1u];
            ++index;
        }
    } else {
        index = from_index;
        while (index > to_index) {
            model->objects[index] = model->objects[index - 1u];
            --index;
        }
    }
    model->objects[to_index] = moved;
    PyZ80DrawRamDLV4_MarkDirty(model, PYZ80_DRAW_RAMDL_V4_DIRTY_ORDER);
    return PYZ80_DRAW_RAMDL_V4_OK;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnCoordinates(
        PyZ80DrawRamDLV4Model *model, uint16_t draw_index,
        int16_t vertex_x, int16_t vertex_y)
{
    if (!PyZ80DrawRamDLV4_ModelMutable(model) ||
            draw_index >= model->count) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    model->objects[draw_index].vertex_x = vertex_x;
    model->objects[draw_index].vertex_y = vertex_y;
    PyZ80DrawRamDLV4_MarkDirty(
        model, PYZ80_DRAW_RAMDL_V4_DIRTY_COORDINATES);
    return PYZ80_DRAW_RAMDL_V4_OK;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnIdentity(
        PyZ80DrawRamDLV4Model *model, uint16_t draw_index,
        const PyZ80DrawRamDLV4Fragment *fragment,
        uint16_t object_generation)
{
    if (!PyZ80DrawRamDLV4_ModelMutable(model) ||
            draw_index >= model->count || fragment == NULL) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    model->objects[draw_index].fragment = fragment;
    model->objects[draw_index].generation = object_generation;
    PyZ80DrawRamDLV4_MarkDirty(model, PYZ80_DRAW_RAMDL_V4_DIRTY_IDENTITY);
    return PYZ80_DRAW_RAMDL_V4_OK;
}

static uint8_t PyZ80DrawRamDLV4_ControlWord(uint32_t word)
{
    uint8_t opcode = (uint8_t)(word >> 24);
    return (uint8_t)(word == PYZ80_DRAW_RAMDL_V4_DL_DISPLAY ||
        opcode == 0x1Du || opcode == 0x1Eu || opcode == 0x24u);
}

static uint8_t PyZ80DrawRamDLV4_CertificateValid(
        const PyZ80DrawRamDLV4Certificate *certificate)
{
    if (certificate == NULL ||
            certificate->format_version !=
                PYZ80_DRAW_RAMDL_V4_CERTIFICATE_VERSION ||
            certificate->immutable_fragment_proof != 1u ||
            certificate->dedup_identity_generation_proof != 1u ||
            certificate->exact_order_hook_proof != 1u ||
            certificate->direct_ram_dl_proof != 1u ||
            certificate->double_shadow_epoch_proof != 1u ||
            certificate->swap_fence_proof != 1u ||
            certificate->raster_proof != 1u ||
            certificate->ts_ram_allocation_proof != 1u ||
            certificate->max_objects != PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS ||
            certificate->max_used_words !=
                PYZ80_DRAW_RAMDL_V4_MAX_USED_WORDS ||
            certificate->safe_line_cycles !=
                PYZ80_DRAW_RAMDL_V4_SAFE_LINE_CYCLES ||
            certificate->fragment_min_words == 0u ||
            certificate->fragment_max_words <
                certificate->fragment_min_words) {
        return 0u;
    }
    return 1u;
}

static PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_CheckRaster(
        const PyZ80DrawRamDLV4Model *model,
        const PyZ80DrawRamDLV4Certificate *certificate,
        const PyZ80DrawRamDLV4RasterProof *raster,
        PyZ80DrawRamDLV4Layout *layout)
{
    uint16_t line;
    uint16_t maximum = 0u;
    uint16_t worst = 0u;
    if (raster == NULL || raster->cycles_by_line == NULL ||
            raster->line_count != 768u ||
            raster->model_epoch != model->epoch ||
            raster->worst_line >= raster->line_count) {
        return PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
    }
    for (line = 0u; line < raster->line_count; ++line) {
        uint16_t cycles = raster->cycles_by_line[line];
        if (cycles > maximum) {
            maximum = cycles;
            worst = line;
        }
    }
    if (maximum != raster->max_cycles || worst != raster->worst_line) {
        return PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
    }
    layout->worst_line_cycles = maximum;
    if (maximum > certificate->safe_line_cycles) {
        return PYZ80_DRAW_RAMDL_V4_RASTER;
    }
    return PYZ80_DRAW_RAMDL_V4_OK;
}

static uint8_t PyZ80DrawRamDLV4_FragmentWordsEqual(
        const PyZ80DrawRamDLV4Fragment *left,
        const PyZ80DrawRamDLV4Fragment *right)
{
    uint16_t index;
    if (left->word_count != right->word_count ||
            left->worst_line_cycles != right->worst_line_cycles) {
        return 0u;
    }
    for (index = 0u; index < left->word_count; ++index) {
        if (left->words[index] != right->words[index]) {
            return 0u;
        }
    }
    return 1u;
}

static uint16_t PyZ80DrawRamDLV4_ChecksumMix(
        uint16_t checksum, uint16_t value)
{
    checksum = (uint16_t)((checksum << 5) | (checksum >> 11));
    return (uint16_t)(checksum ^ value);
}

/* This is deliberately off-frame.  It both seals the caller-owned map and
 * detects a violation of the immutable-fragment contract before READY. */
static uint16_t PyZ80DrawRamDLV4_DedupChecksum(
        const PyZ80DrawRamDLV4Model *model,
        const uint32_t *prefix, uint16_t prefix_words,
        const uint32_t *suffix, uint16_t suffix_words,
        const PyZ80DrawRamDLV4DedupScratch *scratch)
{
    uint16_t checksum = 0x4D37u;
    uint16_t index;
    checksum = PyZ80DrawRamDLV4_ChecksumMix(checksum, model->count);
    checksum = PyZ80DrawRamDLV4_ChecksumMix(checksum, model->epoch);
    checksum = PyZ80DrawRamDLV4_ChecksumMix(
        checksum, scratch->unique_count);
    checksum = PyZ80DrawRamDLV4_ChecksumMix(checksum, prefix_words);
    for (index = 0u; index < prefix_words; ++index) {
        uint32_t word = prefix[index];
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, (uint16_t)word);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, (uint16_t)(word >> 16));
    }
    checksum = PyZ80DrawRamDLV4_ChecksumMix(checksum, suffix_words);
    for (index = 0u; index < suffix_words; ++index) {
        uint32_t word = suffix[index];
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, (uint16_t)word);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, (uint16_t)(word >> 16));
    }
    for (index = 0u; index < model->count; ++index) {
        const PyZ80DrawRamDLV4Object *object = &model->objects[index];
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, object->object_id);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, object->generation);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, (uint16_t)object->vertex_x);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, (uint16_t)object->vertex_y);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, scratch->object_to_unique[index]);
    }
    for (index = 0u; index < scratch->unique_count; ++index) {
        const PyZ80DrawRamDLV4Fragment *fragment =
            scratch->unique_fragments[index];
        uint16_t word_index;
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, scratch->unique_word_offsets[index]);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, scratch->unique_first_object[index]);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, fragment->identity);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, fragment->generation);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, fragment->word_count);
        checksum = PyZ80DrawRamDLV4_ChecksumMix(
            checksum, fragment->worst_line_cycles);
        for (word_index = 0u; word_index < fragment->word_count;
                ++word_index) {
            uint32_t word = fragment->words[word_index];
            checksum = PyZ80DrawRamDLV4_ChecksumMix(
                checksum, (uint16_t)word);
            checksum = PyZ80DrawRamDLV4_ChecksumMix(
                checksum, (uint16_t)(word >> 16));
        }
    }
    return checksum;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_Preflight(
        const PyZ80DrawRamDLV4Model *model,
        const uint32_t *prefix, uint16_t prefix_words,
        const uint32_t *suffix, uint16_t suffix_words,
        const PyZ80DrawRamDLV4Certificate *certificate,
        const PyZ80DrawRamDLV4RasterProof *raster,
        PyZ80DrawRamDLV4DedupScratch *scratch,
        PyZ80DrawRamDLV4Layout *layout)
{
    uint16_t index;
    uint32_t main_words;
    uint32_t subroutine_words = 0ul;
    PyZ80DrawRamDLV4Status status;
    if (layout == NULL || scratch == NULL) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    layout->object_count = 0u;
    layout->prefix_words = 0u;
    layout->coordinate_words = 0u;
    layout->call_words = 0u;
    layout->suffix_words = 0u;
    layout->main_words = 0u;
    layout->subroutine_words = 0u;
    layout->total_words = 0u;
    layout->unique_fragment_count = 0u;
    layout->worst_line_cycles = 0u;
    layout->first_failure_index = PYZ80_DRAW_RAMDL_V4_INVALID_INDEX;
    layout->model_epoch = 0u;
    scratch->unique_count = 0u;
    scratch->model_epoch = 0u;
    scratch->map_checksum = 0u;
    if (model == NULL || model->objects == NULL ||
            model->count > model->capacity ||
            (prefix_words != 0u && prefix == NULL) ||
            suffix == NULL || suffix_words == 0u ||
            suffix[suffix_words - 1u] !=
                PYZ80_DRAW_RAMDL_V4_DL_DISPLAY) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    if (!PyZ80DrawRamDLV4_CertificateValid(certificate)) {
        return PYZ80_DRAW_RAMDL_V4_CERTIFICATE;
    }
    if (model->count > certificate->max_objects) {
        return PYZ80_DRAW_RAMDL_V4_RECORD_BOUND;
    }
    for (index = 0u; index < prefix_words; ++index) {
        if (PyZ80DrawRamDLV4_ControlWord(prefix[index])) {
            layout->first_failure_index = index;
            return PYZ80_DRAW_RAMDL_V4_FRAGMENT;
        }
    }
    for (index = 0u; index + 1u < suffix_words; ++index) {
        if (PyZ80DrawRamDLV4_ControlWord(suffix[index])) {
            layout->first_failure_index = index;
            return PYZ80_DRAW_RAMDL_V4_FRAGMENT;
        }
    }
    /* Main is exact Python order: X, Y, CALL for every object.  Immutable
     * subroutines follow main DISPLAY and are stored once per key. */
    main_words = (uint32_t)prefix_words +
        (uint32_t)model->count * 3ul + suffix_words;
    if (main_words > certificate->max_used_words) {
        return PYZ80_DRAW_RAMDL_V4_CAPACITY;
    }
    for (index = 0u; index < model->count; ++index) {
        const PyZ80DrawRamDLV4Object *object = &model->objects[index];
        const PyZ80DrawRamDLV4Fragment *fragment = object->fragment;
        uint16_t fragment_index;
        uint16_t unique_index = PYZ80_DRAW_RAMDL_V4_INVALID_INDEX;
        if (fragment == NULL || fragment->words == NULL ||
                (((uintptr_t)fragment->words & 3u) != 0u) ||
                fragment->word_count < certificate->fragment_min_words ||
                fragment->word_count > certificate->fragment_max_words ||
                fragment->generation != object->generation) {
            layout->first_failure_index = index;
            return PYZ80_DRAW_RAMDL_V4_FRAGMENT;
        }
        for (fragment_index = 0u;
                fragment_index < fragment->word_count; ++fragment_index) {
            if (PyZ80DrawRamDLV4_ControlWord(
                    fragment->words[fragment_index])) {
                layout->first_failure_index = index;
                return PYZ80_DRAW_RAMDL_V4_FRAGMENT;
            }
        }
        for (fragment_index = 0u;
                fragment_index < scratch->unique_count;
                ++fragment_index) {
            const PyZ80DrawRamDLV4Fragment *known =
                scratch->unique_fragments[fragment_index];
            if (known->identity == fragment->identity &&
                    known->generation == fragment->generation) {
                if (!PyZ80DrawRamDLV4_FragmentWordsEqual(
                        known, fragment)) {
                    layout->first_failure_index = index;
                    return PYZ80_DRAW_RAMDL_V4_DEDUP_MISMATCH;
                }
                unique_index = fragment_index;
                break;
            }
        }
        if (unique_index == PYZ80_DRAW_RAMDL_V4_INVALID_INDEX) {
            unique_index = scratch->unique_count;
            if (unique_index >= PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS) {
                layout->first_failure_index = index;
                return PYZ80_DRAW_RAMDL_V4_RECORD_BOUND;
            }
            scratch->unique_fragments[unique_index] = fragment;
            scratch->unique_first_object[unique_index] = index;
            ++scratch->unique_count;
        }
        scratch->object_to_unique[index] = unique_index;
    }
    for (index = 0u; index < scratch->unique_count; ++index) {
        const PyZ80DrawRamDLV4Fragment *fragment =
            scratch->unique_fragments[index];
        uint32_t destination_words = main_words + subroutine_words;
        scratch->unique_word_offsets[index] =
            (uint16_t)destination_words;
        subroutine_words += (uint32_t)fragment->word_count + 1ul;
        if (main_words + subroutine_words >
                certificate->max_used_words) {
            layout->first_failure_index =
                scratch->unique_first_object[index];
            return PYZ80_DRAW_RAMDL_V4_CAPACITY;
        }
    }
    layout->object_count = model->count;
    layout->prefix_words = prefix_words;
    layout->coordinate_words = (uint16_t)(model->count * 2u);
    layout->call_words = model->count;
    layout->suffix_words = suffix_words;
    layout->main_words = (uint16_t)main_words;
    layout->subroutine_words = (uint16_t)subroutine_words;
    layout->total_words = (uint16_t)(main_words + subroutine_words);
    layout->unique_fragment_count = scratch->unique_count;
    layout->model_epoch = model->epoch;
    status = PyZ80DrawRamDLV4_CheckRaster(
        model, certificate, raster, layout);
    if (status == PYZ80_DRAW_RAMDL_V4_OK) {
        scratch->model_epoch = model->epoch;
        scratch->map_checksum = PyZ80DrawRamDLV4_DedupChecksum(
            model, prefix, prefix_words, suffix, suffix_words, scratch);
    }
    return status;
}

static uint8_t PyZ80DrawRamDLV4_ShadowStorageValid(
        const PyZ80DrawRamDLV4DoubleShadow *shadows)
{
    const PyZ80DrawRamDLV4Shadow *first;
    const PyZ80DrawRamDLV4Shadow *second;
    uint32_t first_begin;
    uint32_t second_begin;
    uint32_t first_end;
    uint32_t second_end;
    if (shadows == NULL) {
        return 0u;
    }
    first = &shadows->slot[0];
    second = &shadows->slot[1];
    if (first->words == NULL || second->words == NULL ||
            first->words == second->words || first->slot != 0u ||
            second->slot != 1u ||
            first->capacity_words != PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS ||
            second->capacity_words != PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS ||
            (first->physical_offset & 3u) != 0u ||
            (second->physical_offset & 3u) != 0u ||
            (uint32_t)first->physical_offset +
                PYZ80_DRAW_RAMDL_V4_SHADOW_BYTES >
                PYZ80_DRAW_RAMDL_V4_TS_PAGE_BYTES ||
            (uint32_t)second->physical_offset +
                PYZ80_DRAW_RAMDL_V4_SHADOW_BYTES >
                PYZ80_DRAW_RAMDL_V4_TS_PAGE_BYTES) {
        return 0u;
    }
    first_begin = (uint32_t)first->physical_page *
        PYZ80_DRAW_RAMDL_V4_TS_PAGE_BYTES + first->physical_offset;
    second_begin = (uint32_t)second->physical_page *
        PYZ80_DRAW_RAMDL_V4_TS_PAGE_BYTES + second->physical_offset;
    first_end = first_begin + PYZ80_DRAW_RAMDL_V4_SHADOW_BYTES;
    second_end = second_begin + PYZ80_DRAW_RAMDL_V4_SHADOW_BYTES;
    return (uint8_t)(first_end <= second_begin || second_end <= first_begin);
}

static uint16_t PyZ80DrawRamDLV4_Checksum(
        const volatile uint32_t *words, uint16_t count)
{
    uint16_t checksum = 0xA5A5u;
    uint16_t index;
    for (index = 0u; index < count; ++index) {
        uint32_t word = words[index];
        checksum = (uint16_t)((checksum << 5) | (checksum >> 11));
        checksum ^= (uint16_t)word;
        checksum ^= (uint16_t)(word >> 16);
    }
    return checksum;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_BuildInactive(
        PyZ80DrawRamDLV4Model *model,
        const uint32_t *prefix, uint16_t prefix_words,
        const uint32_t *suffix, uint16_t suffix_words,
        const PyZ80DrawRamDLV4Certificate *certificate,
        const PyZ80DrawRamDLV4RasterProof *raster,
        PyZ80DrawRamDLV4DedupScratch *scratch,
        PyZ80DrawRamDLV4DoubleShadow *shadows,
        PyZ80DrawRamDLV4Layout *layout)
{
    PyZ80DrawRamDLV4Status status;
    PyZ80DrawRamDLV4Shadow *shadow;
    uint16_t model_epoch;
    uint16_t main_index;
    uint16_t subroutine_index;
    uint16_t index;
    uint8_t slot;
    if (model == NULL) {
        return PYZ80_DRAW_RAMDL_V4_INVALID_INPUT;
    }
    if (model->mutation_lock != 0u) {
        return PYZ80_DRAW_RAMDL_V4_BUSY;
    }
    /* All authoritative mutations are required to use the hooks above.
     * Holding this off-frame lock closes the interval from preflight through
     * the sole READY store without placing any workspace on the Z80 stack. */
    model->mutation_lock = 1u;
    status = PyZ80DrawRamDLV4_Preflight(
        model, prefix, prefix_words, suffix, suffix_words,
        certificate, raster, scratch, layout);
    if (status != PYZ80_DRAW_RAMDL_V4_OK) {
        goto unlock;
    }
    if (scratch->model_epoch != model->epoch ||
            scratch->unique_count != layout->unique_fragment_count ||
            scratch->map_checksum != PyZ80DrawRamDLV4_DedupChecksum(
                model, prefix, prefix_words, suffix, suffix_words,
                scratch)) {
        status = PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
        goto unlock;
    }
    if (!PyZ80DrawRamDLV4_ShadowStorageValid(shadows)) {
        status = PYZ80_DRAW_RAMDL_V4_CERTIFICATE;
        goto unlock;
    }
    if (shadows->active_slot < PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT) {
        slot = (uint8_t)(shadows->active_slot ^ 1u);
    } else {
        slot = 0u;
    }
    shadow = &shadows->slot[slot];
    if (slot == shadows->dma_slot || shadow->state ==
            PYZ80_DRAW_RAMDL_V4_SHADOW_READY ||
            shadow->state == PYZ80_DRAW_RAMDL_V4_SHADOW_DMA ||
            shadow->state == PYZ80_DRAW_RAMDL_V4_SHADOW_SWAP_PENDING ||
            shadow->state == PYZ80_DRAW_RAMDL_V4_SHADOW_ACTIVE) {
        status = PYZ80_DRAW_RAMDL_V4_NO_INACTIVE_SHADOW;
        goto unlock;
    }
    model_epoch = model->epoch;
    shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_BUILDING;
    main_index = 0u;
    for (index = 0u; index < prefix_words; ++index) {
        shadow->words[main_index++] = prefix[index];
    }
    subroutine_index = layout->main_words;
    for (index = 0u; index < model->count; ++index) {
        const PyZ80DrawRamDLV4Object *object = &model->objects[index];
        uint16_t unique_index = scratch->object_to_unique[index];
        uint32_t destination;
        if (unique_index >= scratch->unique_count) {
            shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED;
            layout->first_failure_index = index;
            status = PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
            goto unlock;
        }
        destination =
            (uint32_t)scratch->unique_word_offsets[unique_index] * 4ul;
        if (destination > 8191ul || (destination & 3ul) != 0ul) {
            shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED;
            layout->first_failure_index = index;
            status = PYZ80_DRAW_RAMDL_V4_CAPACITY;
            goto unlock;
        }
        shadow->words[main_index++] =
            PYZ80_DRAW_RAMDL_V4_DL_VERTEX_TRANSLATE_X |
            ((((uint32_t)(uint16_t)object->vertex_x) << 1) & 0x1FFFFul);
        shadow->words[main_index++] =
            PYZ80_DRAW_RAMDL_V4_DL_VERTEX_TRANSLATE_Y |
            ((((uint32_t)(uint16_t)object->vertex_y) << 1) & 0x1FFFFul);
        shadow->words[main_index++] =
            PYZ80_DRAW_RAMDL_V4_DL_CALL | destination;
    }
    for (index = 0u; index < suffix_words; ++index) {
        shadow->words[main_index++] = suffix[index];
    }
    for (index = 0u; index < scratch->unique_count; ++index) {
        const PyZ80DrawRamDLV4Fragment *fragment =
            scratch->unique_fragments[index];
        uint16_t fragment_index;
        if (subroutine_index != scratch->unique_word_offsets[index]) {
            shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED;
            layout->first_failure_index =
                scratch->unique_first_object[index];
            status = PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
            goto unlock;
        }
        for (fragment_index = 0u;
                fragment_index < fragment->word_count; ++fragment_index) {
            shadow->words[subroutine_index++] =
                fragment->words[fragment_index];
        }
        shadow->words[subroutine_index++] =
            PYZ80_DRAW_RAMDL_V4_DL_RETURN;
    }
    if (model->epoch != model_epoch || model_epoch != layout->model_epoch ||
            scratch->model_epoch != model_epoch ||
            scratch->map_checksum != PyZ80DrawRamDLV4_DedupChecksum(
                model, prefix, prefix_words, suffix, suffix_words,
                scratch) ||
            main_index != layout->main_words ||
            subroutine_index != layout->total_words) {
        shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED;
        status = PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
        goto unlock;
    }
    /* The target uses one fixed 8 KiB DMA.  Zero is FT812 DISPLAY, so the
     * unused tail is deterministic and harmless even though main DISPLAY is
     * reached first. */
    for (index = layout->total_words;
            index < PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS; ++index) {
        shadow->words[index] = PYZ80_DRAW_RAMDL_V4_DL_DISPLAY;
    }
    shadows->next_publish_epoch =
        PyZ80DrawRamDLV4_NextEpoch(shadows->next_publish_epoch);
    shadow->used_words = layout->total_words;
    shadow->main_words = layout->main_words;
    shadow->subroutine_words = layout->subroutine_words;
    shadow->object_count = layout->object_count;
    shadow->unique_fragment_count = layout->unique_fragment_count;
    shadow->model_epoch = model_epoch;
    shadow->publish_epoch = shadows->next_publish_epoch;
    shadow->worst_line_cycles = layout->worst_line_cycles;
    shadow->checksum = PyZ80DrawRamDLV4_Checksum(
        shadow->words, shadow->used_words);
    shadow->dedup_checksum = scratch->map_checksum;
    /* With certified hook-only mutations the lock makes this the exact same
     * epoch/map sealed by preflight.  Keep a final defensive check adjacent
     * to READY for host/direct-write fault injection as well. */
    if (model->epoch != model_epoch ||
            scratch->map_checksum != PyZ80DrawRamDLV4_DedupChecksum(
                model, prefix, prefix_words, suffix, suffix_words,
                scratch)) {
        shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED;
        status = PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
        goto unlock;
    }
    /* Sole off-frame publication store. */
    shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_READY;
    status = PYZ80_DRAW_RAMDL_V4_OK;
unlock:
    model->mutation_lock = 0u;
    return status;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_AcquireReady(
        PyZ80DrawRamDLV4DoubleShadow *shadows, uint8_t *slot_out)
{
    uint8_t slot;
    if (shadows == NULL || slot_out == NULL ||
            shadows->dma_slot < PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT) {
        return PYZ80_DRAW_RAMDL_V4_BUSY;
    }
    for (slot = 0u; slot < PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT; ++slot) {
        PyZ80DrawRamDLV4Shadow *shadow = &shadows->slot[slot];
        if (shadow->state == PYZ80_DRAW_RAMDL_V4_SHADOW_READY &&
                shadow->publish_epoch != 0u &&
                shadow->publish_epoch != shadows->retired_epoch) {
            shadows->dma_slot = slot;
            shadows->dma_epoch = shadow->publish_epoch;
            shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_DMA;
            *slot_out = slot;
            return PYZ80_DRAW_RAMDL_V4_OK;
        }
    }
    return PYZ80_DRAW_RAMDL_V4_NO_INACTIVE_SHADOW;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_MarkDMADone(
        PyZ80DrawRamDLV4DoubleShadow *shadows, uint8_t slot)
{
    PyZ80DrawRamDLV4Shadow *shadow;
    if (shadows == NULL || slot >= PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT ||
            shadows->dma_slot != slot) {
        return PYZ80_DRAW_RAMDL_V4_BUSY;
    }
    shadow = &shadows->slot[slot];
    if (shadow->state != PYZ80_DRAW_RAMDL_V4_SHADOW_DMA ||
            shadow->publish_epoch != shadows->dma_epoch) {
        return PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
    }
    shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_SWAP_PENDING;
    return PYZ80_DRAW_RAMDL_V4_OK;
}

PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_RetireSwap(
        PyZ80DrawRamDLV4DoubleShadow *shadows, uint8_t slot,
        uint8_t int_swap_seen, uint8_t reg_dlswap_zero)
{
    PyZ80DrawRamDLV4Shadow *shadow;
    if (shadows == NULL || slot >= PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT ||
            shadows->dma_slot != slot) {
        return PYZ80_DRAW_RAMDL_V4_BUSY;
    }
    shadow = &shadows->slot[slot];
    if (shadow->state != PYZ80_DRAW_RAMDL_V4_SHADOW_SWAP_PENDING ||
            shadow->publish_epoch != shadows->dma_epoch) {
        return PYZ80_DRAW_RAMDL_V4_STALE_EPOCH;
    }
    if (int_swap_seen == 0u || reg_dlswap_zero == 0u) {
        return PYZ80_DRAW_RAMDL_V4_FENCE;
    }
    if (shadows->active_slot < PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT &&
            shadows->active_slot != slot) {
        shadows->slot[shadows->active_slot].state =
            PYZ80_DRAW_RAMDL_V4_SHADOW_RETIRED;
    }
    shadows->active_slot = slot;
    shadows->retired_epoch = shadow->publish_epoch;
    shadows->dma_epoch = 0u;
    shadows->dma_slot = 0xFFu;
    shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_ACTIVE;
    return PYZ80_DRAW_RAMDL_V4_OK;
}
