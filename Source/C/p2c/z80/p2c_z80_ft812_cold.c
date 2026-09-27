/* Аппаратный адаптер VDAC2 (FT812), банковая часть: загрузка изображений в RAM_G
 * (CMD_INFLATE), вытеснение слотов, начало и конец кадра, ввод, отладочный текст.
 *
 * Отступление на аппаратном пределе: отладочная строка рисуется глифами шрифта
 * pygame с шагом символов из метрик шрифта, без кернинга. Ввод отдельной сборки p2c_z80.py
 * (p2c_ft_input) — клавиатура ZX (стрелки как Caps Shift+5..8, QAOP; огонь — Space, Enter),
 * Kempston-джойстик (бит 4 — огонь, бит 5 — Force), кнопки Kempston-мыши (левая — огонь, правая —
 * Force) и правый Alt (Force).
 * Код банка исполняется в окне #C000, поэтому страницы каталога читаются и пишутся
 * только резидентными функциями p2c_z80_physical_read/write. */
#include <string.h>
#include "p2c_z80_adapter.h"
#include "p2c_z80_ft812.h"

__sfr __at(0x57) p2c_cold_spi_data;
__sfr __at(0x77) p2c_cold_spi_ctrl;
__sfr __at(0x1F) p2c_port_kempston;
__sfr __banked __at(0x7FFE) p2c_port_keys_7ffe;
__sfr __banked __at(0xBFFE) p2c_port_keys_bffe;
__sfr __banked __at(0xDFFE) p2c_port_keys_dffe;
__sfr __banked __at(0xFBFE) p2c_port_keys_fbfe;
__sfr __banked __at(0xFDFE) p2c_port_keys_fdfe;
__sfr __banked __at(0xEFFE) p2c_port_keys_effe;
__sfr __banked __at(0xF7FE) p2c_port_keys_f7fe;
__sfr __banked __at(0xFEFE) p2c_port_keys_fefe;
__sfr __banked __at(0xEFF7) p2c_port_gluk_enable;    /* Mr.Gluk ZX Evolution: #80 — регистры открыты */
__sfr __banked __at(0xDFF7) p2c_port_gluk_register;  /* номер регистра */
__sfr __banked __at(0xBFF7) p2c_port_gluk_data;      /* данные регистра */
__sfr __banked __at(0xFADF) p2c_port_mouse_buttons;  /* Kempston-мышь: бит 0 — левая, бит 1 — правая (0 — нажата) */

/* Скан-кодов PS/2 за кадр не больше (очередь с мусором не должна подвешивать кадр). */
#define P2C_PS2_DRAIN 24

static uint8_t p2c_ps2_ready;        /* очередь скан-кодов включена */
static uint8_t p2c_ps2_break;        /* был префикс отпускания F0 */
static uint8_t p2c_ps2_extended;     /* был префикс E0 */
static uint8_t p2c_ps2_altgr;        /* правый Alt нажат */

/* Ждать, пока сопроцессор FT812 исполнит всю очередь (свободно 4092 байта), и снять признак загрузки. */
void p2c_ft_wait_idle(void) __banked {
    while (p2c_ft_read16(FT_REG_CMDB_SPACE) != 4092u) {
    }
    p2c_ft_uploading = 0;
}

/* Команда CMD_INFLATE и сжатые данные текущей записи в очередь сопроцессора кусками по 4 байта.
 * Данные копируются со страниц каталога резидентной p2c_z80_physical_read.
 * Слово команды #FFFFFF22, адрес приёмника (4 байта), затем данные записи; кусок буфера на стеке (256 байт)
 * набирается со страниц каталога (переход через конец страницы — на следующую), в очередь уходит его часть,
 * кратная 4 (когда свободного места хватает); последний кусок дополняется нулями до кратного 4. Сначала — показ
 * прошлого списка (p2c_ft_wait_swap): слот вытесняется, если не выводился в этом и прошлом кадре. */
