/* Платформа TS-Config: доступ к страничным данным и буферы bytes.
 *
 * Страничный контейнер хранит в data адрес внутри окна #C000 и номер первой
 * логической страницы в page (физическую даёт таблица p2c_page_map); смещение элемента может переходить на следующие страницы.
 * На время чтения или записи в окно #C000 ставится страница данных, затем
 * возвращается банк кода p2c_bank, из которого вызвана функция доступа.
 * Буферы от P2C_Z80_PAGED_MIN байт, созданные во время работы, получают
 * страницы из пула сборки; сборщик мусора возвращает их при освобождении.
 *
 * Адрес байта страничных данных: смещение от начала данных = (data − #C000) + индекс; логическая страница =
 * page + (смещение >> 14), адрес в окне = #C000 + (смещение & #3FFF).
 *
 * Горячая часть (доступ к элементам) резидентна, холодная (операции буферов)
 * собирается в банк кода вместе с холодной частью рантайма. */
#include <string.h>
#include "p2c_runtime.h"
#include "p2c_z80_config.h"

/* Порт страницы окна #C000 (TS-Config Page3, #13AF). */
__sfr __banked __at(0x13AF) p2c_port_page3;

/* Буфер bytes от этого размера — на страницах пула, меньше — в куче. */
#define P2C_Z80_PAGED_MIN 1024u
/* Логическая страница данных -> физическая (одинаковые неизменяемые страницы общие). */
#define P2C_MAP(page) (p2c_port_page3 = p2c_page_map[(uint8_t)(page)])
/* Вернуть в окно #C000 банк кода, из которого вызвана функция доступа. */
#define P2C_RESTORE() (p2c_port_page3 = p2c_bank)
/* Смещение начала данных от начала окна (адрес data − #C000) — 32 бита для сложения с индексом. */
#define P2C_BASE(data) ((uint32_t)(uint16_t)((const uint8_t *)(data) - (const uint8_t *)P2C_Z80_WINDOW))

/* Пул страниц крупных буферов: 1 — страница занята (P2C_Z80_POOL_FIRST + номер). */
extern uint8_t p2c_pool_used[P2C_Z80_POOL_COUNT];
void p2c_z80_page_read(uint8_t page, uint32_t offset, uint8_t *target, uint16_t count);
void p2c_z80_page_write(uint8_t page, uint32_t offset, const uint8_t *source, uint16_t count);

#ifndef P2C_SPLIT_COLD

uint8_t p2c_pool_used[P2C_Z80_POOL_COUNT];

/* --- чтение и запись страничных байтов ----------------------------------------- */

/* count байт логических данных с offset (от начала страницы page) в target: кусками до конца страницы, каждая
 * следующая страница — с начала (within = 0). */
void p2c_z80_page_read(uint8_t page, uint32_t offset, uint8_t *target, uint16_t count) {
    uint16_t within = (uint16_t)offset & 0x3FFFu;
    uint16_t chunk;
    page = (uint8_t)(page + (uint8_t)(offset >> 14));
    while (count) {
        chunk = 0x4000u - within;
        if (chunk > count) chunk = count;
        P2C_MAP(page);
        memcpy(target, (const uint8_t *)(P2C_Z80_WINDOW + within), chunk);
        target += chunk;
        count -= chunk;
        page++;
        within = 0;
    }
    P2C_RESTORE();
}

/* Запись count байт из source в логические данные — так же кусками по страницам. */
void p2c_z80_page_write(uint8_t page, uint32_t offset, const uint8_t *source, uint16_t count) {
    uint16_t within = (uint16_t)offset & 0x3FFFu;
    uint16_t chunk;
    page = (uint8_t)(page + (uint8_t)(offset >> 14));
    while (count) {
        chunk = 0x4000u - within;
        if (chunk > count) chunk = count;
        P2C_MAP(page);
        memcpy((uint8_t *)(P2C_Z80_WINDOW + within), source, chunk);
        source += chunk;
        count -= chunk;
        page++;
        within = 0;
    }
    P2C_RESTORE();
}

/* Физическая страница (каталоги адаптеров): банковый код сам окно #C000 не переключает. */
void p2c_z80_physical_read(uint8_t page, uint16_t within, uint8_t *target, uint16_t count) {
    p2c_port_page3 = page;
    memcpy(target, (const uint8_t *)(P2C_Z80_WINDOW + within), count);
    P2C_RESTORE();
}

