/* Аппаратный адаптер вывода: blit(image, x, y) сгенерированного кода → display list FT812.
 *
 * Номер изображения в сборке Z80 кодирует сразу команду FT812:
 * биты 8..12 — BITMAP_HANDLE атласа в RAM_G, биты 0..6 — CELL, бит 14 —
 * сплошной непрозрачный чёрный глиф, бит 15 — изображение не загружено.
 * Логический экран 640×480 выводится аппаратным масштабом 8/5 (матрица A=E=160).
 * Вершины идут в 1/8 физического пикселя; весь кадр сдвинут VERTEX_TRANSLATE_X
 * на -32 px, чтобы левая частично видимая колонка не давала отрицательных X.
 * Байты VERTEX2F берутся из таблиц по логическим X и Y без арифметики.
 * Сплошной чёрный глиф, выводимый до первого нечёрного пикселя кадра,
 * пропускается: он ложится на ту же чёрную заливку и картинку не меняет. */
#include "py2c_platform.h"
#include "../py2c_runtime.h"
#include "py2c_ft812.h"
#include "py2c_stage_resources.h"

#define PY2C_DL ((uint8_t *)0x1000)
/* Предел тайлов оставляет место END и DISPLAY (2040 команд из 2048). */
#define PY2C_DL_END ((uint8_t *)0x1000 + 2040u * 4u)

uint16_t py2c_dl_count;
uint16_t py2c_dl_bytes;
uint16_t py2c_dl_dropped;
uint16_t py2c_dl_skipped;
uint16_t py2c_dl_missing;
uint16_t py2c_dl_peak;
static uint8_t *py2c_dl_cursor;
static uint8_t py2c_handle_now;
static uint8_t py2c_cell_now;
static uint8_t py2c_colored;

static void py2c_dl_long(uint32_t word) {
    if (py2c_dl_cursor >= PY2C_DL_END) {
        ++py2c_dl_dropped;
        return;
    }
    py2c_dl_cursor[0] = (uint8_t)word;
    py2c_dl_cursor[1] = (uint8_t)(word >> 8);
    py2c_dl_cursor[2] = (uint8_t)(word >> 16);
    py2c_dl_cursor[3] = (uint8_t)(word >> 24);
    py2c_dl_cursor += 4;
}

void py2c_frame_begin(void) {
    uint8_t handle;
    const uint32_t *setup;
    py2c_dl_cursor = PY2C_DL;
    py2c_dl_dropped = 0;
    py2c_dl_skipped = 0;
    py2c_dl_missing = 0;
    py2c_dl_long(0x02000000UL);   /* CLEAR_COLOR_RGB 0,0,0 */
    py2c_dl_long(0x26000007UL);   /* CLEAR 1,1,1 */
    py2c_dl_long(0x27000003UL);   /* VERTEX_FORMAT 3 */
    py2c_dl_long(0x04FFFFFFUL);   /* COLOR_RGB 255,255,255 */
    py2c_dl_long(0x100000FFUL);   /* COLOR_A 255 */
    py2c_dl_long(0x0B000014UL);   /* BLEND_FUNC SRC_ALPHA, ONE_MINUS_SRC_ALPHA */
    py2c_dl_long(0x150000A0UL);   /* BITMAP_TRANSFORM_A 160: масштаб 8/5 */
    py2c_dl_long(0x16000000UL);
    py2c_dl_long(0x17000000UL);
    py2c_dl_long(0x18000000UL);
    py2c_dl_long(0x190000A0UL);   /* BITMAP_TRANSFORM_E 160 */
    py2c_dl_long(0x1A000000UL);
    py2c_dl_long(0x2B01FE00UL);   /* VERTEX_TRANSLATE_X -32 px */
    py2c_dl_long(0x1F000001UL);   /* BEGIN BITMAPS */
    setup = py2c_handle_setup;
    for (handle = 0; handle < PY2C_HANDLE_COUNT; ++handle) {
        py2c_dl_long(0x05000000UL | handle);
        py2c_dl_long(setup[0]);
        py2c_dl_long(setup[1]);
        py2c_dl_long(setup[2]);
        py2c_dl_long(setup[3]);
        py2c_dl_long(setup[4]);
        setup += 5;
    }
    py2c_handle_now = 0xFF;
    py2c_cell_now = 0xFF;
    py2c_colored = 0;
}

void py2c_blit(uint16_t image, int16_t x, int16_t y) {
    uint8_t handle;
    uint8_t cell;
    const uint8_t *xb;
    const uint8_t *yb;
    uint8_t *cursor;
    if (image & 0x8000u) {
        ++py2c_dl_missing;
        return;
    }
    if (!py2c_colored) {
        if (image & 0x4000u) {
            ++py2c_dl_skipped;
            return;
        }
        py2c_colored = 1;
    }
    if (x < -16 || x >= 704 || y < 0 || y >= 480) {
        /* Вне таблиц координат изображение за краем экрана целиком. */
        ++py2c_dl_missing;
        return;
    }
    cursor = py2c_dl_cursor;
    if (cursor + 12 > PY2C_DL_END) {
        ++py2c_dl_dropped;
        return;
    }
    handle = (uint8_t)(image >> 8) & 0x1F;
    cell = (uint8_t)image & 0x7F;
    if (handle != py2c_handle_now) {
        cursor[0] = handle; cursor[1] = 0; cursor[2] = 0; cursor[3] = 0x05;   /* BITMAP_HANDLE */
        cursor += 4;
        py2c_handle_now = handle;
        py2c_cell_now = 0xFF;
    }
    if (cell != py2c_cell_now) {
        cursor[0] = cell; cursor[1] = 0; cursor[2] = 0; cursor[3] = 0x06;     /* CELL */
        cursor += 4;
        py2c_cell_now = cell;
    }
    /* VERTEX2F: байты 3..2 и бит 7 байта 1 — из таблицы X, остальное — из таблицы Y. */
    xb = py2c_x_bytes + (uint16_t)(x + 16) * 3;
    yb = py2c_y_bytes + (uint16_t)y * 2;
    cursor[0] = yb[1];
    cursor[1] = (uint8_t)(yb[0] | xb[2]);
    cursor[2] = xb[1];
    cursor[3] = xb[0];
    py2c_dl_cursor = cursor + 4;
}

void py2c_frame_end(void) {
    uint8_t *cursor = py2c_dl_cursor;
    cursor[0] = 0; cursor[1] = 0; cursor[2] = 0; cursor[3] = 0x21;   /* END */
    cursor[4] = 0; cursor[5] = 0; cursor[6] = 0; cursor[7] = 0;      /* DISPLAY */
    py2c_dl_cursor = cursor + 8;
    py2c_dl_bytes = (uint16_t)(py2c_dl_cursor - PY2C_DL);
    py2c_dl_count = py2c_dl_bytes >> 2;
    if (py2c_dl_count > py2c_dl_peak) py2c_dl_peak = py2c_dl_count;
}
