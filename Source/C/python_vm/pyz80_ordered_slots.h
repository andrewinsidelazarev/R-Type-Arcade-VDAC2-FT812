#ifndef PYZ80_ORDERED_SLOTS_H
#define PYZ80_ORDERED_SLOTS_H
#include <stdint.h>

/* Порядок Python-списка не зависит от повторного использования физических
   записей. append добавляет индекс в конец; удаление сохраняет остальных.
   Это провайдер ограниченного списка, а не сортировка по игровому приоритету. */
static uint8_t pyz80_slots_append(uint8_t *order, uint8_t *length,
                                 uint8_t capacity, uint8_t slot) {
    uint8_t index;
    if (*length >= capacity || slot >= capacity) return 0;
    for (index = 0; index < *length; ++index)
        if (order[index] == slot) return 0;
    order[*length] = slot;
    ++*length; /* INC: длина списка после записи последнего индекса. */
    return 1;
}

static uint8_t pyz80_slots_remove(uint8_t *order, uint8_t *length, uint8_t slot) {
    uint8_t index = 0;
    while (index < *length && order[index] != slot) ++index;
    if (index == *length) return 0;
    --*length; /* DEC: новая длина ограничивает копирование соседних индексов. */
    while (index < *length) {
        order[index] = order[index + 1];
        ++index;
    }
    return 1;
}
#endif
