-- Регистровый лог YM2151 аркадного R-Type.
--
-- Звуковой Z80 пишет в чип через свои io-порты: чётный адрес — номер регистра,
-- нечётный — значение. Тап на запись даёт полную партитуру оригинала: тембры
-- (операторные параметры), ноты, key-on/off и их привязку к кадрам. Это
-- исходные данные для переноса музыки на TurboSound FM (2×YM2203), где
-- регистровая модель OPN родственна OPM.
--
-- Переменные окружения:
--   RTYPE_YM_OUT     каталог для ym2151_writes.csv
--   RTYPE_YM_EXIT    кадр выхода
--   RTYPE_YM_COIN    кадр вставки монеты (0 — не вставлять)
--   RTYPE_YM_START   кадр нажатия Start

RTYPE_YM_LOG = RTYPE_YM_LOG or {}

local out_dir = os.getenv("RTYPE_YM_OUT") or "."
local exit_frame = tonumber(os.getenv("RTYPE_YM_EXIT") or "2400")
local coin_frame = tonumber(os.getenv("RTYPE_YM_COIN") or "650")
local start_frame = tonumber(os.getenv("RTYPE_YM_START") or "720")
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
    RTYPE_YM_LOG.tap = space:install_write_tap(0x00, 0xFF, "ym2151_log",
        function(offset, data, mask)
            -- Чётный порт — выбор регистра, нечётный — запись значения.
            if offset % 2 == 0 then
                pending_register = data & 0xFF
            elseif pending_register then
                writes[#writes + 1] = string.format("%d,%02X,%02X",
                    frame, pending_register, data & 0xFF)
            end
            writes.count = (writes.count or 0)
        end)
    print("YM_TAP installed")
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
    if frame >= exit_frame then
        local file = io.open(out_dir .. "/ym2151_writes.csv", "w")
        file:write("frame,register,value\n")
        file:write(table.concat(writes, "\n"))
        file:write("\n")
        file:close()
        print("YM_LOG " .. tostring(#writes))
        manager.machine:exit()
    end
end

RTYPE_YM_LOG.frame = emu.add_machine_frame_notifier(function()
    local ok, message = pcall(process)
    if not ok then
        print("YM_LOG_ERROR frame=" .. tostring(frame) .. " " .. tostring(message))
        manager.machine:exit()
    end
end)
