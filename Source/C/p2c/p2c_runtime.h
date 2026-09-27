/* Общая часть кода транслятора p2c: семантика целых Python, куча со сборкой
 * мусора между кадрами, контейнеры (list, deque, dict, set, bytes), строки,
 * вызываемые значения. Платформа (host/ или z80/) задаёт p2c_platform.h:
 * размер кучи, ширину размеров и аппаратные адаптеры вывода, звука, ввода.
 *
 * Транслятор выбирает ширину каждой операции по доказанному интервалу. В
 * проверочной сборке (P2C_CHECKED) операции вычисляются в int64 и сверяются
 * с выбранной шириной, индексы и Optional проверяются: расхождение — отказ.
 *
 * Кто что пишет: этот заголовок и p2c_runtime.c — руками; функции программы
 * (bank_XX.c), структуры классов (P2cC_*), кортежей (P2cT*), Optional (P2cN*),
 * корни сборки (p2c_roots) и строки (p2c_str_N) — генератор (Source/Tools/p2c). */
#ifndef P2C_RUNTIME_H
#define P2C_RUNTIME_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "p2c_platform.h"

#ifndef P2C_NO_SETJMP
#include <setjmp.h>
#endif

/* Экспорт функции из DLL проверочной сборки на ПК; на Z80 — пусто. */
#ifndef P2C_EXPORT
#define P2C_EXPORT
#endif

/* Редкие функции рантайма: на Z80 лежат в банке кода и вызываются через трамплин. */
#ifndef P2C_COLD
#define P2C_COLD
#endif

/* --- коды отказов (исключения CPython) ------------------------------------ */
/* Код передаётся в p2c_raise; тексты для отладки — p2c_raise_messages (генератор). */
#define P2C_E_INDEX (-1)        /* IndexError: индекс вне длины */
#define P2C_E_OVERFLOW (-2)     /* результат не помещается в int32 */
#define P2C_E_ZERODIV (-3)      /* ZeroDivisionError */
#define P2C_E_STRUCT (-4)       /* struct.error: чтение/запись bytes вне границ или значения вне формата */
#define P2C_E_SHIFT (-5)        /* ValueError: отрицательный сдвиг */
#define P2C_E_WIDTH (-7)        /* значение вышло за ширину, выбранную транслятором (ошибка интервала) */
#define P2C_E_MEMORY (-8)       /* MemoryError: куча, пул страниц или буфер исчерпаны */
#define P2C_E_DISPATCH (-9)     /* вызов значения неизвестного номера (ошибка генератора) */
#define P2C_E_KEY (-10)         /* KeyError */
#define P2C_E_VALUE (-11)       /* ValueError */
#define P2C_E_NONE (-12)        /* обращение к None там, где ожидался объект */
#define P2C_E_EMPTY (-13)       /* min или max пустой последовательности */
#define P2C_E_STOP (-14)        /* next() исчерпанного итератора без значения по умолчанию */

/* На ПК отказ — longjmp в p2c_fault_jump (DLL возвращает код и место сверке); на Z80 код, адрес
 * возврата, SP и банк сохраняются в p2c_fault_*, бордюр — цвет 2, останов (p2c_z80_crt.s). */
#ifndef P2C_NO_SETJMP
extern jmp_buf p2c_fault_jump;
#endif
void p2c_raise(int16_t code);

/* Место исходника Python текущей инструкции: только в проверочной сборке.
 * n — номер строки в таблице мест модуля (генератор пишет рядом комментарий файл:строка). */
#ifdef P2C_CHECKED
extern uint16_t p2c_current_line;
#define P2C_LINE(n) (p2c_current_line = (n))
#else
#define P2C_LINE(n) ((void)0)
#endif

/* --- заголовки объектов кучи ------------------------------------------------ */
/* Служебные номера классов (классы программы — от 1, генератор). */
#define P2C_CLS_FREE 250        /* свободный кусок кучи (P2cFreeChunk) */
#define P2C_CLS_BLOCK 251       /* блок данных контейнера (без собственных ссылок) */
#define P2C_CLS_STR 252         /* строка, созданная во время работы */
#define P2C_CLS_BUF 253         /* bytes/bytearray */

/* Каждый объект кучи начинается с cls (номер класса) и gc (эпоха последней пометки:
 * объект жив, если gc равен текущей p2c_epoch после пометки).
 * page != 0: данные на странице окна #C000 (Z80), data — адрес внутри окна. */
