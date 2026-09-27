-- Deterministic MAME 0.288 reference capture for arcade R-Type (World).
--
-- Environment:
--   RTYPE_MAME_MODE          inventory | attract | stage1 (default: inventory)
--   RTYPE_MAME_OUT           existing output directory
--   RTYPE_MAME_SNAP_FRAMES   comma separated frame numbers
--   RTYPE_MAME_EXIT_FRAME    final dump/exit frame
--   RTYPE_MAME_INVINCIBLE    1 = capture-only World-set invincibility patch
--   RTYPE_MAME_CREDITS_FRAME кадр прыжка в конечные титры (диагностика)
--   RTYPE_MAME_CREDITS_EVENT 1 = событие этапа 1 `$B9D7` создаёт объект титров (диагностика)
--   RTYPE_MAME_LOG_DIRECTOR 1 = писать состояние директора каждый кадр в director.csv
--
-- По умолчанию ROM не меняется. Диагностический invincibility явно включается
-- переменной окружения, действует только внутри процесса MAME и нужен для
-- непрерывной эталонной трассы уровня. В SPG/порт этот patch не попадает.

local mode = os.getenv("RTYPE_MAME_MODE") or "inventory"
local out_dir = os.getenv("RTYPE_MAME_OUT") or "."
local snap_text = os.getenv("RTYPE_MAME_SNAP_FRAMES") or "1,60,120,180,300,600"
local exit_frame = tonumber(os.getenv("RTYPE_MAME_EXIT_FRAME") or "600")
local fire_start = tonumber(os.getenv("RTYPE_MAME_FIRE_START") or "")
local fire_end = tonumber(os.getenv("RTYPE_MAME_FIRE_END") or "")
local fire_button = os.getenv("RTYPE_MAME_FIRE_BUTTON") or "P1_BUTTON1"
local move_start = tonumber(os.getenv("RTYPE_MAME_MOVE_START") or "")
local move_end = tonumber(os.getenv("RTYPE_MAME_MOVE_END") or "")
local move_button = os.getenv("RTYPE_MAME_MOVE_BUTTON") or ""
local disable_periodic_fire = os.getenv("RTYPE_MAME_DISABLE_PERIODIC_FIRE") == "1"
local disable_stage_autoplay = os.getenv("RTYPE_MAME_DISABLE_STAGE_AUTOPLAY") == "1"
local log_vram_writes = os.getenv("RTYPE_MAME_LOG_VRAM_WRITES") == "1"
local log_vram_pc = os.getenv("RTYPE_MAME_LOG_VRAM_PC") == "1"
local log_palette_writes = os.getenv("RTYPE_MAME_LOG_PALETTE_WRITES") == "1"
local log_palette_pc = os.getenv("RTYPE_MAME_LOG_PALETTE_PC") == "1"
local log_palette_state_writes = os.getenv("RTYPE_MAME_LOG_PALETTE_STATE_WRITES") == "1"
local log_spriteram_writes = os.getenv("RTYPE_MAME_LOG_SPRITERAM_WRITES") == "1"
local log_player_writes = os.getenv("RTYPE_MAME_LOG_PLAYER_WRITES") == "1"
local log_object_writes = os.getenv("RTYPE_MAME_LOG_OBJECT_WRITES") == "1"
local log_scroll_state_writes = os.getenv("RTYPE_MAME_LOG_SCROLL_STATE_WRITES") == "1"
local log_rng_calls = os.getenv("RTYPE_MAME_LOG_RNG_CALLS") == "1"
local invincible = os.getenv("RTYPE_MAME_INVINCIBLE") == "1"
-- Диагностический прыжок в конечные титры. Событие этапа 8 `$EEAB` создаёт объект титров
-- (`cx = $0100`, `dx = $EEB5`, аллокатор `$03A6`); инициализатор `$EEB5` ставит полям объекта
-- `+$10 = $88E8` (таблица записей текста `$88E8…$8911`), `+$12 = $30`, `+$14 = $560` и переводит
-- обработчик `+$00` на `$EF09`. Слот директора по линейному `$40000` имеет ту же раскладку полей,
-- поэтому достаточно записать в его слово обработчика `$EEB5`. ROM при этом не меняется, правка
-- живёт только внутри процесса MAME и нужна, чтобы снять эталон титров без прохождения игры.
local credits_frame = tonumber(os.getenv("RTYPE_MAME_CREDITS_FRAME") or "")
-- Тот же прыжок, но по штатному пути аркады: у события этапа 1 `ES:$B9D7` (порог progression $06FC)
-- старший байт команды $6C04 меняется на $BC, и процедура `$1BA7` берёт обработчик из таблицы
-- `ES:$B92D` по смещению $5E — это `$EEAB`, создание объекта титров. Ровно эту же правку образа
-- делает сборка порта (RTYPE_V30_PATCH=1B9DA=BC), поэтому эталон и порт идут одинаково.
local credits_event = os.getenv("RTYPE_MAME_CREDITS_EVENT") == "1"
-- Трасса аттракта: обработчик директора (`$40000`), его таймер (`$4001E`), номер этапа (`$2FCD`)
-- и progression (`$2F4B`) каждый кадр. Нужна как спецификация последовательности демо: какие экраны
-- аркада показывает, в каком порядке и сколько кадров каждый.
local log_director = os.getenv("RTYPE_MAME_LOG_DIRECTOR") == "1"
local director_log = {}
local log_sound = os.getenv("RTYPE_MAME_LOG_SOUND") == "1"
local sound_log = {}
-- Optional deterministic Force probe.  This is diagnostics only: it replaces
-- the permanent DS:$0060 record on one requested MAME frame, then records the
-- native state produced by the unmodified World ROM handlers.  It is used to
-- compare the Python `$2614/$24CE` port against the arcade at exact terrain
-- coordinates without deriving motion from a video.
local force_probe_frame = tonumber(os.getenv("RTYPE_MAME_FORCE_PROBE_FRAME") or "")
local force_probe_x = tonumber(os.getenv("RTYPE_MAME_FORCE_PROBE_X") or "")
local force_probe_y = tonumber(os.getenv("RTYPE_MAME_FORCE_PROBE_Y") or "")
local force_probe_frames = tonumber(os.getenv("RTYPE_MAME_FORCE_PROBE_FRAMES") or "96")
local frame = 0
local fields = {}
local scroll_log = {}
local vram_log = {}
local palette_log = {}
local palette_state_log = {}
local spriteram_log = {}
local player_log = {}
local object_log = {}
local scroll_state_log = {}
local rng_log = {}
local force_probe_log = {}
-- Autoboot chunks are collectible after they return.  Keep subscriptions in a
-- global table; otherwise Lua GC unregisters the notifier after the first frame.
RTYPE_MAME_SUBSCRIPTIONS = RTYPE_MAME_SUBSCRIPTIONS or {}

