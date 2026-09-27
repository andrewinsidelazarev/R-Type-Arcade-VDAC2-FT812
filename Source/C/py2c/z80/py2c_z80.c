/* Реализация платформы TS-Config: страницы окна 2 и отказы. Логики игры нет. */
#include <string.h>
#include "py2c_platform.h"
#include "../py2c_runtime.h"

uint8_t py2c_page2;
uint8_t py2c_fault;
int16_t py2c_fault_code;
static uint8_t py2c_copy_chunk[256];

void py2c_raise(int16_t code) {
    if (!py2c_fault) {
        py2c_fault = 1;
        py2c_fault_code = code;
    }
}

/* Номер страницы многостраничного буфера: старшие биты индекса / 16 КБ. */
static uint8_t py2c_buffer_page(const Py2cBuffer *buffer, int32_t index) {
    return (uint8_t)(buffer->page + (uint8_t)((uint16_t)(index >> 16) << 2) +
                     (uint8_t)((uint16_t)index >> 14));
}

uint8_t py2c_z80_buf_read(const void *pointer, int32_t index) {
    const Py2cBuffer *buffer = (const Py2cBuffer *)pointer;
    uint8_t page;
    if (!buffer->page) return buffer->data[(uint16_t)index];
    page = py2c_buffer_page(buffer, index);
    PY2C_MAP(page);
    return *(uint8_t *)(0x8000u + ((uint16_t)index & 0x3FFFu));
}

void py2c_z80_buf_write(void *pointer, int32_t index, uint8_t value) {
    Py2cBuffer *buffer = (Py2cBuffer *)pointer;
    uint8_t page;
    if (!buffer->page) {
        buffer->data[(uint16_t)index] = value;
        return;
    }
    page = py2c_buffer_page(buffer, index);
    PY2C_MAP(page);
    *(uint8_t *)(0x8000u + ((uint16_t)index & 0x3FFFu)) = value;
}

/* Восстановить рабочую страницу из исходной копии через резидентный буфер. */
void py2c_page_copy(uint8_t destination, uint8_t source) {
    uint16_t offset;
    for (offset = 0; offset < 0x4000u; offset += 256u) {
        PY2C_MAP(source);
        memcpy(py2c_copy_chunk, (uint8_t *)(0x8000u + offset), 256);
        PY2C_MAP(destination);
        memcpy((uint8_t *)(0x8000u + offset), py2c_copy_chunk, 256);
    }
}
