-- Регистровый лог YM2151 для ОДНОЙ звуковой команды, поданной в тишине.
--
-- Зачем отдельно от mame_ym2151_log.lua: тот снимает партитуру из attract-режима,
-- а там идёт демо-игра. У M72 отдельного звукового чипа нет — музыка и SFX
-- играются одним YM2151, поэтому в такой лог вперемешку попадают выстрелы и
-- взрывы демо. Перенесённая партитура начинается верно, а дальше превращается
-- в набор эффектов.
--
-- Тишины между POST и монетой хватает лишь на несколько секунд, а трек идёт
-- минутами: attract успевает дойти до демо-игры, та начинает стрелять, и в лог
-- снова попадает смесь. Поэтому скрипт СНАЧАЛА ВСТАВЛЯЕТ МОНЕТУ и не нажимает
-- Start: с кредитом на счету автомат ждёт игрока и не показывает демо вовсе —
-- проверено, после кадра 654 он не шлёт звуковому Z80 ни одной команды.
--
-- В этой тишине подаётся одна команда музыки, и дальше пишется чистый
-- регистровый лог: посторонних звуков в нём нет.
--
-- Переменные окружения:
--   RTYPE_MUS_CMD    код звуковой команды (десятичный или 0x..)
--   RTYPE_MUS_COIN   кадр вставки монеты (0 — не вставлять)
--   RTYPE_MUS_FRAME  кадр подачи команды (после того, как автомат затих)
--   RTYPE_MUS_EXIT   кадр выхода
--   RTYPE_MUS_OUT    каталог для ym2151_writes.csv

RTYPE_MUS_LOG = RTYPE_MUS_LOG or {}

local command = tonumber(os.getenv("RTYPE_MUS_CMD") or "0x22")
local coin_frame = tonumber(os.getenv("RTYPE_MUS_COIN") or "650")
local at_frame = tonumber(os.getenv("RTYPE_MUS_FRAME") or "700")
local exit_frame = tonumber(os.getenv("RTYPE_MUS_EXIT") or "6000")
local out_dir = os.getenv("RTYPE_MUS_OUT") or "."
local frame = 0
local writes = {}
local fields = {}
local pending_register = nil

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
    local sound_cpu = manager.machine.devices[":soundcpu"]
    if not sound_cpu or not sound_cpu.spaces then
        error("нет :soundcpu или его адресных пространств")
    end
    local space = sound_cpu.spaces["io"]
    if not space then error("у :soundcpu нет io-пространства") end
    RTYPE_MUS_LOG.tap = space:install_write_tap(0x00, 0xFF, "ym2151_music",
        function(offset, data, mask)
            -- Чётный порт — выбор регистра, нечётный — запись значения.
            if offset % 2 == 0 then
                pending_register = data & 0xFF
            elseif pending_register and frame >= at_frame then
                -- Кадры считаются от подачи команды: так поток начинается с нуля.
                writes[#writes + 1] = string.format("%d,%02X,%02X",
                    frame - at_frame, pending_register, data & 0xFF)
            end
        end)
end

-- Команды, поданные автоматом уже после нашей: их быть не должно (с кредитом он
-- молчит), поэтому счётчик служит проверкой чистоты записи, а не фильтром.
local intruders = 0

local function install_watch()
    local space = manager.machine.devices[":maincpu"].spaces["io"]
    if not space then error("у :maincpu нет io-пространства") end
    RTYPE_MUS_LOG.watch = space:install_write_tap(0x00, 0x01, "latch_watch",
        function(offset, data, mask)
            if frame > at_frame and (data & 0xFF) ~= 0 then
                intruders = intruders + 1
            end
            return data
        end)
end

local function send_command()
    local space = manager.machine.devices[":maincpu"].spaces["io"]
    space:write_u16(0x00, command)          -- латч 16-битный
    print(string.format("MUS_CMD frame=%d value=%02X", frame, command))
end

local function process()
    frame = frame + 1
    if frame == 1 then
        collect_fields()
        install_tap()
        install_watch()
    end
    -- Монета без нажатия Start: автомат ждёт игрока и демо не запускает.
    if coin_frame > 0 then
        set_digital(frame >= coin_frame and frame < coin_frame + 8, "Coin 1", "COIN1")
    end
    if frame == at_frame then send_command() end
    if frame >= exit_frame then
        local file = io.open(out_dir .. "/ym2151_writes.csv", "w")
        file:write("frame,register,value\n")
        file:write(table.concat(writes, "\n"))
        file:write("\n")
        file:close()
        print("MUS_LOG " .. tostring(#writes) .. " INTRUDERS " .. tostring(intruders))
        manager.machine:exit()
    end
end

RTYPE_MUS_LOG.frame = emu.add_machine_frame_notifier(function()
    local ok, message = pcall(process)
    if not ok then
        print("MUS_LOG_ERROR frame=" .. tostring(frame) .. " " .. tostring(message))
        manager.machine:exit()
    end
end)