typedef struct { uint8_t cls; uint8_t gc; } P2cObject;
/* list и неизменяемые массивы: length элементов из capacity в блоке data (элемент — sizeof C-типа). */
typedef struct { uint8_t cls; uint8_t gc; uint16_t length; uint16_t capacity; uint8_t *data; uint8_t page; } P2cList;
typedef P2cList P2cArray;
/* collections.deque — кольцо: первый элемент в слоте head, i-й — в (head + i) % capacity. */
typedef struct {
    uint8_t cls; uint8_t gc; uint16_t length; uint16_t capacity; uint16_t head; uint8_t *data; uint8_t page;
} P2cDeque;
/* dict и set в порядке вставки: записи 0…used − 1, live[i] = 0 — запись удалена; length — живых записей.
 * Ключи и значения — плоские массивы по key_size и value_size байт (у set value_size = 0). Поиск —
 * перебором с memcmp: словари программы маленькие. */
typedef struct {
    uint8_t cls; uint8_t gc;
    uint16_t length; uint16_t used; uint16_t capacity;
    uint8_t key_size; uint8_t value_size;
    uint8_t *live; uint8_t *keys; uint8_t *values;
} P2cDict;
typedef P2cDict P2cSet;
/* bytes/bytearray: размеры 32-битные (на Z80 крупный буфер занимает несколько страниц пула). */
typedef struct { uint8_t cls; uint8_t gc; uint32_t length; uint32_t capacity; uint8_t *data; uint8_t page; } P2cBuf;
/* Строка UTF-8 длиной length байт; постоянные строки программы лежат вне кучи (P2C_STR). */
typedef struct { uint8_t cls; uint8_t gc; uint16_t length; const uint8_t *data; } P2cStr;
/* Вызываемое значение: id — номер цели в таблице вызова генератора (0 — None), env — связанный
 * объект (self метода) или окружение замыкания. */
typedef struct { uint8_t id; void *env; } P2cFn;
/* pygame.Rect: x, y — левый верхний угол, w, h — размеры (могут быть отрицательными). */
typedef struct { int32_t x; int32_t y; int32_t w; int32_t h; } P2cRect;
/* Объект платформы (поверхность вывода, шрифт): программа передаёт его, не заглядывая внутрь. */
typedef uintptr_t P2cHandle;

#define P2C_CLS(object) (((P2cObject *)(object))->cls)
/* Постоянная строка программы номер number (p2c_str_N создаёт генератор). */
#define P2C_STR(number) (&p2c_str_##number)
/* Верхняя граница среза без явного конца (a[i:]). */
#define P2C_SLICE_END 0x7FFFFFFFL

/* Структуры не возвращаются из банковых функций (скрытый указатель SDCC): p2c_fn резидентна. */
P2cFn p2c_fn(uint8_t id, void *env);
extern const P2cFn p2c_fn_none;
#define P2C_FN_NONE p2c_fn_none
/* Запись вызываемого значения на место: номер цели и окружение. */
#define P2C_FN_SET(target, number, environment) ((target).id = (uint8_t)(number), (target).env = (void *)(environment))

/* --- целые -------------------------------------------------------------------- */
/* P2C_I16(a, op, b) — операция op в ширине int16 и т. д.: транслятор ставит ширину, в которую, по
 * интервалам, результат гарантированно помещается. P2C_TO_* — приведение к ширине места назначения.
 * В проверочной сборке всё считается в int64, выход за ширину — отказ P2C_E_WIDTH (интервал неверен);
 * в рабочей — обычная арифметика C нужной ширины. */