local function join_path(name)
    local separator = package.config:sub(1, 1)
    if out_dir:sub(-1) == "/" or out_dir:sub(-1) == "\\" then
        return out_dir .. name
    end
    return out_dir .. separator .. name
end

local function parse_frames(text)
    local result = {}
    for item in string.gmatch(text, "[^,]+") do
        local value = tonumber(item)
        if value then result[value] = true end
    end
    return result
end

local snap_frames = parse_frames(snap_text)

local function write_binary(path, data)
    local file, err = io.open(path, "wb")
    if not file then error("cannot open " .. path .. ": " .. tostring(err)) end
    file:write(data)
    file:close()
end

local function write_text(path, text)
    local file, err = io.open(path, "w")
    if not file then error("cannot open " .. path .. ": " .. tostring(err)) end
    file:write(text)
    file:close()
end

local function field_key(field)
    return string.lower(field.name or "")
end

local function inventory()
    print(string.format("RTYPE_REF mode=%s system=%s", mode, manager.machine.system.name))
    for tag, device in pairs(manager.machine.devices) do
        print(string.format("DEVICE %s | %s | %s", tag, device.shortname, device.name))
        if device.spaces then
            for name, space in pairs(device.spaces) do
                print(string.format("SPACE %s.%s width=%d endian=%s mask=%X",
                    tag, name, space.data_width, space.endianness, space.address_mask))
            end
        end
    end
    for tag, share in pairs(manager.machine.memory.shares) do
        print(string.format("SHARE %s size=%d length=%d width=%d endian=%s",
            tag, share.size, share.length, share.bitwidth, share.endianness))
    end
    for tag, region in pairs(manager.machine.memory.regions) do
        print(string.format("REGION %s size=%d width=%d endian=%s",
            tag, region.size, region.bitwidth, region.endianness))
    end
    for tag, port in pairs(manager.machine.ioport.ports) do
        print(string.format("PORT %s active=%X", tag, port.active))
        for name, field in pairs(port.fields) do
            local token = manager.machine.ioport:input_type_to_token(field.type, field.player)
            print(string.format("FIELD %s | %s | player=%d mask=%X token=%s",
                tag, name, field.player, field.mask, token or ""))
            fields[field_key(field)] = field
            fields[string.lower(name)] = field
            if token then fields[string.lower(token)] = field end
        end
    end
    for tag, screen in pairs(manager.machine.screens) do
        print(string.format("SCREEN %s %dx%d refresh=%.9f", tag,
            screen.width, screen.height, screen.refresh))
    end
    for tag, palette in pairs(manager.machine.palettes) do
        print(string.format("PALETTE %s entries=%d", tag, palette.entries))
    end