void p2c_z80_physical_write(uint8_t page, uint16_t within, const uint8_t *source, uint16_t count) {
    p2c_port_page3 = page;
    memcpy((uint8_t *)(P2C_Z80_WINDOW + within), source, count);
    P2C_RESTORE();
}

/* --- элементы списков и кортежей ----------------------------------------------- */

/* Элемент страничного списка читает p2c_z80_at_paged из p2c_z80_access.s (ассемблер). */

/* Запись элемента index (size байт) страничного списка: смещение (data − #C000) + index·size. */
void p2c_z80_put_paged(const void *pointer, uint16_t index, const void *value, uint8_t size) {
    const P2cList *list = (const P2cList *)pointer;
    p2c_z80_page_write(list->page, P2C_BASE(list->data) + (uint32_t)(uint16_t)(index * (uint16_t)size),
                       (const uint8_t *)value, size);
}

/* Байт index страничного буфера: одна страница — без цикла кусков. */
uint8_t p2c_z80_byte_paged(const void *pointer, int32_t index) {
    const P2cBuf *buffer = (const P2cBuf *)pointer;
    uint32_t offset = P2C_BASE(buffer->data) + (uint32_t)index;
    uint8_t value;
    P2C_MAP(buffer->page + (uint8_t)(offset >> 14));
    value = *(const uint8_t *)(P2C_Z80_WINDOW + ((uint16_t)offset & 0x3FFFu));
    P2C_RESTORE();
    return value;
}

void p2c_z80_byte_put_paged(const void *pointer, int32_t index, uint8_t value) {
    const P2cBuf *buffer = (const P2cBuf *)pointer;
    uint32_t offset = P2C_BASE(buffer->data) + (uint32_t)index;
    P2C_MAP(buffer->page + (uint8_t)(offset >> 14));
    *(uint8_t *)(P2C_Z80_WINDOW + ((uint16_t)offset & 0x3FFFu)) = value;
    P2C_RESTORE();
}

/* Копия count байт данных контейнера с offset: резидентные (page = 0) — memcpy, страничные — по страницам. */
void p2c_z80_copy_out(const uint8_t *data, uint8_t page, uint32_t offset, uint8_t *target, uint16_t count) {
    if (!page) {
        memcpy(target, data + (uint16_t)offset, count);
        return;
    }
    p2c_z80_page_read(page, P2C_BASE(data) + offset, target, count);
}

/* --- байты bytes/bytearray ----------------------------------------------------- */

/* Байт index буфера в куче или на страницах. */
uint8_t p2c_z80_byte(const void *pointer, int32_t index) {
    const P2cBuf *buffer = (const P2cBuf *)pointer;
    uint8_t value;
    if (!buffer->page) return buffer->data[(uint16_t)index];
    p2c_z80_page_read(buffer->page, P2C_BASE(buffer->data) + (uint32_t)index, &value, 1);
    return value;
}

void p2c_z80_byte_put(void *pointer, int32_t index, uint8_t value) {
    P2cBuf *buffer = (P2cBuf *)pointer;
    if (!buffer->page) {
        buffer->data[(uint16_t)index] = value;
        return;
    }
    p2c_z80_page_write(buffer->page, P2C_BASE(buffer->data) + (uint32_t)index, &value, 1);
}

/* Слово little-endian по смещению (struct '<H'): байт offset — младший, offset + 1 — старший; два байта
 * страничного буфера могут лежать на разных страницах — поэтому чтение через p2c_z80_page_read. */
uint16_t p2c_z80_buf_u16(const void *pointer, int32_t offset) {
    const P2cBuf *buffer = (const P2cBuf *)pointer;
    uint8_t pair[2];
    if (!buffer->page) {
        const uint8_t *bytes = buffer->data + (uint16_t)offset;
        return (uint16_t)(bytes[0] | ((uint16_t)bytes[1] << 8));
    }
    p2c_z80_page_read(buffer->page, P2C_BASE(buffer->data) + (uint32_t)offset, pair, 2);
    return (uint16_t)(pair[0] | ((uint16_t)pair[1] << 8));
}

void p2c_z80_buf_set_u16(void *pointer, int32_t offset, uint16_t value) {
    P2cBuf *buffer = (P2cBuf *)pointer;
    uint8_t pair[2];
    pair[0] = (uint8_t)value;
    pair[1] = (uint8_t)(value >> 8);
    if (!buffer->page) {
        memcpy(buffer->data + (uint16_t)offset, pair, 2);
        return;
    }
    p2c_z80_page_write(buffer->page, P2C_BASE(buffer->data) + (uint32_t)offset, pair, 2);
}