void p2c_ft_upload(uint32_t address) __banked {
    uint8_t chunk[256];
    uint16_t left = p2c_ft_entry.clen;
    uint16_t within = p2c_ft_entry.offset;
    uint8_t page = p2c_ft_entry.page;
    uint16_t pending = 8;
    uint16_t take;
    uint16_t index;
    p2c_ft_wait_swap();
    chunk[0] = 0x22; chunk[1] = 0xFF; chunk[2] = 0xFF; chunk[3] = 0xFF;
    chunk[4] = (uint8_t)address; chunk[5] = (uint8_t)(address >> 8);
    chunk[6] = (uint8_t)(address >> 16); chunk[7] = 0;
    ++p2c_ft_uploads;
    p2c_ft_uploading = 1;
    for (;;) {
        while (pending < sizeof chunk && left) {
            take = (uint16_t)(sizeof chunk - pending);
            if (take > left) take = left;
            if (take > 0x4000u - within) take = 0x4000u - within;
            p2c_z80_physical_read(page, within, chunk + pending, take);
            pending += take;
            left -= take;
            within += take;
            if (within == 0x4000u) {
                within = 0;
                ++page;
            }
        }
        if (!left) {
            while (pending & 3u) chunk[pending++] = 0;
        }
        take = pending & ~3u;
        if (!take) break;
        while (p2c_ft_read16(FT_REG_CMDB_SPACE) < take) {
        }
        p2c_ft_address(FT_REG_CMDB_WRITE, 1);
        for (index = 0; index < take; ++index) p2c_cold_spi_data = chunk[index];
        p2c_cold_spi_ctrl = FT_CS_OFF;
        memmove(chunk, chunk + take, pending - take);
        pending -= take;
        if (!left && !pending) break;
    }
}

/* Таблица владельцев слотов (страница P2C_FT_SLOT_PAGE): слово — номер записи каталога, #FFFF — слот свободен. */
static uint16_t p2c_ft_slot_entry(uint16_t offset) {
    uint16_t value;
    p2c_z80_physical_read(P2C_FT_SLOT_PAGE, offset, (uint8_t *)&value, 2);
    return value;
}

static void p2c_ft_set_slot_entry(uint16_t offset, uint16_t value) {
    p2c_z80_physical_write(P2C_FT_SLOT_PAGE, offset, (const uint8_t *)&value, 2);
}

/* Слот класса A или B: свободный или не выводившийся ни в этом кадре, ни в показанном сейчас
 * (иначе показанный кадр до DLSWAP видел бы в слоте новое изображение); поиск по кругу.
 * Стрелка класса (p2c_ft_hand_a/b) идёт по слотам; у занятого слота прежняя запись каталога теряет загрузку
 * (state = 0), слот получает текущую запись. Возврат — слот + 1; 0 — все слоты выводились в двух последних кадрах. */
uint16_t p2c_ft_take_slot(uint8_t cls) __banked {
    uint16_t *hand = cls ? &p2c_ft_hand_b : &p2c_ft_hand_a;
    uint16_t slots = cls ? P2C_FT_B_SLOTS : P2C_FT_A_SLOTS;
    uint16_t table = cls ? 0x2000u : 0u;
    uint16_t tries;
    P2cFtEntry saved = p2c_ft_entry;
    uint16_t saved_index = p2c_ft_entry_index;
    for (tries = 0; tries < slots; ++tries) {
        uint16_t slot = *hand;
        uint16_t owner = p2c_ft_slot_entry((uint16_t)(table + (slot << 1)));
        *hand = (uint16_t)(slot + 1u == slots ? 0u : slot + 1u);
        if (owner != 0xFFFFu) {
            p2c_ft_read_entry(owner);
            if ((uint8_t)(p2c_ft_frame - p2c_ft_entry.used) < 2u) continue;
            p2c_ft_entry.state[0] = 0;
            p2c_ft_entry.state[1] = 0;
            p2c_ft_write_state();
        }
        p2c_ft_entry = saved;
        p2c_ft_entry_index = saved_index;
        p2c_ft_set_slot_entry((uint16_t)(table + (slot << 1)), saved_index);
        return (uint16_t)(slot + 1u);
    }
    p2c_ft_entry = saved;
    p2c_ft_entry_index = saved_index;
    return 0;
}

/* Отладочная строка: глифы по порядку символов с шагом из метрик шрифта. Глиф символа — запись каталога из таблицы
 * (код − 32)·2 + black (белый или чёрный вариант); 0 — глифа нет (пробел), шаг всё равно прибавляется. */
