"""Проверка полного World-моста до штатного R-9 launch."""
from __future__ import annotations

import struct
import unittest
from collections import defaultdict

import pygame
from unicorn.x86_const import (
    UC_X86_REG_CS, UC_X86_REG_CX, UC_X86_REG_DI, UC_X86_REG_DS,
    UC_X86_REG_EFLAGS, UC_X86_REG_ES, UC_X86_REG_IP, UC_X86_REG_SI,
)

from rtype_m72.machine import RTypeM72Machine, V30_ADD4S_ADDRESSES
from rtype_port.app import (
    RuntimeInput, _input_mask, _keydown_actions, _wakes_from_demo,
)
from rtype_port.full_runtime import (
    ARCADE_PRESENTATION_ENTRY, ATTRACT_GAME_OVER_X_HIGH_ADDRESS,
    BONUS_LIFE_TABLES, DSW_LIVES_TABLE_ADDRESS, GAME_OVER_DELAY_HANDLER,
    LIVES_CAP_IMMEDIATE_ADDRESS, FullRuntimeGame, _bonus_life_table,
)
from rtype_port.player_lifecycle import INITIAL_LIVES, MAX_LIVES


class FullRuntimeTests(unittest.TestCase):
    def test_balance_patches_are_runtime_local_and_exact(self) -> None:
        game = FullRuntimeGame(lambda _: None, enable_renderer=False)
        cpu = game.machine.cpu

        self.assertEqual(bytes((INITIAL_LIVES,)) * 4,
                         bytes(cpu.mem_read(DSW_LIVES_TABLE_ADDRESS, 4)))
        self.assertEqual(INITIAL_LIVES,
                         int.from_bytes(cpu.mem_read(0x42F14, 2), "little"))
        self.assertEqual(MAX_LIVES,
                         int(cpu.mem_read(LIVES_CAP_IMMEDIATE_ADDRESS, 1)[0]))
        self.assertEqual(b"\x83\x3C\xFF", game.machine.regions["maincpu"][
                         LIVES_CAP_IMMEDIATE_ADDRESS - 2:
                         LIVES_CAP_IMMEDIATE_ADDRESS + 1])

        for address, thresholds in BONUS_LIFE_TABLES:
            expected = _bonus_life_table(thresholds)
            self.assertEqual(expected, bytes(cpu.mem_read(address, len(expected))))
            self.assertNotEqual(expected, game.machine.regions["maincpu"][
                                address:address + len(expected)])

        for lives, instruction_count, expected_pc in (
                (7, 3, 0x0ED5D), (8, 2, 0x0ED62)):
            cpu.mem_write(0x42F32, lives.to_bytes(2, "little"))
            cpu.reg_write(UC_X86_REG_CS, 0x0040)
            cpu.reg_write(UC_X86_REG_IP, 0xE956)
            cpu.reg_write(UC_X86_REG_DS, 0x4000)
            cpu.reg_write(UC_X86_REG_SI, 0x2F32)
            cpu.reg_write(UC_X86_REG_EFLAGS, 0x0002)
            cpu.emu_start(0x0ED56, 0x100000, count=instruction_count)
            self.assertEqual(expected_pc, game.machine.linear_pc())
            self.assertEqual(MAX_LIVES, int.from_bytes(
                cpu.mem_read(0x42F32, 2), "little"))

    def test_attract_game_over_moves_offscreen_only_in_demo(self) -> None:
        game = FullRuntimeGame(lambda _: None, enable_renderer=False)
        rom = game.machine.regions["maincpu"]
        memory = game.machine.cpu

        # Демо-контроллер `$0A8B`: MOV word [SI+4],$0200 → $0000.
        self.assertEqual(b"\xC7\x44\x04\x00\x02",
                         rom[ATTRACT_GAME_OVER_X_HIGH_ADDRESS - 4:
                             ATTRACT_GAME_OVER_X_HIGH_ADDRESS + 1])
        self.assertEqual(b"\xC7\x44\x04\x00\x00", bytes(memory.mem_read(
            ATTRACT_GAME_OVER_X_HIGH_ADDRESS - 4, 5)))
        # Настоящий GAME OVER (`$23A8` и `$EFED`) сохраняет X=$0200.
        for linear in (0x027B0, 0x0F3F5):
            self.assertEqual(b"\xC7\x44\x04\x00\x02", rom[linear:linear + 5])
            self.assertEqual(b"\xC7\x44\x04\x00\x02",
                             bytes(memory.mem_read(linear, 5)))

    def test_hidden_title_opens_attract_demo(self) -> None:
        game = FullRuntimeGame(lambda _: None, enable_renderer=False)
        for _ in range(600):
            if game.advance_title():
                break
        self.assertTrue(game.ready)
        self.assertTrue(game.is_attract_demo)
        self.assertEqual(0x2027, game._player_handler())

    def test_coin_start_reaches_complete_world_gameplay(self) -> None:
        commands: list[int] = []
        game = FullRuntimeGame(commands.append, enable_renderer=False)
        for _ in range(314):
            game.advance_title()
        game.request_start()
        for _ in range(80):
            if game.advance_start():
                break
        self.assertTrue(game.ready)
        self.assertIn(0x63, commands)
        self.assertIn(game._player_handler(), (0x1F3D, 0x2027))
        self.assertEqual(INITIAL_LIVES, int.from_bytes(
            game.machine.cpu.mem_read(0x42F32, 2), "little"))

        game.update(0x19)
        self.assertIn(0x1F, commands)
        self.assertEqual(0x76, game.machine.inputs.in0 & 0x00FF)
        self.assertIsNotNone(game.frame_state)

    def test_first_rom_reward_updates_hud_to_200_not_saturation(self) -> None:
        game = FullRuntimeGame(lambda _: None, enable_renderer=False)
        for _ in range(314):
            game.advance_title()
        game.request_start()
        while not game.advance_start():
            pass
        for age in range(800):
            fire = (age % 36) < 5
            down = age < 60
            game.update((0x10 if fire else 0) | (0x04 if down else 0))
        codes = tuple(
            struct.unpack_from("<H", game.frame_state.vram0,
                               0x013C + index * 4)[0]
            for index in range(7))
        self.assertEqual((0x11, 0x11, 0x11, 0x11, 0x32, 0x30, 0x30),
                         codes)

    def test_arcade_presentation_entry_returns_to_custom_title(self) -> None:
        game = FullRuntimeGame(lambda _: None, enable_renderer=False)
        game.ready = True
        # `$1299` является последней ветвью законченной сессии: она снимает
        # player state и сама записывает `$076C`, не исполняя arcade title.
        game.machine.cpu.mem_write(0x40000, (0x1299).to_bytes(2, "little"))
        game.machine.cpu.mem_write(0x42F32, b"\x00\x00")
        game.machine.cpu.mem_write(0x42F3A, b"\x00\x00")
        game.update(0)
        self.assertEqual(ARCADE_PRESENTATION_ENTRY, game._director_handler())
        self.assertTrue(game.return_to_custom_title)
        game.machine.cpu.mem_write(0x40000, (0x124F).to_bytes(2, "little"))
        game.machine.cpu.mem_write(0x4001E, (2).to_bytes(2, "little"))
        self.assertFalse(game.return_to_custom_title)

    def test_last_game_over_frame_skips_continue_insert_coin(self) -> None:
        game = FullRuntimeGame(lambda _: None, enable_renderer=False)
        game.ready = True
        game.machine.cpu.mem_write(
            0x40000, GAME_OVER_DELAY_HANDLER.to_bytes(2, "little"))
        game.machine.cpu.mem_write(0x4001E, (2).to_bytes(2, "little"))
        self.assertFalse(game.return_to_custom_title)
        game.machine.cpu.mem_write(0x4001E, (1).to_bytes(2, "little"))
        self.assertTrue(game.return_to_custom_title)


