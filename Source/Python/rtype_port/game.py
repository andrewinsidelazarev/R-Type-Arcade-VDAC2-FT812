"""Состояние игрового процесса в логических координатах 640×480."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

from .enemies import M72EnemyWorld, STAGE_EVENT_RANGES, read_descriptor
from .bits import PlayerBits
from .force import Force, ForceInput
from .player_lifecycle import PlayerLifecycle
from .stage import M72CollisionSnapshot, Stage

ROOT = Path(__file__).resolve().parents[3]
SPRITE_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
PLAYER_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "Player"

Q8 = 256
MOVE_X = 853
MOVE_Y = 960
PLAYER_W = 53
PLAYER_H = 28
PLAYFIELD_H = 450
# `$4F2F` initializes the fixed shot anchor at `R-9.x+$0008` native.  The
# cropped logical bitmap therefore starts 16 native pixels to the right of
# the R-9 bitmap origin: 16*5/3 = 26 2/3 logical pixels.  The old value came
# from a snapshot after `$4F40` had already advanced the shot once.
SHOT_DX = 6827
SHOT_DY = 3072
SHOT_VX = 6827
SHOT_LIMIT = 3
# ROM `$F548` scans three ordinary-shot records (`SI=$04D6`, stride `$20`).
# Snapshot frame 1253 gives native bounds `$01D4…$01F2,$010C…$0114`
# for sprite top-left `(155,104)`, i.e. the following 640x480 rectangle.
SHOT_HITBOX_DX = -11
SHOT_HITBOX_DY = -1
SHOT_HITBOX_W = 50
SHOT_HITBOX_H = 15
WAVE_DX = 6827
WAVE_DY = 768
WAVE_VX = 3413
# Player object `+$1D` is the literal ROM charge counter: it advances by two
# per VBlank, saturates at $80 and is classified by `$23EA` on FIRE release.
WAVE_MIN_CHARGE = 0x18
WAVE_MAX_CHARGE = 0x80
WAVE_POWER_TABLE = (0, 4, 8, 12, 16, 20)
WAVE_DELAY = 2
# `$1856…$187D`: five power-dependent native collision records.  The Wave
# assets all start at descriptor origin (-8,-8), so the native object anchor
# lies 8 pixels right/down from their offline-cropped top-left.
WAVE_HITBOX_RADII = {
    4: (2, 16, 8, 8),
    8: (12, 22, 8, 8),
    12: (12, 28, 8, 8),
    16: (12, 20, 8, 8),
    20: (12, 30, 8, 8),
}
PITCH_NEUTRAL = 20
PITCH_MAX = 39
PITCH_CROP_TOP = (0, 1, 1, 1, 1)
INTRO_FRAMES = 226
CHARGE_FIRST_VISIBLE = 0x0F
CHARGE_CROP_LEFT = (0, 0, 0, 1, 1, 1, 0, 0)
CHARGE_CROP_TOP = (0, 1, 3, 5, 7, 11, 12, 14)
BEAM_METER_X = 220
BEAM_METER_Y = 454
BEAM_METER_W = 213
HUD_Y = 450
# `$E9E7…$EA1E` writes the seven P1 score records at foreground byte `$013C`:
# tile row 1, source columns 15…21.  The fixed HUD view begins at source
# column 8, so the logical first column is 7, not 2.
HUD_SCORE_FIRST_COLUMN = 7
HUD_SCORE_Y = HUD_Y + 15
HUD_P1_LABEL_FIRST_COLUMN = 3

# Speed-zero direction table selected by `$20EA…$2109` while `$2FC1!=0`.
# It is ES:[ES:$11B0 + 2*speed] = ES:$11BA for speed zero; each direction
# mask indexes one signed Q8 `(vx,vy)` pair.  Masks 1/2 are right/left and
# 4/8 are up/down in the original player handler.
STAGE_EXIT_VELOCITIES = (
    (0x0000, 0x0000), (0x0200, 0x0000), (-0x0200, 0x0000), (0x0000, 0x0000),
    (0x0000, -0x01B0), (0x0160, -0x0140), (-0x0160, -0x0140), (0x0000, 0x0000),
    (0x0000, 0x01B0), (0x0160, 0x0140), (-0x0160, 0x0140), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
)


@dataclass
class StageExitAutopilot:
    """Literal fixed-player `$2084…$2109` path used after a boss latch."""

    x_q8: int
    y_q8: int
    latch: int = 0xFF
    direction: int = 0

    @property
    def native(self) -> tuple[int, int]:
        return ((self.x_q8 >> 8) & 0xFFFF,
                (self.y_q8 >> 8) & 0xFFFF)

    def advance(self) -> tuple[int, int]:
        # `$208C…$2099`: FF selects `(Y=$00E0,X=$0200)`; every other
        # non-zero latch selects `(Y=$0100,X=$0190)`.
        target_y, target_x = ((0x00E0, 0x0200) if self.latch == 0xFF
                              else (0x0100, 0x0190))
        x, y = self.native
        direction = 0
        if abs(x - target_x) >= 4:
            direction |= 0x01 if x < target_x else 0x02
        if abs(y - target_y) >= 4:
            direction |= 0x04 if y > target_y else 0x08
        self.direction = direction
        velocity_x, velocity_y = STAGE_EXIT_VELOCITIES[direction]
        self.x_q8 += velocity_x
        self.y_q8 += velocity_y
        return self.native


def score_tile_codes(score: int) -> tuple[int, ...]:
    """Exact seven HUD codes produced by `$192F/$193A/$191B`."""
    if not 0 <= score <= 9_999_999:
        raise ValueError("score must fit the seven-digit ROM HUD")
    codes = [0x30 + int(character) for character in f"{score:07d}"]
    # `$191B` replaces at most the first six zero characters with blank $11;
    # the seventh cell therefore remains a visible zero for score 0.
    for index in range(6):
        if codes[index] != 0x30:
            break
        codes[index] = 0x11
    return tuple(codes)


def p1_label_visible(frame_counter: int, options: int = 0x0204) -> bool:
    """Single-player label selected by `$1125…$1177` every 16 VBlanks."""
    return not ((options & 0x0200) and (frame_counter & 0x0010))


def advance_pitch(pitch: int, up: bool, down: bool) -> int:
    """Повторить счётчик наклона R-9 из поля arcade-объекта +$14."""
    if up != down:
        return max(0, pitch - 1) if up else min(PITCH_MAX, pitch + 1)
    if pitch < PITCH_NEUTRAL:
        return pitch + 1
    if pitch > PITCH_NEUTRAL:
        return pitch - 1
    return pitch


def beam_native_width(charge: int) -> int:
    """ROM `$4FD2`: внутренняя заполненная часть после четырёх первых единиц."""
    return min(124, max(0, charge - 4))


def wave_power(charge: int) -> int:
    """ROM `$23EA` classification followed by table `ES:$188C`."""
    if charge < 0x18:
        return 0
    if charge < 0x30:
        return 4
    if charge < 0x48:
        return 8
    if charge < 0x50:
        return 12
    if charge < 0x68:
        return 16
    return 20


def wave_power_tier(power: int) -> int:
    """ROM `$31E3/$3213`: bucket a depleted Wave power into levels 1…5."""
    if power <= 0:
        return 0
    return ((power - 1) & 0x1C) + 4


def advance_wave_charge(charge: int) -> int:
    """ROM `$220A…$2213`: two increments unless `player+$1D >= $80`."""
    return min(WAVE_MAX_CHARGE, charge + 2)


def beam_animation_phase(m72_frame_counter: int) -> int:
    """ROM $244A: (($2EB6 & $001C) * 3) / 2 выбирает запись $1368."""
    return (m72_frame_counter & 0x001C) >> 2


@dataclass(frozen=True)
class LaunchFrame:
    """Результат одного исполнения оригинального сценария появления R-9."""

    player_x: int
    player_y: int
    body_index: int
    effect_kind: int
    effect_x: int
    effect_y: int


@dataclass(frozen=True)
class LaunchStep:
    """Восьмибайтная запись сценария ROM по адресу $10C2..$112A."""

    threshold: int
    velocity_x: int
    body_code: int
    effect_table: int


# Поля буквально перенесены из R-Type World ROM. Обработчик $1F3D сравнивает
# таймер $2F4B с threshold следующей записи, прибавляет velocity_x к 24-битной
# X-координате и передаёт body/effect указатели процедуре вывода $1BCC.
LAUNCH_STEPS = (
    LaunchStep(0x0640, 0x0400, 0x24, 0x1138),
    LaunchStep(0x0649, 0x0400, 0x23, 0x1150),
    LaunchStep(0x0652, 0x0400, 0x22, 0x1168),
    LaunchStep(0x065B, 0x0400, 0x21, 0x1168),
    LaunchStep(0x0664, 0x0400, 0x20, 0x26FE),
    LaunchStep(0x066D, 0x0000, 0x20, 0x26FE),
    LaunchStep(0x0672, -0x0180, 0x20, 0x26FE),
    LaunchStep(0x067B, -0x0180, 0x21, 0x26FE),
    LaunchStep(0x0684, -0x0180, 0x22, 0x26FE),
    LaunchStep(0x068D, -0x0180, 0x22, 0x26FE),
    LaunchStep(0x0696, -0x0180, 0x22, 0x26FE),
    LaunchStep(0x069F, -0x0180, 0x22, 0x26FE),
    LaunchStep(0x06A8, -0x0180, 0x22, 0x26FE),
)

# Четыре шестибайтных кадра каждой таблицы. Индекс в оригинале:
# (($2EB6 & $000C) * 3) / 2, поэтому один кадр держится четыре VBlank.
LAUNCH_EFFECT_TABLES = {
    0x1138: (0x0AA4, 0x0AA6, 0x0AA4, 0x0AA2),
    0x1150: (0x0A23, 0x0AA6, 0x0AA4, 0x0AA6),
    0x1168: (0x0A23, 0x0AA6, 0x0A23, 0x0AA6),
    0x26FE: (0x001F, 0x001F, 0x001F, 0x001F),
}
LAUNCH_EFFECT_KIND = {
    0x001F: 0, 0x0A23: 1, 0x0AA2: 2, 0x0AA4: 3, 0x0AA6: 4,
}


def build_launch_frames() -> tuple[LaunchFrame, ...]:
    """Исполнить исходный ROM-сценарий без покадровой записи MAME."""
    anchor_x = 288 * Q8
    anchor_y = 272
    frames: list[LaunchFrame] = []
    step_index = 0
    for frame in range(INTRO_FRAMES):
        timer = 0x0640 + frame // 2
        while (step_index + 1 < len(LAUNCH_STEPS) and
               timer >= LAUNCH_STEPS[step_index + 1].threshold):
            step_index += 1
        step = LAUNCH_STEPS[step_index]
        anchor_x += step.velocity_x
        anchor_integer_x = anchor_x >> 8

        # Тело: ROM-описатель dx=-16, dy=-6, высота одна 16px ячейка.
        player_x = anchor_integer_x - 16 - 320
        player_y = 384 - (anchor_y - 6) - 16

        phase = ((frame + 10) >> 2) & 3
        effect_code = LAUNCH_EFFECT_TABLES[step.effect_table][phase]
        effect_kind = LAUNCH_EFFECT_KIND[effect_code]
        if effect_code == 0x0A23:
            # Кадр пламени двигателя: dx=-47, dy=-8, высота 16 px.
            effect_x = anchor_integer_x - 47 - 320
            effect_y = 384 - (anchor_y - 8) - 16
        elif effect_code != 0x001F:
            # Большие плазменные кадры: dx=-47, dy=-16, высота 32 px.
            effect_x = anchor_integer_x - 47 - 320
            effect_y = 384 - (anchor_y - 16) - 32
        else:
            # Прозрачный ROM-объект $001F всё равно получает штатные
            # координаты; это важно для полного совпадения состояния M72.
            effect_x = anchor_integer_x - 320
            effect_y = 384 - anchor_y - 16
        frames.append(LaunchFrame(
            player_x, player_y, step.body_code - 0x20,
            effect_kind, effect_x, effect_y,
        ))
    return tuple(frames)


@dataclass
class Shot:
    """Обычный снаряд в логическом Q16.8."""

    x: int
    y: int
    # Authoritative ROM anchor used by `$4F40/$F548`.  Rendering remains in
    # logical 640x480 coordinates, but collision must not round two touching
    # native half-open intervals into a false one-pixel overlap.
    native_x: int | None = None
    native_y: int | None = None
    # Fixed handler state. Enemy `$F548` only clears collision byte `+$17`;
    # `$4F40` notices that on the following pass and enters `$3D17`. Terrain
    # enters the mirrored `$3D37` sequence immediately.
    state: str = "flight"
    terminal_timer: int = 0
    terminal_base: int = 0x2018
    terminal_descriptor: int = 0


def shot_collision_rect(shot: Shot) -> pygame.Rect:
    """Ordinary-shot collision record used by ROM `$F548/$F578`."""
    return pygame.Rect(
        shot.x // Q8 + SHOT_HITBOX_DX,
        shot.y // Q8 + SHOT_HITBOX_DY,
        SHOT_HITBOX_W,
        SHOT_HITBOX_H,
    )


@dataclass
class Wave:
    """Снаряд Wave Cannon и неподвижная вспышка у носа R-9."""

    x: int
    y: int
    release_x: int
    release_y: int
    power: int = 20
    delay: int = WAVE_DELAY
    animation: int = 0
    render_power: int = 0

    def __post_init__(self) -> None:
        if not self.render_power:
            self.render_power = wave_power_tier(self.power)


def wave_collision_rect(wave: Wave) -> pygame.Rect:
    """Wave collision record `SI=$00F6` used by ROM `$F4AA/$F578`."""
    tier = wave_power_tier(wave.power)
    if not tier:
        return pygame.Rect(0, 0, 0, 0)
    left_radius, right_radius, lower_radius, upper_radius = (
        WAVE_HITBOX_RADII[tier])
    left = round((8 - left_radius) * 5 / 3)
    right = round((8 + right_radius) * 5 / 3)
    top = round((8 - upper_radius) * 15 / 8)
    bottom = round((8 + lower_radius) * 15 / 8)
    return pygame.Rect(
        wave.x // Q8 + left,
        wave.y // Q8 + top,
        right - left,
        bottom - top,
    )


@dataclass(frozen=True)
class InputState:
    """Обычные входы игрока; автопилот использует тот же путь, что клавиши."""

    left: bool = False
    right: bool = False
    up: bool = False
    down: bool = False
    fire: bool = False
    force_action: bool = False


def input_from_pygame(keys: pygame.key.ScancodeWrapper,
                      mouse_force: bool = False) -> InputState:
    return InputState(
        left=bool(keys[pygame.K_LEFT]),
        right=bool(keys[pygame.K_RIGHT]),
        up=bool(keys[pygame.K_UP]),
        down=bool(keys[pygame.K_DOWN]),
        fire=bool(keys[pygame.K_SPACE] or keys[pygame.K_z] or
                  keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]),
        force_action=bool(keys[pygame.K_RALT] or mouse_force),
    )


class Game:
    """Самостоятельное состояние текущей Python-версии игры."""

    def __init__(self, play_sfx: Callable[[int], None] | None = None) -> None:
        self.stage = Stage()
        self.enemy_world = M72EnemyWorld(preload_graphics=True)
        self.force = Force(self.enemy_world.rom)
        self.bits = PlayerBits(self.enemy_world.rom)
        self.player_images = [pygame.image.load(str(
            PLAYER_DIR / f"R9_PITCH_{index}_C{0x20 + index:04X}.png"
        )).convert_alpha() for index in range(5)]
        launch_names = (
            "R9_LAUNCH_PLASMA_A_C0A23.png",
            "R9_LAUNCH_EXHAUST_C0AA2.png",
            "R9_LAUNCH_EXHAUST_C0AA4.png",
            "R9_LAUNCH_EXHAUST_C0AA6.png",
        )
        self.launch_effect_images = tuple(
            pygame.image.load(str(PLAYER_DIR / name)).convert_alpha()
            for name in launch_names)
        launch_manifest = json.loads(
            (PLAYER_DIR / "r9_pitch.json").read_text(encoding="utf-8"))
        launch_records = [record for record in launch_manifest["records"]
                          if record["kind"] == "launch"]
        self.launch_effect_crops = {
            int(record["code"]): (int(record["crop_left"]),
                                  int(record["crop_top"]))
            for record in launch_records
        }
        self.launch_frames = build_launch_frames()
        charge_codes = (0x220, 0x222, 0x224, 0x226,
                        0x230, 0x232, 0x234, 0x236)
        self.charge_images = [pygame.image.load(str(
            PLAYER_DIR / f"R9_CHARGE_{index}_C{code:04X}.png"
        )).convert_alpha() for index, code in enumerate(charge_codes)]
        self.beam_meter_images = tuple(
            pygame.image.load(str(
                PLAYER_DIR / f"BEAM_METER_C{charge:03d}.png"
            )).convert_alpha()
            for charge in range(0, WAVE_MAX_CHARGE + 1, 2)
        )
        self.hud_image = pygame.image.load(str(
            PLAYER_DIR / "HUD_FIXED.png")).convert_alpha()
        self.score_digit_images = tuple(
            pygame.image.load(str(
                PLAYER_DIR / f"HUD_SCORE_{digit}_C{0x30 + digit:04X}_P15.png"
            )).convert_alpha()
            for digit in range(10)
        )
        self.life_icon_image = pygame.image.load(str(
            PLAYER_DIR / "HUD_LIFE_C006A_P15.png")).convert_alpha()
        self.p1_label_images = tuple(
            pygame.image.load(str(
                PLAYER_DIR / f"HUD_P1_LABEL_{index}_C{code:04X}_P15.png"
            )).convert_alpha()
            for index, code in enumerate((0x61, 0x62, 0x63, 0x64))
        )
        self.shot_image = pygame.image.load(
            str(SPRITE_DIR / "asset_10_c08f8_p0_16x16_f00.png")).convert_alpha()
        wave_power_dir = SPRITE_DIR / "WavePower"
        self.wave_images = {
            power: tuple(pygame.image.load(str(
                wave_power_dir / f"wave_power_{power:02d}_phase_{phase}.png"
            )).convert_alpha() for phase in range(2))
            for power in WAVE_POWER_TABLE[1:]
        }
        release_names = (
            "asset_17_wave_release_0_c0013_p8_16x16.png",
            "asset_18_wave_release_1_c0043_p8_32x16.png",
            "asset_19_wave_release_2_c0044_p8_32x16.png",
            "asset_20_wave_release_3_c0045_p8_32x16.png",
        )
        self.wave_release_images = [pygame.image.load(str(SPRITE_DIR / name)).convert_alpha()
                                    for name in release_names]
        self.player_x = 233 * Q8
        self.player_y = 192 * Q8
        self.player_pitch = PITCH_NEUTRAL
        self.intro_frame = 0
        # Полное ROM-значение перед MAME VBlank 852. Оно даёт `$02C1` на
        # checkpoint 898 и `$051B` на 1500; launch effect использует свой
        # уже перенесённый локальный phase в `build_launch_frames`.
        self.m72_frame_counter = 0x0292
        self.shots: list[Shot] = []
        # Fire edge `$21E2` sets request byte `$0038`; an idle fixed slot
        # `$04C0/$04E0/$0500` consumes it on the following main pass.  Keep
        # that pass boundary instead of creating and moving a shot early.
        self.pending_shot_spawn = False
        # Fire edge is sampled by the IRQ one display frame before player
        # `$21E2` exposes record byte `$0098` to the fixed matrix wrappers.
        # Python's `fire_matrix` represents the state entered on the following
        # object pass, so its activation is delayed by two active main passes.
        self.pending_matrix_fire: tuple[
            int, int, tuple[int, int] | None, tuple[int, int] | None
        ] | None = None
        self.wave: Wave | None = None
        self.fire_held = False
        self.force_action_held = False
        self.wave_charge = 0
        self.play_sfx = play_sfx or (lambda _name: None)
        self.player_hit = False
        self.lifecycle = PlayerLifecycle()
        self.enemy_world.lifecycle = self.lifecycle
        # Поле запаса жизней HUD (`$F07B`: жизни - 1 значков) меняется только при
        # перерисовке: после задачи очков и кадром позже уменьшения жизней.
        self.hud_lives = max(0, self.lifecycle.lives - 1)
        self.hud_lives_pending = False
        self.death_palette = 0xFF
        self.death_native = (0, 0)
        initial_native = (round((self.player_x // Q8) * 3 / 5) + 0x0150,
                          0x0176 - round((self.player_y // Q8) * 8 / 15))
        # `$2D50` maintains sixteen native X/Y words for the Force return path.
        self.player_native_history = [initial_native] * 16
        self.stage_exit_autopilot: StageExitAutopilot | None = None
        # Temporary diagnostic requested for play-testing.  The hexadecimal
        # value is the literal Stage-1 progression word consumed by the ROM
        # event table, so a reported location maps back to one exact event.
        self.debug_distance_font = pygame.font.Font(None, 20)

    def _sync_boss_hit_flash(self) -> None:
        """Expose ROM `$9CEC` hit-flash state to the background tile palette."""
        bodies = [enemy for enemy in self.enemy_world.enemies
                  if enemy.kind == "dobkeratops_body"]
        self.stage.boss_palette_active = bool(bodies)
        self.stage.boss_hit_flash = any(
            getattr(enemy, "flash_visible", False) for enemy in bodies)

    def _apply_enemy_scroll_velocity_commands(
            self, *, allow_scroll: bool = True) -> None:
        foreground, background = (
            self.enemy_world.take_scroll_velocity_commands())
        stage_init = self.enemy_world.take_stage_init_scroll_command()
        if allow_scroll and stage_init is not None:
            self.stage.m72_scroll.queue_stage_init(*stage_init)
        scroll_reset = self.enemy_world.take_scroll_reset_command()
        if allow_scroll and scroll_reset:
            self.stage.m72_scroll.queue_stage_transition_reset()
        if allow_scroll:
            self.stage.m72_scroll.queue_object_velocity_write(
                foreground, background)
        for command in self.enemy_world.take_sound_commands():
            self.play_sfx(command)

    def _begin_player_death(self) -> None:
        """Исполнить ветку `$2269` без локальной подмены респавна."""
        if not self.lifecycle.begin_death(
                self.enemy_world.stage,
                self.stage.m72_scroll.dispatch_progression):
            return
        self.death_native = self._logical_player_native()

        # ROM очищает weapon/ammo fixed records до установки `$22CD`.
        self.force.sync_level(
            0, self.enemy_world.resources.acquire,
            self.enemy_world.resources.release)
        self.bits.sync_and_update(
            0, self.death_native, 0, self.m72_frame_counter,
            self.enemy_world.resources.acquire,
            self.enemy_world.resources.release)
        self.enemy_world.ram_0033 = 0
        self.enemy_world.ram_0035 = 0
        self.enemy_world.ram_0036 = 0
        self.enemy_world.weapon_pickups = 0
        self.enemy_world.weapon_type = 0
        self.enemy_world.force_level = 0
        self.shots.clear()
        self.pending_shot_spawn = False
        self.pending_matrix_fire = None
        self.wave = None
        self.wave_charge = 0
        self.fire_held = False
        self.force_action_held = False

        self.death_palette = self.enemy_world.resources.acquire(0x09)
        self.stage.m72_scroll.foreground_velocity = 0
        self.stage.m72_scroll.background_velocity = 0
        self.stage.m72_scroll.pending_foreground_velocity = None
        self.stage.m72_scroll.pending_background_velocity = None
        # `$0303` получает именно 0 и `$35`; TargetAudio направит `$35` в GS.
        self.play_sfx(0x00)
        self.play_sfx(0x35)

    def _checkpoint_event_pointer(self, progression: int) -> tuple[int, int]:
        """Повторить поиск `$0FB0` от `ES:$B993` по точному ключу."""
        for first, last in STAGE_EVENT_RANGES.values():
            for pointer in range(first, last + 1, 4):
                if self.enemy_world.rom.word(pointer) == (progression & 0xFFFF):
                    return pointer, last
        raise ValueError(
            f"checkpoint progression ${progression & 0xFFFF:04X} отсутствует в ROM")

    def _restore_checkpoint(self) -> None:
        """Пересобрать ring, очередь объектов и fixed player state."""
        checkpoint = self.lifecycle.checkpoint
        if checkpoint is None:
            raise RuntimeError("респавн без сохранённого checkpoint")

        old_world = self.enemy_world
        score_bcd = bytes(old_world.score_bcd)
        stage_score_bcd = bytes(old_world.stage_score_bcd)
        stage_flags = list(old_world.stage_transition_flags)
        transition_sound_index = old_world.transition_sound_index
        self.stage.reset_checkpoint(checkpoint.stage, checkpoint.ordinal)

        self.enemy_world = M72EnemyWorld(
            stage=checkpoint.stage,
            full_event_stream=True,
            difficulty=old_world.difficulty,
            preload_graphics=True,
            rom=old_world.rom,
            atlas=old_world.atlas)
        pointer, event_last = self._checkpoint_event_pointer(
            checkpoint.progression)
        self.enemy_world.event_pointer = pointer
        self.enemy_world.event_last = event_last
        self.enemy_world.score_bcd[:] = score_bcd
        self.enemy_world.stage_score_bcd[:] = stage_score_bcd
        self.enemy_world.bonus_index = old_world.bonus_index
        self.enemy_world.lifecycle = self.lifecycle
        self.enemy_world.stage_transition_flags[:] = stage_flags
        self.enemy_world.transition_sound_index = transition_sound_index

        self.force = Force(self.enemy_world.rom)
        self.bits = PlayerBits(self.enemy_world.rom)
        self.player_x = round((0x01B0 - 0x0150) * 5 / 3) * Q8
        self.player_y = round((0x0176 - 0x0100) * 15 / 8) * Q8
        self.player_pitch = PITCH_NEUTRAL
        self.player_native_history = [(0x01B0, 0x0100)] * 16
        self.stage_exit_autopilot = None
        self.player_hit = False
        self.death_palette = 0xFF
        self.death_native = (0, 0)

    def _refresh_hud_lives(self) -> None:
        """`$F07B`: поле запаса жизней HUD — жизни минус один значков."""
        self.hud_lives = max(0, self.lifecycle.lives - 1)

    def _take_hud_refresh(self) -> None:
        if self.enemy_world.hud_refresh:
            self.enemy_world.hud_refresh = False
            self._refresh_hud_lives()

    def _update_player_death(self) -> None:
        """Продвинуть остановленный мир и ROM director смерти на VBlank."""
        if self.lifecycle.state == "game_over":
            return
        # Director `$0FA1` перерисовывает HUD кадром позже уменьшения жизней (`$0F03`).
        if self.hud_lives_pending:
            self.hud_lives_pending = False
            self._refresh_hud_lives()
        self.stage.m72_scroll.foreground_velocity = 0
        self.stage.m72_scroll.background_velocity = 0
        self.stage.update()
        self.stage.m72_scroll.foreground_velocity = 0
        self.stage.m72_scroll.background_velocity = 0
        self.enemy_world.update(
            self.stage.m72_scroll.dispatch_progression,
            self.stage.m72_scroll.dispatch_foreground_delta,
            self.m72_frame_counter,
            self.stage.terrain_code,
            self.stage.collision_codes,
            self.death_native,
            self.stage.m72_scroll.dispatch_background_delta,
            self.stage.terrain_address,
            self.stage.erase_foreground,
            self.stage.replace_foreground,
            self.stage.foreground_cell)
        self._apply_enemy_scroll_velocity_commands(allow_scroll=False)
        self._sync_boss_hit_flash()
        self._take_hud_refresh()

        events = self.lifecycle.advance()
        if events.life_decremented:
            self.hud_lives_pending = True
        if events.player_cleared and self.death_palette != 0xFF:
            self.enemy_world.resources.release(self.death_palette)
            self.death_palette = 0xFF
        if events.checkpoint_rebuild:
            # `$55B5` заставляет живые records покинуть очередь до rebuild.
            self.enemy_world.cleanup_active = True
        if events.respawned:
            self._restore_checkpoint()

    def _advance_native_shot(
            self, shot: Shot, collision: M72CollisionSnapshot | None = None,
            replace_terrain: Callable[[int, int, int], None] | None = None
            ) -> bool:
        """Run both `$4F40` eight-pixel steps and terrain probes.

        Return true when `$4FA3 -> $3D37` consumed the active shot on terrain.
        The impact anchor is backed up by eight native pixels exactly as the
        shared cleanup initializer does.
        """
        assert shot.native_x is not None and shot.native_y is not None
        collision = collision or self.stage.collision_snapshot()
        replace_terrain = replace_terrain or self.stage.replace_foreground
        for _step in range(2):
            shot.native_x = (shot.native_x + 8) & 0xFFFF
            foreground, background = collision.collision_codes(
                shot.native_x, shot.native_y)
            if foreground == 0x09F6:
                address = collision.terrain_address(
                    shot.native_x, shot.native_y)
                code, _attribute = collision.foreground_cell(address)
                if code & 0x0FFF == 0x09F6:
                    replace_terrain(address, 0x0FA0, 0)
                    foreground = 0x0FA0
            if foreground < 0x0DFC or background < 0x07D0:
                shot.native_x = (shot.native_x - 8) & 0xFFFF
                shot.x = ((shot.native_x - 0x0148) * 5 * Q8) // 3
                shot.state = "terminal"
                shot.terminal_timer = 3
                shot.terminal_base = 0x2018
                shot.terminal_descriptor = 0
                return True
        shot.x = ((shot.native_x - 0x0148) * 5 * Q8) // 3
        return False

    def _logical_player_native(self) -> tuple[int, int]:
        return (round((self.player_x // Q8) * 3 / 5) + 0x0150,
                0x0176 - round((self.player_y // Q8) * 8 / 15))

    def _advance_stage_exit_autopilot(self) -> tuple[int, int] | None:
        latch = self.enemy_world.player_exit_latch
        if not latch:
            return None
        if self.stage_exit_autopilot is None:
            x, y = self._logical_player_native()
            self.stage_exit_autopilot = StageExitAutopilot(
                x << 8, y << 8, latch)
        else:
            self.stage_exit_autopilot.latch = latch
        native = self.stage_exit_autopilot.advance()
        # Rendering remains in the offline 640x480 coordinate system; native
        # Q8 remains authoritative for object targeting and collision.
        self.player_x = ((self.stage_exit_autopilot.x_q8 - 0x015000) * 5) // 3
        self.player_y = ((0x017600 - self.stage_exit_autopilot.y_q8) * 15) // 8
        return native

    def update(self, inputs: InputState) -> None:
        # Опрос клавиатуры и мыши выполняет app.main (input_from_pygame) до вызова.
        # Исходный IRQ увеличивает $2EB6 один раз на каждый VBlank. Этот
        # счётчик не останавливается при достижении максимального Beam-заряда.
        self.m72_frame_counter = (self.m72_frame_counter + 1) & 0xFFFF
        if self.intro_frame >= INTRO_FRAMES and not self.lifecycle.active:
            self._update_player_death()
            return
        if self.intro_frame >= INTRO_FRAMES:
            self.lifecycle.advance()
        # Player `$216D` runs before both the Force fixed record and the
        # dynamic enemy that may collect another pickup later in this pass.
        self.enemy_world.consume_weapon_pickup()
        if self.intro_frame < INTRO_FRAMES:
            self.stage.update()
            self.enemy_world.update(
                self.stage.m72_scroll.dispatch_progression,
                self.stage.m72_scroll.dispatch_foreground_delta,
                self.m72_frame_counter,
                self.stage.terrain_code,
                self.stage.collision_codes,
                (round((self.player_x // Q8) * 3 / 5) + 0x0150,
                 0x0176 - round((self.player_y // Q8) * 8 / 15)),
                self.stage.m72_scroll.dispatch_background_delta,
                self.stage.terrain_address,
                self.stage.erase_foreground,
                self.stage.replace_foreground,
                self.stage.foreground_cell)
            self._apply_enemy_scroll_velocity_commands()
            self._sync_boss_hit_flash()
            self._take_hud_refresh()
            self._update_intro()
            return
        self.stage.update()
        # Fixed player/Force/weapon records precede the dynamic object list
        # in the ROM scheduler.  Keep their tile reads at that boundary even
        # though Python updates the separately modelled dynamic world first.
        fixed_collision = self.stage.collision_snapshot()
        exit_player_native = self._advance_stage_exit_autopilot()
        enemy_player_native = (exit_player_native or
                               self._logical_player_native())
        self.enemy_world.update(
            self.stage.m72_scroll.dispatch_progression,
            self.stage.m72_scroll.dispatch_foreground_delta,
            self.m72_frame_counter,
            self.stage.terrain_code,
            self.stage.collision_codes,
            enemy_player_native,
            self.stage.m72_scroll.dispatch_background_delta,
            self.stage.terrain_address,
            self.stage.erase_foreground,
            self.stage.replace_foreground,
            self.stage.foreground_cell)
        self._apply_enemy_scroll_velocity_commands()
        self._sync_boss_hit_flash()
        # A fixed-record terrain write occurs before dynamic objects.  When a
        # later dynamic handler changed the same cell, its result must win;
        # applying the delayed Python fixed write would reverse that order.
        # Журнал записей снимка даёт то же множество, что полный перебор
        # 4096 ячеек со сравнением текущей VRAM и снимка.
        dynamic_terrain_changes = fixed_collision.changed_foreground_cells()

        def fixed_replace_terrain(address: int, code: int,
                                  attribute: int) -> None:
            address &= 0x3FFF
            if (address & 0x3FFC) not in dynamic_terrain_changes:
                self.stage.replace_foreground(address, code, attribute)

        if exit_player_native is None:
            if inputs.left:
                self.player_x -= MOVE_X
            if inputs.right:
                self.player_x += MOVE_X
            up = inputs.up
            down = inputs.down
            if up:
                self.player_y -= MOVE_Y
            if down:
                self.player_y += MOVE_Y
            direction = ((1 if inputs.right else 0) |
                         (2 if inputs.left else 0) |
                         (4 if inputs.down else 0) |
                         (8 if inputs.up else 0))
        else:
            rom_direction = self.stage_exit_autopilot.direction
            up = bool(rom_direction & 0x04)
            down = bool(rom_direction & 0x08)
            # Force/Bit input bits use the opposite vertical naming order.
            direction = ((rom_direction & 0x03) |
                         (0x08 if up else 0) |
                         (0x04 if down else 0))
        self.player_pitch = advance_pitch(self.player_pitch, up, down)
        self.player_x = min(max(self.player_x, 0), (640 - PLAYER_W) * Q8)
        self.player_y = min(max(self.player_y, 0), (PLAYFIELD_H - PLAYER_H) * Q8)

        player_native = (exit_player_native or self._logical_player_native())
        self.player_native_history.append(player_native)
        del self.player_native_history[0]
        force_edge = inputs.force_action and not self.force_action_held
        self.force_action_held = inputs.force_action
        force_level_changed = self.force.sync_level(
            self.enemy_world.force_level,
            self.enemy_world.resources.acquire,
            self.enemy_world.resources.release)
        if not force_level_changed:
            self.force.update(
                player_native, tuple(self.player_native_history),
                ForceInput(force_edge, direction), self.m72_frame_counter,
                fixed_collision.collision_codes,
                fixed_collision.terrain_address,
                fixed_collision.foreground_cell, fixed_replace_terrain,
                self.stage.m72_scroll.dispatch_foreground_delta,
                self.play_sfx,
                fixed_collision.background_address,
                fixed_collision.background_cell)
        self.bits.sync_and_update(
            self.enemy_world.ram_0033, player_native, direction,
            self.m72_frame_counter,
            self.enemy_world.resources.acquire,
            self.enemy_world.resources.release,
            fixed_collision.terrain_address,
            fixed_collision.foreground_cell,
            fixed_replace_terrain)

        if self.pending_matrix_fire is not None:
            delay, weapon_type, shot_native, wave_native = (
                self.pending_matrix_fire)
            delay -= 1
            if delay:
                self.pending_matrix_fire = (
                    delay, weapon_type, shot_native, wave_native)
            else:
                self.pending_matrix_fire = None
                self.force.fire_matrix(
                    weapon_type, self.enemy_world.resources.acquire,
                    shot_native, wave_native)
        self.force.update_projectiles(
            fixed_collision.collision_codes,
            lambda rect, damage: self.enemy_world.damage_at(rect, damage),
            self.enemy_world.resources.release,
            fixed_collision.terrain_address,
            fixed_collision.foreground_cell,
            fixed_replace_terrain)
        self.force.update_ray_segments(
            self.stage.m72_scroll.dispatch_foreground_delta,
            fixed_collision.collision_codes,
            lambda rect, damage: self.enemy_world.damage_at(rect, damage),
            self.enemy_world.resources.acquire,
            self.enemy_world.resources.release)
        self.force.update_grid_segments(
            self.m72_frame_counter,
            self.stage.m72_scroll.dispatch_foreground_delta, 0,
            fixed_collision.collision_codes,
            lambda rect, damage: self.enemy_world.damage_at(rect, damage),
            self.enemy_world.resources.acquire,
            self.enemy_world.resources.release)
        self.force.update_type6(
            self.m72_frame_counter, fixed_collision.collision_codes,
            lambda rect, damage: self.enemy_world.damage_at(rect, damage),
            self.enemy_world.resources.acquire,
            self.enemy_world.resources.release,
            fixed_collision.terrain_address,
            fixed_collision.foreground_cell,
            fixed_replace_terrain)

        # `$F493` scans Force, Bit 1 and Bit 2 as alternatives for each enemy:
        # any overlap contributes one point, never one point per body.  The
        # `$F6DA` cadence applies to multi-hit objects; `$F694` one-hit objects
        # and projectiles react immediately on every VBlank.
        force_bounds: tuple[tuple[int, int, int, int], ...] = ()
        if self.force.visible:
            force_bounds = (self.force.collision_bounds(),)
        persistent_bounds = list(force_bounds)
        persistent_bounds.extend(self.bits.collision_bounds())
        self.enemy_world.damage_force_native(
            persistent_bounds,
            # The port retains the pre-IRQ `$2EB6` snapshot; enemy `$F6F8`
            # runs after `$021D` incremented it.  VBlank 4935 is therefore
            # Python `$127F` but ROM `$1280`, the cadence-bearing value.
            cadence_tick=not ((self.m72_frame_counter + 1) & 0x0F),
            force_bounds=force_bounds)

        # In `$F6DA` the persistent Force/Bit hit precedes Wave, and Wave
        # precedes the ordinary-shot scan `$F548`.
        if self.wave is not None:
            if self.wave.power <= 0:
                # `$31E3`: zero power enters `$32AA` on the following update.
                self.wave = None
            elif self.wave.delay:
                self.wave.delay -= 1
            else:
                # `$31E3…$3201` selects the visual before `$328A` subtracts
                # the HP cost accumulated by all enemy `$F6DA` calls.
                self.wave.render_power = wave_power_tier(self.wave.power)
                self.wave.animation += 1
                self.wave.x += WAVE_VX
                if self.wave.x >= 640 * Q8:
                    self.wave = None
                else:
                    cost = self.enemy_world.damage_wave_at(
                        wave_collision_rect(self.wave), self.wave.power)
                    if cost > self.wave.power:
                        # Borrow at `$3294` starts the ROM terminal sequence.
                        self.wave = None
                    else:
                        self.wave.power -= cost

        surviving_shots: list[Shot] = []
        for shot in self.shots:
            if shot.state == "terminal":
                if shot.terminal_timer == 0:
                    continue
                # `$3D57` renders phases 3,2,1 and only then restores the
                # fixed record's idle handler.  Retain the last emitted phase
                # for this draw, but it no longer occupies a firing slot.
                shot.terminal_descriptor = (
                    shot.terminal_base + shot.terminal_timer * 6)
                shot.terminal_timer -= 1
                surviving_shots.append(shot)
                continue

            if shot.native_x is None:
                shot.x += SHOT_VX
            elif self._advance_native_shot(
                    shot, fixed_collision, fixed_replace_terrain):
                surviving_shots.append(shot)
                continue

            if shot.state == "spent":
                # Enemy `$F548` cleared `+$17` after the preceding fixed-shot
                # pass. `$4F40` still performs both moves/probes and emits the
                # ordinary sprite before `$3D17` backs the anchor up by eight.
                if shot.native_x is not None:
                    shot.native_x = (shot.native_x - 8) & 0xFFFF
                    shot.x = ((shot.native_x - 0x0148) * 5 * Q8) // 3
                    shot.state = "terminal"
                    shot.terminal_timer = 3
                    shot.terminal_base = 0x2000
                    shot.terminal_descriptor = 0
                    surviving_shots.append(shot)
                continue

            hit = (self.enemy_world.damage_shot_native(
                (shot.native_x - 0x0F, shot.native_x + 0x0F,
                 shot.native_y - 4, shot.native_y + 4))
                   if shot.native_x is not None and shot.native_y is not None
                   else self.enemy_world.damage_at(shot_collision_rect(shot)))
            if hit and shot.native_x is not None:
                shot.state = "spent"
                surviving_shots.append(shot)
            elif (not hit and
                  (shot.native_x is None or shot.native_x < 0x02B8) and
                  shot.x < 640 * Q8):
                surviving_shots.append(shot)
        self.shots = surviving_shots

        occupied_shot_slots = sum(
            shot.state != "terminal" or shot.terminal_timer != 0
            for shot in self.shots)

        # `$4ED8…$4F3F`: consume the preceding fire-edge request after this
        # pass's already-active shots have moved/collided.  The new `$4F40`
        # record gets its first movement/collision on the following pass.
        if self.pending_shot_spawn:
            self.pending_shot_spawn = False
            if occupied_shot_slots < SHOT_LIMIT:
                native_x, native_y = self._logical_player_native()
                self.shots.append(Shot(self.player_x + SHOT_DX,
                                       self.player_y + SHOT_DY,
                                       native_x + 8, native_y))
                occupied_shot_slots += 1

        fire = inputs.fire
        if fire:
            if not self.fire_held:
                self.fire_held = True
                queued_shot = None
                if (occupied_shot_slots + int(self.pending_shot_spawn) <
                        SHOT_LIMIT):
                    self.pending_shot_spawn = True
                    native_x, native_y = self._logical_player_native()
                    queued_shot = Shot(self.player_x + SHOT_DX,
                                       self.player_y + SHOT_DY,
                                       native_x + 8, native_y)
                    self.enemy_world.request_player_shot_visual()
                    self.play_sfx(0x30)
                latest_shot = queued_shot or next(
                    (shot for shot in reversed(self.shots)
                     if shot.state in ("flight", "spent")), None)
                shot_native = None if latest_shot is None else (
                    round((latest_shot.x // Q8) * 3 / 5) + 0x0140,
                    0x0180 - round((latest_shot.y // Q8) * 8 / 15))
                wave_native = None if self.wave is None else (
                    round((self.wave.x // Q8) * 3 / 5) + 0x0140,
                    0x0180 - round((self.wave.y // Q8) * 8 / 15))
                self.pending_matrix_fire = (
                    2, self.enemy_world.weapon_type, shot_native, wave_native)
            previous_charge = self.wave_charge
            self.wave_charge = advance_wave_charge(self.wave_charge)
            # The Beam-orb object `$2430` sends sound command `$32` exactly
            # once when player byte `+$1D` reaches `$0F`.  Its `$244A` state
            # remains active while FIRE is held.
            if (previous_charge < CHARGE_FIRST_VISIBLE <=
                    self.wave_charge):
                self.play_sfx(0x32)
        elif self.fire_held:
            self.fire_held = False
            # When `+$1D` becomes zero, `$2482..$2494` removes the orb and
            # sends `$33`, stopping the continuous `$32` charge effect.
            if self.wave_charge >= CHARGE_FIRST_VISIBLE:
                self.play_sfx(0x33)
            power = wave_power(self.wave_charge)
            if power:
                self.wave = Wave(
                    self.player_x + WAVE_DX, self.player_y + WAVE_DY,
                    self.player_x + SHOT_DX, self.player_y + WAVE_DY,
                    power=power)
                self.play_sfx(0x31)
            self.wave_charge = 0
        player_rect = self.player_collision_rect()
        native_left = round((self.player_x // Q8) * 3 / 5)
        native_top = round((self.player_y // Q8) * 8 / 15)
        foreground_code, background_code = fixed_collision.collision_codes(
            native_left + 0x0150, 0x0176 - native_top)
        terrain_hit = (foreground_code < 0x0DFC or
                       background_code < 0x07D0)
        self.player_hit = (terrain_hit or
                           self.enemy_world.player_collision(player_rect))
        if self.player_hit and self.lifecycle.collision_enabled:
            self._begin_player_death()
        self._take_hud_refresh()

    def player_collision_rect(self, logical_y: int | None = None,
                              logical_x: int | None = None) -> pygame.Rect:
        """R-9 native hitbox written by ROM `$2027`, converted to 640×480."""
        if logical_x is None:
            logical_x = self.player_x // Q8
        top = self.player_y // Q8 if logical_y is None else logical_y
        anchor_x = round(logical_x * 3 / 5) + 0x0150
        anchor_y = 0x0176 - round(top * 8 / 15)
        left = round((anchor_x - 7 - 0x0140) * 5 / 3)
        right = round((anchor_x + 8 - 0x0140) * 5 / 3)
        logical_top = round((0x0180 - (anchor_y + 6)) * 15 / 8)
        logical_bottom = round((0x0180 - (anchor_y - 1)) * 15 / 8)
        return pygame.Rect(left, logical_top, right - left,
                           logical_bottom - logical_top)

    def _update_intro(self) -> None:
        """Исполнить следующий кадр исходного ROM-сценария R-9."""
        event = self.launch_frames[self.intro_frame]
        self.player_x = round(event.player_x * 5 / 3) * Q8
        # В игровом состоянии Y хранится на единицу ниже полного 32x16 кадра;
        # PITCH_CROP_TOP при выводе возвращает точное положение Sprite RAM.
        self.player_y = (round(event.player_y * 15 / 8) + 1) * Q8
        self.player_pitch = event.body_index << 3
        self.intro_frame += 1

    def render(self, target: pygame.Surface) -> None:
        target.fill("black")
        self.stage.draw_back(target)
        self.enemy_world.draw(target)
        self.force.draw(target, self.enemy_world.atlas)
        self.bits.draw(target, self.enemy_world.atlas)
        pitch_index = self.player_pitch >> 3
        player_y = self.player_y // Q8 + PITCH_CROP_TOP[pitch_index] - 1
        intro_age = self.intro_frame - 1
        if 0 <= intro_age < len(self.launch_frames):
            event = self.launch_frames[intro_age]
            if event.effect_kind:
                image_index = event.effect_kind - 1
                effect_codes = (0x0A23, 0x0AA2, 0x0AA4, 0x0AA6)
                crop_left, crop_top = self.launch_effect_crops[
                    effect_codes[image_index]]
                target.blit(
                    self.launch_effect_images[image_index],
                    (round(event.effect_x * 5 / 3) + crop_left,
                     round(event.effect_y * 15 / 8) + crop_top),
                )
        if self.lifecycle.dying:
            descriptor = self.lifecycle.explosion_descriptor
            if descriptor is not None and self.death_palette != 0xFF:
                self.enemy_world.atlas.draw(
                    target, read_descriptor(self.enemy_world.rom, descriptor),
                    self.death_palette, 0x09,
                    self.death_native[0], self.death_native[1])
        elif self.lifecycle.active:
            target.blit(self.player_images[pitch_index],
                        (self.player_x // Q8, player_y))
        for shot in self.shots:
            if (shot.state == "terminal" and shot.terminal_descriptor and
                    shot.native_x is not None and shot.native_y is not None):
                self.enemy_world.atlas.draw(
                    target,
                    read_descriptor(self.enemy_world.rom,
                                    shot.terminal_descriptor),
                    0, 0x01, shot.native_x, shot.native_y)
            elif shot.state != "terminal":
                target.blit(self.shot_image, (shot.x // Q8, shot.y // Q8))
        if self.wave is not None and self.wave.delay == 0:
            if self.wave.animation < 7:
                release_index = min(3, self.wave.animation // 2)
                target.blit(self.wave_release_images[release_index],
                            (self.wave.release_x // Q8, self.wave.release_y // Q8))
            phase = ((self.wave.animation + 1) >> 1) & 1
            target.blit(self.wave_images[self.wave.render_power][phase],
                        (self.wave.x // Q8, self.wave.y // Q8))
        self._draw_charge_orb(target)
        self.stage.draw_front(target)
        target.blit(self.hud_image, (0, HUD_Y))
        self._draw_lives(target)
        self._draw_player_label(target)
        self._draw_score(target)
        self._draw_beam_meter(target)

    def _draw_lives(self, target: pygame.Surface) -> None:
        """Записи `$F07B`: значки кода $006A с байта $0024, то есть с HUD-столбца 1."""
        for index in range(self.hud_lives):
            target.blit(self.life_icon_image, (round((1 + index) * 40 / 3), HUD_Y))

    def _draw_score(self, target: pygame.Surface) -> None:
        """Seven live tile records produced by `$E8BD/$E9E7`."""
        for index, code in enumerate(score_tile_codes(self.enemy_world.score)):
            if code == 0x11:
                continue
            # One original tile is 8 native pixels = 40/3 logical pixels.
            x = round((HUD_SCORE_FIRST_COLUMN + index) * 40 / 3)
            target.blit(self.score_digit_images[code - 0x30],
                        (x, HUD_SCORE_Y))

    def _draw_player_label(self, target: pygame.Surface) -> None:
        """Draw the exact default-DSW blinking `1P-` four-tile job."""
        if not p1_label_visible(self.m72_frame_counter):
            return
        for index, image in enumerate(self.p1_label_images):
            x = round((HUD_P1_LABEL_FIRST_COLUMN + index) * 40 / 3)
            target.blit(image, (x, HUD_SCORE_Y))

    def _draw_debug_distance(self, target: pygame.Surface) -> None:
        value = self.stage.m72_scroll.progression & 0xFFFF
        image = self.debug_distance_font.render(
            f"DIST {value:04X}", False, (255, 255, 255))
        shadow = self.debug_distance_font.render(
            f"DIST {value:04X}", False, (0, 0, 0))
        x = target.get_width() - image.get_width() - 6
        y = target.get_height() - image.get_height() - 4
        target.blit(shadow, (x + 1, y + 1))
        target.blit(image, (x, y))

    def _draw_charge_orb(self, target: pygame.Surface) -> None:
        """Циклический объект $220..$236 у носа заряжающегося R-9."""
        if self.intro_frame < INTRO_FRAMES:
            return
        if self.fire_held and self.wave_charge >= CHARGE_FIRST_VISIBLE:
            phase = beam_animation_phase(self.m72_frame_counter)
            target.blit(
                self.charge_images[phase],
                (self.player_x // Q8 + 53 + CHARGE_CROP_LEFT[phase],
                 self.player_y // Q8 - 8 + CHARGE_CROP_TOP[phase]),
            )

    def _draw_beam_meter(self, target: pygame.Surface) -> None:
        """Управляемая игроком полоса Beam поверх снятых изменений tilemap."""
        if self.intro_frame < INTRO_FRAMES:
            return
        # `$4FD2…$50C9`: one of 65 offline-converted full/partial-tile states.
        # Runtime does not scale or clip a fabricated solid fill.
        index = min(WAVE_MAX_CHARGE, max(0, self.wave_charge)) // 2
        target.blit(self.beam_meter_images[index],
                    (BEAM_METER_X, BEAM_METER_Y))