#ifdef P2C_CHECKED
int16_t p2c_check_i16(int64_t value);
uint16_t p2c_check_u16(int64_t value);
int32_t p2c_check_i32(int64_t value);
uint8_t p2c_check_u8(int64_t value);
int8_t p2c_check_i8(int64_t value);
#define P2C_I16(a, op, b) p2c_check_i16((int64_t)(a) op (int64_t)(b))
#define P2C_U16(a, op, b) p2c_check_u16((int64_t)(a) op (int64_t)(b))
#define P2C_I32(a, op, b) p2c_check_i32((int64_t)(a) op (int64_t)(b))
#define P2C_TO_U8(v) p2c_check_u8((int64_t)(v))
#define P2C_TO_I8(v) p2c_check_i8((int64_t)(v))
#define P2C_TO_U16(v) p2c_check_u16((int64_t)(v))
#define P2C_TO_I16(v) p2c_check_i16((int64_t)(v))
#define P2C_TO_I32(v) p2c_check_i32((int64_t)(v))
/* Сдвиг влево Python: значение не теряет старших битов (иначе отказ переполнения). */
int32_t p2c_shl_checked(int32_t value, int32_t count);
#define P2C_SHL(a, b) p2c_shl_checked((a), (b))
/* Элемент контейнера с проверкой None и границ (индекс уже приведён к неотрицательному). */
void *p2c_at_checked(const P2cList *list, int32_t index, size_t size);
#define P2C_AT(c, CT, i) (*(CT *)p2c_at_checked((const P2cList *)(c), (int32_t)(i), sizeof(CT)))
uint8_t *p2c_byte_checked(const P2cBuf *buffer, int32_t index);
#define P2C_BYTE(b, i) (*p2c_byte_checked((b), (int32_t)(i)))
void *p2c_deque_at_checked(const P2cDeque *deque, int32_t index, size_t size);
#define P2C_DEQUE_AT(q, CT, i) (*(CT *)p2c_deque_at_checked((q), (int32_t)(i), sizeof(CT)))
/* Значение Optional-структуры (P2cN*): has = 0 — None, отказ. */
uint8_t p2c_check_has(uint8_t has);
#define P2C_UNWRAP(x) ((void)p2c_check_has((x).has), (x).v)
#else
#define P2C_I16(a, op, b) ((int16_t)((int16_t)(a) op (int16_t)(b)))
#define P2C_U16(a, op, b) ((uint16_t)((uint16_t)(a) op (uint16_t)(b)))
#define P2C_I32(a, op, b) ((int32_t)((int32_t)(a) op (int32_t)(b)))
#define P2C_TO_U8(v) ((uint8_t)(v))
#define P2C_TO_I8(v) ((int8_t)(v))
#define P2C_TO_U16(v) ((uint16_t)(v))
#define P2C_TO_I16(v) ((int16_t)(v))
#define P2C_TO_I32(v) ((int32_t)(v))
/* Сдвиг через uint32: у отрицательного value сдвиг int32 влево — неопределённое поведение C. */
#define P2C_SHL(a, b) ((int32_t)((uint32_t)(a) << (b)))
/* Платформа может заменить доступ к элементам (Z80: данные на странице). */
#ifndef P2C_AT
#define P2C_AT(c, CT, i) (((CT *)(c)->data)[(i)])
#define P2C_BYTE(b, i) ((b)->data[(i)])
#define P2C_DEQUE_AT(q, CT, i) (((CT *)(q)->data)[((uint16_t)((q)->head + (i))) % (q)->capacity])
#endif
#define P2C_UNWRAP(x) ((x).v)
#endif

/* Индекс таблицы значений выражения (транслятор, fn_expr.tabulated): v из [lo, lo + n). Разность —
 * по модулю 256 или 65536: при v из интервала она равна v − lo. Проверочная сборка сверяет границы. */
#ifdef P2C_CHECKED
uint16_t p2c_check_table(int64_t offset, uint16_t count);
#define P2C_TAB_INDEX8(v, lo, n) p2c_check_table((int64_t)(v) - (int64_t)(lo), (n))
#define P2C_TAB_INDEX(v, lo, n) p2c_check_table((int64_t)(v) - (int64_t)(lo), (n))
#else
#define P2C_TAB_INDEX8(v, lo, n) ((uint8_t)((uint8_t)(v) - (uint8_t)(lo)))
#define P2C_TAB_INDEX(v, lo, n) ((uint16_t)((uint16_t)(v) - (uint16_t)(lo)))
#endif

/* Истинность Optional[контейнер]: не None и не пуст. */
#define P2C_TRUTH_OPT_LEN(x) ((x) != NULL && (x)->length != 0)

/* Запись элемента: отдельная форма, потому что на Z80 данные могут лежать на странице. */
#ifndef P2C_PUT
#define P2C_PUT(c, CT, i, v) (P2C_AT(c, CT, i) = (v))
#define P2C_DEQUE_PUT(q, CT, i, v) (P2C_DEQUE_AT(q, CT, i) = (v))
#define P2C_BYTE_PUT(b, i, v) (P2C_BYTE(b, i) = (v))
#endif