void p2c_ft_draw_text(uint8_t record, int32_t x, int32_t y) __banked {
    P2cFtText *text = &p2c_ft_texts[record];
    uint16_t position;
    int32_t cursor = x;
    for (position = 0; position < text->text->length; ++position) {
        uint8_t code = text->text->data[position];
        uint16_t index;
        if (code < 32 || code > 127) continue;
        index = p2c_ft_text_glyphs[((code - 32u) << 1) | text->black];
        if (index) p2c_ft_draw_entry(index, cursor, y);
        cursor += p2c_ft_text_advance[code - 32u];
    }
}

/* Handle слотов класса: источник, BITMAP_LAYOUT ARGB4 (шаг строки 2·w, высота h) и BITMAP_SIZE
 * (w·8 + 4) / 5 × (h·8 + 4) / 5 — размеры постоянные, слова считаются при компиляции. */
#define P2C_FT_LAYOUT(w, h) (0x07000000UL | (6UL << 19) | ((((uint32_t)(w) << 1) & 1023u) << 9) | ((h) & 511u))
#define P2C_FT_LAYOUT_H(w, h) (0x28000000UL | ((((uint32_t)(w) << 1) >> 10) << 2) | ((uint32_t)(h) >> 9))
#define P2C_FT_SIZE(w, h) (0x08000000UL | (((((uint32_t)(w) * 8u + 4u) / 5u) & 511u) << 9) | \
                           ((((uint32_t)(h) * 8u + 4u) / 5u) & 511u))
#define P2C_FT_SIZE_H(w, h) (0x29000000UL | (((((uint32_t)(w) * 8u + 4u) / 5u) >> 9) << 2) | \
                             (((uint32_t)(h) * 8u + 4u) / 5u >> 9))

/* count handle подряд с first: у каждого — BITMAP_HANDLE, BITMAP_SOURCE (source, затем + step: 128 слотов на handle),
 * LAYOUT, LAYOUT_H, SIZE, SIZE_H. */
static void p2c_ft_handles(uint8_t first, uint8_t count, uint32_t source, uint32_t step, uint32_t layout,
                           uint32_t layout_h, uint32_t size, uint32_t size_h) {
    uint8_t handle;
    for (handle = first; handle < (uint8_t)(first + count); ++handle) {
        p2c_dl(0x05000000UL | handle);
        p2c_dl(0x01000000UL | source);
        p2c_dl(layout);
        p2c_dl(layout_h);
        p2c_dl(size);
        p2c_dl(size_h);
        source += step;
    }
}

void p2c_ft_init(void) __banked {
    uint8_t empty[256];
    uint16_t offset;
    /* Адрес 0 в записи означает «не загружено», поэтому область C начинается с 4. */
    p2c_ft_c_next = P2C_FT_C_BASE + 4u;
    /* Таблица слотов: #FFFF — свободен (слоты A с #0000, B с #2000). */
    memset(empty, 0xFF, sizeof empty);
    for (offset = 0; offset < 0x4000u; offset += sizeof empty) {
        p2c_z80_physical_write(P2C_FT_SLOT_PAGE, offset, empty, sizeof empty);
    }
}

/* Слоты и адреса загрузки недействительны (RAM_G занимал чужой вывод): записи каталога без
 * загруженных изображений, таблицы слотов и область C — пустые. */
void p2c_ft_reset(void) __banked {
    uint16_t index;
    uint8_t zero[4];
    memset(zero, 0, sizeof zero);
    for (index = 1; index < P2C_FT_ENTRIES; ++index) {
        p2c_z80_physical_write((uint8_t)(P2C_FT_ENTRY_PAGE + (index >> 10)),
                               (uint16_t)(((index & 1023u) << 4) + 12u), zero, 4);
    }
    p2c_ft_hand_a = 0;
    p2c_ft_hand_b = 0;
    p2c_ft_init();
}

/* Начало кадра: display list открывается первым выводом (p2c_ft_open_list) — кадр, в котором
 * выводит только чужой видеоадаптер (шаг машины), своего списка не строит. Номер кадра растёт, буфер и счётчики
 * списка — с нуля. Показ прошлого списка (REG_DLSWAP = 0) ждёт первая запись в RAM_DL (p2c_dl_flush): кадр игры
 * своего списка не пишет, и шаг машины не стоит до кадрового импульса FT812 (адаптер машины ждёт показа сам
 * перед своим списком). */
