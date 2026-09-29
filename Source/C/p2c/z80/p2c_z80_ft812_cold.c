/* Аппаратный адаптер VDAC2 (FT812), банковая часть: загрузка изображений в RAM_G
 * (CMD_INFLATE), вытеснение слотов, начало и конец кадра, ввод, отладочный текст.
 *
 * Отступление на аппаратном пределе: отладочная строка рисуется глифами шрифта
 * pygame с шагом символов из метрик шрифта, без кернинга. Клавиатура — только очередь скан-кодов PS/2 контроллера
 * AVR (p2c_ft_keyboard; матрица клавиш ZX не читается). Ввод отдельной сборки p2c_z80.py (p2c_ft_input) — стрелки
 * и QAOP, огонь — Space, Enter, Kempston-джойстик (бит 4 — огонь, бит 5 — Force), кнопки Kempston-мыши (левая —
 * огонь, правая — Force) и правый Alt (Force).
 * Код банка исполняется в окне #C000, поэтому страницы каталога читаются и пишутся
 * только резидентными функциями p2c_z80_physical_read/write. */
#include <string.h>
#include "p2c_z80_adapter.h"
#include "p2c_z80_ft812.h"

__sfr __at(0x57) p2c_cold_spi_data;
__sfr __at(0x77) p2c_cold_spi_ctrl;
__sfr __at(0x1F) p2c_port_kempston;
__sfr __banked __at(0xEFF7) p2c_port_gluk_enable;    /* Mr.Gluk ZX Evolution: #80 — регистры открыты */
__sfr __banked __at(0xDFF7) p2c_port_gluk_register;  /* номер регистра */
__sfr __banked __at(0xBFF7) p2c_port_gluk_data;      /* данные регистра */
__sfr __banked __at(0xFADF) p2c_port_mouse_buttons;  /* Kempston-мышь: бит 0 — левая, бит 1 — правая (0 — нажата) */

/* Скан-кодов PS/2 за кадр не больше (очередь с мусором не должна подвешивать кадр). */
#define P2C_PS2_DRAIN 24

/* Клавиши PS/2 кадра (p2c_ft_keyboard): p2c_kb_moves — биты P2C_KB_RIGHT…P2C_KB_Q, p2c_kb_buttons — P2C_KB_SPACE,
 * P2C_KB_ENTER, P2C_KB_ALTGR, P2C_KB_ESC (p2c_z80_ft812.h); p2c_kb_wake — в этом кадре нажата любая клавиша;
 * p2c_kb_esc — в этом кадре нажат Esc. */
uint8_t p2c_kb_moves;
uint8_t p2c_kb_buttons;
uint8_t p2c_kb_wake;
uint8_t p2c_kb_esc;

static uint8_t p2c_ps2_ready;        /* очередь скан-кодов включена */
static uint8_t p2c_ps2_break;        /* был префикс отпускания F0 */
static uint8_t p2c_ps2_extended;     /* был префикс E0 */
static uint8_t p2c_ps2_last;         /* код последнего нажатия (0 — нет): его повтор — автоповтор, не нажатие */
static uint8_t p2c_ps2_last_extended; /* у последнего нажатия был префикс E0 */

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

