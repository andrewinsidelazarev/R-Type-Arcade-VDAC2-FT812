/* Реализация общих функций сгенерированного кода (семантика целых Python, struct). */
#include "py2c_platform.h"
#include "py2c_runtime.h"

Py2cOptI32 py2c_some(int32_t value) {
    Py2cOptI32 result;
    result.value = value;
    result.present = 1;
    return result;
}

#ifdef PY2C_CHECKED
int16_t py2c_check_i16(int64_t value) {
    if (value < -32768 || value > 32767) py2c_raise(PY2C_E_WIDTH);
    return (int16_t)value;
}
uint16_t py2c_check_u16(int64_t value) {
    if (value < 0 || value > 65535) py2c_raise(PY2C_E_WIDTH);
    return (uint16_t)value;
}
int32_t py2c_check_i32(int64_t value) {
    if (value < INT32_MIN || value > INT32_MAX) py2c_raise(PY2C_E_OVERFLOW);
    return (int32_t)value;
}
uint8_t py2c_check_u8(int64_t value) {
    if (value < 0 || value > 255) py2c_raise(PY2C_E_WIDTH);
    return (uint8_t)value;
}
int8_t py2c_check_i8(int64_t value) {
    if (value < -128 || value > 127) py2c_raise(PY2C_E_WIDTH);
    return (int8_t)value;
}
void py2c_check_index(int64_t index, int64_t length) {
    if (index < 0 || index >= length) py2c_raise(PY2C_E_INDEX);
}
int32_t py2c_shl_checked(int32_t value, int32_t count) {
    if (count < 0) { py2c_raise(PY2C_E_SHIFT); return 0; }
    if (count > 31) { if (value) py2c_raise(PY2C_E_OVERFLOW); return 0; }
    return py2c_check_i32((int64_t)value * ((int64_t)1 << count));
}
#endif

int16_t py2c_min_i16(int16_t a, int16_t b) { return b < a ? b : a; }
uint16_t py2c_min_u16(uint16_t a, uint16_t b) { return b < a ? b : a; }
int32_t py2c_min_i32(int32_t a, int32_t b) { return b < a ? b : a; }
int16_t py2c_max_i16(int16_t a, int16_t b) { return b > a ? b : a; }
uint16_t py2c_max_u16(uint16_t a, uint16_t b) { return b > a ? b : a; }
int32_t py2c_max_i32(int32_t a, int32_t b) { return b > a ? b : a; }
int16_t py2c_abs_i16(int16_t a) { return a < 0 ? (int16_t)-a : a; }
uint16_t py2c_abs_u16(uint16_t a) { return a; }
int32_t py2c_abs_i32(int32_t a) { return a < 0 ? -a : a; }

/* Python >>: арифметический сдвиг, большие сдвиги дают 0 или -1. */
int32_t py2c_shr(int32_t value, int32_t count) {
    if (count < 0) { py2c_raise(PY2C_E_SHIFT); return 0; }
    if (count > 31) return value < 0 ? -1 : 0;
    return value >> count;
}

int32_t py2c_floordiv(int32_t a, int32_t b) {
    int32_t quotient;
    if (b == 0) { py2c_raise(PY2C_E_ZERODIV); return 0; }
    quotient = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) --quotient;
    return quotient;
}

int32_t py2c_mod(int32_t a, int32_t b) {
    int32_t remainder;
    if (b == 0) { py2c_raise(PY2C_E_ZERODIV); return 0; }
    remainder = a % b;
    if (remainder != 0 && ((remainder < 0) != (b < 0))) remainder += b;
    return remainder;
}

int32_t py2c_index(int32_t index, uint32_t length) {
    if (index < 0) index += (int32_t)length;
    if (index < 0 || (uint32_t)index >= length) { py2c_raise(PY2C_E_INDEX); return 0; }
    return index;
}

uint8_t py2c_buf_get(const Py2cBuffer *buffer, int32_t index) {
    index = PY2C_INDEX_NN(index, buffer->length);
    return PY2C_BUF_READ(buffer, index);
}

