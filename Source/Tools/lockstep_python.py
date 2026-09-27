"""Покадровая lockstep-сверка активного rtype_port с сохранённым оригиналом.

Эталон загружается из `R-Type Python Original 2026-09-13` под именем пакета
`rtype_reference`, поэтому обе версии живут в одном процессе и получают один и
тот же ввод. После каждого кадра сравниваются полное состояние объекта Game,
звуковые команды и список команд отрисовки. Любое расхождение — ошибка правки.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import os
import random
import sys
import time
import types
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / 'R-Type Python Original 2026-09-13'
REFERENCE_PACKAGE = 'rtype_reference'
REPORT_DIR = ROOT / 'Build' / 'Lockstep'

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
for extra in (ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import pygame  # noqa: E402


def load_reference() -> types.ModuleType:
    """Импортировать замороженную копию под отдельным именем пакета."""
    if REFERENCE_PACKAGE in sys.modules:
        return sys.modules[REFERENCE_PACKAGE]
    package_dir = ORIGINAL / 'Source' / 'Python' / 'rtype_port'
    spec = importlib.util.spec_from_file_location(
        REFERENCE_PACKAGE, package_dir / '__init__.py',
        submodule_search_locations=[str(package_dir)])
    if spec is None or spec.loader is None:
        raise RuntimeError(f'нет эталонного пакета: {package_dir}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[REFERENCE_PACKAGE] = module
    spec.loader.exec_module(module)
    return module


class SurfaceIdentity:
    """Содержательная идентичность изображения: размер и хеш пикселей.

    Ресурсные поверхности живут всё время игры, поэтому их хеш кэшируется по id
    вместе с сильной ссылкой (id не может быть переиспользован). Короткоживущие
    поверхности (текст отладочной строки) хешируются при каждом обращении.
    """

    def __init__(self) -> None:
        self._cache: dict[int, tuple[object, tuple[int, int, str]]] = {}
        self._transient: set[int] = set()

    def mark_resources(self, surfaces: list[pygame.Surface]) -> None:
        for surface in surfaces:
            self._key(surface, remember=True)

    def _key(self, surface: pygame.Surface, *, remember: bool) -> tuple[int, int, str]:
        cached = self._cache.get(id(surface))
        if cached is not None and cached[0] is surface:
            return cached[1]
        digest = hashlib.blake2b(pygame.image.tobytes(surface, 'RGBA'),
                                 digest_size=10).hexdigest()
        key = (surface.get_width(), surface.get_height(), digest)
        if remember:
            self._cache[id(surface)] = (surface, key)
        return key

    def __call__(self, surface: pygame.Surface) -> tuple[int, int, str]:
        return self._key(surface, remember=False)


class DrawRecorder:
    """Цель рендера: записывает команды в исходном порядке вместо пикселей."""

    def __init__(self, identity: SurfaceIdentity, atlas_owner: object) -> None:
        self.commands: list[tuple] = []
        self._identity = identity
        self._atlas_owner = atlas_owner
        self._known_cells = 0

    def get_width(self) -> int:
        return 640

    def get_height(self) -> int:
        return 480

    def fill(self, color, rect=None, special_flags=0) -> None:
        self.commands.append(('fill', tuple(pygame.Color(color)), rect,
                              special_flags))

    def blit(self, source, dest, area=None, special_flags=0) -> None:
        self._remember_new_atlas_cells()
        self.commands.append((
            'blit', self._identity(source), dest[0], dest[1],
            None if area is None else tuple(area), special_flags))

    def _remember_new_atlas_cells(self) -> None:
        # Ленивый атлас спрайтов держит свои поверхности в кэше: их можно
        # запомнить по id, не рискуя повторным использованием адреса.
        cells = getattr(self._atlas_owner, '_cells', None)
        if cells is not None and len(cells) != self._known_cells:
            self._identity.mark_resources(list(cells.values()))
            self._known_cells = len(cells)


# Неизменяемые ресурсы сравниваются один раз на старте, а не каждый кадр.
RESOURCE_ATTRIBUTES = frozenset({
    ('Stage', 'sections'), ('Stage', 'section'),
    ('M72SpriteAtlas', '_cells'), ('M72SpriteAtlas', '_banks'),
    ('M72Rom', 'data'), ('M72Tilemaps', 'rom'),
})

# Служебные поля, добавленные эквивалентными правками. Их нет в эталоне, а
# корректность проверяется через наблюдаемое поведение. Каждое поле — явно.
REFACTOR_ONLY_ATTRIBUTES = frozenset({
    # Журнал записей VRAM вместо копии снимка коллизий (2026-09-13).
    ('M72Tilemaps', 'journal_generation'), ('M72Tilemaps', 'journal_active'),
    ('M72Tilemaps', 'journal_layers'), ('M72Tilemaps', 'journal_indices'),
    ('M72Tilemaps', 'journal_values'),
    # Ключи видимых ячеек и занятость строк вместо словаря на ячейку (2026-09-13).
    ('M72Tilemaps', 'tile_key_codes'), ('M72Tilemaps', 'tile_key_attributes'),
    ('M72Tilemaps', 'key_map'), ('M72Tilemaps', 'row_bits'),
    ('StageSection', 'fg_slots'), ('StageSection', 'bg_slots'),
    ('StageSection', 'boss_fg_slots'), ('StageSection', 'boss_bg_slots'),
    ('StageSection', 'flash_fg_slots'), ('StageSection', 'flash_bg_slots'),
    ('StageSection', 'fg_images'), ('StageSection', 'bg_images'),
    ('StageSection', 'boss_fg_images'), ('StageSection', 'boss_bg_images'),
    ('StageSection', 'flash_fg_images'), ('StageSection', 'flash_bg_images'),
    # Готовые состояния ring tilemap checkpoint вместо M72WorldTerrain при рестарте (2026-09-13).
    ('Stage', 'checkpoint_terrain'),
})


class Projector:
    """Каноническая проекция графа объектов в сравнимые кортежи."""

    def __init__(self, prefixes: tuple[str, ...], *, include_resources: bool) -> None:
        self.prefixes = prefixes
        self.include_resources = include_resources
        self._seen: dict[int, str] = {}
        self._alive: list[object] = []

    def _package_class(self, value: object) -> bool:
        module = type(value).__module__
        return any(module == p or module.startswith(p + '.') for p in self.prefixes)

    def project(self, value: object, path: str = 'game') -> object:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            data = bytes(value)
            return (type(value).__name__, len(data),
                    hashlib.blake2b(data, digest_size=12).hexdigest())
        if isinstance(value, pygame.Surface):
            return ('surface', value.get_width(), value.get_height())
        if isinstance(value, pygame.Rect):
            return ('rect', value.x, value.y, value.w, value.h)
        if isinstance(value, pygame.font.Font):
            return ('font',)
        if isinstance(value, types.MethodType):
            return ('bound', value.__func__.__qualname__)
        if isinstance(value, (types.FunctionType, types.BuiltinFunctionType)):
            return ('callable', value.__qualname__)
        # Неизменяемые значения сравниваются по содержимому: общая или отдельная
        # копия кортежа не является наблюдаемым поведением.
        if isinstance(value, tuple):
            return ('tuple', tuple(self.project(item, f'{path}[{index}]')
                                   for index, item in enumerate(value)))
        if isinstance(value, (set, frozenset)):
            return (type(value).__name__, tuple(sorted(repr(item) for item in value)))
        frozen = (dataclasses.is_dataclass(value) and not isinstance(value, type) and
                  value.__dataclass_params__.frozen)
        marker = None if frozen else self._seen.get(id(value))
        if marker is not None:
            return ('ref', marker)
        if self._package_class(value):
            if not frozen:
                self._remember(value, path)
            owner = type(value).__qualname__
            fields = []
            for name, item in sorted(vars(value).items()):
                if not self.include_resources and (owner, name) in RESOURCE_ATTRIBUTES:
                    continue
                # Кэш офлайн-пикселей спрайтов: общий для миров после рестарта (2026-09-13).
                if (owner, name) in (('M72SpriteAtlas', '_cells'), ('M72SpriteAtlas', '_banks')):
                    continue
                if (owner, name) in REFACTOR_ONLY_ATTRIBUTES:
                    continue
                fields.append((name, self.project(item, f'{path}.{name}')))
            # Подклассы list (например, M72PendingList) хранят данные вне __dict__.
            if isinstance(value, list):
                fields.append(('<items>', tuple(self.project(item, f'{path}[{i}]')
                                                for i, item in enumerate(value))))
            return ('obj', owner, tuple(fields))
        if isinstance(value, (list, deque)):
            self._remember(value, path)
            return (type(value).__name__,
                    tuple(self.project(item, f'{path}[{index}]')
                          for index, item in enumerate(value)))
        if isinstance(value, dict):
            self._remember(value, path)
            items = sorted(value.items(), key=lambda item: repr(item[0]))
            return ('dict', tuple((repr(key), self.project(item, f'{path}[{key!r}]'))
                                  for key, item in items))
        module = type(value).__module__
        if module.startswith('numpy'):
            import numpy as np
            array = np.asarray(value)
            return ('ndarray', array.shape, array.dtype.str,
                    hashlib.blake2b(array.tobytes(), digest_size=12).hexdigest())
        raise TypeError(f'{path}: неизвестный тип {type(value)!r}')

    def _remember(self, value: object, path: str) -> None:
        self._seen[id(value)] = path
        self._alive.append(value)


def first_difference(left: object, right: object, path: str = 'game') -> str | None:
    """Найти путь первого расхождения двух проекций."""
    if left == right:
        return None
    if (isinstance(left, tuple) and isinstance(right, tuple) and left and right and
            left[0] == right[0] == 'obj'):
        if left[1] != right[1]:
            return f'{path}: класс {left[1]} != {right[1]}'
        lf, rf = dict(left[2]), dict(right[2])
        for name in sorted(set(lf) | set(rf)):
            if name not in lf or name not in rf:
                return f'{path}.{name}: поле есть только в одной версии'
            found = first_difference(lf[name], rf[name], f'{path}.{name}')
            if found:
                return found
    if (isinstance(left, tuple) and isinstance(right, tuple) and len(left) == 2 and
            len(right) == 2 and left[0] == right[0] and
            isinstance(left[1], tuple) and isinstance(right[1], tuple)):
        if len(left[1]) != len(right[1]):
            return f'{path}: длина {len(left[1])} != {len(right[1])}'
        for index, (a, b) in enumerate(zip(left[1], right[1])):
            found = first_difference(a, b, f'{path}[{index}]')
            if found:
                return found
    return f'{path}: эталон={_short(left)} новая={_short(right)}'


def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 300 else text[:300] + '…'


def _collect_surfaces(game: object, prefixes: tuple[str, ...]) -> list[pygame.Surface]:
    """Все поверхности, достижимые из Game при создании (ресурсы игры)."""
    found: list[pygame.Surface] = []
    seen: set[int] = set()
    stack = [game]
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, pygame.Surface):
            found.append(value)
        elif isinstance(value, (list, tuple, deque, set, frozenset)):
            stack.extend(value)
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif any(type(value).__module__.startswith(p) for p in prefixes):
            stack.extend(vars(value).values())
    return found


@dataclasses.dataclass
class Side:
    """Одна из двух сравниваемых версий игры."""

    name: str
    package: str
    game_module: types.ModuleType
    game: object
    sounds: list[int]
    identity: SurfaceIdentity


def make_side(name: str, package: str) -> Side:
    game_module = importlib.import_module(package + '.game')
    sounds: list[int] = []
    game = game_module.Game(sounds.append)
    identity = SurfaceIdentity()
    identity.mark_resources(_collect_surfaces(game, (package,)))
    return Side(name, package, game_module, game, sounds, identity)


class Coverage:
    """Наблюдатель покрытия правок: только считает, результат не меняет."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    def add(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def maximum(self, name: str, value: int) -> None:
        self.counters[name] = max(self.counters.get(name, 0), value)

    def install(self, package: str) -> None:
        stage = importlib.import_module(package + '.stage')
        tilemaps = stage.M72Tilemaps
        if hasattr(tilemaps, 'journal_changed_cells'):
            original = tilemaps.journal_changed_cells

            def journal_changed_cells(owner, generation, layer):
                result = original(owner, generation, layer)
                self.maximum('journal_bytes_max', len(owner.journal_indices))
                if owner.journal_indices:
                    self.add('frames_with_journal')
                if result:
                    self.add('frames_with_changed_cells')
                    self.maximum('changed_cells_max', len(result))
                return result
            tilemaps.journal_changed_cells = journal_changed_cells


