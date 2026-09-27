"""Deterministic test pilot that drives only the normal `InputState` path."""
from __future__ import annotations

from .game import InputState, Q8


class Stage1Autopilot:
    """Aim at ROM enemies while choosing a landscape-safe vertical lane."""

    def __init__(self) -> None:
        self.frame = 0
        self.goal_y = 210

    @staticmethod
    def _safe(game: object, logical_y: int,
              boxes: list[object] | None = None,
              logical_x: int | None = None,
              future_frame: int = 0) -> bool:
        if logical_x is None:
            logical_x = game.player_x // Q8
        native_left = round(logical_x * 3 / 5)
        native_top = round(logical_y * 8 / 15)
        anchor_x = native_left + 0x0150
        anchor_y = 0x0176 - native_top
        for dx, dy in ((0, 0), (-12, 0), (12, 0),
                       (0, -8), (0, 8)):
            foreground = game.stage.terrain_code(
                anchor_x + dx, anchor_y + dy)
            background = game.stage.collision_codes(
                anchor_x + dx, anchor_y + dy)[1]
            if foreground < 0x0DFC or background < 0x07D0:
                return False
        if boxes is None:
            return True
        player = game.player_collision_rect(logical_y, logical_x).inflate(100, 30)
        return not any(player.colliderect(box) for box in boxes)

    @staticmethod
    def _risk(game: object, logical_y: int,
              boxes: list[object]) -> int:
        player = game.player_collision_rect(logical_y)
        risk = 0
        for box in boxes:
            dx = max(box.left - player.right, player.left - box.right, 0)
            dy = max(box.top - player.bottom, player.top - box.bottom, 0)
            if dx == 0 and dy == 0:
                risk += 1_000_000
            elif dx < 180 and dy < 80:
                risk += (180 - dx) * (80 - dy)
        return risk

    @staticmethod
    def _trajectory_penalty(game: object, horizontal: int, vertical: int,
                            horizon: int = 16) -> tuple[int, int]:
        """Check a constant normal-input move against ROM Q8 projectiles."""
        current_x = game.player_x // Q8
        current_y = game.player_y // Q8
        collision_penalty = 0
        terrain_penalty = 0
        moving = [enemy for enemy in game.enemy_world.enemies
                  if enemy.palette != 0xFF and enemy.kind in
                  ("enemy_projectile", "handler_60ba_child")]
        for frame in range(1, horizon + 1):
            logical_x = round(current_x + horizontal * (853 / 256) * frame)
            logical_x = min(640 - 53, max(0, logical_x))
            logical_y = round(current_y + vertical * 3.75 * frame)
            logical_y = min(421, max(0, logical_y))
            if not Stage1Autopilot._safe(
                    game, logical_y, logical_x=logical_x,
                    future_frame=frame):
                terrain_penalty += horizon + 1 - frame
            player = game.player_collision_rect(logical_y, logical_x)
            for enemy in moving:
                box = enemy.hitbox(game.enemy_world.rom)
                velocity_x = getattr(enemy, "x_velocity", 0)
                velocity_y = getattr(enemy, "y_velocity", 0)
                dx = round(velocity_x * frame * 5 / (256 * 3))
                dy = -round(velocity_y * frame * 15 / (256 * 8))
                if player.colliderect(box.move(dx, dy)):
                    collision_penalty += horizon + 1 - frame
        return terrain_penalty, collision_penalty

    def next(self, game: object) -> InputState:
        self.frame += 1
        if game.intro_frame < len(game.launch_frames):
            return InputState()

        current_y = game.player_y // Q8
        desired_y = 210
        visible = [enemy for enemy in game.enemy_world.enemies
                   if enemy.palette != 0xFF and enemy.shootable and
                   enemy.hitbox(game.enemy_world.rom).right >= 0]
        if visible:
            boss = next((enemy for enemy in visible
                         if enemy.kind == "dobkeratops_body"), None)
            target = boss or min(
                visible, key=lambda enemy: abs(enemy.hitbox(
                    game.enemy_world.rom).centery - current_y))
            desired_y = target.hitbox(game.enemy_world.rom).centery - 14

        # Two narrowing foreground gates cross the current R-9 lane before
        # the local vertical slice itself becomes solid.  Start the descent
        # from ROM progression, not from a captured host-frame number.
        progression = game.stage.m72_scroll.progression
        if (0x1090 <= progression < 0x10D0 or
                0x1450 <= progression < 0x1488):
            desired_y = 180

        candidates = sorted(range(12, 421, 8),
                            key=lambda y: (abs(y - desired_y), abs(y - current_y)))
        hazard_boxes = [
            enemy.hitbox(game.enemy_world.rom)
            for enemy in game.enemy_world.enemies if enemy.palette != 0xFF
        ]
        terrain_safe = [y for y in candidates if self._safe(game, y)]
        clear = [y for y in terrain_safe if self._safe(game, y, hazard_boxes)]
        if clear:
            safe_y = min(clear, key=lambda y: (abs(y - desired_y),
                                                abs(y - current_y)))
        elif terrain_safe:
            safe_y = min(terrain_safe,
                         key=lambda y: (self._risk(game, y, hazard_boxes),
                                        abs(y - current_y)))
        else:
            safe_y = current_y

        self.goal_y = safe_y
        current_x = game.player_x // Q8
        vertical = (-1 if safe_y < current_y - 3 else
                    (1 if safe_y > current_y + 3 else 0))
        horizontal = -1 if current_x > 90 else (1 if current_x < 70 else 0)
        preferred_penalty = self._trajectory_penalty(
            game, horizontal, vertical)
        if any(preferred_penalty):
            penalties = {
                move: self._trajectory_penalty(game, *move)
                for move in ((x, y) for x in (-1, 0, 1)
                             for y in (-1, 0, 1))
            }
            horizontal, vertical = min(
                penalties,
                key=lambda move: (
                    sum(penalties[move]),
                    penalties[move][1],
                    abs(current_y + move[1] * 60 - safe_y),
                    abs(current_x + move[0] * 53 - 80),
                ),
            )
        up = vertical < 0
        down = vertical > 0
        left = horizontal < 0
        right = horizontal > 0

        # Survival pass uses the original ordinary-shot edge at a repeatable
        # two-on/two-off rhythm. Beam has its own ROM regression run.
        fire = (self.frame & 3) < 2
        return InputState(left=left, right=right, up=up, down=down, fire=fire)