/* --- развёртка 59 / 55 Гц и её надпись на титуле ---------------------------------------------------------------------
 * Отступление от оригинала по просьбе пользователя 2026-09-29: «в главном меню нажатие кнопки ESC приводило к смене
 * кадровой частоты FT812 59 (по умолчанию) / 50 Гц … С кратковременным (как и в игре с мышью и клавиатурой) появлением
 * надписи … системным шрифтом: VSync 59 Hz / 50 Hz. Надпись не должна существовать на экране дольше перехода с главного
 * экрана на любой другой», затем «50 Гц мало. Давай сделаем 59 / 55 (родные)» и «По умолчанию должно быть 59 Гц»;
 * «можешь слева вывести надпись, если нет места справа» — справа внизу у титула строки «1987 BY IREM CORP.» и «… BY
 * ANDREW LAZAREV» (до строки 724), поэтому надпись — в левом нижнем углу, как «GS / TSFM» на экране загрузки. 59 Гц —
 * режим загрузчика (TSLib VM_1024_768_59Hz: ядро 64 МГц, строка 1344 такта, кадр 806 строк), 55 Гц — тот же режим с
 * кадром 866 строк: 64 000 000 / (1344 · 866) = 54,99 Гц при 55,02 Гц у M72 (865 строк — 55,05 Гц, дальше). Строка, её
 * цена в тактах FT812 и горизонталь не меняются, 60 лишних строк — пустые после видимых. Игра и мелодии шагают по кадрам
 * развёртки: при 55 Гц — в темпе аркады, при 59 Гц — быстрее на 7,4 %. Часть мониторов 1024×768 с 55 Гц не показывает
 * (так было 16.09, отсюда 59 Гц по умолчанию) — повторный Esc на титуле возвращает 59 Гц; после загрузки — всегда 59 Гц.
 * REG_VCYCLE пишется сразу (TSLib и сам пишет развёртку при включённом REG_PCLK): кадр длиннее — в любой момент без
 * последствий, короче — в худшем случае один кадр длиннее, пока монитор и так перестраивается на новую частоту.
 * Надпись — ПЗУ-шрифт 28 FT812, как у надписей машины (vdac2p_label.asm): 12 слов состояния (сдвиг, ножницы, единичная
 * матрица, BEGIN, белый) и VERTEX2II на знак, пробел — только сдвиг; ширина знака — из таблицы метрик ПЗУ (указатель в
 * #2FFFFC, блок шрифта — 148 байт с номера 16, байт на код) по ходу вывода: в резиденте оболочки места под таблицы
 * нет, а чтений — 11 за кадр и только в ≈3 с показа. Показ — P2C_LABEL_FRAMES кадров развёртки по REG_FRAMES, только в
 * кадрах титула; первый кадр не титула надпись снимает (p2c_rt_frame_end). */
#define P2C_VCYCLE_59 806u
#define P2C_VCYCLE_55 866u
#define P2C_LABEL_FONT 28u
#define P2C_LABEL_LEFT 16u                    /* левый край, физические пиксели 1024×768 */
#define P2C_LABEL_TOP 730u                    /* верх строки шрифта — как у надписей машины */
#define P2C_LABEL_DY 256u                     /* VERTEX_TRANSLATE_Y: у VERTEX2II координаты до 511 */
#define P2C_LABEL_FRAMES 177u                 /* ≈3 с кадров развёртки 59 Гц (при 55 Гц — 3,2 с), как у надписей машины */
#define P2C_LABEL_WORDS (12u + 9u)            /* слов надписи: состояние и 9 знаков «VSync 59 Hz» без пробелов */

uint8_t p2c_ft_vsync55;
uint8_t p2c_ft_label_on;
static uint16_t p2c_ft_label_until;           /* кадр развёртки конца показа (младшие 16 бит REG_FRAMES) */
static uint32_t p2c_ft_label_block;           /* адрес блока метрик шрифта P2C_LABEL_FONT в ПЗУ FT812 */

/* Знак надписи с x: VERTEX2II(x, TOP − DY, шрифт, код) = 2 << 30 | x << 21 | y << 12 | handle << 7 | код (пробел —
 * без слова); возврат — x следующего знака (ширина — байт кода в блоке метрик). */
static uint16_t p2c_ft_label_glyph(uint16_t x, uint8_t code) {
    if (code != ' ') {
        p2c_dl(0x80000000UL | ((uint32_t)(x & 511u) << 21) | ((uint32_t)(P2C_LABEL_TOP - P2C_LABEL_DY) << 12) |
               ((uint32_t)P2C_LABEL_FONT << 7) | code);
    }
    return (uint16_t)(x + p2c_ft_read8(p2c_ft_label_block + code));
}

/* Esc на титуле: развёртка 59 ↔ 55 Гц — сразу в REG_VCYCLE — и надпись «VSync 59 Hz» или «VSync 55 Hz» на
 * P2C_LABEL_FRAMES кадров развёртки. */
