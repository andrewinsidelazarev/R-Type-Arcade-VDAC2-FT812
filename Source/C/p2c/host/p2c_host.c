/* Адаптеры ПК для сверки: запись команд вывода и звука, отказы через longjmp.
 * Собирается в DLL проверочной сборки (P2C_CHECKED): Python-сверка вызывает кадр сгенерированного кода, затем читает
 * записанные выводы, звуки, тексты и вызовы порта машины функциями p2c_host_* и сравнивает их с CPython. */
#include "p2c_runtime.h"

#define P2C_HOST_COMMANDS 16384

/* Вывод кадра: изображение (#FFFFFFFF — заливка чёрным, #40000000 | номер — текст, #80000000 | … — ячейка спрайта). */
typedef struct { uint32_t image; int32_t x; int32_t y; } P2cHostCommand;

static P2cHostCommand p2c_host_commands[P2C_HOST_COMMANDS];
static uint32_t p2c_host_command_count;
static int32_t p2c_host_sounds[256];             /* звуковые команды кадра (−1 — старт музыки) */
static uint32_t p2c_host_sound_count;
static int16_t p2c_host_fault;                   /* код последнего отказа (0 — не было) */
static uint8_t p2c_host_typed_bank[256];         /* 1 — у типа ресурса свой банк ячеек (иначе банк — палитра) */
/* Текст кадра (Font.render): строка, сглаживание, цвет. */
typedef struct { const P2cStr *text; uint8_t antialias; uint32_t color; } P2cHostText;
static P2cHostText p2c_host_texts[64];
static uint32_t p2c_host_text_count;
/* Размеры текста считает Python (шрифт pygame): which = 0 — ширина, 1 — высота. */
typedef int32_t (*P2cHostTextMetric)(const uint8_t *text, int32_t length, int32_t antialias, int32_t which);
static P2cHostTextMetric p2c_host_text_metric;

uint16_t p2c_current_line;                       /* место исходника текущей инструкции (P2C_LINE) */
static uint16_t p2c_host_fault_line;             /* место отказа */
extern const char *const p2c_line_names[];       /* «файл:строка» по номеру места (генератор) */

/* Отказ: код и место запоминаются, управление возвращается в точку setjmp вызвавшей функции DLL. */
void p2c_raise(int16_t code) {
    p2c_host_fault = code;
    p2c_host_fault_line = p2c_current_line;
    longjmp(p2c_fault_jump, 1);
}

P2C_EXPORT int32_t p2c_host_fault_code(void) { return p2c_host_fault; }
P2C_EXPORT const char *p2c_host_fault_place(void) { return p2c_line_names[p2c_host_fault_line]; }
/* Текст отказа с явным сообщением (положительный номер — p2c_raise_messages генератора). */
P2C_EXPORT const char *p2c_host_fault_message(int32_t index) {
    return index > 0 ? p2c_raise_messages[index] : "";
}

/* Начало кадра сверки: журналы пусты, отказа нет. */
P2C_EXPORT void p2c_host_begin_frame(void) {
    p2c_host_command_count = 0;
    p2c_host_sound_count = 0;
    p2c_host_text_count = 0;
    p2c_host_fault = 0;
}

/* Журналы кадра для Python: число записей и адрес массива. */
P2C_EXPORT uint32_t p2c_host_command_total(void) { return p2c_host_command_count; }
P2C_EXPORT P2cHostCommand *p2c_host_command_data(void) { return p2c_host_commands; }
P2C_EXPORT uint32_t p2c_host_sound_total(void) { return p2c_host_sound_count; }
P2C_EXPORT int32_t *p2c_host_sound_data(void) { return p2c_host_sounds; }
P2C_EXPORT void p2c_host_set_typed_bank(int32_t resource_type, int32_t present) {
    p2c_host_typed_bank[resource_type & 255] = (uint8_t)(present != 0);
}
P2C_EXPORT void p2c_host_set_text_metric(P2cHostTextMetric metric) { p2c_host_text_metric = metric; }
/* Текст записи index: байты строки, длина, сглаживание, цвет. */
P2C_EXPORT const uint8_t *p2c_host_text_data(int32_t index, int32_t *length, int32_t *antialias,
                                              uint32_t *color) {
    *length = p2c_host_texts[index].text->length;
    *antialias = p2c_host_texts[index].antialias;
    *color = p2c_host_texts[index].color;
    return p2c_host_texts[index].text->data;
}

/* Сборка мусора по запросу сверки (отказ внутри сборки — просто возврат). */
P2C_EXPORT void p2c_host_collect(void) {
    if (setjmp(p2c_fault_jump)) return;
    p2c_collect();
}
P2C_EXPORT uint32_t p2c_host_heap_used(void) { return (uint32_t)p2c_heap_used(); }
void p2c_heap_census(uint32_t *bytes_by_class);
P2C_EXPORT void p2c_host_heap_census(uint32_t *bytes_by_class) { p2c_heap_census(bytes_by_class); }
P2C_EXPORT uint32_t p2c_host_heap_peak(void) { return (uint32_t)p2c_heap_peak(); }

/* Запись вывода в журнал кадра (переполнение — MemoryError). */
static void p2c_host_record(uint32_t image, int32_t x, int32_t y) {
    if (p2c_host_command_count >= P2C_HOST_COMMANDS) p2c_raise(P2C_E_MEMORY);
    p2c_host_commands[p2c_host_command_count].image = image;
    p2c_host_commands[p2c_host_command_count].x = x;
    p2c_host_commands[p2c_host_command_count].y = y;
    p2c_host_command_count++;
}