/* min, max, abs встроенных Python для ширины, выбранной транслятором. */
int16_t p2c_min_i16(int16_t a, int16_t b);
uint16_t p2c_min_u16(uint16_t a, uint16_t b);
int32_t p2c_min_i32(int32_t a, int32_t b);
int16_t p2c_max_i16(int16_t a, int16_t b);
uint16_t p2c_max_u16(uint16_t a, uint16_t b);
int32_t p2c_max_i32(int32_t a, int32_t b);
int16_t p2c_abs_i16(int16_t a);
uint16_t p2c_abs_u16(uint16_t a);
int32_t p2c_abs_i32(int32_t a);
/* value >> count Python: арифметический сдвиг, count > 31 — знак (−1 или 0), count < 0 — отказ. */
int32_t p2c_shr(int32_t value, int32_t count);
/* a // b и a % b Python: частное к минус бесконечности, остаток со знаком делителя. */
int32_t p2c_floordiv(int32_t a, int32_t b);
int32_t p2c_mod(int32_t a, int32_t b);
/* round(a / b) CPython для целых: округление к чётному при b > 0. */
int32_t p2c_round_div(int32_t a, int32_t b);
/* int.bit_count(): число единичных битов модуля значения. */
uint8_t p2c_bit_count(uint32_t value) P2C_COLD;
uint8_t p2c_bit_count_signed(int32_t value) P2C_COLD;
/* Индекс Python: отрицательный отсчитывается от конца, вне длины — отказ. */
int32_t p2c_index(int32_t index, uint32_t length);
#define P2C_INDEX(c, i) p2c_index((int32_t)(i), (uint32_t)(c)->length)

/* --- куча ----------------------------------------------------------------------- */
/* Кусок кучи: [размер P2cSize][объект]. Выделение — первый подходящий свободный кусок, иначе с вершины;
 * память выдаётся обнулённой. Сборка — пометка от корней (p2c_roots) и развёртка между кадрами. */
void p2c_heap_init(void);
/* Объект класса cls размером size байт (включая заголовок cls, gc). */
P2cObject *p2c_new_object(uint8_t cls, size_t size);
/* Блок данных контейнера: указатель на данные за заголовком блока. */
void *p2c_alloc_block(size_t size);
/* Временный блок на время операции (сортировка): живёт до ближайшей сборки. */
void *p2c_scratch(size_t size);
/* Пометка: объект — в стек пометки (дети обходятся потом), блок данных — сразу. */
void p2c_mark(P2cObject *object);
void p2c_mark_block(void *data);
/* Дети объекта по его классу — генератор (обход полей-ссылок). */
void p2c_mark_children(P2cObject *object);
/* Сборка мусора: вызывается между кадрами, когда стек C не держит ссылок на кучу. */
void p2c_collect(void) P2C_COLD;
extern P2cObject *const p2c_roots[];
extern const uint16_t p2c_root_count;
extern const char *const p2c_raise_messages[];
/* Диагностика: занятые байты сейчас и максимум; перепись по классам. */
size_t p2c_heap_used(void) P2C_COLD;
size_t p2c_heap_peak(void) P2C_COLD;
void p2c_heap_census(uint32_t *bytes_by_class) P2C_COLD;

/* --- списки ----------------------------------------------------------------------- */
/* size — байт на элемент (sizeof C-типа элемента), cls — номер класса контейнера для сборщика. */
P2cList *p2c_list_new(uint8_t cls, size_t size, uint16_t capacity);
/* Массив длиной length с обнулёнными элементами (заполняет вызывающий). */
P2cList *p2c_array_new(uint8_t cls, size_t size, uint16_t length);
/* Место под needed элементов: ёмкость удваивается (с 4), старые данные копируются в новый блок. */
void p2c_list_reserve(P2cList *list, size_t size, uint32_t needed);
/* append: указатель на новый последний элемент (значение пишет вызывающий — P2C_LIST_APPEND). */
void *p2c_list_push(P2cList *list, size_t size);
/* insert(index, v): указатель на освобождённое место; индекс — по правилам list.insert. */
void *p2c_list_insert_slot(P2cList *list, size_t size, int32_t index) P2C_COLD;
#define P2C_LIST_APPEND(l, CT, v) (*(CT *)p2c_list_push((P2cList *)(l), sizeof(CT)) = (v))
#define P2C_LIST_INSERT(l, CT, i, v) (*(CT *)p2c_list_insert_slot((P2cList *)(l), sizeof(CT), (i)) = (v))
void p2c_list_clear(P2cList *list);
/* del list[index:index + count] (индекс уже неотрицательный). */
void p2c_list_delete(P2cList *list, size_t size, int32_t index, uint16_t count) P2C_COLD;
/* del list[low:high] с правилами границ среза Python. */
void p2c_list_delete_slice(P2cList *list, size_t size, int32_t low, int32_t high) P2C_COLD;
/* list[low:high] — новый список (или массив) класса cls. */
P2cList *p2c_list_slice(uint8_t cls, const P2cList *list, size_t size, int32_t low, int32_t high) P2C_COLD;
P2cList *p2c_array_slice(uint8_t cls, const P2cList *list, size_t size, int32_t low, int32_t high) P2C_COLD;

