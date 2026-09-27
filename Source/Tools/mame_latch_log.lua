-- Лог команд звукового латча аркадного R-Type.
--
-- V30 передаёт звуковому Z80 команды через io-порт $00. Регистровый лог YM2151
-- показывает, ЧТО зазвучало, но не показывает, ПО КАКОЙ команде: музыка и
-- эффекты идут через один чип и в логе неразличимы. Этот тап даёт вторую
-- половину картины — последовательность команд с привязкой к кадрам.
--
-- Отсюда видно, какая команда запускает музыку уровня: скрипт вставляет монету
-- и жмёт Start, и первая команда после старта игры — искомый BGM. Заодно видно
-- поток команд эффектов во время демо, из-за которых лог attract-режима и
-- оказался смесью музыки со стрельбой.
--
-- Переменные окружения:
--   RTYPE_LATCH_OUT    каталог для latch_commands.csv (только относительный:
--                      io.open в Lua не открывает пути с кириллицей)
--   RTYPE_LATCH_EXIT   кадр выхода
--   RTYPE_LATCH_COIN   кадр вставки монеты (0 — не вставлять)
--   RTYPE_LATCH_START  кадр нажатия Start
--   RTYPE_LATCH_FIRE   кадр нажатия огня (0 — не стрелять)

RTYPE_LATCH_LOG = RTYPE_LATCH_LOG or {}

local out_dir = os.getenv("RTYPE_LATCH_OUT") or "."
local exit_frame = tonumber(os.getenv("RTYPE_LATCH_EXIT") or "3000")
local coin_frame = tonumber(os.getenv("RTYPE_LATCH_COIN") or "650")
local start_frame = tonumber(os.getenv("RTYPE_LATCH_START") or "720")
local fire_frame = tonumber(os.getenv("RTYPE_LATCH_FIRE") or "0")
local fire_hold = tonumber(os.getenv("RTYPE_LATCH_FIREHOLD") or "4")
local frame = 0
local commands = {}
local fields = {}

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

local function install_tap()
    local space = manager.machine.devices[":maincpu"].spaces["io"]
    if not space then error("у :maincpu нет io-пространства") end
    RTYPE_LATCH_LOG.tap = space:install_write_tap(0x00, 0x01, "latch_log",
        function(offset, data, mask)
            commands[#commands + 1] = string.format("%d,%02X", frame, data & 0xFF)
        end)
end

local function process()
    frame = frame + 1
    if frame == 1 then
        collect_fields()
        install_tap()
    end
    if coin_frame > 0 then
        set_digital(frame >= coin_frame and frame < coin_frame + 8, "Coin 1", "COIN1")
        set_digital(frame >= start_frame and frame < start_frame + 8,
            "1 Player Start", "Start 1", "START1")
    end
    -- Одиночное нажатие огня: команда, пришедшая сразу после него, и есть
    -- звук выстрела. Определять её по догадке нельзя — код 0x32, который
    -- считался «зарядом», на проверке оказался музыкальным треком.
    if fire_frame > 0 then
        -- Одиночный импульс мог не совпасть с моментом, когда корабль
        -- управляем, поэтому огонь удерживается окном RTYPE_LATCH_FIREHOLD.
        set_digital(frame >= fire_frame and frame < fire_frame + fire_hold,
            "P1 Button 1")
    end
    if frame >= exit_frame then
        local file = io.open(out_dir .. "/latch_commands.csv", "w")
        file:write("frame,command\n")
        file:write(table.concat(commands, "\n"))
        file:write("\n")
        file:close()
        print("LATCH_LOG " .. tostring(#commands))
        manager.machine:exit()
    end
end

RTYPE_LATCH_LOG.frame = emu.add_machine_frame_notifier(function()
    local ok, message = pcall(process)
    if not ok then
        print("LATCH_LOG_ERROR frame=" .. tostring(frame) .. " " .. tostring(message))
        manager.machine:exit()
    end
end)
