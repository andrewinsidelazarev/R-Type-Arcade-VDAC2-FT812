"""Пакет для раздачи: эмулятор Unreal (сборка с TurboSound FM, FT812 — bt8xxemu, GS на Z80) с образом SD, на котором
лежит игра, и файлы для настоящей карты (просьба пользователя 27.09.2026: «сделай в корне проекта zip-архив с
эмулятором и текущим билдом»).

Берётся текущая сборка: `Build/_SD/R-Type VDAC2/` и образ `Build/V30Z80/rtype_sd.img`. Из папки эмулятора
`E:/zx/unreal_x64` (только чтение) — лишь нужное для запуска: `Unreal_tsfm.exe`, его ini (путь к образу SD —
относительный), `bt8xxemu.dll`, `bass.dll`, ПЗУ TS-Conf и GS, документация эмулятора. Каталог пакета —
`Build/Package/<имя>`, архив `<имя>.zip` — в корне проекта.

Запуск: vdac2p_package.py v022 27.09.2026 — версия и дата для имени и README пакета.
"""
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNREAL = Path('E:/zx/unreal_x64')
SD = ROOT / 'Build' / '_SD' / 'R-Type VDAC2'
VERSION, DATE = sys.argv[1], sys.argv[2]
NAME = f'R-Type VDAC2 {VERSION}'                 # публичное имя — без «+» (решение пользователя)
STAGE = ROOT / 'Build' / 'Package' / NAME
ZIP = ROOT / f'{NAME}.zip'
CARD_FILES = ('rtype_vdac2.spg', 'RTYPECOD.PAC', 'RTYPELVL.PAC', 'README.TXT')   # README.TXT — управление и звук (cp1251)
sys.stdout.reconfigure(encoding='utf-8')

(STAGE / 'Emulator' / 'rom').mkdir(parents=True, exist_ok=True)   # набор файлов постоянный — перезапись на месте
(STAGE / 'SD card').mkdir(exist_ok=True)

# эмулятор: только то, что нужно для запуска. Без красных строк в консоли Unreal (просьба пользователя 29.09.2026:
# «ошибки в ini эмулятора исправь»): sos.l — метки ПЗУ отладчика (имя зашито в config.cpp), boot.$b — [AUTOLOAD] diskA
# и [BETA128] BOOT, ПЗУ MoonSound грузится всегда (config.cpp), хотя сам MoonSound в ini выключен; образ жёсткого
# диска [HDD] Image0 (wc.img, 100 МБ) не берётся — строка пустая.
for name in ('Unreal_tsfm.exe', 'bt8xxemu.dll', 'bass.dll', 'bpx.ini', 'CMOS', 'NVRAM', 'sos.l', 'boot.$b'):
    shutil.copy2(UNREAL / name, STAGE / 'Emulator' / name)
for name in ('zxevo.rom', 'bootGS.rom', 'YRW801-M - Yamaha - 1993.rom'):
    shutil.copy2(UNREAL / 'rom' / name, STAGE / 'Emulator' / 'rom' / name)
shutil.copytree(UNREAL / 'doc', STAGE / 'Emulator' / 'doc', dirs_exist_ok=True)
ini = (UNREAL / 'Unreal_tsfm.ini').read_bytes().decode('latin1')
lines = ini.split('\n')
sd_lines = [index for index, line in enumerate(lines) if line.startswith('SDCARD=')]
assert len(sd_lines) == 1, 'в ini эмулятора одна строка SDCARD='
lines[sd_lines[0]] = 'SDCARD=rtype_sd.img' + ('\r' if lines[sd_lines[0]].endswith('\r') else '')
section = ''
for index, line in enumerate(lines):
    if line.startswith('['):
        section = line.strip()
    if section == '[SOUND]' and line.startswith('MoonSound=1'):
        lines[index] = 'MoonSound=0' + line[len('MoonSound=1'):]
    elif section == '[HDD]' and line.startswith('Image0='):
        lines[index] = 'Image0=' + ('\r' if line.endswith('\r') else '')
assert any(line.startswith('mon.maxspeed=') for line in lines), \
    'в Unreal_tsfm.ini нет клавиши mon.maxspeed — переустановить E:/zx/unreal-tsfm/install.py'
