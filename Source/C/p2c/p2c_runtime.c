/* Реализация общей части p2c: целые Python, куча, контейнеры, строки, Rect.
 *
 * Файл делится на горячую и холодную части. На ПК обе собираются вместе; на
 * Z80 горячая часть (выделение памяти, списки, словари, пометка) резидентна,
 * а холодная (сборка мусора целиком, редкие операции контейнеров, строки и
 * форматирование) компилируется в банк кода: её функции объявлены P2C_COLD.
 *
 * Куча — непрерывная область [p2c_heap, P2C_HEAP_END): куски [размер][объект] подряд.
 * Размер куска (P2cSize) включает свой заголовок; следующий кусок — по адресу
 * начала + размер. Свободные куски связаны в список p2c_free_list; всё выше
 * p2c_heap_top ещё не выдавалось. */
#include "p2c_runtime.h"

/* Какую часть собирать: P2C_SPLIT_HOT — только горячую (резидент Z80), P2C_SPLIT_COLD — только
 * холодную (банк кода), без признаков — обе (ПК). */
#if defined(P2C_SPLIT_HOT)
#define P2C_HOT_PART 1
#elif defined(P2C_SPLIT_COLD)
#define P2C_COLD_PART 1
#else
#define P2C_HOT_PART 1
#define P2C_COLD_PART 1
#endif

/* --- общие объявления кучи ---------------------------------------------------------- */

/* Заголовок куска — поле размера (на ПК выровнено до 8 байт, на Z80 — 2 байта). */
#define P2C_CHUNK_HEADER P2C_ROUND(sizeof(P2cSize))
/* Смещение данных блока от начала объекта: данные блока идут сразу за cls, gc. */
#define P2C_BLOCK_DATA P2C_ROUND(sizeof(P2cObject))
/* Самый маленький кусок: заголовок + свободный кусок (cls, gc, next) — остаток меньше не отделяется. */
#define P2C_MIN_CHUNK (P2C_CHUNK_HEADER + P2C_ROUND(sizeof(P2cObject) + sizeof(void *)))

/* Свободный кусок: cls = P2C_CLS_FREE, next — следующий свободный (адрес объекта, не заголовка). */
typedef struct { uint8_t cls; uint8_t gc; void *next; } P2cFreeChunk;

/* Все переменные кучи без статических инициализаторов: на Z80 нет кода
 * копирования инициализированных данных, область _DATA обнуляется при старте. */
#ifdef P2C_HEAP_BASE
#define p2c_heap P2C_HEAP_BASE
#define P2C_HEAP_END P2C_HEAP_LIMIT
#else
extern uint8_t p2c_heap[P2C_HEAP_SIZE];
#define P2C_HEAP_END (p2c_heap + P2C_HEAP_SIZE)
#endif
extern uint8_t *p2c_heap_top;        /* первый байт после последнего выданного куска */
extern P2cFreeChunk *p2c_free_list;  /* свободные куски в порядке адресов (строит сборка) */
extern uint8_t p2c_epoch;            /* номер текущей пометки: живой объект имеет gc == p2c_epoch */
extern uint8_t p2c_heap_dirty;
extern size_t p2c_used_bytes;        /* байт в занятых кусках (с заголовками) */
extern size_t p2c_peak_bytes;        /* максимум p2c_used_bytes за работу */
/* Статические объекты программы вне кучи (генератор): их gc тоже сбрасывается при переполнении эпохи. */
extern P2cObject *const p2c_statics[];
extern const uint16_t p2c_static_count;

/* Стек пометки ограничен; при переполнении объект уже отмечен, а его дети
 * обходятся повторным просмотром отмеченных объектов (идемпотентно). */
#ifndef P2C_MARK_STACK
#define P2C_MARK_STACK 4096
#endif
extern P2cObject *p2c_mark_stack[P2C_MARK_STACK];
extern uint16_t p2c_mark_depth;      /* объектов в стеке пометки */
extern uint8_t p2c_mark_overflow;    /* 1 — стек переполнялся, нужен повторный просмотр */

/* Указатель p лежит в выданной части кучи (строки и объекты вне кучи сборщик не трогает). */
#define P2C_IN_HEAP(p) ((uint8_t *)(p) >= p2c_heap && (uint8_t *)(p) < p2c_heap_top)
/* Поле размера куска объекта object (перед объектом). */
#define P2C_CHUNK_SIZE(object) (*(P2cSize *)((uint8_t *)(object) - P2C_CHUNK_HEADER))

/* Освобождение объекта при сборке: платформа возвращает связанные с ним страницы. */
#ifndef P2C_SWEEP_FREE
#define P2C_SWEEP_FREE(object) ((void)0)
#endif

/* Список на странице данных (Z80) имеет постоянную длину: рост и удаление — отказ. */
#define P2C_FIXED_LIST(list) do { if ((list)->page) p2c_raise(P2C_E_VALUE); } while (0)

/* Копирование элементов из данных списка: на Z80 источник может лежать на странице. */
#ifndef P2C_LIST_COPY_OUT
#define P2C_LIST_COPY_OUT(list, offset, target, count) memcpy((target), (list)->data + (offset), (count))
#endif

#ifdef P2C_HOT_PART

#ifndef P2C_NO_SETJMP
jmp_buf p2c_fault_jump;
#endif
/* Вызываемое значение None: номер цели 0. */
const P2cFn p2c_fn_none = { 0, NULL };

/* Вызываемое значение из номера цели и окружения (возврат структуры — только из резидентной функции). */
P2cFn p2c_fn(uint8_t id, void *env) {
    P2cFn result;
    result.id = id;
    result.env = env;
    return result;
}

#ifndef P2C_HEAP_BASE
uint8_t p2c_heap[P2C_HEAP_SIZE];
#endif
uint8_t *p2c_heap_top;
P2cFreeChunk *p2c_free_list;
uint8_t p2c_epoch;
/* 1 — после прошлой сборки были выделения; без них сборка откладывается до следующего
 * выделения (объекты, потерявшие ссылки, освобождаются этой сборкой). */
uint8_t p2c_heap_dirty;
size_t p2c_used_bytes;
size_t p2c_peak_bytes;
P2cObject *p2c_mark_stack[P2C_MARK_STACK];
uint16_t p2c_mark_depth;
uint8_t p2c_mark_overflow;

/* --- целые -------------------------------------------------------------------- */

