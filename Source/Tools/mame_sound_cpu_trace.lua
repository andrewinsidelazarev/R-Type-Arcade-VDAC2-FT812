-- Независимый динамический аудит карты sound Z80 аркадного R-Type.
--
-- После POST автомат получает монету и остаётся на тихом экране ожидания.
-- Затем скрипт подаёт все 256 command bytes. Тапы агрегируют, не сохраняя
-- гигантский поток, множества PC и рёбра PC -> program/I/O read/write.
--
-- RTYPE_Z80_OUT       относительный от cwd каталог результата
-- RTYPE_Z80_FIRST     первый command (по умолчанию 0)
-- RTYPE_Z80_LAST      последний command (по умолчанию 255)
-- RTYPE_Z80_GAP       VBlank между commands (по умолчанию 6)

RTYPE_Z80_TRACE = RTYPE_Z80_TRACE or {}

local out_dir = os.getenv("RTYPE_Z80_OUT") or "."
local first_command = tonumber(os.getenv("RTYPE_Z80_FIRST") or "0")
local last_command = tonumber(os.getenv("RTYPE_Z80_LAST") or "255")
local command_gap = tonumber(os.getenv("RTYPE_Z80_GAP") or "6")
local coin_frame = 650
local first_frame = 700
local exit_frame = first_frame + (last_command - first_command + 1) * command_gap + 120
local frame = 0
local fields = {}
local sound_cpu = nil

local pc_hits = {}
local program_reads = {}
local program_writes = {}
local io_reads = {}
local io_writes = {}
local sent = {}

local function pc()
    return sound_cpu.state["PC"].value & 0xFFFF
end

local function hit(table_, key)
    table_[key] = (table_[key] or 0) + 1
end

local function edge_key(current_pc, address)
    return string.format("%04X,%04X", current_pc, address & 0xFFFF)
end

local function collect_fields()
    for _, port in pairs(manager.machine.ioport.ports) do
        for name, field in pairs(port.fields) do
            fields[string.lower(name)] = field
            local token = manager.machine.ioport:input_type_to_token(field.type, field.player)
            if token then fields[string.lower(token)] = field end
        end
    end
end

local function set_digital(active, ...)
    for _, name in ipairs({...}) do
        local field = fields[string.lower(name)]
        if field then field:set_value(active and 1 or 0) return end
    end
end

local function install_taps()
    sound_cpu = manager.machine.devices[":soundcpu"]
    if not sound_cpu or not sound_cpu.spaces then error("нет :soundcpu") end
    local program = sound_cpu.spaces["program"]
    local io = sound_cpu.spaces["io"]
    if not program or not io then error("нет program/io пространства soundcpu") end

    RTYPE_Z80_TRACE.program_read = program:install_read_tap(
        0x0000, 0xFFFF, "rtype_z80_program_read",
        function(offset, data, mask)
            local current_pc = pc()
            hit(pc_hits, string.format("%04X", current_pc))
            hit(program_reads, edge_key(current_pc, offset))
        end)
    RTYPE_Z80_TRACE.program_write = program:install_write_tap(
        0x0000, 0xFFFF, "rtype_z80_program_write",
        function(offset, data, mask)
            hit(program_writes, edge_key(pc(), offset))
        end)
    RTYPE_Z80_TRACE.io_read = io:install_read_tap(
        0x00, 0xFF, "rtype_z80_io_read",
        function(offset, data, mask)
            hit(io_reads, edge_key(pc(), offset))
        end)
    RTYPE_Z80_TRACE.io_write = io:install_write_tap(
        0x00, 0xFF, "rtype_z80_io_write",
        function(offset, data, mask)
            hit(io_writes, edge_key(pc(), offset))
        end)
end

local function write_table(path, header, table_)
    local keys = {}
    for key, _ in pairs(table_) do keys[#keys + 1] = key end
    table.sort(keys)
    local file = assert(io.open(out_dir .. "/" .. path, "w"))
    file:write(header .. ",hits\n")
    for _, key in ipairs(keys) do
        file:write(key .. "," .. tostring(table_[key]) .. "\n")
    end
    file:close()
end

local function finish()
    write_table("pc_hits.csv", "pc", pc_hits)
    write_table("program_reads.csv", "pc,address", program_reads)
    write_table("program_writes.csv", "pc,address", program_writes)
    write_table("io_reads.csv", "pc,address", io_reads)
    write_table("io_writes.csv", "pc,address", io_writes)
    local file = assert(io.open(out_dir .. "/commands.csv", "w"))
    file:write("frame,command\n")
    file:write(table.concat(sent, "\n"))
    file:write("\n")
    file:close()
    print(string.format("Z80_TRACE pc=%d pread=%d pwrite=%d ioread=%d iowrite=%d",
        #pc_hits, #program_reads, #program_writes, #io_reads, #io_writes))
    manager.machine:exit()
end

local function process()
    frame = frame + 1
    if frame == 1 then
        collect_fields()
        install_taps()
    end
    set_digital(frame >= coin_frame and frame < coin_frame + 8,
        "Coin 1", "COIN1")
    if frame >= first_frame and (frame - first_frame) % command_gap == 0 then
        local command = first_command + ((frame - first_frame) // command_gap)
        if command <= last_command then
            manager.machine.devices[":maincpu"].spaces["io"]:write_u16(0x00, command)
            sent[#sent + 1] = string.format("%d,%02X", frame, command)
        end
    end
    if frame >= exit_frame then finish() end
end

RTYPE_Z80_TRACE.frame = emu.add_machine_frame_notifier(function()
    local ok, message = pcall(process)
    if not ok then
        print("Z80_TRACE_ERROR frame=" .. tostring(frame) .. " " .. tostring(message))
        manager.machine:exit()
    end
end)
