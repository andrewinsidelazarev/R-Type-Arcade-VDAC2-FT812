/* Универсальная граница Python/C -> аппаратный renderer FT812.
 *
 * Игровой C-код не рисует пиксели и не пишет SPI по одному байту. Он сохраняет
 * порядок Python render() в компактной очереди slot3. Резидентный backend затем
 * превращает записи в пакетный display list и отправляет его в FT812 через DMA.
 */
#ifndef PYZ80_FT812_H
#define PYZ80_FT812_H

#include <stdint.h>

#if defined(__SDCC)
#define PYZ80_CALL0 __sdcccall(0)
#else
#define PYZ80_CALL0
#endif

#define PYZ80_FT_QUEUE_FORMAT       3u
#define PYZ80_FT_QUEUE_BYTES        0x4000u
#define PYZ80_FT_QUEUE_VMA          0xC000u
#define PYZ80_FT_QUEUE_PAGE_A       0xEDu
#define PYZ80_FT_QUEUE_PAGE_B       0xEEu
#define PYZ80_FT_TEMPLATE_PAGE      0xEFu
#define PYZ80_FT_BATCH_RECORD_VMA   0xCA44u
#define PYZ80_FT_BATCH_RECORD_BYTES 0x35BCu
#define PYZ80_FT_BATCH_MAX_RECORDS  128u

#define PYZ80_FT_RAM_DL_WORD_LIMIT  2048u
#define PYZ80_FT_CMD_DLSTART        0xFFFFFF00ul
#define PYZ80_FT_CMD_SWAP           0xFFFFFF01ul
#define PYZ80_FT_HQ_TEMPLATE_NOT_FOUND 0xFFFFu

/* Exact M72SpriteAtlas.draw lowering domain. These are the largest symmetric
 * native-coordinate ranges whose phase-exact FT812 VERTEX_TRANSLATE value
 * still fits its signed 17-bit field after the required x2 conversion. */
#define PYZ80_FT_NATIVE_X_MIN (-1535)
#define PYZ80_FT_NATIVE_X_MAX 1535
#define PYZ80_FT_NATIVE_Y_MIN (-1365)
#define PYZ80_FT_NATIVE_Y_MAX 1365
/* Exhaustive compiled-C proof domain used by the translated renderer. The
 * implementation itself remains exact for the entire int16 input domain. */
#define PYZ80_FT_LOGICAL_VERTEX_MIN (-512)
#define PYZ80_FT_LOGICAL_VERTEX_MAX 767

typedef enum PyZ80FtQueueState {
    PYZ80_FT_QUEUE_FREE = 0,
    PYZ80_FT_QUEUE_BUILDING = 1,
    PYZ80_FT_QUEUE_READY = 2,
    PYZ80_FT_QUEUE_CONSUMING = 3
} PyZ80FtQueueState;

/* FULL stays zero so every existing full-frame header remains byte-exact:
 * this byte occupied the low half of the previously zero reserved word. */
typedef enum PyZ80FtQueueKind {
    PYZ80_FT_QUEUE_FULL = 0,
    PYZ80_FT_QUEUE_FRAGMENT = 1
} PyZ80FtQueueKind;

typedef struct PyZ80FtQueueHeader {
    uint16_t magic;
    uint8_t format;
    uint8_t page;
    uint16_t frame_sequence;
    uint16_t count;
    uint16_t payload_bytes;
    uint16_t dl_words;
    uint8_t state;
    uint8_t overflow;
    uint8_t kind;
    uint8_t reserved;
} PyZ80FtQueueHeader;

#define PYZ80_FT_QUEUE_CAPACITY \
    ((PYZ80_FT_QUEUE_BYTES - sizeof(PyZ80FtQueueHeader)) / \
     sizeof(uint32_t))

typedef struct PyZ80FtQueue {
    PyZ80FtQueueHeader header;
    /* Готовый последовательный FT812 command/DL stream. Python Z-order — это
     * порядок слов; backend не сортирует и не переставляет draw-операции. */
    uint32_t words[PYZ80_FT_QUEUE_CAPACITY];
} PyZ80FtQueue;

typedef struct PyZ80FtLoweredCoord {
    int16_t logical;
    int16_t vertex;
    uint8_t phase;
} PyZ80FtLoweredCoord;

/* Literal active-Python sprite identity plus native M72 draw anchor. Records
 * live only in the reserved tail of the same mapped ED/EE queue page. */
typedef struct PyZ80FtDrawRecord {
    uint16_t bank_key;
    uint16_t descriptor_address;
    int16_t anchor_x;
    int16_t anchor_y;
} PyZ80FtDrawRecord;

/* Pre-resolved working-set ABI. The immutable template index is generated
 * from the same HQT3 table as the target code; only the per-frame native
 * anchor remains dynamic. The literal 8-byte ABI above stays available as an
 * independent bank+descriptor oracle. */
typedef struct PyZ80FtTemplateDrawRecord {
    uint16_t template_index;
    int16_t anchor_x;
    int16_t anchor_y;
} PyZ80FtTemplateDrawRecord;

_Static_assert(sizeof(PyZ80FtQueueHeader) == 16, "FT812 queue header ABI changed");
_Static_assert(sizeof(PyZ80FtQueue) == PYZ80_FT_QUEUE_BYTES,
               "FT812 queue must occupy one TS page");