void p2c_ft_vsync_toggle(void) __banked {
    uint16_t vcycle;
    uint32_t fonts;
    p2c_ft_vsync55 ^= 1u;
    vcycle = p2c_ft_vsync55 ? P2C_VCYCLE_55 : P2C_VCYCLE_59;
    p2c_ft_address(FT_REG_VCYCLE, 1);
    p2c_cold_spi_data = (uint8_t)vcycle;
    p2c_cold_spi_data = (uint8_t)(vcycle >> 8);
    p2c_cold_spi_ctrl = FT_CS_OFF;
    fonts = (uint32_t)p2c_ft_read16(0x2FFFFCUL) | ((uint32_t)p2c_ft_read8(0x2FFFFEUL) << 16);
    p2c_ft_label_block = fonts + 148UL * (P2C_LABEL_FONT - 16u);
    p2c_ft_label_until = (uint16_t)(p2c_ft_read16(FT_REG_FRAMES) + P2C_LABEL_FRAMES);
    p2c_ft_label_on = 1;
}

/* Надпись развёртки в конце списка кадра титула (перед END): срок вышел — снять; нет места до FT_DL_LIMIT — кадр без
 * надписи. Сдвиг X 0 (знаки у левого края), Y 256; ножницы — весь экран; матрица — единичная целиком (под матрицей 8/5
 * титула глифы ПЗУ-шрифта рвутся); BEGIN BITMAPS и белый; затем знаки. */
static void p2c_ft_label_emit(void) {
    uint16_t x;
    if ((int16_t)(p2c_ft_read16(FT_REG_FRAMES) - p2c_ft_label_until) >= 0) {
        p2c_ft_label_on = 0;
        return;
    }
    if (p2c_dl_sent + p2c_dl_fill + P2C_LABEL_WORDS * 4u > FT_DL_LIMIT) return;
    p2c_dl(0x2B000000UL);                             /* VERTEX_TRANSLATE_X 0 */
    p2c_dl(0x2C000000UL | (P2C_LABEL_DY * 16u));      /* VERTEX_TRANSLATE_Y 256 (1/16 пикселя) */
    p2c_dl(0x1B000000UL);                             /* SCISSOR_XY 0,0 */
    p2c_dl(0x1C400300UL);                             /* SCISSOR_SIZE 1024,768 */
    p2c_dl(0x15000100UL);                             /* BITMAP_TRANSFORM_A 256 — единичная матрица, целиком */
    p2c_dl(0x16000000UL);
    p2c_dl(0x17000000UL);
    p2c_dl(0x18000000UL);
    p2c_dl(0x19000100UL);                             /* BITMAP_TRANSFORM_E 256 */
    p2c_dl(0x1A000000UL);
    p2c_dl(0x1F000001UL);                             /* BEGIN BITMAPS */
    p2c_dl(0x04FFFFFFUL);                             /* COLOR_RGB 255,255,255 */
    x = p2c_ft_label_glyph(P2C_LABEL_LEFT, 'V');
    x = p2c_ft_label_glyph(x, 'S');
    x = p2c_ft_label_glyph(x, 'y');
    x = p2c_ft_label_glyph(x, 'n');
    x = p2c_ft_label_glyph(x, 'c');
    x = p2c_ft_label_glyph(x, ' ');
    x = p2c_ft_label_glyph(x, '5');
    x = p2c_ft_label_glyph(x, p2c_ft_vsync55 ? '5' : '9');
    x = p2c_ft_label_glyph(x, ' ');
    x = p2c_ft_label_glyph(x, 'H');
    p2c_ft_label_glyph(x, 'z');
}

/* Конец кадра: надпись развёртки (кадры титула), END, DISPLAY, отправка буфера; загрузки сопроцессора должны
 * закончиться до показа; DLSWAP_FRAME. */
void p2c_ft_frame_end(void) __banked {
    if (!p2c_ft_list_open) p2c_ft_open_list();
    if (p2c_ft_label_on) p2c_ft_label_emit();
    p2c_dl(0x21000000UL);          /* END */
    p2c_dl(0x00000000UL);          /* DISPLAY */
    p2c_dl_flush();
    if (p2c_ft_uploading) p2c_ft_wait_idle();
    p2c_ft_write8(FT_REG_DLSWAP, 2);
}