#ifdef P2C_CHECKED
/* Проверки ширины: значение, вычисленное в int64, должно помещаться в ширину, выбранную транслятором. */
int16_t p2c_check_i16(int64_t value) {
    if (value < -32768 || value > 32767) p2c_raise(P2C_E_WIDTH);
    return (int16_t)value;
}
uint16_t p2c_check_u16(int64_t value) {
    if (value < 0 || value > 65535) p2c_raise(P2C_E_WIDTH);
    return (uint16_t)value;
}
/* int32 — наибольшая ширина: выход за неё — переполнение, а не ошибка интервала. */
int32_t p2c_check_i32(int64_t value) {
    if (value < INT32_MIN || value > INT32_MAX) p2c_raise(P2C_E_OVERFLOW);
    return (int32_t)value;
}
uint8_t p2c_check_u8(int64_t value) {
    if (value < 0 || value > 255) p2c_raise(P2C_E_WIDTH);
    return (uint8_t)value;
}
int8_t p2c_check_i8(int64_t value) {
    if (value < -128 || value > 127) p2c_raise(P2C_E_WIDTH);
    return (int8_t)value;
}
/* value << count: count < 0 — ValueError; count > 31 — ноль только у нуля, иначе переполнение;
 * иначе value·2^count в int64 и проверка int32. */
int32_t p2c_shl_checked(int32_t value, int32_t count) {
    if (count < 0) { p2c_raise(P2C_E_SHIFT); return 0; }
    if (count > 31) { if (value) p2c_raise(P2C_E_OVERFLOW); return 0; }
    return p2c_check_i32((int64_t)value * ((int64_t)1 << count));
}
/* Адрес элемента index размером size: список не None, 0 ≤ index < length. */
void *p2c_at_checked(const P2cList *list, int32_t index, size_t size) {
    if (list == NULL) p2c_raise(P2C_E_NONE);
    if (index < 0 || (uint32_t)index >= list->length) p2c_raise(P2C_E_INDEX);
    return list->data + (size_t)index * size;
}
uint8_t *p2c_byte_checked(const P2cBuf *buffer, int32_t index) {
    if (buffer == NULL) p2c_raise(P2C_E_NONE);
    if (index < 0 || (uint32_t)index >= buffer->length) p2c_raise(P2C_E_INDEX);
    return buffer->data + index;
}
/* Элемент index очереди: слот (head + index) mod capacity. */
void *p2c_deque_at_checked(const P2cDeque *deque, int32_t index, size_t size) {
    if (index < 0 || (uint32_t)index >= deque->length) p2c_raise(P2C_E_INDEX);
    return deque->data + (size_t)((deque->head + (uint32_t)index) % deque->capacity) * size;
}
uint8_t p2c_check_has(uint8_t has) {
    if (!has) p2c_raise(P2C_E_NONE);
    return has;
}
/* Индекс таблицы значений выражения: значение вне интервала анализа — отказ (интервал неверен). */
uint16_t p2c_check_table(int64_t offset, uint16_t count) {
    if (offset < 0 || offset >= count) p2c_raise(P2C_E_INDEX);
    return (uint16_t)offset;
}
#endif

/* min, max, abs: при равенстве min и max возвращают первый аргумент, как встроенные Python. */
int16_t p2c_min_i16(int16_t a, int16_t b) { return b < a ? b : a; }
uint16_t p2c_min_u16(uint16_t a, uint16_t b) { return b < a ? b : a; }
int32_t p2c_min_i32(int32_t a, int32_t b) { return b < a ? b : a; }
int16_t p2c_max_i16(int16_t a, int16_t b) { return b > a ? b : a; }
uint16_t p2c_max_u16(uint16_t a, uint16_t b) { return b > a ? b : a; }
int32_t p2c_max_i32(int32_t a, int32_t b) { return b > a ? b : a; }
int16_t p2c_abs_i16(int16_t a) { return a < 0 ? (int16_t)-a : a; }
uint16_t p2c_abs_u16(uint16_t a) { return a; }
int32_t p2c_abs_i32(int32_t a) { return a < 0 ? -a : a; }

/* value >> count Python: сдвиг больше 31 даёт знак значения (−1 или 0). */
int32_t p2c_shr(int32_t value, int32_t count) {
    if (count < 0) { p2c_raise(P2C_E_SHIFT); return 0; }
    if (count > 31) return value < 0 ? -1 : 0;
    return value >> count;
}

/* Деление Python (к минус бесконечности). Значения в пределах int16 делятся 16-битной
 * процедурой: на Z80 32-битное деление в несколько раз дороже. */
#define P2C_FITS16(v) ((v) >= -32767L && (v) <= 32767L)

/* Частное и остаток Python. Деление C округляет к нулю: если остаток ненулевой и его знак не совпадает со
 * знаком делителя, частное уменьшается на 1, а к остатку прибавляется делитель (−7 // 2: C даёт −3 и −1,
 * Python — −4 и 1). Границы ±32767 (без −32768): −32768 / −1 в int16 переполнилось бы. */
static void p2c_divmod(int32_t a, int32_t b, int32_t *quotient, int32_t *remainder) {
    if (b == 0) { p2c_raise(P2C_E_ZERODIV); *quotient = 0; *remainder = 0; return; }
    if (P2C_FITS16(a) && P2C_FITS16(b)) {
        int16_t q = (int16_t)a / (int16_t)b;
        int16_t r = (int16_t)((int16_t)a - q * (int16_t)b);
        if (r != 0 && ((r < 0) != (b < 0))) { --q; r = (int16_t)(r + (int16_t)b); }
        *quotient = q;
        *remainder = r;
        return;
    }
    *quotient = a / b;
    *remainder = a - *quotient * b;
    if (*remainder != 0 && ((*remainder < 0) != (b < 0))) { --*quotient; *remainder += b; }
}

/* a // b */
int32_t p2c_floordiv(int32_t a, int32_t b) {
    int32_t quotient;
    int32_t remainder;
    p2c_divmod(a, b, &quotient, &remainder);
    return quotient;
}

/* a % b */
int32_t p2c_mod(int32_t a, int32_t b) {
    int32_t quotient;
    int32_t remainder;
    p2c_divmod(a, b, &quotient, &remainder);
    return remainder;
}

/* round(a / b) при b > 0: q, r — частное и остаток Python (0 ≤ r < b); 2r > b — вверх, 2r = b — к чётному
 * (q + младший бит q), иначе q. */
int32_t p2c_round_div(int32_t a, int32_t b) {
    int32_t quotient;
    int32_t remainder;
    int32_t twice;
    p2c_divmod(a, b, &quotient, &remainder);
    twice = remainder + remainder;
    if (twice > b) return quotient + 1;
    if (twice == b) return quotient + (quotient & 1);
    return quotient;
}

/* Индекс Python: index < 0 — index + length; результат вне [0, length) — IndexError. */
int32_t p2c_index(int32_t index, uint32_t length) {
    if (index < 0) index += (int32_t)length;
    if (index < 0 || (uint32_t)index >= length) { p2c_raise(P2C_E_INDEX); return 0; }
    return index;
}

/* --- куча: блоки [размер][объект], сборка пометкой по эпохам --------------------- */

