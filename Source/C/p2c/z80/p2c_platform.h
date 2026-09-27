/* Платформа TS-Config (Z80, SDCC) для кода транслятора p2c.
 *
 * Раскладка окон: #0000 — резидентный код и стек, #4000–#BFFF — глобальные
 * данные рантайма, начальное состояние объектов и куча, #C000 — банк кода.
 * Крупные неизменяемые массивы и буферы bytes лежат на страницах: читаются и
 * пишутся резидентными функциями, которые на время доступа ставят страницу
 * данных в окно #C000 и возвращают банк вызывающего кода.
 *
 * Проверки переполнения выключены: сгенерированный C сверен с CPython на ПК. */
#ifndef P2C_PLATFORM_H
#define P2C_PLATFORM_H

#include <stdint.h>

#define P2C_NO_SETJMP 1
#define P2C_COLD __banked
#define P2C_ROUND(x) (x)
typedef uint16_t P2cSize;
typedef uint16_t P2cImage;

/* Куча между концом начального состояния и концом окна #8000 (символы компоновки). */
extern uint8_t p2c_z80_heap_base;
extern uint8_t p2c_z80_heap_limit;
#define P2C_HEAP_BASE (&p2c_z80_heap_base)
#define P2C_HEAP_LIMIT (&p2c_z80_heap_limit)
#define P2C_MARK_STACK 96

/* Окно, в котором видны страницы данных (адрес data страничного контейнера). */
#define P2C_Z80_WINDOW 0xC000u

extern uint8_t p2c_bank;

/* Доступ к элементам. Резидентный контейнер читается на месте (подставляемый код),
 * страничный — функцией платформы. Выражения контейнера и индекса вычисляются
 * повторно: генератор выносит вызовы с побочным действием во временные. */
void *p2c_z80_at_paged(const void *list, uint16_t index, uint8_t size);
void p2c_z80_put_paged(const void *list, uint16_t index, const void *value, uint8_t size);
uint8_t p2c_z80_byte_paged(const void *buffer, int32_t index);
void p2c_z80_byte_put_paged(const void *buffer, int32_t index, uint8_t value);
uint16_t p2c_z80_buf_u16(const void *buffer, int32_t offset);
void p2c_z80_buf_set_u16(void *buffer, int32_t offset, uint16_t value);
uint8_t p2c_z80_byte(const void *buffer, int32_t index);
void p2c_z80_byte_put(void *buffer, int32_t index, uint8_t value);
void p2c_z80_copy_out(const uint8_t *data, uint8_t page, uint32_t offset, uint8_t *target, uint16_t count);
void p2c_z80_buf_release(void *buffer);
void p2c_z80_physical_read(uint8_t page, uint16_t within, uint8_t *target, uint16_t count);
void p2c_z80_physical_write(uint8_t page, uint16_t within, const uint8_t *source, uint16_t count);

#define P2C_AT(c, CT, i) (*((c)->page ? (CT *)p2c_z80_at_paged((c), (uint16_t)(i), (uint8_t)sizeof(CT)) \
    : ((CT *)(c)->data + (uint16_t)(i))))
#define P2C_BYTE(b, i) ((b)->page ? p2c_z80_byte_paged((b), (int32_t)(i)) : (b)->data[(uint16_t)(i)])
#define P2C_DEQUE_AT(q, CT, i) (((CT *)(q)->data)[((uint16_t)((q)->head + (i))) % (q)->capacity])
#define P2C_PUT(c, CT, i, v) do { CT p2c_put_v = (v); \
    if ((c)->page) p2c_z80_put_paged((c), (uint16_t)(i), &p2c_put_v, (uint8_t)sizeof(CT)); \
    else ((CT *)(c)->data)[(uint16_t)(i)] = p2c_put_v; } while (0)
#define P2C_DEQUE_PUT(q, CT, i, v) (P2C_DEQUE_AT(q, CT, i) = (v))
#define P2C_BYTE_PUT(b, i, v) do { uint8_t p2c_put_b = (uint8_t)(v); \
    if ((b)->page) p2c_z80_byte_put_paged((b), (int32_t)(i), p2c_put_b); \
    else (b)->data[(uint16_t)(i)] = p2c_put_b; } while (0)

#define P2C_BUF_U16LE(b, o) p2c_z80_buf_u16((const void *)(b), (int32_t)(o))
#define P2C_BUF_I16LE(b, o) ((int16_t)p2c_z80_buf_u16((const void *)(b), (int32_t)(o)))
#define P2C_BUF_U8LE(b, o) P2C_BYTE(b, o)
#define P2C_BUF_I8LE(b, o) ((int8_t)P2C_BYTE(b, o))
#define P2C_BUF_SET_U16LE(b, o, v) p2c_z80_buf_set_u16((void *)(b), (int32_t)(o), (uint16_t)(v))
#define P2C_BUF_SET_I16LE(b, o, v) p2c_z80_buf_set_u16((void *)(b), (int32_t)(o), (uint16_t)(v))
#define P2C_BUF_SET_U8LE(b, o, v) P2C_BYTE_PUT(b, o, v)
#define P2C_BUF_SET_I8LE(b, o, v) P2C_BYTE_PUT(b, o, v)

/* Буферы bytes и срезы списков реализует платформа (страницы данных). */
#define P2C_PLATFORM_BUFFERS 1
#define P2C_LIST_COPY_OUT(list, offset, target, count) \
    p2c_z80_copy_out((list)->data, (list)->page, (uint32_t)(offset), (uint8_t *)(target), (uint16_t)(count))
#define P2C_SWEEP_FREE(object) \
    do { if ((object)->cls == P2C_CLS_BUF) p2c_z80_buf_release(object); } while (0)

#endif
