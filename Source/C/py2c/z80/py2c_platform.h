/* Платформа TS-Config для сгенерированного кода: окно 2, отказ, вывод FT812.
 * Проверки переполнения выключены; сгенерированный C сверен с CPython на ПК. */
#ifndef PY2C_PLATFORM_H
#define PY2C_PLATFORM_H

#include <stdint.h>

/* Регистр Page2 TS-Config в окне FMAPS (#0400 + номер регистра). */
#define PY2C_PAGE2_REGISTER (*(uint8_t *)0x0412)

extern uint8_t py2c_page2;
extern uint8_t py2c_fault;
extern int16_t py2c_fault_code;

/* Форма выражения: используется внутри PY2C_ELEM через оператор «запятая». */
#define PY2C_MAP(page) ((void)(((uint8_t)(page) != 0 && py2c_page2 != (uint8_t)(page)) \
    ? (PY2C_PAGE2_REGISTER = py2c_page2 = (uint8_t)(page)) : 0))

uint8_t py2c_z80_buf_read(const void *buffer, int32_t index);
void py2c_z80_buf_write(void *buffer, int32_t index, uint8_t value);
void py2c_page_copy(uint8_t destination, uint8_t source);

#define PY2C_BUF_READ(buffer, index) py2c_z80_buf_read((buffer), (index))
#define PY2C_BUF_WRITE(buffer, index, value) py2c_z80_buf_write((buffer), (index), (uint8_t)(value))

#endif
