"""Смерть, жизни и checkpoint-респавн R-9 по автомату World ROM."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT_MANIFEST = (
    ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" /
    "Terrain" / "all_stage_terrain.json"
)

# Отсчёт ведётся от VBlank, в котором `$2027` поставил handler `$22CD`.
# Значения подтверждены `player_writes.csv` и work-RAM кадрами 1471…1720.
DIRECTOR_FIRST_DELAY = 21
PLAYER_CLEAR_AGE = 117
LIFE_DECREMENT_AGE = 180
RESPAWN_AGE = 249
RESPAWN_INVULNERABILITY = 0x80
INITIAL_LIVES = 8
MAX_LIVES = 8

# Pointer `$1318` и начальный timer 3 дают первый кадр три раза. Затем
# duration текущей записи становится длительностью следующего descriptor.
# На `$1362` scheduler R-9 останавливается до окончания director delay.
DEATH_DESCRIPTOR_RANGES = (
    (1, 3, 0x1338),
    (4, 6, 0x133E),
    (7, 8, 0x1344),
    (9, 10, 0x134A),
    (11, 12, 0x1350),
    (13, 15, 0x1356),
    (16, 19, 0x135C),
)


@dataclass(frozen=True)
class Checkpoint:
    """Одна буквальная 14-байтная запись таблицы `ES:$87FA`."""

    stage: int
    ordinal: int
    index: int
    progression: int
    foreground_source: int
    background_source: int
    foreground_velocity_q8: int
    background_velocity_q8: int
    packed_resource_music: int


def checkpoints(manifest_path: Path = CHECKPOINT_MANIFEST) -> tuple[Checkpoint, ...]:
    """Прочитать проверенный all-stage manifest без дублирования ROM-чисел."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage_count") != 8:
        raise ValueError("checkpoint manifest не содержит восемь stages")
    result: list[Checkpoint] = []
    for stage_definition in manifest["stages"]:
        stage = int(stage_definition["stage"])
        for ordinal, record in enumerate(stage_definition["checkpoints"]):
            result.append(Checkpoint(
                stage=stage,
                ordinal=ordinal,
                index=int(record["index"]),
                progression=int(record["progression"]),
                foreground_source=int(record["foreground_source"]),
                background_source=int(record["background_source"]),
                foreground_velocity_q8=int(record["foreground_velocity_q8"]),
                background_velocity_q8=int(record["background_velocity_q8"]),
                packed_resource_music=int(record["packed_resource_music"]),
            ))
    if tuple(point.index for point in result) != tuple(range(16)):
        raise ValueError("нарушена глобальная нумерация checkpoint 0…15")
    return tuple(result)


CHECKPOINTS = checkpoints()


def checkpoint_for_progression(stage: int, progression: int) -> Checkpoint:
    """Выбрать последнюю достигнутую запись текущего stage."""
    stage_points = tuple(point for point in CHECKPOINTS if point.stage == stage)
    if not stage_points:
        raise ValueError("stage должен быть 1…8")
    progression &= 0xFFFF
    eligible = tuple(point for point in stage_points
                     if point.progression <= progression)
    return eligible[-1] if eligible else stage_points[0]


@dataclass(frozen=True)
class LifecycleEvents:
    """Однокадровые действия director, которые выполняет владелец Game."""

    player_cleared: bool = False
    life_decremented: bool = False
    checkpoint_rebuild: bool = False
    respawned: bool = False
    game_over: bool = False


class PlayerLifecycle:
    """Покадровый автомат `$10FA/$11BB/$11CC/$0FA1` и R-9 `$22CD`."""

    def __init__(self, lives: int = INITIAL_LIVES) -> None:
        if not 1 <= lives <= MAX_LIVES:
            raise ValueError("число жизней должно быть в диапазоне 1…8")
        self.lives = lives
        self.state = "active"
        self.death_age = -1
        self.invulnerability = 0
        self.checkpoint: Checkpoint | None = None

    @property
    def active(self) -> bool:
        return self.state == "active"

    @property
    def dying(self) -> bool:
        return self.state == "death"

    @property
    def player_visible(self) -> bool:
        return self.active or (self.dying and self.death_age < PLAYER_CLEAR_AGE)

    @property
    def collision_enabled(self) -> bool:
        return self.active and self.invulnerability == 0

    @property
    def explosion_descriptor(self) -> int | None:
        if not self.dying or self.death_age >= PLAYER_CLEAR_AGE:
            return None
        age = max(1, self.death_age)
        for first, last, descriptor in DEATH_DESCRIPTOR_RANGES:
            if first <= age <= last:
                return descriptor
        return 0x1362

    def begin_death(self, stage: int, progression: int) -> bool:
        """Зафиксировать checkpoint и начать смерть ровно один раз."""
        if not self.collision_enabled:
            return False
        self.state = "death"
        self.death_age = 0
        self.invulnerability = 0
        self.checkpoint = checkpoint_for_progression(stage, progression)
        return True

    def award_life(self) -> bool:
        """Добавить призовую жизнь, не превышая новый предел восемь."""
        if self.lives >= MAX_LIVES:
            return False
        self.lives += 1
        return True

    def advance(self) -> LifecycleEvents:
        """Исполнить один следующий VBlank автомата."""
        if self.active:
            if self.invulnerability:
                self.invulnerability -= 1
            return LifecycleEvents()
        if self.state == "game_over":
            return LifecycleEvents()

        self.death_age += 1
        if self.death_age == PLAYER_CLEAR_AGE:
            return LifecycleEvents(player_cleared=True)
        if self.death_age == LIFE_DECREMENT_AGE:
            self.lives -= 1
            if self.lives <= 0:
                self.state = "game_over"
                return LifecycleEvents(life_decremented=True, game_over=True)
            return LifecycleEvents(
                life_decremented=True, checkpoint_rebuild=True)
        if self.death_age == RESPAWN_AGE:
            self.state = "active"
            self.invulnerability = RESPAWN_INVULNERABILITY
            return LifecycleEvents(respawned=True)
        return LifecycleEvents()
