/* Общая часть сгенерированного транслятором кода: семантика целых Python,
 * страничные буферы и отказы. Платформа задаёт PY2C_MAP, чтение банков,
 * py2c_raise и py2c_blit (см. host/ и z80/ py2c_platform.h).
 *
 * Транслятор выбирает ширину каждой операции по доказанному интервалу
 * значений. В проверочной сборке (PY2C_CHECKED) каждая операция вычисляется
 * в int64 и сверяется с выбранной шириной: ошибка вывода диапазона — отказ. */
#ifndef PY2C_RUNTIME_H
#define PY2C_RUNTIME_H

#include <stdint.h>

#ifndef PY2C_EXPORT
#define PY2C_EXPORT
#endif

typedef struct { int32_t value; uint8_t present; } Py2cOptI32;
/* page == 0: данные резидентны, data указывает на них напрямую. */
typedef struct { uint8_t *data; uint32_t length; uint8_t page; } Py2cBuffer;

void py2c_raise(int16_t code);
void py2c_blit(uint16_t image, int16_t x, int16_t y);

#ifndef PY2C_BUF_READ
#define PY2C_BUF_READ(buffer, index) ((buffer)->data[(index)])
#endif
#ifndef PY2C_BUF_WRITE
#define PY2C_BUF_WRITE(buffer, index, value) ((buffer)->data[(index)] = (uint8_t)(value))
#endif
#ifndef PY2C_MAP
#define PY2C_MAP(page) ((void)(page))
#endif

/* Коды отказов, соответствующие исключениям CPython. */
#define PY2C_E_INDEX (-1)
#define PY2C_E_OVERFLOW (-2)
#define PY2C_E_ZERODIV (-3)
#define PY2C_E_STRUCT (-4)
#define PY2C_E_SHIFT (-5)
#define PY2C_E_CAPACITY (-6)
#define PY2C_E_WIDTH (-7)

Py2cOptI32 py2c_some(int32_t value);

#ifdef PY2C_CHECKED
/* Проверочная сборка: результат вне выбранной ширины — расхождение с анализом. */
int16_t py2c_check_i16(int64_t value);
uint16_t py2c_check_u16(int64_t value);
int32_t py2c_check_i32(int64_t value);
uint8_t py2c_check_u8(int64_t value);
int8_t py2c_check_i8(int64_t value);
void py2c_check_index(int64_t index, int64_t length);
#define PY2C_I16(a, op, b) py2c_check_i16((int64_t)(a) op (int64_t)(b))
#define PY2C_U16(a, op, b) py2c_check_u16((int64_t)(a) op (int64_t)(b))
#define PY2C_I32(a, op, b) py2c_check_i32((int64_t)(a) op (int64_t)(b))
#define PY2C_TO_U8(v) py2c_check_u8((int64_t)(v))
#define PY2C_TO_I8(v) py2c_check_i8((int64_t)(v))
#define PY2C_TO_U16(v) py2c_check_u16((int64_t)(v))
#define PY2C_TO_I16(v) py2c_check_i16((int64_t)(v))
#define PY2C_TO_I32(v) ((int32_t)(v))
#define PY2C_ELEM(c, i) ((c)->data[(py2c_check_index((int64_t)(i), (int64_t)(c)->length), (uint16_t)(i))])
#define PY2C_BUF_ELEM(b, i) ((b)->data[(py2c_check_index((int64_t)(i), (int64_t)(b)->length), (uint32_t)(i))])
#define PY2C_SHL(a, b) py2c_shl_checked((a), (b))
int32_t py2c_shl_checked(int32_t value, int32_t count);
#else
#define PY2C_I16(a, op, b) ((int16_t)((int16_t)(a) op (int16_t)(b)))
#define PY2C_U16(a, op, b) ((uint16_t)((uint16_t)(a) op (uint16_t)(b)))
#define PY2C_I32(a, op, b) ((int32_t)((int32_t)(a) op (int32_t)(b)))
#define PY2C_TO_U8(v) ((uint8_t)(v))
#define PY2C_TO_I8(v) ((int8_t)(v))
#define PY2C_TO_U16(v) ((uint16_t)(v))
#define PY2C_TO_I16(v) ((int16_t)(v))
#define PY2C_TO_I32(v) ((int32_t)(v))
/* Доказанный индекс: страница окна 2 и прямой доступ без проверки. */
#define PY2C_ELEM(c, i) (*(PY2C_MAP((c)->page), &(c)->data[(uint16_t)(i)]))
#define PY2C_BUF_ELEM(b, i) (*(PY2C_MAP((b)->page), &(b)->data[(uint16_t)(i)]))
#define PY2C_SHL(a, b) ((int32_t)((uint32_t)(a) << (b)))
#endif