_Static_assert(sizeof(PyZ80FtLoweredCoord) == 5,
               "FT812 lowered coordinate ABI changed");
_Static_assert(sizeof(PyZ80FtDrawRecord) == 8,
               "FT812 draw-record ABI changed");
_Static_assert(sizeof(PyZ80FtTemplateDrawRecord) == 6,
               "FT812 template draw-record ABI changed");

/* QueueInitialize is a one-time page setup operation. A frame producer must
 * use QueueAcquire afterwards; it may never reset a READY/CONSUMING page. */
uint8_t PyZ80FT_QueueInitialize(volatile PyZ80FtQueue *queue, uint16_t page)
    PYZ80_CALL0;
uint8_t PyZ80FT_QueueAcquire(volatile PyZ80FtQueue *queue,
                            uint16_t frame_sequence)
    PYZ80_CALL0;
/* Fragment mode is embedded into an already open FT_CMD_Start/FT_DL_Start.
 * It starts empty and CommitFragment publishes only its existing payload:
 * no CMD_DLSTART, DISPLAY, or CMD_SWAP is inserted. */
uint8_t PyZ80FT_QueueAcquireFragment(volatile PyZ80FtQueue *queue,
                                    uint16_t frame_sequence)
    PYZ80_CALL0;
uint8_t PyZ80FT_QueuePushCommand(volatile PyZ80FtQueue *queue, uint32_t word)
    PYZ80_CALL0;
uint8_t PyZ80FT_QueuePushDL(volatile PyZ80FtQueue *queue, uint32_t word)
    PYZ80_CALL0;
/* HQT3 is sorted by the exact M72SpriteAtlas._asset bank identity and ROM
 * descriptor: typed=(1,resource), fallback=(0,palette&15). */
uint16_t PyZ80FT_ResolveBankKey(uint16_t palette, uint16_t resource_type)
    PYZ80_CALL0;
/* Exact Python-logical -> VERTEX_FORMAT(3) conversion over all int16 values.
 * The uint16 result is the low 16 bits of the signed rounded coordinate. */
uint16_t PyZ80FT_LogicalVertex(int16_t value)
    PYZ80_CALL0;
/* Exact specialized forms of Python round(native*5/3) and
 * round(native*15/8). They also return the phase used by the immutable
 * CMD_APPEND pack and the signed pre-x2 VERTEX_TRANSLATE coordinate. Calls
 * outside the declared domain fail without touching result. */
uint8_t PyZ80FT_LowerNativeX(int16_t native,
                             PyZ80FtLoweredCoord *result)
    PYZ80_CALL0;
uint8_t PyZ80FT_LowerNativeY(int16_t native,
                             PyZ80FtLoweredCoord *result)
    PYZ80_CALL0;
uint16_t PyZ80FT_FindHQTemplate(uint16_t bank_key,
                                uint16_t descriptor_address)
    PYZ80_CALL0;
/* logical_x/logical_y are the already evaluated Python blit coordinates
 * (M72SpriteAtlas.draw base_x/base_y), not native M72 anchor coordinates. */
uint8_t PyZ80FT_QueuePushTemplate(volatile PyZ80FtQueue *queue,
                                  uint16_t template_index,
                                  int16_t logical_x, int16_t logical_y)
    PYZ80_CALL0;
/* Native anchors have exactly the meaning of M72SpriteAtlas.draw(anchor_x,
 * anchor_y). Descriptor geometry and Python round-to-even are applied here;
 * a derived native coordinate outside the declared exact domain fails closed. */
uint8_t PyZ80FT_QueuePushDescriptor(volatile PyZ80FtQueue *queue,
                                    uint16_t palette,
                                    uint16_t resource_type,
                                    uint16_t descriptor_address,
                                    int16_t anchor_x, int16_t anchor_y)
    PYZ80_CALL0;
/* Isolated hardware-offload path. It emits only VERTEX_TRANSLATE_X/Y and one
 * CMD_APPEND; the immutable phase-exact DL body is already resident in RAM_G.
 * The direct descriptor path above remains available for A/B verification. */
/* The linker-visible spelling stays below ASxxxx's 32-character limit. */
uint8_t PyZ80FT_QueuePushDescAppend(volatile PyZ80FtQueue *queue,
                                    uint16_t palette,
                                    uint16_t resource_type,
                                    uint16_t descriptor_address,
                                    int16_t anchor_x, int16_t anchor_y)
    PYZ80_CALL0;
#define PyZ80FT_QueuePushDescriptorAppend PyZ80FT_QueuePushDescAppend
/* Build and publish one self-contained ordered sprite fragment atomically.
 * remaining_dl_words is the caller's full-frame budget, not a fresh 2048-word
 * local allowance. Records must be wholly inside [#CA44,#10000) of this same
 * slot3 page; output is preflighted not to overlap them. */
uint8_t PyZ80FT_BuildSpriteBatch(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0;
/* Same atomic fragment publication, but without a per-frame bank/descriptor
 * hash. Invalid/stale template indices and every coordinate/budget/range
 * failure are rejected before any public word/header field is published. */
uint8_t PyZ80FT_BuildSpriteBatchFast(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0;
uint8_t PyZ80FT_QueueCommit(volatile PyZ80FtQueue *queue)
    PYZ80_CALL0;
uint8_t PyZ80FT_QueueCommitFragment(volatile PyZ80FtQueue *queue)
    PYZ80_CALL0;

#endif
