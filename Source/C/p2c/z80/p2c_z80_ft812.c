/* Аппаратный адаптер VDAC2 (FT812) для кода p2c, резидентная часть: вывод blit
 * в display list, ячейки спрайтов, размеры отладочного текста. Логики игры здесь нет.
 *
 * Изображения программы описаны каталогом сборки: запись на странице данных
 * хранит размер, класс и сжатые zlib пиксели ARGB4444. В RAM_G изображение
 * загружается при первом выводе командой сопроцессора CMD_INFLATE (банковая
 * часть p2c_z80_ft812_cold.c): класс A (14×15, тайлы и глифы) и класс B (27×30,
 * ячейки спрайтов) — в слоты с вытеснением давно не выводившихся, класс C
 * (прочие) — подряд. Слоты A и B — ячейки BITMAP_HANDLE по 128, прочие выводятся
 * через BITMAP_SOURCE с размерами BITMAP_LAYOUT/BITMAP_SIZE.
 *
 * Экран: логические 640×480 выводятся аппаратным масштабом 8/5 (матрица A=E=160),
 * вершины VERTEX2F в 1/8 физического пикселя; VERTEX_TRANSLATE сдвигает кадр на
 * -512 физических пикселей, чтобы координаты вершин не были отрицательными.
 * Байты вершин берутся из таблиц страницы P2C_FT_TABLE_PAGE.
 *
 * Отступления на аппаратном пределе: изображение, целиком лежащее вне экрана,
 * не выводится; сплошной непрозрачный чёрный глиф до первого вывода в кадре не
 * выводится (он совпадает с чёрной очисткой); при переполнении display list
 * (2048 команд FT812) остаток кадра отбрасывается и считается в p2c_ft_dropped. */
#include <string.h>
#include "p2c_z80_adapter.h"
#include "p2c_z80_ft812.h"

__sfr __at(0x57) p2c_spi_data;                 /* SPI Z-контроллера: байт обмена */
__sfr __at(0x77) p2c_spi_ctrl;                 /* выбор устройства (FT_CS_ON — FT812) */
__sfr __banked __at(0x13AF) p2c_ft_page3;      /* страница окна #C000 */
__sfr __banked __at(0x1AAF) p2c_dma_src_l;     /* DMA: адрес источника (младший, старший байт, страница) */
__sfr __banked __at(0x1BAF) p2c_dma_src_h;
__sfr __banked __at(0x1CAF) p2c_dma_src_x;
__sfr __banked __at(0x26AF) p2c_dma_len;       /* DMA: слов в пакете − 1 */
__sfr __banked __at(0x27AF) p2c_dma_ctrl;      /* DMA: режим (#82 — RAM → SPI); чтение — бит 7 = идёт передача */
__sfr __banked __at(0x28AF) p2c_dma_num;       /* DMA: пакетов − 1 */

uint8_t p2c_ft_frame;            /* номер кадра (по модулю 256) — для вытеснения давно не выводившихся слотов */
/* Совместная работа с видеоадаптером другой программы (цикл app.main полного runtime):
 * p2c_ft_foreign — RAM_G и handle FT812 занимал чужой вывод (слоты загрузки недействительны),
 * p2c_ft_skip_swap — display list кадра уже показан чужим выводом. */
