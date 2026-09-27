#include <string.h>
#include "pyz80_target_imports.h"

static void none(PyZ80VMValue *value)
{
    memset(value, 0, sizeof(*value)); value->symbol = PYZ80_VM_NO_SYMBOL;
}

uint16_t PyZ80Target_ImportStorageBytes(const PyZ80TargetImportPlan *plan, uint8_t depth)
{
    uint32_t bytes;
    if (!plan || !depth || !plan->module_count || !plan->function_count) return 0u;
    bytes = sizeof(PyZ80TargetImports) + (uint32_t)plan->module_count * (sizeof(PyZ80VMValue) + 1u) +
        (uint32_t)plan->function_count * sizeof(PyZ80VMValue) + (uint32_t)depth * sizeof(PyZ80TargetImportFrame);
    return bytes > 65535UL ? 0u : (uint16_t)bytes;
}

static void symbol(PyZ80VMValue *value, uint16_t key)
{
    none(value); value->kind = PYZ80_VM_VALUE_SYMBOL; value->symbol = key;
}

static uint8_t same(const PyZ80VMValue *a, const PyZ80VMValue *b)
{
    return a->kind == b->kind && a->symbol == b->symbol && a->payload == b->payload;
}

static uint8_t overlaps(const void *left, uint32_t size, const void *right, uint32_t other_size)
{
    uintptr_t a = (uintptr_t)left, b = (uintptr_t)right;
    if (!left || !right || !size || !other_size) return 0u;
    return a <= b ? b - a < size : a - b < other_size;
}

static uint8_t separate(PyZ80TargetScopes *scopes, const void *address, uint32_t size)
{
    PyZ80VM *vm = scopes->vm;
    PyZ80TargetContext *objects = scopes->objects;
    return PyZ80Target_TableStorageSeparate(objects,address,size) &&
        !overlaps(address,size,scopes,sizeof(*scopes)) && !overlaps(address,size,vm,sizeof(*vm)) &&
        !overlaps(address,size,objects,sizeof(*objects)) &&
        !overlaps(address,size,objects->nodes,(uint32_t)objects->node_capacity*sizeof(*objects->nodes)) &&
        !overlaps(address,size,objects->fields,(uint32_t)objects->field_capacity*sizeof(*objects->fields)) &&
        !overlaps(address,size,objects->items,(uint32_t)objects->item_capacity*sizeof(*objects->items)) &&
        !overlaps(address,size,vm->frames,(uint32_t)vm->limits.max_call_depth*sizeof(*vm->frames)) &&
        !overlaps(address,size,vm->generators,(uint32_t)vm->limits.max_generators*sizeof(*vm->generators)) &&
        !overlaps(address,size,vm->locals,((uint32_t)vm->limits.max_call_depth+vm->limits.max_generators)*
            vm->limits.locals_per_frame*sizeof(*vm->locals)) &&
        !overlaps(address,size,vm->argument_scratch,(uint32_t)vm->limits.max_arguments*sizeof(*vm->argument_scratch)) &&
        !overlaps(address,size,scopes->frame_closures,(uint32_t)scopes->frame_capacity*sizeof(*scopes->frame_closures)) &&
        !overlaps(address,size,scopes->binding_scratch,(uint32_t)scopes->binding_capacity*sizeof(*scopes->binding_scratch));
}

static uint8_t plain_find(PyZ80TargetImports *imports, uint16_t module, uint16_t key, PyZ80VMValue *result)
{
    uint8_t status = PyZ80Target_FindField(imports->scopes->objects, &imports->modules[module], key, result);
    if (status != 2u) return status;
    /* Missing attributes on a module with __getattr__ need the callable module
       protocol. Do not silently load a child or skip this observable hook. */
    return PyZ80Target_FindField(imports->scopes->objects, &imports->modules[module],
        imports->plan->metadata_keys[5], result) == 2u ? 2u : 0u;
}

