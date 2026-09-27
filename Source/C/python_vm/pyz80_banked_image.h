#ifndef PYZ80_BANKED_IMAGE_H
#define PYZ80_BANKED_IMAGE_H
#include "pyz80_whole_program_vm.h"

/* Driver and all callers, destinations, stack and this state must be resident
   outside the mapped 16 KiB window. map saves the previous mapping/IRQ state in
   token. On map failure it must leave hardware unchanged. restore runs after
   EVERY successful map, including rejected copies. Drivers must serialize IRQ
   users of the same window. No TS-Conf port or interrupt policy is guessed here. */
typedef uint8_t (*PyZ80BankMap)(void *context, uint8_t page,
    const uint8_t **window, uint16_t *token);
typedef uint8_t (*PyZ80BankRestore)(void *context, uint16_t token);
typedef struct PyZ80BankedImage {
    PyZ80BankMap map;
    PyZ80BankRestore restore;
    void *context;
    uint32_t size;
    uint8_t first_page;
    uint8_t busy;
} PyZ80BankedImage;

/* PyZ80VMRead-compatible. A failed multi-page read may have written a prefix;
   consumers must decode/commit only after success. No window pointer escapes. */
uint8_t PyZ80Banked_Read(void *raw, uint32_t offset, uint8_t *destination, uint16_t size);
#endif