/* Пустая куча: всё свободно выше p2c_heap, эпоха 1 (gc = 0 у новых объектов — «не отмечен»). */
void p2c_heap_init(void) {
    p2c_heap_top = p2c_heap;
    p2c_free_list = NULL;
    p2c_used_bytes = 0;
    p2c_epoch = 1;
}

/* Кусок под payload байт объекта (обнулённый): первый подходящий свободный кусок (остаток от P2C_MIN_CHUNK
 * отделяется в новый свободный кусок на месте старого в списке, меньший остаток отдаётся целиком), иначе —
 * с вершины кучи; места нет — MemoryError. Возвращает адрес объекта (за полем размера). */
static P2cObject *p2c_alloc_chunk(size_t payload) {
    size_t size = P2C_ROUND(payload + P2C_CHUNK_HEADER);
    P2cFreeChunk *previous = NULL;
    P2cFreeChunk *chunk;
    uint8_t *start;
    if (p2c_heap_top == NULL) p2c_heap_init();
    p2c_heap_dirty = 1;
    chunk = p2c_free_list;
    if (size < P2C_MIN_CHUNK) size = P2C_MIN_CHUNK;
    while (chunk != NULL) {
        size_t available = P2C_CHUNK_SIZE(chunk);
        if (available >= size) {
            P2cFreeChunk *next = (P2cFreeChunk *)chunk->next;
            if (available - size >= P2C_MIN_CHUNK) {
                /* Остаток — новый свободный кусок сразу за выдаваемым. */
                P2cFreeChunk *rest = (P2cFreeChunk *)((uint8_t *)chunk + size);
                P2C_CHUNK_SIZE(rest) = (P2cSize)(available - size);
                rest->cls = P2C_CLS_FREE;
                rest->gc = 0;
                rest->next = next;
                next = rest;
            } else {
                size = available;
            }
            if (previous == NULL) p2c_free_list = next; else previous->next = next;
            P2C_CHUNK_SIZE(chunk) = (P2cSize)size;
            p2c_used_bytes += size;
            if (p2c_used_bytes > p2c_peak_bytes) p2c_peak_bytes = p2c_used_bytes;
            memset(chunk, 0, size - P2C_CHUNK_HEADER);
            return (P2cObject *)chunk;
        }
        previous = chunk;
        chunk = (P2cFreeChunk *)chunk->next;
    }
    if ((size_t)(P2C_HEAP_END - p2c_heap_top) < size) {
        p2c_raise(P2C_E_MEMORY);
        return NULL;
    }
    start = p2c_heap_top;
    p2c_heap_top += size;
    *(P2cSize *)start = (P2cSize)size;
    p2c_used_bytes += size;
    if (p2c_used_bytes > p2c_peak_bytes) p2c_peak_bytes = p2c_used_bytes;
    memset(start + P2C_CHUNK_HEADER, 0, size - P2C_CHUNK_HEADER);
    return (P2cObject *)(start + P2C_CHUNK_HEADER);
}

P2cObject *p2c_new_object(uint8_t cls, size_t size) {
    P2cObject *object = p2c_alloc_chunk(size);
    object->cls = cls;
    object->gc = 0;
    return object;
}

/* Блок данных: объект класса P2C_CLS_BLOCK, данные — за его заголовком (пустой блок — 1 байт). */
void *p2c_alloc_block(size_t size) {
    P2cObject *block = p2c_alloc_chunk(P2C_BLOCK_DATA + (size ? size : 1));
    block->cls = P2C_CLS_BLOCK;
    return (uint8_t *)block + P2C_BLOCK_DATA;
}

/* Временный блок: на него нет ссылок из корней, сборка между кадрами его освободит. */
void *p2c_scratch(size_t size) {
    return p2c_alloc_block(size);
}

/* Отметить объект живым в текущей эпохе и положить в стек (дети — позже, p2c_drain). Постоянные строки вне
 * кучи и уже отмеченные объекты пропускаются; стек полон — отметка остаётся, дети найдёт p2c_rescan. */
void p2c_mark(P2cObject *object) {
    if (object == NULL) return;
    if (object->cls == P2C_CLS_STR && !P2C_IN_HEAP(object)) return;
    if (object->gc == p2c_epoch) return;
    object->gc = p2c_epoch;
    if (p2c_mark_depth >= P2C_MARK_STACK) { p2c_mark_overflow = 1; return; }
    p2c_mark_stack[p2c_mark_depth++] = object;
}

/* Отметить блок данных по адресу его данных (детей у блока нет); данные вне кучи — не блок. */
void p2c_mark_block(void *data) {
    P2cObject *block;
    if (data == NULL || !P2C_IN_HEAP(data)) return;
    block = (P2cObject *)((uint8_t *)data - P2C_BLOCK_DATA);
    block->gc = p2c_epoch;
}

/* --- списки ------------------------------------------------------------------------- */

/* Пустой список с местом под capacity элементов по size байт (данных нет при capacity = 0). */
P2cList *p2c_list_new(uint8_t cls, size_t size, uint16_t capacity) {
    P2cList *list = (P2cList *)p2c_new_object(cls, sizeof(P2cList));
    list->capacity = capacity;
    list->data = capacity ? (uint8_t *)p2c_alloc_block(size * capacity) : NULL;
    return list;
}

P2cList *p2c_array_new(uint8_t cls, size_t size, uint16_t length) {
    P2cList *list = p2c_list_new(cls, size, length);
    list->length = length;
    return list;
}

/* Ёмкость не меньше needed: удвоение (пустой — 4), не больше 65535 элементов. Старый блок данных не
 * освобождается явно — его освободит сборка, когда ссылок не останется. */
void p2c_list_reserve(P2cList *list, size_t size, uint32_t needed) {
    uint32_t capacity;
    uint8_t *data;
    if (needed <= list->capacity) return;
    if (needed > 65535UL) p2c_raise(P2C_E_MEMORY);
    capacity = list->capacity ? (uint32_t)list->capacity * 2 : 4;
    if (capacity < needed) capacity = needed;
    if (capacity > 65535UL) capacity = 65535UL;
    data = (uint8_t *)p2c_alloc_block(size * capacity);
    if (list->length) memcpy(data, list->data, size * list->length);
    list->data = data;
    list->capacity = (uint16_t)capacity;
}

/* Место нового последнего элемента: адрес data + size·length, затем length + 1. */
void *p2c_list_push(P2cList *list, size_t size) {
    P2C_FIXED_LIST(list);
    p2c_list_reserve(list, size, (uint32_t)list->length + 1);
    return list->data + size * list->length++;
}

/* list.clear(): длина 0, блок данных остаётся (ёмкость сохраняется). */
void p2c_list_clear(P2cList *list) {
    P2C_FIXED_LIST(list);
    list->length = 0;
}

/* --- словари: порядок вставки, удалённые записи пропускаются ------------------------ */