uint8_t py2c_buf_get_any(const Py2cBuffer *buffer, int32_t index) {
    index = py2c_index(index, buffer->length);
    return PY2C_BUF_READ(buffer, index);
}

void py2c_buf_set(Py2cBuffer *buffer, int32_t index, int32_t value) {
    if (value < 0 || value > 255) { py2c_raise(PY2C_E_OVERFLOW); return; }
    index = PY2C_INDEX_NN(index, buffer->length);
    PY2C_BUF_WRITE(buffer, index, value);
}

void py2c_buf_set_any(Py2cBuffer *buffer, int32_t index, int32_t value) {
    if (value < 0 || value > 255) { py2c_raise(PY2C_E_OVERFLOW); return; }
    index = py2c_index(index, buffer->length);
    PY2C_BUF_WRITE(buffer, index, value);
}

int32_t py2c_buf_require(const Py2cBuffer *buffer, int32_t offset, int32_t size) {
    if (offset < 0) offset += (int32_t)buffer->length;
    if (offset < 0 || (uint32_t)offset + (uint32_t)size > buffer->length) {
        py2c_raise(PY2C_E_STRUCT);
        return 0;
    }
    return offset;
}

int32_t py2c_buf_u16le_raw(const Py2cBuffer *buffer, int32_t offset) {
    uint16_t low = PY2C_BUF_READ(buffer, offset);
    uint16_t high = PY2C_BUF_READ(buffer, offset + 1);
    return (int32_t)(uint16_t)(low | (high << 8));
}

int32_t py2c_buf_i16le_raw(const Py2cBuffer *buffer, int32_t offset) {
    return (int32_t)(int16_t)py2c_buf_u16le_raw(buffer, offset);
}

int32_t py2c_buf_u8le_raw(const Py2cBuffer *buffer, int32_t offset) {
    return (int32_t)PY2C_BUF_READ(buffer, offset);
}

int32_t py2c_buf_i8le_raw(const Py2cBuffer *buffer, int32_t offset) {
    return (int32_t)(int8_t)PY2C_BUF_READ(buffer, offset);
}

int32_t py2c_buf_u16le(const Py2cBuffer *buffer, int32_t offset) {
    return py2c_buf_u16le_raw(buffer, py2c_buf_require(buffer, offset, 2));
}

int32_t py2c_buf_i16le(const Py2cBuffer *buffer, int32_t offset) {
    return py2c_buf_i16le_raw(buffer, py2c_buf_require(buffer, offset, 2));
}

int32_t py2c_buf_u8le(const Py2cBuffer *buffer, int32_t offset) {
    return py2c_buf_u8le_raw(buffer, py2c_buf_require(buffer, offset, 1));
}

int32_t py2c_buf_i8le(const Py2cBuffer *buffer, int32_t offset) {
    return py2c_buf_i8le_raw(buffer, py2c_buf_require(buffer, offset, 1));
}

void py2c_require_u16(int32_t value) {
    if (value < 0 || value > 65535L) py2c_raise(PY2C_E_STRUCT);
}

void py2c_require_i16(int32_t value) {
    if (value < -32768L || value > 32767) py2c_raise(PY2C_E_STRUCT);
}

void py2c_require_u8(int32_t value) {
    if (value < 0 || value > 255) py2c_raise(PY2C_E_STRUCT);
}

void py2c_require_i8(int32_t value) {
    if (value < -128 || value > 127) py2c_raise(PY2C_E_STRUCT);
}

void py2c_buf_set_u16le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value) {
    PY2C_BUF_WRITE(buffer, offset, value & 255);
    PY2C_BUF_WRITE(buffer, offset + 1, (value >> 8) & 255);
}

void py2c_buf_set_i16le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value) {
    py2c_buf_set_u16le_raw(buffer, offset, value & 65535L);
}

void py2c_buf_set_u8le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value) {
    PY2C_BUF_WRITE(buffer, offset, value & 255);
}

void py2c_buf_set_i8le_raw(Py2cBuffer *buffer, int32_t offset, int32_t value) {
    PY2C_BUF_WRITE(buffer, offset, value & 255);
}