static uint8_t seed(PyZ80TargetImports *imports, uint16_t module, uint8_t depth)
{
    const PyZ80TargetImportPlan *plan = imports->plan;
    PyZ80TargetContext *objects = imports->scopes->objects;
    const PyZ80TargetModuleSpec *spec = &plan->modules[module];
    PyZ80VMValue value, path;
    PyZ80TargetNode *list;
    uint16_t index;
    if (depth >= imports->frame_capacity || imports->states[module] != PYZ80_MODULE_EMPTY ||
        !PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_OBJECT, PYZ80_VM_NO_SYMBOL,
                                 &imports->modules[module])) return 0u;
    imports->states[module] = PYZ80_MODULE_LOADING; /* Cache BEFORE running source. */
    imports->frames[depth].initializer = module;
    for (index = 0u; index < plan->function_count; ++index)
        if (plan->function_modules[index] == module)
            imports->function_globals[index] = imports->modules[module];
    for (index = 0u; index < 4u; ++index) {
        none(&value);
        if (index < 3u) symbol(&value, index == 0u ? spec->name : (index == 1u ? spec->package : spec->file));
        if (!PyZ80Target_StoreField(objects, &imports->modules[module], plan->metadata_keys[index], &value)) return 0u;
    }
    if (spec->is_package) {
        if (objects->items == 0 || objects->item_used >= objects->item_capacity ||
            !PyZ80Target_AllocateNode(objects, PYZ80_TARGET_NODE_LIST, PYZ80_VM_NO_SYMBOL, &path)) return 0u;
        list = &objects->nodes[(uint16_t)path.payload - 1u];
        list->item_start = objects->item_used;
        list->item_count = 1u;
        list->cursor = 1u; /* Capacity of the mutable list's owned item slice. */
        symbol(&objects->items[objects->item_used++], spec->directory);
        if (!PyZ80Target_StoreField(objects, &imports->modules[module], plan->metadata_keys[4], &path)) return 0u;
    }
    return 1u;
}

static uint8_t path_unchanged(PyZ80TargetImports *imports, uint16_t module)
{
    PyZ80TargetContext *objects = imports->scopes->objects;
    PyZ80VMValue path;
    PyZ80TargetNode *node;
    uint16_t link;
    if (!PyZ80Target_LoadField(objects, &imports->modules[module], imports->plan->metadata_keys[4], &path) ||
        path.kind != PYZ80_VM_VALUE_OPAQUE) return 0u;
    link = (uint16_t)path.payload;
    if (!link || link > objects->node_used) return 0u;
    node = &objects->nodes[link - 1u];
    return node->generation == (uint16_t)(path.payload >> 16) && node->kind == PYZ80_TARGET_NODE_LIST &&
        node->item_count == 1u && node->item_start < objects->item_used &&
        objects->items[node->item_start].kind == PYZ80_VM_VALUE_SYMBOL &&
        objects->items[node->item_start].symbol == imports->plan->modules[module].directory;
}

/* 1 cached, 2 deferred, 3 failed. Walk parent links iteratively. */
static uint8_t ensure(PyZ80TargetImports *imports, uint16_t module, uint16_t *function)
{
    const PyZ80TargetImportPlan *plan = imports->plan;
    uint16_t parent, cursor = module, steps = 0u;
    if (module >= plan->module_count) return 3u;
    if (imports->states[module] != PYZ80_MODULE_EMPTY)
        return imports->states[module] <= PYZ80_MODULE_READY ? 1u : 3u;
    for (;;) {
        if (++steps > plan->module_count) return 3u; /* Guard corrupt parent cycles. */
        parent = plan->modules[cursor].parent;
        if (parent == PYZ80_IMPORT_NONE) break;
        if (parent >= plan->module_count || !plan->modules[parent].is_package) return 3u;
        if (imports->states[parent] != PYZ80_MODULE_EMPTY) {
            if (!path_unchanged(imports, parent)) return 3u;
            break;
        }
        cursor = parent;
    }
    *function = plan->modules[cursor].entry;
    /* Let the VM report its precise CALL_OVERFLOW, without allocating a module
       for a frame that cannot be pushed. failed still unwinds active imports. */
    if (imports->scopes->vm->call_depth >= imports->frame_capacity) return 2u;
    if (!seed(imports, cursor, imports->scopes->vm->call_depth)) return 3u;
    return 2u;
}