end

local function find_field(...)
    local names = {...}
    for _, name in ipairs(names) do
        local value = fields[string.lower(name)]
        if value then return value end
    end
    return nil
end

local function set_digital(active, ...)
    local field = find_field(...)
    if field then
        field:set_value(active and 1 or 0)
    elseif active then
        print("INPUT_MISSING " .. table.concat({...}, "|"))
    end
end

local function apply_inputs()
    if mode ~= "stage1" then return end

    -- One credit, then one-player start.  Generous gaps make the sequence
    -- independent of host speed; timing is in emulated frames.
    -- R-Type performs a long ROM/RAM/video test before accepting controls.
    set_digital(frame >= 650 and frame < 658, "Coin 1", "COIN1")
    set_digital(frame >= 720 and frame < 728,
        "1 Player Start", "Start 1", "START1")

    -- Keep R-9 away from the first wall and fire periodically.  The sequence is
    -- reference capture only; it is not used as gameplay data.
    set_digital(not disable_stage_autoplay and frame >= 840 and frame < 900,
        "P1 Down", "P1_DOWN")
    local firing
    if fire_start and fire_end then
        firing = frame >= fire_start and frame < fire_end
    elseif disable_periodic_fire or disable_stage_autoplay then
        firing = false
    else
        firing = frame >= 800 and ((frame % 36) < 5)
    end
    set_digital(firing, fire_button)
    if move_start and move_end and move_button ~= "" then
        local moving = frame >= move_start and frame < move_end
        if move_button == "P1_UP" then
            set_digital(moving, "P1 Up", "P1_UP")
        elseif move_button == "P1_DOWN" then
            set_digital(moving, "P1 Down", "P1_DOWN")
        elseif move_button == "P1_LEFT" then
            set_digital(moving, "P1 Left", "P1_LEFT")
        elseif move_button == "P1_RIGHT" then
            set_digital(moving, "P1 Right", "P1_RIGHT")
        else
            error("unknown movement input " .. move_button)
        end
    end
end

local function apply_capture_patch()
    if not invincible then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then error("invincibility: program space unavailable") end
    -- Pugsy XML cheat for rtype World: collision/flicker flag + JZ -> JMP.
    local region = manager.machine.memory.regions[":maincpu"] or
        manager.machine.memory.regions["maincpu"]
    if not region then error("invincibility: maincpu region unavailable") end
    program:write_u8(0x42fc6, 0x01)
    region:write_u8(0x025d3, 0xeb)
    if program:read_u8(0x025d3) ~= 0xeb then
        error("invincibility: ROM patch did not stick")
    end
