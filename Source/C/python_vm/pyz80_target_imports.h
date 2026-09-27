#ifndef PYZ80_TARGET_IMPORTS_H
#define PYZ80_TARGET_IMPORTS_H
#include "pyz80_target_scope_runtime.h"

#define PYZ80_IMPORT_NONE 65535u
#define PYZ80_IMPORT_FROM 65534u
enum PyZ80TargetModuleState { PYZ80_MODULE_EMPTY=0, PYZ80_MODULE_LOADING=1, PYZ80_MODULE_READY=2 };

typedef struct PyZ80TargetModuleSpec {
    uint16_t entry, parent, leaf, name, package, file, directory;
    uint8_t is_package;
} PyZ80TargetModuleSpec;
typedef struct PyZ80TargetImportRequest {
    uint16_t owner, target, result, from_start, from_count;
    uint16_t name, level, from_constant, mode;
} PyZ80TargetImportRequest;
typedef struct PyZ80TargetImportFrom { uint16_t name, module; } PyZ80TargetImportFrom;
typedef struct PyZ80TargetImportPlan {
    const PyZ80TargetModuleSpec *modules;
    const PyZ80TargetImportRequest *requests;
    const PyZ80TargetImportFrom *from_items;
    const uint16_t *dispatch, *function_modules, *metadata_keys;
    const uint8_t *proof_sha256;
    uint16_t module_count, request_count, from_count, adapter_count, function_count;
} PyZ80TargetImportPlan;
typedef struct PyZ80TargetImportFrame {
    uint16_t initializer, request, stage;
} PyZ80TargetImportFrame;
#if defined(__SDCC)
typedef char PyZ80ImportAssertFrameBytes[(sizeof(PyZ80TargetImportFrame)==6u) ? 1 : -1];
#endif
typedef struct PyZ80TargetImports {
    PyZ80TargetScopes *scopes;
    const PyZ80TargetImportPlan *plan;
    PyZ80VMControlHooks hooks;
    PyZ80VMValue *modules, *function_globals;
    uint8_t *states;
    PyZ80TargetImportFrame *frames;
    uint8_t frame_capacity;
} PyZ80TargetImports;

/* Mutable loader buffers, INCLUDING its function-globals array but excluding
 * objects/fields/items and the existing scope/VM arena. Zero means invalid
 * dimensions or a >64 KiB resident storage requirement. */
uint16_t PyZ80Target_ImportStorageBytes(const PyZ80TargetImportPlan *plan, uint8_t depth);

/* Caller-owned, disjoint buffers of module_count, module_count, function_count
 * and frame_capacity entries. Attach only to an idle VM. Scopes must use the
 * SAME function_globals array. Cache/module metadata are allocated lazily.
 * All mappings are rooted through scopes->function_globals (each module has
 * an initializer). GC safepoints remain outside callbacks. No heap allocation
 * or recursively executing C interpreter is hidden in this interface.
 * This is a closed regular-source loader, NOT Python's extensible importlib:
 * sys.modules mutation, __getattr__, namespace packages and import hooks are
 * explicit outstanding protocols. Aborting removes all still-loading modules
 * but keeps successfully loaded dependencies, as an uncaught import failure.
 */
uint8_t PyZ80Target_AttachImports(PyZ80TargetImports *imports,
    PyZ80TargetScopes *scopes, const PyZ80TargetImportPlan *plan,
    PyZ80VMValue *modules, uint8_t *states, PyZ80VMValue *function_globals,
    PyZ80TargetImportFrame *frames, uint8_t frame_capacity);

/* Start an uncached module body explicitly. Parent must already be cached;
 * ordinary nested imports load parents on demand. This is NOT Python -m,
 * which additionally needs a __main__/__spec__ bootstrap. Repeated imports
 * inside source code use the cache; explicit Start rejects an existing entry.
 */
uint8_t PyZ80Target_StartModule(PyZ80TargetImports *imports, uint16_t module);
#endif