uint8_t p2c_ft_foreign;
uint8_t p2c_ft_skip_swap;
uint8_t p2c_ft_swapped;          /* показан display list титула (handle и RAM_G титула) */
void (*p2c_ft_foreign_fade)(void);
uint16_t p2c_ft_dropped;         /* выводов, не поместившихся в display list или RAM_G */
uint16_t p2c_ft_missing;         /* выводов изображений без данных в каталоге */
uint16_t p2c_ft_uploads;         /* загрузок изображений в RAM_G */
uint16_t p2c_ft_blits;           /* выведенных изображений */
uint16_t p2c_dl_fill;            /* байт в буфере display list, ещё не отправленных */
uint16_t p2c_dl_sent;            /* байт display list, уже отправленных в RAM_DL */
uint8_t p2c_ft_swap_wait;        /* 1 — в кадре ещё не ждался показ прошлого списка (до первой записи в RAM_DL) */
uint8_t p2c_ft_drawn;            /* в кадре уже что-то выведено (для правила чёрного глифа) */
uint8_t p2c_ft_list_open;
uint8_t p2c_ft_handle;           /* текущий BITMAP_HANDLE списка */
uint8_t p2c_ft_cell;             /* текущий CELL списка */
uint16_t p2c_ft_c_w;             /* размеры, заданные BITMAP_LAYOUT/SIZE для handle класса C */
uint16_t p2c_ft_c_h;
uint32_t p2c_ft_c_next;          /* следующий свободный адрес области C в RAM_G */
uint16_t p2c_ft_hand_a;          /* стрелки вытеснения слотов A и B (по кругу) */
uint16_t p2c_ft_hand_b;
uint8_t p2c_ft_uploading;
P2cFtEntry p2c_ft_entry;         /* прочитанная запись каталога */
uint16_t p2c_ft_entry_index;     /* номер прочитанной записи */
uint8_t p2c_ft_fire_previous;
uint8_t p2c_ft_start_previous;           /* восьмая кнопка Kempston прошлого кадра (бит 7 #1F) */
P2cFtText p2c_ft_texts[8];       /* тексты кадра (p2c_text_image): изображения #C000 + номер */
uint8_t p2c_ft_text_count;

/* --- SPI FT812 ------------------------------------------------------------------- */

/* Выбрать FT812 и передать 22-битный адрес: старший байт — 6 бит адреса, бит 7 = 1 у записи (у чтения 0). */
void p2c_ft_address(uint32_t address, uint8_t write) {
    p2c_spi_ctrl = FT_CS_ON;
    p2c_spi_data = (uint8_t)((address >> 16) & 0x3F) | (write ? 0x80 : 0x00);
    p2c_spi_data = (uint8_t)(address >> 8);
    p2c_spi_data = (uint8_t)address;
}

/* Байт из памяти FT812. Чтение порта данных SPI — обмен: он возвращает байт, принятый прошлым обменом, поэтому после
 * адреса и пустого байта первое чтение пустое. */
uint8_t p2c_ft_read8(uint32_t address) {
    uint8_t value;
    p2c_ft_address(address, 0);
    p2c_spi_data = (uint8_t)address;       /* пустой байт после адреса */
    value = p2c_spi_data;                  /* пустое чтение */
    value = p2c_spi_data;
    p2c_spi_ctrl = FT_CS_OFF;
    return value;
}

/* Слово little-endian из памяти FT812 (регистры). */
uint16_t p2c_ft_read16(uint32_t address) {
    uint16_t value;
    p2c_ft_address(address, 0);
    p2c_spi_data = (uint8_t)address;
    value = p2c_spi_data;
    value = p2c_spi_data;
    value |= (uint16_t)p2c_spi_data << 8;
    p2c_spi_ctrl = FT_CS_OFF;
    return value;
}

void p2c_ft_write8(uint32_t address, uint8_t value) {
    p2c_ft_address(address, 1);
    p2c_spi_data = value;
    p2c_spi_ctrl = FT_CS_OFF;
}

/* Показ прошлого списка (REG_DLSWAP = 0) — раз за кадр, перед первой записью кадра в RAM_DL или RAM_G (выгрузка
 * изображения): вытеснение слотов считает прошлый список уже показанным. Кадр, который сам не пишет (шаг машины с её
 * выводом), не ждёт. */
void p2c_ft_wait_swap(void) {
    if (!p2c_ft_swap_wait) return;
    while (p2c_ft_read8(FT_REG_DLSWAP)) {
    }
    p2c_ft_swap_wait = 0;
}

/* --- display list: буфер в резидентной странице уходит в RAM_DL через DMA RAM->SPI ------ */

/* Адрес буфера постоянный и чётный: DMA RAM->SPI TS-Config передаёт данные с чётного
 * адреса, и буфер с нечётным адресом уходил в RAM_DL со сдвигом на байт.
 * Запись в RAM_DL с места p2c_dl_sent: DMA одним пакетом (p2c_dl_fill / 2) слов из страницы резидента (окно #0000),
 * ожидание конца передачи, затем отправленное прибавляется к p2c_dl_sent. Первая запись кадра сначала ждёт показа
 * прошлого списка (p2c_ft_wait_swap): RAM_DL, в которой ещё лежит запрошенный к показу список, переписывать нельзя. */
