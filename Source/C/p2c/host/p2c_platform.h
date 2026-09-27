/* Платформа ПК: проверочная сборка DLL для покадровой сверки с CPython. */
#ifndef P2C_PLATFORM_H
#define P2C_PLATFORM_H

#include <stdint.h>

#define P2C_CHECKED 1
#define P2C_EXPORT __declspec(dllexport)
#define P2C_HEAP_SIZE (8UL * 1024UL * 1024UL)
#define P2C_ROUND(x) ((((size_t)(x)) + 7u) & ~(size_t)7u)

typedef uint32_t P2cSize;
typedef uint32_t P2cImage;

#endif