/* Освобождение страниц мёртвого буфера при сборке: только буфер на страницах пула (номер в диапазоне пула);
 * страниц — capacity, округлённая вверх до 16 КБ. Буфер после этого пуст (page = 0, data = NULL). */
void p2c_z80_buf_release(void *pointer) {
    P2cBuf *buffer = (P2cBuf *)pointer;
    uint16_t first;
    uint16_t pages;
    uint16_t index;
    if (buffer->page < P2C_Z80_POOL_FIRST || buffer->page >= P2C_Z80_POOL_FIRST + P2C_Z80_POOL_COUNT) return;
    first = (uint16_t)(buffer->page - P2C_Z80_POOL_FIRST);
    pages = (uint16_t)((buffer->capacity + 0x3FFFUL) >> 14);
    for (index = 0; index < pages; index++) p2c_pool_used[first + index] = 0;
    buffer->page = 0;
    buffer->data = NULL;
}

#endif /* !P2C_SPLIT_COLD */

#ifndef P2C_SPLIT_HOT

/* --- пул страниц крупных буферов ------------------------------------------------ */

/* Страниц на size байт: (size + #3FFF) >> 14. */
static uint16_t p2c_pages_for(uint32_t size) {
    return (uint16_t)((size + 0x3FFFUL) >> 14);
}

/* Первые pages свободных страниц пула подряд: занять и вернуть номер первой; нет — MemoryError. */
static uint8_t p2c_pool_take(uint16_t pages) {
    uint16_t first;
    uint16_t index;
    for (first = 0; first + pages <= P2C_Z80_POOL_COUNT; first++) {
        for (index = 0; index < pages && !p2c_pool_used[first + index]; index++) {
        }
        if (index == pages) {
            for (index = 0; index < pages; index++) p2c_pool_used[first + index] = 1;
            return (uint8_t)(P2C_Z80_POOL_FIRST + first);
        }
    }
    p2c_raise(P2C_E_MEMORY);
    return 0;
}

/* Память данных буфера без обнуления: куча или страницы пула. */
static void p2c_storage(P2cBuf *buffer, uint32_t capacity) {
    if (capacity >= P2C_Z80_PAGED_MIN) {
        buffer->page = p2c_pool_take(p2c_pages_for(capacity));
        buffer->data = (uint8_t *)P2C_Z80_WINDOW;
    } else {
        buffer->page = 0;
        buffer->data = (uint8_t *)p2c_alloc_block((size_t)capacity);
    }
    buffer->capacity = capacity;
}

/* Обнулить count байт буфера с offset: кусками по 256 байт через нулевой буфер на стеке (для страниц). */
static void p2c_fill_zero(P2cBuf *buffer, uint32_t offset, uint32_t count) {
    uint8_t p2c_bounce_a[256];
    uint16_t chunk;
    memset(p2c_bounce_a, 0, sizeof p2c_bounce_a);
    while (count) {
        chunk = count > 256u ? 256u : (uint16_t)count;
        if (!buffer->page) memset(buffer->data + (uint16_t)offset, 0, chunk);
        else p2c_z80_page_write(buffer->page, P2C_BASE(buffer->data) + offset, p2c_bounce_a, chunk);
        offset += chunk;
        count -= chunk;
    }
}

/* Перенос байтов между буферами (любое сочетание кучи и страниц). Оба в куче — memmove сразу; иначе кусками по
 * 256 байт: из кучи на страницы, со страниц в кучу, со страниц на страницы — через буфер на стеке (окно #C000 одно). */
static void p2c_transfer(P2cBuf *target, uint32_t target_offset, const P2cBuf *source,
                         uint32_t source_offset, uint32_t count) {
    uint8_t p2c_bounce_a[256];
    uint16_t chunk;
    if (!target->page && !source->page) {
        memmove(target->data + (uint16_t)target_offset, source->data + (uint16_t)source_offset, (uint16_t)count);
        return;
    }
    while (count) {
        chunk = count > 256u ? 256u : (uint16_t)count;
        if (!source->page) {
            p2c_z80_page_write(target->page, P2C_BASE(target->data) + target_offset,
                               source->data + (uint16_t)source_offset, chunk);
        } else if (!target->page) {
            p2c_z80_page_read(source->page, P2C_BASE(source->data) + source_offset,
                              target->data + (uint16_t)target_offset, chunk);
        } else {
            p2c_z80_page_read(source->page, P2C_BASE(source->data) + source_offset, p2c_bounce_a, chunk);
            p2c_z80_page_write(target->page, P2C_BASE(target->data) + target_offset, p2c_bounce_a, chunk);
        }
        target_offset += chunk;
        source_offset += chunk;
        count -= chunk;
    }
}