void p2c_ft_frame_begin(void) __banked {
    p2c_ft_swap_wait = 1;
    ++p2c_ft_frame;
    p2c_dl_fill = 0;
    p2c_dl_sent = 0;
    p2c_ft_drawn = 0;
    p2c_ft_text_count = 0;
    p2c_ft_list_open = 0;
}

/* Заголовок display list кадра: очистка, формат вершин, цвет и смешение, матрица 8/5, сдвиг −512 пикселей, BEGIN
 * BITMAPS и handle слотов A и B; текущие handle, CELL и размеры класса C неизвестны. */
void p2c_ft_open_list(void) __banked {
    p2c_ft_list_open = 1;
    p2c_dl(0x02000000UL);          /* CLEAR_COLOR_RGB 0,0,0 */
    p2c_dl(0x26000007UL);          /* CLEAR 1,1,1 */
    p2c_dl(0x27000003UL);          /* VERTEX_FORMAT 3 */
    p2c_dl(0x04FFFFFFUL);          /* COLOR_RGB 255,255,255 */
    p2c_dl(0x100000FFUL);          /* COLOR_A 255 */
    p2c_dl(0x0B000014UL);          /* BLEND_FUNC SRC_ALPHA, ONE_MINUS_SRC_ALPHA */
    p2c_dl(0x150000A0UL);          /* BITMAP_TRANSFORM_A 160: масштаб 8/5 */
    p2c_dl(0x16000000UL);
    p2c_dl(0x17000000UL);
    p2c_dl(0x18000000UL);
    p2c_dl(0x190000A0UL);          /* BITMAP_TRANSFORM_E 160 */
    p2c_dl(0x1A000000UL);
    p2c_dl(0x2B01E000UL);          /* VERTEX_TRANSLATE_X -512 px */
    p2c_dl(0x2C01E000UL);          /* VERTEX_TRANSLATE_Y -512 px */
    p2c_dl(0x1F000001UL);          /* BEGIN BITMAPS */
    p2c_ft_handles(0, P2C_FT_A_HANDLES, P2C_FT_A_BASE, 128UL * 420u, P2C_FT_LAYOUT(14, 15), P2C_FT_LAYOUT_H(14, 15),
                   P2C_FT_SIZE(14, 15), P2C_FT_SIZE_H(14, 15));
    p2c_ft_handles(P2C_FT_A_HANDLES, P2C_FT_B_HANDLES, P2C_FT_B_BASE, 128UL * 1620u, P2C_FT_LAYOUT(27, 30),
                   P2C_FT_LAYOUT_H(27, 30), P2C_FT_SIZE(27, 30), P2C_FT_SIZE_H(27, 30));
    p2c_ft_handle = 0xFF;
    p2c_ft_cell = 0xFF;
    p2c_ft_c_w = 0;
    p2c_ft_c_h = 0;
}

/* Конец кадра: END, DISPLAY, отправка буфера; загрузки сопроцессора должны закончиться до показа; DLSWAP_FRAME. */
void p2c_ft_frame_end(void) __banked {
    if (!p2c_ft_list_open) p2c_ft_open_list();
    p2c_dl(0x21000000UL);          /* END */
    p2c_dl(0x00000000UL);          /* DISPLAY */
    p2c_dl_flush();
    if (p2c_ft_uploading) p2c_ft_wait_idle();
    p2c_ft_write8(FT_REG_DLSWAP, 2);
}

/* Правый Alt (AltGr) из очереди скан-кодов PS/2 (набор 2) контроллера Mr.Gluk ZX Evolution: #EFF7 = #80 открывает
 * регистры (чип общий с часами, которые их закрывают, — поэтому каждый кадр), регистр #F0 — очередь (0 — пуста).
 * Нажатие — «E0 11», отпускание — «E0 F0 11»; «11» без E0 — левый Alt, он не считается. Первый вызов включает очередь
 * (регистр #0C = 1 — сброс буфера, #F0 = 2 — приём с клавиатуры). #FF — переполнение очереди (или контроллера нет):
 * отпускание могло потеряться, поэтому Alt отпущен и чтение кадра заканчивается. Возврат: 1 — правый Alt нажат. */