void p2c_dl_flush(void) {
    uint16_t offset = P2C_Z80_DL_BUFFER & 0x3FFFu;
    if (!p2c_dl_fill) return;
    p2c_ft_wait_swap();
    p2c_ft_address(FT_RAM_DL + p2c_dl_sent, 1);
    p2c_dma_src_l = (uint8_t)offset;
    p2c_dma_src_h = (uint8_t)(offset >> 8);
    p2c_dma_src_x = P2C_Z80_PAGE_RESIDENT;
    p2c_dma_len = (uint8_t)((p2c_dl_fill >> 1) - 1u);
    p2c_dma_num = 0;
    p2c_dma_ctrl = 0x82;
    while (p2c_dma_ctrl & 0x80) {
    }
    p2c_spi_ctrl = FT_CS_OFF;
    p2c_dl_sent += p2c_dl_fill;
    p2c_dl_fill = 0;
}

/* Слово display list в буфер (little-endian); полный буфер (P2C_DL_SIZE байт) сначала отправляется. */
void p2c_dl(uint32_t word) {
    uint8_t *cursor;
    if (p2c_dl_fill == P2C_DL_SIZE) p2c_dl_flush();
    cursor = p2c_dl_buffer + p2c_dl_fill;
    cursor[0] = (uint8_t)word;
    cursor[1] = (uint8_t)(word >> 8);
    cursor[2] = (uint8_t)(word >> 16);
    cursor[3] = (uint8_t)(word >> 24);
    p2c_dl_fill += 4;
}

/* --- записи каталога ---------------------------------------------------------------- */

/* Запись index каталога (16 байт) → p2c_ft_entry: страница P2C_FT_ENTRY_PAGE + index / 1024, смещение (index % 1024)·16
 * в окне #C000; окно возвращается банку кода. */
void p2c_ft_read_entry(uint16_t index) {
    p2c_ft_page3 = (uint8_t)(P2C_FT_ENTRY_PAGE + (index >> 10));
    memcpy(&p2c_ft_entry, (const uint8_t *)(0xC000u + ((index & 1023u) << 4)), sizeof p2c_ft_entry);
    p2c_ft_page3 = p2c_bank;
    p2c_ft_entry_index = index;
}

/* Состояние загрузки (state и used, байты 12…15 записи) — обратно в каталог. */
void p2c_ft_write_state(void) {
    p2c_ft_page3 = (uint8_t)(P2C_FT_ENTRY_PAGE + (p2c_ft_entry_index >> 10));
    memcpy((uint8_t *)(0xC000u + ((p2c_ft_entry_index & 1023u) << 4) + 12u), p2c_ft_entry.state, 4);
    p2c_ft_page3 = p2c_bank;
}

/* --- вывод ---------------------------------------------------------------------------- */

/* VERTEX2F логической точки (x, y): слово #40000000 | X·2^15 | Y (15 бит каждая, 1/8 пикселя). Байты X и Y заранее
 * посчитаны в таблицах страницы P2C_FT_TABLE_PAGE: байт 0 слова — младший байт Y, байт 1 — старшие биты Y и младший
 * бит X, байт 2 и 3 — остальные биты X с кодом команды. */
static void p2c_ft_vertex(int16_t x, int16_t y) {
    uint8_t *cursor;
    const uint8_t *xb;
    const uint8_t *yb;
    if (p2c_dl_fill == P2C_DL_SIZE) p2c_dl_flush();
    cursor = p2c_dl_buffer + p2c_dl_fill;
    p2c_ft_page3 = P2C_FT_TABLE_PAGE;
    /* Таблица X: 3 байта на логический X с -320, таблица Y: 2 байта с #1000. */
    xb = (const uint8_t *)(0xC000u + (uint16_t)(x + 320) * 3u);
    yb = (const uint8_t *)(0xD000u + ((uint16_t)(y + 320) << 1));
    cursor[0] = yb[1];
    cursor[1] = (uint8_t)(yb[0] | xb[2]);
    cursor[2] = xb[1];
    cursor[3] = xb[0];
    p2c_ft_page3 = p2c_bank;
    p2c_dl_fill += 4;
}