static uint8_t dispatch(void *raw, PyZ80VM *vm, uint16_t adapter,
    const PyZ80VMValue *args, uint8_t count, PyZ80VMValue *result, uint16_t *function)
{
    PyZ80TargetImports *imports = raw;
    const PyZ80TargetImportPlan *plan = imports->plan;
    PyZ80TargetContext *objects = imports->scopes->objects;
    PyZ80TargetImportFrame *frame;
    const PyZ80TargetImportRequest *request;
    const PyZ80TargetImportFrom *item;
    PyZ80VMValue value;
    uint16_t index, module, id;
    uint8_t status;
    if (vm != imports->scopes->vm || adapter >= plan->adapter_count ||
        !vm->call_depth || vm->call_depth > imports->frame_capacity) return 3u;
    id = plan->dispatch[adapter];
    if (id == PYZ80_IMPORT_NONE) return 0u;
    if (id == PYZ80_IMPORT_FROM) {
        if (count != 2u || args[1].kind != PYZ80_VM_VALUE_SYMBOL || args[1].symbol >= vm->header.constant_count) return 3u;
        for (module = 0u; module < plan->module_count; ++module)
            if (imports->states[module] && same(&args[0], &imports->modules[module])) break;
        if (module == plan->module_count) return 0u; /* Foreign module provider. */
        status = plain_find(imports, module, args[1].symbol, result);
        if (status == 1u) return 1u;
        if (status != 2u) return 3u;
        /* IMPORT_FROM's circular-import fallback consults the cache, and does
           NOT start a missing child here. Import-name handled fromlist loading. */
        for (index = 0u; index < plan->module_count; ++index)
            if (plan->modules[index].parent == module && plan->modules[index].leaf == args[1].symbol && imports->states[index]) {
                *result = imports->modules[index]; return 1u;
            }
        return 3u;
    }
    if (id >= plan->request_count) return 3u;
    request = &plan->requests[id];
    if (count != 4u ||
        (request->name == PYZ80_IMPORT_NONE ? args[0].kind != PYZ80_VM_VALUE_NONE :
            (args[0].kind != PYZ80_VM_VALUE_SYMBOL || args[0].symbol != request->name)) ||
        args[1].kind != PYZ80_VM_VALUE_I32 || args[1].payload != request->level ||
        args[2].kind != PYZ80_VM_VALUE_SERIALIZED || args[2].payload != request->from_constant ||
        args[3].kind != PYZ80_VM_VALUE_SYMBOL || args[3].symbol != request->mode) return 3u;
    if (request->level) {
        if (!PyZ80Target_CurrentGlobals(imports->scopes, plan->modules[request->owner].entry, &value) ||
            !PyZ80Target_LoadField(objects, &value, plan->metadata_keys[1], &value) ||
            value.kind != PYZ80_VM_VALUE_SYMBOL || value.symbol != plan->modules[request->owner].package) return 3u;
    }
    frame = &imports->frames[vm->call_depth - 1u];
    if (frame->request == PYZ80_IMPORT_NONE) { frame->request = id; frame->stage = 0u; }
    if (frame->request != id) return 3u;
    if (!frame->stage) {
        status = ensure(imports, request->target, function);
        if (status != 1u) return status;
        frame->stage = 1u;
    }
    if (plan->modules[request->target].is_package) {
        while (frame->stage <= request->from_count) {
            index = request->from_start + frame->stage - 1u; /* ADD/SUB.U16 bounded by plan slice. */
            item = &plan->from_items[index];
            status = plain_find(imports, request->target, item->name, &value);
            if (!status) return 3u;
            if (status == 2u && item->module != PYZ80_IMPORT_NONE) {
                status = ensure(imports, item->module, function);
                if (status != 1u) return status;
            }
            ++frame->stage;
        }
    }
    *result = imports->modules[request->result];
    frame->request = PYZ80_IMPORT_NONE;
    return 1u;
}

static uint8_t returned(void *raw, PyZ80VM *vm)
{
    PyZ80TargetImports *imports = raw;
    const PyZ80TargetModuleSpec *spec;
    uint16_t module;
    if (vm != imports->scopes->vm || !vm->call_depth || vm->call_depth > imports->frame_capacity) return 0u;
    module = imports->frames[vm->call_depth - 1u].initializer;
    if (module >= imports->plan->module_count || imports->states[module] != PYZ80_MODULE_LOADING) return 0u;
    spec = &imports->plan->modules[module];
    if (spec->parent != PYZ80_IMPORT_NONE &&
        !PyZ80Target_StoreField(imports->scopes->objects, &imports->modules[spec->parent], spec->leaf, &imports->modules[module])) return 0u;
    imports->states[module] = PYZ80_MODULE_READY;
    imports->frames[vm->call_depth - 1u].initializer = PYZ80_IMPORT_NONE;
    return 1u;
}