class V30ExtensionTests(unittest.TestCase):
    def test_add4s_uses_two_byte_v30_semantics_and_exact_flags(self) -> None:
        machine = RTypeM72Machine()
        address = V30_ADD4S_ADDRESSES[0]
        self.assertEqual(b"\x0F\x20", machine.regions["maincpu"][
                         address:address + 2])
        self.assertEqual(b"\x90\x90", bytes(machine.cpu.mem_read(address, 2)))
        machine.cpu.reg_write(UC_X86_REG_DS, 0x1000)
        machine.cpu.reg_write(UC_X86_REG_ES, 0x4000)
        machine.cpu.reg_write(UC_X86_REG_SI, 0x0100)
        machine.cpu.reg_write(UC_X86_REG_DI, 0x0200)
        machine.cpu.reg_write(UC_X86_REG_CX, 7)
        machine.cpu.mem_write(0x10100, b"\x00\x02\x00\x00")
        machine.cpu.mem_write(0x40200, b"\x00\x00\x00\x00")
        machine.cpu.reg_write(UC_X86_REG_EFLAGS, 0x0002)
        machine._add4s_hook(machine.cpu, address, 1, None)
        self.assertEqual(b"\x00\x02\x00\x00",
                         bytes(machine.cpu.mem_read(0x40200, 4)))
        self.assertEqual(0, machine.cpu.reg_read(UC_X86_REG_EFLAGS) & 0x0041)

        machine.cpu.mem_write(0x10100, b"\x01\x00\x00\x00")
        machine.cpu.mem_write(0x40200, b"\x99\x99\x99\x99")
        machine._add4s_hook(machine.cpu, address, 1, None)
        self.assertEqual(b"\x00\x00\x00\x00",
                         bytes(machine.cpu.mem_read(0x40200, 4)))
        self.assertEqual(0x0041,
                         machine.cpu.reg_read(UC_X86_REG_EFLAGS) & 0x0041)


class RuntimeInputTests(unittest.TestCase):
    def test_any_key_left_click_or_joystick_button_wakes_demo(self) -> None:
        self.assertTrue(_wakes_from_demo(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_LEFT)))
        self.assertTrue(_wakes_from_demo(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0))))
        self.assertTrue(_wakes_from_demo(pygame.event.Event(
            pygame.JOYBUTTONDOWN, instance_id=1, button=3)))
        self.assertFalse(_wakes_from_demo(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0))))

    def test_fire_and_system_start_are_independent(self) -> None:
        self.assertEqual((True, False, True, False),
                         _keydown_actions(pygame.K_SPACE))
        self.assertEqual((True, True, False, False),
                         _keydown_actions(pygame.K_RETURN))

    def test_release_and_focus_loss_cannot_leave_fire_held(self) -> None:
        keys = defaultdict(bool)
        held = RuntimeInput()
        held.process(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        self.assertEqual(0x10, _input_mask(keys, held))
        held.process(pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE))
        self.assertEqual(0, _input_mask(keys, held))

        held.process(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0)))
        self.assertEqual(0x10, _input_mask(keys, held))
        held.process(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(0, _input_mask(keys, held))
        held.process(pygame.event.Event(pygame.WINDOWFOCUSGAINED))
        self.assertEqual(0x10, _input_mask(keys, held, fire_pulse=True))


if __name__ == "__main__":
    unittest.main()
