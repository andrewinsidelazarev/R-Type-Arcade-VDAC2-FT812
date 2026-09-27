"""Проверки пассивного аудита кэша: физические теги, CPU-записи и невидимые для кэша DMA."""
import unittest

from p2c_z80_check import TSConfModel
from tsconf_cache_probe import CacheProbe


class CacheProbeTests(unittest.TestCase):
    def setUp(self):
        self.model = TSConfModel({page: bytes([page]) * 0x4000 for page in range(1, 6)})
        self.model.map_all([1, 2, 3, 4])
        self.probe = CacheProbe(self.model)

    def tearDown(self):
        self.probe.close()

    def test_window3_enable_and_word_fill(self):
        self.assertEqual(self.probe.read(0xC010), 4)
        self.assertEqual(self.probe.read(0xC011), 4)
        self.assertEqual(self.probe.states[7]['misses'], 2)
        self.assertEqual(self.probe.states[15]['misses'], 1)

    def test_bank_change_misses_but_alias_hits(self):
        self.probe.read(0xC010)
        self.model.map(3, 5)
        self.assertEqual(self.probe.read(0xC010), 5)
        self.assertEqual(self.probe.states[15]['misses'], 2)
        self.model.map(2, 5)
        self.assertEqual(self.probe.read(0x8010), 5)
        self.assertEqual(self.probe.states[15]['misses'], 2)

    def test_cpu_write_invalidates_both_bytes(self):
        self.probe.read(0xC010)
        self.probe.write(0xC011, 9)
        self.assertEqual(self.probe.read(0xC011), 9)
        self.assertEqual(self.probe.states[15]['misses'], 2)
        self.assertEqual(self.probe.states[15]['stale'], 0)

    def test_dma_reports_stale_without_changing_data(self):
        self.probe.read(0xC010)
        self.model.write_block(4 * 0x4000 + 0x10, bytes([9, 10]))
        self.assertEqual(self.probe.read(0xC010), 9)
        self.assertEqual(self.probe.states[7]['stale'], 0)
        self.assertEqual(self.probe.states[15]['stale'], 1)
        self.assertEqual(self.model.memory[0xC010], 9)

    def test_executable_callback_preserves_cpu_writes(self):
        # LD A,9; LD (#8011),A; HALT — запись действительно проходит через callback ядра Z80.
        self.model.memory[0:6] = bytes([0x3E, 9, 0x32, 0x11, 0x80, 0x76])
        self.model.cpu.pc = 0
        self.model.cpu.ticks_to_stop = 40
        self.model.cpu.run()
        self.assertEqual(self.model.memory[0x8011], 9)
        self.assertGreater(self.probe.states[15]['reads'], 0)


if __name__ == '__main__':
    unittest.main()
