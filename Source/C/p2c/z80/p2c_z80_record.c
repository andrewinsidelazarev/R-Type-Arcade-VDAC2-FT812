/* Адаптер сверки для модели Z80: вместо FT812 и звука команды кадра пишутся
 * в страницы журнала, ввод задаёт модель. Используется только проверочной
 * сборкой, в SPG не входит.
 *
 * Страница P2C_Z80_LOG_PAGE: u16 число blit, записи (u16 изображение, i16 x, i16 y).
 * Страница P2C_Z80_LOG_PAGE2: #0000 — u16 число ячеек спрайтов и u32 ключи
 * (как у адаптера ПК), #3000 — u16 число звуковых команд и i16 команды,
 * #3400 — u16 число текстов и записи (u16 адрес строки, u32 цвет, u8 сглаживание). */
#include <string.h>
#include "p2c_runtime.h"
#include "p2c_z80_adapter.h"
#include "p2c_z80_config.h"

__sfr __banked __at(0x13AF) p2c_record_page3;

uint8_t p2c_z80_rec_start;       /* ввод кадра, который пишет модель: нажатие огня */
uint8_t p2c_z80_rec_bits;        /* и биты кнопок */
uint8_t p2c_z80_hook_count;      /* кадров, дошедших до точки останова */
static uint16_t p2c_rec_blits;   /* записей журнала кадра: выводов, ячеек спрайтов, звуков, текстов */
static uint16_t p2c_rec_cells;
static uint16_t p2c_rec_sounds;
static uint16_t p2c_rec_texts;

/* Точка останова модели: конец кадра (журнал заполнен, сборка мусора ещё не прошла). */
void p2c_z80_hook(void) {
    ++p2c_z80_hook_count;
}

/* size байт в страницу журнала page по смещению offset (окно #C000; затем возвращается банк кода). */
static void p2c_rec_write(uint8_t page, uint16_t offset, const void *data, uint8_t size) {
    p2c_record_page3 = page;
    memcpy((uint8_t *)(0xC000u + offset), data, size);
    p2c_record_page3 = p2c_bank;
}

void p2c_z80_adapter_init(void) {
}

/* Начало кадра: журналы пусты. */
void p2c_z80_frame_begin(void) {
    p2c_rec_blits = 0;
    p2c_rec_cells = 0;
    p2c_rec_sounds = 0;
    p2c_rec_texts = 0;
}

/* Конец кадра: числа записей — в заголовки журналов, затем точка останова модели. */
void p2c_z80_frame_end(void) {
    p2c_rec_write(P2C_Z80_LOG_PAGE, 0, &p2c_rec_blits, 2);
    p2c_rec_write(P2C_Z80_LOG_PAGE2, 0, &p2c_rec_cells, 2);
    p2c_rec_write(P2C_Z80_LOG_PAGE2, 0x3000u, &p2c_rec_sounds, 2);
    p2c_rec_write(P2C_Z80_LOG_PAGE2, 0x3400u, &p2c_rec_texts, 2);
    p2c_z80_hook();
}

void p2c_z80_input(uint8_t *start_pressed, uint8_t *input_bits) {
    *start_pressed = p2c_z80_rec_start;
    *input_bits = p2c_z80_rec_bits;
}

void p2c_z80_sound_frame(void) {
}

/* Запись вывода (6 байт: изображение, x, y — младшие 16 бит) после счётчика; не больше 2700 за кадр. */
static void p2c_rec_blit(uint16_t image, int32_t x, int32_t y) {
    uint8_t record[6];
    if (p2c_rec_blits >= 2700u) p2c_raise(P2C_E_MEMORY);
    record[0] = (uint8_t)image;
    record[1] = (uint8_t)(image >> 8);
    record[2] = (uint8_t)x;
    record[3] = (uint8_t)((uint32_t)x >> 8);
    record[4] = (uint8_t)y;
    record[5] = (uint8_t)((uint32_t)y >> 8);
    p2c_rec_write(P2C_Z80_LOG_PAGE, (uint16_t)(2u + p2c_rec_blits * 6u), record, 6);
    ++p2c_rec_blits;
}

void p2c_blit(P2cImage image, int32_t x, int32_t y) {
    p2c_rec_blit(image, x, y);
}

/* Заливка чёрным — вывод изображения #FFFF. */
void p2c_fill_black(void) {
    p2c_rec_blit(0xFFFFu, 0, 0);
}

int16_t p2c_target_get_width(void) {
    return 640;
}

int16_t p2c_target_get_height(void) {
    return 480;
}