/* deque: создание, append (указатель на место нового элемента), popleft, clear. */
P2cDeque *p2c_deque_new(uint8_t cls, size_t size, uint16_t capacity) P2C_COLD;
void *p2c_deque_push(P2cDeque *deque, size_t size) P2C_COLD;
#define P2C_DEQUE_PUSH(q, CT, v) (*(CT *)p2c_deque_push((q), sizeof(CT)) = (v))
void p2c_deque_popleft(P2cDeque *deque) P2C_COLD;
void p2c_deque_clear(P2cDeque *deque) P2C_COLD;

/* --- словари и множества: ключи сравниваются побайтно ------------------------------- */
P2cDict *p2c_dict_new(uint8_t cls, size_t key_size, size_t value_size, uint16_t capacity);
/* Номер живой записи с ключом key или −1. */
int32_t p2c_dict_find(const P2cDict *dict, const void *key);
/* d[key] = value (value = NULL — только ключ, у set); новая запись — в конец порядка вставки. */
void p2c_dict_set(P2cDict *dict, const void *key, const void *value);
/* del d[key]; ключа нет — ничего (KeyError проверяет сгенерированный код через p2c_dict_find). */
void p2c_dict_delete(P2cDict *dict, const void *key) P2C_COLD;
void p2c_dict_clear(P2cDict *dict) P2C_COLD;
/* Удвоение ёмкости с уплотнением: удалённые записи выбрасываются, порядок сохраняется. */
void p2c_dict_grow(P2cDict *dict) P2C_COLD;
/* Запись i: признак жизни, ключ типа KT, значение типа VT. */
#define P2C_DICT_LIVE(d, i) ((d)->live[(i)])
#define P2C_DICT_KEY(d, KT, i) (((KT *)(d)->keys)[(i)])
#define P2C_DICT_VALUE(d, KT, VT, i) (((VT *)(d)->values)[(i)])
#define P2C_SET_LIVE(d, i) ((d)->live[(i)])
#define P2C_SET_KEY(d, KT, i) (((KT *)(d)->keys)[(i)])

/* --- байты ---------------------------------------------------------------------------- */
/* bytes(size) / bytearray(size): обнулённый буфер (mutable_flag реализациями не используется). */
P2cBuf *p2c_buf_new(size_t size, uint8_t mutable_flag) P2C_COLD;
P2cBuf *p2c_buf_copy(const P2cBuf *source, uint8_t mutable_flag) P2C_COLD;
/* source[low:high] — новый буфер. */
P2cBuf *p2c_buf_slice(const P2cBuf *source, int32_t low, int32_t high, uint8_t mutable_flag) P2C_COLD;
/* bytearray.append(value): value 0…255, иначе отказ ValueError. */
void p2c_buf_append(P2cBuf *buffer, int32_t value) P2C_COLD;
/* target[:] = source. */
void p2c_buf_assign(P2cBuf *target, const P2cBuf *source) P2C_COLD;
uint8_t p2c_buf_eq(const P2cBuf *a, const P2cBuf *b) P2C_COLD;
/* Значение байта для записи: 0…255, иначе отказ ValueError. */
uint8_t p2c_byte_value(int32_t value);
/* Смещение struct.unpack_from/pack_into: отрицательное — от конца; size байт должны лежать в буфере. */
int32_t p2c_buf_require(const P2cBuf *buffer, int32_t offset, int32_t size);
/* Слова и байты little-endian в буфере по смещению o (формат struct '<H', '<h', '<B', '<b'). */
#ifndef P2C_BUF_U16LE
#define P2C_BUF_U16LE(b, o) ((uint16_t)((b)->data[(o)] | ((uint16_t)(b)->data[(o) + 1] << 8)))
#define P2C_BUF_I16LE(b, o) ((int16_t)P2C_BUF_U16LE((b), (o)))
#define P2C_BUF_U8LE(b, o) ((uint8_t)(b)->data[(o)])
#define P2C_BUF_I8LE(b, o) ((int8_t)(b)->data[(o)])
#define P2C_BUF_SET_U16LE(b, o, v) do { (b)->data[(o)] = (uint8_t)(v); \
    (b)->data[(o) + 1] = (uint8_t)((uint16_t)(v) >> 8); } while (0)