static void failed(void *raw, PyZ80VM *vm)
{
    PyZ80TargetImports *imports = raw;
    uint16_t index, module;
    (void)vm;
    for (module = 0u; module < imports->plan->module_count; ++module) {
        if (imports->states[module] != PYZ80_MODULE_LOADING) continue;
        imports->states[module] = PYZ80_MODULE_EMPTY;
        none(&imports->modules[module]);
        for (index = 0u; index < imports->plan->function_count; ++index)
            if (imports->plan->function_modules[index] == module) none(&imports->function_globals[index]);
    }
    for (index = 0u; index < imports->frame_capacity; ++index) {
        imports->frames[index].request = PYZ80_IMPORT_NONE;
        imports->frames[index].initializer = PYZ80_IMPORT_NONE;
    }
}

uint8_t PyZ80Target_AttachImports(PyZ80TargetImports *imports,
    PyZ80TargetScopes *scopes, const PyZ80TargetImportPlan *plan,
    PyZ80VMValue *modules, uint8_t *states, PyZ80VMValue *function_globals,
    PyZ80TargetImportFrame *frames, uint8_t frame_capacity)
{
    uint16_t index, parent, steps;
    uint32_t module_bytes, global_bytes, frame_bytes;
    PyZ80VM *vm;
    const PyZ80TargetModuleSpec *module;
    const PyZ80TargetImportRequest *request;
    if (!imports || !scopes || !plan || !modules || !states || !function_globals || !frames ||
        !scopes->vm || !scopes->objects || scopes->function_globals != function_globals ||
        !plan->module_count || !plan->modules || !plan->dispatch || !plan->function_modules ||
        !plan->metadata_keys || !plan->proof_sha256 || (plan->request_count && !plan->requests) ||
        (plan->from_count && !plan->from_items) || plan->request_count >= PYZ80_IMPORT_FROM) return 0u;
    vm = scopes->vm;
    if (vm->status != PYZ80_VM_IDLE || vm->control_hooks || frame_capacity < vm->limits.max_call_depth ||
        plan->function_count != vm->header.function_count || plan->function_count != scopes->function_count ||
        plan->adapter_count != vm->header.adapter_count ||
        memcmp(plan->proof_sha256, vm->image.expected_proof_sha256, 32u) ||
        !PyZ80Target_ImportStorageBytes(plan, frame_capacity)) return 0u;
    module_bytes = (uint32_t)plan->module_count * sizeof(*modules);
    global_bytes = (uint32_t)plan->function_count * sizeof(*function_globals);
    frame_bytes = (uint32_t)frame_capacity * sizeof(*frames);
    if (!separate(scopes,imports,sizeof(*imports)) || !separate(scopes,modules,module_bytes) ||
        !separate(scopes,states,plan->module_count) || !separate(scopes,function_globals,global_bytes) ||
        !separate(scopes,frames,frame_bytes) ||
        overlaps(modules,module_bytes,states,plan->module_count) || overlaps(modules,module_bytes,function_globals,global_bytes) ||
        overlaps(modules,module_bytes,frames,frame_bytes) || overlaps(states,plan->module_count,function_globals,global_bytes) ||
        overlaps(states,plan->module_count,frames,frame_bytes) || overlaps(function_globals,global_bytes,frames,frame_bytes) ||
        overlaps(imports,sizeof(*imports),modules,module_bytes) || overlaps(imports,sizeof(*imports),states,plan->module_count) ||
        overlaps(imports,sizeof(*imports),function_globals,global_bytes) || overlaps(imports,sizeof(*imports),frames,frame_bytes)) return 0u;
    for (index = 0u; index < 6u; ++index) if (plan->metadata_keys[index] >= vm->header.constant_count) return 0u;
    for (index = 0u; index < plan->function_count; ++index) if (plan->function_modules[index] >= plan->module_count) return 0u;
    for (index = 0u; index < plan->module_count; ++index) {
        module = &plan->modules[index];
        if (module->entry >= plan->function_count || plan->function_modules[module->entry] != index ||
            module->name >= vm->header.constant_count || module->leaf >= vm->header.constant_count ||
            module->package >= vm->header.constant_count || module->file >= vm->header.constant_count ||
            module->directory >= vm->header.constant_count || module->is_package > 1u) return 0u;
        parent = module->parent; steps = 0u;
        while (parent != PYZ80_IMPORT_NONE) {
            if (parent >= plan->module_count || !plan->modules[parent].is_package || ++steps >= plan->module_count) return 0u;
            parent = plan->modules[parent].parent;
        }
    }
    for (index = 0u; index < plan->request_count; ++index) {
        request = &plan->requests[index];
        if (request->owner >= plan->module_count || request->target >= plan->module_count || request->result >= plan->module_count ||
            request->from_start > plan->from_count || request->from_count >= PYZ80_IMPORT_NONE ||
            request->from_count > plan->from_count - request->from_start ||
            (request->name != PYZ80_IMPORT_NONE && request->name >= vm->header.constant_count) ||
            request->from_constant >= vm->header.constant_count || request->mode >= vm->header.constant_count) return 0u;
    }
    for (index = 0u; index < plan->from_count; ++index)
        if (plan->from_items[index].name >= vm->header.constant_count ||
            (plan->from_items[index].module != PYZ80_IMPORT_NONE && plan->from_items[index].module >= plan->module_count)) return 0u;
    for (index = 0u; index < plan->adapter_count; ++index)
        if (plan->dispatch[index] < PYZ80_IMPORT_FROM && plan->dispatch[index] >= plan->request_count) return 0u;
    memset(&imports->hooks, 0, sizeof(imports->hooks));
    imports->scopes = scopes; imports->plan = plan; imports->modules = modules;
    imports->function_globals = function_globals; imports->states = states;
    imports->frames = frames; imports->frame_capacity = frame_capacity;
    for (index = 0u; index < plan->module_count; ++index) { none(&modules[index]); states[index] = PYZ80_MODULE_EMPTY; }
    for (index = 0u; index < plan->function_count; ++index) none(&function_globals[index]);
    for (index = 0u; index < frame_capacity; ++index) {
        frames[index].initializer = PYZ80_IMPORT_NONE; frames[index].request = PYZ80_IMPORT_NONE; frames[index].stage = 0u;
    }
    imports->hooks.dispatch = dispatch; imports->hooks.returned = returned;
    imports->hooks.failed = failed; imports->hooks.context = imports;
    imports->hooks.routes = plan->dispatch;
    imports->hooks.roots = modules; imports->hooks.root_count = plan->module_count;
    vm->control_hooks = &imports->hooks;
    return 1u;
}

