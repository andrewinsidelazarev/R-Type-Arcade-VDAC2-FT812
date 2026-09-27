-- Изолированная запись звукового эффекта аркадного R-Type.
--
-- Игра передаёт звуковому Z80 команды через io-порт V30 $00 (soundlatch).
-- Между окончанием POST и вставкой монеты игра не шлёт ни одной команды, то
-- есть звуковой тракт молчит. Скрипт дожидается этой тишины, подаёт ОДНУ
-- команду и завершает работу: в WAV остаётся ровно один эффект без музыки.
--
-- Так эффекты не приходится выделять вычитанием дорожек: у R-Type музыка и SFX
-- играются одним YM2151, и разностный метод неизбежно тянет за собой музыку.
--
-- Переменные окружения:
--   RTYPE_SND_CMD     код звуковой команды (десятичный или 0x..)
--   RTYPE_SND_FRAME   кадр подачи команды (по умолчанию 420, уже после POST)
--   RTYPE_SND_EXIT    кадр выхода

RTYPE_SOUND_CAPTURE = RTYPE_SOUND_CAPTURE or {}

local command = tonumber(os.getenv("RTYPE_SND_CMD") or "0x30")
local at_frame = tonumber(os.getenv("RTYPE_SND_FRAME") or "420")
local exit_frame = tonumber(os.getenv("RTYPE_SND_EXIT") or "520")
local frame = 0

local function send_command()
    local space = manager.machine.devices[":maincpu"].spaces["io"]
    -- Латч 16-битный (тап записи показывает маску FFFF).
    space:write_u16(0x00, command)
    print(string.format("SOUND_CMD frame=%d value=%02X", frame, command))
end

local function process()
    frame = frame + 1
    if frame == at_frame then
        send_command()
    end
    if frame >= exit_frame then
        print("SOUND_CAPTURE_DONE frame=" .. tostring(frame))
        manager.machine:exit()
    end
end

RTYPE_SOUND_CAPTURE.frame = emu.add_machine_frame_notifier(function()
    local ok, message = pcall(process)
    if not ok then
        print("SOUND_CAPTURE_ERROR frame=" .. tostring(frame) .. " " .. tostring(message))
        manager.machine:exit()
    end
end)