(STAGE / 'Emulator' / 'Unreal_tsfm.ini').write_bytes('\n'.join(lines).encode('latin1'))
shutil.copy2(ROOT / 'Build' / 'V30Z80' / 'rtype_sd.img', STAGE / 'Emulator' / 'rtype_sd.img')
shutil.copy2(SD / 'rtype_vdac2.spg', STAGE / 'Emulator' / 'rtype_vdac2.spg')

# файлы для настоящей карты
for name in CARD_FILES:
    shutil.copy2(SD / name, STAGE / 'SD card' / name)

# запуск: SPG в командной строке, рабочий каталог — папка эмулятора (ПЗУ и образ SD — относительными путями)
(STAGE / 'run_emulator.cmd').write_bytes(
    b'@echo off\r\ncd /d "%~dp0Emulator"\r\nstart "" Unreal_tsfm.exe -i Unreal_tsfm.ini rtype_vdac2.spg\r\n')

sums = {name: hashlib.sha256((SD / name).read_bytes()).hexdigest() for name in CARD_FILES}
title = f'R-Type VDAC2 {VERSION} ({DATE})'
readme = f"""{title}
{'=' * len(title)}

Порт аркадного R-Type (Irem M72, набор World) для ZX Evolution с прошивкой TS-Config
и видеоадаптером VDAC2 (FT812). Игра совпадает с оригиналом покадрово.


Запуск в эмуляторе
------------------

Дважды щёлкнуть run_emulator.cmd. Откроется Unreal Speccy (сборка с эмуляцией FT812,
TurboSound FM и General Sound) с образом SD-карты, на котором лежит игра. Сначала экран
загрузки со шкалой BEAM, затем титул; огонь начинает игру.

В образе SD кластер равен сектору (512 байт), поэтому на трети шкалы загрузка стоит около
трёх секунд — это открытие пака уровней. На карте с обычным форматированием FAT32 оно
занимает доли секунды.

Клавиши эмулятора: Shift+Esc — отдать мышь игре (и вернуть системе), Alt+Enter — полный
экран, Alt+F4 — выход.


На настоящей машине
-------------------

Нужны ZX Evolution с TS-Config, VDAC2 (FT812), монитор с режимом 1024x768 и SD-карта FAT32.
Скопировать содержимое папки "SD card" на карту (удобно в одну папку) и запустить
rtype_vdac2.spg. Загрузчик находит паки на карте по имени и размеру. README.TXT в той же
папке — управление и звук (кодировка cp1251).

  rtype_vdac2.spg  SHA-256 {sums['rtype_vdac2.spg']}
  RTYPECOD.PAC     SHA-256 {sums['RTYPECOD.PAC']}
  RTYPELVL.PAC     SHA-256 {sums['RTYPELVL.PAC']}


Управление
----------

Движение  — стрелки, Q/A/O/P, Kempston-джойстик или Kempston-мышь (мышь ведёт корабль).
Огонь     — Space, Enter, огонь джойстика или левая кнопка мыши; удержание заряжает BEAM.
            Огонь же начинает игру с титула (старт есть и на восьмой кнопке джойстика).
Force     — правая кнопка мыши, правый Alt (AltGr) или вторая кнопка джойстика.
Мышь      — средняя кнопка переключает скорость 1x / 0,5x; около трёх секунд в правом
            нижнем углу видна надпись "Mouse speed".
Esc       — в игре шаг корабля с клавиатуры и джойстика 1x / 2x; около трёх секунд в
            правом нижнем углу видна надпись "Keys / joystick speed". На титуле Esc
            переключает кадровую частоту 59 Гц (по умолчанию) / 55 Гц, как у автомата, —
            надпись "VSync" слева внизу; при 55 Гц игра и музыка идут в темпе автомата.


Звук
----

Мелодии — TurboSound FM, эффекты — General Sound / ZX-MultiSound. Без платы GS эффекты
звучат на AY, мелодий нет. Надпись на экране загрузки: "GS / TSFM" или "AY (No GS)".
"""
(STAGE / 'README.txt').write_bytes(readme.replace('\n', '\r\n').encode('utf-8-sig'))

with zipfile.ZipFile(ZIP, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(STAGE.rglob('*')):
        if path.is_file():
            archive.write(path, Path(NAME) / path.relative_to(STAGE))
files = [path for path in STAGE.rglob('*') if path.is_file()]
print(f'пакет: {len(files)} файлов, {sum(path.stat().st_size for path in files) / 2**20:.1f} МБ; '
      f'архив {ZIP.name}: {ZIP.stat().st_size / 2**20:.1f} МБ')