/* Вывод записи каталога index в логической точке (x, y). По порядку: после чужого вывода — затемнение и сброс
 * адаптера; заголовок списка кадра; нет данных — счёт p2c_ft_missing; вне экрана — пропуск; чёрный глиф до первого
 * вывода — пропуск; нет места в списке (32 байта на слова вывода) — счёт p2c_ft_dropped. Классы A и B: state[0..1] —
 * слот + 1 (0 — не загружено: занять слот с вытеснением и загрузить в A_BASE + (слот − 1)·420 или B_BASE + (слот −
 * 1)·1620), used — кадр вывода; handle = (класс B ? P2C_FT_A_HANDLES : 0) + (слот − 1) / 128, CELL = (слот − 1) mod
 * 128 — слова только при смене. Класс C: state[0..2] — адрес в RAM_G (0 — не загружено: занять w·h·2 байт, кратно
 * 4, с p2c_ft_c_next), handle FT_HANDLE_C, BITMAP_SOURCE и при смене размеров BITMAP_LAYOUT (ARGB4, шаг w·2, h) и
 * BITMAP_SIZE ((w·8 + 4) / 5 × (h·8 + 4) / 5 — масштаб 8/5 с округлением). */
void p2c_ft_draw_entry(uint16_t index, int32_t x, int32_t y) {
    uint32_t address;
    if (p2c_ft_foreign) {
        if (p2c_ft_foreign_fade) p2c_ft_foreign_fade();
        p2c_ft_reset();
        p2c_ft_foreign = 0;
    }
    if (!p2c_ft_list_open) p2c_ft_open_list();
    p2c_ft_read_entry(index);
    if (p2c_ft_entry.cls == 0xFF) {
        ++p2c_ft_missing;
        return;
    }
    if (x >= 640 || y >= 480 || x + (int32_t)p2c_ft_entry.w <= 0 || y + (int32_t)p2c_ft_entry.h <= 0) return;
    if (x < -320 || y < -320) return;
    if ((p2c_ft_entry.flags & 1u) && !p2c_ft_drawn) return;
    if (p2c_dl_sent + p2c_dl_fill + 32u > FT_DL_LIMIT) {
        ++p2c_ft_dropped;
        return;
    }
    if (p2c_ft_entry.cls < 2) {
        uint16_t slot = (uint16_t)(p2c_ft_entry.state[0] | ((uint16_t)p2c_ft_entry.state[1] << 8));
        uint8_t handle;
        uint8_t cell;
        if (!slot) {
            slot = p2c_ft_take_slot(p2c_ft_entry.cls);
            if (!slot) {
                ++p2c_ft_dropped;
                return;
            }
            address = p2c_ft_entry.cls ? P2C_FT_B_BASE + (uint32_t)(slot - 1u) * 1620u
                                       : P2C_FT_A_BASE + (uint32_t)(slot - 1u) * 420u;
            p2c_ft_upload(address);
            p2c_ft_entry.state[0] = (uint8_t)slot;
            p2c_ft_entry.state[1] = (uint8_t)(slot >> 8);
            p2c_ft_entry.used = p2c_ft_frame;
            p2c_ft_write_state();
        } else if (p2c_ft_entry.used != p2c_ft_frame) {
            p2c_ft_entry.used = p2c_ft_frame;
            p2c_ft_write_state();
        }
        handle = (uint8_t)((p2c_ft_entry.cls ? P2C_FT_A_HANDLES : 0) + ((slot - 1u) >> 7));
        cell = (uint8_t)((slot - 1u) & 127u);
        if (handle != p2c_ft_handle) {
            p2c_dl(0x05000000UL | handle);                                 /* BITMAP_HANDLE */
            p2c_ft_handle = handle;
        }
        if (cell != p2c_ft_cell) {
            p2c_dl(0x06000000UL | cell);                                   /* CELL */
            p2c_ft_cell = cell;
        }
    } else {
        address = (uint32_t)p2c_ft_entry.state[0] | ((uint32_t)p2c_ft_entry.state[1] << 8) |
                  ((uint32_t)p2c_ft_entry.state[2] << 16);
        if (!address) {
            uint32_t size = ((uint32_t)p2c_ft_entry.w * p2c_ft_entry.h * 2u + 3u) & ~3UL;
            if (p2c_ft_c_next + size > P2C_FT_C_END) {
                ++p2c_ft_dropped;
                return;
            }
            /* Адрес 0 означает «не загружено»: область C начинается со смещения 4. */
            address = p2c_ft_c_next;
            p2c_ft_c_next += size;
            p2c_ft_upload(address);
            p2c_ft_entry.state[0] = (uint8_t)address;
            p2c_ft_entry.state[1] = (uint8_t)(address >> 8);
            p2c_ft_entry.state[2] = (uint8_t)(address >> 16);
            p2c_ft_write_state();
        }
        if (p2c_ft_handle != FT_HANDLE_C) {
            p2c_dl(0x05000000UL | FT_HANDLE_C);
            p2c_ft_handle = FT_HANDLE_C;
        }
        /* CELL — общее состояние графики, а не номера handle: после ячейки слота нужен CELL 0. */
        if (p2c_ft_cell) {
            p2c_dl(0x06000000UL);
            p2c_ft_cell = 0;
        }
        p2c_dl(0x01000000UL | address);                                    /* BITMAP_SOURCE */
        if (p2c_ft_entry.w != p2c_ft_c_w || p2c_ft_entry.h != p2c_ft_c_h) {
            uint16_t stride = p2c_ft_entry.w << 1;
            uint16_t sw = (uint16_t)((p2c_ft_entry.w * 8u + 4u) / 5u);
            uint16_t sh = (uint16_t)((p2c_ft_entry.h * 8u + 4u) / 5u);
            /* BITMAP_LAYOUT ARGB4 (6): шаг — 10 младших бит, высота — 9; старшие биты — BITMAP_LAYOUT_H. */
            p2c_dl(0x07000000UL | (6UL << 19) | (((uint32_t)stride & 1023u) << 9) | (p2c_ft_entry.h & 511u));
            p2c_dl(0x28000000UL | ((stride >> 10) << 2) | (p2c_ft_entry.h >> 9));
            /* BITMAP_SIZE NEAREST, BORDER: 9 младших бит ширины и высоты; старшие — BITMAP_SIZE_H. */
            p2c_dl(0x08000000UL | (((uint32_t)sw & 511u) << 9) | (sh & 511u));
            p2c_dl(0x29000000UL | ((sw >> 9) << 2) | (sh >> 9));
            p2c_ft_c_w = p2c_ft_entry.w;
            p2c_ft_c_h = p2c_ft_entry.h;
        }
    }
    p2c_ft_vertex((int16_t)x, (int16_t)y);
    p2c_ft_drawn = 1;
    ++p2c_ft_blits;
}