/* Клавиша PS/2 (набор 2) → бит p2c_kb_moves или p2c_kb_buttons: code — код клавиши, extended — был префикс E0,
 * pressed — 1 нажатие, 0 отпускание. Префикс E0 различает только правый Alt («E0 11») и левый («11», не считается):
 * у стрелок коды свои (E0 74 → и т. д.), и без E0 они — те же стрелки цифрового блока, Enter цифрового блока
 * («E0 5A») — тот же Enter; так, как в Zuma (Input.asm), потерянный байт E0 стрелку не ломает. Esc («76») — ещё и
 * событие p2c_kb_esc, если до этого кода он был отпущен: автоповтор при удержании (и повтор после других клавиш) не
 * переключает скорость, а нажатие с отпусканием в одном кадре — переключает. Прочие коды — мимо. */
static void p2c_kb_key(uint8_t code, uint8_t extended, uint8_t pressed) {
    uint8_t *state = &p2c_kb_moves;
    uint8_t bit;
    switch (code) {
    case 0x74: bit = P2C_KB_RIGHT; break;           /* → */
    case 0x6B: bit = P2C_KB_LEFT; break;            /* ← */
    case 0x72: bit = P2C_KB_DOWN; break;            /* ↓ */
    case 0x75: bit = P2C_KB_UP; break;              /* ↑ */
    case 0x4D: bit = P2C_KB_P; break;               /* P — вправо */
    case 0x44: bit = P2C_KB_O; break;               /* O — влево */
    case 0x1C: bit = P2C_KB_A; break;               /* A — вниз */
    case 0x15: bit = P2C_KB_Q; break;               /* Q — вверх */
    case 0x29: state = &p2c_kb_buttons; bit = P2C_KB_SPACE; break;
    case 0x5A: state = &p2c_kb_buttons; bit = P2C_KB_ENTER; break;
    case 0x11:
        if (!extended) return;                      /* левый Alt */
        state = &p2c_kb_buttons;
        bit = P2C_KB_ALTGR;
        break;
    case 0x76:                                      /* Esc — шаг R-9 от клавиш и джойстика ×1 ↔ ×2 */
        if (pressed && !(p2c_kb_buttons & P2C_KB_ESC)) p2c_kb_esc = 1;   /* был отпущен — нажатие */
        state = &p2c_kb_buttons;
        bit = P2C_KB_ESC;
        break;
    default:
        return;
    }
    if (pressed) *state |= bit;                     /* нажатие — бит в 1 (повтор нажатия его не меняет) */
    else *state &= (uint8_t)~bit;                   /* отпускание — в 0 */
}

/* Клавиатура — только очередь скан-кодов PS/2 (набор 2) контроллера Mr.Gluk ZX Evolution (AVR), как в Wild
 * Commander (PS2P.ASM) и Zuma (Input.asm); матрица клавиш ZX не читается. Просьба пользователя 28.09.2026: у HIDman
 * mini (USB → PS/2) клавиши залипали в матрице AVR — прошивка считает нажатия каждой клавиши ZX счётчиком (стрелка —
 * Caps Shift + цифра), и нажатие без парного отпускания держит клавишу до Esc или выключения питания («клавиатуру
 * 40-pin вообще не нужно опрашивать», «вот пример игры, где только AVR» — Zuma). Здесь у клавиши одно состояние
 * «нажата»: повтор нажатия его не меняет, отпускание снимает (p2c_kb_key).
 * #EFF7 = #80 открывает регистры (чип общий с часами, которые их закрывают, — поэтому каждый кадр), регистр #F0 —
 * очередь (0 — пуста). Нажатие — код клавиши (у расширенных — с префиксом E0), отпускание — F0 перед кодом. Первый
 * вызов включает очередь (регистр #0C = 1 — сброс буфера, #F0 = 2 — приём с клавиатуры; так же делают WC и Zuma).
 * #FF — переполнение очереди (16 байт, AVR сбрасывает её сам): как в Zuma, пропускается — состояния клавиш остаются,
 * префиксы и последнее нажатие забываются (очередь после сброса начинается с целой клавиши). «E0 12», «E0 59» —
 * ложные Shift клавиатуры при NumLock — мимо.
 * Итог кадра: p2c_kb_moves, p2c_kb_buttons и p2c_kb_wake = 1, если нажата любая клавиша. Нажатие того же кода, что
 * последнее, без отпускания между ними — автоповтор PS/2 (повторяется только последняя нажатая клавиша), не нажатие.
 * p2c_kb_esc = 1 — в кадре нажат Esc (p2c_kb_key). */