#define P2C_BUF_SET_I16LE(b, o, v) P2C_BUF_SET_U16LE((b), (o), (uint16_t)(v))
#define P2C_BUF_SET_U8LE(b, o, v) ((b)->data[(o)] = (uint8_t)(v))
#define P2C_BUF_SET_I8LE(b, o, v) ((b)->data[(o)] = (uint8_t)(v))
#endif
/* Диапазон значения для struct.pack: вне формата — отказ struct.error. */
void p2c_require_u16(int32_t value) P2C_COLD;
void p2c_require_i16(int32_t value) P2C_COLD;
void p2c_require_u8(int32_t value) P2C_COLD;
void p2c_require_i8(int32_t value) P2C_COLD;

/* --- строки ----------------------------------------------------------------------------- */
uint8_t p2c_str_eq(const P2cStr *a, const P2cStr *b);
/* text[index]: строка из одного символа (отрицательный индекс генератор уже пересчитал; вне длины — отказ). */
const P2cStr *p2c_str_char(const P2cStr *text, int32_t index);
const P2cStr *p2c_str_char_other(const uint8_t *data) P2C_COLD;
/* ord(text): код единственного символа. */
uint8_t p2c_ord(const P2cStr *text);
/* len(text.replace(old, "")) без создания строки. */
uint16_t p2c_str_len_without(const P2cStr *text, const P2cStr *old) P2C_COLD;
/* int(str): десятичное целое со знаком, пробелы по краям как в CPython. */
int32_t p2c_str_int(const P2cStr *text) P2C_COLD;
/* text.replace(old, replacement): результат до 512 байт. */
const P2cStr *p2c_str_replace(const P2cStr *text, const P2cStr *old, const P2cStr *replacement) P2C_COLD;
/* f-строка: p2c_fmt_begin, куски p2c_fmt_text и p2c_fmt_int (спецификация формата), p2c_fmt_end —
 * новая строка из общего буфера 256 байт. */
void p2c_fmt_begin(void) P2C_COLD;
void p2c_fmt_text(const P2cStr *text) P2C_COLD;
void p2c_fmt_int(int32_t value, const P2cStr *spec) P2C_COLD;
const P2cStr *p2c_fmt_end(void) P2C_COLD;

/* --- Rect pygame-ce ------------------------------------------------------------------------ */
/* Rect.colliderect: 1 — прямоугольники пересекаются. */
uint8_t p2c_rect_collide(P2cRect a, P2cRect b);

/* --- адаптеры платформы ----------------------------------------------------------------------- */
/* Вывод: изображение (номер или запись каталога) в логическую точку x, y экрана 640×480. */
void p2c_blit(P2cImage image, int32_t x, int32_t y);
void p2c_fill_black(void);
int16_t p2c_target_get_width(void);
int16_t p2c_target_get_height(void);
/* Font.render: изображение текста (на Z80 — запись таблицы текстов адаптера). */
P2cImage p2c_text_image(const P2cStr *text, uint8_t antialias, uint32_t color);
int16_t p2c_image_get_width(P2cImage image);
int16_t p2c_image_get_height(P2cImage image);
/* Звук: команда эффекта или мелодии и старт музыки. */
void p2c_sound_play(int32_t command);
void p2c_sound_start_music(void);
/* Ячейка спрайта M72: палитра, тип ресурса, код ячейки и отражения — изображение каталога. */
P2cImage p2c_sprite_cell(int32_t palette, int32_t resource_type, int32_t code, uint8_t flip_x, uint8_t flip_y);
/* Порт машины M72 цикла app.main полного runtime (p2c_entry_runtime.MachinePort). */
void p2c_port_boot(void);
/* Шаг машины: mask — кнопки игрока, start1/coin1 — импульсы, render — выводить ли кадр. */
void p2c_port_step(int32_t mask, uint8_t start1, uint8_t coin1, uint8_t render);
/* Мышь — координаты R-9: смещение мыши кадра (вход платформы) в позицию корабля до шага кадра игры. */
void p2c_port_mouse(void);
/* Слово рабочего ОЗУ машины: address — адрес V30 (#40000 + смещение), чтение состояния игры циклом main. */
int32_t p2c_port_word(int32_t address);
void p2c_port_show(void);
void p2c_port_reset_session(void);

#endif
