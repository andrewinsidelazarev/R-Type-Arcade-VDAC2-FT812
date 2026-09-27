/* Общие объявления адаптера FT812: резидентная часть (вывод кадра) и банковая
 * (загрузка изображений в RAM_G, кадр, ввод, отладочный текст). */
#ifndef P2C_Z80_FT812_H
#define P2C_Z80_FT812_H

#include <stdint.h>
#include "p2c_runtime.h"
#include "p2c_z80_config.h"

#define FT_CS_ON 0x07              /* порт выбора SPI: FT812 выбран */
#define FT_CS_OFF 0x03             /* ничего не выбрано */
#define FT_RAM_DL 0x300000UL
#define FT_REG_DLSWAP 0x302054UL
#define FT_REG_CMDB_SPACE 0x302574UL
#define FT_REG_CMDB_WRITE 0x302578UL
#define FT_DL_LIMIT 8184u          /* 2046 команд: остаются END и DISPLAY */
#define FT_HANDLE_C 15             /* handle изображений класса C (BITMAP_SOURCE и размеры на каждый вывод) */

/* Запись каталога изображений (16 байт на странице P2C_FT_ENTRY_PAGE + номер / 1024). */
typedef struct {
    uint8_t cls;                   /* класс: 0 — A (14×15), 1 — B (27×30), 2 — C (прочие), #FF — данных нет */
    uint8_t flags;                 /* бит 0 — сплошной непрозрачный чёрный глиф */
    uint16_t w;                    /* размер в логических пикселях */
    uint16_t h;
    uint8_t page;                  /* сжатые пиксели ARGB4444: физическая страница, смещение и длина */
    uint8_t pad;
    uint16_t offset;
    uint16_t clen;
    uint8_t state[3];              /* загрузка: A и B — слот + 1 (0 — не загружено), C — адрес в RAM_G (0 — нет) */
    uint8_t used;                  /* кадр последнего вывода (p2c_ft_frame) — для вытеснения слотов */
} P2cFtEntry;

/* Текст кадра (Font.render): строка и признак чёрного цвета. */
typedef struct { const P2cStr *text; uint8_t black; } P2cFtText;

extern uint8_t p2c_ft_frame;
extern uint8_t p2c_ft_foreign;
extern uint8_t p2c_ft_skip_swap;
extern uint8_t p2c_ft_swapped;
/* Вызывается перед первой загрузкой после чужого вывода (0 — нет): чужой кадр гаснет, пока RAM_G
 * переписывается изображениями этой программы. */
extern void (*p2c_ft_foreign_fade)(void);
extern uint16_t p2c_ft_dropped;
extern uint16_t p2c_ft_missing;
extern uint16_t p2c_ft_uploads;
extern uint16_t p2c_ft_blits;
/* Буфер display list — по постоянному чётному адресу (см. p2c_z80_ft812.c). */
#define P2C_DL_SIZE 256u
#define p2c_dl_buffer ((uint8_t *)P2C_Z80_DL_BUFFER)
extern uint16_t p2c_dl_fill;
extern uint16_t p2c_dl_sent;
extern uint8_t p2c_ft_swap_wait;
extern uint8_t p2c_ft_drawn;
extern uint8_t p2c_ft_list_open;       /* 1 — заголовок display list кадра уже выведен */
extern uint8_t p2c_ft_handle;
extern uint8_t p2c_ft_cell;
extern uint16_t p2c_ft_c_w;
extern uint16_t p2c_ft_c_h;
extern uint32_t p2c_ft_c_next;
extern uint16_t p2c_ft_hand_a;
extern uint16_t p2c_ft_hand_b;
extern uint8_t p2c_ft_uploading;
extern P2cFtEntry p2c_ft_entry;
extern uint16_t p2c_ft_entry_index;
extern uint8_t p2c_ft_fire_previous;
extern uint8_t p2c_ft_start_previous;
extern P2cFtText p2c_ft_texts[8];
extern uint8_t p2c_ft_text_count;
extern const uint16_t p2c_ft_text_glyphs[192];
extern const uint8_t p2c_ft_text_advance[96];

/* Резидентная часть. */
void p2c_ft_address(uint32_t address, uint8_t write);
uint8_t p2c_ft_read8(uint32_t address);
uint16_t p2c_ft_read16(uint32_t address);
void p2c_ft_write8(uint32_t address, uint8_t value);
void p2c_dl(uint32_t word);
void p2c_dl_flush(void);
void p2c_ft_wait_swap(void);
void p2c_ft_read_entry(uint16_t index);
void p2c_ft_write_state(void);
void p2c_ft_draw_entry(uint16_t index, int32_t x, int32_t y);
/* Общий путь p2c_blit при ассемблерном быстром пути (P2C_BLIT_ASM, p2c_z80_blit.s). */
void p2c_blit_c(P2cImage image, int32_t x, int32_t y);

/* Банковая часть. */
void p2c_ft_upload(uint32_t address) __banked;
uint16_t p2c_ft_take_slot(uint8_t cls) __banked;
void p2c_ft_wait_idle(void) __banked;
void p2c_ft_draw_text(uint8_t record, int32_t x, int32_t y) __banked;
void p2c_ft_init(void) __banked;
void p2c_ft_reset(void) __banked;
void p2c_ft_frame_begin(void) __banked;
void p2c_ft_open_list(void) __banked;
void p2c_ft_frame_end(void) __banked;
void p2c_ft_input(uint8_t *start_pressed, uint8_t *input_bits) __banked;
/* Правый Alt (AltGr) из очереди скан-кодов PS/2 ZX Evolution: 1 — нажат (читает очередь, вызывать раз за кадр). */
uint8_t p2c_ft_altgr(void) __banked;

#endif
