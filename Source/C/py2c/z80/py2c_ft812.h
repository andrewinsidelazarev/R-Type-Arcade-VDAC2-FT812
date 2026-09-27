/* Аппаратный адаптер вывода FT812 для сгенерированного кода. */
#ifndef PY2C_FT812_H
#define PY2C_FT812_H

#include <stdint.h>

extern uint16_t py2c_dl_count;
extern uint16_t py2c_dl_bytes;
extern uint16_t py2c_dl_dropped;
extern uint16_t py2c_dl_skipped;
extern uint16_t py2c_dl_missing;
extern uint16_t py2c_dl_peak;

void py2c_frame_begin(void);
void py2c_frame_end(void);

#endif
