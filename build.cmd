@echo off
setlocal
for %%I in ("%~dp0.") do set "RTYPE_ROOT=%%~fI"
for %%I in ("%RTYPE_ROOT%\..") do set "ZX_ROOT=%%~fI"
cd /d "%RTYPE_ROOT%"

if not exist Build mkdir Build

set "PYTHONPATH=%RTYPE_ROOT%\Build\PythonDeps;%RTYPE_ROOT%\Source\Tools;%RTYPE_ROOT%\Source\Python"

if "%PYTHON%"=="" if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
if "%PYTHON%"=="" if exist "%LOCALAPPDATA%\Python\bin\python3.exe" set PYTHON=%LOCALAPPDATA%\Python\bin\python3.exe
if "%PYTHON%"=="" set PYTHON=python
if "%PYTHONUTF8%"=="" set PYTHONUTF8=1
if "%SJASMPLUS%"=="" set SJASMPLUS=%ZX_ROOT%\z80\tsconf_project\exe\sjasmplus\sjasmplus.exe
if "%SPGBLD%"=="" set SPGBLD=%ZX_ROOT%\z80\tsconf_project\exe\spgbld\spgbld.exe
if "%UNREAL_DIR%"=="" set "UNREAL_DIR=%ZX_ROOT%\unreal_x64"

if not exist "%SJASMPLUS%" (
  echo SJASMPLUS not found. Set SJASMPLUS to sjasmplus.exe path.
  exit /b 1
)
if not exist "%SPGBLD%" (
  echo SPGBLD not found. Set SPGBLD to spgbld.exe path.
  exit /b 1
)
if not exist "%UNREAL_DIR%\Unreal.exe" (
  echo Patched Unreal not found in "%UNREAL_DIR%". Set UNREAL_DIR to its exact directory.
  exit /b 1
)

echo === verify supplied M72 World ROM set ===
"%PYTHON%" Source\Tools\m72_arcade.py verify
if errorlevel 1 goto :err

echo === decode M72 tiles and sprites from ROM ===
"%PYTHON%" Source\Tools\m72_arcade.py decode
if errorlevel 1 goto :err

echo === reconstruct exact MAME frame 900 tile layer ===
"%PYTHON%" Source\Tools\m72_scene.py Build\Arcade\MAME\timing_probe --frame 900 --state-frame 898 --fg-x 0x57 --bg-x 0xAF --auto-rows --require-exact --output Build\Arcade\Scenes\stage1_frame0900_exact
if errorlevel 1 goto :err

echo === offline HQ tile upscale 384x256 -^> 640x480 ===
"%PYTHON%" Source\Tools\xbrz_offline.py convert Build\Arcade\Scenes\stage1_frame0900_exact\frame_000900_tiles_native.png Assets\Converted\Arcade\Stage1\STAGE1_FRAME0900_TILES_640x480.png --rgb565 Assets\Converted\Arcade\Stage1\STAGE1_FRAME0900_TILES_640x480_RGB565.bin --source-size 384x256 --target-size 640x480 --factor 6
if errorlevel 1 goto :err

echo === original M72 fire transient -^> General Sound PCM ===
"%PYTHON%" Source\Tools\mame_audio_capture.py
if errorlevel 1 goto :err

echo === exact Python R-9 pitch/launch assets and precomputed frame table ===
"%PYTHON%" Source\Tools\m72_player_assets.py
if errorlevel 1 goto :err
echo === active Python AST + regenerated assets -^> strict TS-Config target ===
"%PYTHON%" Source\Tools\rtype_python_translator.py
if errorlevel 1 goto :err
echo === prove active-Python per-frame draw-record bound before live backend ===
"%PYTHON%" Source\Tools\check_frame_record_bound.py --status --output Build\rtype_python_frame_record_bound_status.json
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\check_frame_record_bound.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\check_rtype_python_assets.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\m72_player_launch_stream.py
if errorlevel 1 goto :err

echo === authentic M72 objects and player shot -^> RAM_G (ARGB4444) ===
"%PYTHON%" Source\Tools\m72_sprite_assets.py
if errorlevel 1 goto :err

echo === title primitives: ROM/MAME -^> logical 640x480 atlas ===
"%PYTHON%" Source\Tools\m72_tile_atlas.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\m72_title_font.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\m72_title_stream.py
if errorlevel 1 goto :err

echo === Stage 1 dynamic tile passes: ROM/MAME -^> HQ primitive atlases ===
"%PYTHON%" Source\Tools\m72_stage_tiles.py
if errorlevel 1 goto :err

echo === Stage 1 MAME VRAM delta -^> compact runtime replay ===
"%PYTHON%" Source\Tools\m72_stage_stream.py
if errorlevel 1 goto :err

echo === all 8 stages: World ROM metatiles -^> offline terrain strips ===
"%PYTHON%" Source\Tools\m72_all_stage_terrain.py
if errorlevel 1 goto :err

echo === complete Z80 target pack: World ROM tables, graphics, 8-stage terrain/events ===
"%PYTHON%" Source\Tools\m72_target_pack.py
if errorlevel 1 goto :err

echo === late-stage V30 controllers -^> precomputed Z80 tables ===
"%PYTHON%" Source\Tools\m72_stage_controller_tables.py
if errorlevel 1 goto :err

echo === native M72 coordinates -^> precomputed FT812 vertex tables ===
"%PYTHON%" Source\Tools\m72_ft812_coordinate_tables.py
if errorlevel 1 goto :err

echo === precompute native M72 collision endpoints ===
"%PYTHON%" Source\Tools\m72_collision_tables.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\m72_fixed_player_tables.py
if errorlevel 1 goto :err

echo === compact per-level RTZ2 packs for SD/FAT32 loading ===
"%PYTHON%" Source\Tools\m72_stage_packs.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\check_stage_packs.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\make_stage_sd_image.py
if errorlevel 1 goto :err

echo === split M72 RAM_G + General Sound pages + spgbld ini ===
"%PYTHON%" Source\Tools\split_sprites.py
if errorlevel 1 goto :err

echo === prove complete FT812 frame budget before assembler or SPG ===
"%PYTHON%" Source\Tools\check_frame_fragment_budget.py --status --output Build\rtype_python_frame_budget_status.json
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\check_frame_fragment_budget.py
if errorlevel 1 goto :err

echo === sjasmplus ===
"%SJASMPLUS%" Source\ASM\main.asm --syntax=ab --lst=Build\rtype.lst --sym=Build\rtype.sym
if errorlevel 1 goto :err

echo === object-bank CALL/JP residency audit ===
"%PYTHON%" Source\Tools\check_object_bank_calls.py
if errorlevel 1 goto :err

echo === spgbld ===
"%SPGBLD%" -b spgbld_rtype.ini Build\rtype_vdac2.spg
if errorlevel 1 goto :err

echo === compiled C FT812 queue and practical scanline budget ===
"%PYTHON%" Source\Tools\sim_hq_sprite_queue_check.py
if errorlevel 1 goto :err
"%PYTHON%" Source\Tools\sim_ft812_page_dma_chunking_check.py
if errorlevel 1 goto :err

echo === deploy current SPG to patched Unreal ===
copy /y "Build\rtype_vdac2.spg" "%UNREAL_DIR%\rtype_vdac2.spg" >nul
if errorlevel 1 goto :err

echo === done ===
goto :eof

:err
echo BUILD FAILED
exit /b 1