/* Словарь с местом под capacity записей: массивы признаков жизни, ключей и значений (у set значений нет). */
P2cDict *p2c_dict_new(uint8_t cls, size_t key_size, size_t value_size, uint16_t capacity) {
    P2cDict *dict = (P2cDict *)p2c_new_object(cls, sizeof(P2cDict));
    dict->key_size = (uint8_t)key_size;
    dict->value_size = (uint8_t)value_size;
    dict->capacity = capacity;
    if (capacity) {
        dict->live = (uint8_t *)p2c_alloc_block(capacity);
        dict->keys = (uint8_t *)p2c_alloc_block(key_size * capacity);
        dict->values = value_size ? (uint8_t *)p2c_alloc_block(value_size * capacity) : NULL;
    }
    return dict;
}

/* Перебор записей 0…used − 1: живая с побайтно равным ключом (ключ i — keys + key_size·i). */
int32_t p2c_dict_find(const P2cDict *dict, const void *key) {
    uint16_t index;
    for (index = 0; index < dict->used; index++) {
        if (dict->live[index] && memcmp(dict->keys + (size_t)dict->key_size * index, key, dict->key_size) == 0) {
            return index;
        }
    }
    return -1;
}

/* Есть ключ — заменить значение; нет — новая запись used (места нет — p2c_dict_grow), length + 1. */
void p2c_dict_set(P2cDict *dict, const void *key, const void *value) {
    int32_t index = p2c_dict_find(dict, key);
    if (index < 0) {
        if (dict->used == dict->capacity) p2c_dict_grow(dict);
        index = dict->used++;
        dict->live[index] = 1;
        memcpy(dict->keys + (size_t)dict->key_size * (size_t)index, key, dict->key_size);
        dict->length++;
    }
    if (value != NULL && dict->value_size) {
        memcpy(dict->values + (size_t)dict->value_size * (size_t)index, value, dict->value_size);
    }
}

/* --- байты и строки: частые проверки ---------------------------------------------------- */

uint8_t p2c_byte_value(int32_t value) {
    if (value < 0 || value > 255) p2c_raise(P2C_E_VALUE);
    return (uint8_t)value;
}

/* Смещение struct: отрицательное — от конца; [offset, offset + size) должно лежать в буфере. */
int32_t p2c_buf_require(const P2cBuf *buffer, int32_t offset, int32_t size) {
    if (offset < 0) offset += (int32_t)buffer->length;
    if (offset < 0 || (uint32_t)offset + (uint32_t)size > buffer->length) {
        p2c_raise(P2C_E_STRUCT);
        return 0;
    }
    return offset;
}

/* Равенство строк: тот же объект, иначе длина и байты (None равен только None). */
uint8_t p2c_str_eq(const P2cStr *a, const P2cStr *b) {
    if (a == b) return 1;
    if (a == NULL || b == NULL || a->length != b->length) return 0;
    if (a->length == 1u) return (uint8_t)(a->data[0] == b->data[0]);   /* один символ — без memcmp */
    return memcmp(a->data, b->data, a->length) == 0;
}

/* Односимвольные строки печатных ASCII 32…127 — постоянные объекты вне кучи (сборщик строки вне
 * кучи не отмечает); строка символа другого кода создаётся в куче холодной частью. */
static const uint8_t p2c_char_codes[96] = {
    32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55,
    56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103,
    104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123,
    124, 125, 126, 127 };
/* Строка символа с кодом 32 + n: класс строки, gc 0, длина 1, данные — байт таблицы кодов. */
#define P2C_CHAR_OBJECT(n) { P2C_CLS_STR, 0, 1u, &p2c_char_codes[n] }
static const P2cStr p2c_chars[96] = {
    P2C_CHAR_OBJECT(0), P2C_CHAR_OBJECT(1), P2C_CHAR_OBJECT(2), P2C_CHAR_OBJECT(3), P2C_CHAR_OBJECT(4),
    P2C_CHAR_OBJECT(5), P2C_CHAR_OBJECT(6), P2C_CHAR_OBJECT(7), P2C_CHAR_OBJECT(8), P2C_CHAR_OBJECT(9),
    P2C_CHAR_OBJECT(10), P2C_CHAR_OBJECT(11), P2C_CHAR_OBJECT(12), P2C_CHAR_OBJECT(13), P2C_CHAR_OBJECT(14),
    P2C_CHAR_OBJECT(15), P2C_CHAR_OBJECT(16), P2C_CHAR_OBJECT(17), P2C_CHAR_OBJECT(18), P2C_CHAR_OBJECT(19),
    P2C_CHAR_OBJECT(20), P2C_CHAR_OBJECT(21), P2C_CHAR_OBJECT(22), P2C_CHAR_OBJECT(23), P2C_CHAR_OBJECT(24),
    P2C_CHAR_OBJECT(25), P2C_CHAR_OBJECT(26), P2C_CHAR_OBJECT(27), P2C_CHAR_OBJECT(28), P2C_CHAR_OBJECT(29),
    P2C_CHAR_OBJECT(30), P2C_CHAR_OBJECT(31), P2C_CHAR_OBJECT(32), P2C_CHAR_OBJECT(33), P2C_CHAR_OBJECT(34),
    P2C_CHAR_OBJECT(35), P2C_CHAR_OBJECT(36), P2C_CHAR_OBJECT(37), P2C_CHAR_OBJECT(38), P2C_CHAR_OBJECT(39),
    P2C_CHAR_OBJECT(40), P2C_CHAR_OBJECT(41), P2C_CHAR_OBJECT(42), P2C_CHAR_OBJECT(43), P2C_CHAR_OBJECT(44),
    P2C_CHAR_OBJECT(45), P2C_CHAR_OBJECT(46), P2C_CHAR_OBJECT(47), P2C_CHAR_OBJECT(48), P2C_CHAR_OBJECT(49),
    P2C_CHAR_OBJECT(50), P2C_CHAR_OBJECT(51), P2C_CHAR_OBJECT(52), P2C_CHAR_OBJECT(53), P2C_CHAR_OBJECT(54),
    P2C_CHAR_OBJECT(55), P2C_CHAR_OBJECT(56), P2C_CHAR_OBJECT(57), P2C_CHAR_OBJECT(58), P2C_CHAR_OBJECT(59),
    P2C_CHAR_OBJECT(60), P2C_CHAR_OBJECT(61), P2C_CHAR_OBJECT(62), P2C_CHAR_OBJECT(63), P2C_CHAR_OBJECT(64),
    P2C_CHAR_OBJECT(65), P2C_CHAR_OBJECT(66), P2C_CHAR_OBJECT(67), P2C_CHAR_OBJECT(68), P2C_CHAR_OBJECT(69),
    P2C_CHAR_OBJECT(70), P2C_CHAR_OBJECT(71), P2C_CHAR_OBJECT(72), P2C_CHAR_OBJECT(73), P2C_CHAR_OBJECT(74),
    P2C_CHAR_OBJECT(75), P2C_CHAR_OBJECT(76), P2C_CHAR_OBJECT(77), P2C_CHAR_OBJECT(78), P2C_CHAR_OBJECT(79),
    P2C_CHAR_OBJECT(80), P2C_CHAR_OBJECT(81), P2C_CHAR_OBJECT(82), P2C_CHAR_OBJECT(83), P2C_CHAR_OBJECT(84),
    P2C_CHAR_OBJECT(85), P2C_CHAR_OBJECT(86), P2C_CHAR_OBJECT(87), P2C_CHAR_OBJECT(88), P2C_CHAR_OBJECT(89),
    P2C_CHAR_OBJECT(90), P2C_CHAR_OBJECT(91), P2C_CHAR_OBJECT(92), P2C_CHAR_OBJECT(93), P2C_CHAR_OBJECT(94),
    P2C_CHAR_OBJECT(95) };