/* Изображение программы: #C000 | номер — текст кадра (p2c_text_image); #8000 | номер — сразу запись каталога; иначе —
 * номер изображения, запись которого берётся из таблицы страниц P2C_FT_IMAGE_PAGE (8192 слова на страницу). */
#ifdef P2C_BLIT_ASM
/* Общий путь вывода: быстрый путь p2c_blit для загруженных изображений — p2c_z80_blit.s. */
void p2c_blit_c(P2cImage image, int32_t x, int32_t y) {
#else
void p2c_blit(P2cImage image, int32_t x, int32_t y) {
#endif
    uint16_t index;
    if ((image & 0xC000u) == 0xC000u) {
        p2c_ft_draw_text((uint8_t)(image & 7u), x, y);
        return;
    }
    if (image & 0x8000u) {
        index = image & 0x3FFFu;
    } else {
        p2c_ft_page3 = (uint8_t)(P2C_FT_IMAGE_PAGE + (image >> 13));
        index = *(uint16_t *)(0xC000u + ((image & 0x1FFFu) << 1));
        p2c_ft_page3 = p2c_bank;
    }
    p2c_ft_draw_entry(index, x, y);
}

/* Surface.fill("black"): экран и так очищается чёрным в заголовке display list. */
void p2c_fill_black(void) {
}

int16_t p2c_target_get_width(void) {
    return 640;
}

int16_t p2c_target_get_height(void) {
    return 480;
}

/* Font.render: текст запоминается в таблице кадра (до 8), изображение — #C000 | номер; black — цвет чёрный. */
P2cImage p2c_text_image(const P2cStr *text, uint8_t antialias, uint32_t color) {
    uint8_t index = p2c_ft_text_count;
    (void)antialias;
    if (index >= 8u) p2c_raise(P2C_E_MEMORY);
    p2c_ft_texts[index].text = text;
    p2c_ft_texts[index].black = (uint8_t)((color & 0xFFFFFFUL) == 0);
    ++p2c_ft_text_count;
    return (P2cImage)(0xC000u | index);
}

/* Ширина поверхности "DIST XXXX" шрифта pygame: таблица по значению (полбайта на значение). Значение — 4
 * шестнадцатеричные цифры с позиции 5; байт таблицы — страница TEXT_WIDTH_PAGE + value >> 15, смещение (value >> 1)
 * & #3FFF; у чётного значения — младший полубайт, у нечётного — старший; ширина = TEXT_WIDTH_BASE + полубайт. */
int16_t p2c_image_get_width(P2cImage image) {
    const P2cStr *text = p2c_ft_texts[image & 7u].text;
    uint16_t value = 0;
    uint8_t index;
    uint8_t packed;
    if (text->length != 9) p2c_raise(P2C_E_VALUE);
    for (index = 5; index < 9; index++) {
        uint8_t digit = text->data[index];
        digit = digit <= '9' ? (uint8_t)(digit - '0') : (uint8_t)(digit - 'A' + 10);
        value = (uint16_t)((value << 4) | digit);
    }
    p2c_ft_page3 = (uint8_t)(P2C_Z80_TEXT_WIDTH_PAGE + (uint8_t)(value >> 15));
    packed = *(uint8_t *)(0xC000u + ((value >> 1) & 0x3FFFu));
    p2c_ft_page3 = p2c_bank;
    return (int16_t)(P2C_Z80_TEXT_WIDTH_BASE + ((value & 1u) ? (packed >> 4) : (packed & 15u)));
}

int16_t p2c_image_get_height(P2cImage image) {
    (void)image;
    return P2C_Z80_TEXT_HEIGHT;
}

/* Ячейка спрайта: банк (типовой ресурс или палитра) и отражения выбирают таблицу страницы. Таблица = банк·4 + fx·2 + fy
 * (#FF у типа — банк = палитра & 15); слово записи каталога — по смещению таблицы + код·2 (12 бит кода). Нет таблицы —
 * запись 0 (#8000). */
P2cImage p2c_sprite_cell(int32_t palette, int32_t resource_type, int32_t code, uint8_t flip_x, uint8_t flip_y) {
    uint8_t bank = p2c_ft_bank_of_type[(uint8_t)resource_type];
    uint8_t table;
    uint16_t index;
    if (bank == 0xFF) bank = (uint8_t)(palette & 15);
    table = (uint8_t)((bank << 2) | (flip_x ? 2u : 0u) | (flip_y ? 1u : 0u));
    if (!p2c_ft_cell_pages[table]) return 0x8000u;
    p2c_ft_page3 = p2c_ft_cell_pages[table];
    index = *(uint16_t *)(0xC000u + p2c_ft_cell_offsets[table] + (((uint16_t)code & 0x0FFFu) << 1));
    p2c_ft_page3 = p2c_bank;
    return (P2cImage)(0x8000u | index);
}

/* --- кадр: вызовы цикла main передаются банковой части ---------------------------------- */

void p2c_z80_adapter_init(void) {
    p2c_ft_init();
}

void p2c_z80_frame_begin(void) {
    p2c_ft_skip_swap = 0;
    p2c_ft_frame_begin();
}

/* Конец кадра: список показывается (DLSWAP), если его не показал чужой вывод (кадр машины); затем точка модели. */
void p2c_z80_frame_end(void) {
    if (!p2c_ft_skip_swap) {
        p2c_ft_frame_end();
        p2c_ft_swapped = 1;
    }
    p2c_z80_hook();
}

void p2c_z80_input(uint8_t *start_pressed, uint8_t *input_bits) {
    p2c_ft_input(start_pressed, input_bits);
}

/* Точка останова модели проверки: конец кадра. */
void p2c_z80_hook(void) {
}

/* Звук идёт через машину (вызовы 7 и 8 страницы переключения): здесь пусто. */
void p2c_z80_sound_frame(void) {
}

void p2c_sound_play(int32_t command) {
    (void)command;
}

void p2c_sound_start_music(void) {
}
