/* Реализация платформы ПК: отказы и команды вывода записываются для сверки. */
#include "py2c_platform.h"
#include "../py2c_runtime.h"

#define PY2C_HOST_BLITS 16384

int16_t py2c_host_fault_code;
uint32_t py2c_host_fault_count;
int32_t py2c_host_blit_log[PY2C_HOST_BLITS * 3];
uint32_t py2c_host_blit_count;

void py2c_raise(int16_t code) {
    if (py2c_host_fault_count == 0) py2c_host_fault_code = code;
    ++py2c_host_fault_count;
}

void py2c_blit(uint16_t image, int16_t x, int16_t y) {
    if (py2c_host_blit_count < PY2C_HOST_BLITS) {
        py2c_host_blit_log[py2c_host_blit_count * 3] = image;
        py2c_host_blit_log[py2c_host_blit_count * 3 + 1] = x;
        py2c_host_blit_log[py2c_host_blit_count * 3 + 2] = y;
    }
    ++py2c_host_blit_count;
}

PY2C_EXPORT void py2c_host_reset(void) {
    py2c_host_blit_count = 0;
}

PY2C_EXPORT uint32_t py2c_host_faults(void) { return py2c_host_fault_count; }
PY2C_EXPORT int32_t py2c_host_fault(void) { return py2c_host_fault_code; }
PY2C_EXPORT uint32_t py2c_host_blits(void) { return py2c_host_blit_count; }
PY2C_EXPORT int32_t *py2c_host_blit_data(void) { return py2c_host_blit_log; }