end

local function log_director_frame()
    if not log_director then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    director_log[#director_log + 1] = string.format("%d,%04X,%04X,%d,%04X", frame,
        program:read_u16(0x40000), program:read_u16(0x4001E),
        program:read_u8(0x42FCD), program:read_u16(0x42F4B))
end

local function apply_credits_event()
    if not credits_event or frame ~= 1 then return end
    local region = manager.machine.memory.regions[":maincpu"] or
        manager.machine.memory.regions["maincpu"]
    if not region then error("credits event: maincpu region unavailable") end
    region:write_u8(0x1B9DA, 0xBC)
    if region:read_u8(0x1B9DA) ~= 0xBC then
        error("credits event: ROM patch did not stick")
    end
end

local function run_credits_jump()
    if not credits_frame or frame ~= credits_frame then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then error("credits jump: program space unavailable") end
    program:write_u16(0x40000, 0xEEB5)
end

local function run_force_probe()
    if not force_probe_frame then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then error("force probe: program space unavailable") end

    local record = 0x40060
    if frame == force_probe_frame then
        if not force_probe_x or not force_probe_y then
            error("force probe: RTYPE_MAME_FORCE_PROBE_X/Y are required")
        end
        program:write_u16(record + 0x00, 0x2614) -- detached handler
        program:write_u8(record + 0x03, 0x00)    -- X fraction
        program:write_u16(record + 0x04, force_probe_x)
        program:write_u8(record + 0x07, 0x00)    -- Y fraction
        program:write_u16(record + 0x08, force_probe_y)
        program:write_u8(record + 0x0A, 0x00)
        program:write_u8(record + 0x0B, 0x00)
        program:write_u16(record + 0x0C, 0x0000) -- return Y velocity
        program:write_u8(record + 0x12, 0x03)    -- full Force level
        program:write_u8(record + 0x13, 0x00)
        program:write_u8(record + 0x14, 0x00)    -- front/right orientation
        program:write_u16(record + 0x30, 0x0900) -- detached Q8 X velocity
        program:write_u8(0x4003E, 0x03)
    end

    if frame >= force_probe_frame and
            frame <= force_probe_frame + force_probe_frames then
        local body_offset = 0
        local body_handler = 0
        for offset = 0x0400, 0x3FC0, 0x40 do
            local handler = program:read_u16(0x40000 + offset)
            if handler == 0x9B9B or handler == 0x9C33 or
                    handler == 0x9C70 or handler == 0x9D30 then
                body_offset = offset
                body_handler = handler
                break
            end
        end
        local body_x = body_offset ~= 0 and
            program:read_u16(0x40000 + body_offset + 0x04) or 0
        local body_hp = body_offset ~= 0 and
            program:read_u8(0x40000 + body_offset + 0x2F) or 0
        local body_damage = body_offset ~= 0 and
            program:read_u8(0x40000 + body_offset + 0x1F) or 0
        force_probe_log[#force_probe_log + 1] = string.format(
            "%d,%04X,%04X,%04X,%04X,%04X,%04X,%04X,%04X,%04X,%02X,%02X",
            frame, program:read_u16(record), program:read_u16(record + 0x04),
            program:read_u16(record + 0x08), program:read_u16(record + 0x0C),
            program:read_u16(record + 0x30), program:read_u16(record + 0x18),
            program:read_u16(record + 0x1A), body_offset, body_handler,
            body_hp, body_damage)
    end
end