def warp_to_checkpoint(side: Side, ordinal: int) -> None:
    """Штатный `_restore_checkpoint` с выбранной записью Stage 1 — в обеих версиях."""
    lifecycle_module = importlib.import_module(side.package + '.player_lifecycle')
    point = next(point for point in lifecycle_module.CHECKPOINTS
                 if point.stage == 1 and point.ordinal == ordinal)
    side.game.intro_frame = side.game_module.INTRO_FRAMES
    side.game.lifecycle.checkpoint = point
    side.game._restore_checkpoint()


def run(frames: int, seed: int, chaos: bool, render_every: int,
        progress_every: int, checkpoint: int | None = None,
        keep_lives: bool = False, invulnerable: bool = False) -> dict:
    load_reference()
    pygame.init()
    pygame.display.set_mode((640, 480))
    coverage = Coverage()
    coverage.install('rtype_port')
    reference = make_side('эталон', REFERENCE_PACKAGE)
    current = make_side('новая', 'rtype_port')
    if checkpoint is not None:
        for side in (reference, current):
            warp_to_checkpoint(side, checkpoint)
    autopilot_module = importlib.import_module(REFERENCE_PACKAGE + '.autopilot')
    pilot = autopilot_module.Stage1Autopilot()
    rng = random.Random(seed)

    def projection(side: Side, include_resources: bool) -> object:
        return Projector((side.package,), include_resources=include_resources).project(side.game)

    started = time.perf_counter()
    report: dict = {'frames_requested': frames, 'seed': seed, 'chaos': chaos,
                    'render_every': render_every, 'coverage': coverage.counters}
    initial = (projection(reference, True), projection(current, True))
    difference = first_difference(*initial, path='init')
    if difference:
        report.update(result='diverged', frame=0, stage='init', difference=difference)
        return report

    chaos_left = 0
    chaos_input = None
    deaths = 0
    for frame in range(1, frames + 1):
        planned = pilot.next(reference.game)
        if chaos:
            # Сегменты случайного ввода расширяют покрытие: смерть, Force, края.
            if chaos_left == 0 and rng.random() < 0.004:
                chaos_left = rng.randint(20, 240)
            if chaos_left:
                if chaos_input is None or rng.random() < 0.08:
                    chaos_input = {field.name: rng.random() < 0.3
                                   for field in dataclasses.fields(planned)}
                planned = type(planned)(**chaos_input)
                chaos_left -= 1
        values = dataclasses.asdict(planned)
        if keep_lives and reference.game.lifecycle.lives < 3:
            # Одинаковая правка обеих версий: прогон не упирается в game over.
            for side in (reference, current):
                side.game.lifecycle.lives = 8
            coverage.add('lives_refills')
        if invulnerable and reference.game.lifecycle.active:
            # Одинаковая неуязвимость обеих версий: автопилот доходит до босса.
            for side in (reference, current):
                side.game.lifecycle.invulnerability = max(side.game.lifecycle.invulnerability, 2)
        was_active = reference.game.lifecycle.active
        reference.game.update(reference.game_module.InputState(**values))
        current.game.update(current.game_module.InputState(**values))
        if was_active and not reference.game.lifecycle.active:
            deaths += 1

        if reference.sounds != current.sounds:
            report.update(result='diverged', frame=frame, stage='sound',
                          difference=f'эталон={reference.sounds} новая={current.sounds}')
            return report
        reference.sounds.clear()
        current.sounds.clear()

        state = (projection(reference, False), projection(current, False))
        difference = first_difference(*state, path='game')
        if difference:
            report.update(result='diverged', frame=frame, stage='update',
                          difference=difference)
            return report

        if render_every and frame % render_every == 0:
            targets = []
            for side in (reference, current):
                recorder = DrawRecorder(side.identity, side.game.enemy_world.atlas)
                side.game.render(recorder)
                targets.append(recorder.commands)
            if targets[0] != targets[1]:
                index = next((i for i, (a, b) in enumerate(zip(*targets)) if a != b),
                             min(len(targets[0]), len(targets[1])))
                left = targets[0][index] if index < len(targets[0]) else None
                right = targets[1][index] if index < len(targets[1]) else None
                report.update(result='diverged', frame=frame, stage='render',
                              difference=(f'команда {index}: эталон={left} новая={right}; '
                                          f'длины {len(targets[0])}/{len(targets[1])}'))
                return report
            # Рендер не должен менять игровое состояние.
            after = (projection(reference, False), projection(current, False))
            difference = first_difference(*after, path='game(render)')
            if difference:
                report.update(result='diverged', frame=frame, stage='render-state',
                              difference=difference)
                return report

        if progress_every and frame % progress_every == 0:
            elapsed = time.perf_counter() - started
            game = reference.game
            print(f'кадр {frame:6d}  progression ${game.stage.m72_scroll.progression:04X}  '
                  f'врагов {len(game.enemy_world.enemies):3d}  смертей {deaths:3d}  '
                  f'очки {game.enemy_world.score:7d}  {frame / elapsed:5.1f} к/с  '
                  f'{coverage.counters}', flush=True)

    elapsed = time.perf_counter() - started
    game = reference.game
    report.update(result='identical', frames=frames, seconds=round(elapsed, 1),
                  deaths=deaths, final_progression=game.stage.m72_scroll.progression,
                  final_score=game.enemy_world.score)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=3000)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--no-chaos', action='store_true',
                        help='только автопилот, без случайных сегментов ввода')
    parser.add_argument('--render-every', type=int, default=1,
                        help='сверять список отрисовки каждые N кадров (0 — никогда)')
    parser.add_argument('--progress-every', type=int, default=500)
    parser.add_argument('--checkpoint', type=int, default=None,
                        help='начать обе версии с чекпоинта Stage 1 (ordinal 0…3)')
    parser.add_argument('--keep-lives', action='store_true',
                        help='одинаково доливать жизни обеим версиям')
    parser.add_argument('--invulnerable', action='store_true',
                        help='одинаковая неуязвимость обеих версий (покрытие до босса)')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    report = run(args.frames, args.seed, not args.no_chaos, args.render_every,
                 args.progress_every, args.checkpoint, args.keep_lives, args.invulnerable)
    report['checkpoint'] = args.checkpoint
    report['keep_lives'] = args.keep_lives
    report['invulnerable'] = args.invulnerable
    report['original'] = ORIGINAL.name
    path = args.report or REPORT_DIR / f'lockstep_seed{args.seed}_{args.frames}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8', newline='\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['result'] == 'identical' else 1


if __name__ == '__main__':
    raise SystemExit(main())