const P2cStr *p2c_str_char(const P2cStr *text, int32_t index) {
    uint8_t value;
    if (index < 0 || (uint32_t)index >= text->length) p2c_raise(P2C_E_INDEX);
    value = text->data[(uint16_t)index];
    if ((uint8_t)(value - 32u) < 96u) return &p2c_chars[(uint8_t)(value - 32u)];   /* код − 32 < 96 */
    return p2c_str_char_other(&text->data[(uint16_t)index]);
}

uint8_t p2c_ord(const P2cStr *text) {
    if (text->length != 1u) p2c_raise(P2C_E_VALUE);
    return text->data[0];
}

/* --- Rect: пересечение по правилам pygame-ce (нулевой размер не пересекается) -------------------- */

/* Отрицательный размер нормализуется: левый край = x + w, правый = x (и так же по y); пересечение — строгие
 * неравенства краёв (касание сторонами не пересечение). */
uint8_t p2c_rect_collide(P2cRect a, P2cRect b) {
    int32_t a_left, a_right, a_top, a_bottom, b_left, b_right, b_top, b_bottom;
    if (a.w == 0 || a.h == 0 || b.w == 0 || b.h == 0) return 0;
    a_left = a.w < 0 ? (int32_t)a.x + a.w : a.x;
    a_right = a.w < 0 ? a.x : (int32_t)a.x + a.w;
    a_top = a.h < 0 ? (int32_t)a.y + a.h : a.y;
    a_bottom = a.h < 0 ? a.y : (int32_t)a.y + a.h;
    b_left = b.w < 0 ? (int32_t)b.x + b.w : b.x;
    b_right = b.w < 0 ? b.x : (int32_t)b.x + b.w;
    b_top = b.h < 0 ? (int32_t)b.y + b.h : b.y;
    b_bottom = b.h < 0 ? b.y : (int32_t)b.y + b.h;
    return a_left < b_right && a_top < b_bottom && a_right > b_left && a_bottom > b_top;
}

#endif /* P2C_HOT_PART */

#ifdef P2C_COLD_PART

/* Число единичных битов: сдвигами по одному биту (вызывается редко). */
uint8_t p2c_bit_count(uint32_t value) P2C_COLD {
    uint8_t count = 0;
    while (value) { count += (uint8_t)(value & 1u); value >>= 1; }
    return count;
}

/* |value| без переполнения у INT32_MIN: −(value + 1) + 1 в uint32. */
uint8_t p2c_bit_count_signed(int32_t value) P2C_COLD {
    return p2c_bit_count(value < 0 ? (uint32_t)(-(value + 1)) + 1u : (uint32_t)value);
}

size_t p2c_heap_used(void) P2C_COLD { return p2c_used_bytes; }
size_t p2c_heap_peak(void) P2C_COLD { return p2c_peak_bytes; }

/* Перепись кучи по номерам классов (байты занятых блоков) для диагностики. */
void p2c_heap_census(uint32_t *bytes_by_class) P2C_COLD {
    uint8_t *cursor;
    for (cursor = p2c_heap; cursor < p2c_heap_top; cursor += *(P2cSize *)cursor) {
        P2cObject *object = (P2cObject *)(cursor + P2C_CHUNK_HEADER);
        bytes_by_class[object->cls] += *(P2cSize *)cursor;
    }
}

/* Дети отмеченного объекта: у строки — блок её данных, у остальных — поля по классу (генератор). */
static void p2c_visit(P2cObject *object) {
    if (object->cls == P2C_CLS_STR) {
        p2c_mark_block((void *)((P2cStr *)object)->data);
        return;
    }
    p2c_mark_children(object);
}

/* Обойти всё, что лежит в стеке пометки (обход кладёт новых детей в тот же стек). */
static void p2c_drain(void) {
    while (p2c_mark_depth) p2c_visit(p2c_mark_stack[--p2c_mark_depth]);
}

/* Стек переполнялся: у отмеченных объектов могли остаться необойдённые дети. Обойти заново все отмеченные
 * статические объекты и объекты кучи (кроме свободных кусков и блоков), пока переполнений не будет. */
static void p2c_rescan(void) {
    uint8_t *cursor;
    uint16_t index;
    while (p2c_mark_overflow) {
        p2c_mark_overflow = 0;
        for (index = 0; index < p2c_static_count; index++) {
            if (p2c_statics[index]->gc == p2c_epoch) {
                p2c_visit(p2c_statics[index]);
                p2c_drain();
            }
        }
        for (cursor = p2c_heap; cursor < p2c_heap_top; cursor += *(P2cSize *)cursor) {
            P2cObject *object = (P2cObject *)(cursor + P2C_CHUNK_HEADER);
            if (object->cls != P2C_CLS_FREE && object->cls != P2C_CLS_BLOCK && object->gc == p2c_epoch) {
                p2c_visit(object);
                p2c_drain();
            }
        }
    }
}

/* Сборка мусора: новая эпоха, пометка от корней, затем развёртка всей кучи по порядку адресов. Живой кусок
 * (gc == эпоха) остаётся; мёртвые и свободные подряд сливаются в один свободный кусок (run) и связываются в
 * список по возрастанию адресов. Если куча кончается свободным куском, он возвращается под вершину:
 * p2c_heap_top опускается на его начало. Без выделений после прошлой сборки делать нечего. */
