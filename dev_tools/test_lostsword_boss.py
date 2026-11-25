"""Offline regressions for the raid card and battle carousel."""

import unittest
from unittest.mock import Mock

import numpy as np

from module.config.server import set_server

set_server('lostsword')

from module.exception import GameStuckError
from module.lostsword.assets import BOSS_CARD
from module.lostsword.boss import LostswordBoss
from module.lostsword.page import page_battle, page_boss


class LostswordBossTest(unittest.TestCase):
    def setUp(self):
        self.task = LostswordBoss.__new__(LostswordBoss)
        self.task.device = Mock()
        self.task.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.addCleanup(BOSS_CARD.clear_offset)

    def prepare_battle_page(self):
        self.task.ui_get_current_page = Mock(return_value=page_battle)
        self.task.battle_goto_normal = Mock(return_value=True)
        self.task.ui_page_appear = lambda page: page == (
            page_boss if self.task.device.adb_shell.called else page_battle)
        self.task.loop = lambda **kwargs: iter(range(2))

    def test_taps_the_raid_card_at_its_shifted_position(self):
        self.prepare_battle_page()
        BOSS_CARD.ensure_template()
        self.task.device.image[548:634, 472:587] = BOSS_CARD.image

        self.task.boss_goto_page()

        self.task.device.adb_shell.assert_called_once_with(['input', 'tap', '529', '591'])
        self.assertEqual(self.task.ui_current, page_boss)

    def test_missing_card_times_out_without_a_tap(self):
        self.prepare_battle_page()

        with self.assertRaises(GameStuckError):
            self.task.boss_goto_page()

        self.task.device.adb_shell.assert_not_called()

    def test_scroll_stops_if_carousel_is_still_moving(self):
        self.task.wait_until_still = Mock(return_value=False)

        with self.assertRaises(GameStuckError):
            self.task.battle_scroll(forward=False)

        self.task.device.swipe_adb.assert_called_once_with((300, 400), (1000, 400), duration=0.625)
        self.task.wait_until_still.assert_called_once_with(
            (0, 140, 1280, 660), timeout=3, skip_first_screenshot=False)


if __name__ == '__main__':
    unittest.main()