/* Изображение текста: номер записи кадра #C000 | индекс. Запись (7 байт): адрес строки, цвет, сглаживание. */
P2cImage p2c_text_image(const P2cStr *text, uint8_t antialias, uint32_t color) {
    uint8_t record[7];
    if (p2c_rec_texts >= 64u) p2c_raise(P2C_E_MEMORY);
    record[0] = (uint8_t)(uint16_t)text;
    record[1] = (uint8_t)((uint16_t)text >> 8);
    memcpy(record + 2, &color, 4);
    record[6] = antialias;
    p2c_rec_write(P2C_Z80_LOG_PAGE2, (uint16_t)(0x3402u + p2c_rec_texts * 7u), record, 7);
    return (P2cImage)(0xC000u | p2c_rec_texts++);
}

/* Значение отладочной строки "DIST XXXX": 4 шестнадцатеричные цифры с позиции 5. */
static uint16_t p2c_rec_hex(const P2cStr *text) {
    uint16_t value = 0;
    uint8_t index;
    if (text->length != 9) p2c_raise(P2C_E_VALUE);
    for (index = 5; index < 9; index++) {
        uint8_t digit = text->data[index];
        digit = digit <= '9' ? (uint8_t)(digit - '0') : (uint8_t)(digit - 'A' + 10);
        value = (uint16_t)((value << 4) | digit);
    }
    return value;
}

/* Ширина отладочной строки шрифта pygame: таблица по значению (страница данных, полбайта на значение — как у
 * адаптера FT812). Строка берётся из записи текста кадра в журнале. */
int16_t p2c_image_get_width(P2cImage image) {
    uint8_t record[2];
    uint16_t value;
    uint8_t packed;
    const P2cStr *text;
    if ((image & 0xC000u) != 0xC000u) p2c_raise(P2C_E_VALUE);
    p2c_record_page3 = P2C_Z80_LOG_PAGE2;
    memcpy(record, (uint8_t *)(0xC000u + 0x3402u + (image & 0x3Fu) * 7u), 2);
    text = (const P2cStr *)(uint16_t)(record[0] | ((uint16_t)record[1] << 8));
    value = p2c_rec_hex(text);
    p2c_record_page3 = P2C_Z80_TEXT_WIDTH_PAGE + (uint8_t)(value >> 15);
    packed = *(uint8_t *)(0xC000u + ((value >> 1) & 0x3FFFu));
    p2c_record_page3 = p2c_bank;
    return (int16_t)(P2C_Z80_TEXT_WIDTH_BASE + ((value & 1u) ? (packed >> 4) : (packed & 15u)));
}

int16_t p2c_image_get_height(P2cImage image) {
    (void)image;
    return P2C_Z80_TEXT_HEIGHT;
}

/* Звуковая команда — в журнал (до 64 за кадр); старт музыки — команда −1. */
void p2c_sound_play(int32_t command) {
    uint8_t record[2];
    if (p2c_rec_sounds >= 64u) p2c_raise(P2C_E_MEMORY);
    record[0] = (uint8_t)command;
    record[1] = (uint8_t)((uint32_t)command >> 8);
    p2c_rec_write(P2C_Z80_LOG_PAGE2, (uint16_t)(0x3002u + p2c_rec_sounds * 2u), record, 2);
    ++p2c_rec_sounds;
}

void p2c_sound_start_music(void) {
    p2c_sound_play(-1);
}

/* Ячейка спрайта: ключ как у адаптера ПК, изображение — #8000 | индекс записи кадра. Ключ: бит 31 — ячейка, бит 30 —
 * типовой банк (p2c_z80_typed_banks), биты 16…23 — банк (тип ресурса или палитра), 2…13 — код, 1 — fx, 0 — fy. */
P2cImage p2c_sprite_cell(int32_t palette, int32_t resource_type, int32_t code, uint8_t flip_x, uint8_t flip_y) {
    uint32_t typed = (p2c_z80_typed_banks[(uint8_t)resource_type >> 3] >> ((uint8_t)resource_type & 7)) & 1u;
    uint32_t bank = typed ? (uint32_t)(resource_type & 255) : (uint32_t)(palette & 15);
    uint32_t key = 0x80000000UL | (typed << 30) | (bank << 16) | ((uint32_t)(code & 0x0FFF) << 2) |
                   ((uint32_t)flip_x << 1) | flip_y;
    if (p2c_rec_cells >= 1000u) p2c_raise(P2C_E_MEMORY);
    p2c_rec_write(P2C_Z80_LOG_PAGE2, (uint16_t)(2u + p2c_rec_cells * 4u), &key, 4);
    return (P2cImage)(0x8000u | p2c_rec_cells++);
}