void p2c_collect(void) P2C_COLD {
    uint8_t *cursor;
    P2cFreeChunk *tail = NULL;       /* последний кусок списка свободных */
    P2cFreeChunk *run = NULL;        /* текущий свободный кусок, к которому прибавляются соседи */
    uint16_t index;
    if (p2c_heap_top == NULL) p2c_heap_init();
    if (!p2c_heap_dirty) return;
    p2c_heap_dirty = 0;
    p2c_epoch++;
    if (p2c_epoch == 0) {
        /* Переполнение эпохи: сбросить отметки статических объектов и кучи. */
        for (index = 0; index < p2c_static_count; index++) p2c_statics[index]->gc = 0;
        for (cursor = p2c_heap; cursor < p2c_heap_top; cursor += *(P2cSize *)cursor) {
            ((P2cObject *)(cursor + P2C_CHUNK_HEADER))->gc = 0;
        }
        p2c_epoch = 1;
    }
    for (index = 0; index < p2c_root_count; index++) p2c_mark(p2c_roots[index]);
    p2c_drain();
    p2c_rescan();
    p2c_free_list = NULL;
    p2c_used_bytes = 0;
    for (cursor = p2c_heap; cursor < p2c_heap_top;) {
        P2cSize size = *(P2cSize *)cursor;
        P2cObject *object = (P2cObject *)(cursor + P2C_CHUNK_HEADER);
        if (object->cls != P2C_CLS_FREE && object->gc == p2c_epoch) {
            p2c_used_bytes += size;
            run = NULL;
            cursor += size;
            continue;
        }
        if (object->cls != P2C_CLS_FREE) P2C_SWEEP_FREE(object);
        if (run != NULL) {
            P2C_CHUNK_SIZE(run) = (P2cSize)(P2C_CHUNK_SIZE(run) + size);
        } else {
            run = (P2cFreeChunk *)object;
            run->cls = P2C_CLS_FREE;
            run->gc = 0;
            run->next = NULL;
            if (tail == NULL) p2c_free_list = run; else tail->next = run;
            tail = run;
        }
        cursor += size;
    }
    if (run != NULL) {
        /* Свободный хвост возвращается в область последовательного выделения. */
        uint8_t *start = (uint8_t *)run - P2C_CHUNK_HEADER;
        P2cFreeChunk *chunk = p2c_free_list;
        P2cFreeChunk *previous = NULL;
        while (chunk != NULL && chunk != run) { previous = chunk; chunk = (P2cFreeChunk *)chunk->next; }
        if (previous == NULL) p2c_free_list = NULL; else previous->next = NULL;
        p2c_heap_top = start;
    }
#ifdef P2C_CHECKED
    /* Проверка: освобождённая память заполняется, чтобы висячие ссылки проявились. */
    {
        P2cFreeChunk *chunk;
        for (chunk = p2c_free_list; chunk != NULL; chunk = (P2cFreeChunk *)chunk->next) {
            size_t size = P2C_CHUNK_SIZE(chunk);
            if (size > P2C_ROUND(sizeof(P2cFreeChunk)) + P2C_CHUNK_HEADER) {
                memset((uint8_t *)chunk + P2C_ROUND(sizeof(P2cFreeChunk)), 0xDD,
                       size - P2C_CHUNK_HEADER - P2C_ROUND(sizeof(P2cFreeChunk)));
            }
        }
    }
#endif
}

/* --- редкие операции списков и очередей ------------------------------------------------ */

/* list.insert(index, v): index < 0 — от конца (не меньше 0), больше длины — в конец; хвост с index
 * сдвигается на элемент вправо (memmove), возвращается адрес освобождённого места. */
void *p2c_list_insert_slot(P2cList *list, size_t size, int32_t index) P2C_COLD {
    P2C_FIXED_LIST(list);
    if (index < 0) { index += list->length; if (index < 0) index = 0; }
    if ((uint32_t)index > list->length) index = list->length;
    p2c_list_reserve(list, size, (uint32_t)list->length + 1);
    memmove(list->data + size * ((size_t)index + 1), list->data + size * (size_t)index,
            size * (list->length - (size_t)index));
    list->length++;
    return list->data + size * (size_t)index;
}

/* Удалить count элементов с index: хвост сдвигается влево на count. */
void p2c_list_delete(P2cList *list, size_t size, int32_t index, uint16_t count) P2C_COLD {
    P2C_FIXED_LIST(list);
    if (index < 0 || (uint32_t)index + count > list->length) { p2c_raise(P2C_E_INDEX); return; }
    memmove(list->data + size * (size_t)index, list->data + size * ((size_t)index + count),
            size * (list->length - (size_t)index - count));
    list->length = (uint16_t)(list->length - count);
}

/* Границы среза Python для длины length: отрицательные — от конца с отсечением к 0, больше длины — к длине,
 * high < low — пустой срез (high = low). */
static void p2c_slice_bounds(uint32_t length, int32_t *low, int32_t *high) {
    if (*low < 0) { *low += (int32_t)length; if (*low < 0) *low = 0; }
    if (*high < 0) { *high += (int32_t)length; if (*high < 0) *high = 0; }
    if ((uint32_t)*low > length) *low = (int32_t)length;
    if ((uint32_t)*high > length) *high = (int32_t)length;
    if (*high < *low) *high = *low;
}

void p2c_list_delete_slice(P2cList *list, size_t size, int32_t low, int32_t high) P2C_COLD {
    p2c_slice_bounds(list->length, &low, &high);
    if (high > low) p2c_list_delete(list, size, low, (uint16_t)(high - low));
}

/* Новый список ровно из high − low элементов (данные копируются и со страницы — P2C_LIST_COPY_OUT). */
P2cList *p2c_list_slice(uint8_t cls, const P2cList *list, size_t size, int32_t low, int32_t high) P2C_COLD {
    P2cList *result;
    p2c_slice_bounds(list->length, &low, &high);
    result = p2c_list_new(cls, size, (uint16_t)(high - low));
    if (high > low) P2C_LIST_COPY_OUT(list, size * (size_t)low, result->data, size * (size_t)(high - low));
    result->length = (uint16_t)(high - low);
    return result;
}

P2cList *p2c_array_slice(uint8_t cls, const P2cList *list, size_t size, int32_t low, int32_t high) P2C_COLD {
    return p2c_list_slice(cls, list, size, low, high);
}

P2cDeque *p2c_deque_new(uint8_t cls, size_t size, uint16_t capacity) P2C_COLD {
    P2cDeque *deque = (P2cDeque *)p2c_new_object(cls, sizeof(P2cDeque));
    deque->capacity = capacity;
    deque->data = capacity ? (uint8_t *)p2c_alloc_block(size * capacity) : NULL;
    return deque;
}

/* append: кольцо полно — новое кольцо вдвое больше (пустое — 8), элементы переписываются по порядку с
 * head = 0. Место нового элемента — слот (head + length) mod capacity. */
void *p2c_deque_push(P2cDeque *deque, size_t size) P2C_COLD {
    if (deque->length == deque->capacity) {
        uint32_t capacity = deque->capacity ? (uint32_t)deque->capacity * 2 : 8;
        uint8_t *data;
        uint16_t index;
        if (capacity > 65535UL) p2c_raise(P2C_E_MEMORY);
        data = (uint8_t *)p2c_alloc_block(size * capacity);
        for (index = 0; index < deque->length; index++) {
            memcpy(data + size * index, deque->data + size * ((deque->head + index) % deque->capacity), size);
        }
        deque->data = data;
        deque->head = 0;
        deque->capacity = (uint16_t)capacity;
    }
    return deque->data + size * ((deque->head + deque->length++) % deque->capacity);
}

