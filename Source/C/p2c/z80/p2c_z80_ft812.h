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
#define FT_REG_FRAMES 0x302004UL
#define FT_REG_VCYCLE 0x302040UL
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
/* Развёртка FT812 59 ↔ 55 Гц (Esc на титуле): REG_VCYCLE — сразу, надпись «VSync 59 Hz» / «VSync 55 Hz» — в кадрах
 * титула до срока или до первого кадра не титула (p2c_ft_label_on = 0). */
void p2c_ft_vsync_toggle(void) __banked;
extern uint8_t p2c_ft_vsync55;         /* 1 — 55 Гц как у M72 (REG_VCYCLE 866), 0 — 59 Гц (806, режим TSLib загрузчика) */
extern uint8_t p2c_ft_label_on;        /* надпись развёртки показывается в кадрах титула */
/* Клавиатура PS/2 из очереди скан-кодов AVR ZX Evolution (читает очередь, вызывать раз за кадр): p2c_kb_moves,
 * p2c_kb_buttons — нажатые клавиши, p2c_kb_wake — в кадре нажата любая клавиша (не автоповтор), p2c_kb_esc — в кадре
 * нажат Esc (переход из «отпущена» в «нажата»: автоповтор не считается, быстрое нажатие с отпусканием в том же кадре —
 * считается). */
void p2c_ft_keyboard(void) __banked;

/* Биты p2c_kb_moves: стрелки — младшая тетрада, P O A Q — старшая, в том же порядке, поэтому направления кадра —
 * (moves | moves >> 4) & 15 с битами GameButtons: вправо 1, влево 2, вниз 4, вверх 8. */
#define P2C_KB_RIGHT 0x01u      /* → (E0 74) */
#define P2C_KB_LEFT 0x02u       /* ← (E0 6B) */
#define P2C_KB_DOWN 0x04u       /* ↓ (E0 72) */
#define P2C_KB_UP 0x08u         /* ↑ (E0 75) */
#define P2C_KB_P 0x10u          /* P (4D) — вправо */
#define P2C_KB_O 0x20u          /* O (44) — влево */
#define P2C_KB_A 0x40u          /* A (1C) — вниз */
#define P2C_KB_Q 0x80u          /* Q (15) — вверх */
/* Биты p2c_kb_buttons. */
#define P2C_KB_SPACE 0x01u      /* Space (29) — огонь */
#define P2C_KB_ENTER 0x02u      /* Enter (5A, у цифрового блока — E0 5A) — огонь */
#define P2C_KB_ALTGR 0x04u      /* правый Alt (E0 11) — Force */
#define P2C_KB_ESC 0x08u        /* Esc (76) — шаг R-9 от клавиш и джойстика ×1 ↔ ×2 (по событию p2c_kb_esc) */
extern uint8_t p2c_kb_moves;
extern uint8_t p2c_kb_buttons;
extern uint8_t p2c_kb_wake;
extern uint8_t p2c_kb_esc;

#endif