/* struct с доказанным смещением внутри одной страницы. */
#define PY2C_BUF_U16LE(b, o) ((uint16_t)(PY2C_BUF_ELEM((b), (o)) | ((uint16_t)PY2C_BUF_ELEM((b), (o) + 1) << 8)))
#define PY2C_BUF_I16LE(b, o) ((int16_t)PY2C_BUF_U16LE((b), (o)))
#define PY2C_BUF_U8LE(b, o) ((uint8_t)PY2C_BUF_ELEM((b), (o)))
#define PY2C_BUF_I8LE(b, o) ((int8_t)PY2C_BUF_ELEM((b), (o)))
#define PY2C_BUF_SET_U16LE(b, o, v) do { PY2C_BUF_ELEM((b), (o)) = (uint8_t)(v); \
    PY2C_BUF_ELEM((b), (o) + 1) = (uint8_t)((uint16_t)(v) >> 8); } while (0)
#define PY2C_BUF_SET_I16LE(b, o, v) PY2C_BUF_SET_U16LE((b), (o), (uint16_t)(v))
#define PY2C_BUF_SET_U8LE(b, o, v) (PY2C_BUF_ELEM((b), (o)) = (uint8_t)(v))
#define PY2C_BUF_SET_I8LE(b, o, v) (PY2C_BUF_ELEM((b), (o)) = (uint8_t)(v))

int16_t py2c_min_i16(int16_t a, int16_t b);
uint16_t py2c_min_u16(uint16_t a, uint16_t b);
int32_t py2c_min_i32(int32_t a, int32_t b);
int16_t py2c_max_i16(int16_t a, int16_t b);
uint16_t py2c_max_u16(uint16_t a, uint16_t b);
int32_t py2c_max_i32(int32_t a, int32_t b);
int16_t py2c_abs_i16(int16_t a);
uint16_t py2c_abs_u16(uint16_t a);
int32_t py2c_abs_i32(int32_t a);

/* Python >>: арифметический сдвиг, большие сдвиги дают 0 или -1. */
int32_t py2c_shr(int32_t value, int32_t count);

/* Python //: округление к минус бесконечности. */
int32_t py2c_floordiv(int32_t a, int32_t b);

/* Python %: знак результата совпадает со знаком делителя. */
int32_t py2c_mod(int32_t a, int32_t b);

/* Индекс Python: отрицательный отсчитывается от конца, вне длины — отказ. */
int32_t py2c_index(int32_t index, uint32_t length);

#ifdef PY2C_CHECKED
#define PY2C_INDEX_NN(index, length) \
    (((uint32_t)(index) < (uint32_t)(length)) ? (index) : (py2c_raise(PY2C_E_INDEX), 0))
#else
#define PY2C_INDEX_NN(index, length) (index)
#endif

uint8_t py2c_buf_get(const Py2cBuffer *buffer, int32_t index);
uint8_t py2c_buf_get_any(const Py2cBuffer *buffer, int32_t index);
void py2c_buf_set(Py2cBuffer *buffer, int32_t index, int32_t value);
void py2c_buf_set_any(Py2cBuffer *buffer, int32_t index, int32_t value);

/* struct: смещение как в CPython (отрицательное — от конца), затем проверка. */
int32_t py2c_buf_require(const Py2cBuffer *buffer, int32_t offset, int32_t size);
int32_t py2c_buf_u16le_raw(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_i16le_raw(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_u8le_raw(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_i8le_raw(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_u16le(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_i16le(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_u8le(const Py2cBuffer *buffer, int32_t offset);
int32_t py2c_buf_i8le(const Py2cBuffer *buffer, int32_t offset);
void py2c_require_u16(int32_t value);
void py2c_require_i16(int32_t value);
void py2c_require_u8(int32_t value);
void py2c_require_i8(int32_t value);
void py2c_buf_set_u16le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value);
void py2c_buf_set_i16le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value);
void py2c_buf_set_u8le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value);
void py2c_buf_set_i8le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value);

#endif