/* popleft без значения (значение генератор читает до вызова): head сдвигается по кольцу. */
void p2c_deque_popleft(P2cDeque *deque) P2C_COLD {
    if (deque->length == 0) { p2c_raise(P2C_E_INDEX); return; }
    deque->head = (uint16_t)((deque->head + 1) % deque->capacity);
    deque->length--;
}

void p2c_deque_clear(P2cDeque *deque) P2C_COLD {
    deque->length = 0;
    deque->head = 0;
}

/* --- редкие операции словарей ---------------------------------------------------------- */

/* Новые массивы вдвое больше (пустой — 4); живые записи переписываются подряд (source → target), удалённые
 * выпадают, порядок вставки сохраняется; used становится числом живых. */
void p2c_dict_grow(P2cDict *dict) P2C_COLD {
    uint32_t capacity = dict->capacity ? (uint32_t)dict->capacity * 2 : 4;
    uint8_t *live;
    uint8_t *keys;
    uint8_t *values;
    uint16_t source;
    uint16_t target = 0;
    if (capacity > 65535UL) p2c_raise(P2C_E_MEMORY);
    live = (uint8_t *)p2c_alloc_block(capacity);
    keys = (uint8_t *)p2c_alloc_block((size_t)dict->key_size * capacity);
    values = dict->value_size ? (uint8_t *)p2c_alloc_block((size_t)dict->value_size * capacity) : NULL;
    for (source = 0; source < dict->used; source++) {
        if (!dict->live[source]) continue;
        live[target] = 1;
        memcpy(keys + (size_t)dict->key_size * target, dict->keys + (size_t)dict->key_size * source, dict->key_size);
        if (values) {
            memcpy(values + (size_t)dict->value_size * target,
                   dict->values + (size_t)dict->value_size * source, dict->value_size);
        }
        target++;
    }
    dict->live = live;
    dict->keys = keys;
    dict->values = values;
    dict->used = target;
    dict->capacity = (uint16_t)capacity;
}

/* Запись помечается мёртвой; мёртвые записи в конце отбрасываются уменьшением used. */
void p2c_dict_delete(P2cDict *dict, const void *key) P2C_COLD {
    int32_t index = p2c_dict_find(dict, key);
    if (index < 0) return;
    dict->live[index] = 0;
    dict->length--;
    while (dict->used && !dict->live[dict->used - 1]) dict->used--;
}

void p2c_dict_clear(P2cDict *dict) P2C_COLD {
    dict->used = 0;
    dict->length = 0;
}

/* --- байты ------------------------------------------------------------------------------ */

/* Буферы в куче (ПК); Z80 реализует их сам со страницами пула (p2c_z80.c). */
#ifndef P2C_PLATFORM_BUFFERS
P2cBuf *p2c_buf_new(size_t size, uint8_t mutable_flag) P2C_COLD {
    P2cBuf *buffer = (P2cBuf *)p2c_new_object(P2C_CLS_BUF, sizeof(P2cBuf));
    (void)mutable_flag;
    buffer->length = (P2cSize)size;
    buffer->capacity = (P2cSize)size;
    buffer->data = (uint8_t *)p2c_alloc_block(size);
    return buffer;
}

P2cBuf *p2c_buf_copy(const P2cBuf *source, uint8_t mutable_flag) P2C_COLD {
    P2cBuf *buffer = p2c_buf_new(source->length, mutable_flag);
    memcpy(buffer->data, source->data, source->length);
    return buffer;
}

P2cBuf *p2c_buf_slice(const P2cBuf *source, int32_t low, int32_t high, uint8_t mutable_flag) P2C_COLD {
    P2cBuf *buffer;
    p2c_slice_bounds(source->length, &low, &high);
    buffer = p2c_buf_new((size_t)(high - low), mutable_flag);
    memcpy(buffer->data, source->data + low, (size_t)(high - low));
    return buffer;
}

/* Полный буфер — новый блок вдвое больше (пустой — 8), затем байт в конец. */
void p2c_buf_append(P2cBuf *buffer, int32_t value) P2C_COLD {
    if (buffer->length == buffer->capacity) {
        P2cSize capacity = buffer->capacity ? buffer->capacity * 2 : 8;
        uint8_t *data = (uint8_t *)p2c_alloc_block(capacity);
        memcpy(data, buffer->data, buffer->length);
        buffer->data = data;
        buffer->capacity = capacity;
    }
    buffer->data[buffer->length++] = p2c_byte_value(value);
}

/* target[:] = source: мало места — новый блок; memmove — source и target могут быть одним буфером. */
void p2c_buf_assign(P2cBuf *target, const P2cBuf *source) P2C_COLD {
    if (target->capacity < source->length) {
        target->data = (uint8_t *)p2c_alloc_block(source->length);
        target->capacity = source->length;
    }
    memmove(target->data, source->data, source->length);
    target->length = source->length;
}

uint8_t p2c_buf_eq(const P2cBuf *a, const P2cBuf *b) P2C_COLD {
    return a->length == b->length && memcmp(a->data, b->data, a->length) == 0;
}
#endif

/* Значение поля struct.pack в границах формата H, h, B, b. */
void p2c_require_u16(int32_t value) P2C_COLD { if (value < 0 || value > 65535L) p2c_raise(P2C_E_STRUCT); }
void p2c_require_i16(int32_t value) P2C_COLD { if (value < -32768L || value > 32767) p2c_raise(P2C_E_STRUCT); }
void p2c_require_u8(int32_t value) P2C_COLD { if (value < 0 || value > 255) p2c_raise(P2C_E_STRUCT); }
void p2c_require_i8(int32_t value) P2C_COLD { if (value < -128 || value > 127) p2c_raise(P2C_E_STRUCT); }

/* --- строки ---------------------------------------------------------------------------------- */

static const P2cStr *p2c_str_make(const uint8_t *data, uint16_t length);

/* Строка символа непечатного кода (печатные 32…127 — постоянные объекты горячей части). */
const P2cStr *p2c_str_char_other(const uint8_t *data) P2C_COLD {
    return p2c_str_make(data, 1);
}

/* len(text.replace(old, "")) без новой строки: длина минус вхождения old, найденные слева направо
 * без перекрытия, как в str.replace CPython; пустая old строку не меняет. */