uint8_t p2c_ft_altgr(void) __banked {
    uint8_t left = P2C_PS2_DRAIN;
    uint8_t code;
    p2c_port_gluk_enable = 0x80;
    if (!p2c_ps2_ready) {
        p2c_port_gluk_register = 0x0C;
        p2c_port_gluk_data = 0x01;
        p2c_port_gluk_register = 0xF0;
        p2c_port_gluk_data = 0x02;
        p2c_ps2_ready = 1;
    }
    p2c_port_gluk_register = 0xF0;
    while (left--) {
        code = p2c_port_gluk_data;
        if (!code) break;                           /* очередь пуста */
        if (code == 0xFF) {
            p2c_ps2_altgr = 0;
            p2c_ps2_break = 0;
            p2c_ps2_extended = 0;
            break;
        }
        if (code == 0xE0) {
            p2c_ps2_extended = 1;                   /* E0 приходит перед F0 */
            continue;
        }
        if (code == 0xF0) {
            p2c_ps2_break = 1;
            continue;
        }
        if (code == 0x11 && p2c_ps2_extended) p2c_ps2_altgr = (uint8_t)!p2c_ps2_break;
        p2c_ps2_break = 0;                          /* код клавиши съедает префиксы */
        p2c_ps2_extended = 0;
    }
    return p2c_ps2_altgr;
}

/* Ввод отдельной сборки p2c_z80.py: биты направлений (1 — влево, 2 — вправо, 4 — вверх, 8 — вниз), огонь 16, Force
 * 32; start_pressed — нажатие огня в этом кадре. Кнопки мыши активным нулём; без мыши порт читается как #FF. */
void p2c_ft_input(uint8_t *start_pressed, uint8_t *input_bits) __banked {
    uint8_t bits = 0;
    uint8_t row_7ffe = p2c_port_keys_7ffe;   /* Space Sym M N B */
    uint8_t row_bffe = p2c_port_keys_bffe;   /* Enter L K J H */
    uint8_t row_dffe = p2c_port_keys_dffe;   /* P O I U Y */
    uint8_t row_fbfe = p2c_port_keys_fbfe;   /* Q W E R T */
    uint8_t row_fdfe = p2c_port_keys_fdfe;   /* A S D F G */
    uint8_t row_effe = p2c_port_keys_effe;   /* 0 9 8 7 6 */
    uint8_t row_f7fe = p2c_port_keys_f7fe;   /* 1 2 3 4 5 */
    uint8_t row_fefe = p2c_port_keys_fefe;   /* Caps Z X C V */
    uint8_t kempston = p2c_port_kempston;
    uint8_t mouse = p2c_port_mouse_buttons;
    uint8_t caps = !(row_fefe & 1u);
    uint8_t fire;
    uint8_t start;
    if (kempston == 0xFF) kempston = 0;       /* порт без джойстика */
    if (!(row_dffe & 2u) || (caps && !(row_f7fe & 16u)) || (kempston & 2u)) bits |= 1u;   /* влево */
    if (!(row_dffe & 1u) || (caps && !(row_effe & 4u)) || (kempston & 1u)) bits |= 2u;   /* вправо */
    if (!(row_fbfe & 1u) || (caps && !(row_effe & 8u)) || (kempston & 8u)) bits |= 4u;   /* вверх */
    if (!(row_fdfe & 1u) || (caps && !(row_effe & 16u)) || (kempston & 4u)) bits |= 8u;  /* вниз */
    fire = (uint8_t)(!(row_7ffe & 1u) || !(row_bffe & 1u) || (kempston & 16u) || !(mouse & 1u));  /* Space, Enter */
    if (fire) bits |= 16u;
    /* Отделение и возврат Force: правый Alt, правая кнопка Kempston-мыши и вторая кнопка
     * Kempston-джойстика (бит 5 порта #1F) — просьба пользователя 22.09.2026. */
    if (p2c_ft_altgr() || !(mouse & 2u) || (kempston & 32u)) bits |= 32u;
    *input_bits = bits;
    /* Старт игры дублирует восьмая кнопка Kempston (бит 7 порта #1F) — просьба пользователя 22.09.2026.
     * Только старт: в input_bits она не идёт, огнём и Force не работает. */
    start = (uint8_t)((kempston & 128u) != 0u);
    *start_pressed = (uint8_t)((fire && !p2c_ft_fire_previous) || (start && !p2c_ft_start_previous));
    p2c_ft_fire_previous = fire;
    p2c_ft_start_previous = start;
}