/* Объект буфера длиной size с памятью под size байт (содержимое не обнулено). */
static P2cBuf *p2c_buf_alloc(uint32_t size) {
    P2cBuf *buffer = (P2cBuf *)p2c_new_object(P2C_CLS_BUF, sizeof(P2cBuf));
    p2c_storage(buffer, size);
    buffer->length = size;
    return buffer;
}

/* Память из кучи уже обнулена выделением — обнулять нужно только страницы пула. */
P2cBuf *p2c_buf_new(size_t size, uint8_t mutable_flag) P2C_COLD {
    P2cBuf *buffer = p2c_buf_alloc(size);
    (void)mutable_flag;
    if (buffer->page) p2c_fill_zero(buffer, 0, size);
    return buffer;
}

P2cBuf *p2c_buf_copy(const P2cBuf *source, uint8_t mutable_flag) P2C_COLD {
    P2cBuf *buffer = p2c_buf_alloc(source->length);
    (void)mutable_flag;
    p2c_transfer(buffer, 0, source, 0, source->length);
    return buffer;
}

/* source[low:high]: границы — как у среза Python (p2c_slice_bounds рантайма), затем перенос. */
P2cBuf *p2c_buf_slice(const P2cBuf *source, int32_t low, int32_t high, uint8_t mutable_flag) P2C_COLD {
    P2cBuf *buffer;
    int32_t length = (int32_t)source->length;
    (void)mutable_flag;
    if (low < 0) { low += length; if (low < 0) low = 0; }
    if (high < 0) { high += length; if (high < 0) high = 0; }
    if (low > length) low = length;
    if (high > length) high = length;
    if (high < low) high = low;
    buffer = p2c_buf_alloc((uint32_t)(high - low));
    p2c_transfer(buffer, 0, source, (uint32_t)low, (uint32_t)(high - low));
    return buffer;
}

/* bytearray.append: буфер полон — новая память вдвое больше (пустой — 8 байт), перенос старых байтов, страницы
 * старой памяти возвращаются в пул. */
void p2c_buf_append(P2cBuf *buffer, int32_t value) P2C_COLD {
    uint8_t byte = p2c_byte_value(value);
    if (buffer->length == buffer->capacity) {
        P2cBuf old = *buffer;
        p2c_storage(buffer, buffer->capacity ? buffer->capacity * 2 : 8u);
        p2c_transfer(buffer, 0, &old, 0, old.length);
        p2c_z80_buf_release(&old);
    }
    p2c_z80_byte_put(buffer, (int32_t)buffer->length, byte);
    buffer->length++;
}

/* target[:] = source: мало места — прежние страницы в пул и новая память. */
void p2c_buf_assign(P2cBuf *target, const P2cBuf *source) P2C_COLD {
    if (target->capacity < source->length) {
        p2c_z80_buf_release(target);
        p2c_storage(target, source->length);
    }
    p2c_transfer(target, 0, source, 0, source->length);
    target->length = source->length;
}

/* Равенство буферов: длины, затем кусками по 128 байт через два буфера на стеке. */
uint8_t p2c_buf_eq(const P2cBuf *a, const P2cBuf *b) P2C_COLD {
    uint8_t p2c_bounce_a[128];
    uint8_t p2c_bounce_b[128];
    uint32_t offset = 0;
    uint16_t chunk;
    if (a->length != b->length) return 0;
    while (offset < a->length) {
        chunk = a->length - offset > 128u ? 128u : (uint16_t)(a->length - offset);
        p2c_z80_copy_out(a->data, a->page, offset, p2c_bounce_a, chunk);
        p2c_z80_copy_out(b->data, b->page, offset, p2c_bounce_b, chunk);
        if (memcmp(p2c_bounce_a, p2c_bounce_b, chunk) != 0) return 0;
        offset += chunk;
    }
    return 1;
}

#endif /* !P2C_SPLIT_HOT */