void p2c_blit(P2cImage image, int32_t x, int32_t y) { p2c_host_record(image, x, y); }
void p2c_fill_black(void) { p2c_host_record(0xFFFFFFFFUL, 0, 0); }
int16_t p2c_target_get_width(void) { return 640; }
int16_t p2c_target_get_height(void) { return 480; }

/* Текстовое изображение: номер записи текста кадра (цвет и сглаживание — в записи). */
P2cImage p2c_text_image(const P2cStr *text, uint8_t antialias, uint32_t color) {
    uint32_t index = p2c_host_text_count;
    if (index >= 64) p2c_raise(P2C_E_MEMORY);
    p2c_host_texts[index].text = text;
    p2c_host_texts[index].antialias = antialias;
    p2c_host_texts[index].color = color;
    p2c_host_text_count++;
    return 0x40000000UL | index;
}

/* Размер текстового изображения через функцию Python (изображение не текст или функции нет — ValueError). */
static int16_t p2c_host_text_size(P2cImage image, int32_t which) {
    P2cHostText *record;
    if ((image & 0xC0000000UL) != 0x40000000UL || p2c_host_text_metric == NULL) p2c_raise(P2C_E_VALUE);
    record = &p2c_host_texts[image & 63];
    return (int16_t)p2c_host_text_metric(record->text->data, record->text->length, record->antialias, which);
}

int16_t p2c_image_get_width(P2cImage image) { return p2c_host_text_size(image, 0); }
int16_t p2c_image_get_height(P2cImage image) { return p2c_host_text_size(image, 1); }

/* Звуковые команды кадра (больше 256 — лишние не пишутся). */
void p2c_sound_play(int32_t command) {
    if (p2c_host_sound_count < 256) p2c_host_sounds[p2c_host_sound_count++] = command;
}

void p2c_sound_start_music(void) {
    if (p2c_host_sound_count < 256) p2c_host_sounds[p2c_host_sound_count++] = -1;
}

/* Порт машины M72 (p2c_entry_runtime.MachinePort): вызовы записываются по порядку, слова
 * рабочего ОЗУ берутся из очереди, которую сверка заполняет результатами CPython.
 * Вызов: вид (1 — новая машина, 2 — шаг, 3 — слово ОЗУ, 4 — показ, 5 — сброс сессии) и до трёх аргументов. */
typedef struct { int32_t kind; int32_t a; int32_t b; int32_t c; } P2cHostPortCall;
static P2cHostPortCall p2c_host_port_calls[64];
static uint32_t p2c_host_port_count;
static int32_t p2c_host_words[64];               /* ответы на чтения слов ОЗУ кадра */
static uint32_t p2c_host_word_count;
static uint32_t p2c_host_word_next;

/* Очередь ответов на чтения слов (до 64) и пустой журнал вызовов порта. */
P2C_EXPORT void p2c_host_set_words(const int32_t *values, int32_t count) {
    int32_t index;
    if (count > 64) count = 64;
    for (index = 0; index < count; index++) p2c_host_words[index] = values[index];
    p2c_host_word_count = (uint32_t)count;
    p2c_host_word_next = 0;
    p2c_host_port_count = 0;
}
P2C_EXPORT uint32_t p2c_host_port_total(void) { return p2c_host_port_count; }
P2C_EXPORT P2cHostPortCall *p2c_host_port_data(void) { return p2c_host_port_calls; }

static void p2c_host_port(int32_t kind, int32_t a, int32_t b, int32_t c) {
    if (p2c_host_port_count >= 64) p2c_raise(P2C_E_MEMORY);
    p2c_host_port_calls[p2c_host_port_count].kind = kind;
    p2c_host_port_calls[p2c_host_port_count].a = a;
    p2c_host_port_calls[p2c_host_port_count].b = b;
    p2c_host_port_calls[p2c_host_port_count].c = c;
    p2c_host_port_count++;
}

void p2c_port_boot(void) { p2c_host_port(1, 0, 0, 0); }
/* Шаг: маска кнопок, START 1 (бит 0) и COIN 1 (бит 1), признак вывода. */
void p2c_port_step(int32_t mask, uint8_t start1, uint8_t coin1, uint8_t render) {
    p2c_host_port(2, mask, start1 | (coin1 << 1), render);
}
/* Слово ОЗУ: следующий ответ очереди (очередь кончилась — ValueError: CPython читал меньше). */
int32_t p2c_port_word(int32_t address) {
    p2c_host_port(3, address, 0, 0);
    if (p2c_host_word_next >= p2c_host_word_count) p2c_raise(P2C_E_VALUE);
    return p2c_host_words[p2c_host_word_next++];
}
void p2c_port_show(void) { p2c_host_port(4, 0, 0, 0); }
void p2c_port_reset_session(void) { p2c_host_port(5, 0, 0, 0); }
/* Мышь: у сверки на ПК мыши нет — только запись вызова. */
void p2c_port_mouse(void) { p2c_host_port(6, 0, 0, 0); }

/* Ячейка спрайта: ключ банка (типовой или палитровый), код и отражения. Бит 31 — ячейка, бит 30 — типовой банк,
 * биты 16…23 — банк, 2…13 — код, 1 — fx, 0 — fy. */
P2cImage p2c_sprite_cell(int32_t palette, int32_t resource_type, int32_t code, uint8_t flip_x, uint8_t flip_y) {
    uint32_t typed = p2c_host_typed_bank[resource_type & 255];
    uint32_t bank = typed ? (uint32_t)(resource_type & 255) : (uint32_t)(palette & 15);
    return 0x80000000UL | (typed << 30) | (bank << 16) | ((uint32_t)(code & 0x0FFF) << 2) |
           ((uint32_t)flip_x << 1) | flip_y;
}
