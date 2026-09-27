"""Проверки строгого разделения TSFM и General Sound."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

from rtype_port.audio import (
    GS_CAPTURE_DIR, MUSIC_PREFILL_FRAMES, MUSIC_STREAMS, STAGE_MUSIC_COMMANDS,
    GeneralSound, TargetAudio, TurboSoundFm, _BassMixer,
)
from rtype_port.tsfm import decode_stream


class AudioRoutingTest(unittest.TestCase):
    def test_music_never_reaches_general_sound(self) -> None:
        audio = TargetAudio(enabled=False)
        for command in (0x00, 0x1A, 0x1B, 0x1C, 0x1F,
                        0x20, 0x21, 0x22, 0x25, 0x28, 0x2B):
            audio.command(command)
        self.assertEqual([], audio.gs.command_log)
        self.assertEqual(audio.command_log, audio.tsfm.command_log)

    def test_all_effects_reach_only_general_sound(self) -> None:
        audio = TargetAudio(enabled=False)
        commands = (0x30, 0x31, 0x32, 0x33, 0x35, 0x36, 0x37,
                    0x3A, 0x50, 0x51, 0x52, 0x53, 0x55)
        for command in commands:
            audio.command(command)
        self.assertEqual(list(commands), audio.gs.command_log)
        self.assertEqual([], audio.tsfm.command_log)

    def test_old_names_are_only_compatibility_aliases(self) -> None:
        audio = TargetAudio(enabled=False)
        for name in ("shot", "wave", "charge", "charge_stop",
                     "force_detach", "force_attach"):
            audio.command(name)
        self.assertEqual([0x30, 0x31, 0x32, 0x33, 0x36, 0x37],
                         audio.gs.command_log)

    def test_general_sound_rejects_music_commands(self) -> None:
        sound = GeneralSound(None)
        with self.assertRaises(ValueError):
            sound.command(0x2F)

    def test_every_runtime_effect_has_a_verified_capture(self) -> None:
        sound = GeneralSound(None)
        for command in (0x30, 0x31, 0x32, 0x35, 0x36, 0x37,
                        0x3A, 0x50, 0x51, 0x52, 0x53, 0x55):
            self.assertIsNotNone(sound._load(command), f"GS ${command:02X}")

    def test_every_rom_effect_has_an_original(self) -> None:
        # Каталог оригиналов эффектов (Source/Tools/rtype_sfx_originals.py): звучащие части записей MAME по
        # каждой команде $30…$FF, которую шлёт ROM (rtype_gs.ROM_COMMANDS), — у каждой свой WAV.
        import json
        import wave

        sys.path.insert(0, str(ROOT / "Source" / "Tools"))
        from rtype_gs import ROM_COMMANDS

        catalog = json.loads(
            (GS_CAPTURE_DIR / "rtype_sfx.json").read_text(encoding="utf-8"))
        sounding = {int(command, 16): info for command, info in catalog["sounding"].items()}
        # $33 и $5B — команды типа $10 без своего звука: останавливают голос $32 и $5A (rtype_gs.stop_targets).
        self.assertEqual(set(ROM_COMMANDS) - {0x33, 0x5B}, set(sounding))
        for command, info in sounding.items():
            path = GS_CAPTURE_DIR / info["file"]
            self.assertTrue(path.is_file(), f"GS ${command:02X}")
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(info["samples"], wav.getnframes(), f"GS ${command:02X}")

    def test_death_effect_stops_the_continuous_charge_voice(self) -> None:
        class Mixer:
            def __init__(self) -> None:
                self.stopped = 0

            def stop_charge(self) -> None:
                self.stopped += 1

            def play_gs(self, _command: int, _pcm: bytes, _rate: int,
                        _channels: int, *, loop: bool = False) -> None:
                pass

        mixer = Mixer()
        sound = GeneralSound(mixer)
        sound.command(0x35)
        self.assertEqual(1, mixer.stopped)

    def test_all_detected_melodies_are_complete_tsfm_streams(self) -> None:
        self.assertEqual({0x01, 0x04, 0x07, 0x0A, 0x0D, 0x10, 0x13, 0x16,
                          0x19, 0x1C,
                          0x1F, 0x22, 0x25, 0x28, 0x2B},
                         set(MUSIC_STREAMS))
        # Потоки из оракула (rtype_music.py) — вступление и один проход петли: самая короткая петля $16 —
        # 262 кадра и 252 записи; прежний порог 300 записей был рассчитан на записи MAME длиной 218 с.
        for command, path in MUSIC_STREAMS.items():
            events, frames = decode_stream(path.read_bytes())
            self.assertGreater(frames, 250, f"TSFM ${command:02X}")
            self.assertGreater(sum(map(len, events.values())), 200,
                               f"TSFM ${command:02X}")
            self.assertIn(0, events, f"TSFM ${command:02X}: записи с первого шага")

    def test_stage_music_mapping_follows_rom_f3d8_table(self) -> None:
        self.assertEqual(
            {1: 0x01, 2: 0x04, 3: 0x07, 4: 0x0A,
             5: 0x10, 6: 0x0D, 7: 0x13, 8: 0x16},
            STAGE_MUSIC_COMMANDS)

    def test_tsfm_registers_leave_through_multisound_ports(self) -> None:
        class Mixer:
            def __init__(self) -> None:
                self.blocks = 0

            def reset_music(self) -> None:
                pass

            def push_music(self, _samples: object,
                           _gain: float = 1.0) -> None:
                self.blocks += 1

        writes: list[tuple[int, int]] = []
        mixer = Mixer()
        music = TurboSoundFm(
            mixer, enabled=True,
            port_writer=lambda port, value: writes.append((port, value)))
        music.command(0x1F)
        music.step_frame()
        self.assertTrue(writes)
        self.assertEqual(MUSIC_PREFILL_FRAMES, mixer.blocks)
        self.assertEqual(0, len(writes) % 3)
        for index in range(0, len(writes), 3):
            select, register, value = writes[index:index + 3]
            self.assertIn(select, ((0xFFFD, 0xF8), (0xFFFD, 0xF9)))
            self.assertEqual(0xFFFD, register[0])
            self.assertEqual(0xBFFD, value[0])

    def test_start_replace_fade_and_noop_follow_sound_z80_records(self) -> None:
        class Mixer:
            def reset_music(self) -> None:
                pass

            def push_music(self, _samples: object,
                           _gain: float = 1.0) -> None:
                pass

        music = TurboSoundFm(Mixer(), enabled=True)
        music.command(0x01)
        self.assertEqual((0x01, 0x01),
                         (music.current_command, music.owner_command))
        music.command(0x00)
        self.assertEqual(0x01, music.owner_command)
        music.command(0x03)
        self.assertEqual(0x70, music.fade_remaining)
        music.command(0x02)
        self.assertEqual(0x02, music.current_command)
        self.assertIsNone(music.owner_command)
        self.assertFalse(music.emulator.loop)

    def test_music_waits_for_stable_prefill_before_playback(self) -> None:
        class Bass:
            def __init__(self) -> None:
                self.played = 0

            def BASS_StreamPutData(self, *_args: object) -> int:
                return 0

            def BASS_ChannelPlay(self, *_args: object) -> int:
                self.played += 1
                return 1

            def BASS_ErrorGetCode(self) -> int:
                return 0

        mixer = object.__new__(_BassMixer)
        mixer._bass = Bass()
        mixer.music_stream = 1
        mixer._music_started = False
        mixer._music_prefill_frames = 0
        import numpy as np
        samples = np.zeros(32, dtype=np.int16)
        for _ in range(MUSIC_PREFILL_FRAMES - 1):
            mixer.push_music(samples)
        self.assertEqual(0, mixer._bass.played)
        mixer.push_music(samples)
        self.assertEqual(1, mixer._bass.played)

    def test_session_reset_clears_tsfm_owner(self) -> None:
        audio = TargetAudio(enabled=False)
        audio.command(0x01)
        self.assertEqual(0x01, audio.tsfm.owner_command)
        audio.reset_session()
        self.assertIsNone(audio.tsfm.owner_command)


if __name__ == "__main__":
    unittest.main()