uint8_t PyZ80Target_StartModule(PyZ80TargetImports *imports, uint16_t module)
{
    PyZ80VM *vm;
    const PyZ80VMControlHooks *hooks;
    uint16_t parent;
    uint16_t remaining = 255u;
    uint8_t status;
    if (!imports || !imports->scopes || !imports->plan || module >= imports->plan->module_count) return PYZ80_VM_ERROR;
    vm = imports->scopes->vm;
    hooks = vm->control_hooks;
    while (hooks && hooks != &imports->hooks && remaining--) hooks = hooks->previous;
    if (hooks != &imports->hooks || vm->status == PYZ80_VM_RUNNING || vm->status == PYZ80_VM_YIELDED ||
        imports->states[module] != PYZ80_MODULE_EMPTY) return PYZ80_VM_ERROR;
    parent = imports->plan->modules[module].parent;
    if (parent != PYZ80_IMPORT_NONE && !imports->states[parent]) return PYZ80_VM_ERROR;
    if (!seed(imports, module, 0u)) { failed(imports, vm); return PyZ80VM_Abort(vm, PYZ80_VM_E_ADAPTER); }
    status = PyZ80VM_Start(vm, imports->plan->modules[module].entry);
    if (status != PYZ80_VM_RUNNING) { failed(imports, vm); return status; }
    vm->frames[0].reserved |= PYZ80_VM_FRAME_CONTROL_RETURN | PYZ80_VM_FRAME_REQUIRE_NONE_RETURN;
    return status;
}