uint16_t p2c_str_len_without(const P2cStr *text, const P2cStr *old) P2C_COLD {
    uint16_t index;
    uint16_t length = text->length;
    if (old->length == 0u) return length;
    if (old->length == 1u) {
        uint8_t code = old->data[0];
        for (index = 0; index < text->length; ++index) {
            if (text->data[index] == code) --length;
        }
        return length;
    }
    index = 0;
    while ((uint16_t)(index + old->length) <= text->length) {
        if (memcmp(text->data + index, old->data, old->length) == 0) {
            length = (uint16_t)(length - old->length);
            index = (uint16_t)(index + old->length);
        } else {
            ++index;
        }
    }
    return length;
}

/* Разбор: пробелы по краям, знак, цифры (подчёркивания пропускаются); значение набирается как
 * value·10 + цифра = (value << 3) + (value << 1) + цифра; модуль до 2147483648, положительное — до INT32_MAX. */
int32_t p2c_str_int(const P2cStr *text) P2C_COLD {
    uint16_t index = 0;
    uint16_t end = text->length;
    uint8_t negative = 0;
    uint32_t value = 0;
    while (index < end && text->data[index] == ' ') index++;
    while (end > index && text->data[end - 1] == ' ') end--;
    if (index < end && (text->data[index] == '-' || text->data[index] == '+')) {
        negative = text->data[index] == '-';
        index++;
    }
    if (index >= end) p2c_raise(P2C_E_VALUE);
    for (; index < end; index++) {
        uint8_t digit = text->data[index];
        if (digit == '_' ) continue;
        if (digit < '0' || digit > '9') p2c_raise(P2C_E_VALUE);
        digit = (uint8_t)(digit - '0');
        /* Проверка до умножения: результат не больше 2147483648 (модуль INT32_MIN). */
        if (value > 214748364UL || (value == 214748364UL && digit > 8)) p2c_raise(P2C_E_OVERFLOW);
        value = (value << 3) + (value << 1) + digit;
    }
    if (negative) return (int32_t)(0UL - value);
    if (value > (uint32_t)INT32_MAX) p2c_raise(P2C_E_OVERFLOW);
    return (int32_t)value;
}

/* Новая строка в куче: объект строки и блок-копия length байт. */
static const P2cStr *p2c_str_make(const uint8_t *data, uint16_t length) {
    P2cStr *result = (P2cStr *)p2c_new_object(P2C_CLS_STR, sizeof(P2cStr));
    uint8_t *copy = (uint8_t *)p2c_alloc_block(length);
    memcpy(copy, data, length);
    result->length = length;
    result->data = copy;
    return result;
}

/* Замена вхождений old слева направо без перекрытия; результат собирается в буфере на стеке (512 байт). */
const P2cStr *p2c_str_replace(const P2cStr *text, const P2cStr *old, const P2cStr *replacement) P2C_COLD {
    uint8_t buffer[512];
    uint16_t out = 0;
    uint16_t index = 0;
    if (old->length == 0) p2c_raise(P2C_E_VALUE);
    while (index < text->length) {
        if (index + old->length <= text->length && memcmp(text->data + index, old->data, old->length) == 0) {
            if (out + replacement->length > sizeof buffer) p2c_raise(P2C_E_MEMORY);
            memcpy(buffer + out, replacement->data, replacement->length);
            out = (uint16_t)(out + replacement->length);
            index = (uint16_t)(index + old->length);
        } else {
            if (out >= sizeof buffer) p2c_raise(P2C_E_MEMORY);
            buffer[out++] = text->data[index++];
        }
    }
    return p2c_str_make(buffer, out);
}

/* Буфер собираемой f-строки и его заполнение. */
static uint8_t p2c_fmt_buffer[256];
static uint16_t p2c_fmt_length;

void p2c_fmt_begin(void) P2C_COLD { p2c_fmt_length = 0; }

void p2c_fmt_text(const P2cStr *text) P2C_COLD {
    if (p2c_fmt_length + text->length > sizeof p2c_fmt_buffer) p2c_raise(P2C_E_MEMORY);
    memcpy(p2c_fmt_buffer + p2c_fmt_length, text->data, text->length);
    p2c_fmt_length = (uint16_t)(p2c_fmt_length + text->length);
}

/* Целое по спецификации: [0]ширина[d|x|X]. Цифры набираются с младшей в digits, затем выводятся в обратном
 * порядке с дополнением до ширины; у знака с дополнением нулями «−» идёт перед нулями, иначе — перед цифрами. */
void p2c_fmt_int(int32_t value, const P2cStr *spec) P2C_COLD {
    /* Поддержаны спецификации "" (десятичная), "0NX"/"NX" (шестнадцатеричная). */
    uint8_t digits[16];
    uint8_t count = 0;
    uint8_t width = 0;
    uint8_t pad = ' ';
    uint8_t base = 10;
    uint8_t upper = 1;
    uint8_t negative = 0;
    uint16_t position = 0;
    uint32_t magnitude;
    if (spec->length) {
        if (spec->data[0] == '0') { pad = '0'; position = 1; }
        while (position < spec->length && spec->data[position] >= '0' && spec->data[position] <= '9') {
            width = (uint8_t)(width * 10 + (spec->data[position] - '0'));
            position++;
        }
        if (position < spec->length) {
            uint8_t kind = spec->data[position];
            if (kind == 'X') base = 16;
            else if (kind == 'x') { base = 16; upper = 0; }
            else if (kind != 'd') p2c_raise(P2C_E_VALUE);
        }
    }
    /* Модуль без переполнения у INT32_MIN: −(value + 1) + 1. */
    if (value < 0) { negative = 1; magnitude = (uint32_t)(-(value + 1)) + 1; } else magnitude = (uint32_t)value;
    /* Старшие разряды — 32-битным делением, остаток до 65535 — 16-битным. */
    while (magnitude > 65535UL) {
        uint8_t digit = (uint8_t)(magnitude % base);
        digits[count++] = (uint8_t)(digit < 10 ? '0' + digit : (upper ? 'A' : 'a') + digit - 10);
        magnitude /= base;
    }
    {
        uint16_t small = (uint16_t)magnitude;
        do {
            uint8_t digit = (uint8_t)(small % base);
            digits[count++] = (uint8_t)(digit < 10 ? '0' + digit : (upper ? 'A' : 'a') + digit - 10);
            small /= base;
        } while (small);
    }
    if (negative) {
        if (pad == '0') {
            p2c_fmt_buffer[p2c_fmt_length++] = '-';
            if (width) width--;
        } else {
            digits[count++] = '-';
        }
    }
    while (count < width) { p2c_fmt_buffer[p2c_fmt_length++] = pad; width--; }
    while (count) p2c_fmt_buffer[p2c_fmt_length++] = digits[--count];
}

/* Готовая f-строка — новая строка в куче. */
const P2cStr *p2c_fmt_end(void) P2C_COLD {
    return p2c_str_make(p2c_fmt_buffer, p2c_fmt_length);
}

#endif /* P2C_COLD_PART */