void p2c_ft_keyboard(void) __banked {
    uint8_t left = P2C_PS2_DRAIN;
    uint8_t code;
    p2c_kb_wake = 0;
    p2c_kb_esc = 0;
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
        if (code == 0xFF) {                         /* переполнение: состояния клавиш остаются */
            p2c_ps2_break = 0;
            p2c_ps2_extended = 0;
            p2c_ps2_last = 0;
            continue;
        }
        if (code == 0xE0) {
            p2c_ps2_extended = 1;                   /* E0 приходит перед F0 */
            continue;
        }
        if (code == 0xF0) {
            p2c_ps2_break = 1;
            continue;
        }
        if (!(p2c_ps2_extended && (code == 0x12 || code == 0x59))) {
            if (p2c_ps2_break) {
                /* отпускание: у последнего нажатия его повтор снова будет нажатием */
                if (code == p2c_ps2_last && p2c_ps2_extended == p2c_ps2_last_extended) p2c_ps2_last = 0;
                p2c_kb_key(code, p2c_ps2_extended, 0);
            } else {
                if (code != p2c_ps2_last || p2c_ps2_extended != p2c_ps2_last_extended) {
                    p2c_kb_wake = 1;                /* нажатие, а не автоповтор */
                    p2c_ps2_last = code;
                    p2c_ps2_last_extended = p2c_ps2_extended;
                }
                p2c_kb_key(code, p2c_ps2_extended, 1);
            }
        }
        p2c_ps2_break = 0;                          /* код клавиши съедает префиксы */
        p2c_ps2_extended = 0;
    }
}

/* Ввод отдельной сборки p2c_z80.py: биты направлений (1 — влево, 2 — вправо, 4 — вверх, 8 — вниз), огонь 16, Force
 * 32; start_pressed — нажатие огня в этом кадре. Кнопки мыши активным нулём; без мыши порт читается как #FF. */
void p2c_ft_input(uint8_t *start_pressed, uint8_t *input_bits) __banked {
    uint8_t bits = 0;
    uint8_t kempston = p2c_port_kempston;
    uint8_t mouse = p2c_port_mouse_buttons;
    uint8_t moves;
    uint8_t fire;
    uint8_t start;
    if (kempston == 0xFF) kempston = 0;       /* порт без джойстика */
    p2c_ft_keyboard();
    moves = (uint8_t)((p2c_kb_moves | (p2c_kb_moves >> 4)) & 15u);   /* стрелки | P O A Q: вправо 1, влево 2, вниз 4, вверх 8 */
    if ((moves & 2u) || (kempston & 2u)) bits |= 1u;    /* влево */
    if ((moves & 1u) || (kempston & 1u)) bits |= 2u;    /* вправо */
    if ((moves & 8u) || (kempston & 8u)) bits |= 4u;    /* вверх */
    if ((moves & 4u) || (kempston & 4u)) bits |= 8u;    /* вниз */
    fire = (uint8_t)((p2c_kb_buttons & (P2C_KB_SPACE | P2C_KB_ENTER)) || (kempston & 16u) || !(mouse & 1u));
    if (fire) bits |= 16u;
    /* Отделение и возврат Force: правый Alt, правая кнопка Kempston-мыши и вторая кнопка
     * Kempston-джойстика (бит 5 порта #1F) — просьба пользователя 22.09.2026. */
    if ((p2c_kb_buttons & P2C_KB_ALTGR) || !(mouse & 2u) || (kempston & 32u)) bits |= 32u;
    *input_bits = bits;
    /* Старт игры дублирует восьмая кнопка Kempston (бит 7 порта #1F) — просьба пользователя 22.09.2026.
     * Только старт: в input_bits она не идёт, огнём и Force не работает. */
    start = (uint8_t)((kempston & 128u) != 0u);
    *start_pressed = (uint8_t)((fire && !p2c_ft_fire_previous) || (start && !p2c_ft_start_previous));
    p2c_ft_fire_previous = fire;
    p2c_ft_start_previous = start;
}