local function install_scroll_tap()
    local cpu = manager.machine.devices[":maincpu"]
    if not cpu or not cpu.spaces then return end
    local io = cpu.spaces["io"]
    if not io then
        print("SCROLL_TAP no io address space")
        return
    end
    RTYPE_MAME_SUBSCRIPTIONS.scroll = io:install_write_tap(0x80, 0x87, "rtype_scroll",
        function(offset, data, mask)
            scroll_log[#scroll_log + 1] = string.format(
                "%d,%04X,%04X,%04X", frame, offset, data, mask)
        end)
    print("SCROLL_TAP installed")
end

-- Звуковая защёлка: главный CPU пишет команду звука в порт I/O $00 (у порта тот же смысл, что у
-- `OUT 0` переведённой программы). Лог нужен как эталон звука аттракта: что и на каком кадре шлёт
-- аркада до начала игры.
local function install_sound_tap()
    if not log_sound then return end
    local cpu = manager.machine.devices[":maincpu"]
    if not cpu or not cpu.spaces then return end
    local io = cpu.spaces["io"]
    if not io then
        print("SOUND_TAP no io address space")
        return
    end
    RTYPE_MAME_SUBSCRIPTIONS.sound = io:install_write_tap(0x00, 0x01, "rtype_sound",
        function(offset, data, mask)
            sound_log[#sound_log + 1] = string.format("%d,%04X,%04X,%04X", frame, offset, data, mask)
        end)
    print("SOUND_TAP installed")
end

local function install_vram_taps()
    if not log_vram_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    if not cpu or not cpu.spaces then return end
    local program = cpu.spaces["program"]
    if not program then
        print("VRAM_TAP no program address space")
        return
    end
    local function install(name, first, last, layer)
        RTYPE_MAME_SUBSCRIPTIONS[name] = program:install_write_tap(
            first, last, name,
            function(offset, data, mask)
                if log_vram_pc then
                    local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
                    vram_log[#vram_log + 1] = string.format(
                        "%d,%d,%05X,%04X,%04X,%05X",
                        frame, layer, offset, data, mask, pc)
                else
                    vram_log[#vram_log + 1] = string.format(
                        "%d,%d,%05X,%04X,%04X", frame, layer, offset, data, mask)
                end
            end)
    end
    install("rtype_vram0", 0xd0000, 0xd3fff, 0)
    install("rtype_vram1", 0xd8000, 0xdbfff, 1)
    print("VRAM_TAP installed")
end

local function install_palette_taps()
    if not log_palette_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    local function install(name, first, last, bank)
        RTYPE_MAME_SUBSCRIPTIONS[name] = program:install_write_tap(
            first, last, name,
            function(offset, data, mask)
                if log_palette_pc then
                    local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
                    palette_log[#palette_log + 1] = string.format(
                        "%d,%d,%05X,%04X,%04X,%05X",
                        frame, bank, offset, data, mask, pc)
                else
                    palette_log[#palette_log + 1] = string.format(
                        "%d,%d,%05X,%04X,%04X", frame, bank, offset, data, mask)
                end
            end)
    end
    install("rtype_palette0", 0xc8000, 0xc8bff, 0)
    install("rtype_palette1", 0xcc000, 0xccbff, 1)
    print("PALETTE_TAP installed")
end

local function install_palette_state_taps()
    if not log_palette_state_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    local function install(name, first, last)
        RTYPE_MAME_SUBSCRIPTIONS[name] = program:install_write_tap(
            first, last, name,
            function(offset, data, mask)
                local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
                local bx = cpu.state["BX"] and cpu.state["BX"].value or 0
                local cx = cpu.state["CX"] and cpu.state["CX"].value or 0
                local sp = cpu.state["SP"] and cpu.state["SP"].value or 0
                local ss = cpu.state["SS"] and cpu.state["SS"].value or 0
                local ret = program:read_u16((ss * 16 + sp) & 0xfffff)
                palette_state_log[#palette_state_log + 1] = string.format(
                    "%d,%05X,%04X,%04X,%05X,%04X,%04X,%04X",
                    frame, offset, data, mask, pc, bx, cx, ret)
            end)
    end
    -- `$5271/$52C2`: palette staging buffers and one dirty record per slot.
    install("rtype_palette_stage", 0x42734, 0x42cf3)
    install("rtype_palette_dirty", 0x42dfa, 0x42eaf)
    print("PALETTE_STATE_TAP installed")
end

local function install_spriteram_tap()
    if not log_spriteram_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    RTYPE_MAME_SUBSCRIPTIONS.spriteram = program:install_write_tap(
        0xc0000, 0xc03ff, "rtype_spriteram",
        function(offset, data, mask)
            spriteram_log[#spriteram_log + 1] = string.format(
                "%d,%05X,%04X,%04X", frame, offset, data, mask)
        end)
    print("SPRITERAM_TAP installed")
end

local function install_player_log_tap()
    if not log_player_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    RTYPE_MAME_SUBSCRIPTIONS.player_log = program:install_write_tap(
        0x40000, 0x4003f, "rtype_player_log",
        function(offset, data, mask)
            local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
            player_log[#player_log + 1] = string.format(
                "%d,%05X,%04X,%04X,%05X", frame, offset, data, mask, pc)
        end)
    print("PLAYER_TAP installed")
end

local function install_object_log_tap()
    if not log_object_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    -- DS=4000 object records, scheduler links and the resource pool at
    -- DS:$2D34 all belong to the same ROM object system.  The old $41FFF
    -- upper bound silently missed later pools (including the Stage 1 terrain
    -- modifier parent), so keep the complete main-RAM object area visible.
    RTYPE_MAME_SUBSCRIPTIONS.object_log = program:install_write_tap(
        0x40020, 0x43fff, "rtype_object_log",
        function(offset, data, mask)
            local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
            object_log[#object_log + 1] = string.format(
                "%d,%05X,%04X,%04X,%05X", frame, offset, data, mask, pc)
        end)
    print("OBJECT_TAP installed")
end

local function install_scroll_state_log_tap()
    if not log_scroll_state_writes then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    RTYPE_MAME_SUBSCRIPTIONS.scroll_state_log = program:install_write_tap(
        0x42ec0, 0x42efb, "rtype_scroll_state_log",
        function(offset, data, mask)
            local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
            scroll_state_log[#scroll_state_log + 1] = string.format(
                "%d,%05X,%04X,%04X,%05X", frame, offset, data, mask, pc)
        end)
    print("SCROLL_STATE_TAP installed")
end

local function install_rng_log_tap()
    if not log_rng_calls then return end
    local cpu = manager.machine.devices[":maincpu"]
    local program = cpu and cpu.spaces and cpu.spaces["program"] or nil
    if not program then return end
    -- `$EDE9` saves BX,CX, advances the three-byte state at DS:$2F28, and
    -- stores the new first byte at `$EDFE`.  At that write SP is four bytes
    -- below the near-call return address, so SS:(SP+4) identifies the exact
    -- ROM caller without changing game timing.
    RTYPE_MAME_SUBSCRIPTIONS.rng_log = program:install_write_tap(
        0x42f28, 0x42f29, "rtype_rng_log",
        function(offset, data, mask)
            if offset ~= 0x42f28 then return end
            local pc = cpu.state["PC"] and cpu.state["PC"].value or 0
            -- The same aligned word is written again at `$EE02`; only the
            -- low-byte write at `$EDFE` represents one completed RNG call.
            if pc ~= 0x0edfe then return end
            local ss = cpu.state["SS"] and cpu.state["SS"].value or 0
            local sp = cpu.state["SP"] and cpu.state["SP"].value or 0
            local bp = cpu.state["BP"] and cpu.state["BP"].value or 0
            local ax = cpu.state["AX"] and cpu.state["AX"].value or 0
            local bx = cpu.state["BX"] and cpu.state["BX"].value or 0
            local cx = cpu.state["CX"] and cpu.state["CX"].value or 0
            local stack = (ss * 16 + sp + 4) & 0xfffff
            local ret = program:read_u16(stack)
            local caller = (ret - 3) & 0xffff
            rng_log[#rng_log + 1] = string.format(
                "%d,%05X,%04X,%04X,%05X,%04X,%04X,%04X,%04X,%04X,%04X,%04X,%04X",
                frame, offset, data, mask, pc, ss, sp, ret, caller, bp, ax, bx, cx)
        end)
    print("RNG_TAP installed")
end

local snapshot_ranges = {
    {"workram.bin",   0x40000, 0x43fff},
    {"spriteram.bin", 0xc0000, 0xc03ff},
    {"palette0.bin",  0xc8000, 0xc8bff},
    {"palette1.bin",  0xcc000, 0xccbff},
    {"vram0.bin",     0xd0000, 0xd3fff},
    {"vram1.bin",     0xd8000, 0xdbfff},
}

local function dump_snapshot_memory(prefix)
    local cpu = manager.machine.devices[":maincpu"]
    if not cpu or not cpu.spaces or not cpu.spaces["program"] then
        error("maincpu program space not available")
    end
    local space = cpu.spaces["program"]
    for _, item in ipairs(snapshot_ranges) do
        local data = space:read_range(item[2], item[3], 8)
        write_binary(join_path(prefix .. item[1]), data)
    end
end

local function snapshot()
    local screen = manager.machine.screens[":screen"]
    if not screen then error("MAME screen :screen not found") end
    local name = string.format("frame_%06d.png", frame)
    local path = join_path(name)
    local err = screen:snapshot(path)
    if err then
        error("snapshot failed: " .. tostring(err))
    end
    -- Keep the native indexed framebuffer too.  This is independent of the
    -- host video backend and can be re-rendered with the captured palette.
    local pixels, width, height = screen:pixels()
    write_binary(join_path(string.format("frame_%06d_pixels_u32le.bin", frame)), pixels)
    local palette = screen.palette
    if not palette then error("screen palette not available") end
    local colors = {}
    for pen = 0, palette.entries - 1 do
        colors[#colors + 1] = string.pack("<I4", palette:pen_color(pen))
    end
    write_binary(join_path(string.format("frame_%06d_palette_argb8888_le.bin", frame)),
        table.concat(colors))
    write_text(join_path(string.format("frame_%06d_pixels.txt", frame)),
        string.format("width=%d\nheight=%d\nbytes=%d\n", width, height, #pixels))
    dump_snapshot_memory(string.format("frame_%06d_", frame))
    print("SNAPSHOT " .. path)
end

local function dump_palette()
    local screen = manager.machine.screens[":screen"]
    local palette = screen and screen.palette or nil
    if not palette then error("screen palette not available") end
    local parts = {}
    for pen = 0, palette.entries - 1 do
        parts[#parts + 1] = string.pack("<I4", palette:pen_color(pen))
    end
    write_binary(join_path("palette_argb8888_le.bin"), table.concat(parts))
end

local function dump_runtime()
    local cpu = manager.machine.devices[":maincpu"]
    if not cpu or not cpu.spaces or not cpu.spaces["program"] then
        error("maincpu program space not available")
    end
    local space = cpu.spaces["program"]
    local ranges = {
        {"workram.bin",   0x40000, 0x43fff},
        {"spriteram.bin", 0xc0000, 0xc03ff},
        {"palette0.bin",  0xc8000, 0xc8bff},
        {"palette1.bin",  0xcc000, 0xccbff},
        {"vram0.bin",     0xd0000, 0xd3fff},
        {"vram1.bin",     0xd8000, 0xdbfff},
        {"soundram.bin",  0xe0000, 0xeffff},
    }
    local meta = {
        "format=1",
        "mame=mame0288",
        "set=rtype",
        "mode=" .. mode,
        "invincible=" .. tostring(invincible),
        "frame=" .. tostring(frame),
    }
    for _, item in ipairs(ranges) do
        local data = space:read_range(item[2], item[3], 8)
        write_binary(join_path(item[1]), data)
        meta[#meta + 1] = string.format("range=%s,%05X,%05X,%d",
            item[1], item[2], item[3], #data)
    end
    dump_palette()
    write_text(join_path("scroll_writes.csv"),
        "frame,address,data,mask\n" .. table.concat(scroll_log, "\n") .. "\n")
    if log_sound then
        write_text(join_path("sound_writes.csv"),
            "frame,port,data,mask\n" .. table.concat(sound_log, "\n") .. "\n")
    end
    if log_director then
        write_text(join_path("director.csv"),
            "frame,handler,timer,stage,progression\n" .. table.concat(director_log, "\n") .. "\n")
    end
    if log_vram_writes then
        local vram_header = "frame,layer,address,data,mask\n"
        if log_vram_pc then
            vram_header = "frame,layer,address,data,mask,pc\n"
        end
        write_text(join_path("vram_writes.csv"),
            vram_header .. table.concat(vram_log, "\n") .. "\n")
    end
    if log_palette_writes then
        local palette_header = "frame,bank,address,data,mask\n"
        if log_palette_pc then
            palette_header = "frame,bank,address,data,mask,pc\n"
        end
        write_text(join_path("palette_writes.csv"),
            palette_header ..
            table.concat(palette_log, "\n") .. "\n")
    end
    if log_palette_state_writes then
        write_text(join_path("palette_state_writes.csv"),
            "frame,address,data,mask,pc,bx,cx,ret\n" ..
            table.concat(palette_state_log, "\n") .. "\n")
    end
    if log_spriteram_writes then
        write_text(join_path("spriteram_writes.csv"),
            "frame,address,data,mask\n" ..
            table.concat(spriteram_log, "\n") .. "\n")
    end
    if log_player_writes then
        write_text(join_path("player_writes.csv"),
            "frame,address,data,mask,pc\n" ..
            table.concat(player_log, "\n") .. "\n")
    end
    if log_object_writes then
        write_text(join_path("object_writes.csv"),
            "frame,address,data,mask,pc\n" ..
            table.concat(object_log, "\n") .. "\n")
    end
    if log_scroll_state_writes then
        write_text(join_path("scroll_state_writes.csv"),
            "frame,address,data,mask,pc\n" ..
            table.concat(scroll_state_log, "\n") .. "\n")
    end
    if log_rng_calls then
        write_text(join_path("rng_calls.csv"),
            "frame,address,data,mask,pc,ss,sp,ret,caller,bp,ax,bx,cx\n" ..
            table.concat(rng_log, "\n") .. "\n")
    end
    if force_probe_frame then
        write_text(join_path("force_probe.csv"),
            "frame,handler,x,y,vy,vx,left,right,body_offset,body_handler,body_hp,body_damage\n" ..
            table.concat(force_probe_log, "\n") .. "\n")
    end
    write_text(join_path("runtime.txt"), table.concat(meta, "\n") .. "\n")
    print("RUNTIME_DUMP frame=" .. tostring(frame))
end

local function process_frame()
    frame = frame + 1
    if frame == 1 then
        inventory()
        install_scroll_tap()
        install_sound_tap()
        install_vram_taps()
        install_palette_taps()
        install_palette_state_taps()
        install_spriteram_tap()
        install_player_log_tap()
        install_object_log_tap()
        install_scroll_state_log_tap()
        install_rng_log_tap()
    end
    apply_inputs()
    apply_capture_patch()
    log_director_frame()
    apply_credits_event()
    run_credits_jump()
    run_force_probe()
    if snap_frames[frame] then snapshot() end

    if mode == "inventory" and frame >= 3 then
        manager.machine:exit()
    elseif frame >= exit_frame then
        dump_runtime()
        manager.machine:exit()
    end
end

RTYPE_MAME_SUBSCRIPTIONS.frame = emu.add_machine_frame_notifier(function()
    local ok, message = pcall(process_frame)
    if not ok then
        print("RTYPE_LUA_ERROR frame=" .. tostring(frame) .. " " .. tostring(message))
        manager.machine:exit()
    end
end)
